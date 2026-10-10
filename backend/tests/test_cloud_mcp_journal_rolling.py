"""Signed rolling reads preserve grant, refresh and concurrent revocation boundaries."""

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import cloud_mcp_journal as journal
from journal_coach_publication import publish_snapshot, rolling_window
from journal_coach_snapshot import Snapshot
from tests import test_cloud_mcp_journal as existing
from tests.test_cloud_mcp_journal import call, content


@pytest.fixture
def setup(tmp_path, monkeypatch):
    return existing.setup.__wrapped__(tmp_path, monkeypatch)


def rolling(setup, *, now=None):
    cfg, _, _, config, data, token = setup
    now = now or datetime.now(timezone.utc)
    start, end = rolling_window(now, 30)
    data.update(generated_at=now.isoformat(), start_day=start.isoformat(), end_day=end.isoformat())
    for row in data["trades"]:
        row["opened_at"] = f"{end}T09:30:00"
        row["closed_at"] = f"{end}T10:00:00"
    pointer = cfg.parent / "current.json"
    publish_snapshot(Snapshot.model_validate_json(json.dumps(data)), pointer)
    for key in ("snapshot_file", "snapshot_sha256", "start_day", "end_day"):
        config.pop(key)
    config.update(publication_file=str(pointer), rolling_days=30)
    cfg.write_text(json.dumps(config))
    return cfg, pointer, config, data, token


def test_rolling_reads_refresh_without_identity_or_server_restart(setup):
    cfg, pointer, _, data, token = rolling(setup)
    with TestClient(journal.create_server(cfg).streamable_http_app()) as client:
        original = content(call(client, token()))
        data["trades"][0]["realized_pnl"] = "8.00"
        data["generated_at"] = datetime.now(timezone.utc).isoformat()
        publish_snapshot(Snapshot.model_validate_json(json.dumps(data)), pointer)
        refreshed = content(call(client, token()))
        assert original["snapshot_sha256"] != refreshed["snapshot_sha256"]
        assert refreshed["summary"]["realized_pnl_total"] == "-17.25"
        assert refreshed["start_day"] == original["start_day"]
        assert content(call(client, token(), "list_journal_trades", {"offset":50}))["next_offset"] is None


@pytest.mark.parametrize("change", ["days", "publication", "sample", "disabled"])
def test_running_rolling_grant_cannot_expand(setup, change):
    cfg, _, config, _, token = rolling(setup)
    server = journal.create_server(cfg)
    if change == "days":
        config["rolling_days"] = 31
    if change == "publication":
        config["publication_file"] += ".other"
    if change == "sample":
        config["sample_data"] = False
    if change == "disabled":
        config["enabled"] = False
    cfg.write_text(json.dumps(config))
    with TestClient(server.streamable_http_app()) as client:
        response = call(client, token())
        assert response.status_code in (401,403) or response.json()["result"].get("isError")
        assert "-25.25" not in response.text


def test_publish_during_read_returns_no_mixed_export(setup, monkeypatch):
    cfg, pointer, _, data, token = rolling(setup)
    original = journal.read_publication
    def racing(*args, **kwargs):
        value = original(*args, **kwargs)
        data["trades"][0]["realized_pnl"] = "8.00"
        publish_snapshot(Snapshot.model_validate_json(json.dumps(data)), pointer)
        return value
    monkeypatch.setattr(journal, "read_publication", racing)
    with TestClient(journal.create_server(cfg).streamable_http_app()) as client:
        response = call(client, token()).json()["result"]
        assert response["isError"] and "-25.25" not in str(response)


def test_rolling_scope_requires_current_eastern_window_even_before_ttl(setup):
    cfg, _, _, data, _ = rolling(setup)
    generated = datetime.fromisoformat(data["generated_at"])
    value, _ = journal.approved_snapshot(journal.read_config(cfg), now=generated)
    assert value.end_day == rolling_window(generated, 30)[1]
    with pytest.raises(ValueError):
        journal.approved_snapshot(journal.read_config(cfg), now=generated+timedelta(days=1))


@pytest.mark.parametrize("extra", [{"start_day":"2026-01-01"}, {"snapshot_sha256":"0"*64}, {"rolling_days":True}])
def test_rolling_config_rejects_ambiguous_or_noninteger_scope(setup, extra):
    cfg, _, config, _, _ = rolling(setup)
    config.update(extra)
    cfg.write_text(json.dumps(config))
    with pytest.raises(ValueError):
        journal.read_config(cfg)
