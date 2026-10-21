"""Destructive deployment operations are exercised only against tmp_path/fakes.

Native systemd and the packaged application have a separate Ubuntu CI smoke.
"""

from datetime import datetime, timezone
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import subprocess
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


def test_offsite_credentials_are_confined_to_restic_environment(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "deploy"))
    offsite = load("offsite")
    config = tmp_path / "offsite.env"
    config.write_text(
        "RESTIC_REPOSITORY=s3:https://account.r2.cloudflarestorage.com/trade-journal/repo\n"
        "AWS_ACCESS_KEY_ID=access-id\nAWS_SECRET_ACCESS_KEY=private-secret\n"
    )
    password = tmp_path / "restic-password"
    password.write_text("encryption-secret\n")
    monkeypatch.setattr(offsite, "CONFIG", config)
    monkeypatch.setattr(offsite, "PASSWORD_FILE", password)
    monkeypatch.setattr(offsite.os, "geteuid", lambda: 0)
    monkeypatch.setattr(offsite, "_root_only", lambda _path: None)
    monkeypatch.setenv("UNRELATED_SECRET", "never-inherit")

    environment = offsite.restic_environment()
    assert environment["AWS_SECRET_ACCESS_KEY"] == "private-secret"
    assert environment["RESTIC_PASSWORD_FILE"] == str(password)
    assert "encryption-secret" not in str(environment)
    assert "UNRELATED_SECRET" not in environment


def test_offsite_restore_drops_disposable_database_on_failure(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "deploy"))
    offsite = load("offsite")
    dump = tmp_path / "database.dump"
    dump.write_bytes(b"test dump")
    calls = []

    def run(command, **_kwargs):
        calls.append(command)
        if "pg_restore" in command:
            raise subprocess.CalledProcessError(1, command)
        return SimpleNamespace(stdout="")

    monkeypatch.setattr(offsite.subprocess, "run", run)
    with pytest.raises(subprocess.CalledProcessError):
        offsite.restore_database(dump)
    assert any("createdb" in command for command in calls)
    assert any("dropdb" in command for command in calls)
    assert all("test dump" not in str(command) for command in calls)


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


def test_launcher_runs_the_capture_lane_with_the_model_outside_the_backed_up_data(tmp_path, monkeypatch):
    launch = load("launch")
    (tmp_path / "backend").mkdir()
    (tmp_path / "release.json").write_text('{"release_id":"test"}')
    monkeypatch.setattr(launch, "RELEASE", tmp_path)
    monkeypatch.setattr(launch.sys, "argv", ["launch.py", "worker", "capture"])
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.delenv("MIGRATION_DATABASE_URL", raising=False)
    monkeypatch.delenv("CAPTURE_MODEL_DIR", raising=False)
    for name in ("JOB_EXECUTION_MODE", "JOB_LOCK_DIR", "TRADEJOURNAL_RELEASE", "PYTHONDONTWRITEBYTECODE"):
        monkeypatch.setenv(name, os.environ.get(name, ""))
    monkeypatch.chdir(tmp_path)
    commands = []
    monkeypatch.setattr(launch.os, "execv", lambda _, command: commands.append(command))
    launch.main()
    assert commands[0][-2:] == ["--lane", "capture"]
    assert launch.os.environ["CAPTURE_MODEL_DIR"] == "/var/lib/tradejournal/models"
    assert "tradejournal-worker@capture" in load("control").SERVICES


def test_every_managed_unit_ships_with_the_release():
    control = load("control")
    systemd = Path(__file__).resolve().parents[2] / "deploy" / "systemd"
    assert "tradejournal-worker@gmail" in control.SERVICES
    assert "tradejournal-sync-pipeline.timer" in control.TIMERS
    assert "tradejournal-offsite-backup.timer" in control.TIMERS
    assert "tradejournal-alerts.timer" in control.TIMERS
    assert control.MOOMOO_SERVICE in control.OPTIONAL_UNITS
    for name in control.OPTIONAL_UNITS:
        assert (systemd / name).is_file(), name
    timer = (systemd / "tradejournal-sync-pipeline.timer").read_text()
    assert "OnCalendar=*-*-* 08:00:00 America/New_York" in timer
    assert "OnCalendar=*-*-* 17:00:00 America/New_York" in timer


def test_the_api_reads_the_phone_alert_topic_for_level_alerts_without_requiring_it():
    unit = (Path(__file__).resolve().parents[2] / "deploy/systemd/tradejournal-api.service").read_text()
    # Optional ("-"): a server without phone alerts still starts its API.
    assert "EnvironmentFile=-/etc/tradejournal/alerts.env" in unit
    assert unit.index("EnvironmentFile=/etc/tradejournal/backend.env") < unit.index("alerts.env")


def test_deployment_stop_leaves_the_alert_check_running(control, monkeypatch):
    stopped = []
    monkeypatch.setattr(control.subprocess, "run", lambda *a, **kw: SimpleNamespace(stdout="loaded\n", check_returncode=lambda: None))
    monkeypatch.setattr(control, "run", lambda *command, **kw: stopped.append(command[-1]))
    control.stop_services()
    assert "tradejournal-backup.timer" in stopped and "tradejournal-api" in stopped
    assert not control.ALERT_UNITS & set(stopped)


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


def test_options_snapshot_is_queued_after_the_close_and_retried(monkeypatch, capsys):
    automation = load("automation")
    responses = [(409, {"detail": "busy"}), (200, {"run_id": "run-1"})]
    calls = []
    monkeypatch.setattr(automation, "request", lambda path, method="GET": calls.append((path, method)) or responses.pop(0))
    monkeypatch.setattr(automation.time, "sleep", lambda _seconds: None)
    automation.options_snapshot()
    assert calls == [("/sync/jobs/options_snapshot/run", "POST")] * 2
    assert "queued: run-1" in capsys.readouterr().out
    timer = (Path(__file__).resolve().parents[2] / "deploy/systemd/tradejournal-options-snapshot.timer").read_text()
    # After the 16:15 option close and before SPX's 20:15 overnight session.
    assert "OnCalendar=Mon..Fri *-*-* 16:20:00 America/New_York" in timer
    assert "OnCalendar=Mon..Fri *-*-* 19:20:00 America/New_York" in timer
    assert "tradejournal-options-snapshot.timer" in load("control").TIMERS


def test_an_options_snapshot_that_cannot_be_queued_fails_the_unit(monkeypatch):
    # A session's open interest cannot be recorded later, so this is not a quiet skip.
    automation = load("automation")
    monkeypatch.setattr(automation, "request", lambda *_args, **_kwargs: (409, {"detail": "busy"}))
    monkeypatch.setattr(automation.time, "sleep", lambda _seconds: None)
    with pytest.raises(SystemExit, match="not queued"):
        automation.options_snapshot(retry_seconds=0)
    alerts = load("alerts")
    assert "tradejournal-options-snapshot.service" in alerts.SERVICES
    assert "tradejournal-options-snapshot.timer" in alerts.TIMERS


