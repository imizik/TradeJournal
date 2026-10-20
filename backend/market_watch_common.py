"""Frozen MW-1 protocol values and canonical immutable record helpers."""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
import copy
import hashlib
import json
import math


def _check_finite(value):
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("non-finite number")
    if isinstance(value, dict):
        for item in value.values():
            _check_finite(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _check_finite(item)


def canonical(value) -> bytes:
    _check_finite(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def digest(value) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def seal(record: dict) -> dict:
    result = dict(record)
    result.setdefault("schema_version", 1)
    result.setdefault("created_at", datetime.now(UTC).isoformat().replace("+00:00", "Z"))
    result.pop("content_sha256", None)
    result["content_sha256"] = digest(result)
    return result


def verify(record: dict) -> None:
    if not isinstance(record, dict) or type(record.get("schema_version")) is not int or record["schema_version"] != 1:
        raise ValueError("record schema is invalid")
    supplied = record.get("content_sha256")
    body = {key: value for key, value in record.items() if key != "content_sha256"}
    if not isinstance(supplied, str) or supplied != digest(body):
        raise ValueError("record content hash is invalid")


def parse_time(value: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp must be a string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("timestamp is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must include an offset")
    return parsed.astimezone(UTC)


PROTOCOL = {
    "schema_version": 1,
    "created_at": "2026-10-14T00:00:00.000000Z",
    "protocol_id": "mw-v1",
    "effective_from": "2026-10-14",
    "universe": ["SPY", "QQQ"],
    "source_policy": {"prices": "alpaca_iex", "volatility": "existing_timestamped_vix", "calendar": "official_cpi_fomc_jobs", "news": "existing_alpaca_benzinga"},
    "feature_version": "mw-snapshot-v1",
    "freshness_limits": {"rth_price_seconds": 180, "vix_seconds": 3600, "news_retrieval_seconds": 1800},
    "horizons": ["30m", "60m", "close"],
    "anchor_rule": {"kind": "first_regular_session_minute_close_strictly_after_received_at", "max_delay_minutes": 1},
    "price_basis": "split-consistent non-dividend-adjusted Alpaca IEX OHLC",
    "missing_policy": "explicit status and gaps; never substitute zero or forward-fill",
    "comparator_version": "price-check-v1",
    "comparator": {"down": {"spy_below_vwap": True, "qqq_below_vwap": True, "spy_below_or15_low": True, "probabilities": {"30m": 0.65, "60m": 0.65, "close": 0.65}},
                   "up": {"spy_above_vwap": True, "qqq_above_vwap": True, "spy_above_or15_high": True, "probabilities": {"30m": 0.35, "60m": 0.35, "close": 0.35}},
                   "neutral_probability": 0.5, "unavailable_on_missing_or_stale": True},
    "day_label_version": "session-label-v1",
    "evaluation": {"target_grace_minutes": 15, "return": "target/anchor-1", "negative_label": "return_lt_zero",
                    "tie_label": 0, "brier": "(probability-y)^2", "path_requires_all_intermediate_bars": True,
                    "path_high_low": True, "revision_start": 1},
    "session_label": {"atr_period": 14, "atr": "arithmetic_mean_prior_true_ranges_excluding_today",
                      "trend_threshold_atr": 0.5, "outer_range_fraction": 0.3,
                      "missed_before_local_time": "12:00", "coverage_status": "manual_partial"},
    "calibration_bins": [[i / 10, (i + 1) / 10] for i in range(10)],
}
PROTOCOL["content_sha256"] = digest(PROTOCOL)
PROTOCOL_SHA256 = PROTOCOL["content_sha256"]


# Keep the original sealed IEX protocol reproducible. New live inputs name a
# distinct source/price basis instead of relabelling historical evidence.
TRADIER_PROTOCOL = copy.deepcopy(PROTOCOL)
TRADIER_PROTOCOL.update(protocol_id="mw-tradier-v2", effective_from="2026-10-20",
    created_at="2026-10-20T00:00:00.000000Z", feature_version="mw-snapshot-tradier-v2",
    price_basis="Tradier provider-reported OHLC; dividend adjustment not guaranteed",
    source_policy={**PROTOCOL["source_policy"], "prices": "tradier_full_market"})
TRADIER_PROTOCOL.pop("content_sha256")
TRADIER_PROTOCOL["content_sha256"] = digest(TRADIER_PROTOCOL)
PROTOCOLS = {p["protocol_id"]: p for p in (PROTOCOL, TRADIER_PROTOCOL)}


def snapshot_protocol(record):
    protocol = PROTOCOLS.get(record.get("protocol_id"))
    if protocol is None or record.get("protocol_sha256") != protocol["content_sha256"]:
        raise ValueError("snapshot protocol hash is invalid")
    return protocol


def session_bounds(day: date):
    from app.engine.chart_calendar import chart_calendar
    from zoneinfo import ZoneInfo
    # This helper is safe to call from validators and the isolated check
    # process: it consults only the already-loaded exchange-calendar cache.
    hours = chart_calendar.cached(day)
    if not hours or hours.get("status") != "open":
        return None
    et = ZoneInfo("America/New_York")
    opened = datetime.combine(day, datetime.min.time(), et).replace(hour=hours["open"] // 60, minute=hours["open"] % 60)
    closed = datetime.combine(day, datetime.min.time(), et).replace(hour=hours["close"] // 60, minute=hours["close"] % 60)
    return opened.astimezone(UTC), closed.astimezone(UTC)


def previous_session_date(day: date) -> date | None:
    """Find the prior session from the exchange calendar cache; never guess holidays."""
    from app.engine.chart_calendar import chart_calendar
    from datetime import timedelta
    candidate = day - timedelta(days=1)
    for _ in range(14):
        row = chart_calendar.cached(candidate)
        if row is None:
            return None
        if row.get("status") == "open":
            return candidate
        if row.get("status") != "closed":
            return None
        candidate -= timedelta(days=1)
    return None


MAX_VERIFIED_OMISSIONS = 8
MAX_OMISSION_TRADES = 200
VERIFIED_OMISSION_REASON = "verified_iex_non_price_forming_minutes"


def verified_omission_starts(proofs, *, opened, cutoff, finished):
    """Reproduce bounded IEX no-bar evidence, without synthesizing OHLCV.

    Alpaca does not emit a minute bar when only odd lots (condition I) trade,
    or when no trades occur. Unknown/truncated/error responses never qualify.
    Opening-range gaps remain unavailable under the existing strict rule.
    """
    if not isinstance(proofs, list) or len(proofs) > MAX_VERIFIED_OMISSIONS:
        raise ValueError("invalid omitted-minute evidence")
    starts = set()
    for proof in proofs:
        if not isinstance(proof, dict) or set(proof) != {"start", "end", "retrieved_at", "complete", "trades"} or proof["complete"] is not True:
            raise ValueError("incomplete omitted-minute evidence")
        start, end, retrieved = (parse_time(proof[k]) for k in ("start", "end", "retrieved_at"))
        if (start.second or start.microsecond or end != start + timedelta(minutes=1)
                or start < opened + timedelta(minutes=15) or end > cutoff
                or not end <= retrieved <= finished or start in starts):
            raise ValueError("invalid omitted-minute window")
        trades = proof["trades"]
        if not isinstance(trades, list) or len(trades) > MAX_OMISSION_TRADES:
            raise ValueError("invalid omitted-minute trades")
        for trade in trades:
            if (not isinstance(trade, dict) or set(trade) != {"t", "c"}
                    or not start <= parse_time(trade["t"]) < end
                    or not isinstance(trade["c"], list) or not trade["c"]
                    or any(not isinstance(c, str) for c in trade["c"])
                    or len(trade["c"]) != len(set(trade["c"]))
                    or set(trade["c"]) not in ({"I"}, {"@", "I"})):
                raise ValueError("omitted minute contains unverified or price-forming trades")
        starts.add(start)
    return starts


def validate_snapshot(record: dict) -> None:
    verify(record)
    protocol = snapshot_protocol(record)
    tradier = protocol is TRADIER_PROTOCOL
    allowed_top = {"schema_version", "created_at", "content_sha256", "snapshot_id", "protocol_id", "protocol_sha256",
                   "session_date", "collection_started_at", "collection_finished_at", "session_open_at", "session_close_at",
                   "market_phase", "indices", "volatility", "calendar", "headlines", "gaps", "input_manifest"}
    if set(record) != allowed_top:
        raise ValueError("snapshot contains fields outside the public market schema")
    required = {"snapshot_id", "protocol_id", "session_date", "collection_started_at", "collection_finished_at", "session_open_at", "session_close_at", "market_phase", "indices", "volatility", "calendar", "headlines", "gaps", "input_manifest"}
    if not required <= record.keys():
        raise ValueError("snapshot protocol or fields are invalid")
    if not isinstance(record.get("snapshot_id"), str):
        raise ValueError("snapshot id is invalid")
    if record.get("snapshot_id") != "mws_" + digest({k: v for k, v in record.items() if k not in {"snapshot_id", "content_sha256"}})[:32]:
        raise ValueError("snapshot id does not match its contents")
    parse_time(record["created_at"])
    date.fromisoformat(record["session_date"])
    started, finished = parse_time(record["collection_started_at"]), parse_time(record["collection_finished_at"])
    if started > finished:
        raise ValueError("snapshot collection window is invalid")
    if record["session_open_at"] is None or record["session_close_at"] is None:
        if record["session_open_at"] is not None or record["session_close_at"] is not None or record["market_phase"] not in {"calendar_unavailable", "market_closed"}:
            raise ValueError("snapshot session bounds are invalid")
    else:
        parse_time(record["session_open_at"])
        parse_time(record["session_close_at"])
    if set(record["indices"]) != {"SPY", "QQQ"}:
        raise ValueError("snapshot universe is invalid")
    manifest = record["input_manifest"]
    if not isinstance(manifest, list):
        raise ValueError("snapshot manifest is invalid")
    for symbol, group in record["indices"].items():
        index_fields = {"symbol", "source", "observed_at", "retrieved_at", "age_seconds", "status", "reason", "source_sha256",
                        "price", "prior_close", "session_open", "bar_1m", "vwap", "or15_high", "or15_low",
                        "return_vs_prior_close", "distance_to_vwap", "bars_5m"}
        if set(group) != index_fields:
            raise ValueError("index contains fields outside the public market schema")
        if group.get("symbol") != symbol or group.get("source") != ("Tradier full_market" if tradier else "Alpaca IEX"):
            raise ValueError("index source or symbol is invalid")
        if group.get("status") not in {"fresh", "stale", "missing", "not_ready", "not_supported"}:
            raise ValueError("index status is invalid")
        for stamp in (group.get("observed_at"), group.get("retrieved_at")):
            if stamp is not None and parse_time(stamp) > finished:
                raise ValueError("source timestamp is after collection")
        observed, retrieved = (parse_time(group[key]) if group.get(key) else None for key in ("observed_at", "retrieved_at"))
        if observed is None:
            if group["status"] != "missing":
                raise ValueError("index with unknown observation time must be missing")
        else:
            if retrieved is None:
                raise ValueError("index observation requires retrieval time")
            age = max(0.0, (retrieved - observed).total_seconds())
            expected = "stale" if age > PROTOCOL["freshness_limits"]["rth_price_seconds"] else "fresh"
            if group["status"] != expected or not math.isclose(float(group["age_seconds"]), age, abs_tol=0.001):
                raise ValueError("index freshness does not match its timestamps")
        for field in ("price", "bar_1m", "vwap", "or15_high", "or15_low"):
            if field not in group:
                raise ValueError(f"index field {field} is missing")
        bar = group.get("bar_1m")
        if bar:
            start = parse_time(bar["start"])
            end = parse_time(bar["end"])
            if end - start != timedelta(minutes=1) or start.second != 0 or start.microsecond != 0:
                # Minute timestamps are UTC-aligned boundaries from Alpaca.
                raise ValueError("minute bar timestamps are invalid")
            if end > finished:
                raise ValueError("unclosed/future minute bar is invalid")
        for subfield in ("price", "prior_close", "session_open", "vwap", "or15_high", "or15_low"):
            sub = group[subfield]
            if not isinstance(sub, dict) or sub.get("status") not in {"fresh", "stale", "missing", "not_ready", "not_supported"}:
                raise ValueError("index metric status is invalid")
            if sub.get("at") is not None and parse_time(sub["at"]) > finished:
                raise ValueError("index metric timestamp is after collection")
        entries = [item for item in manifest if item.get("group") == f"indices.{symbol}.bars_1m"]
        if len(entries) != 1 or entries[0].get("payload_sha256") != group["source_sha256"]:
            raise ValueError("minute bar manifest hash is invalid")
        if tradier and (entries[0].get("provider") != "Tradier" or entries[0].get("feed") != "full_market"
                or entries[0].get("adjustment") != "provider_reported" or entries[0].get("omitted_minutes")):
            raise ValueError("Tradier source manifest is invalid")
        bars = entries[0].get("bars")
        if not isinstance(bars, list) or digest(bars) != group["source_sha256"]:
            raise ValueError("minute bar manifest payload is invalid")
        if any(parse_time(bar["end"]) > finished or (record["session_close_at"] and parse_time(bar["end"]) > parse_time(record["session_close_at"])) for bar in bars):
            raise ValueError("future minute bar is present in manifest")
        starts = [parse_time(bar["start"]) for bar in bars]
        if starts != sorted(set(starts)):
            raise ValueError("minute bar ordering or duplicates are invalid")
        if not bars:
            if entries[0].get("omitted_minutes", []) != []:
                raise ValueError("empty source bars cannot carry omitted-minute evidence")
            if group["bars_5m"] or group["bar_1m"] is not None or any(
                group[field].get("value") is not None for field in ("price", "session_open", "vwap", "or15_high", "or15_low")
            ) or group["return_vs_prior_close"] is not None or group["distance_to_vwap"] is not None:
                raise ValueError("empty source bars cannot supply derived price evidence")
        for bar in bars:
            bar_start, bar_end = parse_time(bar["start"]), parse_time(bar["end"])
            if (bar_start.second or bar_start.microsecond or bar_end - bar_start != timedelta(minutes=1)
                    or record["session_open_at"] is None or bar_start < parse_time(record["session_open_at"])):
                raise ValueError("source minute bar must be an exact regular-session minute")
            vals = [bar.get(name) for name in ("open", "high", "low", "close", "volume")]
            if any(type(number) not in (int, float) or not math.isfinite(number) for number in vals):
                raise ValueError("minute bar values are invalid")
            if bar["volume"] < 0 or bar["high"] < max(bar["open"], bar["close"], bar["low"]) or bar["low"] > min(bar["open"], bar["close"], bar["high"]):
                raise ValueError("minute OHLCV is inconsistent")
        if bars:
            open_at = parse_time(record["session_open_at"])
            omitted = verified_omission_starts(entries[0].get("omitted_minutes", []), opened=open_at,
                                              cutoff=parse_time(entries[0]["window_end"]), finished=finished)
            required_minutes = {open_at + timedelta(minutes=i) for i in range(int((parse_time(bars[-1]["end"]) - open_at).total_seconds() // 60))}
            if omitted & set(starts) or not omitted <= required_minutes:
                raise ValueError("omitted-minute evidence overlaps bars or lies outside the bar path")
            contiguous = starts[0] == open_at and required_minutes <= set(starts) | omitted
            opening_bar = bars[0] if starts[0] == open_at else None
            session_open = group["session_open"]
            if opening_bar:
                if session_open.get("value") != opening_bar["open"] or parse_time(session_open.get("at")) != open_at:
                    raise ValueError("session open does not match the exact opening minute")
            elif session_open.get("value") is not None or session_open.get("at") is not None or session_open.get("status") != "missing":
                raise ValueError("session open must be missing without the exact opening minute")
            last = bars[-1]
            if group["bar_1m"] != last or group["price"].get("value") != last["close"]:
                raise ValueError("latest price does not match its bar")
            if contiguous and sum(bar["volume"] for bar in bars) > 0:
                expected_vwap = sum(((bar["high"] + bar["low"] + bar["close"]) / 3) * bar["volume"] for bar in bars) / sum(bar["volume"] for bar in bars)
                actual_vwap = group["vwap"].get("value")
                if actual_vwap is None or not math.isclose(actual_vwap, expected_vwap, rel_tol=1e-12, abs_tol=1e-12):
                    raise ValueError("VWAP does not match its source bars")
                if omitted and group["vwap"].get("reason") != VERIFIED_OMISSION_REASON:
                    raise ValueError("VWAP must disclose verified IEX omissions")
            elif group["vwap"].get("value") is not None or group["vwap"].get("status") != "missing":
                raise ValueError("VWAP must be unavailable when source bars are incomplete")
            buckets = []
            by_start = {parse_time(bar["start"]): bar for bar in bars}
            for start in sorted(by_start):
                if (start - open_at).total_seconds() % 300:
                    continue
                keys = [start + timedelta(minutes=i) for i in range(5)]
                if any(key not in by_start for key in keys):
                    continue
                chunk = [by_start[key] for key in keys]
                buckets.append({"start": chunk[0]["start"], "end": chunk[-1]["end"], "open": chunk[0]["open"],
                    "high": max(bar["high"] for bar in chunk), "low": min(bar["low"] for bar in chunk),
                    "close": chunk[-1]["close"], "volume": sum(bar["volume"] for bar in chunk)})
            if group["bars_5m"] != buckets[-12:]:
                raise ValueError("five-minute bars do not match completed session-aligned source bars")
            first15 = bars[:15]
            or_ready = (len(first15) == 15 and first15[0]["start"] == record["session_open_at"] and
                        all(parse_time(first15[i]["start"]) == parse_time(first15[0]["start"]) + timedelta(minutes=i) for i in range(15)))
            if or_ready:
                if group["or15_high"].get("value") != max(bar["high"] for bar in first15) or group["or15_low"].get("value") != min(bar["low"] for bar in first15):
                    raise ValueError("opening range does not match its source bars")
            elif group["or15_high"].get("value") is not None or group["or15_low"].get("value") is not None:
                raise ValueError("opening range must be unavailable before all 15 bars")
    for name in ("volatility", "calendar", "headlines"):
        group = record[name]
        group_fields = {
            "volatility": {"source", "observed_at", "retrieved_at", "age_seconds", "status", "reason", "source_sha256", "instrument", "instrument_type", "value", "change_pct"},
            "calendar": {"source", "observed_at", "retrieved_at", "age_seconds", "status", "reason", "source_sha256", "coverage_start", "coverage_end", "calendar_version", "events"},
            "headlines": {"source", "observed_at", "retrieved_at", "age_seconds", "status", "reason", "source_sha256", "query_symbols", "window_start", "window_end", "coverage", "errors", "items"},
        }[name]
        if set(group) != group_fields:
            raise ValueError(f"{name} contains fields outside the public market schema")
        if not isinstance(group, dict) or group.get("status") not in {"fresh", "stale", "missing", "not_ready", "not_supported"}:
            raise ValueError(f"{name} group status is invalid")
        if not isinstance(group.get("source_sha256"), str) or len(group["source_sha256"]) != 64:
            raise ValueError(f"{name} source hash is invalid")
        for stamp in (group.get("observed_at"), group.get("retrieved_at")):
            if stamp is not None and parse_time(stamp) > finished:
                raise ValueError(f"{name} source timestamp is after collection")
        observed = parse_time(group["observed_at"]) if group.get("observed_at") else None
        retrieved = parse_time(group["retrieved_at"]) if group.get("retrieved_at") else None
        if observed is None and group["status"] != "missing":
            raise ValueError(f"{name} with unknown observation time must be missing")
        if name == "volatility" and observed is not None:
            age = max(0.0, (retrieved - observed).total_seconds())
            expected = "stale" if age > PROTOCOL["freshness_limits"]["vix_seconds"] else "fresh"
            if group["status"] != expected or not math.isclose(float(group["age_seconds"]), age, abs_tol=0.001):
                raise ValueError("volatility freshness does not match its timestamps")
            payload = {"source": group["source"], "value": group["value"], "change_pct": group["change_pct"], "observed_at": group["observed_at"]}
            if digest(payload) != group["source_sha256"]:
                raise ValueError("volatility payload hash is invalid")
        if name == "calendar":
            payload = {"coverage_start": group["coverage_start"], "coverage_end": group["coverage_end"],
                       "calendar_version": group["calendar_version"], "events": group["events"]}
            if digest(payload) != group["source_sha256"]:
                raise ValueError("calendar payload hash is invalid")
        if name == "headlines":
            if observed is None:
                if group["status"] != "missing":
                    raise ValueError("headlines with unknown observation time must be missing")
            else:
                if retrieved is None:
                    raise ValueError("headlines with an observation require retrieval time")
                age = max(0.0, (finished - retrieved).total_seconds())
                expected = "stale" if age > PROTOCOL["freshness_limits"]["news_retrieval_seconds"] else "fresh"
                if group["status"] != expected or not math.isclose(float(group["age_seconds"]), age, abs_tol=0.001):
                    raise ValueError("headline retrieval freshness does not match its timestamps")
            if digest(group["items"]) != group["source_sha256"]:
                raise ValueError("headline payload hash is invalid")
        item = next((entry for entry in manifest if entry.get("group") == name), None)
        if item is None or item.get("payload_sha256") != group["source_sha256"]:
            raise ValueError(f"{name} manifest hash is invalid")
    expected_manifest_groups = {"volatility", "calendar", "headlines"} | {
        f"indices.{symbol}.bars_1m" for symbol in ("SPY", "QQQ")
    }
    if any(item.get("group") not in expected_manifest_groups | {"indices.SPY.prior_daily_bar", "indices.QQQ.prior_daily_bar"} for item in manifest):
        raise ValueError("snapshot manifest contains an unsupported source")
    if tradier and any((item.get("provider"), item.get("feed"), item.get("adjustment")) != ("Tradier", "full_market", "provider_reported")
            for item in manifest if item.get("group", "").startswith("indices.")):
        raise ValueError("Tradier source manifest is invalid")
    if len({item.get("group") for item in manifest}) != len(manifest):
        raise ValueError("snapshot manifest has duplicate source groups")
    if len(record["headlines"].get("items", [])) > 10:
        raise ValueError("headline limit is exceeded")
    for article in record["headlines"].get("items", []):
        article_fields = {"article_id", "provider", "url", "headline", "published_at", "provider_updated_at", "first_observed_at", "retrieved_at", "payload_sha256", "truncated"}
        if set(article) != article_fields:
            raise ValueError("headline contains fields outside the public market schema")
        for field in ("published_at", "provider_updated_at", "first_observed_at", "retrieved_at"):
            if article.get(field) is not None and parse_time(article[field]) > finished:
                raise ValueError("headline source timestamp is after collection")
        if article.get("published_at") is None or parse_time(article["published_at"]) < finished - timedelta(hours=24):
            raise ValueError("headline is outside the retained 24-hour window")
        if not isinstance(article.get("payload_sha256"), str) or len(article["payload_sha256"]) != 64:
            raise ValueError("headline payload hash is invalid")
        if digest({key: value for key, value in article.items() if key != "payload_sha256"}) != article["payload_sha256"]:
            raise ValueError("headline evidence hash is invalid")
        url = article.get("url")
        if url is not None:
            from urllib.parse import parse_qsl, urlsplit
            parsed = urlsplit(url)
            sensitive = {"token", "key", "api_key", "secret", "password", "authorization", "signature"}
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or any(k.lower() in sensitive for k, _ in parse_qsl(parsed.query)):
                raise ValueError("headline URL is not a public link")
    calendar_fields = {"event_id", "kind", "name", "scheduled_at", "source", "calendar_version", "coverage_start", "coverage_end", "actual", "consensus", "surprise", "release_values_status"}
    for event in record["calendar"].get("events", []):
        if (set(event) != calendar_fields or event.get("release_values_status") != "not_supported"
                or event.get("actual") is not None or event.get("consensus") is not None or event.get("surprise") is not None):
            raise ValueError("calendar event contains unsupported fields")
        parse_time(event["scheduled_at"])
    for gap in record["gaps"]:
        if not isinstance(gap, dict) or not {"group", "reason"} <= gap.keys():
            raise ValueError("snapshot gap is invalid")
