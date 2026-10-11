"""Separate offline advisor identity; never imports journal/application storage."""
import os
from pathlib import Path
import stat
import struct
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
    # Optional, explicitly reviewed named-UID read grant for the owner process.
    # None preserves the existing 0600-only fixture permission contract.
    owner_reader_uid: int | None = Field(default=None, ge=1)

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


def fixture_acl(uid, *, directory=False):
    """Linux POSIX ACL: one named UID, no group/other access, never write."""
    undefined = 0xFFFFFFFF
    permission = 1 if directory else 4
    entries = ((1, 7 if directory else 6, undefined), (2, permission, uid),
        (4, 0, undefined), (16, permission, undefined), (32, 0, undefined))
    return struct.pack("<I", 2) + b"".join(struct.pack("<HHI", *entry) for entry in entries)


def private_fixture(path, *, owner_reader_uid=None):
    """Validate original private mode or an exact separately approved UID ACL.

    The ACL mask appears as group mode bits. Its group entry remains zero;
    changing membership does not grant anyone else read/traverse permission.
    Unsupported/missing xattrs refuse when an owner grant is configured.
    """
    path = Path(path)
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or path.suffix != ".db":
        raise ValueError("Require a private existing fixture SQLite file")
    mode = stat.S_IMODE(info.st_mode)
    if owner_reader_uid is None:
        if mode & 0o077:
            raise ValueError("Require a private existing fixture SQLite file")
        return  # Preserve the original owner-only mode contract (normally 0600).
    if owner_reader_uid is None or info.st_uid == owner_reader_uid or mode != 0o640:
        raise ValueError("Require the exact separately approved read-only owner UID grant")
    parent = path.parent
    if not hasattr(os, "getxattr"):
        raise ValueError("Platform cannot verify the named-UID fixture ACL")
    parent_info = parent.stat()
    if (not stat.S_ISDIR(parent_info.st_mode) or stat.S_IMODE(parent_info.st_mode) != 0o710
            or parent_info.st_uid != info.st_uid
            or os.getxattr(path, "system.posix_acl_access") != fixture_acl(owner_reader_uid)
            or os.getxattr(parent, "system.posix_acl_access") != fixture_acl(owner_reader_uid, directory=True)):
        raise ValueError("Owner read-only UID ACL changed")


class AdvisorVerifier(JWKSVerifier):
    def __init__(self, path):
        super().__init__(path, config_reader=read_config)

    def active_config(self):
        current = super().active_config()
        if (current is None or current.backend_socket != self.config.backend_socket
                or current.owner_reader_uid != self.config.owner_reader_uid):
            return None
        initial = self.config.profiles[0].model_dump(exclude={"enabled"})
        return current if current.profiles[0].model_dump(exclude={"enabled"}) == initial else None


def reject_credentials():
    reject_model_credentials()
    if any(value and (name.startswith(("PG", "ALPACA_", "TRADIER_", "POLYGON_"))
                      or name in {"DATABASE_URL", "MIGRATION_DATABASE_URL", "JOURNAL_EXPORT_DATABASE_URL", "WEBULL_USERNAME", "WEBULL_PASSWORD"})
           for name, value in os.environ.items()):
        raise ValueError("Advisor serving refuses ambient provider/database credentials")
