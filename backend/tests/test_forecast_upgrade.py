"""Upgrade refusal and sandbox contracts; all fixtures are local and invented."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "deploy"))
import advisor_forecast_prepare as prep  # noqa: E402
import advisor_forecast_upgrade as upgrade  # noqa: E402


def test_existing_old_unit_fingerprints_match_the_reviewed_v1():
    # v2 adds a baseline action but does not change the other unit policies.
    for action in ("history", "snapshot", "outcomes"):
        for kind, render in (("service", prep.service), ("timer", prep.timer)):
            old = render(action).replace("/opt/tj-forecast/v2", "/opt/tj-forecast/v1")
            assert hashlib.sha256(old.encode()).hexdigest() == upgrade.OLD_UNITS[f"tj-forecast-{action}.{kind}"]


def test_unsafe_old_manifest_refuses_before_unit_or_account_mutation(tmp_path, monkeypatch):
    old = tmp_path / "v1"
    target = old / "research/advisor-forecast/manifest.json"
    target.parent.mkdir(parents=True)
    target.write_text('{"files": {}}')
    monkeypatch.setattr(upgrade, "OLD", old)
    monkeypatch.setattr(prep, "host_guard", lambda: None)
    monkeypatch.setattr(prep, "check_source", lambda _: None)
    monkeypatch.setattr(upgrade, "owned", lambda *a, **k: None)
    command = Mock(side_effect=AssertionError("mutation attempted"))
    monkeypatch.setattr(upgrade.subprocess, "run", command)
    with pytest.raises(ValueError, match="old study manifest"):
        upgrade.install(tmp_path, tmp_path, "0" * 64)
    command.assert_not_called()


def test_existing_destination_and_symlink_refused(tmp_path):
    (tmp_path / "occupied").mkdir()
    (tmp_path / "link").symlink_to(tmp_path / "missing")
    for name in ("occupied", "link"):
        with pytest.raises(ValueError, match="already exists"):
            upgrade.absent(tmp_path / name)


def test_mcp_sandbox_only_mounts_snapshot_and_receipt_data():
    units = upgrade.mcp_units()
    mcp = units["tj-forecast-mcp.service"]
    assert "PrivateNetwork=true\nRestrictAddressFamilies=AF_UNIX" in mcp
    assert "TemporaryFileSystem=/etc:ro /var:ro /opt:ro /run:ro" in mcp
    assert "BindPaths=/var/lib/tj-forecast-receipts\n" in mcp
    assert "BindReadOnlyPaths=/opt/tj-forecast/v2 /etc/tj-forecast-mcp /var/lib/tj-forecast-keys /var/lib/tj-forecast/snapshots\n" in mcp
    assert "EnvironmentFile" not in mcp
    assert "SocketMode=0660" in units["tj-forecast-mcp.socket"]
    assert "SocketGroup=caddy" in units["tj-forecast-mcp.socket"]
    keys = units["tj-forecast-keys.service"]
    assert "User=tj-forecast-keys" in keys
    assert "ReadWritePaths=/var/lib/tj-forecast-keys\n" in keys
    assert "EnvironmentFile" not in keys
    assert "Persistent=false" in units["tj-forecast-keys.timer"]


def test_bundle_inventory_contains_all_executed_sources():
    assert "backend/cloud_mcp_d0_refresh.py" in prep.FILES
    assert "deploy/advisor_forecast_upgrade.py" in prep.FILES
    assert importlib.util.find_spec("advisor_forecast_upgrade") is not None


def test_proxy_exposes_only_forecast_paths_on_explicit_public_bind():
    value = upgrade.proxy_stanza("https://study.example/forecast/mcp", "8.8.8.8")
    assert "reverse_proxy unix//run/tj-forecast/mcp.sock" in value
    assert "path /forecast/mcp /.well-known/oauth-protected-resource/forecast/mcp" in value
    assert "respond 404" in value
    assert "8080" not in value and "8000" not in value
    for url, address in (("https://study.example/mcp", "8.8.8.8"),
                         ("https://study.example/forecast/mcp", "100.64.0.1"),
                         ("https://study.example:443/forecast/mcp", "8.8.8.8")):
        with pytest.raises(ValueError):
            upgrade.proxy_stanza(url, address)


def test_provider_revision_rolls_back_bundle_and_binding_on_write_failure(tmp_path, monkeypatch):
    runtime, source, config, units = [tmp_path / n for n in ("runtime", "source", "config", "units")]
    names = ("research/advisor-forecast/spec.json", "script.py")
    for root in (runtime, source):
        (root / "research/advisor-forecast").mkdir(parents=True)
    config.mkdir()
    units.mkdir()
    old_spec, new_spec = {"protocol": "old"}, {"protocol": "advisor-forecast-v3-tradier"}
    for root, spec in ((runtime, old_spec), (source, new_spec)):
        (root / names[0]).write_text(json.dumps(spec))
        (root / names[1]).write_text(root.name)
    manifest = {"files": {n: upgrade.sha(runtime / n) for n in names}}
    manifest_name = "research/advisor-forecast/manifest.json"
    (runtime / manifest_name).write_text(json.dumps(manifest))
    (source / manifest_name).write_text('{"new": true}')
    old_hash = hashlib.sha256(json.dumps(old_spec, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    binding = {"expected_spec_hash": old_hash, "spec_file": str(runtime / names[0]), "client_id": "unchanged"}
    (config / "config.json").write_text(json.dumps(binding))
    before = {n: (runtime / n).read_bytes() for n in (*names, manifest_name)}
    monkeypatch.setattr(prep, "RUNTIME", runtime)
    monkeypatch.setattr(prep, "FILES", names)
    monkeypatch.setattr(prep, "CONFIG", tmp_path / "approval")
    for name in ("STATE", "BASELINES", "OUTCOMES", "RECEIPTS"):
        monkeypatch.setattr(prep, name, tmp_path / name)
    monkeypatch.setattr(upgrade, "UNITS", units)
    monkeypatch.setattr(upgrade, "MCP_CONFIG", config)
    monkeypatch.setattr(upgrade, "V2_MANIFEST_SHA", upgrade.sha(runtime / manifest_name))
    monkeypatch.setattr(prep, "host_guard", lambda: None)
    monkeypatch.setattr(prep, "check_source", lambda _: None)
    monkeypatch.setattr(upgrade, "owned", lambda *a, **k: None)
    monkeypatch.setattr(upgrade, "inactive", lambda *a, **k: None)
    for action in prep.ACTIONS:
        for kind, render in (("service", prep.service), ("timer", prep.timer)):
            (units / f"tj-forecast-{action}.{kind}").write_text(render(action))
    for name, body in upgrade.mcp_units().items():
        (units / name).write_text(body)
    run = Mock()
    monkeypatch.setattr(upgrade.subprocess, "run", run)
    monkeypatch.setattr(upgrade.subprocess, "check_output", lambda *a, **k: "active\n")
    actual_replace = upgrade.replace_bytes
    failed = False
    def replacement(path, body, mode):
        nonlocal failed
        if path == config / "config.json" and not failed:
            failed = True
            raise OSError("invented disk error")
        actual_replace(path, body, mode)
    monkeypatch.setattr(upgrade, "replace_bytes", replacement)
    with pytest.raises(OSError, match="disk error"):
        upgrade.revise_provider(source)
    assert {n: (runtime / n).read_bytes() for n in before} == before
    assert json.loads((config / "config.json").read_text()) == binding
    assert all((runtime / "before-tradier" / n).exists() for n in before)
    assert run.call_args.args[0] == ["systemctl", "start", "tj-forecast-mcp.socket", "tj-forecast-keys.timer"]
    assert not any("tradejournal-" in str(call) for call in run.call_args_list)
