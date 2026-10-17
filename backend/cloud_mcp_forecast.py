"""Dormant, separately bound forecast-only MCP. No app DB, providers or inference."""
import argparse
from pathlib import Path
import sys
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.routes import create_protected_resource_routes
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import Tool, ToolAnnotations
from pydantic import AnyHttpUrl, Field, field_validator, model_validator
import uvicorn

from cloud_mcp_d0 import Config, Strict, JWKSVerifier, MAX_BYTES, RequestLimits, activated_socket
from cloud_mcp_advisor_common import reject_credentials

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import advisor_forecast as core  # noqa: E402
from advisor_forecast_exchange import ForecastExchange  # noqa: E402

PROFILE, READ, WRITE = "forecast:profile", "forecast:read", "forecast:write"
TOOL_ARGS = {"get_profile": set(), "get_forecast_snapshot": {"ticker"}, "save_forecast": {"ticker", "snapshot_hash", "forecast"}, "get_forecast_receipt": {"ticker", "snapshot_hash"}}


class Profile(Strict):
    subject: str = Field(min_length=1, max_length=200)
    id: str = Field(pattern=r"^forecast_[a-z0-9-]{8,80}$")
    enabled: bool = True


class ForecastConfig(Strict):
    enabled: bool = False
    forecast_only: Literal[True]
    issuer_url: str
    resource_url: str
    jwks_url: str
    jwks_file: str
    client_id: str = Field(min_length=1, max_length=200)
    client_claim: Literal["client_id", "azp"] = "client_id"
    profiles: list[Profile] = Field(min_length=1, max_length=1)
    spec_file: str
    snapshots: str
    receipts: str
    expected_spec_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    authorized_sessions: list[str] = Field(min_length=2, max_length=2)

    @field_validator("issuer_url", "resource_url", "jwks_url")
    @classmethod
    def https(cls, value):
        return Config.https_url(value)

    @field_validator("jwks_file", "spec_file", "snapshots", "receipts")
    @classmethod
    def absolute(cls, value):
        p = Path(value)
        if not p.is_absolute() or ".." in p.parts or str(p) != value or str(p) == "/":
            raise ValueError("canonical absolute path required")
        if any(p == Path(root) or Path(root) in p.parents for root in ("/opt/tradejournal", "/var/lib/tradejournal", "/etc/tradejournal")):
            raise ValueError("production paths forbidden")
        return value

    @model_validator(mode="after")
    def boundary(self):
        from datetime import date
        if self.authorized_sessions != sorted(set(self.authorized_sessions)) or any(date.fromisoformat(d).isoformat() != d for d in self.authorized_sessions):
            raise ValueError("two exact development sessions required")
        if urlsplit(self.resource_url).path != "/forecast/mcp":
            raise ValueError("separate forecast audience required")
        if urlsplit(self.issuer_url).netloc != urlsplit(self.jwks_url).netloc:
            raise ValueError("issuer/key origin mismatch")
        a, b = Path(self.snapshots), Path(self.receipts)
        if a == b or a in b.parents or b in a.parents:
            raise ValueError("separate snapshot and receipt roots required")
        return self


def read_config(path):
    body = Path(path).read_bytes()
    if len(body) > MAX_BYTES:
        raise ValueError("configuration too large")
    return ForecastConfig.model_validate_json(body)


class Verifier(JWKSVerifier):
    def __init__(self, path):
        super().__init__(path, config_reader=read_config)

    def active_config(self):
        current = super().active_config()
        immutable = ("spec_file", "snapshots", "receipts", "expected_spec_hash", "authorized_sessions")
        if current is None or any(getattr(current, k) != getattr(self.config, k) for k in immutable):
            return None
        try:
            if core.digest(core.read_json(current.spec_file)) != current.expected_spec_hash:
                return None
        except (OSError, ValueError):
            return None
        return current


def scopes(name):
    return [PROFILE, *([READ] if name != "get_profile" else []), *([WRITE] if name == "save_forecast" else [])]


