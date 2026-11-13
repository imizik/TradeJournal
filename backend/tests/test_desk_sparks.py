"""The desk's book sparklines (app/engine/desk_sparks.py): where each line comes from, what it may be kept for, and that it
never takes more than its share of the chart feed. Every value is invented."""

from __future__ import annotations

from datetime import UTC, datetime
import threading
import time

import httpx

from app.engine import alpaca, desk_sparks, tradier
from app.engine.chart_calendar import chart_calendar
from app.engine.chart_feed import PROVIDER_SLOTS, ChartFeedError, chart_feed
from tests.desk_latency import seed_radar
from tests.test_copilot_desk import desk  # noqa: F401  (the desk app over the shared fixtures)
from tests.test_copilot_plans import engine, quotes  # noqa: F401  (fixtures)
from tests.test_today import clock, marks  # noqa: F401  (fixtures)

OPEN = int(datetime(2026, 10, 21, 13, 30, tzinfo=UTC).timestamp())  # 9:30 New York; the clock reads 14:49
HOURS = {"status": "open", "open": 570, "close": 960}


def minute(at: float, close: float) -> dict:
    return {"time": int(at), "end_time": int(at) + 60, "source": "tradier", "open": close, "high": close, "low": close,
            "close": close, "volume": 10}


def day_of(closes, start: float = OPEN) -> list[dict]:
    return [minute(start + 60 * i, c) for i, c in enumerate(closes)]


class Providers:
    """What the sparklines asked outside: Tradier minute reads and Alpaca's batched read."""

    def __init__(self):
        self.minutes: dict[str, list[dict] | Exception] = {}
        self.read: list[str] = []
        self.alpaca: list[dict] = []
        self.alpaca_reply: dict | Exception = {}


def sparks_for(client, *names):
    response = client.get("/copilot/desk/sparks", params={"symbols": ",".join(names)})
    assert response.status_code == 200, response.text
    return response.json()


import pytest  # noqa: E402


@pytest.fixture
def rig(desk, quotes, clock, monkeypatch):  # noqa: F811
    provider = Providers()
    desk_sparks.clear()
    monkeypatch.setattr(chart_calendar, "hours", lambda day: HOURS)
    quotes["rows"] += [{"symbol": "SPY", "last": 580.0, "change_percentage": 0.4}, {"symbol": "MU", "last": 1.0, "change_percentage": -1.2}]

    def today_minutes(symbol, now, max_age=120):
        provider.read.append(symbol)
        found = provider.minutes.get(symbol, [])
        if isinstance(found, Exception):
            raise found
        return found
    monkeypatch.setattr(chart_feed, "today_minutes", today_minutes)
    monkeypatch.setattr(chart_feed, "peek_minutes", lambda symbol, day: None)

    def alpaca_get(path, params):
        provider.alpaca.append(params)
        if isinstance(provider.alpaca_reply, Exception):
            raise provider.alpaca_reply
        return provider.alpaca_reply
    monkeypatch.setattr(alpaca, "_alpaca_get_fast", alpaca_get)
    monkeypatch.setattr(alpaca, "alpaca_configured", lambda: False)
    provider.client, provider.clock, provider.quotes, provider.patch = desk, clock, quotes, monkeypatch
    yield provider
    desk_sparks.clear()


def alpaca_on(rig, bars):
    rig.patch.setattr(alpaca, "alpaca_configured", lambda: True)
    rig.alpaca_reply = {"bars": bars, "next_page_token": None}


def alpaca_bar(at: float, close: float) -> dict:
    return {"t": datetime.fromtimestamp(at, UTC).isoformat().replace("+00:00", "Z"), "o": close, "h": close, "l": close, "c": close, "v": 10}


# ---------------------------------------------------------------------------------------------------- the route


