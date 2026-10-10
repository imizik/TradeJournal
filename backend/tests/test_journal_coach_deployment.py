"""Deployment boundary checks for the separately staged journal coach."""
from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "deploy"))
sys.path.insert(0, str(ROOT / "backend"))
import journal_coach_stage as stage  # noqa: E402
from cloud_mcp_journal import JournalConfig  # noqa: E402
from journal_coach_snapshot import load_snapshot  # noqa: E402

_SMOKE_SPEC = importlib.util.spec_from_file_location(
    "journal_native_smoke", ROOT / "deploy/cloud-mcp-journal/smoke.py"
)
native_smoke = importlib.util.module_from_spec(_SMOKE_SPEC)
assert _SMOKE_SPEC.loader is not None
_SMOKE_SPEC.loader.exec_module(native_smoke)


ISSUER = "https://identity.example.test/"
RESOURCE = "https://journal.example.test/mcp"


def stage_fixture(destination: Path, **kwargs):
    return stage.stage(destination, issuer_url=ISSUER, resource_url=RESOURCE,
                       client_id="coach-client", subject="coach-subject",
                       profile_id="d0_11111111-1111-4111-8111-111111111111", **kwargs)


def test_stage_creates_disabled_invented_bundle_with_verified_snapshot(tmp_path: Path) -> None:
    destination = tmp_path / "journal-coach"
    manifest = stage_fixture(destination)

    assert destination.stat().st_mode & 0o777 == 0o700
    assert manifest["fixture_only"] is True and manifest["enabled"] is False
    assert manifest["production_reads"] is False
    assert manifest["service_installed"] is False and manifest["os_user_created"] is False
    assert manifest["oauth_registered"] is False
    assert set(manifest["source_sha256"]) == {
        "runtime/backend/cloud_mcp_d0.py",
        "runtime/backend/cloud_mcp_journal.py",
        "runtime/backend/journal_coach_snapshot.py",
        "units/tradejournal-journal-coach.service",
        "units/tradejournal-journal-coach.socket",
        "state/approved.json",
        "config/config.json",
    }
    for relative, expected in manifest["source_sha256"].items():
        assert hashlib.sha256((destination / relative).read_bytes()).hexdigest() == expected
        assert (destination / relative).stat().st_mode & 0o777 == 0o600

    config = JournalConfig.model_validate_json((destination / "config/config.json").read_bytes())
    assert config.enabled is False and config.profiles[0].enabled is False
    payload = (destination / "state/approved.json").read_bytes()
    snapshot = load_snapshot(destination / "state/approved.json", config.snapshot_sha256)
    assert hashlib.sha256(payload).hexdigest() == config.snapshot_sha256
    assert snapshot.sample_data is True and snapshot.source == "approved_journal_export"
    assert snapshot.start_day.isoformat() == snapshot.end_day.isoformat() == "2026-01-02"
    assert len(snapshot.trades) == 2
    assert [(row.ticker, row.realized_pnl) for row in snapshot.trades] == [
        ("MU", "-1.250000"), ("NBIS", None)
    ]


def test_stage_refuses_existing_symlink_and_noncanonical_destinations(tmp_path: Path) -> None:
    existing = tmp_path / "existing"
    existing.mkdir()
    sentinel = existing / "keep.txt"
    sentinel.write_text("preserve", encoding="utf-8")
    with pytest.raises(ValueError):
        stage_fixture(existing)
    assert sentinel.read_text(encoding="utf-8") == "preserve"

    linked = tmp_path / "linked"
    linked.symlink_to(existing, target_is_directory=True)
    with pytest.raises(ValueError):
        stage_fixture(linked)
    with pytest.raises(ValueError):
        stage_fixture(Path("relative-destination"))

    symlink_parent = tmp_path / "parent-link"
    symlink_parent.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError):
        stage_fixture(symlink_parent / "new-bundle")


