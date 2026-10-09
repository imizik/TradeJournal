"""Offline key snapshot and socket activation security contract for D0."""
from __future__ import annotations

import asyncio
import base64
import json
import os
import uuid
import socket
import stat
import sys
import time
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from cryptography.hazmat.primitives.asymmetric import rsa

import cloud_mcp_d0 as d0

ISSUER = "https://identity.example.test/"
RESOURCE = "https://journal.example.test/mcp"
JWKS_URL = "https://identity.example.test/.well-known/jwks.json"
CLIENT_ID = "d0-test-client"
PROFILE_ID = f"d0_{uuid.UUID('a7e2e42a-8a8f-4cf9-96f9-87e115de1f02')}"


def _b64int(value: int) -> str:
    return base64.urlsafe_b64encode(value.to_bytes((value.bit_length() + 7) // 8, "big")).rstrip(b"=").decode()


def _jwks(key: rsa.RSAPublicKey) -> dict[str, Any]:
    numbers = key.public_numbers()
    return {"keys": [{"kty": "RSA", "use": "sig", "alg": "RS256", "kid": "test-key",
        "n": _b64int(numbers.n), "e": _b64int(numbers.e)}]}


def _write_config(path: Path, **overrides: Any) -> None:
    config: dict[str, Any] = {"enabled": True, "synthetic_only": True, "issuer_url": ISSUER,
        "resource_url": RESOURCE, "jwks_url": JWKS_URL, "client_id": CLIENT_ID,
        "profiles": [{"subject": "owner-subject", "id": PROFILE_ID, "enabled": True}]}
    config.update(overrides)
    path.write_text(json.dumps(config), encoding="utf-8")


def _token(key: rsa.RSAPrivateKey, *, subject: str = "owner-subject") -> str:
    import jwt
    now = int(time.time())
    claims = {"iss": ISSUER, "aud": RESOURCE, "sub": subject, "client_id": CLIENT_ID,
        "scope": "d0:profile", "iat": now, "exp": now + 120}
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "test-key"})


def _config(path: Path, snapshot: Path | None = None, **overrides: Any) -> None:
    values: dict[str, Any] = {}
    if snapshot is not None:
        values["jwks_file"] = str(snapshot)
    values.update(overrides)
    _write_config(path, **values)


def _snapshot(path: Path, key: rsa.RSAPrivateKey, **overrides: Any) -> None:
    now = int(time.time())
    data: dict[str, Any] = {
        "issuer_url": ISSUER,
        "jwks_url": JWKS_URL,
        "fetched_at": now,
        "expires_at": now + 3600,
        "keys": _jwks(key.public_key())["keys"],
    }
    data.update(overrides)
    path.write_text(json.dumps(data), encoding="utf-8")


def _offline_app(config_path: Path, counter: list[int]):
    async def no_network(request: httpx.Request) -> httpx.Response:
        counter[0] += 1
        raise AssertionError("offline verification attempted network access")

    return d0.create_server(config_path, http_transport=httpx.MockTransport(no_network)).streamable_http_app()


def _call(client: TestClient, token: str):
    return client.post(
        RESOURCE,
        headers={"Accept": "application/json", "Authorization": f"Bearer {token}"},
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
              "params": {"name": "get_profile", "arguments": {}}},
    )


def test_config_requires_absolute_optional_snapshot_path(tmp_path: Path) -> None:
    cfg = tmp_path / "config.json"
    _config(cfg, jwks_file="relative.json")
    with pytest.raises(ValueError):
        d0.read_config(cfg)
    _config(cfg)
    assert d0.read_config(cfg).jwks_file is None


def test_offline_success_and_denial_never_use_network(tmp_path: Path) -> None:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    cfg, snapshot = tmp_path / "config.json", tmp_path / "keys.json"
    _config(cfg, snapshot)
    _snapshot(snapshot, key)
    calls = [0]
    with TestClient(_offline_app(cfg, calls)) as client:
        good = _call(client, _token(key))
        bad = _call(client, _token(rsa.generate_private_key(public_exponent=65537, key_size=2048)))
    assert good.status_code == 200 and PROFILE_ID in good.text
    assert bad.status_code in (401, 403) and PROFILE_ID not in bad.text
    assert calls == [0]


