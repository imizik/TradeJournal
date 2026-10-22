"""Index-native charts: explicit units, provider hours and bounded shared reads."""
from datetime import datetime

import httpx
import pytest

from app.engine import chart_feed as feed_module
from app.engine.chart_feed import ChartFeed, ChartFeedError
from app.engine.chart_indices import index_bars, index_quote, normalize_index
from app.engine.chart_math import ET


def candle(day="2026-10-20", **changes):
    return {"date": day, "open": 51.2, "high": 51.6, "low": 51.1, "close": 51.46, "volume": 0, **changes}


def test_yield_scale_is_explicit_for_quotes_and_ohlc_not_magnitude():
    quote = index_quote({"symbol": "TNX:CGI", "last": 51.46, "previous_close": 51.17, "trade_time": 1234, "volume": 0})
    assert quote["symbol"] == "US10Y" and quote["unit"] == "percent"
    assert quote["last"] == pytest.approx(5.146)
    assert quote["change_bps"] == pytest.approx(2.9)
    assert quote["trade_time"] == 1234 and quote["volume"] is None
    bars, issues = normalize_index([candle()], "US10Y", True)
    assert bars[0]["open"] == pytest.approx(5.12)
    assert bars[0]["close"] == pytest.approx(quote["last"])
    assert not issues
    vix = {"symbol": "VIX", "last": 16.68, "previous_close": 17.31}
    assert index_quote(vix)["last"] == 16.68
    stock = {"symbol": "SPY", "last": 600}
    assert index_quote(stock) is stock


def test_invalid_daily_row_and_conflicting_date_stay_missing():
    bars, issues = normalize_index([candle("2026-03-18"), candle("2026-03-19", open="NaN"),
                                   candle("2026-03-20"), candle("2026-03-20", close=51.5)], "US10Y", True)
    assert len(bars) == 1
    assert "2026-03-19" in issues[0] and "2026-03-20" in issues[0]
    assert bars[0]["volume"] == 0
    assert datetime.fromtimestamp(bars[0]["time"], ET).hour == 0


@pytest.mark.parametrize("day", ["2026-03-06", "2026-03-09", "2026-10-30", "2026-11-02"])
def test_four_hour_index_buckets_keep_overnight_hours_and_dst(day):
    rows = []
    for hour, minute, close in [(3, 15, 16), (3, 45, 17), (8, 15, 18), (14, 45, 19)]:
        stamp = int(datetime.fromisoformat(f"{day}T{hour:02}:{minute:02}").replace(tzinfo=ET).timestamp())
        rows.append({"timestamp": stamp, "open": close, "high": close + 1, "low": close - 1, "close": close})
    bars, _ = normalize_index(rows, "VIX", False)
    result = index_bars(bars, "4h")
    assert [datetime.fromtimestamp(b["time"], ET).hour for b in result] == [0, 8, 12]
    assert result[0]["open"] == 16 and result[0]["close"] == 17
    assert all(b["vwap"] is None and b["volume"] == 0 for b in result)
    assert result[-1]["observed_at"] == rows[-1]["timestamp"]


@pytest.fixture
def index_feed(monkeypatch):
    calls = []
    monkeypatch.setattr(feed_module.tradier, "TRADIER_API_KEY", "fixture")
    monkeypatch.setattr(feed_module.tradier, "TRADIER_BASE_URL", "https://api.tradier.com")
    def get(url, params, **kwargs):
        calls.append((url, params))
        if url.endswith("/history"):
            payload = {"history": {"day": [candle(), candle("2026-03-19", open="NaN")]}}
        elif url.endswith("/timesales"):
            payload = {"series": {"data": [{**candle(), "timestamp": int(datetime(2026, 10, 20, 8, 15, tzinfo=ET).timestamp())}]}}
        elif url.endswith("/quotes"):
            payload = {"quotes": {"quote": {"symbol": "TNX:CGI", "last": 51.46, "prevclose": 51.17, "trade_date": 1234000}}}
        else:
            pytest.fail(f"Stock-only provider path requested: {url}")
        return httpx.Response(200, json=payload, request=httpx.Request("GET", url))
    monkeypatch.setattr(feed_module.httpx, "get", get)
    return ChartFeed(), calls


def test_workspace_uses_shared_cache_no_stock_enrichment_or_stream(index_feed):
    feed, calls = index_feed
    def forbidden(*a, **k):
        pytest.fail("Stock enrichment used for index")
    result = feed.workspace("US10Y", ["4h", "1D"], [], "regular", calendar=object(),
                            stored_session=forbidden, volume_profile=forbidden, extra_levels=forbidden, range_levels=forbidden)
    assert len(calls) == 4
    assert all(params["symbol"] == "TNX:CGI" for url, params in calls if not url.endswith("/quotes"))
    assert next(p for u, p in calls if u.endswith("/timesales"))["session_filter"] == "all"
    assert result["quotes"][0]["trade_time"] == 1234
    assert result["instrument"]["unit"] == "percent"
    assert result["market"]["sessions"] == [] and result["auto_levels"] is None and result["rvol"] is None
    assert result["adjustment"]["basis"] == "index_native"
    assert "2026-03-19" in " ".join(result["issues"])
    again = feed.workspace("US10Y", ["4h", "1D"], [], "extended")
    assert again["panels"] == result["panels"] and len(calls) == 4
    page = feed.indices.page("US10Y", "4h", 9999999999, 100, "regular")
    assert page["exhausted"] and page["continuation"] is None
    assert page["bars"] == result["panels"]["4h"]["bars"] and len(calls) == 4
    with pytest.raises(ChartFeedError):
        feed.indices.page("US10Y", "1m", 9999999999, 100, "regular")


def test_index_cache_failure_keeps_original_observation_and_fetch_time(index_feed, monkeypatch):
    feed, _ = index_feed
    clock = [1000.0]
    monkeypatch.setattr(feed_module.time, "time", lambda: clock[0])
    first = feed.workspace("VIX", ["4h"], [], "extended", quotes=False)
    clock[0] += 61
    def denied(*args, **kwargs):
        return httpx.Response(429, json={}, request=httpx.Request("GET", "https://api.tradier.com/v1/markets/timesales"))
    monkeypatch.setattr(feed_module.httpx, "get", denied)
    retained = feed.workspace("VIX", ["4h"], [], "extended", quotes=False)
    assert retained["panels"] == first["panels"]
    assert retained["intraday_as_of"] == first["intraday_as_of"]
    assert retained["fetched_at"] == first["fetched_at"]
    assert retained["issues"] and "allowance" in " ".join(retained["issues"])


def test_daily_tail_revisions_win_and_conflicts_are_not_repaired(index_feed, monkeypatch):
    feed, _ = index_feed
    def read(path, params, ttl):
        rows = [candle("2026-03-19"), candle("2026-03-20"), candle("2026-03-21"), candle("2026-03-21", close=51.5)] if ttl == 86400 else [candle("2026-03-19", open="NaN"), candle("2026-03-20", close=51.5)]
        return {"history": {"day": rows}}, 123, None
    monkeypatch.setattr(feed, "read", read)
    bars, _, issues = feed.indices.series("US10Y", "1D")
    assert len(bars) == 1 and bars[0]["close"] == pytest.approx(5.15)
    assert "2026-03-19" in " ".join(issues) and "2026-03-21" in " ".join(issues)
