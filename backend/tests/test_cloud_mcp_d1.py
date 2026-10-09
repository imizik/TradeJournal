"""Real signed tokens and restricted sample projections, without issuer/model calls."""
from datetime import timedelta
import asyncio
import json
from types import SimpleNamespace
import time
import uuid

from fastapi.testclient import TestClient
import httpx
import pytest
from sqlmodel import Session, select

from app.engine import access, cloud_practice_access, decisions, practice, sample_replay
from app.main import app
from app.models import AccessPrincipal, DecisionRecord, DecisionContext, DecisionEvent, JobRun, PracticeRun
from cloud_mcp_d1 import create_server
import cloud_mcp_d1
from cloud_mcp_d1_common import MAX_RESPONSE_BYTES
from tests.test_browser_access import boundary as boundary
from tests.test_sample_practice import writer as writer, choose
from tests.test_sample_replay import replay as replay, saved, start
from tests.test_cloud_mcp_d0 import signing_key as signing_key, _token, _jwks, _write_config, _request, PROFILE_ID, ISSUER, JWKS_URL


@pytest.fixture
def linked(request, signing_key, tmp_path):
    replay_mode = getattr(request, "param", None) == "replay"
    writer = request.getfixturevalue("replay" if replay_mode else "writer")
    principal_id = "replay-writer" if replay_mode else "writer"
    config, keys = tmp_path / "d1.json", tmp_path / "keys.json"
    _write_config(config, sample_only=True, jwks_file=str(keys), backend_socket=str(tmp_path / "reads.sock"),
        profiles=[{"subject": "owner-subject", "id": PROFILE_ID, "enabled": True,
            "principal_id": principal_id, "principal_version": 1}])
    now = int(time.time())
    keys.write_text(json.dumps({"issuer_url": ISSUER, "jwks_url": JWKS_URL,
        "fetched_at": now, "expires_at": now + 3600, "keys": _jwks(signing_key.public_key())["keys"]}))
    writer.patch.setenv("TJ_CLOUD_MCP_ENABLED", "true")
    writer.patch.setenv("TJ_CLOUD_MCP_CONFIG", str(config))
    writer.patch.setattr(app.state, "cloud_mcp_sample_only", True, raising=False)
    cloud_practice_access.verifier.cache_clear()
    token = _token(signing_key, scope="d0:profile practice:read")
    client = TestClient(app)
    client.headers["authorization"] = "Bearer " + token
    result = SimpleNamespace(**vars(writer), config=config, keys=keys, token=token,
        signer=signing_key, backend=client)
    yield result
    client.close()
    cloud_practice_access.verifier.cache_clear()


def detail(linked):
    return linked.backend.get(f"/cloud-mcp/practice/runs/{linked.run.id}")


def test_assigned_sample_read_reuses_own_projection_and_preserves_records(linked):
    saved = choose(linked).json()["opportunities"][0]["choice"]
    with Session(linked.engine) as db:
        for actor in ("human", "agent:someone-else"):
            decisions.create(db, {"operation_id": actor, "opportunity_id": f"a3:{linked.opportunities['MU'].id}",
                "actor": actor, "decision": "skip", "symbol": "MU",
                "context_id": str(linked.opportunities["MU"].context_id), "rationale": "PRIVATE OTHER ACTOR"}, routine=True)
        before = {model.__name__: [row.model_dump(mode="json") for row in db.exec(select(model)).all()]
            for model in (PracticeRun, JobRun, DecisionContext, DecisionRecord, DecisionEvent)}
    def prohibited(*args, **kwargs):
        raise AssertionError("A read attempted preparation, generic recovery or replay start")
    linked.patch.setattr(practice, "view", prohibited)
    linked.patch.setattr(practice, "start", prohibited)
    linked.patch.setattr(sample_replay, "start", prohibited)
    listed = linked.backend.get("/cloud-mcp/practice/runs", params={"day": linked.run.day.isoformat()})
    assert listed.status_code == 200, listed.text
    assert [run["id"] for run in listed.json()["runs"]] == [str(linked.run.id)]
    response = detail(linked)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["sample_data"] is True and body["time_zone"] == "America/New_York"
    assert body["ui_path"] == "/daily/" + linked.run.day.isoformat()
    assert "PRIVATE OTHER ACTOR" not in response.text
    own = next(opp["choice"] for opp in body["run"]["opportunities"] if opp["symbol"] == "MU")
    assert own["id"] == saved["id"] and own["record_sha256"] == saved["record_sha256"]
    with Session(linked.engine) as db:
        after = {model.__name__: [row.model_dump(mode="json") for row in db.exec(select(model)).all()]
            for model in (PracticeRun, JobRun, DecisionContext, DecisionRecord, DecisionEvent)}
    assert after == before