def test_tradier_reads_are_todays_closes_thinned_with_the_change_against_spy(rig):
    rig.minutes["NBIS"] = day_of([90.0 + m / 100 for m in range(200)])
    rig.minutes["MU"] = [minute(OPEN - 30 * 60, 1.0) | {"extended": True}]  # pre-market only: the session has no bars yet
    rig.minutes["BAD"] = ChartFeedError("no feed")
    body = sparks_for(rig.client, "nbis", "MU", "BAD", "../x")
    assert set(body["rows"]) == {"NBIS", "MU"} and body["spy_change_pct"] == 0.4  # BAD unreadable, ../x not a symbol
    nbis = body["rows"]["NBIS"]["points"]
    assert len(nbis) <= desk_sparks.POINTS + 1 and nbis[0] == 90.0 and nbis[-1] == 91.99
    assert body["rows"]["MU"] == {"points": [1.0], "change_pct": -1.2}
    assert sparks_for(rig.client)["rows"] == {}
    rig.minutes["NBIS"] = []  # within the minute the same symbols reuse their lines: nothing is read again
    asked = len(rig.read)
    assert sparks_for(rig.client, "nbis", "MU") == {**body, "rows": {k: body["rows"][k] for k in ("NBIS", "MU")}}
    assert len(rig.read) == asked


def test_a_symbol_with_no_minutes_today_has_no_line(rig):
    rig.minutes["IREN"] = []
    rig.minutes["CIFR"] = [minute(OPEN - 86400 + 60 * i, 5.0 + i) for i in range(30)]  # yesterday's session, nothing today
    body = sparks_for(rig.client, "IREN", "CIFR")
    assert body["rows"]["IREN"]["points"] == [] and body["rows"]["CIFR"]["points"] == []


# ---------------------------------------------------------------------------------------------------- Radar


def test_a_symbol_the_recorder_covers_makes_no_provider_call(rig, tmp_path):
    seed_radar(tmp_path / "radar.sqlite", rig.clock["t"], ("NBIS", "MU", "SPY"), monkeypatch=rig.patch)
    body = sparks_for(rig.client, "NBIS", "MU")
    nbis = body["rows"]["NBIS"]
    assert 2 <= len(nbis["points"]) <= desk_sparks.POINTS + 1 and nbis["points"] == sorted(nbis["points"])
    last = nbis["points"][-1]
    assert nbis["change_pct"] == round((last - 99.0) / 99.0 * 100, 2)
    assert body["spy_change_pct"] == round((last - 99.0) / 99.0 * 100, 2)  # SPY's rows are the same invented climb
    assert rig.read == [] and rig.alpaca == [] and "asked" not in rig.quotes  # no minute read, no batched read, no quote read


def test_only_what_the_recorder_does_not_cover_is_read(rig, tmp_path):
    seed_radar(tmp_path / "radar.sqlite", rig.clock["t"], ("NBIS", "SPY"), monkeypatch=rig.patch)
    rig.minutes["IREN"] = day_of([5.0, 5.1, 5.2])
    body = sparks_for(rig.client, "NBIS", "IREN")
    assert rig.read == ["IREN"] and set(body["rows"]) == {"NBIS", "IREN"}
    assert rig.quotes["asked"] == [["IREN"]]  # SPY and NBIS changes came from the recorder's rows


def test_a_recorder_that_is_late_stale_or_gappy_is_not_the_day_so_far(rig, tmp_path):
    now = rig.clock["t"]
    rig.minutes.update({"NBIS": day_of([90.0, 91.0, 92.0]), "MU": day_of([10.0, 11.0]), "IREN": day_of([5.0, 6.0])})
    seed_radar(tmp_path / "late.sqlite", now, ("NBIS",), since_minute=11 * 60)  # started at 11:00: a late start
    rig.patch.setenv("RADAR_ENABLED", "true")
    rig.patch.setenv("RADAR_STORE", str(tmp_path / "late.sqlite"))
    assert sparks_for(rig.client, "NBIS")["rows"]["NBIS"]["points"] == [90.0, 91.0, 92.0]
    desk_sparks.clear()
    seed_radar(tmp_path / "stale.sqlite", now - 600, ("MU",))  # the newest pass is ten minutes old: the recorder is down
    rig.patch.setenv("RADAR_STORE", str(tmp_path / "stale.sqlite"))
    assert sparks_for(rig.client, "MU")["rows"]["MU"]["points"] == [10.0, 11.0]
    desk_sparks.clear()
    yesterday = tmp_path / "yesterday.sqlite"
    seed_radar(yesterday, now - 86400, ("IREN",))  # yesterday's session only
    rig.patch.setenv("RADAR_STORE", str(yesterday))
    assert sparks_for(rig.client, "IREN")["rows"]["IREN"]["points"] == [5.0, 6.0]
    assert rig.read == ["NBIS", "MU", "IREN"]


