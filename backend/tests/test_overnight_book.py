"""The QQQ overnight paper book: entry at 15:59 on full sessions, exit at the next session's open, fresh quotes only."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from app.engine import overnight_book as ob
from app.engine.chart_math import ET
from app.engine.tradier import TradierQuote


def at(day: str, hh: int, mm: int, ss: int = 0) -> float:
    d = date.fromisoformat(day)
    return datetime(d.year, d.month, d.day, hh, mm, ss, tzinfo=ET).timestamp()


class Calendar:
    def __init__(self, days: dict[str, dict]):
        self.days = days

    def hours(self, day: date):
        return self.days.get(day.isoformat(), {"status": "open", "open": 570, "close": 960})


class Clock:
    def __init__(self, t: float):
        self.t = t

    def __call__(self) -> float:
        return self.t


def quote_feed(bid: float, ask: float, clock: Clock, age: float = 1.0, calls: list | None = None):
    def get(symbols):
        if calls is not None:
            calls.append(clock.t)
        ms = int((clock.t - age) * 1000)
        return {"QQQ": TradierQuote(symbol="QQQ", bid=bid, ask=ask, bid_date=ms, ask_date=ms)}
    return get


def book(tmp_path, clock, quote, days=None):
    return ob.OvernightBook(Calendar(days or {}), clock=clock, quote=quote, store=ob.Store(tmp_path / "book.sqlite3"))


def test_buys_at_1559_at_the_ask_and_sells_at_the_next_open_at_the_bid(tmp_path):
    clock, calls = Clock(at("2026-11-12", 15, 58, 50)), []
    b = book(tmp_path, clock, quote_feed(500.00, 500.02, clock, calls=calls))
    b.run()
    assert b.store.nights() == [] and calls == []  # nothing before 15:59:00
    clock.t = at("2026-11-12", 15, 59, 3)
    b.run()
    n = b.store.night("2026-11-12")
    assert (n["status"], n["entry_ask"]) == ("open", 500.02)
    clock.t = at("2026-11-12", 15, 59, 30)
    b.run()
    assert len(calls) == 1  # one buy a night
    clock.t = at("2026-11-13", 9, 29, 55)
    b.run()
    assert b.store.night("2026-11-12")["status"] == "open"  # not before 09:30:00
    b.quote = quote_feed(502.00, 502.03, clock)
    clock.t = at("2026-11-13", 9, 30, 4)
    b.run()
    n = b.store.night("2026-11-12")
    assert (n["status"], n["exit_day"], n["exit_bid"]) == ("closed", "2026-11-13", 502.00)
    assert ob.result_bp(n) == pytest.approx((502.00 - 500.02) / 500.02 * 10_000)


def test_holds_through_the_weekend_and_buys_again_only_after_selling(tmp_path):
    clock = Clock(at("2026-11-13", 15, 59, 2))  # a Friday
    b = book(tmp_path, clock, quote_feed(500.0, 500.02, clock))
    b.run()
    clock.t = at("2026-11-14", 9, 31)  # Saturday: shut
    b.run()
    assert b.store.night("2026-11-13")["status"] == "open"
    clock.t = at("2026-11-16", 9, 30, 2)
    b.run()
    assert b.store.night("2026-11-13")["exit_day"] == "2026-11-16"
    clock.t = at("2026-11-16", 15, 59, 1)
    b.run()
    assert b.store.night("2026-11-16")["status"] == "open"


def test_no_entry_on_an_early_close_or_a_holiday(tmp_path):
    clock = Clock(at("2026-11-27", 12, 59, 5))
    days = {"2026-11-27": {"status": "open", "open": 570, "close": 780}, "2026-11-26": {"status": "closed"}}
    b = book(tmp_path, clock, quote_feed(500.0, 500.02, clock), days)
    for t in (at("2026-11-27", 12, 59, 5), at("2026-11-27", 15, 59, 5), at("2026-11-27", 16, 1), at("2026-11-26", 15, 59, 5)):
        clock.t = t
        b.run()
    assert b.store.nights() == []


def test_a_stale_or_crossed_quote_does_not_fill_and_the_night_is_missed_after_the_close(tmp_path):
    clock = Clock(at("2026-11-12", 15, 59, 2))
    b = book(tmp_path, clock, quote_feed(500.0, 500.02, clock, age=120))
    b.run()
    b.quote = quote_feed(500.05, 500.0, clock)  # crossed
    clock.t = at("2026-11-12", 15, 59, 40)
    b.run()
    assert b.store.night("2026-11-12") is None
    clock.t = at("2026-11-12", 16, 0, 10)
    b.run()
    assert b.store.night("2026-11-12")["status"] == "missed"


def test_a_failed_exit_keeps_trying_in_the_session_and_never_sells_after_hours(tmp_path):
    clock = Clock(at("2026-11-12", 15, 59, 2))
    b = book(tmp_path, clock, quote_feed(500.0, 500.02, clock))
    b.run()

    def broken(symbols):
        raise RuntimeError("provider down")
    b.quote = broken
    for t in (at("2026-11-13", 9, 30, 2), at("2026-11-13", 15, 59, 2), at("2026-11-13", 16, 5)):
        clock.t = t
        b.run()  # never raises into the monitor
    assert b.store.night("2026-11-12")["status"] == "open"
    assert b.store.night("2026-11-13") is None  # no second position while one is open
    b.quote = quote_feed(501.0, 501.02, clock)
    clock.t = at("2026-11-16", 9, 30, 5)
    b.run()
    assert b.store.night("2026-11-12")["exit_day"] == "2026-11-16"


def test_read_summarises_without_a_provider(tmp_path, monkeypatch):
    path = tmp_path / "book.sqlite3"
    monkeypatch.setenv("OVERNIGHT_BOOK_PATH", str(path))
    monkeypatch.setenv("OVERNIGHT_BOOK_ENABLED", "true")
    empty = ob.read(0)
    assert (empty["enabled"], empty["state"], empty["nights"], empty["totals"]["closed"]) == (True, "flat", [], 0)
    store = ob.Store(path)
    store.enter("2026-11-11", 1.0, 499.98, 500.00)
    store.exit("2026-11-11", "2026-11-12", 2.0, 505.00, 505.02)
    store.miss("2026-11-12", "no fresh QQQ quote")
    store.enter("2026-11-13", 3.0, 510.00, 510.02)
    view = ob.read(4)
    assert view["state"] == "holding"
    assert [n["day"] for n in view["nights"]] == ["2026-11-13", "2026-11-12", "2026-11-11"]
    assert view["nights"][2]["bp"] == pytest.approx(100.0) and view["nights"][2]["dollars"] == pytest.approx(100.0)
    assert view["totals"] == {"closed": 1, "missed": 1, "mean_bp": 100.0, "dollars": 100.0, "up": 1}
    assert view["backtest"]["protocol_id"] == "qqq-overnight-20261114-v1"


def test_off_by_default(monkeypatch):
    monkeypatch.delenv("OVERNIGHT_BOOK_ENABLED", raising=False)
    assert not ob.enabled()

