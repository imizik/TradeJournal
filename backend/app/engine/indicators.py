"""
Local indicator computation from raw bar data using pandas.
No external indicator library required — all formulas are implemented directly.

All public functions accept Alpaca bar dicts (keys: t, o, h, l, c, v, vw)
and return results keyed by date string "YYYY-MM-DD" or hour string "YYYY-MM-DD HH".
"""

import math
import logging
from datetime import date, datetime
from typing import Optional
from zoneinfo import ZoneInfo

import pandas as pd

log = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")


# ---------------------------------------------------------------------------
# DataFrame builder
# ---------------------------------------------------------------------------

def bars_to_df(bars: list[dict]) -> pd.DataFrame:
    """Convert an Alpaca bar list to a UTC-indexed DataFrame."""
    if not bars:
        return pd.DataFrame()
    df = pd.DataFrame(bars)
    df["t"] = pd.to_datetime(df["t"], utc=True)
    df = df.sort_values("t").set_index("t")
    rename = {"o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"}
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
    if "vw" in df.columns:
        df = df.rename(columns={"vw": "bar_vwap"})
    return df


# ---------------------------------------------------------------------------
# Indicator implementations (pure pandas, Wilder smoothing where specified)
# ---------------------------------------------------------------------------

def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def _sma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window=window).mean()


def _rsi(series: pd.Series, window: int = 14) -> pd.Series:
    """Wilder's RSI (alpha = 1/window)."""
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1 / window, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / window, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, float("nan"))
    return 100 - (100 / (1 + rs))


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 14) -> pd.Series:
    """Wilder's ATR."""
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    return tr.ewm(alpha=1 / window, adjust=False).mean()


