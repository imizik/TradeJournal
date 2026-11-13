"""The desk's live prices (app/engine/desk_ticks.py): one batched read shared by every open desk for a few seconds, the
regular session only, inside the chart feed's budget, and never a made-up price. Every value is invented."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.engine import desk_ticks
from app.engine.chart_calendar import chart_calendar
from app.engine.chart_feed import ChartFeedError, chart_feed
from tests.test_copilot_desk import desk  # noqa: F401  (the desk app over the shared fixtures)
from tests.test_copilot_plans import engine, quotes  # noqa: F401  (fixtures)
from tests.test_today import clock, marks  # noqa: F401  (fixtures)

HOURS = {"status": "open", "open": 570, "close": 960}
CALL = "NBIS261023C00100000"


@pytest.fixture
def rig(desk, clock, monkeypatch):  # noqa: F811
    desk_ticks.clear()
    monkeypatch.setattr(chart_calendar, "hours", lambda day: HOURS)
    monkeypatch.setattr(chart_feed, "calls_last_minute", lambda: 0)
    state = {"calls": [], "kwargs": [], "fail": None, "rows": {
        "NBIS": {"symbol": "NBIS", "last": 94.1, "change_percentage": 1.234, "previous_close": 93.0},
        "MU": {"symbol": "MU", "last": 120.5, "change_percentage": -0.5, "previous_close": 121.1},
        CALL: {"symbol": CALL, "last": 4.5, "bid": 4.0, "ask": 4.2, "change_percentage": 12.0},
        "ZERO": {"symbol": "ZERO", "last": 0.0, "change_percentage": 0.0},
        "NONE": {"symbol": "NONE", "last": None, "change_percentage": None},
    }}

    def quote_rows(symbols, ttl=15, keep=True, low=False):
        state["calls"].append(sorted(symbols))
        state["kwargs"].append((ttl, keep, low))
        if state["fail"]:
            raise state["fail"]
        return [state["rows"][s] for s in symbols if s in state["rows"]], 0.0, None
    monkeypatch.setattr(chart_feed, "quote_rows", quote_rows)
    state["client"], state["clock"], state["patch"] = desk, clock, monkeypatch
    yield state
    desk_ticks.clear()


def ticks(rig, *names):
    response = rig["client"].get("/copilot/desk/ticks", params={"symbols": ",".join(names)})
    assert response.status_code == 200, response.text
    return response


def at_ny(rig, hour: int, minute: int = 0):
    rig["clock"]["t"] = datetime(2026, 10, 21, hour + 4, minute, tzinfo=UTC).timestamp()  # New York is UTC-4 in October


def test_every_symbol_is_one_batched_read_kept_for_a_few_seconds(rig):
    body = ticks(rig, "nbis", "MU", CALL, "../x").json()
    assert rig["calls"] == [sorted(["NBIS", "MU", CALL])]  # one call for all three; ../x is not a symbol
    assert rig["kwargs"] == [(desk_ticks.TICK_SECONDS, False, True)]  # its own few seconds, no stale fallback, low priority
    assert body["state"] == "ok" and body["poll_seconds"] == desk_ticks.POLL_SECONDS
    now = int(rig["clock"]["t"])
    assert body["rows"]["NBIS"] == {"last": 94.1, "change_pct": 1.23, "prev_close": 93.0, "at": now}
    assert body["rows"][CALL] == {"last": 4.1, "change_pct": None, "prev_close": None, "at": now}  # a contract's mark: the midpoint

    rig["clock"]["t"] += 2  # another tab, or the phone, inside the window: served from the kept read
    assert ticks(rig, "MU").json()["rows"]["MU"]["last"] == 120.5 and len(rig["calls"]) == 1

    rig["clock"]["t"] += desk_ticks.TICK_SECONDS  # past the window: one read again, still carrying what the others asked for
    rig["rows"]["MU"]["last"] = 121.0
    assert ticks(rig, "MU").json()["rows"]["MU"] == {"last": 121.0, "change_pct": -0.5, "prev_close": 121.1, "at": int(rig["clock"]["t"])}
    assert rig["calls"][-1] == sorted(["MU", "NBIS", CALL]) and len(rig["calls"]) == 2


def test_a_symbol_no_desk_asked_for_lately_leaves_the_batch(rig):
    ticks(rig, "NBIS")
    rig["clock"]["t"] += desk_ticks.WANTED_SECONDS + 1
    ticks(rig, "MU")
    assert rig["calls"] == [["NBIS"], ["MU"]]


def test_outside_the_regular_session_nothing_is_asked(rig):
    at_ny(rig, 8)  # pre-market
    body = ticks(rig, "NBIS").json()
    assert body["state"] == "closed" and body["rows"] == {} and body["poll_seconds"] is None
    assert body["opens_at"] == int(datetime(2026, 10, 21, 13, 30, tzinfo=UTC).timestamp())  # 9:30 New York
    at_ny(rig, 17)  # after the close: no open left today
    assert ticks(rig, "NBIS").json() | {"as_of": None} == {"state": "closed", "as_of": None, "rows": {}, "opens_at": None, "poll_seconds": None}
    rig["patch"].setattr(chart_calendar, "hours", lambda day: {"status": "closed"})
    at_ny(rig, 11)  # a holiday
    assert ticks(rig, "NBIS").json()["state"] == "closed"
    assert rig["calls"] == []


def test_a_failed_read_is_unavailable_and_a_missing_price_is_never_a_zero(rig):
    body = ticks(rig, "ZERO", "NONE", "NBIS").json()
    assert set(body["rows"]) == {"NBIS"}  # no zero, no blank row
    rig["clock"]["t"] += desk_ticks.TICK_SECONDS
    rig["fail"] = ChartFeedError("Tradier unavailable")
    body = ticks(rig, "NBIS", "MU").json()
    # The last good price is kept with the time it was read, so the desk can grey it; nothing new is invented.
    assert body["state"] == "unavailable" and set(body["rows"]) == {"NBIS"}
    assert body["rows"]["NBIS"]["at"] == int(rig["clock"]["t"]) - desk_ticks.TICK_SECONDS
    rig["clock"]["t"] += desk_ticks.TICK_SECONDS
    rig["fail"] = None
    assert ticks(rig, "NBIS", "MU").json()["state"] == "ok"


def test_the_ticks_stop_asking_before_the_chart_feed_runs_out(rig):
    rig["patch"].setattr(chart_feed, "calls_last_minute", lambda: desk_ticks.BUDGET_HEADROOM)
    body = ticks(rig, "NBIS").json()
    assert body["state"] == "unavailable" and body["rows"] == {} and rig["calls"] == []


def test_refused_while_the_lab_is_off(rig):
    from types import SimpleNamespace
    from app.routers import copilot_desk
    rig["patch"].setattr(copilot_desk.copilot, "settings", lambda: SimpleNamespace(enabled=False))
    assert rig["client"].get("/copilot/desk/ticks", params={"symbols": "NBIS"}).status_code == 503


def test_a_symbol_with_no_price_is_remembered_so_every_tab_shares_one_call(rig):
    ticks(rig, "NBIS", "ILLQ")  # ILLQ: the provider has no price for it
    for _ in range(3):  # three more tabs inside the window
        rig["clock"]["t"] += 1
        assert set(ticks(rig, "NBIS", "ILLQ").json()["rows"]) == {"NBIS"}
    assert len(rig["calls"]) == 1


def test_a_book_row_ticks_from_the_cost_that_gives_its_own_pnl():
    from app.routers.copilot_desk import _tick
    # 1000 shares at an average of 45.6789 (shown as 45.68), marked 50.00: the server's +4321.10, not +4320.00.
    row = {"symbol": "NBIS", "instrument": "stock", "avg_entry": 45.68, "quantity": 1000.0, "mark": 50.0, "unrealized_usd": 4321.1,
           "direction": "long"}
    tick = _tick(row)
    assert tick["quote"] == "NBIS" and tick["scale"] == 1 and round((50.0 - tick["cost"]) * 1000, 2) == 4321.1
    assert _tick({**row, "unrealized_usd": None})["cost"] == 45.68  # no P&L yet: the journal's cost
    assert _tick({**row, "direction": "short", "unrealized_usd": -4321.1})["cost"] == tick["cost"]
