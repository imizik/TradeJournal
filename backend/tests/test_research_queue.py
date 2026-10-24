"""Copilot Lab research queue (docs/copilot-lab.md § Research queue): jobs, triggers, runner, routes. Stubbed jobs only."""
import asyncio
import copy
import json
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, delete

from app.database import engine
from app.engine import copilot_investigations as inv
from app.engine import research_queue as q
from app.main import app
from app.models import CopilotInvestigation, ResearchJob
from app.engine.radar_store import RadarStore
from tests.test_browser_access import boundary, signin  # noqa: F401  (the shared access fixture)

EVENT = json.loads((Path(__file__).parent / "fixtures" / "radar" / "sample_event.json").read_text())["event"]
CFG = q.QueueSettings(enabled=True, daily_budget_usd=2.0, radar_trigger=False, reassess_after_hours=0, idle_s=0)


@pytest.fixture(autouse=True)
def clean():
    with Session(engine) as db:
        db.exec(delete(ResearchJob))
        db.exec(delete(CopilotInvestigation))
        db.commit()
    yield


def _done(cost=0.1, saved="00000000-0000-0000-0000-000000000001", error=None):
    async def run(question, symbols, evidence, *, now, title, lim):
        run.calls.append({"question": question, "symbols": symbols, "title": title, "budget": lim.budget_usd})
        if error:
            return {"status": "error", "error": error, "metrics": {"cost_usd": cost}, "saved_id": None}
        return {"status": "ok", "metrics": {"cost_usd": cost}, "saved_id": saved}
    run.calls = []
    return run


def _runner(run, cfg=CFG, **kwargs):
    return q.QueueRunner(cfg, run_job=run, evidence_factory=lambda: "evidence", **kwargs)


# --------------------------------------------------------------------------- enqueue, dedupe, cancel

def test_defaults_are_off():
    cfg = q.settings()
    assert cfg.enabled is False and cfg.radar_trigger is False and cfg.reassess_after_hours == 0 and cfg.daily_budget_usd == 2.0


def test_question_jobs_dedupe_per_day_and_cancel():
    job, created = q.enqueue_question("Why are neoclouds weak?", ["NBIS"])
    again, created_again = q.enqueue_question("Why are neoclouds weak?", ["NBIS"])
    assert created and not created_again and again["id"] == job["id"] and job["status"] == "queued"
    assert q.enqueue_question("Why are neoclouds weak?", ["CRWV"])[1]
    assert q.cancel(job["id"])["status"] == "cancelled" and q.cancel(job["id"])["status"] == "cancelled"
    with pytest.raises(q.QueueError):
        q.cancel("not-a-uuid")
    with pytest.raises(q.QueueError):
        q.enqueue("trade", {}, "x")


def test_retry_with_backoff_then_failed_and_non_retryable_fails_at_once():
    job, _ = q.enqueue_question("q", [])
    for attempt in (1, 2):
        claimed = q.claim_next()
        assert claimed["id"] == job["id"] and claimed["attempts"] == attempt
        out = q.record_outcome(job["id"], cost_usd=0.1, investigation_id=None, error={"code": "timeout", "message": "slow"})
        assert out["status"] == "queued" and out["error"] == "timeout: slow" and q.claim_next() is None  # backing off
        with Session(engine) as db:
            row = db.get(ResearchJob, uuid.UUID(job["id"]))
            row.next_attempt_at = datetime.utcnow() - timedelta(seconds=1)
            db.add(row)
            db.commit()
    q.claim_next()
    out = q.record_outcome(job["id"], cost_usd=0.1, investigation_id=None, error={"code": "timeout", "message": "slow"})
    assert out["status"] == "failed" and out["attempts"] == 3 and out["cost_usd"] == pytest.approx(0.3)

    other, _ = q.enqueue_question("q2", [])
    q.claim_next()
    assert q.record_outcome(other["id"], cost_usd=None, investigation_id=None,
                            error={"code": "plan_local_only", "message": "x"})["status"] == "failed"


