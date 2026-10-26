"""Pre-market prep: one phone ping each trading morning with what the owner holds and has planned.

At ``PREMARKET_PREP_AT`` (default 08:30 New York) on a trading day (the market
calendar's regular session; never a weekend or holiday) the day is claimed once
(``PremarketPrep.day`` is unique, so a restart or a second process never
prepares a second one) and a compact pack is assembled from code that already
exists:

- open positions with days to expiry, expires-today, give-back watch state and
  open P&L (the owner context pack's positions section);
- armed copilot plans with their distance to the entry and the invalidation
  (``copilot_plans.board``, one batched quote read);
- earnings this week for held symbols and symbols with an active thesis memory
  (the ``get_symbol_events`` calendar, one batched read, at most 8 symbols);
- today's pending plan time stops, and the plan streak.

One Copilot Lab turn (``run_turn``, the lab's backend and system prompt as
configured, its turn budget cap included) writes at most 6 lines from it, and
the result is saved as a copilot investigation titled ``Pre-market prep
<date>`` so it shows in Open threads. The ping's title is ``Pre-market prep``,
its body the first two lines, and a tap opens that investigation. If the turn
fails, the ping carries the raw facts (expiries and nearest triggers) instead,
labelled as such. Nothing here places, changes or suggests an order.

Off unless ``PREMARKET_PREP_ENABLED=true``, and nothing runs while the lab is
off (``COPILOT_ENABLED``). It runs on the level alert monitor's loop beside the
plan pings; the prep itself (reads and the model turn) runs on its own thread so
the alert loop is never held up. A prep not started within ``WINDOW_MINUTES``
of its time is not started late. Delivery is at-most-once, as plan nudges': a
send that may have reached ntfy is ``unknown`` and never resent, and a ping not
sent within ``EXPIRE_SECONDS`` of its claim is dropped as ``expired``.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta
import json
import logging
import os
import threading
import time
from typing import Callable
import uuid

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.engine import notification_policy, ntfy, ping_images
from app.engine.chart_math import ET, session_windows
from app.engine.position_alerts import BACKOFF, CLAIM_SECONDS, _epoch, _surely_unsent, _utc
from app.models import PlanTimeStop, PremarketPrep

log = logging.getLogger(__name__)

RUN_SECONDS = 30
DEFAULT_AT = 8 * 60 + 30
WINDOW_MINUTES = 60  # a prep not started this long after its time waits for the next trading day
PREPARE_SECONDS = 10 * 60  # a claimed prep that never finished (a crash mid-turn) is given up, not redone
EXPIRE_SECONDS = 30 * 60
MAX_LINES = 6
BODY_LINES = 2
MAX_PLANS = 6
MAX_EARNINGS_SYMBOLS = 8
TITLE = "Pre-market prep"
FALLBACK_LABEL = "Raw facts (the copilot turn failed):"


def enabled() -> bool:
    return os.environ.get("PREMARKET_PREP_ENABLED", "").lower() == "true"


def prep_minute() -> int:
    """``PREMARKET_PREP_AT`` (``HH:MM`` New York) as a minute of the day; 08:30 when unset or unreadable."""
    raw = os.environ.get("PREMARKET_PREP_AT", "").strip()
    if not raw:
        return DEFAULT_AT
    try:
        hour, minute = (int(part) for part in raw.split(":"))
    except ValueError:
        hour = minute = -1
    if 0 <= hour < 24 and 0 <= minute < 60:
        return hour * 60 + minute
    log.warning("PREMARKET_PREP_AT=%r is not HH:MM; using 08:30", raw)
    return DEFAULT_AT


def _lab_on() -> bool:
    from app.ai import copilot
    return copilot.settings().enabled


def _trading_day(calendar, day: date) -> bool:
    hours = calendar.hours(day) if calendar is not None else None
    return any(w[0] == "regular" for w in session_windows(day, hours))


# --------------------------------------------------------------------------- the pack

def _positions(db: Session, now_et: datetime) -> dict:
    """The owner context pack's positions section, cut to what the morning needs; expiring soonest first."""
    from app.ai import copilot_context
    section = copilot_context._positions(db, None, now_et)
    keep = ("symbol", "instrument", "option", "direction", "quantity", "unrealized_usd", "unrealized_pct",
            "days_to_expiry", "expires_today", "giveback", "peak_gain_pct")
    rows = []
    for row in section["positions"]:
        out = {k: row[k] for k in keep if row.get(k) is not None}
        if row.get("plan", {}).get("setup"):
            out["plan"] = row["plan"]["setup"]
        rows.append(out)
    rows.sort(key=lambda r: (not r.get("expires_today"), r.get("days_to_expiry", 10_000)))
    return {"state": "ok", "count": section["count"], "shown": len(rows), "positions": rows}


