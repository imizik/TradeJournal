"""Separate pre-trade check identity; never imports journal storage or the owner API.

See docs/agent/advisor-pretrade-check-contract.md. The check resource has its
own path and scopes, so journal, advisor and D0 tokens are never accepted.
"""
import os
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
import uuid

from pydantic import Field, field_validator, model_validator

from cloud_mcp_d0 import Config, JWKSVerifier, MAX_BYTES, Strict, reject_model_credentials

READ_SCOPE = "check:read"
RUN_SCOPE = "check:run"
NOTE_SCOPE = "check:note"
SHADOW_SCOPE = "shadow:decide"
MARKET_READ_SCOPE = "market-watch:read"
MARKET_SUBMIT_SCOPE = "market-watch:submit"
RESOURCE_PATH = "/check/mcp"
SCHEMA = "pretrade-check-mcp-v1"
CREDENTIAL_NAMES = ("alpaca-key-id", "alpaca-secret-key")


class CheckProfile(Strict):
    subject: str = Field(min_length=1, max_length=200)
    id: str = Field(pattern=r"^check_[0-9a-f-]{36}$")
    enabled: bool = True

    @field_validator("id")
    @classmethod
    def canonical_uuid(cls, value):
        if str(uuid.UUID(value[6:])) != value[6:]:
            raise ValueError("Require a canonical check profile UUID")
        return value


class CheckConfig(Strict):
    enabled: bool = False
    check_only: Literal[True]
    issuer_url: str
    resource_url: str
    jwks_url: str
    jwks_file: str
    client_id: str = Field(min_length=1, max_length=200)
    client_claim: Literal["client_id", "azp"] = "client_id"
    profiles: list[CheckProfile] = Field(min_length=1, max_length=1)
    ledger_file: str
    features_pointer: str
    market_watch_snapshots_dir: str | None = None
    shadow_setups_dir: str | None = None
    shadow_outbox_dir: str | None = None
    # History older than this is still real; it is used with a caveat.
    max_feature_age_seconds: int = Field(default=36 * 3600, ge=60, le=14 * 86400)
    provider_feed: Literal["iex", "sip"] = "iex"
    provider_timeout_seconds: float = Field(default=3.0, gt=0, le=5)

    @field_validator("check_only", mode="before")
    @classmethod
    def explicit_check(cls, value):
        if value is not True:
            raise ValueError("Require an explicit check-only binding")
        return value

    @field_validator("issuer_url", "resource_url", "jwks_url")
    @classmethod
    def https_url(cls, value):
        return Config.https_url(value)

    @field_validator("jwks_file", "ledger_file", "features_pointer", "shadow_setups_dir", "shadow_outbox_dir", "market_watch_snapshots_dir")
    @classmethod
    def absolute_path(cls, value):
        if value is None:
            return value
        if not Path(value).is_absolute() or os.path.normpath(value) != value or ".." in Path(value).parts:
            raise ValueError("Require an exact absolute operator-owned path")
        return value

    @model_validator(mode="after")
    def isolated_audience(self):
        issuer, keys = urlsplit(self.issuer_url), urlsplit(self.jwks_url)
        if (issuer.scheme, issuer.netloc) != (keys.scheme, keys.netloc):
            raise ValueError("Keys must match the check issuer")
        # D0/journal end in /mcp and the advisor in /advisor/mcp: their tokens
        # carry a different audience and are refused here.
        if urlsplit(self.resource_url).path != RESOURCE_PATH:
            raise ValueError("Require the separate /check/mcp resource")
        if len({self.ledger_file, self.features_pointer, self.jwks_file}) != 3:
            raise ValueError("Ledger, features and keys must be distinct files")
        paths = [Path(p) for p in (self.shadow_setups_dir, self.shadow_outbox_dir, self.market_watch_snapshots_dir) if p]
        if any(a == b or a in b.parents or b in a.parents for i, a in enumerate(paths) for b in paths[i+1:]):
            raise ValueError("Exchange directories must be distinct and disjoint")
        if any(p == Path(f) or p in Path(f).parents for p in paths
                for f in (self.ledger_file, self.features_pointer, self.jwks_file)):
            raise ValueError("Exchange directories must not contain private check files")
        return self


def read_config(path):
    with Path(path).open("rb") as handle:
        body = handle.read(MAX_BYTES + 1)
    if len(body) > MAX_BYTES:
        raise ValueError("Check configuration exceeds its bound")
    return CheckConfig.model_validate_json(body)


class CheckVerifier(JWKSVerifier):
    """Grant changes apply per call; changing paths or identity needs a restart."""

    def __init__(self, path):
        super().__init__(path, config_reader=read_config)

    def active_config(self):
        current = super().active_config()
        fixed = ("ledger_file", "features_pointer", "provider_feed", "shadow_setups_dir", "shadow_outbox_dir", "market_watch_snapshots_dir")
        if current is None or any(getattr(current, key) != getattr(self.config, key) for key in fixed):
            return None
        return current


def reject_credentials():
    """The service gets its provider key only as a systemd credential file."""
    reject_model_credentials()
    if any(value and (name.startswith(("PG", "ALPACA_", "TRADIER_", "POLYGON_", "APCA_"))
                      or name in {"DATABASE_URL", "MIGRATION_DATABASE_URL", "JOURNAL_EXPORT_DATABASE_URL",
                                  "WEBULL_USERNAME", "WEBULL_PASSWORD"})
           for name, value in os.environ.items()):
        raise ValueError("Check serving refuses ambient provider/database credentials")
