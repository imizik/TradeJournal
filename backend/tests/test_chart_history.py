"""Chart-only SIP session, paging, and indicator acceptance fixtures."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time as wall_time, timedelta, timezone
import threading

import httpx
import pytest

from app.engine import alpaca, chart_history as module
from app.engine.chart_history import ChartHistory, HistoryError, Work
from app.engine.chart_math import CLOCK_NOTE, ET, chart_bars, normalize_bars


def previous_weekday() -> date:
    day = datetime.now(ET).date() - timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


def completed_session_cursor(day: date, now: datetime | None = None) -> int:
    # Keep yesterday as the first history session while avoiding a future
    # next-day 04:00 cursor during New York's midnight-to-04:00 window.
    next_morning = datetime.combine(day + timedelta(days=1), wall_time(4), ET)
    return int(min(next_morning, now or datetime.now(ET)).timestamp())


@pytest.mark.parametrize("hour, minute", [(0, 1), (3, 59), (4, 1)])
def test_completed_session_cursor_is_past_at_new_york_midnight(hour: int, minute: int):
    day = date(2026, 9, 30)
    now = datetime(2026, 10, 1, hour, minute, tzinfo=ET)
    cursor = completed_session_cursor(day, now)
    assert datetime.combine(day, wall_time(20), ET).timestamp() < cursor <= now.timestamp()


def raw(day: date, hour: int, minute: int, price: float = 100.0) -> dict:
    stamp = datetime.combine(day, wall_time(hour, minute), ET).astimezone(timezone.utc)
    return {"t": stamp.isoformat(), "o": price, "h": price + 1, "l": price - 1, "c": price, "v": 10}


def normalized(day: date, hour: int, minute: int, price: float = 100.0) -> dict:
    item = raw(day, hour, minute, price)
    stamp = int(datetime.fromisoformat(item["t"]).timestamp())
    return normalize_bars([{"timestamp": stamp, "open": item["o"], "high": item["h"], "low": item["l"], "close": item["c"], "volume": item["v"]}], source="alpaca_sip")[0]


@pytest.fixture
def history(tmp_path, monkeypatch):
    monkeypatch.setattr(alpaca, "ALPACA_API_KEY", "fixture-key")
    monkeypatch.setattr(alpaca, "ALPACA_API_SECRET", "fixture-secret")
    monkeypatch.setattr(alpaca, "ALPACA_DATA_FEED", "iex")
    return ChartHistory(tmp_path)


def test_every_initial_page_and_retry_request_is_sip_raw_and_safe(history, monkeypatch):
    day = previous_weekday()
    before = completed_session_cursor(day)
    monkeypatch.setattr(module, "WARMUP", 0)
    calls = []
    replies = [(200, {"bars": [raw(day, 4, 0)], "next_page_token": "next"}),
               (429, {}),
               (200, {"bars": [raw(day, 4, 0)], "next_page_token": "next"}),
               (200, {"bars": [raw(day, 9, 30), raw(day, 20, 0)], "next_page_token": None})]

    def get(url, *, params, headers, timeout):
        calls.append(dict(params))
        status, payload = replies.pop(0)
        return httpx.Response(status, json=payload, headers={"Retry-After": "1"}, request=httpx.Request("GET", url))

    monkeypatch.setattr(module.httpx, "get", get)
    first = history.page("SPY", "1m", "extended", before, limit=2)
    assert first["issue"]["code"] == "rate_limited" and first["continuation"]
    assert not history._path("SPY", day).exists()  # incomplete candidate was never published
    history._cooldown = 0
    second = history.page("SPY", "1m", "extended", before, limit=2, continuation=first["continuation"])
    assert second["warmup"] == "ready" and [b["source"] for b in second["bars"]] == ["alpaca_sip"] * 2
    assert [b["time"] for b in second["bars"]] == [normalized(day, 4, 0)["time"], normalized(day, 9, 30)["time"]]
    assert [c.get("page_token") for c in calls] == [None, "next", None, "next"]
    for params in calls:
        assert params["feed"] == "sip" and params["adjustment"] == "raw" and params["timeframe"] == "1Min"
        assert datetime.fromisoformat(params["end"]) <= datetime.now(timezone.utc) - timedelta(minutes=15)
    assert alpaca.ALPACA_DATA_FEED == "iex"
    assert history._cached("SPY", day) == [normalized(day, 4, 0), normalized(day, 9, 30)]
    restarted = ChartHistory(history.root)
    assert restarted._cached("SPY", day) == history._cached("SPY", day)
    assert len(calls) == 4  # validated completed session costs zero requests


def test_symbol_is_one_cache_and_url_segment_and_current_session_is_rejected(history, monkeypatch):
    day = previous_weekday()
    symbol = "BRK/B"
    path = history._path(symbol, day)
    assert path.parent == history.root / "BRK%2FB"
    assert history._path("A/../../B", day).parent == history.root / "A%2F..%2F..%2FB"
    calls = []

    def get(url, **kwargs):
        calls.append(url)
        return httpx.Response(200, json={"bars": [], "next_page_token": None}, request=httpx.Request("GET", url))

    monkeypatch.setattr(module.httpx, "get", get)
    history._session(symbol, day, Work((symbol, "1m", "regular", 1, 1), day), module.time.monotonic() + 10, [0])
    assert calls[0].endswith("/BRK%2FB/bars")

    _, end = history._bounds(day)
    just_closed = end + timedelta(minutes=14)

    class JustClosed(datetime):
        @classmethod
        def now(cls, tz=None):
            return just_closed.astimezone(tz)

    monkeypatch.setattr(module, "datetime", JustClosed)
    with pytest.raises(HistoryError) as recent:
        history._attempt("SPY", day, None, module.time.monotonic() + 10, [0])
    assert recent.value.code == "invalid_request"
    assert len(calls) == 1


def test_empty_success_corruption_and_malformed_are_distinct(history, monkeypatch):
    day = previous_weekday()
    work = Work(("SPY", "1m", "regular", 1, 1), day)
    monkeypatch.setattr(module.httpx, "get", lambda url, **kw: httpx.Response(200, json={"bars": [], "next_page_token": None}, request=httpx.Request("GET", url)))
    assert history._session("SPY", day, work, module.time.monotonic() + 10, [0]) == []
    assert history._cached("SPY", day) == []
    path = history._path("SPY", day)
    path.write_text("not json")
    with pytest.raises(HistoryError) as corrupt:
        history._cached("SPY", day)
    assert corrupt.value.code == "cache_invalid"
    path.unlink()
    monkeypatch.setattr(module.httpx, "get", lambda url, **kw: httpx.Response(200, json={"unexpected": []}, request=httpx.Request("GET", url)))
    with pytest.raises(HistoryError) as malformed:
        history._session("SPY", day, Work(work.identity, day), module.time.monotonic() + 10, [0])
    assert malformed.value.code == "malformed" and not path.exists()


def test_simultaneous_miss_coalesces_and_continuation_is_bound(history, monkeypatch):
    day = previous_weekday()
    before = completed_session_cursor(day)
    monkeypatch.setattr(module, "WARMUP", 0)
    calls = []

    def get(url, **kw):
        calls.append(kw["params"])
        return httpx.Response(200, json={"bars": [raw(day, 9, 30)], "next_page_token": None}, request=httpx.Request("GET", url))

    monkeypatch.setattr(module.httpx, "get", get)
    with ThreadPoolExecutor(max_workers=2) as pool:
        pages = list(pool.map(lambda _: history.page("SPY", "1m", "regular", before, limit=1), range(2)))
    assert len(calls) == 1
    assert pages[0]["bars"] == pages[1]["bars"]
    with pytest.raises(HistoryError) as invalid:
        history.page("QQQ", "1m", "regular", before, limit=1, continuation="arbitrary")
    assert invalid.value.code == "invalid_request"


def test_page_reference_uses_1400_requested_interval_candles(history, monkeypatch):
    last_day = previous_weekday()
    before = completed_session_cursor(last_day)
    sessions = {}
    # Two completed 4h buckets per weekday; the oldest reference bars extend
    # well beyond the 1,400-candle prefix used by a returned page.
    for offset in range(1200):
        day = last_day - timedelta(days=offset)
        if day.weekday() >= 5:
            continue
        price = 80 + offset * 0.013 + (offset % 17) * 0.04
        sessions[day] = [normalized(day, 9, 30, price), normalized(day, 13, 30, price + 0.3)]

    def session(symbol, day, work, deadline, attempts):
        return sessions.get(day, [])

    monkeypatch.setattr(history, "_session", session)
    all_minutes = [bar for day in sorted(sessions) for bar in sessions[day]]
    for interval in ("1m", "5m", "1h", "4h"):
        result = history.page("SPY", interval, "regular", before, limit=5)
        assert result["warmup"] == "ready", interval
        reference = {b["time"]: b for b in chart_bars(all_minutes, [], interval, "regular")}
        overlap = history.page("SPY", interval, "regular", result["bars"][2]["time"] + 1, limit=5)
        shared = {b["time"]: b for b in result["bars"] if b["time"] in {x["time"] for x in overlap["bars"]}}
        assert shared
        for bar in result["bars"] + overlap["bars"]:
            expected = reference[bar["time"]]
            assert bar["vwap"] == pytest.approx(expected["vwap"], abs=1e-8)
            for field in ("ema9", "ema20", "ema50", "ema200"):
                assert bar[field] == pytest.approx(expected[field], abs=max(1e-4, expected["close"] * 1e-6))
            assert bar["rsi"] == pytest.approx(expected["rsi"], abs=0.001)
            if bar["time"] in shared:
                assert bar["ema200"] == pytest.approx(shared[bar["time"]]["ema200"], abs=1e-4)


def test_mid_bucket_page_uses_complete_session_and_insufficient_warmup_is_explicit(history, monkeypatch):
    day = previous_weekday()
    minutes = [normalized(day, 9, 30 + i, 100 + i) for i in range(5)]
    history._publish("SPY", day, minutes)
    monkeypatch.setattr(module, "WARMUP", 0)
    before = int(datetime.combine(day, wall_time(9, 33), ET).timestamp())
    page = history.page("SPY", "5m", "regular", before, limit=1)
    whole = chart_bars(minutes, [], "5m", "regular")[0]
    assert page["bars"][0]["close"] == whole["close"] == 104
    assert page["bars"][0]["vwap"] == pytest.approx(whole["vwap"])
    monkeypatch.setattr(module, "WARMUP", 1400)
    monkeypatch.setattr(history, "_session", lambda *args: [])
    before_floor = int(datetime.combine(module.FLOOR, wall_time(9, 30), ET).timestamp())
    result = history.page("SPY", "1m", "regular", before_floor, limit=5)
    assert result["exhausted"] and result["warmup"] == "insufficient"
    assert result["bars"] == []


def test_history_wait_does_not_hold_tradier_lock(history, monkeypatch):
    """A blocked SIP request leaves Tradier's independent polling path usable."""
    from app.engine.chart_feed import ChartFeed
    from app.engine import tradier

    day = previous_weekday()
    before = completed_session_cursor(day)
    entered, release = threading.Event(), threading.Event()
    monkeypatch.setattr(module, "WARMUP", 0)
    monkeypatch.setattr(tradier, "TRADIER_API_KEY", "fixture")
    monkeypatch.setattr(tradier, "TRADIER_BASE_URL", "https://tradier.invalid")

    def get(url, **kw):
        if "alpaca" in url:
            entered.set()
            assert release.wait(3)
            return httpx.Response(200, json={"bars": [raw(day, 9, 30)], "next_page_token": None}, request=httpx.Request("GET", url))
        return httpx.Response(200, json={"quotes": {"quote": []}}, request=httpx.Request("GET", url))

    monkeypatch.setattr(module.httpx, "get", get)
    with ThreadPoolExecutor(max_workers=2) as pool:
        future = pool.submit(history.page, "SPY", "1m", "regular", before, 1)
        assert entered.wait(2)
        data, _, _ = pool.submit(ChartFeed().read, "/v1/markets/quotes", {"symbols": "SPY"}, 15).result(timeout=1)
        assert data == {"quotes": {"quote": []}}
        release.set()
        assert future.result(timeout=3)["bars"]


