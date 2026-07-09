"""
Scoring-logic tests for the Scalper Analyzer.

score_scalp() is a pure function over a gathered packet, so these tests build
synthetic packets directly — no network, no mocking of Alpaca calls.
"""

from datetime import date, datetime
from zoneinfo import ZoneInfo

import app.engine.scalper as scalper
from app.engine.scalper import (
    _intraday_block,
    _occ_symbol,
    _parse_occ,
    _staleness_block,
    score_scalp,
)

ET = ZoneInfo("America/New_York")


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def make_packet(**over) -> dict:
    """Strong long setup, mid-session, fresh data — overrides applied on top."""
    base = {
        "symbol": "TSLA",
        "generated_at": "2026-07-08T13:00:00-04:00",
        "session_date": "2026-07-08",
        "market_state": "rth",
        "snapshot": {
            "price": 251.3,
            "last_trade_time": "2026-07-08T16:59:58Z",
            "prev_close": 245.0,
            "change_pct": 2.57,
            "gap_pct": 1.2,
            "today_open": 248.0,
            "today_high": 251.8,
            "today_low": 247.2,
            "today_volume": 55_000_000,
            "avg_volume_20": 60_000_000,
            "day_rvol": 0.92,
        },
        "intraday": {
            "session_date": "2026-07-08",
            "is_live_today": True,
            "price": 251.3,
            "vwap": 249.8,
            "price_vs_vwap_pct": 0.6,
            "prev_bar_close": 251.1,
            "day_high": 251.8,
            "day_low": 247.2,
            "day_range_used_pct": 89.0,
            "dist_from_day_high_pct": -0.2,
            "dist_from_day_low_pct": 1.74,
            "premarket_high": 249.0,
            "premarket_low": 246.0,
            "premarket_volume": 1_000_000,
            "or5_high": 249.5,
            "or5_low": 247.8,
            "or15_high": 250.0,
            "or15_low": 247.5,
            "or5_complete": True,
            "or15_complete": True,
            "ema9_intraday": 250.9,
            "ema20_intraday": 250.2,
            "intraday_bar_count": 210,
            "vwap_cross_count_30m": 0,
            "cumulative_rth_volume": 40_000_000,
            "rvol": 1.8,
            "rvol_method": "time_adjusted_20d_cache",
            "minutes_since_open": 210,
        },
        "daily": {
            "as_of_date": "2026-07-07",
            "last_close": 245.0,
            "ema_9": 246.0,
            "ema_20": 243.0,
            "sma_20": 242.0,
            "sma_50": 238.0,
            "sma_200": 220.0,
            "rsi_14": 61.0,
            "atr_14": 8.4,
            "macd": 2.1,
            "macd_signal": 1.6,
            "macd_histogram": 0.5,
        },
        "market": {
            "SPY": {"pct_change": 0.5, "price": 630.0, "vwap": 628.0,
                    "price_vs_vwap_pct": 0.32, "above_vwap": True},
            "QQQ": {"pct_change": 0.7, "price": 560.0, "vwap": 557.5,
                    "price_vs_vwap_pct": 0.45, "above_vwap": True},
        },
        "news": [],
        "option": None,
        "staleness": {"last_trade_age_seconds": 2, "last_bar_age_seconds": 40, "is_stale": False},
        "missing": [],
        "data_source_notes": [],
    }
    return _merge(base, over)


def make_bear_packet(**over) -> dict:
    """Strong short setup mirroring the long baseline."""
    bear = make_packet(
        snapshot={
            "price": 244.0, "prev_close": 247.0, "change_pct": -1.21, "gap_pct": -0.8,
            "today_open": 245.0, "today_high": 246.8, "today_low": 243.8,
        },
        intraday={
            "price": 244.0, "vwap": 245.5, "price_vs_vwap_pct": -0.61,
            "prev_bar_close": 244.2, "day_high": 246.8, "day_low": 243.8,
            "day_range_used_pct": 7.0, "premarket_high": 246.0, "premarket_low": 244.5,
            "or5_high": 246.2, "or5_low": 245.0, "or15_high": 246.5, "or15_low": 244.8,
            "ema9_intraday": 244.3, "ema20_intraday": 244.9, "rvol": 1.7,
        },
        daily={"ema_9": 246.0, "ema_20": 248.0, "rsi_14": 42.0, "macd_histogram": -0.5},
        market={
            "SPY": {"pct_change": -0.6, "above_vwap": False},
            "QQQ": {"pct_change": -0.8, "above_vwap": False},
        },
    )
    return _merge(bear, over)


