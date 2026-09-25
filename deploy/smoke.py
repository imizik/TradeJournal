#!/usr/bin/env python3
"""Exercise the real release on a fresh, disposable GitHub Ubuntu runner only."""

import argparse
import hashlib
import http.server
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import control
from build import package

URL = "postgresql+psycopg://tj:tj@127.0.0.1:5432/tj_deployment"
IDENTITY = "127.0.0.1:5432/tj_deployment"
INGRESS_TOKEN = "ci-only-webhook-token-never-use-in-production"
# The commit the repackaged second build claims, as a newer merge would.
NEXT_COMMIT = "5" * 40


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


def webhook(port=8090, token=INGRESS_TOKEN):
    # Old on purpose: exercise the real durable worker without provider calls.
    payload = {
        "v": 1, "indicator_version": "deployment-smoke", "symbol": "AAPL",
        "timeframe": "5", "setup": "orb_break", "side": "long", "price": 100,
        "bar_time_ms": 1737561600000,
        "alert_id": "v1:deployment-smoke:AAPL:5:1737561600000:orb_break:long",
    }
    req = urllib.request.Request(
        f"http://localhost:{port}/tradingview/webhook?token={token}",
        data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=3) as response:
        return json.load(response)


def status(url):
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code


def check_webhook_proxy(release):
    # Exercise the shipped routing/logging through a real Caddy process.
    # Local HTTP fixtures avoid public DNS/ACME calls in disposable CI.
    with tempfile.TemporaryDirectory() as scratch:
        config = Path(scratch) / "Caddyfile"
        config.write_text((release / "deploy/Caddyfile.tradingview.example").read_text()
                          .replace("https://alerts.example.com", "http://localhost:8091")
                          .replace("http://alerts.example.com", "http://localhost:8092")
                          .replace("203.0.113.10", "127.0.0.1"))
        control.run("caddy", "validate", "--config", config, "--adapter", "caddyfile")
        log = Path(scratch) / "caddy.log"
        with log.open("w") as output:
            process = subprocess.Popen(["caddy", "run", "--config", str(config), "--adapter", "caddyfile"], stdout=output, stderr=output)
            try:
                def ready():
                    try:
                        return status("http://localhost:8091/health") == 404
                    except OSError:
                        return False
                wait_for(ready)
                assert webhook(8091)["dup"] is True
                for path in ("/", "/health", "/docs", "/openapi.json", "/tradingview/alerts", "/api/backend/health"):
                    assert status(f"http://localhost:8091{path}") == 404
                assert status("http://localhost:8092/tradingview/webhook") == 404
                control.run("systemctl", "stop", control.INGRESS_SERVICE)
                try:
                    webhook(8091)
                    raise AssertionError("Stopped ingress unexpectedly accepted a webhook")
                except urllib.error.HTTPError as exc:
                    assert exc.code == 502
            finally:
                process.terminate()
                process.wait(timeout=10)
                control.run("systemctl", "start", control.INGRESS_SERVICE)
                control.ingress_health()
        assert INGRESS_TOKEN not in log.read_text()


class FakeGitHub(http.server.ThreadingHTTPServer):
    """GitHub's releases API and asset downloads, plus an ntfy endpoint.

    Serves one published build of NEXT_COMMIT from local files, so the shipped
    autodeploy unit can run its real download, install and activation path.
    """

    def __init__(self, files):
        self.files = files
        self.notes = []
        super().__init__(("127.0.0.1", 0), FakeGitHubHandler)

    @property
    def url(self):
        return f"http://127.0.0.1:{self.server_port}"


class FakeGitHubHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        path = urllib.parse.urlsplit(self.path).path
        files = self.server.files
        if path == "/repos/smoke/tradejournal/releases":
            body = json.dumps([{
                "tag_name": f"build-{NEXT_COMMIT[:12]}", "draft": False, "published_at": "2026-01-01T00:00:00Z",
                "target_commitish": NEXT_COMMIT, "body": "Deployment smoke build\n",
                "assets": [{"name": name, "browser_download_url": f"{self.server.url}/download/{name}"} for name in files],
            }]).encode()
        elif path.startswith("/repos/smoke/tradejournal/compare/"):
            body = json.dumps({"status": "ahead"}).encode()
        elif path.startswith("/download/") and path.removeprefix("/download/") in files:
            source = files[path.removeprefix("/download/")]
            self.send_response(200)
            self.send_header("Content-Length", str(source.stat().st_size))
            self.end_headers()
            with source.open("rb") as handle:
                shutil.copyfileobj(handle, self.wfile)
            return
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0))).decode()
        self.server.notes.append((self.headers.get("Title"), body))
        self.send_response(200)
        self.end_headers()

    def log_message(self, *_args):
        pass


def publish(second, second_archive):
    """Lay out the build the way the Release workflow publishes it."""
    controller = second_archive.parent / "tradejournal-deploy.py"
    shutil.copyfile(second / "deploy/control.py", controller)
    files = {path.name: path for path in (second_archive, controller)}
    sums = second_archive.parent / "SHA256SUMS"
    sums.write_text("".join(f"{digest(path)}  {name}\n" for name, path in files.items()))
    github = FakeGitHub({**files, "SHA256SUMS": sums})
    threading.Thread(target=github.serve_forever, daemon=True).start()
    config = control.CONFIG / "autodeploy.env"
    config.write_text(
        f"AUTODEPLOY_ENABLED=true\nAUTODEPLOY_REPOSITORY=smoke/tradejournal\nAUTODEPLOY_CONFIRM_DATABASE={IDENTITY}\n"
        f"AUTODEPLOY_HOLD_WINDOW=off\nAUTODEPLOY_API_URL={github.url}\nNTFY_URL={github.url}/ntfy\n"
    )
    config.chmod(0o600)
    return github


def autodeploy_pass():
    """Run the unit the timer starts; return the decision it recorded."""
    # A oneshot start returns when the pass ends, and fails if the pass failed.
    # A Gmail check can hold the sync lane for a moment; the pass then reports
    # that it is waiting and records nothing, and the caller tries again.
    control.run("systemctl", "start", f"{control.AUTODEPLOY}.service")
    state = control.STATE / "autodeploy/state.json"
    return json.loads(state.read_text()) if state.exists() else {}


