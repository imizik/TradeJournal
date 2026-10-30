"""Radar phone pings (``docs/radar.md`` § Phone alerts): two digests a session and, for a strong event, one
ping the minute the recorder writes it. Off unless ``RADAR_ALERTS_ENABLED=true``.

The end goal's first step is timely, factual alerts without waiting for AI analysis. Every new Radar event
gets one outbox row. A **strong** event (``strong``: a stock at least ``RADAR_SINGLE_MIN_RELATIVE_PCT``,
default 7.0, against SPY, or a group with every member moving the same way and a median at least
``RADAR_SINGLE_MIN_GROUP_PCT``, default 3.0) is a single ping (kind ``radar_event``): a title such as
``Radar: LAD +7.3% vs SPY +0.1%``, the feed's one-line summary and the time as the body, a tap that opens
the event on ``/radar`` (where its "Ask copilot" and "Plan a trade" buttons are), and two actions,
**Useful** and **Not useful**, which open the same event with that rating in the link; the page posts it
through the existing feedback route. ntfy shows at most three actions; the "Open app" one
``ntfy.publish`` adds is the third. At most one single a stock or group an hour; a strong event inside
that hour, and every other event, waits for the digest (``digest``, its body the event's digest line).

At each ``RADAR_DIGEST_AT`` time (default ``10:00,14:00`` New York) one **digest** ping (kind
``radar_digest``) lists every event waiting since the previous digest or the session's start, newest first,
one line each (``AAA up 5.2% vs SPY · 10:07 AM``), at most ``DIGEST_LINES`` with "+N more"; the tap opens
``/radar``. A digest whose time passed more than ``DIGEST_WINDOW_MINUTES`` ago is not written, and one with
nothing waiting is written ``skipped`` so its slot is used once. The digest is its own outbox row (kind
``digest``, ``event_id`` ``digest-<session>-<HHMM>``); when it is sent, held or dropped, its events take the
same delivery, so ``/radar/proof`` counts an event a digest reached as alerted. Events after the last
digest stay in the feed only, and are written ``skipped`` at the next session's first digest.

Only a new event pings; revisions (extended, faded, reversed) never do. The recorder calls ``record``
inside regular hours only, right after the pass that wrote the events, then ``deliver`` every pass.
Right before every send, the app's notification policy (``notification_policy.decide``) may hold it: the
budget of its kind (4 singles and 2 digests a day by default), the daily ceiling, or, for a single
(anchored to the stock's open position or the stock, or to the group), the quiet window after a ping for
the same position. A held ping is written ``held`` with the reason and never sent later; a held single
does not count toward the hourly rule, which counts one rule version's singles only. A dip-buy
candidate (``radar_dip``, kind ``dip_turn``, only with ``RADAR_DIP_RULES=alert``) is always a single ping: the owner
chose to be told the minute it turns, and the first-hour window would be over by the 10:00 digest. Rows live in the journal database (``RadarAlert``; the Radar file
stays append-only and alert-free). Delivery is the position alerts' at-most-once outbox: a send that may
have reached ntfy is ``unknown`` and never resent, and one not sent within ``EXPIRE_SECONDS`` is dropped
as late. ``sent`` proves ntfy accepted it, not that the phone showed it.
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
from sqlalchemy import or_, update
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.engine import notification_policy, ntfy, ping_images, radar_dip
from app.engine.chart_math import ET
from app.models import RadarAlert

log = logging.getLogger(__name__)

# The same outbox timings as position_alerts (not imported: that module reaches the Radar runner, which imports this one).
CLAIM_SECONDS = 120
BACKOFF = (30, 60, 120, 300)
EXPIRE_SECONDS = 15 * 60
SUBJECT_HOUR_SECONDS = 60 * 60
RATING_ACTIONS = (("Useful", "useful"), ("Not useful", "irrelevant"))
DIGEST = "digest"  # the RadarAlert.kind of a digest row, and the delivery of an event waiting for one
DIGEST_AT = (10 * 60, 14 * 60)
DIGEST_WINDOW_MINUTES = 15
DIGEST_LINES = 12
SINGLE_MIN_RELATIVE_PCT = 7.0
SINGLE_MIN_GROUP_PCT = 3.0
# Singles that count toward the hourly rule: waiting to be tried, or tried. A held or skipped single and an event that
# rode a digest were never tried (attempts 0).
SINGLE = (RadarAlert.kind != DIGEST) & or_(RadarAlert.delivery.in_(("pending", "sending")), RadarAlert.attempts > 0)


def enabled() -> bool:
    return os.environ.get("RADAR_ALERTS_ENABLED", "").lower() == "true"


def _number(name: str, default: float) -> float:
    try:
        return max(0.0, float(os.environ.get(name, "").strip()))
    except ValueError:
        return default


def digest_minutes() -> tuple[int, ...]:
    """``RADAR_DIGEST_AT`` as minutes after midnight New York, in order; unreadable entries are ignored."""
    found = set()
    for part in os.environ.get("RADAR_DIGEST_AT", "").split(","):
        try:
            hour, minute = (int(x) for x in part.strip().split(":"))
        except ValueError:
            continue
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            found.add(hour * 60 + minute)
    return tuple(sorted(found)) or DIGEST_AT


def strong(event: dict) -> bool:
    """Whether a Radar event is worth a ping of its own: a stock at least ``RADAR_SINGLE_MIN_RELATIVE_PCT`` against
    SPY (a sector event reads its SPY-relative move), or a group whose every member with data moved the same way with
    a median at least ``RADAR_SINGLE_MIN_GROUP_PCT`` against SPY."""
    m = event.get("measures") or {}
    if event.get("kind") == "group_move":
        members = m.get("members_with_data") or 0
        median = m.get("median_relative_pct")
        return (members > 0 and m.get("members_same_direction") == members and median is not None
                and abs(median) >= _number("RADAR_SINGLE_MIN_GROUP_PCT", SINGLE_MIN_GROUP_PCT))
    vs_spy = m.get("relative_pct") if event.get("kind") == "relative_to_spy" else m.get("spy_relative_pct")
    return vs_spy is not None and abs(vs_spy) >= _number("RADAR_SINGLE_MIN_RELATIVE_PCT", SINGLE_MIN_RELATIVE_PCT)


def subject(event: dict) -> str:
    """What the hourly cap is keyed on: the stock, or the group name."""
    return event["group"] if event["kind"] == "group_move" else event["symbols"][0]


def _parse(iso: str) -> float:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()


def _utc(stamp: float) -> datetime:
    return datetime.fromtimestamp(stamp, UTC).replace(tzinfo=None)


def _epoch(moment: datetime) -> float:
    return moment.replace(tzinfo=UTC).timestamp()


def _minute_of(stamp: float) -> int:
    moment = datetime.fromtimestamp(stamp, ET)
    return moment.hour * 60 + moment.minute


def _surely_unsent(exc: ntfy.NtfyError) -> bool:
    """True when the push certainly never reached ntfy: not configured, refused with a status, or no connection."""
    cause = exc.__cause__
    return cause is None or isinstance(cause, (httpx.ConnectError, httpx.ConnectTimeout))


def _signed(value: float) -> str:
    return f"{'+' if value > 0 else '−' if value < 0 else ''}{abs(value):.1f}%"


def _clock(stamp: float) -> str:
    moment = datetime.fromtimestamp(stamp, ET)
    return f"{(moment.hour - 1) % 12 + 1}:{moment.minute:02d} {'AM' if moment.hour < 12 else 'PM'} ET"


def _minute_label(minute: int) -> str:
    hour, rest = divmod(minute, 60)
    return f"{(hour - 1) % 12 + 1}:{rest:02d} {'AM' if hour < 12 else 'PM'}"


def message(event: dict) -> tuple[str, str]:
    """Title and body: the event's own numbers, then the feed's summary and the time it was first seen."""
    m = event["measures"]
    if event["kind"] == "dip_turn":
        title = (f"Radar dip: {event['symbols'][0]} turning up, {_signed(m['day_change_pct'])} "
                 f"(low {_signed(m['low_change_pct'])})")
    elif event["kind"] == "group_move":
        title = (f"Radar: {event['group']} {_signed(m['median_relative_pct'])} vs SPY "
                 f"({m['members_same_direction']} of {m['members_with_data']} {'up' if event['direction'] == 'up' else 'down'})")
    else:
        title = f"Radar: {event['symbols'][0]} {_signed(m['change_pct'])} vs {event['benchmark']} {_signed(m['benchmark_change_pct'])}"
    return title, f"{event['summary']} · {_clock(_parse(event['first_seen_at']))}"


def digest_line(event: dict) -> str:
    """One digest line: ``AAA up 5.2% vs SPY · 10:07 AM`` or ``Semis down 3.1% vs SPY (5 of 6) · 10:12 AM``."""
    m = event["measures"]
    way = "up" if event["direction"] == "up" else "down"
    when = _clock(_parse(event["first_seen_at"])).removesuffix(" ET")
    if event["kind"] == radar_dip.KIND:
        return f"{event['symbols'][0]} dip turning up, {_signed(m['day_change_pct'])} (low {_signed(m['low_change_pct'])}) · {when}"
    if event["kind"] == "group_move":
        return (f"{event['group']} {way} {abs(m['median_relative_pct']):.1f}% vs SPY "
                f"({m['members_same_direction']} of {m['members_with_data']}) · {when}")
    return f"{event['symbols'][0]} {way} {abs(m['relative_pct']):.1f}% vs {event['benchmark']} · {when}"


def digest_message(lines: list[str], since: str) -> tuple[str, str]:
    """The digest's title and body: the lines newest first (the caller's order), at most ``DIGEST_LINES``, then +N more."""
    title = f"Radar digest: {len(lines)} event{'' if len(lines) == 1 else 's'} since {since}"
    shown = lines[:DIGEST_LINES]
    more = len(lines) - len(shown)
    return title, "\n".join(shown + ([f"+{more} more"] if more else []))


def event_path(event_id: str, rating: str | None = None) -> str:
    """The event on /radar; with ``rating`` the page saves that rating through the feedback route, then shows the event."""
    return "/radar?" + urlencode({"event": event_id, **({"rate": rating} if rating else {})})


class RadarAlerts:
    def __init__(self, engine, *, clock: Callable[[], float] = time.time, store=None):
        self.engine = engine
        self.clock = clock
        self.store = store  # the Radar store, for the ping's picture (the event against its benchmark); None sends text

    # ------------------------------------------------------------ record

    def record(self, events: list[dict]) -> list[RadarAlert]:
        """One outbox row per new event: a strong one is a single ping, the rest wait for the digest (``digest``, the
        body its digest line). An event already written is left alone."""
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
                if event["kind"] != radar_dip.KIND and not strong(event):
                    alert.delivery, alert.body = DIGEST, digest_line(event)
                elif reason := self._hour_reason(db, alert, now):
                    alert.delivery, alert.body, alert.last_error = DIGEST, digest_line(event), reason
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

    def _hour_reason(self, db: Session, alert: RadarAlert, now: float) -> str | None:
        mine = RadarAlert.rule_version == alert.rule_version
        recent = db.exec(select(RadarAlert.detected_at).where(RadarAlert.subject == alert.subject, mine, SINGLE,
                                                              RadarAlert.detected_at > _utc(now - SUBJECT_HOUR_SECONDS))
                         .order_by(RadarAlert.detected_at.desc())).first()
        if recent is not None:
            return f"{alert.subject} was already alerted at {_clock(_epoch(recent))}; one an hour, so this one waits for the digest."
        return None

    # ------------------------------------------------------------ digest

    def digest(self) -> RadarAlert | None:
        """Write the digest whose time has come (within ``DIGEST_WINDOW_MINUTES``), once; None when none is due."""
        now = self.clock()
        moment = datetime.fromtimestamp(now, ET)
        minute = moment.hour * 60 + moment.minute
        times = digest_minutes()
        due = next((t for t in reversed(times) if t <= minute < t + DIGEST_WINDOW_MINUTES), None)
        if due is None:
            return None
        session = moment.date().isoformat()
        event_id = f"digest-{session}-{due // 60:02d}{due % 60:02d}"
        with Session(self.engine) as db:
            if db.exec(select(RadarAlert.id).where(RadarAlert.event_id == event_id)).first() is not None:
                return None
            # An event after the last digest of an earlier session was only ever in the feed.
            db.exec(update(RadarAlert).where(RadarAlert.delivery == DIGEST, RadarAlert.session_date < session)
                    .values(delivery="skipped", last_error="Seen after its session's last digest, so it was only in the feed."))
            waiting = db.exec(select(RadarAlert).where(RadarAlert.delivery == DIGEST, RadarAlert.session_date == session,
                                                       RadarAlert.detected_at <= _utc(now))
                              .order_by(RadarAlert.first_seen_at.desc(), RadarAlert.event_id)).all()
            earlier = [t for t in times if t < due]
            since = _minute_label(earlier[-1]) if earlier else "the open"
            title, body = digest_message([r.body for r in waiting], since)
            row = RadarAlert(event_id=event_id, session_date=session, rule_version="", kind=DIGEST, subject="Radar digest",
                             title=title, body=body, first_seen_at=_utc(now), detected_at=_utc(now))
            if not waiting:
                row.delivery, row.last_error = "skipped", f"Nothing new on Radar since {since}, so no digest was sent."
            db.add(row)
            try:
                db.commit()
            except IntegrityError:  # another process wrote this digest first
                db.rollback()
                return None
            db.refresh(row)
            db.expunge(row)
            log.info("Radar digest %s: %s", row.delivery, row.title)
            return row

    @staticmethod
    def _settle(db: Session, digest: RadarAlert) -> None:
        """The digest's events take its delivery: sent, unknown, held or expired."""
        if digest.kind != DIGEST:
            return
        when = _minute_label(_minute_of(_epoch(digest.detected_at)))
        error = None if digest.delivery == "sent" else f"In the {when} Radar digest: {digest.last_error}"
        db.exec(update(RadarAlert).where(RadarAlert.delivery == DIGEST, RadarAlert.session_date == digest.session_date,
                                         RadarAlert.kind != DIGEST, RadarAlert.detected_at <= digest.detected_at)
                .values(delivery=digest.delivery, delivered_at=digest.delivered_at, last_error=error))

    # ------------------------------------------------------------ deliver

    def deliver(self) -> None:
        now = self.clock()
        with Session(self.engine) as db:
            # A claim this old may have reached ntfy before the pass died: never resent.
            stale = (RadarAlert.delivery == "sending") & (RadarAlert.claimed_at < _utc(now - CLAIM_SECONDS))
            digests = db.exec(select(RadarAlert.id).where(stale, RadarAlert.kind == DIGEST)).all()
            db.exec(update(RadarAlert).where(stale)
                    .values(delivery="unknown", last_error="The send was interrupted and may have reached the phone, so it was not resent."))
            for digest_id in digests:
                self._settle(db, db.get(RadarAlert, digest_id))
            db.commit()
        self.digest()
        with Session(self.engine) as db:
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
                self._settle(db, alert)
                db.commit()
                return
            if not ntfy.configured():
                alert.delivery, alert.next_attempt_at = "pending", _utc(now + BACKOFF[-1])
                alert.last_error = "Phone alerts are not set up on this server (NTFY_URL is not set)."
                db.commit()
                return
            digest = alert.kind == DIGEST
            if digest:
                kind, anchor, symbol, trade_id = "radar_digest", None, None, None
            elif alert.kind == "group_move":
                kind, anchor, symbol, trade_id = "radar_event", f"group:{alert.subject}", None, None
            else:
                kind, symbol = "radar_event", alert.subject
                anchor, trade_id = notification_policy.symbol_anchor(db, symbol)
            ticket = notification_policy.decide(db, sender="radar_alerts", source_id=str(alert.id), kind=kind, title=alert.title,
                                                body=alert.body, now=now, anchor=anchor, symbol=symbol, trade_id=trade_id)
            if ticket.held:
                alert.delivery, alert.last_error = "held", ticket.reason
                self._settle(db, alert)
                db.commit()
                return
            image = ping_images.picture(ping_images.radar(alert.title, self.store, alert.event_id, alert.session_date, now)
                                        if self.store is not None and alert.attempts == 0 and not digest else None)  # a retry goes as text
            alert.attempts += 1
            try:
                if digest:
                    _, image_state = ping_images.publish(alert.title, alert.body + ticket.append, None, priority=3, tags=("satellite",),
                                                         path="/radar", direct_click=True)
                else:
                    _, image_state = ping_images.publish(
                        alert.title, alert.body + ticket.append, image, priority=4, tags=("satellite",), path=event_path(alert.event_id),
                        direct_click=True, more=tuple((label, event_path(alert.event_id, rating)) for label, rating in RATING_ACTIONS))
            except ntfy.NtfyError as exc:
                if not _surely_unsent(exc):
                    alert.delivery, alert.last_error = "unknown", f"{exc} It may have reached the phone, so it was not resent."
                    notification_policy.delivered(db, ticket, now)
                    self._settle(db, alert)
                else:
                    alert.delivery, alert.last_error = "pending", str(exc)
                    alert.next_attempt_at = _utc(now + BACKOFF[min(alert.attempts, len(BACKOFF)) - 1])
                db.commit()
                log.warning("Radar alert delivery failed (attempt %d): %s", alert.attempts, exc)
                return
            alert.delivery, alert.delivered_at, alert.last_error = "sent", _utc(self.clock()), None
            notification_policy.delivered(db, ticket, now)
            ping_images.record(db, ticket, image_state)
            self._settle(db, alert)
            db.commit()
