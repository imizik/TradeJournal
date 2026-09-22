"""Destructive deployment operations are exercised only against tmp_path/fakes.

Native systemd and the packaged application have a separate Ubuntu CI smoke.
"""

import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tarfile
from types import SimpleNamespace

import pytest


def load(name):
    path = Path(__file__).resolve().parents[2] / "deploy" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"deployment_{name}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def control(tmp_path, monkeypatch):
    module = load("control")
    monkeypatch.setattr(module, "ROOT", tmp_path / "opt")
    (module.ROOT / "releases").mkdir(parents=True)
    return module


def test_schema_mismatch_refuses_before_stopping_services(control, monkeypatch):
    old = control.release_path("old")
    old.mkdir()
    control.atomic_link(old, control.ROOT / "current")
    calls = []
    monkeypatch.setattr(control, "stop_services", lambda: calls.append("stop"))

    def incompatible(*args):
        raise RuntimeError("Database is ahead of this code")

    monkeypatch.setattr(control, "database", incompatible)
    with pytest.raises(RuntimeError, match="ahead"):
        control.activate(control.release_path("new"), "scratch")
    assert control.current() == old
    assert calls == []


def test_failed_activation_restores_previous_release(control, monkeypatch):
    old, new = [control.release_path(name) for name in ("old", "new")]
    old.mkdir()
    new.mkdir()
    control.atomic_link(old, control.ROOT / "current")
    events = []
    monkeypatch.setattr(control, "database", lambda release, *_: events.append(("check", release.name)))
    monkeypatch.setattr(control, "stop_services", lambda: events.append(("stop", "")))

    def start(release, _identity):
        events.append(("start", release.name))
        if release == new:
            raise RuntimeError("bad frontend")

    monkeypatch.setattr(control, "start_services", start)
    with pytest.raises(RuntimeError, match="bad frontend"):
        control.activate(new, "scratch")
    assert control.current() == old
    assert events == [("check", "new"), ("stop", ""), ("start", "new"), ("stop", ""), ("check", "old"), ("start", "old")]


def test_success_records_reversible_release_pair(control, monkeypatch):
    old, new = [control.release_path(name) for name in ("old", "new")]
    old.mkdir()
    new.mkdir()
    control.atomic_link(old, control.ROOT / "current")
    monkeypatch.setattr(control, "database", lambda *_: None)
    monkeypatch.setattr(control, "stop_services", lambda: None)
    monkeypatch.setattr(control, "start_services", lambda *_: None)
    control.activate(new, "scratch")
    assert (control.current(), control.current("previous")) == (new, old)
    control.activate(control.current("previous"), "scratch")
    assert (control.current(), control.current("previous")) == (old, new)


def test_checksum_failure_does_not_extract(control, tmp_path):
    archive = tmp_path / "release.tar.gz"
    archive.write_bytes(b"not an archive")
    with pytest.raises(ValueError, match="checksum"):
        control.install(archive, "0" * 64)
    assert list((control.ROOT / "releases").iterdir()) == []


def test_archive_traversal_is_rejected_and_partial_release_removed(control, tmp_path, monkeypatch):
    archive = tmp_path / "release.tar"
    with tarfile.open(archive, "w") as bundle:
        for name, content in [("new/release.json", json.dumps({"release_id": "new"})), ("new/../../../outside", "unsafe")]:
            info = tarfile.TarInfo(name)
            data = content.encode()
            info.size = len(data)
            bundle.addfile(info, io.BytesIO(data))
    monkeypatch.setattr(control, "validate_platform", lambda _: None)
    with pytest.raises(tarfile.FilterError):
        control.install(archive, hashlib.sha256(archive.read_bytes()).hexdigest())
    assert not (tmp_path / "outside").exists()
    assert not control.release_path("new").exists()


def test_database_owner_must_match_routing_parameters():
    target = load("database").target
    assert target("postgresql+psycopg://app:secret@db/journal") == target("postgresql+psycopg://owner:other@db:5432/journal")
    assert target("postgresql+psycopg://app@db/journal") != target("postgresql+psycopg://owner@db/journal?host=other")


