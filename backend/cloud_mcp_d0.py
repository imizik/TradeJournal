"""Synthetic-only cloud MCP probe. Never imports the application or its database.

The external OAuth issuer owns login, consent, PKCE and token refresh. This
resource server exposes one fixed synthetic profile and validates every call.
Run explicitly with a separate configuration; nothing starts it with the app.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import socket
import tempfile
import time
from typing import Literal
from urllib.parse import urlsplit
import uuid

import httpx
import jwt
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import Tool, ToolAnnotations
from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, field_validator, model_validator
from starlette.responses import JSONResponse
import uvicorn

SCOPE = "d0:profile"
MAX_BYTES = 65536
TOKEN_LIFETIME = 300
JWKS_TTL = 60
BODY_READ_TIMEOUT = 10
KEY_SNAPSHOT_LIFETIME = 3600


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ProfileGrant(Strict):
    subject: str = Field(min_length=1, max_length=200)
    id: str = Field(pattern=r"^d0_[0-9a-f-]{36}$")
    enabled: bool = True

    @field_validator("id")
    @classmethod
    def valid_id(cls, value):
        if value != "d0_" + str(uuid.UUID(value[3:])):
            raise ValueError("Use a canonical synthetic profile UUID")
        return value


class Config(Strict):
    enabled: bool = False
    synthetic_only: Literal[True]
    issuer_url: str
    resource_url: str
    jwks_url: str
    jwks_file: str | None = None
    client_id: str = Field(min_length=1, max_length=200)
    client_claim: Literal["client_id", "azp"] = "client_id"
    profiles: list[ProfileGrant] = Field(min_length=1, max_length=10)

    @field_validator("jwks_file")
    @classmethod
    def absolute_key_file(cls, value):
        if value is not None and not Path(value).is_absolute():
            raise ValueError("Use an absolute operator-managed public-key file")
        return value

    @field_validator("synthetic_only", mode="before")
    @classmethod
    def synthetic_flag(cls, value):
        if value is not True:
            raise ValueError("Only an explicitly synthetic probe is supported")
        return value

    @field_validator("issuer_url", "resource_url", "jwks_url")
    @classmethod
    def https_url(cls, value):
        parsed = urlsplit(value)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username
                or parsed.password or parsed.query or parsed.fragment
                or str(AnyHttpUrl(value)) != value):
            raise ValueError("Use an exact canonical HTTPS URL without credentials or query")
        return value

    @model_validator(mode="after")
    def validate_boundary(self):
        issuer, jwks = urlsplit(self.issuer_url), urlsplit(self.jwks_url)
        if (issuer.scheme, issuer.netloc) != (jwks.scheme, jwks.netloc):
            raise ValueError("JWKS must use the explicitly configured issuer origin")
        if urlsplit(self.resource_url).path != "/mcp":
            raise ValueError("The synthetic resource must end in /mcp")
        if (len({p.subject for p in self.profiles}) != len(self.profiles)
                or len({p.id for p in self.profiles}) != len(self.profiles)):
            raise ValueError("Subjects and synthetic profile IDs must be unique")
        return self


class Profile(Strict):
    id: str = Field(pattern=r"^d0_[0-9a-f-]{36}$")
    name: Literal["TradeJournal D0 synthetic profile"] = "TradeJournal D0 synthetic profile"


def read_config(path: Path) -> Config:
    with path.open("rb") as handle:
        body = handle.read(MAX_BYTES + 1)
    if len(body) > MAX_BYTES:
        raise ValueError("Synthetic configuration is too large")
    return Config.model_validate_json(body)


class KeySnapshot(Strict):
    issuer_url: str
    jwks_url: str
    fetched_at: int
    expires_at: int
    keys: list[dict]


def validate_keys(keys):
    if not isinstance(keys, list) or not 1 <= len(keys) <= 16:
        raise ValueError("Invalid issuer keys")
    ids = []
    for key in keys:
        if not isinstance(key, dict):
            raise ValueError("Invalid issuer keys")
        kid = key.get("kid")
        if not isinstance(kid, str) or not 1 <= len(kid) <= 200:
            raise ValueError("Invalid issuer key IDs")
        # A snapshot contains public verification keys, never issuer secrets.
        operations = key.get("key_ops", ["verify"])
        if (key.get("kty") != "RSA" or key.get("alg", "RS256") != "RS256"
                or key.get("use", "sig") != "sig" or not isinstance(operations, list)
                or "verify" not in operations
                or set(key) & {"d", "p", "q", "dp", "dq", "qi", "oth", "k"}):
            raise ValueError("Only public RSA verification keys are supported")
        try:
            if jwt.PyJWK.from_dict(key).key.key_size < 2048:
                raise ValueError("Weak public key")
        except (jwt.PyJWTError, ValueError, TypeError, AttributeError) as exc:
            raise ValueError("Invalid public verification key") from exc
        ids.append(kid)
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate issuer key IDs")
    return keys


def local_keys(config: Config):
    with Path(config.jwks_file).open("rb") as handle:
        body = handle.read(MAX_BYTES + 1)
    if len(body) > MAX_BYTES:
        raise ValueError("Public-key snapshot is too large")
    snapshot = KeySnapshot.model_validate_json(body)
    if (snapshot.issuer_url != config.issuer_url or snapshot.jwks_url != config.jwks_url
            or not snapshot.fetched_at <= time.time() < snapshot.expires_at
            or not 0 < snapshot.expires_at - snapshot.fetched_at <= KEY_SNAPSHOT_LIFETIME):
        raise ValueError("Public-key snapshot is expired or does not match the issuer")
    return validate_keys(snapshot.keys)


async def refresh_keys(config: Config, *, http_transport=None):
    """Operator-only public-key fetch. The isolated serving process cannot run it."""
    if config.jwks_file is None:
        raise ValueError("Configure an operator-managed key file first")
    await check_issuer(config, http_transport=http_transport)
    keys = validate_keys((await fetch_json(config.jwks_url, http_transport)).get("keys"))
    now = int(time.time())
    snapshot = KeySnapshot(issuer_url=config.issuer_url, jwks_url=config.jwks_url,
        fetched_at=now, expires_at=now + KEY_SNAPSHOT_LIFETIME, keys=keys)
    body = snapshot.model_dump_json().encode()
    if len(body) > MAX_BYTES:
        raise ValueError("Public-key snapshot is too large")
    target = Path(config.jwks_file)
    previous = target.stat() if target.exists() else None
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as handle:
            temporary = Path(handle.name)
            os.chmod(temporary, 0o640)
            if previous is not None:
                os.chown(temporary, previous.st_uid, previous.st_gid)
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return {"keys": "refreshed", "expires_in_seconds": KEY_SNAPSHOT_LIFETIME,
        "login_observed": False}


def activated_socket(config: Config):
    if config.jwks_file is None:
        raise ValueError("Socket deployment requires offline public keys")
    # Refuse accidental model/tunnel credential inheritance without printing values.
    prefixes = ("OPENAI_", "AZURE_OPENAI_", "ANTHROPIC_", "TUNNEL_")
    names = {"GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENROUTER_API_KEY"}
    if any(value and (name.startswith(prefixes) or name in names) for name, value in os.environ.items()):
        raise ValueError("Remove model and tunnel credentials from the probe environment")
    if os.environ.get("LISTEN_PID") != str(os.getpid()) or os.environ.get("LISTEN_FDS") != "1":
        raise ValueError("Exactly one systemd listening socket is required")
    # Auto-detect the actual socket family rather than assigning AF_UNIX to a TCP fd.
    try:
        with socket.socket(fileno=os.dup(3)) as inherited:
            if (inherited.family != socket.AF_UNIX or inherited.type != socket.SOCK_STREAM
                    or not isinstance(inherited.getsockname(), (str, bytes))
                    or not inherited.getsockopt(socket.SOL_SOCKET, socket.SO_ACCEPTCONN)):
                raise ValueError("Only a listening Unix socket is supported")
    except OSError as exc:
        raise ValueError("Listening socket inspection is unavailable") from exc
    local_keys(config)
    return 3


async def fetch_json(url, http_transport=None):
    async with httpx.AsyncClient(transport=http_transport, timeout=5,
            follow_redirects=False, trust_env=False) as client:
        async with client.stream("GET", url) as response:
            response.raise_for_status()
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > MAX_BYTES:
                    raise ValueError("Issuer response too large")
    document = json.loads(body)
    if not isinstance(document, dict):
        raise ValueError("Invalid issuer response")
    return document


async def check_issuer(config: Config, *, http_transport=None):
    """Check the selected external issuer before configuring a cloud link.

    This is metadata validation, not a login, consent or token-exchange test.
    Only the configured issuer origin is contacted and redirects are refused.
    """
    issuer = urlsplit(config.issuer_url)
    base = f"{issuer.scheme}://{issuer.netloc}"
    oauth_metadata = base + "/.well-known/oauth-authorization-server" + issuer.path.rstrip("/")
    try:
        metadata = await fetch_json(oauth_metadata, http_transport)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code != 404:
            raise
        metadata = await fetch_json(config.issuer_url.rstrip("/") + "/.well-known/openid-configuration", http_transport)
    if metadata.get("issuer") != config.issuer_url or metadata.get("jwks_uri") != config.jwks_url:
        raise ValueError("Issuer or key metadata does not match the selected configuration")
    for key in ("authorization_endpoint", "token_endpoint"):
        value = metadata.get(key)
        if not isinstance(value, str):
            raise ValueError("Issuer endpoints are missing")
        Config.https_url(value)
        parsed = urlsplit(value)
        if (parsed.scheme, parsed.netloc) != (issuer.scheme, issuer.netloc):
            raise ValueError("Issuer endpoints must use the selected origin")
    checks = {"code_challenge_methods_supported": "S256", "grant_types_supported": "authorization_code",
        "response_types_supported": "code"}
    if any(not isinstance(metadata.get(key), list) or expected not in metadata[key] for key, expected in checks.items()):
        raise ValueError("Issuer must advertise authorization code and PKCE S256")
    # Provider-wide discovery need not enumerate resource-specific API scopes.
    # This preflight never grants access: the signed token must still carry SCOPE
    # at every authenticated discovery/tool request, enforced by the SDK.
    scopes = metadata.get("scopes_supported", [])
    if not isinstance(scopes, list) or any(not isinstance(scope, str) for scope in scopes):
        raise ValueError("Invalid advertised scope metadata")
    if "refresh_token" not in metadata["grant_types_supported"]:
        raise ValueError("D0 requires a refresh-capable connection")
    methods = metadata.get("token_endpoint_auth_methods_supported", ["client_secret_basic"])
    if not isinstance(methods, list) or not set(methods) & {"none", "client_secret_basic", "client_secret_post"}:
        raise ValueError("Configure a supported predefined OAuth client")
    return {"metadata": "valid", "mode": "synthetic_only", "pkce": "S256",
        "refresh": "advertised", "synthetic_scope_advertised": SCOPE in scopes,
        "scope_enforcement": "access_token", "login_observed": False}


class JWKSVerifier:
    """Only configured RS256 keys; no token-selected URLs or identity headers."""

    def __init__(self, config_path: Path, *, http_transport=None):
        self.config_path = config_path
        self.config = read_config(config_path)
        if not self.config.enabled:
            raise ValueError("Synthetic MCP probe is disabled")
        self.http_transport = http_transport
        self.keys = []
        self.fetched_at = None
        self.lock = asyncio.Lock()

    def active_config(self) -> Config | None:
        try:
            current = read_config(self.config_path)
            # Grant changes/revocation take effect immediately. Changing the
            # issuer/client/resource needs a restart, never an implicit relink.
            immutable = {"issuer_url", "resource_url", "jwks_url", "jwks_file", "client_id", "client_claim"}
            if not current.enabled or any(getattr(current, key) != getattr(self.config, key) for key in immutable):
                return None
            original_ids = {p.subject: p.id for p in self.config.profiles}
            if any(original_ids.get(p.subject) != p.id for p in current.profiles):
                return None
            return current
        except (OSError, ValueError):
            return None

    async def signing_keys(self):
        if self.config.jwks_file is not None:
            # Check expiry/rotation on every call. Never fall back to network keys.
            return local_keys(self.config)
        async with self.lock:
            stamp = time.monotonic()
            if self.fetched_at is not None and stamp - self.fetched_at < JWKS_TTL:
                return self.keys
            # Cache failed lookups as well: forged kids cannot force repeated
            # network calls. A key rotation may take up to JWKS_TTL to appear.
            self.keys, self.fetched_at = [], stamp
            keys = (await fetch_json(self.config.jwks_url, self.http_transport)).get("keys")
            if not isinstance(keys, list) or not 1 <= len(keys) <= 16:
                raise ValueError("Invalid issuer keys")
            if any(not isinstance(key, dict) for key in keys):
                raise ValueError("Invalid issuer keys")
            ids = [key.get("kid") for key in keys]
            if any(not isinstance(kid, str) or not 1 <= len(kid) <= 200 for kid in ids) or len(set(ids)) != len(ids):
                raise ValueError("Invalid issuer key IDs")
            self.keys = keys
            return self.keys

    async def verify_token(self, token: str) -> AccessToken | None:
        current = self.active_config()
        if current is None or not isinstance(token, str) or len(token) > 8192:
            return None
        try:
            header = jwt.get_unverified_header(token)
            kid = header.get("kid")
            if header.get("alg") != "RS256" or header.get("crit") or not isinstance(kid, str) or len(kid) > 200:
                return None
            key = next((key for key in await self.signing_keys() if key["kid"] == kid), None)
            if (key is None or key.get("kty") != "RSA" or key.get("alg", "RS256") != "RS256"
                    or key.get("use", "sig") != "sig" or "verify" not in key.get("key_ops", ["verify"])):
                return None
            public_key = jwt.PyJWK.from_dict(key).key
            if public_key.key_size < 2048:
                return None
            claims = jwt.decode(token, public_key, algorithms=["RS256"],
                issuer=self.config.issuer_url, audience=self.config.resource_url,
                options={"require": ["iss", "aud", "sub", "exp", "iat", self.config.client_claim], "strict_aud": True})
            if (type(claims["exp"]) is not int or type(claims["iat"]) is not int
                    or not 0 < claims["exp"] - claims["iat"] <= TOKEN_LIFETIME
                    or claims[self.config.client_claim] != self.config.client_id):
                return None
            subject, scopes = claims["sub"], claims.get("scope", "")
            if not isinstance(subject, str) or not isinstance(scopes, str) or len(scopes) > 200:
                return None
            profile = next((p for p in current.profiles if p.subject == subject and p.enabled), None)
            if profile is None:
                return None
            return AccessToken(token=token, client_id=self.config.client_id, subject=subject,
                expires_at=claims["exp"], resource=self.config.resource_url, scopes=scopes.split(),
                claims={"profile_id": profile.id})
        except (OSError, jwt.PyJWTError, httpx.HTTPError, ValueError, TypeError, KeyError, AttributeError, RecursionError):
            # Neither tokens nor issuer responses belong in an error/result log.
            return None


class SyntheticMCP(FastMCP):
    def streamable_http_app(self):
        app = super().streamable_http_app()
        app.add_middleware(RequestLimits)
        return app

    async def list_tools(self) -> list[Tool]:
        tools = await super().list_tools()
        return [Tool.model_validate({**tool.model_dump(by_alias=True),
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
            "securitySchemes": [{"type": "oauth2", "scopes": [SCOPE]}]}) for tool in tools]

    async def call_tool(self, name, arguments):
        if name != "get_profile" or arguments:
            raise ToolError("Only get_profile with an empty argument object is supported")
        return await super().call_tool(name, arguments)


class RequestLimits:
    """Bound even unauthenticated HTTP input before the SDK processes it."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = scope.get("headers", [])
        if sum(len(k) + len(v) for k, v in headers) > 16384:
            return await JSONResponse({"error": "Headers too large"}, status_code=431)(scope, receive, send)
        if len([v for k, v in headers if k.lower() == b"authorization"]) > 1:
            return await JSONResponse({"error": "Ambiguous authorization"}, status_code=400)(scope, receive, send)
        if scope["method"] == "POST":
            async def read_body():
                body = bytearray()
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        return None
                    body.extend(message.get("body", b""))
                    if len(body) > MAX_BYTES or not message.get("more_body"):
                        return body

            # One deadline covers the entire upload. More chunks must never
            # renew an unauthenticated caller's concurrency slot indefinitely.
            try:
                body = await asyncio.wait_for(read_body(), timeout=BODY_READ_TIMEOUT)
            except asyncio.TimeoutError:
                # Uvicorn counts open connections in its concurrency limit;
                # stop incomplete uploads rather than leaving them on keepalive.
                return await JSONResponse({"error": "Request timed out"}, status_code=408,
                    headers={"Connection": "close"})(scope, receive, send)
            if body is None:
                return
            if len(body) > MAX_BYTES:
                return await JSONResponse({"error": "Request too large"}, status_code=413)(scope, receive, send)
            delivered = False

            async def replay():
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {"type": "http.request", "body": bytes(body), "more_body": False}
                return await receive()

            return await self.app(scope, replay, send)
        return await self.app(scope, receive, send)


