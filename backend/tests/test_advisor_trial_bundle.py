"""Offline causal proof for the optional install-only trial upgrade."""
import io
import json
import os
from pathlib import Path
import shutil
import tarfile
from types import SimpleNamespace

import pytest

from tests import test_advisor_mcp_bundle as base

stage = base.stage
old = base.control
trial = base.load("advisor_trial_stage")
control = base.load("advisor_trial_control")
LEGACY_PREFLIGHT = old.preflight_install


@pytest.fixture(scope="module")
def prepared(tmp_path_factory):
    root = tmp_path_factory.mktemp("trial-preparation")
    wheels = root / "wheels"
    wheels.mkdir()
    (wheels / "offline-fixture.whl").touch()
    archive = root / "release.tar.gz"
    metadata = {"commit": stage.reviewed_git("rev-parse", "HEAD").decode().strip(), "node": "v22.1.0",
        "platform": {"os": "ubuntu", "version": "24.04", "arch": "x86_64", "python": "3.12"}}
    with tarfile.open(archive, "w:gz") as output:
        for name, content in {"release.json": json.dumps(metadata), "frontend/server.js": "// compiled fixture",
                "frontend/.next/server/app/advisor-review/page.js": "// compiled fixture", "bin/node": "fixture executable"}.items():
            entry = tarfile.TarInfo("release/" + name)
            data = content.encode()
            entry.size = len(data)
            output.addfile(entry, io.BytesIO(data))
    bundle = root / "bundle"
    trial.prepare(bundle, archive=archive, archive_sha256=stage.digest(archive), wheels=wheels, guards={})
    return bundle


def host(tmp_path, monkeypatch, prepared):
    calls = base.mock_host(tmp_path, monkeypatch)
    monkeypatch.setattr(old, "preflight_install", lambda bundle: stage.validate(bundle))
    old.install(prepared, approve_install=stage.digest(prepared / "manifest.json"))
    for name, value in (("ROOT", tmp_path / "v2"), ("CONFIG", tmp_path / "v2-config"), ("STATE", tmp_path / "v2-state")):
        monkeypatch.setattr(control, name, value)
    monkeypatch.setattr(control, "RECORD", control.ROOT / "installation.json")
    monkeypatch.setattr(control, "DROPIN", old.UNIT_DIR / (trial.FRONTEND + ".d") / "advisor-trial.conf")
    monkeypatch.setattr(trial, "RUN", str(tmp_path / "v2-run"))
    monkeypatch.setattr(trial, "OWNER_RUN", str(tmp_path / "v2-owner-run"))
    monkeypatch.setattr(control, "OWNER_ENV", tmp_path / "owner.env")
    monkeypatch.setattr(control, "API_ENV", tmp_path / "api.env")
    files = {"old_record_sha256": old.RECORD, "frontend_unit_sha256": old.UNIT_DIR / trial.FRONTEND,
        "owner_env_sha256": control.OWNER_ENV, "api_env_sha256": control.API_ENV}
    for key, path in files.items():
        if key != "old_record_sha256":
            path.write_text("unchanged fixture " + key)
            path.chmod(0o600)
    bundle = tmp_path / "bundle"
    shutil.copytree(prepared, bundle)
    plan = json.loads((bundle / "trial.json").read_text())
    plan["guards"] = {key: stage.digest(path) for key, path in files.items()}
    (bundle / "trial.json").write_text(json.dumps(plan))
    manifest = stage.validate(prepared)
    manifest["inventory"] = stage.inventory(bundle)
    (bundle / "manifest.json").write_text(json.dumps(manifest))
    original_stat = Path.stat
    def root_stat(path, *args, **kwargs):
        fields = list(original_stat(path, *args, **kwargs))
        fields[4] = 0
        return os.stat_result(fields)
    monkeypatch.setattr(Path, "stat", root_stat)
    command = old.run
    def execute(*args, **kwargs):
        result = command(*args, **kwargs)
        if args[0] == "getent" or "cat" in args:
            result.returncode = 2
        result.stdout = b""
        if "--property=FragmentPath" in args:
            unit = args[2]
            path = old.UNIT_DIR / unit
            result.stdout = ("FragmentPath=" + (str(path) if path.exists() else "") + "\nDropInPaths="
                + (str(control.DROPIN) if unit == trial.FRONTEND and control.DROPIN.exists() else "")
                + "\nLoadState=" + ("loaded" if path.exists() else "not-found") + "\n").encode()
        return result
    monkeypatch.setattr(old, "run", execute)
    monkeypatch.setattr(control.platform, "freedesktop_os_release", lambda: {"ID": "ubuntu", "VERSION_ID": "24.04"})
    monkeypatch.setattr(control.platform, "machine", lambda: "x86_64")
    accounts = {name: SimpleNamespace(pw_name=name, pw_uid=uid, pw_gid=gid, pw_shell="/usr/sbin/nologin") for name, uid, gid in
        ((old.ACCOUNT, 300, 280), (old.BACKEND_ACCOUNT, 301, 280), (trial.READER_ACCOUNT, 302, 281), (trial.WEB_ACCOUNT, 303, 282))}
    monkeypatch.setattr(control.pwd, "getpwnam", accounts.__getitem__)
    monkeypatch.setattr(control.pwd, "getpwall", lambda: list(accounts.values()))
    monkeypatch.setattr(control.grp, "getgrnam", lambda name: SimpleNamespace(gr_gid=accounts[name].pw_gid, gr_mem=[]))
    monkeypatch.setattr(control.grp, "getgrall", lambda: [])
    calls.clear()
    return bundle, calls


