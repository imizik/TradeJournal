"""The opening cache projection is bounded, detached and never fetches."""

from datetime import UTC, datetime, timedelta
from collections import OrderedDict, deque
import socket
import threading
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from fastapi import HTTPException

from app.engine.chart_calendar import ChartCalendar
from app.engine.chart_feed import ChartFeed
from app.engine.opening_cache import (
    OBSERVATION_SCHEMA,
    parse_observation_checkpoint,
    peek_opening_cache,
    peek_opening_observation,
)
from app.routers import charts as charts_router
from app.routers.charts import opening_cache, opening_observation


CHECKPOINT = "2026-10-28T13:35:00Z"  # 09:35 ET
OBSERVED = datetime(2026, 10, 28, 13, 35, 4, tzinfo=UTC)


class Feed:
    def __init__(self, entries=(), busy=False):
        self.entries, self.busy = tuple(entries), busy
        self.peek_calls = 0

    def nonblocking_cache_peek(self):
        self.peek_calls += 1
        return None if self.busy else self.entries


class Calendar:
    def __init__(self, entry=None):
        self.entry = entry
        self.calls = 0

    def nonblocking_peek(self, day):
        self.calls += 1
        return self.entry


def record(path, params, data, fetched_at, base="https://api.tradier.com"):
    key = (base, path, tuple(sorted(params.items())))
    return key, SimpleNamespace(data=data, fetched_at=fetched_at, expires_at=OBSERVED.timestamp() + 60)


def cache_fixture():
    fetched = OBSERVED.timestamp() - 2
    quotes = {"quotes": {"quote": [
        {"symbol": "SPY", "bid": 100.1, "ask": 100.2, "bidsize": 10, "asksize": 11,
         "bid_date": 1_798_000_000, "ask_date": 1_798_000_001, "lot_size": 100, "last": 100.15},
        {"symbol": "QQQ", "bid": 200.1, "ask": 200.2, "bidsize": 20, "asksize": 21,
         "bid_date": 1_798_000_000, "ask_date": 1_798_000_001, "lot_size": 100, "description": "extra"},
        {"symbol": "NVDA", "bid": 10},
    ]}}
    minutes = []
    for minute in range(30, 35):
        stamp = int(datetime(2026, 10, 28, 9, minute, tzinfo=ZoneInfo("America/New_York")).timestamp())
        minutes.append({"timestamp": stamp, "time": stamp, "open": 100, "high": 101, "low": 99,
                        "close": 100.5, "volume": 50, "symbol": "NVDA", "extra": "omit"})
    entries = [record("/v1/markets/quotes", {"symbols": "QQQ,SPY"}, quotes, fetched)]
    for symbol in ("SPY", "QQQ"):
        entries.append(record("/v1/markets/timesales", {"symbol": symbol, "interval": "1min", "session_filter": "all"},
                              {"series": {"data": minutes}}, fetched))
    return entries, quotes, minutes, fetched


