"""The monthly review: its statistics, context and gaps, the nightly run's
first-of-month trigger and the routes. Claude Code is a fake; nothing reaches a network."""

from datetime import date, datetime, timedelta
from decimal import Decimal
import json
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.ai import monthly_reviewer, plan_runner
from app.database import get_session
from app.jobs import plan_reviews
from app.models import Account, CaptureLink, DailyReviewRecord, Fill, FillMarketContext, MonthlyReviewRecord, Trade, TradeFill
from app.routers.monthly_review import router
from tests.test_plan_reviews import FAKE_CLAUDE, Fake  # noqa: F401  (the same fake Claude Code)

ACCOUNT = UUID(int=1)
MONTHLY = {"summary": "Mornings paid, afternoons leaked.", "month_grade": "B: consistent size", "edge": [], "leaks": [],
           "recurring_patterns": [], "rules_scorecard": [], "last_commitment_check": None,
           "one_commitment": "No entries after 15:00", "vs_last_month": [], "data_gaps": []}


@pytest.fixture
def engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Account(id=ACCOUNT, name="Individual", type="individual", last4="1113"))
        session.commit()
    yield engine
    engine.dispose()


@pytest.fixture
def fake(tmp_path, monkeypatch):
    import stat

    binary = tmp_path / "claude"
    binary.write_text(FAKE_CLAUDE)
    binary.chmod(binary.stat().st_mode | stat.S_IEXEC)
    fake = Fake(tmp_path)
    fake.set(answer=MONTHLY)
    for key, value in {"TJ_CLAUDE_BIN": str(binary), "TJ_CLAUDE_CONFIG_DIR": str(tmp_path / "config"),
                       "TJ_PLAN_REVIEW_DIR": str(tmp_path / "state"), "CLAUDE_CODE_OAUTH_TOKEN": "plan-token"}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("AI_REVIEW_BACKEND", raising=False)
    monkeypatch.setattr(monthly_reviewer, "_spy_days", lambda month, gaps: {date(2026, 9, 1): "SPY up >0.5%", date(2026, 9, 2): "SPY down >0.5%"})
    plan_runner._checked.clear()
    yield fake
    plan_runner._checked.clear()


def trade(number, opened, pnl, *, ticker="SPY", premium=200, hold=20, closed=None):
    return Trade(id=UUID(int=100 + number), account_id=ACCOUNT, ticker=ticker, instrument_type="option", option_type="call",
                 contracts=1, avg_entry_premium=2, total_premium_paid=premium, realized_pnl=Decimal(str(pnl)), pnl_pct=None,
                 opened_at=opened, closed_at=closed or opened + timedelta(minutes=10), status="closed", hold_duration_mins=hold)


def seed(engine, *rows):
    with Session(engine) as session:
        session.add_all(rows)
        session.commit()


def test_stats_break_the_month_down_and_name_their_gaps(engine, fake):
    trades = [trade(1, datetime(2026, 9, 1, 9, 40), 120), trade(2, datetime(2026, 9, 1, 9, 50), 80),
              trade(3, datetime(2026, 9, 2, 15, 10), -150, ticker="NVDA"), trade(4, datetime(2026, 9, 2, 15, 20), -90, ticker="NVDA"),
              trade(5, datetime(2026, 8, 29, 10, 0), 500)]  # August: not this month
    entry = Fill(id=UUID(int=501), account_id=ACCOUNT, raw_email_id="mail-1", ticker="SPY", instrument_type="option", side="buy_to_open",
                 contracts=1, price=2, executed_at=datetime(2026, 9, 1, 9, 40), option_type="call", strike=580, expiration=date(2026, 9, 2))
    seed(engine, *trades, entry, TradeFill(trade_id=UUID(int=101), fill_id=UUID(int=501), role="entry"),
         FillMarketContext(fill_id=UUID(int=501), data_source="alpaca", fetched_at=datetime(2026, 9, 1, 20), is_chase_entry=1, dte_bucket="0dte"),
         CaptureLink(capture_id=UUID(int=900), account_id=ACCOUNT, source_key="mail-1", method="manual"))
    gaps: list[str] = []
    with Session(engine) as session:
        stats = monthly_reviewer.month_stats(session, "2026-09", gaps)
    overall = stats["overall"]
    assert (overall["trades"], overall["pnl"], overall["win_rate"], overall["trading_days"]) == (4, -40.0, 0.5, 2)
    assert overall["profit_factor"] == 0.83 and overall["worst_day"] == {"day": "2026-09-02", "pnl": -240.0}
    by = stats["by"]
    assert [(row["group"], row["pnl"]) for row in by["ticker"]] == [("NVDA", -240.0), ("SPY", 200.0)]
    assert [row["group"] for row in by["entry_time"]] == ["15:00 and later", "09:30-10:00"]
    assert {row["group"]: row["trades"] for row in by["spy_that_day"]} == {"SPY down >0.5%": 2, "SPY up >0.5%": 2}
    assert by["had_captured_plan"] == [{"group": "no", "trades": 3, "pnl": -160.0, "win_rate": 0.333, "avg_win": 80.0, "avg_loss": -120.0}]
    assert by["chase_entry"] == []  # one trade with context is below the two-trade floor
    assert gaps == ["Entry market context for 1 of 4 trades, so flag and days-to-expiry breakdowns cover only those"]


