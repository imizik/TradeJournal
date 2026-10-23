"""Observed group returns from two common Radar passes; never a detector or signal."""
from datetime import UTC, datetime
import math
import hashlib
import json

from app.engine.radar_store import RadarStore

WINDOW_SECONDS = 15 * 60
PASS_TOLERANCE_SECONDS = 90
TRADE_AGE_SECONDS = 120
STALE_SECONDS = 180
BENCHMARKS = ("QQQ", "SPY")


def epoch(value: str) -> float:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Radar observation needs a timezone")
    return parsed.timestamp()


def iso(value: float) -> str:
    return datetime.fromtimestamp(value, UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def accepted_group_versions(universe: dict) -> list[str]:
    versions = [universe["version"]]
    # v2 added sector metadata only (7344f004); groups match v1 (2e8e6f58).
    # Pin the entire known membership, not just a version name that could drift.
    groups = sorted((g["name"], sorted(g["members"])) for g in universe["groups"])
    fingerprint = hashlib.sha256(json.dumps(groups, separators=(",", ":")).encode()).hexdigest()
    if universe["version"] == "radar-universe-v2" and fingerprint == "29bbed1b91b5168675e370a0d2000c07ceb254d0cb3c6c60a960d0be74981fb0":
        versions.append("radar-universe-v1")
    return versions


def empty_comparison(symbol: str, group: str | None, universe: dict, now: float) -> dict:
    groups = [g for g in universe["groups"] if symbol in g["members"]]
    selected = next((g for g in groups if g["name"] == group), groups[0] if groups else None)
    return {"symbol": symbol, "state": "insufficient" if selected else "ungrouped", "reason": "No recorded comparison yet." if selected else "No curated Radar group for this symbol.",
            "groups": groups, "group": selected, "universe_version": universe["version"],
            "accepted_group_versions": accepted_group_versions(universe),
            "source": "Radar curated groups · Tradier sampled trades", "methodology": "sampled_last_trade_observation",
            "window_minutes": 15, "window": None, "session": None, "live": False,
            "generated_at": iso(now), "rows": [], "coverage": None}


def _endpoint(quote: dict | None, record: dict) -> tuple[dict | None, str | None]:
    if quote is None:
        return None, "Missing observation"
    try:
        last = float(quote["last"])
        retrieved = epoch(quote["retrieved_at"])
        trade = float(quote["trade_time_ms"]) / 1000
        if not math.isfinite(last) or last <= 0 or not math.isfinite(trade):
            return None, "Invalid price or trade time"
        if not epoch(record["started_at"]) <= retrieved <= epoch(record["finished_at"]):
            return None, "Observation outside its pass"
        if not 0 <= retrieved - trade <= TRADE_AGE_SECONDS:
            return None, "Stale or future trade time"
        return {"price": last, "retrieved_at": quote["retrieved_at"], "trade_at": iso(trade)}, None
    except (TypeError, ValueError, OverflowError):
        return None, "Missing or invalid price/time"


def compare_group(store: RadarStore, result: dict, *, today: str, now: float, live: bool) -> dict:
    """No future rows, per-symbol endpoint substitution, overnight carry or gap filling."""
    passes = store.comparison_passes(today, iso(now), current_session=live)
    session_result = empty_comparison(result["symbol"], result["group"]["name"],
                                      {"groups": result["groups"], "version": result["universe_version"]}, now)
    session_result["window_minutes"] = None
    session_result["accepted_group_versions"] = result["accepted_group_versions"]
    recovery_result = {**session_result, "rows": []}
    result = _compare_window(store, result, passes, now=now, live=live, mode="recent")
    result["session_context"] = _compare_window(store, session_result, passes, now=now, live=live, mode="session")
    result["recovery_context"] = _compare_window(store, recovery_result, passes, now=now, live=live, mode="recovery")
    return result


def _recovery_anchor(store: RadarStore, result: dict, passes: list[dict], usable: list[dict]) -> dict | None:
    """Selected-stock sampled minimum; every peer later uses this exact pass."""
    end = usable[0]
    end_time = epoch(end["started_at"])
    if any(p["universe_version"] not in result["accepted_group_versions"] for p in usable):
        result["reason"] = "Recorded group version changed during the session; sampled-low context is unavailable."
        return None
    # One indexed symbol/session read, not a full universe read for every minute.
    quotes = {q["pass_id"]: q for q in store.quotes(session_date=result["session"], symbol=result["symbol"])}
    eligible = []
    for record in usable:
        if not 0 <= epoch(record["finished_at"]) - epoch(record["started_at"]) <= PASS_TOLERANCE_SECONDS:
            continue
        point, _ = _endpoint(quotes.get(record["id"]), record)
        if point:
            eligible.append((record, point))
    searched = [p for p in passes if epoch(p["started_at"]) <= end_time]
    search_start = min(epoch(p["started_at"]) for p in searched)
    result["low_search"] = {"start": iso(search_start), "end": end["started_at"],
                            "eligible_samples": len(eligible), "omitted_samples": len(searched) - len(eligible),
                            "eligible_minutes": len({int(epoch(p["started_at"]) // 60) for p, _ in eligible}),
                            "expected_minutes": int(end_time // 60 - search_start // 60) + 1}
    if not eligible:
        result["reason"] = "No eligible selected-stock samples to locate a recorded low."
        return None
    # Repeated equal lows use the earliest observation, with pass ID breaking time ties.
    start, low = min(eligible, key=lambda item: (item[1]["price"], epoch(item[0]["started_at"]), item[0]["id"]))
    result["low_anchor"] = {"symbol": result["symbol"], "pass_id": start["id"], "pass_at": start["started_at"], **low}
    if not any(p["id"] == end["id"] for p, _ in eligible):
        result["reason"] = "Selected stock has no eligible latest sample; rebound context is unavailable."
        return None
    if len(eligible) < 2:
        result["reason"] = "At least two eligible selected-stock samples are needed for rebound context."
        return None
    if end_time - epoch(start["started_at"]) < 60:
        result["reason"] = "The recorded low is too recent: no rebound window of at least one minute yet."
        return None
    result["window_minutes"] = (end_time - epoch(start["started_at"])) / 60
    return start



def compare_entry(store: RadarStore, result: dict, *, today: str, now: float, live: bool,
                  regular_start: float, regular_end: float) -> dict:
    # Never carry an overnight session into an entry comparison, even after hours.
    passes = store.comparison_passes(today, iso(now), current_session=True)
    passes = [p for p in passes if regular_start <= epoch(p["started_at"])
              and epoch(p["finished_at"]) <= regular_end]
    return _compare_window(store, result, passes, now=now, live=live, mode="entry")


def _entry_anchor(store: RadarStore, result: dict, usable: list[dict]) -> dict | None:
    boundary = epoch(result["entry"]["not_before"])
    deadline = boundary + PASS_TOLERANCE_SECONDS
    relevant = [p for p in usable if epoch(p["started_at"]) >= boundary]
    if any(p["universe_version"] not in result["accepted_group_versions"] for p in relevant):
        result["reason"] = "Recorded group version differs from the current membership."
        return None
    candidates = sorted((p for p in relevant if epoch(p["started_at"]) <= deadline),
                        key=lambda p: (epoch(p["started_at"]), p["id"]))
    selected_quotes = {q["pass_id"]: q for q in store.quotes(session_date=result["session"], symbol=result["symbol"])}
    start = None
    for p in candidates:
        if not 0 <= epoch(p["finished_at"]) - epoch(p["started_at"]) <= PASS_TOLERANCE_SECONDS:
            continue
        point, _ = _endpoint(selected_quotes.get(p["id"]), p)
        if point and epoch(point["trade_at"]) >= boundary:
            start = p
            break
    if start is None:
        result["reason"] = "No eligible post-entry sample within the 90-second search window; no later baseline substituted."
        return None
    result["entry"]["baseline_delay_seconds"] = epoch(start["started_at"]) - epoch(result["entry"]["recorded_at"])
    result["entry"]["baseline_at"] = start["started_at"]
    end = usable[0]
    latest, _ = _endpoint(selected_quotes.get(end["id"]), end)
    if not latest or epoch(latest["trade_at"]) < boundary:
        result["reason"] = "Selected stock has no eligible latest sample; since-entry context is unavailable."
        return None
    if epoch(end["started_at"]) - epoch(start["started_at"]) < 60:
        result["reason"] = "Waiting for at least one minute after the post-entry baseline."
        return None
    result["window_minutes"] = (epoch(end["started_at"]) - epoch(start["started_at"])) / 60
    return start


def _compare_window(store: RadarStore, result: dict, passes: list[dict], *, now: float,
                    live: bool, mode: str) -> dict:
    result["live"] = live
    if not passes:
        result["reason"] = "Waiting for this session's recorded observations." if live else "No recorded session yet."
        return result
    result["session"] = passes[0]["session_date"]
    usable = [p for p in passes if p["status"] in ("ok", "partial")]
    if not usable:
        result["reason"] = "No usable recorded passes in this session."
        return result
    end = usable[0]
    end_time = epoch(end["started_at"])
    stale = live and now - end_time > STALE_SECONDS
    if mode in ("entry", "recovery"):
        if stale:
            result["state"] = "stale"
        start = _entry_anchor(store, result, usable) if mode == "entry" else _recovery_anchor(store, result, passes, usable)
        if start is None:
            if stale:
                result["reason"] = "Recording is stale. " + result["reason"]
            return result
    elif mode == "session":
        # Never move the baseline forward to find a more convenient price/version.
        start = usable[-1]
        if end_time - epoch(start["started_at"]) < 60:
            result.update(state="stale" if stale else "insufficient",
                          reason="Session context needs two recorded passes at least one minute apart.")
            return result
        result["window_minutes"] = (end_time - epoch(start["started_at"])) / 60
    else:
        target = end_time - WINDOW_SECONDS
        start = next((p for p in usable if epoch(p["started_at"]) <= target), None)
        if start is None or target - epoch(start["started_at"]) > PASS_TOLERANCE_SECONDS:
            result.update(state="stale" if stale else "insufficient", reason="A complete 15-minute observation window is unavailable.")
            return result
    # Historical membership is not persisted: fail visibly instead of applying today's list to an old version.
    if any(p["universe_version"] not in result["accepted_group_versions"] for p in (start, end)):
        result["reason"] = "Recorded group version differs from the current membership."
        return result
    if any(not 0 <= epoch(p["finished_at"]) - epoch(p["started_at"]) <= PASS_TOLERANCE_SECONDS for p in (start, end)):
        result["reason"] = "Recording passes took too long for an aligned comparison."
        return result
    result["recorded_versions"] = sorted({p["universe_version"] for p in (start, end)})
    result["window"] = {"start": start["started_at"], "end": end["started_at"],
                        "start_pass_id": start["id"], "end_pass_id": end["id"]}
    quotes = [{q["symbol"]: q for q in store.quotes(pass_id=p["id"])} for p in (start, end)]
    symbol, members = result["symbol"], result["group"]["members"]
    symbols = list(dict.fromkeys([symbol, *members, *BENCHMARKS]))
    for ticker in symbols:
        a, a_error = _endpoint(quotes[0].get(ticker), start)
        b, b_error = _endpoint(quotes[1].get(ticker), end)
        if mode == "entry":
            if a and epoch(a["trade_at"]) < epoch(result["entry"]["not_before"]):
                a, a_error = None, "Trade precedes the post-entry boundary"
            if a and b and epoch(b["trade_at"]) < epoch(a["trade_at"]):
                b, b_error = None, "Latest trade precedes the baseline trade"
            if ticker == symbol and (not a or not b):
                result.update(window=None, rows=[], reason="Selected stock has no eligible common-window observations.")
                return result
        change = (b["price"] / a["price"] - 1) * 100 if a and b else None
        if change is not None and not math.isfinite(change):
            change, b_error = None, "Invalid return"
        result["rows"].append({"symbol": ticker, "role": "selected" if ticker == symbol else "benchmark" if ticker in BENCHMARKS else "peer",
                               "change_pct": change, "reason": a_error or b_error, "start": a, "end": b})
    peers = [r for r in result["rows"] if r["role"] == "peer"]
    valid = [r for r in peers if r["change_pct"] is not None]
    missing = [r["symbol"] for r in result["rows"] if r["change_pct"] is None]
    start_time = epoch(start["started_at"])
    recorded = len({int(epoch(p["started_at"]) // 60) for p in usable
                    if start_time <= epoch(p["started_at"]) <= end_time})
    expected = int(end_time // 60 - start_time // 60) + 1
    result["coverage"] = {"peers_total": len(peers), "peers_available": len(valid),
                          "peers_up": sum(r["change_pct"] > 0 for r in valid),
                          "peers_down": sum(r["change_pct"] < 0 for r in valid), "missing": missing,
                          "recorded_minutes": recorded, "expected_minutes": expected}
    search = result.get("low_search")
    partial_search = bool(search and (search["eligible_minutes"] < search["expected_minutes"] or search["omitted_samples"]))
    partial = bool(missing) or recorded < expected or partial_search
    result["state"] = "stale" if stale else "partial" if partial else "ready"
    result["reason"] = "Recording is stale; these are older observations." if stale else "Some observations are missing or ineligible." if partial else None
    if mode == "recovery":
        selected = next(row for row in result["rows"] if row["role"] == "selected")
        result["at_recorded_low"] = selected["change_pct"] == 0
    return result