def test_cancelled_while_running_stays_cancelled_and_restart_requeues():
    job, _ = q.enqueue_question("q", [])
    q.claim_next()
    q.cancel(job["id"])
    out = q.record_outcome(job["id"], cost_usd=0.2, investigation_id="00000000-0000-0000-0000-000000000002", error=None)
    assert out["status"] == "cancelled" and out["cost_usd"] == 0.2 and out["investigation_id"].endswith("2")

    second, _ = q.enqueue_question("q3", [])
    q.claim_next()
    assert q.requeue_interrupted() == 1 and q.get(second["id"])["status"] == "queued"
    assert q.get(second["id"])["error"] == "interrupted by a restart"


# --------------------------------------------------------------------------- triggers

def test_radar_events_enqueue_once_and_become_an_assignment(tmp_path, monkeypatch):
    store_path = tmp_path / "radar.sqlite"
    RadarStore(store_path).append_event(copy.deepcopy(EVENT))
    assert q.enqueue_radar_events(str(store_path), EVENT["session_date"]) == 1
    assert q.enqueue_radar_events(str(store_path), EVENT["session_date"]) == 0
    [job] = q.list_jobs()
    assert job["kind"] == "radar_event" and job["input"] == {"event_id": EVENT["event_id"]}
    monkeypatch.setenv("RADAR_STORE", str(store_path))
    question, symbols, title = q.assignment(job)
    assert EVENT["first_seen_at"] in question and symbols == EVENT["symbols"][:8] and title.startswith("Radar:")
    monkeypatch.setenv("RADAR_STORE", str(tmp_path / "missing.sqlite"))
    RadarStore(tmp_path / "missing.sqlite")  # an empty store: the event is gone
    with pytest.raises(q.QueueError):
        q.assignment(job)


def test_stale_open_investigations_get_one_reassessment_a_day():
    fresh = inv.save_research_result(title="Fresh", symbol="NBIS", findings={"summary": "s"})
    stale = inv.save_research_result(title="Neocloud financing", symbol="CRWV",
                                     findings={"summary": "Debt worries.", "key_findings": ["Yields up [1]"]})
    with Session(engine) as db:
        row = db.get(CopilotInvestigation, uuid.UUID(stale["id"]))
        row.updated_at = datetime.utcnow() - timedelta(hours=30)
        db.add(row)
        db.commit()
    assert q.enqueue_reassessments(24) == 1 and q.enqueue_reassessments(24) == 0
    [job] = q.list_jobs()
    assert job["input"] == {"investigation_id": stale["id"]} and fresh["id"] not in json.dumps(job)
    question, symbols, title = q.assignment(job)
    assert "Debt worries." in question and "Yields up [1]" in question and symbols == ["CRWV"]
    assert title == "Reassess: Neocloud financing"


# --------------------------------------------------------------------------- the runner

def test_runner_runs_one_job_and_records_the_result():
    job, _ = q.enqueue_question("Why?", ["NBIS"])
    run = _done(cost=0.12)
    out = asyncio.run(_runner(run).run_once())
    assert out["id"] == job["id"] and out["status"] == "done" and out["cost_usd"] == 0.12 and out["investigation_id"].endswith("1")
    assert run.calls == [{"question": "Why?", "symbols": ["NBIS"], "title": "Why?", "budget": 0.5}]
    assert asyncio.run(_runner(run).run_once()) is None  # nothing left


def test_runner_retries_failures_and_records_missing_saves():
    job, _ = q.enqueue_question("Why?", [])
    out = asyncio.run(_runner(_done(error={"code": "sdk", "message": "boom"})).run_once())
    assert out["status"] == "queued" and out["error"] == "sdk: boom"
    other, _ = q.enqueue_question("Other", [])
    out = asyncio.run(_runner(_done(saved=None)).run_once())
    assert out["id"] == other["id"] and out["status"] == "failed" and out["error"].startswith("save_failed")


