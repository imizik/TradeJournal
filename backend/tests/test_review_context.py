"""The Daily Review's day context: the trader's plans, tags, levels, alerts and
option walls from the database, the market and per-ticker parts from stubbed
providers, and a gap for every part that is missing. Nothing reaches a network."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import json
from uuid import UUID

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.ai import review_context
from app.engine import options_recorder
from app.models import (Account, CaptureLink, ChartSettingsRecord, DayJournalEntry, Fill, LevelAlert, LevelAlertEvent, OptionChainSnapshot, Tag,
                        Trade, TradeCapture, TradeCaptureNote, TradeFill, TradeTag)

ACCOUNT = UUID(int=1)
DAY = date(2026, 9, 30)


@pytest.fixture
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Account(id=ACCOUNT, name="Individual", type="individual", last4="1113"))
        db.commit()
        yield db
    engine.dispose()


@pytest.fixture
def offline(monkeypatch):
    """Providers stubbed: the tests below say what each returns."""
    calls = {}
    def daily(day, symbols):
        calls["daily_symbols"] = symbols
        return calls.setdefault("daily", {
        "SPY": {"change_pct": -0.5, "gap_pct": 0.1, "open_to_close_pct": -0.6, "close_in_range": 0.2, "range_vs_20d": 1.4, "close": 580.0},
        "NVDA": {"change_pct": 1.5, "gap_pct": 0.5, "open_to_close_pct": 1.0, "close_in_range": 0.9, "range_vs_20d": 1.1, "close": 180.0},
        "SMH": {"change_pct": 0.5, "gap_pct": 0.2, "open_to_close_pct": 0.3, "close_in_range": 0.6, "range_vs_20d": 1.0, "close": 300.0}})
    monkeypatch.setattr(review_context, "daily_moves", daily)
    monkeypatch.setattr(review_context, "intraday_shape", lambda day: {"SPY": {"trend_efficiency": 0.12, "close_vs_vwap_pct": -0.3}})
    monkeypatch.setattr(review_context, "gauges", lambda day: {"vix": {"close": 21.4, "change": 2.1}, "source": "yfinance (unofficial)"})
    monkeypatch.setattr(review_context, "_headlines", lambda day, symbols, gaps: {"NVDA": ["10:02 Nvidia wins order"]})
    monkeypatch.setattr(review_context, "company_facts", lambda symbols, day: {symbol: {
        "sector": "Technology", "sector_state": "ready",
        "earnings": {"state": "ready", "next": {"date": "2026-10-02", "status": "confirmed", "label": "Q3"}, "reports": [], "time_note": "no time"}}
        for symbol in symbols})
    return calls


def trade(number, ticker="NVDA", opened=datetime(2026, 9, 30, 10, 5)):
    return Trade(id=UUID(int=100 + number), account_id=ACCOUNT, ticker=ticker, instrument_type="option", option_type="call",
                 strike=Decimal("185"), contracts=2, avg_entry_premium=2, total_premium_paid=400, realized_pnl=Decimal("50"),
                 pnl_pct=None, opened_at=opened, closed_at=datetime(2026, 9, 30, 10, 40), status="closed")


def fill(number, trade_id):
    return Fill(id=UUID(int=500 + number), account_id=ACCOUNT, raw_email_id=f"mail-{number}", ticker="NVDA", instrument_type="option",
                side="buy_to_open", contracts=2, price=2, executed_at=datetime(2026, 9, 30, 10, 5), option_type="call", strike=185,
                expiration=date(2026, 10, 2)), TradeFill(trade_id=trade_id, fill_id=UUID(int=500 + number), role="entry")


def capture(number, received, **values):
    return TradeCapture(id=UUID(int=900 + number), client_id=f"c{number}", received_at=received, account_id=ACCOUNT,
                        account_label="Individual", underlying=values.pop("underlying", "NVDA"), side="buy_calls", instrument="option",
                        mode="discretionary", context_state="captured", image_state="unavailable", **values)


def test_plans_link_to_their_trade_with_minutes_before_entry_and_untraded_plans_are_kept(session):
    traded = trade(1)
    entry, link_row = fill(1, traded.id)
    session.add_all([traded, entry, link_row,
                     # 10:00 New York = 14:00 UTC, five minutes before the 10:05 entry.
                     capture(1, datetime(2026, 9, 30, 14, 0), wording="Calls if 182 holds", quantity=2, strike=185.0),
                     CaptureLink(capture_id=UUID(int=901), account_id=ACCOUNT, source_key="mail-1", method="manual"),
                     TradeCaptureNote(capture_id=UUID(int=901), kind="note", text="Held too long", created_at=datetime(2026, 9, 30, 14, 30)),
                     capture(2, datetime(2026, 9, 30, 15, 30), underlying="AMD", wording="AMD puts under 160", not_taken_at=datetime(2026, 9, 30, 18)),
                     # Captured today, linked to a trade on another day: traded, so not "not traded".
                     capture(3, datetime(2026, 9, 30, 21, 0), underlying="MU", wording="MU calls Monday"),
                     CaptureLink(capture_id=UUID(int=903), account_id=ACCOUNT, source_key="mail-other-day", method="manual")])
    session.commit()
    plans = review_context.plans(session, DAY, [traded])
    linked = plans["by_trade"][str(traded.id)][0]
    assert linked["plan"] == "Calls if 182 holds" and linked["minutes_before_entry"] == 5
    assert linked["later_notes"] == [{"text": "Held too long", "created_at": "2026-09-30T14:30:00Z", "kind": "note"}]
    assert linked["captured_at"] == "2026-09-30 10:00"
    assert plans["not_traded"] == [{"captured_at": "2026-09-30 11:30", "underlying": "AMD", "side": "buy_calls", "plan": "AMD puts under 160",
                                    "marked_not_taken": True}]


def test_owner_thoughts_join_the_day_context_and_their_symbols_get_market_context(session, offline):
    session.add(DayJournalEntry(operation_id="thought", day=DAY, kind="idea", text="NVDA relative strength holds",
                                symbol="NVDA", actor="owner", created_at=datetime(2026, 9, 30, 15, 0)))
    session.commit()
    context = review_context.build(session, DAY, [])
    assert context["owner_timeline"][0]["text"] == "NVDA relative strength holds"
    assert context["owner_timeline"][0]["retrospective"] is False
    assert "NVDA" in offline["daily_symbols"]


def test_owner_timeline_keeps_first_morning_entry_and_latest_entries_when_capped(session, offline):
    start = datetime(2026, 9, 30, 12, 0)
    session.add_all([
        DayJournalEntry(operation_id=f"thought-{index}", day=DAY,
                        kind="outlook" if index == 0 else "update",
                        text="Morning outlook" if index == 0 else f"Update {index}",
                        created_at=start + timedelta(minutes=index))
        for index in range(61)
    ])
    session.commit()

    context = review_context.build(session, DAY, [])

    timeline = context["owner_timeline"]
    assert len(timeline) == 50
    assert timeline[0]["text"] == "Morning outlook"
    assert [row["text"] for row in timeline[1:]] == [f"Update {index}" for index in range(12, 61)]
    assert [row["created_at"] for row in timeline] == sorted(row["created_at"] for row in timeline)
    assert context["owner_timeline_truncated_count"] == 11
    assert "first entry and latest 49 of 61 entries" in " ".join(context["gaps"])


def test_levels_alerts_tags_and_open_interest_walls(session):
    traded = trade(1)
    session.add_all([traded, Tag(id=UUID(int=7), name="ORB", source="manual"), TradeTag(trade_id=traded.id, tag_id=UUID(int=7)),
                     ChartSettingsRecord(name="default", data_json=json.dumps({"levels": {"NVDA": [{"price": 182.5, "label": "PDH"}, {"price": 178}]}})),
                     LevelAlert(id=UUID(int=8), symbol="NVDA", price=182.5, created_on=DAY, condition="crosses", session="regular", direction="up",
                                source_kind="level", label="PDH"),
                     LevelAlertEvent(alert_id=UUID(int=8), generation=1, level=182.5, price=182.6, source="stream",
                                     event_at=datetime(2026, 9, 30, 13, 58, tzinfo=timezone.utc).replace(tzinfo=None)),
                     OptionChainSnapshot(session_date=date(2026, 9, 29), underlying="NVDA", expiration=date(2026, 10, 2), provider="tradier",
                                         captured_at=datetime(2026, 9, 29, 21), contracts=4, data_json=json.dumps({
                                             # The recorder's own columns and side codes.
                                             "columns": options_recorder.COLUMNS,
                                             "rows": [["NVDA", "C", 190, 50000, 1], ["NVDA", "C", 185, 20000, 1],
                                                      ["NVDA", "P", 175, 30000, 1], ["NVDA", "C", 260, 99999, 1],
                                                      ["NVDA1", "C", 180, 999999, 1]]}))])  # an adjusted root is left out
    session.commit()
    assert review_context.tags(session, [traded]) == {str(traded.id): ["ORB"]}
    assert review_context.saved_levels(session, ["NVDA", "AMD"]) == {"NVDA": [{"price": 178, "label": None}, {"price": 182.5, "label": "PDH"}]}
    assert review_context.fired_alerts(session, DAY, ["NVDA"]) == {"NVDA": [{"at": "09:58", "level": 182.5, "price": 182.6, "label": "PDH", "condition": "crosses up"}]}
    walls = review_context.open_interest_walls(session, DAY, "NVDA", 180.0)
    assert walls["as_of_session"] == "2026-09-29"
    assert walls["call_walls"] == [{"strike": 190.0, "open_interest": 50000}, {"strike": 185.0, "open_interest": 20000}]  # 260 is too far
    assert walls["put_walls"] == [{"strike": 175.0, "open_interest": 30000}] and walls["put_call_oi"] == 0.43
    # A snapshot more than five days older than the day no longer describes it.
    assert review_context.open_interest_walls(session, date(2026, 10, 9), "NVDA", 180.0) is None


def test_build_puts_the_day_together_and_names_every_gap(session, offline, monkeypatch):
    traded = trade(1)
    session.add(traded)
    session.commit()
    context = review_context.build(session, DAY, [traded])
    nvda = context["tickers"]["NVDA"]
    assert (nvda["vs_spy_pct"], nvda["sector_etf"], nvda["vs_sector_pct"]) == (2.0, "SMH", 1.0)
    assert nvda["headlines"] == ["10:02 Nvidia wins order"] and nvda["earnings"]["next"]["days_after"] == 2
    assert context["market"]["indexes"]["SPY"]["close_in_range"] == 0.2
    assert context["market"]["volatility"]["vix"]["close"] == 21.4
    assert context["macro"] == {"events": [], "calendar": "FOMC, CPI and jobs reports only"}
    assert "No captured trade plans for this day" in context["gaps"] and "No tags on these trades" in context["gaps"]
    assert "No recent options snapshot for NVDA, so its open-interest walls are unknown" in context["gaps"]


def test_unavailable_tradier_data_is_a_named_gap_not_silence(session, offline, monkeypatch):
    monkeypatch.setattr(review_context, "company_facts", lambda symbols, day: {symbol: {
        "sector": None, "sector_state": "unavailable", "earnings": {"state": "unavailable", "next": None, "reports": []}} for symbol in symbols})
    traded = trade(1, ticker="TSLA")
    session.add(traded)
    session.commit()
    context = review_context.build(session, DAY, [traded])
    assert "Sector unavailable for TSLA, so its move against its sector is unknown" in context["gaps"]
    assert "Earnings dates unavailable for TSLA" in context["gaps"]
    assert "earnings" not in (context["tickers"] or {}).get("TSLA", {})


def test_a_failing_provider_is_a_gap_not_a_failed_review(session, offline, monkeypatch):
    def down(*_args):
        raise TimeoutError("feed down")

    monkeypatch.setattr(review_context, "daily_moves", down)
    monkeypatch.setattr(review_context, "intraday_shape", down)
    traded = trade(1)
    session.add(traded)
    session.commit()
    context = review_context.build(session, DAY, [traded])
    assert context["market"]["indexes"] is None and context["market"]["intraday"] is None
    assert any(gap.startswith("Daily bars unavailable") and "TimeoutError" in gap for gap in context["gaps"])


def test_the_macro_calendar_names_release_days_and_refuses_days_it_does_not_cover():
    assert review_context.macro_events(date(2026, 9, 15))["events"] == [
        {"when": "next trading day", "time_et": "14:00", "event": "FOMC decision with projections", "kind": "fomc"}]
    # Friday's next trading day is Monday: the Oct 2 jobs report is "today", and Friday Sep 11's CPI.
    assert review_context.macro_events(date(2026, 10, 9))["events"] == []
    assert [event["when"] for event in review_context.macro_events(date(2026, 10, 13))["events"]] == ["next trading day"]
    assert [event["kind"] for event in review_context.macro_events(date(2026, 9, 11))["events"]] == ["cpi"]
    # Holidays are skipped (Jan 9 2025 was a closure), and a release while the market is shut lands on the next open.
    assert [event["when"] for event in review_context.macro_events(date(2025, 1, 8))["events"]] == ["next trading day"]
    assert [event["when"] for event in review_context.macro_events(date(2026, 4, 2))["events"]] == ["before the next trading day (market closed)"]
    assert [event["kind"] for event in review_context.macro_events(date(2027, 1, 7))["events"]] == ["jobs"]
    assert [event["event"] for event in review_context.macro_events(date(2027, 1, 12))["events"]] == ["CPI (Dec 2026)"]
    assert review_context.macro_events(date(2027, 3, 25))["events"] == []
    with pytest.raises(LookupError):
        review_context.macro_events(date(2028, 1, 3))
    with pytest.raises(LookupError):
        review_context.macro_events(date(2024, 12, 31))
    calendar = json.loads(review_context.MACRO_FILE.read_text())
    dates = [event["date"] for event in calendar["events"]]
    assert dates == sorted(dates) and all(event["kind"] in {"fomc", "cpi", "jobs"} for event in calendar["events"])
    closed = calendar["market_closed"]
    assert closed == sorted(closed)
    assert all(date.fromisoformat(day).weekday() < 5 for day in closed)
    for kind in ("fomc", "cpi", "jobs"):
        assert len([day for day in dates if day.startswith("2027") and calendar["events"][dates.index(day)]["kind"] == kind]) >= 8


def test_semis_compare_with_smh_funds_have_no_sector_and_others_follow_their_sector():
    facts = {"META": {"sector": "Communication Services"}, "XYZ": {"sector": None}}
    assert review_context.sector_etfs(["NVDA", "SPY", "SPXW", "META", "XYZ"], facts) == {"NVDA": "SMH", "META": "XLC"}


def test_earnings_on_the_day_carry_the_unknown_time_of_day():
    view = {"state": "ready", "next": {"date": "2026-09-30", "status": "confirmed", "label": "Q3"}, "reports": [], "time_note": "Time of day not published."}
    assert review_context._earnings_near(view, DAY)["next"]["time_note"] == "Time of day not published."
    assert review_context._earnings_near({"state": "unavailable"}, DAY) is None


def test_a_review_during_the_session_says_its_numbers_are_intraday(session, offline, monkeypatch):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 9, 30, 13, 5, tzinfo=tz)

    monkeypatch.setattr(review_context, "datetime", Clock)
    traded = trade(1)
    session.add(traded)
    session.commit()
    context = review_context.build(session, DAY, [traded])
    assert context["market"]["partial_as_of"] == "13:05"
    assert any(gap.startswith("Reviewed during the session") for gap in context["gaps"])
