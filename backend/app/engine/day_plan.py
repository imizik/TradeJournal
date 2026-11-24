"""The pre-market plan card (docs/copilot-lab.md § The day plan): before the open he sets two limits for the day, and
the phone holds him to them.

- **The plan.** A max size (dollars of premium for one option position) and a hard exit time (New York wall clock),
  either may be left out. Saved as a ``day_plan`` day-journal entry (append-only; the day's newest wins), its numbers in
  the entry's ``context_json`` (``{"source": "day_plan", "max_usd": ..., "exit_by": "HH:MM"}``), so it also shows in
  the day journal and needs no table.
- **Over size** (kind ``plan_size``). An option position opened today (the journal's trades, Webull left out) whose
  premium paid is over the plan's max: one ping a position, saying by how much. A position is known by its first entry
  fill (``position_alerts.anchor``), as the position alerts know it, so a rebuild never pings it again.
- **Exit time** (kind ``plan_exit``). At the plan's exit time, when an option position opened today is still open: one
  ping that day naming them. An option position opened after the exit time gets its own ping (``plan_late``).

Only long and short option trades the journal holds are judged, so a fill that has not reached the journal yet (its
email or the read feed lagging) is judged when it lands. Nothing is locked, canceled or sized here: Robinhood's accounts
are not touched, this only tells the phone.

Off unless ``DAY_PLAN_ALERTS=true`` (the owner's switch). Saving and showing a plan works either way. While on, its pass
runs in the regular session every ``RUN_SECONDS`` on the level-alert monitor's loop. Each ping is claimed once through the
notification policy (``decide(new_only=True)``, sender ``day_plan``) and sent at most once: a failed send is logged, never
retried.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, time as clock_time, timedelta
import json
import logging
import os
import re
import time
from typing import Callable

from sqlmodel import Session, col, select

from app.engine import day_journal, notification_policy, phone
from app.engine.chart_journal import contract_label
from app.engine.chart_math import ET, session_windows
from app.models import Account, DayJournalEntry, Fill, Trade, TradeFill

log = logging.getLogger(__name__)

SENDER = "day_plan"
KIND = "day_plan"  # the day-journal entry
SIZE, EXIT, LATE = "plan_size", "plan_exit", "plan_late"
RUN_SECONDS = 30
MAX_USD = 1_000_000.0
HHMM = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def enabled() -> bool:
    return os.environ.get("DAY_PLAN_ALERTS", "").strip().lower() == "true"


class PlanError(ValueError):
    pass


# ------------------------------------------------------------------ the plan

def _minutes(hhmm: str) -> int:
    hour, minute = hhmm.split(":")
    return int(hour) * 60 + int(minute)


def clock_label(hhmm: str) -> str:
    hour, minute = divmod(_minutes(hhmm), 60)
    return f"{(hour - 1) % 12 + 1}:{minute:02d} {'AM' if hour < 12 else 'PM'}"


def describe(max_usd: float | None, exit_by: str | None) -> str:
    parts = []
    if max_usd is not None:
        parts.append(f"max ${max_usd:,.0f} a position")
    if exit_by is not None:
        parts.append(f"out of today's options by {clock_label(exit_by)} ET")
    return "Day plan: " + (", ".join(parts) if parts else "no limits")


def check(max_usd: float | None, exit_by: str | None) -> tuple[float | None, str | None]:
    if max_usd is not None and not 0 < max_usd <= MAX_USD:
        raise PlanError(f"max size must be above $0 and at most ${MAX_USD:,.0f}")
    if exit_by is not None and not HHMM.fullmatch(exit_by):
        raise PlanError("exit time must be HH:MM, 24-hour New York time")
    if max_usd is None and exit_by is None:
        raise PlanError("set a max size, an exit time or both")
    return (round(float(max_usd), 2) if max_usd is not None else None), exit_by


def save(db: Session, day: date, max_usd: float | None, exit_by: str | None, operation_id: str) -> dict:
    max_usd, exit_by = check(max_usd, exit_by)
    row = day_journal.append(db, day=day, operation_id=operation_id, kind=KIND, text=describe(max_usd, exit_by),
                             context={"source": "day_plan", "max_usd": max_usd, "exit_by": exit_by})
    return _plan(row)


def _plan(row: DayJournalEntry) -> dict:
    try:
        ctx = json.loads(row.context_json or "{}")
    except (TypeError, ValueError):
        ctx = {}
    max_usd = ctx.get("max_usd") if isinstance(ctx.get("max_usd"), (int, float)) else None
    exit_by = ctx.get("exit_by") if isinstance(ctx.get("exit_by"), str) and HHMM.fullmatch(ctx["exit_by"]) else None
    return {"day": row.day.isoformat(), "max_usd": max_usd, "exit_by": exit_by, "text": row.text,
            "saved_at": int(row.created_at.replace(tzinfo=UTC).timestamp())}


def plan_for(db: Session, day: date) -> dict | None:
    """The day's newest plan, or None."""
    row = db.exec(select(DayJournalEntry).where(DayJournalEntry.kind == KIND, DayJournalEntry.day == day)
                  .order_by(col(DayJournalEntry.created_at).desc())).first()
    return _plan(row) if row is not None else None


# ------------------------------------------------------------------ the rules

def options_today(db: Session, today: date) -> list[tuple[Trade, str]]:
    """The option trades opened today (naive New York), Webull left out, each with its position key."""
    from app.engine.position_alerts import anchor
    webull = select(Account.id).where(Account.broker == "webull")
    start = datetime.combine(today, clock_time())
    trades = db.exec(select(Trade).where(Trade.instrument_type == "option", Trade.opened_at >= start,
                                         Trade.opened_at < start + timedelta(days=1), col(Trade.account_id).not_in(webull))
                     .order_by(Trade.opened_at)).all()
    out = []
    for trade in trades:
        entries = db.exec(select(Fill).join(TradeFill, TradeFill.fill_id == Fill.id)
                          .where(TradeFill.trade_id == trade.id, TradeFill.role == "entry")).all()
        if entries:
            out.append((trade, anchor(list(entries))))
    return out


