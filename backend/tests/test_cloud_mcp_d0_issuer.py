"""Selected-issuer metadata checks; no actual OAuth account is contacted."""
import asyncio
import copy
import json
from pathlib import Path
import subprocess
import sys

import httpx
import pytest

from cloud_mcp_d0 import Config, check_issuer
import cloud_mcp_d0


def config():
    return Config(enabled=False, synthetic_only=True,
        issuer_url="https://issuer.example/realm", resource_url="https://probe.example/mcp",
        jwks_url="https://issuer.example/realm/keys", client_id="predefined-client",
        profiles=[{"subject": "synthetic-subject", "id": "d0_11111111-1111-4111-8111-111111111111"}])


def metadata():
    return {"issuer": "https://issuer.example/realm", "jwks_uri": "https://issuer.example/realm/keys",
        "authorization_endpoint": "https://issuer.example/realm/authorize", "token_endpoint": "https://issuer.example/realm/token",
        "code_challenge_methods_supported": ["S256"], "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"], "scopes_supported": ["d0:profile"],
        "token_endpoint_auth_methods_supported": ["none"]}


def check(document):
    return asyncio.run(check_issuer(config(), http_transport=httpx.MockTransport(lambda req: httpx.Response(200, json=document))))


def test_metadata_validation_does_not_claim_a_login():
    result = check(metadata())
    assert result == {"metadata": "valid", "mode": "synthetic_only", "pkce": "S256",
        "refresh": "advertised", "synthetic_scope_advertised": True,
        "scope_enforcement": "access_token", "login_observed": False}


@pytest.mark.parametrize("field,value", [
    ("issuer", "https://other.example/realm"),
    ("jwks_uri", "https://issuer.example/other/keys"),
    ("authorization_endpoint", "https://other.example/authorize"),
    ("token_endpoint", "http://issuer.example/token"),
    ("token_endpoint", "https://secret@issuer.example/token"),
    ("code_challenge_methods_supported", ["plain"]),
    ("code_challenge_methods_supported", "S256"),
    ("grant_types_supported", ["authorization_code"]),
    ("response_types_supported", ["token"]),
    ("scopes_supported", "d0:profile"),
    ("scopes_supported", [42]),
    ("scopes_supported", None),
    ("token_endpoint_auth_methods_supported", ["unsupported"]),
])
def test_nonmatching_or_incompatible_issuer_is_rejected(field, value):
    document = copy.deepcopy(metadata())
    document[field] = value
    with pytest.raises(ValueError):
        check(document)


@pytest.mark.parametrize("scopes", [[], ["openid", "profile", "offline_access"], ["journal:read"]])
def test_resource_scope_not_advertised_does_not_imply_login_or_scope_grant(scopes):
    document = metadata()
    document["scopes_supported"] = scopes
    result = check(document)
    assert result["metadata"] == "valid"
    assert result["synthetic_scope_advertised"] is False
    assert result["scope_enforcement"] == "access_token"
    assert result["login_observed"] is False


def test_optional_scope_metadata_may_be_omitted():
    document = metadata()
    del document["scopes_supported"]
    assert check(document)["synthetic_scope_advertised"] is False


def test_recorded_auth0_discovery_contract_is_supported():
    fixture = Path(__file__).parent / "fixtures/auth0-d0-discovery-2026-10-09.json"
    recorded = json.loads(fixture.read_text())
    document = recorded["metadata"]
    selected = config().model_copy(update={"issuer_url": document["issuer"], "jwks_url": document["jwks_uri"]})
    requested = []

    def respond(request):
        requested.append(str(request.url))
        return httpx.Response(200, json=document)

    result = asyncio.run(check_issuer(selected, http_transport=httpx.MockTransport(respond)))
    assert requested == ["https://tenant.example/.well-known/oauth-authorization-server"]
    assert result["synthetic_scope_advertised"] is False
    assert result["scope_enforcement"] == "access_token"
    assert result["login_observed"] is False


def test_oidc_fallback_only_follows_a_missing_oauth_metadata_document():
    requested = []

    def respond(request):
        requested.append(str(request.url))
        if len(requested) == 1:
            return httpx.Response(404)
        return httpx.Response(200, json=metadata())

    asyncio.run(check_issuer(config(), http_transport=httpx.MockTransport(respond)))
    assert requested == ["https://issuer.example/.well-known/oauth-authorization-server/realm",
        "https://issuer.example/realm/.well-known/openid-configuration"]


@pytest.mark.parametrize("status", [302, 403, 503])
def test_metadata_errors_and_redirects_are_not_followed(status):
    requested = []

    def respond(request):
        requested.append(str(request.url))
        return httpx.Response(status, headers={"location": "https://untrusted.example/"})

    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(check_issuer(config(), http_transport=httpx.MockTransport(respond)))
    assert len(requested) == 1


def test_synthetic_mode_rejects_numeric_true():
    values = config().model_dump()
    values["synthetic_only"] = 1
    with pytest.raises(ValueError):
        Config.model_validate(values)


def test_probe_import_does_not_load_application_or_database():
    script = Path(cloud_mcp_d0.__file__).resolve()
    code = "import runpy,sys; runpy.run_path(sys.argv[1]); assert not any(n == 'app' or n.startswith('app.') for n in sys.modules)"
    subprocess.run([sys.executable, "-c", code, str(script)], check=True, capture_output=True)


def test_trial_service_denies_production_paths_even_when_they_are_absent():
    root = Path(__file__).resolve().parents[2]
    unit = (root / "deploy/cloud-mcp-d0/tradejournal-d0.service").read_text()
    paths = next(line.split("=", 1)[1].split() for line in unit.splitlines() if line.startswith("InaccessiblePaths="))
    # systemd's '-' prefix tolerates absent paths but still denies existing ones.
    assert paths == ["-/etc/tradejournal", "-/var/lib/tradejournal"]


def test_cli_requires_explicit_enable_and_only_binds_loopback(tmp_path, monkeypatch):
    path = tmp_path / "d0.json"
    path.write_text(config().model_dump_json())
    monkeypatch.setattr(sys, "argv", ["cloud_mcp_d0.py", "--config", str(path)])
    with pytest.raises(SystemExit) as disabled:
        cloud_mcp_d0.main()
    assert disabled.value.code == 2
    values = config().model_dump()
    values["enabled"] = True
    path.write_text(json.dumps(values))
    starts = []
    monkeypatch.setattr(cloud_mcp_d0.uvicorn, "run", lambda app, **kwargs: starts.append(kwargs))
    cloud_mcp_d0.main()
    assert starts[0]["host"] == "127.0.0.1"
    assert starts[0]["access_log"] is False
    monkeypatch.setattr(sys, "argv", ["cloud_mcp_d0.py", "--config", str(path), "--host", "0.0.0.0"])
    with pytest.raises(SystemExit) as external_host:
        cloud_mcp_d0.main()
    assert external_host.value.code == 2
    assert len(starts) == 1
