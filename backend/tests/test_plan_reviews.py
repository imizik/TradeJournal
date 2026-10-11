"""Daily reviews on the Claude plan: the claude -p call, the review's history,
the nightly run's choice of days and its status. Claude Code is a fake script;
nothing here reaches Anthropic."""

from datetime import datetime
from decimal import Decimal
import json
import os
from pathlib import Path
import stat
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.ai import daily_reviewer, plan_runner
from app.database import get_session
from app.jobs import plan_reviews
from app.models import Account, DailyReviewRecord, Trade
from app.routers.daily_review import router

ACCOUNT = UUID(int=1)
ANSWER = {"summary": "Two trades, +$60.", "day_grade": "B: sized to plan", "key_takeaways": ["SPY 9:31 entry was on plan"],
          "best_trade": {"trade_id": None, "ticker": "SPY", "reason": "waited for the reclaim"},
          "worst_trade": {"trade_id": None, "ticker": "SPY", "reason": "chased"}, "patterns": [],
          "next_session_rules": ["Max 2 contracts"], "rules_check": [], "vs_baseline": [], "data_gaps": []}

FAKE_CLAUDE = r'''#!/usr/bin/env python3
import json, os, sys
fake = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "fake.json")))
with open(fake["log"], "a") as handle:
    handle.write(json.dumps({"argv": sys.argv[1:], "token": os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"),
                             "api_key": os.environ.get("ANTHROPIC_API_KEY"), "base_url": os.environ.get("ANTHROPIC_BASE_URL"),
                             "database": os.environ.get("DATABASE_URL"), "config": os.environ.get("CLAUDE_CONFIG_DIR")}) + "\n")
if sys.argv[1:3] == ["auth", "status"]:
    print(json.dumps({"authMethod": fake.get("auth", "oauth_token"), "apiProvider": "firstParty"}))
    sys.exit(0)
message = sys.stdin.read()
mode = fake.get("mode", "ok")
if mode == "error":
    print(json.dumps({"type": "result", "subtype": "error_max_turns", "is_error": True, "result": "usage limit reached"}))
    sys.exit(1)
answer = fake["answer"]
print(json.dumps({"type": "result", "subtype": "success", "is_error": False, "structured_output": answer,
                  "total_cost_usd": 0.0123, "duration_ms": 4200,
                  "modelUsage": {"claude-sonnet-5-5": {"inputTokens": 900, "outputTokens": 300, "cacheReadInputTokens": 100}}}))
'''


class Fake:
    """The fake Claude Code's settings, in fake.json beside it."""

    def __init__(self, folder: Path):
        self.folder, self.log = folder, folder / "calls.jsonl"
        self.settings = {"log": str(self.log), "answer": ANSWER}
        self.save()

    def save(self):
        (self.folder / "fake.json").write_text(json.dumps(self.settings))

    def set(self, **values):
        self.settings.update(values)
        self.save()

    def __call__(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []


@pytest.fixture
def fake_claude(tmp_path, monkeypatch):
    binary = tmp_path / "claude"
    binary.write_text(FAKE_CLAUDE)
    binary.chmod(binary.stat().st_mode | stat.S_IEXEC)
    fake = Fake(tmp_path)
    monkeypatch.setenv("TJ_CLAUDE_BIN", str(binary))
    monkeypatch.setenv("TJ_CLAUDE_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("TJ_PLAN_REVIEW_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "plan-token")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "must-not-reach-claude")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://elsewhere.invalid")
    monkeypatch.setenv("DATABASE_URL", "postgresql://must-not-reach-claude")
    monkeypatch.delenv("AI_REVIEW_BACKEND", raising=False)
    plan_runner._checked.clear()
    yield fake
    plan_runner._checked.clear()


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


# ---- the claude -p call ----

def test_the_plan_token_reaches_claude_and_nothing_that_would_bill_or_redirect_it(fake_claude):
    answer = plan_runner.ask("system", "message", {"type": "object"})
    assert answer.data == ANSWER
    assert answer.model == "claude-sonnet-5-5"
    assert (answer.input_tokens, answer.output_tokens, answer.api_equivalent_usd, answer.seconds) == (1000, 300, 0.0123, 4.2)
    calls = fake_claude()
    assert [call["argv"][:2] for call in calls] == [["auth", "status"], ["-p", "--restricted"]]
    for call in calls:
        assert call["token"] == "plan-token"
        assert call["api_key"] is None and call["base_url"] is None and call["database"] is None
        assert call["config"].endswith("config")
    argv = calls[1]["argv"]
    assert argv[argv.index("--tools") + 1] == ""
    assert argv[argv.index("--model") + 1] == "sonnet"
    assert argv[argv.index("--max-budget-usd") + 1] == "2"
    assert "plan-token" not in " ".join(argv)  # never an argument
    plan_runner.ask("system", "again", {"type": "object"})
    assert len(fake_claude()) == 3  # the sign-in is checked once per process