def test_cache_projection_is_bounded_detached_and_preserves_received_provenance():
    entries, quote_source, bar_source, fetched = cache_fixture()
    calendar_data = {"date": "2026-10-28", "status": "open", "open": 570, "close": 960,
                     "description": "ignored", "source": "tradier"}
    feed, calendar = Feed(entries), Calendar((datetime(2026, 10, 28).date(), calendar_data))
    # The actual ChartCalendar returns (fetched_on, day); today must match.
    calendar.entry = (datetime(2026, 10, 28).date(), calendar_data)
    result = peek_opening_cache(feed, calendar, CHECKPOINT, now=OBSERVED)

    assert result["status"] == "ok" and result["schema"] == "TRADIER_OPENING_CACHE_V1"
    assert result["checkpoint"] == CHECKPOINT
    assert result["observed_at"] == "2026-10-28T13:35:04.000000Z"
    assert result["provider_requests"] == result["stream_sessions_created"] == 0
    assert set(result["quotes"]) == set(result["bars"]) == {"SPY", "QQQ"}
    assert result["quotes"]["SPY"]["received_at"] == datetime.fromtimestamp(fetched, UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    assert set(result["quotes"]["SPY"]["data"]) == {"symbol", "bid", "ask", "bidsize", "asksize", "bid_date", "ask_date", "lot_size"}
    assert len(result["bars"]["SPY"]["data"]) == 5
    assert all(set(row) <= {"time", "timestamp", "open", "high", "low", "close", "volume"} for row in result["bars"]["SPY"]["data"])
    result["quotes"]["SPY"]["data"]["bid"] = -1
    result["bars"]["SPY"]["data"].clear()
    assert quote_source["quotes"]["quote"][0]["bid"] == 100.1
    assert len(bar_source) == 5 and feed.peek_calls == 1 and calendar.calls == 1


def test_missing_or_busy_cache_returns_unavailable_without_provider_io(monkeypatch):
    entries, _, _, _ = cache_fixture()
    feed = Feed(entries[:0])
    calendar = Calendar()
    network_calls = []
    def forbidden(*args, **kwargs):
        network_calls.append((args, kwargs))
        raise AssertionError("cache-only route attempted network I/O")
    from app.engine import market_http
    monkeypatch.setattr(market_http, "get", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(feed, "read", forbidden, raising=False)
    monkeypatch.setattr(calendar, "hours", forbidden, raising=False)
    result = peek_opening_cache(feed, calendar, CHECKPOINT, now=OBSERVED)
    assert result["status"] == "unavailable" and result["reason"] == "cache_missing"
    busy = peek_opening_cache(Feed(entries, busy=True), calendar, CHECKPOINT, now=OBSERVED)
    assert busy["reason"] == "cache_busy"
    assert calendar.calls == 1 and not network_calls  # calendar is skipped on cache contention


def test_invalid_checkpoint_is_rejected_before_any_cache_peek():
    feed, calendar = Feed(), Calendar()
    with pytest.raises(ValueError, match="invalid_checkpoint"):
        peek_opening_cache(feed, calendar, "2026-10-27T13:35:00Z", now=OBSERVED)
    with pytest.raises(ValueError, match="invalid_checkpoint"):
        peek_opening_cache(feed, calendar, CHECKPOINT, now=datetime(2026, 10, 28, 13, 35, 6, tzinfo=UTC))
    assert feed.peek_calls == calendar.calls == 0


def test_newest_bad_quote_batch_does_not_fall_back_to_an_older_good_batch():
    entries, _, _, fetched = cache_fixture()
    newer = record("/v1/markets/quotes", {"symbols": "QQQ,SPY"}, {"quotes": {"quote": []}}, fetched + 1)
    feed = Feed([*entries, newer])
    result = peek_opening_cache(feed, Calendar((datetime(2026, 10, 28).date(), {
        "date": "2026-10-28", "status": "open", "open": 570, "close": 960, "source": "tradier",
    })), CHECKPOINT, now=OBSERVED)
    assert result["status"] == "unavailable" and result["quotes"] == {}


def test_nonproduction_cache_sources_are_ignored():
    entries, _, _, _ = cache_fixture()
    entries = [(key[:0] + ("https://sandbox.tradier.com", *key[1:]), value) for key, value in entries]
    result = peek_opening_cache(Feed(entries), Calendar(), CHECKPOINT, now=OBSERVED)
    assert result["status"] == "unavailable" and result["quotes"] == result["bars"] == {}


@pytest.mark.parametrize("kind", ["future", "expired"])
def test_newest_invalid_cache_entry_does_not_fall_back_to_older_healthy_data(kind):
    entries, _, _, fetched = cache_fixture()
    if kind == "future":
        newest = record("/v1/markets/quotes", {"symbols": "QQQ,SPY"}, {"quotes": {"quote": []}}, OBSERVED.timestamp() + 1)
    elif kind == "expired":
        newest = record("/v1/markets/quotes", {"symbols": "QQQ,SPY"}, {"quotes": {"quote": []}}, fetched + 1)
        newest[1].expires_at = OBSERVED.timestamp() - 1
    result = peek_opening_cache(Feed([*entries, newest]), Calendar(), CHECKPOINT, now=OBSERVED)
    assert result["status"] == "unavailable" and result["quotes"] == {}


def test_cache_received_before_checkpoint_is_stale():
    entries, _, _, _ = cache_fixture()
    stale_at = datetime(2026, 10, 28, 13, 34, 59, tzinfo=UTC).timestamp()
    for _, cached in entries:
        cached.fetched_at = stale_at
    result = peek_opening_cache(Feed(entries), Calendar(), CHECKPOINT, now=OBSERVED)
    assert result["status"] == "unavailable" and result["quotes"] == result["bars"] == {}


def test_projection_skips_nested_and_oversized_values_and_allows_empty_opening_bars():
    entries, quote_source, bar_source, _ = cache_fixture()
    for _, cached in entries:
        cached.fetched_at = datetime(2026, 10, 28, 13, 30, 2, tzinfo=UTC).timestamp()
        cached.expires_at = datetime(2026, 10, 28, 13, 31, 0, tzinfo=UTC).timestamp()
    quote_source["quotes"]["quote"][0]["bid"] = {"nested": "bad"}
    quote_source["quotes"]["quote"][0]["ask"] = "x" * 1000
    bar_source[0]["open"] = {"nested": 1}
    calendar_data = {"date": "2026-10-28", "status": "open", "open": 570, "close": 960, "source": "tradier"}
    result = peek_opening_cache(Feed(entries), Calendar((datetime(2026, 10, 28).date(), calendar_data)),
                                "2026-10-28T13:30:00Z", now=datetime(2026, 10, 28, 13, 30, 4, tzinfo=UTC))
    assert result["status"] == "ok"
    assert "bid" not in result["quotes"]["SPY"]["data"] and "ask" not in result["quotes"]["SPY"]["data"]
    assert result["bars"]["SPY"]["data"] == []


def test_real_chart_cache_lock_contention_is_immediate_and_does_not_mutate_cache_state():
    entries, _, _, _ = cache_fixture()
    feed = ChartFeed.__new__(ChartFeed)
    feed._lock, feed._cache, feed._calls = threading.RLock(), OrderedDict(entries), deque([1.0])
    before_keys, before_calls = tuple(feed._cache), tuple(feed._calls)
    acquired, release = threading.Event(), threading.Event()
    def hold():
        with feed._lock:
            acquired.set()
            release.wait(2)
    thread = threading.Thread(target=hold)
    thread.start()
    try:
        assert acquired.wait(1)
        result = peek_opening_cache(feed, Calendar(), CHECKPOINT, now=OBSERVED)
        assert result["reason"] == "cache_busy"
        assert tuple(feed._cache) == before_keys and tuple(feed._calls) == before_calls
    finally:
        release.set()
        thread.join(2)
    assert not thread.is_alive()


def test_real_calendar_lock_contention_is_immediate_and_unavailable():
    entries, _, _, _ = cache_fixture()
    calendar = ChartCalendar.__new__(ChartCalendar)
    calendar._lock, calendar._months = threading.Lock(), {}
    acquired, release = threading.Event(), threading.Event()
    def hold():
        with calendar._lock:
            acquired.set()
            release.wait(2)
    thread = threading.Thread(target=hold)
    thread.start()
    try:
        assert acquired.wait(1)
        result = peek_opening_cache(Feed(entries), calendar, CHECKPOINT, now=OBSERVED)
        assert result["status"] == "unavailable" and result["reason"] == "calendar_unavailable"
    finally:
        release.set()
        thread.join(2)
    assert not thread.is_alive()


def test_route_denies_nonowner_and_missing_authenticated_identity_before_cache_peek(monkeypatch):
    from app.engine.access import Identity

    request = SimpleNamespace(state=SimpleNamespace(access=Identity("reader", "assistant")))
    with pytest.raises(HTTPException) as error:
        opening_cache(request, CHECKPOINT)
    assert error.value.status_code == 403
    monkeypatch.setattr(charts_router.access, "enabled", lambda: True)
    request = SimpleNamespace(state=SimpleNamespace())
    with pytest.raises(HTTPException) as missing:
        opening_cache(request, CHECKPOINT)
    assert missing.value.status_code == 403


def observation_time(local, seconds=4):
    stamp = local.replace(tzinfo=ZoneInfo("America/New_York")).astimezone(UTC)
    return stamp.strftime("%Y-%m-%dT%H:%M:%SZ"), stamp + timedelta(seconds=seconds)


def test_minute_observation_projects_only_quote_allowlist_without_refresh_or_lru_mutation(
    monkeypatch,
):
    entries, source, _, fetched = cache_fixture()
    feed = ChartFeed.__new__(ChartFeed)
    feed._lock, feed._cache, feed._calls = threading.RLock(), OrderedDict(entries), deque([1.0])
    original = (tuple(feed._cache.items()), tuple(feed._calls))
    from app.engine import market_http

    monkeypatch.setattr(
        market_http,
        "get",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("network")),
    )
    monkeypatch.setattr(
        feed,
        "read",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("provider refresh")),
        raising=False,
    )
    checkpoint, observed = observation_time(datetime(2026, 10, 28, 9, 35))
    result = peek_opening_observation(feed, checkpoint, now=observed)
    assert result["status"] == "ok" and result["schema"] == OBSERVATION_SCHEMA
    assert result["provider_requests"] == result["stream_sessions_created"] == 0
    assert set(result) == {
        "schema",
        "checkpoint",
        "observed_at",
        "status",
        "reason",
        "quotes",
        "provider_requests",
        "stream_sessions_created",
    }
    assert set(result["quotes"]) == {"SPY", "QQQ"}
    assert set(result["quotes"]["SPY"]["data"]) == {
        "symbol",
        "bid",
        "ask",
        "bidsize",
        "asksize",
        "bid_date",
        "ask_date",
        "lot_size",
    }
    assert result["quotes"]["SPY"]["received_at"] == datetime.fromtimestamp(
        fetched, UTC
    ).isoformat(timespec="microseconds").replace("+00:00", "Z")
    assert source["quotes"]["quote"][0]["bid"] == result["quotes"]["SPY"]["data"]["bid"]
    assert (tuple(feed._cache.items()), tuple(feed._calls)) == original


