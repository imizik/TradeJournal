"""A3 fixtures prove storage/isolation; never human/live acceptance."""
from datetime import date, datetime, timedelta, timezone
import json
import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.database import get_session
from app.engine import paper, practice, practice_agent
from app.engine.job_runtime import job_lane
from app.models import DecisionRecord, JobRun, PracticeAgentCall, PracticeRun
from app.routers import decisions as decision_routes, practice as routes

UTC = timezone.utc


class Calendar:
    def __init__(self, hours=None):
        self.value = hours or {"status": "open", "open": 570, "close": 960, "source": "tradier"}

    def hours(self, day):
        return {**self.value, "date": day.isoformat()} if self.value != "unavailable" else None


def packet(symbol):
    stamp = datetime.now(UTC) - timedelta(minutes=2)
    return {"symbol": symbol, "data_source": "alpaca_sip",
        "journal_activity": "SECRET_JOURNAL", "human_decision": "SECRET_HUMAN",
        "recent_minute_bars": [{"t": stamp.isoformat(), "o": 100, "h": 102, "l": 99, "c": 101}]}


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


@pytest.fixture
def http(db, monkeypatch):
    app = FastAPI()
    app.include_router(routes.router, prefix="/practice")
    app.include_router(decision_routes.router, prefix="/decisions")
    app.dependency_overrides[get_session] = lambda: db
    monkeypatch.setattr(routes, "submit_job", lambda _: None)
    with TestClient(app) as client:
        yield client


def prepared(db, calendar=None, loader=packet):
    run = practice.start(db)
    practice.prepare(db, run, calendar=calendar or Calendar(), packet_loader=loader)
    return run


def skip():
    return {"decision": "skip", "rationale": "No clean setup"}


def enable(monkeypatch):
    monkeypatch.setattr(practice_agent, "config", lambda: {"model": "fixture", "timeout_seconds": 2,
        "input_tokens": 20000, "output_tokens": 2000, "daily_usd": 1,
        "input_usd_per_million": 1, "output_usd_per_million": 1})


def answer(payload, limits):
    return {"raw": json.dumps({"choices": [{"opportunity_id": o["opportunity_id"], **skip()} for o in payload["opportunities"]]}),
        "usage": {"input_tokens": 200, "output_tokens": 100}, "stop_reason": "end_turn"}


def test_canonical_retries_revision_and_mode_are_frozen(db):
    first = practice.start(db, mode="manual")
    assert practice.start(db, mode="scheduled", comparison="assisted").id == first.id
    assert len(practice.opportunities(db, first.id)) == 5
    assert db.exec(select(JobRun)).one().job_type == "practice_prepare"
    with pytest.raises(ValueError, match="still active"):
        practice.start(db, revision=1)
    practice.prepare(db, first, calendar=Calendar(), packet_loader=packet)
    revised = practice.start(db, revision=1)
    assert revised.parent_id == first.id and revised.comparison == "assisted"
    assert practice.start(db, revision=1).id == revised.id
    assert len(db.exec(select(PracticeRun)).all()) == 2


@pytest.mark.parametrize("day,deadline", [(date(2026, 3, 6), 14), (date(2026, 3, 9), 13), (date(2026, 11, 2), 14)])
def test_et_deadline_dst(db, day, deadline):
    run = practice.start(db, day=day, now=datetime(day.year, day.month, day.day, deadline, 1))
    assert run.deadline.hour == deadline and run.late


@pytest.mark.parametrize("calendar,result", [(Calendar("unavailable"), "failed"), (Calendar({"status": "closed"}), "no_session")])
def test_calendar_never_invents_session(db, calendar, result):
    run = prepared(db, calendar)
    assert run.result == result
    assert all((o.context_id is None) == (result == "no_session") for o in practice.opportunities(db, run.id))


def test_provider_failure_keeps_nonresponse_and_valid_skip(db):
    def fail(symbol):
        raise RuntimeError("fixture outage")
    run = prepared(db, loader=fail)
    view = practice.view(db, run)
    assert view["result"] == "failed" and view["agent"]["cost"] is None
    opp = practice.opportunities(db, run.id)[0]
    practice.choose(db, opp, skip())
    assert practice.view(db, run)["counts"] == {"take": 0, "wait": 0, "skip": 1}
    assert len([o for o in practice.view(db, run)["opportunities"] if o["human"] is None]) == 4
    with pytest.raises(ValueError):
        practice.choose(db, practice.opportunities(db, run.id)[1], {"decision": "take", "plan": {}})


