"""Security and contract tests for the standalone D0 MCP server.

These tests use an in-process JWKS fixture and generated RSA keys. They do not
contact an identity provider or imply that an external OAuth deployment works.
"""

from __future__ import annotations

import json
import asyncio
import base64
import hashlib
import secrets
import time
import uuid
from urllib.parse import parse_qs, urlencode, urlsplit
from pathlib import Path
from typing import Any

import anyio
import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from pydantic import ValidationError
from fastapi import FastAPI, Request
from starlette.responses import RedirectResponse
from mcp.client.auth import OAuthClientProvider
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata

from cloud_mcp_d0 import create_server
import cloud_mcp_d0


ISSUER = "https://identity.example.test/"
RESOURCE = "https://journal.example.test/mcp"
JWKS_URL = "https://identity.example.test/.well-known/jwks.json"
CLIENT_ID = "d0-test-client"
PROFILE_ID = f"d0_{uuid.UUID('a7e2e42a-8a8f-4cf9-96f9-87e115de1f02')}"


def _b64int(value: int) -> str:
    import base64

    raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


@pytest.fixture
def signing_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _jwks(key: rsa.RSAPublicKey, kid: str = "test-key") -> dict[str, Any]:
    numbers = key.public_numbers()
    return {
        "keys": [
            {
                "kty": "RSA",
                "use": "sig",
                "alg": "RS256",
                "kid": kid,
                "n": _b64int(numbers.n),
                "e": _b64int(numbers.e),
            }
        ]
    }


@pytest.fixture
def config_path(tmp_path: Path) -> Path:
    path = tmp_path / "cloud-mcp-d0.json"
    _write_config(path)
    return path


def _write_config(path: Path, **overrides: Any) -> None:
    config: dict[str, Any] = {
        "enabled": True,
        "synthetic_only": True,
        "issuer_url": ISSUER,
        "resource_url": RESOURCE,
        "jwks_url": JWKS_URL,
        "client_id": CLIENT_ID,
        "profiles": [
            {"subject": "owner-subject", "id": PROFILE_ID, "enabled": True}
        ],
    }
    config.update(overrides)
    path.write_text(json.dumps(config), encoding="utf-8")


def _token(
    key: rsa.RSAPrivateKey,
    *,
    kid: str = "test-key",
    issuer: str = ISSUER,
    audience: str = RESOURCE,
    subject: str = "owner-subject",
    client_id: str = CLIENT_ID,
    scope: str = "d0:profile",
    now: int | None = None,
    lifetime: int = 120,
    extra: dict[str, Any] | None = None,
    algorithm: str = "RS256",
) -> str:
    import jwt

    issued = int(time.time()) if now is None else now
    claims: dict[str, Any] = {
        "iss": issuer,
        "aud": audience,
        "sub": subject,
        "client_id": client_id,
        "scope": scope,
        "iat": issued,
        "exp": issued + lifetime,
    }
    if extra:
        claims.update(extra)
    signing_material: Any = key if algorithm == "RS256" else "fixture-secret-that-is-at-least-32-bytes"
    return jwt.encode(claims, signing_material, algorithm=algorithm, headers={"kid": kid})


def _app(config_path: Path, key: rsa.RSAPrivateKey, *, status: int = 200, body: Any = None):
    jwks = _jwks(key.public_key())

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == httpx.URL(JWKS_URL)
        if body is not None:
            return httpx.Response(status, content=body)
        return httpx.Response(status, json=jwks if status == 200 else {"error": "offline"})

    server = create_server(config_path, http_transport=httpx.MockTransport(handler))
    return server.streamable_http_app()


def _request(client: TestClient, method: str, params: dict[str, Any] | None = None,
             token: str | None = None) -> dict[str, Any]:
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    response = client.post(
        RESOURCE,
        headers=headers,
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_discovery_and_tool_contract_without_auth(config_path: Path, signing_key: rsa.RSAPrivateKey) -> None:
    app = _app(config_path, signing_key)
    with TestClient(app) as client:
        metadata = client.get("/.well-known/oauth-protected-resource/mcp")
        assert metadata.status_code == 200
        assert metadata.json()["resource"] == RESOURCE
        assert ISSUER in metadata.json()["authorization_servers"]

        listing = _request(client, "tools/list", token=_token(signing_key))
        assert "result" in listing
        tools = listing["result"]["tools"]
        assert [tool["name"] for tool in tools] == ["get_profile"]
        tool = tools[0]
        assert tool.get("annotations", {}).get("readOnlyHint") is True
        assert tool.get("_meta", {}).get("openai/profile") is True
        assert tool.get("securitySchemes") == [{"type": "oauth2", "scopes": ["d0:profile"]}]
        assert tool["inputSchema"].get("additionalProperties") is False
        assert tool["outputSchema"].get("additionalProperties") is False


def test_anonymous_profile_request_gets_auth_challenge_without_data(
    config_path: Path, signing_key: rsa.RSAPrivateKey
) -> None:
    with TestClient(_app(config_path, signing_key)) as client:
        response = client.post(
            RESOURCE,
            headers={"Accept": "application/json"},
            json={"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": "get_profile", "arguments": {}}},
        )
    assert response.status_code == 401
    assert "WWW-Authenticate" in response.headers
    assert "TradeJournal D0 synthetic profile" not in response.text
    assert PROFILE_ID not in response.text


