"""Offline causal proof for the optional install-only trial upgrade."""
import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
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
    for name, relative in (("KEPT", "previous-runtime"), ("FAILED", "failed-upgrades"), ("INTENT", "upgrade-intent.json"),
            ("LEDGER_BACKUPS", "ledger-backups")):
        monkeypatch.setattr(control, name, control.ROOT / relative)
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
        result.stdout = b"inactive\n" if "--property=ActiveState" in args else b""
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


def newer_bundle(bundle, edit=None):
    """A re-approved copy of the reviewed bundle with one changed runtime file."""
    target = bundle.parent / "newer-bundle"
    shutil.copytree(bundle, target)
    bridge = target / "backend/cloud_mcp_advisor_bridge.py"
    bridge.write_text(bridge.read_text() + "\n# reviewed newer runtime\n")
    if edit:
        edit(target)
    for path in target.rglob("*"):
        path.chmod(0o600 if path.is_file() else 0o700)
    manifest = json.loads((target / "manifest.json").read_text())
    manifest["inventory"] = stage.inventory(target)
    (target / "manifest.json").write_text(json.dumps(manifest))
    return target, stage.digest(target / "manifest.json")


def live_values():
    """Values the operator set after install; upgrade must keep them."""
    config_path = control.CONFIG / "advisor/config.json"
    config = json.loads(config_path.read_text())
    config.update(client_claim="azp", client_id="live-client")
    config["profiles"][0]["subject"] = "auth0|live-advisor"
    control.write_private(config_path, config)
    ledger = sqlite3.connect(control.STATE / "fixture.db")
    ledger.execute("CREATE TABLE saved_receipt_fixture (receipt TEXT)")
    ledger.execute("INSERT INTO saved_receipt_fixture VALUES ('e98582d6')")
    ledger.commit()
    ledger.close()


def preserved_bytes():
    paths = [*control.CONFIG.rglob("*"), control.STATE / "fixture.db", *(control.ROOT / "recovery").rglob("*"),
        *[old.UNIT_DIR / name for name in control.UNITS], control.DROPIN, old.RECORD, old.STATE / "fixture.db"]
    return {path: path.read_bytes() for path in paths if path.is_file()}


RUNTIME_FIELDS = {"manifest_sha256", "source_commit", "release", "runtime_inventory", "previous_runtimes", "schema_revision", "schema_sql"}


def test_upgrade_swaps_only_runtime_and_downgrade_restores_it(prepared, tmp_path, monkeypatch):
    bundle, calls = host(tmp_path, monkeypatch, prepared)
    control.install(bundle, stage.digest(bundle / "manifest.json"))
    live_values()
    first = json.loads(control.RECORD.read_text())
    before = preserved_bytes()
    newer, approved = newer_bundle(bundle)
    calls.clear()
    record = control.upgrade(newer, approved)
    assert record["manifest_sha256"] == approved and record["runtime_inventory"] != first["runtime_inventory"]
    assert "reviewed newer runtime" in (control.ROOT / "backend/cloud_mcp_advisor_bridge.py").read_text()
    assert preserved_bytes() == before  # Config values, ledger receipts, recovery, units, drop-in.
    assert {k: v for k, v in record.items() if k not in RUNTIME_FIELDS} == {k: v for k, v in first.items() if k not in RUNTIME_FIELDS}
    assert [kept["manifest_sha256"] for kept in record["previous_runtimes"]] == [first["manifest_sha256"]]
    assert not control.INTENT.exists() and control.RECORD.stat().st_mode & 0o777 == 0o600
    assert not any(word in command for command in calls for word in ("start", "restart", "enable", "stop", "daemon-reload"))
    assert not any("useradd" in command or "chown" in command for command in calls)

    record = control.downgrade()
    assert record["runtime_inventory"] == first["runtime_inventory"]
    assert record["manifest_sha256"] == first["manifest_sha256"]
    assert "reviewed newer runtime" not in (control.ROOT / "backend/cloud_mcp_advisor_bridge.py").read_text()
    assert [kept["manifest_sha256"] for kept in record["previous_runtimes"]] == [approved]
    assert preserved_bytes() == before
    assert record == {**first, "previous_runtimes": record["previous_runtimes"], "schema_revision": record["schema_revision"],
        "schema_sql": None}
    assert control.upgrade(newer, approved)["manifest_sha256"] == approved  # Re-upgrade builds afresh.
    control.rollback()  # The original side-by-side rollback still works after upgrades.
    assert (control.STATE / "fixture.db").read_bytes() == before[control.STATE / "fixture.db"]