def test_a_recorder_with_a_hole_in_the_day_is_not_the_day_so_far(rig, tmp_path):
    now = rig.clock["t"]
    path = tmp_path / "hole.sqlite"
    seed_radar(path, OPEN + 60 * 60, ("NBIS",))  # 9:30 to 10:29
    seed_radar(path, now, ("NBIS",), since_minute=12 * 60)  # then nothing until noon
    rig.patch.setenv("RADAR_ENABLED", "true")
    rig.patch.setenv("RADAR_STORE", str(path))
    rig.minutes["NBIS"] = day_of([90.0, 91.0])
    assert sparks_for(rig.client, "NBIS")["rows"]["NBIS"]["points"] == [90.0, 91.0]


def test_the_recorder_is_not_read_outside_the_regular_session(rig, tmp_path):
    rig.clock["t"] = OPEN - 50 * 60  # 8:40 New York: the pre-market
    seed_radar(tmp_path / "radar.sqlite", OPEN + 60 * 60, ("NBIS",), monkeypatch=rig.patch)
    rig.minutes["NBIS"] = day_of([90.0, 91.0], OPEN - 3600)
    assert sparks_for(rig.client, "NBIS")["rows"]["NBIS"]["points"] == [90.0, 91.0] and rig.read == ["NBIS"]


# ---------------------------------------------------------------------------------------------------- the chart feed's cache


def test_a_chart_just_drawn_serves_the_line_without_a_call(rig):
    held = {"NBIS": (day_of([90.0, 91.0, 92.0]), time.time() - 30), "MU": (day_of([1.0, 2.0]), time.time() - 600)}
    rig.patch.setattr(chart_feed, "peek_minutes", lambda symbol, day: held.get(symbol))
    rig.minutes["MU"] = day_of([1.0, 3.0])
    body = sparks_for(rig.client, "NBIS", "MU")
    assert body["rows"]["NBIS"]["points"] == [90.0, 91.0, 92.0]
    assert body["rows"]["MU"]["points"] == [1.0, 3.0] and rig.read == ["MU"]  # ten minutes old: not "just drawn"


# ---------------------------------------------------------------------------------------------------- the batched read


def test_what_is_left_is_one_batched_read_not_one_each(rig):
    pre = OPEN - 60 * 60
    alpaca_on(rig, {"NBIS": [alpaca_bar(pre, 88.0), alpaca_bar(OPEN, 90.0), alpaca_bar(OPEN + 60, 91.0)],
                    "IREN": [alpaca_bar(OPEN, 5.0), alpaca_bar(OPEN + 60, 5.5)],
                    "CIFR": [alpaca_bar(OPEN, 4.0), alpaca_bar(OPEN + 60, 4.2)]})
    body = sparks_for(rig.client, "NBIS", "IREN", "CIFR", "MU")
    assert len(rig.alpaca) == 1 and rig.alpaca[0]["symbols"] == "CIFR,IREN,MU,NBIS" and rig.alpaca[0]["feed"] == "sip"
    assert body["rows"]["NBIS"]["points"] == [90.0, 91.0]  # the session's minutes once it has them, not the pre-market
    assert body["rows"]["IREN"]["points"] == [5.0, 5.5]
    assert rig.read == ["MU"]  # Alpaca had nothing for MU: its own low-priority read; the other three made none