def test_valid_token_returns_only_stable_synthetic_profile(
    config_path: Path, signing_key: rsa.RSAPrivateKey
) -> None:
    token = _token(signing_key)
    with TestClient(_app(config_path, signing_key)) as client:
        result = _request(client, "tools/call", {"name": "get_profile", "arguments": {}}, token)
    text = json.dumps(result)
    assert PROFILE_ID in text
    assert "TradeJournal D0 synthetic profile" in text
    assert "owner-subject" not in text


def test_profile_identity_is_stable_across_tokens_and_server_restart(
    config_path: Path, signing_key: rsa.RSAPrivateKey
) -> None:
    results = []
    for _ in range(2):
        with TestClient(_app(config_path, signing_key)) as client:
            token = _token(signing_key, extra={"jti": str(uuid.uuid4())})
            results.append(_request(client, "tools/call", {"name": "get_profile", "arguments": {}}, token))
    assert results[0] == results[1]


@pytest.mark.parametrize(
    "token_kwargs",
    [
        {"issuer": "https://attacker.example.test/"},
        {"audience": "https://other.example.test/mcp"},
        {"client_id": "another-client"},
        {"subject": "unmapped-subject"},
        {"scope": "openid profile"},
        {"lifetime": -1},
        {"lifetime": 301},
        {"extra": {"iat": None}},
        {"extra": {"exp": None}},
        {"algorithm": "HS256"},
    ],
)
def test_invalid_token_claims_are_rejected(
    config_path: Path, signing_key: rsa.RSAPrivateKey, token_kwargs: dict[str, Any]
) -> None:
    token = _token(signing_key, **token_kwargs)
    with TestClient(_app(config_path, signing_key)) as client:
        response = client.post(
            RESOURCE,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            json={"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "get_profile", "arguments": {}}},
        )
    assert response.status_code in (401, 403)
    assert PROFILE_ID not in response.text


def test_bad_signature_and_unknown_key_are_rejected(
    config_path: Path, signing_key: rsa.RSAPrivateKey
) -> None:
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    cases = [_token(other), _token(signing_key, kid="unknown")]
    for token in cases:
        with TestClient(_app(config_path, signing_key)) as client:
            response = client.post(
                RESOURCE,
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                json={"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "get_profile", "arguments": {}}},
            )
        assert response.status_code in (401, 403)


def test_application_and_profile_revocation_are_immediate(
    config_path: Path, signing_key: rsa.RSAPrivateKey
) -> None:
    token = _token(signing_key)
    with TestClient(_app(config_path, signing_key)) as client:
        assert PROFILE_ID in json.dumps(_request(client, "tools/call", {"name": "get_profile", "arguments": {}}, token))
        _write_config(config_path, profiles=[{"subject": "owner-subject", "id": PROFILE_ID, "enabled": False}])
        request_headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        revoked = client.post(RESOURCE, headers=request_headers, json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "get_profile", "arguments": {}}})
        assert revoked.status_code in (401, 403)
        _write_config(config_path, enabled=False)
        disabled = client.post(RESOURCE, headers=request_headers, json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "get_profile", "arguments": {}}})
        assert disabled.status_code in (401, 403)


