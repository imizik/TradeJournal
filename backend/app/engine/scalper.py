"""
Scalper Analyzer — read-only, deterministic intraday setup-quality assessment.

Answers "should I scalp X right now / buy intraday calls at the open / is this
VWAP reclaim real?" with structured data plus deterministic scoring. It never
places trades and never gives blind buy/sell advice — the verdict is a setup
classification with trigger, invalidation, targets, and missing-data caveats.
Claude writes the narrative on top of this packet; news content judgment stays
with Claude (headlines are passed through raw, only counted for event risk).

Two layers, kept separate so scoring is unit-testable without network:

  build_scalp_analysis()  gathers live data (Alpaca snapshots, live minute
                          bars, daily bars, Benzinga news, option snapshots).
                          Live minute bars use fetch_minute_bars_live and are
                          NEVER written to the persistent enrichment cache.
  score_scalp()           pure function over the gathered packet — verdict,
                          scores, plan, reasons, caveats.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta
from typing import Optional

import pandas as pd

from app.engine.alpaca import (
    ALPACA_DATA_FEED,
    ALPACA_OPTIONS_FEED,
    ET,
    _latest_completed_daily_bar_date,
    alpaca_configured,
    fetch_daily_bars,
    fetch_minute_bars_for_date,
    fetch_minute_bars_live,
    fetch_option_chain_snapshots,
    fetch_option_snapshots,
    fetch_snapshots,
)
from app.engine.indicators import (
    analyze_minute_bars,
    bars_to_df,
    compute_avg_daily_volume,
    compute_daily_indicators,
    compute_rvol,
)
from app.engine.news import fetch_news
from app.engine.packets import _market_state, _symbol_metrics

log = logging.getLogger(__name__)

MARKET_TICKERS = ["SPY", "QQQ"]

MAX_OPTION_SPREAD_PCT = 10.0   # reject option scalps beyond this % of mid
WIDE_OPTION_SPREAD_PCT = 5.0   # warn (and add risk) beyond this
STALE_TRADE_SECONDS = 600      # no print for 10 min during RTH = stale
STALE_BAR_SECONDS = 420        # no minute bar for 7 min during RTH = stale
CHOP_RVOL_MAX = 1.0            # inside the VWAP/OR band below this RVOL = chop
VWAP_CHOP_CROSSES = 4          # VWAP crosses in 30 min that mark a fakeout-prone tape

DISCLAIMER = (
    "Decision support only — deterministic setup classification, not trade "
    "execution or financial advice. Verify levels, spreads, and news before acting."
)

_DIRECTION_ALIASES = {"long": "long", "up": "long", "short": "short", "down": "short"}

# Levels considered when picking triggers/invalidations/targets, by side.
_PLAN_LEVELS_UP = ("vwap", "or5_high", "or15_high", "premarket_high", "day_high", "prev_close", "today_open")
_PLAN_LEVELS_DOWN = ("vwap", "or5_low", "or15_low", "premarket_low", "day_low", "prev_close", "today_open")


# ---------------------------------------------------------------------------
# input normalization
# ---------------------------------------------------------------------------

def _norm_direction(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    normalized = _DIRECTION_ALIASES.get(value.strip().lower())
    if normalized is None:
        raise ValueError(f"direction must be one of long/short/up/down, got {value!r}")
    return normalized


def _norm_choice(field: str, value: Optional[str], allowed: set[str]) -> Optional[str]:
    if not value:
        return None
    v = value.strip().lower()
    if v not in allowed:
        raise ValueError(f"{field} must be one of {sorted(allowed)}, got {value!r}")
    return v


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------

def build_scalp_analysis(
    symbol: str,
    direction: Optional[str] = None,
    instrument: Optional[str] = None,
    option_type: Optional[str] = None,
    expiration: Optional[str] = None,
    strike: Optional[float] = None,
    style: Optional[str] = None,
) -> dict:
    """Gather live data and score a potential scalp. Read-only; never trades."""
    if not alpaca_configured():
        raise RuntimeError("Alpaca keys not configured — set ALPACA_API_KEY / ALPACA_API_SECRET")

    symbol = symbol.strip().upper()
    direction = _norm_direction(direction)
    instrument = _norm_choice("instrument", instrument, {"stock", "option"})
    option_type = _norm_choice("option_type", option_type, {"call", "put"})
    style = _norm_choice("style", style, {"open", "midday", "power_hour"})
    exp_date = date.fromisoformat(expiration) if expiration else None
    if strike is not None and strike <= 0:
        raise ValueError("strike must be positive")

    wants_option = instrument == "option" or any(
        v is not None for v in (option_type, exp_date, strike)
    )
    if wants_option:
        instrument = "option"
        if option_type is None and direction is not None:
            option_type = "call" if direction == "long" else "put"
    else:
        instrument = "stock"

    packet = _gather_packet(symbol, wants_option, option_type, exp_date, strike)
    assessment = score_scalp(packet, direction=direction, instrument=instrument, style=style)
    return {
        "request": {
            "symbol": symbol,
            "direction": direction,
            "instrument": instrument,
            "option_type": option_type,
            "expiration": exp_date.isoformat() if exp_date else None,
            "strike": strike,
            "style": style,
        },
        "assessment": assessment,
        "data": packet,
    }


# ---------------------------------------------------------------------------
# data gathering (network) — everything below feeds the pure scoring layer
# ---------------------------------------------------------------------------

def _gather_packet(
    symbol: str,
    wants_option: bool,
    option_type: Optional[str],
    expiration: Optional[date],
    strike: Optional[float],
) -> dict:
    now_et = datetime.now(ET)
    session_date = now_et.date()
    while session_date.weekday() >= 5:
        session_date -= timedelta(days=1)
    market_state = _market_state(now_et)
    latest_completed = _latest_completed_daily_bar_date(now_et)

    missing: list[str] = []
    notes = [
        f"stocks: alpaca {ALPACA_DATA_FEED} feed (IEX is thinner than SIP — pre/post-market volume understated)",
        "live minute bars fetched fresh; never written to the persistent enrichment cache",
    ]

    tickers = [symbol] + [t for t in MARKET_TICKERS if t != symbol]
    snapshots = fetch_snapshots(tickers)
    daily = fetch_daily_bars(tickers, session_date - timedelta(days=400), session_date)
    minute = fetch_minute_bars_live(tickers, session_date)

    snap = snapshots.get(symbol)
    sym_daily = daily.get(symbol, [])
    sym_minute = minute.get(symbol, [])
    if not snap:
        missing.append(f"{symbol}: no Alpaca snapshot (bad/unsupported symbol?)")
    if not sym_daily:
        missing.append(f"{symbol}: no daily bars — daily trend/RSI/ATR unavailable")
    if not sym_minute:
        missing.append(f"{symbol}: no minute bars for {session_date.isoformat()} — intraday read unavailable")

    metrics = _symbol_metrics(symbol, snap, sym_daily, session_date)
    snapshot_block = _snapshot_block(metrics, snap, session_date)
    intraday_block = _intraday_block(symbol, sym_minute, sym_daily, now_et, session_date, missing, notes)
    daily_block = _daily_block(sym_daily, latest_completed)
    if sym_daily and not daily_block:
        missing.append(f"{symbol}: not enough daily history to compute indicators")

    market_block: dict[str, dict] = {}
    for t in MARKET_TICKERS:
        market_block[t] = _index_block(
            t, snapshots.get(t), daily.get(t, []), minute.get(t, []), now_et, session_date
        )
        if market_block[t].get("pct_change") is None:
            missing.append(f"{t}: no market-context data")

    try:
        articles = fetch_news(symbols=[symbol], start=now_et - timedelta(hours=24), limit=10)
        news_block = [
            {
                "headline": a.get("headline"),
                "source": a.get("source"),
                "created_at": a.get("created_at"),
                "url": a.get("url"),
            }
            for a in articles
        ]
    except Exception as exc:
        news_block = []
        missing.append(f"news: fetch failed ({exc})")

    option_block = None
    if wants_option:
        option_block = _gather_option(
            symbol,
            option_type,
            expiration,
            strike,
            intraday_block.get("price") if intraday_block.get("price") is not None else snapshot_block.get("price"),
            session_date,
            missing,
            notes,
        )

    staleness = _staleness_block(market_state, snapshot_block, sym_minute, now_et)
    if staleness.get("is_stale"):
        missing.append("live data stale during market hours — last trade/bar too old to act on")

    return {
        "symbol": symbol,
        "generated_at": now_et.isoformat(),
        "session_date": session_date.isoformat(),
        "market_state": market_state,
        "snapshot": snapshot_block,
        "intraday": intraday_block,
        "daily": daily_block,
        "market": market_block,
        "news": news_block,
        "option": option_block,
        "staleness": staleness,
        "missing": missing,
        "data_source_notes": notes,
    }


def _snapshot_block(metrics: dict, snap: Optional[dict], session_date: date) -> dict:
    if not snap:
        return {}
    daily_bar = snap.get("dailyBar") or {}
    bar_dt = _parse_iso(daily_bar.get("t"))
    is_session_bar = bar_dt is not None and bar_dt.astimezone(ET).date() == session_date
    return {
        "price": metrics.get("last_price"),
        "last_trade_time": metrics.get("last_trade_at"),
        "prev_close": metrics.get("prev_close"),
        "change_pct": metrics.get("pct_change"),
        "gap_pct": metrics.get("gap_pct"),
        "today_open": daily_bar.get("o") if is_session_bar else None,
        "today_high": metrics.get("session_high"),
        "today_low": metrics.get("session_low"),
        "today_volume": metrics.get("day_volume"),
        "avg_volume_20": metrics.get("avg_volume_20"),
        "day_rvol": metrics.get("rvol"),
    }


def _intraday_block(
    symbol: str,
    bars: list[dict],
    daily_bars: list[dict],
    now_et: datetime,
    session_date: date,
    missing: list[str],
    notes: list[str],
) -> dict:
    if not bars:
        return {}
    live_session = session_date == now_et.date()
    if live_session:
        ref_dt = now_et.replace(tzinfo=None)
    else:
        ref_dt = datetime(session_date.year, session_date.month, session_date.day, 16, 0)

    raw = analyze_minute_bars(bars, ref_dt)
    if not raw:
        return {}

    minutes_since_open: Optional[int] = None
    if live_session:
        minutes_since_open = (now_et.hour * 60 + now_et.minute) - (9 * 60 + 30)

    df = bars_to_df(bars)
    rth_start = pd.Timestamp(
        datetime(session_date.year, session_date.month, session_date.day, 9, 30, tzinfo=ET)
    ).tz_convert("UTC")
    ref_utc = pd.Timestamp(ref_dt.replace(tzinfo=ET)).tz_convert("UTC")
    pre = df[df.index < rth_start]
    rth = df[(df.index >= rth_start) & (df.index <= ref_utc)]

    ema9 = ema20 = None
    if len(rth) >= 9:
        ema9 = round(float(rth["close"].ewm(span=9, adjust=False).mean().iloc[-1]), 4)
    if len(rth) >= 20:
        ema20 = round(float(rth["close"].ewm(span=20, adjust=False).mean().iloc[-1]), 4)
    elif len(rth) > 0:
        notes.append("intraday EMAs limited — fewer than 20 RTH minute bars so far")

    rvol, rvol_method = _live_rvol(symbol, raw, daily_bars, session_date, ref_dt)
    if rvol is None:
        missing.append(f"{symbol}: RVOL unavailable (no cached minute history and no ADV baseline)")

    or5_complete = (minutes_since_open is not None and minutes_since_open >= 5) or (
        not live_session and raw.get("opening_range_5m_high") is not None
    )
    or15_complete = (minutes_since_open is not None and minutes_since_open >= 15) or (
        not live_session and raw.get("opening_range_15m_high") is not None
    )

    return {
        "session_date": session_date.isoformat(),
        "is_live_today": live_session,
        "price": raw.get("entry_underlying_price"),
        "vwap": raw.get("entry_vwap"),
        "price_vs_vwap_pct": raw.get("entry_vs_vwap_pct"),
        "prev_bar_close": raw.get("prev_bar_close"),
        "day_high": raw.get("entry_day_high_so_far"),
        "day_low": raw.get("entry_day_low_so_far"),
        "day_range_used_pct": raw.get("entry_day_range_used_pct"),
        "dist_from_day_high_pct": raw.get("entry_distance_from_day_high_pct"),
        "dist_from_day_low_pct": raw.get("entry_distance_from_day_low_pct"),
        "premarket_high": raw.get("premarket_high"),
        "premarket_low": raw.get("premarket_low"),
        "premarket_volume": int(pre["volume"].sum()) if not pre.empty else None,
        "or5_high": raw.get("opening_range_5m_high"),
        "or5_low": raw.get("opening_range_5m_low"),
        "or15_high": raw.get("opening_range_15m_high"),
        "or15_low": raw.get("opening_range_15m_low"),
        "or5_complete": or5_complete,
        "or15_complete": or15_complete,
        "ema9_intraday": ema9,
        "ema20_intraday": ema20,
        "intraday_bar_count": int(len(rth)),
        "vwap_cross_count_30m": _vwap_cross_count(rth),
        "cumulative_rth_volume": raw.get("cumulative_volume_at_entry"),
        "rvol": rvol,
        "rvol_method": rvol_method,
        "minutes_since_open": minutes_since_open,
    }


def _vwap_cross_count(rth: pd.DataFrame, window: int = 30) -> Optional[int]:
    """Count VWAP crosses over the trailing `window` minute bars (fakeout gauge)."""
    if rth.empty or len(rth) < 2:
        return None
    vols = rth["volume"].astype(float)
    cum_vol = vols.cumsum()
    if float(cum_vol.iloc[-1]) <= 0:
        return None
    typical = (rth["high"] + rth["low"] + rth["close"]) / 3
    cum_vwap = (typical * vols).cumsum() / cum_vol.replace(0, float("nan"))
    diff = (rth["close"] - cum_vwap).tail(window).dropna()
    signs = diff.apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
    signs = signs[signs != 0]
    if len(signs) < 2:
        return 0
    return int((signs.diff().fillna(0) != 0).sum())


def _live_rvol(
    symbol: str,
    raw_intraday: dict,
    daily_bars: list[dict],
    session_date: date,
    ref_dt: datetime,
) -> tuple[Optional[float], Optional[str]]:
    """
    Time-adjusted RVOL vs the same minute-of-day over up to 20 cached sessions,
    falling back to linear RVOL vs 20-day ADV. Today's cumulative volume comes
    from the live bars already in hand; historical minute bars are read
    cache-only so this path never triggers backfill fetches.
    """
    today_cum = raw_intraday.get("cumulative_volume_at_entry")
    mins_since_open = ref_dt.hour * 60 + ref_dt.minute - (9 * 60 + 30)
    if today_cum and mins_since_open > 0 and daily_bars:
        prev_dates = sorted(
            {d for b in daily_bars if (d := _daily_bar_date(b)) is not None and d < session_date},
            reverse=True,
        )[:20]
        hist = [v for d in prev_dates if (v := _cached_cum_volume(symbol, d, mins_since_open)) is not None]
        if len(hist) >= 5:
            avg = sum(hist) / len(hist)
            if avg > 0:
                return round(today_cum / avg, 2), "time_adjusted_20d_cache"
    adv = compute_avg_daily_volume(daily_bars, session_date) if daily_bars else None
    linear = compute_rvol(raw_intraday, adv, ref_dt)
    if linear is not None:
        return round(linear, 2), "linear_vs_adv20"
    return None, None


def _cached_cum_volume(symbol: str, day: date, mins_since_open: int) -> Optional[float]:
    bars = fetch_minute_bars_for_date([symbol], day, cache_only=True).get(symbol, [])
    if not bars:
        return None
    df = bars_to_df(bars)
    if df.empty:
        return None
    rth_open = pd.Timestamp(datetime(day.year, day.month, day.day, 9, 30, tzinfo=ET)).tz_convert("UTC")
    target = rth_open + pd.Timedelta(minutes=mins_since_open)
    seg = df[(df.index >= rth_open) & (df.index <= target)]
    return float(seg["volume"].sum()) if not seg.empty else None


def _daily_block(bars: list[dict], latest_completed: date) -> dict:
    if not bars:
        return {}
    indic_map = compute_daily_indicators(bars)
    if not indic_map:
        return {}
    cutoff = latest_completed.isoformat()
    completed = [b for b in bars if str(b.get("t") or "")[:10] <= cutoff]
    closes = [b["c"] for b in completed if b.get("c") is not None]
    if not closes:
        return {}
    keys = [k for k in indic_map if k <= cutoff]
    as_of = max(keys) if keys else max(indic_map)
    indic = indic_map[as_of]
    last_close = closes[-1]
    sma_200 = round(sum(closes[-200:]) / 200, 4) if len(closes) >= 200 else None
    return {
        "as_of_date": as_of,
        "last_close": last_close,
        "ema_9": indic.get("ema_9"),
        "ema_20": indic.get("ema_20"),
        "sma_20": indic.get("sma_20"),
        "sma_50": indic.get("sma_50"),
        "sma_200": sma_200,
        "rsi_14": indic.get("rsi_14"),
        "atr_14": indic.get("atr_14"),
        "macd": indic.get("macd"),
        "macd_signal": indic.get("macd_signal"),
        "macd_histogram": indic.get("macd_histogram"),
        "pct_vs_sma_20": _pct(last_close, indic.get("sma_20")),
        "pct_vs_sma_50": _pct(last_close, indic.get("sma_50")),
        "pct_vs_sma_200": _pct(last_close, sma_200),
    }


def _index_block(
    ticker: str,
    snap: Optional[dict],
    daily_bars: list[dict],
    minute_bars: list[dict],
    now_et: datetime,
    session_date: date,
) -> dict:
    m = _symbol_metrics(ticker, snap, daily_bars, session_date)
    if session_date == now_et.date():
        ref_dt = now_et.replace(tzinfo=None)
    else:
        ref_dt = datetime(session_date.year, session_date.month, session_date.day, 16, 0)
    raw = analyze_minute_bars(minute_bars, ref_dt) if minute_bars else {}
    price = raw.get("entry_underlying_price")
    if price is None:
        price = m.get("last_price")
    vwap = raw.get("entry_vwap")
    return {
        "pct_change": m.get("pct_change"),
        "price": price,
        "vwap": vwap,
        "price_vs_vwap_pct": raw.get("entry_vs_vwap_pct"),
        "above_vwap": (price > vwap) if (price is not None and vwap) else None,
    }


def _staleness_block(
    market_state: str,
    snapshot_block: dict,
    minute_bars: list[dict],
    now_et: datetime,
) -> dict:
    last_trade_age = _age_seconds(snapshot_block.get("last_trade_time"), now_et)
    last_bar_age = _age_seconds(minute_bars[-1].get("t"), now_et) if minute_bars else None
    is_stale = False
    if market_state == "rth":
        trade_stale = last_trade_age is None or last_trade_age > STALE_TRADE_SECONDS
        bar_stale = last_bar_age is None or last_bar_age > STALE_BAR_SECONDS
        # Either a fresh print or a fresh bar is enough to call the read live.
        is_stale = trade_stale and bar_stale
    return {
        "last_trade_age_seconds": last_trade_age,
        "last_bar_age_seconds": last_bar_age,
        "is_stale": is_stale,
    }


# ---------------------------------------------------------------------------
# options
# ---------------------------------------------------------------------------

def _gather_option(
    symbol: str,
    option_type: Optional[str],
    expiration: Optional[date],
    strike: Optional[float],
    spot: Optional[float],
    session_date: date,
    missing: list[str],
    notes: list[str],
) -> Optional[dict]:
    notes.append(f"options: alpaca {ALPACA_OPTIONS_FEED} feed snapshots (indicative quotes on the free tier)")
    if option_type is None:
        missing.append("option: no option_type given and no direction to derive it from — contract not resolved")
        return None
    try:
        occ, snap, auto = _resolve_option_contract(
            symbol, option_type, expiration, strike, spot, session_date, missing
        )
    except Exception as exc:
        log.warning("option contract resolution failed for %s", symbol, exc_info=True)
        missing.append(f"option: lookup failed ({exc})")
        return None
    if occ is None:
        return None
    block = _option_block(occ, snap, option_type, spot, session_date)
    if block.get("quote_missing"):
        missing.append("option: no live quote for the contract (check ALPACA_OPTIONS_FEED entitlement)")
    if block.get("iv") is None:
        missing.append("option: IV/greeks unavailable from the snapshot")
    if auto:
        notes.append(f"option contract auto-selected: {occ} (nearest expiration, strike nearest {strike or spot})")
    return block


def _resolve_option_contract(
    symbol: str,
    option_type: str,
    expiration: Optional[date],
    strike: Optional[float],
    spot: Optional[float],
    session_date: date,
    missing: list[str],
) -> tuple[Optional[str], Optional[dict], bool]:
    if expiration is not None and strike is not None:
        occ = _occ_symbol(symbol, expiration, option_type, strike)
        snap = fetch_option_snapshots([occ]).get(occ)
        return occ, snap, False

    reference = strike if strike is not None else spot
    if reference is None:
        missing.append("option: cannot auto-select a contract without a live underlying price")
        return None, None, False

    kwargs: dict = {"option_type": option_type}
    if expiration is not None:
        kwargs["expiration"] = expiration
    else:
        kwargs["expiration_gte"] = session_date
    if strike is not None:
        kwargs["strike_gte"] = strike * 0.99
        kwargs["strike_lte"] = strike * 1.01
    else:
        kwargs["strike_gte"] = reference * 0.90
        kwargs["strike_lte"] = reference * 1.10

    chain = fetch_option_chain_snapshots(symbol, **kwargs)
    candidates = []
    for occ, snap in chain.items():
        parsed = _parse_occ(occ)
        if parsed and parsed["option_type"] == option_type:
            candidates.append((occ, parsed, snap))
    if not candidates:
        missing.append("option: no matching contracts in the chain snapshot")
        return None, None, False

    future = [c for c in candidates if c[1]["expiration"] >= session_date]
    pool = future or candidates
    nearest_exp = min(p["expiration"] for _, p, _ in pool)
    pool = [c for c in pool if c[1]["expiration"] == nearest_exp]
    occ, _parsed, snap = min(pool, key=lambda c: abs(c[1]["strike"] - reference))
    return occ, snap, True


def _option_block(
    occ: str,
    snap: Optional[dict],
    option_type: str,
    spot: Optional[float],
    session_date: date,
) -> dict:
    parsed = _parse_occ(occ) or {}
    exp = parsed.get("expiration")
    strike = parsed.get("strike")
    quote = (snap or {}).get("latestQuote") or {}
    trade = (snap or {}).get("latestTrade") or {}
    greeks = (snap or {}).get("greeks") or {}

    bid = quote.get("bp")
    ask = quote.get("ap")
    mid = spread_pct = None
    if bid is not None and ask is not None and (bid + ask) > 0 and ask >= bid:
        mid = round((bid + ask) / 2, 4)
        if mid > 0:
            spread_pct = round((ask - bid) / mid * 100, 2)

    moneyness = moneyness_pct = None
    if spot and strike:
        signed = (spot - strike) / strike * 100 if option_type == "call" else (strike - spot) / strike * 100
        moneyness_pct = round(signed, 2)
        moneyness = "ATM" if abs(signed) < 0.5 else ("ITM" if signed > 0 else "OTM")

    return {
        "contract": occ,
        "option_type": option_type,
        "expiration": exp.isoformat() if exp else None,
        "strike": strike,
        "dte": (exp - session_date).days if exp else None,
        "moneyness": moneyness,
        "moneyness_pct": moneyness_pct,
        "bid": bid,
        "ask": ask,
        "mid": mid,
        "spread_pct": spread_pct,
        "bid_size": quote.get("bs"),
        "ask_size": quote.get("as"),
        "quote_time": quote.get("t"),
        "last_trade_price": trade.get("p"),
        "last_trade_time": trade.get("t"),
        "iv": (snap or {}).get("impliedVolatility"),
        "delta": greeks.get("delta"),
        "gamma": greeks.get("gamma"),
        "theta": greeks.get("theta"),
        "vega": greeks.get("vega"),
        "rho": greeks.get("rho"),
        "quote_missing": not quote and not trade,
        "feed": ALPACA_OPTIONS_FEED,
    }


def _occ_symbol(ticker: str, expiration: date, option_type: str, strike: float) -> str:
    cp = "C" if option_type == "call" else "P"
    return f"{ticker.upper()}{expiration.strftime('%y%m%d')}{cp}{int(round(strike * 1000)):08d}"


def _parse_occ(occ: str) -> Optional[dict]:
    if not occ or len(occ) < 16:
        return None
    tail = occ[-15:]
    exp_s, cp, strike_s = tail[:6], tail[6], tail[7:]
    if cp not in ("C", "P") or not exp_s.isdigit() or not strike_s.isdigit():
        return None
    try:
        exp = date(2000 + int(exp_s[:2]), int(exp_s[2:4]), int(exp_s[4:6]))
    except ValueError:
        return None
    return {
        "root": occ[:-15],
        "expiration": exp,
        "option_type": "call" if cp == "C" else "put",
        "strike": int(strike_s) / 1000.0,
    }


# ---------------------------------------------------------------------------
# scoring (pure — no I/O; unit-testable with hand-built packets)
# ---------------------------------------------------------------------------

def score_scalp(
    packet: dict,
    direction: Optional[str] = None,
    instrument: Optional[str] = None,
    style: Optional[str] = None,
) -> dict:
    """Deterministic verdict/scoring over a gathered packet."""
    requested = _norm_direction(direction)
    style = _norm_choice("style", style, {"open", "midday", "power_hour"})

    intraday = packet.get("intraday") or {}
    snapshot = packet.get("snapshot") or {}
    daily = packet.get("daily") or {}
    option = packet.get("option")
    staleness = packet.get("staleness") or {}
    market_state = packet.get("market_state") or "closed"
    missing = list(packet.get("missing") or [])
    notes = list(packet.get("data_source_notes") or [])

    if instrument not in ("stock", "option"):
        instrument = "option" if option else "stock"

    evaluated_direction = requested
    if evaluated_direction is None and option and option.get("option_type"):
        evaluated_direction = "long" if option["option_type"] == "call" else "short"
        notes.append(f"direction derived from option_type={option['option_type']}")

    if evaluated_direction is not None:
        ev = _evaluate_direction(packet, evaluated_direction)
    else:
        ev_long = _evaluate_direction(packet, "long")
        ev_short = _evaluate_direction(packet, "short")
        ev = ev_long if (ev_long["setup_score"] or 0) >= (ev_short["setup_score"] or 0) else ev_short
        if ev["setup_score"] is not None:
            notes.append(f"no direction given — evaluated both sides, {ev['direction']} scored higher")

    minutes_since_open = intraday.get("minutes_since_open")
    if style is None:
        style = _default_style(minutes_since_open)

    reasons_for = list(ev["reasons_for"])
    reasons_against = list(ev["reasons_against"])

    liquidity_score, liq_for, liq_against = _liquidity_score(packet, instrument)
    reasons_for += liq_for
    reasons_against += liq_against

    risk_score, risk_against = _risk_score(packet, ev, instrument, liquidity_score)
    reasons_against += risk_against

    setup = ev["setup_score"]
    rvol = intraday.get("rvol")

    # --- option gate --------------------------------------------------------
    option_gate: Optional[str] = None
    if instrument == "option":
        if not option or option.get("quote_missing") or option.get("spread_pct") is None:
            option_gate = "wait"
            reasons_against.append(
                "option quote/spread could not be validated — do not take the option leg without checking it live"
            )
        elif option["spread_pct"] > MAX_OPTION_SPREAD_PCT:
            option_gate = "no_trade"
            reasons_against.append(
                f"option spread {option['spread_pct']}% of mid exceeds the {MAX_OPTION_SPREAD_PCT}% scalp limit — "
                "slippage kills the trade even if the underlying setup works"
            )

    # --- verdict gates (ordered) ---------------------------------------------
    verdict: Optional[str] = None
    if setup is None:
        reasons_against.append("insufficient live data to score the setup")
    if market_state == "closed":
        verdict = "no_trade"
        reasons_against.append("market closed — nothing to scalp right now")
    elif market_state == "afterhours":
        verdict = "no_trade"
        reasons_against.append("regular session is over — scalp window closed")
    elif market_state == "premarket":
        verdict = "wait"
        reasons_against.append("premarket — wait for the 9:30 open; this is a premarket read only")
    elif staleness.get("is_stale"):
        verdict = "wait"
        reasons_against.append("live quotes/bars are stale — refresh before acting")
    elif setup is None:
        verdict = "wait"

    if verdict is None and option_gate == "no_trade":
        verdict = "no_trade"

    if verdict is None and ev["is_chop"]:
        verdict = "wait" if setup >= 40 else "no_trade"
        reasons_against.append(
            "chop: price stuck between VWAP and the opening range on weak volume — "
            "reclaim/breakout signals here are fakeout-prone"
        )

    if verdict is None and minutes_since_open is not None and 0 <= minutes_since_open < 5:
        verdict = "wait"
        reasons_against.append("first 5 minutes — opening range not established, spreads and fakeouts are worst here")

    if (
        verdict is None
        and style == "open"
        and minutes_since_open is not None
        and minutes_since_open < 15
        and (setup < 70 or (rvol or 0.0) < 1.5)
    ):
        verdict = "wait"
        reasons_against.append(
            "open-style scalp before OR15 requires an exceptional setup (score >= 70 and RVOL >= 1.5) — not met yet"
        )

    if verdict is None:
        if setup >= 65 and liquidity_score >= 45 and risk_score <= 70:
            if option_gate == "wait":
                verdict = "wait"
            else:
                verdict = "long_scalp" if ev["direction"] == "long" else "short_scalp"
        elif setup >= 65:
            verdict = "wait"
            if liquidity_score < 45:
                reasons_against.append("setup qualifies but liquidity is too weak to execute cleanly")
            else:
                reasons_against.append("setup qualifies but aggregate risk is too high right now")
        elif setup >= 50:
            verdict = "wait"
        else:
            verdict = "no_trade"

    bias = _bias(packet, ev["is_chop"])

    if staleness.get("is_stale") or setup is None or len(missing) >= 4:
        confidence = "low"
    elif (setup >= 75 or setup <= 30) and len(missing) <= 2:
        confidence = "high"
    else:
        confidence = "medium"

    price = intraday.get("price") if intraday.get("price") is not None else snapshot.get("price")
    trigger, invalidation, targets = _plan(
        ev["direction"], price, _levels(intraday, snapshot), daily.get("atr_14")
    )

    return {
        "symbol": packet.get("symbol"),
        "generated_at": packet.get("generated_at"),
        "market_state": market_state,
        "instrument": instrument,
        "style": style,
        "direction_requested": requested,
        "direction_evaluated": ev["direction"],
        "verdict": verdict,
        "confidence": confidence,
        "bias": bias,
        "setup_score": setup,
        "liquidity_score": liquidity_score,
        "risk_score": risk_score,
        "trigger": trigger,
        "invalidation": invalidation,
        "targets": targets,
        "reasons_for": reasons_for,
        "reasons_against": reasons_against,
        "option_check": _option_check(option) if instrument == "option" else None,
        "missing": missing,
        "data_source_notes": notes,
        "disclaimer": DISCLAIMER,
    }


def _evaluate_direction(packet: dict, direction: str) -> dict:
    intraday = packet.get("intraday") or {}
    snapshot = packet.get("snapshot") or {}
    daily = packet.get("daily") or {}
    market = packet.get("market") or {}
    is_long = direction == "long"

    reasons_for: list[str] = []
    reasons_against: list[str] = []
    score = 50.0
    data_points = 0

    price = intraday.get("price") if intraday.get("price") is not None else snapshot.get("price")
    vwap = intraday.get("vwap")
    vs_vwap = intraday.get("price_vs_vwap_pct")
    rvol = intraday.get("rvol")
    crosses = intraday.get("vwap_cross_count_30m")

    # VWAP side, true reclaim/loss, and fakeout-prone tape
    if price is not None and vwap:
        data_points += 1
        above = price > vwap
        if above == is_long:
            score += 12
            reasons_for.append(f"price on the right side of VWAP ({_fmt_pct(vs_vwap)} vs VWAP)")
        else:
            score -= 12
            reasons_against.append(f"price on the wrong side of VWAP ({_fmt_pct(vs_vwap)} vs VWAP)")
        prev = intraday.get("prev_bar_close")
        if prev is not None:
            if is_long and prev < vwap < price:
                score += 10
                reasons_for.append("fresh VWAP reclaim (previous 1m close below VWAP, now above)")
            elif not is_long and prev > vwap > price:
                score += 10
                reasons_for.append("fresh VWAP loss (previous 1m close above VWAP, now below)")
        if crosses is not None and crosses >= 3:
            score -= 8
            reasons_against.append(
                f"{crosses} VWAP crosses in the last 30 minutes — reclaims/losses here are fakeout-prone"
            )

    # Opening range (only once established; OR15 preferred over OR5)
    or_high = or_low = None
    or_label = None
    if intraday.get("or15_complete") and intraday.get("or15_high") is not None:
        or_high, or_low, or_label = intraday.get("or15_high"), intraday.get("or15_low"), "OR15"
    elif intraday.get("or5_complete") and intraday.get("or5_high") is not None:
        or_high, or_low, or_label = intraday.get("or5_high"), intraday.get("or5_low"), "OR5"

    if price is not None and or_high is not None and or_low is not None:
        data_points += 1
        if is_long:
            if price > or_high:
                score += 12
                reasons_for.append(f"trading above the {or_label} high ({or_high}) — opening-range breakout")
            elif price < or_low:
                score -= 8
                reasons_against.append(f"below the {or_label} low — longs are fighting the opening range")
        else:
            if price < or_low:
                score += 12
                reasons_for.append(f"trading below the {or_label} low ({or_low}) — opening-range breakdown")
            elif price > or_high:
                score -= 8
                reasons_against.append(f"above the {or_label} high — shorts are fighting the opening range")

    # Premarket levels (breakout for longs; failed PM high or PM-low break for shorts)
    pm_high = intraday.get("premarket_high")
    pm_low = intraday.get("premarket_low")
    day_high = intraday.get("day_high")
    if price is not None:
        if is_long and pm_high is not None and price > pm_high:
            score += 8
            reasons_for.append(f"holding above the premarket high ({pm_high})")
        if not is_long:
            if pm_high is not None and day_high is not None and day_high > pm_high and price < pm_high:
                score += 8
                reasons_for.append(f"failed premarket-high breakout (poked above {pm_high}, trading back below)")
            elif pm_low is not None and price < pm_low:
                score += 8
                reasons_for.append(f"below the premarket low ({pm_low})")

    # Intraday 1-minute EMA stack
    e9 = intraday.get("ema9_intraday")
    e20 = intraday.get("ema20_intraday")
    if price is not None and e9 is not None and e20 is not None:
        data_points += 1
        aligned = (price > e9 > e20) if is_long else (price < e9 < e20)
        if aligned:
            score += 10
            reasons_for.append("1-minute EMA stack aligned (price / 9EMA / 20EMA in order)")
        else:
            score -= 5
            reasons_against.append("1-minute EMA stack not aligned with the trade")

    # Daily trend alignment
    d9 = daily.get("ema_9")
    d20 = daily.get("ema_20")
    macd_hist = daily.get("macd_histogram")
    if price is not None and d9 and d20 and macd_hist is not None:
        data_points += 1
        aligned = (price > d9 > d20 and macd_hist > 0) if is_long else (price < d9 < d20 and macd_hist < 0)
        if aligned:
            score += 10
            reasons_for.append("daily trend aligned (EMA9/EMA20 stack + MACD histogram)")
        else:
            score -= 4
            reasons_against.append("daily trend not aligned — this is a countertrend scalp on the daily chart")

    # Daily RSI stretched against the trade
    rsi = daily.get("rsi_14")
    if rsi is not None:
        if is_long and rsi >= 75:
            score -= 6
            reasons_against.append(f"daily RSI {rsi:.0f} — stretched for fresh longs")
        elif not is_long and rsi <= 25:
            score -= 6
            reasons_against.append(f"daily RSI {rsi:.0f} — stretched for fresh shorts")

    # Relative volume
    if rvol is not None:
        data_points += 1
        if rvol >= 2.0:
            score += 10
            reasons_for.append(f"RVOL {rvol:.2f} — strong participation")
        elif rvol >= 1.5:
            score += 8
            reasons_for.append(f"RVOL {rvol:.2f} — above-average participation")
        elif rvol >= 1.0:
            score += 4
        elif rvol < 0.8:
            score -= 8
            reasons_against.append(f"RVOL {rvol:.2f} — not enough volume to trust the move")

    # Range location — holding the favorable extreme of the day
    range_used = intraday.get("day_range_used_pct")
    if range_used is not None:
        if is_long and range_used >= 70:
            score += 4
            reasons_for.append("holding the upper part of today's range")
        elif not is_long and range_used <= 30:
            score += 4
            reasons_for.append("pinned near the lows — sellers in control")

    # SPY/QQQ confirmation
    align_ok = 0
    align_checked = 0
    for t in ("SPY", "QQQ"):
        m = market.get(t) or {}
        pct = m.get("pct_change")
        if pct is None:
            continue
        align_checked += 1
        ok = pct > 0 if is_long else pct < 0
        above = m.get("above_vwap")
        if above is not None:
            ok = ok and (above == is_long)
        align_ok += 1 if ok else 0
    market_align: Optional[str] = None
    if align_checked:
        data_points += 1
        if align_ok == align_checked:
            market_align = "confirming"
            score += 10
            reasons_for.append("SPY/QQQ confirm the direction (price change + VWAP side)")
        elif align_ok == 0:
            market_align = "opposing"
            score -= 10
            reasons_against.append("SPY/QQQ are against this trade")
        else:
            market_align = "mixed"
            reasons_against.append("index confirmation is mixed (SPY/QQQ disagree)")

    # Extension beyond VWAP (chase risk)
    extension_pct: Optional[float] = None
    if vs_vwap is not None:
        extension_pct = vs_vwap if is_long else -vs_vwap
        if extension_pct > 4.0:
            score -= 12
            reasons_against.append(f"{extension_pct:.1f}% extended beyond VWAP — chasing")
        elif extension_pct > 2.5:
            score -= 6
            reasons_against.append(f"{extension_pct:.1f}% beyond VWAP — getting extended")

    # Chop: inside the VWAP/opening-range band on weak volume or a whippy tape
    is_chop = False
    band_vals = [v for v in (vwap, or_high, or_low) if v is not None]
    if price is not None and vwap is not None and len(band_vals) >= 2 and min(band_vals) < price < max(band_vals):
        rvol_low = rvol is not None and rvol < CHOP_RVOL_MAX
        choppy_tape = crosses is not None and crosses >= VWAP_CHOP_CROSSES
        if rvol_low or choppy_tape:
            is_chop = True

    setup_score = round(max(0.0, min(100.0, score)), 1) if data_points > 0 else None

    return {
        "direction": direction,
        "setup_score": setup_score,
        "reasons_for": reasons_for,
        "reasons_against": reasons_against,
        "is_chop": is_chop,
        "extension_pct": extension_pct,
        "market_align": market_align,
        "data_points": data_points,
    }


def _bias(packet: dict, is_chop: bool) -> str:
    if is_chop:
        return "chop"
    intraday = packet.get("intraday") or {}
    snapshot = packet.get("snapshot") or {}
    daily = packet.get("daily") or {}
    market = packet.get("market") or {}

    signals: list[int] = []  # +1 bull, -1 bear
    price = intraday.get("price") if intraday.get("price") is not None else snapshot.get("price")
    vwap = intraday.get("vwap")
    if price is not None and vwap:
        signals.append(1 if price > vwap else -1)
    e9, e20 = intraday.get("ema9_intraday"), intraday.get("ema20_intraday")
    if e9 is not None and e20 is not None and e9 != e20:
        signals.append(1 if e9 > e20 else -1)
    gap = snapshot.get("gap_pct")
    if gap is not None and abs(gap) >= 0.3:
        signals.append(1 if gap > 0 else -1)
    hist = daily.get("macd_histogram")
    if hist:
        signals.append(1 if hist > 0 else -1)
    rng = intraday.get("day_range_used_pct")
    if rng is not None:
        if rng >= 70:
            signals.append(1)
        elif rng <= 30:
            signals.append(-1)
    for t in ("SPY", "QQQ"):
        pct = (market.get(t) or {}).get("pct_change")
        if pct is not None and abs(pct) >= 0.15:
            signals.append(1 if pct > 0 else -1)

    if not signals:
        return "mixed"
    bull = sum(1 for s in signals if s > 0)
    bear = len(signals) - bull
    if bull >= bear + 2:
        return "bullish"
    if bear >= bull + 2:
        return "bearish"
    return "mixed"


def _liquidity_score(packet: dict, instrument: str) -> tuple[float, list[str], list[str]]:
    intraday = packet.get("intraday") or {}
    snapshot = packet.get("snapshot") or {}
    option = packet.get("option")
    score = 50.0
    reasons_for: list[str] = []
    reasons_against: list[str] = []

    rvol = intraday.get("rvol")
    if rvol is not None:
        if rvol >= 2.0:
            score += 20
            reasons_for.append(f"RVOL {rvol:.2f} — very active tape")
        elif rvol >= 1.5:
            score += 15
        elif rvol >= 1.0:
            score += 8
        elif rvol >= 0.8:
            score -= 5
        else:
            score -= 20
            reasons_against.append(f"RVOL {rvol:.2f} — thin tape for a scalp")

    price = intraday.get("price") if intraday.get("price") is not None else snapshot.get("price")
    volume = snapshot.get("today_volume")
    if price and volume:
        dollars = price * volume
        if dollars >= 50e6:
            score += 15
        elif dollars >= 10e6:
            score += 5
        elif dollars < 2e6:
            score -= 20
            reasons_against.append("under $2M traded today — too illiquid to scalp")

    if instrument == "option":
        if not option:
            score -= 20
        else:
            spread = option.get("spread_pct")
            if spread is None:
                score -= 20
            elif spread <= 2.0:
                score += 15
                reasons_for.append(f"tight option spread ({spread}% of mid)")
            elif spread <= WIDE_OPTION_SPREAD_PCT:
                score += 5
            elif spread <= MAX_OPTION_SPREAD_PCT:
                score -= 10
                reasons_against.append(f"option spread {spread}% of mid — wide for a scalp")
            else:
                score -= 30

    return round(max(0.0, min(100.0, score)), 1), reasons_for, reasons_against


def _risk_score(
    packet: dict, ev: dict, instrument: str, liquidity_score: float
) -> tuple[float, list[str]]:
    intraday = packet.get("intraday") or {}
    daily = packet.get("daily") or {}
    option = packet.get("option")
    staleness = packet.get("staleness") or {}
    market_state = packet.get("market_state") or "closed"
    against: list[str] = []
    score = 35.0  # scalping baseline — never "low risk"

    if staleness.get("is_stale"):
        score += 25
    if market_state != "rth":
        score += 10

    mins = intraday.get("minutes_since_open")
    if mins is not None and 0 <= mins < 5:
        score += 20
    elif mins is not None and 0 <= mins < 15:
        score += 10

    ext = ev.get("extension_pct")
    if ext is not None:
        if ext > 4.0:
            score += 20
        elif ext > 2.5:
            score += 10

    if ev.get("market_align") == "opposing":
        score += 10
    if ev.get("is_chop"):
        score += 10

    rsi = daily.get("rsi_14")
    if rsi is not None and (
        (ev.get("direction") == "long" and rsi >= 75)
        or (ev.get("direction") == "short" and rsi <= 25)
    ):
        score += 8

    recent_news = _recent_news_count(packet, hours=2)
    if recent_news:
        score += 8
        against.append(
            f"{recent_news} headline(s) in the last 2 hours — event risk; read the news before acting"
        )

    if instrument == "option" and option:
        dte = option.get("dte")
        if dte is not None:
            if dte <= 0:
                score += 15
                against.append("0DTE contract — extreme gamma/theta; speed and sizing matter more than the setup")
            elif dte <= 3:
                score += 8
        spread = option.get("spread_pct")
        if spread is not None and WIDE_OPTION_SPREAD_PCT < spread <= MAX_OPTION_SPREAD_PCT:
            score += 8
        if option.get("iv") is None:
            score += 4

    if liquidity_score < 40:
        score += 10

    return round(max(0.0, min(100.0, score)), 1), against


def _recent_news_count(packet: dict, hours: int = 2) -> int:
    generated = _parse_iso(packet.get("generated_at"))
    if generated is None:
        return 0
    count = 0
    for article in packet.get("news") or []:
        created = _parse_iso(article.get("created_at"))
        if created is None:
            continue
        try:
            if timedelta(0) <= generated - created <= timedelta(hours=hours):
                count += 1
        except TypeError:  # naive/aware mismatch — skip rather than crash
            continue
    return count


def _levels(intraday: dict, snapshot: dict) -> dict[str, Optional[float]]:
    return {
        "vwap": intraday.get("vwap"),
        "or5_high": intraday.get("or5_high"),
        "or5_low": intraday.get("or5_low"),
        "or15_high": intraday.get("or15_high"),
        "or15_low": intraday.get("or15_low"),
        "premarket_high": intraday.get("premarket_high"),
        "premarket_low": intraday.get("premarket_low"),
        "day_high": intraday.get("day_high"),
        "day_low": intraday.get("day_low"),
        "prev_close": snapshot.get("prev_close"),
        "today_open": snapshot.get("today_open"),
    }


def _plan(
    direction: str,
    price: Optional[float],
    levels: dict,
    atr: Optional[float],
) -> tuple[Optional[dict], Optional[dict], list[dict]]:
    """Deterministic trigger/invalidation/targets from the nearest tracked levels."""
    if price is None or direction not in ("long", "short"):
        return None, None, []
    is_long = direction == "long"
    forward_names = _PLAN_LEVELS_UP if is_long else _PLAN_LEVELS_DOWN
    behind_names = _PLAN_LEVELS_DOWN if is_long else _PLAN_LEVELS_UP

    forward = sorted(
        (
            (n, v) for n, v in levels.items()
            if n in forward_names and v is not None and (v > price if is_long else v < price)
        ),
        key=lambda x: abs(x[1] - price),
    )
    behind = sorted(
        (
            (n, v) for n, v in levels.items()
            if n in behind_names and v is not None and (v < price if is_long else v > price)
        ),
        key=lambda x: abs(x[1] - price),
    )
    side_word = "above" if is_long else "below"
    back_word = "below" if is_long else "above"

    if forward:
        t_name, t_price = forward[0]
        trigger = {
            "level": t_name,
            "price": t_price,
            "description": f"1m close {side_word} {t_name} at {t_price} with expanding volume",
        }
    else:
        trigger = {
            "level": None,
            "price": None,
            "description": f"already {side_word} all tracked levels — wait for a pullback that holds rather than chasing",
        }

    if behind:
        i_name, i_price = behind[0]
        invalidation = {
            "level": i_name,
            "price": i_price,
            "description": f"1m close back {back_word} {i_name} at {i_price} kills the setup",
        }
    elif atr:
        stop = round(price - 0.3 * atr, 2) if is_long else round(price + 0.3 * atr, 2)
        invalidation = {
            "level": "atr_stop",
            "price": stop,
            "description": f"no structural level nearby — use ~{stop} (0.3x daily ATR) as the invalidation",
        }
    else:
        invalidation = None

    base = trigger["price"] if trigger["price"] is not None else price
    targets = [
        {"level": n, "price": v}
        for n, v in forward
        if (v > base if is_long else v < base)
    ][:3]
    if atr:
        ext = round(price + 0.5 * atr, 2) if is_long else round(price - 0.5 * atr, 2)
        targets.append({"level": "half_daily_atr_extension", "price": ext})
    return trigger, invalidation, targets


def _option_check(option: Optional[dict]) -> dict:
    if not option:
        return {"status": "unresolved", "detail": "no contract resolved"}
    spread = option.get("spread_pct")
    if option.get("quote_missing") or spread is None:
        status = "unknown"
    elif spread > MAX_OPTION_SPREAD_PCT:
        status = "reject_spread"
    elif spread > WIDE_OPTION_SPREAD_PCT:
        status = "caution_spread"
    else:
        status = "ok"
    return {
        "status": status,
        "contract": option.get("contract"),
        "spread_pct": spread,
        "dte": option.get("dte"),
        "delta": option.get("delta"),
        "iv": option.get("iv"),
    }


def _default_style(minutes_since_open: Optional[int]) -> Optional[str]:
    if minutes_since_open is None:
        return None
    if minutes_since_open < 30:
        return "open"
    if minutes_since_open >= 330:  # 15:00 ET onward
        return "power_hour"
    return "midday"


# ---------------------------------------------------------------------------
# small utilities
# ---------------------------------------------------------------------------

def _fmt_pct(value: Optional[float]) -> str:
    return f"{value:+.2f}%" if value is not None else "n/a"


def _pct(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b is None or b == 0:
        return None
    return round((a - b) / b * 100, 2)


def _daily_bar_date(bar: dict) -> Optional[date]:
    t = bar.get("t")
    if not isinstance(t, str) or len(t) < 10:
        return None
    try:
        return date.fromisoformat(t[:10])
    except ValueError:
        return None


def _parse_iso(ts) -> Optional[datetime]:
    if not ts:
        return None
    s = str(ts).replace("Z", "+00:00")
    # Alpaca trade timestamps carry nanoseconds; trim to microseconds.
    s = re.sub(r"\.(\d{6})\d+", r".\1", s)
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _age_seconds(ts, now_et: datetime) -> Optional[int]:
    dt = _parse_iso(ts)
    if dt is None or dt.tzinfo is None:
        return None
    return max(0, int((now_et - dt.astimezone(ET)).total_seconds()))
