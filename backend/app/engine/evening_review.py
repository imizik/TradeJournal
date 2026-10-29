"""The evening review ping: once a trading day after the close, one phone ping saying what waits for review on the
Copilot desk, opening Close the day.

At ``EVENING_REVIEW_PING_AT`` New York (``16:30`` by default; a time before 16:00 or unreadable keeps the default) on a
trading day (the market calendar: no weekend or holiday ping) the desk's counts are read once through
``copilot_desk.waiting``, the same rules the desk shows: the symbols still asking their close question, the position
alerts waiting on an answer, the Radar hits not rated and the fills waiting to link. Nothing waiting, the lab off, or a
desk source that could not be read is recorded ``skipped`` with the reason and nothing is sent. Otherwise one ping, "To review: 2 threads, 3 alerts,
1 fill to link.", goes through ``notification_policy.decide`` (kind ``evening_review``, ranked with the prep, so the
daily cap holds it first) and opens ``/copilot-lab?close=1``, which starts the desk's Close the day pass.

Off unless ``EVENING_REVIEW_PING_ENABLED=true``. On the level alert monitor's loop. The unique ``EveningReview.day`` is
the once-a-day guard; a day not counted by ``WINDOW_MINUTES`` after its time waits for the next. Delivery is
at-most-once, as Watch your day's: a send that may have reached ntfy is ``unknown`` and never resent, and one not sent
within ``EXPIRE_SECONDS`` is dropped as ``expired``. No model call.
"""

from __future__ import annotations

from datetime import datetime
import logging
import os
import time
from typing import Callable
import uuid

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.engine import notification_policy, ntfy, ping_images
from app.engine.chart_math import ET
from app.engine.position_alerts import BACKOFF, CLAIM_SECONDS, _epoch, _surely_unsent, _utc
from app.engine.premarket_prep import _trading_day
from app.models import EveningReview

log = logging.getLogger(__name__)

RUN_SECONDS = 30
AT = 16 * 60 + 30
EARLIEST = 16 * 60  # the desk's close questions ask after 16:00
WINDOW_MINUTES = 120  # a day not counted by then (the flag switched on, or the API down) waits for the next
EXPIRE_SECONDS = 2 * 60 * 60
TITLE = "Close the day"
PATH = "/copilot-lab?close=1"


def enabled() -> bool:
    return os.environ.get("EVENING_REVIEW_PING_ENABLED", "").strip().lower() == "true"


def at_minute() -> int:
    """``EVENING_REVIEW_PING_AT`` as minutes after midnight New York; the default when unset, unreadable or before 16:00."""
    raw = os.environ.get("EVENING_REVIEW_PING_AT", "").strip()
    try:
        hour, minute = (int(part) for part in raw.split(":"))
    except ValueError:
        return AT
    if not (0 <= hour <= 23 and 0 <= minute <= 59) or hour * 60 + minute < EARLIEST:
        return AT
    return hour * 60 + minute


def _part(count: int, one: str, many: str) -> str | None:
    return f"{count} {one if count == 1 else many}" if count else None


def message(counts: dict) -> str | None:
    """"To review: 2 threads, 3 alerts, 1 Radar hit, 1 fill to link." or None when nothing waits."""
    parts = [p for p in (_part(counts["review"], "thread", "threads"), _part(counts["alerts"], "alert", "alerts"),
                         _part(counts["radar"], "Radar hit", "Radar hits"), _part(counts["fills"], "fill to link", "fills to link")) if p]
    return f"To review: {', '.join(parts)}." if parts else None


def count(db: Session, now: float) -> dict | None:
    """The desk's counts, or None while the Copilot Lab is off (the desk the ping opens is not there)."""
    from app.ai import copilot
    from app.routers import copilot_desk
    if not copilot.settings().enabled:
        return None
    return copilot_desk.waiting(db, now)


