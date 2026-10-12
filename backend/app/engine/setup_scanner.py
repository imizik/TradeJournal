"""Setup scanner S1: finds setups, freezes them and paper-trades each one by rule.

Runs inside the level alert monitor's loop, beside the Practice paper watcher,
only when ``SETUP_SCANNER_ENABLED`` is true. The rules are in
``scanner_rules`` (pure); this module reads Tradier through the chart feed's
shared budgeted read, the options chain budget and the quote endpoint, and
stores what the rules decide as ``ScannerCandidate`` rows and append-only
``ScannerEvent`` rows. A trade's state is always the fold of its events, so a
restart rebuilds it from the database.

Nothing here touches fills, trades, accounts, decisions or alerts, and nothing
is sent anywhere. Every entry and exit is priced from an option quote read
after the decision; a decision that cannot be priced within two minutes, or a
condition noticed more than two minutes late, ends the trade ``unresolved``.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.engine import scanner_rules as rules
from app.engine import tradier
from app.engine.chart_feed import ChartFeedError
from app.engine.chart_math import ET, normalize_bars
from app.engine.level_alerts import LATENESS
from app.engine.options_chain import OptionsChainError
from app.engine.paper import regular_session
from app.models import ScannerCandidate, ScannerEvent

log = logging.getLogger(__name__)

SOURCE = "tradier_timesales_1min"
TERMINAL = {"exit", "unresolved", "no_contract"}


def enabled() -> bool:
    return os.environ.get("SETUP_SCANNER_ENABLED", "false").lower() in ("1", "true", "yes")


def _utc(stamp: float) -> datetime:
    return datetime.fromtimestamp(stamp, UTC).replace(tzinfo=None)


def _epoch(moment: datetime) -> float:
    return moment.replace(tzinfo=UTC).timestamp()


def fold(events: list[ScannerEvent]) -> dict:
    """The trade's state: one entry per event type, by type."""
    return {e.event_type: {**json.loads(e.data_json), "at": _epoch(e.effective_at)} for e in events}


def status_of(candidate: ScannerCandidate, state: dict) -> str:
    if candidate.contract_json is None:
        return "no_contract"
    for kind in ("unresolved", "exit", "exit_intent", "entry"):
        if kind in state:
            return {"exit_intent": "exiting", "entry": "open"}.get(kind, kind)
    return "pending_entry"


def _quote(occ: str):
    return tradier.get_quotes([occ]).get(occ)


