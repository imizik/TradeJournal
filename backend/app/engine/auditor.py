"""Read-only trade audit against independent math on existing cached evidence.

Never fetches provider data. Missing evidence and old versions cannot produce a
passing badge; a match is reproducibility, not broker/source verification.
"""
from typing import Optional

from app.engine.alpaca import ALPACA_DATA_FEED, CACHE_DIR
from app.engine import metric_reference as reference
from app.engine.metric_validation import CachedBars, evidence, record, validate_fill, validate_trade
from app.engine.metric_versions import CONTEXT_VERSION
from app.models import Fill, FillMarketContext, Trade, TradePathMetrics


def compute_audit(trade: Trade, fills: list[Fill], ctx_by_fill: dict[str, FillMarketContext], path: Optional[TradePathMetrics]) -> dict:
    cache = CachedBars(CACHE_DIR, ALPACA_DATA_FEED)
    trade_data, fill_data = record(trade), [record(f) for f in fills]
    contexts = {str(k): record(v) for k, v in ctx_by_fill.items()}
    entries = sorted((f for f in fill_data if f["side"] in reference.OPEN_SIDES),
                     key=lambda f: (reference.timestamp(f["executed_at"]), str(f["id"])))
    direction = reference.exposure_direction(entries[0]) if entries else None
    try:
        validation = validate_trade(trade_data, fill_data, contexts, record(path) if path else None, cache, include_samples=True)
    except (ValueError, KeyError, TypeError) as exc:
        validation = {"checks": [{"field": "input_integrity", "status": "error", "reason": str(exc)}],
                      "broker_verification": "not_performed", "fills": [], "underlying": None, "option": None}
    return {
        "trade_id": str(trade.id), "ticker": trade.ticker, "instrument_type": trade.instrument_type,
        "option_type": trade.option_type, "strike": trade.strike, "expiration": str(trade.expiration) if trade.expiration else None,
        "direction": "bullish" if direction is True else "bearish" if direction is False else None,
        "opened_at_et": str(trade.opened_at), "closed_at_et": str(trade.closed_at) if trade.closed_at else None,
        "status": trade.status, "reference_revision": reference.REFERENCE_REVISION,
        "fills": [_audit_fill_data(f, contexts.get(str(f["id"])), cache) for f in sorted(fill_data, key=lambda f: (f["executed_at"], str(f["id"])))],
        "path": _path_output(trade_data, entries[0] if entries else None, contexts, validation, path),
        "indicators": _audit_indicators(trade.ticker, entries[0], cache) if entries else None,
        "validation": validation,
    }


_ALIASES = {"underlying_price": "entry_underlying_price", "vwap": "entry_vwap", "vs_vwap_pct": "entry_vs_vwap_pct",
            "day_high_so_far": "entry_day_high_so_far", "day_low_so_far": "entry_day_low_so_far",
            "day_range_used_pct": "entry_day_range_used_pct", "premarket_high": "premarket_high", "premarket_low": "premarket_low",
            "or5_high": "opening_range_5m_high", "or5_low": "opening_range_5m_low", "rsi_14": "entry_rsi_14"}


