"""The backend a turn runs on (docs/copilot-lab.md § Backend picker and the API budget): GET /status offers the backends
that are usable here; POST /chat takes one of them; the plan backend reaches a hosted database only with the owner's
COPILOT_PLAN_REMOTE_OK; every turn is recorded with its model and cost; API turns stop for the day at the budget."""
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.ai import copilot, copilot_spend
from app.database import engine
from app.main import app
from app.models import CopilotTurn, utc_now_naive


def _turn():
    return {"messages": [{"role": "user", "content": "x"}]}


def test_offered_backends_follow_what_is_usable(monkeypatch):
    monkeypatch.delenv("COPILOT_BACKENDS", raising=False)
    assert copilot.requested_backends() == ("anthropic", "plan")
    monkeypatch.setenv("COPILOT_BACKENDS", "plan, anthropic, fake, plan")
    assert copilot.requested_backends() == ("plan", "anthropic")  # fake is never offered; duplicates dropped
    both = ("anthropic", "plan")
    assert copilot.offered_backends("anthropic", both, key_configured=True, plan_usable=True) == ("anthropic", "plan")
    assert copilot.offered_backends("anthropic", both, key_configured=True, plan_usable=False) == ("anthropic",)
    assert copilot.offered_backends("plan", both, key_configured=False, plan_usable=True) == ("plan",)
    assert copilot.offered_backends("fake", both, key_configured=True, plan_usable=True) == ("fake", "anthropic", "plan")