def test_independent_output_hidden_on_all_owner_endpoints_until_both_commit(db, http, monkeypatch):
    enable(monkeypatch)
    run = practice.start(db)
    practice.prepare(db, run, calendar=Calendar(), packet_loader=packet, adapter=answer)
    assert run.result == "no_setup"
    assert practice.view(db, run)["result"] != "no_setup"  # no global verdict leak
    opp = practice.opportunities(db, run.id)[0]
    agent = practice.records(db, opp)["agent:a3"]
    assert http.get(f"/practice/runs/{run.id}").json()["opportunities"][0]["agent"] is None
    assert http.get(f"/decisions/{agent.id}").status_code == 404
    assert http.get(f"/decisions/{agent.id}/paper").status_code == 404
    assert http.post(f"/decisions/{agent.id}/arm", json={"operation_id": "probe"}).status_code == 404
    assert http.get("/decisions").json()["decisions"] == []
    assert http.post(f"/practice/opportunities/{opp.id}/reveal", json={}).status_code == 409
    chosen = http.post(f"/practice/opportunities/{opp.id}/choice", json=skip())
    assert chosen.status_code == 200
    assert chosen.json()["opportunities"][0]["agent"] is None
    revealed = http.post(f"/practice/opportunities/{opp.id}/reveal", json={}).json()
    assert revealed["opportunities"][0]["agent"]["id"] == str(agent.id)
    assert http.get(f"/decisions/{agent.id}").status_code == 200
    assert http.post(f"/practice/opportunities/{opp.id}/choice", json={"decision": "skip", "rationale": "changed"}).status_code == 409
    assert http.post(f"/practice/opportunities/{opp.id}/choice", json=skip()).status_code == 200


def test_forged_actor_context_and_runner_operations_denied(db, http):
    run = prepared(db)
    opp = practice.opportunities(db, run.id)[0]
    for forged in ({"actor": "agent:a3"}, {"context_id": str(uuid.uuid4())}, {"opportunity_id": "other"}):
        assert http.post(f"/practice/opportunities/{opp.id}/choice", json={**skip(), **forged}).status_code == 422
    payload = {"operation_id": "forged", "opportunity_id": f"a3:{opp.id}", "actor": "human", "symbol": opp.symbol, "context_id": str(opp.context_id), **skip()}
    assert http.post("/decisions", json=payload).status_code == 422
    payload["opportunity_id"] = "unowned"
    assert http.post("/decisions", json=payload).status_code == 422
    assert http.get("/practice/runner/journal").status_code == 404
    assert http.post("/practice/runner/arm", json={}).status_code == 404
    submitted = practice.runner_payload(db, run)
    assert "SECRET" not in json.dumps(submitted)
    assert set(submitted) == {"prompt_version", "policy", "deadline", "benchmark", "session_calendar", "plan_contract", "opportunities"}
    assert set(submitted["opportunities"][0]) == {"opportunity_id", "symbol", "context_sha256", "price_facts"}


@pytest.mark.parametrize("kind,status", [("malformed", "invalid"), ("forged", "invalid"), ("timeout", "uncertain"), ("missing_usage", "completed")])
def test_model_failures_exact_output_usage_and_no_paid_retry(db, monkeypatch, kind, status):
    enable(monkeypatch)
    run = practice.start(db)
    calls = []
    def adapter(payload, limits):
        calls.append(payload)
        if kind == "timeout":
            raise TimeoutError()
        result = answer(payload, limits)
        if kind == "malformed":
            result["raw"] = "bad json"
        elif kind == "forged":
            result["raw"] = json.dumps({"choices": [{"opportunity_id": o["opportunity_id"], "actor": "human", **skip()} for o in payload["opportunities"]]})
        elif kind == "missing_usage":
            result["usage"] = None
        return result
    practice.prepare(db, run, calendar=Calendar(), packet_loader=packet, adapter=adapter)
    saved = db.exec(select(PracticeAgentCall)).one()
    assert saved.status == status
    assert saved.payload_json == json.dumps(calls[0])
    assert saved.cost_usd is None if kind in {"timeout", "missing_usage"} else saved.cost_usd > 0
    if status != "completed":
        assert not db.exec(select(DecisionRecord)).all()
    with pytest.raises(ValueError, match="already reserved"):
        practice.run_agent(db, run, adapter=adapter)
    assert len(calls) == 1


