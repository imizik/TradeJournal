"""Disabled bundle/control proof; never operates host users, systemd or ingress."""
import importlib.util
import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
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


def test_git_trust_is_exact_checkout_command_only_and_admin_environment_is_clean(monkeypatch):
    seen = []
    def git(command, **kwargs):
        seen.append((command, kwargs))
        return b"verified commit"
    monkeypatch.setattr(stage.subprocess, "check_output", git)
    stage.reviewed_git("rev-parse", "HEAD")
    assert seen == [(["git", "-c", f"safe.directory={stage.SOURCE}", "rev-parse", "HEAD"], {"cwd": stage.SOURCE})]
    def execute(command, **kwargs):
        assert kwargs["env"] == {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin",
            "PYTHON_DOTENV_DISABLED": "1", "PYTHONDONTWRITEBYTECODE": "1"}
        assert "ANTHROPIC_API_KEY" not in kwargs["env"] and "SUDO_UID" not in kwargs["env"]
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(control.subprocess, "run", execute)
    control.run("groupadd", "--system", "fixture-name-never-executed")


def test_new_verified_wheel_modes_normalized_before_inventory(prepared, tmp_path, monkeypatch):
    mock_host(tmp_path, monkeypatch)
    monkeypatch.setattr(control, "preflight_install", lambda bundle: stage.validate(bundle))
    command = control.run
    def wheel_modes(*args, **kwargs):
        result = command(*args, **kwargs)
        if "venv" in args:
            venv = Path(args[-1])
            (venv / "lib").chmod(0o775)
            (venv / "lib/dependency.py").chmod(0o664)
            (venv / "bin/wheel-tool").write_text("verified entry point fixture")
            (venv / "bin/wheel-tool").chmod(0o775)
        return result
    monkeypatch.setattr(control, "run", wheel_modes)
    control.install(prepared, approve_install=stage.digest(prepared / "manifest.json"))
    for role in ("adapter", "backend"):
        tree = control.ROOT / role
        assert (tree / ".venv/lib").stat().st_mode & 0o777 == 0o755
        assert (tree / ".venv/lib/dependency.py").stat().st_mode & 0o777 == 0o644
        assert (tree / ".venv/bin/wheel-tool").stat().st_mode & 0o777 == 0o755
        assert (tree / ".venv/bin/python").is_symlink()
    assert (tmp_path / "host-python").stat().st_mode & 0o777 == 0o755
    with pytest.raises(ValueError, match="existing recorded runtime"):
        control.normalize_new_runtime("backend")


