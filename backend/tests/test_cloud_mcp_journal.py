"""Real signed offline OAuth with fixture-only curated journal data."""

import hashlib
import json
import os
import time
from datetime import datetime, timezone
from uuid import UUID

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

import cloud_mcp_journal as journal
from tests.test_cloud_mcp_d0_offline import (
    _snapshot,
    ISSUER,
    RESOURCE,
    JWKS_URL,
    CLIENT_ID,
    PROFILE_ID,
)


@pytest.fixture
def setup(tmp_path, monkeypatch):
    # This standalone server must never inherit even the fixture DB URL.
    for name in list(os.environ):
        if name in {
            "DATABASE_URL",
            "MIGRATION_DATABASE_URL",
            "JOURNAL_EXPORT_DATABASE_URL",
        } or name.startswith("PG"):
            monkeypatch.delenv(name)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    keys, cfg, exported = (
        tmp_path / name for name in ("keys.json", "config.json", "journal.json")
    )
    _snapshot(keys, key)
    trades = [
        {
            "id": str(UUID(int=i + 1)),
            "ticker": "MU",
            "instrument_type": "stock",
            "quantity": "2.50",
            "realized_pnl": "-1.01" if i % 2 else None,
            "status": "closed",
            "opened_at": "2026-01-02T09:30:00",
            "closed_at": "2026-01-02T10:00:00",
        }
        for i in range(51)
    ]
    data = {
        "schema_version": "journal-coach-snapshot-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "start_day": "2026-01-01",
        "end_day": "2026-01-03",
        "source": "approved_journal_export",
        "sample_data": True,
        "trades": trades,
    }
    exported.write_text(json.dumps(data))
    config = {
        "enabled": True,
        "journal_only": True,
        "issuer_url": ISSUER,
        "resource_url": RESOURCE,
        "jwks_url": JWKS_URL,
        "jwks_file": str(keys),
        "client_id": CLIENT_ID,
        "profiles": [{"subject": "coach-subject", "id": PROFILE_ID, "enabled": True}],
        "snapshot_file": str(exported),
        "snapshot_sha256": hashlib.sha256(exported.read_bytes()).hexdigest(),
        "start_day": "2026-01-01",
        "end_day": "2026-01-03",
        "sample_data": True,
    }
    cfg.write_text(json.dumps(config))

    def token(**overrides):
        now = int(time.time())
        claims = {
            "iss": ISSUER,
            "aud": RESOURCE,
            "sub": "coach-subject",
            "client_id": CLIENT_ID,
            "scope": "d0:profile journal:read",
            "iat": now,
            "exp": now + 120,
            **overrides,
        }
        return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "test-key"})

    return cfg, exported, keys, config, data, token


def call(
    client, token, name="get_journal_summary", arguments=None, method="tools/call"
):
    return client.post(
        RESOURCE,
        headers={"Accept": "application/json", "Authorization": f"Bearer {token}"},
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": {"name": name, "arguments": arguments or {}}
            if method == "tools/call"
            else {},
        },
    )


def content(response):
    result = response.json()["result"]
    assert not result.get("isError"), result
    return json.loads(result["content"][0]["text"])


def test_signed_reads_catalog_and_pagination(setup):
    cfg, _, _, _, _, token = setup
    with TestClient(journal.create_server(cfg).streamable_http_app()) as client:
        tools = call(client, token(), method="tools/list").json()["result"]["tools"]
        assert {t["name"] for t in tools} == {
            "get_journal_summary",
            "list_journal_trades",
        }
        assert all(t["annotations"]["readOnlyHint"] for t in tools)
        overview = content(call(client, token()))
        assert overview["summary"]["known_pnl_count"] == 25
        assert overview["summary"]["missing_pnl_count"] == 26
        assert overview["summary"]["realized_pnl_total"] == "-25.25"
        first = content(call(client, token(), "list_journal_trades"))
        last = content(
            call(
                client, token(), "list_journal_trades", {"offset": first["next_offset"]}
            )
        )
        assert len(first["trades"]) == 50 and len(last["trades"]) == 1
        assert last["next_offset"] is None
        assert not {"account_id", "ai_review", "notes", "email"} & set(
            first["trades"][0]
        )