def test_minute_observation_requires_both_quotes_and_never_falls_back_to_older_batch():
    entries, _, _, fetched = cache_fixture()
    checkpoint, observed = observation_time(datetime(2026, 10, 28, 9, 35))
    result = peek_opening_observation(Feed(entries[:0]), checkpoint, now=observed)
    assert result["status"] == "unavailable" and result["reason"] == "cache_missing"
    broken = record(
        "/v1/markets/quotes",
        {"symbols": "QQQ,SPY"},
        {"quotes": {"quote": []}},
        fetched + 1,
    )
    result = peek_opening_observation(
        Feed([*entries, broken]), checkpoint, now=observed
    )
    assert result["status"] == "unavailable" and result["quotes"] == {}


def test_minute_observation_keeps_bad_side_timestamps_for_downstream_causal_rejection():
    entries, quote_source, _, _ = cache_fixture()
    checkpoint, observed = observation_time(datetime(2026, 10, 28, 9, 35))
    quote_source["quotes"]["quote"][0]["bid_date"] = int(
        (observed - timedelta(seconds=1)).timestamp()
    )
    quote_source["quotes"]["quote"][1]["ask_date"] = int(
        (observed + timedelta(seconds=1)).timestamp()
    )
    result = peek_opening_observation(Feed(entries), checkpoint, now=observed)
    assert result["status"] == "ok"
    assert (
        result["quotes"]["SPY"]["data"]["bid_date"]
        == quote_source["quotes"]["quote"][0]["bid_date"]
    )
    assert (
        result["quotes"]["QQQ"]["data"]["ask_date"]
        == quote_source["quotes"]["quote"][1]["ask_date"]
    )