class SetupScanner:
    def __init__(self, engine, feed, calendar, options, clock, quote=_quote):
        self.engine, self.feed, self.calendar, self.options, self.clock = engine, feed, calendar, options, clock
        self.quote = quote
        self._scanned_through = 0  # the newest 5-minute bar end already judged
        self._atr: dict[tuple[str, date], float | None] = {}

    def run(self) -> None:
        now = self.clock()
        today = datetime.fromtimestamp(now, ET).date()
        session = regular_session(today, self.calendar.hours(today))
        try:
            self.manage(now, today, session)
        finally:
            if session is not None:
                self.scan(today, session)

    # -------------------------------------------------------------- scanning

    def scan(self, today: date, session) -> None:
        now = self.clock()
        bar_end = session.open_at + (int(now - LATENESS) - session.open_at) // rules.BAR_SECONDS * rules.BAR_SECONDS
        last_end = min(int(datetime(today.year, today.month, today.day, rules.LAST_BAR_END_MINUTE // 60,
                                    rules.LAST_BAR_END_MINUTE % 60, tzinfo=ET).timestamp()), session.close_at - 3600)
        if bar_end <= self._scanned_through or bar_end - rules.BAR_SECONDS < session.open_at + rules.FIRST_BAR_AFTER or bar_end > last_end:
            return
        self._scanned_through = bar_end
        if now - bar_end > rules.MAX_DELAY_SECONDS + LATENESS:
            log.info("Setup scanner skipped the bar ending %s: noticed %.0fs late", _utc(bar_end), now - bar_end)
            return
        for symbol in rules.UNIVERSE:
            try:
                self._scan_symbol(symbol, today, session, bar_end, last_end)
            except (ChartFeedError, OptionsChainError, ValueError) as exc:
                log.warning("Setup scanner could not judge %s at %s: %s", symbol, _utc(bar_end), exc)
            except Exception:
                log.exception("Setup scanner failed on %s", symbol)

    def _scan_symbol(self, symbol: str, today: date, session, bar_end: int, last_end: int) -> None:
        atr = self._daily_atr(symbol, today)
        if atr is None:
            return
        minutes = self._minutes(symbol, today)
        complete = [m for m in minutes if m["end_time"] <= bar_end]
        if not any(m["time"] >= bar_end - rules.BAR_SECONDS for m in complete):
            raise ChartFeedError("the newest 5-minute bar has no minutes yet")
        bars = rules.five_minute_bars(complete, session.open_at, session.close_at)
        with Session(self.engine) as db:
            saved = db.exec(select(ScannerCandidate).where(ScannerCandidate.session_date == today, ScannerCandidate.symbol == symbol,
                                                           ScannerCandidate.scanner_version == rules.VERSION)).all()
            taken = {(c.setup, int(_epoch(c.bar_end))) for c in saved}
            busy = any(status_of(c, fold(self._events(db, c.id))) in ("pending_entry", "open", "exiting") for c in saved)
        signals = rules.scan(bars, atr, session.open_at, last_end, taken)
        signal = signals[-1] if signals and signals[-1]["bar_end"] == bar_end else None
        if signal is None or busy:
            return
        if any(_epoch(c.bar_end) > bar_end - rules.COOLDOWN_SECONDS for c in saved):
            return
        contract, note = self._contract(symbol, today, signal["direction"])
        detected = self.clock()
        candidate = ScannerCandidate(
            scanner_version=rules.VERSION, params_hash=rules.PARAMS_HASH, session_date=today, symbol=symbol,
            setup=signal["setup"], direction=signal["direction"], bar_start=_utc(signal["bar_start"]), bar_end=_utc(bar_end),
            detected_at=_utc(detected), expires_at=_utc(detected + rules.EXPIRY_SECONDS), stop=signal["stop"],
            target=signal["target"], flags_json=json.dumps(signal["flags"]),
            facts_json=json.dumps({**signal["facts"], **({"contract_note": note} if note else {})}, sort_keys=True),
            contract_json=json.dumps(contract, sort_keys=True) if contract else None, source=SOURCE,
        )
        with Session(self.engine) as db:
            db.add(candidate)
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                return  # another pass already saved this bar
            db.refresh(candidate)
        if contract is not None:
            self._enter(candidate, self.clock())

    def _contract(self, symbol: str, today: date, direction: str) -> tuple[dict | None, str | None]:
        expiration = rules.pick_expiration(self.options.expirations(symbol), today)
        if expiration is None:
            return None, "no expiration today or 3-7 days out"
        chosen = rules.choose_contract(self.options.chain(symbol, expiration).contracts, direction)
        return chosen, None if chosen else "no contract met the delta and liquidity limits"

    def _daily_atr(self, symbol: str, today: date) -> float | None:
        key = (symbol, today)
        if key not in self._atr:
            data, _, issue = self.feed.read("/v1/markets/history", {
                "symbol": symbol, "interval": "daily", "start": (today - timedelta(days=40)).isoformat(),
                "end": (today - timedelta(days=1)).isoformat()}, 3600)
            if issue:
                raise ChartFeedError(f"daily bars not current: {issue}")
            days = ((data or {}).get("history") or {}).get("day") or []
            days = [days] if isinstance(days, dict) else days
            rows = [r for r in normalize_bars(days, daily=True) if datetime.fromtimestamp(r["time"], ET).date() < today]
            self._atr[key] = rules.atr14(rows)
        return self._atr[key]

    def _minutes(self, symbol: str, today: date) -> list[dict]:
        # The same request the Practice paper watcher makes for a same-day plan, so a shared cache entry.
        data, _, issue = self.feed.read("/v1/markets/timesales", {
            "symbol": symbol, "interval": "1min", "session_filter": "all",
            "start": today.strftime("%Y-%m-%d 04:00"), "end": today.strftime("%Y-%m-%d 20:00"),
        }, 15)
        if issue:
            raise ChartFeedError(f"minute bars not current: {issue}")
        series = (data or {}).get("series") or {}
        rows = series.get("data") if isinstance(series, dict) else None
        return normalize_bars(rows if isinstance(rows, list) else [rows] if isinstance(rows, dict) else [])

    # -------------------------------------------------------------- the paper trades

    def manage(self, now: float, today: date, session) -> None:
        with Session(self.engine) as db:
            rows = db.exec(select(ScannerCandidate).where(ScannerCandidate.contract_json.is_not(None))
                           .where(ScannerCandidate.session_date >= today - timedelta(days=7))).all()
            active = [(c, fold(self._events(db, c.id))) for c in rows]
        for candidate, state in active:
            status = status_of(candidate, state)
            if status not in ("pending_entry", "open", "exiting"):
                continue
            try:
                if candidate.session_date != today or session is None:
                    self._store(candidate, "unresolved", self.clock(), {"reason": "session ended before the trade finished"})
                elif status == "pending_entry":
                    self._enter(candidate, now)
                elif status == "open":
                    self._watch(candidate, state, session)
                else:
                    self._exit(candidate, state)
            except (ChartFeedError, ValueError) as exc:
                log.warning("Scanner trade %s not judged this pass: %s", candidate.id, exc)
            except Exception:
                log.exception("Scanner trade %s failed this pass", candidate.id)

    def _enter(self, candidate: ScannerCandidate, now: float) -> None:
        contract = json.loads(candidate.contract_json)
        quote = self._read_quote(contract["symbol"])
        at = self.clock()
        if quote is not None and quote.ask and quote.ask > 0 and quote.bid is not None:
            self._store(candidate, "entry", at, {"ask": quote.ask, "bid": quote.bid, "ask_time": quote.ask_date, "bid_time": quote.bid_date})
        elif at - _epoch(candidate.detected_at) > rules.MAX_DELAY_SECONDS:
            self._store(candidate, "unresolved", at, {"reason": "no entry quote within two minutes"})

    def _watch(self, candidate: ScannerCandidate, state: dict, session) -> None:
        entry_at = state["entry"]["at"]
        contract = json.loads(candidate.contract_json)
        same_day = contract["expiration"] == candidate.session_date.isoformat()
        minutes = self._minutes(candidate.symbol, candidate.session_date)
        now = self.clock()
        found = rules.exit_condition(candidate.direction, candidate.stop, candidate.target, minutes, entry_at,
                                     entry_at + rules.TIME_STOP_SECONDS, rules.flat_at(session.open_at, session.close_at, same_day),
                                     now, LATENESS)
        if found is None:
            return
        if now - found["condition_at"] > rules.MAX_DELAY_SECONDS + LATENESS:
            return self._store(candidate, "unresolved", now, {**found, "condition": found["reason"], "reason": "monitoring gap: exit condition noticed late"})
        self._store(candidate, "exit_intent", now, found)
        state = self._state(candidate)
        if "exit_intent" in state and "exit" not in state:
            self._exit(candidate, state)

    def _exit(self, candidate: ScannerCandidate, state: dict) -> None:
        contract = json.loads(candidate.contract_json)
        quote = self._read_quote(contract["symbol"])
        at = self.clock()
        if quote is not None and quote.bid is not None and quote.ask:
            exit_ = {"bid": quote.bid, "ask": quote.ask, "bid_time": quote.bid_date, "ask_time": quote.ask_date,
                     "reason": state["exit_intent"]["reason"]}
            self._store(candidate, "exit", at, {**exit_, **rules.result(state["entry"], exit_, contract["multiplier"])})
        elif at - state["exit_intent"]["at"] > rules.MAX_DELAY_SECONDS:
            self._store(candidate, "unresolved", at, {"reason": "no exit quote within two minutes"})

    def _read_quote(self, occ: str):
        try:
            return self.quote(occ)
        except tradier.TradierError as exc:
            log.warning("Scanner quote for %s unavailable: %s", occ, exc)
            return None

    # -------------------------------------------------------------- storage

    @staticmethod
    def _events(db: Session, candidate_id: uuid.UUID) -> list[ScannerEvent]:
        return list(db.exec(select(ScannerEvent).where(ScannerEvent.candidate_id == candidate_id).order_by(ScannerEvent.recorded_at)).all())

    def _state(self, candidate: ScannerCandidate) -> dict:
        with Session(self.engine) as db:
            return fold(self._events(db, candidate.id))

    def _store(self, candidate: ScannerCandidate, kind: str, at: float, data: dict) -> None:
        with Session(self.engine) as db:
            db.add(ScannerEvent(candidate_id=candidate.id, key=kind, event_type=kind, effective_at=_utc(at),
                                recorded_at=_utc(self.clock()), data_json=json.dumps(data, sort_keys=True)))
            try:
                db.commit()
            except IntegrityError:
                db.rollback()  # already stored by another pass


