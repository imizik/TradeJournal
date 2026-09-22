#!/usr/bin/env python3
"""Exercise the real release on a fresh, disposable GitHub Ubuntu runner only."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request

import control
from build import package

URL = "postgresql+psycopg://tj:tj@127.0.0.1:5432/tj_deployment"
IDENTITY = "127.0.0.1:5432/tj_deployment"


def request(path, method="GET"):
    req = urllib.request.Request(f"http://127.0.0.1:3000/api/backend{path}", method=method)
    with urllib.request.urlopen(req, timeout=10) as response:
        return json.load(response)


def wait_for(predicate, timeout=40):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(1)
    raise AssertionError("Condition did not become true")


def digest(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    args = parser.parse_args()
    if os.geteuid() != 0 or os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("TJ_DISPOSABLE_RUNNER") != "1":
        parser.error("Requires root and an explicitly disposable GitHub Actions runner")
    if control.ROOT.exists() or control.STATE.exists() or control.CONFIG.exists():
        parser.error("Refusing an existing TradeJournal installation")
    os.umask(0o022)
    archive = args.archive.resolve()
    release = control.install(archive, digest(archive))
    (control.CONFIG / "backend.env").write_text(
        f"DATABASE_URL={URL}\nAPP_ENV=deployment-ci\nFRONTEND_PUBLIC_URL=http://127.0.0.1:3000\n"
        "WEBULL_LISTENER_AUTOSTART=false\nGMAIL_WATCH_AUTOSTART=false\nTRADINGVIEW_ANALYSIS_AUTOSTART=false\n"
    )
    (control.CONFIG / "migration.env").write_text(f"MIGRATION_DATABASE_URL={URL}\n")
    # Use the shipped CLI for each operation, including its confirmation gate.
    controller = [sys.executable, str(release / "deploy/control.py")]

    def cli(*args):
        control.run(*controller, *args)

    try:
        cli("migrate", release.name, "--confirm-database", IDENTITY)
        control.run("runuser", "-u", "tradejournal", "--", release / "backend/.venv/bin/python", "scripts/seed_dev_data.py", "--database-url", URL, cwd=release / "backend", env={**os.environ, "DATABASE_URL": URL, "MIGRATION_DATABASE_URL": URL, "PYTHONDONTWRITEBYTECODE": "1"})
        cli("activate", release.name, "--confirm-database", IDENTITY)
        assert request("/stats")["total_trades"] == 6
        control.run("systemctl", "is-enabled", *control.SERVICES, *control.TIMERS)
        control.run("systemctl", "start", "tradejournal-backup.service")
        latest_backup = control.BACKUPS / "latest"
        assert latest_backup.is_symlink()
        control.run(
            release / "backend/.venv/bin/python",
            release / "deploy/backup.py",
            "verify",
            latest_backup.resolve(),
        )
        # The backend/frontend must not acquire a wildcard listener.
        sockets = control.run("ss", "-ltnH", capture_output=True, text=True).stdout
        for port in (3000, 8080):
            listeners = [line.split()[3] for line in sockets.splitlines() if line.split()[3].endswith(f":{port}")]
            assert listeners == [f"127.0.0.1:{port}"], listeners

        def pid():
            return control.run("systemctl", "show", "tradejournal-worker@sync", "--property=MainPID", "--value", capture_output=True, text=True).stdout.strip()

        worker_pid = pid()
        # Pause the executor so a POST is provably durable before API restart.
        control.run("systemctl", "kill", "--signal=SIGSTOP", "tradejournal-worker@sync")
        job_id = request("/sync/jobs/fill_import_check/run", "POST")["run_id"]

        def job_status():
            return next(row["status"] for row in request("/sync/runs") if row["id"] == job_id)

        assert job_status() == "queued"
        control.run("systemctl", "restart", "tradejournal-api")
        control.health(release, IDENTITY)
        assert pid() == worker_pid and job_status() == "queued"
        control.run("systemctl", "kill", "--signal=SIGCONT", "tradejournal-worker@sync")
        wait_for(lambda: job_status() == "succeeded")
        control.run("systemctl", "kill", "--signal=SIGKILL", "tradejournal-worker@sync")
        wait_for(lambda: pid() not in {"0", worker_pid})
        job_id = request("/sync/jobs/fill_import_check/run", "POST")["run_id"]
        wait_for(lambda: job_status() == "succeeded")

        sentinel = control.STATE / "data/deployment-smoke-state.txt"
        sentinel.write_text("persistent\n")
        # Repackage the same code with a second identity to exercise a real
        # offline install, symlink switch, rollback and persistent state reuse.
        with tempfile.TemporaryDirectory() as scratch:
            scratch = Path(scratch)
            with tarfile.open(archive) as bundle:
                bundle.extractall(scratch, filter="data")
            second = scratch / f"{release.name}-second"
            (scratch / release.name).rename(second)
            for relative in ("release.json", "frontend/public/deployment.json"):
                metadata = json.loads((second / relative).read_text())
                metadata["release_id"] = second.name
                (second / relative).write_text(json.dumps(metadata))
            second_archive = package(second, scratch)
            cli("install", second_archive, "--sha256", digest(second_archive))
            cli("activate", second.name, "--confirm-database", IDENTITY)
            assert sentinel.read_text() == "persistent\n"
            cli("rollback", "--confirm-database", IDENTITY)
            assert control.current() == release
            assert sentinel.read_text() == "persistent\n"
        # Boot wiring is inspected; a stop/start tests full process recovery.
        # This is deliberately not labelled a physical VPS reboot test.
        control.stop_services()
        control.start_services(release, IDENTITY)
        assert request("/stats")["total_trades"] == 6
        assert job_status() == "succeeded"
        print("Native deployment smoke passed: install, migration, proxy, workers, backup, timers, API restart, crash restart, upgrade, rollback, persistent state and full restart")
    finally:
        subprocess.run(["systemctl", "kill", "--signal=SIGCONT", "tradejournal-worker@sync"], check=False)
        subprocess.run(["journalctl", "--no-pager", "-n", "150", *[f"--unit={unit}" for unit in control.SERVICES]], check=False)
        control.stop_services()


if __name__ == "__main__":
    main()
