"""
Local indicator computation from raw bar data using pandas.
No external indicator library required — all formulas are implemented directly.

All public functions accept Alpaca bar dicts (keys: t, o, h, l, c, v, vw)
and return results keyed by date string "YYYY-MM-DD" or hour string "YYYY-MM-DD HH".
"""

import math
import logging
from datetime import date, datetime
from typing import Callable, Optional
from zoneinfo import ZoneInfo

import pandas as pd

log = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")

# Minute bars for one ticker on one day, as Alpaca bar dicts. Injected rather
# than fetched here: this module computes, it does not decide where bars come
# from or pay for them. An empty list means "no bars for that day".
MinuteBarLoader = Callable[[str, date], list[dict]]


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

    # Previous bar close (needed for true VWAP reclaim check)
    prev_bar_close: Optional[float] = None
    if len(bars_to_fill) >= 2:
        prev_bar_close = _f(float(bars_to_fill.iloc[-2]["close"]))

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
        "prev_bar_close": prev_bar_close,
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
    """Simple RVOL: cumulative vol / (ADV × fraction of day elapsed). Linear — use as fallback only."""
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


def compute_rvol_time_adjusted(
    ticker: str,
    fill_date: date,
    fill_dt: datetime,
    daily_bars: list[dict],
    load_minute_bars: MinuteBarLoader,
) -> Optional[float]:
    """
    Time-adjusted RVOL: compare today's cumulative RTH volume at fill time
    against the historical average cumulative volume at the same minute of day
    over the past 20 trading days.

    ``load_minute_bars(ticker, day)`` supplies the bars for one day and returns
    an empty list when that day is not available. The caller decides where they
    come from, and owns the "no extra API calls" part: this function asks for up
    to 21 days and treats every miss as a day without data, so a loader that
    only reads a cache keeps the cost at zero. A day this function cannot get
    bars for does not count toward the history.

    Returns None if fewer than 5 historical days are available.
    """
    fill_dt_et = fill_dt.replace(tzinfo=ET)
    fill_mins = fill_dt_et.hour * 60 + fill_dt_et.minute
    market_open_mins = 9 * 60 + 30
    if fill_mins < market_open_mins:
        return None
    mins_since_open = fill_mins - market_open_mins

    def _cum_vol(d: date) -> Optional[float]:
        bars = load_minute_bars(ticker, d)
        if not bars:
            return None
        df = bars_to_df(bars)
        if df.empty:
            return None
        rth_open = pd.Timestamp(
            datetime(d.year, d.month, d.day, 9, 30, tzinfo=ET)
        ).tz_convert("UTC")
        target = rth_open + pd.Timedelta(minutes=mins_since_open)
        seg = df[(df.index >= rth_open) & (df.index <= target)]
        return float(seg["volume"].sum()) if not seg.empty else None

    today_cum = _cum_vol(fill_date)
    if today_cum is None:
        return None

    prev_dates = sorted(
        [_bar_date(b) for b in daily_bars if _bar_date(b) < fill_date],
        reverse=True,
    )[:20]

    hist = [v for d in prev_dates if (v := _cum_vol(d)) is not None]
    if len(hist) < 5:
        return None

    avg = sum(hist) / len(hist)
    return round(today_cum / avg, 4) if avg > 0 else None


# ---------------------------------------------------------------------------
# Derived flags
# ---------------------------------------------------------------------------