def test_a_refused_batched_read_falls_to_single_reads_and_is_not_asked_again_for_a_while(rig):
    rig.patch.setattr(alpaca, "alpaca_configured", lambda: True)
    rig.alpaca_reply = {}  # a 403 reads as {}: the plan does not allow recent SIP minutes
    rig.minutes.update({"NBIS": day_of([90.0, 91.0]), "IREN": day_of([5.0, 5.5])})
    body = sparks_for(rig.client, "NBIS", "IREN")
    assert body["rows"]["NBIS"]["points"] == [90.0, 91.0] and sorted(rig.read) == ["IREN", "NBIS"] and len(rig.alpaca) == 1
    rig.clock["t"] += 3600
    sparks_for(rig.client, "NBIS", "IREN")
    assert len(rig.alpaca) == 1  # off for ten minutes of the real clock


def test_a_batched_day_cut_off_by_its_page_limit_is_not_a_line(rig):
    rig.patch.setattr(alpaca, "alpaca_configured", lambda: True)
    rig.alpaca_reply = {"bars": {"NBIS": [alpaca_bar(OPEN, 90.0)]}, "next_page_token": "more"}
    rig.minutes.update({"NBIS": day_of([90.0, 91.0, 92.0]), "IREN": day_of([5.0, 5.5])})
    body = sparks_for(rig.client, "NBIS", "IREN")
    assert len(rig.alpaca) == desk_sparks.SIP_PAGES
    assert body["rows"]["NBIS"]["points"] == [90.0, 91.0, 92.0]


# ---------------------------------------------------------------------------------------------------- freshness


def test_a_line_is_kept_a_minute_in_the_session_and_not_past_its_own_day(rig):
    rig.minutes["NBIS"] = day_of([90.0, 91.0])
    sparks_for(rig.client, "NBIS")
    rig.minutes["NBIS"] = day_of([90.0, 91.0, 92.0])
    rig.clock["t"] += 30
    assert sparks_for(rig.client, "NBIS")["rows"]["NBIS"]["points"] == [90.0, 91.0]
    rig.clock["t"] += 31
    assert sparks_for(rig.client, "NBIS")["rows"]["NBIS"]["points"] == [90.0, 91.0, 92.0]
    # After the extended session ends the line is kept to midnight; the next New York date builds it again.
    rig.clock["t"] = OPEN + (20 * 60 + 5 - 9 * 60 - 30) * 60  # 20:05
    sparks_for(rig.client, "NBIS")
    asked = len(rig.read)
    rig.clock["t"] += 3 * 3600  # 23:05: still today's
    sparks_for(rig.client, "NBIS")
    assert len(rig.read) == asked
    rig.clock["t"] += 2 * 3600  # 01:05 the next day: yesterday's line is never served as today's
    rig.minutes["NBIS"] = []
    assert sparks_for(rig.client, "NBIS")["rows"]["NBIS"]["points"] == [] and len(rig.read) == asked + 1


def test_valid_until_after_hours_and_overnight():
    et = desk_sparks.ET
    at = lambda h, m=0, d=21: datetime(2026, 10, d, h, m, tzinfo=et).timestamp()  # noqa: E731
    assert desk_sparks._valid_until(at(11), "regular") == at(11) + 60
    assert desk_sparks._valid_until(at(17), "post") == at(17) + 300
    assert desk_sparks._valid_until(at(21), "closed") == at(0, 0, 22)
    assert desk_sparks._valid_until(at(2), "closed") == at(4)


def test_a_failed_read_that_hands_back_old_data_is_no_line(monkeypatch):
    monkeypatch.setattr(tradier, "tradier_configured", lambda: True)
    old = {"series": {"data": [{"timestamp": OPEN, "open": 9, "high": 9, "low": 9, "close": 9, "volume": 1}]}}
    monkeypatch.setattr(chart_feed, "read", lambda path, params, ttl, keep=True, low=False: (old, time.time() - 600, "The chart data connection is unavailable."))
    now = datetime(2026, 10, 21, 14, 49, tzinfo=desk_sparks.ET).timestamp()
    try:
        chart_feed.today_minutes("NBIS", now)
    except ChartFeedError:
        pass
    else:
        raise AssertionError("ten-minute-old data marked as a failure was used as a line")
    monkeypatch.setattr(chart_feed, "read", lambda path, params, ttl, keep=True, low=False: (old, time.time() - 20, "slow"))
    assert chart_feed.today_minutes("NBIS", now)[0]["close"] == 9.0  # twenty seconds old is still a minute or two