def test_rvol_history_is_queued_before_the_open_and_skips_when_the_lane_stays_busy(monkeypatch, capsys):
    automation = load("automation")
    responses = [(409, {"detail": "busy"}), (200, {"run_id": "run-1"})]
    calls = []
    monkeypatch.setattr(automation, "request", lambda path, method="GET": calls.append((path, method)) or responses.pop(0))
    monkeypatch.setattr(automation.time, "sleep", lambda _seconds: None)
    automation.rvol_history()
    assert calls == [("/sync/jobs/rvol_history/run", "POST")] * 2
    assert "queued: run-1" in capsys.readouterr().out
    # A missed slot costs only today's RVol until the catch-up: a skip, never a unit failure.
    monkeypatch.setattr(automation, "request", lambda *_args, **_kwargs: (409, {"detail": "busy"}))
    automation.rvol_history(retry_seconds=0)
    assert "skipped" in capsys.readouterr().out
    timer = (Path(__file__).resolve().parents[2] / "deploy/systemd/tradejournal-rvol-history.timer").read_text()
    # After New York midnight (yesterday's SIP session is complete) and before the open, with a catch-up.
    assert "OnCalendar=Mon..Fri *-*-* 06:00:00 America/New_York" in timer
    assert "OnCalendar=Mon..Fri *-*-* 08:40:00 America/New_York" in timer
    assert "tradejournal-rvol-history.timer" in load("control").TIMERS
    alerts = load("alerts")
    assert "tradejournal-rvol-history.service" in alerts.SERVICES
    assert "tradejournal-rvol-history.timer" in alerts.TIMERS


def test_market_context_is_queued_every_15_minutes_and_skips_when_busy(monkeypatch, capsys):
    automation = load("automation")
    responses = [(409, {"detail": "busy"}), (200, {"run_id": "run-1"})]
    calls = []
    monkeypatch.setattr(automation, "request", lambda path, method="GET": calls.append((path, method)) or responses.pop(0))
    monkeypatch.setattr(automation.time, "sleep", lambda _seconds: None)
    automation.market_context()
    assert calls == [("/sync/jobs/market_context/run", "POST")] * 2 and "queued: run-1" in capsys.readouterr().out
    monkeypatch.setattr(automation, "request", lambda *_args, **_kwargs: (409, {"detail": "busy"}))
    automation.market_context(retry_seconds=0)
    assert "skipped" in capsys.readouterr().out
    timer = (Path(__file__).resolve().parents[2] / "deploy/systemd/tradejournal-market-context.timer").read_text()
    assert "OnCalendar=Mon..Fri *-*-* 06..16:00/15:00 America/New_York" in timer
    assert "tradejournal-market-context.timer" in load("control").TIMERS
    alerts = load("alerts")
    assert "tradejournal-market-context.service" in alerts.SERVICES and "tradejournal-market-context.timer" in alerts.TIMERS


@pytest.fixture
def alerts(tmp_path, monkeypatch):
    module = load("alerts")
    monkeypatch.setattr(module, "STATE_FILE", tmp_path / "alerts" / "state.json")
    monkeypatch.setattr(module, "ENV_FILE", tmp_path / "missing.env")
    return module


def job_run(job_type, status, finished_at, error=None, label=None):
    return {"job_type": job_type, "status": status, "finished_at": finished_at, "created_at": finished_at,
            "error_summary": error, "label": label or job_type}


def test_alert_waits_out_its_grace_then_fires_once_and_recovers_once(alerts):
    down = {"api": alerts.Problem("TradeJournal isn't responding", "refused", 300, "TradeJournal is responding again")}
    notices, state = alerts.evaluate(down, {}, now=1000)
    assert notices == []
    notices, state = alerts.evaluate(down, state, now=1299)
    assert notices == []
    notices, state = alerts.evaluate(down, state, now=1300)
    assert [n["title"] for n in notices] == ["TradeJournal isn't responding"]
    notices, state = alerts.evaluate(down, state, now=1500)
    assert notices == []
    notices, state = alerts.evaluate({"api": None}, state, now=2800)
    assert notices == [{"keys": ["api"], "recovered": True, "title": "TradeJournal is responding again",
                        "message": "Resolved after 30 minutes."}]
    assert state["conditions"] == {}


def test_a_blip_shorter_than_the_grace_is_never_mentioned(alerts):
    down = {"gmail": alerts.gmail_problem({"status": "degraded", "message": "reconnecting"})}
    _, state = alerts.evaluate(down, {}, now=0)
    notices, state = alerts.evaluate({"gmail": None}, state, now=120)
    assert notices == [] and state["conditions"] == {}


def test_unknown_conditions_keep_their_state(alerts):
    failed = {"tradejournal-backup.service": alerts.Problem("Nightly backup failed", "x", 0, "Nightly backup is working again")}
    _, state = alerts.evaluate(failed, {}, now=0)
    # After a reboot systemd forgets the failure; that is not a recovery.
    rebooted = alerts.unit_problems({"tradejournal-backup.service": {
        "Id": "tradejournal-backup.service", "LoadState": "loaded", "ActiveState": "inactive",
        "Result": "success", "ExecMainExitTimestampMonotonic": "0"}})
    assert "tradejournal-backup.service" not in rebooted
    notices, state = alerts.evaluate(rebooted, state, now=60)
    assert notices == [] and state["conditions"]["tradejournal-backup.service"]["alerted"]
    ran = alerts.unit_problems({"tradejournal-backup.service": {
        "LoadState": "loaded", "ActiveState": "inactive", "Result": "success", "ExecMainExitTimestampMonotonic": "91"}})
    notices, _ = alerts.evaluate(ran, state, now=86400)
    assert [n["title"] for n in notices] == ["Nightly backup is working again"]


def test_failed_units_and_stopped_timers_are_problems(alerts):
    observed = alerts.unit_problems({
        "tradejournal-offsite-backup.service": {"LoadState": "loaded", "ActiveState": "failed", "Result": "exit-code"},
        "tradejournal-backup.timer": {"LoadState": "loaded", "ActiveState": "inactive"},
        "tradejournal-sync-pipeline.timer": {"LoadState": "loaded", "ActiveState": "active"},
        "tradejournal-gmail-sync.timer": {"LoadState": "not-found", "ActiveState": "inactive"},
    })
    assert observed["tradejournal-offsite-backup.service"].title == "Offsite backup failed"
    assert observed["tradejournal-backup.timer"].grace == alerts.TIMER_GRACE
    assert observed["tradejournal-sync-pipeline.timer"] is None
    assert "tradejournal-gmail-sync.timer" not in observed


def test_the_opt_in_plan_review_schedule_is_a_problem_only_once_enabled(alerts):
    name = "tradejournal-plan-reviews.timer"
    assert name not in alerts.unit_problems({name: {"LoadState": "loaded", "UnitFileState": "disabled", "ActiveState": "inactive"}})
    stopped = alerts.unit_problems({name: {"LoadState": "loaded", "UnitFileState": "enabled", "ActiveState": "inactive"}})
    assert stopped[name].title == "Nightly AI reviews is switched off"
    assert alerts.unit_problems({name: {"LoadState": "loaded", "UnitFileState": "enabled", "ActiveState": "active"}})[name] is None
    failed = alerts.unit_problems({"tradejournal-plan-reviews.service": {"LoadState": "loaded", "ActiveState": "failed", "Result": "exit-code"}})
    assert failed["tradejournal-plan-reviews.service"].title == "Nightly AI reviews failed"


def test_job_failures_before_alerts_started_are_history(alerts):
    since = alerts.timestamp("2026-09-24T00:00:00Z")
    runs = [job_run("daily_review", "failed", "2026-09-23T12:00:00Z", "old news")]
    assert alerts.job_problems(runs, since, gmail_down=False) == {}
    runs.insert(0, job_run("daily_review", "failed", "2026-09-24T09:00:00Z", "Anthropic said no\ntraceback", "Daily review generation"))
    problem = alerts.job_problems(runs, since, gmail_down=False)["job:daily_review"]
    assert (problem.title, problem.message, problem.grace) == ("Daily review generation failed", "Anthropic said no", 0)
    runs.insert(0, job_run("daily_review", "succeeded", "2026-09-24T10:00:00Z"))
    assert alerts.job_problems(runs, since, gmail_down=False) == {"job:daily_review": None}