def test_disabled_private_artifact_and_exact_optional_paths(prepared):
    stage.validate(prepared)
    for name in control.UNITS:
        text = (prepared / "units" / name).read_text()
        assert "[Install]" not in text and "v2-v2" not in text
    text = (prepared / "units/tradejournal-advisor-owner.socket").read_text()
    assert "SocketGroup=tj-advisor-web-owner\n" in text and "SocketGroup=tradejournal\n" not in text
    assert "TJ_ADVISOR_OWNER_ENABLED=false" in (prepared / "config/frontend.env").read_text()
    assert json.loads((prepared / "config/owner.json").read_text())["enabled"] is False
    assert "API_INTERNAL_URL" not in (prepared / "units/frontend.conf").read_text()
    assert "unix//run/tradejournal-advisor-v2/mcp.sock" in (prepared / "proxy/Caddyfile.example").read_text()


def test_install_preserves_old_receipts_and_auth_and_records_independent_uid_gid(prepared, tmp_path, monkeypatch):
    bundle, calls = host(tmp_path, monkeypatch, prepared)
    before = {p: p.read_bytes() for p in (old.RECORD, old.STATE / "fixture.db", old.ROOT / "recovery/request.json", control.OWNER_ENV, control.API_ENV)}
    with pytest.raises(ValueError, match="pre-existing advisor destination"):
        LEGACY_PREFLIGHT(bundle)  # Original causal blocker: no overwrite upgrade.
    record = control.install(bundle, stage.digest(bundle / "manifest.json"))
    assert record["enabled"] is False
    assert record["new_accounts"][trial.READER_ACCOUNT] == {"uid": 302, "gid": 281}
    assert record["new_accounts"][trial.WEB_ACCOUNT] == {"uid": 303, "gid": 282}
    assert all(p.read_bytes() == value for p, value in before.items())
    assert not any(any(word in command for word in ("start", "restart", "enable", "setfacl")) for command in calls)
    assert json.loads((control.CONFIG / "owner/config.json").read_text())["peer_uid"] == 303
    new_ledger = (control.STATE / "fixture.db").read_bytes()
    control.rollback()
    assert all(p.read_bytes() == value for p, value in before.items())
    assert (control.STATE / "fixture.db").read_bytes() == new_ledger
    assert not control.DROPIN.exists()
    old.installed()  # Exact original unit/runtime authority restored.
    assert not any(trial.FRONTEND in command and "stop" in command for command in calls)


@pytest.mark.parametrize("change", ["old-record", "owner-env", "api-env", "owner-unit", "dropin", "destination", "approval"])
def test_drift_and_collision_refuse_before_any_runtime_execution(prepared, tmp_path, monkeypatch, change):
    bundle, calls = host(tmp_path, monkeypatch, prepared)
    if change in {"old-record", "owner-env", "api-env", "owner-unit"}:
        path = {"old-record": old.RECORD, "owner-env": control.OWNER_ENV, "api-env": control.API_ENV,
            "owner-unit": old.UNIT_DIR / trial.FRONTEND}[change]
        path.write_bytes(path.read_bytes() + b" ")
    elif change == "dropin":
        control.DROPIN.parent.mkdir()
    elif change == "destination":
        control.ROOT.mkdir()
    approved = "wrong" if change == "approval" else stage.digest(bundle / "manifest.json")
    with pytest.raises(ValueError):
        control.install(bundle, approved)
    assert not any("venv" in command or "useradd" in command for command in calls)


@pytest.mark.parametrize("phase", ["unit-prefix", "unit-chmod", "unit-replace-before", "unit-replace-after",
    "dropin-prefix", "dropin-chmod", "dropin-replace-before", "dropin-replace-after"])
