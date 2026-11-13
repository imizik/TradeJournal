"""The centre's Grid (app/engine/desk_grid.py, GET /copilot/desk/grid): one batched read for every tile, cached minutes
before any provider, the chart feed only within its budget, never a hidden ticker, and each tile's candles, VWAP, the
previous session's tail and its levels. Every value is invented."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from sqlmodel import Session

from app.engine import alpaca, desk_grid
from app.engine.chart_calendar import chart_calendar
from app.engine.chart_feed import chart_feed
from app.models import DayJournalEntry, LevelAlert
from tests.test_copilot_desk import desk  # noqa: F401  (the desk app over the shared fixtures)
from tests.test_copilot_plans import engine, quotes  # noqa: F401  (fixtures)
from tests.test_today import clock, marks  # noqa: F401  (fixtures)

HOURS = {"status": "open", "open": 570, "close": 960}
OPEN = int(datetime(2026, 10, 21, 13, 30, tzinfo=UTC).timestamp())  # 9:30 New York; the clock reads 14:49
PRIOR_CLOSE = int(datetime(2026, 10, 20, 20, 0, tzinfo=UTC).timestamp())  # Tue 16:00 New York


def minute(at: float, close: float, volume: float = 10) -> dict:
    return {"time": int(at), "end_time": int(at) + 60, "source": "tradier", "open": close, "high": close + 0.1,
            "low": close - 0.1, "close": close, "volume": volume}


def alpaca_bar(at: float, close: float) -> dict:
    return {"t": datetime.fromtimestamp(at, UTC).isoformat().replace("+00:00", "Z"), "o": close, "h": close + 0.1,
            "l": close - 0.1, "c": close, "v": 10}


class Rig:
    def __init__(self):
        self.tradier: list[str] = []
        self.tradier_minutes: dict[str, list[dict]] = {}
        self.alpaca: list[dict] = []
        self.alpaca_reply: dict = {}
        self.peek: dict[str, tuple[list[dict], float]] = {}
        self.calls = 0


@pytest.fixture
def rig(desk, clock, engine, monkeypatch):  # noqa: F811
    r = Rig()
    desk_grid.clear()
    monkeypatch.setattr(chart_calendar, "hours", lambda day: HOURS)
    monkeypatch.setattr(desk_grid, "_stored_tail", lambda symbol, before: None)

    def today_minutes(symbol, now, max_age=120):
        r.tradier.append(symbol)
        return r.tradier_minutes.get(symbol, [])
    monkeypatch.setattr(chart_feed, "today_minutes", today_minutes)
    monkeypatch.setattr(chart_feed, "peek_minutes", lambda symbol, day: r.peek.get(symbol))
    monkeypatch.setattr(chart_feed, "calls_last_minute", lambda: r.calls)

    def alpaca_get(path, params):
        r.alpaca.append(params)
        return r.alpaca_reply
    monkeypatch.setattr(alpaca, "_alpaca_get_fast", alpaca_get)
    monkeypatch.setattr(alpaca, "alpaca_configured", lambda: False)
    r.client, r.clock, r.engine, r.patch = desk, clock, engine, monkeypatch
    yield r
    desk_grid.clear()


def grid(rig, symbols, timeframe="1m"):
    response = rig.client.get("/copilot/desk/grid", params={"symbols": symbols, "timeframe": timeframe})
    assert response.status_code == 200, response.text
    return response.json()


def alpaca_on(rig, bars):
    rig.patch.setattr(alpaca, "alpaca_configured", lambda: True)
    rig.alpaca_reply = {"bars": bars, "next_page_token": None}


def session_bars(closes, start=OPEN):
    return [alpaca_bar(start + 60 * i, c) for i, c in enumerate(closes)]


def tail_bars(closes):
    return [alpaca_bar(PRIOR_CLOSE - 60 * (len(closes) - i), c) for i, c in enumerate(closes)]


# ---------------------------------------------------------------------------------------------------- one batched read


def test_every_tile_comes_from_one_batched_read_and_a_second_read_or_timeframe_costs_nothing(rig):
    alpaca_on(rig, {"NBIS": tail_bars([80.0] * 40) + session_bars([90.0 + i / 10 for i in range(30)]),
                    "MU": tail_bars([200.0] * 40) + session_bars([210.0] * 30)})
    body = grid(rig, "nbis,MU")
    assert len(rig.alpaca) == 1 and rig.alpaca[0]["symbols"] == "MU,NBIS" and rig.tradier == []
    # The read starts at the previous session's last half hour (Tue 15:30 New York) and runs to now.
    assert rig.alpaca[0]["start"].startswith("2026-10-20T15:30")
    nbis = body["rows"]["NBIS"]
    assert nbis["state"] == "ok" and nbis["source"] == "alpaca" and nbis["last"] == 92.9
    prior = [b for b in nbis["bars"] if b["prior"]]
    today = [b for b in nbis["bars"] if not b["prior"]]
    assert len(prior) == desk_grid.TAIL_MINUTES and prior[-1]["time"] == PRIOR_CLOSE - 60  # Tue's last 30 minutes only
    assert all(b["vwap"] is None for b in prior) and len(today) == 30 and today[0]["time"] == OPEN
    assert today[0]["vwap"] == 90.0 and today[-1]["vwap"] is not None  # today's RTH VWAP, from its first minute
    assert body["timeframe"] == "1m" and body["step"] == 60 and body["live"] is True and body["day"] == "2026-10-21"

    five = grid(rig, "NBIS,MU", "5m")  # the same minutes, five to a candle: no read
    assert len(rig.alpaca) == 1 and five["step"] == 300
    assert len([b for b in five["rows"]["NBIS"]["bars"] if not b["prior"]]) == 6
    assert len([b for b in five["rows"]["NBIS"]["bars"] if b["prior"]]) == desk_grid.TAIL_MINUTES // 5
    grid(rig, "MU,NBIS")  # a second desk within the minute
    assert len(rig.alpaca) == 1 and rig.tradier == []

    for symbol, kept in list(desk_grid._minutes.items()):  # the kept minutes age past the minute
        desk_grid._minutes[symbol] = (kept[0] - desk_grid.KEEP_SECONDS - 5, *kept[1:])
    grid(rig, "MU,NBIS")  # a minute later: one read again, and the tails (a finished session) are not asked again
    assert len(rig.alpaca) == 2 and rig.alpaca[1]["start"].startswith("2026-10-21T04:00")


def test_a_chart_drawn_in_the_last_minute_serves_its_tile_with_no_read(rig):
    rig.peek["NBIS"] = ([minute(OPEN + 60 * i, 90.0) for i in range(5)], datetime.now().timestamp())
    rig.peek["MU"] = ([minute(OPEN, 200.0)], datetime.now().timestamp() - 600)  # ten minutes old: not now
    rig.tradier_minutes["MU"] = [minute(OPEN + 60 * i, 201.0) for i in range(3)]
    body = grid(rig, "NBIS,MU")
    assert body["rows"]["NBIS"]["source"] == "chart" and body["rows"]["MU"]["source"] == "tradier"
    assert rig.tradier == ["MU"] and rig.alpaca == []  # Alpaca is not set up here: MU fell to the chart feed


def test_the_chart_feed_is_asked_only_within_its_budget(rig):
    rig.tradier_minutes["NBIS"] = [minute(OPEN, 90.0)]
    rig.calls = desk_grid.TRADIER_HEADROOM  # the feed is busy: the grid waits its turn
    body = grid(rig, "NBIS")
    assert rig.tradier == [] and body["rows"]["NBIS"]["state"] == "unavailable" and body["rows"]["NBIS"]["bars"] == []
    rig.calls = 0
    assert grid(rig, "NBIS")["rows"]["NBIS"]["state"] == "ok" and rig.tradier == ["NBIS"]


def test_a_refused_batched_read_backs_off_and_the_chart_feed_serves(rig):
    alpaca_on(rig, {})
    rig.alpaca_reply = {}  # refused (403 reads as nothing)
    rig.tradier_minutes["NBIS"] = [minute(OPEN, 90.0)]
    assert grid(rig, "NBIS")["rows"]["NBIS"]["source"] == "tradier"
    desk_grid._minutes.clear()
    grid(rig, "NBIS")
    assert len(rig.alpaca) == 1  # backing off: not asked again


# ---------------------------------------------------------------------------------------------------- names


def test_a_hidden_ticker_is_never_read_and_at_most_nine_tiles(rig):
    with Session(rig.engine) as db:
        db.add(DayJournalEntry(operation_id="hide-CRWV", day=date(2026, 10, 21), kind="follow", symbol="CRWV", text="Not following"))
        db.commit()
    alpaca_on(rig, {})
    names = "CRWV,A,B,C,D,E,F,G,H,I,J,../x"
    body = grid(rig, names)
    assert list(body["rows"]) == ["A", "B", "C", "D", "E", "F", "G", "H", "I"]
    assert "CRWV" not in rig.alpaca[0]["symbols"].split(",")
    assert grid(rig, "")["rows"] == {}


def test_levels_are_the_plans_lines_and_armed_alerts(rig):
    with Session(rig.engine) as db:
        db.add(LevelAlert(symbol="NBIS", price=95.0, created_on=date(2026, 10, 21), condition="crosses", session="regular",
                          direction="up", source_kind="copilot", source_id="x", label="", plan_role="entry"))
        db.add(LevelAlert(symbol="NBIS", price=96.5, created_on=date(2026, 10, 21), condition="crosses", session="regular",
                          direction="up", source_kind="level", source_id="desk", label="From the desk"))
        db.add(LevelAlert(symbol="NBIS", price=97.0, created_on=date(2026, 10, 21), condition="crosses", session="regular",
                          direction="up", source_kind="level", source_id="desk", label="", state="fired"))  # fired: no line
        db.commit()
    rig.tradier_minutes["NBIS"] = [minute(OPEN, 90.0)]
    levels = grid(rig, "NBIS")["rows"]["NBIS"]["levels"]
    assert levels == [{"price": 95.0, "role": "entry", "label": None}, {"price": 96.5, "role": "alert", "label": "From the desk"}]


# ---------------------------------------------------------------------------------------------------- which day


def test_before_four_in_the_morning_the_tiles_show_the_last_session_and_are_not_live(rig):
    rig.clock["t"] = int(datetime(2026, 10, 21, 7, 0, tzinfo=UTC).timestamp())  # 03:00 New York
    day, _hours, live = desk_grid.shown_day(rig.clock["t"])
    assert day == date(2026, 10, 20) and live is False
    saturday = int(datetime(2026, 10, 24, 16, 0, tzinfo=UTC).timestamp())
    assert desk_grid.shown_day(saturday)[0] == date(2026, 10, 23)
