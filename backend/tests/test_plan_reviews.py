"""Daily reviews through the Anthropic API: the structured call, the review's history, the nightly run's choice of
days and its status. The Messages API is a scripted client; nothing here reaches Anthropic."""

from datetime import datetime
from decimal import Decimal
import json
import os
from pathlib import Path
from uuid import UUID

import anthropic
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.ai import api_runner, daily_reviewer
from app.database import get_session
from app.jobs import plan_reviews
from app.models import Account, DailyReviewRecord, DayJournalEntry, Trade
from app.routers.daily_review import router
from tests.fake_anthropic import FakeAnthropic, api_error, json_message, message, text

ACCOUNT = UUID(int=1)
ANSWER = {"summary": "Two trades, +$60.", "day_grade": "B: sized to plan", "key_takeaways": ["SPY 9:31 entry was on plan"],
          "best_trade": {"trade_id": None, "ticker": "SPY", "reason": "waited for the reclaim"},
          "worst_trade": {"trade_id": None, "ticker": "SPY", "reason": "chased"}, "patterns": [],
          "next_session_rules": ["Max 2 contracts"], "rules_check": [], "vs_baseline": [], "data_gaps": [],
          "expectation_checks": []}


class Fake:
    """The fake Messages API behind ``api_runner.ask``: every review call gets ``answer`` until told otherwise."""

    def __init__(self):
        self.client = FakeAnthropic([], default=self.reply(ANSWER))

    @staticmethod
    def reply(answer):
        return json_message(answer, input_tokens=1000, output_tokens=300)

    def set(self, answer=None, error=None):
        self.client.default = error if error is not None else self.reply(answer)

    @property
    def requests(self):
        return self.client.requests

    def __call__(self):
        return self.client.requests


@pytest.fixture
def fake_claude(tmp_path, monkeypatch):
    """A key on the backend and a scripted API behind it (the name is the old fixture's, kept for the tests that use it)."""
    fake = Fake()
    built = []
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    monkeypatch.delenv("TJ_PLAN_REVIEW_MODEL", raising=False)
    monkeypatch.setattr(api_runner.anthropic, "Anthropic", lambda **kwargs: built.append(kwargs) or fake.client)
    fake.built = built
    monkeypatch.setenv("TJ_PLAN_REVIEW_DIR", str(tmp_path / "state"))
    monkeypatch.delenv("AI_REVIEW_BACKEND", raising=False)
    # The day's market context reads providers; tests/test_review_context.py covers it offline.
    from app.ai import review_context

    monkeypatch.setattr(review_context, "build", lambda session, day, trades, **kwargs: {"gaps": ["stubbed in tests"]})
    # The monthly review has its own tests (tests/test_monthly_review.py); these runs are about the day.
    monkeypatch.setattr(plan_reviews, "plan_month", lambda session, today: None)
    yield fake


def trade(number, opened, closed=None, pnl="10", premium=100, status="closed"):
    return Trade(id=UUID(int=100 + number), account_id=ACCOUNT, ticker="SPY", instrument_type="option", contracts=1,
                 avg_entry_premium=premium, total_premium_paid=premium, realized_pnl=Decimal(pnl) if pnl is not None else None,
                 pnl_pct=None, opened_at=opened, closed_at=closed, status=status, hold_duration_mins=30)


@pytest.fixture
def engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Account(id=ACCOUNT, name="Individual", type="individual", last4="1113"))
        session.commit()
    yield engine
    engine.dispose()


def add(engine, *rows):
    with Session(engine) as session:
        session.add_all(rows)
        session.commit()


def review_record(day, **review):
    return DailyReviewRecord(day=datetime.fromisoformat(day).date(), review_json=json.dumps({**ANSWER, **review}), trade_count=1)


# ---- the API call ----

