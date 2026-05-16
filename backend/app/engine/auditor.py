"""
Compute a structured audit report for a single trade.

Used by GET /market-context/audit/{trade_id}.
Re-reads the same cached bars and re-derives all computed values so the UI can
show intermediate steps and verify nothing is wrong with timezone handling,
bar selection, or formula application.

Does NOT modify any data.
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

import pandas as pd

from app.engine.alpaca import ALPACA_DATA_FEED, CACHE_DIR, fetch_minute_bars_for_date
from app.engine.indicators import bars_to_df, _f, _pct_diff
from app.engine.trade_path import _date_range, _is_bullish
from app.models import Fill, FillMarketContext, Trade, TradePathMetrics

log = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def compute_audit(
    trade: Trade,
    fills: list[Fill],
    ctx_by_fill: dict[str, FillMarketContext],
    path: Optional[TradePathMetrics],
) -> dict:
    entry_fills = [f for f in fills if f.side in ("buy_to_open", "sell_to_open", "buy")]
    exit_fills = [f for f in fills if f not in entry_fills]
    entry_fill = min(entry_fills, key=lambda f: f.executed_at) if entry_fills else None
    last_exit = max(exit_fills, key=lambda f: f.executed_at) if exit_fills else None

    bullish = _is_bullish(trade, entry_fill) if entry_fill else None

    # Gather all fill audit records
    fill_audits = []
    for fill in sorted(fills, key=lambda f: f.executed_at):
        is_entry = fill in entry_fills
        ctx = ctx_by_fill.get(str(fill.id))
        fill_audits.append(_audit_fill(fill, is_entry, ctx))

    # Trade path audit
    path_audit = None
    if trade.opened_at and trade.closed_at and entry_fill:
        path_audit = _audit_path(trade, entry_fill, bullish, path)

    # Indicator lookback from daily bars cache
    indic_audit = None
    if entry_fill:
        indic_audit = _audit_indicators(trade.ticker, entry_fill)

    return {
        "trade_id": str(trade.id),
        "ticker": trade.ticker,
        "instrument_type": trade.instrument_type,
        "option_type": trade.option_type,
        "strike": trade.strike,
        "expiration": str(trade.expiration) if trade.expiration else None,
        "direction": "bullish" if bullish else ("bearish" if bullish is False else None),
        "opened_at_et": str(trade.opened_at),
        "closed_at_et": str(trade.closed_at) if trade.closed_at else None,
        "status": trade.status,
        "fills": fill_audits,
        "path": path_audit,
        "indicators": indic_audit,
    }


# ---------------------------------------------------------------------------
# Per-fill audit
# ---------------------------------------------------------------------------

def _audit_fill(fill: Fill, is_entry: bool, ctx: Optional[FillMarketContext]) -> dict:
    fill_date = fill.executed_at.date()
    fill_dt_et = fill.executed_at.replace(tzinfo=ET)
    fill_dt_utc = fill_dt_et.astimezone(UTC)

    # Load cached minute bars
    cache_file = CACHE_DIR / "stocks" / "1Min" / ALPACA_DATA_FEED / fill.ticker / f"{fill_date.isoformat()}.json"
    bars_raw = json.loads(cache_file.read_text()) if cache_file.exists() else []

    # Build DataFrame
    df = bars_to_df(bars_raw)

    # Find the bar at or nearest to fill time (scan back up to 5 minutes)
    raw_bar = None
    bars_back = None
    for delta in range(6):
        t = fill_dt_utc - timedelta(minutes=delta)
        candidates = df[(df.index >= t - timedelta(seconds=30)) & (df.index <= t + timedelta(seconds=30))]
        if not candidates.empty:
            row = candidates.iloc[-1]
            raw_bar = {
                "timestamp_utc": str(candidates.index[-1]),
                "timestamp_et": str(candidates.index[-1].astimezone(ET).strftime("%H:%M %Z")),
                "open": round(float(row["open"]), 4),
                "high": round(float(row["high"]), 4),
                "low": round(float(row["low"]), 4),
                "close": round(float(row["close"]), 4),
                "volume": int(row.get("volume", 0)),
                "bar_vwap": round(float(row["bar_vwap"]), 4) if "bar_vwap" in row and not pd.isna(row["bar_vwap"]) else None,
                "bars_back": delta,
            }
            bars_back = delta
            break

    # Session boundaries
    def _et(h, m):
        return datetime(fill_date.year, fill_date.month, fill_date.day, h, m, tzinfo=ET).astimezone(UTC)

    pm_start = _et(4, 0)
    rth_open = _et(9, 30)
    or5_end  = _et(9, 35)
    or15_end = _et(9, 45)

    # Sub-ranges
    pm_bars    = df[(df.index >= pm_start) & (df.index < rth_open)]
    rth_to_fill = df[(df.index >= rth_open) & (df.index <= fill_dt_utc)]
    or5_bars   = df[(df.index >= rth_open) & (df.index < or5_end)]
    or15_bars  = df[(df.index >= rth_open) & (df.index < or15_end)]

    # Recompute key values
    entry_price = raw_bar["close"] if raw_bar else None
    day_high = float(rth_to_fill["high"].max()) if not rth_to_fill.empty else None
    day_low  = float(rth_to_fill["low"].min())  if not rth_to_fill.empty else None

    vwap = None
    cum_vol = None
    if not rth_to_fill.empty and fill_dt_et.hour * 60 + fill_dt_et.minute >= 9 * 60 + 30:
        vols = rth_to_fill["volume"]
        typical = (rth_to_fill["high"] + rth_to_fill["low"] + rth_to_fill["close"]) / 3
        vol_sum = float(vols.sum())
        if vol_sum > 0:
            vwap = round(float((typical * vols).sum() / vol_sum), 4)
            cum_vol = int(vol_sum)

    pm_high = float(pm_bars["high"].max()) if not pm_bars.empty else None
    pm_low  = float(pm_bars["low"].min())  if not pm_bars.empty else None
    or5_high = float(or5_bars["high"].max()) if not or5_bars.empty else None
    or5_low  = float(or5_bars["low"].min())  if not or5_bars.empty else None
    or15_high = float(or15_bars["high"].max()) if not or15_bars.empty else None
    or15_low  = float(or15_bars["low"].min())  if not or15_bars.empty else None

    # Find bar times for day high/low
    day_high_bar_et = None
    day_low_bar_et  = None
    if not rth_to_fill.empty:
        hi_idx = rth_to_fill["high"].idxmax()
        lo_idx = rth_to_fill["low"].idxmin()
        if hi_idx is not None:
            day_high_bar_et = hi_idx.astimezone(ET).strftime("%H:%M")
        if lo_idx is not None:
            day_low_bar_et = lo_idx.astimezone(ET).strftime("%H:%M")

    # Formula strings
    formulas = {}
    if entry_price and vwap:
        vs_vwap = _pct_diff(entry_price, vwap)
        formulas["entry_vs_vwap_pct"] = (
            f"({entry_price:.4f} - {vwap:.4f}) / {vwap:.4f} * 100 = {vs_vwap:+.4f}%"
            if vs_vwap is not None else "n/a"
        )
    if entry_price and day_high is not None and day_low is not None and day_high != day_low:
        rng_used = (entry_price - day_low) / (day_high - day_low) * 100
        formulas["day_range_used_pct"] = (
            f"({entry_price:.4f} - {day_low:.4f}) / ({day_high:.4f} - {day_low:.4f}) * 100 = {rng_used:.2f}%"
        )
    if entry_price and ctx and ctx.entry_ema_9:
        vs_ema9 = _pct_diff(entry_price, ctx.entry_ema_9)
        formulas["entry_vs_ema9_pct"] = (
            f"({entry_price:.4f} - {ctx.entry_ema_9:.4f}) / {ctx.entry_ema_9:.4f} * 100 = {vs_ema9:+.4f}%"
            if vs_ema9 is not None else "n/a"
        )

    # Stored vs recomputed comparison
    stored = {}
    recomputed = {}
    if ctx:
        stored = {
            "underlying_price": ctx.entry_underlying_price,
            "vwap": ctx.entry_vwap,
            "vs_vwap_pct": ctx.entry_vs_vwap_pct,
            "day_high_so_far": ctx.entry_day_high_so_far,
            "day_low_so_far": ctx.entry_day_low_so_far,
            "day_range_used_pct": ctx.entry_day_range_used_pct,
            "premarket_high": ctx.premarket_high,
            "premarket_low": ctx.premarket_low,
            "or5_high": ctx.opening_range_5m_high,
            "or5_low": ctx.opening_range_5m_low,
            "rsi_14": ctx.entry_rsi_14,
        }
    recomputed = {
        "underlying_price": entry_price,
        "vwap": vwap,
        "vs_vwap_pct": _pct_diff(entry_price, vwap),
        "day_high_so_far": day_high,
        "day_low_so_far": day_low,
        "day_range_used_pct": round((entry_price - day_low) / (day_high - day_low) * 100, 2)
            if entry_price and day_high and day_low and day_high != day_low else None,
        "premarket_high": pm_high,
        "premarket_low": pm_low,
        "or5_high": or5_high,
        "or5_low": or5_low,
    }

    # Discrepancy check: flag any stored vs recomputed difference > 0.05%
    discrepancies = []
    for key in ["underlying_price", "vwap", "day_high_so_far", "day_low_so_far"]:
        s = stored.get(key)
        r = recomputed.get(key)
        if s is not None and r is not None:
            diff = abs(s - r)
            if diff > 0.05:
                discrepancies.append(f"{key}: stored={s:.4f} recomputed={r:.4f} diff={diff:.4f}")

    return {
        "fill_id": str(fill.id),
        "is_entry": is_entry,
        "side": fill.side,
        "executed_at_et": str(fill.executed_at),
        "contracts": float(fill.contracts),
        "price": float(fill.price),
        "cache_file": str(cache_file.relative_to(CACHE_DIR.parent.parent)) if cache_file.exists() else None,
        "cache_exists": cache_file.exists(),
        "total_bars_in_file": len(bars_raw),
        "rth_bars_to_fill": len(rth_to_fill),
        "pm_bars": len(pm_bars),
        "or5_bars": len(or5_bars),
        "raw_bar": raw_bar,
        "bars_back": bars_back,
        "formulas": formulas,
        "structure": {
            "day_high_bar_et": day_high_bar_et,
            "day_low_bar_et": day_low_bar_et,
            "pm_high": pm_high,
            "pm_low": pm_low,
            "or5_high": or5_high,
            "or5_low": or5_low,
            "or15_high": or15_high,
            "or15_low": or15_low,
        },
        "stored": stored,
        "recomputed": recomputed,
        "discrepancies": discrepancies,
    }


# ---------------------------------------------------------------------------
# Trade path audit
# ---------------------------------------------------------------------------

def _audit_path(
    trade: Trade,
    entry_fill: Fill,
    bullish: Optional[bool],
    stored_path: Optional[TradePathMetrics],
) -> dict:
    entry_ctx_underlying = None

    opened_et = trade.opened_at.replace(tzinfo=ET)
    closed_et = trade.closed_at.replace(tzinfo=ET)
    opened_utc = opened_et.astimezone(UTC)
    closed_utc = closed_et.astimezone(UTC)

    # Gather cached bars across hold window
    all_bars: list[dict] = []
    for day in _date_range(trade.opened_at.date(), trade.closed_at.date()):
        day_bars = fetch_minute_bars_for_date([trade.ticker], day).get(trade.ticker, [])
        all_bars.extend(day_bars)

    df = bars_to_df(all_bars)
    window = df[(df.index >= opened_utc) & (df.index <= closed_utc)]

    entry_bar_candidates = df[df.index <= opened_utc + timedelta(minutes=1)]
    entry_underlying = float(entry_bar_candidates.iloc[-1]["close"]) if not entry_bar_candidates.empty else None

    if window.empty or entry_underlying is None or bullish is None:
        return {
            "window_bars": len(window),
            "window_start_et": opened_et.strftime("%Y-%m-%d %H:%M"),
            "window_end_et": closed_et.strftime("%Y-%m-%d %H:%M"),
            "error": "Not enough data to compute path",
            "stored": _path_stored(stored_path),
        }

    if bullish:
        favorable = (window["high"] - entry_underlying) / entry_underlying * 100
        adverse   = (entry_underlying - window["low"]) / entry_underlying * 100
    else:
        favorable = (entry_underlying - window["low"]) / entry_underlying * 100
        adverse   = (window["high"] - entry_underlying) / entry_underlying * 100

    mfe_idx = favorable.idxmax()
    mae_idx = adverse.idxmax()
    mfe_pct = float(favorable.max())
    mae_pct = float(adverse.max())

    mfe_bar_et = mfe_idx.astimezone(ET).strftime("%Y-%m-%d %H:%M") if mfe_idx is not None else None
    mae_bar_et = mae_idx.astimezone(ET).strftime("%Y-%m-%d %H:%M") if mae_idx is not None else None

    return {
        "window_bars": len(window),
        "window_start_et": opened_et.strftime("%Y-%m-%d %H:%M"),
        "window_end_et": closed_et.strftime("%Y-%m-%d %H:%M"),
        "entry_underlying_used": entry_underlying,
        "bullish": bullish,
        "mfe_pct_recomputed": round(mfe_pct, 4),
        "mae_pct_recomputed": round(mae_pct, 4),
        "mfe_bar_et": mfe_bar_et,
        "mfe_bar_high": round(float(window.loc[mfe_idx]["high"]), 4) if mfe_idx is not None else None,
        "mfe_bar_low":  round(float(window.loc[mfe_idx]["low"]), 4)  if mfe_idx is not None else None,
        "mae_bar_et": mae_bar_et,
        "mae_bar_high": round(float(window.loc[mae_idx]["high"]), 4) if mae_idx is not None else None,
        "mae_bar_low":  round(float(window.loc[mae_idx]["low"]), 4)  if mae_idx is not None else None,
        "stored": _path_stored(stored_path),
    }


def _path_stored(path: Optional[TradePathMetrics]) -> dict:
    if not path:
        return {}
    return {
        "mfe_pct": path.underlying_mfe_pct,
        "mae_pct": path.underlying_mae_pct,
        "exit_efficiency": path.underlying_exit_efficiency,
        "time_to_mfe_mins": path.time_to_underlying_mfe_minutes,
        "time_to_mae_mins": path.time_to_underlying_mae_minutes,
    }


# ---------------------------------------------------------------------------
# Indicator lookback audit
# ---------------------------------------------------------------------------

def _audit_indicators(ticker: str, entry_fill: Fill) -> dict:
    cache_path = CACHE_DIR / "stocks" / "1Day" / ALPACA_DATA_FEED / f"{ticker}.json"
    if not cache_path.exists():
        return {"error": "Daily bar cache not found", "cache_file": str(cache_path)}

    bars_raw = json.loads(cache_path.read_text())
    fill_date = entry_fill.executed_at.date()

    # Bars up to and including fill_date
    df = bars_to_df(bars_raw)
    df_to_fill = df[df.index.tz_convert(ET).map(lambda t: t.date()) <= fill_date]

    total_bars = len(df_to_fill)
    if total_bars == 0:
        return {"error": "No daily bars up to fill date"}

    earliest = df_to_fill.index[0].astimezone(ET).strftime("%Y-%m-%d")
    latest   = df_to_fill.index[-1].astimezone(ET).strftime("%Y-%m-%d")

    return {
        "cache_file": str(cache_path.relative_to(CACHE_DIR.parent.parent)),
        "total_daily_bars_available": total_bars,
        "earliest_bar": earliest,
        "latest_bar": latest,
        "sma_20_bars_needed": 20,
        "sma_50_bars_needed": 50,
        "rsi_14_window": 14,
        "warmup_note": f"400-day fetch window ensures {total_bars} bars available for indicator warmup",
        "rsi_formula": "Wilder smoothing via ewm(alpha=1/14, adjust=False); seeds from first bar (converges after ~50 bars with large warmup)",
        "ema_formula": "ewm(span=N, adjust=False) — standard EMA, matches most charting platforms within a few cents",
    }
