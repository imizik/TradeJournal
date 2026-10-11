"""Disabled bundle/control proof; never operates host users, systemd or ingress."""
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace
import uuid

import pytest
from sqlmodel import Session, create_engine

from app.engine import advisor_shadow as service
from app.models import PracticeAgentCall
from app.schema import ensure_current

REPO = Path(__file__).resolve().parents[2]


def load(name):
    spec = importlib.util.spec_from_file_location(name, REPO / "deploy" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


stage = load("advisor_mcp_stage")
control = load("advisor_mcp_control")


@pytest.fixture(scope="module")
def prepared(tmp_path_factory):
    destination = tmp_path_factory.mktemp("advisor-bundle") / "disabled"
    stage.stage(destination)
    return destination


def test_private_disabled_migrated_invented_single_binding_no_credentials(prepared):
    manifest = stage.validate(prepared)
    assert manifest["fixture_only"] and not manifest["enabled"]
    config = json.loads((prepared / "config/config.json").read_text())
    request = json.loads((prepared / "recovery/request.json").read_text())
    assert not config["enabled"] and not config["profiles"][0]["enabled"]
    assert config["profiles"][0]["packet_sha256"] == request["packet_sha256"]
    assert config["profiles"][0]["request_sha256"] == request["request_sha256"]
    assert request["transport"] == "manual-paste" and request["demo_only"]
    engine = create_engine("sqlite:///" + str(prepared / "state/fixture.db"))
    ensure_current(engine)
    with Session(engine) as db:
        call = db.get(PracticeAgentCall, uuid.UUID(request["assignment_id"]))
        config = json.loads(call.config_json)
        assert not config["enabled"] and config["advisor"]["receipt"] is None
        assert service.owner_view(db, call.run_id)["advisor"]["export"] == request
    engine.dispose()
    assert set(p.name for p in (prepared / "adapter").iterdir()) == set(stage.ADAPTER_FILES)
    assert not list(prepared.rglob("*.timer")) and not list(prepared.rglob("*.env"))
    assert json.loads((prepared / "config/public-keys.json").read_text())["expires_at"] == 0


@pytest.mark.parametrize("change", ["bytes", "mode", "extra", "missing", "symlink", "manifest_path"])
def test_inventory_mode_path_tampering_refuses(prepared, tmp_path, change):
    copied = tmp_path / "copy"
    shutil.copytree(prepared, copied)
    if change == "bytes":
        (copied / "config/config.json").write_text("{}")
    elif change == "mode":
        (copied / "state/fixture.db").chmod(0o644)
    elif change == "extra":
        (copied / "unexpected").touch(mode=0o600)
    elif change == "missing":
        (copied / "recovery/request.json").unlink()
    elif change == "symlink":
        path = copied / "recovery/request.json"
        path.unlink()
        path.symlink_to(prepared / "recovery/request.json")
    else:
        path = copied / "manifest.json"
        path.unlink()
        path.symlink_to(prepared / "manifest.json")
    with pytest.raises(ValueError):
        stage.validate(copied)


def test_collision_and_partial_staging_failure_preserve_prior_evidence(prepared, tmp_path, monkeypatch):
    original = stage.digest(prepared / "state/fixture.db")
    with pytest.raises(ValueError):
        stage.stage(prepared)
    assert stage.digest(prepared / "state/fixture.db") == original
    def fail(*args, **kwargs):
        raise subprocess.CalledProcessError(1, "offline fixture migration")
    monkeypatch.setattr(stage.subprocess, "run", fail)
    path = tmp_path / "failed"
    with pytest.raises(subprocess.CalledProcessError):
        stage.stage(path)
    assert not path.exists()


def test_templates_exact_identity_mounts_routes_limits_and_dormant_release():
    directory = REPO / "deploy/cloud-mcp-advisor"
    for name in stage.UNITS:
        text = (directory / name).read_text()
        assert "[Install]" not in text and "WantedBy=" not in text and "EnvironmentFile=" not in text
    adapter = (directory / "tradejournal-advisor-mcp.service").read_text()
    backend = (directory / "tradejournal-advisor-backend.service").read_text()
    for text in (adapter, backend):
        assert "RestrictAddressFamilies=AF_UNIX" in text and "PrivateNetwork=true" in text
        assert "TemporaryFileSystem=/etc:ro /var:ro /opt:ro /run:ro" in text
        assert "User=tj-advisor" in text and "CapabilityBoundingSet=\n" in text
    assert "User=tj-advisor-backend\n" in backend
    assert "ReadWritePaths=/var/lib/tradejournal-advisor" in backend
    assert "/var/lib/tradejournal-advisor" not in adapter
    assert "SocketGroup=caddy" in (directory / "tradejournal-advisor-mcp.socket").read_text()
    assert "SocketGroup=tj-advisor" in (directory / "tradejournal-advisor-backend.socket").read_text()
    proxy = (directory / "Caddyfile.example").read_text()
    assert "path /advisor/mcp\n" in proxy and "path /.well-known/oauth-protected-resource/advisor/mcp\n" in proxy
    assert "max_size 64KB" in proxy and "respond 404" in proxy and "* /" not in proxy
    # Normal release copies dormant source; its install/activate controller does
    # not install these units or publish the proxy. This must remain separate.
    normal = (REPO / "deploy/control.py").read_text()
    assert "advisor" not in normal


def mock_host(tmp_path, monkeypatch):
    for name, relative in (("ROOT", "runtime"), ("CONFIG", "config"), ("STATE", "state"), ("RUN", "run"), ("UNIT_DIR", "units")):
        monkeypatch.setattr(control, name, tmp_path / relative)
    control.UNIT_DIR.mkdir()
    monkeypatch.setattr(control, "RECORD", control.ROOT / "installation.json")
    monkeypatch.setattr(control, "root_only", lambda: None)
    calls = []
    def command(*args, check=True):
        calls.append(tuple(map(str, args)))
        code = 3 if "is-active" in args else 0
        return SimpleNamespace(returncode=code)
    monkeypatch.setattr(control, "run", command)
    return calls


def test_stop_attempts_both_socket_and_process_groups_even_if_first_fails(tmp_path, monkeypatch):
    calls = mock_host(tmp_path, monkeypatch)
    command = control.run
    def fail_sockets(*args, **kwargs):
        result = command(*args, **kwargs)
        if "stop" in args and any(str(a).endswith(".socket") for a in args):
            result.returncode = 1
        return result
    monkeypatch.setattr(control, "run", fail_sockets)
    with pytest.raises(RuntimeError, match="both groups"):
        control.stop()
    assert calls[0] == ("systemctl", "stop", *control.SOCKETS)
    assert calls[1] == ("systemctl", "stop", *control.SERVICES)


def test_install_inert_partial_cleanup_and_receipt_preserving_rollback(prepared, tmp_path, monkeypatch):
    calls = mock_host(tmp_path, monkeypatch)
    monkeypatch.setattr(control, "preflight_install", lambda bundle: stage.validate(bundle))
    with pytest.raises(ValueError, match="Approval"):
        control.install(prepared, approve_install="wrong")
    assert not control.ROOT.exists()
    record = control.install(prepared, approve_install=stage.digest(prepared / "manifest.json"))
    assert not any("start" in c or "enable" in c for c in calls)
    ledger = stage.digest(control.STATE / "fixture.db")
    monkeypatch.setattr(control, "installed", lambda **kwargs: record)
    control.rollback()
    assert stage.digest(control.STATE / "fixture.db") == ledger
    assert (control.ROOT / "recovery/request.json").read_bytes() == (prepared / "recovery/request.json").read_bytes()
    assert not any((control.UNIT_DIR / u).exists() for u in control.UNITS)


def test_failed_install_removes_only_own_units_keeps_fixture(prepared, tmp_path, monkeypatch):
    calls = mock_host(tmp_path, monkeypatch)
    monkeypatch.setattr(control, "preflight_install", lambda bundle: stage.validate(bundle))
    original = control.shutil.copyfile
    def fail(source, target, **kwargs):
        if str(target).endswith("tradejournal-advisor-mcp.socket"):
            raise OSError("controlled partial copy failure")
        return original(source, target, **kwargs)
    monkeypatch.setattr(control.shutil, "copyfile", fail)
    with pytest.raises(OSError):
        control.install(prepared, approve_install=stage.digest(prepared / "manifest.json"))
    assert (control.STATE / "fixture.db").read_bytes() == (prepared / "state/fixture.db").read_bytes()
    assert not any((control.UNIT_DIR / u).exists() for u in control.UNITS)
    assert any("stop" in c for c in calls) and not any("start" in c for c in calls)


def test_failed_activation_stops_both_pairs_and_wrong_approval_never_starts(tmp_path, monkeypatch):
    calls = mock_host(tmp_path, monkeypatch)
    monkeypatch.setattr(control, "installed", lambda: {})
    identity = {"config_sha256": "fixture"}
    monkeypatch.setattr(control, "activation_identity", lambda: identity)
    with pytest.raises(ValueError, match="Activation approval"):
        control.activate(approve_activation="wrong")
    assert not calls
    import hashlib
    approved = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    command = control.run
    def fail(*args, **kwargs):
        if args[:2] == ("systemctl", "start") and any(str(a).endswith(".service") for a in args):
            command(*args, **kwargs)
            raise RuntimeError("controlled service startup failure")
        return command(*args, **kwargs)
    monkeypatch.setattr(control, "run", fail)
    with pytest.raises(RuntimeError, match="startup failure"):
        control.activate(approve_activation=approved)
    assert ("systemctl", "stop", *control.SOCKETS) in calls
    assert ("systemctl", "stop", *control.SERVICES) in calls