def test_daily_budget_cap_holds_jobs_and_caps_the_job_budget():
    spent, _ = q.enqueue_question("spent", [])
    q.claim_next()
    q.record_outcome(spent["id"], cost_usd=1.8, investigation_id=None, error=None)
    q.enqueue_question("next", [])
    run = _done()
    asyncio.run(_runner(run).run_once())
    assert run.calls[0]["budget"] == pytest.approx(0.2)  # what is left of the $2 day
    held = q.QueueSettings(enabled=True, daily_budget_usd=1.0, radar_trigger=False, reassess_after_hours=0)
    q.enqueue_question("held", [])
    assert asyncio.run(_runner(_done(), cfg=held).run_once()) is None
    assert any(j["status"] == "queued" for j in q.list_jobs())


def test_cancel_stops_a_running_job():
    job, _ = q.enqueue_question("slow", [])

    async def slow(question, symbols, evidence, *, now, title, lim):
        await asyncio.sleep(30)

    async def scenario():
        runner = _runner(slow, cancel_poll_s=0.05)
        task = asyncio.create_task(runner.run_once())
        await asyncio.sleep(0.1)
        await asyncio.to_thread(q.cancel, job["id"])
        return await asyncio.wait_for(task, 5)

    assert asyncio.run(scenario())["status"] == "cancelled"


def test_a_missing_input_fails_the_job_without_running_it(monkeypatch):
    monkeypatch.delenv("RADAR_STORE", raising=False)
    q.enqueue("radar_event", {"event_id": "gone"}, "radar_event:gone")
    run = _done()
    out = asyncio.run(_runner(run).run_once())
    assert out["status"] == "failed" and out["error"].startswith("not_found") and run.calls == []


# --------------------------------------------------------------------------- routes and startup

def test_owner_routes_enqueue_list_and_cancel(monkeypatch):
    monkeypatch.delenv("RESEARCH_QUEUE_ENABLED", raising=False)
    with TestClient(app) as client:
        assert app.state.research_queue is None  # the runner stays off by default
        made = client.post("/copilot/research-jobs", json={"question": "Why are neoclouds weak?", "symbols": ["nbis"]})
        assert made.status_code == 201 and made.json()["created"] and made.json()["queue_enabled"] is False
        job = made.json()["job"]
        assert job["input"] == {"question": "Why are neoclouds weak?", "symbols": ["NBIS"]}
        assert client.post("/copilot/research-jobs", json={"question": "Why are neoclouds weak?", "symbols": ["NBIS"]}).json()["created"] is False
        listed = client.get("/copilot/research-jobs").json()
        assert [j["id"] for j in listed["jobs"]] == [job["id"]] and listed["daily_budget_usd"] == 2.0
        assert client.post(f"/copilot/research-jobs/{job['id']}/cancel").json()["job"]["status"] == "cancelled"
        assert client.post("/copilot/research-jobs/nope/cancel").status_code == 404
        assert client.post("/copilot/research-jobs", json={"question": "x", "symbols": ["../etc"]}).status_code == 422
        assert client.post("/copilot/research-jobs", json={"question": ""}).status_code == 422


def test_assistant_sessions_cannot_reach_the_queue(boundary):  # noqa: F811
    assert boundary.owner.get("/copilot/research-jobs").status_code == 200
    assert signin(boundary).status_code == 200
    assert boundary.public.get("/copilot/research-jobs").status_code == 403
    assert boundary.public.post("/copilot/research-jobs", json={"question": "NBIS?"}).status_code == 403
    assert boundary.public.post("/copilot/research-jobs/x/cancel").status_code == 403


def test_the_runner_starts_only_when_enabled(monkeypatch):
    monkeypatch.setenv("RESEARCH_QUEUE_ENABLED", "true")
    monkeypatch.setenv("RESEARCH_DAILY_BUDGET_USD", "0")  # started, but nothing may run
    with TestClient(app):
        assert isinstance(app.state.research_queue, q.QueueRunner) and app.state.research_queue.cfg.daily_budget_usd == 0
