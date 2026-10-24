"""Copilot Lab research queue (docs/copilot-lab.md § Research queue): jobs, triggers, runner, routes. Stubbed jobs only."""
import asyncio
import copy
import json
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, delete, select

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


def _claim():
    return q.claim_next(0.5, 2.0)


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
        claimed = _claim()
        assert claimed["id"] == job["id"] and claimed["attempts"] == attempt
        out = q.record_outcome(job["id"], cost_usd=0.1, investigation_id=None, error={"code": "timeout", "message": "slow"})
        assert out["status"] == "queued" and out["error"] == "timeout: slow" and _claim() is None  # backing off
        with Session(engine) as db:
            row = db.get(ResearchJob, uuid.UUID(job["id"]))
            row.next_attempt_at = datetime.utcnow() - timedelta(seconds=1)
            db.add(row)
            db.commit()
    _claim()
    out = q.record_outcome(job["id"], cost_usd=0.1, investigation_id=None, error={"code": "timeout", "message": "slow"})
    assert out["status"] == "failed" and out["attempts"] == 3 and out["cost_usd"] == pytest.approx(0.3)

    other, _ = q.enqueue_question("q2", [])
    _claim()
    assert q.record_outcome(other["id"], cost_usd=None, investigation_id=None,
                            error={"code": "plan_local_only", "message": "x"})["status"] == "failed"


def test_cancelled_while_running_stays_cancelled_and_restart_requeues():
    job, _ = q.enqueue_question("q", [])
    _claim()
    q.cancel(job["id"])
    out = q.record_outcome(job["id"], cost_usd=0.2, investigation_id="00000000-0000-0000-0000-000000000002", error=None)
    assert out["status"] == "cancelled" and out["cost_usd"] == 0.2 and out["investigation_id"].endswith("2")

    second, _ = q.enqueue_question("q3", [])
    _claim()
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
    RadarStore(tmp_path / "empty.sqlite")  # a store without the event
    monkeypatch.setenv("RADAR_STORE", str(tmp_path / "empty.sqlite"))
    with pytest.raises(q.QueueError, match="not in the Radar store"):
        q.assignment(job)
    for missing in (str(tmp_path / "missing.sqlite"), "relative/radar.sqlite", ""):  # never created, relative, unset
        monkeypatch.setenv("RADAR_STORE", missing)
        with pytest.raises(q.QueueError, match="RADAR_STORE"):
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
    _claim()
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
        # Asked from a saved investigation: the link is recorded for the lab to show; the job's assignment ignores it.
        source = "0b5a3e1c-8f3a-4d7e-9a49-6a2f1d0c7b11"
        linked = client.post("/copilot/research-jobs", json={"question": "Deeper on NBIS?", "symbols": ["NBIS"], "investigation_id": source}).json()["job"]
        assert linked["input"] == {"question": "Deeper on NBIS?", "symbols": ["NBIS"], "from_investigation": source}
        assert q.assignment(linked) == ("Deeper on NBIS?", ["NBIS"], "Deeper on NBIS?")
        assert client.post("/copilot/research-jobs", json={"question": "x", "investigation_id": "not-a-uuid"}).status_code == 422


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



# --------------------------------------------------------------------------- review fixes: spend, reassess, stuck, shutdown

def _skip_backoff():
    with Session(engine) as db:
        for job in db.exec(select(ResearchJob)):
            job.next_attempt_at = datetime.utcnow() - timedelta(seconds=1)
            db.add(job)
        db.commit()


def test_attempts_with_unknown_cost_are_charged_their_budget_so_the_cap_holds():
    """Six always-timing-out jobs report no cost: each attempt is charged its $0.50 budget, so a $2 day stops at 4."""
    for i in range(6):
        q.enqueue_question(f"q{i}", [])

    async def timeout(question, symbols, evidence, *, now, title, lim):
        return {"status": "error", "error": {"code": "timeout", "message": "slow"}, "saved_id": None}  # no metrics

    ran = 0
    for _ in range(30):
        _skip_backoff()
        if asyncio.run(_runner(timeout).run_once()) is None:
            break
        ran += 1
    assert ran == 4 and q.spent_today() == pytest.approx(2.0)
    assert all(e["estimated"] for j in q.list_jobs() for e in j["spend"])


