"""Real-money day lock: at most two phone pings a New York day, about the day as a whole rather than one position.

- **Daily loss lock** (kind ``day_loss``). The paper challenge's daily limit (``paper_challenge.DAILY_PCT``, 3%) on
  his real accounts: once the day's P&L is at or below minus that share of the start-of-day value, one ping says he is
  done for the day. Nothing is locked or canceled here: the real accounts are Robinhood's, and this only tells the phone.
- **Green, walk away** (kind ``day_green``). The October 21, 2026 behavior audit found trades opened with the day
  already green cost $8.9k (``fill_interrupts``' ``opened_green`` record). That interrupt fires after the next entry;
  this one comes first: within ``GREEN_FRESH_MINUTES`` of a close that leaves him flat on today's trades (no position
  opened today still open) with today's realized P&L at least ``GREEN_MIN_DOLLARS``, one ping says to stop while green,
  with his own record of trades opened while green.

**The day's P&L** is today's realized P&L (the journal's trades closed today, Webull left out, the same closes
``fill_interrupts`` reads) plus Robinhood's change today on what is still open (each account's ``day_change`` from the
read-only feed, read as the desk's own account line reads it, ``copilot_desk._robinhood``; an account whose change the
order history makes unsure is unknown). The
start-of-day value is the accounts' total value now less that P&L, so the percent is of the morning's value. Known
limits: a trade opened before today and closed today counts its whole realized P&L; a partial close of a position
still open is not counted until it closes; a deposit or withdrawal is not told apart. The loss lock needs the feed
(on, signed in and fresh) and every shown account's value and change; without them it stays silent (it cannot tell),
never guesses. The green ping needs only the journal; when the feed is fresh, the open positions' change must not
take the day to zero or below.

Off unless ``DAY_LOCK_ALERTS=true`` (the owner's switch). While on, its pass reads the feed's cached snapshot each
``RUN_SECONDS`` in the regular session and lets the feed refresh as an open desk does (the desk's own read: at most one
read a minute), so the lock works with no desk open. Each ping is claimed once a day through the notification policy
(``decide(new_only=True)``, sender ``day_lock``, source ``<kind>:<day>``; a claim that fails holds it) and sent at
most once: a failed send is logged, never retried.
"""

from __future__ import annotations

from datetime import date, datetime, time as clock_time, timedelta
import logging
import os
import time
from typing import Callable

from sqlmodel import Session, col, select

from app.engine import notification_policy, phone
from app.engine.chart_math import ET, session_windows
from app.engine.paper_challenge import DAILY_PCT
from app.models import Account, Trade

log = logging.getLogger(__name__)

SENDER = "day_lock"
LOSS, GREEN = "day_loss", "day_green"
RUN_SECONDS = 30
GREEN_MIN_DOLLARS = 50.0
GREEN_FRESH_MINUTES = 20  # a close older than this is not the moment he went flat (fill emails can lag)
MIN_SAMPLE = 5


def enabled() -> bool:
    return os.environ.get("DAY_LOCK_ALERTS", "").strip().lower() == "true"


# ------------------------------------------------------------------ the rules (pure)

def open_change(accounts: list[dict] | None) -> float | None:
    """The shown accounts' change today on what is open; None when any is unknown or there are none."""
    if not accounts:
        return None
    moves = [a.get("day_change") for a in accounts]
    return None if any(not isinstance(m, (int, float)) for m in moves) else round(sum(moves), 2)


def day_figures(realized: float, accounts: list[dict] | None) -> dict:
    """The day's P&L and its percent of the start-of-day value; ``pnl`` is realized alone (``complete`` false) when
    the feed's figures are missing, and ``pct`` is then None."""
    change = open_change(accounts)
    values = [a.get("total_value") for a in accounts or []]
    if change is None or not values or any(not isinstance(v, (int, float)) for v in values):
        return {"pnl": round(realized, 2), "pct": None, "start": None, "complete": False}
    pnl = round(realized + change, 2)
    start = round(sum(values) - pnl, 2)
    return {"pnl": pnl, "pct": round(100 * pnl / start, 2) if start > 0 else None, "start": start, "complete": True}


def loss_due(figures: dict) -> bool:
    return figures["pct"] is not None and figures["pct"] <= -DAILY_PCT


def green_due(realized: float, figures: dict, open_today: int, last_close: datetime | None, now_ny: datetime) -> bool:
    """Flat on today's trades, a close in the last ``GREEN_FRESH_MINUTES``, realized at least ``GREEN_MIN_DOLLARS``,
    and (when the feed's figures are known) the whole day still above zero."""
    if open_today or last_close is None or realized < GREEN_MIN_DOLLARS:
        return False
    if not timedelta(0) <= now_ny - last_close <= timedelta(minutes=GREEN_FRESH_MINUTES):
        return False
    return not figures["complete"] or figures["pnl"] > 0


def money(value: float) -> str:
    return f"{'+' if value >= 0 else '−'}${abs(value):,.0f}"