@pytest.mark.parametrize("change", ["approval", "active", "frontend-active", "bridge-activating", "unit", "dropin", "schema", "drift", "same"])
def test_upgrade_refuses_before_any_runtime_change(prepared, tmp_path, monkeypatch, change):
    bundle, calls = host(tmp_path, monkeypatch, prepared)
    control.install(bundle, stage.digest(bundle / "manifest.json"))
    edits = {
        "unit": lambda b: (b / "units" / stage.UNITS[3]).write_text((b / "units" / stage.UNITS[3]).read_text() + "Restart=always\n"),
        "dropin": lambda b: (b / "units/frontend.conf").write_text((b / "units/frontend.conf").read_text() + "User=root\n"),
        "schema": lambda b: [sqlite3.connect(b / "state/fixture.db").execute("UPDATE alembic_version SET version_num='newer'").connection.commit()],
    }
    newer, approved = newer_bundle(bundle, edits.get(change))
    if change == "approval":
        approved = "0" * 64
    elif change == "same":
        newer, approved = bundle, stage.digest(bundle / "manifest.json")
    elif change == "drift":
        (control.ROOT / "backend/.venv/lib/dependency.py").write_text("unreviewed drift")
    elif change in {"active", "frontend-active", "bridge-activating"}:
        unit = {"active": control.UNITS[0], "frontend-active": trial.FRONTEND, "bridge-activating": control.OWNER_BRIDGE[0]}[change]
        command = old.run
        def active(*args, **kwargs):
            result = command(*args, **kwargs)
            if "--property=ActiveState" in args and unit in args:
                result.stdout = b"activating\n" if change == "bridge-activating" else b"active\n"
            return result
        monkeypatch.setattr(old, "run", active)
    record = control.RECORD.read_bytes()
    runtime = {path: path.read_bytes() for path in (control.ROOT / "backend").rglob("*") if path.is_file() and not path.is_symlink()}
    calls.clear()
    reason = {"approval": "Approval", "active": "Stop the six", "frontend-active": "owner frontend", "bridge-activating": "bridge",
        "unit": "changes advisor units", "dropin": "drop-in", "schema": "Ledger schema", "drift": "inventory drift",
        "same": "already the installed"}[change]
    with pytest.raises(ValueError, match=reason):
        control.upgrade(newer, approved)
    assert control.RECORD.read_bytes() == record
    assert {path: path.read_bytes() for path in (control.ROOT / "backend").rglob("*") if path.is_file() and not path.is_symlink()} == runtime
    assert not control.KEPT.exists() and not control.INTENT.exists()
    assert not any("venv" in command for command in calls)


def test_failed_build_restores_recorded_runtime_and_retry_succeeds(prepared, tmp_path, monkeypatch):
    bundle, calls = host(tmp_path, monkeypatch, prepared)
    control.install(bundle, stage.digest(bundle / "manifest.json"))
    first = control.RECORD.read_bytes()
    newer, approved = newer_bundle(bundle)
    command = old.run
    def fail_backend_pip(*args, **kwargs):
        if "pip" in args and str(control.ROOT / "backend") in str(args[0]):
            raise RuntimeError("Controlled offline wheel failure")
        return command(*args, **kwargs)
    monkeypatch.setattr(old, "run", fail_backend_pip)
    with pytest.raises(RuntimeError, match="Controlled"):
        control.upgrade(newer, approved)
    assert control.RECORD.read_bytes() == first and not control.INTENT.exists()
    control.installed()  # Exact recorded runtime is back in place.
    failed = list(control.FAILED.iterdir())
    assert len(failed) == 1 and {p.name for p in failed[0].iterdir()} == {"adapter", "backend"}  # Kept, not deleted.
    assert not list(control.KEPT.iterdir())
    monkeypatch.setattr(old, "run", command)
    assert control.upgrade(newer, approved)["manifest_sha256"] == approved


