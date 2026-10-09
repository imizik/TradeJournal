"""Adversarial save and own-receipt coverage for the D2 sample choice bridge."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import uuid

from fastapi.testclient import TestClient
import httpx
import pytest
from sqlmodel import Session, select

from app.engine import access, cloud_practice_access, decisions
from app.main import app
from app.models import (AccessPrincipal, DecisionContext, DecisionEvent, DecisionRecord,
                        Fill, JobRun, PracticeOpportunity, PracticeRun)
from cloud_mcp_d1 import create_server
from cloud_mcp_d2_common import MAX_CHOICE_BYTES
from tests.test_cloud_mcp_d0 import _request, _token, signing_key as signing_key
from tests.test_browser_access import boundary as boundary
from tests.test_cloud_mcp_d1 import linked as d1linked  # noqa: F401
from tests.test_sample_practice import writer as writer, choose
from tests.test_sample_replay import replay as replay
from tests.test_dot_trial import trial as trial


@pytest.fixture
def linked(request):
    """D1's real linked OAuth fixture, explicitly opted into the D2 writer."""
    base_fixture = request.getfixturevalue("d1linked")
    cfg = json.loads(base_fixture.config.read_text())
    cfg["decision_writes"] = True
    base_fixture.config.write_text(json.dumps(cfg))
    for flag in ("TJ_CLOUD_MCP_DECISION_WRITES", "TJ_SAMPLE_DECISION_WRITES"):
        base_fixture.patch.setenv(flag, "true")
    base_fixture.patch.setenv("TJ_CLOUD_MCP_ENABLED", "true")
    cloud_practice_access.verifier.cache_clear()
    base_fixture.token = _token(base_fixture.signer, scope="d0:profile practice:read practice:write")
    base_fixture.backend.headers["authorization"] = "Bearer " + base_fixture.token
    return base_fixture


def choice_path(linked, symbol="MU"):
    return f"/cloud-mcp/practice/opportunities/{linked.opportunities[symbol].id}/choice"


def payload(decision="skip", **extra):
    return {"decision": decision, "rationale": "No clear setup in this simulated exercise", **extra}


def saved_choice(linked, symbol="MU"):
    response = linked.backend.get(choice_path(linked, symbol))
    assert response.status_code == 200, response.text
    envelope = response.json()
    assert envelope["schema_version"] == "d2-sample-choice-v1"
    assert envelope["sample_data"] is True
    assert envelope["time_zone"] == "America/New_York"
    assert envelope["ui_path"] == f"/daily/{linked.run.day.isoformat()}"
    assert envelope["status"] == "recorded"
    return envelope["choice"]


@pytest.mark.parametrize("decision,extra", [
    ("take", {}),
    ("wait", {"wait_condition": "Reassess after the simulated breakout",
              "wait_expiry": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()}),
    ("skip", {}),
])
def test_real_mcp_round_trip_records_sample_choices(linked, decision, extra):
    server = create_server(linked.config, backend_transport=httpx.ASGITransport(app=app))
    with TestClient(server.streamable_http_app()) as client:
        listed = _request(client, "tools/list", {}, linked.token)["result"]["tools"]
        tools = {tool["name"]: tool for tool in listed}
        assert {"record_practice_choice", "get_practice_choice"} <= tools.keys()
        assert tools["record_practice_choice"]["inputSchema"]["additionalProperties"] is False
        assert tools["record_practice_choice"]["annotations"]["readOnlyHint"] is False
        write_scopes = ["d0:profile", "practice:read", "practice:write"]
        assert tools["record_practice_choice"]["securitySchemes"] == [{"type": "oauth2", "scopes": write_scopes}]
        assert tools["record_practice_choice"]["_meta"]["securitySchemes"] == [{"type": "oauth2", "scopes": write_scopes}]
        read_tool = tools["get_practice_choice"]
        read_scopes = ["d0:profile", "practice:read"]
        assert read_tool["securitySchemes"] == [{"type": "oauth2", "scopes": read_scopes}]
        assert read_tool["_meta"]["securitySchemes"] == [{"type": "oauth2", "scopes": read_scopes}]
        if decision == "take":
            run_data = linked.backend.get(f"/cloud-mcp/practice/runs/{linked.run.id}").json()["run"]
            opportunity = next(item for item in run_data["opportunities"] if item["symbol"] == "MU")
            extra = {"plan": opportunity["context"]["packet"]["sample_plan"]}
        args = {"opportunity_id": str(linked.opportunities["MU"].id), **payload(decision, **extra)}
        result = _request(client, "tools/call", {"name": "record_practice_choice", "arguments": args}, linked.token)
        assert result["result"].get("isError") is not True, result
        assert result["result"]["structuredContent"]["created"] is True
        receipt = saved_choice(linked)
        assert receipt["decision"] == decision
        assert receipt["symbol"] == "MU"
        assert receipt["record_sha256"] and receipt["evidence_sha256"]
        read = _request(client, "tools/call", {"name": "get_practice_choice",
            "arguments": {"opportunity_id": str(linked.opportunities["MU"].id)}}, linked.token)
        assert read["result"].get("isError") is not True, read
        assert receipt["id"] in json.dumps(read)
    run_body = linked.backend.get(f"/cloud-mcp/practice/runs/{linked.run.id}").json()
    assert run_body["run"]["opportunities"][0]["choice"]["status"] == "practice_draft_unarmed"