def test_retry_pending_cancelled_and_interrupted_attempts_all_count():
    failing, _ = q.enqueue_question("sdk", [])

    async def sdk_fail(question, symbols, evidence, *, now, title, lim):
        return {"status": "error", "error": {"code": "sdk", "message": "x"}, "metrics": {"cost_usd": 0.3}, "saved_id": None}

    assert asyncio.run(_runner(sdk_fail).run_once())["status"] == "queued"
    assert q.spent_today() == pytest.approx(0.3)  # real cost of a job that is not finished yet

    restarted, _ = q.enqueue_question("restart", [])
    _claim()
    q.requeue_interrupted()
    assert q.get(restarted["id"])["spend"][0]["usd"] == 0.5 and q.spent_today() == pytest.approx(0.8)

    slow_job, _ = q.enqueue_question("slow", [])

    async def slow(question, symbols, evidence, *, now, title, lim):
        await asyncio.sleep(30)

    async def scenario():
        task = asyncio.create_task(_runner(slow, cancel_poll_s=0.05).run_once())
        await asyncio.sleep(0.1)
        await asyncio.to_thread(q.cancel, slow_job["id"])
        return await asyncio.wait_for(task, 5)

    q.cancel(restarted["id"])
    q.cancel(failing["id"])
    out = asyncio.run(scenario())
    assert out["id"] == slow_job["id"] and out["status"] == "cancelled" and out["cost_usd"] == 0.5
    assert out["error"] is None or "cancelled" in out["error"]
    assert q.spent_today() == pytest.approx(1.3)


def test_refused_or_missing_input_costs_nothing(monkeypatch):
    monkeypatch.delenv("RADAR_STORE", raising=False)
    q.enqueue("radar_event", {"event_id": "gone"}, "radar_event:gone")
    out = asyncio.run(_runner(_done()).run_once())
    assert out["status"] == "failed" and out["cost_usd"] == 0.0 and q.spent_today() == 0.0


def test_a_broken_evidence_source_fails_the_job_instead_of_leaving_it_running():
    q.enqueue_question("q", [])

    def broken():
        raise RuntimeError("no store")

    out = asyncio.run(q.QueueRunner(CFG, run_job=_done(), evidence_factory=broken).run_once())
    assert out["status"] == "failed" and out["error"].startswith("input_error: RuntimeError") and _claim() is None


def test_reassessments_stay_one_per_original_per_day_over_several_days(monkeypatch):
    clock = {"now": datetime(2026, 10, 26, 14, 0)}
    monkeypatch.setattr(q, "_utcnow", lambda: clock["now"])
    original = inv.save_research_result(title="Neocloud financing", symbol="CRWV", findings={"summary": "Debt."})
    other = inv.save_research_result(title="Fresh question", symbol="NBIS", findings={"summary": "s"})

    def age_everything():  # every investigation, outputs included, looks stale
        with Session(engine) as db:
            for row in db.exec(select(CopilotInvestigation)):
                row.updated_at = clock["now"] - timedelta(hours=30)
                db.add(row)
            db.commit()

    async def reassess(question, symbols, evidence, *, now, title, lim):
        saved = inv.save_research_result(title=title, symbol=(symbols or [None])[0], findings={"summary": "new"})
        return {"status": "ok", "metrics": {"cost_usd": 0.01}, "saved_id": saved["id"]}

    created = []
    for day in range(4):
        age_everything()
        created.append(q.enqueue_reassessments(24))
        while asyncio.run(_runner(reassess).run_once()) is not None:
            pass
        clock["now"] += timedelta(hours=25)
    assert created == [2, 2, 2, 2]  # the two originals, once a day; outputs are never reassessed
    jobs = q.list_jobs()
    assert {j["input"]["investigation_id"] for j in jobs} == {original["id"], other["id"]}
    with Session(engine) as db:
        assert len(list(db.exec(select(CopilotInvestigation)))) == 2 + 8


def test_a_waiting_reassessment_blocks_another():
    stale = inv.save_research_result(title="Old", symbol="CRWV", findings={"summary": "s"})
    with Session(engine) as db:
        row = db.get(CopilotInvestigation, uuid.UUID(stale["id"]))
        row.updated_at = datetime.utcnow() - timedelta(hours=30)
        db.add(row)
        db.commit()
    assert q.enqueue_reassessments(24) == 1
    with Session(engine) as db:  # an older day's job is still queued
        job = db.exec(select(ResearchJob)).one()
        job.created_at, job.dedupe_key = job.created_at - timedelta(days=2), "reassess:old"
        db.add(job)
        db.commit()
    assert q.enqueue_reassessments(24) == 0