def test_a_sign_in_other_than_the_plan_stops_before_any_question(fake_claude, monkeypatch):
    fake_claude.set(auth="api_key")
    with pytest.raises(plan_runner.PlanUnavailable, match="would not sign in with the plan token"):
        plan_runner.ask("system", "message", {"type": "object"})
    assert [call["argv"][0] for call in fake_claude()] == ["auth"]


def test_no_token_or_no_binary_is_unavailable_not_a_crash(fake_claude, monkeypatch, tmp_path):
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN")
    with pytest.raises(plan_runner.PlanUnavailable, match="setup-token"):
        plan_runner.ask("system", "message", {})
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "plan-token")
    monkeypatch.setenv("TJ_CLAUDE_BIN", str(tmp_path / "missing"))
    assert not plan_runner.plan_configured()
    with pytest.raises(plan_runner.PlanUnavailable, match="not installed"):
        plan_runner.ask("system", "message", {})


def test_an_error_answer_is_a_failed_call_with_its_reason(fake_claude, monkeypatch):
    fake_claude.set(mode="error")
    with pytest.raises(plan_runner.PlanCallFailed, match="usage limit reached"):
        plan_runner.ask("system", "message", {})


# ---- the review ----

def test_the_review_sees_the_last_rules_and_the_traders_normal(fake_claude, engine, monkeypatch):
    seen = {}
    real_ask = plan_runner.ask

    def ask(system, message, schema, **kwargs):
        seen["message"], seen["schema"] = message, schema
        return real_ask(system, message, schema, **kwargs)

    monkeypatch.setattr(plan_runner, "ask", ask)
    add(engine,
        trade(1, datetime(2026, 9, 1, 9, 31), datetime(2026, 9, 1, 10, 0), pnl="50", premium=100),
        trade(2, datetime(2026, 9, 2, 9, 31), datetime(2026, 9, 2, 10, 0), pnl="-30", premium=300),
        trade(3, datetime(2026, 9, 3, 9, 31), datetime(2026, 9, 3, 9, 40), pnl="20", premium=400),
        review_record("2026-09-01", next_session_rules=["Old rule"]),
        review_record("2026-09-02", next_session_rules=["No entries after 3 PM"], day_grade="C: chased"))
    from app.ai import daily_review_service

    with Session(engine) as session:
        record, review = daily_review_service.generate(session, datetime(2026, 9, 3).date())
    context = json.loads(seen["message"].split("\n\n", 1)[1])
    assert [item["day"] for item in context["history"]["prior_reviews"]] == ["2026-09-02", "2026-09-01"]
    assert context["history"]["prior_reviews"][0]["next_session_rules"] == ["No entries after 3 PM"]
    baseline = context["history"]["baseline"]
    assert (baseline["trading_days"], baseline["trades_per_day"], baseline["median_premium_per_trade"], baseline["win_rate"]) == (2, 1.0, 200.0, 0.5)
    assert (baseline["avg_win"], baseline["avg_loss"], baseline["worst_day_pnl"]) == (50.0, -30.0, -30.0)
    assert [item["id"] for item in context["trades"]] == [str(UUID(int=103))]
    assert {"rules_check", "vs_baseline", "data_gaps"} <= set(seen["schema"]["required"])
    assert review["generated_by"] == "claude-sonnet-5-5 through claude -p on the Claude plan"
    assert review["prompt_version"] == daily_reviewer.PROMPT_VERSION
    assert json.loads(record.review_json)["usage"]["output_tokens"] == 300


def test_the_review_never_falls_back_to_the_api(fake_claude, engine, monkeypatch):
    import sys
    import types

    monkeypatch.setitem(sys.modules, "anthropic", types.SimpleNamespace(Anthropic=lambda **_: pytest.fail("the API was called")))
    fake_claude.set(auth="api_key")
    add(engine, trade(1, datetime(2026, 9, 3, 9, 31), datetime(2026, 9, 3, 10, 0)))
    from app.ai import daily_review_service

    with Session(engine) as session, pytest.raises(plan_runner.PlanUnavailable):
        daily_review_service.generate(session, datetime(2026, 9, 3).date())


# ---- the nightly run ----