@pytest.mark.parametrize("phase", ["before-switch", "after-switch"])
def test_interrupted_swap_fails_closed_and_resumes(prepared, tmp_path, monkeypatch, phase):
    bundle, _ = host(tmp_path, monkeypatch, prepared)
    control.install(bundle, stage.digest(bundle / "manifest.json"))
    first = json.loads(control.RECORD.read_text())
    newer, approved = newer_bundle(bundle)
    command, rename, unlink = old.run, Path.rename, Path.unlink
    if phase == "before-switch":
        def fail_pip(*args, **kwargs):
            if "pip" in args:
                raise RuntimeError("Controlled build failure")
            return command(*args, **kwargs)
        def fail_restore(path, target):
            if path.parent.parent == control.KEPT and Path(target).parent == control.ROOT:
                raise OSError("Controlled restore interruption")
            return rename(path, target)
        monkeypatch.setattr(old, "run", fail_pip)
        monkeypatch.setattr(Path, "rename", fail_restore)
    else:
        def fail_clear(path, *args, **kwargs):
            if path == control.INTENT:
                raise OSError("Controlled interruption after record switch")
            return unlink(path, *args, **kwargs)
        monkeypatch.setattr(Path, "unlink", fail_clear)
    with pytest.raises((OSError, RuntimeError)):
        control.upgrade(newer, approved)
    assert control.INTENT.exists()
    with pytest.raises(ValueError, match="journal pending"):
        control.installed()  # Preflight, rollback and key upkeep all refuse until resume.
    if phase == "before-switch":
        assert json.loads(control.RECORD.read_text()) == first
    monkeypatch.setattr(old, "run", command)
    monkeypatch.setattr(Path, "rename", rename)
    monkeypatch.setattr(Path, "unlink", unlink)
    control.resume()
    assert not control.INTENT.exists()
    record = control.installed()
    assert record["manifest_sha256"] == (first["manifest_sha256"] if phase == "before-switch" else approved)
    if phase == "before-switch":
        assert control.upgrade(newer, approved)["manifest_sha256"] == approved


def test_downgrade_refuses_changed_retained_runtime(prepared, tmp_path, monkeypatch):
    bundle, _ = host(tmp_path, monkeypatch, prepared)
    control.install(bundle, stage.digest(bundle / "manifest.json"))
    with pytest.raises(ValueError, match="No retained"):
        control.downgrade()
    newer, approved = newer_bundle(bundle)
    record = control.upgrade(newer, approved)
    slot = control.KEPT / record["previous_runtimes"][0]["slot"]
    (slot / "backend/cloud_mcp_advisor_bridge.py").write_text("tampered")
    before = control.RECORD.read_bytes()
    with pytest.raises(ValueError, match="Retained previous runtime changed"):
        control.downgrade()
    assert control.RECORD.read_bytes() == before and not control.INTENT.exists()
    control.installed()


def alembic(*args, bundle=None, database=None):
    """The installed runtime's real migrations against only a disposable ledger."""
    url = "sqlite:///" + str(database or control.STATE / "fixture.db")
    subprocess.run([sys.executable, "-B", "-m", "alembic", *args], cwd=(bundle or control.ROOT) / "backend", check=True, capture_output=True,
        env={"PATH": os.environ["PATH"], "PYTHON_DOTENV_DISABLED": "1", "DATABASE_URL": url, "MIGRATION_DATABASE_URL": url})