def test_database_helper_resets_login_environment_before_dropping_privileges(monkeypatch):
    database = load("database")
    account = SimpleNamespace(pw_name="tradejournal", pw_dir="/var/lib/tradejournal", pw_uid=123, pw_gid=456)
    events = []
    monkeypatch.setattr(database.pwd, "getpwnam", lambda _: account)
    monkeypatch.setattr(database.os, "geteuid", lambda: 0)
    monkeypatch.setattr(database.os, "initgroups", lambda name, gid: events.append(("groups", name, gid)))
    monkeypatch.setattr(database.os, "setgid", lambda gid: events.append(("gid", gid)))
    monkeypatch.setattr(database.os, "setuid", lambda uid: events.append(("uid", uid)))
    monkeypatch.setenv("HOME", "/root")
    monkeypatch.setenv("USER", "root")
    monkeypatch.setenv("LOGNAME", "root")

    database.drop_to_service_account()

    assert {name: database.os.environ[name] for name in ("HOME", "USER", "LOGNAME")} == {
        "HOME": "/var/lib/tradejournal",
        "USER": "tradejournal",
        "LOGNAME": "tradejournal",
    }
    assert events == [("groups", "tradejournal", 456), ("gid", 456), ("uid", 123)]


def test_backup_database_command_never_contains_password(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "deploy"))
    backup = load("backup")
    safe, password = backup.pg_dump_url(
        "postgresql+psycopg://owner:s%40cret@db.example/journal?sslmode=require"
    )
    assert password == "s@cret"
    assert "s@cret" not in safe
    assert "s%40cret" not in safe
    assert safe == "postgresql://owner@db.example/journal?sslmode=require"


def test_backup_retention_ignores_unrecognized_directories(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "deploy"))
    backup = load("backup")
    monkeypatch.setattr(backup, "BACKUP_ROOT", tmp_path)
    for day in range(1, 10):
        (tmp_path / f"202609{day:02d}T051500Z").mkdir()
    (tmp_path / "keep-me").mkdir()
    removed = backup.prune_backups(7)
    assert [path.name for path in removed] == ["20260901T051500Z", "20260902T051500Z"]
    assert (tmp_path / "keep-me").is_dir()


def test_backup_archive_contains_runtime_state_and_recovery_credentials(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "deploy"))
    backup = load("backup")
    state = tmp_path / "state"
    config = tmp_path / "config"
    for name in ("data", "oauth"):
        (state / name).mkdir(parents=True)
        (state / name / "sample").write_text(name)
    config.mkdir()
    for name in backup.CONFIG_FILES:
        (config / name).write_text(f"test-{name}")
    (config / "local-postgres.env").write_text("staging-only")
    monkeypatch.setattr(backup, "STATE_ROOT", state)
    monkeypatch.setattr(backup, "CONFIG_ROOT", config)

    archive = tmp_path / "state.tar.gz"
    backup.archive_state(archive)

    with tarfile.open(archive) as bundle:
        names = set(bundle.getnames())
        assert {"data/sample", "oauth/sample", "config/backend.env", "config/migration.env"} <= names
        assert "config/local-postgres.env" not in names
        for name in backup.CONFIG_FILES:
            assert bundle.extractfile(f"config/{name}").read() == f"test-{name}".encode()


def test_gmail_automation_rebuilds_only_after_new_fills(monkeypatch):
    automation = load("automation")
    starts = []
    results = {
        "gmail": {"message": "Imported 2 new fill(s), skipped 0."},
        "rebuild": {"message": "Rebuilt 4 trade(s)."},
    }

    def start(job_type, **_kwargs):
        starts.append(job_type)
        return "gmail" if job_type == "gmail_sync" else "rebuild"

    monkeypatch.setattr(automation, "start_job", start)
    monkeypatch.setattr(automation, "wait_for_job", lambda job_id: results[job_id])
    automation.gmail_sync()
    assert starts == ["gmail_sync", "trade_rebuild"]


def test_gmail_automation_does_not_rebuild_without_new_fills(monkeypatch):
    automation = load("automation")
    starts = []
    monkeypatch.setattr(automation, "start_job", lambda job_type, **_kwargs: starts.append(job_type) or "gmail")
    monkeypatch.setattr(
        automation,
        "wait_for_job",
        lambda _job_id: {"message": "Imported 0 new fill(s), skipped 0."},
    )
    automation.gmail_sync()
    assert starts == ["gmail_sync"]


