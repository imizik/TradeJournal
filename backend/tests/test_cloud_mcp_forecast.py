"""Offline OAuth and real MCP read/save/recover path; no Jo or provider calls."""
import json
import time

from fastapi.testclient import TestClient
import pytest

from cloud_mcp_forecast import create_server
from tests.test_advisor_forecast import packet, forecast, spec as spec  # noqa: F401
from tests.test_cloud_mcp_d0 import signing_key as signing_key, _token, _jwks, ISSUER, JWKS_URL  # noqa: F401
import advisor_forecast as core

RESOURCE = "https://study.example.test/forecast/mcp"
SCOPES = "forecast:profile forecast:read forecast:write"


@pytest.fixture
def linked(tmp_path, signing_key, spec, monkeypatch):
    for key in ("DATABASE_URL", "MIGRATION_DATABASE_URL"):
        monkeypatch.delenv(key, raising=False)
    p = packet(spec)
    core.exclusive_json(tmp_path / "snapshots" / p["session"] / "MU.json", p)
    core.exclusive_json(tmp_path / "snapshots" / p["session"] / "manifest.json", {t: core.digest(p) for t in spec["tickers"]})
    spec_file = tmp_path / "spec.json"
    spec_file.write_text(json.dumps(spec))
    keys = tmp_path / "keys.json"
    keys.write_text(json.dumps({"issuer_url": ISSUER, "jwks_url": JWKS_URL, "fetched_at": int(time.time()) - 1,
                               "expires_at": int(time.time()) + 600, **_jwks(signing_key.public_key())}))
    config = {"enabled": True, "forecast_only": True, "issuer_url": ISSUER, "resource_url": RESOURCE,
              "jwks_url": JWKS_URL, "jwks_file": str(keys), "client_id": "forecast-client",
              "profiles": [{"subject": "jo-forecast", "id": "forecast-synthetic-study".replace("forecast-", "forecast_"), "enabled": True}],
              "spec_file": str(spec_file), "expected_spec_hash": core.digest(spec),
              "snapshots": str(tmp_path / "snapshots"), "receipts": str(tmp_path / "receipts")}
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps(config))
    clock = [core.at(p["session"], "10:00:06")]
    server = create_server(config_file, clock=lambda: clock[0])
    def token(**overrides):
        return _token(signing_key, **{"audience": RESOURCE, "subject": "jo-forecast", "client_id": "forecast-client", "scope": SCOPES, **overrides})
    with TestClient(server.streamable_http_app()) as client:
        yield client, token, p, clock, config_file, config


def rpc(client, token, name, args):
    return client.post(RESOURCE, headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
                       json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args}})


def test_catalog_read_save_recover_server_timestamp_and_no_outcomes(linked):
    client, token, p, clock, _, _ = linked
    listed = client.post(RESOURCE, headers={"Authorization": "Bearer " + token(), "Accept": "application/json"},
                         json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}).json()
    tools = listed["result"]["tools"]
    assert {t["name"] for t in tools} == {"get_profile", "get_forecast_snapshot", "save_forecast", "get_forecast_receipt"}
    assert all(t["inputSchema"]["additionalProperties"] is False for t in tools)
    read = rpc(client, token(), "get_forecast_snapshot", {"ticker": "MU"}).json()["result"]
    assert not read.get("isError")
    assert read["structuredContent"]["snapshot_hash"] == core.digest(p)
    clock[0] = core.at(p["session"], "10:00:08")
    args = {"ticker": "MU", "snapshot_hash": core.digest(p), "forecast": forecast()}
    saved = rpc(client, token(), "save_forecast", args).json()["result"]
    assert not saved.get("isError")
    assert saved["structuredContent"]["saved_at"].endswith("10:00:08-05:00")
    clock[0] = core.at(p["session"], "10:03:00")
    assert rpc(client, token(), "save_forecast", args).json()["result"] == saved
    recovered = rpc(client, token(), "get_forecast_receipt", {"ticker": "MU", "snapshot_hash": core.digest(p)}).json()["result"]
    assert recovered["structuredContent"]["receipt"] == saved["structuredContent"]
    assert "outcome" not in recovered["structuredContent"]["receipt"]
    assert rpc(client, token(), "save_forecast", {**args, "saved_at": "invented"}).json()["result"]["isError"]
    assert rpc(client, token(), "save_forecast", {**args, "forecast": forecast(terminal_price=100.5)}).json()["result"]["isError"]


@pytest.mark.parametrize("change,status", [({"subject": "production-jo"}, 401), ({"audience": "https://study.example.test/mcp"}, 401), ({"scope": "practice:read"}, 403), ({"now": 1}, 401)])
def test_forecast_identity_audience_scope_and_expiry_refused(linked, change, status):
    client, token, _, _, _, _ = linked
    assert rpc(client, token(**change), "get_forecast_snapshot", {"ticker": "MU"}).status_code == status


def test_write_scope_and_binding_revocation(linked):
    client, token, p, _, path, config = linked
    args = {"ticker": "MU", "snapshot_hash": core.digest(p), "forecast": forecast()}
    denied = rpc(client, token(scope="forecast:profile forecast:read"), "save_forecast", args).json()["result"]
    assert denied["isError"]
    config["enabled"] = False
    path.write_text(json.dumps(config))
    assert rpc(client, token(), "get_forecast_snapshot", {"ticker": "MU"}).status_code == 401
