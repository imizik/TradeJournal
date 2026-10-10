"""Actual auth and persistence prove the sample writer's resource boundary."""
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace
import uuid

import pytest
from sqlmodel import Session, select
from starlette.middleware import Middleware

from app.engine import decisions, paper, sample_practice
from app.main import app
from app.models import AccessPrincipal, DecisionRecord, PracticeOpportunity, PracticeRun, Fill, DecisionEvent
from tests.test_browser_access import boundary as boundary, signin
from tests.test_dot_trial import trial


@pytest.fixture
def writer(boundary):
    for name in ("TJ_ACCESS_SAMPLE_DATA", "TJ_DOT_TRIAL_ENABLED", "TJ_SAMPLE_DECISION_WRITES"):
        boundary.patch.setenv(name, "true")
    boundary.patch.setattr(app, "user_middleware", [app.user_middleware[0], Middleware(trial.FixtureMarket), *app.user_middleware[1:]])
    boundary.patch.setattr(app, "middleware_stack", None)
    with Session(boundary.engine) as db:
        run = sample_practice.prepare(db)
        opportunities = db.exec(select(PracticeOpportunity).where(PracticeOpportunity.run_id == run.id)).all()
        grants = {"symbols": ["MU", "NBIS"], "run_ids": [str(run.id)], "journal_read": False, "decision_write": True}
    created = boundary.owner.post("/access/assistants", json={"identifier": "writer", "grants": grants})
    assert created.status_code == 201, created.text
    boundary.key = created.json()["key"]
    assert signin(boundary, identifier="writer").status_code == 200
    return SimpleNamespace(**vars(boundary), run=run, opportunities={opp.symbol: opp for opp in opportunities}, grants=grants)


def choose(w, selected="MU", **overrides):
    body = {"decision": "skip", "rationale": "No clear setup in this simulated exercise", **overrides}
    return w.public.post(f"/practice/opportunities/{w.opportunities[selected].id}/agent-choice", json=body)


def test_write_receipt_retry_reopen_and_immutability(writer):
    first = choose(writer)
    assert first.status_code == 201, first.text
    record = first.json()["opportunities"][0]["choice"]
    assert record["actor"] == "agent:writer"
    assert record["policy_version"] == decisions.SAMPLE_POLICY_VERSION
    assert record["policy_hash"] == decisions.SAMPLE_POLICY_HASH != decisions.POLICY_HASH
    assert record["evidence"]["packet"]["sample_data"] is True
    again = choose(writer)
    assert again.status_code == 200
    assert again.json()["opportunities"][0]["choice"]["id"] == record["id"]
    assert choose(writer, rationale="Changed my mind").status_code == 409
    reopened = writer.public.get("/decisions/" + record["id"])
    assert reopened.status_code == 200
    assert reopened.json()["record_sha256"] == record["record_sha256"]
    assert writer.public.patch("/decisions/" + record["id"], json={"decision": "take"}).status_code == 404
    with Session(writer.engine) as db:
        assert len(db.exec(select(DecisionRecord)).all()) == 1
        assert db.exec(select(Fill)).all() == []
        assert db.exec(select(DecisionEvent)).all() == []


def test_take_retains_simulated_provenance_and_cannot_arm(writer):
    run = writer.public.get(f"/practice/runs/{writer.run.id}").json()
    opp = next(item for item in run["opportunities"] if item["symbol"] == "MU")
    plan = opp["context"]["packet"]["sample_plan"]
    response = choose(writer, decision="take", plan=plan)
    assert response.status_code == 201, response.text
    record = next(item["choice"] for item in response.json()["opportunities"] if item["symbol"] == "MU")
    assert record["plan"]["trigger_source"]["source"] == "sample_fixture"
    assert record["plan"]["trigger_source"]["split_basis"] == "simulated_raw"
    assert record["plan"]["initial_risk_per_share"] == 2
    assert writer.public.post(f"/decisions/{record['id']}/arm", json={"operation_id": "forged-arm"}).status_code == 403
    assert writer.public.get(f"/decisions/{record['id']}/paper").status_code == 403
    with Session(writer.engine) as db:
        with pytest.raises(paper.PaperError):
            paper.arm(db, uuid.UUID(record["id"]), "arm-sample", now=datetime.now(timezone.utc), calendar=None)
        # The ordinary live source validation also refuses the same sample facts.
        with pytest.raises(decisions.DecisionError, match="unsupported symbol or price basis"):
            decisions._validate_take("MU", datetime.fromisoformat(record["input_cutoff"]).replace(tzinfo=None),
                record["evidence"], plan, datetime.now(timezone.utc).replace(tzinfo=None))


def test_writer_cannot_access_human_other_actor_or_other_run(writer):
    opp = writer.opportunities["MU"]
    with Session(writer.engine) as db:
        for identity in ("human", "agent:someone-else"):
            decisions.create(db, {"operation_id": identity, "opportunity_id": f"a3:{opp.id}", "actor": identity,
                "decision": "skip", "symbol": "MU", "context_id": str(opp.context_id), "rationale": "PRIVATE CHOICE"}, routine=True)
        records = db.exec(select(DecisionRecord)).all()
    data = writer.public.get(f"/practice/runs/{writer.run.id}")
    assert data.status_code == 200
    assert "PRIVATE CHOICE" not in data.text and "human" not in data.text
    assert writer.public.get("/decisions").json() == {"decisions": []}
    for record in records:
        assert writer.public.get(f"/decisions/{record.id}").status_code == 404
    assert writer.public.get(f"/practice/runs/{uuid.uuid4()}").status_code == 404
    assert writer.public.post(f"/practice/opportunities/{uuid.uuid4()}/agent-choice", json={"decision": "skip", "rationale": "guess"}).status_code == 404
    for path in ("/fills", "/trades", "/accounts", "/stats", "/daily-review", "/charts/symbol/MU/you"):
        assert writer.public.get(path).status_code == 403
    for path in ("/decisions", "/decisions/context/MU", "/practice/prepare", f"/practice/opportunities/{opp.id}/choice", f"/practice/opportunities/{opp.id}/reveal"):
        assert writer.public.post(path, json={}).status_code == 403


