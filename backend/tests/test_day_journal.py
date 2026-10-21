from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.database import get_session
from app.engine import day_journal
from app.models import Account, DayJournalEntry, Trade, TradeCapture, TradeCaptureNote
from app.routers.day_journal import router as day_journal_router
from app.routers.daily_review import router as daily_review_router

DAY = date(2026, 9, 30)


@pytest.fixture
def journal():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)

    def override():
        with Session(engine) as session:
            yield session

    app = FastAPI()
    app.include_router(day_journal_router, prefix="/day-journal")
    app.include_router(daily_review_router, prefix="/daily-review")
    app.dependency_overrides[get_session] = override
    with TestClient(app) as client:
        yield client, engine
    app.dependency_overrides.clear()
    engine.dispose()


def entry(operation_id="op-1", **values):
    return {"operation_id": operation_id, "kind": "outlook", "text": "SPY holds 580 into the open",
            "symbol": "spy", **values}


def test_day_journal_appends_and_idempotent_retry_conflicts_only_on_changed_payload(journal):
    client, _ = journal
    first = client.post(f"/day-journal/{DAY}/entries", json=entry())
    assert first.status_code == 200, first.text
    saved = first.json()
    assert saved["symbol"] == "SPY" and saved["actor"] == "owner" and saved["created_at"].endswith("Z")
    assert client.post(f"/day-journal/{DAY}/entries", json=entry()).json() == saved
    assert client.post(f"/day-journal/2026-10-01/entries", json=entry()).status_code == 409
    assert client.post(f"/day-journal/{DAY}/entries", json=entry(text="changed")).status_code == 409
    assert client.post(f"/day-journal/{DAY}/entries", json={**entry(), "created_at": "2026-09-30T12:00:00Z"}).status_code == 422
    assert client.get(f"/day-journal/{DAY}").json()["entries"] == [saved]


def test_day_journal_rejects_invalid_day_symbol_and_empty_text(journal):
    client, _ = journal
    assert client.post("/day-journal/not-a-day/entries", json=entry()).status_code == 422
    assert client.post(f"/day-journal/{DAY}/entries", json=entry(symbol="SPY;DROP")).status_code == 422
    assert client.post(f"/day-journal/{DAY}/entries", json=entry(text="  ")).status_code == 422


@pytest.mark.parametrize("competing_text, expected", [
    ("SPY holds 580 into the open", "retry"),
    ("Different competing payload", "conflict"),
])
def test_append_recovers_integrity_error_during_autoflush(journal, monkeypatch, competing_text, expected):
    _, engine = journal
    from app.engine.day_journal import EntryConflict

    with Session(engine) as session:
        original_add = session.add
        inserted = False

        def add_with_competing_writer(row, *args, **kwargs):
            nonlocal inserted
            if isinstance(row, DayJournalEntry) and row.operation_id == "race-op" and not inserted:
                inserted = True
                with Session(engine) as competing:
                    competing.add(DayJournalEntry(operation_id="race-op", day=DAY, kind="outlook",
                        text=competing_text, actor="owner"))
                    competing.commit()
            return original_add(row, *args, **kwargs)

        monkeypatch.setattr(session, "add", add_with_competing_writer)
        if expected == "conflict":
            with pytest.raises(EntryConflict, match="different entry"):
                day_journal.append(session, day=DAY, operation_id="race-op", kind="outlook",
                                   text="SPY holds 580 into the open")
        else:
            result = day_journal.append(session, day=DAY, operation_id="race-op", kind="outlook",
                                        text="SPY holds 580 into the open")
            assert result.text == competing_text
            assert len(session.exec(select(DayJournalEntry)).all()) == 1


def test_calendar_lists_thought_days_and_no_trade_review_accepts_owner_thoughts(journal, monkeypatch):
    client, engine = journal
    client.post(f"/day-journal/{DAY}/entries", json=entry())
    seen = {}

    def context(session, day, trades, **kwargs):
        seen["day_context"] = {"owner_timeline": [{"id": "entry-id", "retrospective": False}]}
        return seen["day_context"]

    from app.ai import review_context, plan_runner
    monkeypatch.setattr(review_context, "build", context)
    answer = {"summary": "Saved outlook reviewed.", "day_grade": "B: documented the plan", "key_takeaways": [],
              "best_trade": {"trade_id": None, "ticker": None, "reason": "No trade"},
              "worst_trade": {"trade_id": None, "ticker": None, "reason": "No trade"}, "patterns": [],
              "next_session_rules": [], "rules_check": [], "vs_baseline": [], "market_read": "No trade recorded",
              "plan_vs_execution": [], "data_gaps": [],
              "expectation_checks": [{"entry_id": "entry-id", "expected": "SPY holds 580", "observed": "No source data",
                                      "assessment": "unresolved", "evidence": "entry-id; market evidence unavailable"}]}
    answer["expectation_checks"].append({"entry_id": "not-in-context", "expected": "invented", "observed": "invented",
                                         "assessment": "supported", "evidence": "unverified"})
    monkeypatch.setattr(plan_runner, "ask", lambda *_args, **_kwargs: type("Answer", (), {
        "data": dict(answer), "author": "test", "input_tokens": 0, "output_tokens": 0,
        "api_equivalent_usd": 0, "seconds": 0})())
    calendar = client.get("/daily-review").json()
    assert calendar[0]["day"] == DAY.isoformat() and calendar[0]["trade_count"] == 0
    generated = client.post("/daily-review", json={"day": DAY.isoformat(), "trade_ids": []})
    assert generated.status_code == 200, generated.text
    assert generated.json()["trade_count"] == 0
    assert generated.json()["review"]["owner_thoughts_included"] is True
    assert generated.json()["review"]["expectation_checks"][0]["assessment"] == "unresolved"
    assert len(generated.json()["review"]["expectation_checks"]) == 1
    assert any("not in this day's saved timeline" in gap for gap in generated.json()["review"]["data_gaps"])
    generated_at = generated.json()["generated_at"]
    later = client.post(f"/day-journal/{DAY}/entries", json=entry("op-2", kind="update", text="No longer expecting a flat open"))
    assert later.status_code == 200
    saved_review = client.get(f"/daily-review/{DAY}").json()
    assert saved_review["review"]["source_data_stale"] is True
    assert saved_review["review"]["source_data_stale_reason"] == "Owner thoughts changed after this review's input snapshot."
    assert saved_review["generated_at"] == generated_at
    assert client.post("/daily-review", json={"day": "2026-09-29", "trade_ids": []}).status_code == 404