def table_addition_bundle(bundle):
    """Pin successful preservation tests to day_journal_entry's table addition.

    The trial guard deliberately rejects alterations of existing tables, so the
    latest application migration is not necessarily an allowed trial migration.
    """
    from alembic.script import ScriptDirectory

    def pin(target):
        head = "6b2f9d4a1c73"
        alembic("downgrade", head, bundle=target, database=target / "state/fixture.db")
        keep = control.migration_ancestors(target, [head])
        scripts = list(ScriptDirectory(str(target / "backend/alembic")).walk_revisions())
        for script in scripts:
            if script.revision not in keep:
                Path(script.path).unlink()
    return newer_bundle(bundle, edit=pin)


def behind_ledger(prepared, tmp_path, monkeypatch, revision="-1"):
    """An install whose ledger predates the newest migration, like the #251 ledger."""
    bundle, calls = host(tmp_path, monkeypatch, prepared)
    control.install(bundle, stage.digest(bundle / "manifest.json"))
    alembic("downgrade", revision)
    live_values()
    monkeypatch.setattr(control, "run_alembic", alembic)
    return bundle, calls


def test_upgrade_accepts_older_ledger_and_separate_migration_keeps_receipts(prepared, tmp_path, monkeypatch):
    bundle, calls = behind_ledger(prepared, tmp_path, monkeypatch, revision="d4f1a7c3e9b2")
    ledger = control.STATE / "fixture.db"
    old_revision = control.ledger_revision(ledger)
    newer, approved = table_addition_bundle(bundle)
    head = control.ledger_revision(newer / "state/fixture.db")
    assert old_revision != head
    record = control.upgrade(newer, approved)
    assert record["schema_revision"] == head and control.ledger_revision(ledger) == old_revision  # Not migrated.
    before_bytes, before = ledger.read_bytes(), control.ledger_content(ledger)
    preserved = {path: value for path, value in preserved_bytes().items() if path != ledger}
    calls.clear()
    record = control.migrate_ledger()
    assert control.ledger_revision(ledger) == head
    after = control.ledger_content(ledger)
    assert all(after["rows"][name] == digest for name, digest in before["rows"].items())  # Receipts untouched.
    assert set(after["schema"]) - set(before["schema"])  # Only additions.
    migration = record["ledger_migrations"][-1]
    assert migration["from"] == old_revision and migration["to"] == head
    assert Path(migration["backup"]).read_bytes() == before_bytes and Path(migration["backup"]).stat().st_mode & 0o777 == 0o600
    assert {path: value for path, value in preserved_bytes().items() if path != ledger} == preserved
    assert not any(word in command for command in calls for word in ("start", "restart", "enable"))
    with pytest.raises(ValueError, match="already matches"):
        control.migrate_ledger()
    with pytest.raises(ValueError, match="migrated past"):
        control.downgrade()  # The older runtime would refuse the newer schema.


def test_failed_or_destructive_migration_restores_ledger_bytes(prepared, tmp_path, monkeypatch):
    bundle, _ = behind_ledger(prepared, tmp_path, monkeypatch, revision="d4f1a7c3e9b2")
    newer, approved = table_addition_bundle(bundle)
    control.upgrade(newer, approved)
    ledger = control.STATE / "fixture.db"
    original = ledger.read_bytes()
    def destructive(*args):
        alembic(*args)
        connection = sqlite3.connect(ledger)
        connection.execute("DELETE FROM saved_receipt_fixture")
        connection.commit()
        connection.close()
    monkeypatch.setattr(control, "run_alembic", destructive)
    with pytest.raises(ValueError, match="changed existing ledger content"):
        control.migrate_ledger()
    assert ledger.read_bytes() == original
    record = control.installed()
    assert "ledger_migrations" not in record
    monkeypatch.setattr(control, "run_alembic", alembic)
    assert control.migrate_ledger()["ledger_migrations"][-1]["to"] == record["schema_revision"]