def enable_ingress(release, cli):
    sql = """
        CREATE ROLE tj_ingress LOGIN PASSWORD 'ci-ingress-only';
        GRANT USAGE ON SCHEMA public TO tj_ingress;
        GRANT SELECT, INSERT, UPDATE ON tradingview_alert TO tj_ingress;
    """
    control.run("psql", "-h", "127.0.0.1", "-U", "tj", "-d", "tj_deployment", "-v", "ON_ERROR_STOP=1",
                input=sql, text=True, env={**os.environ, "PGPASSWORD": "tj"})
    config = control.CONFIG / "backend.env"
    config.write_text(config.read_text().replace("TRADINGVIEW_ANALYSIS_AUTOSTART=false", "TRADINGVIEW_ANALYSIS_AUTOSTART=true")
                      + "ALPACA_API_KEY=ci-placeholder\nALPACA_API_SECRET=ci-placeholder\n")
    (control.CONFIG / "tradingview.env").write_text(
        "TRADINGVIEW_INGRESS_ENABLED=true\n"
        "TRADINGVIEW_DATABASE_URL=postgresql+psycopg://tj_ingress:ci-ingress-only@127.0.0.1:5432/tj_deployment\n"
        f"TRADINGVIEW_WEBHOOK_TOKEN={INGRESS_TOKEN}\n"
    )
    cli("activate", release.name, "--confirm-database", IDENTITY)
    control.run("systemctl", "is-enabled", control.INGRESS_SERVICE)
    accepted = webhook()
    assert accepted["dup"] is False
    assert webhook()["dup"] is True
    try:
        webhook(token="wrong")
        raise AssertionError("Unauthenticated webhook accepted")
    except urllib.error.HTTPError as exc:
        assert exc.code == 401
    wait_for(lambda: any(row["alert_id"] == accepted["alert_id"] and row["analysis_status"] == "skipped"
                         for row in request("/tradingview/alerts")))
    # The public OS identity cannot read private runtime data or config.
    for path in (control.CONFIG / "backend.env", control.STATE / "oauth", control.STATE / "data"):
        denied = subprocess.run(["runuser", "-u", "tradejournal-ingress", "--", "test", "-r", str(path)], check=False)
        assert denied.returncode != 0
    check_webhook_proxy(release)
    logs = control.run("journalctl", "--no-pager", "--unit", control.INGRESS_SERVICE, capture_output=True, text=True).stdout
    assert INGRESS_TOKEN not in logs


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
        assert subprocess.run(["systemctl", "is-active", "--quiet", control.INGRESS_SERVICE], check=False).returncode != 0
        enable_ingress(release, cli)
        control.run("systemctl", "is-enabled", *control.SERVICES, *control.TIMERS)
        # A real 08:00/17:00 New York run would make the sync POSTs below
        # return 409. Enablement is what this smoke asserts.
        control.run("systemctl", "stop", "tradejournal-sync-pipeline.timer")
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
        for port in (3000, 8080, 8090):
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
                metadata["commit"] = NEXT_COMMIT
                (second / relative).write_text(json.dumps(metadata))
            second_archive = package(second, scratch)
            # Upgrade the unattended way: the shipped autodeploy unit polls a
            # stand-in for GitHub, verifies checksums, installs the controller
            # and the release, and activates it.
            github = publish(second, second_archive)
            try:
                for _ in range(12):
                    if autodeploy_pass().get("outcome") == "deployed":
                        break
                    time.sleep(5)
                assert control.current().name == second.name
                assert Path("/usr/local/sbin/tradejournal-deploy").read_bytes() == (second / "deploy/control.py").read_bytes()
                assert sentinel.read_text() == "persistent\n"
                assert webhook()["dup"] is True
                cli("rollback", "--confirm-database", IDENTITY)
                assert control.current() == release
                # The next pass must not put back the build an operator left.
                assert autodeploy_pass()["outcome"] == "rolled-back"
                assert control.current() == release
                assert [title for title, _ in github.notes] == ["TradeJournal updated", "TradeJournal update paused"]
            finally:
                github.shutdown()
                (control.CONFIG / "autodeploy.env").unlink()
            assert sentinel.read_text() == "persistent\n"
            assert webhook()["dup"] is True
            # Only two releases exist, both current or previous: nothing to remove.
            cli("prune", "--keep", "0")
            assert release.is_dir() and control.release_path(second.name).is_dir()
        # Boot wiring is inspected; a stop/start tests full process recovery.
        # This is deliberately not labelled a physical VPS reboot test.
        control.stop_services()
        control.start_services(release, IDENTITY)
        assert request("/stats")["total_trades"] == 6
        assert job_status() == "succeeded"
        assert webhook()["dup"] is True
        print("Native deployment smoke passed: install, migration, proxy, workers, restricted ingress, webhook dedupe, analysis, token-safe proxy logs, backup, timers, API restart, crash restart, unattended upgrade, rollback that stays rolled back, prune, persistent state and full restart")
    finally:
        subprocess.run(["systemctl", "kill", "--signal=SIGCONT", "tradejournal-worker@sync"], check=False)
        subprocess.run(["journalctl", "--no-pager", "-n", "150", *[f"--unit={unit}" for unit in [*control.SERVICES, control.INGRESS_SERVICE, control.AUTODEPLOY]]], check=False)
        control.stop_services()


if __name__ == "__main__":
    main()