def test_the_run_reviews_the_latest_day_then_stale_then_backfill_newest_first_within_its_cap(fake_claude, engine):
    add(engine, *[trade(day, datetime(2026, 9, day, 10, 0), datetime(2026, 9, day, 11, 0)) for day in range(1, 8)],
        review_record("2026-09-02", source_data_stale=True), review_record("2026-09-04"))
    with Session(engine) as session:
        picked, remaining = plan_reviews.plan(session, 4)
        assert [(day.isoformat(), reason) for day, reason in picked] == [
            ("2026-09-07", "latest"), ("2026-09-02", "stale"), ("2026-09-06", "backfill"), ("2026-09-05", "backfill")]
        assert remaining == 2  # Sep 3 and Sep 1
        status = plan_reviews.run(session, 4)
    assert status["state"] == "ok"
    assert [item["day"] for item in status["written"]] == ["2026-09-07", "2026-09-02", "2026-09-06", "2026-09-05"]
    assert status["backfill_remaining"] == 2
    assert status["usage"]["output_tokens"] == 1200
    with Session(engine) as session:
        assert plan_reviews.plan(session, 10)[0] == [(datetime(2026, 9, 3).date(), "backfill"), (datetime(2026, 9, 1).date(), "backfill")]


def test_a_review_written_mid_session_is_redone_when_trades_were_added(fake_claude, engine):
    add(engine, trade(1, datetime(2026, 9, 7, 10, 0), datetime(2026, 9, 7, 11, 0)), trade(2, datetime(2026, 9, 7, 14, 0), datetime(2026, 9, 7, 15, 0)),
        review_record("2026-09-07"))  # saved when only one trade existed
    with Session(engine) as session:
        assert plan_reviews.plan(session, 10)[0] == [(datetime(2026, 9, 7).date(), "latest")]


def test_two_failed_calls_in_a_row_stop_the_run_and_the_plan_being_unavailable_fails_it(fake_claude, engine, monkeypatch):
    add(engine, *[trade(day, datetime(2026, 9, day, 10, 0), datetime(2026, 9, day, 11, 0)) for day in range(1, 6)])
    fake_claude.set(mode="error")
    with Session(engine) as session:
        status = plan_reviews.run(session, 10)
    assert status["state"] == "failed" and len(status["failed"]) == 2 and status["written"] == []
    assert "usage limit" in status["message"]
    fake_claude.set(mode="ok")
    fake_claude.set(auth="api_key")
    plan_runner._checked.clear()
    with Session(engine) as session:
        status = plan_reviews.run(session, 10)
    assert status["state"] == "failed" and "Claude plan is not available" in status["message"]
    assert len(status["failed"]) == 1


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
    fake_claude.set(auth="api_key")
    plan_runner._checked.clear()
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


def test_the_button_uses_the_plan_and_says_when_it_is_not_set_up(fake_claude, engine, client, monkeypatch):
    add(engine, trade(1, datetime(2026, 9, 1, 10, 0), datetime(2026, 9, 1, 11, 0)))
    body = {"day": "2026-09-01", "trade_ids": [str(UUID(int=101))]}
    response = client.post("/daily-review", json=body)
    assert response.status_code == 200
    assert response.json()["review"]["generated_by"].endswith("on the Claude plan")
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN")
    response = client.post("/daily-review", json=body)
    assert response.status_code == 503 and "not set up on the Claude plan" in response.json()["detail"]


def test_the_runner_status_route(fake_claude, client):
    assert client.get("/daily-review/runner").json() == {"configured": True, "status": None}
    state = Path(os.environ["TJ_PLAN_REVIEW_DIR"])
    state.mkdir(parents=True)
    (state / "status.json").write_text(json.dumps({"state": "ok", "written": []}))
    assert client.get("/daily-review/runner").json()["status"]["state"] == "ok"


def test_the_nightly_run_stays_on_the_plan_even_when_the_button_is_set_to_the_api(fake_claude, engine, monkeypatch):
    import sys
    import types

    monkeypatch.setitem(sys.modules, "anthropic", types.SimpleNamespace(Anthropic=lambda **_: pytest.fail("the API was called")))
    monkeypatch.setenv("AI_REVIEW_BACKEND", "api")
    add(engine, trade(1, datetime(2026, 9, 1, 10, 0), datetime(2026, 9, 1, 11, 0)))
    with Session(engine) as session:
        status = plan_reviews.run(session, 10)
    assert status["state"] == "ok"
    assert status["model"].endswith("on the Claude plan")


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


def test_rules_from_an_old_review_carry_how_old_they_are(fake_claude, engine):
    add(engine, trade(1, datetime(2026, 9, 30, 10, 0), datetime(2026, 9, 30, 11, 0)), review_record("2026-09-01", next_session_rules=["Old"]))
    with Session(engine) as session:
        history = daily_reviewer._history_context(datetime(2026, 9, 30).date(), session)
    assert history["prior_reviews"][0]["days_before"] == 29
    assert "more than 4" in daily_reviewer._SYSTEM_PROMPT