def test_ui_mcp_sequential_concurrent_retry_and_changed_content_conflict(linked):
    path = choice_path(linked)
    original = payload()
    ui = choose(linked)
    assert ui.status_code == 201, ui.text
    expected = ui.json()["opportunities"][0]["choice"]
    assert linked.backend.post(path, json=original).status_code == 200
    with ThreadPoolExecutor(max_workers=8) as pool:
        statuses = list(pool.map(lambda _: linked.backend.post(path, json=original).status_code, range(8)))
    assert statuses and set(statuses) == {200}
    assert linked.backend.post(path, json=payload(rationale="Changed my mind")).status_code == 409
    own = saved_choice(linked)
    assert own["id"] == expected["id"] and own["record_sha256"] == expected["record_sha256"]
    with Session(linked.engine) as db:
        assert len(db.exec(select(DecisionRecord)).all()) == 1
    second_path = choice_path(linked, "NBIS")
    with ThreadPoolExecutor(max_workers=8) as pool:
        statuses = list(pool.map(lambda _: linked.backend.post(second_path, json=original).status_code, range(8)))
    assert statuses and set(statuses) == {201, 200}
    with Session(linked.engine) as db:
        assert len(db.exec(select(DecisionRecord)).all()) == 2


def test_lost_committed_mcp_response_recovers_by_own_receipt(linked):
    calls = 0
    async def transport(request):
        nonlocal calls
        calls += 1
        response = await httpx.ASGITransport(app=app).handle_async_request(request)
        if request.method == "POST" and calls == 1:
            await response.aread()
            raise httpx.ReadError("simulated response lost after backend commit", request=request)
        return response
    server = create_server(linked.config, backend_transport=httpx.MockTransport(transport))
    with TestClient(server.streamable_http_app()) as client:
        write = _request(client, "tools/call", {"name": "record_practice_choice", "arguments": {
            "opportunity_id": str(linked.opportunities["MU"].id), **payload()}}, linked.token)
        assert write["result"]["isError"] is True
        assert "receipt" in json.dumps(write).lower()
        recovered = _request(client, "tools/call", {"name": "get_practice_choice", "arguments": {
            "opportunity_id": str(linked.opportunities["MU"].id)}}, linked.token)
        assert recovered["result"].get("isError") is not True, recovered
        assert saved_choice(linked)["id"] in json.dumps(recovered)
    assert calls == 2


@pytest.mark.parametrize("change", [
    {"scope": "d0:profile practice:read"}, {"subject": "other"},
    {"audience": "https://other.test/mcp"}, {"client_id": "other"},
    {"issuer": "https://other.test/"}, {"now": 1}, {"lifetime": 301},
])
def test_invalid_or_read_only_token_cannot_write(linked, change):
    token = _token(linked.signer, **{"scope": "d0:profile practice:read practice:write", **change})
    response = linked.backend.post(choice_path(linked), headers={"authorization": "Bearer " + token}, json=payload())
    assert response.status_code == 401
    get_status = linked.backend.get(choice_path(linked), headers={"authorization": "Bearer " + token}).status_code
    assert get_status == (200 if "scope" in change else 401)