def test_eight_attempt_batch_resumes_paginated_session_without_partial_file(history, monkeypatch):
    day = previous_weekday()
    before = completed_session_cursor(day)
    monkeypatch.setattr(module, "WARMUP", 0)
    calls = []

    def get(url, *, params, **kw):
        calls.append(dict(params))
        number = int(params.get("page_token", "0")) + 1
        return httpx.Response(200, json={"bars": [raw(day, 9, 30)] if number == 10 else [],
                                          "next_page_token": str(number) if number < 10 else None},
                              request=httpx.Request("GET", url))

    monkeypatch.setattr(module.httpx, "get", get)
    first = history.page("SPY", "1m", "regular", before, limit=1)
    assert first["issue"]["code"] == "pending" and first["continuation"]
    assert len(calls) == 8 and not history._path("SPY", day).exists()
    second = history.page("SPY", "1m", "regular", before, limit=1, continuation=first["continuation"])
    assert len(calls) == 10 and len(second["bars"]) == 1 and second["continuation"] is None
    assert history._cached("SPY", day) == [normalized(day, 9, 30)]
    assert all(call["feed"] == "sip" and call["adjustment"] == "raw" for call in calls)


def test_rolling_budget_counts_actual_http_attempts(history, monkeypatch):
    day = previous_weekday()
    calls = []

    def get(url, **kw):
        calls.append(kw["params"])
        return httpx.Response(200, json={"bars": [], "next_page_token": None}, request=httpx.Request("GET", url))

    monkeypatch.setattr(module.httpx, "get", get)
    for _ in range(30):
        history._attempt("SPY", day, None, module.time.monotonic() + 10, [0])
    with pytest.raises(HistoryError) as capped:
        history._attempt("SPY", day, None, module.time.monotonic() + 10, [0])
    assert capped.value.code == "rate_limited" and capped.value.retry_at
    assert len(calls) == 30