def test_minute_observation_validates_per_minute_window_same_day_and_dst_before_peek():
    feed = Feed()
    for local in (
        datetime(2026, 10, 28, 9, 29),
        datetime(2026, 10, 28, 10, 17),
        datetime(2026, 10, 28, 9, 35, 1),
    ):
        checkpoint, observed = observation_time(local)
        with pytest.raises(ValueError, match="invalid_checkpoint"):
            peek_opening_observation(feed, checkpoint, now=observed)
    checkpoint, observed = observation_time(datetime(2026, 10, 28, 9, 35))
    with pytest.raises(ValueError, match="invalid_checkpoint"):
        peek_opening_observation(feed, checkpoint, now=observed + timedelta(seconds=2))
    dst_checkpoint, dst_now = observation_time(datetime(2026, 11, 2, 9, 30))
    assert (
        parse_observation_checkpoint(dst_checkpoint, dst_now)
        .astimezone(ZoneInfo("America/New_York"))
        .hour
        == 9
    )
    with pytest.raises(ValueError, match="invalid_checkpoint"):
        parse_observation_checkpoint(dst_checkpoint, observed)
    assert feed.peek_calls == 0


def test_minute_observation_cache_contention_is_nonblocking_and_does_not_touch_calendar():
    entries, _, _, _ = cache_fixture()
    feed = ChartFeed.__new__(ChartFeed)
    feed._lock, feed._cache, feed._calls = (
        threading.RLock(),
        OrderedDict(entries),
        deque([1.0]),
    )
    before = (tuple(feed._cache), tuple(feed._calls))
    acquired, release = threading.Event(), threading.Event()

    def hold():
        with feed._lock:
            acquired.set()
            release.wait(2)

    thread = threading.Thread(target=hold)
    thread.start()
    try:
        assert acquired.wait(1)
        checkpoint, observed = observation_time(datetime(2026, 10, 28, 9, 35))
        result = peek_opening_observation(feed, checkpoint, now=observed)
        assert result["reason"] == "cache_busy"
        assert before == (tuple(feed._cache), tuple(feed._calls))
    finally:
        release.set()
        thread.join(2)
    assert not thread.is_alive()