@pytest.mark.parametrize("header,value", [
    ("cookie", "tj_session=fake"), ("x-tj-service", "fake-owner"),
    ("x-tj-gateway", "fake-owner"), ("x-tj-bootstrap", "true"),
])
def test_mixed_credentials_cannot_write(linked, header, value):
    response = linked.backend.post(choice_path(linked), headers={header: value}, json=payload())
    assert response.status_code == 401


def test_current_grant_scope_and_feature_switches_fail_closed(linked):
    assert linked.backend.post(choice_path(linked), json=payload()).status_code == 201
    server = create_server(linked.config, backend_transport=httpx.ASGITransport(app=app))
    read_token = _token(linked.signer, scope="d0:profile practice:read")
    with Session(linked.engine) as db:
        row = db.get(AccessPrincipal, "writer")
        row.grants_json = json.dumps({**linked.grants, "decision_write": False})
        db.add(row)
        db.commit()
    assert linked.backend.post(choice_path(linked, "NBIS"), json=payload()).status_code == 403
    receipt = linked.backend.get(choice_path(linked), headers={"authorization": "Bearer " + read_token})
    assert receipt.status_code == 200 and receipt.json()["status"] == "recorded"
    with TestClient(server.streamable_http_app()) as client:
        mcp_read = _request(client, "tools/call", {"name": "get_practice_choice", "arguments": {
            "opportunity_id": str(linked.opportunities["MU"].id)}}, read_token)
        assert mcp_read["result"].get("isError") is not True
        assert receipt.json()["choice"]["id"] in json.dumps(mcp_read)
        with Session(linked.engine) as db:
            row = db.get(AccessPrincipal, "writer")
            row.grants_json = json.dumps(linked.grants)
            db.add(row)
            db.commit()
        for flag in ("TJ_CLOUD_MCP_DECISION_WRITES", "TJ_SAMPLE_DECISION_WRITES"):
            linked.patch.setenv(flag, "false")
            assert linked.backend.post(choice_path(linked, "NBIS"), json=payload()).status_code == 503
            linked.patch.setenv(flag, "true")
        config = json.loads(linked.config.read_text())
        config["decision_writes"] = False
        linked.config.write_text(json.dumps(config))
        assert linked.backend.post(choice_path(linked, "NBIS"), json=payload()).status_code == 503
        mcp_write = _request(client, "tools/call", {"name": "record_practice_choice", "arguments": {
            "opportunity_id": str(linked.opportunities["NBIS"].id), **payload()}}, linked.token)
        assert mcp_write["result"]["isError"] is True
        mcp_read = _request(client, "tools/call", {"name": "get_practice_choice", "arguments": {
            "opportunity_id": str(linked.opportunities["MU"].id)}}, read_token)
        assert mcp_read["result"].get("isError") is not True
        assert receipt.json()["choice"]["id"] in json.dumps(mcp_read)


@pytest.mark.parametrize("field,value", [
    ("enabled", False), ("version", 2),
    ("credential_expires_at", access.now() - timedelta(seconds=1)),
])
def test_current_principal_revocation_blocks_write_with_still_valid_token(linked, field, value):
    with Session(linked.engine) as db:
        principal = db.get(AccessPrincipal, "writer")
        setattr(principal, field, value)
        db.add(principal)
        db.commit()
    response = linked.backend.post(choice_path(linked), json=payload())
    assert response.status_code == 401
    assert linked.backend.get(choice_path(linked)).status_code == 401


@pytest.mark.parametrize("field", ["actor", "symbol", "context_id", "operation_id", "retry_key", "run_id"])
def test_server_owned_identity_and_retry_fields_are_rejected(linked, field):
    forged = payload(**{field: "forged"})
    response = linked.backend.post(choice_path(linked), json=forged)
    assert response.status_code == 422
    assert linked.backend.get("/decisions").status_code == 401


def test_unassigned_unknown_and_wrong_symbol_opportunities_are_hidden(linked):
    unknown = linked.backend.get(f"/cloud-mcp/practice/opportunities/{uuid.uuid4()}/choice")
    assert unknown.status_code == 404
    with Session(linked.engine) as db:
        principal = db.get(AccessPrincipal, "writer")
        principal.grants_json = json.dumps({**linked.grants, "symbols": ["MU"]})
        db.add(principal)
        db.commit()
    assert linked.backend.get(choice_path(linked, "NBIS")).status_code == 404
    assert linked.backend.post(choice_path(linked, "NBIS"), json=payload()).status_code == 404