@pytest.mark.parametrize("mutation", [
    "missing", "corrupt", "expired", "future", "wrong_issuer", "wrong_url",
    "too_long", "private", "weak",
])
def test_invalid_snapshot_fails_closed_without_network(tmp_path: Path, mutation: str) -> None:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    cfg, snapshot = tmp_path / "config.json", tmp_path / "keys.json"
    _config(cfg, snapshot)
    if mutation == "missing":
        pass
    elif mutation == "corrupt":
        snapshot.write_bytes(b"{")
    elif mutation in {"expired", "future", "wrong_issuer", "wrong_url", "too_long", "private", "weak"}:
        _snapshot(snapshot, key)
        data = json.loads(snapshot.read_text())
        if mutation == "expired":
            data.update(fetched_at=int(time.time()) - 4000, expires_at=int(time.time()) - 1)
        elif mutation == "future":
            data.update(fetched_at=int(time.time()) + 60, expires_at=int(time.time()) + 3600)
        elif mutation == "wrong_issuer":
            data["issuer_url"] = "https://attacker.example.test/"
        elif mutation == "wrong_url":
            data["jwks_url"] = "https://identity.example.test/other"
        elif mutation == "too_long":
            data["padding"] = "x" * 65536
        elif mutation == "private":
            data["keys"][0]["d"] = "secret-material"
        elif mutation == "weak":
            weak = rsa.generate_private_key(public_exponent=65537, key_size=1024)
            data["keys"] = _jwks(weak.public_key())["keys"]
        snapshot.write_text(json.dumps(data))
    calls = [0]
    with TestClient(_offline_app(cfg, calls)) as client:
        response = _call(client, _token(key))
    assert response.status_code in (401, 403)
    assert PROFILE_ID not in response.text
    assert calls == [0]


def test_snapshot_exact_shape_and_lifetime_limit(tmp_path: Path) -> None:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    cfg, snapshot = tmp_path / "config.json", tmp_path / "keys.json"
    _config(cfg, snapshot)
    now = int(time.time())
    base = {"issuer_url": ISSUER, "jwks_url": JWKS_URL, "fetched_at": now,
            "expires_at": now + 3600, "keys": _jwks(key.public_key())["keys"]}
    for bad in ({**base, "extra": True}, {**base, "expires_at": now + 3601}):
        snapshot.write_text(json.dumps(bad))
        with pytest.raises(ValueError):
            d0.local_keys(d0.read_config(cfg))


def test_refresh_keys_checks_issuer_and_atomically_preserves_mode_and_owner(tmp_path: Path) -> None:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    target, cfg = tmp_path / "keys.json", tmp_path / "config.json"
    _config(cfg, target)
    target.write_text("old")
    target.chmod(0o600)
    before = target.stat()
    metadata = {"issuer": ISSUER, "jwks_uri": JWKS_URL,
        "authorization_endpoint": ISSUER + "authorize", "token_endpoint": ISSUER + "token",
        "code_challenge_methods_supported": ["S256"], "grant_types_supported": ["authorization_code", "refresh_token"],
        "response_types_supported": ["code"], "scopes_supported": ["d0:profile"],
        "token_endpoint_auth_methods_supported": ["none"]}
    calls: list[str] = []
    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if request.url.path == "/.well-known/oauth-authorization-server":
            return httpx.Response(200, json=metadata)
        assert request.url == httpx.URL(JWKS_URL)
        return httpx.Response(200, json=_jwks(key.public_key()))
    result = asyncio.run(d0.refresh_keys(d0.read_config(cfg), http_transport=httpx.MockTransport(handler)))
    after = target.stat()
    saved = d0.KeySnapshot.model_validate_json(target.read_bytes())
    assert result["keys"] == "refreshed"
    assert calls == [ISSUER + ".well-known/oauth-authorization-server", JWKS_URL]
    assert stat.S_IMODE(after.st_mode) == 0o640
    assert (after.st_uid, after.st_gid) == (before.st_uid, before.st_gid)
    assert len(target.read_bytes()) <= 65536
    assert saved.issuer_url == ISSUER and saved.jwks_url == JWKS_URL
    assert saved.expires_at - saved.fetched_at == 3600