def test_listeners_and_running_jobs_are_not_judged_as_jobs(alerts):
    runs = [job_run("gmail_sync", "running", None), job_run("webull_listener", "failed", "2026-09-24T09:00:00Z"),
            job_run("gmail_listener", "failed", "2026-09-24T09:00:00Z")]
    assert alerts.job_problems(runs, 0, gmail_down=False) == {}


def test_gmail_job_failures_defer_to_the_gmail_alert(alerts):
    runs = [job_run("gmail_sync", "failed", "2026-09-24T09:00:00Z", "Gmail authorization is required.")]
    assert alerts.job_problems(runs, 0, gmail_down=True) == {}
    assert alerts.job_problems(runs, 0, gmail_down=False)["job:gmail_sync"].grace == alerts.GMAIL_GRACE


def test_interrupted_import_asks_for_a_rebuild(alerts):
    error = "Worker interrupted; partial work may be committed. Review and start a new run."
    runs = [job_run("full_pipeline", "failed", "2026-09-24T09:00:00Z", error),
            job_run("polygon_enrich", "failed", "2026-09-24T09:00:00Z", error)]
    observed = alerts.job_problems(runs, 0, gmail_down=False)
    assert "Rebuild trades" in observed["job:full_pipeline"].message
    assert "Rebuild" not in observed["job:polygon_enrich"].message


def test_a_pipeline_and_its_failed_step_arrive_as_one_message(alerts):
    runs = [job_run("full_pipeline", "failed", "2026-09-24T12:00:05Z", "rebuild broke", "Full sync pipeline"),
            job_run("trade_rebuild", "failed", "2026-09-24T12:00:04Z", "rebuild broke", "Rebuild trades / FIFO matching")]
    notices, state = alerts.evaluate(alerts.job_problems(runs, 0, gmail_down=False), {}, now=0)
    assert len(notices) == 1
    assert notices[0]["title"] == "2 sync jobs failed"
    assert sorted(notices[0]["keys"]) == ["job:full_pipeline", "job:trade_rebuild"]
    assert "• Full sync pipeline failed: rebuild broke" in notices[0]["message"]
    recovered = {"job:full_pipeline": None, "job:trade_rebuild": None}
    notices, _ = alerts.evaluate(recovered, state, now=60)
    assert [n["title"] for n in notices] == ["2 sync jobs are working again"]


def test_undelivered_alert_is_retried_and_reported_to_the_dead_mans_switch(alerts, monkeypatch):
    problem = alerts.Problem("Offsite backup failed", "x", 0, "Offsite backup is working again")
    monkeypatch.setattr(alerts, "observe", lambda since: {"tradejournal-offsite-backup.service": problem})
    pings, sent = [], []

    def offline(config, title, message, *, recovered=False):
        raise OSError("ntfy unreachable")

    monkeypatch.setattr(alerts, "publish", offline)
    monkeypatch.setattr(alerts, "ping", lambda config, healthy: pings.append(healthy))
    assert alerts.check({}, now=100) is False
    assert alerts.read_state()["conditions"]["tradejournal-offsite-backup.service"]["alerted"] is False
    monkeypatch.setattr(alerts, "publish", lambda config, title, message, **kw: sent.append(title))
    assert alerts.check({}, now=220) is True
    assert alerts.check({}, now=340) is True
    assert sent == ["Offsite backup failed"] and pings == [False, True, True]
    assert alerts.read_state()["watching_since"] == 100


def disk(monkeypatch, alerts, percent_by_path, device_by_path=None):
    """1000 blocks of 1 MiB; `percent` used as df counts it, no reserved blocks."""
    devices = device_by_path or {path: 1 for path in percent_by_path}

    def stat(path):
        if path not in percent_by_path:
            raise FileNotFoundError(path)
        return SimpleNamespace(st_dev=devices[path])

    def statvfs(path):
        used = percent_by_path[path] * 10
        return SimpleNamespace(f_blocks=1000, f_bfree=1000 - used, f_bavail=1000 - used, f_frsize=1024**2)

    monkeypatch.setattr(alerts.os, "stat", stat)
    monkeypatch.setattr(alerts.os, "statvfs", statvfs)


def test_disk_warning_waits_out_a_deploy_then_fires_once_and_recovers(alerts, monkeypatch):
    disk(monkeypatch, alerts, {"/": 85})
    observed = alerts.disk_problems(("/",))
    assert observed["disk:/:critical"] is None
    warning = observed["disk:/:warning"]
    assert warning.title == "Server disk is 85% full" and "0.1 GB free on /" in warning.message
    notices, state = alerts.evaluate(observed, {}, now=0)
    assert notices == []
    notices, state = alerts.evaluate(alerts.disk_problems(("/",)), state, now=alerts.DISK_GRACE)
    assert [n["title"] for n in notices] == ["Server disk is 85% full"]
    notices, state = alerts.evaluate(alerts.disk_problems(("/",)), state, now=alerts.DISK_GRACE + 120)
    assert notices == []
    disk(monkeypatch, alerts, {"/": 60})
    notices, state = alerts.evaluate(alerts.disk_problems(("/",)), state, now=alerts.DISK_GRACE + 240)
    assert [(n["title"], n["recovered"]) for n in notices] == [("Server disk is back under 80%", True)]


def test_disk_critical_fires_at_once_without_a_second_warning(alerts, monkeypatch):
    disk(monkeypatch, alerts, {"/": 85})
    _, state = alerts.evaluate(alerts.disk_problems(("/",)), {}, now=0)
    notices, state = alerts.evaluate(alerts.disk_problems(("/",)), state, now=alerts.DISK_GRACE)
    assert [n["title"] for n in notices] == ["Server disk is 85% full"]
    disk(monkeypatch, alerts, {"/": 92})
    observed = alerts.disk_problems(("/",))
    assert "disk:/:warning" not in observed  # unknown this pass: keeps its alerted state
    notices, state = alerts.evaluate(observed, state, now=alerts.DISK_GRACE + 120)
    assert [n["title"] for n in notices] == ["Server disk is 92% full"]
    assert state["conditions"]["disk:/:warning"]["alerted"] is True
    disk(monkeypatch, alerts, {"/": 70})
    notices, _ = alerts.evaluate(alerts.disk_problems(("/",)), state, now=alerts.DISK_GRACE + 240)
    assert sorted(n["title"] for n in notices) == ["Server disk is back under 80%", "Server disk is back under 90%"]


def test_each_disk_is_checked_once_and_missing_paths_are_skipped(alerts, monkeypatch):
    disk(monkeypatch, alerts, {"/": 50, "/var/lib/postgresql": 50, "/var/backups/tradejournal": 95},
         {"/": 1, "/var/lib/postgresql": 1, "/var/backups/tradejournal": 2})
    observed = alerts.disk_problems(("/", "/var/lib/postgresql", "/var/backups/tradejournal", "/missing"))
    assert sorted(observed) == ["disk:/:critical", "disk:/:warning", "disk:/var/backups/tradejournal:critical"]
    assert observed["disk:/var/backups/tradejournal:critical"].title == "Server disk is 95% full"


def test_disk_is_part_of_every_alert_pass(alerts, monkeypatch):
    monkeypatch.setattr(alerts, "get", lambda path: (_ for _ in ()).throw(OSError("refused")))
    monkeypatch.setattr(alerts, "systemd_units", lambda: {})
    monkeypatch.setattr(alerts, "disk_problems", lambda: {"disk:/:critical": None})
    assert "disk:/:critical" in alerts.observe(0)


