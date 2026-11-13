"""A held option's own chart on the desk (app/engine/desk_contract.py): the contract's minute trades from one cached chart
feed read, today's marks the live prices remembered, the stock's price per slot and the journal's fills at their
per-share premium; nothing drawn when there is nothing, and a hidden ticker never read. Every value is invented."""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import UUID

import pytest
from sqlmodel import Session

from app.engine import desk_contract, desk_ticks
from app.engine.chart_calendar import chart_calendar
from app.engine.chart_feed import ChartFeedError, chart_feed
from app.models import Account, Fill
from app.routers.fills import _rebuild_trades
from tests.test_copilot_desk import desk  # noqa: F401  (the desk app over the shared fixtures)
from tests.test_copilot_plans import engine, quotes  # noqa: F401  (fixtures)
from tests.test_today import ROTH, buy, clock, marks  # noqa: F401  (fixtures)

CALL = "NBIS261023C00100000"  # the contract ``buy`` opens: NBIS Oct 23 2026 100C, 2 contracts at $310 each


def ny(day: int, hour: int, minute: int = 0) -> int:
    return int(datetime(2026, 10, day, hour + 4, minute, tzinfo=UTC).timestamp())  # New York is UTC-4 in October


def minute(stamp: int, close: float, *, low: float | None = None, high: float | None = None, volume: int = 3) -> dict:
    return {"timestamp": stamp, "open": close, "high": high or close, "low": low or close, "close": close, "volume": volume}


@pytest.fixture
def feed(desk, clock, monkeypatch):  # noqa: F811
    desk_ticks.clear()
    monkeypatch.setattr(chart_calendar, "hours", lambda day: {"status": "open", "open": 570, "close": 960})
    monkeypatch.setattr(chart_feed, "calls_last_minute", lambda: 0)
    state = {"reads": [], "series": [], "fail": None, "stock": [], "client": desk, "clock": clock}

    def read(path, params, ttl, keep=True, low=False):
        state["reads"].append((path, dict(params), ttl, low))
        if state["fail"]:
            raise state["fail"]
        return {"series": {"data": state["series"]} if state["series"] else None}, 0.0, None

    def today_minutes(symbol, now, max_age=120):
        state["stock_symbol"] = symbol
        return [{"time": t, "open": p, "high": p, "low": p, "close": p, "volume": 10} for t, p in state["stock"]]
    monkeypatch.setattr(chart_feed, "read", read)
    monkeypatch.setattr(chart_feed, "today_minutes", today_minutes)
    yield state
    desk_ticks.clear()


def contract(feed, symbol="NBIS", occ=CALL):
    response = feed["client"].get("/copilot/desk/contract", params={"symbol": symbol, "occ": occ})
    assert response.status_code == 200, response.text
    return response.json()


def test_trades_become_two_minute_candles_with_his_fills_at_their_premium_and_the_stock_beside(feed, engine):  # noqa: F811
    buy(engine, 500)  # 2 contracts at $310 a contract, Oct 21 10:05
    feed["series"] = [minute(ny(20, 15, 58), 2.9),  # the session before: not shown once today has trades
                      minute(ny(21, 10, 4), 3.0, high=3.2), minute(ny(21, 10, 5), 3.1, low=2.95, volume=5),
                      minute(ny(21, 10, 6), 3.3), minute(ny(21, 10, 8), 3.4)]
    feed["stock"] = [(ny(21, 10, 4), 94.0), (ny(21, 10, 5), 94.2), (ny(21, 10, 7), 94.5)]
    body = contract(feed)
    assert body["state"] == "ok" and body["day"] == "2026-10-21" and body["label"] == "NBIS 10/23/26 100C"
    assert body["live"] is True and body["step"] == 120 and body["source"].startswith("Tradier")
    # One read of the contract's own trades: its OCC symbol, a few days back to today's 20:00, kept under a minute.
    assert feed["reads"] == [("/v1/markets/timesales", {"symbol": CALL, "interval": "1min", "session_filter": "all",
                              "start": "2026-10-16 09:30", "end": "2026-10-21 20:00"}, desk_contract.LIVE_TTL, False)]
    assert body["bars"] == [
        {"time": ny(21, 10, 4), "open": 3.0, "high": 3.2, "low": 2.95, "close": 3.1, "volume": 8.0},  # 10:04 and 10:05
        {"time": ny(21, 10, 6), "open": 3.3, "high": 3.3, "low": 3.3, "close": 3.3, "volume": 3.0},
        {"time": ny(21, 10, 8), "open": 3.4, "high": 3.4, "low": 3.4, "close": 3.4, "volume": 3.0},
    ]
    assert body["style"] == "candles"  # every 2-minute slot from the first trade to the last traded
    assert body["stock"] == [{"time": ny(21, 10, 4), "price": 94.2}, {"time": ny(21, 10, 6), "price": 94.5}]
    assert feed["stock_symbol"] == "NBIS"
    assert body["fills"] == [{"at": ny(21, 10, 5), "side": "buy", "opening": True, "contracts": 2.0, "price": 3.1,
                              "provisional": False, "text": "Bought 2 at 3.10"}]
    assert body["marks"] == []