def test_daily_budget_refuses_before_adapter(db, monkeypatch):
    run = prepared(db)
    enable(monkeypatch)
    configured = practice_agent.config()
    configured["daily_usd"] = 0.000001
    monkeypatch.setattr(practice_agent, "config", lambda: configured)
    assert practice.run_agent(db, run, adapter=lambda *_: pytest.fail("paid call")) == "budget_exhausted"
    assert db.exec(select(PracticeAgentCall)).one().output_json is None


def test_interrupted_run_retains_evidence_and_requires_revision(db):
    run = practice.start(db)
    job = db.get(JobRun, run.job_id)
    job.status = "failed"
    db.add(job)
    db.commit()
    assert practice.view(db, run)["status"] == "failed"
    assert practice.start(db).id == run.id
    assert practice.start(db, revision=1).parent_id == run.id


def test_manual_timings_and_feedback_are_reported_not_inferred(db, http, monkeypatch):
    monkeypatch.delenv("PRACTICE_SCHEDULE_ENABLED", raising=False)
    run = prepared(db)
    opp = practice.opportunities(db, run.id)[0]
    assert http.post("/practice/prepare", json={"mode": "scheduled"}).status_code == 403
    assert http.post(f"/practice/runs/{run.id}/timing", json={"phase": "morning", "seconds": 145}).status_code == 200
    view = http.post(f"/practice/runs/{run.id}/timing", json={"phase": "review", "seconds": 220, "reason": "Investigated missing data"}).json()
    assert view["timings"]["morning"]["seconds"] + view["timings"]["review"]["seconds"] == 365
    assert view["mode"] == "manual"
    rated = http.post(f"/practice/opportunities/{opp.id}/feedback", json={"rating": "useful", "phone_received": True}).json()
    assert rated["opportunities"][0]["feedback"]["phone_received"] is True
    assert len(db.exec(select(DecisionRecord)).all()) == 0


def test_benchmark_regular_full_coverage_and_early_close():
    day = date(2026, 11, 27)
    hours = {"status": "open", "open": 570, "close": 780}
    session = paper.regular_session(day, hours)
    bars = [{"time": t, "source": "tradier", "open": 100, "high": 102, "low": 99, "close": 101} for t in range(session.open_at, session.close_at, 60)]
    now = datetime.fromtimestamp(session.close_at, UTC).replace(tzinfo=None)
    full = practice.benchmark(day, hours, bars, {"status": "ok", "splits": []}, now=now)
    assert full["status"] == "complete" and full["return_pct"] == pytest.approx(1)
    assert full["expected_minutes"] == 210
    assert practice.benchmark(day, hours, bars[:-1], {"status": "ok"}, now=now)["status"] == "unavailable"
    assert practice.benchmark(day, hours, bars, {"status": "stale"}, now=now)["status"] == "unavailable"
    assert practice.benchmark(day, hours, bars, {"status": "ok"}, now=now-timedelta(seconds=1))["status"] == "unavailable"


def test_dedicated_lane_and_scheduler_default_off(monkeypatch, capsys):
    from app.jobs import practice_schedule
    assert job_lane("practice_prepare") == "practice"
    assert job_lane("capture_transcribe") == "capture"
    monkeypatch.delenv("PRACTICE_SCHEDULE_ENABLED", raising=False)
    monkeypatch.setattr(practice_schedule, "ensure_current", lambda _: pytest.fail("disabled must not touch DB"))
    practice_schedule.main()
    assert "disabled" in capsys.readouterr().out


def test_missed_schedule_records_deadline_without_paid_or_market_calls(db, monkeypatch):
    moment = datetime(2026, 10, 8, 14)
    monkeypatch.setattr(practice, "now_utc", lambda: moment)
    run = practice.start(db, mode="scheduled", now=moment)
    practice.prepare(db, run, calendar=Calendar(), packet_loader=lambda _: pytest.fail("market call"), adapter=lambda *_: pytest.fail("paid call"))
    assert run.status == "late" and run.result == "missed_deadline"
    assert all(o.context_id is None for o in practice.opportunities(db, run.id))


