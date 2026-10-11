"""Offline invented-fixture advisor acceptance; no actual Jo/OAuth exposure."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import time
from types import SimpleNamespace
import uuid

from fastapi.testclient import TestClient
import httpx
import pytest
from sqlmodel import Session, select

from app.engine import advisor_shadow as service, decisions, practice
from app.models import DecisionEvent, DecisionRecord, PracticeAgentCall, PracticeRun
from cloud_mcp_advisor import create_server
from cloud_mcp_advisor_bridge import build_app, create_app
from cloud_mcp_advisor_common import AdvisorVerifier, READ_PATH, WRITE_PATH, read_config
from tests.test_advisor_shadow import fixture as fixture, handoff
from tests.test_cloud_mcp_d0 import signing_key as signing_key, _token, _jwks, ISSUER, JWKS_URL

RESOURCE = "https://advisor.example.test/advisor/mcp"
SCOPES = "advisor:profile advisor:read advisor:write"


@pytest.fixture
def linked(fixture, signing_key, tmp_path, monkeypatch):
    engine, run_id, call_id, _, shadow, owner = fixture
    exported, envelope = handoff(owner, run_id)
    keys = tmp_path / "public-keys.json"
    keys.write_text(json.dumps({"issuer_url": ISSUER, "jwks_url": JWKS_URL,
        "fetched_at": int(time.time()) - 1, "expires_at": int(time.time()) + 600,
        **_jwks(signing_key.public_key())}))
    path = tmp_path / "advisor.json"
    config = {"enabled": True, "advisor_only": True, "issuer_url": ISSUER, "resource_url": RESOURCE,
        "jwks_url": JWKS_URL, "jwks_file": str(keys), "client_id": "advisor-client",
        "backend_socket": str(tmp_path / "advisor.sock"), "profiles": [{
            "subject": "jo-advisor", "id": "advisor_" + str(uuid.uuid4()), "enabled": True,
            "binding_version": 1, **{key: exported[key] for key in ("assignment_id", "run_id", "packet_sha256", "request_sha256")}}]}
    path.write_text(json.dumps(config))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("MIGRATION_DATABASE_URL", raising=False)
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    token = _token(signing_key, audience=RESOURCE, subject="jo-advisor", client_id="advisor-client", scope=SCOPES)
    app = build_app(engine, path)
    with TestClient(app) as backend:
        backend.headers["authorization"] = "Bearer " + token
        yield SimpleNamespace(engine=engine, run_id=run_id, call_id=call_id, shadow=shadow, owner=owner,
            export=exported, envelope=envelope, answer={k: envelope[k] for k in ("packet_sha256", "request_sha256", "answer")},
            config=path, keys=keys, token=token, signer=signing_key, app=app, backend=backend)


def rpc(client, name, arguments, token):
    response = client.post(RESOURCE, headers={"Accept": "application/json", "Authorization": "Bearer " + token},
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": arguments}})
    assert response.status_code == 200, response.text
    return response.json()["result"]


def owner_receipt(linked):
    return linked.owner.get(f"/advisor-shadow/runs/{linked.run_id}").json()["advisor"]["receipt"]


def test_catalog_frozen_request_cited_save_owner_reload_and_legacy_origin(linked):
    before_shadow = linked.shadow.get("/receipt").json()
    server = create_server(linked.config, backend_transport=httpx.ASGITransport(app=linked.app))
    with TestClient(server.streamable_http_app()) as client:
        metadata = client.get("/.well-known/oauth-protected-resource/advisor/mcp").json()
        assert metadata["resource"] == RESOURCE
        assert metadata["scopes_supported"] == SCOPES.split()
        listing = client.post(RESOURCE, headers={"Authorization": "Bearer " + linked.token, "Accept": "application/json"},
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}).json()
        tools = {item["name"]: item for item in listing["result"]["tools"]}
        assert set(tools) == {"get_profile", "get_advisor_request", "save_advisor_answer"}
        for name, tool in tools.items():
            assert tool["inputSchema"]["additionalProperties"] is False
            assert tool["securitySchemes"] == tool["_meta"]["securitySchemes"]
            assert tool["annotations"]["readOnlyHint"] == (name != "save_advisor_answer")
        assert set(tools["get_advisor_request"]["inputSchema"]["properties"]) == set()
        assert set(tools["save_advisor_answer"]["inputSchema"]["properties"]) == {"packet_sha256", "request_sha256", "answer"}
        assert rpc(client, "get_profile", {}, linked.token)["structuredContent"]["id"].startswith("advisor_")
        read = rpc(client, "get_advisor_request", {}, linked.token)["structuredContent"]
        assert read["request"] == linked.export and read["receipt"] is None
        assert read["delivery_transport"] == "oauth-mcp" and read["request_origin_transport"] == "manual-paste"
        saved = rpc(client, "save_advisor_answer", linked.answer, linked.token)["structuredContent"]["receipt"]
        assert saved == owner_receipt(linked)
        assert saved["submitted_output"] == linked.envelope and saved["transport"] == "oauth-mcp"
        assert saved["receipt_sha256"] == service.digest({k: v for k, v in saved.items() if k != "receipt_sha256"})
        assert rpc(client, "save_advisor_answer", linked.answer, linked.token)["structuredContent"]["receipt"] == saved
        assert rpc(client, "get_advisor_request", {}, linked.token)["structuredContent"]["receipt"] == saved
    # Reopen a new backend against the same persisted ledger: no in-memory receipt.
    with TestClient(build_app(linked.engine, linked.config)) as restarted:
        reopened = restarted.get(READ_PATH, headers={"Authorization": "Bearer " + linked.token}).json()
        assert reopened["receipt"] == saved and reopened["request"] == linked.export
    assert linked.shadow.get("/receipt").json() == before_shadow
    assert linked.owner.get(f"/advisor-shadow/runs/{linked.run_id}").json()["advisor"]["export"] == linked.export
    with Session(linked.engine) as db:
        assert db.exec(select(DecisionRecord)).all() == [] and db.exec(select(DecisionEvent)).all() == []
        assert db.get(PracticeRun, linked.run_id).comparison == "assisted"


@pytest.mark.parametrize("name,arguments", [
    ("get_advisor_request", {"run_id": str(uuid.uuid4())}), ("get_profile", {"subject": "owner"}),
    ("list_practice_runs", {}), ("get_journal_summary", {}), ("get_shadow_choices", {}),
    ("save_advisor_answer", {"assignment_id": str(uuid.uuid4())}),
])
def test_catalog_refuses_selectors_and_other_domains(linked, name, arguments):
    server = create_server(linked.config, backend_transport=httpx.ASGITransport(app=linked.app))
    with TestClient(server.streamable_http_app()) as client:
        assert rpc(client, name, arguments, linked.token)["isError"] is True
    assert owner_receipt(linked) is None


@pytest.mark.parametrize("change", [
    {"subject": "owner-subject"}, {"subject": "jo-journal"}, {"audience": "https://journal.example.test/mcp"},
    {"client_id": "journal-client"}, {"scope": "d0:profile journal:read practice:write"},
    {"scope": "advisor:profile"}, {"issuer": "https://other.test/"}, {"now": 1}, {"lifetime": 301},
])
def test_direct_bridge_independent_auth_refuses_wrong_identity_scope_or_expiry(linked, change):
    token = _token(linked.signer, **{"audience": RESOURCE, "subject": "jo-advisor", "client_id": "advisor-client", "scope": SCOPES, **change})
    headers = {"Authorization": "Bearer " + token}
    assert linked.backend.get(READ_PATH, headers=headers).status_code == 401
    assert linked.backend.post(WRITE_PATH, headers=headers, json=linked.answer).status_code == 401
    assert owner_receipt(linked) is None


def test_read_token_saves_denied_but_receipt_read_allowed(linked):
    token = _token(linked.signer, audience=RESOURCE, subject="jo-advisor", client_id="advisor-client", scope="advisor:profile advisor:read")
    assert linked.backend.post(WRITE_PATH, json=linked.answer).status_code == 200
    assert linked.backend.get(READ_PATH, headers={"Authorization": "Bearer " + token}).json()["receipt"] == owner_receipt(linked)
    assert linked.backend.post(WRITE_PATH, headers={"Authorization": "Bearer " + token}, json=linked.answer).status_code == 401


@pytest.mark.parametrize("header", ["cookie", "x-tj-service", "x-tj-gateway", "x-tj-bootstrap"])
def test_owner_browser_or_gateway_credentials_never_substitute(linked, header):
    assert linked.backend.get(READ_PATH, headers={header: "fake"}).status_code == 401
    assert linked.backend.post(WRITE_PATH, headers={header: "fake"}, json=linked.answer).status_code == 401
    linked.backend.headers.pop("authorization")
    assert linked.backend.get(READ_PATH, headers={header: "fake"}).status_code == 401


@pytest.mark.parametrize("path", ["/health", "/packet", "/choices", "/receipt", "/docs", "/openapi.json",
    "/advisor-shadow/runs/x", "/cloud-mcp/practice/runs", "/journal", "/decisions/x/arm"])
def test_direct_routes_no_other_domain_or_wildcard(linked, path):
    assert linked.backend.get(path).status_code == 404
    assert linked.backend.post(path, json=linked.answer).status_code == 404
    assert linked.backend.get(READ_PATH + "?assignment_id=x").status_code == 401


@pytest.mark.parametrize("change", ["packet_sha256", "request_sha256", "assignment_id", "run_id", "version", "citation_id", "citation_name", "empty", "hidden"])
def test_bad_identity_citations_and_hidden_fields_never_save(linked, change):
    body = json.loads(json.dumps(linked.answer))
    if change in {"packet_sha256", "request_sha256"}:
        body[change] = "f" * 64
    elif change == "citation_id":
        body["answer"]["references"][0]["opportunity_id"] = str(uuid.uuid4())
    elif change == "citation_name":
        body["answer"]["references"][0]["fact_name"] = "fake"
    elif change == "empty":
        body["answer"]["references"] = []
    elif change == "hidden":
        body["answer"]["shadow_choices"] = []
    else:
        body[change] = "forged"
    assert linked.backend.post(WRITE_PATH, json=body).status_code in {409, 422}
    assert owner_receipt(linked) is None


def test_concurrent_exact_retries_conflicts_and_manual_retry_preserve_transport(linked):
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: linked.backend.post(WRITE_PATH, json=linked.answer), range(4)))
    assert {response.status_code for response in results} == {200}
    saved = owner_receipt(linked)
    assert all(response.json()["receipt"] == saved for response in results)
    changed = {**linked.answer, "answer": {**linked.answer["answer"], "summary": "different"}}
    assert linked.backend.post(WRITE_PATH, json=changed).status_code == 409
    assert linked.owner.post(f"/advisor-shadow/runs/{linked.run_id}/advisor-import", json=linked.envelope).json()["advisor"]["receipt"] == saved
    assert saved["transport"] == "oauth-mcp"


def test_existing_manual_receipt_never_rewritten_by_mcp_retry(linked):
    saved = linked.owner.post(f"/advisor-shadow/runs/{linked.run_id}/advisor-import", json=linked.envelope).json()["advisor"]["receipt"]
    assert saved["transport"] == "manual-paste"
    assert linked.backend.post(WRITE_PATH, json=linked.answer).json()["receipt"] == saved
    assert linked.backend.get(READ_PATH).json()["receipt"] == saved == owner_receipt(linked)


@pytest.mark.parametrize("change", ["config_enabled", "profile_enabled", "binding_version", "assignment_id", "request_sha256", "keys", "assignment_revoked", "assignment_expired"])
def test_read_and_retry_revocation_expiry_and_binding_changes_fail_closed_owner_recovers(linked, monkeypatch, change):
    assert linked.backend.post(WRITE_PATH, json=linked.answer).status_code == 200
    saved = owner_receipt(linked)
    if change == "assignment_revoked":
        with Session(linked.engine) as db:
            service.set_enabled(db, linked.call_id, False)
    elif change == "assignment_expired":
        monkeypatch.setattr(practice, "now_utc", lambda: decisions._utc(linked.export["expires_at"], "expiry").replace(tzinfo=None))
    elif change == "keys":
        data = json.loads(linked.keys.read_text())
        data["expires_at"] = int(time.time()) - 1
        linked.keys.write_text(json.dumps(data))
    else:
        data = json.loads(linked.config.read_text())
        if change == "config_enabled":
            data["enabled"] = False
        elif change == "profile_enabled":
            data["profiles"][0]["enabled"] = False
        elif change == "binding_version":
            data["profiles"][0][change] = 2
        else:
            data["profiles"][0][change] = str(uuid.uuid4()) if change.endswith("_id") else "f" * 64
        linked.config.write_text(json.dumps(data))
    assert linked.backend.get(READ_PATH).status_code in {401, 403}
    assert linked.backend.post(WRITE_PATH, json=linked.answer).status_code in {401, 409}
    assert owner_receipt(linked) == saved


def test_lost_committed_response_recovered_without_automatic_retry(linked):
    calls = []
    async def transport(request):
        calls.append(request.method)
        response = await httpx.ASGITransport(app=linked.app).handle_async_request(request)
        if request.method == "POST":
            await response.aread()
            raise httpx.ReadError("Fixture lost committed response", request=request)
        return response
    server = create_server(linked.config, backend_transport=httpx.MockTransport(transport))
    with TestClient(server.streamable_http_app()) as client:
        result = rpc(client, "save_advisor_answer", linked.answer, linked.token)
        assert result["isError"] is True and "get_advisor_request" in json.dumps(result)
        receipt = rpc(client, "get_advisor_request", {}, linked.token)["structuredContent"]["receipt"]
        assert receipt == owner_receipt(linked) and receipt["submitted_output"] == linked.envelope
    assert calls == ["POST", "GET"]


def test_ambient_credentials_and_nonprivate_or_wrong_database_startup_refused(linked, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-never-used")
    with pytest.raises(ValueError, match="credentials"):
        create_server(linked.config)
    monkeypatch.delenv("OPENAI_API_KEY")
    monkeypatch.setenv("DATABASE_URL", "fixture-never-connected")
    with pytest.raises(ValueError, match="credentials"):
        create_app(linked.config, "/private/tmp/not-a-real-db.db")
    monkeypatch.delenv("DATABASE_URL")
    with pytest.raises(ValueError, match="private isolated"):
        create_app(linked.config, "/private/tmp/not-a-real-db.db")


@pytest.mark.parametrize("key,value", [("advisor_only", False), ("resource_url", "https://advisor.example.test/mcp"),
    ("backend_socket", "../socket"), ("jwks_file", "/tmp/../keys"), ("database", "forbidden"),
    ("profiles", []), ("profiles", [{"id": "owner"}])])
def test_strict_separate_configuration_refuses_broad_or_legacy_bindings(linked, key, value):
    config = json.loads(linked.config.read_text())
    config[key] = value
    linked.config.write_text(json.dumps(config))
    with pytest.raises(ValueError):
        read_config(linked.config)


def test_adapter_same_bearer_fixed_path_no_proxy_redirect_retry_or_fallback(linked):
    seen = []
    def transport(request):
        seen.append(request)
        return httpx.Response(302, headers={"location": "https://private-owner.test/"})
    server = create_server(linked.config, backend_transport=httpx.MockTransport(transport))
    with TestClient(server.streamable_http_app()) as client:
        assert rpc(client, "get_advisor_request", {}, linked.token)["isError"] is True
    assert len(seen) == 1 and str(seen[0].url) == "http://advisor-backend" + READ_PATH
    assert seen[0].headers["authorization"] == "Bearer " + linked.token


def test_backend_expiry_immediately_before_commit_rolls_back(linked, monkeypatch):
    original = service.active_assignment
    count = 0
    def expire(config):
        nonlocal count
        count += 1
        if count >= 4:
            monkeypatch.setattr(practice, "now_utc", lambda: decisions._utc(config["expires_at"], "expiry").replace(tzinfo=None))
        return original(config)
    monkeypatch.setattr(service, "active_assignment", expire)
    assert linked.backend.post(WRITE_PATH, json=linked.answer).status_code == 409
    assert owner_receipt(linked) is None


def test_config_revocation_before_commit_rolls_back(linked, monkeypatch):
    original = AdvisorVerifier.verify_token
    count = 0
    async def revoke(self, token):
        nonlocal count
        count += 1
        if count == 3:
            config = json.loads(linked.config.read_text())
            config["enabled"] = False
            linked.config.write_text(json.dumps(config))
        return await original(self, token)
    monkeypatch.setattr(AdvisorVerifier, "verify_token", revoke)
    assert linked.backend.post(WRITE_PATH, json=linked.answer).status_code == 401
    assert owner_receipt(linked) is None


def test_oversize_request_and_response_fail_without_truncation(linked):
    assert linked.backend.post(WRITE_PATH, content=b"x" * 65537).status_code == 413
    server = create_server(linked.config, backend_transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b"x" * 65537)))
    with TestClient(server.streamable_http_app()) as client:
        assert rpc(client, "get_advisor_request", {}, linked.token)["isError"] is True
    assert owner_receipt(linked) is None


@pytest.mark.parametrize("target", ["request", "receipt", "packet"])
def test_stored_frozen_request_receipt_or_packet_tampering_refuses(linked, target):
    assert linked.backend.post(WRITE_PATH, json=linked.answer).status_code == 200
    with Session(linked.engine) as db:
        call = db.get(PracticeAgentCall, linked.call_id)
        config = json.loads(call.config_json)
        if target == "request":
            config["advisor"]["export"]["question"] = "Changed frozen question"
        elif target == "receipt":
            config["advisor"]["receipt"]["submitted_output"]["answer"]["summary"] = "Changed saved answer"
        else:
            packet = json.loads(call.payload_json)
            packet["missing"].append("forged")
            call.payload_json = service.canonical(packet)
        call.config_json = service.canonical(config)
        db.add(call)
        db.commit()
    assert linked.backend.get(READ_PATH).status_code == 403
    assert linked.backend.post(WRITE_PATH, json=linked.answer).status_code == 409


def test_real_unix_bridge_process_replacement_receipt_equality(linked):
    """Only disposable local Unix IPC, no service activation or TCP listener."""
    import os
    from pathlib import Path
    import subprocess
    import sys
    import tempfile

    backend = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="tj-advisor-unix-", dir="/tmp") as temporary:
        socket_path = str(Path(temporary) / "bridge.sock")
        data = json.loads(linked.config.read_text())
        data["backend_socket"] = socket_path
        linked.config.write_text(json.dumps(data))
        clean = {"PATH": os.environ.get("PATH", ""), "PYTHON_DOTENV_DISABLED": "1"}
        source = """