def test_context_carries_last_month_its_commitment_and_the_daily_rules(engine, fake):
    seed(engine, trade(1, datetime(2026, 9, 1, 9, 40), 120), trade(2, datetime(2026, 8, 3, 10, 0), -50),
         MonthlyReviewRecord(month="2026-08", review_json=json.dumps({**MONTHLY, "one_commitment": "Max 2 contracts"})),
         DailyReviewRecord(day=date(2026, 9, 1), trade_count=1, review_json=json.dumps({
             "day_grade": "B: fine", "patterns": ["Waited for the reclaim"],
             "rules_check": [{"rule": "Max 2 contracts", "set_on": "2026-08-31", "result": "kept", "evidence": "1 contract"}]})))
    with Session(engine) as session:
        context = monthly_reviewer.build_context(session, "2026-09")
    assert context["last_month"]["pnl"] == -50.0
    assert context["last_commitment"] == {"month": "2026-08", "commitment": "Max 2 contracts", "grade": "B: consistent size"}
    assert context["daily_reviews"]["grades"] == [{"day": "2026-09-01", "grade": "B"}]
    assert context["daily_reviews"]["rules_checked"] == [{"rule": "Max 2 contracts", "kept": 1}]
    with Session(engine) as session, pytest.raises(LookupError):
        monthly_reviewer.build_context(session, "2026-07")


def test_the_first_run_of_a_month_writes_last_months_review_once(engine, fake, monkeypatch):
    from app.ai import review_context

    monkeypatch.setattr(review_context, "build", lambda session, day, trades: {"gaps": []})
    seed(engine, trade(1, datetime(2026, 9, 30, 10, 0), 75))
    with Session(engine) as session:
        assert plan_reviews.plan_month(session, date(2026, 9, 30)) is None  # September is not over
        assert plan_reviews.plan_month(session, date(2026, 10, 1)) == "2026-09"
        fake.set(answer={**MONTHLY})
        # The latest day (Sep 30) also needs its daily review; the fake answers both with the monthly shape, so the
        # daily one fails its required fields and is recorded, while the month is written.
        status = plan_reviews.run(session, today=date(2026, 10, 1))
    assert {item["day"]: item["reason"] for item in status["planned"]} == {"2026-09-30": "latest", "2026-09": "monthly"}
    assert [item["day"] for item in status["written"]] == ["2026-09"]
    assert status["written"][0]["grade"] == "B: consistent size"
    with Session(engine) as session:
        assert plan_reviews.plan_month(session, date(2026, 10, 2)) is None  # written once


@pytest.fixture
def client(engine):
    def override():
        with Session(engine) as session:
            yield session

    app = FastAPI()
    app.include_router(router, prefix="/monthly-review")
    app.dependency_overrides[get_session] = override
    with TestClient(app) as test_client:
        yield test_client


def test_routes_list_months_generate_and_read(engine, fake, client, monkeypatch):
    seed(engine, trade(1, datetime(2026, 9, 1, 9, 40), 120), trade(2, datetime(2026, 8, 3, 10, 0), -50))
    assert [(row["month"], row["closed_trades"], row["saved"]) for row in client.get("/monthly-review").json()] == [
        ("2026-09", 1, False), ("2026-08", 1, False)]
    response = client.post("/monthly-review", json={"month": "2026-09"})
    assert response.status_code == 200 and response.json()["review"]["generated_by"].endswith("on the Claude plan")
    assert client.get("/monthly-review/2026-09").json()["review"]["one_commitment"] == "No entries after 15:00"
    assert client.get("/monthly-review").json()[0]["grade"] == "B: consistent size"
    assert client.post("/monthly-review", json={"month": "2026-07"}).status_code == 404
    assert client.post("/monthly-review", json={"month": "Sept"}).status_code == 400
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN")
    assert client.post("/monthly-review", json={"month": "2026-09"}).status_code == 503