# ------------------------------------------------------------------ reading


def day_view(db: Session, day: date, own_entries: list[datetime] | None = None) -> dict:
    """The day's candidates and rules-only results for the owner page.

    ``own_entries`` are Isaac's option entry times that day (New York wall
    clock); they fill the review-time ``sixth_plus_entry`` flag and are never
    read by the scanner itself."""
    rows = db.exec(select(ScannerCandidate).where(ScannerCandidate.session_date == day).order_by(ScannerCandidate.bar_end)).all()
    items, totals = [], {"candidates": 0, "trades": 0, "resolved": 0, "unresolved": 0, "no_contract": 0,
                         "pnl": 0.0, "pnl_2x_spread": 0.0, "wins": 0}
    for c in rows:
        state = fold(SetupScanner._events(db, c.id))
        status = status_of(c, state)
        flags = json.loads(c.flags_json)
        if own_entries is not None:
            detected_et = c.detected_at.replace(tzinfo=UTC).astimezone(ET).replace(tzinfo=None)
            if sum(1 for t in own_entries if t < detected_et) >= 5:
                flags = flags + ["sixth_plus_entry"]
        exit_ = state.get("exit")
        totals["candidates"] += 1
        if status == "no_contract":
            totals["no_contract"] += 1
        elif status == "unresolved":
            totals["unresolved"] += 1
        if exit_:
            totals["resolved"] += 1
            totals["pnl"] += exit_["pnl"]
            totals["pnl_2x_spread"] += exit_["pnl_2x_spread"]
            totals["wins"] += exit_["pnl"] > 0
        if "entry" in state:
            totals["trades"] += 1
        items.append({
            "id": str(c.id), "symbol": c.symbol, "setup": c.setup, "direction": c.direction,
            "bar_end": c.bar_end.isoformat() + "Z", "detected_at": c.detected_at.isoformat() + "Z",
            "stop": c.stop, "target": c.target, "flags": flags, "facts": json.loads(c.facts_json),
            "contract": json.loads(c.contract_json) if c.contract_json else None, "status": status,
            "events": {k: {**v, "at": datetime.fromtimestamp(v["at"], UTC).isoformat().replace("+00:00", "Z")} for k, v in state.items()},
        })
    totals["pnl"], totals["pnl_2x_spread"] = round(totals["pnl"], 2), round(totals["pnl_2x_spread"], 2)
    return {"date": day.isoformat(), "scanner_version": rules.VERSION, "params_hash": rules.PARAMS_HASH,
            "enabled": enabled(), "totals": totals, "candidates": items}