import sys
from sqlmodel import create_engine
from cloud_mcp_advisor_bridge import build_app
import uvicorn
engine=create_engine(sys.argv[1],connect_args={"check_same_thread":False,"timeout":2})
uvicorn.run(build_app(engine,sys.argv[2]),uds=sys.argv[3],access_log=False,log_level="warning",ws="none")
"""
        receipt = None
        for cycle in range(2):
            process = subprocess.Popen([sys.executable, "-c", source, str(linked.engine.url), str(linked.config), socket_path],
                cwd=backend, env=clean, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                async def exercise():
                    nonlocal receipt
                    transport = httpx.AsyncHTTPTransport(uds=socket_path, retries=0)
                    async with httpx.AsyncClient(transport=transport, trust_env=False, timeout=2,
                            headers={"Authorization": "Bearer " + linked.token}) as client:
                        started = time.monotonic()
                        while True:
                            try:
                                response = await client.get("http://advisor-backend" + READ_PATH)
                                break
                            except httpx.ConnectError:
                                if process.poll() is not None or time.monotonic() - started > 10:
                                    raise AssertionError("Disposable Unix backend failed to start: " + process.communicate(timeout=5)[1].decode())
                                await asyncio.sleep(0.02)
                        assert response.status_code == 200, response.text
                        assert response.json()["request"] == linked.export
                        # Exercise the adapter's default real Unix transport,
                        # not the ASGI injection used by other offline fixtures.
                        server = create_server(linked.config)
                        with TestClient(server.streamable_http_app()) as mcp:
                            if cycle == 0:
                                saved = rpc(mcp, "save_advisor_answer", linked.answer, linked.token)
                                assert saved.get("isError") is not True, saved
                                receipt = saved["structuredContent"]["receipt"]
                            else:
                                recovered = rpc(mcp, "get_advisor_request", {}, linked.token)
                                assert recovered.get("isError") is not True, recovered
                                assert recovered["structuredContent"]["receipt"] == receipt
                                assert response.json()["receipt"] == receipt
                        assert (await client.get("http://advisor-backend/health")).status_code == 404
                        denied = await client.get("http://advisor-backend" + READ_PATH, headers={"Authorization": "Bearer invalid"})
                        assert denied.status_code == 401
                asyncio.run(exercise())
            finally:
                process.terminate()
                process.communicate(timeout=5)
                Path(socket_path).unlink(missing_ok=True)
        assert receipt == owner_receipt(linked)


@pytest.mark.parametrize("revoke", ["config", "assignment"])
def test_revocation_during_body_reception_prevents_save(linked, revoke):
    class SlowBody(httpx.AsyncByteStream):
        async def __aiter__(self):
            encoded = json.dumps(linked.answer).encode()
            yield encoded[:20]
            if revoke == "config":
                config = json.loads(linked.config.read_text())
                config["profiles"][0]["enabled"] = False
                linked.config.write_text(json.dumps(config))
            else:
                with Session(linked.engine) as db:
                    service.set_enabled(db, linked.call_id, False)
            yield encoded[20:]
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=linked.app), base_url="http://advisor-backend") as client:
            return await client.post(WRITE_PATH, headers={"Authorization": "Bearer " + linked.token}, content=SlowBody())
    assert asyncio.run(run()).status_code in {401, 409}
    assert owner_receipt(linked) is None


def test_assignment_revocation_waiting_for_writer_lock_prevents_save(linked):
    from threading import Event
    started = Event()
    def waiting():
        started.set()
        return linked.backend.post(WRITE_PATH, json=linked.answer)
    with Session(linked.engine) as db:
        service.lock(db)
        call = db.get(PracticeAgentCall, linked.call_id)
        config = json.loads(call.config_json)
        config["enabled"] = False
        call.config_json = service.canonical(config)
        db.add(call)
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(waiting)
            assert started.wait(1)
            db.commit()
            assert pending.result(timeout=5).status_code == 409
    assert owner_receipt(linked) is None


def test_supported_factory_migrated_private_fixture_restart_and_revoked_startup(linked, tmp_path):
    import os
    from pathlib import Path
    import subprocess
    import sys

    target = tmp_path / "migrated-capability.json"
    clean = {"PATH": os.environ.get("PATH", ""), "PYTHON_DOTENV_DISABLED": "1"}
    created = subprocess.run([sys.executable, "scripts/advisor_shadow_demo.py", "create", str(target)],
        cwd=Path(__file__).resolve().parents[1], env=clean, capture_output=True, text=True)
    assert created.returncode == 0, created.stderr
    fixture_config = json.loads(target.read_text())
    from sqlmodel import create_engine
    engine = create_engine("sqlite:///" + fixture_config["database"], connect_args={"check_same_thread": False, "timeout": 2})
    with Session(engine) as db:
        call_id = uuid.UUID(fixture_config["assignment_id"])
        call = db.get(PracticeAgentCall, call_id)
        exported = service.advisor_handoff(db, call.run_id, {"question": "Invented startup fixture?", "user_plan": "Wait for verified evidence"})
    data = json.loads(linked.config.read_text())
    data["profiles"][0].update({key: exported[key] for key in ("assignment_id", "run_id", "packet_sha256", "request_sha256")})
    linked.config.write_text(json.dumps(data))
    for _ in range(2):
        with TestClient(create_app(linked.config, fixture_config["database"])) as client:
            result = client.get(READ_PATH, headers={"Authorization": "Bearer " + linked.token})
            assert result.status_code == 200 and result.json()["request"] == exported
    with Session(engine) as db:
        service.set_enabled(db, call_id, False)
    with pytest.raises(decisions.DecisionError, match="expired or revoked"):
        create_app(linked.config, fixture_config["database"])
    engine.dispose()
