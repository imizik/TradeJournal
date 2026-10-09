"""Public-only publisher: bounded fetches, failure preservation and no grants."""
from __future__ import annotations

import asyncio
import base64
import json
import stat
import time

from cryptography.hazmat.primitives.asymmetric import rsa
import httpx
import pytest

import cloud_mcp_d0 as d0
import cloud_mcp_d0_refresh as publisher

ISSUER = "https://identity.example.test/"
JWKS = ISSUER + "keys"


def metadata():
    return {"issuer": ISSUER, "jwks_uri": JWKS,
        "authorization_endpoint": ISSUER + "authorize", "token_endpoint": ISSUER + "token",
        "code_challenge_methods_supported": ["S256"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "response_types_supported": ["code"], "scopes_supported": ["openid"],
        "token_endpoint_auth_methods_supported": ["none"]}


def public_key():
    numbers = rsa.generate_private_key(public_exponent=65537, key_size=2048).public_key().public_numbers()
    def b64(value):
        return base64.urlsafe_b64encode(value.to_bytes((value.bit_length() + 7) // 8, "big")).rstrip(b"=").decode()
    return {"kid": "public", "kty": "RSA", "alg": "RS256", "use": "sig", "n": b64(numbers.n), "e": b64(numbers.e)}


def config(tmp_path, **overrides):
    path, target = tmp_path / "refresh.json", tmp_path / "keys" / "jwks.json"
    target.parent.mkdir(exist_ok=True)
    value = {"issuer_url": ISSUER, "jwks_url": JWKS, "jwks_file": str(target)}
    value.update(overrides)
    path.write_text(json.dumps(value))
    return path, target


def test_publisher_contacts_only_fixed_public_urls_and_preserves_permissions(tmp_path):
    path, target = config(tmp_path)
    target.write_bytes(b"previous snapshot")
    target.chmod(0o600)
    before = target.stat()
    calls, key = [], public_key()
    async def handler(request):
        calls.append((str(request.url), request.method))
        assert "authorization" not in request.headers and "cookie" not in request.headers
        return httpx.Response(200, json=metadata() if request.url.path.startswith("/.well-known/") else {"keys": [key]})
    result = asyncio.run(publisher.publish(path, http_transport=httpx.MockTransport(handler)))
    saved = d0.KeySnapshot.model_validate_json(target.read_bytes())
    after = target.stat()
    assert result == {"keys": "refreshed", "expires_in_seconds": 3600, "login_observed": False}
    assert calls == [(ISSUER + ".well-known/oauth-authorization-server", "GET"), (JWKS, "GET")]
    assert saved.keys == [key] and saved.expires_at - saved.fetched_at == 3600
    assert (after.st_uid, after.st_gid) == (before.st_uid, before.st_gid)
    assert stat.S_IMODE(after.st_mode) == 0o640
    assert list(target.parent.iterdir()) == [target]


@pytest.mark.parametrize("failure", ["unavailable", "timeout", "redirect", "bad_keys", "private_keys", "oversized", "wrong_issuer"])
def test_failed_publication_preserves_expiry_and_never_falls_back(tmp_path, failure):
    path, target = config(tmp_path)
    now = int(time.time())
    old = {"issuer_url": ISSUER, "jwks_url": JWKS, "fetched_at": now - 3590,
        "expires_at": now + 10, "keys": [public_key()]}
    target.write_text(json.dumps(old))
    before = target.read_bytes()
    calls = []
    async def handler(request):
        calls.append(str(request.url))
        if request.url.path.startswith("/.well-known/"):
            body = metadata()
            if failure == "wrong_issuer":
                body["issuer"] = "https://other.example/"
            return httpx.Response(200, json=body)
        if failure == "timeout":
            raise httpx.ReadTimeout("response-must-not-leak")
        if failure == "redirect":
            return httpx.Response(302, headers={"Location": "https://model.example/paid"})
        if failure == "bad_keys":
            return httpx.Response(200, json={"keys": []})
        if failure == "private_keys":
            return httpx.Response(200, json={"keys": [{**public_key(), "d": "private-material"}]})
        if failure == "oversized":
            return httpx.Response(200, content=b"x" * (d0.MAX_BYTES + 1))
        return httpx.Response(503, json={"error": "issuer-content-must-not-leak"})
    with pytest.raises((ValueError, httpx.HTTPError)):
        asyncio.run(publisher.publish(path, http_transport=httpx.MockTransport(handler)))
    assert target.read_bytes() == before
    assert d0.KeySnapshot.model_validate_json(before).expires_at == now + 10
    assert set(calls) <= {ISSUER + ".well-known/oauth-authorization-server", JWKS}
    assert list(target.parent.iterdir()) == [target]


@pytest.mark.parametrize("extra", ["profiles", "client_id", "client_secret", "model_api_key"])
def test_publisher_refuses_grants_credentials_and_client_configuration(tmp_path, extra):
    path, target = config(tmp_path, **{extra: "value-must-not-leak"})
    with pytest.raises(ValueError):
        asyncio.run(publisher.publish(path, http_transport=httpx.MockTransport(
            lambda _request: pytest.fail("invalid configuration reached network"))))
    assert not target.exists()


@pytest.mark.parametrize("overrides", [
    {"jwks_url": "https://other.example/keys"},
    {"issuer_url": "http://identity.example.test/"},
    {"jwks_url": JWKS + "?secret=value"},
    {"jwks_file": "relative.json"},
])
def test_publisher_rejects_unsafe_urls_or_relative_output_before_network(tmp_path, overrides):
    path, _ = config(tmp_path, **overrides)
    with pytest.raises(ValueError):
        asyncio.run(publisher.publish(path, http_transport=httpx.MockTransport(
            lambda _request: pytest.fail("invalid configuration reached network"))))


@pytest.mark.parametrize("credential", ["OPENAI_API_KEY", "AZURE_OPENAI_KEY", "ANTHROPIC_API_KEY", "TUNNEL_TOKEN", "GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENROUTER_API_KEY"])
def test_publisher_refuses_inherited_model_credentials_before_network(tmp_path, monkeypatch, credential):
    path, _ = config(tmp_path)
    monkeypatch.setenv(credential, "value-must-not-leak")
    with pytest.raises(ValueError) as error:
        asyncio.run(publisher.publish(path, http_transport=httpx.MockTransport(
            lambda _request: pytest.fail("credential-bearing process reached network"))))
    assert "value-must-not-leak" not in str(error.value)


def test_cli_failure_never_logs_configuration_or_exception_values(tmp_path, capsys, monkeypatch):
    path, _ = config(tmp_path, client_secret="value-must-not-leak")
    assert publisher.main(["--config", str(path)]) == 1
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == "Public-key refresh failed\n"
    async def broken(*args, **kwargs):
        raise RuntimeError("response-must-not-leak")
    monkeypatch.setattr(publisher, "publish", broken)
    assert publisher.main(["--config", str(path)]) == 1
    assert capsys.readouterr().err == "Public-key refresh failed\n"


def test_failed_atomic_replace_preserves_snapshot_and_removes_temporary_file(tmp_path, monkeypatch):
    path, target = config(tmp_path)
    target.write_bytes(b"old snapshot must survive publication failure")
    before = target.read_bytes()
    key = public_key()
    async def handler(request):
        return httpx.Response(200, json=metadata() if request.url.path.startswith("/.well-known/") else {"keys": [key]})
    def failed_replace(*args):
        raise PermissionError("filesystem-detail-must-not-leak")
    monkeypatch.setattr(d0.os, "replace", failed_replace)
    with pytest.raises(PermissionError):
        asyncio.run(publisher.publish(path, http_transport=httpx.MockTransport(handler)))
    assert target.read_bytes() == before
    assert list(target.parent.iterdir()) == [target]