def test_daily_review_rejects_a_foreign_day_trade_selection(journal):
    client, engine = journal
    with Session(engine) as session:
        session.add(Account(id=UUID(int=56), name="IRA", type="roth_ira", last4="1234"))
        session.add(Trade(id=UUID(int=1234), account_id=UUID(int=56), ticker="SPY", instrument_type="option",
                          contracts=1, avg_entry_premium=1, total_premium_paid=1,
                          realized_pnl=Decimal("0"), pnl_pct=None, opened_at=datetime(2026, 9, 29, 10),
                          closed_at=datetime(2026, 9, 29, 11), status="closed"))
        session.commit()
    response = client.post("/daily-review", json={"day": DAY.isoformat(), "trade_ids": [str(UUID(int=1234))]})
    assert response.status_code == 400 and "belong to the review day" in response.json()["detail"]


def test_review_generation_fails_if_it_omits_a_saved_outlook_check(journal, monkeypatch):
    _, engine = journal
    from app.ai import daily_reviewer, plan_runner, review_context

    monkeypatch.setattr(review_context, "build", lambda *_, **__: {"owner_timeline": [{"id": "outlook-1", "kind": "outlook"}]})
    incomplete = {"summary": "A summary", "day_grade": "B: clear plan", "key_takeaways": [],
                  "best_trade": {"trade_id": None, "ticker": None, "reason": "No trade"},
                  "worst_trade": {"trade_id": None, "ticker": None, "reason": "No trade"}, "patterns": [],
                  "next_session_rules": [], "rules_check": [], "vs_baseline": [], "data_gaps": [],
                  "market_read": "Unclear", "plan_vs_execution": []}
    monkeypatch.setattr(plan_runner, "ask", lambda *_args, **_kwargs: type("Answer", (), {
        "data": dict(incomplete), "author": "test", "input_tokens": 0, "output_tokens": 0,
        "api_equivalent_usd": 0, "seconds": 0})())
    with Session(engine) as session, pytest.raises(ValueError, match="expectation_checks"):
        daily_reviewer.review_trading_day(DAY.isoformat(), [], {}, session)


def test_review_context_preserves_creation_time_and_retrospective_provenance(journal):
    _, engine = journal
    from app.ai import review_context

    with Session(engine) as session:
        row = DayJournalEntry(operation_id="retro", day=DAY, kind="update", text="Changed my mind",
                              created_at=datetime(2026, 10, 1, 12, 0), actor="owner")
        prior = DayJournalEntry(operation_id="prior-evening", day=DAY, kind="outlook", text="Plan for tomorrow",
                                created_at=datetime(2026, 9, 29, 20, 0), actor="owner")
        session.add_all([row, prior])
        capture = TradeCapture(id=UUID(int=990), client_id="late-plan", received_at=datetime(2026, 10, 1, 12, 1),
                               account_id=UUID(int=10), account_label="IRA", underlying="SPY", side="buy_calls",
                               instrument="option", mode="discretionary", context_state="captured", image_state="unavailable")
        session.add(capture)
        session.commit()
        session.add(TradeCaptureNote(capture_id=capture.id, kind="note", text="Later thought",
                                     created_at=datetime(2026, 10, 1, 12, 2)))
        session.commit()
        timeline = review_context.owner_timeline(session, DAY)
        plans = review_context.plans(session, date(2026, 10, 1), [])
    assert timeline[0]["retrospective"] is False
    assert timeline[0]["created_at"] == "2026-09-29T20:00:00Z"
    assert timeline[1]["retrospective"] is True and timeline[1]["created_at"] == "2026-10-01T12:00:00Z"
    assert plans["not_traded"][0]["later_notes"] == [{"text": "Later thought", "created_at": "2026-10-01T12:02:00Z", "kind": "note"}]

