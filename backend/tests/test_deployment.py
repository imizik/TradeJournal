"""Destructive deployment operations are exercised only against tmp_path/fakes.

Native systemd and the packaged application have a separate Ubuntu CI smoke.
"""

import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
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


def test_every_managed_unit_ships_with_the_release():
    control = load("control")
    systemd = Path(__file__).resolve().parents[2] / "deploy" / "systemd"
    assert "tradejournal-worker@gmail" in control.SERVICES
    assert "tradejournal-sync-pipeline.timer" in control.TIMERS
    assert "tradejournal-offsite-backup.timer" in control.TIMERS
    assert "tradejournal-alerts.timer" in control.TIMERS
    for name in control.OPTIONAL_UNITS:
        assert (systemd / name).is_file(), name
    timer = (systemd / "tradejournal-sync-pipeline.timer").read_text()
    assert "OnCalendar=*-*-* 08:00:00 America/New_York" in timer
    assert "OnCalendar=*-*-* 17:00:00 America/New_York" in timer


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


@pytest.fixture
def ingress(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "deploy"))
    return load("ingress")


def ingress_config():
    return {
        "TRADINGVIEW_INGRESS_ENABLED": "true",
        "TRADINGVIEW_DATABASE_URL": "postgresql+psycopg://ingress:secret@db/journal",
        "TRADINGVIEW_WEBHOOK_TOKEN": "dedicated-test-token-" * 3,
    }, {
        "DATABASE_URL": "postgresql+psycopg://app:other@db:5432/journal",
        "TRADINGVIEW_ANALYSIS_AUTOSTART": "true",
        "ALPACA_API_KEY": "fake-key", "ALPACA_API_SECRET": "fake-secret",
    }


def test_ingress_preflight_is_opt_in_and_accepts_separate_matching_role(ingress):
    assert not ingress.validate_settings({}, {})
    assert not ingress.validate_settings({"TRADINGVIEW_INGRESS_ENABLED": "false"}, {})
    settings, private = ingress_config()
    assert ingress.validate_settings(settings, private)


@pytest.mark.parametrize("change", [
    {"TRADINGVIEW_INGRESS_ENABLED": "yes"},
    {"TRADINGVIEW_WEBHOOK_TOKEN": "short"},
    {"TRADINGVIEW_DATABASE_URL": "sqlite:///scratch.db"},
    {"TRADINGVIEW_DATABASE_URL": "postgresql+psycopg://app:secret@db/journal"},
    {"TRADINGVIEW_DATABASE_URL": "postgresql+psycopg://ingress:secret@other/journal"},
    {"TRADINGVIEW_DATABASE_URL": "postgresql+psycopg://ingress:secret@db/other"},
    {"TRADINGVIEW_DATABASE_URL": "postgresql+psycopg://ingress:secret@db/journal?host=other"},
    {"DATABASE_URL": "private-secret-must-never-appear"},
    {"ALPACA_API_KEY": "private-secret-must-never-appear"},
])
def test_ingress_rejects_unsafe_configuration_without_disclosing_it(ingress, change):
    settings, private = ingress_config()
    settings.update(change)
    with pytest.raises(ValueError) as error:
        ingress.validate_settings(settings, private)
    assert "secret" not in str(error.value)


@pytest.mark.parametrize("change", [
    {"TRADINGVIEW_ANALYSIS_AUTOSTART": "false"},
    {"ALPACA_API_SECRET": ""},
])
def test_ingress_requires_configured_analysis_worker(ingress, change):
    settings, private = ingress_config()
    private.update(change)
    with pytest.raises(ValueError):
        ingress.validate_settings(settings, private)