def test_minute_observation_owner_denial_precedes_cache_peek(monkeypatch):
    from app.engine.access import Identity

    request = SimpleNamespace(
        state=SimpleNamespace(access=Identity("reader", "assistant"))
    )
    peeks = []
    monkeypatch.setattr(
        charts_router, "peek_opening_observation", lambda *a, **k: peeks.append((a, k))
    )
    with pytest.raises(HTTPException) as error:
        opening_observation(request, CHECKPOINT)
    assert error.value.status_code == 403
    assert peeks == []
    from app.access_manifest import DOMAIN_ROUTES

    assert "GET /charts/research/opening-observation" in DOMAIN_ROUTES


def test_minute_observation_owner_can_read_without_provider_or_calendar(monkeypatch):
    entries, _, _, _ = cache_fixture()
    from app.engine.access import Identity

    feed = ChartFeed.__new__(ChartFeed)
    feed._lock, feed._cache, feed._calls = threading.RLock(), OrderedDict(entries), deque([1.0])
    monkeypatch.setattr(charts_router, "chart_feed", feed)
    checkpoint, observed = observation_time(datetime(2026, 10, 28, 9, 35))
    monkeypatch.setattr(
        charts_router,
        "peek_opening_observation",
        lambda existing_feed, stamp: peek_opening_observation(
            existing_feed, stamp, now=observed
        ),
    )
    request = SimpleNamespace(
        state=SimpleNamespace(access=Identity("owner", "owner", owner=True))
    )
    result = opening_observation(request, checkpoint)
    assert result["status"] == "ok"
    assert set(result["quotes"]) == {"SPY", "QQQ"}