def _level(level: dict | None) -> dict | None:
    if level is None:
        return None
    return {k: level[k] for k in ("price", "state", "distance_pct") if level.get(k) is not None}


def _plans(db: Session) -> dict:
    from app.ai.copilot_context import _trim
    from app.engine import copilot_plans
    board = copilot_plans.board(db)
    rows = [{k: v for k, v in {
        "symbol": p["symbol"], "direction": p["direction"], "last": p["last"], "thesis": _trim(p["thesis"], 100),
        "entry": _level(p["entry"]), "invalidation": _level(p["invalidation"]), "position": p["position"],
        "time_stop": f"{p['time_stop']['text']} ({p['time_stop']['state']})" if p["time_stop"] else None,
    }.items() if v is not None} for p in board["plans"][:MAX_PLANS]]
    out = {"state": "ok", "count": len(board["plans"]), "plans": rows}
    if board["quote_issue"]:
        out["quote_issue"] = board["quote_issue"]
    return out


def _thesis_symbols(db: Session) -> list[str]:
    from app.engine import jo_briefing
    found = []
    for memory in jo_briefing.memories(db, status="active", limit=40):
        if memory.get("symbol") and not memory.get("redacted_at") and (memory.get("body") or {}).get("kind") == "thesis":
            found.append(memory["symbol"])
    return found


def _earnings(symbols: list[str], today: date) -> dict:
    """Reports from today through Sunday for up to ``MAX_EARNINGS_SYMBOLS`` symbols, from one batched calendar read."""
    from app.engine.chart_indices import is_index
    from app.engine.symbol_info_tradier import symbol_events
    wanted = [s for s in dict.fromkeys(symbols) if not is_index(s)][:MAX_EARNINGS_SYMBOLS]
    if not wanted:
        return {"state": "ok", "checked": [], "this_week": []}
    issue = symbol_events.refresh("calendars", wanted)  # one read for every stale symbol; each view below is cached
    week_end = (today + timedelta(days=6 - today.weekday())).isoformat()
    rows, missing = [], []
    for symbol in wanted:
        view = symbol_events.forecast_earnings(symbol, today)
        upcoming = view.get("next")
        if upcoming and upcoming["date"] <= week_end:
            rows.append({"symbol": symbol, "date": upcoming["date"], "status": upcoming["status"]})
        elif view.get("state") in ("unavailable", "loading"):
            missing.append(symbol)
    out = {"state": "ok", "checked": wanted, "this_week": rows}
    if missing:
        out.update(unavailable=missing, message=issue or "The earnings calendar could not be read for these.")
    return out


def _time_stops(db: Session, today: date) -> dict:
    start = datetime(today.year, today.month, today.day, tzinfo=ET)
    rows = db.exec(select(PlanTimeStop).where(PlanTimeStop.delivery == "scheduled",
                                              PlanTimeStop.due_at >= _utc(start.timestamp()),
                                              PlanTimeStop.due_at < _utc((start + timedelta(days=1)).timestamp()))
                   .order_by(PlanTimeStop.due_at)).all()
    return {"state": "ok", "today": [{"symbol": r.symbol, "text": r.text,
                                       "due": datetime.fromtimestamp(_epoch(r.due_at), ET).strftime("%H:%M ET")} for r in rows]}


def _streak(db: Session, now: float) -> dict:
    from app.engine import plan_streak
    found = plan_streak.streak(db, _utc(now))
    week = found["this_week"]
    out = {"state": "ok", "current": found["current"], "best": found["best"], "this_week": f"{week['planned']} of {week['total']} planned"}
    if found["last_break"]:
        out["last_break"] = f"{found['last_break']['short']} ({found['last_break']['reason']})"
    return out


