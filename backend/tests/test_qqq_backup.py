"""The Alpaca backup reads for the QQQ paper books: IEX quote and bars forced whatever ALPACA_DATA_FEED says."""

from __future__ import annotations

from datetime import date, datetime

from app.engine import alpaca, qqq_backup
from app.engine.chart_math import ET


def fake(monkeypatch, payload):
    seen = []

    def get(path, params):
        seen.append((path, params))
        return payload
    monkeypatch.setattr(alpaca, "alpaca_configured", lambda: True)
    monkeypatch.setattr(alpaca, "ALPACA_DATA_FEED", "sip")  # production's delayed setting must not leak in
    monkeypatch.setattr(alpaca, "_alpaca_get_fast", get)
    return seen


def test_quote_is_iex_with_its_one_stamp_on_both_sides(monkeypatch):
    seen = fake(monkeypatch, {"symbol": "QQQ", "quote": {"t": "2026-11-17T20:59:01.123456789Z", "bp": 600.01, "ap": 600.04}})
    q = qqq_backup.quote("QQQ")
    assert seen == [("/v2/stocks/QQQ/quotes/latest", {"feed": "iex"})]
    assert (q.bid, q.ask) == (600.01, 600.04)
    assert q.bid_date == q.ask_date == int(datetime(2026, 11, 17, 15, 59, 1, 123456, tzinfo=ET).timestamp() * 1000)


def test_minutes_name_their_feed_and_previous_close_is_sip(monkeypatch):
    bar = {"t": "2026-11-17T14:30:00Z", "o": 600, "h": 601, "l": 599, "c": 600.5, "v": 1200}
    seen = fake(monkeypatch, {"bars": [bar], "next_page_token": None})
    now = datetime(2026, 11, 17, 10, 0, 5, tzinfo=ET).timestamp()
    (row,) = qqq_backup.minutes("QQQ", date(2026, 11, 17), now, "iex")
    assert seen[-1][1]["feed"] == "iex" and row["time"] == int(datetime(2026, 11, 17, 9, 30, tzinfo=ET).timestamp())
    fake(monkeypatch, {"bars": [{"t": "2026-11-13T05:00:00Z", "c": 598.0}, {"t": "2026-11-16T05:00:00Z", "c": 599.5}]})
    assert qqq_backup.previous_close("QQQ", date(2026, 11, 17)) == (date(2026, 11, 16), 599.5)


def test_failures_and_odd_shapes_give_none(monkeypatch):
    fake(monkeypatch, {"quote": {"t": "nope"}})
    assert qqq_backup.quote("QQQ") is None
    fake(monkeypatch, {"bars": [], "next_page_token": "more"})
    assert qqq_backup.minutes("QQQ", date(2026, 11, 17), datetime(2026, 11, 17, 11, tzinfo=ET).timestamp(), "iex") is None

    def boom(path, params):
        raise alpaca.AlpacaFastFailure("429")
    monkeypatch.setattr(alpaca, "_alpaca_get_fast", boom)
    assert qqq_backup.quote("QQQ") is None and qqq_backup.previous_close("QQQ", date(2026, 11, 17)) is None
    monkeypatch.setattr(alpaca, "alpaca_configured", lambda: False)
    monkeypatch.setattr(alpaca, "_alpaca_get_fast", lambda *a: (_ for _ in ()).throw(AssertionError("no call unconfigured")))
    assert qqq_backup.quote("QQQ") is None