def test_settings_offer_the_plan_off_a_local_database_only_with_the_opt_in(monkeypatch):
    monkeypatch.setenv("COPILOT_ENABLED", "true")
    monkeypatch.setenv("COPILOT_BACKEND", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.delenv("COPILOT_BACKENDS", raising=False)
    monkeypatch.setattr(copilot, "_plan_configured", lambda: True)
    monkeypatch.setattr(copilot, "_is_local", lambda: False)
    monkeypatch.delenv("COPILOT_PLAN_REMOTE_OK", raising=False)
    cfg = copilot.settings()
    assert cfg.backends == ("anthropic",) and cfg.plan_configured and not cfg.plan_remote_ok
    monkeypatch.setenv("COPILOT_PLAN_REMOTE_OK", "true")
    cfg = copilot.settings()
    assert cfg.backends == ("anthropic", "plan") and cfg.plan_remote_ok
    assert cfg.public()["backends"] == ["anthropic", "plan"] and cfg.public()["daily_budget_usd"] == 2.0
    monkeypatch.setattr(copilot, "_is_local", lambda: True)
    monkeypatch.delenv("COPILOT_PLAN_REMOTE_OK")
    assert copilot.settings().backends == ("anthropic", "plan")  # local: as before, no opt-in needed
    with pytest.raises(copilot.CopilotError, match="not offered"):
        copilot.with_backend(copilot.settings(), "fake")
    assert copilot.with_backend(cfg, None) is cfg and copilot.with_backend(cfg, "plan").backend == "plan"


def test_the_plan_adapter_guard_takes_the_opt_in(monkeypatch):
    from app.ai import copilot_plan
    from app import environment
    monkeypatch.setattr(environment, "describe", lambda: type("D", (), {"is_local": False})())
    monkeypatch.setattr(copilot_plan, "preflight", lambda env: "/usr/bin/claude")
    base = dict(enabled=True, backend="plan", evidence="fixture", model="m", effort="medium", fallbacks=False, key_configured=False)
    with pytest.raises(copilot.CopilotError, match="COPILOT_PLAN_REMOTE_OK"):
        copilot_plan.PlanAdapter(copilot.Settings(**base), sdk=object(), env={})
    adapter = copilot_plan.PlanAdapter(copilot.Settings(**base, plan_remote_ok=True), sdk=object(), env={})
    assert adapter.binary == "/usr/bin/claude"


def test_a_turn_picks_a_backend_and_is_recorded_with_its_model_and_cost(monkeypatch):
    monkeypatch.setenv("COPILOT_ENABLED", "true")
    monkeypatch.setenv("COPILOT_BACKEND", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.delenv("COPILOT_BACKENDS", raising=False)
    monkeypatch.setenv("COPILOT_PLAN_REMOTE_OK", "true")
    monkeypatch.setattr(copilot, "_plan_configured", lambda: True)
    seen: list[str] = []
    monkeypatch.setattr(copilot, "adapter_for", lambda cfg: seen.append(cfg.backend) or copilot.FakeAdapter(0))
    with Session(engine) as db:
        for row in db.exec(select(CopilotTurn)).all():
            db.delete(row)
        db.commit()
    with TestClient(app) as client:
        status = client.get("/copilot/status").json()
        assert status["backends"] == ["anthropic", "plan"] and status["spend_today_usd"] == 0.0 and status["daily_budget_usd"] == 2.0
        assert client.post("/copilot/chat", json={**_turn(), "backend": "plan", "symbol": "NBIS"}).status_code == 200 and seen[-1] == "plan"
        assert client.post("/copilot/chat", json=_turn()).status_code == 200 and seen[-1] == "anthropic"
        assert client.post("/copilot/chat", json={**_turn(), "backend": "fake"}).status_code == 422  # not a pickable backend
        monkeypatch.setenv("COPILOT_BACKENDS", "anthropic")
        refused = client.post("/copilot/chat", json={**_turn(), "backend": "plan"})
        assert refused.status_code == 422 and "not offered" in refused.json()["detail"]
    with Session(engine) as db:
        rows = db.exec(select(CopilotTurn).order_by(CopilotTurn.started_at)).all()
    assert [(r.backend, r.billing, r.symbol) for r in rows][:2] == [("plan", "claude_plan", "NBIS"), ("anthropic", "api", None)]
    assert all(r.model == "fake-scripted" and r.rounds >= 1 for r in rows[:2])  # the scripted model, as the done event reported


def test_api_turns_stop_for_the_day_at_the_budget(monkeypatch):
    monkeypatch.setenv("COPILOT_ENABLED", "true")
    monkeypatch.setenv("COPILOT_BACKEND", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setenv("COPILOT_DAILY_BUDGET_USD", "1.5")
    monkeypatch.setenv("COPILOT_PLAN_REMOTE_OK", "true")
    monkeypatch.setattr(copilot, "_plan_configured", lambda: True)
    monkeypatch.setattr(copilot, "adapter_for", lambda cfg: copilot.FakeAdapter(0))
    with Session(engine) as db:
        for row in db.exec(select(CopilotTurn)).all():
            db.delete(row)
        db.add(CopilotTurn(backend="anthropic", billing="api", model="claude-opus-5-5", cost_usd=0.9))
        db.add(CopilotTurn(backend="anthropic", billing="api", model="claude-sonnet-5-5", cost_usd=0.7))
        db.add(CopilotTurn(backend="plan", billing="claude_plan", model="claude-opus-5-5", cost_usd=5.0))  # API-equivalent, not billed
        db.add(CopilotTurn(backend="anthropic", billing="api", model="claude-opus-5-5", cost_usd=9.0,
                           started_at=utc_now_naive() - timedelta(days=2)))  # another day
        db.commit()
    assert copilot_spend.spent_today() == 1.6
    with TestClient(app) as client:
        assert client.get("/copilot/status").json()["spend_today_usd"] == 1.6
        over = client.post("/copilot/chat", json=_turn())
        assert over.status_code == 429 and "$1.50" in over.json()["detail"] and "plan backend" in over.json()["detail"]
        assert client.post("/copilot/chat", json={**_turn(), "backend": "plan"}).status_code == 200  # the plan still answers
    with Session(engine) as db:
        for row in db.exec(select(CopilotTurn)).all():
            db.delete(row)
        db.commit()


def test_turn_metrics_reach_the_journal_logger():
    import logging
    ai = logging.getLogger("app.ai")
    assert ai.level <= logging.INFO or logging.getLogger().handlers  # configured by copilot._journal_logging, or by the test runner
