"""Tests for chart_fallback.workspace_or_fallback and its wired callers."""

from datetime import datetime, time as wall_time, timedelta

import pytest

from app.ai import copilot_book, copilot_moment
from app.engine import alpaca, chart_fallback, chart_splits, desk_context, ping_images, setup_record
from app.engine.chart_calendar import chart_calendar
from app.engine.chart_feed import ChartFeedError, chart_feed
from app.engine.chart_math import ET
from app.engine.chart_splits import UNAVAILABLE


def _bar(stamp: int, close: float = 100.0, *, source: str = "tradier", extended: bool = False) -> dict:
    return {
        "time": stamp,
        "end_time": stamp + 60,
        "open": close,
        "high": close + 1,
        "low": close - 1,
        "close": close,
        "volume": 100,
        "source": source,
        "extended": extended,
    }


def test_workspace_or_fallback_returns_primary_when_no_issues(monkeypatch):
    seen = []
    primary = {
        "symbol": "SPY",
        "provider": "Tradier",
        "delayed": False,
        "panels": {"5m": {"bars": [_bar(1790693820)], "markers": []}},
        "issues": [],
    }

    def fake_primary(symbol, frames, watchlist, session, *, calendar, quotes=True, **kwargs):
        seen.append((symbol, frames, watchlist, session, calendar, quotes, kwargs))
        return primary

    monkeypatch.setattr(alpaca, "alpaca_configured", lambda: True)
    monkeypatch.setattr(chart_feed, "workspace", fake_primary)
    monkeypatch.setattr(chart_fallback, "workspace", lambda *a, **k: pytest.fail("fallback must not run when primary has no issues"))

    got = chart_fallback.workspace_or_fallback(
        "SPY", ["5m"], ["QQQ"], "extended", calendar=chart_calendar, quotes=False, auto=False
    )
    assert got is primary
    assert seen == [("SPY", ["5m"], ["QQQ"], "extended", chart_calendar, False, {"auto": False})]


def test_workspace_or_fallback_returns_fallback_when_primary_raises_and_alpaca_configured(monkeypatch):
    fallback_calls = []
    fallback = {
        "symbol": "SPY",
        "provider": chart_fallback.PROVIDER,
        "delayed": True,
        "panels": {"5m": {"bars": [_bar(1790693820, source=chart_fallback.SOURCE)], "markers": []}},
        "issues": [],
    }

    def raise_primary(*args, **kwargs):
        raise ChartFeedError("Tradier refused access.", "access_denied")

    def fake_fallback(symbol, frames, watchlist, session, *, calendar, quotes=True):
        fallback_calls.append((symbol, frames, watchlist, session, calendar, quotes))
        return fallback

    monkeypatch.setattr(alpaca, "alpaca_configured", lambda: True)
    monkeypatch.setattr(chart_feed, "workspace", raise_primary)
    monkeypatch.setattr(chart_fallback, "workspace", fake_fallback)

    got = chart_fallback.workspace_or_fallback(
        "SPY", ["5m"], ["QQQ"], "extended", calendar=chart_calendar, quotes=True, stored_session=lambda *a: None
    )
    assert got is fallback
    assert fallback_calls == [("SPY", ["5m"], ["QQQ"], "extended", chart_calendar, True)]


def test_workspace_or_fallback_raises_primary_error_when_both_fail(monkeypatch):
    def raise_primary(*args, **kwargs):
        raise ChartFeedError("primary failure", "access_denied")

    def raise_fallback(*args, **kwargs):
        raise ChartFeedError("fallback failure", "provider_unavailable")

    monkeypatch.setattr(alpaca, "alpaca_configured", lambda: True)
    monkeypatch.setattr(chart_feed, "workspace", raise_primary)
    monkeypatch.setattr(chart_fallback, "workspace", raise_fallback)

    with pytest.raises(ChartFeedError, match="primary failure"):
        chart_fallback.workspace_or_fallback("SPY", ["5m"], [], "extended", calendar=chart_calendar)