@pytest.mark.parametrize("change", [{"scope": "d0:profile"}, {"subject": "other"}, {"audience": "https://other.test/mcp"},
    {"client_id": "other"}, {"issuer": "https://other.test/"}, {"now": 1}, {"lifetime": 301}])
def test_backend_independently_refuses_bad_token_or_scope(linked, change):
    token = _token(linked.signer, **{"scope": "d0:profile practice:read", **change})
    response = linked.backend.get(f"/cloud-mcp/practice/runs/{linked.run.id}", headers={"authorization": "Bearer " + token})
    assert response.status_code == 401 and str(linked.run.id) not in response.text


@pytest.mark.parametrize("change", [{"enabled": False}, {"version": 2}, {"credential_expires_at": access.now() - timedelta(seconds=1)}])
def test_current_principal_revocation_expires_still_valid_token(linked, change):
    assert detail(linked).status_code == 200
    with Session(linked.engine) as db:
        row = db.get(AccessPrincipal, "writer")
        for key, value in change.items():
            setattr(row, key, value)
        db.add(row)
        db.commit()
    assert detail(linked).status_code == 401


@pytest.mark.parametrize("name,arguments", [("get_practice_run", {"run_id": "https://owner.test/"}),
    ("get_practice_run", {"run_id": str(uuid.uuid4()), "actor": "human"}),
    ("list_practice_runs", {"day": "2026-02-30"}), ("list_practice_runs", {"day": "20261009"}),
    ("get_market_snapshot", {"symbol": "MU"}), ("get_profile", {"identity": "owner"})])
def test_invalid_tool_arguments_never_reach_backend(linked, name, arguments):
    def prohibited(request):
        raise AssertionError("Invalid tool reached backend")
    server = create_server(linked.config, backend_transport=httpx.MockTransport(prohibited))
    with TestClient(server.streamable_http_app()) as client:
        reply = _request(client, "tools/call", {"name": name, "arguments": arguments}, linked.token)
        assert reply.get("error") or reply["result"]["isError"] is True


@pytest.mark.parametrize("kind", ["size", "wrong-schema", "timeout"])
def test_backend_failure_limits_return_generic_unavailable(linked, kind):
    async def handler(request):
        if kind == "timeout":
            await asyncio.sleep(1)
        if kind == "size":
            return httpx.Response(200, content=b"x" * (MAX_RESPONSE_BYTES + 1))
        return httpx.Response(200, json={"sample_data": False, "private": "PRIVATE BODY"})
    linked.patch.setattr(cloud_mcp_d1, "BACKEND_DEADLINE", .01)
    server = create_server(linked.config, backend_transport=httpx.MockTransport(handler))
    with TestClient(server.streamable_http_app()) as client:
        reply = _request(client, "tools/call", {"name": "get_practice_run", "arguments": {"run_id": str(linked.run.id)}}, linked.token)
        assert reply["result"]["isError"] is True and "PRIVATE BODY" not in json.dumps(reply)


def test_grants_filter_symbols_and_unassigned_runs(linked):
    with Session(linked.engine) as db:
        row = db.get(AccessPrincipal, "writer")
        row.grants_json = json.dumps({**linked.grants, "symbols": ["MU"]})
        db.add(row)
        db.commit()
    body = detail(linked).json()
    assert [opp["symbol"] for opp in body["run"]["opportunities"]] == ["MU"]
    assert linked.backend.get(f"/cloud-mcp/practice/runs/{uuid.uuid4()}").status_code == 404
    assert linked.backend.get("/cloud-mcp/practice/runs", params={"day": "2001-01-01"}).json()["runs"] == []


