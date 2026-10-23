"""Observed group returns from two common Radar passes; never a detector or signal."""
from datetime import UTC, datetime
import math

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


def empty_comparison(symbol: str, group: str | None, universe: dict, now: float) -> dict:
    groups = [g for g in universe["groups"] if symbol in g["members"]]
    selected = next((g for g in groups if g["name"] == group), groups[0] if groups else None)
    return {"symbol": symbol, "state": "insufficient" if selected else "ungrouped", "reason": "No recorded comparison yet." if selected else "No curated Radar group for this symbol.",
            "groups": groups, "group": selected, "universe_version": universe["version"],
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
    result = _compare_window(store, result, passes, now=now, live=live, session_window=False)
    result["session_context"] = _compare_window(store, session_result, passes, now=now, live=live, session_window=True)
    return result


def _compare_window(store: RadarStore, result: dict, passes: list[dict], *, now: float,
                    live: bool, session_window: bool) -> dict:
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
    if session_window:
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
    if any(p["universe_version"] != result["universe_version"] for p in (start, end)):
        result["reason"] = "Recorded group version differs from the current membership."
        return result
    if any(not 0 <= epoch(p["finished_at"]) - epoch(p["started_at"]) <= PASS_TOLERANCE_SECONDS for p in (start, end)):
        result["reason"] = "Recording passes took too long for an aligned comparison."
        return result
    result["window"] = {"start": start["started_at"], "end": end["started_at"],
                        "start_pass_id": start["id"], "end_pass_id": end["id"]}
    quotes = [{q["symbol"]: q for q in store.quotes(pass_id=p["id"])} for p in (start, end)]
    symbol, members = result["symbol"], result["group"]["members"]
    symbols = list(dict.fromkeys([symbol, *members, *BENCHMARKS]))
    for ticker in symbols:
        a, a_error = _endpoint(quotes[0].get(ticker), start)
        b, b_error = _endpoint(quotes[1].get(ticker), end)
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
    partial = bool(missing) or recorded < expected
    result["state"] = "stale" if stale else "partial" if partial else "ready"
    result["reason"] = "Recording is stale; these are older observations." if stale else "Some observations are missing or ineligible." if partial else None
    return result