def test_notification_is_posted_as_json_to_the_ntfy_server(alerts, monkeypatch):
    requests = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(alerts, "urlopen", lambda request, timeout: requests.append(request) or Response())
    config = {"NTFY_URL": "https://ntfy.sh/tradejournal-secret", "NTFY_TOKEN": "tk", "ALERT_APP_URL": "https://vps.example.ts.net"}
    alerts.publish(config, "Gmail needs reconnecting", "Reconnect Gmail.")
    request = requests[0]
    assert request.full_url == "https://ntfy.sh/" and request.get_method() == "POST"
    assert request.get_header("Authorization") == "Bearer tk"
    assert json.loads(request.data) == {"topic": "tradejournal-secret", "title": "Gmail needs reconnecting",
                                        "message": "Reconnect Gmail.", "priority": 4, "tags": ["warning"],
                                        "click": "https://vps.example.ts.net"}


def test_systemctl_show_blocks_are_parsed_per_unit(alerts, monkeypatch):
    output = ("Id=tradejournal-backup.service\nLoadState=loaded\nActiveState=failed\n\n"
              "Id=tradejournal-backup.timer\nLoadState=loaded\nActiveState=active\n")
    monkeypatch.setattr(alerts.subprocess, "run", lambda *a, **kw: SimpleNamespace(stdout=output))
    units = alerts.systemd_units()
    assert units["tradejournal-backup.service"]["ActiveState"] == "failed"
    assert units["tradejournal-backup.timer"]["ActiveState"] == "active"


def test_retired_ingress_unit_is_stopped_and_removed_during_upgrade(control, tmp_path, monkeypatch):
    units = tmp_path / "units"
    units.mkdir()
    (units / "tradejournal-ingress.service").write_text("legacy unit")
    release = tmp_path / "new-release"
    (release / "deploy/systemd").mkdir(parents=True)
    monkeypatch.setattr(control, "UNITS", units)
    calls = []
    monkeypatch.setattr(control, "run", lambda *args: calls.append(args))
    monkeypatch.setattr(control.subprocess, "run", lambda args, **_: calls.append(args))

    control.install_units(release)

    assert ["systemctl", "disable", "--now", "tradejournal-ingress.service"] in calls
    assert not (units / "tradejournal-ingress.service").exists()
    assert not (release / "deploy/systemd/tradejournal-ingress.service").exists()
    assert "tradejournal-ingress.service" not in control.OPTIONAL_UNITS
    assert "tradejournal-ingress" in control.RETIRED_SERVICES


def test_backups_preserve_legacy_ingress_configuration(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "deploy"))
    backup = load("backup")
    state, config = tmp_path / "state", tmp_path / "config"
    config.mkdir()
    for name in ("data", "oauth"):
        (state / name).mkdir(parents=True)
    for name in (*backup.CONFIG_FILES, "tradingview.env"):
        (config / name).write_text("fixture-credentials")
    monkeypatch.setattr(backup, "STATE_ROOT", state)
    monkeypatch.setattr(backup, "CONFIG_ROOT", config)
    archive = tmp_path / "state.tar.gz"
    backup.archive_state(archive)
    with tarfile.open(archive) as bundle:
        assert bundle.extractfile("config/tradingview.env").read() == b"fixture-credentials"


def test_prune_keeps_the_newest_releases_and_never_current_or_previous(control, tmp_path, monkeypatch):
    monkeypatch.setattr(control, "STATE", tmp_path / "state")
    ages = {"previous-build": 4, "current-build": 3, "older-build": 2, "newest-build": 1}
    for name, days_old in ages.items():
        release = control.release_path(name)
        release.mkdir()
        stamp = 1_790_000_000 - days_old * 86_400
        os.utime(release, (stamp, stamp))
        (control.STATE / "frontend-cache" / name).mkdir(parents=True)
    (control.ROOT / "releases/.install-staging").mkdir()
    (control.ROOT / "releases/Not_A_Release").mkdir()
    control.atomic_link(control.release_path("current-build"), control.ROOT / "current")
    control.atomic_link(control.release_path("previous-build"), control.ROOT / "previous")

    control.prune(1)

    remaining = sorted(path.name for path in (control.ROOT / "releases").iterdir())
    assert remaining == [".install-staging", "Not_A_Release", "current-build", "newest-build", "previous-build"]
    assert not (control.STATE / "frontend-cache/older-build").exists()
    assert (control.STATE / "frontend-cache/current-build").exists()


def test_busy_controller_exits_with_the_code_autodeploy_retries(control, monkeypatch):
    import fcntl
    import sys

    monkeypatch.setattr(control.os, "geteuid", lambda: 0)
    monkeypatch.setattr(sys, "argv", ["tradejournal-deploy", "status"])
    monkeypatch.setattr(control.os, "umask", lambda _mask: 0o022)
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "deploy"))
    autodeploy = load("autodeploy")
    with (control.ROOT / "deployment.lock").open("a+b") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(SystemExit) as exit_info:
            control.main()
    assert exit_info.value.code == control.BUSY == autodeploy.CONTROLLER_BUSY


def test_deployment_pauses_the_autodeploy_timer_but_never_its_running_service(control, monkeypatch):
    stopped = []

    def systemctl(command, **_kwargs):
        if command[1] == "show":
            return SimpleNamespace(stdout="loaded\n", check_returncode=lambda: None)
        return None

    monkeypatch.setattr(control.subprocess, "run", systemctl)
    monkeypatch.setattr(control, "run", lambda *args: stopped.append(args[-1]))
    control.stop_services()
    assert "tradejournal-autodeploy.timer" in stopped
    assert "tradejournal-autodeploy.service" not in stopped
    assert "tradejournal-autodeploy.timer" in control.TIMERS
    assert "tradejournal-autodeploy.service" in control.OPTIONAL_UNITS


def test_moomoo_bridge_stops_before_frontend_during_release_switch(control, monkeypatch):
    stopped = []

    def systemctl(command, **_kwargs):
        if command[1] == "show":
            return SimpleNamespace(stdout="loaded\n", check_returncode=lambda: None)
        return None

    monkeypatch.setattr(control.subprocess, "run", systemctl)
    monkeypatch.setattr(control, "run", lambda *args: stopped.append(args[-1]))
    control.stop_services()
    assert stopped.index(control.MOOMOO_SERVICE) < stopped.index("tradejournal-frontend")


def test_moomoo_bridge_restart_requires_enabled_unit_and_explicit_frontend_config(control, tmp_path, monkeypatch):
    env = tmp_path / "moomoo-frontend.env"
    monkeypatch.setattr(control, "MOOMOO_FRONTEND_ENV", env)
    monkeypatch.setattr(control.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0))
    assert not control.moomoo_is_enabled()
    env.write_text("TJ_MOOMOO_LAB_ENABLED=false\n")
    assert not control.moomoo_is_enabled()
    env.write_text("TJ_MOOMOO_LAB_ENABLED=true\n")
    assert control.moomoo_is_enabled()
    monkeypatch.setattr(control.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=1))
    assert not control.moomoo_is_enabled()


def test_depth_recorder_units_are_opt_in_and_never_see_r2_or_journal_state(control):
    systemd = Path(__file__).resolve().parents[2] / "deploy/systemd"
    recorder = (systemd / "tradejournal-depth-recorder.service").read_text()
    upload = (systemd / "tradejournal-depth-upload.service").read_text()
    assert control.DEPTH_RECORDER in control.OPTIONAL_UNITS and "tradejournal-depth-upload.timer" in control.OPT_IN_TIMERS
    assert "User=tradejournal-moomoo" in recorder and "StateDirectory=tradejournal-depth" in recorder
    assert "depth-r2" not in recorder and "InaccessiblePaths=-/var/lib/tradejournal -/etc/tradejournal" in recorder
    assert "EnvironmentFile=/etc/tradejournal/depth-r2.env" in upload and "LoadCredential" not in upload
    assert "offsite.env" not in upload and "ReadWritePaths=-/var/lib/tradejournal-depth" in upload