def test_workspace_or_fallback_raises_primary_error_when_alpaca_not_configured(monkeypatch):
    def raise_primary(*args, **kwargs):
        raise ChartFeedError("Tradier unavailable.", "provider_unavailable")

    monkeypatch.setattr(alpaca, "alpaca_configured", lambda: False)
    monkeypatch.setattr(chart_feed, "workspace", raise_primary)
    monkeypatch.setattr(chart_fallback, "workspace", lambda *a, **k: pytest.fail("fallback must not run when Alpaca is off"))

    with pytest.raises(ChartFeedError, match="Tradier unavailable."):
        chart_fallback.workspace_or_fallback("SPY", ["5m"], [], "extended", calendar=chart_calendar)


@pytest.mark.parametrize("symbol", ["VIX", "US10Y"])
def test_workspace_or_fallback_never_falls_back_for_index_symbols(monkeypatch, symbol):
    monkeypatch.setattr(alpaca, "alpaca_configured", lambda: True)
    monkeypatch.setattr(chart_fallback, "workspace", lambda *a, **k: pytest.fail("index symbols must never fall back"))

    def raise_primary(*args, **kwargs):
        raise ChartFeedError("Tradier down.")

    monkeypatch.setattr(chart_feed, "workspace", raise_primary)
    with pytest.raises(ChartFeedError, match="Tradier down."):
        chart_fallback.workspace_or_fallback(symbol, ["1D"], [], "extended", calendar=chart_calendar)

    primary = {"symbol": symbol, "panels": {"1D": {"bars": [], "markers": []}}, "issues": ["stale"]}
    monkeypatch.setattr(chart_feed, "workspace", lambda *a, **k: primary)
    assert chart_fallback.workspace_or_fallback(symbol, ["1D"], [], "extended", calendar=chart_calendar) is primary


def test_desk_context_today_minutes_uses_fallback_when_primary_raises(monkeypatch):
    today = datetime.now(ET).date()
    half_hours = {
        "date": today.isoformat(),
        "status": "open",
        "open": 570,
        "close": 780,
        "description": "Market closes early at 13:00",
        "source": "tradier",
    }
    calls = []

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.combine(today, wall_time(11), ET).astimezone(tz)

    def denied(*args, **kwargs):
        raise ChartFeedError("Tradier refused access.", "access_denied")

    def read(path, params, ttl):
        calls.append((path, params))
        assert params["timeframe"] == "1Min"
        assert datetime.fromisoformat(params["end"]).time() == wall_time(10, 44)
        assert params["feed"] == "sip"
        assert params["adjustment"] == "raw"
        stamp = datetime.combine(today, wall_time(10, 43), ET)
        return {"symbol": "SPY", "bars": [{"t": stamp.isoformat(), "o": 100, "h": 102, "l": 99, "c": 101, "v": 9}]}, 10, None

    monkeypatch.setattr(alpaca, "alpaca_configured", lambda: True)
    monkeypatch.setattr(chart_feed, "workspace", denied)
    monkeypatch.setattr(chart_feed.splits, "get", lambda symbol: UNAVAILABLE)
    monkeypatch.setattr(chart_calendar, "hours", lambda day: half_hours)
    monkeypatch.setattr(chart_fallback, "datetime", Clock)
    monkeypatch.setattr(chart_fallback.feed, "read", read)

    bars = desk_context.today_minutes("SPY")
    assert len(bars) == 1
    assert bars[0]["source"] == chart_fallback.SOURCE
    assert bars[0]["close"] == 101.0
    assert len(calls) == 1


def test_desk_read_marks_delayed_from_shown_bars(monkeypatch):
    day = datetime(2026, 10, 21, 10, 30, tzinfo=ET)
    now = day.timestamp() + 120
    start = int(day.timestamp())

    monkeypatch.setattr(desk_context, "_warm", lambda symbol, timeframe, before: [])
    monkeypatch.setattr(desk_context, "kept_close", lambda symbol, before, today: None)

    monkeypatch.setattr(desk_context, "today_minutes", lambda symbol: [_bar(start, 100.0, source=chart_fallback.SOURCE)])
    delayed_read = desk_context._desk_read("NBIS", "2m", now)
    assert delayed_read is not None and delayed_read["delayed"] is True
    assert "source" not in delayed_read["bars"][0]

    monkeypatch.setattr(desk_context, "today_minutes", lambda symbol: [_bar(start, 100.0, source="tradier")])
    live_read = desk_context._desk_read("NBIS", "2m", now)
    assert live_read is not None and live_read["delayed"] is False