def compute_flags(fill, intraday: dict, daily_indic: dict) -> dict:
    """
    Compute deterministic behavioral flags from fill metadata + context.
    fill: a Fill model instance.
    Returns a dict of flag fields (int 0/1 or None, plus score and bucket fields).
    """
    entry_price = intraday.get("entry_underlying_price")
    vwap = intraday.get("entry_vwap")
    prev_bar_close = intraday.get("prev_bar_close")
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

    # ---- is_above_vwap: price on the correct side of VWAP at entry ----
    # (replaces the old mislabeled is_vwap_reclaim logic)
    is_above_vwap: Optional[int] = None
    if vwap and entry_price:
        if is_long:
            is_above_vwap = 1 if entry_price > vwap else 0
        elif is_short:
            is_above_vwap = 1 if entry_price < vwap else 0

    # ---- is_vwap_reclaim: true reclaim — prev bar on wrong side, entry bar on right side ----
    is_vwap_reclaim: Optional[int] = None
    if vwap is not None and entry_price is not None and prev_bar_close is not None:
        is_vwap_reclaim = 0
        if is_long and prev_bar_close < vwap and entry_price > vwap:
            is_vwap_reclaim = 1
        elif is_short and prev_bar_close > vwap and entry_price < vwap:
            is_vwap_reclaim = 1

    # ---- chase_score 0-100: continuous score replacing binary is_chase ----
    # Components: RSI stretch, VWAP extension, day range exhaustion
    chase_score = 0
    chase_parts = 0

    if rsi is not None:
        # RSI: 0 pts at 50, 25 pts at 70, 40 pts at 80+
        if is_long:
            rsi_pts = max(0.0, min(40.0, (rsi - 50) * 2.0)) if rsi > 50 else 0.0
        else:
            rsi_pts = max(0.0, min(40.0, (50 - rsi) * 2.0)) if rsi < 50 else 0.0
        chase_score += rsi_pts
        chase_parts += 1

    if vs_vwap is not None:
        # VWAP extension: 0 pts at 0%, 30 pts at 3%+
        if is_long:
            vwap_pts = max(0.0, min(30.0, vs_vwap * 10.0)) if vs_vwap > 0 else 0.0
        else:
            vwap_pts = max(0.0, min(30.0, -vs_vwap * 10.0)) if vs_vwap < 0 else 0.0
        chase_score += vwap_pts
        chase_parts += 1

    if day_range_used is not None:
        # Day range: 0 pts below 60%, 30 pts at 95%+
        if is_long:
            range_pts = max(0.0, min(30.0, (day_range_used - 60.0) * (30.0 / 35.0))) if day_range_used > 60 else 0.0
        else:
            # For shorts, low day_range_used (near LOD) is the chase
            range_pts = max(0.0, min(30.0, (40.0 - day_range_used) * (30.0 / 35.0))) if day_range_used < 40 else 0.0
        chase_score += range_pts
        chase_parts += 1

    chase_score = round(min(100.0, chase_score), 1) if chase_parts > 0 else None
    # Derive binary flag from score
    is_chase = (1 if chase_score >= 40 else 0) if chase_score is not None else None

    # ---- Trend aligned: price vs EMA stack + MACD histogram direction ----
    is_trend: Optional[int] = None
    if entry_price and ema9 and ema20 and macd_hist is not None:
        if is_long:
            is_trend = 1 if (entry_price > ema9 and ema9 > ema20 and macd_hist > 0) else 0
        elif is_short:
            is_trend = 1 if (entry_price < ema9 and ema9 < ema20 and macd_hist < 0) else 0

    # ---- Late move: entering near day high on long, near day low on short ----
    is_late: Optional[int] = None
    if is_long and dist_day_high is not None:
        is_late = 1 if dist_day_high > -0.5 else 0
    if is_short and dist_day_low is not None:
        is_late = 1 if dist_day_low < 0.5 else 0

    # ---- Opening range breakout ----
    is_or_break: Optional[int] = None
    if is_long and or5_high is not None and entry_price is not None:
        is_or_break = 1 if entry_price > or5_high else 0
    elif is_short and or5_low is not None and entry_price is not None:
        is_or_break = 1 if entry_price < or5_low else 0

    # ---- Premarket breakout ----
    is_pm_break: Optional[int] = None
    if is_long and pm_high is not None and entry_price is not None:
        is_pm_break = 1 if entry_price > pm_high else 0
    elif is_short and pm_low is not None and entry_price is not None:
        is_pm_break = 1 if entry_price < pm_low else 0

    # ---- Near resistance (call entry near HOD or prev-day high) ----
    is_near_res: Optional[int] = None
    if is_long:
        if dist_day_high is not None or dist_prev_high is not None:
            is_near_res = 1 if (
                (dist_day_high is not None and dist_day_high > -0.5)
                or (dist_prev_high is not None and dist_prev_high > -0.5)
            ) else 0

    # ---- Near support (put entry near LOD or prev-day low) ----
    is_near_sup: Optional[int] = None
    if is_short:
        if dist_day_low is not None or dist_prev_low is not None:
            is_near_sup = 1 if (
                (dist_day_low is not None and dist_day_low < 0.5)
                or (dist_prev_low is not None and dist_prev_low < 0.5)
            ) else 0

    # ---- Overnight: fill outside RTH 09:30–16:00 ET ----
    fill_mins = fill.executed_at.hour * 60 + fill.executed_at.minute
    is_overnight = 1 if fill_mins < 9 * 60 + 30 or fill_mins >= 16 * 60 else 0

    # ---- Entry time bucket ----
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

    # ---- DTE bucket (options only) ----
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

    # ---- Setup quality score 0-100 (positive signals minus negative signals) ----
    setup_quality_score = compute_setup_score(
        is_trend_aligned=is_trend,
        is_above_vwap=is_above_vwap,
        is_vwap_reclaim=is_vwap_reclaim,
        is_or_break=is_or_break,
        is_pm_break=is_pm_break,
        chase_score=chase_score,
        is_late=is_late,
        is_near_res=is_near_res if is_long else None,
        is_near_sup=is_near_sup if is_short else None,
        rsi=rsi,
        macd_hist=macd_hist,
    )

    return {
        "is_chase_entry": is_chase,
        "chase_score": chase_score,
        "is_trend_aligned": is_trend,
        "is_late_move": is_late,
        "is_above_vwap": is_above_vwap,
        "is_vwap_reclaim": is_vwap_reclaim,
        "is_opening_range_breakout": is_or_break,
        "is_premarket_breakout": is_pm_break,
        "is_near_resistance_on_call_entry": is_near_res,
        "is_near_support_on_put_entry": is_near_sup,
        "is_overnight": is_overnight,
        "entry_time_bucket": entry_time_bucket,
        "dte_bucket": dte_bucket,
        "setup_quality_score": setup_quality_score,
    }


