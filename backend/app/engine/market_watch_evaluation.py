"""Finite, offline MW-1 outcome evaluation and owner-export import.

This module deliberately accepts frozen bars from its caller. It never asks a
provider for continuation data and never rescans records automatically.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import sqlite3
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from market_watch_common import PROTOCOL, canonical, digest, verify, validate_snapshot


HORIZONS = ("30m", "60m", "close")
OUTCOME_SCHEMA = "market-watch-outcome-v1"
SESSION_SCHEMA = "market-watch-session-outcome-v1"
PRICE_BASIS = "split-consistent_non-dividend-adjusted"
APPLICATION_ID = 0x4D574F31  # MWO1: explicit, isolated MW owner outcome file.


class MarketWatchEvaluationError(ValueError):
    pass


def _time(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        result = value
    else:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None or result.utcoffset() is None:
        raise MarketWatchEvaluationError("timestamp must include an offset")
    return result.astimezone(timezone.utc)


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _bar(row: dict) -> dict:
    """Validate a minute bar. `start` is its timestamp; evaluation is at end."""
    required = ("start", "open", "high", "low", "close", "volume")
    if not isinstance(row, dict) or any(k not in row for k in required):
        raise MarketWatchEvaluationError("bar lacks exact timestamp/OHLCV fields")
    start = _time(row["start"])
    if start.second or start.microsecond:
        raise MarketWatchEvaluationError("bar timestamp must be an exact minute start")
    if any(not _finite(row[k]) for k in required[1:]):
        raise MarketWatchEvaluationError("bar values must be finite")
    if any(row[k] <= 0 for k in ("open", "high", "low", "close")):
        raise MarketWatchEvaluationError("bar prices must be positive")
    if row["high"] < max(row["open"], row["close"], row["low"]) or row["low"] > min(row["open"], row["close"], row["high"]):
        raise MarketWatchEvaluationError("bar OHLC values are inconsistent")
    if row["volume"] < 0:
        raise MarketWatchEvaluationError("bar volume cannot be negative")
    return {"start": start, "end": start + timedelta(minutes=1),
            "open": float(row["open"]), "high": float(row["high"]),
            "low": float(row["low"]), "close": float(row["close"]),
            "volume": float(row["volume"])}


def _manifest(bars: list[dict]) -> str:
    payload = [{"start": b["start"].isoformat(), "open": b["open"], "high": b["high"],
                "low": b["low"], "close": b["close"], "volume": b["volume"]} for b in bars]
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _source_manifest(source: dict | None, bars: list[dict]) -> dict:
    source = source or {}
    retrieved = source.get("retrieved_at")
    if retrieved is not None:
        _time(retrieved)
    latest_bar_end = max((b["end"] for b in bars), default=None)
    time_verified = retrieved is not None and (latest_bar_end is None or _time(retrieved) >= latest_bar_end)
    return {"provider": source.get("provider"), "feed": source.get("feed"),
            "adjustment": source.get("adjustment"), "price_basis": source.get("price_basis"),
            "retrieved_at": retrieved, "source_claim_matches_protocol": time_verified and source.get("provider") == "Alpaca" and
            source.get("feed") == "iex" and source.get("adjustment") == "split" and
            source.get("price_basis") == PRICE_BASIS,
            "bars_sha256": _manifest(bars)}


def _prices_at(bars: list[dict], at: datetime) -> dict | None:
    return next((b for b in bars if b["end"] == at), None)


def evaluate_forecast(read: dict, forecast: dict, bars: Iterable[dict], *,
                      session_open_at: str | datetime, session_close_at: str | datetime,
                      evaluated_at: str | datetime, comparator_probability: float | None = None,
                      bar_source: dict | None = None,
                      market_phase: str | None = None,
                      revision: int = 1, supersedes_outcome_id: str | None = None) -> dict:
    """Evaluate one frozen forecast using exact minute endpoints and path bars."""
    parsed = sorted((_bar(row) for row in bars), key=lambda b: b["start"])
    if len({b["start"] for b in parsed}) != len(parsed):
        raise MarketWatchEvaluationError("duplicate minute bars")
    received = _time(read["received_at"])
    now = _time(evaluated_at)
    horizon = forecast.get("horizon")
    if horizon not in HORIZONS:
        raise MarketWatchEvaluationError("unknown forecast horizon")
    probability = forecast.get("probability")
    if probability is not None and (not _finite(probability) or not 0 <= probability <= 1):
        raise MarketWatchEvaluationError("forecast probability must be null or in [0,1]")
    if comparator_probability is not None and (not _finite(comparator_probability) or not 0 <= comparator_probability <= 1):
        raise MarketWatchEvaluationError("comparator probability must be null or in [0,1]")
    source = _source_manifest(bar_source, parsed)
    if source["retrieved_at"] is not None and _time(source["retrieved_at"]) > now:
        source["source_claim_matches_protocol"] = False
    if session_open_at is None or session_close_at is None:
        bar_sha = digest({"source": source, "bars": _manifest(parsed)})
        result = {"schema_version": 1, "created_at": now.isoformat(),
                  "outcome_id": hashlib.sha256(f"{read['read_id']}:{horizon}:{read['protocol_id']}:{revision}:{bar_sha}".encode()).hexdigest()[:32],
                  "evaluation_revision": revision, "supersedes_outcome_id": supersedes_outcome_id,
                  "read_id": read["read_id"], "forecast_id": forecast["forecast_id"], "protocol_id": read["protocol_id"],
                  "horizon": horizon, "evaluated_at": now.isoformat(),
                  "status": "not_eligible" if market_phase in ("closed", "market_closed") else "unavailable",
                  "reason": "exchange_closed" if market_phase in ("closed", "market_closed") else "session_calendar_unavailable",
                  "anchor_at": None, "anchor_price": None,
                  "target_at": None, "target_price": None, "return": None, "outcome_y": None,
                  "probability": probability, "brier": None, "comparator_probability": comparator_probability,
                  "comparator_brier": None, "adverse_excursion": None, "favorable_excursion": None,
                  "path_status": "unavailable", "bar_manifest": {"source": source, "bars": [{"start": b["start"].isoformat(), "open": b["open"],
                      "high": b["high"], "low": b["low"], "close": b["close"], "volume": b["volume"]} for b in parsed],
                  }, "bar_manifest_sha256": bar_sha}
        result["content_sha256"] = digest(result)
        return result
    opening, closing = _time(session_open_at), _time(session_close_at)
    if any(b["start"] < opening or b["end"] > closing for b in parsed):
        raise MarketWatchEvaluationError("evaluation bars must be regular-session bars only")
    if horizon == "30m":
        target_offset = timedelta(minutes=30)
    elif horizon == "60m":
        target_offset = timedelta(minutes=60)
    else:
        target_offset = None
    # The reference close is determined by the receipt clock, never by the
    # first available row. A missing exact bar remains unavailable.
    next_close = received.replace(second=0, microsecond=0) + timedelta(minutes=1)
    anchor_at = next_close
    target_at = closing if target_offset is None else anchor_at + target_offset
    if comparator_probability is not None and (not _finite(comparator_probability) or not 0 <= comparator_probability <= 1):
        raise MarketWatchEvaluationError("comparator probability must be null or in [0,1]")
    out_of_session = received < opening or received >= closing
    not_eligible = (out_of_session or target_at <= anchor_at or target_at > closing)
    pending = not not_eligible and target_at is not None and now < target_at + timedelta(minutes=15)
    if pending:
        return {"status": "pending", "reason": "target_grace_period", "read_id": read["read_id"],
                "forecast_id": forecast["forecast_id"], "protocol_id": read["protocol_id"],
                "horizon": horizon, "anchor_at": anchor_at.isoformat() if anchor_at else None,
                "target_at": target_at.isoformat() if target_at else None,
                "evaluated_at": now.isoformat(), "evaluation_revision": revision}
    if not_eligible:
        status, reason = "not_eligible", "outside_regular_session_or_target"
    elif probability is None:
        status, reason = "abstained", forecast.get("abstention_reason") or "abstained"
    else:
        status, reason = "scored", None
    anchor_bar = _prices_at(parsed, anchor_at) if anchor_at else None
    target_bar = _prices_at(parsed, target_at) if target_at else None
    if status == "scored" and (anchor_bar is None or target_bar is None):
        status, reason = "unavailable", "exact_anchor_or_target_bar_missing"
    if status == "scored" and not source["source_claim_matches_protocol"]:
        status, reason = "unavailable", "bar_source_metadata_missing_or_mismatched"
    ret = target_bar["close"] / anchor_bar["close"] - 1 if anchor_bar and target_bar and anchor_bar["close"] > 0 else None
    if status == "scored" and ret is None:
        status, reason = "unavailable", "invalid_anchor_price"
    y = int(ret < 0) if ret is not None else None
    brier = (float(probability) - y) ** 2 if status == "scored" else None
    cbrier = (float(comparator_probability) - y) ** 2 if status == "scored" and comparator_probability is not None else None
    direction = read.get("view")
    path = [b for b in parsed if anchor_at and target_at and b["end"] > anchor_at and b["end"] <= target_at]
    # Missing interior minutes affect only path metrics, never endpoint scoring.
    expected = int((target_at - anchor_at).total_seconds() // 60) if anchor_at and target_at else 0
    contiguous = len(path) == expected and all(path[i]["end"] - path[i-1]["end"] == timedelta(minutes=1) for i in range(1, len(path)))
    mfe = mae = None
    if direction in ("up", "down") and anchor_bar and contiguous:
        sign = 1 if direction == "up" else -1
        favorable = [sign * (p / anchor_bar["close"] - 1) for bar in path for p in (bar["high"], bar["low"])]
        adverse = [-v for v in favorable]
        mfe, mae = max(0.0, max(favorable, default=0.0)), max(0.0, max(adverse, default=0.0))
    bar_sha = digest({"source": source, "bars": _manifest(parsed)})
    bar_manifest = [{"start": b["start"].isoformat(), "open": b["open"], "high": b["high"],
                     "low": b["low"], "close": b["close"], "volume": b["volume"]} for b in parsed]
    record = {"schema_version": 1, "created_at": now.isoformat(),
              "outcome_id": hashlib.sha256(f"{read['read_id']}:{horizon}:{read['protocol_id']}:{revision}:{bar_sha}".encode()).hexdigest()[:32],
              "evaluation_revision": revision, "supersedes_outcome_id": supersedes_outcome_id,
              "read_id": read["read_id"], "forecast_id": forecast["forecast_id"], "protocol_id": read["protocol_id"],
              "horizon": horizon, "evaluated_at": now.isoformat(), "status": status, "reason": reason,
              "anchor_at": anchor_at.isoformat() if anchor_at else None, "anchor_price": anchor_bar["close"] if anchor_bar else None,
              "target_at": target_at.isoformat() if target_at else None, "target_price": target_bar["close"] if target_bar else None,
              "return": ret, "outcome_y": y, "probability": probability, "brier": brier,
              "comparator_probability": comparator_probability, "comparator_brier": cbrier,
              "adverse_excursion": mae, "favorable_excursion": mfe,
              "path_status": "available" if contiguous else "missing_intermediate_bars",
              "bar_manifest": {"source": source, "bars": bar_manifest}, "bar_manifest_sha256": bar_sha}
    record["content_sha256"] = digest(record)
    return record


def session_diagnostic(*, session_date: str, read_rows: list[dict], today_bars: Iterable[dict],
                       prior_sessions: Iterable[dict], session_open_at: str | datetime,
                       session_close_at: str | datetime, protocol_id: str = "mw-v1",
                       market_phase: str | None = None,
                       bar_source: dict | None = None,
                       calendar_roster: Iterable[dict] | None = None,
                       evaluated_at: str | datetime | None = None,
                       revision: int = 1, supersedes_outcome_id: str | None = None) -> dict:
    """Compute the frozen directional day label and read-coverage diagnostics."""
    today = sorted((_bar(x) for x in today_bars), key=lambda b: b["start"])
    prior = list(prior_sessions)
    roster = list(calendar_roster or [])
    for row in roster:
        if (not isinstance(row, dict) or row.get("status") not in ("open", "closed") or
            not isinstance(row.get("session_date"), str)):
            raise MarketWatchEvaluationError("exchange calendar roster row is invalid")
        date.fromisoformat(row["session_date"])
        if row["status"] == "open":
            _time(row.get("open_at"))
            _time(row.get("close_at"))
        elif row.get("open_at") is not None or row.get("close_at") is not None:
            raise MarketWatchEvaluationError("closed calendar row must not contain session bounds")
    normalized_prior = []
    for day in prior:
        parsed_day = sorted((_bar(x) for x in day.get("bars", [])), key=lambda b: b["start"])
        normalized_prior.append({"session_date": day.get("session_date"), "session_open_at": day.get("session_open_at"),
            "session_close_at": day.get("session_close_at"), "previous_close": day.get("previous_close"),
            "bar_source": _source_manifest(day.get("bar_source"), parsed_day),
            "bars": [{"start": b["start"].isoformat(), "open": b["open"], "high": b["high"],
                      "low": b["low"], "close": b["close"], "volume": b["volume"]} for b in parsed_day]})
    today_manifest = [{"start": b["start"].isoformat(), "open": b["open"], "high": b["high"],
                       "low": b["low"], "close": b["close"], "volume": b["volume"]} for b in today]
    today_source = _source_manifest(bar_source, today)
    session_manifest = {"today_source": today_source, "today": today_manifest,
                        "prior_sessions": normalized_prior, "calendar_roster": roster}
    if session_open_at is None or session_close_at is None:
        result = {"schema_version": 1, "created_at": _time(evaluated_at).isoformat() if evaluated_at else datetime.now(timezone.utc).isoformat(),
                  "evaluation_revision": revision, "supersedes_outcome_id": supersedes_outcome_id,
                  "session_date": session_date, "protocol_id": protocol_id, "open": None, "close": None,
                  "high": None, "low": None, "prior_atr14": None,
                  "day_label": "unavailable",
                  "reason": "exchange_closed" if market_phase in ("closed", "market_closed") else "session_calendar_unavailable",
                  "first_directional_read_at": None,
                  "false_alarm": None, "opposite_direction": None, "missed_before_noon": None,
                  "late_only": None, "coverage_status": "manual_partial", "bar_manifest": session_manifest,
                  "bar_manifest_sha256": digest(session_manifest)}
        result["outcome_id"] = hashlib.sha256(f"session:{session_date}:{protocol_id}:{revision}:{result['bar_manifest_sha256']}".encode()).hexdigest()[:32]
        result["content_sha256"] = digest(result)
        return result
    opening, closing = _time(session_open_at), _time(session_close_at)
    reason = None
    atr = None
    ranges = []
    prior_session_close = None
    evaluated_time = _time(evaluated_at) if evaluated_at else datetime.now(timezone.utc)
    if (not today_source["source_claim_matches_protocol"] or
        (today_source["retrieved_at"] is not None and _time(today_source["retrieved_at"]) > evaluated_time)):
        reason = "bar_source_metadata_missing_or_mismatched"
    roster_by_date = {day.get("session_date"): day for day in roster if isinstance(day, dict)}
    roster_dates = sorted(roster_by_date)
    try:
        continuous = bool(roster_dates) and roster_dates == [(datetime.fromisoformat(roster_dates[0]).date() + timedelta(days=i)).isoformat()
            for i in range(len(roster_dates))]
    except (TypeError, ValueError):
        continuous = False
    if len(roster_by_date) != len(roster) or not continuous or session_date not in roster_by_date:
        reason = "exchange_calendar_roster_missing_or_invalid"
    elif roster_by_date[session_date].get("status") != "open":
        reason = "session_not_open_in_calendar_roster"
    elif (_time(roster_by_date[session_date].get("open_at")) != opening or
          _time(roster_by_date[session_date].get("close_at")) != closing):
        reason = "session_bounds_do_not_match_roster"
    if reason is None and len(prior) < 14:
        reason = "fewer_than_14_prior_sessions"
    elif reason is None:
        open_dates = [d for d in roster_dates if d < session_date and roster_by_date[d].get("status") == "open"]
        expected_dates = open_dates[-14:]
        if len(expected_dates) != 14:
            reason = "exchange_calendar_has_fewer_than_14_prior_sessions"
        days = prior[-14:]
        dates = [day.get("session_date") for day in days]
        if reason is None and dates != expected_dates:
            reason = "prior_sessions_do_not_match_exchange_calendar_roster"
        for day_idx, day in enumerate(days):
            if reason:
                break
            rows = sorted((_bar(x) for x in day["bars"]), key=lambda b: b["start"])
            start = _time(day.get("session_open_at"))
            end = _time(day.get("session_close_at"))
            cal_day = roster_by_date.get(day.get("session_date"), {})
            if cal_day.get("status") != "open" or _time(cal_day.get("open_at")) != start or _time(cal_day.get("close_at")) != end:
                reason = "prior_session_bounds_do_not_match_roster"
                break
            count = int((end - start).total_seconds() // 60)
            if (not rows or len(rows) != count or rows[0]["start"] != start or rows[-1]["end"] != end or
                any(rows[i]["end"] - rows[i - 1]["end"] != timedelta(minutes=1) for i in range(1, len(rows))) or
                not _finite(day.get("previous_close"))):
                reason = "prior_session_history_missing"
                break
            prior_source = _source_manifest(day.get("bar_source"), rows)
            normalized_prior[len(prior) - len(days) + day_idx]["bar_source"] = prior_source
            if (not prior_source["source_claim_matches_protocol"] or
                (prior_source["retrieved_at"] is not None and _time(prior_source["retrieved_at"]) > evaluated_time)):
                reason = "prior_session_source_metadata_missing_or_mismatched"
                break
            high, low = max(b["high"] for b in rows), min(b["low"] for b in rows)
            if prior_session_close is not None and not math.isclose(float(day["previous_close"]), prior_session_close, rel_tol=0, abs_tol=1e-9):
                reason = "prior_close_chain_mismatch"
                break
            ranges.append(max(high-low, abs(high-day["previous_close"]), abs(low-day["previous_close"])))
            prior_session_close = rows[-1]["close"]
        if reason is None:
            atr = sum(ranges) / 14
    regular = [b for b in today if b["start"] >= opening and b["end"] <= closing]
    if len(regular) != len(today):
        raise MarketWatchEvaluationError("session diagnostic bars must be regular-session bars only")
    high = max((b["high"] for b in regular), default=None)
    low = min((b["low"] for b in regular), default=None)
    openbar = _prices_at(today, opening + timedelta(minutes=1))
    closebar = _prices_at(today, closing)
    label = "unavailable"
    expected = int((closing - opening).total_seconds() // 60)
    complete_today = (len(regular) == expected and bool(regular) and regular[0]["start"] == opening and
                      regular[-1]["end"] == closing and all(regular[i]["end"] - regular[i - 1]["end"] == timedelta(minutes=1) for i in range(1, len(regular)))
                      and openbar is not None and closebar is not None)
    if reason is None and (not complete_today or high == low):
        reason = "session_bars_missing_or_zero_range"
    if reason is None:
        closepos = (closebar["close"] - low) / (high - low)
        move = closebar["close"] - openbar["open"]
        if move >= 0.5 * atr and closepos >= 0.70:
            label = "up_trend"
        elif -move >= 0.5 * atr and closepos <= 0.30:
            label = "down_trend"
        else:
            label = "chop"
    et = ZoneInfo("America/New_York")
    cutoff = min(datetime.combine(opening.astimezone(et).date(), datetime.min.time(), tzinfo=et).replace(hour=12).astimezone(timezone.utc), closing)
    directional = sorted((_time(r["received_at"]), r.get("view")) for r in read_rows
                         if r.get("view") in ("up", "down") and opening <= _time(r["received_at"]) < closing)
    first = directional[0][0] if directional else None
    trend = "up" if label == "up_trend" else "down" if label == "down_trend" else None
    result = {"schema_version": 1, "created_at": _time(evaluated_at).isoformat() if evaluated_at else datetime.now(timezone.utc).isoformat(),
              "evaluation_revision": revision, "supersedes_outcome_id": supersedes_outcome_id,
              "session_date": session_date, "protocol_id": protocol_id, "open": openbar["open"] if openbar else None,
              "close": closebar["close"] if closebar else None, "high": high, "low": low, "prior_atr14": atr,
              "day_label": label, "reason": reason, "first_directional_read_at": first.isoformat() if first else None,
              "false_alarm": bool(label == "chop" and first is not None),
              "opposite_direction": bool(trend and any(v != trend for _, v in directional)),
              "missed_before_noon": bool(trend and not any(v == trend and t < cutoff for t, v in directional)),
              "late_only": bool(trend and not any(v == trend and t < cutoff for t, v in directional) and any(v == trend and t >= cutoff for t, v in directional)),
              "coverage_status": "manual_partial", "bar_manifest": session_manifest,
              "bar_manifest_sha256": digest(session_manifest)}
    result["outcome_id"] = hashlib.sha256(f"session:{session_date}:{protocol_id}:{revision}:{result['bar_manifest_sha256']}".encode()).hexdigest()[:32]
    result["content_sha256"] = digest(result)
    return result


_SCHEMA = """
CREATE TABLE IF NOT EXISTS imported_export(export_id TEXT PRIMARY KEY, actor TEXT NOT NULL, export_sha256 TEXT NOT NULL,
  export_json TEXT NOT NULL, imported_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS evaluation(outcome_id TEXT PRIMARY KEY, read_id TEXT NOT NULL, forecast_id TEXT NOT NULL,
  horizon TEXT NOT NULL, revision INTEGER NOT NULL, payload TEXT NOT NULL, UNIQUE(read_id,forecast_id,revision));
CREATE TABLE IF NOT EXISTS session_evaluation(outcome_id TEXT PRIMARY KEY, session_date TEXT NOT NULL,
  revision INTEGER NOT NULL, payload TEXT NOT NULL, UNIQUE(session_date,revision));
CREATE TRIGGER IF NOT EXISTS evaluation_no_update BEFORE UPDATE ON evaluation BEGIN SELECT RAISE(ABORT,'immutable evaluation'); END;
CREATE TRIGGER IF NOT EXISTS evaluation_no_delete BEFORE DELETE ON evaluation BEGIN SELECT RAISE(ABORT,'immutable evaluation'); END;
CREATE TRIGGER IF NOT EXISTS session_evaluation_no_update BEFORE UPDATE ON session_evaluation BEGIN SELECT RAISE(ABORT,'immutable evaluation'); END;
CREATE TRIGGER IF NOT EXISTS session_evaluation_no_delete BEFORE DELETE ON session_evaluation BEGIN SELECT RAISE(ABORT,'immutable evaluation'); END;
CREATE TRIGGER IF NOT EXISTS import_no_update BEFORE UPDATE ON imported_export BEGIN SELECT RAISE(ABORT,'immutable import'); END;
CREATE TRIGGER IF NOT EXISTS import_no_delete BEFORE DELETE ON imported_export BEGIN SELECT RAISE(ABORT,'immutable import'); END;
CREATE TRIGGER IF NOT EXISTS evaluation_no_replace BEFORE INSERT ON evaluation
  WHEN EXISTS(SELECT 1 FROM evaluation WHERE outcome_id=NEW.outcome_id OR (read_id=NEW.read_id AND forecast_id=NEW.forecast_id AND revision=NEW.revision))
  BEGIN SELECT RAISE(ABORT,'immutable evaluation'); END;
CREATE TRIGGER IF NOT EXISTS session_evaluation_no_replace BEFORE INSERT ON session_evaluation
  WHEN EXISTS(SELECT 1 FROM session_evaluation WHERE outcome_id=NEW.outcome_id OR (session_date=NEW.session_date AND revision=NEW.revision))
  BEGIN SELECT RAISE(ABORT,'immutable evaluation'); END;
CREATE TRIGGER IF NOT EXISTS import_no_replace BEFORE INSERT ON imported_export
  WHEN EXISTS(SELECT 1 FROM imported_export WHERE export_id=NEW.export_id)
  BEGIN SELECT RAISE(ABORT,'immutable import'); END;
"""


class MarketWatchOutcomeStore:
    """Explicit owner-selected app-side SQLite file for exports and outcomes."""
    def __init__(self, path: str | Path):
        self.path = Path(path)
        if not self.path.is_absolute():
            raise MarketWatchEvaluationError("outcome store path must be absolute")
        if self.path.exists() and self.path.is_symlink():
            raise MarketWatchEvaluationError("outcome store may not be a symlink")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            marker = db.execute("PRAGMA application_id").fetchone()[0]
            version = db.execute("PRAGMA user_version").fetchone()[0]
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
            expected = {"imported_export", "evaluation", "session_evaluation"}
            if marker == 0 and not tables and version == 0:
                db.execute(f"PRAGMA application_id={APPLICATION_ID}")
                db.execute("PRAGMA user_version=1")
            elif marker != APPLICATION_ID or version != 1 or tables != expected:
                raise MarketWatchEvaluationError("refusing to adopt a non-MW outcome database")
            db.executescript(_SCHEMA)

    def _db(self):
        db = sqlite3.connect(self.path, timeout=10, isolation_level="IMMEDIATE")
        db.row_factory = sqlite3.Row
        return db

    def import_export(self, export: dict) -> bool:
        """Validate the narrow sealed export and persist once; return replay flag."""
        if not isinstance(export, dict) or not {"export_id", "actor", "protocol_id", "inputs", "reads", "comparators", "messages", "content_sha256"} <= export.keys() or export.keys() - {"export_id", "actor", "protocol_id", "inputs", "reads", "comparators", "messages", "content_sha256", "schema_version", "created_at"}:
            raise MarketWatchEvaluationError("export shape is invalid")
        try:
            verify(export)
        except Exception as exc:
            raise MarketWatchEvaluationError("export envelope hash is invalid") from exc
        if export["protocol_id"] != PROTOCOL.get("protocol_id", "mw-v1"):
            raise MarketWatchEvaluationError("export protocol mismatch")
        actor = export["actor"]
        if not isinstance(actor, str) or not actor:
            raise MarketWatchEvaluationError("export actor is invalid")
        collections = {key: export[key] for key in ("inputs", "reads", "comparators", "messages")}
        if export.get("export_id") != "mwx_" + digest(collections):
            raise MarketWatchEvaluationError("export identity does not match its contents")
        export_sha = export["content_sha256"]
        maps = {}
        for key in ("inputs", "reads", "comparators", "messages"):
            values = export[key]
            if not isinstance(values, list):
                raise MarketWatchEvaluationError("export collection is invalid")
            maps[key] = {}
            for item in values:
                try:
                    verify(item)
                except Exception as exc:
                    raise MarketWatchEvaluationError(f"sealed {key} record failed verification") from exc
                if item.get("actor") != actor or item.get("protocol_id", export["protocol_id"]) != export["protocol_id"]:
                    raise MarketWatchEvaluationError("cross-actor or protocol reference")
                ident = item.get({"inputs": "input_id", "reads": "read_id", "comparators": "comparator_id", "messages": "event_id"}[key])
                if not isinstance(ident, str) or ident in maps[key]:
                    raise MarketWatchEvaluationError("duplicate or missing export identity")
                prefix = {"inputs": "mwi_", "reads": "mwr_", "comparators": "mwc_", "messages": "mwe_"}[key]
                suffix = ident[len(prefix):] if ident.startswith(prefix) else ""
                try:
                    valid_uuid = str(__import__("uuid").UUID(suffix)) == suffix
                except ValueError:
                    valid_uuid = False
                if not valid_uuid:
                    raise MarketWatchEvaluationError("forged export identity")
                maps[key][ident] = item
        for inp in maps["inputs"].values():
            snap = inp.get("snapshot_json")
            if not isinstance(snap, dict):
                raise MarketWatchEvaluationError("input snapshot hash mismatch")
            try:
                validate_snapshot(snap)
            except Exception as exc:
                raise MarketWatchEvaluationError("input snapshot hash mismatch") from exc
            if snap.get("content_sha256") != inp.get("snapshot_sha256"):
                raise MarketWatchEvaluationError("input snapshot hash mismatch")
        if (len(maps["comparators"]) != len(maps["reads"]) or
            {c.get("read_id") for c in maps["comparators"].values()} != set(maps["reads"])):
            raise MarketWatchEvaluationError("comparator set does not match exported reads")
        for read in maps["reads"].values():
            suffix = read["read_id"].removeprefix("mwr_")
            try:
                if str(__import__("uuid").UUID(suffix)) != suffix:
                    raise ValueError
            except ValueError as exc:
                raise MarketWatchEvaluationError("read identity is invalid") from exc
            inp = maps["inputs"].get(read.get("input_id"))
            if not inp or read.get("snapshot_sha256") != inp.get("snapshot_sha256") or read.get("snapshot_id") != inp["snapshot_json"].get("snapshot_id"):
                raise MarketWatchEvaluationError("read input link is invalid")
            if read.get("session_date") != inp["snapshot_json"].get("session_date"):
                raise MarketWatchEvaluationError("read session does not match its input")
            if len(read.get("forecasts", [])) != 3 or {f.get("horizon") for f in read["forecasts"]} != set(HORIZONS):
                raise MarketWatchEvaluationError("read forecast slots are invalid")
            for f in read["forecasts"]:
                if (f.get("forecast_id") != read["read_id"] + ":" + f.get("horizon", "") or
                    f.get("predicate") != "spy_return_lt_zero" or
                    (f.get("probability") is None and not f.get("abstention_reason")) or
                    (f.get("probability") is not None and (not _finite(f["probability"]) or not 0 <= f["probability"] <= 1))):
                    raise MarketWatchEvaluationError("forecast definition is invalid")
            comp = next((c for c in maps["comparators"].values() if c.get("read_id") == read["read_id"]), None)
            if not comp:
                raise MarketWatchEvaluationError("read comparator is missing")
            probabilities = comp.get("probabilities")
            if (not isinstance(probabilities, dict) or set(probabilities) != set(HORIZONS) or
                comp.get("snapshot_sha256") != read.get("snapshot_sha256")):
                raise MarketWatchEvaluationError("comparator probabilities are invalid")
            if any(v is not None and (not _finite(v) or not 0 <= v <= 1) for v in probabilities.values()):
                raise MarketWatchEvaluationError("comparator probability is invalid")
        read_order = {read_id: index for index, read_id in enumerate(maps["reads"])}
        for read in maps["reads"].values():
            for ref in (read.get("previous_read_id"), read.get("correction_of_read_id")):
                if ref is not None:
                    parent = maps["reads"].get(ref)
                    if (not parent or parent.get("session_date") != read.get("session_date")
                            or read_order[ref] >= read_order[read["read_id"]]
                            or _time(parent["received_at"]) > _time(read["received_at"])):
                        raise MarketWatchEvaluationError("read parent reference is invalid")
        for message in maps["messages"].values():
            if message.get("read_id") not in maps["reads"] or message.get("actor") != actor:
                raise MarketWatchEvaluationError("message references an unknown read")
            suffix = message.get("message_id", "").removeprefix("mwm_")
            try:
                if not suffix or str(__import__("uuid").UUID(suffix)) != suffix:
                    raise ValueError
            except ValueError as exc:
                raise MarketWatchEvaluationError("message identity is invalid") from exc
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM imported_export WHERE actor<>? LIMIT 1", (actor,)).fetchone():
                raise MarketWatchEvaluationError("outcome store is bound to a different owner actor")
            old = db.execute("SELECT export_sha256,export_json FROM imported_export WHERE export_id=?", (export["export_id"],)).fetchone()
            if old:
                if old[0] != export_sha or old[1] != canonical(export).decode():
                    raise MarketWatchEvaluationError("export ID conflicts with prior import")
                return True
            db.execute("INSERT INTO imported_export VALUES(?,?,?,?,?)", (export["export_id"], actor, export_sha,
                       canonical(export).decode(), datetime.now(timezone.utc).isoformat()))
        return False

    def append_evaluations(self, outcomes: Iterable[dict]) -> int:
        """Append deterministic terminal rows; identical repeats do not duplicate."""
        inserted = 0
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            for outcome in outcomes:
                if outcome.get("status") == "pending":
                    continue
                if outcome.get("content_sha256") != digest({k: v for k, v in outcome.items() if k != "content_sha256"}):
                    raise MarketWatchEvaluationError("outcome hash mismatch")
                payload = canonical(outcome).decode()
                existing = db.execute("SELECT outcome_id,payload FROM evaluation WHERE read_id=? AND forecast_id=? AND revision=?",
                                      (outcome["read_id"], outcome["forecast_id"], outcome["evaluation_revision"])).fetchone()
                if existing:
                    if existing["outcome_id"] != outcome["outcome_id"] or existing["payload"] != payload:
                        raise MarketWatchEvaluationError("evaluation revision already exists with different content")
                    continue
                previous = db.execute("SELECT outcome_id,revision FROM evaluation WHERE read_id=? AND forecast_id=? ORDER BY revision DESC LIMIT 1",
                                      (outcome["read_id"], outcome["forecast_id"])).fetchone()
                if previous is None:
                    if outcome["evaluation_revision"] != 1 or outcome.get("supersedes_outcome_id") is not None:
                        raise MarketWatchEvaluationError("initial evaluation revision must be 1")
                elif outcome["evaluation_revision"] != previous["revision"] + 1 or outcome.get("supersedes_outcome_id") != previous["outcome_id"]:
                    raise MarketWatchEvaluationError("corrected evaluation must supersede latest revision")
                cur = db.execute("INSERT OR IGNORE INTO evaluation VALUES(?,?,?,?,?,?)",
                                  (outcome["outcome_id"], outcome["read_id"], outcome["forecast_id"],
                                   outcome["horizon"], outcome["evaluation_revision"], payload))
                if cur.rowcount:
                    inserted += 1
                else:
                    prior = db.execute("SELECT payload FROM evaluation WHERE outcome_id=?", (outcome["outcome_id"],)).fetchone()
                    if prior is None or prior[0] != payload:
                        raise MarketWatchEvaluationError("outcome identity conflicts")
        return inserted

    def append_session_evaluations(self, outcomes: Iterable[dict]) -> int:
        inserted = 0
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            for outcome in outcomes:
                if outcome.get("content_sha256") != digest({k: v for k, v in outcome.items() if k != "content_sha256"}):
                    raise MarketWatchEvaluationError("session outcome hash mismatch")
                payload = canonical(outcome).decode()
                existing = db.execute("SELECT outcome_id,payload FROM session_evaluation WHERE session_date=? AND revision=?",
                                      (outcome["session_date"], outcome["evaluation_revision"])).fetchone()
                if existing:
                    if existing["outcome_id"] != outcome["outcome_id"] or existing["payload"] != payload:
                        raise MarketWatchEvaluationError("session revision already exists with different content")
                    continue
                previous = db.execute("SELECT outcome_id,revision FROM session_evaluation WHERE session_date=? ORDER BY revision DESC LIMIT 1",
                                      (outcome["session_date"],)).fetchone()
                if previous is None:
                    if outcome["evaluation_revision"] != 1 or outcome.get("supersedes_outcome_id") is not None:
                        raise MarketWatchEvaluationError("initial session revision must be 1")
                elif outcome["evaluation_revision"] != previous["revision"] + 1 or outcome.get("supersedes_outcome_id") != previous["outcome_id"]:
                    raise MarketWatchEvaluationError("corrected session evaluation must supersede latest revision")
                cur = db.execute("INSERT OR IGNORE INTO session_evaluation VALUES(?,?,?,?)",
                                 (outcome["outcome_id"], outcome["session_date"], outcome["evaluation_revision"], payload))
                if cur.rowcount:
                    inserted += 1
                else:
                    prior = db.execute("SELECT payload FROM session_evaluation WHERE outcome_id=?", (outcome["outcome_id"],)).fetchone()
                    if prior is None or prior[0] != payload:
                        raise MarketWatchEvaluationError("session outcome identity conflicts")
        return inserted

    def evaluate_export(self, export: dict, *, bars_by_session: dict[str, Iterable[dict]],
                        evaluated_at: str | datetime,
                        prior_sessions_by_date: dict[str, Iterable[dict]] | None = None,
                        calendar_roster_by_date: dict[str, Iterable[dict]] | None = None,
                        bar_source_by_date: dict[str, dict] | None = None) -> dict:
        """Import then manually evaluate the exact exported read cohort once.

        The caller supplies finite, already-frozen SPY bars and prior complete
        sessions. There is no data adapter or automatic rescore path here.
        """
        import_replayed = self.import_export(export)
        reads = export["reads"]
        inputs = {item["input_id"]: item for item in export["inputs"]}
        comparators = {item["read_id"]: item for item in export["comparators"]}
        outcomes = []
        existing_outcomes = {(o["read_id"], o["forecast_id"], o["evaluation_revision"]): o for o in self.outcomes()}
        session_rows: dict[str, list[dict]] = {}
        normalized_bars = {day: list(rows) for day, rows in bars_by_session.items()}
        bar_source_by_date = bar_source_by_date or {}
        for read in reads:
            snap = inputs[read["input_id"]]["snapshot_json"]
            session_rows.setdefault(read["session_date"], []).append(read)
            bars = normalized_bars.get(read["session_date"], ())
            comparator = comparators[read["read_id"]]
            for forecast in read["forecasts"]:
                existing = existing_outcomes.get((read["read_id"], forecast["forecast_id"], 1))
                if existing:
                    outcomes.append(existing)
                    continue
                cp = comparator["probabilities"].get(forecast["horizon"])
                outcomes.append(evaluate_forecast(read, forecast, bars,
                    session_open_at=snap["session_open_at"], session_close_at=snap["session_close_at"],
                    evaluated_at=evaluated_at, comparator_probability=cp, market_phase=snap.get("market_phase"),
                    bar_source=bar_source_by_date.get(read["session_date"])))
        count = self.append_evaluations(outcomes)
        session_outcomes = []
        prior_sessions_by_date = prior_sessions_by_date or {}
        calendar_roster_by_date = calendar_roster_by_date or {}
        existing_sessions = {(o["session_date"], o["evaluation_revision"]): o for o in self.session_outcomes()}
        for session_date, day_reads in session_rows.items():
            if (session_date, 1) in existing_sessions:
                session_outcomes.append(existing_sessions[(session_date, 1)])
                continue
            snap = inputs[day_reads[-1]["input_id"]]["snapshot_json"]
            if (snap["session_close_at"] is not None and
                _time(evaluated_at) < _time(snap["session_close_at"]) + timedelta(minutes=15)):
                continue
            session_outcomes.append(session_diagnostic(session_date=session_date, read_rows=day_reads,
                today_bars=normalized_bars.get(session_date, ()), prior_sessions=prior_sessions_by_date.get(session_date, ()),
                session_open_at=snap["session_open_at"], session_close_at=snap["session_close_at"], protocol_id=export["protocol_id"],
                market_phase=snap.get("market_phase"), bar_source=bar_source_by_date.get(session_date),
                calendar_roster=calendar_roster_by_date.get(session_date, ()),
                evaluated_at=evaluated_at))
        session_count = self.append_session_evaluations(session_outcomes)
        return {"import_replayed": import_replayed, "outcomes": outcomes, "session_outcomes": session_outcomes,
                "inserted_outcomes": count, "inserted_session_outcomes": session_count}

    def outcomes(self) -> list[dict]:
        with self._db() as db:
            return [json.loads(row[0]) for row in db.execute("SELECT payload FROM evaluation ORDER BY read_id,horizon,revision")]

    def session_outcomes(self) -> list[dict]:
        with self._db() as db:
            return [json.loads(row[0]) for row in db.execute("SELECT payload FROM session_evaluation ORDER BY session_date,revision")]

    def imported_exports(self) -> list[dict]:
        """Return the exact verified owner exports retained for reproducibility."""
        with self._db() as db:
            return [json.loads(row[0]) for row in db.execute("SELECT export_json FROM imported_export ORDER BY imported_at,export_id")]

    def report(self, reads: Iterable[dict], *, protocol_id: str | None = None) -> dict:
        """Coverage, fixed calibration bins and paired scores, split by revision."""
        outcomes = self.outcomes()
        read_by_id = {r["read_id"]: r for r in reads}
        slots = {(r["read_id"], f["forecast_id"]): (r, f) for r in read_by_id.values() for f in r.get("forecasts", [])}
        selected = [o for o in outcomes if (o["read_id"], o["forecast_id"]) in slots and
                    (protocol_id is None or o["protocol_id"] == protocol_id)]
        groups: dict[tuple, dict] = {}

        def group_for(horizon, proto, model, prompt, revision):
            key = (horizon, proto, model, prompt, revision)
            return groups.setdefault(key, {"submitted": 0, "scored": 0, "abstained": 0, "ineligible": 0,
                "unavailable": 0, "pending": 0, "brier_sum": 0.0, "jo_brier_sum": 0.0,
                "baseline_brier_sum": 0.0, "bins": [{"count": 0, "probability_sum": 0.0, "outcome_sum": 0.0} for _ in range(10)],
                "paired_count": 0, "paired_jo_brier_sum": 0.0, "paired_comparator_brier_sum": 0.0,
                "excluded_comparator": 0, "stale_input_count": 0, "quality_flags": [], "quality_flag_counts": {}})

        def add_quality_flags(group, read):
            flags = read.get("quality_flags", [])
            for flag in flags:
                if flag not in group["quality_flags"]:
                    group["quality_flags"].append(flag)
                group["quality_flag_counts"][flag] = group["quality_flag_counts"].get(flag, 0) + 1
            if any(flag == "snapshot-stale" or str(flag).lower().endswith(":stale") for flag in flags):
                group["stale_input_count"] += 1

        for r, f in slots.values():
            if protocol_id is not None and r["protocol_id"] != protocol_id:
                continue
            g = group_for(f["horizon"], r["protocol_id"], r.get("model_id") or "unknown",
                          r.get("prompt_version") or "unknown", 1)
            g["submitted"] += 1
            add_quality_flags(g, r)
        for o in selected:
            r, f = slots[(o["read_id"], o["forecast_id"])]
            revision = o["evaluation_revision"]
            g = group_for(o["horizon"], o["protocol_id"], r.get("model_id") or "unknown",
                          r.get("prompt_version") or "unknown", revision)
            if revision > 1:
                g["submitted"] += 1
                add_quality_flags(g, r)
            if o["status"] == "scored":
                g["scored"] += 1
                g["brier_sum"] += o["brier"]
                g["baseline_brier_sum"] += (0.5 - o["outcome_y"]) ** 2
                p = o["probability"]
                jo_brier = (p - o["outcome_y"]) ** 2
                g["jo_brier_sum"] += jo_brier
                idx = min(9, int(p * 10))
                g["bins"][idx]["count"] += 1
                g["bins"][idx]["probability_sum"] += p
                g["bins"][idx]["outcome_sum"] += o["outcome_y"]
                if o["comparator_brier"] is None:
                    g["excluded_comparator"] += 1
                else:
                    g["paired_count"] += 1
                    g["paired_jo_brier_sum"] += jo_brier
                    g["paired_comparator_brier_sum"] += o["comparator_brier"]
            elif o["status"] == "abstained":
                g["abstained"] += 1
            elif o["status"] == "not_eligible":
                g["ineligible"] += 1
            elif o["status"] == "unavailable":
                g["unavailable"] += 1
        for g in groups.values():
            g["pending"] = max(0, g["submitted"] - g["scored"] - g["abstained"] - g["ineligible"] - g["unavailable"])
            g["brier"] = g["brier_sum"] / g["scored"] if g["scored"] else None
            g["comparator_brier"] = g["paired_comparator_brier_sum"] / g["paired_count"] if g["paired_count"] else None
            g["jo_brier"] = g["jo_brier_sum"] / g["scored"] if g["scored"] else None
            g["no_information_brier"] = g["baseline_brier_sum"] / g["scored"] if g["scored"] else None
            g["paired_jo_brier"] = g["paired_jo_brier_sum"] / g["paired_count"] if g["paired_count"] else None
            g["paired_comparator_brier"] = g["paired_comparator_brier_sum"] / g["paired_count"] if g["paired_count"] else None
            g["calibration_bins"] = [{"range": f"[{i/10:.1f},{(i+1)/10:.1f}{']' if i == 9 else ')'}", **b,
                "mean_probability": b["probability_sum"] / b["count"] if b["count"] else None,
                "observed_rate": b["outcome_sum"] / b["count"] if b["count"] else None} for i, b in enumerate(g.pop("bins"))]
        session_groups = {}
        for outcome in self.session_outcomes():
            if protocol_id is not None and outcome["protocol_id"] != protocol_id:
                continue
            key = (outcome["protocol_id"], outcome["evaluation_revision"])
            g = session_groups.setdefault(key, {"sessions": 0, "available_labels": 0, "unavailable_labels": 0,
                "false_alarms": 0, "opposite_direction": 0, "missed_before_noon": 0, "late_only": 0,
                "manual_partial_sessions": 0})
            g["sessions"] += 1
            g["available_labels"] += int(outcome["day_label"] in ("up_trend", "down_trend", "chop"))
            g["unavailable_labels"] += int(outcome["day_label"] == "unavailable")
            g["false_alarms"] += int(outcome["false_alarm"] is True)
            g["opposite_direction"] += int(outcome["opposite_direction"] is True)
            g["missed_before_noon"] += int(outcome["missed_before_noon"] is True)
            g["late_only"] += int(outcome["late_only"] is True)
            g["manual_partial_sessions"] += int(outcome["coverage_status"] == "manual_partial")
        for g in session_groups.values():
            g["whole_day_miss_rate"] = None  # MW-1 has no wake-failure observation roster.
        return {"groups": [{"horizon": k[0], "protocol_id": k[1], "model_id": k[2], "prompt_version": k[3],
                             "evaluation_revision": k[4], **v} for k, v in sorted(groups.items())],
                "session_groups": [{"protocol_id": k[0], "evaluation_revision": k[1], **v} for k, v in sorted(session_groups.items())],
                "total_submitted_slots": len(slots), "revision_coverage": sum(g["submitted"] for g in groups.values()),
                "paired_exclusions": sum(g["excluded_comparator"] for g in groups.values()),
                "revision_policy": "original and corrected revisions are reported in separate cohorts"}