@pytest.mark.parametrize("flag", ["TJ_ACCESS_ENABLED", "TJ_ACCESS_SAMPLE_DATA", "TJ_DOT_TRIAL_ENABLED", "TJ_CLOUD_MCP_ENABLED"])
def test_disabled_or_non_sample_backend_refuses_even_valid_bearer(linked, flag):
    linked.patch.setenv(flag, "false")
    assert detail(linked).status_code == 503


def test_flags_alone_cannot_enable_normal_backend(linked):
    linked.patch.setattr(app.state, "cloud_mcp_sample_only", False)
    assert detail(linked).status_code == 503


@pytest.mark.parametrize("header,value", [("x-tj-service", "fake-owner"), ("x-tj-gateway", "fake-owner"),
    ("cookie", "tj_session=fake"), ("x-tj-bootstrap", "true")])
def test_no_mixed_browser_service_identity_fallback(linked, header, value):
    assert linked.backend.get(f"/cloud-mcp/practice/runs/{linked.run.id}", headers={header: value}).status_code == 401


def test_bearer_grants_no_other_routes_or_writes(linked):
    for path in ("/trades", "/accounts", "/access/me", "/practice/runs", "/decisions", "/stats"):
        assert linked.backend.get(path).status_code == 401
    for path in ("/practice/prepare", f"/practice/opportunities/{linked.opportunities['MU'].id}/agent-choice",
            f"/practice/opportunities/{linked.opportunities['MU'].id}/sample-replay", "/cloud-mcp/practice/runs"):
        assert linked.backend.post(path, json={}).status_code in (401, 404)


def test_offline_key_expiry_and_local_link_disable_take_effect(linked):
    assert detail(linked).status_code == 200
    body = json.loads(linked.keys.read_text())
    body["expires_at"] = int(time.time()) - 1
    linked.keys.write_text(json.dumps(body))
    assert detail(linked).status_code == 401
    body["expires_at"] = int(time.time()) + 1800
    linked.keys.write_text(json.dumps(body))
    assert detail(linked).status_code == 200
    config = json.loads(linked.config.read_text())
    config["profiles"][0]["enabled"] = False
    linked.config.write_text(json.dumps(config))
    assert detail(linked).status_code == 401


def test_mcp_end_to_end_catalog_and_authenticated_backend_read(linked):
    server = create_server(linked.config, backend_transport=httpx.ASGITransport(app=app))
    with TestClient(server.streamable_http_app()) as client:
        assert set(client.get("/.well-known/oauth-protected-resource/mcp").json()["scopes_supported"]) == {"d0:profile", "practice:read"}
        tools = _request(client, "tools/list", {}, linked.token)["result"]["tools"]
        assert {tool["name"] for tool in tools} == {"get_profile", "list_practice_runs", "get_practice_run"}
        for tool in tools:
            assert tool["inputSchema"]["additionalProperties"] is False
            assert tool["annotations"]["readOnlyHint"] is True
            scopes = ["d0:profile"] if tool["name"] == "get_profile" else ["d0:profile", "practice:read"]
            assert tool["securitySchemes"] == [{"type": "oauth2", "scopes": scopes}]
        for name, arguments in (("list_practice_runs", {"day": linked.run.day.isoformat()}),
                ("get_practice_run", {"run_id": str(linked.run.id)})):
            reply = _request(client, "tools/call", {"name": name, "arguments": arguments}, linked.token)
            assert reply["result"].get("isError") is not True, reply
            assert str(linked.run.id) in json.dumps(reply)
        profile_only = _token(linked.signer)
        reply = _request(client, "tools/call", {"name": "get_practice_run", "arguments": {"run_id": str(linked.run.id)}}, profile_only)
        assert reply["result"]["isError"] is True and str(linked.run.id) not in json.dumps(reply)
        assert PROFILE_ID in json.dumps(_request(client, "tools/call", {"name": "get_profile", "arguments": {}}, profile_only))


