"""Manual MW-1 snapshot producer and content-addressed public file exchange.

The producer has no scheduler. Source readers are injectable so contract tests
never invoke providers; runtime reads only the existing Alpaca/VIX/calendar/news
sources already used by TradeJournal.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
import json
import os
from pathlib import Path
import tempfile
from typing import Callable
import fcntl
from market_watch_common import PROTOCOL, PROTOCOL_SHA256, digest, parse_time, previous_session_date, seal, session_bounds, validate_snapshot, verify

ET_NAME = "America/New_York"


def _time(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("source timestamp must be timezone-aware")
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _raw_time(value) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("source timestamp must be timezone-aware")
        return value.astimezone(UTC)
    return parse_time(str(value))


def _stamp_group(source: str, observed_at, retrieved_at: datetime, payload, *, limit: int, active: bool, reason=None):
    observed = _raw_time(observed_at) if observed_at else None
    retrieved = retrieved_at.astimezone(UTC)
    age = max(0, (retrieved - observed).total_seconds()) if observed else None
    status = "missing" if observed is None else "stale" if active and age > limit else "fresh"
    if reason:
        status = "missing"
    return {"source": source, "observed_at": _time(observed) if observed else None,
            "retrieved_at": _time(retrieved), "age_seconds": age, "status": status,
            "reason": reason or ("observation_time_unknown" if observed is None else None),
            "source_sha256": digest(payload)}


def _bar(row: dict) -> dict:
    start = _raw_time(row["t"])
    return {"start": _time(start), "end": _time(start + timedelta(minutes=1)),
            "open": float(row["o"]), "high": float(row["h"]), "low": float(row["l"]),
            "close": float(row["c"]), "volume": float(row["v"])}


def _session_bars(rows: list[dict], opened: datetime, cutoff: datetime) -> list[dict]:
    bars = []
    for row in rows:
        try:
            item = _bar(row)
        except (KeyError, TypeError, ValueError):
            continue
        start, end = parse_time(item["start"]), parse_time(item["end"])
        if start >= opened and end <= cutoff:
            bars.append(item)
    bars.sort(key=lambda item: item["start"])
    if any(bar["start"] == bars[i - 1]["start"] for i, bar in enumerate(bars) if i):
        raise ValueError("duplicate_minute_bar")
    return bars


def _index(symbol: str, rows: list[dict], raw_rows: list[dict], prior_close: dict | None,
           opened: datetime, cutoff: datetime, retrieved: datetime, rth: bool) -> tuple[dict, list[dict]]:
    bars = _session_bars(rows, opened, cutoff)
    gaps = []
    last = bars[-1] if bars else None
    opening_bar = bars[0] if bars and parse_time(bars[0]["start"]) == opened else None
    price = {"value": last["close"] if last else None, "at": last["end"] if last else None,
             "status": "fresh" if last and (retrieved - parse_time(last["end"])).total_seconds() <= 180 else "stale" if last else "missing",
             "reason": None if last else "no_completed_regular_session_bar"}
    opening_complete = len(bars) >= 15 and all(parse_time(bars[i]["start"]) == opened + timedelta(minutes=i) for i in range(15))
    complete_path = bool(bars) and parse_time(bars[0]["start"]) == opened and all(
        parse_time(bars[i]["start"]) == parse_time(bars[i - 1]["start"]) + timedelta(minutes=1)
        for i in range(1, len(bars)))
    if not bars:
        observed = None
    else:
        observed = last["end"]
    retrieved_s = _time(retrieved)
    status = "missing" if not bars else "stale" if price["status"] == "stale" else "fresh"
    vwap = None
    volume = sum(bar["volume"] for bar in bars)
    if bars and volume > 0 and complete_path:
        vwap = sum(((bar["high"] + bar["low"] + bar["close"]) / 3) * bar["volume"] for bar in bars) / volume
    or_status = "not_ready" if cutoff < opened + timedelta(minutes=15) else "fresh" if opening_complete else "missing"
    group = {"symbol": symbol, "source": "Alpaca IEX", "observed_at": observed,
             "retrieved_at": retrieved_s, "age_seconds": max(0, (retrieved - parse_time(observed)).total_seconds()) if observed else None,
             "status": status, "reason": None if bars else "no_completed_regular_session_bar",
             "source_sha256": digest(bars), "price": price,
             "prior_close": prior_close or {"value": None, "at": None, "status": "missing", "reason": "prior_close_unavailable"},
             "session_open": {"value": opening_bar["open"] if opening_bar else None, "at": opening_bar["start"] if opening_bar else None,
                              "status": "fresh" if opening_bar else "missing", "reason": None if opening_bar else "session_open_bar_missing"},
             "bar_1m": last, "vwap": {"value": vwap, "status": status if vwap is not None else "missing",
                                         "reason": None if vwap is not None else "missing_minute_bar_or_nonpositive_volume"},
             "or15_high": {"value": max((bar["high"] for bar in bars[:15]), default=None) if opening_complete else None, "status": or_status,
                           "reason": None if or_status == "fresh" else "opening_range_incomplete" if or_status == "not_ready" else "opening_range_bar_gap"},
             "or15_low": {"value": min((bar["low"] for bar in bars[:15]), default=None) if opening_complete else None, "status": or_status,
                          "reason": None if or_status == "fresh" else "opening_range_incomplete" if or_status == "not_ready" else "opening_range_bar_gap"},
             "return_vs_prior_close": ((last["close"] / prior_close["value"] - 1) if last and prior_close and prior_close.get("value") else None),
             "distance_to_vwap": ((last["close"] / vwap - 1) if last and vwap else None),
             "bars_5m": []}
    # Keep at most 12 completed 5-minute buckets; partial buckets never qualify.
    by_start = {parse_time(bar["start"]): bar for bar in bars}
    for offset in range(0, max(0, int((cutoff - opened).total_seconds() // 60) - 4), 5):
        starts = [opened + timedelta(minutes=offset+i) for i in range(5)]
        if any(start not in by_start for start in starts):
            continue
        chunk = [by_start[start] for start in starts]
        group["bars_5m"].append({"start": chunk[0]["start"], "end": chunk[-1]["end"], "open": chunk[0]["open"],
                                "high": max(x["high"] for x in chunk), "low": min(x["low"] for x in chunk),
                                "close": chunk[-1]["close"], "volume": sum(x["volume"] for x in chunk)})
    group["bars_5m"] = group["bars_5m"][-12:]
    if status != "fresh":
        gaps.append({"group": f"indices.{symbol}", "reason": group["reason"] or "stale_price_bar"})
    if opening_bar is None:
        gaps.append({"group": f"indices.{symbol}.session_open", "reason": "session_open_bar_missing"})
    if vwap is None:
        gaps.append({"group": f"indices.{symbol}.vwap", "reason": group["vwap"]["reason"]})
    if or_status != "fresh":
        gaps.append({"group": f"indices.{symbol}.opening_range", "reason": group["or15_high"]["reason"]})
    return group, gaps


def build_snapshot(now: datetime | None = None, *, bars_reader: Callable | None = None,
                   daily_reader: Callable | None = None, vix_reader: Callable | None = None,
                   calendar_reader: Callable | None = None, news_reader: Callable | None = None,
                   bounds_reader: Callable | None = None) -> dict:
    """Build a sealed bounded packet. Every source can fail independently."""
    from zoneinfo import ZoneInfo
    fixed_clock = now is not None
    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        raise ValueError("collection time must be timezone-aware")
    now = now.astimezone(UTC)
    collection_started = now
    def source_clock():
        return now if fixed_clock else datetime.now(UTC)
    day = now.astimezone(ZoneInfo(ET_NAME)).date()
    calendar_state = None
    if bounds_reader is None:
        # The manually invoked app producer may warm the existing exchange
        # calendar once. The shared bounds helper stays read-only for check
        # process validation and owner export paths.
        from app.engine.chart_calendar import chart_calendar
        try:
            chart_calendar.hours(day)
        except Exception:
            pass
        calendar_state = chart_calendar.cached(day)
        bounds_reader = session_bounds
    bounds = bounds_reader(day)
    if bounds is None:
        opened = closed = None
        phase = "market_closed" if calendar_state and calendar_state.get("status") == "closed" else "calendar_unavailable"
    else:
        opened, closed = bounds
        phase = "pre_market" if now < opened else "regular_session" if now < closed else "post_market"
    gaps = []
    if bounds is None:
        gaps.append({"group": "session_calendar", "reason": "exchange_calendar_unavailable_or_closed"})
    cutoff = min(now.replace(second=0, microsecond=0), closed) if closed else now.replace(second=0, microsecond=0)
    if bars_reader is None:
        from app.engine import alpaca
        if alpaca.ALPACA_DATA_FEED != "iex":
            raise RuntimeError("MW-1 snapshots require the configured Alpaca feed to be IEX")
        def bars_reader(symbols, d):
            # The ordinary full-day cache waits until extended hours close.
            # Read the bounded live portion through the same Alpaca adapter,
            # without writing a partial day into that immutable cache.
            result = alpaca._alpaca_get_fast("/v2/stocks/bars", {
                "symbols": ",".join(symbols), "timeframe": "1Min",
                "start": opened.isoformat(), "end": cutoff.isoformat(),
                "adjustment": "split", "feed": "iex", "limit": 10000,
            })
            return result.get("bars", {})
    if daily_reader is None:
        from app.engine import alpaca
        def daily_reader(symbols, d):
            start_day = d - timedelta(days=14)
            result = alpaca._alpaca_get_fast("/v2/stocks/bars", {
                "symbols": ",".join(symbols), "timeframe": "1Day",
                "start": start_day.isoformat(), "end": d.isoformat(),
                "adjustment": "split", "feed": "iex", "limit": 10000,
            })
            return result.get("bars", {})
    if vix_reader is None:
        def vix_reader():
            from sqlmodel import Session, select
            from app.database import engine
            from app.models import MarketContextItem
            with Session(engine) as db:
                row = db.exec(select(MarketContextItem).where(MarketContextItem.kind == "vix")
                              .order_by(MarketContextItem.fetched_at.desc()).limit(1)).first()
            if row is None:
                return None
            observed = row.observed_at.replace(tzinfo=UTC) if row.observed_at and row.observed_at.tzinfo is None else row.observed_at
            return {"observed_at": observed, "value": row.value, "change_pct": row.change_pct,
                    "source": row.source, "fetched_at": row.fetched_at}
    if calendar_reader is None:
        def calendar_reader(day, at):
            from pathlib import Path
            calendar_path = Path(__file__).resolve().parents[2] / "data" / "macro_calendar.json"
            data = json.loads(calendar_path.read_text())
            start_coverage, end_coverage = data["covers_from"], data["covers_through"]
            if not start_coverage <= day.isoformat() <= end_coverage:
                return {"status": "missing", "reason": "calendar_out_of_coverage", "source": "BLS/Federal Reserve schedule",
                        "observed_at": None, "retrieved_at": _time(at), "age_seconds": None,
                        "source_sha256": digest({"coverage_start": start_coverage, "coverage_end": end_coverage,
                                                  "calendar_version": digest(data), "events": []}), "coverage_start": start_coverage,
                        "coverage_end": end_coverage, "calendar_version": digest(data), "events": []}
            events = []
            for row in data.get("events", []):
                if row.get("date") != day.isoformat() or row.get("kind") not in {"cpi", "fomc", "jobs"}:
                    continue
                try:
                    hour, minute = (int(part) for part in row["time"].split(":"))
                    from zoneinfo import ZoneInfo
                    scheduled = datetime.combine(day, datetime.min.time(), ZoneInfo(ET_NAME)).replace(hour=hour, minute=minute)
                except (KeyError, TypeError, ValueError):
                    continue
                events.append({"event_id": digest({"date": day.isoformat(), "kind": row["kind"], "name": row["name"]})[:24],
                               "kind": row["kind"], "name": row["name"], "scheduled_at": _time(scheduled),
                               "source": "BLS/Federal Reserve schedule", "calendar_version": digest(data),
                               "coverage_start": start_coverage, "coverage_end": end_coverage,
                               "actual": None, "consensus": None, "surprise": None, "release_values_status": "not_supported"})
            return {"status": "missing", "reason": "observation_time_unknown", "source": "BLS/Federal Reserve schedule",
                    "observed_at": None, "retrieved_at": _time(at), "age_seconds": None,
                    "source_sha256": digest({"coverage_start": start_coverage, "coverage_end": end_coverage,
                                              "calendar_version": digest(data), "events": events}), "coverage_start": start_coverage, "coverage_end": end_coverage,
                    "calendar_version": digest(data), "events": events}
    if news_reader is None:
        def news_reader(window_start, window_end):
            # No existing durable headline cache can be read safely here.
            # MW-1 therefore records an explicit gap instead of starting a
            # collector or presenting a new provider response as pre-fetched.
            return {"status": "missing", "reason": "no_published_headline_cache", "source": "Alpaca Benzinga",
                    "observed_at": None, "retrieved_at": _time(window_end), "age_seconds": None,
                    "source_sha256": digest([]), "query_symbols": ["SPY", "QQQ"],
                    "window_start": _time(window_start), "window_end": _time(window_end),
                    "coverage": "unpublished", "errors": [], "items": []}
    try:
        raw = (bars_reader(["SPY", "QQQ"], day) or {}) if opened and closed else {}
    except Exception as exc:
        raw = {}
        gaps.append({"group": "indices", "reason": f"source_error:{type(exc).__name__}"})
    bars_retrieved = source_clock()
    try:
        daily = (daily_reader(["SPY", "QQQ"], day) or {}) if bounds else {}
    except Exception as exc:
        daily = {}
        gaps.append({"group": "prior_close", "reason": f"source_error:{type(exc).__name__}"})
    daily_retrieved = source_clock()
    indices = {}
    published_rows = {}
    prior_manifest_rows = {}
    for symbol in ("SPY", "QQQ"):
        rows = raw.get(symbol) or []
        try:
            _session_bars(rows, opened, cutoff)
        except ValueError as exc:
            gaps.append({"group": f"indices.{symbol}", "reason": str(exc)})
            rows = []
        published_rows[symbol] = rows
        prior = None
        prior_rows = []
        prior_day = previous_session_date(day) if bounds else None
        for row in daily.get(symbol, []):
            try:
                if prior_day is not None and str(row.get("t", ""))[:10] == prior_day.isoformat():
                    prior_rows.append(row)
            except Exception:
                continue
        prior_bounds = None
        if prior_day is not None:
            prior_bounds = session_bounds(prior_day)
        if len(prior_rows) == 1 and prior_bounds:
            row = prior_rows[0]
            try:
                prior = {"value": float(row["c"]), "at": _time(prior_bounds[1]), "status": "fresh", "reason": None}
                prior_manifest_rows[symbol] = {"t": str(row["t"]), "c": float(row["c"])}
            except (KeyError, TypeError, ValueError):
                prior = None
        if opened:
            indices[symbol], found = _index(symbol, rows, rows, prior, opened, cutoff, bars_retrieved, phase == "regular_session")
        else:
            indices[symbol] = {"symbol": symbol, "source": "Alpaca IEX", "observed_at": None, "retrieved_at": _time(now),
                "age_seconds": None, "status": "missing", "reason": "session_calendar_unavailable", "source_sha256": digest([]),
                "price": {"value": None, "at": None, "status": "missing", "reason": "session_calendar_unavailable"},
                "prior_close": {"value": None, "at": None, "status": "missing", "reason": "prior_session_unavailable"},
                "session_open": {"value": None, "at": None, "status": "missing", "reason": "session_calendar_unavailable"},
                "bar_1m": None, "vwap": {"value": None, "status": "missing", "reason": "session_calendar_unavailable"},
                "or15_high": {"value": None, "status": "missing", "reason": "session_calendar_unavailable"},
                "or15_low": {"value": None, "status": "missing", "reason": "session_calendar_unavailable"},
                "return_vs_prior_close": None, "distance_to_vwap": None, "bars_5m": []}
            found = [{"group": f"indices.{symbol}", "reason": "session_calendar_unavailable"}]
        gaps.extend(found)
        if prior is None:
            gaps.append({"group": f"indices.{symbol}.prior_close", "reason": "prior_session_close_unavailable" if len(prior_rows) <= 1 else "duplicate_prior_daily_bars"})
    volatility = {"status": "missing", "reason": "vix_unavailable", "source": "existing_market_context", "observed_at": None, "retrieved_at": _time(now), "age_seconds": None, "source_sha256": digest(None), "instrument": "VIX", "instrument_type": "spot_index", "value": None, "change_pct": None}
    if vix_reader:
        try:
            item = vix_reader()
            vix_retrieved = source_clock()
            if item:
                observed = item.get("observed_at")
                payload = {"source": "Tradier", "value": item.get("value"), "change_pct": item.get("change_pct"),
                           "observed_at": _time(_raw_time(observed)) if observed else None}
                group = _stamp_group("Tradier", observed, vix_retrieved, payload, limit=3600, active=True)
                volatility = {**group, "instrument": "VIX", "instrument_type": "spot_index", "value": item.get("value"), "change_pct": item.get("change_pct")}
        except Exception as exc:
            vix_retrieved = source_clock()
            volatility["reason"] = f"source_error:{type(exc).__name__}"
        volatility["retrieved_at"] = _time(vix_retrieved)
    else:
        gaps.append({"group": "volatility", "reason": "vix_unavailable"})
    calendar_started = source_clock()
    calendar = {"status": "missing", "reason": "calendar_unavailable", "source": "macro_calendar", "observed_at": None,
                "retrieved_at": _time(calendar_started), "age_seconds": None, "source_sha256": digest(None), "coverage_start": None, "coverage_end": None, "calendar_version": None, "events": []}
    calendar["source_sha256"] = digest({key: calendar[key] for key in
        ("coverage_start", "coverage_end", "calendar_version", "events")})
    if calendar_reader:
        try:
            calendar = calendar_reader(day, calendar_started)
        except Exception as exc:
            calendar["reason"] = f"source_error:{type(exc).__name__}"
    else:
        gaps.append({"group": "calendar", "reason": calendar["reason"]})
    headlines_started = source_clock()
    headlines = {"status": "missing", "reason": "news_unavailable", "source": "Alpaca Benzinga", "observed_at": None,
                 "retrieved_at": _time(headlines_started), "age_seconds": None, "source_sha256": digest([]), "query_symbols": ["SPY", "QQQ"], "window_start": _time(now - timedelta(hours=24)), "window_end": _time(headlines_started), "coverage": "unknown", "errors": [], "items": []}
    if news_reader:
        try:
            headlines = news_reader(now - timedelta(hours=24), headlines_started)
        except Exception as exc:
            headlines["reason"] = f"source_error:{type(exc).__name__}"
    else:
        gaps.append({"group": "headlines", "reason": headlines["reason"]})
    for name, source in (("volatility", volatility), ("calendar", calendar), ("headlines", headlines)):
        if source.get("status") in {"missing", "stale", "not_ready"}:
            gaps.append({"group": name, "reason": source.get("reason") or source["status"]})
    finished = source_clock()
    if calendar["retrieved_at"] == _time(calendar_started):
        calendar["retrieved_at"] = _time(finished if not fixed_clock else calendar_started)
    if headlines["retrieved_at"] == _time(headlines_started):
        headlines["retrieved_at"] = _time(finished if not fixed_clock else headlines_started)
    if headlines.get("observed_at") is not None:
        headlines["age_seconds"] = max(0.0, (finished - parse_time(headlines["retrieved_at"])).total_seconds())
        if headlines["age_seconds"] > PROTOCOL["freshness_limits"]["news_retrieval_seconds"]:
            headlines["status"] = "stale"
    manifest = []
    for symbol, group in indices.items():
        source_rows = published_rows[symbol]
        session_bars = _session_bars(source_rows, opened, cutoff) if opened else []
        manifest.append({"group": f"indices.{symbol}.bars_1m", "provider": "Alpaca", "feed": "iex",
                         "adjustment": "split", "window_start": _time(opened) if opened else None, "window_end": _time(cutoff),
                         "retrieved_at": group["retrieved_at"], "payload_sha256": group["source_sha256"],
                         "bars": session_bars})
        previous = prior_manifest_rows.get(symbol)
        if previous:
            manifest.append({"group": f"indices.{symbol}.prior_daily_bar", "provider": "Alpaca", "feed": "iex",
                             "adjustment": "split", "window_start": (day - timedelta(days=14)).isoformat(),
                             "window_end": day.isoformat(), "retrieved_at": _time(daily_retrieved),
                             "payload_sha256": digest([previous]), "bars": [previous]})
    for group_name, source in (("volatility", volatility), ("calendar", calendar), ("headlines", headlines)):
        manifest.append({"group": group_name, "provider": source.get("source"),
                         "retrieved_at": source.get("retrieved_at"),
                         "payload_sha256": source.get("source_sha256")})
    packet = {"schema_version": 1, "protocol_id": "mw-v1", "protocol_sha256": PROTOCOL_SHA256, "session_date": day.isoformat(),
              "collection_started_at": _time(collection_started), "collection_finished_at": _time(finished),
              "created_at": _time(finished),
              "session_open_at": _time(opened) if opened else None, "session_close_at": _time(closed) if closed else None, "market_phase": phase,
              "indices": indices, "volatility": volatility, "calendar": calendar, "headlines": headlines,
              "gaps": gaps, "input_manifest": manifest}
    packet["snapshot_id"] = "mws_" + digest(packet)[:32]
    packet = seal(packet)
    validate_snapshot(packet)
    return packet


def publish_snapshot(directory: str | Path, snapshot: dict) -> Path:
    """Publish a frozen protocol and immutable packet; advance latest monotonically."""
    validate_snapshot(snapshot)
    root = Path(directory)
    if root.is_symlink():
        raise ValueError("snapshot publication directory may not be a symlink")
    root.mkdir(parents=True, exist_ok=True)
    content_path = root / f"{snapshot['content_sha256']}.json"
    if content_path.is_symlink():
        raise ValueError("snapshot content path may not be a symlink")
    data = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    protocol_dir = root / "protocols"
    protocol_dir.mkdir(exist_ok=True)
    protocol_path = protocol_dir / f"{PROTOCOL_SHA256}.json"
    if protocol_path.is_symlink():
        raise ValueError("protocol publication path may not be a symlink")
    protocol_bytes = json.dumps(PROTOCOL, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    lock_path = root / ".publish.lock"
    lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o640)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        _publish_immutable(content_path, data)
        _publish_immutable(protocol_path, protocol_bytes)
        _fsync_directory(root)
        _fsync_directory(protocol_dir)
        latest = root / "latest.json"
        if latest.is_symlink():
            raise ValueError("latest snapshot pointer may not be a symlink")
        current = None
        if latest.exists():
            try:
                pointer = json.loads(_read_bounded(latest, 4096))
                current_hash = pointer["content_sha256"]
                if isinstance(current_hash, str) and len(current_hash) == 64 and all(ch in "0123456789abcdef" for ch in current_hash):
                    current = json.loads(_read_bounded(root / f"{current_hash}.json", 2 * 1024 * 1024))
                    verify(current)
                    validate_snapshot(current)
            except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
                current = None
        candidate_key = (snapshot["session_date"], snapshot["collection_finished_at"])
        current_key = (current["session_date"], current["collection_finished_at"]) if current else None
        if current_key is None or candidate_key >= current_key:
            pointer = {"content_sha256": snapshot["content_sha256"], "snapshot_id": snapshot["snapshot_id"]}
            fd, name = tempfile.mkstemp(prefix=".latest-", suffix=".tmp", dir=root)
            temporary = Path(name)
            try:
                os.fchmod(fd, 0o640)
                with os.fdopen(fd, "wb") as stream:
                    stream.write(json.dumps(pointer, sort_keys=True, separators=(",", ":")).encode())
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, latest)
                _fsync_directory(root)
            finally:
                temporary.unlink(missing_ok=True)
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)
    return content_path


def _publish_immutable(path: Path, data: bytes) -> None:
    if path.is_symlink():
        raise ValueError("immutable publication path may not be a symlink")
    if path.exists():
        if _read_bounded(path, 2 * 1024 * 1024).encode("utf-8") != data:
            raise ValueError("content-addressed publication conflicts with existing file")
        return
    fd, name = tempfile.mkstemp(prefix=".market-watch-", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        os.fchmod(fd, 0o640)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if _read_bounded(path, 2 * 1024 * 1024).encode("utf-8") != data:
                raise ValueError("content-addressed publication conflicts with existing file")
    finally:
        temporary.unlink(missing_ok=True)


def _fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def read_latest_snapshot(directory: str | Path, now: datetime) -> dict | None:
    root = Path(directory)
    if root.is_symlink() or (root / "latest.json").is_symlink():
        return None
    now_utc = now.astimezone(UTC) if now.tzinfo else (_ for _ in ()).throw(ValueError("now must be timezone-aware"))
    try:
        pointer = json.loads(_read_bounded(root / "latest.json", 4096))
        sha = pointer["content_sha256"]
        if not isinstance(sha, str) or len(sha) != 64 or any(ch not in "0123456789abcdef" for ch in sha):
            return None
        snapshot = json.loads(_read_bounded(root / f"{sha}.json", 2 * 1024 * 1024))
        if (root / f"{sha}.json").is_symlink():
            return None
        protocol_path = root / "protocols" / f"{PROTOCOL_SHA256}.json"
        if protocol_path.is_symlink() or json.loads(_read_bounded(protocol_path, 64 * 1024)) != PROTOCOL:
            return None
        verify(snapshot)
        validate_snapshot(snapshot)
        if snapshot["content_sha256"] != sha or snapshot["snapshot_id"] != pointer["snapshot_id"]:
            return None
        # Only a current-session packet may be served. Snapshot freshness is
        # surfaced to callers and never changes the immutable source evidence.
        from zoneinfo import ZoneInfo
        if date.fromisoformat(snapshot["session_date"]) != now_utc.astimezone(ZoneInfo(ET_NAME)).date():
            return None
        return snapshot
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _read_bounded(path: Path, limit: int) -> str:
    """Read one regular file without following its final symlink or trusting its size."""
    absolute = path.absolute()
    if any(part in {".", ".."} for part in absolute.parts[1:]):
        raise ValueError("published snapshot path is invalid")
    directory_fd = os.open(absolute.anchor, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        for component in absolute.parts[1:-1]:
            child = os.open(component, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0), dir_fd=directory_fd)
            os.close(directory_fd)
            directory_fd = child
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(absolute.name, flags, dir_fd=directory_fd)
    except BaseException:
        os.close(directory_fd)
        raise
    try:
        stat = os.fstat(fd)
        if not __import__("stat").S_ISREG(stat.st_mode) or stat.st_size > limit:
            raise ValueError("published snapshot file exceeds its type or size bound")
        chunks, remaining = [], limit + 1
        while remaining:
            chunk = os.read(fd, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
        if len(data) > limit:
            raise ValueError("published snapshot file exceeds its size bound")
        return data.decode("utf-8")
    finally:
        os.close(fd)
        os.close(directory_fd)
