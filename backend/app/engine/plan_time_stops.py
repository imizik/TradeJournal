"""Plan time stops: a confirmed copilot plan's "out by 15:30" becomes one timed phone ping.

The plan card's time stop is read by ``parse``: a clock time (``out by 15:30``,
``15:30``, ``3:30pm``) is the next regular session that still has it ahead,
today when it can be; a duration in minutes or hours (``45m``, ``2h``) counts
from the Confirm; a number of days (``2 days``) is that many trading days
ahead at 15:30 ET (half an hour before an early close). A length runs no later
than today's close. The market calendar is only published through the current
month, so a day count landing in a later month sees weekends but not its
holidays or early closes (the preview shows the date). Text it cannot read
stays a note in the plan and schedules nothing.

At ``due_at`` the row is judged once: if the owner holds an open position in
the symbol whose first entry came after the plan, one ntfy notification goes
out (``NBIS time stop: you planned to be out by 15:30.``) and its tap opens the
trade; otherwise it is recorded ``skipped`` and nothing is sent. Nothing here
places, changes or suggests an order.

Off unless ``PLAN_TIME_STOPS_ENABLED=true``. It runs on the level alert
monitor's loop beside plan nudges. Webull is dormant and left out. Delivery is
at-most-once, as plan nudges': a send that may have reached ntfy is
``unknown`` and never resent, and one not judged or sent within
``EXPIRE_SECONDS`` of its time is dropped as ``expired``. Right before the send,
``notification_policy.decide`` may hold it (``held``, with the reason): the
shared daily cap, or a ping for the same position moments earlier.
"""

from datetime import date, datetime, timedelta
import logging
import os
import re
import time
from typing import Callable
import uuid

from sqlalchemy import or_, update
from sqlmodel import Session, select

from app.engine import notification_policy, ntfy, ping_images
from app.engine.chart_journal import stamp
from app.engine.chart_math import ET, session_windows
from app.engine.position_alerts import BACKOFF, CLAIM_SECONDS, _epoch, _surely_unsent, _utc
from app.models import Account, Fill, PlanTimeStop, Trade, TradeFill

log = logging.getLogger(__name__)

EXPIRE_SECONDS = 15 * 60
DAY_STOP_MINUTE = 15 * 60 + 30  # "2 days" means out by 15:30 ET on the second trading day
MAX_DAYS = 30  # trading days ahead a time stop may be

_CLOCK = re.compile(r"\b(\d{1,2})(?::([0-5]\d))?\s*(a\.?m\.?|p\.?m\.?)?(?![\w:])", re.I)
_DURATION = re.compile(r"(?<![\d.])\b(\d{1,3})\s*(m|mins?|minutes?|h|hrs?|hours?|d|days?|trading\s+days?)\b(\s+\w+)?", re.I)
# "10 minutes before the close", "5m closes under 92": an offset or a candle, not a length
_NOT_A_LENGTH = {"before", "after", "close", "closes", "closing", "candle", "candles", "bar", "bars", "chart"}


def enabled() -> bool:
    return os.environ.get("PLAN_TIME_STOPS_ENABLED", "").lower() == "true"


def _regular(calendar, day: date):
    hours = calendar.hours(day) if calendar is not None else None
    return next((w for w in session_windows(day, hours) if w[0] == "regular"), None)


