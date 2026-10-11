"""Repeatable questions: generated-token/fixture proof, never actual Jo."""
import json
from pathlib import Path
import uuid
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient
import httpx
import pytest
from sqlmodel import Session

from app.engine import advisor_assignments as managed
from cloud_mcp_advisor import create_server
from cloud_mcp_advisor_bridge import build_app, MANAGE_PATH
from cloud_mcp_advisor_common import READ_PATH, WRITE_PATH, read_config
from tests.test_cloud_mcp_advisor import linked as linked, rpc
from tests.test_advisor_shadow import fixture as fixture
from tests.test_cloud_mcp_d0 import signing_key as signing_key

PEER = 71234


@pytest.fixture
def manager(linked):
    Path(linked.engine.url.database).chmod(0o600)
    config = json.loads(linked.config.read_text())
    config.update(assignment_management=True, owner_peer_uid=PEER)
    linked.config.write_text(json.dumps(config))
    app = build_app(linked.engine, linked.config)
    class Peer:
        async def __call__(self, scope, receive, send):
            scope["advisor_owner_peer_uid"] = PEER
            await app(scope, receive, send)
    with TestClient(Peer()) as owner, TestClient(app) as cloud:
        cloud.headers["authorization"] = "Bearer " + linked.token
        linked.manager, linked.cloud, linked.managed_app = owner, cloud, app
        yield linked


def create(manager, question="What is missing from this invented setup?"):
    body = {"operation_id": str(uuid.uuid4()), "question": question, "user_plan": "Wait for verified trigger and risk inputs.", "invented_only": True}
    response = manager.manager.post(MANAGE_PATH, json=body)
    assert response.status_code == 200, response.text
    return body, response.json()["record"]["request"]


def answer(manager, request):
    return {"packet_sha256": request["packet_sha256"], "request_sha256": request["request_sha256"], "answer": manager.answer["answer"]}


def test_two_questions_same_process_oauth_and_exact_owner_recovery(manager):
    config_before = manager.config.read_bytes()
    original = manager.owner.get(f"/advisor-shadow/runs/{manager.run_id}").json()["advisor"]
    body, first = create(manager)
    server = create_server(manager.config, backend_transport=httpx.ASGITransport(app=manager.managed_app))
    with TestClient(server.streamable_http_app()) as client:
        read = rpc(client, "get_advisor_request", {}, manager.token)["structuredContent"]
        assert read["request"] == first
        saved = rpc(client, "save_advisor_answer", answer(manager, first), manager.token)["structuredContent"]["receipt"]
        assert saved["submitted_output"]["assignment_id"] == first["assignment_id"]
        retry = manager.manager.post(MANAGE_PATH, json=body).json()
        assert len(retry["assignments"]) == 1 and retry["record"]["receipt"] == saved
        _, second = create(manager, "Which invented inputs are still missing?")
        assert second["assignment_id"] != first["assignment_id"]
        assert second["request_sha256"] != first["request_sha256"]
        assert rpc(client, "get_advisor_request", {}, manager.token)["structuredContent"]["request"] == second
        assert rpc(client, "save_advisor_answer", answer(manager, first), manager.token)["isError"] is True
        assert manager.manager.get(MANAGE_PATH, params={"assignment_id": first["assignment_id"]}).json()["record"]["receipt"] == saved
        assert manager.manager.post(MANAGE_PATH, json={"revoke": second["assignment_id"]}).json()["record"]["status"] == "revoked"
        assert rpc(client, "get_advisor_request", {}, manager.token)["isError"] is True
        assert rpc(client, "save_advisor_answer", answer(manager, second), manager.token)["isError"] is True
        assert manager.manager.post(MANAGE_PATH, json={"revoke": first["assignment_id"]}).json()["record"]["receipt"] == saved
    assert manager.config.read_bytes() == config_before
    assert manager.owner.get(f"/advisor-shadow/runs/{manager.run_id}").json()["advisor"] == original
    with Session(manager.engine) as db:
        record = managed.owner_view(db, read_config(manager.config).profiles[0], first["assignment_id"])
        assert record["record"]["request"] == first and record["record"]["receipt"] == saved
        assert record["record"]["status"] == "revoked"


def test_pending_idempotency_bad_body_and_owner_peer_denials(manager):
    body, request = create(manager)
    assert manager.manager.post(MANAGE_PATH, json=body).status_code == 200
    assert manager.manager.post(MANAGE_PATH, json={**body, "question": "changed"}).status_code == 409
    assert manager.manager.post(MANAGE_PATH, json={**body, "operation_id": str(uuid.uuid4())}).status_code == 409
    for extra in ({"invented_only": False}, {"question": ""}, {"subject": "jo"}):
        assert manager.manager.post(MANAGE_PATH, json={**body, **extra}).status_code == 409
    for method in ("get", "post"):
        assert getattr(manager.cloud, method)(MANAGE_PATH, headers={"x-owner-uid": str(PEER)}).status_code == 403
    for header in ("authorization", "cookie", "x-tj-gateway", "x-tj-service", "x-tj-bootstrap"):
        assert manager.manager.get(MANAGE_PATH, headers={header: "fake"}).status_code == 403
    assert manager.manager.get(MANAGE_PATH + "?subject=other").status_code == 400
    assert manager.manager.get(MANAGE_PATH + "?assignment_id=x&assignment_id=y").status_code == 400
    assert manager.cloud.get(READ_PATH).json()["request"] == request