def test_two_sip_days_stitch_with_tradier_today_without_overlap(history, monkeypatch):
    latest = previous_weekday()
    earlier = latest - timedelta(days=1)
    while earlier.weekday() >= 5:
        earlier -= timedelta(days=1)
    before = completed_session_cursor(latest)
    monkeypatch.setattr(module, "WARMUP", 0)
    history._publish("SPY", earlier, [normalized(earlier, 9, 30)])
    history._publish("SPY", latest, [normalized(latest, 9, 30)])
    page = history.page("SPY", "1m", "regular", before, limit=2)
    today_day = latest + timedelta(days=1)
    while today_day.weekday() >= 5:
        today_day += timedelta(days=1)
    today_start = int(datetime.combine(today_day, wall_time(9, 30), ET).timestamp())
    today = normalize_bars([{"timestamp": today_start, "open": 101, "high": 102,
                             "low": 100, "close": 101, "volume": 12}], source="tradier")
    stitched = chart_bars(page["bars"] + today, [], "1m", "regular")
    assert len(stitched) == 3
    assert [b["source"] for b in stitched] == ["alpaca_sip", "alpaca_sip", "tradier"]
    assert len({b["time"] for b in stitched}) == 3
    assert [b["time"] for b in stitched] == sorted(b["time"] for b in stitched)
    assert page["older_cursor"] == stitched[0]["time"]