def build_pack(db: Session, now: float) -> dict:
    """The morning's facts. Each section degrades to ``unavailable`` on its own."""
    from app.ai.copilot_context import _section
    now_et = datetime.fromtimestamp(now, ET)
    today = now_et.date()
    positions = _section("positions", lambda: _positions(db, now_et))
    held = [p["symbol"] for p in positions.get("positions", [])]
    try:
        thesis = _thesis_symbols(db)
    except Exception:  # noqa: BLE001 - earnings for the held symbols still stand
        log.warning("premarket prep: thesis memories unavailable")
        thesis = []
    return {
        "day": today.isoformat(), "as_of": now_et.strftime("%Y-%m-%d %H:%M ET"),
        "positions": positions,
        "plans": _section("plans", lambda: _plans(db)),
        "earnings": _section("earnings", lambda: _earnings(held + thesis, today)),
        "time_stops": _section("time_stops", lambda: _time_stops(db, today)),
        "streak": _section("streak", lambda: _streak(db, now)),
    }


def prompt(pack: dict) -> str:
    day = date.fromisoformat(pack["day"])
    return (f"{TITLE} for {day:%a %b} {day.day}. Below are TradeJournal's facts for this morning, assembled before the open. "
            f"Write at most {MAX_LINES} short plain lines, no headings: first what expires today or sits nearest a trigger, "
            "then one thing to decide before the open. Use only these facts; leave out a section that is empty or unavailable. "
            "Invent nothing: no prices, levels, news or dates that are not here, and no orders.\n\n"
            "[Pre-market facts]\n" + json.dumps(pack, default=str, separators=(",", ":")))


def lines(text: str) -> list[str]:
    return [line.strip() for line in (text or "").splitlines() if line.strip()][:MAX_LINES]


def _contract(row: dict) -> str:
    option = row.get("option")
    if not option:
        return f"{row['symbol']} stock"
    return f"{row['symbol']} {option['strike']:g}{'C' if option['side'] == 'call' else 'P'} {option['expiry'][5:].replace('-', '/')}"


def fallback_lines(pack: dict) -> list[str]:
    """The raw facts when the turn fails: expiries first, then the nearest triggers. Nothing interpreted."""
    out = [FALLBACK_LABEL]
    held = pack["positions"].get("positions", [])
    soon = [p for p in held if p.get("days_to_expiry") is not None and p["days_to_expiry"] <= 2]
    if soon:
        out.append("Expiring: " + "; ".join(f"{_contract(p)} " + ("today" if p.get("expires_today") else f"in {p['days_to_expiry']}d")
                                            for p in soon[:3]))
    elif pack["positions"].get("state") == "ok":
        out.append(f"{pack['positions']['count']} open, none expiring within 2 days.")
    else:
        out.append("Positions unavailable.")
    triggers = []
    for plan in pack["plans"].get("plans", []):
        for role in ("entry", "invalidation"):
            level = plan.get(role)
            if level and level.get("state") == "armed":
                pct = level.get("distance_pct")
                gap = f" ({pct:+.1f}%)" if pct is not None else ""
                triggers.append((abs(pct) if pct is not None else float("inf"), f"{plan['symbol']} {role} {level['price']:g}{gap}"))
    if triggers:
        out.append("Nearest triggers: " + "; ".join(text for _, text in sorted(triggers, key=lambda t: t[0])[:3]))
    elif pack["plans"].get("state") != "ok":
        out.append("Plans unavailable.")
    stops = pack["time_stops"].get("today", [])
    if stops:
        out.append("Time stops today: " + "; ".join(f"{s['symbol']} {s['due']}" for s in stops[:3]))
    earnings = pack["earnings"].get("this_week", [])
    if earnings:
        out.append("Earnings this week: " + "; ".join(f"{e['symbol']} {e['date'][5:]}" for e in earnings[:4]))
    return out[:MAX_LINES]