# ---------------------------------------------------------------------------------------------------- budget and share


def test_lines_that_are_not_ready_in_the_budget_are_left_out_and_filled_for_the_next_refresh(rig, monkeypatch):
    release = threading.Event()
    rig.minutes["NBIS"] = day_of([90.0, 91.0])
    inner = chart_feed.today_minutes

    def slow(symbol, now, max_age=120):
        if symbol == "IREN":
            release.wait(5)
            return day_of([5.0, 6.0])
        return inner(symbol, now)
    monkeypatch.setattr(chart_feed, "today_minutes", slow)
    monkeypatch.setattr(desk_sparks, "BUDGET_SECONDS", 0.3)
    started = time.perf_counter()
    body = sparks_for(rig.client, "NBIS", "IREN")
    assert time.perf_counter() - started < 3 and set(body["rows"]) == {"NBIS"}
    release.set()
    deadline = time.time() + 3
    while time.time() < deadline and "IREN" not in sparks_for(rig.client, "NBIS", "IREN")["rows"]:
        time.sleep(0.05)
    assert sparks_for(rig.client, "NBIS", "IREN")["rows"]["IREN"]["points"] == [5.0, 6.0]


def test_the_sparklines_never_hold_more_than_their_share_of_the_feeds_places(monkeypatch):
    from collections import OrderedDict, deque
    now = datetime(2026, 10, 21, 14, 49, tzinfo=desk_sparks.ET).timestamp()
    desk_sparks.clear()
    monkeypatch.delenv("RADAR_ENABLED", raising=False)
    monkeypatch.setattr(tradier, "TRADIER_API_KEY", "test-key")
    monkeypatch.setattr(alpaca, "alpaca_configured", lambda: False)
    monkeypatch.setattr(chart_calendar, "hours", lambda day: HOURS)
    monkeypatch.setattr(desk_sparks, "BUDGET_SECONDS", 10)
    for name, empty in (("_cache", OrderedDict()), ("_calls", deque()), ("_failed", {}), ("_flights", {})):
        monkeypatch.setattr(chart_feed, name, empty)
    lock = threading.Lock()
    state = {"now": 0, "max": 0, "lows": 0}

    def get(url, **kwargs):
        timesales = url.endswith("/timesales")
        with lock:
            state["now"] += timesales
            state["max"] = max(state["max"], state["now"])
            state["lows"] += timesales
        time.sleep(0.05)
        with lock:
            state["now"] -= timesales
        body = {"series": None} if timesales else {"quotes": {"quote": []}}
        return httpx.Response(200, json=body, request=httpx.Request("GET", url))
    monkeypatch.setattr("app.engine.chart_feed.market_http.get", get)
    names = ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF", "GGG", "HHH"]
    result = {}
    worker = threading.Thread(target=lambda: result.update(desk_sparks.read(",".join(names), now)))
    worker.start()
    time.sleep(0.06)  # the lines are being read, two at a time
    started = time.perf_counter()
    chart_feed.read("/v1/markets/quotes", {"symbols": "ZZZ"}, 15)  # a screen's read meanwhile
    assert time.perf_counter() - started < 0.2  # not behind the eight 50 ms line reads
    worker.join(10)
    assert state["lows"] == 8 and 1 <= state["max"] <= PROVIDER_SLOTS // 2
    assert set(result["rows"]) == set(names)
    desk_sparks.clear()


