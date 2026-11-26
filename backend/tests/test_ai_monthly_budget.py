"""Shared monthly AI spend cap (``AI_MONTHLY_BUDGET_USD``), month-to-date aggregation across all cost records,
``/copilot/status`` fields, call-site refusals, and Sonnet 5.5 cache-read pricing. Offline."""
from __future__ import annotations

import asyncio
import json
from datetime import UTC, date, datetime, timedelta

import anthropic
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, delete, select

from app.ai import api_runner, copilot, copilot_spend, research_job, shadow_turn
from app.ai.copilot_fixture import FixtureEvidence
from app.database import engine
from app.engine import practice, practice_agent, premarket_prep, research_queue
from app.main import app
from app.models import CopilotTurn, PracticeAgentCall, ResearchJob
from scripts import strategy_factory
from tests.fake_anthropic import FakeAnthropic, json_message


@pytest.fixture(autouse=True)
def clean():
    with Session(engine) as db:
        db.exec(delete(CopilotTurn))
        db.exec(delete(ResearchJob))
        db.commit()
    yield
    with Session(engine) as db:
        db.exec(delete(CopilotTurn))
        db.exec(delete(ResearchJob))
        db.commit()


def _in_month() -> datetime:
    return copilot_spend._month_start_utc() + timedelta(minutes=5)


def _before_month() -> datetime:
    return copilot_spend._month_start_utc() - timedelta(minutes=5)


def test_sonnet_cache_read_price_is_point_one_zero_and_opus_stays_point_two_zero():
    assert copilot.PRICES["claude-sonnet-5-5"] == (2.00, 10.00, 0.10, 2.50)
    assert copilot.PRICES["claude-opus-5-5"] == (4.00, 20.00, 0.20, 5.00)
    usage = {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 1_000_000, "cache_creation_input_tokens": 0}
    assert copilot.cost_usd("claude-sonnet-5-5", usage) == pytest.approx(0.10)
    assert copilot.cost_usd("claude-opus-5-5", usage) == pytest.approx(0.20)


def test_opus_5_pricing_and_opus_5_5_prefix_match():
    usage = {"input_tokens": 1_000_000, "output_tokens": 1_000_000, "cache_read_input_tokens": 1_000_000, "cache_creation_input_tokens": 1_000_000}
    assert copilot.cost_usd("claude-opus-5", usage) == pytest.approx(36.75)
    assert copilot.cost_usd("claude-opus-5-20261101", usage) == pytest.approx(36.75)
    assert copilot.cost_usd("claude-opus-5-5", usage) == pytest.approx(29.20)
    assert copilot.cost_usd("claude-opus-5-5-20260901", usage) == pytest.approx(29.20)


def test_monthly_budget_env_default_and_validation(monkeypatch):
    monkeypatch.delenv("AI_MONTHLY_BUDGET_USD", raising=False)
    assert copilot_spend.monthly_budget_usd() == 100.0
    monkeypatch.setenv("AI_MONTHLY_BUDGET_USD", "25")
    assert copilot_spend.monthly_budget_usd() == 25.0
    for bad in ("0", "-5", "inf", "nan", "not-a-number"):
        monkeypatch.setenv("AI_MONTHLY_BUDGET_USD", bad)
        assert copilot_spend.monthly_budget_usd() == 100.0


def test_spent_this_month_sums_existing_records_and_excludes_prior_month():
    in_m = _in_month()
    before_m = _before_month()
    mem = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(mem)
    try:
        with Session(mem) as db:
            run_now = practice.start(db, day=date(2026, 10, 8))
            run_old = practice.start(db, day=date(2026, 9, 8))
            db.add_all([
                CopilotTurn(backend="anthropic", billing="api", cost_usd=12.5, started_at=in_m),
                CopilotTurn(backend="shadow", billing="api_background", cost_usd=3.25, started_at=in_m),
                CopilotTurn(backend="api_background", billing="api_background", cost_usd=1.75, started_at=in_m),
                CopilotTurn(backend="fake", billing="none", cost_usd=99.0, started_at=in_m),
                CopilotTurn(backend="plan", billing="claude_plan", cost_usd=99.0, started_at=in_m),
                CopilotTurn(backend="anthropic", billing="api", cost_usd=50.0, started_at=before_m),
                ResearchJob(
                    kind="question", input_json="{}", dedupe_key="cur", started_at=in_m, cost_usd=14.5,
                    spend_json=json.dumps([
                        {"at": before_m.isoformat(), "usd": 10.0, "estimated": False},
                        {"at": in_m.isoformat(), "usd": 4.5, "estimated": False},
                    ]),
                ),
                ResearchJob(
                    kind="question", input_json="{}", dedupe_key="old", started_at=before_m, cost_usd=20.0,
                    spend_json=json.dumps([{"at": before_m.isoformat(), "usd": 20.0, "estimated": False}]),
                ),
                PracticeAgentCall(
                    day=run_now.day, run_id=run_now.id, status="completed", model="claude-sonnet-5-5",
                    prompt_version="v1", payload_json="{}", config_json="{}", started_at=in_m, cost_usd=2.25,
                ),
                PracticeAgentCall(
                    day=run_old.day, run_id=run_old.id, status="completed", model="claude-sonnet-5-5",
                    prompt_version="v1", payload_json="{}", config_json="{}", started_at=before_m, cost_usd=30.0,
                ),
            ])
            db.commit()
            assert copilot_spend.spent_this_month(db) == pytest.approx(24.25)
    finally:
        mem.dispose()


