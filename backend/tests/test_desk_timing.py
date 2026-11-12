"""The desk's server time (docs/copilot-lab.md § Where the wait goes): the Server-Timing header and the timings read,
the overlapped provider waits (and no extra call from them), no Robinhood call on any request path, and the startup
warm-up. Outside calls are faked at the transport and take ``latency.seconds`` each (``tests/desk_latency.py``)."""

from __future__ import annotations

import logging
import re
import threading
import time
from types import SimpleNamespace

import pytest

from app.engine import request_timing
from app.routers import copilot_desk
from tests.desk_latency import latency, slow_desk  # noqa: F401  (fixture)
from tests.test_copilot_plans import engine  # noqa: F401  (fixture)
from tests.test_today import clock  # noqa: F401  (fixture)

PART = re.compile(r"^[A-Za-z0-9_.-]+;dur=\d+\.\d$")
DESK_GETS = ["/copilot/desk/threads", "/copilot/desk/session", "/copilot/desk/feed", "/copilot/desk/sparks?symbols=NBIS,CRWV",
             "/copilot/desk/scorecard", "/copilot/desk/day-report", "/copilot/desk/pings", "/copilot/desk/pings?day_only=true",
             "/copilot/desk/to-rate", "/copilot/desk/timings", "/charts/journal/positions/NBIS/context"]


@pytest.fixture
def desk(slow_desk, monkeypatch):  # noqa: F811
    monkeypatch.setattr(latency, "seconds", 0.2)
    slow_desk.providers.calls.clear()
    slow_desk.providers.spans.clear()
    return slow_desk


def _overlap(spans, a, b) -> bool:
    (_, _, start_a, end_a, _), (_, _, start_b, end_b, _) = a, b
    return start_a < end_b and start_b < end_a


def _settle(feed):
    """Waits for a background Robinhood refresh the reads kicked (so it cannot leak into the next test)."""
    for _ in range(200):
        if not feed._flight.locked():
            return
        time.sleep(0.05)


# --------------------------------------------------------------------------- the header and the timings read

def test_each_desk_read_names_its_sections_in_server_timing_and_nothing_else(desk):
    response = desk.client.get("/copilot/desk/threads")
    assert response.status_code == 200
    header = response.headers["server-timing"]
    parts = header.split(", ")
    assert all(PART.match(p) for p in parts), header
    names = [p.split(";")[0] for p in parts]
    assert {"desk-board", "desk-positions", "desk-position-marks", "desk-radar"} <= set(names) and names[-1] == "total"
    assert not re.search(r"NBIS|CRWV|APLD|[0-9a-f]{8}-[0-9a-f]{4}", header)  # names and milliseconds only
    for path in DESK_GETS[1:-2]:
        assert "total;dur=" in desk.client.get(path).headers["server-timing"]
    assert "total;dur=" in desk.client.get("/charts/journal/positions/NBIS/context").headers["server-timing"]
    assert "server-timing" not in desk.client.get("/copilot/desk/timings").headers  # the diagnostics read is not timed
    _settle(desk.feed)


def test_the_timings_read_gives_each_route_p50_p90_and_its_sections(desk):
    request_timing.reset()
    for _ in range(3):
        desk.client.get("/copilot/desk/threads")
    desk.client.get("/copilot/desk/session")
    body = desk.client.get("/copilot/desk/timings?limit=2").json()
    threads = body["routes"]["GET /copilot/desk/threads"]
    assert threads["count"] == 3 and threads["p50_ms"] <= threads["p90_ms"] <= threads["max_ms"]
    assert [r["first"] for r in threads["recent"]] == [False, False]  # newest first; only the first since start is cold
    assert threads["recent"][0]["status"] == 200 and "desk board" in threads["recent"][0]["sections"]
    assert set(threads["sections"]["desk board"]) == {"p50", "p90", "n"}
    assert "GET /copilot/desk/session" in body["routes"] and "GET /copilot/desk/timings" not in body["routes"]
    assert body["slow_ms"] == request_timing.SLOW_MS
    _settle(desk.feed)


def test_a_slow_read_logs_one_line_naming_its_slowest_sections(desk, monkeypatch, caplog):
    monkeypatch.setattr(request_timing, "SLOW_MS", 100)
    with caplog.at_level(logging.WARNING, logger="app.engine.request_timing"):
        desk.client.get("/copilot/desk/threads")
        desk.client.get("/copilot/desk/threads")  # served from the caches: fast, no line
    lines = [r.getMessage() for r in caplog.records if r.name == "app.engine.request_timing"]
    assert len(lines) == 1 and lines[0].startswith("slow desk read GET /copilot/desk/threads ")
    assert "desk board" in lines[0] and "NBIS" not in lines[0]
    _settle(desk.feed)