def test_a_background_read_waits_for_the_reads_queued_ahead_of_it_and_never_makes_a_screen_read_wait(monkeypatch):
    from collections import OrderedDict, deque
    monkeypatch.setattr(tradier, "TRADIER_API_KEY", "test-key")
    for name, empty in (("_cache", OrderedDict()), ("_calls", deque()), ("_failed", {}), ("_flights", {})):
        monkeypatch.setattr(chart_feed, name, empty)
    gates = {f"busy{i}": threading.Event() for i in range(4)}
    started: list[str] = []
    lock = threading.Lock()

    def get(url, **kwargs):
        symbol = kwargs["params"].get("symbol") or kwargs["params"].get("symbols")
        with lock:
            started.append(symbol)
        if symbol in gates:
            gates[symbol].wait(5)
        return httpx.Response(200, json={"series": None}, request=httpx.Request("GET", url))
    monkeypatch.setattr("app.engine.chart_feed.market_http.get", get)
    results: dict[str, object] = {}

    def read(name, low=False):
        results[name] = chart_feed.read("/v1/markets/timesales", {"symbol": name}, 15, low=low)
    threads = [threading.Thread(target=read, args=(f"busy{i}",)) for i in range(4)]  # all four places held
    for t in threads:
        t.start()
    time.sleep(0.1)
    low = threading.Thread(target=read, args=("NBIS", True))
    screen = threading.Thread(target=read, args=("MU",))  # a screen's read, queued for a place
    screen.start()
    time.sleep(0.05)
    low.start()
    time.sleep(0.1)
    late = threading.Thread(target=read, args=("AMD",))  # a screen read that arrives after the background one
    late.start()
    time.sleep(0.05)
    same = threading.Thread(target=read, args=("NBIS",))  # and one that wants what the background read wants
    same.start()
    time.sleep(0.1)
    for gate in gates.values():  # one place at a time, so the order the waiting reads start in is the order they queued
        gate.set()
        time.sleep(0.05)
    for t in (*threads, low, screen, same, late):
        t.join(5)
    assert started.index("MU") < started.index("AMD") < started.index("NBIS")  # the background read went last, not in line
    assert started.count("NBIS") == 1 and "NBIS" in results  # and the screen's own NBIS read was not made to wait on it


def test_a_line_built_just_after_the_extended_session_ends_is_read_again_before_the_night():
    et = desk_sparks.ET
    at = lambda h, m=0: datetime(2026, 10, 21, h, m, tzinfo=et).timestamp()  # noqa: E731
    assert desk_sparks._valid_until(at(20, 1), "closed") == at(20, 1) + desk_sparks.AFTER_CLOSE_SECONDS
    assert desk_sparks._valid_until(at(20, 10), "closed") == datetime(2026, 10, 22, tzinfo=et).timestamp()
    early = {"status": "open", "open": 570, "close": 780}  # an early close: the window ends at 17:00
    assert desk_sparks._valid_until(at(17, 1), "closed", early) == at(17, 1) + desk_sparks.AFTER_CLOSE_SECONDS
    assert desk_sparks._valid_until(at(17, 10), "closed", early) == datetime(2026, 10, 22, tzinfo=et).timestamp()


def test_old_quote_rows_from_a_failed_read_are_no_change(rig):
    rig.quotes["issue"] = "The chart data connection is unavailable."
    rig.quotes["at"] = time.time() - 600
    rig.minutes["NBIS"] = day_of([90.0, 91.0])
    body = sparks_for(rig.client, "NBIS")
    assert body["rows"]["NBIS"] == {"points": [90.0, 91.0], "change_pct": None} and body["spy_change_pct"] is None


# ---------------------------------------------------------------------------------------------------- the Watching list