class ForecastMCP(FastMCP):
    def streamable_http_app(self):
        app = super().streamable_http_app()
        routes = create_protected_resource_routes(resource_url=self.settings.auth.resource_server_url,
            authorization_servers=[self.settings.auth.issuer_url], scopes_supported=[PROFILE, READ, WRITE])
        paths = {r.path for r in routes}
        app.routes[:] = [r for r in app.routes if r.path not in paths] + routes
        return RequestLimits(app)

    async def list_tools(self):
        return [Tool.model_validate({**t.model_dump(by_alias=True), "inputSchema": {**t.inputSchema, "additionalProperties": False},
            "securitySchemes": [{"type": "oauth2", "scopes": scopes(t.name)}]}) for t in await super().list_tools()]

    async def call_tool(self, name, arguments):
        if name not in TOOL_ARGS or not isinstance(arguments, dict) or set(arguments) != TOOL_ARGS[name]:
            raise ToolError("Only the declared forecast tools and exact arguments are allowed")
        return await super().call_tool(name, arguments)


def create_server(config_path, *, clock=None):
    reject_credentials()
    verifier = Verifier(config_path)
    config = verifier.config
    spec = core.read_json(config.spec_file)
    if core.digest(spec) != config.expected_spec_hash:
        raise ValueError("spec binding mismatch")
    exchange = ForecastExchange(config.snapshots, config.receipts, core.with_timing(spec, 0), enabled=True, clock=clock)
    host = urlsplit(config.resource_url).netloc
    server = ForecastMCP("tradejournal-isolated-forecast", json_response=True, stateless_http=True,
        streamable_http_path="/forecast/mcp", instructions=(core.SPEC_DIR / "prompt.txt").read_text(),
        token_verifier=verifier, auth=AuthSettings(issuer_url=AnyHttpUrl(config.issuer_url), resource_server_url=AnyHttpUrl(config.resource_url), required_scopes=[PROFILE]),
        transport_security=TransportSecuritySettings(allowed_hosts=[host], allowed_origins=["https://" + host]))

    async def dispatch(name, **args):
        token = get_access_token()
        checked = await verifier.verify_token(token.token) if token else None
        if checked is None or not set(scopes(name)) <= set(checked.scopes):
            raise ToolError("Forecast identity or scope unavailable; no fallback")
        if name == "get_profile":
            return {"id": checked.claims["profile_id"], "name": "Isolated Jo forecast study", "model_pinned": False}
        try:
            if core.stamp(exchange.clock()).date().isoformat() not in config.authorized_sessions:
                raise ValueError("outside two authorized development sessions")
            return getattr(exchange, name)(**args)
        except (ValueError, OSError, KeyError, TypeError):
            raise ToolError("Forecast unavailable, late, malformed or conflicting. Recover the receipt; never bypass through another connector.") from None

    def hints(write=False):
        return ToolAnnotations(readOnlyHint=not write, destructiveHint=False, idempotentHint=True, openWorldHint=False)

    @server.tool(annotations=hints(), structured_output=True, meta={"openai/profile": True, "securitySchemes": [{"type": "oauth2", "scopes": scopes("get_profile")}]})
    async def get_profile() -> dict[str, Any]:
        return await dispatch("get_profile")

    @server.tool(annotations=hints(), structured_output=True, meta={"securitySchemes": [{"type": "oauth2", "scopes": scopes("get_forecast_snapshot")}]})
    async def get_forecast_snapshot(ticker: str) -> dict[str, Any]:
        """Read today's immutable snapshot only. Never fetch fresh quotes or outcomes."""
        return await dispatch("get_forecast_snapshot", ticker=ticker)

    @server.tool(annotations=hints(True), structured_output=True, meta={"securitySchemes": [{"type": "oauth2", "scopes": scopes("save_forecast")}]})
    async def save_forecast(ticker: str, snapshot_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")], forecast: dict) -> dict[str, Any]:
        """Save once; server timestamps. Exact retries return original receipt; changed answers conflict."""
        return await dispatch("save_forecast", ticker=ticker, snapshot_hash=snapshot_hash, forecast=forecast)

    @server.tool(annotations=hints(), structured_output=True, meta={"securitySchemes": [{"type": "oauth2", "scopes": scopes("get_forecast_receipt")}]})
    async def get_forecast_receipt(ticker: str, snapshot_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]) -> dict[str, Any]:
        """Recover only the submitted forecast receipt; no outcome or grading fields."""
        return {"receipt": await dispatch("get_forecast_receipt", ticker=ticker, snapshot_hash=snapshot_hash)}

    return server


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    uvicorn.run(create_server(args.config).streamable_http_app(), fd=activated_socket(read_config(args.config)),
        access_log=False, proxy_headers=False, ws="none", loop="asyncio", log_level="warning", limit_concurrency=8)
