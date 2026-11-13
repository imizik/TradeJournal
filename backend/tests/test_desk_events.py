"""Known events on the desk (app/engine/desk_events.py, GET /copilot/desk/events, the desk chart's ``events``): the
7-trading-day window, the amber case of a held option expiring on or after the report, no tag without a known date,
no tag for a ticker he does not follow, one batched cached read, and the chart's earnings and macro markers. Every
date and price is invented."""

from __future__ import annotations

from datetime import date, datetime

import pytest
from sqlmodel import Session

from app.engine import desk_events
from app.engine.chart_math import ET
from app.engine.symbol_info_tradier import SymbolEvents
from app.models import DayJournalEntry
from tests.test_copilot_desk import desk  # noqa: F401  (the desk app over the shared fixtures)
from tests.test_copilot_plans import engine, quotes  # noqa: F401  (fixtures)
from tests.test_today import clock, marks  # noqa: F401  (fixtures)

WED = date(2026, 10, 21)  # the shared desk clock's day
CLOSED = ["2026-11-26"]  # Thanksgiving


def upcoming(day: str, status: str = "confirmed") -> dict:
    return {"date": day, "status": status, "label": "Q3 FY2026"}


# ------------------------------------------------------------------ the window


def test_trading_days_skip_weekends_and_closures():
    assert desk_events.trading_days_until(WED, WED, CLOSED) == 0
    assert desk_events.trading_days_until(WED, date(2026, 10, 23), CLOSED) == 2   # Fri
    assert desk_events.trading_days_until(WED, date(2026, 10, 26), CLOSED) == 3   # next Mon: the weekend does not count
    assert desk_events.trading_days_until(date(2026, 11, 24), date(2026, 11, 27), CLOSED) == 2  # Thanksgiving skipped
    assert desk_events.trading_days_until(WED, date(2026, 10, 20), CLOSED) is None


def test_grey_tag_only_within_seven_trading_days():
    seventh = desk_events.tag("NVDA", upcoming("2026-10-30"), WED, [], CLOSED)  # Fri next week: 7 trading days
    assert seventh == {"symbol": "NVDA", "date": "2026-10-30", "status": "confirmed", "trading_days": 7,
                       "label": "ER 10/30", "tone": "grey", "through": []}
    assert desk_events.tag("NVDA", upcoming("2026-11-02"), WED, [], CLOSED) is None  # the 8th: no tag
    assert desk_events.tag("NVDA", upcoming("2026-10-22"), WED, [], CLOSED)["label"] == "ER Thu"
    assert desk_events.tag("NVDA", upcoming("2026-10-21"), WED, [], CLOSED)["label"] == "ER today"
    assert desk_events.tag("NVDA", upcoming("2026-10-22", "estimated"), WED, [], CLOSED)["label"] == "ER Thu?"


def test_amber_when_a_held_option_expires_on_or_after_the_report():
    report = upcoming("2026-10-22")  # Thu
    before = desk_events.tag("AMD", report, WED, [date(2026, 10, 21)], CLOSED)
    assert before["tone"] == "grey" and before["through"] == []  # expires before the report: no event risk inside it
    same_day = desk_events.tag("AMD", report, WED, [date(2026, 10, 22)], CLOSED)
    assert same_day["tone"] == "amber" and same_day["through"] == ["2026-10-22"]  # the report's time of day is unknown
    after = desk_events.tag("AMD", report, WED, [date(2026, 10, 21), date(2026, 10, 23)], CLOSED)
    assert after["tone"] == "amber" and after["through"] == ["2026-10-23"]
    # A report weeks out is still amber when a held contract lives through it, though past the grey window.
    far = desk_events.tag("AMD", upcoming("2026-11-19"), WED, [date(2026, 12, 18)], CLOSED)
    assert far["tone"] == "amber" and far["label"] == "ER 11/19" and far["trading_days"] > desk_events.WINDOW


def test_unknown_or_past_dates_show_nothing():
    assert desk_events.tag("CRWV", None, WED, [date(2026, 12, 18)], CLOSED) is None
    assert desk_events.tag("CRWV", {"date": None}, WED, [date(2026, 12, 18)], CLOSED) is None
    assert desk_events.tag("CRWV", upcoming("2026-10-20"), WED, [date(2026, 12, 18)], CLOSED) is None


def test_tags_leave_out_hidden_tickers_funds_and_unknown_dates():
    asked = []

    def read(symbols, today):
        asked.append(list(symbols))
        return {"NVDA": {"state": "ready", "next": upcoming("2026-10-22")},
                "APLD": {"state": "ready", "next": upcoming("2026-10-23")},
                "MU": {"state": "none", "next": None},
                "CRWV": {"state": "loading", "next": None}}

    out = desk_events.tags(["nvda", "APLD", "MU", "SPY", "CRWV", "NVDA", ""], {"APLD": [date(2026, 10, 23)]}, WED, {"NVDA"}, read)
    assert asked == [["APLD", "MU", "CRWV"]]  # one read for every symbol; the hidden one and the fund never asked
    assert out["state"] == "ok" and set(out["rows"]) == {"APLD"} and out["rows"]["APLD"]["tone"] == "amber"
    assert out["loading"] is True  # CRWV's calendar is on its way: read again
    assert desk_events.tags([], {}, WED, set(), read)["rows"] == {} and len(asked) == 1
    broken = desk_events.tags(["APLD"], {}, WED, set(), lambda *a: (_ for _ in ()).throw(RuntimeError("down")))
    assert broken["state"] == "unavailable" and broken["rows"] == {}


