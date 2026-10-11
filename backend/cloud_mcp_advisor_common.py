"""Separate offline advisor identity; never imports journal/application storage."""
import os
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
import uuid

from pydantic import Field, field_validator, model_validator

from cloud_mcp_d0 import Config, JWKSVerifier, MAX_BYTES, Strict, reject_model_credentials

PROFILE_SCOPE = "advisor:profile"
READ_SCOPE = "advisor:read"
WRITE_SCOPE = "advisor:write"
READ_PATH = "/cloud-mcp/advisor/request"
WRITE_PATH = "/cloud-mcp/advisor/answer"
SCHEMA = "advisor-mcp-fixture-v1"
IDENTITY_KEYS = ("version", "assignment_id", "run_id", "packet_sha256", "request_sha256")
REQUEST_KEYS = ("version", "assignment_id", "run_id", "packet_sha256", "expires_at", "requested_at", "comparison", "question", "user_plan")


class AdvisorProfile(Strict):
    subject: str = Field(min_length=1, max_length=200)
    id: str = Field(pattern=r"^advisor_[0-9a-f-]{36}$")
    enabled: bool = True
    binding_version: int = Field(ge=1)
    assignment_id: str = Field(min_length=36, max_length=36)
    run_id: str = Field(min_length=36, max_length=36)
    packet_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("id", "assignment_id", "run_id")
    @classmethod
    def canonical_uuid(cls, value):
        raw = value[8:] if value.startswith("advisor_") else value
        if str(uuid.UUID(raw)) != raw:
            raise ValueError("Require a canonical advisor UUID")
        return value


class AdvisorConfig(Strict):
    enabled: bool = False
    advisor_only: Literal[True]
    issuer_url: str
    resource_url: str
    jwks_url: str
    jwks_file: str
    client_id: str = Field(min_length=1, max_length=200)
    client_claim: Literal["client_id", "azp"] = "client_id"
    profiles: list[AdvisorProfile] = Field(min_length=1, max_length=1)
    backend_socket: str

    @field_validator("advisor_only", mode="before")
    @classmethod
    def explicit_advisor(cls, value):
        if value is not True:
            raise ValueError("Require an explicit advisor-only binding")
        return value

    @field_validator("issuer_url", "resource_url", "jwks_url")
    @classmethod
    def https_url(cls, value):
        return Config.https_url(value)

    @field_validator("jwks_file", "backend_socket")
    @classmethod
    def absolute_path(cls, value):
        if not Path(value).is_absolute() or str(Path(value)) != value or ".." in Path(value).parts:
            raise ValueError("Require an exact absolute operator-owned path")
        return value

    @model_validator(mode="after")
    def isolated_audience(self):
        issuer, keys = urlsplit(self.issuer_url), urlsplit(self.jwks_url)
        if (issuer.scheme, issuer.netloc) != (keys.scheme, keys.netloc):
            raise ValueError("Keys must match the advisor issuer")
        # Existing D0/practice/journal resources end in /mcp. Tokens for those
        # resources cannot be accepted by this independent advisor entrance.
        if urlsplit(self.resource_url).path != "/advisor/mcp":
            raise ValueError("Require the separate /advisor/mcp resource")
        return self


def read_config(path):
    with Path(path).open("rb") as handle:
        body = handle.read(MAX_BYTES + 1)
    if len(body) > MAX_BYTES:
        raise ValueError("Advisor configuration exceeds its bound")
    return AdvisorConfig.model_validate_json(body)


class AdvisorVerifier(JWKSVerifier):
    def __init__(self, path):
        super().__init__(path, config_reader=read_config)

    def active_config(self):
        current = super().active_config()
        if current is None or current.backend_socket != self.config.backend_socket:
            return None
        initial = self.config.profiles[0].model_dump(exclude={"enabled"})
        return current if current.profiles[0].model_dump(exclude={"enabled"}) == initial else None


def reject_credentials():
    reject_model_credentials()
    if any(value and (name.startswith(("PG", "ALPACA_", "TRADIER_", "POLYGON_"))
                      or name in {"DATABASE_URL", "MIGRATION_DATABASE_URL", "JOURNAL_EXPORT_DATABASE_URL", "WEBULL_USERNAME", "WEBULL_PASSWORD"})
           for name, value in os.environ.items()):
        raise ValueError("Advisor serving refuses ambient provider/database credentials")
