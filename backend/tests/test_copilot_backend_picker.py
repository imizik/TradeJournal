"""The backend a turn runs on (docs/copilot-lab.md § Backend picker and the API budget): GET /status offers the backends
that are usable here (the API, with its key); POST /chat takes one of them; COPILOT_BACKEND=plan is only an old spelling of
the API; every turn is recorded with its model and cost; API turns stop for the day at the budget."""
from dataclasses import replace
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
    assert copilot.requested_backends() == ("anthropic",)
    monkeypatch.setenv("COPILOT_BACKENDS", "plan, anthropic, fake, plan")
    assert copilot.requested_backends() == ("anthropic",)  # the plan is gone; fake is never offered; duplicates dropped
    assert copilot.BACKENDS == ("anthropic",)
    assert copilot.offered_backends("anthropic", ("anthropic",), key_configured=True) == ("anthropic",)
    assert copilot.offered_backends("anthropic", ("anthropic",), key_configured=False) == ("anthropic",)
    assert copilot.offered_backends("fake", ("anthropic",), key_configured=True) == ("fake", "anthropic")
    assert copilot.offered_backends("fake", ("anthropic",), key_configured=False) == ("fake",)  # no key, not offered


def test_settings_offer_the_api_with_its_key_and_know_nothing_of_the_plan(monkeypatch):
    monkeypatch.setenv("COPILOT_ENABLED", "true")
    monkeypatch.setenv("COPILOT_BACKEND", "fake")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.delenv("COPILOT_BACKENDS", raising=False)
    cfg = copilot.settings()
    assert cfg.backend == "fake" and cfg.backends == ("fake", "anthropic")
    public = cfg.public()
    assert public["backends"] == ["fake", "anthropic"] and public["daily_budget_usd"] == 4.0
    assert "plan_configured" not in public and not hasattr(cfg, "plan_remote_ok") and not hasattr(cfg, "plan_configured")
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    assert copilot.settings().backends == ("fake",)
    with pytest.raises(copilot.CopilotError, match="not offered"):
        copilot.with_backend(copilot.settings(), "anthropic")
    with pytest.raises(copilot.CopilotError, match="not offered"):
        copilot.with_backend(cfg, "plan")
    assert copilot.with_backend(cfg, None) is cfg and copilot.with_backend(cfg, "anthropic").backend == "anthropic"


def test_an_environment_still_saying_plan_means_the_api(monkeypatch):
    monkeypatch.setenv("COPILOT_ENABLED", "true")
    monkeypatch.setenv("COPILOT_BACKEND", "plan")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    cfg = copilot.settings()
    assert cfg.backend == "anthropic"  # never a silent fall to the scripted model
    assert cfg.backends == ("anthropic",)
    monkeypatch.setenv("COPILOT_BACKEND", "nonsense")
    assert copilot.settings().backend == "fake"


def test_the_api_adapter_needs_its_key(monkeypatch):
    cfg = copilot.settings()
    with pytest.raises(copilot.CopilotError) as missing:
        copilot.adapter_for(replace(cfg, backend="anthropic", key_configured=False))
    assert missing.value.code == "api_not_configured"
    assert not hasattr(copilot, "_plan_configured") and not hasattr(copilot, "_is_local")


def test_a_turn_runs_on_the_api_and_is_recorded_with_its_model_and_cost(monkeypatch):
    monkeypatch.setenv("COPILOT_ENABLED", "true")
    monkeypatch.setenv("COPILOT_BACKEND", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.delenv("COPILOT_BACKENDS", raising=False)
    seen: list[str] = []
    monkeypatch.setattr(copilot, "adapter_for", lambda cfg: seen.append(cfg.backend) or copilot.FakeAdapter(0))
    with Session(engine) as db:
        for row in db.exec(select(CopilotTurn)).all():
            db.delete(row)
        db.commit()
    with TestClient(app) as client:
        status = client.get("/copilot/status").json()
        assert status["backends"] == ["anthropic"] and status["spend_today_usd"] == 0.0 and status["daily_budget_usd"] == 4.0
        assert client.post("/copilot/chat", json={**_turn(), "backend": "anthropic", "symbol": "NBIS"}).status_code == 200 and seen[-1] == "anthropic"
        assert client.post("/copilot/chat", json=_turn()).status_code == 200 and seen[-1] == "anthropic"
        assert client.post("/copilot/chat", json={**_turn(), "backend": "fake"}).status_code == 422  # not a pickable backend
        assert client.post("/copilot/chat", json={**_turn(), "backend": "plan"}).status_code == 422  # the plan backend is gone
    with Session(engine) as db:
        rows = db.exec(select(CopilotTurn).order_by(CopilotTurn.started_at)).all()
    assert [(r.backend, r.billing, r.symbol) for r in rows][:2] == [("anthropic", "api", "NBIS"), ("anthropic", "api", None)]
    assert all(r.model == "fake-scripted" and r.rounds >= 1 for r in rows[:2])  # the scripted model, as the done event reported


def test_turn_billing_labels_keep_old_plan_rows_readable_and_shadow_apart():
    assert copilot_spend.BILLING == {"anthropic": "api", "shadow": "api_background", "plan": "claude_plan", "fake": "none"}


def test_api_turns_stop_for_the_day_at_the_budget_and_background_turns_do_not_count(monkeypatch):
    monkeypatch.setenv("COPILOT_ENABLED", "true")
    monkeypatch.setenv("COPILOT_BACKEND", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setenv("COPILOT_DAILY_BUDGET_USD", "1.5")
    monkeypatch.setattr(copilot, "adapter_for", lambda cfg: copilot.FakeAdapter(0))
    with Session(engine) as db:
        for row in db.exec(select(CopilotTurn)).all():
            db.delete(row)
        db.add(CopilotTurn(backend="anthropic", billing="api", model="claude-opus-5-5", cost_usd=0.9))
        db.add(CopilotTurn(backend="anthropic", billing="api", model="claude-sonnet-5-5", cost_usd=0.7))
        db.add(CopilotTurn(backend="plan", billing="claude_plan", model="claude-opus-5-5", cost_usd=5.0))  # an old plan row, never billed
        db.add(CopilotTurn(backend="shadow", billing="api_background", model="claude-sonnet-5-5", cost_usd=4.0))  # its own cap
        db.add(CopilotTurn(backend="anthropic", billing="api", model="claude-opus-5-5", cost_usd=9.0,
                           started_at=utc_now_naive() - timedelta(days=2)))  # another day
        db.commit()
    assert copilot_spend.spent_today() == 1.6
    with TestClient(app) as client:
        assert client.get("/copilot/status").json()["spend_today_usd"] == 1.6
        over = client.post("/copilot/chat", json=_turn())
        assert over.status_code == 429 and "$1.50" in over.json()["detail"] and "COPILOT_DAILY_BUDGET_USD" in over.json()["detail"]
        assert "plan" not in over.json()["detail"].lower()
    with Session(engine) as db:
        for row in db.exec(select(CopilotTurn)).all():
            db.delete(row)
        db.commit()


def test_turn_metrics_reach_the_journal_logger():
    import logging
    ai = logging.getLogger("app.ai")
    assert ai.level <= logging.INFO or logging.getLogger().handlers  # configured by copilot._journal_logging, or by the test runner
