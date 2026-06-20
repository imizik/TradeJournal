"""
On-demand single-ticker analysis for ANY symbol (traded or not), as of the
latest data Alpaca can return.

Pure data + standard indicators. The buy/sell judgment is intentionally left to
the caller (Claude), same as the market report — no verdict logic lives here.

Reuses the existing market-data + indicator plumbing:
  - fetch_daily_bars / compute_daily_indicators  -> long-term (daily) block
  - fetch_snapshots                              -> current price / change
  - fetch_minute_bars_live (or last session)     -> short-term (intraday) block
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

from app.engine.alpaca import (
    ALPACA_DATA_FEED,
    ET,
    _latest_completed_daily_bar_date,
    alpaca_configured,
    fetch_daily_bars,
    fetch_minute_bars_for_date,
    fetch_minute_bars_live,
    fetch_snapshots,
)
from app.engine.indicators import analyze_minute_bars, compute_daily_indicators

log = logging.getLogger(__name__)


def _pct(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b is None or b == 0:
        return None
    return round((a - b) / b * 100, 2)


def _bar_date_str(bar: dict) -> Optional[str]:
    t = bar.get("t")
    return t[:10] if isinstance(t, str) else None


def build_ticker_analysis(
    symbol: str,
    daily_lookback_days: int = 400,
    daily_tail: int = 30,
    minute_tail: int = 30,
) -> dict:
    """Build a live analysis packet (short-term + long-term) for one ticker."""
    if not alpaca_configured():
        raise RuntimeError(
            "Alpaca keys not configured — set ALPACA_API_KEY / ALPACA_API_SECRET"
        )

    symbol = symbol.strip().upper()
    now_et = datetime.now(ET)
    today = now_et.date()
    latest_completed = _latest_completed_daily_bar_date()

    # ---- Daily / long-term ----
    daily_start = today - timedelta(days=daily_lookback_days)
    daily_bars = fetch_daily_bars([symbol], daily_start, today).get(symbol, [])
    daily_indic_map = compute_daily_indicators(daily_bars)

    # Exclude today's still-forming bar from long-term stats; current price comes
    # from the snapshot instead.
    completed_bars = [
        b for b in daily_bars
        if (_bar_date_str(b) or "") <= latest_completed.isoformat()
    ]
    long_term = _long_term_block(completed_bars, daily_indic_map, latest_completed)
    recent_daily = [
        {"date": _bar_date_str(b), "o": b.get("o"), "h": b.get("h"),
         "l": b.get("l"), "c": b.get("c"), "v": b.get("v")}
        for b in completed_bars[-daily_tail:]
    ]

    # ---- Current snapshot ----
    snap = fetch_snapshots([symbol]).get(symbol, {})
    current = _snapshot_block(snap)

    # ---- Intraday / short-term ----
    live = fetch_minute_bars_live([symbol], today).get(symbol, [])
    as_of_day = today
    if live:
        ref_dt = now_et.replace(tzinfo=None)
    else:
        # No live prints yet (weekend/holiday/premarket) — fall back to the last
        # completed session so the short-term block is still populated.
        as_of_day = latest_completed
        live = fetch_minute_bars_for_date([symbol], as_of_day).get(symbol, [])
        ref_dt = datetime(as_of_day.year, as_of_day.month, as_of_day.day, 16, 0)

    intraday = analyze_minute_bars(live, ref_dt) if live else {}
    recent_minute = [
        {"t": b.get("t"), "o": b.get("o"), "h": b.get("h"), "l": b.get("l"),
         "c": b.get("c"), "v": b.get("v"), "vw": b.get("vw")}
        for b in live[-minute_tail:]
    ]

    return {
        "symbol": symbol,
        "generated_at": now_et.isoformat(),
        "data_source": f"alpaca_{ALPACA_DATA_FEED}",
        "feed_note": (
            "Free Alpaca feed is IEX (thinner than full SIP); treat pre/post-market "
            "and thin names as approximate."
        ),
        "current": current,
        "short_term": {
            "as_of_session": as_of_day.isoformat(),
            "is_live_today": bool(as_of_day == today and intraday),
            **intraday,
        },
        "long_term": long_term,
        "recent_daily_bars": recent_daily,
        "recent_minute_bars": recent_minute,
        "missing": _missing(daily_bars, snap, intraday),
    }


def _long_term_block(bars: list[dict], indic_map: dict, latest_completed) -> dict:
    if not bars:
        return {}
    closes = [b["c"] for b in bars if b.get("c") is not None]
    highs = [b["h"] for b in bars if b.get("h") is not None]
    lows = [b["l"] for b in bars if b.get("l") is not None]
    if not closes:
        return {}

    last_close = closes[-1]
    indic = indic_map.get(latest_completed.isoformat())
    if indic is None and indic_map:
        indic = indic_map[max(indic_map)]
    indic = indic or {}

    sma_200 = round(sum(closes[-200:]) / len(closes[-200:]), 4) if len(closes) >= 200 else None
    win = 252
    high_52w = max(highs[-win:]) if highs else None
    low_52w = min(lows[-win:]) if lows else None

    def ret(n: int) -> Optional[float]:
        if len(closes) > n and closes[-n - 1]:
            return round((closes[-1] - closes[-n - 1]) / closes[-n - 1] * 100, 2)
        return None

    return {
        "as_of_date": latest_completed.isoformat(),
        "last_close": last_close,
        "sma_20": indic.get("sma_20"),
        "sma_50": indic.get("sma_50"),
        "sma_200": sma_200,
        "ema_9": indic.get("ema_9"),
        "ema_20": indic.get("ema_20"),
        "rsi_14": indic.get("rsi_14"),
        "atr_14": indic.get("atr_14"),
        "macd": indic.get("macd"),
        "macd_signal": indic.get("macd_signal"),
        "macd_histogram": indic.get("macd_histogram"),
        "pct_vs_sma_20": _pct(last_close, indic.get("sma_20")),
        "pct_vs_sma_50": _pct(last_close, indic.get("sma_50")),
        "pct_vs_sma_200": _pct(last_close, sma_200),
        "high_52w": high_52w,
        "low_52w": low_52w,
        "pct_off_52w_high": _pct(last_close, high_52w),
        "pct_above_52w_low": _pct(last_close, low_52w),
        "return_1m_pct": ret(21),
        "return_3m_pct": ret(63),
        "return_6m_pct": ret(126),
        "trading_days_available": len(closes),
    }


def _snapshot_block(snap: dict) -> dict:
    if not snap:
        return {}
    lt = snap.get("latestTrade") or {}
    db = snap.get("dailyBar") or {}
    pdb = snap.get("prevDailyBar") or {}
    price = lt.get("p")
    prev_close = pdb.get("c")
    return {
        "price": price,
        "last_trade_time": lt.get("t"),
        "today_open": db.get("o"),
        "today_high": db.get("h"),
        "today_low": db.get("l"),
        "today_volume": db.get("v"),
        "prev_close": prev_close,
        "change_pct_from_prev_close": _pct(price, prev_close),
    }


def _missing(daily_bars: list[dict], snap: dict, intraday: dict) -> list[str]:
    missing = []
    if not daily_bars:
        missing.append("daily_bars")
    if not snap:
        missing.append("snapshot")
    if not intraday:
        missing.append("intraday")
    return missing
