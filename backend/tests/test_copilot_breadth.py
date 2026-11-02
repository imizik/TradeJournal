"""The copilot's market breadth and options positioning (docs/copilot-lab.md § Breadth and positioning). Offline: Tradier
and the options feed are stubbed."""
from datetime import date, datetime
from types import SimpleNamespace

import pytest

from app.ai import copilot, copilot_breadth as b, copilot_tools
from app.engine import tradier
from app.engine.chart_math import ET
from app.engine.options_models import OptionContract
from tests.test_copilot import _text, _turn

NOW = datetime(2026, 11, 2, 15, 0, tzinfo=ET)


def quote(last, prev, high=None, low=None, top=None, bottom=None):
    return {"last": last, "prevclose": prev, "high": high or last, "low": low or last, "week_52_high": top, "week_52_low": bottom}


def test_breadth_counts_the_average_stock_and_each_sector():
    index = {"AAA": "Tech", "BBB": "Tech", "CCC": "Energy", "DDD": "Energy", "EEE": "Energy"}
    quotes = {"AAA": quote(110, 100, high=111, top=111),  # +10%, a new high
              "BBB": quote(70, 80, low=69, top=100, bottom=69),  # -12.5%, a new low, 30% off its high
              "CCC": quote(50, 49, top=52),  # +2%, within 5% of its high
              "DDD": quote(40, 40, top=60)}  # unchanged, 33% off; EEE has no quote
    out = b.breadth(quotes, index)
    assert (out["members"], out["quoted"], out["advancers"], out["decliners"], out["up_share"]) == (5, 4, 2, 1, 0.5)
    assert out["median_day_pct"] == pytest.approx(1.02) and out["equal_weight_day_pct"] == pytest.approx((10 - 12.5 + 2.041 + 0) / 4, abs=0.01)
    assert (out["new_52w_highs"], out["new_52w_lows"]) == (1, 1)
    assert out["within_5pct_of_52w_high"] == 0.5 and out["20pct_or_more_below_52w_high"] == 0.5
    assert out["by_sector"]["Energy"]["up_share"] == 0.5 and out["by_sector"]["Tech"]["advancers"] == 1


def test_the_hand_kept_list_is_the_whole_index_in_quote_form():
    index, as_of = b.members()
    assert 495 <= len(index) <= 510 and len(set(index.values())) == 11 and as_of
    assert "BRK.B" in index and b._provider("BRK.B") == "BRK/B"


def test_live_breadth_maps_provider_symbols_back_and_caches(monkeypatch):
    b._cache.clear()
    calls = []
    index = {"BRK.B": "Financials", "AAPL": "Information Technology"}
    monkeypatch.setattr(b, "members", lambda: (index, "2026-11-02"))

    def quotes(symbols, greeks=False):
        calls.append(symbols)
        return {"BRK/B": SimpleNamespace(raw=quote(500, 490)), "AAPL": SimpleNamespace(raw=quote(330, 340))}
    monkeypatch.setattr(tradier, "get_quotes_once", quotes)
    first = b.live_breadth(NOW)
    assert calls == [["BRK/B", "AAPL"]] and first["advancers"] == 1 and first["state"] == "ok"
    assert b.live_breadth(NOW) is first and len(calls) == 1  # three minutes of cache
    b._cache.clear()

    def down(symbols, greeks=False):
        raise tradier.TradierError("429")
    monkeypatch.setattr(tradier, "get_quotes_once", down)
    assert b.live_breadth(NOW)["state"] == "unavailable"
    b._cache.clear()


def contract(kind, strike, iv, delta, volume, oi, expiration=date(2026, 12, 4)):
    return OptionContract(symbol=f"SPY{kind}{strike}", underlying="SPY", root="SPY", expiration=expiration, option_type=kind,
                          strike=strike, multiplier=100, bid=1.0, ask=1.1, last=1.0, bid_size=1, ask_size=1, volume=volume,
                          open_interest=oi, bid_time=None, ask_time=None, trade_time=None, iv=iv, iv_smoothed=None, delta=delta,
                          gamma=None, theta=None, vega=None, greeks_updated_at=None)


def test_chain_stats_read_atm_iv_skew_and_put_call():
    chain = SimpleNamespace(expiration=date(2026, 12, 4), contracts=[
        contract("call", 100, 0.20, 0.52, 100, 1000), contract("put", 100, 0.22, -0.48, 150, 2000),
        contract("call", 110, 0.15, 0.24, 50, 500), contract("put", 90, 0.30, -0.26, 250, 3000),
        contract("call", 120, 0.14, 0.10, 50, 500)])
    out = b.chain_stats(chain, 101.0, date(2026, 11, 2))
    assert out["days"] == 32 and out["atm_strike"] == 100 and out["atm_iv_pct"] == 21.0
    assert (out["put_25d_iv_pct"], out["call_25d_iv_pct"], out["skew_25d"]) == (30.0, 15.0, 15.0)
    assert out["put_call_volume"] == 2.0 and out["put_call_open_interest"] == 2.5


def test_two_expiries_near_and_a_month_out():
    today = date(2026, 11, 2)
    live = [date(2026, 11, 3), date(2026, 11, 9), date(2026, 11, 30), date(2026, 12, 4), date(2027, 1, 15)]
    assert b.pick_two(live, today) == [date(2026, 11, 9), date(2026, 11, 30)]
    assert b.pick_two([date(2026, 11, 3)], today) == []


def test_the_vix_curve_shape():
    rows = lambda a, c, d: {"VIX9D": {"last": a}, "VIX": {"last": c}, "VIX3M": {"last": d}}  # noqa: E731
    assert b.vol_indexes(rows(15, 16, 18))["curve"] == "contango"
    assert b.vol_indexes(rows(30, 26, 23))["curve"] == "backwardation"
    assert b.vol_indexes(rows(22.5, 21.2, 21.6))["curve"] == "mixed"


def test_positioning_defaults_to_spy_and_refuses_bad_symbols():
    assert copilot_tools.validate("get_positioning", {}) == {"symbol": "SPY"}
    assert copilot_tools.validate("get_positioning", {"symbol": "smh"}) == {"symbol": "SMH"}
    with pytest.raises(copilot_tools.ToolInputError):
        copilot_tools.validate("get_positioning", {"symbol": "../x"})
    with pytest.raises(copilot_tools.ToolInputError):
        copilot_tools.validate("get_breadth", {"symbol": "SPY"})


def test_the_fixture_turns_read_both_tools():
    breadth = _turn([{"role": "user", "content": "Is the average stock participating, or is this rotation?"}], copilot.FakeAdapter(0))
    assert "get_breadth" in [e["name"] for e in breadth if e["type"] == "tool"] and "Breadth" in _text(breadth)
    fear = _turn([{"role": "user", "content": "Is fear priced in? What does SPY skew say?"}], copilot.FakeAdapter(0))
    assert "get_positioning" in [e["name"] for e in fear if e["type"] == "tool"] and "VIX curve" in _text(fear)