def test_jwks_network_failure_fails_closed(config_path: Path, signing_key: rsa.RSAPrivateKey) -> None:
    token = _token(signing_key)
    with TestClient(_app(config_path, signing_key, status=503)) as client:
        response = client.post(RESOURCE, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"}, json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "get_profile", "arguments": {}}})
    assert response.status_code in (401, 403, 503)
    assert PROFILE_ID not in response.text


def test_malformed_jwks_fails_closed(config_path: Path, signing_key: rsa.RSAPrivateKey) -> None:
    token = _token(signing_key)
    with TestClient(_app(config_path, signing_key, body=b"not-json")) as client:
        response = client.post(RESOURCE, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"}, json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "get_profile", "arguments": {}}})
    assert response.status_code in (401, 403)
    assert PROFILE_ID not in response.text


def test_malformed_config_fails_closed(
    config_path: Path, signing_key: rsa.RSAPrivateKey
) -> None:
    config_path.write_text('{"enabled": true,', encoding="utf-8")
    with pytest.raises(ValidationError):
        _app(config_path, signing_key)


def test_azp_client_claim_is_supported_when_explicitly_configured(
    config_path: Path, signing_key: rsa.RSAPrivateKey
) -> None:
    _write_config(config_path, client_claim="azp")
    token = _token(signing_key, extra={"client_id": None, "azp": CLIENT_ID})
    with TestClient(_app(config_path, signing_key)) as client:
        response = _request(client, "tools/call", {"name": "get_profile", "arguments": {}}, token)
    assert PROFILE_ID in json.dumps(response)


def test_unknown_tool_and_extra_arguments_are_rejected(
    config_path: Path, signing_key: rsa.RSAPrivateKey
) -> None:
    token = _token(signing_key)
    with TestClient(_app(config_path, signing_key)) as client:
        unknown = _request(client, "tools/call", {"name": "read_trades", "arguments": {}}, token)
        extra = _request(client, "tools/call", {"name": "get_profile", "arguments": {"include_account": True}}, token)
    assert unknown.get("error") or unknown.get("result", {}).get("isError") is True
    assert extra.get("error") or extra.get("result", {}).get("isError") is True
    assert PROFILE_ID not in json.dumps(extra)


def test_request_limits_and_host_validation(config_path: Path, signing_key: rsa.RSAPrivateKey) -> None:
    with TestClient(_app(config_path, signing_key)) as client:
        oversized = client.post(RESOURCE, headers={"Accept": "application/json"}, content=b"x" * 65537)
        duplicate_auth = client.post(
            RESOURCE,
            headers=[("accept", "application/json"), ("authorization", "Bearer a"), ("authorization", "Bearer b")],
            content=b"{}",
        )
        bad_host = client.post(
            RESOURCE,
            headers={
                "host": "attacker.example",
                "accept": "application/json",
                "authorization": f"Bearer {_token(signing_key)}",
            },
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        )
    assert oversized.status_code == 413
    assert duplicate_auth.status_code == 400
    assert bad_host.status_code in (400, 421)


def test_sdk_oauth_pkce_refresh_and_revoked_configuration(
    config_path: Path, signing_key: rsa.RSAPrivateKey
) -> None:
    """Exercise maintained MCP OAuth interoperability with a local issuer fixture."""
    anyio.run(_sdk_oauth_flow, config_path, signing_key)


def test_slow_chunks_cannot_renew_the_complete_body_deadline(monkeypatch):
    monkeypatch.setattr(cloud_mcp_d0, "BODY_READ_TIMEOUT", 0.05)

    async def exercise():
        chunks = 0
        sent = []

        async def receive():
            nonlocal chunks
            if chunks >= 2:
                # Each chunk arrives sooner than the allowed upload duration,
                # but the body never completes. A per-chunk timer would hang.
                await asyncio.sleep(0.02)
            chunks += 1
            return {"type": "http.request", "body": b"x", "more_body": True}

        async def send(message):
            sent.append(message)

        async def app(scope, receive, send):
            pytest.fail("A timed-out upload reached the authenticated SDK app")

        middleware = cloud_mcp_d0.RequestLimits(app)
        await asyncio.wait_for(middleware({"type": "http", "method": "POST", "headers": []}, receive, send), timeout=1)
        assert chunks >= 2
        assert sent[0]["status"] == 408

    anyio.run(exercise)


async def _sdk_oauth_flow(config_path: Path, signing_key: rsa.RSAPrivateKey) -> None:
    issuer_app = FastAPI()
    codes: dict[str, dict[str, str]] = {}
    refreshes = {"count": 0}
    registrations = {"count": 0}
    disabled_rejections = {"count": 0}

    @issuer_app.get("/.well-known/oauth-authorization-server")
    async def authorization_server_metadata():
        return {
            "issuer": ISSUER,
            "authorization_endpoint": ISSUER + "authorize",
            "token_endpoint": ISSUER + "token",
            "registration_endpoint": ISSUER + "register",
            "code_challenge_methods_supported": ["S256"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "response_types_supported": ["code"],
            "token_endpoint_auth_methods_supported": ["none"],
        }

    @issuer_app.post("/register")
    async def register_client(request: Request):
        registrations["count"] += 1
        payload = await request.json()
        assert "http://localhost/callback" in payload["redirect_uris"]
        return {
            "client_id": CLIENT_ID,
            "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "redirect_uris": payload["redirect_uris"],
        }

    @issuer_app.get("/authorize")
    async def authorize(request: Request):
        query = dict(request.query_params)
        assert query["response_type"] == "code"
        assert query["client_id"] == CLIENT_ID
        assert query["scope"] == "d0:profile"
        assert query["code_challenge_method"] == "S256"
        assert query["resource"] == RESOURCE
        code = secrets.token_urlsafe(24)
        codes[code] = {
            "challenge": query["code_challenge"],
            "redirect_uri": query["redirect_uri"],
            "scope": query["scope"],
        }
        return RedirectResponse(
            query["redirect_uri"] + "?" + urlencode({"code": code, "state": query["state"]}),
            status_code=302,
        )

    @issuer_app.post("/token")
    async def token_endpoint(request: Request):
        form = dict(await request.form())
        assert form["client_id"] == CLIENT_ID
        assert form["resource"] == RESOURCE
        if form["grant_type"] == "authorization_code":
            code = codes.pop(form["code"])
            verifier = form["code_verifier"]
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
            assert challenge == code["challenge"]
            assert form["redirect_uri"] == code["redirect_uri"]
            scope = code["scope"]
        else:
            assert form["grant_type"] == "refresh_token"
            assert form["refresh_token"] == "fixture-refresh"
            refreshes["count"] += 1
            scope = "d0:profile"
        now = int(time.time())
        access = _token(signing_key, now=now, lifetime=30, scope=scope)
        return {"access_token": access, "token_type": "Bearer", "expires_in": 1,
                "refresh_token": "fixture-refresh", "scope": scope}

    resource_app = _app(config_path, signing_key)

    class RoutedASGITransport(httpx.AsyncBaseTransport):
        def __init__(self):
            self.resource = httpx.ASGITransport(app=resource_app)
            self.issuer = httpx.ASGITransport(app=issuer_app)

        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            if request.url.host == "journal.example.test":
                response = await self.resource.handle_async_request(request)
                if response.status_code == 401 and not json.loads(config_path.read_text())["enabled"]:
                    disabled_rejections["count"] += 1
                return response
            if request.url.host == "identity.example.test":
                return await self.issuer.handle_async_request(request)
            raise AssertionError(f"Unexpected OAuth test host: {request.url.host}")

        async def aclose(self) -> None:
            await self.resource.aclose()
            await self.issuer.aclose()

    router = RoutedASGITransport()

    stored: dict[str, Any] = {"tokens": None, "client": None}
    stored["client"] = OAuthClientInformationFull(
        client_id=CLIENT_ID,
        redirect_uris=["http://localhost/callback"],
        token_endpoint_auth_method="none",
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
    )

    class Storage:
        async def get_tokens(self):
            return stored["tokens"]

        async def set_tokens(self, value):
            stored["tokens"] = value

        async def get_client_info(self):
            return stored["client"]

        async def set_client_info(self, value):
            stored["client"] = value

    callback: dict[str, str] = {}

    async def redirect_handler(url: str) -> None:
        async with httpx.AsyncClient(transport=router, follow_redirects=False) as client:
            response = await client.get(url)
        assert response.status_code == 302
        callback.update(parse_qs(urlsplit(response.headers["location"]).query))

    async def callback_handler() -> tuple[str, str | None]:
        return callback["code"][0], callback["state"][0]

    auth = OAuthClientProvider(
        server_url=RESOURCE,
        client_metadata=OAuthClientMetadata(
            redirect_uris=["http://localhost/callback"],
            token_endpoint_auth_method="none",
            scope="d0:profile",
            client_name="D0 SDK fixture",
        ),
        storage=Storage(),
        redirect_handler=redirect_handler,
        callback_handler=callback_handler,
        timeout=5,
    )

    async with resource_app.router.lifespan_context(resource_app):
        async with httpx.AsyncClient(transport=router, auth=auth, timeout=10) as http_client:
            async with streamable_http_client(RESOURCE, http_client=http_client) as (read_stream, write_stream, _):
                async with ClientSession(read_stream, write_stream) as session:
                    initialized = await session.initialize()
                    negotiated = initialized.protocolVersion
                    tools = await session.list_tools()
                    assert [tool.name for tool in tools.tools] == ["get_profile"]
                    first = await session.call_tool("get_profile", {})
                    assert PROFILE_ID in json.dumps(first.model_dump())
                    assert refreshes["count"] == 0

                    await anyio.sleep(1.1)
                    refreshed = await session.call_tool("get_profile", {})
                    assert PROFILE_ID in json.dumps(refreshed.model_dump())
                    assert refreshes["count"] == 1
        assert registrations["count"] == 0
        _write_config(config_path, enabled=False)
        with pytest.raises(Exception):
            async with httpx.AsyncClient(transport=router, auth=auth, timeout=10) as http_client:
                async with streamable_http_client(RESOURCE, http_client=http_client) as (read_stream, write_stream, _):
                    async with ClientSession(read_stream, write_stream) as session:
                        await session.initialize()
                        await session.call_tool("get_profile", {})

    assert negotiated == "2025-11-25"
    assert refreshes["count"] == 1
    assert registrations["count"] == 0
    assert disabled_rejections["count"] >= 1
