"""Radar phone pings (``docs/radar.md`` § Phone alerts): one ntfy notification when the recorder writes a
new Radar event. Off unless ``RADAR_ALERTS_ENABLED=true``.

The end goal's first step is timely, factual alerts without waiting for AI analysis. This sends the
event's own read the minute the rules save it: a title such as ``Radar: LAD +5.3% vs SPY +0.1%``, the
feed's one-line summary and the time as the body, a tap that opens the event on ``/radar`` (where its
"Ask copilot" and "Plan a trade" buttons are), and two actions, **Useful** and **Not useful**, which open
the same event with that rating in the link; the page posts it through the existing feedback route, so
the tap is the rating and there is no new server route or one-tap token. ntfy shows at most three
actions; the "Open app" one ``ntfy.publish`` adds is the third.

Only a new event pings; revisions (extended, faded, reversed) never do. The recorder calls ``record``
inside regular hours only, right after the pass that wrote the events, then ``deliver`` every pass. Caps:
at most ``RADAR_ALERTS_DAILY_CAP`` (default 8) a session and one per stock or group an hour; an event
past a cap is written ``skipped`` with the reason and never sent later. Rows live in the journal
database (``RadarAlert``; the Radar file stays append-only and alert-free) so ``/radar/proof`` can count
alerted events apart from events merely seen in the feed. Delivery is the position alerts' at-most-once
outbox: a send that may have reached ntfy is ``unknown`` and never resent, and an alert not sent within
``EXPIRE_SECONDS`` is dropped as late. ``sent`` proves ntfy accepted it, not that the phone showed it.
"""
from __future__ import annotations

from datetime import UTC, datetime
import logging
import os
import time
from typing import Callable
from urllib.parse import urlencode
import uuid

import httpx
from sqlalchemy import func, update
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.engine import ntfy
from app.engine.chart_math import ET
from app.models import RadarAlert

log = logging.getLogger(__name__)

# The same outbox timings as position_alerts (not imported: that module reaches the Radar runner, which imports this one).
CLAIM_SECONDS = 120
BACKOFF = (30, 60, 120, 300)
EXPIRE_SECONDS = 15 * 60
SUBJECT_HOUR_SECONDS = 60 * 60
DEFAULT_DAILY_CAP = 8
RATING_ACTIONS = (("Useful", "useful"), ("Not useful", "irrelevant"))
COUNTED = RadarAlert.delivery != "skipped"  # rows that count toward the caps


def enabled() -> bool:
    return os.environ.get("RADAR_ALERTS_ENABLED", "").lower() == "true"


def daily_cap() -> int:
    try:
        return max(0, int(os.environ.get("RADAR_ALERTS_DAILY_CAP", "").strip()))
    except ValueError:
        return DEFAULT_DAILY_CAP


def subject(event: dict) -> str:
    """What the hourly cap is keyed on: the stock, or the group name."""
    return event["group"] if event["kind"] == "group_move" else event["symbols"][0]


def _parse(iso: str) -> float:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()


def _utc(stamp: float) -> datetime:
    return datetime.fromtimestamp(stamp, UTC).replace(tzinfo=None)


def _epoch(moment: datetime) -> float:
    return moment.replace(tzinfo=UTC).timestamp()


def _surely_unsent(exc: ntfy.NtfyError) -> bool:
    """True when the push certainly never reached ntfy: not configured, refused with a status, or no connection."""
    cause = exc.__cause__
    return cause is None or isinstance(cause, (httpx.ConnectError, httpx.ConnectTimeout))


def _signed(value: float) -> str:
    return f"{'+' if value > 0 else '−' if value < 0 else ''}{abs(value):.1f}%"


def _clock(stamp: float) -> str:
    moment = datetime.fromtimestamp(stamp, ET)
    return f"{(moment.hour - 1) % 12 + 1}:{moment.minute:02d} {'AM' if moment.hour < 12 else 'PM'} ET"


def message(event: dict) -> tuple[str, str]:
    """Title and body: the event's own numbers, then the feed's summary and the time it was first seen."""
    m = event["measures"]
    if event["kind"] == "group_move":
        title = (f"Radar: {event['group']} {_signed(m['median_relative_pct'])} vs SPY "
                 f"({m['members_same_direction']} of {m['members_with_data']} {'up' if event['direction'] == 'up' else 'down'})")
    else:
        title = f"Radar: {event['symbols'][0]} {_signed(m['change_pct'])} vs {event['benchmark']} {_signed(m['benchmark_change_pct'])}"
    return title, f"{event['summary']} · {_clock(_parse(event['first_seen_at']))}"


def event_path(event_id: str, rating: str | None = None) -> str:
    """The event on /radar; with ``rating`` the page saves that rating through the feedback route, then shows the event."""
    return "/radar?" + urlencode({"event": event_id, **({"rate": rating} if rating else {})})