def _at(day: date, minute: int) -> float:
    return datetime(day.year, day.month, day.day, minute // 60, minute % 60, tzinfo=ET).timestamp()


def _clock_text(due: float, now: float) -> str:
    moment, today = datetime.fromtimestamp(due, ET), datetime.fromtimestamp(now, ET).date()
    hhmm = moment.strftime("%H:%M")
    if moment.date() == today:
        return f"today {hhmm} ET"
    return f"{moment.strftime('%a %b')} {moment.day}, {hhmm} ET"


def parse(text: str, now: float, calendar=None) -> dict:
    """``{"due_at": epoch, "when": "today 15:30 ET"}`` or ``{"due_at": None, "reason": ...}`` for a note."""
    text = (text or "").strip()
    if not text:
        return {"due_at": None, "reason": "No time stop."}
    today = datetime.fromtimestamp(now, ET).date()
    duration = _DURATION.search(text)
    clock = next((m for m in _CLOCK.finditer(text) if m.group(2) or m.group(3)), None)  # a bare "3" is not a time
    if duration and (clock is None or duration.start() < clock.start()):
        count, unit = int(duration.group(1)), duration.group(2).lower()
        if (duration.group(3) or "").strip().lower() in _NOT_A_LENGTH:
            return {"due_at": None, "reason": "That reads as a candle or an offset, not a length, so it stays a note."}
        if count <= 0:
            return {"due_at": None, "reason": "A time stop needs a length above zero."}
        if unit[0] in "dt":
            if count > MAX_DAYS:
                return {"due_at": None, "reason": f"Up to {MAX_DAYS} trading days ahead."}
            day, left = today, count
            for _ in range(MAX_DAYS * 3):
                day += timedelta(days=1)
                regular = _regular(calendar, day)
                if regular is not None:
                    left -= 1
                    if left == 0:
                        due = _at(day, min(DAY_STOP_MINUTE, regular[2] - 30))
                        return {"due_at": due, "when": _clock_text(due, now)}
            return {"due_at": None, "reason": "No trading day was found that far ahead."}
        minutes = count if unit[0] == "m" else count * 60
        if minutes > 6 * 60 + 30:
            return {"due_at": None, "reason": "For longer than a session, give days (e.g. 2 days)."}
        regular = _regular(calendar, today)
        minute = datetime.fromtimestamp(now, ET)
        if regular is None or minute.hour * 60 + minute.minute >= regular[2]:
            return {"due_at": None, "reason": "A length in minutes or hours counts in today's session; give a clock time or days."}
        due = min(now + minutes * 60, _at(today, regular[2]))  # no later than today's close
        return {"due_at": due, "when": _clock_text(due, now)}
    if clock is None:
        return {"due_at": None, "reason": "No time or length in it, so it stays a note."}
    hour, minute, half = int(clock.group(1)), int(clock.group(2) or 0), (clock.group(3) or "").lower()
    if half:
        if not 1 <= hour <= 12:
            return {"due_at": None, "reason": "That is not a clock time."}
        hour = hour % 12 + (12 if half.startswith("p") else 0)
    elif 1 <= hour <= 8:
        hour += 12  # "3:30" during a trading day is the afternoon
    if hour > 23:
        return {"due_at": None, "reason": "That is not a clock time."}
    target = hour * 60 + minute
    day = today
    for _ in range(10):
        regular = _regular(calendar, day)
        if regular is not None:
            if not regular[1] < target <= regular[2]:
                return {"due_at": None, "reason": "That time is outside regular market hours, so it stays a note."}
            due = _at(day, target)
            if due > now:
                return {"due_at": due, "when": _clock_text(due, now)}
        day += timedelta(days=1)
    return {"due_at": None, "reason": "No trading day was found for that time."}


def create(db: Session, *, client_id: str, investigation_id: str, symbol: str, text: str, now: float, calendar=None) -> PlanTimeStop:
    """Save one plan's time stop; a repeated ``client_id`` returns the first. Raises ValueError for a note."""
    held = db.exec(select(PlanTimeStop).where(PlanTimeStop.client_id == client_id)).first()
    if held is not None:
        return held
    parsed = parse(text, now, calendar)
    if parsed["due_at"] is None:
        raise ValueError(parsed["reason"])
    row = PlanTimeStop(client_id=client_id, investigation_id=investigation_id, symbol=symbol, text=text.strip()[:80],
                       due_at=_utc(parsed["due_at"]), created_at=_utc(now))
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def message(row: PlanTimeStop) -> tuple[str, str, str]:
    """Title, body and the app path the notification opens."""
    hhmm = datetime.fromtimestamp(_epoch(row.due_at), ET).strftime("%H:%M")
    return f"{row.symbol} time stop", f"{row.symbol} time stop: you planned to be out by {hhmm}.", f"/trades/{row.trade_id}"


def _picture(db: Session, row: PlanTimeStop, title: str, now: float):
    """The ping's chart: the day so far with the stop time and the entry."""
    return ping_images.day_with_stop(title, row.symbol, _epoch(row.due_at), ping_images.entry_fills(db, row.trade_id), now)


def rows(db: Session, investigation_id: str) -> list[dict]:
    found = db.exec(select(PlanTimeStop).where(PlanTimeStop.investigation_id == investigation_id)
                    .order_by(PlanTimeStop.created_at)).all()
    return [{
        "id": str(r.id), "symbol": r.symbol, "text": r.text, "due_at": int(_epoch(r.due_at)), "delivery": r.delivery,
        "trade_id": str(r.trade_id) if r.trade_id else None, "error": r.last_error,
        "delivered_at": int(_epoch(r.delivered_at)) if r.delivered_at else None,
    } for r in found]


class PlanTimeStops:
    def __init__(self, engine, calendar=None, *, clock: Callable[[], float] = time.time):
        self.engine = engine
        self.calendar = calendar
        self.clock = clock

    def run(self) -> None:
        """Judge each time stop that has come due: ping about a position opened after the plan, or skip."""
        now = self.clock()
        with Session(self.engine) as db:
            due = db.exec(select(PlanTimeStop).where(PlanTimeStop.delivery == "scheduled", PlanTimeStop.due_at <= _utc(now))).all()
            for row in due:
                row.detected_at = _utc(now)
                if now - _epoch(row.due_at) > EXPIRE_SECONDS:
                    row.delivery, row.last_error = "expired", "Not judged within 15 minutes of its time, so it was not sent late."
                elif (trade_id := self._position(db, row)) is None:
                    row.delivery = "skipped"
                    row.last_error = f"No open {row.symbol} position opened after the plan, so nothing was sent."
                else:
                    row.delivery, row.trade_id = "pending", trade_id
                db.commit()
                log.info("Plan time stop %s for %s", row.delivery, row.symbol)

    def _position(self, db: Session, row: PlanTimeStop) -> uuid.UUID | None:
        """The newest open trade in the symbol whose first entry came after the plan (whole-minute fill times count
        the plan's own minute)."""
        trades = db.exec(select(Trade).join(Account, Account.id == Trade.account_id)
                         .where(Trade.status == "open", Trade.ticker == row.symbol,
                                or_(Account.broker.is_(None), Account.broker != "webull"))).all()
        planned = _epoch(row.created_at)
        best = None
        for trade in trades:
            first = db.exec(select(Fill.executed_at).join(TradeFill, TradeFill.fill_id == Fill.id)
                            .where(TradeFill.trade_id == trade.id, TradeFill.role == "entry").order_by(Fill.executed_at)).first()
            if first is not None and stamp(first) + 60 > planned and (best is None or first > best[0]):
                best = (first, trade.id)
        return best[1] if best else None

    # ------------------------------------------------------------ deliver

    def deliver(self) -> None:
        now = self.clock()
        with Session(self.engine) as db:
            # A claim this old may have reached ntfy before the pass died: never resent.
            db.exec(update(PlanTimeStop).where(PlanTimeStop.delivery == "sending", PlanTimeStop.claimed_at < _utc(now - CLAIM_SECONDS))
                    .values(delivery="unknown", last_error="The send was interrupted and may have reached the phone, so it was not resent."))
            db.commit()
            due = db.exec(select(PlanTimeStop.id).where(PlanTimeStop.delivery == "pending")
                          .where((PlanTimeStop.next_attempt_at.is_(None)) | (PlanTimeStop.next_attempt_at <= _utc(now)))
                          .order_by(PlanTimeStop.due_at).limit(20)).all()
        for row_id in due:
            self._send(row_id)

    def _send(self, row_id: uuid.UUID) -> None:
        now = self.clock()
        with Session(self.engine) as db:
            claimed = db.exec(update(PlanTimeStop).where(PlanTimeStop.id == row_id, PlanTimeStop.delivery == "pending")
                              .values(delivery="sending", claimed_at=_utc(now)))
            db.commit()
            if claimed.rowcount != 1:
                return  # another process or pass has it
            row = db.get(PlanTimeStop, row_id)
            if now - _epoch(row.due_at) > EXPIRE_SECONDS:
                row.delivery, row.last_error = "expired", "Not sent within 15 minutes of its time, so it was not sent late."
                db.commit()
                return
            if not ntfy.configured():
                row.delivery, row.next_attempt_at = "pending", _utc(now + BACKOFF[-1])
                row.last_error = "Phone alerts are not set up on this server (NTFY_URL is not set)."
                db.commit()
                return
            title, body, path = message(row)
            ticket = notification_policy.decide(
                db, sender="plan_time_stops", source_id=str(row.id), kind="time_stop", title=title, body=body, now=now,
                anchor=notification_policy.position_anchor(db, row.trade_id), symbol=row.symbol, trade_id=row.trade_id)
            if ticket.held:
                row.delivery, row.last_error = "held", ticket.reason
                db.commit()
                return
            image = ping_images.picture(ping_images.prepare(db, _picture, row, title, now)) if row.attempts == 0 else None  # a retry goes as text
            row.attempts += 1
            try:
                _, image_state = ping_images.publish(title, body + ticket.append, image, priority=4, tags=("hourglass",), path=path,
                                                     direct_click=True)
            except ntfy.NtfyError as exc:
                if not _surely_unsent(exc):
                    row.delivery, row.last_error = "unknown", f"{exc} It may have reached the phone, so it was not resent."
                    notification_policy.delivered(db, ticket, now)
                else:
                    row.delivery, row.last_error = "pending", str(exc)
                    row.next_attempt_at = _utc(now + BACKOFF[min(row.attempts, len(BACKOFF)) - 1])
                db.commit()
                log.warning("Plan time stop delivery failed (attempt %d): %s", row.attempts, exc)
                return
            row.delivery, row.delivered_at, row.last_error = "sent", _utc(self.clock()), None
            notification_policy.delivered(db, ticket, now)
            ping_images.record(db, ticket, image_state)
            db.commit()