@pytest.mark.parametrize("extra", [{"actor": "human"}, {"context_id": str(uuid.uuid4())}, {"symbol": "SPY"}, {"operation_id": "forge"}])
def test_server_owned_fields_cannot_be_forged(writer, extra):
    assert choose(writer, **extra).status_code == 422
    assert writer.public.get("/decisions").json()["decisions"] == []


def test_wait_validation_csrf_key_revocation_and_feature_disable(writer):
    assert choose(writer, decision="wait", wait_condition="later", wait_expiry="2020-01-01T00:00:00Z").status_code == 422
    response = choose(writer, decision="wait", wait_condition="Reassess after the simulated breakout", wait_expiry=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat())
    assert response.status_code == 201, response.text
    opp = writer.opportunities["NBIS"]
    assert writer.public.post(f"/practice/opportunities/{opp.id}/agent-choice", headers={"x-tj-csrf": "fake"}, json={"decision": "skip", "rationale": "x"}).status_code == 403
    writer.patch.setenv("TJ_SAMPLE_DECISION_WRITES", "false")
    assert choose(writer, "NBIS").status_code == 403
    assert writer.public.get(f"/practice/runs/{writer.run.id}").status_code == 403
    writer.patch.setenv("TJ_SAMPLE_DECISION_WRITES", "true")
    assert writer.owner.post("/access/assistants/writer/revoke", json={}).status_code == 200
    assert choose(writer, "NBIS").status_code == 401
    assert signin(writer, identifier="writer").status_code == 401


def test_symbol_grants_filter_evidence_and_saves(writer):
    assert choose(writer, "NBIS").status_code == 201
    with Session(writer.engine) as db:
        row = db.get(AccessPrincipal, "writer")
        row.grants_json = json.dumps({**writer.grants, "symbols": ["MU"]})
        db.add(row)
        db.commit()
    run = writer.public.get(f"/practice/runs/{writer.run.id}").json()
    assert [opp["symbol"] for opp in run["opportunities"]] == ["MU"]
    assert choose(writer, "NBIS").status_code == 404
    assert writer.public.get("/decisions").json()["decisions"] == []
    assert writer.public.get("/charts/workspace?symbol=SPY&watchlist=MU").status_code == 403


def test_existing_unassigned_run_and_opportunity_are_denied(writer):
    with Session(writer.engine) as db:
        run = PracticeRun(session_key="dot-sample-decision:other", day=writer.run.day, job_id=writer.run.job_id,
            mode="manual", comparison="assisted", status="prepared", deadline=writer.run.deadline,
            policy_version=decisions.SAMPLE_POLICY_VERSION, policy_hash=decisions.SAMPLE_POLICY_HASH)
        db.add(run)
        db.flush()
        opp = PracticeOpportunity(run_id=run.id, symbol="MU", context_id=writer.opportunities["MU"].context_id)
        db.add(opp)
        db.commit()
        run_id, opp_id = run.id, opp.id
    assert writer.public.get(f"/practice/runs/{run_id}").status_code == 404
    assert writer.public.post(f"/practice/opportunities/{opp_id}/agent-choice", json={"decision": "skip", "rationale": "Forged selected run"}).status_code == 404


def test_exercise_deadline_refuses_new_choices_but_preserves_retries_and_reads(writer):
    assert choose(writer).status_code == 201
    assert choose(writer, "NBIS", decision="wait", wait_condition="Later", wait_expiry=(datetime.now(timezone.utc) + timedelta(days=2)).isoformat()).status_code == 422
    with Session(writer.engine) as db:
        run = db.get(PracticeRun, writer.run.id)
        run.deadline = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=1)
        db.add(run)
        db.commit()
    assert choose(writer).status_code == 200
    assert choose(writer, "NBIS").status_code == 422
    assert len(writer.public.get("/decisions").json()["decisions"]) == 1


@pytest.mark.parametrize("change", [{"journal_read": True}, {"run_ids": []}, {"symbols": ["MU", "NBIS", "SPY"]}, {"decision_write": "true"}])
def test_writer_grant_is_bounded(writer, change):
    result = writer.owner.post("/access/assistants", json={"identifier": "bad-grant", "grants": {**writer.grants, **change}})
    assert result.status_code in {403, 422}


def test_simulated_chart_contract_has_nulls_studies_and_supported_intervals():
    for interval in ("1m", "3m", "5m", "15m", "30m", "1h", "4h", "1D", "1W"):
        bars = trial.candles("MU", interval)
        for bar in bars:
            assert all(key in bar for key in ("ema9", "ema20", "ema50", "ema200", "rsi", "vwap", "vwap_sd"))
        assert bars[-1]["ema9"] is not None and bars[-1]["rsi"] is not None
        assert bars[-1]["ema200"] is None and bars[-1]["vwap"] is None