def test_mcp_never_exposes_backend_error_or_uses_redirect_fallback(linked):
    seen = []
    def failing(request):
        seen.append(request)
        assert request.headers["authorization"] == "Bearer " + linked.token
        assert "cookie" not in request.headers and "x-tj-service" not in request.headers
        return httpx.Response(302, headers={"location": "https://unapproved.test/"}, text="PRIVATE BACKEND ERROR")
    server = create_server(linked.config, backend_transport=httpx.MockTransport(failing))
    with TestClient(server.streamable_http_app()) as client:
        reply = _request(client, "tools/call", {"name": "get_practice_run", "arguments": {"run_id": str(linked.run.id)}}, linked.token)
        assert reply["result"]["isError"] is True
        assert "PRIVATE BACKEND ERROR" not in json.dumps(reply) and linked.token not in json.dumps(reply)
    assert len(seen) == 1 and seen[0].url.path.startswith("/cloud-mcp/practice/runs/")


@pytest.mark.parametrize("linked", ["replay"], indirect=True)
def test_replay_reads_preserve_unrevealed_and_committed_results(linked):
    record = saved(linked)
    second = saved(linked, symbol="NBIS")
    before = detail(linked)
    assert before.status_code == 200
    assert '"nonce"' not in before.text and '"continuation"' not in before.text
    assert all(opp["replay"] is None for opp in before.json()["run"]["opportunities"])
    started = start(linked)
    assert started.status_code == 201, started.text
    ui_result = next(opp["replay"] for opp in started.json()["opportunities"] if opp["symbol"] == "MU")
    second_started = start(linked, selected="NBIS")
    assert second_started.status_code == 201, second_started.text
    second_result = next(opp["replay"] for opp in second_started.json()["opportunities"] if opp["symbol"] == "NBIS")
    with Session(linked.engine) as db:
        events = [row.model_dump(mode="json") for row in db.exec(select(DecisionEvent)).all()]
    def prohibited(*args, **kwargs):
        raise AssertionError("Read tried to start/recompute replay")
    linked.patch.setattr(sample_replay, "start", prohibited)
    response = detail(linked)
    assert response.status_code == 200, response.text
    own = next(opp for opp in response.json()["run"]["opportunities"] if opp["symbol"] == "MU")
    assert own["choice"]["id"] == record["id"] and own["replay"] == ui_result
    nbis = next(opp for opp in response.json()["run"]["opportunities"] if opp["symbol"] == "NBIS")
    assert nbis["choice"]["id"] == second["id"] and nbis["replay"] == second_result
    with Session(linked.engine) as db:
        assert events == [row.model_dump(mode="json") for row in db.exec(select(DecisionEvent)).all()]


@pytest.mark.parametrize("extra", [{"journal_read": True}, {"run_ids": []}, {"run_ids": "bad"},
    {"symbols": ["SPY"]}, {"symbols": []}, {"run_ids": [str(uuid.uuid4()), str(uuid.uuid4())]}])
def test_unsafe_current_grants_refuse(linked, extra):
    with Session(linked.engine) as db:
        row = db.get(AccessPrincipal, "writer")
        row.grants_json = json.dumps({**linked.grants, **extra})
        db.add(row)
        db.commit()
    assert detail(linked).status_code == 403


def test_ordinary_browser_and_oauth_share_persisted_budget(linked):
    from app.models import AccessLoginLimit
    with Session(linked.engine) as db:
        now = access.now()
        bucket_id = access.digest("requests:writer")
        row = db.get(AccessLoginLimit, bucket_id)
        if row is None:
            row = AccessLoginLimit(id=bucket_id, window_at=now, attempts=240)
        else:
            row.window_at, row.attempts = now, 240
        db.add(row)
        db.commit()
    assert detail(linked).status_code == 429
    assert linked.public.get(f"/practice/runs/{linked.run.id}").status_code == 429


def test_unprepared_run_and_binding_change_refuse_without_fallback(linked):
    with Session(linked.engine) as db:
        row = db.get(PracticeRun, linked.run.id)
        row.status = "preparing"
        db.add(row)
        db.commit()
    assert detail(linked).status_code == 404
    assert linked.backend.get("/cloud-mcp/practice/runs", params={"day": linked.run.day.isoformat()}).json()["runs"] == []
    config = json.loads(linked.config.read_text())
    config["profiles"][0]["principal_id"] = "someone-else"
    linked.config.write_text(json.dumps(config))
    assert detail(linked).status_code == 401