def test_a_review_is_one_structured_call_with_the_key_pinned_to_the_api(fake_claude, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://elsewhere.invalid")
    answer = api_runner.ask("system", "message", {"type": "object", "properties": {"summary": {"type": "string"}}})
    assert answer.data == ANSWER and answer.model == "claude-sonnet-5-5"
    assert (answer.input_tokens, answer.output_tokens, answer.usd) == (1000, 300, 0.005)
    [request] = fake_claude()
    assert request["system"] == "system" and request["messages"] == [{"role": "user", "content": "message"}]
    assert request["output_config"]["format"]["type"] == "json_schema"
    [built] = fake_claude.built
    assert built["api_key"] == "sk-test" and built["base_url"] == "https://api.anthropic.com"


def test_no_key_is_unavailable_not_a_crash(fake_claude, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    assert not api_runner.configured()
    with pytest.raises(api_runner.ApiUnavailable, match="ANTHROPIC_API_KEY"):
        api_runner.ask("system", "message", {})
    assert fake_claude() == [] and fake_claude.built == []


@pytest.mark.parametrize("failure,reason", [
    (api_error(anthropic.RateLimitError, 429), "rate limit"),
    (message(text("no"), stop_reason="refusal"), "refusal"),
    (json_message("not json"), "not JSON"),
])
def test_a_failed_call_is_an_error_with_its_reason(fake_claude, failure, reason):
    fake_claude.set(error=failure)
    with pytest.raises(api_runner.ApiCallFailed, match=reason):
        api_runner.ask("system", "message", {})


# ---- the review ----

def test_the_review_sees_the_last_rules_and_the_traders_normal(fake_claude, engine, monkeypatch):
    add(engine,
        trade(1, datetime(2026, 9, 1, 9, 31), datetime(2026, 9, 1, 10, 0), pnl="50", premium=100),
        trade(2, datetime(2026, 9, 2, 9, 31), datetime(2026, 9, 2, 10, 0), pnl="-30", premium=300),
        trade(3, datetime(2026, 9, 3, 9, 31), datetime(2026, 9, 3, 9, 40), pnl="20", premium=400),
        review_record("2026-09-01", next_session_rules=["Old rule"]),
        review_record("2026-09-02", next_session_rules=["No entries after 3 PM"], day_grade="C: chased"))
    from app.ai import daily_review_service

    with Session(engine) as session:
        record, review = daily_review_service.generate(session, datetime(2026, 9, 3).date())
    [request] = fake_claude()
    context = json.loads(request["messages"][0]["content"].split("\n\n", 1)[1])
    assert [item["day"] for item in context["history"]["prior_reviews"]] == ["2026-09-02", "2026-09-01"]
    assert context["history"]["prior_reviews"][0]["next_session_rules"] == ["No entries after 3 PM"]
    baseline = context["history"]["baseline"]
    assert (baseline["trading_days"], baseline["trades_per_day"], baseline["median_premium_per_trade"], baseline["win_rate"]) == (2, 1.0, 200.0, 0.5)
    assert (baseline["avg_win"], baseline["avg_loss"], baseline["worst_day_pnl"]) == (50.0, -30.0, -30.0)
    assert [item["id"] for item in context["trades"]] == [str(UUID(int=103))]
    schema = request["output_config"]["format"]["schema"]
    assert {"rules_check", "vs_baseline", "data_gaps", "expectation_checks"} <= set(schema["required"])
    assert schema["additionalProperties"] is False  # the API's structured outputs want every object closed
    assert review["generated_by"] == "claude-sonnet-5-5 through the Anthropic API"
    assert review["prompt_version"] == daily_reviewer.PROMPT_VERSION
    assert json.loads(record.review_json)["usage"]["output_tokens"] == 300


@pytest.mark.parametrize("append_during_generation", [False, True])
def test_review_stales_if_owner_thoughts_change_during_generation(engine, monkeypatch, append_during_generation):
    from app.ai import daily_review_service

    day = datetime(2026, 9, 3).date()
    add(engine, trade(1, datetime(2026, 9, 3, 9, 31), datetime(2026, 9, 3, 10, 0)))

    def fake_review(_day, _trades, _fills, session):
        if append_during_generation:
            session.add(DayJournalEntry(operation_id="during-review", day=day, kind="update", text="New thought"))
            session.commit()
        return {**ANSWER, "owner_thoughts_included": False}

    monkeypatch.setattr(daily_reviewer, "review_trading_day", fake_review)
    with Session(engine) as session:
        record, review = daily_review_service.generate(session, day)
        stored = json.loads(record.review_json)

    if append_during_generation:
        assert review["source_data_stale"] is True
        assert review["source_data_stale_reason"] == "Owner thoughts changed while this review was being generated."
        assert review["owner_thoughts_included"] is True
        assert stored["source_data_stale"] is True and stored["owner_thoughts_included"] is True
        assert stored["owner_input_count"] == 0
    else:
        assert "source_data_stale" not in review
        assert review["owner_thoughts_included"] is False
        assert "source_data_stale" not in stored


def test_private_prior_day_rules_make_the_next_review_private(fake_claude, engine, monkeypatch):
    from app.ai import daily_review_service, review_context

    prior_day = datetime(2026, 9, 2).date()
    review_day = datetime(2026, 9, 3).date()
    add(engine,
        DayJournalEntry(operation_id="private-prior", day=prior_day, kind="outlook", text="Private outlook"),
        review_record(prior_day.isoformat(), owner_thoughts_included=True, owner_input_count=1,
                      next_session_rules=["SECRET prior-day rule"]),
        trade(1, datetime(2026, 9, 3, 9, 31), datetime(2026, 9, 3, 10, 0)))
    monkeypatch.setattr(review_context, "build", lambda *_args, **_kwargs: {"gaps": []})
    seen = {}

    def ask(_system, message, _schema, **_kwargs):
        context = json.loads(message.split("\n\n", 1)[1])
        seen["history"] = context["history"]
        answer = {**ANSWER, "next_session_rules": context["history"]["prior_reviews"][0]["next_session_rules"]}
        return type("Answer", (), {"data": answer, "author": "test", "usage": {
            "input_tokens": 0, "output_tokens": 0, "api_equivalent_usd": 0, "seconds": 0}})()

    monkeypatch.setattr(api_runner, "ask", ask)
    with Session(engine) as session:
        record, review = daily_review_service.generate(session, review_day)

    assert seen["history"]["owner_private_inputs"] is True
    assert review["next_session_rules"] == ["SECRET prior-day rule"]
    assert review["owner_thoughts_included"] is True
    assert json.loads(record.review_json)["owner_thoughts_included"] is True


def test_a_review_without_a_key_is_unavailable_and_saves_nothing(fake_claude, engine, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    add(engine, trade(1, datetime(2026, 9, 3, 9, 31), datetime(2026, 9, 3, 10, 0)))
    from app.ai import daily_review_service

    with Session(engine) as session, pytest.raises(api_runner.ApiUnavailable):
        daily_review_service.generate(session, datetime(2026, 9, 3).date())
    with Session(engine) as session:
        assert session.exec(select(DailyReviewRecord)).all() == []


# ---- the nightly run ----

def test_the_run_reviews_only_the_latest_day_and_never_backfills(fake_claude, engine):
    add(engine, *[trade(day, datetime(2026, 9, day, 10, 0), datetime(2026, 9, day, 11, 0)) for day in range(1, 8)],
        review_record("2026-09-02", source_data_stale=True))
    with Session(engine) as session:
        assert plan_reviews.plan(session) == [(datetime(2026, 9, 7).date(), "latest")]
        status = plan_reviews.run(session)
    assert status["state"] == "ok"
    assert [item["day"] for item in status["written"]] == ["2026-09-07"]
    assert status["usage"]["output_tokens"] == 300
    with Session(engine) as session:
        # Older unreviewed days and an older stale review wait for their own button.
        assert plan_reviews.plan(session) == []
        assert plan_reviews.run(session)["state"] == "nothing"


def test_the_latest_day_is_redone_when_trades_were_added_or_its_review_went_stale(fake_claude, engine):
    add(engine, trade(1, datetime(2026, 9, 7, 10, 0), datetime(2026, 9, 7, 11, 0)), trade(2, datetime(2026, 9, 7, 14, 0), datetime(2026, 9, 7, 15, 0)),
        review_record("2026-09-07"))  # saved when only one trade existed
    with Session(engine) as session:
        assert plan_reviews.plan(session) == [(datetime(2026, 9, 7).date(), "trades added")]
        record = session.exec(select(DailyReviewRecord)).one()
        record.trade_count = 2
        record.review_json = json.dumps({**ANSWER, "source_data_stale": True})
        session.add(record)
        session.commit()
        assert plan_reviews.plan(session) == [(datetime(2026, 9, 7).date(), "stale")]


def test_a_failed_call_is_recorded_and_the_api_being_unavailable_fails_the_run(fake_claude, engine, monkeypatch):
    add(engine, trade(1, datetime(2026, 9, 1, 10, 0), datetime(2026, 9, 1, 11, 0)))
    fake_claude.set(error=api_error(anthropic.RateLimitError, 429))
    with Session(engine) as session:
        status = plan_reviews.run(session)
    assert status["state"] == "failed" and len(status["failed"]) == 1 and status["written"] == []
    assert "rate limit" in status["failed"][0]["error"]
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    with Session(engine) as session:
        status = plan_reviews.run(session)
    assert status["state"] == "failed" and "Anthropic API is not available" in status["message"]


def test_main_writes_the_status_and_exits_1_only_on_failure(fake_claude, engine, monkeypatch):
    import app.database

    monkeypatch.setattr(app.database, "engine", engine)
    add(engine, trade(1, datetime(2026, 9, 1, 10, 0), datetime(2026, 9, 1, 11, 0)))
    assert plan_reviews.main([]) == 0
    assert plan_reviews.read_status()["state"] == "ok"
    assert plan_reviews.main([]) == 0
    assert plan_reviews.read_status()["state"] == "nothing"
    with Session(engine) as session:
        session.add(trade(2, datetime(2026, 9, 2, 10, 0), datetime(2026, 9, 2, 11, 0)))
        session.commit()
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    assert plan_reviews.main([]) == 1
    assert plan_reviews.read_status()["state"] == "failed"


# ---- the API ----

@pytest.fixture
def client(engine):
    def override():
        with Session(engine) as session:
            yield session

    app = FastAPI()
    app.include_router(router, prefix="/daily-review")
    app.dependency_overrides[get_session] = override
    with TestClient(app) as test_client:
        yield test_client


def test_the_button_uses_the_api_and_says_when_it_is_not_set_up(fake_claude, engine, client, monkeypatch):
    add(engine, trade(1, datetime(2026, 9, 1, 10, 0), datetime(2026, 9, 1, 11, 0)))
    body = {"day": "2026-09-01", "trade_ids": [str(UUID(int=101))]}
    response = client.post("/daily-review", json=body)
    assert response.status_code == 200
    assert response.json()["review"]["generated_by"].endswith("through the Anthropic API")
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    response = client.post("/daily-review", json=body)
    assert response.status_code == 503 and "not set up" in response.json()["detail"] and "ANTHROPIC_API_KEY" in response.json()["detail"]


def test_the_runner_status_route(fake_claude, client, monkeypatch):
    assert client.get("/daily-review/runner").json() == {"configured": True, "status": None}
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    assert client.get("/daily-review/runner").json() == {"configured": False, "status": None}
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    state = Path(os.environ["TJ_PLAN_REVIEW_DIR"])
    state.mkdir(parents=True)
    (state / "status.json").write_text(json.dumps({"state": "ok", "written": []}))
    assert client.get("/daily-review/runner").json()["status"]["state"] == "ok"


@pytest.mark.parametrize("setting", ["plan", "api"])
def test_the_old_review_backend_setting_changes_nothing(fake_claude, engine, monkeypatch, setting):
    monkeypatch.setenv("AI_REVIEW_BACKEND", setting)
    add(engine, trade(1, datetime(2026, 9, 1, 10, 0), datetime(2026, 9, 1, 11, 0)))
    with Session(engine) as session:
        status = plan_reviews.run(session)
    assert status["state"] == "ok" and status["model"].endswith("through the Anthropic API")
    assert len(fake_claude()) == 1


def test_a_run_stopped_midway_reads_as_interrupted_and_a_crash_leaves_a_failed_status(fake_claude, engine, monkeypatch):
    plan_reviews._write_status({"state": "running", "started_at": "2026-09-01T00:00:00+00:00", "written": []})
    assert plan_reviews.read_status()["state"] == "interrupted"
    import app.database

    monkeypatch.setattr(app.database, "engine", engine)

    def broken(*_args, **_kwargs):
        raise RuntimeError("database went away")

    monkeypatch.setattr(plan_reviews, "run", broken)
    with pytest.raises(RuntimeError):
        plan_reviews.main([])
    status = plan_reviews.read_status()
    assert status["state"] == "failed" and "database went away" in status["message"]
    plan_reviews._write_status({"state": "ok", "written": [{"day": "2026-08-31"}], "failed": [{"day": "2026-08-30", "error": "old"}]})
    with pytest.raises(RuntimeError):
        plan_reviews.main([])
    status = plan_reviews.read_status()
    assert status["state"] == "failed" and status["written"] == [] and status["failed"] == []  # not last night's


def test_rules_from_an_old_review_carry_how_old_they_are(fake_claude, engine):
    add(engine, trade(1, datetime(2026, 9, 30, 10, 0), datetime(2026, 9, 30, 11, 0)), review_record("2026-09-01", next_session_rules=["Old"]))
    with Session(engine) as session:
        history = daily_reviewer._history_context(datetime(2026, 9, 30).date(), session)
    assert history["prior_reviews"][0]["days_before"] == 29
    assert "more than 4" in daily_reviewer._SYSTEM_PROMPT


# ---- one trade's review (the Review button on a trade) ----

TRADE_ANSWER = {"strategy": "Long Call (bullish directional)", "flags": ["good_entry"], "summary": "Bought the reclaim.",
                "entry_quality": "Good: waited for the reclaim.", "exit_quality": "Fair: sold into strength early.",
                "suggestions": ["Hold half to the first wall"], "market_read": "Trend day; traded with it.",
                "plan_check": None, "data_gaps": []}


def test_a_trade_review_runs_on_the_api_with_the_days_context_and_says_when_it_is_not_set_up(fake_claude, engine, monkeypatch):
    from app.ai import review_context
    from app.routers.trades import router as trades_router

    days = []
    monkeypatch.setattr(review_context, "build", lambda session, day, trades: days.append((day, [t.id for t in trades])) or {"gaps": []})
    fake_claude.set(TRADE_ANSWER)
    add(engine, trade(1, datetime(2026, 9, 1, 10, 0), datetime(2026, 9, 1, 11, 0)))

    def override():
        with Session(engine) as session:
            yield session

    app = FastAPI()
    app.include_router(trades_router, prefix="/trades")
    app.dependency_overrides[get_session] = override
    with TestClient(app) as test_client:
        response = test_client.post(f"/trades/{UUID(int=101)}/review")
        assert response.status_code == 200, response.text
        review = json.loads(response.json()["ai_review"])
        assert review["generated_by"].endswith("through the Anthropic API") and review["market_read"] and review["prompt_version"] == 2
        assert days == [(datetime(2026, 9, 1).date(), [UUID(int=101)])]
        assert len(fake_claude()) == 1 and fake_claude.built[0]["base_url"] == "https://api.anthropic.com"
        monkeypatch.delenv("ANTHROPIC_API_KEY")
        response = test_client.post(f"/trades/{UUID(int=101)}/review")
        assert response.status_code == 503 and "not set up" in response.json()["detail"]