class Calendar:
    """Normalized calendar days by date; anything missing is unavailable."""

    def __init__(self, days: dict[date, dict]):
        self.days, self.asked = days, []

    def hours(self, day: date) -> dict | None:
        self.asked.append(day)
        return self.days.get(day)


def open_day(day: date, close: int = 960) -> dict:
    return {"date": day.isoformat(), "status": "open", "open": 570, "close": close, "description": "", "source": "tradier"}


def test_holidays_cost_no_alpaca_request_and_half_days_end_at_13_00(history, monkeypatch):
    half = previous_weekday()
    holiday = half - timedelta(days=1)
    while holiday.weekday() >= 5:
        holiday -= timedelta(days=1)
    earlier = holiday - timedelta(days=1)
    while earlier.weekday() >= 5:
        earlier -= timedelta(days=1)
    history.calendar = Calendar({half: open_day(half, 780), earlier: open_day(earlier),
                                 holiday: {"date": holiday.isoformat(), "status": "closed", "open": None, "close": None, "description": "Holiday", "source": "tradier"}})
    monkeypatch.setattr(module, "WARMUP", 0)
    requested = []

    def get(url, *, params, headers, timeout):
        day = datetime.fromisoformat(params["start"]).astimezone(ET).date()
        requested.append(day)
        bars = [raw(day, 9, 30, 100), raw(day, 12, 59, 101), raw(day, 13, 0, 102), raw(day, 15, 59, 103)]
        return httpx.Response(200, json={"bars": bars, "next_page_token": None}, request=httpx.Request("GET", url))

    monkeypatch.setattr(module.httpx, "get", get)
    before = completed_session_cursor(half)
    page = history.page("SPY", "1h", "regular", before, limit=5)
    assert holiday not in requested and requested[:2] == [half, earlier]
    by_day = {}
    for bar in page["bars"]:
        by_day.setdefault(datetime.fromtimestamp(bar["time"], ET).date(), []).append(bar)
    assert [datetime.fromtimestamp(b["end_time"], ET).strftime("%H:%M") for b in by_day[half]] == ["10:30", "13:00"]
    assert by_day[half][-1]["close"] == 101  # 13:00 onward is postmarket on a half day
    assert by_day[earlier][-1]["close"] == 103 and holiday not in by_day
    assert page["calendar_note"] is None
    # The cached minutes are raw; classification happens per page, so the
    # same session resamples correctly in extended mode too.
    extended = history.page("SPY", "1h", "extended", before, limit=5)
    post = [b for b in extended["bars"] if datetime.fromtimestamp(b["time"], ET).date() == half and b["extended"]]
    assert [datetime.fromtimestamp(b["time"], ET).strftime("%H:%M") for b in post] == ["13:00", "15:00"]
    assert len(requested) == 2


def test_sessions_resampled_without_the_calendar_are_disclosed(history, monkeypatch):
    day = previous_weekday()
    history._publish("SPY", day, [normalized(day, 9, 30)])
    monkeypatch.setattr(module, "WARMUP", 0)
    before = completed_session_cursor(day)
    history.calendar = Calendar({})
    page = history.page("SPY", "1m", "regular", before, limit=1)
    assert page["bars"] and page["calendar_note"] == CLOCK_NOTE
    history.calendar = Calendar({day: open_day(day)})
    assert history.page("SPY", "1m", "regular", before, limit=1)["calendar_note"] is None
