"""Shared offline OAuth boundary for the opt-in sample Practice reader."""
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator

from cloud_mcp_d0 import Config, JWKSVerifier, MAX_BYTES, ProfileGrant
from cloud_mcp_d2_common import CHOICE_GET_PATH

PRACTICE_SCOPE = "practice:read"
READ_PATHS = frozenset({"GET /cloud-mcp/practice/runs", "GET /cloud-mcp/practice/runs/{run_id}", CHOICE_GET_PATH})
MAX_RESPONSE_BYTES = 1048576


class LinkedProfile(ProfileGrant):
    principal_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{2,63}$")
    principal_version: int = Field(ge=1)

    @field_validator("principal_id")
    @classmethod
    def restricted_principal(cls, value):
        if value == "owner":
            raise ValueError("An owner cannot be a cloud reader")
        return value


class SampleReadConfig(Config):
    sample_only: Literal[True]
    decision_writes: bool = Field(default=False, strict=True)
    profiles: list[LinkedProfile] = Field(min_length=1, max_length=1)
    backend_socket: str = "/run/tradejournal-d1/reads.sock"

    @field_validator("sample_only", mode="before")
    @classmethod
    def explicit_sample(cls, value):
        if value is not True:
            raise ValueError("Sample reads must be explicitly enabled")
        return value

    @field_validator("backend_socket")
    @classmethod
    def unix_path(cls, value):
        if not Path(value).is_absolute() or str(Path(value)) != value or ".." in Path(value).parts:
            raise ValueError("Use an exact absolute Unix socket path")
        return value

    @model_validator(mode="after")
    def offline_only(self):
        if self.jwks_file is None:
            raise ValueError("Domain reads require offline verification keys")
        return self


def read_config(path: Path):
    with path.open("rb") as handle:
        body = handle.read(MAX_BYTES + 1)
    if len(body) > MAX_BYTES:
        raise ValueError("Cloud reader configuration is too large")
    return SampleReadConfig.model_validate_json(body)


class SampleReadVerifier(JWKSVerifier):
    def __init__(self, path):
        super().__init__(path, config_reader=read_config)

    def active_config(self):
        current = super().active_config()
        if current is None or current.backend_socket != self.config.backend_socket:
            return None
        def bindings(config):
            return [(p.subject, p.id, p.principal_id, p.principal_version) for p in config.profiles]
        return current if bindings(current) == bindings(self.config) else None
