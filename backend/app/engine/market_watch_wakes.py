"""MW-2: event wake-ups for Jo's market watch, and selective messages.

Complements the selected first slice (#315): Jo's own scheduled reads at
09:50, 11:00, 12:30 and 14:00 and its snapshot publisher
(``market_watch_schedule``). This module publishes no snapshots and sends no
scheduled wakes. Off unless ``MARKET_WATCH_ENABLED`` is true and
``MARKET_WATCH_SNAPSHOTS_DIR`` (the #315 publication directory) and
``MARKET_WATCH_STORE`` are absolute paths. Each pass (about every 30 seconds in
the API process) does, in order:

1. read new sealed read notices from ``MARKET_WATCH_OUTBOX_DIR`` (written by the
   check service on ``market_watch_submit``), when that outbox is configured;
2. read the latest published current-session snapshot;
3. run the deterministic detector (``DETECTOR``) on it;
4. plan event wakes under ``WAKE_POLICY`` (coalesced with recent wakes and with
   Jo's scheduled reads) and email each wake ID to Jo through the scanner's
   mail path (``scanner_mail``);
5. push Jo's notify reads to Isaac through the server's ntfy alerts
   (``MESSAGE_POLICY``), within a daily discretionary budget; a correction of a
   message that reached Isaac skips the budget (once per message, capped).

Every event, wake, send attempt (recorded before the send starts), notice,
refused notice, message decision and failure is an append-only row in an
owner-selected SQLite file, separate from the journal database and from the
check ledger. A send whose outcome is uncertain (crash mid-send, a transport
timeout after the request went out) is recorded ``unknown`` and never resent. Nothing here places, sizes or arms an
order, touches S1 or shadow S1, or feeds Shadow Isaac: reads are advice to
Isaac only. Thresholds are frozen and versioned; changing one is a new version.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
import json
import logging
import math
import os
from pathlib import Path
import re
import sqlite3
import uuid
from zoneinfo import ZoneInfo

from market_watch_common import digest, parse_time, seal, session_bounds, validate_snapshot, verify

log = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")

DETECTOR = {
    "detector_version": "mw-detect-v1",
    "symbol": "SPY",
    "release_kinds": ["cpi", "fomc", "jobs"],
    "levels": ["vwap", "or15_high", "or15_low"],
    "levels_from_minutes_after_open": 15,
    "level_band_fraction": 0.0005,
    "level_cooldown_minutes": 30,
    "session_extreme_after_local_time": "11:00",
    "session_extreme_cooldown_minutes": 30,
    "atr_period": 14,
    "atr_move_multiple": 0.5,
    "max_detection_lag_minutes": 10,
}
WAKE_POLICY = {
    "wake_policy_version": "mw-wake-v1",
    "jo_scheduled_local_times": ["09:50", "11:00", "12:30", "14:00"],  # #315's scheduled task, not sent here
    "jo_scheduled_operation_prefix": "mw-scheduled-v1",
    "coalesce_before_scheduled_minutes": 5,
    "event_min_gap_minutes": 15,
    "event_wakes_per_session": 6,
    "send_freshness_minutes": 5,
    "max_attempts": 3,
    "retry_seconds": 60,
    "email_subject_prefix": "TJ Market Watch:",
    "event_operation_prefix": "mw-event-v1",
    "read_attribution_minutes": 30,
}
MESSAGE_POLICY = {
    "message_policy_version": "mw-message-v1",
    "channel": "push",
    "transport": "ntfy",
    "discretionary_per_session": 3,
    "corrections_bypass_budget": "when_the_corrected_message_reached_isaac_once_per_message",
    "freshness_minutes": 10,
    "max_attempts": 3,
    "retry_seconds": 60,
    "max_chars": 3500,
    "budget_free_corrections_per_session": 3,
    "cautions": ["puts in the first 15 minutes", "chasing extended moves", "late-day holds"],
}
POLICY_SHA256 = digest({"detector": DETECTOR, "wakes": WAKE_POLICY, "messages": MESSAGE_POLICY})
KINDS = ("event", "wake", "wake_attempt", "read_notice", "notice_refusal", "message_decision", "message_attempt")
NO_WAKE_EVENTS = ("minute_gap",)  # recorded so a blind spot is visible, never a reason to wake Jo
TERMINAL = ("accepted", "expired", "unknown")
APPLICATION_ID = 0x4D574431  # MWD1: the isolated MW-2 wake/delivery file.
NOTICE_LIMIT = 64 * 1024

_SCHEMA = """
CREATE TABLE IF NOT EXISTS record(id TEXT PRIMARY KEY, kind TEXT NOT NULL, session_date TEXT NOT NULL,
  ref TEXT, payload TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS record_session ON record(session_date, kind);
CREATE TRIGGER IF NOT EXISTS record_no_update BEFORE UPDATE ON record BEGIN SELECT RAISE(ABORT,'market watch records are immutable'); END;
CREATE TRIGGER IF NOT EXISTS record_no_delete BEFORE DELETE ON record BEGIN SELECT RAISE(ABORT,'market watch records are immutable'); END;
CREATE TRIGGER IF NOT EXISTS record_no_replace BEFORE INSERT ON record WHEN EXISTS(SELECT 1 FROM record WHERE id=NEW.id)
  BEGIN SELECT RAISE(ABORT,'market watch records are immutable'); END;
"""


def enabled() -> bool:
    return os.environ.get("MARKET_WATCH_ENABLED", "false").lower() in ("1", "true", "yes")


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _local_minutes(value: str) -> int:
    hour, minute = (int(part) for part in value.split(":"))
    return hour * 60 + minute


def _at_local(day: date, value: str) -> datetime:
    minutes = _local_minutes(value)
    return datetime(day.year, day.month, day.day, minutes // 60, minutes % 60, tzinfo=ET).astimezone(UTC)


def _new_id(prefix: str) -> str:
    return prefix + "_" + str(uuid.uuid4())


# ------------------------------------------------------------------ store

class MarketWatchWakeStore:
    """Explicit owner-selected SQLite file; every row is immutable."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        if not self.path.is_absolute():
            raise ValueError("market-watch wake store path must be absolute")
        if self.path.is_symlink():
            raise ValueError("market-watch wake store may not be a symlink")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            marker = db.execute("PRAGMA application_id").fetchone()[0]
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
            if marker == 0 and not tables:
                db.execute(f"PRAGMA application_id={APPLICATION_ID}")
            elif marker != APPLICATION_ID or tables != {"record"}:
                raise ValueError("refusing to adopt a non-MW-2 database")
            db.executescript(_SCHEMA)

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.path, timeout=10, isolation_level="IMMEDIATE")
        try:
            with db:
                yield db
        finally:
            db.close()

    def append(self, kind: str, record: dict, *, ident: str, ref: str | None = None) -> bool:
        """Insert once; an existing identical id is kept (first record wins) and reports False."""
        if kind not in KINDS:
            raise ValueError("unknown market-watch record kind")
        verify(record)
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM record WHERE id=?", (ident,)).fetchone():
                return False
            db.execute("INSERT INTO record VALUES(?,?,?,?,?)",
                       (ident, kind, record["session_date"], ref, json.dumps(record, sort_keys=True, separators=(",", ":"))))
        return True

    def records(self, kind: str | None = None, session_date: str | None = None) -> list[dict]:
        sql, args = "SELECT payload FROM record WHERE 1=1", []
        if kind:
            sql, args = sql + " AND kind=?", args + [kind]
        if session_date:
            sql, args = sql + " AND session_date=?", args + [session_date]
        with self._db() as db:
            rows = [json.loads(row[0]) for row in db.execute(sql + " ORDER BY rowid", args)]
        for row in rows:
            verify(row)
        return rows