def loss_message(figures: dict) -> tuple[str, str]:
    return (f"Down {money(figures['pnl'])} today ({figures['pct']:+.1f}%): your {DAILY_PCT:g}% day lock",
            f"That is your daily loss limit, the same {DAILY_PCT:g}% the paper challenge locks at, of about "
            f"${figures['start']:,.0f} this morning. Done for today: close what you must, open nothing new.")


def green_message(realized: float, record: dict | None) -> tuple[str, str]:
    lines = [f"You closed green ({money(realized)} realized today) and you are flat. This is the moment to stop."]
    if record and record["n"] >= MIN_SAMPLE:
        lines.append(f"Your past trades opened with the day already green: {record['n']:,}, {money(record['pnl'])}.")
    lines.append("Walk away for the day.")
    return f"Green on the day {money(realized)}: walk away", "\n".join(lines)


# ------------------------------------------------------------------ the reads

def journal_today(db: Session, today: date) -> tuple[float, datetime | None, int]:
    """Today's realized P&L, the newest close today (naive New York) and the positions opened today still open, from
    the journal; Webull (dormant) left out."""
    webull = select(Account.id).where(Account.broker == "webull")
    start = datetime.combine(today, clock_time())
    end = start + timedelta(days=1)
    closes = db.exec(select(Trade.realized_pnl, Trade.closed_at).where(
        Trade.status.in_(("closed", "expired")), Trade.closed_at >= start, Trade.closed_at < end,
        col(Trade.account_id).not_in(webull))).all()
    open_today = db.exec(select(Trade.id).where(Trade.status == "open", Trade.opened_at >= start, Trade.opened_at < end,
                                                col(Trade.account_id).not_in(webull))).all()
    realized = round(sum(float(p or 0) for p, _c in closes), 2)
    return realized, max((c for _p, c in closes), default=None), len(open_today)


def live_accounts() -> list[dict] | None:
    """The feed's shown accounts when its snapshot is fresh (letting it refresh as a desk read does), with today's
    change left unknown where the order history makes it unsure; None when it cannot tell."""
    try:
        from app.routers import copilot_desk  # the account line exactly as the desk's read holds it
        live = copilot_desk._robinhood()
        return live["view"].get("accounts") if live["snapshot"] is not None else None
    except Exception:  # noqa: BLE001 - no read means no judgment, never a failed pass
        log.info("Day lock: Robinhood feed unreadable", exc_info=True)
        return None


def green_record(db: Session) -> dict | None:
    """``fill_interrupts``' opened-while-green record over every closed trade; None when it cannot be read."""
    try:
        from app.engine import fill_interrupts
        return fill_interrupts.record(fill_interrupts.load_history(db), "opened_green")
    except Exception:  # noqa: BLE001 - the ping matters more than its record
        log.warning("Day lock: green record skipped", exc_info=True)
        return None


# ------------------------------------------------------------------ the pass

class DayLock:
    def __init__(self, engine, calendar=None, *, clock: Callable[[], float] = time.time, accounts: Callable[[], list[dict] | None] = live_accounts):
        self.engine = engine
        self.calendar = calendar
        self.clock = clock
        self.accounts = accounts
        self._last_run = 0.0
        self._done: set[str] = set()  # "<kind>:<day>" already claimed by this process

    def run(self) -> None:
        try:
            self._run()
        except Exception:  # noqa: BLE001 - one bad pass never stops the monitor's other stages
            log.exception("Day lock pass failed")

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
        if f"{LOSS}:{day}" in self._done and f"{GREEN}:{day}" in self._done:
            return
        with Session(self.engine) as db:
            realized, last_close, open_today = journal_today(db, today)
            figures = day_figures(realized, self.accounts())
            if f"{LOSS}:{day}" not in self._done and loss_due(figures):
                self._ping(db, LOSS, day, *loss_message(figures), priority=5, now=now)
            if f"{GREEN}:{day}" not in self._done and green_due(realized, figures, open_today, last_close, moment.replace(tzinfo=None)):
                self._ping(db, GREEN, day, *green_message(realized, green_record(db)), priority=4, now=now)

    def _ping(self, db: Session, kind: str, day: str, title: str, body: str, *, priority: int, now: float) -> None:
        """Claim the day's ping once, then send it once; a failed send is not retried (it may have arrived)."""
        if not phone.configured():
            return
        self._done.add(f"{kind}:{day}")
        ticket = notification_policy.decide(db, sender=SENDER, source_id=f"{kind}:{day}", kind=kind, title=title, body=body,
                                            now=now, new_only=True)
        if ticket.held:
            log.info("Day lock %s held: %s", kind, ticket.reason)
            return
        try:
            phone.send(title, body + ticket.append, kind=kind, path=phone.desk_link("/"), priority=priority, tags=("warning",))
        except phone.SendError as exc:
            log.warning("Day lock %s not sent: %s", kind, exc)
            return
        notification_policy.delivered(db, ticket, now)
        db.commit()