def _macd(
    series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[pd.Series, pd.Series, pd.Series]:
    macd_line = _ema(series, fast) - _ema(series, slow)
    signal_line = _ema(macd_line, signal)
    return macd_line, signal_line, macd_line - signal_line


# ---------------------------------------------------------------------------
# Public: daily indicator series
# ---------------------------------------------------------------------------

def compute_daily_indicators(bars: list[dict]) -> dict[str, dict]:
    """
    Compute all daily indicators from Alpaca daily bars.
    Returns {date_str: {sma_20, sma_50, ema_9, ema_20, rsi_14, macd,
                         macd_signal, macd_histogram, atr_14}}.
    Dates are the bar's calendar date (Alpaca daily bars close at ~16:00 ET,
    timestamp is typically 05:00 UTC the same calendar day).
    """
    df = bars_to_df(bars)
    if df.empty or len(df) < 10:
        return {}

    df["sma_20"] = _sma(df["close"], 20)
    df["sma_50"] = _sma(df["close"], 50)
    df["ema_9"] = _ema(df["close"], 9)
    df["ema_20"] = _ema(df["close"], 20)
    df["rsi_14"] = _rsi(df["close"], 14)
    df["atr_14"] = _atr(df["high"], df["low"], df["close"], 14)
    macd_line, signal_line, histogram = _macd(df["close"])
    df["macd"] = macd_line
    df["macd_signal"] = signal_line
    df["macd_histogram"] = histogram

    result: dict[str, dict] = {}
    for ts, row in df.iterrows():
        # Alpaca daily bar timestamps are UTC. Convert to ET date.
        et_date = ts.astimezone(ET).strftime("%Y-%m-%d")
        result[et_date] = {
            "sma_20": _f(row.get("sma_20")),
            "sma_50": _f(row.get("sma_50")),
            "ema_9": _f(row.get("ema_9")),
            "ema_20": _f(row.get("ema_20")),
            "rsi_14": _f(row.get("rsi_14")),
            "atr_14": _f(row.get("atr_14")),
            "macd": _f(row.get("macd")),
            "macd_signal": _f(row.get("macd_signal")),
            "macd_histogram": _f(row.get("macd_histogram")),
        }
    return result


# ---------------------------------------------------------------------------
# Public: intraday context from minute bars
# ---------------------------------------------------------------------------

def analyze_minute_bars(bars: list[dict], fill_dt: datetime) -> dict:
    """
    Compute intraday market context for a fill from 1-minute bars.

    fill_dt: naive datetime treated as America/New_York (as stored in the DB).
    Returns a flat dict of context fields — all values may be None.
    """
    df = bars_to_df(bars)
    if df.empty:
        return {}

    # Treat fill_dt as ET; convert to UTC for DataFrame index comparison
    fill_dt_et = fill_dt.replace(tzinfo=ET)
    fill_dt_utc = fill_dt_et.astimezone(UTC)

    # Bars at or before fill time
    bars_to_fill = df[df.index <= fill_dt_utc]
    if bars_to_fill.empty:
        return {}

    fill_bar = bars_to_fill.iloc[-1]
    entry_price = float(fill_bar["close"])
    entry_volume = int(fill_bar.get("volume", 0)) if not _nan(fill_bar.get("volume")) else None

    fill_date = fill_dt_et.date()

    # Session boundary timestamps (UTC)
    def _et_to_utc(h: int, m: int) -> pd.Timestamp:
        dt = datetime(fill_date.year, fill_date.month, fill_date.day, h, m, tzinfo=ET)
        return pd.Timestamp(dt).tz_convert("UTC")

    pm_start = _et_to_utc(4, 0)
    rth_open = _et_to_utc(9, 30)
    or5_end = _et_to_utc(9, 35)
    or15_end = _et_to_utc(9, 45)

    # Premarket bars (04:00–09:29 ET)
    pm_bars = df[(df.index >= pm_start) & (df.index < rth_open)]
    premarket_high = _series_max(pm_bars, "high")
    premarket_low = _series_min(pm_bars, "low")

    # Opening range bars
    or5_bars = df[(df.index >= rth_open) & (df.index < or5_end)]
    or15_bars = df[(df.index >= rth_open) & (df.index < or15_end)]
    or5_high = _series_max(or5_bars, "high")
    or5_low = _series_min(or5_bars, "low")
    or15_high = _series_max(or15_bars, "high")
    or15_low = _series_min(or15_bars, "low")

    # RTH bars up to fill (for day high/low so far and cumulative VWAP)
    rth_to_fill = df[(df.index >= rth_open) & (df.index <= fill_dt_utc)]
    day_high = _series_max(rth_to_fill, "high")
    day_low = _series_min(rth_to_fill, "low")

    # Cumulative VWAP (RTH only — undefined before open)
    vwap: Optional[float] = None
    cum_volume: Optional[int] = None
    if not rth_to_fill.empty and fill_dt_et.hour * 60 + fill_dt_et.minute >= 9 * 60 + 30:
        vols = rth_to_fill["volume"]
        typical = (rth_to_fill["high"] + rth_to_fill["low"] + rth_to_fill["close"]) / 3
        vol_sum = float(vols.sum())
        if vol_sum > 0:
            vwap = round(float((typical * vols).sum() / vol_sum), 4)
        cum_volume = int(vol_sum)

    # Day range used %
    day_range_used: Optional[float] = None
    if day_high and day_low and day_high != day_low:
        day_range_used = round((entry_price - day_low) / (day_high - day_low) * 100, 2)

    return {
        "entry_underlying_price": round(entry_price, 4),
        "entry_vwap": vwap,
        "entry_vs_vwap_pct": _pct_diff(entry_price, vwap),
        "entry_volume": entry_volume,
        "cumulative_volume_at_entry": cum_volume,
        "entry_day_high_so_far": day_high,
        "entry_day_low_so_far": day_low,
        "entry_day_range_used_pct": day_range_used,
        "entry_distance_from_day_high_pct": _pct_diff(entry_price, day_high),
        "entry_distance_from_day_low_pct": _pct_diff(entry_price, day_low),
        "premarket_high": premarket_high,
        "premarket_low": premarket_low,
        "entry_distance_from_premarket_high_pct": _pct_diff(entry_price, premarket_high),
        "entry_distance_from_premarket_low_pct": _pct_diff(entry_price, premarket_low),
        "opening_range_5m_high": or5_high,
        "opening_range_5m_low": or5_low,
        "opening_range_15m_high": or15_high,
        "opening_range_15m_low": or15_low,
        "entry_distance_from_or5_high_pct": _pct_diff(entry_price, or5_high),
        "entry_distance_from_or5_low_pct": _pct_diff(entry_price, or5_low),
        "entry_distance_from_or15_high_pct": _pct_diff(entry_price, or15_high),
        "entry_distance_from_or15_low_pct": _pct_diff(entry_price, or15_low),
    }


# ---------------------------------------------------------------------------
# Helpers for daily bar lookups
# ---------------------------------------------------------------------------

def get_previous_day_data(bars: list[dict], fill_date: date) -> dict:
    """Return the last daily bar strictly before fill_date."""
    prev = [b for b in bars if _bar_date(b) < fill_date]
    if not prev:
        return {}
    b = prev[-1]
    return {"high": b.get("h"), "low": b.get("l"), "close": b.get("c")}


def compute_avg_daily_volume(bars: list[dict], fill_date: date, window: int = 20) -> Optional[float]:
    """Rolling 20-day average volume from daily bars before fill_date."""
    prev = [b for b in bars if _bar_date(b) < fill_date]
    if len(prev) < 3:
        return None
    recent = prev[-window:]
    vols = [float(b["v"]) for b in recent if b.get("v") is not None]
    return round(sum(vols) / len(vols), 0) if vols else None


def compute_rvol(
    intraday: dict, adv: Optional[float], executed_at: datetime
) -> Optional[float]:
    """Approximate relative volume at fill time vs expected fraction of ADV."""
    cum_vol = intraday.get("cumulative_volume_at_entry")
    if cum_vol is None or adv is None or adv == 0:
        return None
    fill_mins = executed_at.hour * 60 + executed_at.minute
    market_open_mins = 9 * 60 + 30
    market_close_mins = 16 * 60
    if fill_mins <= market_open_mins:
        return None
    elapsed = min(fill_mins - market_open_mins, market_close_mins - market_open_mins)
    fraction = elapsed / (market_close_mins - market_open_mins)
    expected = adv * fraction
    return round(cum_vol / expected, 4) if expected > 0 else None


# ---------------------------------------------------------------------------
# Derived flags
# ---------------------------------------------------------------------------

def compute_flags(fill, intraday: dict, daily_indic: dict) -> dict:
    """
    Compute deterministic behavioral flags from fill metadata + context.
    fill: a Fill model instance.
    Returns a dict of flag fields (int 0/1 or None, plus string bucket fields).
    """
    entry_price = intraday.get("entry_underlying_price")
    vwap = intraday.get("entry_vwap")
    rsi = daily_indic.get("rsi_14")
    ema9 = daily_indic.get("ema_9")
    ema20 = daily_indic.get("ema_20")
    macd_hist = daily_indic.get("macd_histogram")
    vs_vwap = intraday.get("entry_vs_vwap_pct")
    day_range_used = intraday.get("entry_day_range_used_pct")
    dist_day_high = intraday.get("entry_distance_from_day_high_pct")
    dist_day_low = intraday.get("entry_distance_from_day_low_pct")
    dist_prev_high = intraday.get("entry_distance_from_prev_high_pct")
    dist_prev_low = intraday.get("entry_distance_from_prev_low_pct")
    or5_high = intraday.get("opening_range_5m_high")
    or5_low = intraday.get("opening_range_5m_low")
    pm_high = intraday.get("premarket_high")
    pm_low = intraday.get("premarket_low")

    is_long = fill.side in ("buy_to_open", "buy")
    is_short = fill.side in ("sell_to_open", "sell")

    # Chase entry: RSI extended, price far above VWAP, or day range nearly exhausted
    is_chase = 0
    if rsi is not None and rsi > 70:
        is_chase = 1
    if vs_vwap is not None and vs_vwap > 2.0:
        is_chase = 1
    if day_range_used is not None and day_range_used > 80:
        is_chase = 1

    # Trend aligned: price vs EMA stack + MACD histogram direction
    is_trend: Optional[int] = None
    if entry_price and ema9 and ema20 and macd_hist is not None:
        if is_long:
            is_trend = 1 if (entry_price > ema9 and ema9 > ema20 and macd_hist > 0) else 0
        elif is_short:
            is_trend = 1 if (entry_price < ema9 and ema9 < ema20 and macd_hist < 0) else 0

    # Late move: entering near day high on long, near day low on short
    is_late = 0
    if is_long and dist_day_high is not None and dist_day_high > -0.5:
        is_late = 1
    if is_short and dist_day_low is not None and dist_day_low < 0.5:
        is_late = 1

    # VWAP reclaim (simplified): price is above VWAP on a long entry
    is_vwap_reclaim = 0
    if vwap and entry_price:
        if is_long and entry_price > vwap:
            is_vwap_reclaim = 1
        elif is_short and entry_price < vwap:
            is_vwap_reclaim = 1

    # Opening range breakout
    is_or_break = 0
    if or5_high and or5_low and entry_price:
        if is_long and entry_price > or5_high:
            is_or_break = 1
        elif is_short and entry_price < or5_low:
            is_or_break = 1

    # Premarket breakout
    is_pm_break = 0
    if pm_high and pm_low and entry_price:
        if is_long and entry_price > pm_high:
            is_pm_break = 1
        elif is_short and entry_price < pm_low:
            is_pm_break = 1

    # Near resistance (call entry near HOD or prev-day high)
    is_near_res = 0
    if is_long:
        if dist_day_high is not None and dist_day_high > -0.5:
            is_near_res = 1
        elif dist_prev_high is not None and dist_prev_high > -0.5:
            is_near_res = 1

    # Near support (put entry near LOD or prev-day low)
    is_near_sup = 0
    if is_short:
        if dist_day_low is not None and dist_day_low < 0.5:
            is_near_sup = 1
        elif dist_prev_low is not None and dist_prev_low < 0.5:
            is_near_sup = 1

    # Overnight: fill outside RTH 09:30–16:00 ET
    fill_mins = fill.executed_at.hour * 60 + fill.executed_at.minute
    is_overnight = 1 if fill_mins < 9 * 60 + 30 or fill_mins >= 16 * 60 else 0

    # Entry time bucket
    if fill_mins < 9 * 60 + 30:
        entry_time_bucket = "premarket"
    elif fill_mins < 10 * 60:
        entry_time_bucket = "open"
    elif fill_mins < 14 * 60:
        entry_time_bucket = "mid"
    elif fill_mins < 16 * 60:
        entry_time_bucket = "close"
    else:
        entry_time_bucket = "afterhours"

    # DTE bucket (options only)
    dte_bucket: Optional[str] = None
    if fill.expiration and fill.executed_at:
        dte = (fill.expiration - fill.executed_at.date()).days
        if dte <= 0:
            dte_bucket = "0dte"
        elif dte <= 3:
            dte_bucket = "1-3dte"
        elif dte <= 7:
            dte_bucket = "4-7dte"
        elif dte <= 21:
            dte_bucket = "8-21dte"
        else:
            dte_bucket = "22+dte"

    return {
        "is_chase_entry": is_chase,
        "is_trend_aligned": is_trend,
        "is_late_move": is_late,
        "is_vwap_reclaim": is_vwap_reclaim,
        "is_opening_range_breakout": is_or_break,
        "is_premarket_breakout": is_pm_break,
        "is_near_resistance_on_call_entry": is_near_res,
        "is_near_support_on_put_entry": is_near_sup,
        "is_overnight": is_overnight,
        "entry_time_bucket": entry_time_bucket,
        "dte_bucket": dte_bucket,
    }


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _f(val) -> Optional[float]:
    """Return None for NaN/None, else float."""
    if val is None:
        return None
    try:
        f = float(val)
        return None if math.isnan(f) or math.isinf(f) else round(f, 6)
    except (TypeError, ValueError):
        return None


def _nan(val) -> bool:
    try:
        return math.isnan(float(val))
    except (TypeError, ValueError):
        return True


def _pct_diff(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b is None or b == 0:
        return None
    return round((a - b) / b * 100, 4)


def _series_max(df: pd.DataFrame, col: str) -> Optional[float]:
    if df.empty or col not in df.columns:
        return None
    val = df[col].max()
    return _f(val)


def _series_min(df: pd.DataFrame, col: str) -> Optional[float]:
    if df.empty or col not in df.columns:
        return None
    val = df[col].min()
    return _f(val)


def _bar_date(bar: dict) -> date:
    return pd.to_datetime(bar["t"], utc=True).astimezone(ET).date()