def compute_setup_score(
    *,
    is_trend_aligned: Optional[int],
    is_above_vwap: Optional[int],
    is_vwap_reclaim: Optional[int],
    is_or_break: Optional[int],
    is_pm_break: Optional[int],
    chase_score: Optional[float],
    is_late: Optional[int],
    is_near_res: Optional[int],
    is_near_sup: Optional[int],
    rsi: Optional[float],
    macd_hist: Optional[float],
) -> Optional[float]:
    """
    Aggregate setup quality score 0–100.
    Positive signals add points; negative conditions subtract them.
    Returns None when insufficient data to compute a meaningful score.

    Weights:
      +25  trend aligned (EMA stack + MACD)
      +20  VWAP reclaim (true cross)
      +15  above VWAP (weaker — just on right side)
      +15  opening range breakout
      +10  premarket breakout
      +10  MACD histogram positive (long) / negative (short)
      +5   RSI in healthy range (40–65 for longs, 35–60 for shorts)
      -----
       -25  chase_score ≥ 60 (major penalty)
       -15  chase_score 40–59 (moderate penalty)
       -10  late move
       -10  near resistance (for longs) / near support (for shorts)

    Returns None if no positive signal data is available at all.
    """
    score = 50.0  # start at neutral
    data_points = 0

    if is_trend_aligned is not None:
        data_points += 1
        score += 25 if is_trend_aligned else -5

    if is_vwap_reclaim:
        data_points += 1
        score += 20

    if is_above_vwap is not None:
        data_points += 1
        score += 15 if is_above_vwap else -5

    if is_or_break:
        data_points += 1
        score += 15

    if is_pm_break:
        data_points += 1
        score += 10

    if macd_hist is not None:
        data_points += 1
        score += 10 if macd_hist > 0 else -5

    if rsi is not None:
        data_points += 1
        # RSI in healthy range is a mild positive
        healthy = 40 <= rsi <= 65
        score += 5 if healthy else 0

    # Negative conditions
    if chase_score is not None and chase_score >= 60:
        score -= 25
    elif chase_score is not None and chase_score >= 40:
        score -= 15

    if is_late:
        score -= 10

    if is_near_res:
        score -= 10

    if is_near_sup:
        score -= 10

    if data_points == 0:
        return None

    return round(max(0.0, min(100.0, score)), 1)


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