def test_key_removal_takes_effect_on_same_verifier_without_network(tmp_path: Path) -> None:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    replacement = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    cfg, snapshot = tmp_path / "config.json", tmp_path / "keys.json"
    _config(cfg, snapshot)
    _snapshot(snapshot, key)
    verifier = d0.JWKSVerifier(cfg, http_transport=httpx.MockTransport(
        lambda _request: pytest.fail("offline verifier attempted network access")))
    token = _token(key)
    assert asyncio.run(verifier.verify_token(token)) is not None
    _snapshot(snapshot, replacement)
    assert asyncio.run(verifier.verify_token(token)) is None


def test_failed_key_refresh_preserves_snapshot_and_leaves_no_temporary_file(tmp_path: Path) -> None:
    directory = tmp_path / "keys"
    directory.mkdir()
    target, cfg = directory / "snapshot.json", tmp_path / "config.json"
    _config(cfg, target)
    old_contents = b"previous snapshot remains intact"
    target.write_bytes(old_contents)
    metadata = {"issuer": ISSUER, "jwks_uri": JWKS_URL,
        "authorization_endpoint": ISSUER + "authorize", "token_endpoint": ISSUER + "token",
        "code_challenge_methods_supported": ["S256"], "grant_types_supported": ["authorization_code", "refresh_token"],
        "response_types_supported": ["code"], "scopes_supported": ["d0:profile"],
        "token_endpoint_auth_methods_supported": ["none"]}
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/.well-known/oauth-authorization-server":
            return httpx.Response(200, json=metadata)
        return httpx.Response(503, json={"error": "unavailable"})
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(d0.refresh_keys(d0.read_config(cfg), http_transport=httpx.MockTransport(handler)))
    assert target.read_bytes() == old_contents
    assert list(directory.iterdir()) == [target]


def test_revocation_remains_immediate_with_offline_keys(tmp_path: Path) -> None:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    cfg, snapshot = tmp_path / "config.json", tmp_path / "keys.json"
    _config(cfg, snapshot)
    _snapshot(snapshot, key)
    calls = [0]
    with TestClient(_offline_app(cfg, calls)) as client:
        assert PROFILE_ID in _call(client, _token(key)).text
        _write_config(cfg, jwks_file=str(snapshot), profiles=[{"subject": "owner-subject", "id": PROFILE_ID, "enabled": False}])
        revoked = _call(client, _token(key))
    assert revoked.status_code in (401, 403)
    assert PROFILE_ID not in revoked.text
    assert calls == [0]