def test_before_todays_first_trade_the_last_session_with_trades_is_shown(feed, engine):  # noqa: F811
    feed["series"] = [minute(ny(20, 15, 50), 2.9), minute(ny(20, 15, 58), 2.7)]
    body = contract(feed)
    assert body["state"] == "ok" and body["day"] == "2026-10-20"
    assert [b["time"] for b in body["bars"]] == [ny(20, 15, 50), ny(20, 15, 58)]
    assert body["style"] == "line"  # two prints eight minutes apart: a line, not two dashes


def test_marks_the_live_prices_saw_today_fill_in_where_trades_are_sparse(feed, engine, monkeypatch):  # noqa: F811
    for minute_of_hour, bid in ((40, 3.2), (40, 3.3), (43, 3.5)):  # two reads in the 14:40 minute: the newer one stands
        feed["clock"]["t"] = ny(21, 14, minute_of_hour) + 10 + (bid == 3.3) * 20
        monkeypatch.setattr(chart_feed, "quote_rows", lambda symbols, ttl=15, keep=True, low=False, b=bid: (
            [{"symbol": CALL, "last": 3.0, "bid": b, "ask": b + 0.2}], 0.0, None))
        ticks = feed["client"].get("/copilot/desk/ticks", params={"symbols": CALL})
        assert ticks.status_code == 200 and CALL in ticks.json()["rows"]
        desk_ticks._kept.clear()  # the next read is a new one
    feed["series"] = [minute(ny(21, 10, 4), 3.0)]
    body = contract(feed)
    assert body["state"] == "ok" and body["style"] == "line"
    assert body["marks"] == [{"time": ny(21, 14, 40), "price": 3.4}, {"time": ny(21, 14, 42), "price": 3.6}]  # midpoints, per 2-minute slot

    feed["series"] = []  # no trade today at all: the marks alone are still real
    assert contract(feed)["marks"] and contract(feed)["bars"] == []
    assert desk_ticks.marks("NBIS261023P00100000", feed["clock"]["t"]) == []  # only the contract quoted


def test_nothing_to_draw_is_none_and_a_failed_read_says_why(feed, engine):  # noqa: F811
    body = contract(feed)
    assert body["state"] == "none" and body["bars"] == [] and body["reason"]
    feed["fail"] = ChartFeedError("Chart requests are cooling down to stay within the data allowance.", "rate_limited")
    body = contract(feed)
    assert body["state"] == "unavailable" and "cooling down" in body["reason"]


def test_a_symbol_that_is_not_the_contracts_or_a_hidden_ticker_is_never_read(feed, engine):  # noqa: F811
    assert contract(feed, symbol="MU")["state"] == "unavailable"
    assert contract(feed, occ="NBIS261023X00100000")["state"] == "unavailable"
    assert contract(feed, occ="../etc")["state"] == "unavailable"
    assert feed["reads"] == []
    from app.models import DayJournalEntry
    with Session(engine) as db:
        db.add(DayJournalEntry(day=date(2026, 10, 21), kind="follow", symbol="NBIS", text="Not following", operation_id="hide-nbis"))
        db.commit()
    body = contract(feed)
    assert body == {"state": "none", "symbol": "NBIS", "reason": None} and feed["reads"] == []


def test_fills_leave_off_rolls_and_webull_and_keep_earlier_days_of_the_open_trade(feed, engine):  # noqa: F811
    webull = UUID(int=9)
    with Session(engine) as db:
        db.add(Account(id=webull, name="Webull", type="individual", last4="0001", broker="webull"))
        db.add(Fill(id=UUID(int=600), account_id=ROTH, ticker="NBIS", instrument_type="option", side="buy_to_open", contracts=1,
                    price=250, executed_at=datetime(2026, 10, 19, 11, 0), raw_email_id="gmail:600", option_type="call",
                    strike=100, expiration=date(2026, 10, 23)))
        db.add(Fill(id=UUID(int=601), account_id=ROTH, ticker="NBIS", instrument_type="option", side="buy_to_open", contracts=1,
                    price=280, executed_at=datetime(2026, 10, 21, 11, 0), raw_email_id="roll:601", option_type="call",
                    strike=100, expiration=date(2026, 10, 23)))
        db.add(Fill(id=UUID(int=602), account_id=webull, ticker="NBIS", instrument_type="option", side="buy_to_open", contracts=1,
                    price=300, executed_at=datetime(2026, 10, 21, 11, 0), raw_email_id="gmail:602", option_type="call",
                    strike=100, expiration=date(2026, 10, 23)))
        db.add(Fill(id=UUID(int=603), account_id=ROTH, ticker="NBIS", instrument_type="option", side="buy_to_open", contracts=1,
                    price=150, executed_at=datetime(2026, 10, 21, 11, 0), raw_email_id="gmail:603", option_type="put",
                    strike=100, expiration=date(2026, 10, 23)))
        db.commit()
        _rebuild_trades(db, "test")
        db.commit()
    feed["series"] = [minute(ny(21, 10, 4), 3.0)]
    body = contract(feed)
    assert [(f["at"], f["price"], f["text"]) for f in body["fills"]] == [(ny(19, 11), 2.5, "Bought 1 at 2.50")]