def test_shutdown_stops_the_attempt_and_puts_the_job_back():
    job, _ = q.enqueue_question("slow", [])
    seen = {}

    async def slow(question, symbols, evidence, *, now, title, lim):
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            seen["cancelled"] = True
            raise

    async def scenario():
        loop = asyncio.create_task(_runner(slow, cancel_poll_s=0.05).loop())
        await asyncio.sleep(0.3)
        loop.cancel()
        await asyncio.gather(loop, return_exceptions=True)

    asyncio.run(scenario())
    after = q.get(job["id"])
    assert seen.get("cancelled") and after["status"] == "queued" and after["error"] == "interrupted by a shutdown"
    assert after["spend"][0]["usd"] == 0.5


def test_malformed_numbers_fall_back_instead_of_crashing(monkeypatch):
    monkeypatch.setenv("RESEARCH_DAILY_BUDGET_USD", "two dollars")
    monkeypatch.setenv("RESEARCH_REASSESS_AFTER_HOURS", "1.5")
    cfg = q.settings()
    assert cfg.daily_budget_usd == 2.0 and cfg.reassess_after_hours == 0


def test_a_question_is_its_own_job_per_investigation_and_can_be_asked_again_after_it_fails():
    a, b = str(uuid.uuid4()), str(uuid.uuid4())
    job_a, _ = q.enqueue_question("Why is NBIS lagging?", ["NBIS"], from_investigation=a)
    job_b, created = q.enqueue_question("Why is NBIS lagging?", ["NBIS"], from_investigation=b)
    assert created and job_b["id"] != job_a["id"]  # B gets its own job instead of A's
    assert [j["id"] for j in q.list_jobs(from_investigation=a)] == [job_a["id"]]
    assert [j["id"] for j in q.list_jobs(from_investigation=b)] == [job_b["id"]]
    assert q.enqueue_question("Why is NBIS lagging?", ["NBIS"], from_investigation=a)[1] is False  # still queued: dedupes

    # Failed or cancelled: asking again queues a new job, and the old one keeps its outcome.
    with Session(engine) as db:
        row = db.get(ResearchJob, uuid.UUID(job_a["id"]))
        row.status, row.error = "failed", "timed out"
        db.commit()
    retry, created = q.enqueue_question("Why is NBIS lagging?", ["NBIS"], from_investigation=a)
    assert created and retry["id"] != job_a["id"] and retry["status"] == "queued"
    assert {j["id"]: j["status"] for j in q.list_jobs(from_investigation=a)} == {retry["id"]: "queued", job_a["id"]: "failed"}
    q.cancel(retry["id"])
    again, created = q.enqueue_question("Why is NBIS lagging?", ["NBIS"], from_investigation=a)
    assert created and again["id"] not in (retry["id"], job_a["id"])
    # A done job still dedupes for the day.
    with Session(engine) as db:
        db.get(ResearchJob, uuid.UUID(again["id"])).status = "done"
        db.commit()
    assert q.enqueue_question("Why is NBIS lagging?", ["NBIS"], from_investigation=a) == (q.list_jobs(from_investigation=a)[0], False)

    # Only owner-asked questions are retried: a trigger's failed job keeps its key, so a pass does not queue it again.
    radar, _ = q.enqueue("radar_event", {"event_id": "evt-1"}, "radar_event:evt-1")
    with Session(engine) as db:
        db.get(ResearchJob, uuid.UUID(radar["id"])).status = "failed"
        db.commit()
    assert q.enqueue("radar_event", {"event_id": "evt-1"}, "radar_event:evt-1")[1] is False


def test_the_route_lists_one_investigations_jobs(monkeypatch):
    monkeypatch.delenv("RESEARCH_QUEUE_ENABLED", raising=False)
    a, b = str(uuid.uuid4()), str(uuid.uuid4())
    with TestClient(app) as client:
        for source, question in ((a, "q1"), (b, "q2"), (None, "q3")):
            client.post("/copilot/research-jobs", json={"question": question, **({"investigation_id": source} if source else {})})
        assert [j["input"]["question"] for j in client.get(f"/copilot/research-jobs?from_investigation={a}").json()["jobs"]] == ["q1"]
        assert len(client.get("/copilot/research-jobs").json()["jobs"]) == 3
        assert client.get("/copilot/research-jobs?from_investigation=nope").status_code == 422