def test_revocation_race_and_disabled_config_rollback(manager):
    _, request = create(manager)
    with ThreadPoolExecutor(2) as pool:
        save = pool.submit(manager.cloud.post, WRITE_PATH, json=answer(manager, request))
        revoke = pool.submit(manager.manager.post, MANAGE_PATH, json={"revoke": request["assignment_id"]})
        assert revoke.result().status_code == 200
        result = save.result()
        assert result.status_code in (200, 409)
    assert manager.cloud.get(READ_PATH).status_code == 403
    assert manager.cloud.post(WRITE_PATH, json=answer(manager, request)).status_code == 409
    recovered = manager.manager.get(MANAGE_PATH, params={"assignment_id": request["assignment_id"]}).json()["record"]
    assert recovered["status"] == "revoked"
    assert recovered["receipt"] == (result.json()["receipt"] if result.status_code == 200 else None)
    profile = read_config(manager.config).profiles[0]
    with Session(manager.engine) as db:
        before = managed.owner_view(db, profile)
        count = 0
        def revoke_authority():
            nonlocal count
            count += 1
            if count == 2:
                raise ValueError("Authority revoked before commit")
        with pytest.raises(ValueError):
            managed.mutate(db, profile, {"operation_id": str(uuid.uuid4()), "question": "Invented?", "user_plan": "Wait", "invented_only": True}, revoke_authority)
        assert managed.owner_view(db, profile) == before
    config = json.loads(manager.config.read_text())
    config["assignment_management"] = False
    manager.config.write_text(json.dumps(config))
    assert manager.manager.get(MANAGE_PATH).status_code == 403
    assert manager.cloud.get(READ_PATH).status_code == 401


def test_expiry_tampering_and_before_commit_save_revoke(manager, monkeypatch):
    from datetime import timedelta
    from app.engine import practice, decisions
    from app.models import PracticeAgentCall
    _, request = create(manager)
    profile = read_config(manager.config).profiles[0]
    now = practice.now_utc()
    monkeypatch.setattr(practice, "now_utc", lambda: now + timedelta(minutes=31))
    assert manager.cloud.get(READ_PATH).status_code == 403
    assert manager.cloud.post(WRITE_PATH, json=answer(manager, request)).status_code == 409
    assert manager.manager.get(MANAGE_PATH, params={"assignment_id": request["assignment_id"]}).json()["record"]["status"] == "expired"
    monkeypatch.setattr(practice, "now_utc", lambda: now)
    with Session(manager.engine) as db:
        checks = 0
        def disable():
            nonlocal checks
            checks += 1
            if checks == 2:
                raise ValueError("Disabled before commit")
        with pytest.raises(ValueError):
            managed.save(db, profile, answer(manager, request), disable)
        assert managed.owner_view(db, profile, request["assignment_id"])["record"]["receipt"] is None
        call = db.get(PracticeAgentCall, manager.call_id)
        config = json.loads(call.config_json)
        config[managed.KEY]["entries"][0]["request"]["question"] = "Changed behind immutable hash"
        call.config_json = json.dumps(config)
        db.add(call)
        db.commit()
        with pytest.raises(decisions.DecisionError):
            managed.owner_view(db, profile)
    assert manager.cloud.get(READ_PATH).status_code == 403


def test_adapter_refuses_owner_uid_and_management_limit(manager, monkeypatch):
    import os
    from app.models import PracticeAgentCall
    config = json.loads(manager.config.read_text())
    config["owner_peer_uid"] = os.geteuid()
    manager.config.write_text(json.dumps(config))
    with pytest.raises(ValueError, match="owner management UID"):
        create_server(manager.config)
    config["owner_peer_uid"] = PEER
    manager.config.write_text(json.dumps(config))
    _, request = create(manager)
    assert manager.manager.post(MANAGE_PATH, json={"revoke": request["assignment_id"]}).status_code == 200
    # Use the public engine limit with real writes; no synthetic historical IDs.
    monkeypatch.setattr(managed, "MAX_QUESTIONS", 2)
    _, second = create(manager)
    assert manager.manager.post(MANAGE_PATH, json={"revoke": second["assignment_id"]}).status_code == 200
    body = {"operation_id": str(uuid.uuid4()), "question": "Third?", "user_plan": "Wait", "invented_only": True}
    assert manager.manager.post(MANAGE_PATH, json=body).status_code == 409
    with Session(manager.engine) as db:
        call = db.get(PracticeAgentCall, manager.call_id)
        assert len(json.loads(call.config_json)[managed.KEY]["entries"]) == 2