# ---------------------------------------------------------------------------
# Polygon-equivalent indicators from Polygon aggregate bars
# ---------------------------------------------------------------------------
# The Polygon enricher used to fetch each indicator series from Polygon's
# /v1/indicators endpoints (seven calls per ticker). These functions compute
# the same numbers from the aggregates those endpoints are built on, so one
# daily-bars call and one hourly-bars call replace them without changing any
# stored value. Polygon does not document its formulas; every convention below
# was established empirically against cached Polygon output and is pinned by
# tests/test_enricher.py (max difference 0 for EMA/RSI/MACD, ~1e-13 for SMA):
#
#   SMA   mean of the last `window` closes; first value at bar `window`.
#   EMA   alpha = 2/(window+1), seeded with the first close and iterated from
#         bar 1; first *reported* value at bar `window`.
#   RSI   Wilder smoothing (alpha = 1/window) of gains and losses. Seed at bar
#         `window`: the first window-1 changes summed and divided by `window`.
#   MACD  EMA(12) - EMA(26) of the closes, each EMA seeded and iterated as
#         above, reported from bar 26. Signal = EMA(9) of the MACD line
#         iterated from bar 1 (where the line is 0). Histogram = MACD - signal.
#
# Bars before the first reported value are omitted (None), matching the shape
# of Polygon's series, so "last completed bar strictly before the fill"
# lookups behave exactly as they did with the fetched series.
#
# Bars are Polygon aggregate dicts: ms-epoch `t`, plus `c` (close).

def polygon_bar_et_date(bar: dict) -> str:
    """Calendar date in America/New_York of a Polygon bar's timestamp."""
    return datetime.fromtimestamp(bar["t"] / 1000, tz=UTC).astimezone(ET).strftime("%Y-%m-%d")


def polygon_bar_et_hour(bar: dict) -> str:
    """'YYYY-MM-DD HH' in America/New_York of a Polygon bar's timestamp."""
    dt = datetime.fromtimestamp(bar["t"] / 1000, tz=UTC).astimezone(ET)
    return f"{dt.strftime('%Y-%m-%d')} {dt.hour:02d}"


def _polygon_sma(values: list[float], window: int) -> list[Optional[float]]:
    out: list[Optional[float]] = [None] * len(values)
    for i in range(window - 1, len(values)):
        out[i] = sum(values[i - window + 1 : i + 1]) / window
    return out


def _polygon_ema(values: list[float], window: int, report_from: Optional[int] = None) -> list[Optional[float]]:
    """EMA seeded with the first value; reported from index `report_from`
    (default: bar `window`, i.e. index window-1)."""
    alpha = 2.0 / (window + 1)
    first = window - 1 if report_from is None else report_from
    out: list[Optional[float]] = [None] * len(values)
    ema: Optional[float] = None
    for i, value in enumerate(values):
        ema = value if ema is None else alpha * value + (1 - alpha) * ema
        if i >= first:
            out[i] = ema
    return out