def test_staging_source_symlink_refusal_leaves_destination_absent(tmp_path: Path) -> None:
    source = tmp_path / "repo"
    (source / "backend").mkdir(parents=True)
    (source / "deploy/cloud-mcp-journal").mkdir(parents=True)
    for name in stage.RUNTIME_FILES:
        target = source / "backend" / name
        original = ROOT / "backend" / name
        target.symlink_to(original)
    for name in stage.UNITS:
        (source / "deploy/cloud-mcp-journal" / name).write_text("fixture unit", encoding="utf-8")
    destination = tmp_path / "bundle"
    with pytest.raises(ValueError, match="regular reviewed source files"):
        stage_fixture(destination, source=source)
    assert not destination.exists()


def test_journal_units_keep_service_read_only_and_unix_only() -> None:
    service = (ROOT / "deploy/cloud-mcp-journal/tradejournal-journal-coach.service").read_text()
    socket_unit = (ROOT / "deploy/cloud-mcp-journal/tradejournal-journal-coach.socket").read_text()

    assert "User=tj-journal-coach" in service and "Group=tj-journal-coach" in service
    assert "ExecStart=/opt/tradejournal-journal/runtime/backend/.venv/bin/python" in service
    assert "cloud_mcp_journal.py --config /etc/tradejournal-journal/config.json" in service
    assert "PrivateNetwork=true" in service and "RestrictAddressFamilies=AF_UNIX" in service
    assert "ProtectSystem=strict" in service and "ProtectHome=true" in service
    assert "InaccessiblePaths=" in service and "/opt/tradejournal" in service
    assert "NoNewPrivileges=true" in service and "CapabilityBoundingSet=" in service
    assert "EnvironmentFile=" not in service and "DATABASE_URL" not in service
    assert "ListenStream=/run/tradejournal-journal-coach/mcp.sock" in socket_unit
    assert "SocketGroup=caddy" in socket_unit and "SocketMode=0660" in socket_unit


def test_deployment_workflow_runs_journal_smoke_after_d1() -> None:
    workflow = (ROOT / ".github/workflows/deployment.yml").read_text()
    d1 = "deploy/cloud-mcp-d1/smoke.py"
    journal = "deploy/cloud-mcp-journal/smoke.py"
    assert d1 in workflow and journal in workflow
    assert workflow.index(journal) > workflow.index(d1)
    line = next(line for line in workflow.splitlines() if journal in line)
    assert "GITHUB_ACTIONS=true" in line and "TJ_DISPOSABLE_RUNNER=1" in line


def test_native_smoke_checks_root_and_runner_markers_before_host_probes(monkeypatch) -> None:
    monkeypatch.setattr(native_smoke.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(native_smoke, "run", lambda *args, **kwargs: pytest.fail("host probe ran"))
    with pytest.raises(RuntimeError, match="must run as root"):
        native_smoke.preflight()

    monkeypatch.setattr(native_smoke.os, "geteuid", lambda: 0)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("TJ_DISPOSABLE_RUNNER", raising=False)
    with pytest.raises(RuntimeError, match="explicitly disposable GitHub runner"):
        native_smoke.preflight()


def test_native_smoke_refuses_preexisting_runtime_before_user_probe(tmp_path, monkeypatch) -> None:
    occupied = tmp_path / "runtime"
    occupied.symlink_to(tmp_path / "missing-target")
    assert not occupied.exists() and occupied.is_symlink()
    monkeypatch.setattr(native_smoke, "INSTALL", tmp_path / "install")
    monkeypatch.setattr(native_smoke, "RUNTIME", occupied)
    monkeypatch.setattr(native_smoke.os, "geteuid", lambda: 0)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("TJ_DISPOSABLE_RUNNER", "1")
    monkeypatch.setattr(native_smoke, "run", lambda *args, **kwargs: pytest.fail("host probe ran"))
    with pytest.raises(RuntimeError, match="refusing pre-existing journal smoke paths"):
        native_smoke.preflight()


def test_native_smoke_exercise_requires_its_owned_marker_before_fixture_writes(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(native_smoke.os, "geteuid", lambda: 0)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("TJ_DISPOSABLE_RUNNER", "1")
    monkeypatch.setattr(native_smoke, "OWNER_MARKER", tmp_path / ".native-smoke-ownership")
    with pytest.raises(RuntimeError, match="requires its owned runtime marker"):
        native_smoke.assert_owned_fixture("not-the-marker")
    assert not (tmp_path / "config.json").exists()
    assert not (tmp_path / "approved.json").exists()