# --------------------------------------------------------------------------- the waits overlap, no call is added

def test_the_book_read_waits_on_its_quote_and_its_marks_side_by_side_with_one_call_each(desk):
    desk.client.get("/copilot/desk/threads")
    tradier = [s for s in desk.providers.spans if s[0] == "tradier" and s[1] == "/v1/markets/quotes"]
    assert len(tradier) == 2  # the plans' underlying quote and the positions' option marks, each once
    assert _overlap(desk.providers.spans, *tradier)
    desk.providers.spans.clear()
    desk.client.get("/copilot/desk/threads")
    assert [s for s in desk.providers.spans if s[0] == "tradier"] == []  # inside the caches' minute: no call at all
    _settle(desk.feed)


def test_the_feed_reads_its_two_headline_sources_side_by_side(desk):
    desk.client.get("/copilot/desk/feed")
    news = [s for s in desk.providers.spans if s[0] == "news"]
    assert len(news) == 2 and _overlap(desk.providers.spans, *news)


def test_opening_a_position_waits_on_its_marks_quote_and_headlines_at_once_with_one_call_each(desk):
    body = desk.client.get("/charts/journal/positions/NBIS/context").json()
    assert body["positions"] and body["positions"][0]["symbol"] == "NBIS"
    lines = {line["key"]: line for line in body["positions"][0]["since_entry"]["lines"]}
    assert lines["headlines"]["state"] == "ok" and lines["underlying"]["state"] in ("ok", "missing")
    quotes = [s for s in desk.providers.spans if s[0] == "tradier" and s[1] == "/v1/markets/quotes"]
    news = [s for s in desk.providers.spans if s[0] == "news"]
    assert len(quotes) == 2 and len(news) == 1  # the option marks, the underlying, the headlines: once each
    assert _overlap(desk.providers.spans, quotes[0], quotes[1]) and _overlap(desk.providers.spans, quotes[0], news[0])


def test_a_headline_read_that_fails_still_reads_as_unavailable_with_its_reason(desk, monkeypatch):
    from app.engine import news

    def refused(*args, **kwargs):
        raise PermissionError("refused key")
    monkeypatch.setattr(news, "_alpaca_get_fast", refused)
    monkeypatch.setattr(news, "_alpaca_get", refused)
    body = desk.client.get("/charts/journal/positions/NBIS/context").json()
    line = next(x for x in body["positions"][0]["since_entry"]["lines"] if x["key"] == "headlines")
    assert line["state"] == "unavailable" and "could not be read" in line["text"]


# --------------------------------------------------------------------------- Robinhood is never read on a request path

def test_no_desk_read_calls_robinhood_and_the_first_one_does_not_wait_for_it(desk):
    gate = threading.Event()
    desk.providers.robinhood_gate = gate  # the background refresh blocks here until the reads are done
    try:
        first = desk.client.get("/copilot/desk/threads").json()
        assert first["robinhood"]["state"] == "loading"  # no snapshot yet: the journal's rows, not a wait
        assert any(r.get("book") for r in first["threads"])
        for path in DESK_GETS:
            assert desk.client.get(path).status_code == 200, path
    finally:
        gate.set()
    _settle(desk.feed)
    on_robinhood = [s for s in desk.providers.spans if s[0] == "robinhood"]
    assert on_robinhood and {s[4] for s in on_robinhood} == {"robinhood-feed"}  # every call on the feed's own thread
    later = desk.client.get("/copilot/desk/threads").json()
    assert later["robinhood"]["state"] == "ok" and later["robinhood"]["as_of"] == int(desk.clock["t"])  # its true read time


# --------------------------------------------------------------------------- the startup warm-up

def test_the_startup_warm_up_reads_the_calendar_on_its_own_thread_and_never_waits(monkeypatch):
    from app.engine.chart_calendar import chart_calendar
    release, seen = threading.Event(), []

    def hours(day):
        seen.append(threading.current_thread().name)
        release.wait(5)
        return None
    monkeypatch.setattr(chart_calendar, "hours", hours)
    monkeypatch.setattr(copilot_desk.copilot, "settings", lambda: SimpleNamespace(enabled=False))
    copilot_desk.warm_at_start()
    time.sleep(0.05)
    assert seen == []  # the lab is off: nothing is read
    monkeypatch.setattr(copilot_desk.copilot, "settings", lambda: SimpleNamespace(enabled=True))
    start = time.perf_counter()
    copilot_desk.warm_at_start()
    assert time.perf_counter() - start < 0.5  # returned while the calendar read is still blocked
    for _ in range(100):
        if seen:
            break
        time.sleep(0.01)
    release.set()
    assert seen and seen[0] == "desk-warm"