def test_depth_recorder_restarts_only_when_enabled(control, monkeypatch, tmp_path):
    release = tmp_path / "release"
    (release / "deploy/systemd").mkdir(parents=True)
    (release / "deploy/systemd" / control.DEPTH_RECORDER).write_text("")
    started = []
    monkeypatch.setattr(control, "install_units", lambda release: None)
    monkeypatch.setattr(control, "health", lambda *args: None)
    monkeypatch.setattr(control, "moomoo_is_enabled", lambda: False)
    monkeypatch.setattr(control.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(control, "run", lambda *command, **kwargs: None)
    for enabled, start_code in ((1, 0), (0, 0), (0, 1)):
        started.clear()
        def fake(command, **kwargs):
            if command[:2] == ["systemctl", "start"]:
                started.append(command[2])
                return type("R", (), {"returncode": start_code})()
            return type("R", (), {"returncode": enabled})()
        monkeypatch.setattr(control.subprocess, "run", fake)
        control.start_services(release, "fixture")  # a recorder that fails to start never raises
        assert (control.DEPTH_RECORDER in started) == (enabled == 0)


def test_moomoo_unit_is_loopback_bridge_with_separate_read_only_credentials():
    systemd = Path(__file__).resolve().parents[2] / "deploy/systemd"
    bridge = (systemd / "tradejournal-moomoo.service").read_text()
    frontend = (systemd / "tradejournal-frontend.service").read_text()
    assert "User=tradejournal-moomoo" in bridge
    assert "ExecStart=/opt/tradejournal/current/backend/.venv/bin/python -m scripts.moomoo_lab_server" in bridge
    assert "LoadCredential=appkey:/etc/tradejournal/moomoo/appkey" in bridge
    assert "LoadCredential=phase1-ed25519.pem:/etc/tradejournal/moomoo/phase1-ed25519.pem" in bridge
    assert "InaccessiblePaths=-/var/lib/tradejournal -/etc/tradejournal" in bridge
    assert "EnvironmentFile=-/etc/tradejournal/moomoo-frontend.env" in frontend


def test_moomoo_provisioning_accepts_only_canonical_private_https_origin():
    config = load("moomoo_config")
    assert config.validate_origin("https://tradejournal.tailnet.ts.net") == "https://tradejournal.tailnet.ts.net"
    for origin in (
        "http://tradejournal.tailnet.ts.net",
        "https://tradejournal.tailnet.ts.net.evil.example",
        "https://TRADEJOURNAL.tailnet.ts.net",
        "https://tradejournal.tailnet.ts.net:443",
        "https://tradejournal.tailnet.ts.net/path",
    ):
        with pytest.raises(ValueError, match="canonical private HTTPS"):
            config.validate_origin(origin)


def test_moomoo_provisioning_validates_ed25519_pem_without_secret_fixtures(tmp_path):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.asymmetric.rsa import generate_private_key

    config = load("moomoo_config")

    def write_key(name, key):
        path = tmp_path / name
        path.write_bytes(key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ))
        path.chmod(0o600)
        return path

    ed25519 = write_key("ed25519.pem", Ed25519PrivateKey.generate())
    rsa = write_key("rsa.pem", generate_private_key(public_exponent=65537, key_size=2048))
    assert config.read_source(ed25519, key=True)
    with pytest.raises(ValueError, match="must contain an Ed25519"):
        config.read_source(rsa, key=True)


def test_practice_timer_is_packaged_but_never_enabled_by_install():
    systemd = Path(__file__).resolve().parents[2] / "deploy/systemd"
    control = load("control")
    assert "tradejournal-practice.timer" not in control.TIMERS
    assert "tradejournal-practice.timer" in control.OPTIONAL_UNITS
    assert "tradejournal-worker@practice" in control.SERVICES
    timer = (systemd / "tradejournal-practice.timer").read_text()
    assert "08:50:00 America/New_York" in timer
    assert "Persistent=true" in timer
    service = (systemd / "tradejournal-practice.service").read_text()
    assert "app.jobs.practice_schedule" in service
    assert "TimeoutStartSec=5min" in service
    assert "EnvironmentFile=/etc/tradejournal/backend.env" in service


def test_plan_reviews_are_packaged_opt_in_with_a_pinned_claude_code_and_the_token_file():
    root = Path(__file__).resolve().parents[2]
    systemd = root / "deploy/systemd"
    control = load("control")
    assert "tradejournal-plan-reviews.timer" not in control.TIMERS
    assert {"tradejournal-plan-reviews.service", "tradejournal-plan-reviews.timer"} <= set(control.OPTIONAL_UNITS)
    assert "tradejournal-plan-reviews.timer" in control.OPT_IN_TIMERS
    service = (systemd / "tradejournal-plan-reviews.service").read_text()
    assert "-m app.jobs.plan_reviews" in service
    assert "EnvironmentFile=/etc/tradejournal/claude-plan.env" in service  # required: no token, no run
    assert "TJ_CLAUDE_BIN=/opt/tradejournal/current/bin/claude" in service
    assert "ReadWritePaths=/var/lib/tradejournal" in service and "ProtectHome=true" in service
    timer = (systemd / "tradejournal-plan-reviews.timer").read_text()
    assert "20:10:00 America/New_York" in timer and "Persistent=true" in timer
    api = (systemd / "tradejournal-api.service").read_text()
    assert "ReadWritePaths=-/var/lib/tradejournal-shadow" in api
    assert "EnvironmentFile=-/etc/tradejournal/claude-plan.env" in api  # optional for the API
    pinned = json.loads((root / "deploy/claude-code/package.json").read_text())["dependencies"]["@anthropic-ai/claude-code"]
    assert re.fullmatch(r"\d+\.\d+\.\d+", pinned)
    lock = json.loads((root / "deploy/claude-code/package-lock.json").read_text())
    assert lock["packages"]["node_modules/@anthropic-ai/claude-code"]["version"] == pinned
    assert "claude-code-linux-{arch}/claude" in (root / "deploy/build.py").read_text()
    example = (root / "deploy/claude-plan.env.example").read_text()
    assert "CLAUDE_CODE_OAUTH_TOKEN=\n" in example and "ANTHROPIC_API_KEY" not in example