# ---------------------------------------------------------------------------
# core verdicts
# ---------------------------------------------------------------------------

def test_strong_long_setup_scores_long_scalp():
    result = score_scalp(make_packet(), direction="long")
    assert result["verdict"] == "long_scalp"
    assert result["setup_score"] >= 65
    assert result["bias"] == "bullish"
    assert result["confidence"] in ("medium", "high")
    assert result["reasons_for"]
    assert result["trigger"] is not None
    assert result["invalidation"] is not None
    assert result["targets"]
    assert result["disclaimer"]


def test_strong_short_setup_scores_short_scalp():
    result = score_scalp(make_bear_packet(), direction="short")
    assert result["verdict"] == "short_scalp"
    assert result["setup_score"] >= 65
    assert result["bias"] == "bearish"


def test_direction_aliases_up_down():
    assert score_scalp(make_packet(), direction="up")["direction_evaluated"] == "long"
    assert score_scalp(make_bear_packet(), direction="down")["direction_evaluated"] == "short"


def test_no_direction_picks_stronger_side():
    result = score_scalp(make_bear_packet())
    assert result["direction_requested"] is None
    assert result["direction_evaluated"] == "short"
    assert result["verdict"] == "short_scalp"


# ---------------------------------------------------------------------------
# hard gates: market state, staleness
# ---------------------------------------------------------------------------

def test_market_closed_forces_no_trade():
    result = score_scalp(make_packet(market_state="closed"), direction="long")
    assert result["verdict"] == "no_trade"


def test_afterhours_forces_no_trade():
    result = score_scalp(make_packet(market_state="afterhours"), direction="long")
    assert result["verdict"] == "no_trade"


def test_premarket_forces_wait():
    result = score_scalp(make_packet(market_state="premarket"), direction="long")
    assert result["verdict"] == "wait"


def test_stale_data_forces_wait_and_low_confidence():
    packet = make_packet(
        staleness={"last_trade_age_seconds": 1800, "last_bar_age_seconds": 1800, "is_stale": True},
        missing=["live data stale during market hours — last trade/bar too old to act on"],
    )
    result = score_scalp(packet, direction="long")
    assert result["verdict"] == "wait"
    assert result["confidence"] == "low"


# ---------------------------------------------------------------------------
# chop classification
# ---------------------------------------------------------------------------

def test_low_rvol_inside_vwap_or_band_is_chop():
    packet = make_packet(intraday={
        "price": 249.0, "price_vs_vwap_pct": -0.32, "prev_bar_close": 249.1,
        "vwap": 249.5, "or15_high": 250.5, "or15_low": 248.0,
        "or5_high": 250.2, "or5_low": 248.4,
        "ema9_intraday": 249.2, "ema20_intraday": 249.4,
        "rvol": 0.6, "vwap_cross_count_30m": 5, "day_range_used_pct": 45.0,
    })
    result = score_scalp(packet, direction="long")
    assert result["bias"] == "chop"
    assert result["verdict"] in ("wait", "no_trade")
    assert any("chop" in reason for reason in result["reasons_against"])


# ---------------------------------------------------------------------------
# option gates
# ---------------------------------------------------------------------------

def _option(**over) -> dict:
    base = {
        "contract": "TSLA260710C00250000", "option_type": "call",
        "expiration": "2026-07-10", "strike": 250.0, "dte": 2,
        "moneyness": "ITM", "moneyness_pct": 0.52,
        "bid": 4.0, "ask": 4.1, "mid": 4.05, "spread_pct": 2.47,
        "last_trade_price": 4.05, "iv": 0.55, "delta": 0.55,
        "gamma": 0.04, "theta": -0.9, "vega": 0.12,
        "quote_missing": False, "feed": "indicative",
    }
    base.update(over)
    return base


def test_wide_option_spread_rejects_even_with_good_underlying():
    packet = make_packet(option=_option(bid=1.0, ask=1.16, mid=1.08, spread_pct=14.8))
    result = score_scalp(packet, direction="long", instrument="option")
    assert result["verdict"] == "no_trade"
    assert result["option_check"]["status"] == "reject_spread"
    assert any("spread" in reason for reason in result["reasons_against"])