def test_clean_child_factory_preserves_recorded_empty_import_directories(prepared, tmp_path, monkeypatch):
    mock_host(tmp_path, monkeypatch)
    monkeypatch.setattr(control, "preflight_install", lambda bundle: stage.validate(bundle))
    control.install(prepared, approve_install=stage.digest(prepared / "manifest.json"))
    config = json.loads((control.CONFIG / "config.json").read_text())
    config.update(enabled=True, issuer_url="https://identity.fixture.invalid/", jwks_url="https://identity.fixture.invalid/keys",
        resource_url="https://advisor.fixture.invalid/advisor/mcp", client_id="offline-factory-fixture",
        backend_socket=str(control.RUN / "backend.sock"), jwks_file=str(control.CONFIG / "public-keys.json"))
    config["profiles"][0].update(enabled=True, subject="offline-factory-fixture")
    (control.CONFIG / "config.json").write_text(json.dumps(config))
    from cryptography.hazmat.primitives.asymmetric import rsa
    numbers = rsa.generate_private_key(public_exponent=65537, key_size=2048).public_key().public_numbers()
    def b64(number):
        return base64.urlsafe_b64encode(number.to_bytes((number.bit_length() + 7) // 8, "big")).rstrip(b"=").decode()
    now = int(time.time())
    (control.CONFIG / "public-keys.json").write_text(json.dumps({"issuer_url": config["issuer_url"], "jwks_url": config["jwks_url"],
        "fetched_at": now, "expires_at": now + 3600, "keys": [{"kid": "fixture", "kty": "RSA", "alg": "RS256", "use": "sig", "n": b64(numbers.n), "e": b64(numbers.e)}]}))
    database = control.STATE / "fixture.db"
    engine = create_engine("sqlite:///" + str(database))
    with Session(engine) as db:
        service.set_enabled(db, uuid.UUID(config["profiles"][0]["assignment_id"]), True)
    engine.dispose()
    before = control.runtime_inventory()
    # Fresh subprocess actually imports the copied source, not pytest's already
    # imported engine modules. Existing project deps are used, no pip/listener.
    script = '''import os,sys,socket,ssl
os.umask(0)
original_socket=socket.socket
class OfflineSocket(original_socket):
    def __init__(self,family=socket.AF_INET,*args,**kwargs):
        assert family not in (socket.AF_INET,socket.AF_INET6),"offline factory attempted IP"
        super().__init__(family,*args,**kwargs)
socket.socket=OfflineSocket
from cloud_mcp_advisor_common import read_config
from cloud_mcp_d0 import local_keys
from cloud_mcp_advisor_bridge import create_app
local_keys(read_config(sys.argv[1]))
create_app(sys.argv[1],sys.argv[2])
print("clean copied-source factory passed without IP/credentials/listener")
'''
    result = subprocess.run([sys.executable, "-B", "-c", script, str(control.CONFIG / "config.json"), str(database)],
        cwd=control.ROOT / "backend", env={"PATH": "/usr/bin:/bin", "PYTHON_DOTENV_DISABLED": "1", "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert control.runtime_inventory() == before
    control.installed()
    data = control.ROOT / "backend/data"
    assert {p.name for p in data.iterdir()} == {"alpaca_cache"}
    assert list((data / "alpaca_cache").iterdir()) == []
    assert not (control.ROOT / "adapter/data").exists()


def test_factory_mutation_refuses_before_preflight_returns_approval(prepared, tmp_path, monkeypatch):
    calls = mock_host(tmp_path, monkeypatch)
    monkeypatch.setattr(control, "preflight_install", lambda bundle: stage.validate(bundle))
    control.install(prepared, approve_install=stage.digest(prepared / "manifest.json"))
    config = json.loads((control.CONFIG / "config.json").read_text())
    config.update(enabled=True, resource_url="https://advisor.fixture.invalid/advisor/mcp",
        issuer_url="https://identity.fixture.invalid/", client_id="approved-fixture",
        backend_socket=str(control.RUN / "backend.sock"), jwks_file=str(control.CONFIG / "public-keys.json"))
    config["profiles"][0].update(enabled=True, subject="approved-fixture")
    (control.CONFIG / "config.json").write_text(json.dumps(config))
    invoked = []
    def mutating_factory(*args, **kwargs):
        invoked.append(args)
        (control.ROOT / "backend/unexpected-import.py").write_text("unexpected executable import output")
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(control.subprocess, "run", mutating_factory)
    with pytest.raises(ValueError, match="runtime inventory changed"):
        control.activation_identity()
    assert len(invoked) == 1 and not any("start" in command for command in calls)


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
    original_stat = Path.stat
    original_lstat = Path.lstat
    def owned(value):
        fields = list(value)
        fields[4] = 0
        return os.stat_result(fields)
    def root_stat(path, *args, **kwargs):
        value = original_stat(path, *args, **kwargs)
        return owned(value) if path.is_relative_to(tmp_path) else value
    def root_lstat(path, *args, **kwargs):
        value = original_lstat(path, *args, **kwargs)
        return owned(value) if path.is_relative_to(tmp_path) else value
    monkeypatch.setattr(Path, "stat", root_stat)
    monkeypatch.setattr(Path, "lstat", root_lstat)
    calls = []
    def command(*args, check=True):
        calls.append(tuple(map(str, args)))
        if "venv" in args:
            venv = Path(args[-1])
            (venv / "bin").mkdir(parents=True)
            (venv / "lib").mkdir()
            interpreter = tmp_path / "host-python"
            if not interpreter.exists():
                interpreter.write_text("verified executable fixture")
                interpreter.chmod(0o755)
            (venv / "bin/python").symlink_to(interpreter)
            (venv / "lib/dependency.py").write_text("verified dependency fixture")
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


@pytest.mark.parametrize("change", ["dependency", "added_import", "interpreter", "symlink", "bytecode", "mode"])
def test_installed_runtime_mutation_refuses_before_interpreter_or_service(prepared, tmp_path, monkeypatch, change):
    calls = mock_host(tmp_path, monkeypatch)
    monkeypatch.setattr(control, "preflight_install", lambda bundle: stage.validate(bundle))
    control.install(prepared, approve_install=stage.digest(prepared / "manifest.json"))
    config = json.loads((control.CONFIG / "config.json").read_text())
    config.update(enabled=True, resource_url="https://advisor.fixture.invalid/advisor/mcp",
        issuer_url="https://identity.fixture.invalid/", client_id="approved-fixture",
        backend_socket=str(control.RUN / "backend.sock"), jwks_file=str(control.CONFIG / "public-keys.json"))
    config["profiles"][0].update(enabled=True, subject="approved-fixture")
    (control.CONFIG / "config.json").write_text(json.dumps(config))
    invoked = []
    def interpreter(*args, **kwargs):
        invoked.append(args)
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(control.subprocess, "run", interpreter)
    control.installed()
    original_identity = control.activation_identity()
    original_approval = __import__("hashlib").sha256(json.dumps(original_identity, sort_keys=True).encode()).hexdigest()
    invoked.clear()
    calls.clear()
    venv = control.ROOT / "backend/.venv"
    if change == "dependency":
        (venv / "lib/dependency.py").write_text("altered importable dependency")
    elif change == "added_import":
        (venv / "lib/new_import.pth").write_text("import unwanted_fixture_module")
    elif change == "interpreter":
        (tmp_path / "host-python").write_text("altered external executable")
    elif change == "symlink":
        (venv / "other").write_text("alternate executable")
        (venv / "bin/python").unlink()
        (venv / "bin/python").symlink_to("../other")
    elif change == "bytecode":
        (venv / "lib/__pycache__").mkdir()
        (venv / "lib/__pycache__/dependency.cpython-312.pyc").write_bytes(b"altered compiled import")
    else:
        (venv / "lib/dependency.py").chmod(0o666)
    with pytest.raises(ValueError, match="runtime"):
        control.activation_identity()  # Public preflight entry must validate first.
    with pytest.raises(ValueError, match="runtime"):
        control.activate(approve_activation=original_approval)
    assert not invoked and not any("start" in c for c in calls)