def test_moomoo_provisioning_preserves_existing_state_and_cleans_partial_creation(tmp_path, monkeypatch):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    config = load("moomoo_config")
    target = tmp_path / "etc"
    monkeypatch.setattr(config, "CONFIG", target)
    monkeypatch.setattr(config, "CREDENTIALS", target / "moomoo")
    monkeypatch.setattr(config, "BRIDGE_ENV", target / "bridge.env")
    monkeypatch.setattr(config, "FRONTEND_ENV", target / "frontend.env")
    monkeypatch.setattr(config.os, "geteuid", lambda: 0)
    monkeypatch.setattr(config.pwd, "getpwnam", lambda name: SimpleNamespace())
    appkey, pem = tmp_path / "source-appkey", tmp_path / "source-key"
    appkey.write_bytes(b"fixture-appkey")
    pem.write_bytes(Ed25519PrivateKey.generate().private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    appkey.chmod(0o600)
    pem.chmod(0o600)
    target.mkdir(mode=0o700)
    config.FRONTEND_ENV.write_text("preserve")
    with pytest.raises(FileExistsError):
        config.provision(appkey, pem, "https://fixture.tail000.ts.net")
    assert config.FRONTEND_ENV.read_text() == "preserve"
    config.FRONTEND_ENV.unlink()
    original = config.atomic_secret
    def fail_frontend(path, content, mode):
        if path == config.FRONTEND_ENV:
            raise OSError("fixture-write-failure")
        original(path, content, mode)
    monkeypatch.setattr(config, "atomic_secret", fail_frontend)
    with pytest.raises(OSError, match="fixture-write-failure"):
        config.provision(appkey, pem, "https://fixture.tail000.ts.net")
    assert list(target.iterdir()) == []
    assert appkey.read_bytes() == b"fixture-appkey"
    monkeypatch.setattr(config, "atomic_secret", original)
    config.provision(appkey, pem, "https://fixture.tail000.ts.net")
    bridge = dict(line.split("=", 1) for line in config.BRIDGE_ENV.read_text().splitlines())
    frontend = dict(line.split("=", 1) for line in config.FRONTEND_ENV.read_text().splitlines())
    assert bridge["TJ_MOOMOO_LAB_TOKEN"] == frontend["TJ_MOOMOO_LAB_TOKEN"]
    assert frontend["TJ_MOOMOO_WEB_ORIGIN"] == "https://fixture.tail000.ts.net"
    assert config.FRONTEND_ENV.stat().st_mode & 0o777 == 0o600
    assert config.CREDENTIALS.stat().st_mode & 0o777 == 0o700


def test_moomoo_native_readiness_wait_is_bounded_and_rejects_auth_and_invalid_status(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "deploy"))
    smoke = load("smoke")
    clock = [0.0]
    monkeypatch.setattr(smoke.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(smoke.time, "sleep", lambda delay: clock.__setitem__(0, clock[0] + delay))
    calls = []
    def starting(request, timeout):
        calls.append(request)
        if len(calls) == 1:
            raise smoke.urllib.error.URLError("connection refused fixture")
        return io.BytesIO(b'{"enabled":true}')
    monkeypatch.setattr(smoke.urllib.request, "urlopen", starting)
    assert smoke.moomoo_status("fixture-token") == {"enabled": True}
    assert len(calls) == 2
    def refused(*args, **kwargs):
        raise smoke.urllib.error.URLError("connection refused fixture")
    monkeypatch.setattr(smoke.urllib.request, "urlopen", refused)
    with pytest.raises(RuntimeError, match="readiness timed out"):
        smoke.moomoo_status("fixture-token", timeout=0.2)
    def unauthorized(*args, **kwargs):
        raise smoke.urllib.error.HTTPError("fixture", 403, "denied", {}, None)
    monkeypatch.setattr(smoke.urllib.request, "urlopen", unauthorized)
    with pytest.raises(smoke.urllib.error.HTTPError):
        smoke.moomoo_status("fixture-token")
    monkeypatch.setattr(smoke.urllib.request, "urlopen", lambda *args, **kwargs: io.BytesIO(b'{"enabled":false}'))
    with pytest.raises(ValueError, match="Unexpected bridge readiness"):
        smoke.moomoo_status("fixture-token")


# Morning brief watchdog: 2026-10-20 is a Tuesday; 13:15 UTC is the 09:15 ET deadline.
MORNING_DEADLINE = datetime(2026, 10, 20, 13, 15, tzinfo=timezone.utc).timestamp()


def morning_view(publication="published", fulfilment="pending", last_pass=MORNING_DEADLINE, pending=None,
                 status="published", day="2026-10-20", enabled=True, configuration_error=False):
    iso = lambda value: datetime.fromtimestamp(value, timezone.utc).isoformat() if value else None  # noqa: E731
    return {"day": day, "automation": {"enabled": enabled, "configuration_error": configuration_error,
            "last_pass": iso(last_pass), "last_status": status,
            "pending": pending or {"count": 0, "oldest_submitted_at": None, "unreadable": 0}},
            "delivery": {"publication": publication, "fulfilment": fulfilment, "deadline": "2026-10-20T13:15:00+00:00",
                         "publish_at": "2026-10-20T12:45:00+00:00"}}


def test_morning_conditions_name_one_cause_and_leave_unknowns_alone(alerts):
    now = MORNING_DEADLINE + 30
    brief, publication = "jo_morning:2026-10-20:brief", "jo_morning:2026-10-20:publication"
    missing = alerts.morning_problems(morning_view(fulfilment="missing"), now)
    assert missing[brief].title == "Jo's morning brief is missing" and "9:15 AM ET" in missing[brief].message
    assert missing[publication] is None and missing[brief].grace == 0
    assert "read" not in missing[brief].message  # Older API: no trace field, no claim either way.
    traced = morning_view(fulfilment="missing")
    traced["delivery"].update(context_read="recorded", context_read_at="2026-10-20T13:02:00+00:00")
    assert "Jo read the packet at 9:02 AM ET but nothing was saved (a read doesn't show who started the run)." in alerts.morning_problems(traced, now)[brief].message
    traced["delivery"].update(context_read="not_recorded", context_read_at=None)
    assert "No read of the packet was recorded." in alerts.morning_problems(traced, now)[brief].message
    unpublished = alerts.morning_problems(morning_view(publication="missing", fulfilment="missing"), now)
    assert unpublished[publication].grace == alerts.MORNING_PUBLICATION_GRACE and unpublished[brief] is None
    for done in ("late", "on_time", "pending", "not_expected"):
        assert alerts.morning_problems(morning_view(fulfilment=done), now)[brief] is None
    unknown = alerts.morning_problems(morning_view(publication="unknown", fulfilment="unknown"), now)
    assert brief not in unknown and publication not in unknown
    assert alerts.morning_problems(morning_view(fulfilment="missing", enabled=False), now) == {}
    broken = alerts.morning_problems(morning_view(fulfilment="not_expected", enabled=False, configuration_error=True), now)
    assert list(broken) == ["jo_morning:runner"] and broken["jo_morning:runner"].grace == alerts.API_GRACE


def test_a_stopped_runner_hides_its_stale_pending_and_calendar_facts(alerts):
    old = {"count": 1, "oldest_submitted_at": "2026-10-20T13:00:00+00:00", "unreadable": 1}
    stale = alerts.morning_problems(morning_view(last_pass=MORNING_DEADLINE - 600, pending=old, status="calendar_unavailable"), MORNING_DEADLINE)
    assert stale["jo_morning:runner"].grace == alerts.API_GRACE
    assert {"jo_morning:import", "jo_morning:unreadable", "jo_morning:calendar"}.isdisjoint(stale)
    assert alerts.morning_problems(morning_view(last_pass=None), MORNING_DEADLINE)["jo_morning:runner"] is not None
    fresh = alerts.morning_problems(morning_view(pending=old, status="calendar_unavailable"), MORNING_DEADLINE + 60)
    assert fresh["jo_morning:runner"] is None
    assert "9:00 AM ET" in fresh["jo_morning:import"].message
    assert fresh["jo_morning:unreadable"] is not None
    assert fresh["jo_morning:calendar"].grace == alerts.MORNING_CALENDAR_GRACE
    recent = {"count": 1, "oldest_submitted_at": "2026-10-20T13:14:30+00:00", "unreadable": 0}
    assert alerts.morning_problems(morning_view(pending=recent), MORNING_DEADLINE + 60)["jo_morning:import"] is None
    saturday = alerts.morning_problems(morning_view(day="2026-10-24", status="calendar_unavailable"), MORNING_DEADLINE + 60)
    assert "jo_morning:calendar" not in saturday


def morning_pass(alerts, monkeypatch, view, sends, fail=None):
    monkeypatch.setattr(alerts, "observe", lambda since: {"api": None})
    monkeypatch.setattr(alerts, "get", lambda path: view)
    monkeypatch.setattr(alerts, "ping", lambda config, healthy: None)

    def publish(config, title, message, *, recovered=False):
        if fail:
            raise fail
        sends.append(title)
    monkeypatch.setattr(alerts, "publish", publish)


def test_missed_brief_alerts_once_then_late_recovery_keeps_the_record(alerts, monkeypatch):
    sends, config = [], {"JO_MORNING_ALERTS": "true"}
    morning_pass(alerts, monkeypatch, morning_view(fulfilment="missing"), sends)
    assert alerts.check(config, now=MORNING_DEADLINE + 10)
    assert alerts.check(config, now=MORNING_DEADLINE + 130)
    assert sends == ["Jo's morning brief is missing"]
    morning_pass(alerts, monkeypatch, morning_view(fulfilment="late"), sends)
    assert alerts.check(config, now=MORNING_DEADLINE + 720)
    assert sends == ["Jo's morning brief is missing", "Jo's morning brief arrived late"]
    record = alerts.read_state()["jo_morning"]
    assert record["enabled"] is True and record["error"] is None and record["checked_at"]
    assert [(n["kind"], n["recovered"], n["outcome"]) for n in record["notices"]["2026-10-20"]] == [("brief", False, "sent"), ("brief", True, "sent")]


def test_yesterdays_unrecovered_miss_ends_silently_and_old_notices_age_out(alerts, monkeypatch):
    sends, config = [], {"JO_MORNING_ALERTS": "true"}
    morning_pass(alerts, monkeypatch, morning_view(fulfilment="missing"), sends)
    alerts.check(config, now=MORNING_DEADLINE + 10)
    tomorrow = MORNING_DEADLINE + 86400 - 3600
    morning_pass(alerts, monkeypatch, morning_view(fulfilment="pending", day="2026-10-21"), sends)
    alerts.check(config, now=tomorrow)
    assert sends == ["Jo's morning brief is missing"]
    assert not [key for key in alerts.read_state()["conditions"] if "2026-10-20" in key]
    alerts.check(config, now=MORNING_DEADLINE + 8 * 86400)
    assert "2026-10-20" not in alerts.read_state()["jo_morning"]["notices"]


def test_uncertain_morning_send_is_recorded_and_never_resent(alerts, monkeypatch):
    sends, config = [], {"JO_MORNING_ALERTS": "true"}
    # A bare TimeoutError is urlopen waiting for ntfy's reply: the request may have arrived.
    morning_pass(alerts, monkeypatch, morning_view(fulfilment="missing"), sends, fail=TimeoutError("timed out"))
    assert alerts.check(config, now=MORNING_DEADLINE + 10)
    morning_pass(alerts, monkeypatch, morning_view(fulfilment="missing"), sends)
    alerts.check(config, now=MORNING_DEADLINE + 130)
    assert sends == []
    assert [n["outcome"] for n in alerts.read_state()["jo_morning"]["notices"]["2026-10-20"]] == ["unknown"]


def test_failed_morning_send_is_retried_and_reported(alerts, monkeypatch):
    sends, config = [], {"JO_MORNING_ALERTS": "true"}
    # urlopen wraps a connect timeout in URLError: nothing reached ntfy, so it is retried.
    for failure in (alerts.URLError(ConnectionRefusedError("refused")), alerts.URLError(TimeoutError("timed out"))):
        morning_pass(alerts, monkeypatch, morning_view(fulfilment="missing"), sends, fail=failure)
        assert alerts.check(config, now=MORNING_DEADLINE + 10) is False
        assert alerts.check(config, now=MORNING_DEADLINE + 130) is False
    morning_pass(alerts, monkeypatch, morning_view(fulfilment="missing"), sends)
    assert alerts.check(config, now=MORNING_DEADLINE + 250)
    assert sends == ["Jo's morning brief is missing"]
    log = alerts.read_state()["jo_morning"]["notices"]["2026-10-20"]
    assert [(n["outcome"], n["attempts"]) for n in log] == [("sent", 5)]  # retries collapse into one line
    assert alerts.uncertain(alerts.URLError("ntfy could not be reached (ReadTimeout)"))
    assert not alerts.uncertain(alerts.URLError("ntfy could not be reached (ConnectTimeout)"))
    assert not alerts.uncertain(alerts.HTTPError("https://ntfy.sh/", 503, "unavailable", {}, None))


def test_morning_watchdog_is_opt_in_and_skips_an_unreachable_api(alerts, monkeypatch):
    sends, reads = [], []
    morning_pass(alerts, monkeypatch, morning_view(fulfilment="missing"), sends)
    monkeypatch.setattr(alerts, "get", lambda path: reads.append(path) or morning_view(fulfilment="missing"))
    alerts.check({}, now=MORNING_DEADLINE + 10)
    assert reads == [] and sends == [] and alerts.read_state()["jo_morning"]["enabled"] is False
    monkeypatch.setattr(alerts, "observe", lambda since: {"api": alerts.Problem("down", "x", 300)})
    alerts.check({"JO_MORNING_ALERTS": "true"}, now=MORNING_DEADLINE + 20)
    assert reads == []
    monkeypatch.setattr(alerts, "observe", lambda since: {"api": None})
    monkeypatch.setattr(alerts, "get", lambda path: (_ for _ in ()).throw(OSError("refused")))
    alerts.check({"JO_MORNING_ALERTS": "true"}, now=MORNING_DEADLINE + 30)
    assert alerts.read_state()["jo_morning"]["error"] == "Morning status unreadable (OSError)"
    alerts.check({"JO_MORNING_ALERTS": "true"}, now=MORNING_DEADLINE + 30 + alerts.MORNING_STATUS_GRACE)
    assert sends == ["Morning brief status unreadable"]


def test_disabled_automation_ends_quietly_but_broken_settings_alert(alerts, monkeypatch):
    sends, config = [], {"JO_MORNING_ALERTS": "true"}
    morning_pass(alerts, monkeypatch, morning_view(fulfilment="missing"), sends)
    alerts.check(config, now=MORNING_DEADLINE + 10)
    morning_pass(alerts, monkeypatch, morning_view(fulfilment="not_expected", enabled=False, configuration_error=True), sends)
    alerts.check(config, now=MORNING_DEADLINE + 130)
    alerts.check(config, now=MORNING_DEADLINE + 130 + alerts.API_GRACE)
    assert sends == ["Jo's morning brief is missing", "Morning brief automation can't load its settings"]
    assert "jo_morning:2026-10-20:brief" in alerts.read_state()["conditions"]  # still missing, not "arrived"
    morning_pass(alerts, monkeypatch, morning_view(fulfilment="not_expected", enabled=False), sends)
    alerts.check(config, now=MORNING_DEADLINE + 900)
    assert len(sends) == 2 and not [k for k in alerts.read_state()["conditions"] if k.startswith("jo_morning:")]


def test_weekend_keeps_an_unresolved_calendar_condition(alerts, monkeypatch):
    sends, config = [], {"JO_MORNING_ALERTS": "true"}
    friday = datetime(2026, 10, 23, 22, 0, tzinfo=timezone.utc).timestamp()
    morning_pass(alerts, monkeypatch, morning_view(day="2026-10-23", last_pass=friday, status="calendar_unavailable"), sends)
    alerts.check(config, now=friday)
    later = friday + alerts.MORNING_CALENDAR_GRACE
    morning_pass(alerts, monkeypatch, morning_view(day="2026-10-23", last_pass=later, status="calendar_unavailable"), sends)
    alerts.check(config, now=later)
    saturday = datetime(2026, 10, 24, 4, 30, tzinfo=timezone.utc).timestamp()
    morning_pass(alerts, monkeypatch, morning_view(day="2026-10-24", last_pass=saturday, status="calendar_unavailable", fulfilment="not_expected"), sends)
    alerts.check(config, now=saturday)
    assert sends == ["Market calendar unavailable for the morning brief"]


# Scheduled market-read watchdog: 2026-10-21 is a Wednesday; 15:15 UTC is the 11:00 ET slot's 11:15 deadline.
READ_DEADLINE = datetime(2026, 10, 21, 15, 15, tzinfo=timezone.utc).timestamp()


def market_reads_view(delivery="pending", last_ingest=READ_DEADLINE, enabled=True, outbox=True, day="2026-10-21", packet="published"):
    iso = lambda value: datetime.fromtimestamp(value, timezone.utc).isoformat() if value else None  # noqa: E731
    slot = {"slot": "11:00", "scheduled_at": f"{day}T15:00:00+00:00", "deadline": f"{day}T15:15:00+00:00",
            "delivery": delivery, "packet": {"status": packet}}
    return {"market_watch_enabled": enabled,
            "importer": {"running": True, "outbox_configured": outbox, "last_ingest": iso(last_ingest)},
            "sessions": [{"session_date": day, "slots": [slot]}]}


def test_market_read_conditions_alert_only_on_a_judged_miss(alerts):
    now, key = READ_DEADLINE + 90, "jo_market_read:2026-10-21:1100"
    missing = alerts.market_read_problems(market_reads_view("missing"), "2026-10-21", now)
    assert missing[key].title == "Jo's 11:00 AM market read is missing" and missing[key].grace == 0
    assert "by 11:15 AM ET" in missing[key].message and missing[key].recovered == "Jo's 11:00 AM market read arrived late"
    assert "packet" not in missing[key].message
    failed = alerts.market_read_problems(market_reads_view("missing", packet="failed"), "2026-10-21", now)
    assert "packet for this read failed" in failed[key].message
    for done in ("on_time", "late", "pending", "not_expected"):
        assert alerts.market_read_problems(market_reads_view(done), "2026-10-21", now)[key] is None
    assert key not in alerts.market_read_problems(market_reads_view("unknown"), "2026-10-21", now)
    # A stale importer or no outbox: slots stay unknown and the gap itself is the condition.
    for view in (market_reads_view("missing", last_ingest=now - 600), market_reads_view("missing", last_ingest=None),
                 market_reads_view("missing", outbox=False)):
        stale = alerts.market_read_problems(view, "2026-10-21", now)
        assert list(stale) == ["jo_market_read:importer"] and stale["jo_market_read:importer"].grace == alerts.API_GRACE
    # A day without a session row (weekend, outside the list) says nothing about slots.
    assert alerts.market_read_problems(market_reads_view("missing"), "2026-10-24", now) == {"jo_market_read:importer": None}


def market_pass(alerts, monkeypatch, view, sends, fail=None):
    morning_pass(alerts, monkeypatch, view, sends, fail)


def test_missed_market_read_alerts_once_then_late_recovery_is_logged(alerts, monkeypatch):
    sends, config = [], {"JO_MARKET_READ_ALERTS": "true"}
    market_pass(alerts, monkeypatch, market_reads_view("missing", last_ingest=READ_DEADLINE + 80), sends)
    assert alerts.check(config, now=READ_DEADLINE + 90)
    market_pass(alerts, monkeypatch, market_reads_view("missing", last_ingest=READ_DEADLINE + 200), sends)
    assert alerts.check(config, now=READ_DEADLINE + 210)
    assert sends == ["Jo's 11:00 AM market read is missing"]
    market_pass(alerts, monkeypatch, market_reads_view("late", last_ingest=READ_DEADLINE + 400), sends)
    assert alerts.check(config, now=READ_DEADLINE + 410)
    assert sends == ["Jo's 11:00 AM market read is missing", "Jo's 11:00 AM market read arrived late"]
    record = alerts.read_state()["jo_market_reads"]
    assert record["enabled"] is True and record["error"] is None
    assert [(n["kind"], n["recovered"], n["outcome"]) for n in record["notices"]["2026-10-21"]] == [("1100", False, "sent"), ("1100", True, "sent")]
    assert alerts.read_state()["jo_morning"]["enabled"] is False  # the morning watchdog stays separate


def test_market_read_watchdog_is_opt_in_and_off_with_market_watch(alerts, monkeypatch):
    sends, reads = [], []
    market_pass(alerts, monkeypatch, None, sends)
    monkeypatch.setattr(alerts, "get", lambda path: reads.append(path) or market_reads_view("missing", last_ingest=READ_DEADLINE + 80))
    alerts.check({}, now=READ_DEADLINE + 90)
    assert reads == [] and sends == [] and alerts.read_state()["jo_market_reads"]["enabled"] is False
    config = {"JO_MARKET_READ_ALERTS": "true"}
    alerts.check(config, now=READ_DEADLINE + 90)
    assert reads == ["/jo/market-reads"] and sends == ["Jo's 11:00 AM market read is missing"]
    # Market watch switched off on the server: open conditions end silently.
    monkeypatch.setattr(alerts, "get", lambda path: market_reads_view("missing", enabled=False))
    alerts.check(config, now=READ_DEADLINE + 210)
    assert len(sends) == 1 and not [k for k in alerts.read_state()["conditions"] if k.startswith("jo_market_read:")]


def test_uncertain_market_read_send_is_never_resent_and_unreadable_status_alerts(alerts, monkeypatch):
    sends, config = [], {"JO_MARKET_READ_ALERTS": "true"}
    market_pass(alerts, monkeypatch, market_reads_view("missing", last_ingest=READ_DEADLINE + 80), sends, fail=TimeoutError("timed out"))
    assert alerts.check(config, now=READ_DEADLINE + 90)
    market_pass(alerts, monkeypatch, market_reads_view("missing", last_ingest=READ_DEADLINE + 200), sends)
    alerts.check(config, now=READ_DEADLINE + 210)
    assert sends == []
    assert [n["outcome"] for n in alerts.read_state()["jo_market_reads"]["notices"]["2026-10-21"]] == ["unknown"]
    monkeypatch.setattr(alerts, "get", lambda path: (_ for _ in ()).throw(OSError("refused")))
    alerts.check(config, now=READ_DEADLINE + 300)
    assert alerts.read_state()["jo_market_reads"]["error"] == "Market read status unreadable (OSError)"
    alerts.check(config, now=READ_DEADLINE + 300 + alerts.MARKET_READ_STATUS_GRACE)
    assert sends == ["Market read status unreadable"]
    assert "jo_market_read:2026-10-21:1100" in alerts.read_state()["conditions"]  # unknown, not resolved


def test_yesterdays_market_read_miss_ends_silently(alerts, monkeypatch):
    sends, config = [], {"JO_MARKET_READ_ALERTS": "true"}
    market_pass(alerts, monkeypatch, market_reads_view("missing", last_ingest=READ_DEADLINE + 80), sends)
    alerts.check(config, now=READ_DEADLINE + 90)
    tomorrow = READ_DEADLINE + 86400 - 3600
    market_pass(alerts, monkeypatch, market_reads_view("pending", last_ingest=tomorrow, day="2026-10-22"), sends)
    alerts.check(config, now=tomorrow)
    assert sends == ["Jo's 11:00 AM market read is missing"]
    assert not [key for key in alerts.read_state()["conditions"] if "2026-10-21" in key]


def test_market_read_flag_reaches_the_config_from_systemd(alerts, monkeypatch, tmp_path):
    monkeypatch.setattr(alerts, "ENV_FILE", tmp_path / "absent.env")
    monkeypatch.setenv("JO_MARKET_READ_ALERTS", "true")
    monkeypatch.setenv("JO_MORNING_ALERTS", "true")
    config = alerts.load_config()
    assert config["JO_MARKET_READ_ALERTS"] == "true" and config["JO_MORNING_ALERTS"] == "true"