def test_held_pairs_parse_and_skip_bad_ones():
    assert desk_events.parse_held("aapl:2026-11-20, TSLA:2026-11-27,bad,X:soon,AAPL:2026-12-18") == {
        "AAPL": [date(2026, 11, 20), date(2026, 12, 18)], "TSLA": [date(2026, 11, 27)]}


def test_one_batched_read_is_kept_for_hours(tmp_path):
    """The tags ride the earnings cache: one batched provider read for all the symbols, then none for 12 hours."""
    seconds = [1_000_000.0]
    queued = []
    events = SymbolEvents(root=tmp_path, clock=lambda: seconds[0], spawn=queued.append)
    calls = []

    def fake_read(dataset, symbols):
        calls.append((dataset, tuple(symbols)))
        return {"NVDA": [{"date": "2026-10-22", "status": "confirmed", "fiscal_year": 2026, "fiscal_quarter": 3, "event": "x"}],
                "AMD": [{"date": "2026-10-27", "status": "estimated", "fiscal_year": 2026, "fiscal_quarter": 3, "event": "x"}]}

    events._read = fake_read
    read = lambda symbols, day: events.chart_earnings(symbols, [], day)  # noqa: E731
    import app.engine.symbol_info_tradier as module
    original = module.tradier.tradier_configured
    module.tradier.tradier_configured = lambda: True
    try:
        first = desk_events.tags(["NVDA", "AMD"], {}, WED, set(), read)
        assert first["rows"] == {} and first["loading"] is True and not calls  # never a read in the request
        queued.pop()()  # the one background refresh
        assert calls == [("calendars", ("NVDA", "AMD"))]
        seconds[0] += 6 * 3600
        later = desk_events.tags(["NVDA", "AMD"], {}, WED, set(), read)
        assert later["rows"]["NVDA"]["label"] == "ER Thu" and later["rows"]["AMD"]["label"] == "ER Tue?"
        assert later["loading"] is False and not queued and len(calls) == 1
    finally:
        module.tradier.tradier_configured = original


# ------------------------------------------------------------------ the route


def test_route_tags_followed_rows_only(desk, clock, engine, monkeypatch):  # noqa: F811
    seen = []

    def read(symbols, today):
        seen.append((list(symbols), today))
        return {s: {"state": "ready", "next": upcoming("2026-10-23")} for s in symbols}

    monkeypatch.setattr(desk_events, "_earnings", read)
    with Session(engine) as db:
        db.add(DayJournalEntry(operation_id="hide-CRWV", day=WED, kind="follow", symbol="CRWV", text="Not following"))
        db.commit()
    body = desk.get("/copilot/desk/events", params={"symbols": "APLD,CRWV,MU", "held": "APLD:2026-10-23,MU:2026-10-22"}).json()
    assert seen == [(["APLD", "MU"], WED)]
    assert body["rows"]["APLD"]["tone"] == "amber" and body["rows"]["MU"]["tone"] == "grey" and "CRWV" not in body["rows"]
    assert body["note"].startswith("Time of day not published")


# ------------------------------------------------------------------ the chart


def test_chart_events_next_last_and_implied_move(monkeypatch):
    now = datetime(2026, 10, 21, 14, 49, tzinfo=ET)
    block = {"state": "ready", "next": upcoming("2026-10-28"), "reports": [{"date": "2026-07-29", "label": "Q2 FY2026"}]}
    monkeypatch.setattr(desk_events, "implied_move", lambda symbol, report, spot, at: {
        "expiration": "2026-10-30", "move": 6.4, "percent": 0.052} if spot else None)
    out = desk_events.chart("AMD", WED, now, date(2026, 6, 23), 123.0, lambda s, d: {"AMD": block})
    assert out["macro"] == []  # macro days only on SPY, QQQ and IWM
    assert out["earnings"]["next"] == {"date": "2026-10-28", "status": "confirmed", "label": "Q3 FY2026",
                                       "implied": {"expiration": "2026-10-30", "move": 6.4, "percent": 0.052}}
    assert out["earnings"]["last"] == {"date": "2026-07-29", "label": "Q2 FY2026"}
    unknown = desk_events.chart("AMD", WED, now, None, 123.0, lambda s, d: {"AMD": {"state": "none", "next": None, "reports": []}})
    assert unknown["earnings"] is None
    no_quote = desk_events.chart("AMD", WED, now, None, None, lambda s, d: {"AMD": block})
    assert no_quote["earnings"]["next"]["implied"] is None


def test_macro_days_only_on_index_etfs(monkeypatch):
    now = datetime(2026, 10, 21, 14, 49, tzinfo=ET)
    monkeypatch.setattr(desk_events, "_macro", lambda: {"market_closed": [], "events": [
        {"date": "2026-09-11", "time": "08:30", "kind": "cpi", "name": "CPI (Aug 2026)"},
        {"date": "2026-10-28", "time": "14:00", "kind": "fomc", "name": "FOMC statement"},
        {"date": "2026-11-06", "time": "08:30", "kind": "jobs", "name": "Jobs report (Oct 2026)"},
        {"date": "2026-12-09", "time": "14:00", "kind": "fomc", "name": "FOMC statement"}]})
    never = lambda *a: pytest.fail("a fund has no earnings read")  # noqa: E731
    spy = desk_events.chart("SPY", WED, now, date(2026, 9, 1), 600.0, never)
    assert [e["kind"] for e in spy["macro"]] == ["cpi", "fomc", "jobs"] and spy["earnings"] is None
    assert desk_events.chart("NVDA", WED, now, date(2026, 9, 1), 1.0, lambda s, d: {})["macro"] == []