def _polygon_rsi(values: list[float], window: int) -> list[Optional[float]]:
    out: list[Optional[float]] = [None] * len(values)
    if len(values) < window:
        return out
    gains = [max(values[i] - values[i - 1], 0.0) for i in range(1, len(values))]
    losses = [max(values[i - 1] - values[i], 0.0) for i in range(1, len(values))]

    def _rsi(avg_gain: float, avg_loss: float) -> float:
        return 100.0 if avg_loss == 0 else 100 - 100 / (1 + avg_gain / avg_loss)

    avg_gain = sum(gains[: window - 1]) / window
    avg_loss = sum(losses[: window - 1]) / window
    out[window - 1] = _rsi(avg_gain, avg_loss)
    for i in range(window - 1, len(gains)):
        avg_gain = (avg_gain * (window - 1) + gains[i]) / window
        avg_loss = (avg_loss * (window - 1) + losses[i]) / window
        out[i + 1] = _rsi(avg_gain, avg_loss)
    return out


def _polygon_macd(
    values: list[float], fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[list[Optional[float]], list[Optional[float]], list[Optional[float]]]:
    ema_fast = _polygon_ema(values, fast, report_from=0)
    ema_slow = _polygon_ema(values, slow, report_from=0)
    line_full = [f - s for f, s in zip(ema_fast, ema_slow)]  # type: ignore[operator]
    signal_full = _polygon_ema(line_full, signal, report_from=0)
    n = len(values)
    line: list[Optional[float]] = [None] * n
    sig: list[Optional[float]] = [None] * n
    hist: list[Optional[float]] = [None] * n
    for i in range(slow - 1, n):
        line[i] = line_full[i]
        sig[i] = signal_full[i]
        hist[i] = line_full[i] - signal_full[i]  # type: ignore[operator]
    return line, sig, hist


POLYGON_DAILY_INDICATORS = ("sma_20", "sma_50", "ema_9", "ema_20", "rsi_14", "macd", "macd_signal", "macd_histogram")


def polygon_daily_indicators(bars: list[dict]) -> dict[str, dict[str, Optional[float]]]:
    """
    {date_str: {sma_20, sma_50, ema_9, ema_20, rsi_14, macd, macd_signal,
    macd_histogram}} from Polygon daily bars, reproducing Polygon's own
    indicator endpoints for the same bars. Warmup entries are None.
    """
    ordered = sorted(bars, key=lambda b: b["t"])
    closes = [float(b["c"]) for b in ordered]
    dates = [polygon_bar_et_date(b) for b in ordered]
    sma_20 = _polygon_sma(closes, 20)
    sma_50 = _polygon_sma(closes, 50)
    ema_9 = _polygon_ema(closes, 9)
    ema_20 = _polygon_ema(closes, 20)
    rsi_14 = _polygon_rsi(closes, 14)
    macd, macd_signal, macd_histogram = _polygon_macd(closes)
    return {
        day: {
            "sma_20": sma_20[i],
            "sma_50": sma_50[i],
            "ema_9": ema_9[i],
            "ema_20": ema_20[i],
            "rsi_14": rsi_14[i],
            "macd": macd[i],
            "macd_signal": macd_signal[i],
            "macd_histogram": macd_histogram[i],
        }
        for i, day in enumerate(dates)
    }


def polygon_hourly_ema(bars: list[dict], window: int = 9) -> dict[str, float]:
    """{'YYYY-MM-DD HH' (ET) -> EMA} from Polygon hourly bars, same convention
    as Polygon's hourly EMA endpoint. Warmup bars are omitted."""
    ordered = sorted(bars, key=lambda b: b["t"])
    closes = [float(b["c"]) for b in ordered]
    keys = [polygon_bar_et_hour(b) for b in ordered]
    return {key: value for key, value in zip(keys, _polygon_ema(closes, window)) if value is not None}