def test_acceptable_option_spread_allows_scalp_verdict():
    packet = make_packet(option=_option())
    result = score_scalp(packet, direction="long", instrument="option")
    assert result["verdict"] == "long_scalp"
    assert result["option_check"]["status"] == "ok"


def test_missing_option_quote_caps_verdict_at_wait():
    packet = make_packet(option=_option(bid=None, ask=None, mid=None,
                                        spread_pct=None, quote_missing=True))
    result = score_scalp(packet, direction="long", instrument="option")
    assert result["verdict"] == "wait"
    assert result["option_check"]["status"] == "unknown"


def test_direction_derived_from_put_option_type():
    packet = make_bear_packet(option=_option(option_type="put", moneyness="OTM"))
    result = score_scalp(packet, instrument="option")
    assert result["direction_evaluated"] == "short"


# ---------------------------------------------------------------------------
# open-session strictness
# ---------------------------------------------------------------------------

def test_first_five_minutes_forces_wait():
    packet = make_packet(intraday={
        "minutes_since_open": 3, "or5_complete": False, "or15_complete": False,
    })
    result = score_scalp(packet, direction="long")
    assert result["verdict"] == "wait"
    assert any("opening range" in reason for reason in result["reasons_against"])


def test_open_style_extra_strict_before_or15():
    packet = make_packet(intraday={
        "minutes_since_open": 10, "or15_complete": False, "rvol": 1.1,
    })
    result = score_scalp(packet, direction="long", style="open")
    assert result["verdict"] == "wait"
    assert any("OR15" in reason for reason in result["reasons_against"])


# ---------------------------------------------------------------------------
# missing data, bounds, caveats
# ---------------------------------------------------------------------------

def test_no_data_yields_wait_and_low_confidence():
    packet = make_packet(
        snapshot={}, intraday={}, daily={}, market={},
        missing=["TSLA: no Alpaca snapshot", "TSLA: no daily bars", "TSLA: no minute bars"],
    )
    # dict-merge keeps base keys, so force-empty the blocks explicitly
    packet["snapshot"] = {}
    packet["intraday"] = {}
    packet["daily"] = {}
    packet["market"] = {}
    result = score_scalp(packet, direction="long")
    assert result["verdict"] in ("wait", "no_trade")
    assert result["setup_score"] is None
    assert result["confidence"] == "low"
    assert any("insufficient" in reason for reason in result["reasons_against"])
    assert result["missing"]


def test_scores_are_clamped_0_to_100():
    for packet, direction in ((make_packet(), "long"), (make_bear_packet(), "short")):
        result = score_scalp(packet, direction=direction)
        for key in ("setup_score", "liquidity_score", "risk_score"):
            assert 0 <= result[key] <= 100, key


def test_missing_caveats_are_passed_through():
    packet = make_packet(missing=["TSLA: RVOL unavailable"])
    result = score_scalp(packet, direction="long")
    assert "TSLA: RVOL unavailable" in result["missing"]


def test_recent_news_adds_event_risk_warning():
    packet = make_packet(news=[{
        "headline": "TSLA announces something big",
        "created_at": "2026-07-08T16:30:00Z",  # 30 min before generated_at
        "source": "benzinga", "url": "https://example.com",
    }])
    result = score_scalp(packet, direction="long")
    assert any("event risk" in reason for reason in result["reasons_against"])


# ---------------------------------------------------------------------------
# plan (trigger / invalidation / targets)
# ---------------------------------------------------------------------------

def test_long_plan_uses_nearest_levels():
    result = score_scalp(make_packet(), direction="long")
    # price 251.3: nearest overhead level is day_high 251.8, nearest support is vwap 249.8
    assert result["trigger"]["level"] == "day_high"
    assert result["trigger"]["price"] == 251.8
    assert result["invalidation"]["level"] == "vwap"
    assert result["invalidation"]["price"] == 249.8
    assert any(t["level"] == "half_daily_atr_extension" for t in result["targets"])