def test_column_migration_is_refused_and_restores_existing_ledger(prepared, tmp_path, monkeypatch):
    bundle, _ = behind_ledger(prepared, tmp_path, monkeypatch, revision="6b2f9d4a1c73")
    newer, approved = newer_bundle(bundle)
    control.upgrade(newer, approved)
    ledger = control.STATE / "fixture.db"
    before, record = ledger.read_bytes(), control.RECORD.read_bytes()
    with pytest.raises(ValueError, match="changed existing ledger content"):
        control.migrate_ledger()
    assert ledger.read_bytes() == before and control.RECORD.read_bytes() == record
    assert "ledger_migrations" not in control.installed()


def test_native_smoke_upgrade_path_preserves_guard_and_receipts(prepared, tmp_path, monkeypatch):
    """Exercise the real smoke migration branch on disposable ledgers."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("trial_smoke_fixture", base.REPO / "deploy/cloud-mcp-advisor/trial_smoke.py")
    smoke = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(smoke)
    monkeypatch.setattr(smoke, "control", control)
    monkeypatch.setattr(smoke, "old", old)
    monkeypatch.setattr(smoke, "trial", trial)
    monkeypatch.setattr(smoke, "staging", stage)
    bundle, calls = host(tmp_path, monkeypatch, prepared)
    control.install(bundle, stage.digest(bundle / "manifest.json"))
    live_values()
    monkeypatch.setattr(control, "run_alembic", alembic)
    scratch = tmp_path / "smoke"
    scratch.mkdir()
    # Keep the installed fixture's unit paths while supplying a distinct runtime.
    def prepare(target, **kwargs):
        staged, _ = newer_bundle(bundle)
        staged.rename(target)
    monkeypatch.setattr(trial, "prepare", prepare)
    calls.clear()

    def run(*args, **kwargs):
        if args[1:4] == ("-B", "-m", "alembic"):
            target = Path(kwargs["cwd"]).parent
            assert target == scratch / "trial-table-addition"
            return alembic(*args[4:], bundle=target, database=target / "state/fixture.db")
        assert args[0] == "systemctl"
        result = old.run(*args, **kwargs)
        if args[1] == "is-active":
            result.returncode = 3
        return result

    smoke.upgraded_runtime(prepared.parent / "release.tar.gz", scratch, run)
    record = control.installed()
    assert record["schema_revision"] == ["f3b7d1e9a2c4"]
    assert control.ledger_revision(control.STATE / "fixture.db") == ["6b2f9d4a1c73"]
    assert len(record["ledger_migrations"]) == 1  # Refusal never records success.
    with sqlite3.connect(control.STATE / "fixture.db") as db:
        assert db.execute("SELECT receipt FROM saved_receipt_fixture").fetchall() == [("e98582d6",)]
    assert not any(word in command for command in calls for word in ("start", "restart", "enable"))


def test_partial_earlier_migration_is_refused_not_recorded(prepared, tmp_path, monkeypatch):
    """A killed run can leave the new table without its index; a rerun must not accept that."""
    # This interrupted-migration fixture specifically predates market_context_item.
    bundle, _ = behind_ledger(prepared, tmp_path, monkeypatch, revision="a7c3e9f1b2d4")
    newer, approved = newer_bundle(bundle)
    control.upgrade(newer, approved)
    ledger = control.STATE / "fixture.db"
    connection = sqlite3.connect(ledger)
    connection.execute("CREATE TABLE market_context_item (id CHAR(32) NOT NULL, PRIMARY KEY (id))")
    connection.commit()
    connection.close()
    partial = ledger.read_bytes()
    with pytest.raises(ValueError, match="did not reach the runtime schema") as refused:
        control.migrate_ledger()
    assert any("Pre-migration ledger copy" in note for note in refused.value.__notes__)
    assert ledger.read_bytes() == partial
    assert "ledger_migrations" not in control.installed()


def test_migration_ancestry_reads_every_repository_script():
    scripts = list((base.REPO / "backend/alembic/versions").glob("*.py"))
    from app.schema import alembic_heads
    assert len(control.migration_ancestors(base.REPO, alembic_heads())) == len(scripts)