def create_server(config_path: Path, *, http_transport: httpx.AsyncBaseTransport | None = None) -> FastMCP:
    verifier = JWKSVerifier(config_path, http_transport=http_transport)
    config = verifier.config
    resource = urlsplit(config.resource_url)
    server = SyntheticMCP("tradejournal-d0-synthetic", json_response=True, stateless_http=True,
        instructions="Synthetic connectivity probe only. get_profile returns a fixed test profile. "
        "No TradeJournal data, writes, monitoring or subscriptions are available. "
        "For UI inspection, use the separately authorized assistant browser entrance.",
        token_verifier=verifier, auth=AuthSettings(issuer_url=AnyHttpUrl(config.issuer_url),
            resource_server_url=AnyHttpUrl(config.resource_url), required_scopes=[SCOPE]),
        transport_security=TransportSecuritySettings(allowed_hosts=["127.0.0.1:*", "localhost:*", resource.netloc],
            allowed_origins=["http://127.0.0.1:*", "http://localhost:*", f"{resource.scheme}://{resource.netloc}"]))

    @server.tool(title="Synthetic connection profile", annotations=ToolAnnotations(
        readOnlyHint=True, destructiveHint=False, openWorldHint=False, idempotentHint=True),
        meta={"openai/profile": True}, structured_output=True)
    async def get_profile() -> Profile:
        """Return the synthetic profile for the authenticated connection. No arguments."""
        access = get_access_token()
        checked = await verifier.verify_token(access.token) if access else None
        if checked is None or SCOPE not in checked.scopes:
            raise ToolError("Synthetic connection is unavailable; reconnect or contact the owner")
        return Profile(id=checked.claims["profile_id"])

    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8788)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check-issuer", action="store_true", help="Validate external OAuth metadata without starting the server")
    mode.add_argument("--refresh-keys", action="store_true", help="Operator-only refresh of the offline public-key snapshot")
    mode.add_argument("--socket-activated", action="store_true", help="Serve an inherited Unix socket using offline public keys")
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535 or args.port in {3000, 3001, 8000, 8080}:
        parser.error("Use a dedicated unprivileged probe port")
    try:
        if args.check_issuer:
            print(json.dumps(asyncio.run(check_issuer(read_config(args.config)))))
            return
        if args.refresh_keys:
            print(json.dumps(asyncio.run(refresh_keys(read_config(args.config)))))
            return
        fd = activated_socket(read_config(args.config)) if args.socket_activated else None
        app = create_server(args.config).streamable_http_app()
    except (OSError, ValueError, httpx.HTTPError):
        parser.error("Synthetic MCP configuration/issuer is missing, invalid, unavailable or disabled")
    uvicorn.run(app, host="127.0.0.1", port=args.port, access_log=False,
        fd=fd, loop="asyncio", ws="none", proxy_headers=False,
        log_level="warning", limit_concurrency=16, timeout_keep_alive=5)


if __name__ == "__main__":
    main()