def label(trade: Trade) -> str:
    return contract_label(trade.ticker, trade.instrument_type, trade.option_type, trade.strike, trade.expiration)


def over_size(trades: list[tuple[Trade, str]], max_usd: float | None) -> list[tuple[Trade, str]]:
    if max_usd is None:
        return []
    return [(t, key) for t, key in trades if float(t.total_premium_paid or 0) > max_usd + 0.005]


def exit_due(trades: list[tuple[Trade, str]], exit_by: str | None, minute: int) -> list[Trade]:
    """Today's option positions still open at or after the exit time."""
    if exit_by is None or minute < _minutes(exit_by):
        return []
    return [t for t, _ in trades if t.status == "open"]


def late(trades: list[tuple[Trade, str]], exit_by: str | None) -> list[tuple[Trade, str]]:
    """Today's option positions opened at or after the exit time."""
    if exit_by is None:
        return []
    cut = _minutes(exit_by)
    return [(t, key) for t, key in trades if t.opened_at.hour * 60 + t.opened_at.minute >= cut]


def size_message(trade: Trade, max_usd: float) -> tuple[str, str]:
    paid = float(trade.total_premium_paid or 0)
    return (f"{trade.ticker}: ${paid:,.0f} in, over your ${max_usd:,.0f} max",
            f"{label(trade)}: ${paid:,.0f} of premium, ${paid - max_usd:,.0f} over the max size you set this morning. "
            f"Trim it back to ${max_usd:,.0f} or less.")


def exit_message(open_now: list[Trade], exit_by: str) -> tuple[str, str]:
    names = ", ".join(label(t) for t in open_now[:4]) + (f" and {len(open_now) - 4} more" if len(open_now) > 4 else "")
    n = len(open_now)
    return (f"{clock_label(exit_by)}: your exit time, {n} still open",
            f"You planned to be out of today's options by {clock_label(exit_by)}. Still open: {names}. Close {'it' if n == 1 else 'them'} now.")


def late_message(trade: Trade, exit_by: str) -> tuple[str, str]:
    return (f"{trade.ticker}: opened after your {clock_label(exit_by)} exit time",
            f"{label(trade)} was opened after the exit time you set this morning. Close it, and open nothing else today.")


# ------------------------------------------------------------------ the pass

class DayPlanPings:
    def __init__(self, engine, calendar=None, *, clock: Callable[[], float] = time.time):
        self.engine = engine
        self.calendar = calendar
        self.clock = clock
        self._last_run = 0.0
        self._done: set[str] = set()  # sources already claimed by this process

    def run(self) -> None:
        try:
            self._run()
        except Exception:  # noqa: BLE001 - one bad pass never stops the monitor's other stages
            log.exception("Day plan pass failed")

    def _run(self) -> None:
        now = self.clock()
        if now - self._last_run < RUN_SECONDS:
            return
        self._last_run = now
        moment = datetime.fromtimestamp(now, ET)
        today, minute = moment.date(), moment.hour * 60 + moment.minute
        hours = self.calendar.hours(today) if self.calendar is not None else None
        regular = next((w for w in session_windows(today, hours) if w[0] == "regular"), None)
        if regular is None or not regular[1] <= minute < regular[2]:
            return
        day = today.isoformat()
        with Session(self.engine) as db:
            plan = plan_for(db, today)
            if plan is None:
                return
            trades = options_today(db, today)
            for trade, key in over_size(trades, plan["max_usd"]):
                self._ping(db, SIZE, f"{SIZE}:{day}:{key}", *size_message(trade, plan["max_usd"]), symbol=trade.ticker, now=now)
            opened_late = late(trades, plan["exit_by"])
            for trade, key in opened_late:
                self._ping(db, LATE, f"{LATE}:{day}:{key}", *late_message(trade, plan["exit_by"]), symbol=trade.ticker, now=now)
            # The exit-time ping names the positions opened before it; one opened later has its own ping.
            late_ids = {id(t) for t, _ in opened_late}
            hidden = day_journal.quiet(db)  # tickers he hid on the desk; the policy also holds a one-ticker ping for them
            still = [t for t in exit_due(trades, plan["exit_by"], minute) if id(t) not in late_ids and t.ticker not in hidden]
            if still:
                self._ping(db, EXIT, f"{EXIT}:{day}", *exit_message(still, plan["exit_by"]),
                           symbol=still[0].ticker if len(still) == 1 else None, now=now)

    def _ping(self, db: Session, kind: str, source: str, title: str, body: str, *, symbol: str | None, now: float) -> None:
        """Claim the ping once, then send it once; a failed send is not retried (it may have arrived)."""
        if source in self._done or not phone.configured():
            return
        self._done.add(source)
        ticket = notification_policy.decide(db, sender=SENDER, source_id=source, kind=kind, title=title, body=body,
                                            now=now, symbol=symbol, new_only=True)
        if ticket.held:
            log.info("Day plan %s held: %s", kind, ticket.reason)
            return
        try:
            phone.send(title, body + ticket.append, kind=kind, path=phone.desk_link("/", symbol=symbol), priority=5, tags=("warning",))
        except phone.SendError as exc:
            log.warning("Day plan %s not sent: %s", kind, exc)
            return
        notification_policy.delivered(db, ticket, now)
        db.commit()