def test_copilot_status_exposes_monthly_spend_and_cap(monkeypatch):
    monkeypatch.setenv("COPILOT_ENABLED", "true")
    monkeypatch.delenv("AI_MONTHLY_BUDGET_USD", raising=False)
    with Session(engine) as db:
        db.add(CopilotTurn(backend="anthropic", billing="api", cost_usd=12.34, started_at=_in_month()))
        db.commit()
    with TestClient(app) as client:
        default_status = client.get("/copilot/status").json()
        assert default_status["monthly_budget_usd"] == 100.0
        assert default_status["spend_this_month_usd"] == pytest.approx(12.34)
        monkeypatch.setenv("AI_MONTHLY_BUDGET_USD", "150")
        custom_status = client.get("/copilot/status").json()
        assert custom_status["monthly_budget_usd"] == 150.0
        assert custom_status["spend_this_month_usd"] == pytest.approx(12.34)


def test_copilot_chat_prep_and_week_review_refuse_when_month_is_spent(monkeypatch):
    monkeypatch.setenv("COPILOT_ENABLED", "true")
    monkeypatch.setenv("COPILOT_BACKEND", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("COPILOT_DAILY_BUDGET_USD", "50")
    monkeypatch.setenv("AI_MONTHLY_BUDGET_USD", "5")
    # Background spend counts toward the monthly cap even though spent_today() stays 0.
    with Session(engine) as db:
        db.add(CopilotTurn(backend="shadow", billing="api_background", cost_usd=5.0, started_at=_in_month()))
        db.commit()
    assert copilot_spend.spent_today() == 0.0
    monkeypatch.setattr(copilot, "adapter_for", lambda cfg: pytest.fail("adapter must not be built when month is spent"))

    with TestClient(app) as client:
        res = client.post("/copilot/chat", json={"messages": [{"role": "user", "content": "Is NBIS confirming?"}], "symbol": "NBIS"})
        assert res.status_code == 429 and "AI_MONTHLY_BUDGET_USD" in res.json()["detail"]

    now = datetime.now(UTC).timestamp()
    prep_answer, prep_err = premarket_prep._turn("Morning brief", now, kind="prep")
    assert prep_answer == "" and "budget" in prep_err.lower()
    week_answer, week_err = premarket_prep._turn("Review my week", now, kind="week_review")
    assert week_answer == "" and "budget" in week_err.lower()

    with Session(engine) as db:
        refused = db.exec(select(CopilotTurn).where(CopilotTurn.error == "monthly_budget")).all()
    assert [(r.kind, r.cost_usd) for r in refused] == [("ask", 0.0), ("prep", 0.0), ("week_review", 0.0)]


def test_api_runner_shadow_research_practice_and_factory_refuse_when_month_is_spent(monkeypatch):
    monkeypatch.setenv("AI_MONTHLY_BUDGET_USD", "1.00")
    schema = {"type": "object", "required": ["verdict"], "properties": {"verdict": {"type": "string"}}}

    # Under budget: api_runner.ask succeeds and records its cost to copilot_turn (counted in spent_this_month).
    ok = api_runner.ask("s", "q", schema, client=FakeAnthropic([json_message({"verdict": "ok"}, input_tokens=1000, output_tokens=100)]))
    assert ok.data == {"verdict": "ok"} and copilot_spend.spent_this_month() == pytest.approx(0.003) and copilot_spend.spent_today() == 0.0

    # Spend reaches the $1.00 monthly cap: every subsystem refuses before calling Anthropic.
    with Session(engine) as db:
        db.add(CopilotTurn(backend="anthropic", billing="api", cost_usd=1.00, started_at=_in_month()))
        db.commit()

    def no_anthropic(*args, **kwargs):
        raise AssertionError("Anthropic client must not be built or called when monthly budget is spent")

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(anthropic, "Anthropic", no_anthropic)
    monkeypatch.setattr(anthropic, "AsyncAnthropic", no_anthropic)

    with pytest.raises(api_runner.ApiUnavailable, match="month's AI budget"):
        api_runner.ask("s", "q", schema)

    run = api_runner.AgentRun(model="claude-sonnet-5-5")
    asyncio.run(api_runner.run_agent(run, "s", "p", schema, tools=[], execute=lambda c: no_anthropic(), max_turns=2, budget_usd=0.5))
    assert run.error["code"] == "monthly_budget"

    shadow_out = asyncio.run(shadow_turn.decide({"event_id": "e1", "symbols": ["NBIS"], "summary": "x"}, {},
                                                datetime(2026, 10, 22, 10, 40), evidence=FixtureEvidence()))
    assert shadow_out["answer"] is None and shadow_out["error"]["code"] == "monthly_budget"

    research_queue.enqueue_question("Why?", ["NBIS"])
    assert research_queue.claim_next(0.5, 5.0) is None
    with pytest.raises(research_job.ResearchError, match="month's AI budget"):
        research_job.run("Why?", ["NBIS"], FixtureEvidence(), now=datetime(2026, 10, 22, 10, 40))

    with pytest.raises(SystemExit, match="month's AI budget"):
        strategy_factory.claude_proposer("sys", "brief")

    # Practice agent checks the monthly cap on its DB session.
    monkeypatch.setattr(practice_agent, "config", lambda: {
        "model": "fixture", "timeout_seconds": 2, "input_tokens": 20000, "output_tokens": 2000,
        "daily_usd": 5.0, "input_usd_per_million": 1, "output_usd_per_million": 1,
    })
    mem = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(mem)
    try:
        with Session(mem) as db:
            db.add(CopilotTurn(backend="anthropic", billing="api", cost_usd=1.00, started_at=_in_month()))
            db.commit()
            practice_run = practice.start(db, day=date(2026, 10, 8))
            status = practice.run_agent(db, practice_run, adapter=lambda *a: no_anthropic())
            assert status == "budget_exhausted"
            call = db.exec(select(PracticeAgentCall)).one()
            assert "month's AI budget" in (call.error or "")
    finally:
        mem.dispose()