def test_receipt_only_returns_linked_principals_own_choice(linked):
    opportunity = linked.opportunities["MU"]
    path = choice_path(linked)
    pending = linked.backend.get(path)
    assert pending.status_code == 200
    assert pending.json()["status"] == "not_recorded" and pending.json()["choice"] is None
    other_rows = []
    with Session(linked.engine) as db:
        for actor, rationale in (("human", "PRIVATE HUMAN CHOICE"),
                                 ("agent:other", "PRIVATE OTHER AGENT CHOICE")):
            row, _created = decisions.create(db, {"operation_id": f"seed:{actor}",
                "opportunity_id": f"a3:{opportunity.id}", "actor": actor, "decision": "skip",
                "symbol": opportunity.symbol, "context_id": str(opportunity.context_id),
                "rationale": rationale}, routine=True)
            other_rows.append(row)
        db.commit()
        protected = {row.id: row.model_dump(mode="json") for row in other_rows}
    pending = linked.backend.get(path)
    assert pending.status_code == 200 and pending.json()["status"] == "not_recorded"
    assert "PRIVATE HUMAN CHOICE" not in pending.text and "PRIVATE OTHER AGENT CHOICE" not in pending.text
    own = linked.backend.post(path, json=payload())
    assert own.status_code == 201, own.text
    own_id = own.json()["choice"]["id"]
    readback = linked.backend.get(path)
    assert readback.status_code == 200 and readback.json()["choice"]["id"] == own_id
    assert "PRIVATE HUMAN CHOICE" not in readback.text and "PRIVATE OTHER AGENT CHOICE" not in readback.text
    with Session(linked.engine) as db:
        assert {row.id: row.model_dump(mode="json") for row in db.exec(select(DecisionRecord)).all()
                if row.id in protected} == protected


def test_expired_new_write_and_existing_retry_receipt(linked):
    initial = linked.backend.post(choice_path(linked), json=payload())
    assert initial.status_code == 201
    with Session(linked.engine) as db:
        run = db.get(PracticeRun, linked.run.id)
        run.deadline = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=1)
        db.add(run)
        db.commit()
    assert linked.backend.post(choice_path(linked), json=payload()).status_code == 200
    assert linked.backend.get(choice_path(linked)).status_code == 200
    assert linked.backend.post(choice_path(linked, "NBIS"), json=payload()).status_code in (400, 422)


def test_oversized_selected_frozen_fact_refuses_without_mutating_context(linked):
    run_body = linked.backend.get(f"/cloud-mcp/practice/runs/{linked.run.id}").json()["run"]
    opportunity = next(item for item in run_body["opportunities"] if item["symbol"] == "MU")
    plan = opportunity["context"]["packet"]["sample_plan"]
    fact_name = plan["trigger_fact"]
    context_id = linked.opportunities["MU"].context_id
    with Session(linked.engine) as db:
        context = db.get(DecisionContext, context_id)
        evidence = json.loads(context.data_json)
        fact = next(item for item in evidence["price_facts"] if item["name"] == fact_name)
        fact["source_path"] = "x" * 5000
        context.data_json = json.dumps(evidence, separators=(",", ":"), sort_keys=True)
        db.add(context)
        db.commit()
        altered = context.data_json
    result = linked.backend.post(choice_path(linked), json=payload("take", plan=plan))
    assert result.status_code == 422, result.text
    with Session(linked.engine) as db:
        assert db.get(DecisionContext, context_id).data_json == altered
        assert db.exec(select(DecisionRecord)).all() == []


def test_choice_io_never_creates_jobs_events_fills_or_contexts(linked):
    with Session(linked.engine) as db:
        before = {model: [row.model_dump(mode="json") for row in db.exec(select(model)).all()]
                  for model in (PracticeRun, PracticeOpportunity, JobRun, DecisionContext, DecisionRecord, DecisionEvent, Fill)}
    assert linked.backend.get(choice_path(linked)).json()["status"] == "not_recorded"
    assert linked.backend.post(choice_path(linked), json=payload()).status_code == 201
    assert linked.backend.get(choice_path(linked)).json()["status"] == "recorded"
    with Session(linked.engine) as db:
        after = {model: [row.model_dump(mode="json") for row in db.exec(select(model)).all()]
                 for model in (PracticeRun, PracticeOpportunity, JobRun, DecisionContext, DecisionRecord, DecisionEvent, Fill)}
    for model in (PracticeRun, PracticeOpportunity, JobRun, DecisionContext, DecisionEvent, Fill):
        assert after[model] == before[model]
    assert len(after[DecisionRecord]) == len(before[DecisionRecord]) + 1