def test_partial_switch_failure_restores_only_owned_units_and_preserves_data(prepared, tmp_path, monkeypatch, phase):
    bundle, calls = host(tmp_path, monkeypatch, prepared)
    before = {name: (old.UNIT_DIR / name).read_bytes() for name in stage.UNITS}
    copy = control.shutil.copyfile
    chmod = Path.chmod
    replace = control.os.replace
    selected = control.DROPIN if phase.startswith("dropin") else old.UNIT_DIR / stage.UNITS[1]
    fired = False
    def failure():
        nonlocal fired
        fired = True
        raise OSError("Controlled switch failure after actual write")
    def is_temporary(path):
        return Path(path).parent == selected.parent and Path(path).name.startswith("." + selected.name + ".")
    def fail(source, target, **kwargs):
        if not fired and phase.endswith("prefix") and is_temporary(target):
            Path(target).write_bytes(Path(source).read_bytes()[:12])
            failure()
        return copy(source, target, **kwargs)
    def fail_chmod(path, mode, **kwargs):
        result = chmod(path, mode, **kwargs)
        if not fired and phase.endswith("chmod") and is_temporary(path):
            failure()
        return result
    def fail_replace(source, target):
        if not fired and Path(target) == selected and phase.endswith("replace-before"):
            failure()
        result = replace(source, target)
        if not fired and Path(target) == selected and phase.endswith("replace-after"):
            failure()
        return result
    monkeypatch.setattr(control.shutil, "copyfile", fail)
    monkeypatch.setattr(Path, "chmod", fail_chmod)
    monkeypatch.setattr(control.os, "replace", fail_replace)
    with pytest.raises(OSError, match="Controlled"):
        control.install(bundle, stage.digest(bundle / "manifest.json"))
    assert all((old.UNIT_DIR / name).read_bytes() == value for name, value in before.items())
    assert (control.STATE / "fixture.db").read_bytes() == (bundle / "state/fixture.db").read_bytes()
    assert (control.ROOT / "recovery/request.json").is_file()
    assert not control.DROPIN.exists() and not control.DROPIN.parent.exists()
    assert not list(old.UNIT_DIR.glob(".*"))
    old.installed()
    assert len([c for c in calls if "stop" in c]) == 2
    with pytest.raises(ValueError, match="collision"):
        control.install(bundle, stage.digest(bundle / "manifest.json"))


@pytest.mark.parametrize("phase", ["pre-switch", "installed"])
@pytest.mark.parametrize("override", ["runtime", "vendor", "generic", "fragment"])
def test_effective_override_authority_refused(prepared, tmp_path, monkeypatch, phase, override):
    bundle, calls = host(tmp_path, monkeypatch, prepared)
    if phase == "installed":
        control.install(bundle, stage.digest(bundle / "manifest.json"))
    command = old.run
    def drift(*args, **kwargs):
        result = command(*args, **kwargs)
        if "--property=DropInPaths" in args and args[2] == stage.UNITS[1]:
            if override == "fragment":
                result.stdout = result.stdout.replace(str(old.UNIT_DIR / stage.UNITS[1]).encode(), b"/usr/lib/systemd/system/unreviewed.service")
            else:
                path = {"runtime": "/run/systemd/system/" + stage.UNITS[1] + ".d/override.conf",
                    "vendor": "/usr/lib/systemd/system/" + stage.UNITS[1] + ".d/override.conf",
                    "generic": "/run/systemd/system/service.d/override.conf"}[override]
                result.stdout = result.stdout.replace(b"DropInPaths=\n", ("DropInPaths=" + path + "\n").encode())
        return result
    monkeypatch.setattr(old, "run", drift)
    with pytest.raises(ValueError, match="effective systemd"):
        control.installed() if phase == "installed" else control.install(bundle, stage.digest(bundle / "manifest.json"))
    assert not any("start" in command or "restart" in command for command in calls)


@pytest.mark.parametrize("change", ["runtime", "node", "unit", "extra-dropin", "group"])
def test_post_install_drift_refuses_and_stops_all_six_before_rollback(prepared, tmp_path, monkeypatch, change):
    bundle, calls = host(tmp_path, monkeypatch, prepared)
    control.install(bundle, stage.digest(bundle / "manifest.json"))
    if change in {"runtime", "node", "unit", "extra-dropin"}:
        path = {"runtime": control.ROOT / "backend/.venv/lib/dependency.py", "node": control.ROOT / "bin/node",
            "unit": old.UNIT_DIR / trial.OWNER_UNITS[0], "extra-dropin": control.DROPIN.parent / "other.conf"}[change]
        path.write_text("unreviewed drift")
    else:
        monkeypatch.setattr(control.grp, "getgrall", lambda: [SimpleNamespace(gr_name="journal", gr_mem=[trial.WEB_ACCOUNT])])
    calls.clear()
    with pytest.raises(ValueError):
        control.rollback()
    assert calls[0] == ("systemctl", "stop", *[u for u in control.UNITS if u.endswith(".socket")])
    assert calls[1] == ("systemctl", "stop", *[u for u in control.UNITS if u.endswith(".service")])
    assert control.DROPIN.exists()  # Never remove drifted resources.