def test_ingress_preflight_failure_leaves_healthy_release_running(control, monkeypatch):
    old = control.release_path("old")
    old.mkdir()
    control.atomic_link(old, control.ROOT / "current")
    events = []
    monkeypatch.setattr(control, "database", lambda *_: None)
    monkeypatch.setattr(control, "stop_services", lambda: events.append("stopped"))

    def fail(_release):
        raise RuntimeError("Ingress database/schema/role check failed")

    monkeypatch.setattr(control, "ingress_enabled", fail)
    with pytest.raises(RuntimeError, match="Ingress"):
        control.activate(control.release_path("new"), "scratch")
    assert control.current() == old
    assert not events


def test_ingress_launcher_scrubs_private_environment_and_binds_loopback(tmp_path, monkeypatch):
    launch = load("launch")
    (tmp_path / "backend").mkdir()
    (tmp_path / "release.json").write_text('{"release_id":"test"}')
    monkeypatch.setattr(launch, "RELEASE", tmp_path)
    monkeypatch.setattr(launch.sys, "argv", ["launch.py", "ingress"])
    settings, _ = ingress_config()
    for key, value in settings.items():
        monkeypatch.setenv(key, value)
    for key in ("DATABASE_URL", "MIGRATION_DATABASE_URL", "ALPACA_API_KEY", "PGHOST", "PYTHONPATH"):
        monkeypatch.setenv(key, "never-inherit")
    for key in ("TRADEJOURNAL_RELEASE", "PYTHONDONTWRITEBYTECODE"):
        monkeypatch.setenv(key, os.environ.get(key, ""))
    monkeypatch.chdir(tmp_path)
    calls = []
    monkeypatch.setattr(launch.os, "execve", lambda executable, args, env: calls.append((args, env)))
    launch.main()
    args, environment = calls[0]
    assert "app.tradingview_ingress:app" in args
    assert args[-5:] == ["--host", "127.0.0.1", "--port", "8090", "--no-access-log"]
    assert "never-inherit" not in environment.values()
    assert environment["TRADINGVIEW_WEBHOOK_TOKEN"] == settings["TRADINGVIEW_WEBHOOK_TOKEN"]


@pytest.mark.parametrize("enabled", [False, True])
def test_service_lifecycle_respects_ingress_opt_in(control, tmp_path, monkeypatch, enabled):
    release = tmp_path / "release"
    unit_dir = release / "deploy/systemd"
    unit_dir.mkdir(parents=True)
    (unit_dir / "tradejournal-ingress.service").touch()
    monkeypatch.setattr(control, "ingress_enabled", lambda _: enabled)
    monkeypatch.setattr(control, "install_units", lambda _: None)
    monkeypatch.setattr(control, "health", lambda *_: None)
    monkeypatch.setattr(control.time, "sleep", lambda _: None)
    calls = []
    monkeypatch.setattr(control, "run", lambda *args: calls.append(args))
    monkeypatch.setattr(control, "ingress_health", lambda: calls.append(("ingress-ready",)))
    control.start_services(release, "scratch")
    if enabled:
        assert ("systemctl", "enable", "--now", "tradejournal-ingress") in calls
        assert ("ingress-ready",) in calls
    else:
        assert ("systemctl", "disable", "--now", "tradejournal-ingress") in calls
        assert ("ingress-ready",) not in calls


def test_rollback_to_release_without_ingress_removes_its_boot_unit(control, tmp_path, monkeypatch):
    units = tmp_path / "units"
    units.mkdir()
    (units / "tradejournal-ingress.service").touch()
    release = tmp_path / "old"
    release.mkdir()
    monkeypatch.setattr(control, "UNITS", units)
    monkeypatch.setattr(control, "run", lambda *_: None)
    calls = []
    monkeypatch.setattr(control.subprocess, "run", lambda args, **_: calls.append(args))
    assert not control.ingress_enabled(release)
    control.install_units(release)
    assert ["systemctl", "disable", "--now", "tradejournal-ingress.service"] in calls
    assert not (units / "tradejournal-ingress.service").exists()


def test_backups_preserve_optional_ingress_credentials(tmp_path, monkeypatch):
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