def _audit_fill_data(fill, ctx, cache):
    report = validate_fill(fill, ctx, cache)
    intraday = report["intraday"]
    values = intraday["values"]
    raw = intraday.get("raw_bar")
    dt = reference.timestamp(fill["executed_at"]).astimezone(reference.ET)
    day = dt.date()
    path = cache.root / "stocks" / "1Min" / cache.feed / fill["ticker"] / f"{day}.json"
    back = int((dt - reference.timestamp(raw["t"]).astimezone(reference.ET)).total_seconds() / 60) if raw else None
    raw_bar = {"timestamp_utc": raw["t"], "timestamp_et": reference.timestamp(raw["t"]).astimezone(reference.ET).strftime("%H:%M %Z"),
               "open": raw["o"], "high": raw["h"], "low": raw["l"], "close": raw["c"], "volume": int(raw["v"]),
               "bar_vwap": None, "bars_back": back} if raw else None
    discrepancies = [c["reason"] for c in report["checks"] if c["status"] == "error"]
    discrepancies += [f"{c['field']}: stored={c.get('stored')} reference={c.get('reference')}" for c in report["checks"] if c["status"] == "mismatch"]
    if ctx and ctx.get("calculation_version") != CONTEXT_VERSION:
        discrepancies.insert(0, "Stored context predates the current calculation version")
    return {"fill_id": str(fill["id"]), "is_entry": fill["side"] in reference.OPEN_SIDES, "side": fill["side"],
            "executed_at_et": str(fill["executed_at"]), "contracts": float(fill["contracts"]), "price": float(fill["price"]),
            "cache_file": str(path.relative_to(cache.root)) if path.exists() else None, "cache_exists": path.exists(),
            "total_bars_in_file": intraday.get("total_bars", 0), "rth_bars_to_fill": intraday.get("rth_bars", 0),
            "pm_bars": intraday.get("pm_bars", 0), "or5_bars": intraday.get("or5_bars", 0), "raw_bar": raw_bar, "bars_back": back,
            "context_as_of": values.get("entry_context_as_of"), "formulas": {},
            "structure": {"day_high_bar_et": _et(intraday.get("day_high_bar")), "day_low_bar_et": _et(intraday.get("day_low_bar")),
                          **{label: values.get(key) for label, key in (("pm_high", "premarket_high"), ("pm_low", "premarket_low"),
                           ("or5_high", "opening_range_5m_high"), ("or5_low", "opening_range_5m_low"),
                           ("or15_high", "opening_range_15m_high"), ("or15_low", "opening_range_15m_low"))}},
            "stored": {alias: (ctx or {}).get(key) for alias, key in _ALIASES.items()},
            "recomputed": {alias: values.get(key) for alias, key in _ALIASES.items() if alias != "rsi_14"},
            "discrepancies": discrepancies, "checks": report["checks"]}


def _et(ts):
    return reference.timestamp(ts).astimezone(reference.ET).strftime("%Y-%m-%d %H:%M") if ts else None


def _path_output(trade, entry, contexts, validation, path):
    if not trade.get("closed_at") or entry is None:
        return None
    result = validation.get("underlying") or {"values": {}, "reason": "Unable to validate inputs"}
    values = result["values"]
    ctx = contexts.get(str(entry["id"])) or {}
    anchor = ctx.get("entry_underlying_price") or entry.get("underlying_price_at_fill")
    if anchor is None and trade["instrument_type"] == "stock":
        anchor = validation.get("accounting", {}).get("avg_entry_premium")
    return {"window_bars": result.get("bars", 0), "window_start_et": _et(trade["opened_at"]), "window_end_et": _et(trade["closed_at"]),
            "entry_underlying_used": anchor, "bullish": reference.exposure_direction(entry),
            "mfe_pct_recomputed": values.get("underlying_mfe_pct"), "mae_pct_recomputed": values.get("underlying_mae_pct"),
            "mfe_bar_et": _et(result.get("mfe_bar")), "mae_bar_et": _et(result.get("mae_bar")),
            "mfe_bar_high": result.get("mfe_high"), "mfe_bar_low": result.get("mfe_low"),
            "mae_bar_high": result.get("mae_high"), "mae_bar_low": result.get("mae_low"),
            "error": result.get("reason"), "stored": {"mfe_pct": path.underlying_mfe_pct, "mae_pct": path.underlying_mae_pct,
                "exit_efficiency": path.underlying_exit_efficiency, "time_to_mfe_mins": path.time_to_underlying_mfe_minutes,
                "time_to_mae_mins": path.time_to_underlying_mae_minutes} if path else {}}


def _audit_indicators(ticker, fill, cache):
    result = evidence(lambda: reference.daily_indicators(cache.daily(ticker), fill["executed_at"]))
    if result["reason"]:
        return {"error": result["reason"]}
    return {"total_daily_bars_available": result["bars"], "earliest_bar": result["earliest"], "latest_bar": result["latest"],
            "sma_20_bars_needed": 20, "sma_50_bars_needed": 50, "rsi_14_window": 14,
            "warmup_note": "Only completed days before the fill. A requested history window does not guarantee available bars.",
            "rsi_formula": "First-delta-seeded Wilder recurrence (alpha=1/14); zero smoothed loss remains unavailable under this journal's formula.",
            "ema_formula": "First-close-seeded recurrence: alpha=2/(span+1). Compare only identical feed, history, and adjustments."}