def _turn(text: str, now: float, events: list | None = None) -> tuple[str, str | None]:
    """One lab turn on the owner's prompt: ``(answer, error)``. An error means the answer cannot be used. ``events``, when
    given, collects every turn event (the week review reads its tool and proposal events)."""
    from app.ai import copilot
    cfg = copilot.settings()
    now_et = datetime.fromtimestamp(now, ET)
    history = [{"role": "user", "content": text}]

    async def go() -> tuple[str, str | None]:
        adapter = await asyncio.to_thread(copilot.adapter_for, cfg)
        evidence = copilot.evidence_for(cfg)
        parts, error = [], None
        try:
            # The plan backend's SDK runs its own tool loop, so it supplies the whole turn (as the chat route does).
            turn = (adapter.run_turn(history, None, cfg, evidence, now_et) if hasattr(adapter, "run_turn")
                    else copilot.run_turn(history, None, cfg, adapter, evidence, now_et))
            async for event in turn:
                if events is not None:
                    events.append(event)
                if event["type"] == "text":
                    parts.append(event["delta"])
                elif event["type"] == "error" and error is None:
                    error = event.get("message") or event.get("code") or "error"
        finally:
            if hasattr(adapter, "aclose"):
                await adapter.aclose()
        return "".join(parts), error

    try:
        answer, error = asyncio.run(go())
    except copilot.CopilotError as exc:
        return "", exc.message
    except Exception as exc:  # noqa: BLE001 - any failure falls back to the raw facts
        log.warning("scheduled copilot turn failed: %s", type(exc).__name__)
        return "", "The copilot turn failed unexpectedly."
    if error is None and not lines(answer):
        error = "The copilot wrote nothing."
    return answer, error


def _save(db: Session, day: date, question: str, written: list[str]) -> str:
    from app.engine import copilot_investigations as investigations
    fields = investigations.InvestigationFields(
        title=f"{TITLE} {day.isoformat()}", conclusion=written[0][:280] if written else None,
        transcript=[{"role": "user", "content": question[:20_000]}, {"role": "assistant", "content": "\n".join(written)}])
    return investigations.create(fields, session=db)["id"]


def message(row: PremarketPrep) -> tuple[str, str, str]:
    """Title, body (the first two lines) and the app path the notification opens."""
    shown = (row.body or "").splitlines()[:BODY_LINES]
    # ``origin``: a plan made from the prep records it (docs/copilot-lab.md § Origin).
    path = (f"/copilot-lab?investigation={row.investigation_id}&origin=premarket_prep:{row.investigation_id}"
            if row.investigation_id else "/copilot-lab?origin=premarket_prep")
    return TITLE, "\n".join(shown) or TITLE, path


