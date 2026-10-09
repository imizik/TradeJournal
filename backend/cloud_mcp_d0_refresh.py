"""Scheduled public-key publisher; never serves MCP or reads profile grants."""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit

from pydantic import field_validator, model_validator

from cloud_mcp_d0 import Config, MAX_BYTES, Strict, refresh_keys, reject_model_credentials


class RefreshConfig(Strict):
    issuer_url: str
    jwks_url: str
    jwks_file: str

    @field_validator("issuer_url", "jwks_url")
    @classmethod
    def public_https_url(cls, value):
        return Config.https_url(value)

    @field_validator("jwks_file")
    @classmethod
    def absolute_key_file(cls, value):
        return Config.absolute_key_file(value)

    @model_validator(mode="after")
    def same_issuer_origin(self):
        issuer, jwks = urlsplit(self.issuer_url), urlsplit(self.jwks_url)
        if (issuer.scheme, issuer.netloc) != (jwks.scheme, jwks.netloc):
            raise ValueError("Public keys must use the configured issuer origin")
        return self


async def publish(config_path: Path, *, http_transport=None):
    reject_model_credentials()
    with config_path.open("rb") as handle:
        body = handle.read(MAX_BYTES + 1)
    if len(body) > MAX_BYTES:
        raise ValueError("Public-key configuration is too large")
    config = RefreshConfig.model_validate_json(body)
    return await refresh_keys(config, http_transport=http_transport)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = asyncio.run(publish(args.config))
    except Exception:
        # Validation and transport exceptions can contain configuration/response
        # values. Never put those values or inherited credentials in the journal.
        print("Public-key refresh failed", file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
