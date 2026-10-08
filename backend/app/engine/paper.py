"""Practice paper plans (A2): arming a frozen TAKE, watching it, and its phone messages.

The rules live in ``paper_execution`` (pure); this module stores what they decide.
Every economic fact is a ``DecisionEvent`` row written once under a unique
(record, key); the position is always ``paper_execution.fold`` of those rows, so a
restart rebuilds it from the database and never from memory.

Arming checks a TAKE against the complete ``shadow-isaac-p0-v1`` policy
(``docs/agent/practice-policy.md``) and stores that policy's hash on the
``armed`` event. Watching reads Tradier's consolidated one-minute bars through
the chart feed's shared, cached read, inside the level alert monitor's loop.
Paper events never touch fills, trades, accounts or the strategy factory.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, text, update
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.engine import decisions, ntfy
from app.engine import paper_execution as px
from app.engine.chart_feed import ChartFeedError
from app.engine.chart_math import ET, chart_bars, normalize_bars, session_windows
from app.engine.level_alerts import LATENESS
from app.models import DecisionEvent, DecisionRecord

log = logging.getLogger(__name__)

SOURCE = "tradier_timesales_1min"
UNIVERSE = ("SPY", "QQQ", "IWM", "AAPL", "MSFT")
MAX_TAKES_PER_SESSION = 3
COST = {"version": "p0-cost-v1", "slippage_bps": 1.0, "slippage_per_share": 0.01}
FRESHNESS_SECONDS = 86_400
WATCH_END = (15 * 60 + 15, 45)  # 15:15 New York, or this many minutes before an early close, if earlier
ON_TIME_BY = 9 * 60  # decisions received by 09:00 New York join that day's on-time cohort
POLICY_VERSION = "shadow-isaac-p0-v1"
POLICY_SPEC = {
    "version": POLICY_VERSION,
    "plan_schema": {"version": decisions.POLICY_VERSION, "hash": decisions.POLICY_HASH},
    "universe": list(UNIVERSE), "max_takes_per_session": MAX_TAKES_PER_SESSION, "plans_per_symbol": 1,
    "on_time_by_minute": ON_TIME_BY, "watch_end": {"latest_minute": WATCH_END[0], "before_close_minutes": WATCH_END[1]},
    "freshness_limit_seconds": FRESHNESS_SECONDS, "cost": COST, "cost_stress_factor": 3,
    "execution": {"version": px.EXEC_VERSION, "max_detection_delay_seconds": px.MAX_DETECTION_DELAY,
                  "bar_lateness_seconds": LATENESS, "source": SOURCE},
}
POLICY_HASH = hashlib.sha256(json.dumps(POLICY_SPEC, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

# Events worth a phone message. An untriggered expiry is not: it would interrupt for nothing.
NOTIFY = {"trigger", "missed_trigger", "entry", "entry_rejected", "exit", "unresolved"}
CLAIM_SECONDS = 120
EXPIRE_SECONDS = 6 * 3600
BACKOFF = (30, 60, 120, 300, 900)
LATE_SECONDS = 120  # a message about an event older than this says how late it is


class PaperError(ValueError):
    pass


def _naive(moment: datetime) -> datetime:
    return moment.astimezone(UTC).replace(tzinfo=None) if moment.tzinfo else moment


def _epoch(moment: datetime) -> float:
    return moment.replace(tzinfo=UTC).timestamp()


def _utc(stamp: float) -> datetime:
    return datetime.fromtimestamp(stamp, UTC).replace(tzinfo=None)


# ------------------------------------------------------------------ sessions


def regular_session(day: date, hours: dict | None) -> px.Session | None:
    """A verified open day's regular session; None for a closed day or an unavailable calendar."""
    if hours is None or hours.get("status") != "open":
        return None
    regular = next((w for w in session_windows(day, hours) if w[0] == "regular"), None)
    if regular is None:
        return None
    edge = [int(datetime(day.year, day.month, day.day, m // 60, m % 60, tzinfo=ET).timestamp()) for m in regular[1:]]
    return px.Session(day.isoformat(), edge[0], edge[1])


def watch_cutoff(session: px.Session) -> int:
    """The last 15-minute close the policy watches: 15:15, or 45 minutes before an early close."""
    day = date.fromisoformat(session.day)
    latest = int(datetime(day.year, day.month, day.day, WATCH_END[0] // 60, WATCH_END[0] % 60, tzinfo=ET).timestamp())
    return min(latest, session.close_at - WATCH_END[1] * 60)


def sessions_from(calendar, first: date, today: date, ahead: int = 7) -> list[px.Session]:
    """Regular sessions from ``first`` through a week past ``today``, as far as the calendar publishes them."""
    found, day = [], first
    while day <= today + timedelta(days=ahead):
        hours = calendar.hours(day)
        if hours is None and day > today:
            break  # the calendar has not published further; the reducer waits for it
        session = regular_session(day, hours)
        if session is not None:
            found.append(session)
        day += timedelta(days=1)
    return found


# ------------------------------------------------------------------ events


def events_for(db: Session, record_id: uuid.UUID) -> list[DecisionEvent]:
    return list(db.exec(select(DecisionEvent).where(DecisionEvent.record_id == record_id).order_by(DecisionEvent.seq)).all())


def _data(rows: list[DecisionEvent]) -> list[dict]:
    return [json.loads(row.data_json) for row in rows]


def append(db: Session, record_id: uuid.UUID, events: list[dict], *, now: float, reconstructed_before: float | None = None) -> bool:
    """Store new reducer events in order, all or none. False when another writer stored them first."""
    if not events:
        return True
    seq = db.exec(select(func.max(DecisionEvent.seq)).where(DecisionEvent.record_id == record_id)).one() or 0
    for event in events:
        seq += 1
        late = reconstructed_before is not None and event["at"] < reconstructed_before
        if late:
            event = {**event, "reconstructed": True}
        db.add(DecisionEvent(
            record_id=record_id, seq=seq, key=event["key"], event_type=event["type"], effective_at=_utc(event["at"]),
            recorded_at=_utc(now), exec_version=px.EXEC_VERSION, source=SOURCE,
            reconstructed=bool(event.get("reconstructed")), data_json=decisions._canonical(event),
            delivery="pending" if event["type"] in NOTIFY else "none"))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return False
    return True


def _armed_rows(db: Session) -> list[DecisionEvent]:
    return list(db.exec(select(DecisionEvent).where(DecisionEvent.event_type == "armed")).all())


def state_of(db: Session, record_id: uuid.UUID) -> px.Paper:
    return px.fold(_data(events_for(db, record_id)))


# ------------------------------------------------------------------ arming


def arm(db: Session, record_id: uuid.UUID, operation_id: str, *, now: datetime, calendar) -> tuple[list[DecisionEvent], bool]:
    """Arm one frozen TAKE under the complete P0 policy. Returns its events and whether this call armed it.

    The same ``operation_id`` again returns the original arming; another one is refused. Every refusal
    names the policy rule; nothing is stored unless every rule passes.
    """
    # Caps cover different records, so per-record uniqueness cannot enforce
    # them. Serialize the eligibility read and armed-event commit together.
    if db.get_bind().dialect.name == "postgresql":
        db.exec(text("SELECT pg_advisory_xact_lock(72431002)"))
    elif db.get_bind().dialect.name == "sqlite":
        db.exec(text("BEGIN IMMEDIATE"))
    now = _naive(now)
    record = db.get(DecisionRecord, record_id)
    if record is None:
        raise LookupError("Decision record not found")
    existing = events_for(db, record.id)
    if existing:
        armed = json.loads(existing[0].data_json)
        if armed.get("operation_id") == operation_id:
            return existing, False
        raise PaperError("this plan is already armed under another operation_id")
    if record.opportunity_id.startswith("a3:"):
        paired_arm = db.exec(select(DecisionEvent.id).join(DecisionRecord, DecisionEvent.record_id == DecisionRecord.id).where(
            DecisionRecord.opportunity_id == record.opportunity_id, DecisionRecord.id != record.id,
            DecisionEvent.event_type == "armed")).first()
        if paired_arm is not None:
            raise PaperError("this shared opportunity was already armed through another actor; paired choices cannot create another paper plan")
    plan = json.loads(record.decision_json)["plan"]
    if record.decision != "take":
        raise PaperError("only a TAKE plan can be armed")
    if (record.policy_version, record.policy_hash) != (decisions.POLICY_VERSION, decisions.POLICY_HASH):
        raise PaperError("the plan was saved under a different plan schema and must be decided again")
    if record.symbol not in UNIVERSE:
        raise PaperError(f"{record.symbol} is outside the P0 universe ({', '.join(UNIVERSE)})")
    costs = plan.get("cost_model") or {}
    if {k: costs.get(k) for k in COST} != COST or plan.get("freshness_limit_seconds") != FRESHNESS_SECONDS:
        raise PaperError("P0 requires cost model p0-cost-v1 (1 bp + $0.01) and a 86400-second freshness limit")
    terms = px.terms_from_plan(plan)
    moment = now.replace(tzinfo=UTC).astimezone(ET)
    today = moment.date()
    session = regular_session(today, calendar.hours(today))
    if session is None:
        raise PaperError("the market calendar does not show an open session today, so nothing can be armed")
    if record.received_at.replace(tzinfo=UTC).astimezone(ET).date() != today:
        raise PaperError("only a plan decided today can be armed today")
    cutoff = watch_cutoff(session)
    if terms.expiry > cutoff:
        raise PaperError("plan expiry is later than the P0 watch cutoff (15:15, or 45 minutes before an early close)")
    if terms.expiry <= _epoch(now):
        raise PaperError("plan expiry has passed")
    armed_today, open_symbols = 0, set()
    for row in _armed_rows(db):
        other = db.get(DecisionRecord, row.record_id)
        if row.effective_at.replace(tzinfo=UTC).astimezone(ET).date() == today:
            armed_today += 1
        if state_of(db, row.record_id).status not in px.TERMINAL:
            open_symbols.add(other.symbol)
    if armed_today >= MAX_TAKES_PER_SESSION:
        raise PaperError(f"P0 arms at most {MAX_TAKES_PER_SESSION} plans per session")
    if record.symbol in open_symbols:
        raise PaperError(f"another {record.symbol} plan is still active; P0 allows one per symbol")
    received = record.received_at.replace(tzinfo=UTC).astimezone(ET)
    event = {**px.arm_event(_epoch(now)), "operation_id": operation_id, "policy_version": POLICY_VERSION,
             "policy_hash": POLICY_HASH, "session_day": today.isoformat(), "watch_cutoff": cutoff,
             "on_time": received.hour * 60 + received.minute < ON_TIME_BY}
    if not append(db, record.id, [event], now=_epoch(now)):
        return arm(db, record_id, operation_id, now=now, calendar=calendar)  # a concurrent arm won; report it
    return events_for(db, record.id), True


# ------------------------------------------------------------------ watching


class PaperWatcher:
    """One pass over every active plan, run inside the level alert monitor's loop."""

    def __init__(self, engine, feed, calendar, splits=None, clock=None):
        self.engine, self.feed, self.calendar, self.splits = engine, feed, calendar, splits
        self.clock = clock

    def active(self) -> list[tuple[DecisionRecord, px.Terms, px.Paper]]:
        with Session(self.engine) as db:
            result = []
            for row in _armed_rows(db):
                policy = json.loads(row.data_json)
                if (policy.get("policy_version"), policy.get("policy_hash"), row.exec_version) != (POLICY_VERSION, POLICY_HASH, px.EXEC_VERSION):
                    log.error("Paper plan %s paused: saved policy/execution differs from this watcher", row.record_id)
                    continue
                state = state_of(db, row.record_id)
                if state.status in px.TERMINAL:
                    continue
                record = db.get(DecisionRecord, row.record_id)
                result.append((record, px.terms_from_plan(json.loads(record.decision_json)["plan"]), state))
            return result

    def run(self) -> None:
        for record, terms, state in self.active():
            try:
                self._judge(record, terms, state)
            except (ChartFeedError, ValueError) as exc:
                log.warning("Paper plan %s not judged this pass: %s", record.id, exc)
            except Exception:  # one plan's failure must not stop the others
                log.exception("Paper plan %s failed this pass", record.id)

    def _judge(self, record: DecisionRecord, terms: px.Terms, state: px.Paper) -> None:
        now = self.clock()
        today = datetime.fromtimestamp(now, ET).date()
        first = datetime.fromtimestamp(state.armed_at, ET).date()
        if state.status == "armed":
            past_expiry = now > terms.expiry + px.MAX_DETECTION_DELAY
            session = regular_session(today, self.calendar.hours(today))
            in_session = session is not None and session.open_at < now <= session.close_at + LATENESS + 120
            if not (in_session or past_expiry):
                return  # nothing can have closed since the last pass
            # The trigger is judged before expiry, so a restart past the expiry still finds a missed trigger.
            minutes = self._minutes(record.symbol, first, today)
            detected = self.clock()  # after the read: the bars cannot be newer than this
            events = px.watch(state, terms, self._bars15(minutes, detected, state.armed_at, terms), detected)
            if not events:
                events = px.check_expiry(state, terms, detected)
            if not events:
                return
            self._store(record, events)
            state = px.fold(self._history(record.id))
            if state.status != "triggered":
                return
        if state.status not in ("triggered", "open"):
            return
        if state.status == "triggered" and state.order_intent is None:
            # This clock sample happens after the trigger commit returned.
            # recorded_at on that trigger was sampled before commit and cannot
            # prove that the next minute began after durable detection.
            intent_at = self.clock()
            if intent_at - state.trigger["detected_at"] > px.MAX_DETECTION_DELAY:
                return self._store(record, px.end_unresolved(state, intent_at, "monitoring gap before durable entry intent"))
            self._store(record, [{"type": "order_intent", "key": "order_intent", "at": intent_at,
                                  "eligible_at": (int(intent_at) // 60 + 1) * 60}])
            state = px.fold(self._history(record.id))
            if state.status != "triggered" or state.order_intent is None:
                return
        split = self._split_since(record.symbol, first, today)
        if split is None:
            return  # the split source is unavailable: wait rather than judge across a possible split
        if split:
            return self._store(record, px.end_unresolved(state, now, "split"))
        session = regular_session(today, self.calendar.hours(today))
        if session is None:
            return
        # Completed bars remain recoverable after the close. Restrict the bars,
        # not the wall clock: a restart must recover a final-minute time exit.
        minutes = self._minutes(record.symbol, first, today)
        seen = self.clock()
        bars = [{"start": b["time"], "o": b["open"], "h": b["high"], "l": b["low"], "c": b["close"]}
                for b in minutes if b["end_time"] + LATENESS <= seen]
        events = px.advance(state, terms, bars, sessions_from(self.calendar, first, today))
        self._store(record, events, reconstructed_before=seen - px.MAX_DETECTION_DELAY - 60)

    def _bars15(self, minutes: list[dict], now: float, armed_at: float, terms: px.Terms) -> list[dict]:
        day = datetime.fromtimestamp(armed_at, ET).date()
        last = datetime.fromtimestamp(min(now, terms.expiry), ET).date()
        hours, sessions = {}, []
        while day <= last:
            hours[day] = self.calendar.hours(day)
            if hours[day] is None:
                raise ChartFeedError("market calendar unavailable; trigger coverage cannot be verified")
            session = regular_session(day, hours[day])
            if session is not None:
                sessions.append(session)
            day += timedelta(days=1)
        relevant = [b for b in minutes if datetime.fromtimestamp(b["time"], ET).date() in hours]
        candles = {b["end_time"]: b for b in chart_bars(relevant, [], "15m", "regular", hours)}
        starts = {b["time"] for b in minutes}
        completed = []
        for session in sessions:
            for start in range(session.open_at, session.close_at, 15 * 60):
                end = min(start + 15 * 60, session.close_at)
                if end <= armed_at or end > terms.expiry or end + LATENESS > now:
                    continue
                if end not in candles or any(t not in starts for t in range(start, end, 60)):
                    raise ChartFeedError("one-minute trigger coverage is incomplete; plan evaluation paused")
                completed.append({"start": start, "end": end, "close": candles[end]["close"]})
                # The first crossing decides the plan. Later gaps must not
                # suppress an already observable trigger or missed trigger.
                if candles[end]["close"] > terms.trigger:
                    return completed
        return completed

    def _history(self, record_id: uuid.UUID) -> list[dict]:
        with Session(self.engine) as db:
            return _data(events_for(db, record_id))

    def _store(self, record: DecisionRecord, events: list[dict], **kwargs) -> None:
        with Session(self.engine) as db:
            if not append(db, record.id, events, now=self.clock(), **kwargs):
                log.info("Paper events for %s were already stored by another pass", record.id)

    def _minutes(self, symbol: str, first: date, today: date) -> list[dict]:
        data, _, issue = self.feed.read("/v1/markets/timesales", {
            "symbol": symbol, "interval": "1min", "session_filter": "all",
            "start": first.strftime("%Y-%m-%d 04:00"), "end": today.strftime("%Y-%m-%d 20:00"),
        }, 15)
        if issue:
            # A stale or partial answer (an outage served from cache) is never judged as final bars.
            raise ChartFeedError(f"minute bars not current: {issue}")
        series = (data or {}).get("series") or {}
        rows = series.get("data") if isinstance(series, dict) else None
        return normalize_bars(rows if isinstance(rows, list) else [rows] if isinstance(rows, dict) else [])

    def _split_since(self, symbol: str, first: date, today: date) -> bool | None:
        """True or False from the split source; None when it cannot answer."""
        if self.splits is None:
            return False
        try:
            info = self.splits.get(symbol, today)
            if info.get("status") != "ok":
                return None
            found = info.get("splits") or []
            return any(first < date.fromisoformat(s["ex_date"]) <= today for s in found)
        except Exception:
            return None

    # -------------------------------------------------------------- delivery

    def deliver(self) -> None:
        now = self.clock()
        with Session(self.engine) as db:
            db.exec(update(DecisionEvent).where(DecisionEvent.delivery == "sending", DecisionEvent.claimed_at < _utc(now - CLAIM_SECONDS))
                    .values(delivery="pending"))
            db.commit()
            due = db.exec(select(DecisionEvent.id).where(DecisionEvent.delivery == "pending")
                          .where((DecisionEvent.next_attempt_at.is_(None)) | (DecisionEvent.next_attempt_at <= _utc(now)))
                          .order_by(DecisionEvent.recorded_at).limit(20)).all()
        for event_id in due:
            self._send(event_id, now)

    def _send(self, event_id: uuid.UUID, now: float) -> None:
        with Session(self.engine) as db:
            claimed = db.exec(update(DecisionEvent).where(DecisionEvent.id == event_id, DecisionEvent.delivery == "pending")
                              .values(delivery="sending", claimed_at=_utc(now)))
            db.commit()
            if claimed.rowcount != 1:
                return
            event = db.get(DecisionEvent, event_id)
            if now - _epoch(event.recorded_at) > EXPIRE_SECONDS:
                event.delivery, event.last_error = "expired", "Not delivered within six hours, so it was not sent late."
                db.commit()
                return
            record = db.get(DecisionRecord, event.record_id)
            title, body = message(record, json.loads(event.data_json), now)
            event.attempts += 1
            try:
                ntfy.publish(title, body, path=f"/?decision={record.id}")
            except ntfy.NtfyError as exc:
                event.delivery = "pending"
                event.next_attempt_at = _utc(now + BACKOFF[min(event.attempts, len(BACKOFF)) - 1])
                event.last_error = str(exc)
                db.commit()
                return
            event.delivery, event.delivered_at, event.last_error = "sent", _utc(self.clock()), None
            db.commit()


def message(record: DecisionRecord, event: dict, now: float) -> tuple[str, str]:
    """The phone text for one paper event: always labelled practice, and late when it is."""
    when = datetime.fromtimestamp(event["at"], ET).strftime("%H:%M")
    what = {
        "trigger": f"15m close {event.get('close', 0):.2f} above {event.get('level', 0):.2f} at {when}; paper entry next minute",
        "missed_trigger": f"Trigger at {when} was seen too late; no paper entry",
        "entry": f"Paper entry {event.get('fill', 0):.2f} at {when}",
        "entry_rejected": f"Paper entry refused at {when}: {str(event.get('reason', '')).replace('_', ' ')}",
        "exit": f"Paper {event.get('kind')} exit {event.get('fill', 0):.2f} at {when}"
                + (" (ambiguous bar)" if event.get("ambiguous") else ""),
        "unresolved": f"Paper outcome unresolved: {event.get('reason')}",
    }[event["type"]]
    # Bar events are dated by the minute's start; they are knowable once it closed and was final.
    knowable = event["bar_start"] + 60 + LATENESS if event["type"] in ("entry", "entry_rejected", "exit") else event["at"] + LATENESS
    age = now - max(event["at"], knowable)
    if age > LATE_SECONDS:
        what += f" (late by {int(age // 60)} min)"
    return f"PRACTICE · {record.symbol} {event['type'].replace('_', ' ')}", what + ". Not a real trade."


def paper_row(db: Session, record_id: uuid.UUID, *, record: DecisionRecord | None = None, event_rows: list[DecisionEvent] | None = None) -> dict:
    """The plan's paper state, event timeline and outcome at base and triple costs."""
    record = record if record is not None else db.get(DecisionRecord, record_id)
    if record is None:
        raise LookupError("Decision record not found")
    rows = event_rows if event_rows is not None else events_for(db, record_id)
    state = px.fold(_data(rows))
    terms = px.terms_from_plan(json.loads(record.decision_json)["plan"]) if record.decision == "take" else None
    return {
        "record_id": str(record_id), "status": state.status,
        "policy_version": json.loads(rows[0].data_json)["policy_version"] if rows else None,
        "events": [{**json.loads(r.data_json), "seq": r.seq, "recorded_at": _epoch(r.recorded_at), "source": r.source,
                    "reconstructed": r.reconstructed, "delivery": r.delivery, "delivery_error": r.last_error} for r in rows],
        "outcome": px.outcome(state, terms) if terms else None,
        "outcome_x3": px.outcome(state, terms, 3) if terms else None,
    }