def test_archive_link_cannot_target_an_existing_release(control, tmp_path, monkeypatch):
    archive = tmp_path / "release.tar"
    with tarfile.open(archive, "w") as bundle:
        metadata = json.dumps({"release_id": "new"}).encode()
        info = tarfile.TarInfo("new/release.json")
        info.size = len(metadata)
        bundle.addfile(info, io.BytesIO(metadata))
        link = tarfile.TarInfo("new/escape")
        link.type = tarfile.SYMTYPE
        link.linkname = "../existing"
        bundle.addfile(link)
    monkeypatch.setattr(control, "validate_platform", lambda _: None)
    with pytest.raises(tarfile.FilterError, match="leaves its release"):
        control.install(archive, hashlib.sha256(archive.read_bytes()).hexdigest())
    assert not control.release_path("new").exists()


def test_launcher_forces_private_bind_and_shared_ownership(tmp_path, monkeypatch):
    launch = load("launch")
    (tmp_path / "backend").mkdir()
    (tmp_path / "release.json").write_text('{"release_id":"test"}')
    monkeypatch.setattr(launch, "RELEASE", tmp_path)
    monkeypatch.setattr(launch.sys, "argv", ["launch.py", "api"])
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.delenv("MIGRATION_DATABASE_URL", raising=False)
    monkeypatch.setenv("JOB_EXECUTION_MODE", "embedded")
    monkeypatch.setenv("JOB_LOCK_DIR", "/wrong")
    monkeypatch.chdir(tmp_path)
    commands = []
    monkeypatch.setattr(launch.os, "execv", lambda _, command: commands.append(command))
    launch.main()
    assert commands[0][-4:] == ["--host", "127.0.0.1", "--port", "8080"]
    assert launch.os.environ["JOB_LOCK_DIR"] == "/var/lib/tradejournal/job-locks"
    assert launch.os.environ["JOB_EXECUTION_MODE"] == "external"


def test_launcher_accepts_the_gmail_listener_lane(tmp_path, monkeypatch):
    launch = load("launch")
    (tmp_path / "backend").mkdir()
    (tmp_path / "release.json").write_text('{"release_id":"test"}')
    monkeypatch.setattr(launch, "RELEASE", tmp_path)
    monkeypatch.setattr(launch.sys, "argv", ["launch.py", "worker", "gmail"])
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.delenv("MIGRATION_DATABASE_URL", raising=False)
    # launch.main() rewrites these in os.environ; restore them for later tests.
    for name in ("JOB_EXECUTION_MODE", "JOB_LOCK_DIR", "TRADEJOURNAL_RELEASE", "PYTHONDONTWRITEBYTECODE"):
        monkeypatch.setenv(name, os.environ.get(name, ""))
    monkeypatch.chdir(tmp_path)
    commands = []
    monkeypatch.setattr(launch.os, "execv", lambda _, command: commands.append(command))
    launch.main()
    assert commands[0][-2:] == ["--lane", "gmail"]


def test_every_managed_unit_ships_with_the_release():
    control = load("control")
    systemd = Path(__file__).resolve().parents[2] / "deploy" / "systemd"
    assert "tradejournal-worker@gmail" in control.SERVICES
    assert "tradejournal-sync-pipeline.timer" in control.TIMERS
    for name in control.OPTIONAL_UNITS:
        assert (systemd / name).is_file(), name
    timer = (systemd / "tradejournal-sync-pipeline.timer").read_text()
    assert "OnCalendar=*-*-* 08:00:00 America/New_York" in timer
    assert "OnCalendar=*-*-* 17:00:00 America/New_York" in timer


def test_sync_pipeline_waits_out_a_running_sync(monkeypatch):
    automation = load("automation")
    responses = [(409, {"detail": "busy"}), (409, {"detail": "busy"}), (200, {"pipeline_run_id": "run-1"})]
    calls = []
    monkeypatch.setattr(automation, "request", lambda path, method="GET": calls.append((path, method)) or responses.pop(0))
    monkeypatch.setattr(automation.time, "sleep", lambda _seconds: None)
    automation.sync_pipeline()
    assert calls == [("/sync/pipeline/run", "POST")] * 3


def test_sync_pipeline_gives_up_after_its_retry_window(monkeypatch, capsys):
    automation = load("automation")
    monkeypatch.setattr(automation, "request", lambda *_args, **_kwargs: (409, {"detail": "busy"}))
    monkeypatch.setattr(automation.time, "sleep", lambda _seconds: None)
    automation.sync_pipeline(retry_seconds=0)
    assert "skipped" in capsys.readouterr().out