class RadarAlerts:
    def __init__(self, engine, *, clock: Callable[[], float] = time.time):
        self.engine = engine
        self.clock = clock

    # ------------------------------------------------------------ record

    def record(self, events: list[dict]) -> list[RadarAlert]:
        """One outbox row per new event; a capped one is written ``skipped``. An event already written is left alone."""
        now = self.clock()
        written = []
        with Session(self.engine) as db:
            for event in events:
                if db.exec(select(RadarAlert.id).where(RadarAlert.event_id == event["event_id"])).first() is not None:
                    continue
                title, body = message(event)
                alert = RadarAlert(event_id=event["event_id"], session_date=event["session_date"], rule_version=event["rule_version"],
                                   kind=event["kind"], subject=subject(event), title=title, body=body,
                                   first_seen_at=_utc(_parse(event["first_seen_at"])), detected_at=_utc(now))
                reason = self._cap_reason(db, alert, now)
                if reason:
                    alert.delivery, alert.last_error = "skipped", reason
                db.add(alert)
                try:
                    db.commit()
                except IntegrityError:  # another process wrote this event's row first
                    db.rollback()
                    continue
                db.refresh(alert)
                db.expunge(alert)  # a later commit in this loop would expire it; callers read it after the session closes
                written.append(alert)
                log.info("Radar alert %s for %s: %s", alert.delivery, alert.subject, alert.title)
        return written

    def _cap_reason(self, db: Session, alert: RadarAlert, now: float) -> str | None:
        cap = daily_cap()
        today = db.exec(select(func.count()).select_from(RadarAlert)
                        .where(RadarAlert.session_date == alert.session_date, COUNTED)).one()
        if today >= cap:
            return f"Daily cap of {cap} Radar alerts reached, so this one was not sent."
        recent = db.exec(select(RadarAlert.detected_at).where(RadarAlert.subject == alert.subject, COUNTED,
                                                              RadarAlert.detected_at > _utc(now - SUBJECT_HOUR_SECONDS))
                         .order_by(RadarAlert.detected_at.desc())).first()
        if recent is not None:
            return f"{alert.subject} was already alerted at {_clock(_epoch(recent))}; one an hour, so this one was not sent."
        return None

    # ------------------------------------------------------------ deliver

    def deliver(self) -> None:
        now = self.clock()
        with Session(self.engine) as db:
            # A claim this old may have reached ntfy before the pass died: never resent.
            db.exec(update(RadarAlert).where(RadarAlert.delivery == "sending", RadarAlert.claimed_at < _utc(now - CLAIM_SECONDS))
                    .values(delivery="unknown", last_error="The send was interrupted and may have reached the phone, so it was not resent."))
            db.commit()
            due = db.exec(select(RadarAlert.id).where(RadarAlert.delivery == "pending")
                          .where((RadarAlert.next_attempt_at.is_(None)) | (RadarAlert.next_attempt_at <= _utc(now)))
                          .order_by(RadarAlert.detected_at).limit(20)).all()
        for alert_id in due:
            self._send(alert_id)

    def _send(self, alert_id: uuid.UUID) -> None:
        now = self.clock()
        with Session(self.engine) as db:
            claimed = db.exec(update(RadarAlert).where(RadarAlert.id == alert_id, RadarAlert.delivery == "pending")
                              .values(delivery="sending", claimed_at=_utc(now)))
            db.commit()
            if claimed.rowcount != 1:
                return  # another process or pass has it
            alert = db.get(RadarAlert, alert_id)
            if now - _epoch(alert.detected_at) > EXPIRE_SECONDS:
                alert.delivery, alert.last_error = "expired", "Not sent within 15 minutes, so it was not sent late."
                db.commit()
                return
            if not ntfy.configured():
                alert.delivery, alert.next_attempt_at = "pending", _utc(now + BACKOFF[-1])
                alert.last_error = "Phone alerts are not set up on this server (NTFY_URL is not set)."
                db.commit()
                return
            alert.attempts += 1
            try:
                ntfy.publish(alert.title, alert.body, priority=4, tags=("satellite",), path=event_path(alert.event_id), direct_click=True,
                             more=tuple((label, event_path(alert.event_id, rating)) for label, rating in RATING_ACTIONS))
            except ntfy.NtfyError as exc:
                if not _surely_unsent(exc):
                    alert.delivery, alert.last_error = "unknown", f"{exc} It may have reached the phone, so it was not resent."
                else:
                    alert.delivery, alert.last_error = "pending", str(exc)
                    alert.next_attempt_at = _utc(now + BACKOFF[min(alert.attempts, len(BACKOFF)) - 1])
                db.commit()
                log.warning("Radar alert delivery failed (attempt %d): %s", alert.attempts, exc)
                return
            alert.delivery, alert.delivered_at, alert.last_error = "sent", _utc(self.clock()), None
            db.commit()