@pytest.mark.parametrize("credential_name", [
    "OPENAI_API_KEY", "OPENAI_CUSTOM", "AZURE_OPENAI_KEY", "ANTHROPIC_API_KEY",
    "TUNNEL_TOKEN", "GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENROUTER_API_KEY",
])
def test_socket_activation_refuses_each_model_or_tunnel_credential_without_leaking(
    tmp_path: Path, monkeypatch, credential_name: str,
) -> None:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    cfg, snapshot = tmp_path / "config.json", tmp_path / "keys.json"
    _config(cfg)
    with pytest.raises(ValueError):
        d0.activated_socket(d0.read_config(cfg))
    _config(cfg, snapshot)
    _snapshot(snapshot, key)
    monkeypatch.setenv("LISTEN_PID", str(os.getpid()))
    monkeypatch.setenv("LISTEN_FDS", "1")
    credential_names = [
        "OPENAI_API_KEY", "OPENAI_CUSTOM", "AZURE_OPENAI_KEY", "ANTHROPIC_API_KEY",
        "TUNNEL_TOKEN", "GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENROUTER_API_KEY",
    ]
    for name in credential_names:
        monkeypatch.delenv(name, raising=False)
    secret = "credential-value-must-not-appear"
    monkeypatch.setenv(credential_name, secret)
    with pytest.raises(ValueError) as raised:
        d0.activated_socket(d0.read_config(cfg))
    assert secret not in str(raised.value)
    monkeypatch.delenv(credential_name)
    monkeypatch.setenv("LISTEN_PID", str(os.getpid() + 1))
    with pytest.raises(ValueError):
        d0.activated_socket(d0.read_config(cfg))
    monkeypatch.setenv("LISTEN_PID", str(os.getpid()))
    monkeypatch.setenv("LISTEN_FDS", "2")
    with pytest.raises(ValueError):
        d0.activated_socket(d0.read_config(cfg))


def _activation_env(monkeypatch) -> None:
    monkeypatch.setenv("LISTEN_PID", str(os.getpid()))
    monkeypatch.setenv("LISTEN_FDS", "1")
    for name in (
        "OPENAI_API_KEY", "OPENAI_CUSTOM", "AZURE_OPENAI_KEY", "ANTHROPIC_API_KEY",
        "TUNNEL_TOKEN", "GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENROUTER_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)


def _map_listener_fd(monkeypatch, listener: socket.socket) -> None:
    original_dup = os.dup
    monkeypatch.setattr(os, "dup", lambda fd: original_dup(listener.fileno()) if fd == 3 else original_dup(fd))


def _unix_listener(path: Path) -> socket.socket:
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(path))
    listener.listen()
    return listener


def test_socket_activation_accepts_actual_unix_listener(tmp_path: Path, monkeypatch) -> None:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    cfg, snapshot = tmp_path / "config.json", tmp_path / "keys.json"
    _config(cfg, snapshot)
    _snapshot(snapshot, key)
    path = Path("/private/tmp") / f"d0-{uuid.uuid4().hex[:10]}.sock"
    listener = _unix_listener(path)
    _activation_env(monkeypatch)
    _map_listener_fd(monkeypatch, listener)
    try:
        if sys.platform == "darwin":
            # macOS does not expose SO_ACCEPTCONN for AF_UNIX; fail closed
            # because the listener state cannot be verified portably here.
            with pytest.raises(ValueError):
                d0.activated_socket(d0.read_config(cfg))
        else:
            assert d0.activated_socket(d0.read_config(cfg)) == 3
    finally:
        listener.close()
        path.unlink(missing_ok=True)


def test_socket_activation_rejects_actual_tcp_listener(tmp_path: Path, monkeypatch) -> None:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    cfg, snapshot = tmp_path / "config.json", tmp_path / "keys.json"
    _config(cfg, snapshot)
    _snapshot(snapshot, key)
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    _activation_env(monkeypatch)
    _map_listener_fd(monkeypatch, listener)
    try:
        with pytest.raises(ValueError):
            d0.activated_socket(d0.read_config(cfg))
    finally:
        listener.close()


def test_socket_activation_rejects_nonlistening_unix_socket(tmp_path: Path, monkeypatch) -> None:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    cfg, snapshot = tmp_path / "config.json", tmp_path / "keys.json"
    _config(cfg, snapshot)
    _snapshot(snapshot, key)
    path = Path("/private/tmp") / f"d0-{uuid.uuid4().hex[:10]}.sock"
    candidate = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    candidate.bind(str(path))
    _activation_env(monkeypatch)
    _map_listener_fd(monkeypatch, candidate)
    try:
        with pytest.raises(ValueError):
            d0.activated_socket(d0.read_config(cfg))
    finally:
        candidate.close()
        path.unlink(missing_ok=True)