class PremarketPreps:
    def __init__(self, engine, calendar=None, *, clock: Callable[[], float] = time.time,
                 spawn: Callable[[Callable[[], None]], None] | None = None, turn=_turn):
        self.engine = engine
        self.calendar = calendar
        self.clock = clock
        self.turn = turn
        self._spawn = spawn or (lambda work: threading.Thread(target=work, daemon=True, name="premarket-prep").start())
        self._last_run = 0.0

    def run(self) -> None:
        """Claim today's prep once it is due, then prepare it off the alert loop."""
        now = self.clock()
        if now - self._last_run < RUN_SECONDS:
            return
        self._last_run = now
        if not enabled() or not _lab_on():
            return
        moment = datetime.fromtimestamp(now, ET)
        start = prep_minute()
        if not start <= moment.hour * 60 + moment.minute < start + WINDOW_MINUTES or not _trading_day(self.calendar, moment.date()):
            return
        with Session(self.engine) as db:
            if db.exec(select(PremarketPrep.id).where(PremarketPrep.day == moment.date())).first():
                return
            row = PremarketPrep(day=moment.date(), detected_at=_utc(now))
            db.add(row)
            try:
                db.commit()
            except IntegrityError:
                db.rollback()  # another process claimed today a moment earlier
                return
            row_id = row.id
        log.info("Pre-market prep claimed for %s", moment.date())
        self._spawn(lambda: self._prepare_and_send(row_id))

    def _prepare_and_send(self, row_id: uuid.UUID) -> None:
        try:
            self.prepare(row_id)
        except Exception:
            log.exception("Pre-market prep failed")
            with Session(self.engine) as db:
                db.exec(update(PremarketPrep).where(PremarketPrep.id == row_id, PremarketPrep.delivery == "preparing")
                        .values(delivery="expired", last_error="The prep could not be assembled, so nothing was sent."))
                db.commit()
            return
        self.deliver()

    def prepare(self, row_id: uuid.UUID) -> None:
        """Assemble the pack, run the turn, save the investigation and queue the ping."""
        now = self.clock()
        with Session(self.engine) as db:
            row = db.get(PremarketPrep, row_id)
            if row is None or row.delivery != "preparing":
                return
            pack = build_pack(db, now)
            question = prompt(pack)
        answer, error = self.turn(question, now)
        written = lines(answer) if error is None else fallback_lines(pack)
        with Session(self.engine) as db:
            row = db.get(PremarketPrep, row_id)
            if row is None or row.delivery != "preparing":
                return  # given up meanwhile: never sent late
            investigation_id = _save(db, row.day, question, written)
            # Only a prep still preparing is queued: one given up meanwhile stays expired.
            queued = db.exec(update(PremarketPrep).where(PremarketPrep.id == row_id, PremarketPrep.delivery == "preparing").values(
                delivery="pending", investigation_id=investigation_id, body="\n".join(written), fallback=error is not None,
                last_error=None if error is None else f"Copilot turn failed: {error}"[:500]))
            db.commit()
            if queued.rowcount != 1:
                return
        log.info("Pre-market prep ready (%s)", "raw facts" if error else "copilot")

    # ------------------------------------------------------------ deliver

    def deliver(self) -> None:
        now = self.clock()
        with Session(self.engine) as db:
            db.exec(update(PremarketPrep).where(PremarketPrep.delivery == "preparing", PremarketPrep.detected_at < _utc(now - PREPARE_SECONDS))
                    .values(delivery="expired", last_error="The prep did not finish in time, so nothing was sent."))
            # A claim this old may have reached ntfy before the pass died: never resent.
            db.exec(update(PremarketPrep).where(PremarketPrep.delivery == "sending", PremarketPrep.claimed_at < _utc(now - CLAIM_SECONDS))
                    .values(delivery="unknown", last_error="The send was interrupted and may have reached the phone, so it was not resent."))
            db.commit()
            due = db.exec(select(PremarketPrep.id).where(PremarketPrep.delivery == "pending")
                          .where((PremarketPrep.next_attempt_at.is_(None)) | (PremarketPrep.next_attempt_at <= _utc(now)))
                          .order_by(PremarketPrep.detected_at).limit(5)).all()
        for row_id in due:
            self._send(row_id)

    def _send(self, row_id: uuid.UUID) -> None:
        now = self.clock()
        with Session(self.engine) as db:
            claimed = db.exec(update(PremarketPrep).where(PremarketPrep.id == row_id, PremarketPrep.delivery == "pending")
                              .values(delivery="sending", claimed_at=_utc(now)))
            db.commit()
            if claimed.rowcount != 1:
                return  # another process or pass has it
            row = db.get(PremarketPrep, row_id)
            if now - _epoch(row.detected_at) > EXPIRE_SECONDS:
                row.delivery, row.last_error = "expired", "Not sent within 30 minutes of its time, so it was not sent late."
                db.commit()
                return
            if not ntfy.configured():
                row.delivery, row.next_attempt_at = "pending", _utc(now + BACKOFF[-1])
                row.last_error = "Phone alerts are not set up on this server (NTFY_URL is not set)."
                db.commit()
                return
            title, body, path = message(row)
            ticket = notification_policy.decide(db, sender="premarket_prep", source_id=str(row.id), kind="prep", title=title, body=body, now=now)
            if ticket.held:
                row.delivery, row.last_error = "held", ticket.reason
                db.commit()
                return
            image = ping_images.picture(ping_images.prepare(db, self._picture, now)) if row.attempts == 0 else None  # a retry goes as text
            row.attempts += 1
            try:
                _, image_state = ping_images.publish(title, body + ticket.append, image, priority=3, tags=("sunrise",), path=path,
                                                     direct_click=True)
            except ntfy.NtfyError as exc:
                if not _surely_unsent(exc):
                    row.delivery, row.last_error = "unknown", f"{exc} It may have reached the phone, so it was not resent."
                    notification_policy.delivered(db, ticket, now)
                else:
                    row.delivery, row.last_error = "pending", str(exc)
                    row.next_attempt_at = _utc(now + BACKOFF[min(row.attempts, len(BACKOFF)) - 1])
                db.commit()
                log.warning("Pre-market prep delivery failed (attempt %d): %s", row.attempts, exc)
                return
            row.delivery, row.delivered_at = "sent", _utc(self.clock())
            notification_policy.delivered(db, ticket, now)
            ping_images.record(db, ticket, image_state)
            db.commit()

    def _picture(self, db: Session, now: float):
        """One picture: the open options by days to expiry, else the first armed plan's chart."""
        today = datetime.fromtimestamp(now, ET).date()
        options, plan = ping_images.premarket_facts(db, today)
        if options:
            return ping_images.positions_strip("Pre-market · days to expiry", options)
        if plan is None:
            return None
        symbol, levels = plan
        return ping_images.armed_plan(f"Pre-market · {symbol} plan", symbol, levels, today, self.calendar)