class EveningReviews:
    def __init__(self, engine, calendar=None, *, clock: Callable[[], float] = time.time,
                 counts: Callable[[Session, float], dict | None] = count):
        self.engine = engine
        self.calendar = calendar
        self.clock = clock
        self.counts = counts
        self._last_run = 0.0

    def run(self) -> None:
        """Count the day once its time has come, and queue the ping when something waits."""
        now = self.clock()
        if now - self._last_run < RUN_SECONDS:
            return
        self._last_run = now
        if not enabled():
            return
        moment = datetime.fromtimestamp(now, ET)
        start = at_minute()
        if not start <= moment.hour * 60 + moment.minute < start + WINDOW_MINUTES or not _trading_day(self.calendar, moment.date()):
            return
        with Session(self.engine) as db:
            if db.exec(select(EveningReview.id).where(EveningReview.day == moment.date())).first():
                return
            row = EveningReview(day=moment.date(), detected_at=_utc(now))
            try:
                counts = self.counts(db, now)
            except Exception as exc:  # noqa: BLE001 - recorded once; the alert loop goes on
                log.exception("Evening review counts failed")
                db.rollback()
                row.delivery, row.last_error = "skipped", f"The desk's counts could not be read ({type(exc).__name__}), so nothing was sent."
                counts = {}
            if counts is None:
                row.delivery, row.last_error = "skipped", "The Copilot Lab is off, so there is no desk to open."
            elif counts:
                row.review, row.alerts, row.radar, row.fills = counts["review"], counts["alerts"], counts["radar"], counts["fills"]
                row.body = message(counts)
                if row.body is None:
                    row.delivery, row.last_error = "skipped", "Nothing was waiting for review, so nothing was sent."
            db.add(row)
            try:
                db.commit()
            except IntegrityError:
                db.rollback()  # another process counted the day a moment earlier
                return
            log.info("Evening review for %s: %s", row.day, row.delivery if row.body is None else row.body)
        self.deliver()

    def deliver(self) -> None:
        now = self.clock()
        with Session(self.engine) as db:
            # A claim this old may have reached ntfy before the pass died: never resent.
            db.exec(update(EveningReview).where(EveningReview.delivery == "sending", EveningReview.claimed_at < _utc(now - CLAIM_SECONDS))
                    .values(delivery="unknown", last_error="The send was interrupted and may have reached the phone, so it was not resent."))
            db.commit()
            due = db.exec(select(EveningReview.id).where(EveningReview.delivery == "pending")
                          .where((EveningReview.next_attempt_at.is_(None)) | (EveningReview.next_attempt_at <= _utc(now)))
                          .order_by(EveningReview.detected_at).limit(5)).all()
        for row_id in due:
            self._send(row_id)

    def _send(self, row_id: uuid.UUID) -> None:
        now = self.clock()
        with Session(self.engine) as db:
            claimed = db.exec(update(EveningReview).where(EveningReview.id == row_id, EveningReview.delivery == "pending")
                              .values(delivery="sending", claimed_at=_utc(now)))
            db.commit()
            if claimed.rowcount != 1:
                return  # another process or pass has it
            row = db.get(EveningReview, row_id)
            if now - _epoch(row.detected_at) > EXPIRE_SECONDS:
                row.delivery, row.last_error = "expired", "Not sent within 2 hours of its time, so it was not sent late."
                db.commit()
                return
            if not ntfy.configured():
                row.delivery, row.next_attempt_at = "pending", _utc(now + BACKOFF[-1])
                row.last_error = "Phone alerts are not set up on this server (NTFY_URL is not set)."
                db.commit()
                return
            body = row.body or ""
            ticket = notification_policy.decide(db, sender="evening_review", source_id=str(row.id), kind="evening_review",
                                                title=TITLE, body=body, now=now)
            if ticket.held:
                row.delivery, row.last_error = "held", ticket.reason
                db.commit()
                return
            row.attempts += 1
            try:
                _, state = ping_images.publish(TITLE, body + ticket.append, None, priority=3, tags=("memo",), path=PATH,
                                               direct_click=True)
            except ntfy.NtfyError as exc:
                if not _surely_unsent(exc):
                    row.delivery, row.last_error = "unknown", f"{exc} It may have reached the phone, so it was not resent."
                    notification_policy.delivered(db, ticket, now)
                else:
                    row.delivery, row.last_error = "pending", str(exc)
                    row.next_attempt_at = _utc(now + BACKOFF[min(row.attempts, len(BACKOFF)) - 1])
                db.commit()
                log.warning("Evening review delivery failed (attempt %d): %s", row.attempts, exc)
                return
            row.delivery, row.delivered_at, row.last_error = "sent", _utc(self.clock()), None
            notification_policy.delivered(db, ticket, now)
            ping_images.record(db, ticket, state)
            db.commit()