def test_short_plan_mirrors_direction():
    result = score_scalp(make_bear_packet(), direction="short")
    # price 244.0: nearest breakdown level below is day_low 243.8; nearest
    # resistance-type level above is today_open 245.0
    assert result["trigger"]["level"] == "day_low"
    assert result["trigger"]["price"] == 243.8
    assert result["invalidation"]["level"] == "today_open"
    assert result["invalidation"]["price"] == 245.0


# ---------------------------------------------------------------------------
# intraday gathering block (synthetic bars, no network)
# ---------------------------------------------------------------------------

def _minute_bar(day: date, hour: int, minute: int, price: float, volume: int = 5000) -> dict:
    ts = datetime(day.year, day.month, day.day, hour, minute, tzinfo=ET)
    return {
        "t": ts.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "o": price, "h": price + 0.1, "l": price - 0.1, "c": price, "v": volume,
    }


def test_intraday_block_from_synthetic_bars(monkeypatch):
    # RVOL's historical leg is cache-only; force the linear-ADV fallback.
    monkeypatch.setattr(scalper, "fetch_minute_bars_for_date", lambda *a, **k: {})

    day = date(2026, 7, 8)
    now_et = datetime(2026, 7, 8, 10, 10, tzinfo=ET)
    bars = [_minute_bar(day, 9, 25, 99.5, volume=2000)]  # one premarket bar
    price = 100.0
    for i in range(40):  # 9:30 .. 10:09, drifting up
        bars.append(_minute_bar(day, 9 + (30 + i) // 60, (30 + i) % 60, price + i * 0.05))
    daily_bars = [
        {"t": f"2026-06-{d:02d}T04:00:00Z", "o": 100, "h": 101, "l": 99, "c": 100, "v": 1_000_000}
        for d in range(1, 27)
    ]

    missing: list = []
    notes: list = []
    block = _intraday_block("TESTX", bars, daily_bars, now_et, day, missing, notes)

    assert block["price"] == bars[-1]["c"]
    assert block["vwap"] is not None
    assert block["minutes_since_open"] == 40
    assert block["or5_complete"] and block["or15_complete"]
    assert block["or5_high"] is not None and block["or15_high"] is not None
    assert block["premarket_high"] is not None
    assert block["premarket_volume"] == 2000
    assert block["ema9_intraday"] is not None
    assert block["ema20_intraday"] is not None
    assert block["intraday_bar_count"] == 40
    assert block["rvol"] is not None
    assert block["rvol_method"] == "linear_vs_adv20"
    assert block["vwap_cross_count_30m"] is not None
    # a steadily rising tape should not read as whippy around VWAP
    assert block["vwap_cross_count_30m"] <= 2


def test_staleness_block_flags_dead_tape_during_rth():
    now_et = datetime(2026, 7, 8, 13, 0, tzinfo=ET)
    fresh_bar = _minute_bar(date(2026, 7, 8), 12, 59, 100.0)
    old_bar = _minute_bar(date(2026, 7, 8), 11, 0, 100.0)

    live = _staleness_block("rth", {"last_trade_time": "2026-07-08T16:59:58Z"}, [fresh_bar], now_et)
    assert live["is_stale"] is False

    dead = _staleness_block("rth", {"last_trade_time": "2026-07-08T15:00:00Z"}, [old_bar], now_et)
    assert dead["is_stale"] is True

    # outside RTH the staleness gate is handled by market_state instead
    closed = _staleness_block("closed", {}, [], now_et)
    assert closed["is_stale"] is False


# ---------------------------------------------------------------------------
# OCC symbol helpers
# ---------------------------------------------------------------------------

def test_occ_symbol_round_trip():
    occ = _occ_symbol("TSLA", date(2026, 7, 10), "call", 250)
    assert occ == "TSLA260710C00250000"
    parsed = _parse_occ(occ)
    assert parsed == {"root": "TSLA", "expiration": date(2026, 7, 10),
                      "option_type": "call", "strike": 250.0}

    occ = _occ_symbol("nbis", date(2026, 12, 18), "put", 42.5)
    assert occ == "NBIS261218P00042500"
    parsed = _parse_occ(occ)
    assert parsed["option_type"] == "put"
    assert parsed["strike"] == 42.5


def test_parse_occ_rejects_garbage():
    assert _parse_occ("") is None
    assert _parse_occ("TSLA") is None
    assert _parse_occ("TSLA260710X00250000") is None