@pytest.mark.parametrize("d1linked", ["replay"], indirect=True)
def test_d2_choice_io_does_not_reveal_or_start_sample_replay(linked, d1linked):  # noqa: F811
    linked.opportunities = d1linked.opps
    linked.grants = d1linked.grants
    before_read = linked.backend.get(f"/cloud-mcp/practice/runs/{linked.run.id}")
    assert before_read.status_code == 200
    assert '"nonce"' not in before_read.text and '"continuation"' not in before_read.text
    assert all(item["replay"] is None for item in before_read.json()["run"]["opportunities"])
    with Session(linked.engine) as db:
        before_events = [row.model_dump(mode="json") for row in db.exec(select(DecisionEvent)).all()]
    saved = linked.backend.post(choice_path(linked), json=payload())
    assert saved.status_code == 201, saved.text
    receipt = linked.backend.get(choice_path(linked))
    assert receipt.status_code == 200 and receipt.json()["status"] == "recorded"
    readback = linked.backend.get(f"/cloud-mcp/practice/runs/{linked.run.id}")
    assert readback.status_code == 200
    assert '"nonce"' not in readback.text and '"continuation"' not in readback.text
    assert all(item["replay"] is None for item in readback.json()["run"]["opportunities"])
    with Session(linked.engine) as db:
        assert before_events == [row.model_dump(mode="json") for row in db.exec(select(DecisionEvent)).all()]
    opportunity_id = linked.opportunities["MU"].id
    for path in ("/practice/prepare", f"/practice/opportunities/{opportunity_id}/reveal",
                 f"/practice/opportunities/{opportunity_id}/sample-replay",
                 f"/decisions/{saved.json()['choice']['id']}/arm"):
        response = linked.backend.post(path, json={})
        assert response.status_code in (401, 403, 404), (path, response.status_code, response.text)


def test_sample_connector_refuses_assigned_historical_run_without_reveal_or_write(linked):
    from app.engine import historical_replay
    from scripts.historical_trial_fixture import bundle

    with Session(linked.engine) as db:
        run = historical_replay.prepare(db, bundle(), identifier="historical-connector-test", proof=True)
        opportunity_ids = [row.id for row in db.exec(select(PracticeOpportunity).where(PracticeOpportunity.run_id == run.id)).all()]
        principal = db.get(AccessPrincipal, "writer")
        principal.grants_json = json.dumps({**linked.grants, "run_ids": [str(run.id)]})
        db.add(principal)
        db.commit()
        before = {model: [row.model_dump(mode="json") for row in db.exec(select(model)).all()]
                  for model in (PracticeRun, DecisionContext, DecisionRecord, DecisionEvent)}
    for opportunity_id in opportunity_ids:
        path = f"/cloud-mcp/practice/opportunities/{opportunity_id}/choice"
        for response in (linked.backend.get(path), linked.backend.post(path, json=payload())):
            assert response.status_code == 404, response.text
            assert "nonce" not in response.text and "continuation" not in response.text
        response = linked.backend.post(f"/practice/opportunities/{opportunity_id}/historical-replay", json={})
        assert response.status_code in (401, 403, 404), response.text
    with Session(linked.engine) as db:
        after = {model: [row.model_dump(mode="json") for row in db.exec(select(model)).all()]
                 for model in before}
    assert after == before


def test_oversize_and_mcp_backend_failures_are_generic(linked):
    huge = payload(rationale="x" * MAX_CHOICE_BYTES)
    assert linked.backend.post(choice_path(linked), json=huge).status_code in (413, 422)
    def private_failure(request):
        return httpx.Response(500, text="PRIVATE DATABASE DETAIL")
    server = create_server(linked.config, backend_transport=httpx.MockTransport(private_failure))
    with TestClient(server.streamable_http_app()) as client:
        reply = _request(client, "tools/call", {"name": "get_practice_choice", "arguments": {
            "opportunity_id": str(linked.opportunities["MU"].id)}}, linked.token)
        assert reply["result"]["isError"] is True
        assert "PRIVATE DATABASE DETAIL" not in json.dumps(reply) and linked.token not in json.dumps(reply)