# --------------------------------------------------------------- detector

def _spy_bars(snapshot: dict) -> list[dict]:
    entry = next((m for m in snapshot["input_manifest"] if m.get("group") == "indices.SPY.bars_1m"), None)
    return list(entry["bars"]) if entry else []


def snapshot_price(snapshot: dict) -> float | None:
    price = snapshot["indices"]["SPY"].get("price") or {}
    value = price.get("value")
    return float(value) if isinstance(value, (int, float)) and math.isfinite(value) else None


def _event(snapshot: dict, kind: str, key: list, occurred_at: str, detected_at: datetime, detail: dict) -> dict:
    lag = (detected_at - parse_time(occurred_at)).total_seconds() / 60
    body = {"session_date": snapshot["session_date"], "detector_version": DETECTOR["detector_version"], "kind": kind, "key": key}
    return seal({"event_id": "mwv_" + digest(body)[:32], **body, "policy_sha256": POLICY_SHA256,
                 "occurred_at": occurred_at, "detected_at": _iso(detected_at), "created_at": _iso(detected_at),
                 "late": lag > DETECTOR["max_detection_lag_minutes"], "detail": detail,
                 "snapshot_id": snapshot["snapshot_id"], "snapshot_sha256": snapshot["content_sha256"]})


def detect_events(snapshot: dict, *, detected_at: datetime, atr: dict | None = None,
                  last_read: dict | None = None) -> list[dict]:
    """Replay the snapshot's frozen SPY minutes from the open; same input, same events.

    ``atr`` is ``{"atr14": float, "bars_sha256": str}`` from prior complete
    sessions; ``last_read`` is ``{"read_id", "received_at", "price"}`` (SPY at
    the read's served snapshot). Either missing simply yields no ATR event.
    """
    validate_snapshot(snapshot)
    events = []
    finished = parse_time(snapshot["collection_finished_at"])
    for item in snapshot["calendar"].get("events", []):
        if item["kind"] in DETECTOR["release_kinds"] and parse_time(item["scheduled_at"]) <= finished:
            events.append(_event(snapshot, "release_time_passed", [item["event_id"]], item["scheduled_at"], detected_at,
                                 {"calendar_event_id": item["event_id"], "release_kind": item["kind"], "name": item["name"],
                                  "scheduled_at": item["scheduled_at"], "release_values_status": item["release_values_status"]}))
    if not snapshot.get("session_open_at"):
        return events
    opened = parse_time(snapshot["session_open_at"])
    bars = _spy_bars(snapshot)
    # A missing minute ends the reproducible VWAP (nothing is invented after it) and is
    # recorded once; OR levels, session extremes and ATR moves keep using the real bars.
    gap_at = next((i for i, bar in enumerate(bars) if parse_time(bar["start"]) != opened + timedelta(minutes=i)), None)
    if gap_at is not None:
        expected = opened + timedelta(minutes=gap_at)
        events.append(_event(snapshot, "minute_gap", [_iso(expected)], _iso(expected + timedelta(minutes=1)), detected_at,
                             {"missing_from": _iso(expected), "next_bar_start": bars[gap_at]["start"],
                              "effect": "vwap_events_stop_for_the_session"}))
    or_high = or_low = None
    if all(parse_time(bar["start"]) == opened + timedelta(minutes=i) for i, bar in enumerate(bars[:15])) and len(bars) >= 15:
        or_high = max(bar["high"] for bar in bars[:15])
        or_low = min(bar["low"] for bar in bars[:15])
    extreme_after = _local_minutes(DETECTOR["session_extreme_after_local_time"])
    pv = volume = 0.0
    high = low = None
    side: dict[str, str] = {}
    last_fire: dict[str, datetime] = {}
    atr_fired: set[tuple] = set()
    band = DETECTOR["level_band_fraction"]

    def cooled(key, at, minutes):
        previous = last_fire.get(key)
        return previous is None or at - previous >= timedelta(minutes=minutes)

    for index, bar in enumerate(bars):
        end = parse_time(bar["end"])
        vwap = None
        if gap_at is None or index < gap_at:
            pv += ((bar["high"] + bar["low"] + bar["close"]) / 3) * bar["volume"]
            volume += bar["volume"]
            vwap = pv / volume if volume > 0 else None
        local = end.astimezone(ET)
        bar_brief = {k: bar[k] for k in ("start", "end", "open", "high", "low", "close")}
        if high is not None and local.hour * 60 + local.minute >= extreme_after:
            for name, broke, level in (("new_session_high", bar["high"] > high, high), ("new_session_low", bar["low"] < low, low)):
                if broke and cooled(name, end, DETECTOR["session_extreme_cooldown_minutes"]):
                    last_fire[name] = end
                    events.append(_event(snapshot, name, [bar["start"]], bar["end"], detected_at,
                                         {"prior_extreme": level, "bar": bar_brief}))
        high = bar["high"] if high is None else max(high, bar["high"])
        low = bar["low"] if low is None else min(low, bar["low"])
        if end - opened > timedelta(minutes=DETECTOR["levels_from_minutes_after_open"]):
            for name, value in (("vwap", vwap), ("or15_high", or_high), ("or15_low", or_low)):
                if value is None:
                    continue
                now_side = "above" if bar["close"] > value * (1 + band) else "below" if bar["close"] < value * (1 - band) else "at"
                if now_side == "at":
                    continue
                before = side.get(name)
                kind = direction = None
                if before is not None and before != now_side:
                    kind, direction = "level_cross", "up" if now_side == "above" else "down"
                elif before == now_side and ((now_side == "below" and bar["high"] >= value) or (now_side == "above" and bar["low"] <= value)):
                    kind, direction = "level_fail", "down" if now_side == "below" else "up"
                side[name] = now_side
                if kind and cooled(name, end, DETECTOR["level_cooldown_minutes"]):
                    last_fire[name] = end
                    events.append(_event(snapshot, kind, [name, direction, bar["start"]], bar["end"], detected_at,
                                         {"level": name, "direction": direction, "level_value": value, "bar": bar_brief}))
        if atr and last_read and atr.get("atr14") and last_read.get("price") and end > parse_time(last_read["received_at"]):
            step = DETECTOR["atr_move_multiple"] * atr["atr14"]
            move = bar["close"] - last_read["price"]
            multiple = int(abs(move) // step)
            direction = "up" if move > 0 else "down"
            if multiple >= 1 and (multiple, direction) not in atr_fired:
                atr_fired.update((k, direction) for k in range(1, multiple + 1))
                events.append(_event(snapshot, "atr_move_since_read", [last_read["read_id"], direction, multiple], bar["end"], detected_at,
                                     {"read_id": last_read["read_id"], "read_price": last_read["price"], "direction": direction,
                                      "multiple": multiple, "move": move, "atr14": atr["atr14"],
                                      "atr_bars_sha256": atr.get("bars_sha256"), "bar": bar_brief}))
    return events


def prior_atr14(daily_rows: list[dict], day: date) -> dict | None:
    """Mean true range over the 14 complete sessions before ``day`` (protocol session-label rule)."""
    rows = sorted((r for r in daily_rows if str(r.get("t", ""))[:10] < day.isoformat()), key=lambda r: str(r["t"]))
    rows = rows[-(DETECTOR["atr_period"] + 1):]
    if len(rows) < DETECTOR["atr_period"] + 1:
        return None
    try:
        ranges = [max(float(cur["h"]) - float(cur["l"]), abs(float(cur["h"]) - float(prev["c"])), abs(float(cur["l"]) - float(prev["c"])))
                  for prev, cur in zip(rows, rows[1:])]
    except (KeyError, TypeError, ValueError):
        return None
    value = sum(ranges) / len(ranges)
    if not math.isfinite(value) or value <= 0:
        return None
    return {"atr14": value, "bars_sha256": digest([{k: r.get(k) for k in ("t", "h", "l", "c")} for r in rows])}


# ----------------------------------------------------------- read notices

NOTICE_FIELDS = {"schema_version", "created_at", "content_sha256", "notice_version", "read_id", "actor", "received_at",
                 "session_date", "protocol_id", "snapshot_id", "snapshot_sha256", "read_sha256", "previous_read_id", "view",
                 "message_intent", "message_id", "is_correction", "corrects_message_id", "correction_of_read_id",
                 "main_text", "alternative_text", "invalidation_text", "change_summary", "forecasts", "quality_flags"}


def validate_notice(notice: dict, snapshots_dir: str | Path, now: datetime) -> dict:
    """Verify one outbox notice against its seal and the snapshot this app published."""
    verify(notice)
    if set(notice) != NOTICE_FIELDS or notice["notice_version"] != "mw-read-notice-v1" or notice["protocol_id"] != "mw-v1":
        raise ValueError("read notice fields are invalid")
    if not re.fullmatch(r"mwr_[0-9a-f-]{36}", notice["read_id"]) or not re.fullmatch(r"check_[0-9a-f-]{36}", notice["actor"]):
        raise ValueError("read notice identity is invalid")
    if notice["view"] not in ("up", "down", "mixed", "no_view") or notice["message_intent"] not in ("none", "update", "correction"):
        raise ValueError("read notice view or intent is invalid")
    if (notice["message_intent"] == "none") != (notice["message_id"] is None):
        raise ValueError("read notice message link is invalid")
    if notice["message_id"] is not None and not re.fullmatch(r"mwm_[0-9a-f-]{36}", notice["message_id"]):
        raise ValueError("read notice message identity is invalid")
    if notice["is_correction"] != (notice["message_intent"] == "correction") or (notice["is_correction"] and not notice["corrects_message_id"]):
        raise ValueError("read notice correction link is invalid")
    for field in ("main_text", "alternative_text", "invalidation_text", "change_summary"):
        if not isinstance(notice[field], str) or not notice[field].strip() or len(notice[field]) > 2000:
            raise ValueError("read notice text is invalid")
    forecasts = notice["forecasts"]
    if (not isinstance(forecasts, list) or len(forecasts) != 3 or not all(isinstance(f, dict) and set(f) == {"horizon", "probability"} for f in forecasts)
            or {f["horizon"] for f in forecasts} != {"30m", "60m", "close"}
            or not all(f["probability"] is None or (type(f["probability"]) in (int, float) and 0 <= f["probability"] <= 1) for f in forecasts)):
        raise ValueError("read notice forecasts are invalid")
    received = parse_time(notice["received_at"])
    if received > now:
        raise ValueError("read notice is from the future")
    sha = notice["snapshot_sha256"]
    if not re.fullmatch(r"[0-9a-f]{64}", sha):
        raise ValueError("read notice snapshot hash is invalid")
    snapshot = load_snapshot(snapshots_dir, sha)
    if snapshot["snapshot_id"] != notice["snapshot_id"] or snapshot["session_date"] != notice["session_date"]:
        raise ValueError("read notice does not match a snapshot this app published")
    if received < parse_time(snapshot["collection_finished_at"]):
        raise ValueError("read notice precedes its snapshot")
    return snapshot


def load_snapshot(snapshots_dir: str | Path, sha: str) -> dict:
    from app.engine.market_watch_snapshot import _read_bounded
    if not re.fullmatch(r"[0-9a-f]{64}", sha):
        raise ValueError("snapshot hash is invalid")
    snapshot = json.loads(_read_bounded(Path(snapshots_dir) / f"{sha}.json", 2 * 1024 * 1024))
    validate_snapshot(snapshot)
    if snapshot["content_sha256"] != sha:
        raise ValueError("snapshot content does not match its address")
    return snapshot


def message_text(notice: dict) -> tuple[str, str]:
    """Title and body: the read in one line, named forecast, what proves it wrong, cautions as flags."""
    label = {"up": "UP", "down": "DOWN", "mixed": "MIXED", "no_view": "NO VIEW"}[notice["view"]]
    title = ("Jo correction: " if notice["is_correction"] else "Jo market read: ") + label
    probabilities = " · ".join(f"{f['horizon']} {f['probability']:.2f}" if f.get("probability") is not None else f"{f['horizon']} —"
                               for f in sorted(notice["forecasts"], key=lambda f: ("30m", "60m", "close").index(f["horizon"])))
    lines = [notice["main_text"].strip(),
             f"P(SPY lower than at the read): {probabilities}",
             f"Wrong if: {notice['invalidation_text'].strip()}",
             f"Alternative: {notice['alternative_text'].strip()}",
             f"Changed: {notice['change_summary'].strip()}",
             "Your cautions (flags, not rules): " + "; ".join(MESSAGE_POLICY["cautions"]),
             f"Read {notice['read_id']}" + (f" corrects message {notice['corrects_message_id']}" if notice["is_correction"] else "")]
    body = "\n".join(lines)
    if len(body) > MESSAGE_POLICY["max_chars"]:
        body = body[: MESSAGE_POLICY["max_chars"] - 1] + "…"
    return title, body


# ----------------------------------------------------------------- runner

def _classify(exc: BaseException) -> tuple[str, str]:
    """``failed`` when the request surely never reached the transport, else ``unknown`` (never resent)."""
    import httpx
    import smtplib
    if str(exc) in ("mail_not_configured", "ntfy_not_configured"):
        return "failed", str(exc)
    chain, seen = [], exc
    while seen is not None and len(chain) < 5:
        chain.append(seen)
        seen = seen.__cause__ or seen.__context__
    if any(isinstance(e, (httpx.ConnectError, httpx.ConnectTimeout, smtplib.SMTPConnectError, smtplib.SMTPAuthenticationError,
                          smtplib.SMTPRecipientsRefused, smtplib.SMTPSenderRefused, ConnectionRefusedError)) for e in chain):
        return "failed", type(chain[-1]).__name__
    if any(isinstance(e, (TimeoutError, httpx.TimeoutException, httpx.ReadError, httpx.WriteError, httpx.RemoteProtocolError,
                          smtplib.SMTPServerDisconnected, ConnectionResetError)) for e in chain):
        return "unknown", type(chain[-1]).__name__
    return "failed", type(chain[-1]).__name__


def _default_mail(subject: str, body: str) -> str | None:
    from app.engine import scanner_mail
    if not scanner_mail.configured():
        raise RuntimeError("mail_not_configured")
    scanner_mail.send(subject, body)
    return None


def _default_push(title: str, body: str) -> str | None:
    from app.engine import ntfy
    if not ntfy.configured():
        raise RuntimeError("ntfy_not_configured")
    return ntfy.publish(title, body, priority=4, tags=("chart_with_downwards_trend",))


def _default_daily(day: date) -> list[dict]:
    from app.engine import alpaca
    result = alpaca._alpaca_get_fast("/v2/stocks/bars", {
        "symbols": "SPY", "timeframe": "1Day", "start": (day - timedelta(days=40)).isoformat(),
        "end": day.isoformat(), "adjustment": "split", "feed": "iex", "limit": 10000})
    return result.get("bars", {}).get("SPY", [])


class MarketWatchRunner:
    """One idempotent pass at a time; every decision is reconstructed from the store."""

    def __init__(self, store: MarketWatchWakeStore, snapshots_dir: str | Path, *, outbox_dir: str | Path | None = None,
                 clock=lambda: datetime.now(UTC), bounds=None, mail=_default_mail, push=_default_push,
                 daily=_default_daily):
        self.store = store
        self.snapshots_dir = Path(snapshots_dir)
        self.outbox_dir = Path(outbox_dir) if outbox_dir else None
        self.clock = clock
        self.bounds = bounds
        self.mail, self.push, self.daily = mail, push, daily
        self._atr: dict[date, dict | None] = {}

    # The real exchange calendar is warmed once per pass; tests inject bounds.
    def _session(self, day: date):
        if self.bounds is not None:
            return self.bounds(day)
        from app.engine.chart_calendar import chart_calendar
        try:
            chart_calendar.hours(day)
        except Exception:
            pass
        return session_bounds(day)

    def run_once(self) -> None:
        day = self.clock().astimezone(ET).date()
        for step in (self.ingest_notices, lambda n: self.pass_session(n, day), self.deliver_messages):
            try:
                step(self.clock())  # freshness is judged when each step starts, not when the pass began
            except Exception:
                log.exception("Market watch pass step failed")

    def pass_session(self, now: datetime, day: date) -> None:
        bounds = self._session(day)
        if bounds is None:
            return
        opened, closed = bounds
        if not opened <= now <= closed + timedelta(minutes=1):
            return
        from app.engine.market_watch_snapshot import read_latest_snapshot
        snapshot = read_latest_snapshot(self.snapshots_dir, now)  # published by #315's timer, never here
        if snapshot is not None:
            self.record_events(snapshot, now, day)
        self.plan_wakes(now, day, closed, snapshot)
        self.send_wakes(self.clock(), day)  # the ATR read above may have taken a while

    def _last_read(self, day: date) -> dict | None:
        notices = sorted(self.store.records("read_notice", day.isoformat()), key=lambda n: n["received_at"])
        if not notices:
            return None
        latest = notices[-1]
        try:
            price = snapshot_price(load_snapshot(self.snapshots_dir, latest["snapshot_sha256"]))
        except (OSError, ValueError, json.JSONDecodeError):
            price = None
        return {"read_id": latest["read_id"], "received_at": latest["received_at"], "price": price} if price else None

    def record_events(self, snapshot: dict, now: datetime, day: date) -> None:
        if day not in self._atr:
            try:
                self._atr[day] = prior_atr14(self.daily(day), day)
            except Exception:
                log.warning("Market watch ATR unavailable for %s; retried next pass", day)
        for event in detect_events(snapshot, detected_at=now, atr=self._atr.get(day), last_read=self._last_read(day)):
            self.store.append("event", event, ident=event["event_id"], ref=event["kind"])

    def _wake(self, now, day, snapshot, trigger, ref, due_at, decision, reason=None, event_id=None):
        wake_id = "mwk_" + digest({"session_date": day.isoformat(), "trigger": trigger, "ref": ref})[:32]
        record = seal({"wake_id": wake_id, "session_date": day.isoformat(), "policy_sha256": POLICY_SHA256,
                       "wake_policy_version": WAKE_POLICY["wake_policy_version"], "trigger": trigger, "ref": ref,
                       "event_id": event_id, "due_at": _iso(due_at), "created_at": _iso(now), "decision": decision,
                       "reason": reason, "snapshot_id": snapshot["snapshot_id"] if snapshot else None,
                       "snapshot_sha256": snapshot["content_sha256"] if snapshot else None})
        self.store.append("wake", record, ident=wake_id, ref=trigger)

    def plan_wakes(self, now: datetime, day: date, closed: datetime, snapshot: dict | None) -> None:
        session = day.isoformat()
        planned = {w["ref"] for w in self.store.records("wake", session)}
        gap = timedelta(minutes=WAKE_POLICY["event_min_gap_minutes"])
        ahead = timedelta(minutes=WAKE_POLICY["coalesce_before_scheduled_minutes"])
        # Jo's own scheduled reads (#315) count as wakes: an event just after one, or just before one, adds nothing.
        scheduled = [slot for slot in WAKE_POLICY["jo_scheduled_local_times"]
                     if _at_local(day, slot) < closed and now - gap < _at_local(day, slot) <= now + ahead]
        events = [e for e in self.store.records("event", session) if e["event_id"] not in planned and e["kind"] not in NO_WAKE_EVENTS]
        for event in events:
            wakes = self.store.records("wake", session)
            sent = [w for w in wakes if w["decision"] == "send"]
            recent = [w for w in sent if now - parse_time(w["created_at"]) < gap]
            if event["late"]:
                decision, reason = "event_late", "detected after the lag limit"
            elif sum(w["trigger"] == "event" for w in sent) >= WAKE_POLICY["event_wakes_per_session"]:
                decision, reason = "rate_limited", "daily event-wake cap reached"
            elif recent:
                decision, reason = "coalesced", f"within {WAKE_POLICY['event_min_gap_minutes']} minutes of {recent[-1]['wake_id']}"
            elif scheduled:
                decision, reason = "coalesced", f"next to Jo's scheduled {scheduled[0]} read"
            else:
                decision, reason = "send", None
            self._wake(now, day, snapshot, "event", event["event_id"], parse_time(event["detected_at"]), decision, reason,
                       event_id=event["event_id"])

    def _attempt(self, kind, now, session, parent_field, parent_id, attempt, result, channel, receipt=None, error=None, extra=None):
        record = seal({"attempt_id": _new_id("mwa"), "session_date": session, parent_field: parent_id, "attempt": attempt,
                       "result": result, "channel": channel, "transport_receipt_id": receipt, "error_code": error,
                       "occurred_at": _iso(now), "created_at": _iso(now), **(extra or {})})
        self.store.append(kind, record, ident=record["attempt_id"], ref=parent_id)

    def _deliver(self, kind, now, session, parent_field, parent_id, created, freshness, policy, channel, send, extra=None):
        attempts = [a for a in self.store.records(kind, session) if a.get(parent_field) == parent_id]
        if any(a["result"] in TERMINAL for a in attempts):
            return
        started = [a for a in attempts if a["result"] == "sending"]
        settled = {a["attempt"] for a in attempts if a["result"] == "failed"}
        orphan = next((a for a in started if a["attempt"] not in settled), None)
        if orphan is not None:
            # The process stopped between starting a send and recording its result: it may have gone out.
            self._attempt(kind, now, session, parent_field, parent_id, orphan["attempt"], "unknown", channel,
                          error="result_not_recorded", extra=extra)
            return
        tries = [a for a in attempts if a["result"] == "failed"]
        stale = now - created > timedelta(minutes=freshness)
        if stale or len(tries) >= policy["max_attempts"]:
            self._attempt(kind, now, session, parent_field, parent_id, len(tries), "expired", channel,
                          error="past_freshness" if stale else "attempts_exhausted", extra=extra)
            return
        if tries and now - parse_time(tries[-1]["occurred_at"]) < timedelta(seconds=policy["retry_seconds"]):
            return
        number = len(tries) + 1
        self._attempt(kind, self.clock(), session, parent_field, parent_id, number, "sending", channel, extra=extra)
        try:
            receipt = send()
        except Exception as exc:
            result, code = _classify(exc)
            self._attempt(kind, self.clock(), session, parent_field, parent_id, number, result, channel, error=code, extra=extra)
            log.warning("Market watch %s %s attempt %s: %s", channel, parent_id, result, code)
            return
        self._attempt(kind, self.clock(), session, parent_field, parent_id, number, "accepted", channel, receipt=receipt, extra=extra)

    def send_wakes(self, now: datetime, day: date) -> None:
        session = day.isoformat()
        for wake in self.store.records("wake", session):
            if wake["decision"] != "send":
                continue
            subject = f"{WAKE_POLICY['email_subject_prefix']} {wake['wake_id']}"
            self._deliver("wake_attempt", now, session, "wake_id", wake["wake_id"], parse_time(wake["created_at"]),
                          WAKE_POLICY["send_freshness_minutes"], WAKE_POLICY, "email",
                          lambda: self.mail(subject, f"Wake ID: {wake['wake_id']}\n"))

    def ingest_notices(self, now: datetime) -> None:
        if self.outbox_dir is None:
            return
        from app.engine.market_watch_snapshot import _read_bounded
        known = {n["read_id"] for n in self.store.records("read_notice")}
        refused = {r["refusal_id"] for r in self.store.records("notice_refusal")}
        found = []
        for path in self.outbox_dir.glob("read-mwr_*.json"):
            read_id = path.name[len("read-"):-len(".json")]
            if read_id in known:
                continue
            raw = None
            try:
                raw = _read_bounded(path.absolute(), NOTICE_LIMIT)
                notice = json.loads(raw)
                validate_notice(notice, self.snapshots_dir, now)
                if notice["read_id"] != read_id:
                    raise ValueError("read notice file name does not match its read")
            except Exception as exc:  # one bad file never stalls the others
                refusal_id = "mwn_" + digest({"file": path.name, "content": digest(raw) if raw is not None else None,
                                               "reason": type(exc).__name__})[:32]
                if refusal_id not in refused:
                    log.warning("Market watch read notice %s refused: %s", path.name, exc)
                    record = seal({"refusal_id": refusal_id, "session_date": now.astimezone(ET).date().isoformat(),
                                   "file": path.name, "read_id": read_id, "content_sha256": digest(raw) if raw is not None else None,
                                   "reason": f"{type(exc).__name__}: {str(exc)[:200]}", "created_at": _iso(now)})
                    self.store.append("notice_refusal", record, ident=refusal_id, ref=read_id)
                    refused.add(refusal_id)
                continue
            found.append(notice)
        # Receipt order decides the message budget, so store notices in the order Jo submitted them.
        for notice in sorted(found, key=lambda n: (parse_time(n["received_at"]), n["read_id"])):
            self.store.append("read_notice", notice, ident=notice["read_id"], ref=notice["message_id"])

    def deliver_messages(self, now: datetime) -> None:
        decided = {d["message_id"]: d for d in self.store.records("message_decision")}
        for notice in self.store.records("read_notice"):
            if notice["message_id"] is None or notice["message_id"] in decided:
                continue
            session = notice["session_date"]
            received = parse_time(notice["received_at"])
            decisions = self.store.records("message_decision", session)
            attempts = self.store.records("message_attempt", session)
            def reached(message_id):
                results = {a["result"] for a in attempts if a["message_id"] == message_id}
                return "accepted" in results or "unknown" in results

            spent = free = 0
            for d in decisions:
                if d["decision"] != "send":
                    continue
                if d.get("budget_free"):
                    free += 1
                    continue
                results = {a["result"] for a in attempts if a["message_id"] == d["message_id"]}
                if "expired" not in results or "accepted" in results or "unknown" in results:
                    spent += 1  # reached Isaac, may have, or still in flight; a send that expired undelivered is refunded
            # A correction skips the budget only when it corrects a message that reached (or may have
            # reached) Isaac, once per corrected message, and at most a few times a session.
            budget_free = (notice["is_correction"] and reached(notice["corrects_message_id"])
                           and not any(d.get("budget_free") and d["corrects_message_id"] == notice["corrects_message_id"] for d in decisions)
                           and free < MESSAGE_POLICY["budget_free_corrections_per_session"])
            if now - received > timedelta(minutes=MESSAGE_POLICY["freshness_minutes"]):
                decision, reason = "expired_before_send", "notice arrived after the freshness limit"
            elif not budget_free and spent >= MESSAGE_POLICY["discretionary_per_session"]:
                decision, reason = "suppressed_budget", f"{spent} discretionary messages already used" + (
                    "; this correction's original never reached Isaac or its budget-free correction was used" if notice["is_correction"] else "")
            else:
                decision, reason = "send", None
            record = seal({"message_id": notice["message_id"], "read_id": notice["read_id"], "session_date": session,
                           "policy_sha256": POLICY_SHA256, "message_policy_version": MESSAGE_POLICY["message_policy_version"],
                           "is_correction": notice["is_correction"], "corrects_message_id": notice["corrects_message_id"],
                           "decision": decision, "reason": reason, "budget_used_before": spent,
                           "budget_free": bool(budget_free and decision == "send"),
                           "channel": MESSAGE_POLICY["channel"], "created_at": _iso(now)})
            self.store.append("message_decision", record, ident="decision:" + notice["message_id"], ref=notice["read_id"])
            decided[notice["message_id"]] = record
        notices = {n["message_id"]: n for n in self.store.records("read_notice") if n["message_id"]}
        for message_id, d in decided.items():
            if d["decision"] != "send" or message_id not in notices:
                continue
            notice = notices[message_id]
            title, body = message_text(notice)
            self._deliver("message_attempt", now, d["session_date"], "message_id", message_id, parse_time(notice["received_at"]),
                          MESSAGE_POLICY["freshness_minutes"], MESSAGE_POLICY, MESSAGE_POLICY["channel"],
                          lambda: self.push(title, body),
                          extra={"read_id": notice["read_id"], "text_sha256": digest(notice["main_text"]),
                                 "body_sha256": digest(body)})


def runner_from_env() -> MarketWatchRunner | None:
    if not enabled():
        return None
    snapshots, store, outbox = (os.environ.get(k, "").strip() for k in
                                ("MARKET_WATCH_SNAPSHOTS_DIR", "MARKET_WATCH_STORE", "MARKET_WATCH_OUTBOX_DIR"))
    paths = [Path(p) for p in (snapshots, store, outbox) if p]
    if not snapshots or not store or any(not p.is_absolute() for p in paths):
        log.error("MARKET_WATCH_ENABLED needs absolute MARKET_WATCH_SNAPSHOTS_DIR and MARKET_WATCH_STORE; market watch stays off")
        return None
    return MarketWatchRunner(MarketWatchWakeStore(store), snapshots, outbox_dir=outbox or None)


# ----------------------------------------------------------------- report

def session_report(store: MarketWatchWakeStore, outcome_store=None) -> dict:
    """Wakes → reads → messages → outcomes per session, plus the MW-1 evaluator's score groups.

    Triggers are MW-2 event wakes that went out plus Jo's scheduled reads (#315).
    A read whose exported ``operation_id`` names its trigger
    (``mw-event-v1:<wake ID>``, ``mw-scheduled-v1:<date>:<HH:MM>``) is linked
    exactly; otherwise the first unclaimed read within the attribution window
    (and before the next trigger) is linked by time and labelled so.
    """
    exported_reads, outcomes, session_outcomes = [], [], []
    if outcome_store is not None:
        for export in outcome_store.imported_exports():
            exported_reads.extend(export["reads"])
        outcomes = outcome_store.outcomes()
        session_outcomes = outcome_store.session_outcomes()
    exported = {r["read_id"]: r for r in exported_reads}
    by_session: dict[str, dict] = {}
    rows = store.records()
    sessions = sorted({r["session_date"] for r in rows} | {r["session_date"] for r in exported_reads})
    window = timedelta(minutes=WAKE_POLICY["read_attribution_minutes"])
    for session in sessions:
        wakes = store.records("wake", session)
        wake_attempts = store.records("wake_attempt", session)
        notices = sorted(store.records("read_notice", session), key=lambda n: n["received_at"])
        decisions = store.records("message_decision", session)
        message_attempts = store.records("message_attempt", session)
        events = store.records("event", session)
        refusals = store.records("notice_refusal", session)
        read_times = {n["read_id"]: parse_time(n["received_at"]) for n in notices}
        operations = {}
        close_at = None
        for read in exported_reads:
            if read["session_date"] == session:
                read_times.setdefault(read["read_id"], parse_time(read["received_at"]))
                operations[read.get("operation_id")] = read["read_id"]
        for export in (outcome_store.imported_exports() if outcome_store is not None else []):
            for inp in export["inputs"]:
                if inp["snapshot_json"]["session_date"] == session and inp["snapshot_json"]["session_close_at"]:
                    close_at = parse_time(inp["snapshot_json"]["session_close_at"])
        day = date.fromisoformat(session)
        # Event wakes that went out, or may have (``unknown``), and Jo's scheduled reads can be answered by a read.
        triggers = sorted([(parse_time(a["occurred_at"]), a["wake_id"], f"{WAKE_POLICY['event_operation_prefix']}:{a['wake_id']}")
                           for a in wake_attempts if a["result"] in ("accepted", "unknown")] +
                          [(_at_local(day, slot), "scheduled:" + slot, f"{WAKE_POLICY['jo_scheduled_operation_prefix']}:{session}:{slot}")
                           for slot in WAKE_POLICY["jo_scheduled_local_times"] if close_at is None or _at_local(day, slot) < close_at])
        attributed: dict[str, tuple[str, str] | None] = {}
        claimed = set()
        for _, key, operation in triggers:
            if operations.get(operation):
                attributed[key] = (operations[operation], "operation_id")
                claimed.add(operations[operation])
        for index, (at, key, _) in enumerate(triggers):
            if key in attributed:
                continue
            until = min(at + window, triggers[index + 1][0] if index + 1 < len(triggers) else at + window)
            first = next((rid for rid, t in sorted(read_times.items(), key=lambda kv: kv[1]) if at <= t < until and rid not in claimed), None)
            attributed[key] = (first, "time_window") if first else None
            if first:
                claimed.add(first)
        wake_rows = []
        for wake in wakes:
            results = [a["result"] for a in wake_attempts if a["wake_id"] == wake["wake_id"]]
            delivery = next((r for r in TERMINAL if r in results), None) or ("failed_pending" if results else
                "pending" if wake["decision"] == "send" else "not_sent")
            read_id, link = attributed.get(wake["wake_id"]) or (None, None)
            outcome = "read" if read_id else "no_read" if delivery in ("accepted", "unknown") else (
                "recorded_failure" if delivery in ("expired", "failed_pending") else wake["decision"])
            wake_rows.append({"wake_id": wake["wake_id"], "trigger": wake["trigger"], "ref": wake["ref"], "due_at": wake["due_at"],
                              "decision": wake["decision"], "reason": wake["reason"], "delivery": delivery,
                              "attempts": results.count("sending"), "read_id": read_id, "attribution": link,
                              "outcome": outcome})
        scheduled_rows = []
        for _, key, _ in triggers:
            if key.startswith("scheduled:"):
                read_id, link = attributed.get(key) or (None, None)
                scheduled_rows.append({"slot": key.removeprefix("scheduled:"), "sent_by": "jo_scheduled_task (#315)",
                                       "read_id": read_id, "attribution": link, "outcome": "read" if read_id else "no_read_seen"})
        message_rows = []
        for d in decisions:
            results = [a for a in message_attempts if a["message_id"] == d["message_id"]]
            final = next((a for a in results if a["result"] in TERMINAL), None)
            message_rows.append({"message_id": d["message_id"], "read_id": d["read_id"], "is_correction": d["is_correction"],
                                 "decision": d["decision"], "reason": d["reason"], "budget_free": d.get("budget_free", False),
                                 "attempts": sum(a["result"] == "sending" for a in results),
                                 "delivery": final["result"] if final else ("failed_pending" if results else "pending" if d["decision"] == "send" else "not_sent"),
                                 "transport_receipt_id": final.get("transport_receipt_id") if final else None,
                                 "error_code": final.get("error_code") if final else None})
        session_reads = [rid for rid, _ in sorted(read_times.items(), key=lambda kv: kv[1])]
        read_outcomes = [o for o in outcomes if o["read_id"] in read_times]
        status_counts: dict[str, int] = {}
        for o in read_outcomes:
            status_counts[o["status"]] = status_counts.get(o["status"], 0) + 1
        notice_ids = {n["read_id"] for n in notices}
        mismatched = [n["read_id"] for n in notices if n["read_id"] in exported and exported[n["read_id"]]["content_sha256"] != n["read_sha256"]]
        triggered = wake_rows
        by_session[session] = {
            "events": {"total": len(events), "late": sum(e["late"] for e in events),
                       "by_kind": {k: sum(e["kind"] == k for e in events) for k in sorted({e["kind"] for e in events})}},
            "wakes": wake_rows,
            "scheduled_reads": scheduled_rows,
            "wake_summary": {"jo_scheduled_slots": len(scheduled_rows),
                             "jo_scheduled_with_read": sum(r["outcome"] == "read" for r in scheduled_rows),
                             "event_wakes_sent": sum(w["delivery"] == "accepted" for w in triggered),
                             "event_wakes_withheld": sum(w["decision"] != "send" for w in triggered),
                             "with_read": sum(w["outcome"] == "read" for w in wake_rows),
                             "without_read_or_failure": sum(w["outcome"] == "no_read" for w in wake_rows),
                             "recorded_failures": sum(w["outcome"] == "recorded_failure" for w in wake_rows)},
            "reads": {"total": len(session_reads), "attributed_to_wake": len(claimed),
                      "unprompted": len(session_reads) - len(claimed), "read_ids": session_reads,
                      "notices_missing_from_export": sorted(notice_ids - set(exported)) if outcome_store is not None else None,
                      "exported_without_notice": sorted(r for r in read_times if r in exported and r not in notice_ids),
                      "notice_hash_mismatches": mismatched,
                      "refused_notices": [{"file": r["file"], "reason": r["reason"]} for r in refusals]},
            "messages": message_rows,
            "message_summary": {"intents": len(message_rows),
                                "discretionary_accepted": sum(m["delivery"] == "accepted" and not m["is_correction"] for m in message_rows),
                                "corrections": sum(m["is_correction"] for m in message_rows),
                                "corrections_accepted": sum(m["delivery"] == "accepted" and m["is_correction"] for m in message_rows),
                                "suppressed_budget": sum(m["decision"] == "suppressed_budget" for m in message_rows),
                                "failed_or_expired": sum(m["delivery"] in ("expired", "failed_pending") or m["decision"] == "expired_before_send"
                                                         for m in message_rows),
                                "uncertain": sum(m["delivery"] == "unknown" for m in message_rows),
                                "budget": MESSAGE_POLICY["discretionary_per_session"],
                                "delivery_evidence": "ntfy accepted the push; phone display is not observed"},
            "outcomes": {"forecast_status_counts": status_counts,
                         "session_labels": [{"day_label": s["day_label"], "evaluation_revision": s["evaluation_revision"],
                                             "false_alarm": s["false_alarm"], "missed_before_noon": s["missed_before_noon"],
                                             "late_only": s["late_only"], "coverage_status": s["coverage_status"]}
                                            for s in session_outcomes if s["session_date"] == session]},
        }
    return {"policy_sha256": POLICY_SHA256, "detector_version": DETECTOR["detector_version"],
            "wake_policy_version": WAKE_POLICY["wake_policy_version"],
            "message_policy_version": MESSAGE_POLICY["message_policy_version"], "sessions": by_session,
            "scores": outcome_store.report(exported_reads) if outcome_store is not None else None,
            "limits": ["reads link to a trigger by operation_id when exported, else by time window; wakes with an unknown send count as sent",
                  "scheduled reads are #315's Jo task; MW-2 did not send them and cannot see a scheduled run that saved nothing",
                       "independence-unverified: reads are advice to Isaac and never feed Shadow Isaac or S1",
                       "message delivery is ntfy acceptance, not proof Isaac saw it; ratings are owner-reported"]}
