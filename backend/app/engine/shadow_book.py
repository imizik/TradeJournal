"""Shadow book v1: the copilot's own paper book, decided by itself from Radar events (docs/radar.md § Shadow book).

Off unless ``SHADOW_BOOK_ENABLED=true`` and Radar's ``RADAR_STORE`` is an absolute path; it runs in the API process.
During the regular session each new Radar event of today, read only from the Radar store, gets at most one decision:
one unattended copilot turn on the owner's Claude plan (``app.ai.shadow_turn``, never an API key), at most
``SHADOW_BOOK_MAX_TURNS`` a session (default 12). An event the book reaches more than ``FRESH_SECONDS`` after Radar
first saw it, one in the session's last half hour, and one past the cap is recorded ``not_decided`` with no turn.
Between sessions it is quiet.

The answer is SKIP or one plan in the copilot's ``trade_plan`` shape plus a target and a New York clock time stop.
One unit per position: one option contract for calls or puts, or whole shares worth ``STOCK_UNIT_USD`` for stock.
Pricing is the setup scanner's: the entry is the first quote whose bid and ask were both updated after the decision
(the ask to buy, the bid to sell short), within two minutes or the position is ``unresolved``. The invalidation and
the target are touches on completed 1-minute bars of the underlying (a bar touching both is the invalidation); the
time stop and the session's last regular minute are clock exits. The exit is the first fresh quote after the
condition (the bid to sell, the ask to cover). Every economic fact is an append-only ``ShadowBookEvent``; a position
is their fold, so a restart rebuilds the book. A position still open once its session has ended is ``unresolved``.

Nothing here touches fills, trades, accounts, alerts, notifications or the strategy factory.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from app.engine import scanner_rules as rules
from app.engine import tradier
from app.engine.chart_math import ET, normalize_bars
from app.engine.level_alerts import LATENESS
from app.engine.occ import occ_symbol
from app.engine.paper import regular_session
from app.engine.setup_scanner import _fresh
from app.models import ShadowBookDecision, ShadowBookEvent

log = logging.getLogger(__name__)

STOCK_UNIT_USD = 1000.0  # a stock position is the whole shares this buys (or sells short) at the entry quote, at least one
MULTIPLIER = 100  # one standard option contract
FRESH_SECONDS = 10 * 60  # an event first seen longer ago than this when the book reaches it is not decided
LAST_DECISION_SECONDS = 30 * 60  # no new decision in the session's last half hour
MAX_DELAY_SECONDS = rules.MAX_DELAY_SECONDS  # a quote or exit condition later than this is not acted on
PASS_SECONDS = 15
OPEN = ("pending_entry", "open", "exiting")
TURNS = ("deciding", "plan", "skip", "error")  # decisions that used a turn
EXIT_REASONS = {"stop": "invalidation", "target": "target", "time_stop": "time_stop", "flat": "last_minute"}


def enabled() -> bool:
    return os.environ.get("SHADOW_BOOK_ENABLED", "false").lower() in ("1", "true", "yes")


def max_turns() -> int:
    try:
        return max(0, int(os.environ.get("SHADOW_BOOK_MAX_TURNS", "12")))
    except ValueError:
        return 12


def _utc(stamp: float) -> datetime:
    return datetime.fromtimestamp(stamp, UTC).replace(tzinfo=None)


def _epoch(moment: datetime) -> float:
    return moment.replace(tzinfo=UTC).timestamp()


def _iso(moment: datetime | None) -> str | None:
    return None if moment is None else moment.replace(tzinfo=UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


# ------------------------------------------------------------------ the rules (pure)


class PlanError(ValueError):
    pass


def check_plan(plan: dict, symbols: list[str], decided: float, close_at: int) -> dict:
    """The copilot's plan, normalized: its ``trade_plan`` fields (the same checks ``propose_plan`` makes), then a target
    beyond the entry, a time stop after the decision (capped at the session's last regular minute) and, for options,
    the contract as an OCC symbol. Raises PlanError."""
    from app.ai import copilot_tools
    if not isinstance(plan, dict):
        raise PlanError("no plan")
    args = {k: plan[k] for k in ("symbol", "direction", "instrument", "thesis", "entry_trigger", "invalidation")
            if plan.get(k) is not None}
    try:
        out = copilot_tools.validate("propose_plan", {"kind": "trade_plan", **args})
    except copilot_tools.ToolInputError as exc:
        raise PlanError(str(exc)) from None
    if out["symbol"] not in symbols:
        raise PlanError(f"{out['symbol']} is not one of this event's symbols ({', '.join(symbols)})")
    entry, short = out["entry_trigger"]["price"], out["direction"] == "short"
    target = plan.get("target")
    if isinstance(target, bool) or not isinstance(target, (int, float)) or not 0 < target < 1_000_000:
        raise PlanError("target must be a positive price")
    if (short and not target < entry) or (not short and not target > entry):
        raise PlanError(f"a {out['direction']} plan's target must be {'below' if short else 'above'} its entry")
    day = datetime.fromtimestamp(decided, ET).date()
    try:
        hour, minute = (int(part) for part in str(plan.get("time_stop", "")).strip().split(":"))
        stop_at = int(datetime(day.year, day.month, day.day, hour, minute, tzinfo=ET).timestamp())
    except (TypeError, ValueError):
        raise PlanError("time_stop must be a New York time like 15:30") from None
    stop_at = min(stop_at, close_at - 60)
    if stop_at <= decided:
        raise PlanError("time_stop must be later than now and before the session's last minute")
    out.update(target=round(float(target), 4), time_stop=datetime.fromtimestamp(stop_at, ET).strftime("%H:%M"),
               time_stop_at=stop_at, quote_symbol=out["symbol"], unit=f"${STOCK_UNIT_USD:,.0f} of shares")
    if out["instrument"] != "stock":
        try:
            expiration = date.fromisoformat(str(plan.get("contract_expiration")))
            strike = float(plan.get("contract_strike"))
        except (TypeError, ValueError):
            raise PlanError("calls and puts need contract_expiration (YYYY-MM-DD) and contract_strike") from None
        if expiration < day or not 0 < strike < 1_000_000:
            raise PlanError("the contract must expire today or later at a positive strike")
        kind = "call" if out["instrument"] == "calls" else "put"
        out.update(contract=f"{expiration.isoformat()} {strike:g} {kind}", quote_symbol=occ_symbol(out["symbol"], expiration, kind, strike),
                   unit="1 contract")
    return out


def fold(events: list[ShadowBookEvent]) -> dict:
    """A position's state: one entry per event type."""
    return {e.event_type: {**json.loads(e.data_json), "at": _epoch(e.effective_at)} for e in events}


def position_status(decision: ShadowBookDecision, state: dict) -> str:
    if decision.status != "plan":
        return decision.status
    for kind in ("unresolved", "exit", "exit_intent", "entry"):
        if kind in state:
            return {"exit_intent": "exiting", "entry": "open"}.get(kind, kind)
    return "pending_entry"


def _sells_first(plan: dict) -> bool:
    return plan["instrument"] == "stock" and plan["direction"] == "short"


def entry_fill(plan: dict, quote, decided: float) -> dict | None:
    """The entry from a quote both of whose sides moved after the decision, or None (wait for the next one)."""
    if quote is None or not _fresh(quote, decided) or not quote.bid or not quote.ask or quote.bid <= 0 or quote.ask < quote.bid:
        return None
    fill = {"bid": quote.bid, "ask": quote.ask, "bid_time": quote.bid_date, "ask_time": quote.ask_date,
            "price": quote.bid if _sells_first(plan) else quote.ask}
    if plan["instrument"] == "stock":
        fill["shares"] = max(1, int(STOCK_UNIT_USD // fill["price"]))
    return fill


def exit_fill(plan: dict, entry: dict, quote, decided: float, reason: str) -> dict | None:
    """The exit from a fresh quote after the exit condition, with its result, or None (wait for the next one)."""
    if quote is None or not _fresh(quote, decided) or quote.bid is None or not quote.ask or quote.bid < 0:
        return None
    exit_ = {"bid": quote.bid, "ask": quote.ask, "bid_time": quote.bid_date, "ask_time": quote.ask_date, "reason": reason,
             "price": quote.ask if _sells_first(plan) else quote.bid}
    return {**exit_, **result(plan, entry, exit_)}


def result(plan: dict, entry: dict, exit_: dict) -> dict:
    """Dollars for the one unit: options per contract as the scanner scores them (ask in, bid out, commissions); stock
    on its shares, no commission."""
    if plan["instrument"] == "stock":
        sign = -1 if plan["direction"] == "short" else 1
        pnl = sign * (exit_["price"] - entry["price"]) * entry["shares"]
        return {"pnl": round(pnl, 2), "return_pct": round(100 * pnl / (entry["price"] * entry["shares"]), 2)}
    scored = rules.result(entry, exit_, MULTIPLIER)
    ratio = scored["return_on_premium"]
    return {"pnl": scored["pnl"], "return_pct": None if ratio is None else round(100 * ratio, 2),
            "pnl_2x_spread": scored["pnl_2x_spread"]}


def exit_condition(plan: dict, minutes: list[dict], entry_at: float, close_at: int, now: float) -> dict | None:
    """The first exit after entry (the scanner's rule): invalidation or target on the underlying, else the clock."""
    found = rules.exit_condition(plan["direction"], plan["invalidation"]["price"], plan["target"], minutes, entry_at,
                                 plan["time_stop_at"], close_at - 60, now, LATENESS)
    return None if found is None else {**found, "reason": EXIT_REASONS[found["reason"]]}


def event_brief(event: dict) -> dict:
    """What the turn and the record keep of a Radar event."""
    return {k: event.get(k) for k in ("event_id", "kind", "direction", "symbols", "benchmark", "group", "first_seen_at",
                                      "summary", "measures")}


# ------------------------------------------------------------------ the worker


def _quote(symbol: str):
    return tradier.get_quotes_once([symbol]).get(symbol)


class ShadowBook:
    """Claims Radar events, runs one decision at a time and manages the paper positions. ``decide`` is
    ``shadow_turn.decide`` (injectable, so tests never start Claude Code)."""

    def __init__(self, engine, store_path: str, feed, calendar, *, clock=time.time, quote=_quote, decide=None,
                 turns: int | None = None):
        self.engine, self.store_path, self.feed, self.calendar, self.clock = engine, store_path, feed, calendar, clock
        self.quote, self._decide = quote, decide
        self.turns = max_turns() if turns is None else turns
        self._deciding: asyncio.Task | None = None
        self.last_error: str | None = None

    def session(self, now: float):
        today = datetime.fromtimestamp(now, ET).date()
        return regular_session(today, self.calendar.hours(today))

    # -------------------------------------------------------------- decisions

    def recover(self) -> int:
        """A decision cut off by a restart is recorded as an error and never retried: one turn per event, at most."""
        with Session(self.engine) as db:
            rows = db.exec(select(ShadowBookDecision).where(ShadowBookDecision.status == "deciding")).all()
            for row in rows:
                row.status, row.reason = "error", "Interrupted by a restart; never retried."
                db.add(row)
            db.commit()
            return len(rows)

    def claim_next(self) -> ShadowBookDecision | None:
        """The next of today's undecided Radar events, claimed for a turn; earlier ones that cannot be decided are
        recorded ``not_decided`` on the way. None outside the regular session or with nothing new."""
        from app.engine.radar_store import RadarStore
        now = self.clock()
        session = self.session(now)
        if session is None or not session.open_at <= now < session.close_at:
            return None
        today = datetime.fromtimestamp(now, ET).date()
        events = sorted(RadarStore(self.store_path, read_only=True).events(today.isoformat()), key=lambda e: e["first_seen_at"])
        with Session(self.engine) as db:
            rows = db.exec(select(ShadowBookDecision).where(ShadowBookDecision.session_date == today)).all()
            known = {r.radar_event_id for r in rows}
            used = sum(r.status in TURNS for r in rows)
            for event in events:
                if event["event_id"] in known:
                    continue
                age = now - datetime.fromisoformat(event["first_seen_at"].replace("Z", "+00:00")).timestamp()
                reason = None
                if age > FRESH_SECONDS:
                    reason = f"Radar saw it {age / 60:.0f} minutes before the shadow book reached it; too late to decide."
                elif now >= session.close_at - LAST_DECISION_SECONDS:
                    reason = "In the session's last half hour: no new positions."
                elif used >= self.turns:
                    reason = f"This session's {self.turns} turns were used."
                row = ShadowBookDecision(radar_event_id=event["event_id"], session_date=today,
                                         symbol=(event.get("symbols") or [None])[0], event_json=json.dumps(event_brief(event)),
                                         status="not_decided" if reason else "deciding", reason=reason, claimed_at=_utc(now))
                db.add(row)
                try:
                    db.commit()
                except IntegrityError:
                    db.rollback()  # another process claimed it first
                    continue
                if reason is None:
                    db.refresh(row)
                    return row
        return None

    def book(self, today: date) -> dict:
        """The shadow book's own state for the prompt: open positions, recent results and today's turns."""
        with Session(self.engine) as db:
            rows = db.exec(select(ShadowBookDecision).where(ShadowBookDecision.status == "plan")
                           .order_by(col(ShadowBookDecision.decided_at).desc()).limit(40)).all()
            states = [(r, fold(self._events(db, r.id))) for r in rows]
            used = len(db.exec(select(ShadowBookDecision.id).where(ShadowBookDecision.session_date == today)
                               .where(col(ShadowBookDecision.status).in_(TURNS))).all())
        open_, recent = [], []
        for row, state in states:
            plan, status = json.loads(row.plan_json), position_status(row, state)
            line = {k: plan.get(k) for k in ("symbol", "direction", "instrument", "contract", "target", "time_stop", "thesis")}
            line.update(session=row.session_date.isoformat(), invalidation=plan["invalidation"]["price"], status=status)
            if status in OPEN:
                open_.append({**line, "entry": state.get("entry", {}).get("price")})
            elif "exit" in state and len(recent) < 10:
                recent.append({**line, "pnl": state["exit"]["pnl"], "exit_reason": state["exit"]["reason"]})
        return {"open_positions": open_, "recent_results": recent, "turns_today": used, "turn_cap": self.turns,
                "unit": f"one option contract, or ${STOCK_UNIT_USD:,.0f} of shares"}

    async def decide_one(self, row: ShadowBookDecision) -> None:
        event = json.loads(row.event_json)
        try:
            book = await asyncio.to_thread(self.book, row.session_date)
            decide = self._decide
            if decide is None:
                from app.ai.shadow_turn import decide
            answer = await decide(event, book, datetime.fromtimestamp(self.clock(), ET))
        except Exception as exc:  # noqa: BLE001 - a failed turn is recorded on its decision, never retried
            log.exception("Shadow book turn failed")
            answer = {"error": {"code": "internal", "message": type(exc).__name__}}
        await asyncio.to_thread(self.record_answer, row.id, answer)

    def record_answer(self, decision_id: uuid.UUID, answer: dict) -> None:
        decided = self.clock()
        plan = None
        with Session(self.engine) as db:
            row = db.get(ShadowBookDecision, decision_id)
            if row is None or row.status != "deciding":
                return
            row.model, row.decided_at = answer.get("model"), _utc(decided)
            data, error = answer.get("answer"), answer.get("error")
            if error or not isinstance(data, dict) or data.get("decision") not in ("skip", "plan"):
                row.status = "error"
                row.reason = (error or {}).get("message") or "The turn ended without a decision."
            elif data["decision"] == "skip":
                row.status, row.reason = "skip", str(data.get("reason") or "")[:300] or "No reason given."
            else:
                session = self.session(decided)
                try:
                    if session is None:
                        raise PlanError("the session is closed")
                    plan = check_plan(data.get("plan"), json.loads(row.event_json).get("symbols") or [], decided, session.close_at)
                except PlanError as exc:
                    row.status, row.reason = "error", f"The plan was refused: {exc}"[:300]
                else:
                    row.status, row.symbol, row.plan_json = "plan", plan["symbol"], json.dumps(plan, sort_keys=True)
                    row.reason = str(data.get("reason") or "")[:300] or None
            db.add(row)
            db.commit()
        if plan is not None:
            self._enter(decision_id, plan, decided)

    # -------------------------------------------------------------- positions

    def manage(self) -> None:
        now = self.clock()
        today = datetime.fromtimestamp(now, ET).date()
        session = self.session(now)
        with Session(self.engine) as db:
            rows = db.exec(select(ShadowBookDecision).where(ShadowBookDecision.status == "plan")
                           .where(ShadowBookDecision.session_date >= today - timedelta(days=7))).all()
            active = [(r, fold(self._events(db, r.id))) for r in rows]
        for row, state in active:
            status = position_status(row, state)
            if status not in OPEN:
                continue
            plan = json.loads(row.plan_json)
            try:
                if row.session_date != today or session is None:
                    self._store(row.id, "unresolved", self.clock(), {"reason": "session ended before the position finished"})
                elif status == "pending_entry":
                    self._enter(row.id, plan, _epoch(row.decided_at))
                elif status == "open":
                    self._watch(row, plan, state, session)
                else:
                    self._exit(row.id, plan, state)
            except Exception:  # noqa: BLE001 - one position's failure never stops the others
                log.exception("Shadow book position %s failed this pass", row.id)

    def _enter(self, decision_id: uuid.UUID, plan: dict, decided: float) -> None:
        quote = self._read_quote(plan["quote_symbol"])
        at = self.clock()
        fill = entry_fill(plan, quote, decided)
        if fill is not None and at - decided <= MAX_DELAY_SECONDS:
            self._store(decision_id, "entry", at, fill)
        elif at - decided > MAX_DELAY_SECONDS:
            self._store(decision_id, "unresolved", at, {"reason": "no entry quote within two minutes"})

    def _watch(self, row: ShadowBookDecision, plan: dict, state: dict, session) -> None:
        minutes = self._minutes(plan["symbol"], row.session_date)
        now = self.clock()
        found = exit_condition(plan, minutes, state["entry"]["at"], session.close_at, now)
        if found is None:
            return
        if now - found["condition_at"] > MAX_DELAY_SECONDS + LATENESS:
            return self._store(row.id, "unresolved", now, {**found, "condition": found["reason"],
                                                           "reason": "monitoring gap: exit condition noticed late"})
        self._store(row.id, "exit_intent", now, found)
        with Session(self.engine) as db:
            state = fold(self._events(db, row.id))
        if "exit_intent" in state and "exit" not in state:
            self._exit(row.id, plan, state)

    def _exit(self, decision_id: uuid.UUID, plan: dict, state: dict) -> None:
        decided = state["exit_intent"]["at"]
        quote = self._read_quote(plan["quote_symbol"])
        at = self.clock()
        fill = exit_fill(plan, state["entry"], quote, decided, state["exit_intent"]["reason"])
        if fill is not None and at - decided <= MAX_DELAY_SECONDS:
            self._store(decision_id, "exit", at, fill)
        elif at - decided > MAX_DELAY_SECONDS:
            self._store(decision_id, "unresolved", at, {"reason": "no exit quote within two minutes"})

    def _minutes(self, symbol: str, day: date) -> list[dict]:
        # The setup scanner's request, so the chart feed's cache is shared.
        data, _, issue = self.feed.read("/v1/markets/timesales", {
            "symbol": symbol, "interval": "1min", "session_filter": "all",
            "start": day.strftime("%Y-%m-%d 04:00"), "end": day.strftime("%Y-%m-%d 20:00"),
        }, 15)
        if issue:
            raise ValueError(f"minute bars not current: {issue}")
        series = (data or {}).get("series") or {}
        rows = series.get("data") if isinstance(series, dict) else None
        return normalize_bars(rows if isinstance(rows, list) else [rows] if isinstance(rows, dict) else [])

    def _read_quote(self, symbol: str):
        try:
            return self.quote(symbol)
        except tradier.TradierError as exc:
            log.warning("Shadow book quote for %s unavailable: %s", symbol, exc)
            return None

    @staticmethod
    def _events(db: Session, decision_id: uuid.UUID) -> list[ShadowBookEvent]:
        return list(db.exec(select(ShadowBookEvent).where(ShadowBookEvent.decision_id == decision_id)
                            .order_by(ShadowBookEvent.recorded_at)).all())

    def _store(self, decision_id: uuid.UUID, kind: str, at: float, data: dict) -> None:
        with Session(self.engine) as db:
            db.add(ShadowBookEvent(decision_id=decision_id, event_type=kind, effective_at=_utc(at),
                                   recorded_at=_utc(self.clock()), data_json=json.dumps(data, sort_keys=True)))
            try:
                db.commit()
            except IntegrityError:
                db.rollback()  # already stored by another pass

    # -------------------------------------------------------------- the loop

    async def run_once(self) -> None:
        """Manage the positions, then start the next decision unless one is still running."""
        await asyncio.to_thread(self.manage)
        if self._deciding is None or self._deciding.done():
            row = await asyncio.to_thread(self.claim_next)
            if row is not None:
                self._deciding = asyncio.create_task(self.decide_one(row))

    async def loop(self) -> None:
        await asyncio.to_thread(self.recover)
        try:
            while True:
                try:
                    await self.run_once()
                    self.last_error = None
                except asyncio.CancelledError:
                    raise
                except Exception:
                    self.last_error = "Shadow book pass failed"
                    log.exception("Shadow book pass failed")
                await asyncio.sleep(PASS_SECONDS)
        finally:
            if self._deciding is not None and not self._deciding.done():
                self._deciding.cancel()  # left ``deciding``; the next start records it as interrupted


def book_from_env(engine) -> ShadowBook | None:
    if not enabled():
        return None
    store = os.environ.get("RADAR_STORE", "").strip()
    if not store or not os.path.isabs(store):
        log.error("SHADOW_BOOK_ENABLED needs Radar's absolute RADAR_STORE; the shadow book stays off")
        return None
    from app.engine.chart_calendar import chart_calendar
    from app.engine.chart_feed import chart_feed
    return ShadowBook(engine, store, chart_feed, chart_calendar)


# ------------------------------------------------------------------ reading


def decision_view(row: ShadowBookDecision, state: dict) -> dict:
    plan = json.loads(row.plan_json) if row.plan_json else None
    entry, exit_ = state.get("entry"), state.get("exit")

    def moment(value: dict | None) -> str | None:
        return None if value is None else _iso(_utc(value["at"]))
    return {
        "id": str(row.id), "radar_event_id": row.radar_event_id, "session_date": row.session_date.isoformat(),
        "event": json.loads(row.event_json), "decision": row.status, "status": position_status(row, state),
        "reason": row.reason, "plan": plan, "model": row.model, "decided_at": _iso(row.decided_at),
        "entry": None if entry is None else {"price": entry["price"], "at": moment(entry), "shares": entry.get("shares")},
        "exit": None if exit_ is None else {"price": exit_["price"], "at": moment(exit_), "reason": exit_["reason"]},
        "result": None if exit_ is None else {k: exit_.get(k) for k in ("pnl", "return_pct", "pnl_2x_spread")},
        "unresolved": (state.get("unresolved") or {}).get("reason"),
    }


def week_view(db: Session, week_start: date | None = None, today: date | None = None) -> dict:
    """The week's decisions, newest first, and one summary line: the shadow book's P&L and count beside the owner's own
    week from the week review. Side by side only; different sizes and choices, so neither is called better."""
    today = today or datetime.now(ET).date()
    day = week_start or today
    monday = day - timedelta(days=day.weekday())
    friday = monday + timedelta(days=4)
    rows = db.exec(select(ShadowBookDecision).where(ShadowBookDecision.session_date >= monday)
                   .where(ShadowBookDecision.session_date <= friday)
                   .order_by(col(ShadowBookDecision.claimed_at).desc())).all()
    decisions = [decision_view(r, fold(ShadowBook._events(db, r.id))) for r in rows]
    closed = [d["result"]["pnl"] for d in decisions if d["result"]]
    shadow = {"decisions": len(decisions), "turns": sum(d["decision"] in TURNS for d in decisions),
              "plans": sum(d["decision"] == "plan" for d in decisions), "closed": len(closed),
              "pnl_usd": round(sum(closed), 2)}
    try:
        from app.ai import copilot_review
        review = copilot_review.week_review(monday.isoformat(), session=db)
        totals = review.get("totals") or {}
        owner = {"state": "ok", "trades": int(totals.get("trades") or 0), "pnl_usd": round(float(totals.get("pnl_usd") or 0), 2)}
    except Exception:  # noqa: BLE001 - the owner's side is context; the shadow record still shows
        log.exception("Week review unavailable for the shadow book summary")
        owner = {"state": "unavailable"}
    return {"enabled": enabled(), "max_turns": max_turns(), "week": {"start": monday.isoformat(), "end": friday.isoformat()},
            "summary": {"shadow": shadow, "owner": owner,
                        "note": "Side by side, not compared: one paper unit per shadow position against your real sizes."},
            "decisions": decisions}