def test_runner_child_has_no_database_environment_or_application_tools(monkeypatch):
    import subprocess
    monkeypatch.setenv("DATABASE_URL", "secret-db")
    monkeypatch.setenv("MIGRATION_DATABASE_URL", "secret-owner-db")
    monkeypatch.setenv("API_INTERNAL_URL", "secret-private-api")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fixture-key")
    def child(command, **kwargs):
        assert "DATABASE_URL" not in kwargs["env"]
        assert "API_INTERNAL_URL" not in kwargs["env"]
        assert "MIGRATION_DATABASE_URL" not in kwargs["env"]
        assert kwargs["env"]["ANTHROPIC_API_KEY"] == "fixture-key"
        assert kwargs["timeout"] == 2
        request = json.loads(kwargs["input"])
        assert set(request) == {"payload", "limits"}
        assert "tools" not in request["payload"]
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps({"raw": "{}", "usage": None}))
    monkeypatch.setattr(subprocess, "run", child)
    assert practice_agent.invoke({"opportunities": []}, {"timeout_seconds": 2})["usage"] is None


def test_simultaneous_manual_scheduled_start_have_one_job(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    engine = create_engine(f"sqlite:///{tmp_path / 'concurrency.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    barrier = Barrier(2)
    def start(mode):
        with Session(engine) as db:
            barrier.wait()
            return practice.start(db, mode=mode).id
    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(pool.map(start, ["manual", "scheduled"]))
    assert ids[0] == ids[1]
    with Session(engine) as db:
        assert len(db.exec(select(JobRun)).all()) == 1
        assert len(practice.opportunities(db, ids[0])) == 5
    engine.dispose()


def test_a3_take_and_wait_reuse_a1_validation_without_arming(db, http):
    run = prepared(db)
    opp, waiting = practice.opportunities(db, run.id)[:2]
    plan = {"instrument": "stock", "direction": "long", "trigger": decisions_trigger(),
        "trigger_level": 101, "trigger_fact": "minute:0:c", "stop": 99, "stop_fact": "minute:0:l",
        "target": 102, "target_fact": "minute:0:h", "entry_guard": {"min": 101, "max": 101.5},
        "expiry": (datetime.now(UTC) + timedelta(days=1)).isoformat(), "max_holding_sessions": 2,
        "freshness_limit_seconds": 86400, "cost_model": paper.COST}
    response = http.post(f"/practice/opportunities/{opp.id}/choice", json={"decision": "take", "plan": plan})
    assert response.status_code == 200
    human = response.json()["opportunities"][0]["human"]
    assert human["plan"]["initial_risk_per_share"] == 2
    assert response.json()["opportunities"][0]["paper"]["events"] == []
    assert human["evidence_sha256"] == response.json()["opportunities"][0]["context"]["context_sha256"]
    assert http.post(f"/practice/opportunities/{waiting.id}/choice", json={"decision": "wait"}).status_code == 409
    response = http.post(f"/practice/opportunities/{waiting.id}/choice", json={"decision": "wait", "wait_condition": "Wait for verified opening facts", "wait_expiry": (datetime.now(UTC) + timedelta(days=1)).isoformat()})
    assert response.status_code == 200
    assert response.json()["counts"] == {"take": 1, "wait": 1, "skip": 0}


def decisions_trigger():
    return {"kind": "close_beyond_level", "interval": "15m", "session": "regular"}


def test_a3_agent_cap_refuses_all_four_take_output_before_any_commit(db, monkeypatch):
    enable(monkeypatch)
    run = practice.start(db)
    def too_many(payload, _limits):
        return {"raw": json.dumps({"choices": [{"opportunity_id": o["opportunity_id"], "decision": "take" if i < 4 else "skip", "rationale": "fixture", "plan": {} if i < 4 else None} for i, o in enumerate(payload["opportunities"])]}), "stop_reason": "end_turn"}
    practice.prepare(db, run, calendar=Calendar(), packet_loader=packet, adapter=too_many)
    assert db.exec(select(PracticeAgentCall)).one().status == "invalid"
    assert not db.exec(select(DecisionRecord)).all()