def test_watched_names_ride_the_same_quote_read_and_never_get_a_read_of_their_own(rig):
    rig.minutes.update({"NBIS": day_of([90.0, 91.0])})
    rig.quotes["rows"] += [{"symbol": "RKLB", "last": 25.5, "change_percentage": 3.1}, {"symbol": "PLTR", "last": 180.0, "change_percentage": -0.8}]
    rig.quotes["asked"] = []
    response = rig.client.get("/copilot/desk/sparks", params={"symbols": "NBIS", "watch": "RKLB,PLTR,NBIS"})
    body = response.json()
    assert rig.read == ["NBIS"]  # the book's own line read; the watched names made none
    assert len(rig.quotes["asked"]) == 1 and set(rig.quotes["asked"][0]) >= {"NBIS", "RKLB", "PLTR", "SPY"}  # one quote read
    assert body["rows"]["RKLB"] == {"points": [], "change_pct": 3.1, "last": 25.5}
    assert body["rows"]["PLTR"] == {"points": [], "change_pct": -0.8, "last": 180.0}
    assert "last" not in body["rows"]["NBIS"]  # a name in both lists is the book's row


def test_watched_names_take_a_line_from_the_batched_read_only(rig):
    alpaca_on(rig, {"RKLB": [alpaca_bar(OPEN, 25.0), alpaca_bar(OPEN + 60, 25.5)]})
    rig.quotes["rows"] += [{"symbol": "RKLB", "last": 25.5, "change_percentage": 3.1}, {"symbol": "SOFI", "last": 30.0, "change_percentage": 1.0}]
    body = rig.client.get("/copilot/desk/sparks", params={"watch": "RKLB,SOFI"}).json()
    assert len(rig.alpaca) == 1 and rig.alpaca[0]["symbols"] == "RKLB,SOFI"
    assert body["rows"]["RKLB"]["points"] == [25.0, 25.5] and body["rows"]["SOFI"]["points"] == []
    assert rig.read == []  # SOFI, missing from the batched read, is not read on its own


def test_before_the_open_a_watched_name_shows_no_change(rig):
    rig.clock["t"] = OPEN - 30 * 60  # 9:00 New York
    rig.quotes["rows"] += [{"symbol": "RKLB", "last": 25.5, "change_percentage": 0.0}]
    body = rig.client.get("/copilot/desk/sparks", params={"watch": "RKLB"}).json()
    assert body["rows"]["RKLB"] == {"points": [], "change_pct": None, "last": None}  # never a +0.00% from a rolled close


def test_a_long_watchlist_that_overflows_its_batch_never_turns_off_the_books(rig):
    """Book and Watching names are separate batched reads: a watchlist batch that needs more pages than allowed (or
    fails) gives the watched names no line, and the book's batch, its lines and its back-off are untouched."""
    book_bars = {"NBIS": [alpaca_bar(OPEN, 90.0), alpaca_bar(OPEN + 60, 91.0)], "IREN": [alpaca_bar(OPEN, 5.0), alpaca_bar(OPEN + 60, 5.5)]}
    rig.patch.setattr(alpaca, "alpaca_configured", lambda: True)

    def alpaca_get(path, params):
        rig.alpaca.append(params)
        if "NBIS" in params["symbols"]:
            return {"bars": book_bars, "next_page_token": None}
        return {"bars": {}, "next_page_token": "more"}  # the watched batch never ends within the pages
    rig.patch.setattr(alpaca, "_alpaca_get_fast", alpaca_get)
    rig.quotes["rows"] += [{"symbol": s, "last": 10.0, "change_percentage": 1.0} for s in ("RKLB", "SOFI")]
    body = rig.client.get("/copilot/desk/sparks", params={"symbols": "NBIS,IREN", "watch": "RKLB,SOFI"}).json()
    assert [p["symbols"] for p in rig.alpaca][0] == "IREN,NBIS"
    assert all(p["symbols"] == "RKLB,SOFI" for p in rig.alpaca[1:]) and len(rig.alpaca) == 1 + desk_sparks.SIP_PAGES
    assert body["rows"]["NBIS"]["points"] == [90.0, 91.0] and body["rows"]["RKLB"]["points"] == []
    assert rig.read == []  # no Tradier minute read, for the book or the watched names
    assert desk_sparks._sip_off_until == 0.0 and desk_sparks._sip_watch_off_until > 0  # only the watched batch backs off