@pytest.mark.parametrize(
    "claims",
    [
        {"scope": "d0:profile"},
        {"scope": "journal:read"},
        {"sub": "other"},
        {"aud": "https://other.example.test/mcp"},
        {"client_id": "other"},
        {"iat": 1, "exp": 121},
    ],
)
def test_denied_tokens_never_return_data(setup, claims):
    cfg, _, _, _, _, token = setup
    with TestClient(journal.create_server(cfg).streamable_http_app()) as client:
        response = call(client, token(**claims))
        assert response.status_code in (401, 403)
        assert "-25.25" not in response.text and "MU" not in response.text


@pytest.mark.parametrize(
    "name,args",
    [
        ("record_practice_choice", {}),
        ("get_journal_summary", {"account_id": "anything"}),
        ("list_journal_trades", {"offset": True}),
        ("list_journal_trades", {"offset": "0"}),
        ("list_journal_trades", {"offset": -1}),
        ("list_journal_trades", {"offset": 501}),
        ("list_journal_trades", {"path": "/etc/passwd"}),
    ],
)
def test_unknown_tools_and_arguments_refused(setup, name, args):
    cfg, _, _, _, _, token = setup
    with TestClient(journal.create_server(cfg).streamable_http_app()) as client:
        response = call(client, token(), name, args)
        assert response.json().get("error") or response.json()["result"].get("isError")
        assert "-25.25" not in response.text


@pytest.mark.parametrize(
    "change",
    ["disabled", "subject", "window", "path", "sample", "corrupt", "expired_keys"],
)
def test_current_revocation_pins_integrity_and_keys(setup, change):
    cfg, exported, keys, config, _, token = setup
    app = journal.create_server(cfg).streamable_http_app()
    if change == "disabled":
        config["enabled"] = False
    if change == "subject":
        config["profiles"][0]["subject"] = "other"
    if change == "window":
        config["end_day"] = "2026-01-04"
    if change == "path":
        config["snapshot_file"] = str(exported.parent / "other.json")
    if change == "sample":
        config["sample_data"] = False
    if change == "corrupt":
        exported.write_text("private unapproved content")
    if change == "expired_keys":
        value = json.loads(keys.read_text())
        value["expires_at"] = int(time.time()) - 1
        keys.write_text(json.dumps(value))
    cfg.write_text(json.dumps(config))
    with TestClient(app) as client:
        response = call(client, token())
        assert response.status_code in (401, 403) or response.json()["result"].get(
            "isError"
        )
        assert (
            "private unapproved content" not in response.text
            and "-25.25" not in response.text
        )


def test_revocation_during_snapshot_load_refuses_response(setup, monkeypatch):
    cfg, _, _, config, _, token = setup
    original = journal.load_snapshot

    def revoked(*args, **kwargs):
        value = original(*args, **kwargs)
        config["enabled"] = False
        cfg.write_text(json.dumps(config))
        return value

    monkeypatch.setattr(journal, "load_snapshot", revoked)
    with TestClient(journal.create_server(cfg).streamable_http_app()) as client:
        result = call(client, token()).json()["result"]
        assert result["isError"] and "-25.25" not in str(result)


def test_model_credentials_refused(setup, monkeypatch):
    cfg = setup[0]
    monkeypatch.setenv("OPENAI_API_KEY", "must-never-be-used")
    with pytest.raises(ValueError, match="Remove model"):
        journal.create_server(cfg)


@pytest.mark.parametrize(
    "name", ["DATABASE_URL", "JOURNAL_EXPORT_DATABASE_URL", "PGPASSWORD"]
)
def test_serving_database_credentials_refused(setup, monkeypatch, name):
    monkeypatch.setenv(name, "must-never-be-inherited")
    with pytest.raises(ValueError, match="Remove database"):
        journal.create_server(setup[0])