def test_copilot_book_chart_context_includes_delayed_and_provider_when_delayed(monkeypatch):
    stamp = 1792700000
    fallback = {
        "symbol": "NBIS",
        "provider": chart_fallback.PROVIDER,
        "delayed": True,
        "session": "extended",
        "intraday_as_of": stamp,
        "checked_at": stamp,
        "market": {"date": "2026-10-23", "status": "open", "description": None},
        "panels": {"5m": {"bars": [_bar(stamp, 95.0, source=chart_fallback.SOURCE)]}},
        "quotes": [],
        "issues": [],
    }
    monkeypatch.setattr(alpaca, "alpaca_configured", lambda: True)
    monkeypatch.setattr(chart_feed, "workspace", lambda *a, **k: (_ for _ in ()).throw(ChartFeedError("Tradier down.")))
    monkeypatch.setattr(chart_fallback, "workspace", lambda *a, **k: fallback)

    delayed_out = copilot_book.chart_context("NBIS", "5m")
    assert delayed_out["state"] == "ok"
    assert delayed_out["delayed"] is True
    assert delayed_out["provider"] == chart_fallback.PROVIDER

    primary = {**fallback, "provider": "Tradier", "delayed": False, "panels": {"5m": {"bars": [_bar(stamp, 95.0)]}}}
    monkeypatch.setattr(chart_feed, "workspace", lambda *a, **k: primary)
    live_out = copilot_book.chart_context("NBIS", "5m")
    assert live_out["delayed"] is False
    assert "provider" not in live_out


def test_other_wired_readers_fall_back_when_primary_raises(monkeypatch):
    day = datetime(2026, 10, 23, 10, 30, tzinfo=ET)
    daily_stamp = int(datetime.combine(day.date(), wall_time(9, 30), ET).timestamp())
    prev_stamp = int(datetime.combine(day.date() - timedelta(days=1), wall_time(9, 30), ET).timestamp())
    minute_bar = _bar(int(day.timestamp()), 101.0, source=chart_fallback.SOURCE)
    daily_bars = [_bar(prev_stamp, 99.0, source=chart_fallback.SOURCE), _bar(daily_stamp, 101.0, source=chart_fallback.SOURCE)]

    def fake_fallback(symbol, frames, watchlist, session, *, calendar, quotes=True):
        bars = daily_bars if "1D" in frames else [minute_bar]
        return {"symbol": symbol, "provider": chart_fallback.PROVIDER, "delayed": True,
                "panels": {frame: {"bars": bars, "markers": []} for frame in frames}, "issues": [], "checked_at": int(day.timestamp())}

    monkeypatch.setattr(alpaca, "alpaca_configured", lambda: True)
    monkeypatch.setattr(chart_feed, "workspace", lambda *a, **k: (_ for _ in ()).throw(ChartFeedError("Tradier down.")))
    monkeypatch.setattr(chart_fallback, "workspace", fake_fallback)
    monkeypatch.setattr(chart_splits.chart_splits, "get", lambda symbol: {"splits": []})
    monkeypatch.setattr(chart_calendar, "hours", lambda d: None)

    # Ping pictures, position alerts, day replay and the brief scorecard read today_bars as live: they stay on the
    # regular feed only, so a Tradier outage leaves them empty rather than about 15 minutes stale.
    with pytest.raises(ChartFeedError):
        ping_images.today_bars("NBIS")
    assert setup_record._daily_bars("NBIS") == daily_bars
    moment = copilot_moment.live_chart("NBIS", day, "1D", now=day)
    assert moment["state"] == "ok" and moment["bar"]["c"] == 101.0
