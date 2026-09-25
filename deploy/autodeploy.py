#!/usr/bin/env python3
"""Install the newest verified main build on this server, unattended.

The server is private to the tailnet, so GitHub cannot push to it; a systemd
timer runs this every five minutes and pulls instead. The Release workflow
publishes a build-<commit> GitHub release only after CI and the Deployment
package smoke test both passed on that main commit, so a red merge never gets
here. Installation and activation go through tradejournal-deploy, whose health
checks restore the running release when an activation fails.

A newer build waits instead of deploying while:
- it is 09:25-16:15 New York time on a weekday, unless its pull request carries
  the deploy-now label;
- a sync or enrichment job is running, or the API is not answering;
- it changes the database schema. It is installed, and a person runs
  `run --allow-migration`, which takes a verified backup first;
- it is not ahead of the running commit on main. This never moves the server
  backwards, and never replaces a build someone deployed by hand from a branch;
- it is the build an operator rolled back from, or one whose activation failed.

Opt-in: nothing happens until /etc/tradejournal/autodeploy.env exists with
AUTODEPLOY_ENABLED=true. Run with sudo.
"""

import argparse
from dataclasses import dataclass
from datetime import datetime, time, timezone
import fcntl
import hashlib
from http.client import HTTPException
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from alerts import publish
from dotenv import dotenv_values

ROOT = Path("/opt/tradejournal")
CONFIG = Path("/etc/tradejournal/autodeploy.env")
# Phone alerts' ntfy settings, used unless autodeploy.env names its own topic.
ALERTS_CONFIG = Path("/etc/tradejournal/alerts.env")
NTFY_KEYS = ("NTFY_URL", "NTFY_TOKEN", "ALERT_APP_URL")
STATE = Path("/var/lib/tradejournal/autodeploy")
CONTROLLER = Path("/usr/local/sbin/tradejournal-deploy")
BACKUPS = Path("/var/backups/tradejournal")
API = "http://127.0.0.1:8080"
GITHUB = "https://api.github.com"
NEW_YORK = ZoneInfo("America/New_York")
DEFAULT_HOLD = "09:25-16:15"
DEPLOY_NOW = "deploy-now"
# control.py exits with EX_TEMPFAIL when another operation holds its lock.
CONTROLLER_BUSY = 75
RELEASE_ID = re.compile(r"[a-z0-9][a-z0-9.-]{0,95}")
COMMIT = re.compile(r"[0-9a-f]{40}")


class Waiting(Exception):
    """Nothing is wrong; try again on the next run."""


class Failed(Exception):
    """A deployment step failed and a person should look."""


@dataclass(frozen=True)
class Settings:
    enabled: bool
    repository: str
    confirm_database: str
    hold: tuple[time, time] | None
    keep: int
    api_url: str
    ntfy: dict[str, str]


@dataclass(frozen=True)
class Build:
    tag: str
    commit: str
    release_id: str
    title: str
    assets: dict[str, str]


def parse_hold(value: str | None) -> tuple[time, time] | None:
    value = (value or DEFAULT_HOLD).strip()
    if value == "off":
        return None
    start, end = (time.fromisoformat(part.strip()) for part in value.split("-"))
    if start >= end:
        raise ValueError("AUTODEPLOY_HOLD_WINDOW must be HH:MM-HH:MM with the start first")
    return start, end


def _root_only(path: Path) -> None:
    # It names the database a release switch may touch, and the ntfy topic
    # URL is enough to post to or read the phone notifications.
    info = path.stat()
    if info.st_uid != 0 or stat.S_IMODE(info.st_mode) != 0o600:
        raise RuntimeError(f"Expected a root-owned 0600 file: {path}")


def load_settings(path: Path = CONFIG) -> Settings | None:
    if not path.exists():
        return None
    _root_only(path)
    values = dotenv_values(path, interpolate=False)
    ntfy = {key: values[key] for key in NTFY_KEYS if values.get(key)}
    if "NTFY_URL" not in ntfy and ALERTS_CONFIG.exists():
        # One topic for everything this server tells the phone.
        alerts = dotenv_values(ALERTS_CONFIG, interpolate=False)
        ntfy = {key: alerts[key] for key in NTFY_KEYS if alerts.get(key)}
    repository = values.get("AUTODEPLOY_REPOSITORY") or ""
    confirm = values.get("AUTODEPLOY_CONFIRM_DATABASE") or ""
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", repository) or not confirm:
        raise RuntimeError("Set AUTODEPLOY_REPOSITORY and AUTODEPLOY_CONFIRM_DATABASE in autodeploy.env")
    return Settings(
        enabled=values.get("AUTODEPLOY_ENABLED") == "true",
        repository=repository,
        confirm_database=confirm,
        hold=parse_hold(values.get("AUTODEPLOY_HOLD_WINDOW")),
        keep=int(values.get("AUTODEPLOY_KEEP_RELEASES") or 3),
        api_url=(values.get("AUTODEPLOY_API_URL") or GITHUB).rstrip("/"),
        ntfy=ntfy,
    )


def in_hold(now: datetime, hold: tuple[time, time] | None) -> bool:
    if hold is None:
        return False
    local = now.astimezone(NEW_YORK)
    return local.weekday() < 5 and hold[0] <= local.time() < hold[1]


def fetch(url: str, *, accept: str = "application/vnd.github+json", timeout: float = 30):
    return urlopen(Request(url, headers={"Accept": accept, "User-Agent": "tradejournal-autodeploy"}), timeout=timeout)


def github(settings: Settings, path: str, *, missing=None):
    """Unauthenticated: the repository is public and nothing here writes to it."""
    try:
        with fetch(f"{settings.api_url}/repos/{settings.repository}{path}") as response:
            return json.load(response)
    except HTTPError as exc:
        if exc.code == 404 and missing is not None:
            return missing
        # Includes 403/429 rate limiting: unauthenticated calls get 60 an hour.
        raise Waiting(f"GitHub answered {exc.code} for {path}") from exc
    except (URLError, TimeoutError) as exc:
        raise Waiting(f"GitHub did not answer ({exc})") from exc


def newest_build(releases: list[dict]) -> Build | None:
    builds = []
    for release in releases:
        assets = {asset["name"]: asset["browser_download_url"] for asset in release.get("assets", [])}
        archives = [name.removesuffix(".tar.gz") for name in assets if name.endswith(".tar.gz")]
        if (
            release.get("draft")
            or not release.get("tag_name", "").startswith("build-")
            or not COMMIT.fullmatch(release.get("target_commitish", ""))
            or not {"SHA256SUMS", "tradejournal-deploy.py"} <= assets.keys()
            or len(archives) != 1
            or not RELEASE_ID.fullmatch(archives[0])
        ):
            continue
        builds.append((release["published_at"], release, archives[0], assets))
    if not builds:
        return None
    _, release, release_id, assets = max(builds, key=lambda build: build[0])
    title = (release.get("body") or "").strip().splitlines()
    return Build(release["tag_name"], release["target_commitish"], release_id, title[0] if title else release["tag_name"], assets)


def labelled_deploy_now(settings: Settings, build: Build) -> bool:
    pulls = github(settings, f"/commits/{build.commit}/pulls")
    return any(label["name"] == DEPLOY_NOW for pull in pulls for label in pull.get("labels", []))


def job_running() -> bool:
    try:
        with urlopen(f"{API}/sync/summary", timeout=10) as response:
            return bool(json.load(response)["running"])
    except (URLError, TimeoutError, KeyError, ValueError) as exc:
        # An unhealthy server needs a person, not an unattended release switch.
        raise Waiting(f"The API is not answering ({exc}); not deploying onto it") from exc


def parse_sums(text: str) -> dict[str, str]:
    sums = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        digest, name = line.split(maxsplit=1)
        name = name.lstrip("*")
        if not re.fullmatch(r"[0-9a-f]{64}", digest) or "/" in name:
            raise Failed("SHA256SUMS is malformed")
        sums[name] = digest
    return sums


def download(build: Build, directory: Path) -> tuple[Path, Path, str]:
    """Fetch the archive and controller; accept them only if SHA256SUMS agrees."""
    try:
        with fetch(build.assets["SHA256SUMS"], accept="application/octet-stream") as response:
            sums = parse_sums(response.read().decode())
        archive = f"{build.release_id}.tar.gz"
        for name in (archive, "tradejournal-deploy.py"):
            if name not in sums:
                raise Failed(f"SHA256SUMS does not list {name}")
            with fetch(build.assets[name], accept="application/octet-stream", timeout=120) as response, (directory / name).open("wb") as handle:
                shutil.copyfileobj(response, handle, 1 << 20)
            with (directory / name).open("rb") as handle:
                if hashlib.file_digest(handle, "sha256").hexdigest() != sums[name]:
                    raise Failed(f"{name} does not match SHA256SUMS")
    except (URLError, TimeoutError) as exc:
        raise Waiting(f"Download of {build.tag} did not finish ({exc})") from exc
    return directory / archive, directory / "tradejournal-deploy.py", sums[archive]


def install_controller(source: Path) -> None:
    pending = CONTROLLER.with_name(f".{CONTROLLER.name}.new")
    shutil.copyfile(source, pending)
    pending.chmod(0o755)
    pending.replace(CONTROLLER)


def controller(*args) -> str:
    result = subprocess.run([str(CONTROLLER), *map(str, args)], capture_output=True, text=True)
    output = "\n".join(part.strip() for part in (result.stdout, result.stderr) if part.strip())
    if output:
        print(output, flush=True)
    if result.returncode == CONTROLLER_BUSY:
        raise Waiting("Another deployment operation is running")
    if result.returncode:
        tail = "\n".join(output.splitlines()[-6:])
        raise Failed(f"tradejournal-deploy {args[0]} failed:\n{tail}")
    return output


def schema_changes(current: Path, candidate: Path) -> bool:
    def revisions(release: Path) -> set[str]:
        return {path.name for path in (release / "backend/alembic/versions").glob("*.py")}

    return revisions(current) != revisions(candidate)


def backup(current: Path) -> None:
    try:
        subprocess.run(["systemctl", "start", "tradejournal-backup.service"], check=True)
        subprocess.run([current / "backend/.venv/bin/python", current / "deploy/backup.py", "verify", (BACKUPS / "latest").resolve()], check=True)
    except subprocess.CalledProcessError as exc:
        raise Failed("The backup before the migration did not verify; nothing was changed") from exc


def api_healthy() -> bool:
    try:
        with urlopen(f"{API}/health", timeout=10) as response:
            return json.load(response).get("status") == "ok"
    except (URLError, TimeoutError, ValueError):
        return False


def notify(settings: Settings, title: str, message: str, *, good_news: bool = False) -> None:
    """Through the phone alerts' sender, so both land on one topic alike."""
    if not settings.ntfy.get("NTFY_URL"):
        return
    try:
        publish(settings.ntfy, title, message, recovered=good_news)
    except (OSError, HTTPException) as exc:
        print(f"Phone notification not delivered: {exc}", flush=True)


def release_commit(link: Path) -> str | None:
    try:
        return json.loads((link / "release.json").read_text())["commit"]
    except (FileNotFoundError, KeyError, ValueError):
        return None


def load_state() -> dict:
    try:
        return json.loads((STATE / "state.json").read_text())
    except FileNotFoundError:
        return {}


def save_state(state: dict) -> None:
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    pending = STATE / "state.json.new"
    pending.write_text(json.dumps(state, indent=2) + "\n")
    pending.replace(STATE / "state.json")


def record(settings: Settings, state: dict, build: Build, outcome: str, detail: str, *, title: str) -> None:
    """Remember a decision about a build; notify only the first time it is made."""
    if (state.get("commit"), state.get("outcome")) != (build.commit, outcome):
        notify(settings, title, detail, good_news=outcome == "deployed")
    state.update(commit=build.commit, release=build.release_id, outcome=outcome, detail=detail, at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    if outcome == "deployed":
        state["deployed"] = build.commit
    save_state(state)


def deploy(settings: Settings, *, now: datetime, ignore_hold: bool = False, allow_migration: bool = False) -> str:
    """One pass. Returns a line for the journal; raises Waiting or Failed."""
    state = load_state()
    running = json.loads((ROOT / "current/release.json").read_text())
    build = newest_build(github(settings, "/releases?per_page=20"))
    if build is None:
        return "No verified build is published yet"
    short = build.commit[:12]
    if build.commit == running["commit"]:
        return f"Up to date with {short}"
    if (state.get("commit"), state.get("outcome")) == (build.commit, "failed"):
        return f"Not retrying {short}: it failed before. Merge a fix, or deploy it by hand"
    # After a rollback the controller's "previous" link names the release it
    # left, whoever had deployed it: this pass or an operator by hand.
    if build.commit in {state.get("deployed"), release_commit(ROOT / "previous")}:
        record(settings, state, build, "rolled-back", f"The server was moved off {short} ({build.title}) after it deployed, so it is not being put back. The next merge deploys as usual.", title="TradeJournal update paused")
        return f"Not redeploying {short}: an operator rolled it back"
    if not ignore_hold and in_hold(now, settings.hold) and not labelled_deploy_now(settings, build):
        return f"Holding {short} until the market closes"
    # A commit GitHub has never seen (a local build) compares as unknown.
    relation = github(settings, f"/compare/{running['commit']}...{build.commit}", missing={"status": "unknown"})["status"]
    if relation in {"behind", "identical"}:
        return f"The server already runs {running['commit'][:12]}, which includes {short}"
    if relation != "ahead":
        record(settings, state, build, "diverged", f"The server runs {running['commit'][:12]}, which is not on main's history, so {short} ({build.title}) was not installed over it. Deploy it by hand once that build is no longer needed.", title="TradeJournal update waiting")
        return f"Not replacing {running['commit'][:12]}: it is not an ancestor of {short}"
    if job_running():
        raise Waiting("A sync or enrichment job is running")

    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    release = ROOT / "releases" / build.release_id
    if not release.exists():
        try:
            with tempfile.TemporaryDirectory(dir=STATE) as scratch:
                archive, source, digest = download(build, Path(scratch))
                install_controller(source)
                controller("install", archive, "--sha256", digest)
        except Failed as exc:
            record(settings, state, build, "failed", f"{short} ({build.title}) could not be installed; the server is unchanged.\n{exc}", title="TradeJournal update failed")
            raise
    if schema_changes(ROOT / "current", release):
        if not allow_migration:
            record(settings, state, build, "needs-migration", f"{short} ({build.title}) changes the database, so it is installed but not live. Ask Claude to apply it; that takes a backup first.", title="TradeJournal update waiting")
            return f"Holding {short}: it changes the database schema"
        backup(ROOT / "current")
        try:
            controller("migrate", build.release_id, "--confirm-database", settings.confirm_database)
        except Failed as exc:
            # migrate checks the owner connection before it stops anything.
            if api_healthy():
                record(settings, state, build, "failed", f"The database migration for {short} was refused before anything stopped.\n{exc}", title="TradeJournal update failed")
            else:
                record(settings, state, build, "failed", f"The database migration for {short} failed and the app is stopped.\n{exc}", title="TradeJournal is DOWN")
            raise
    try:
        controller("activate", build.release_id, "--confirm-database", settings.confirm_database)
    except Failed as exc:
        if api_healthy():
            record(settings, state, build, "failed", f"{short} ({build.title}) failed its health checks, so the server went back to {running['commit'][:12]}.\n{exc}", title="TradeJournal update failed")
        else:
            record(settings, state, build, "failed", f"{short} failed to start and the previous release did not come back either.\n{exc}", title="TradeJournal is DOWN")
        raise
    record(settings, state, build, "deployed", f"{build.title}\nNow running {short}.", title="TradeJournal updated")
    try:
        controller("prune", "--keep", settings.keep)
    except (Failed, Waiting) as exc:
        print(f"Old releases were not pruned: {exc}", flush=True)
    return f"Deployed {build.release_id}"


def status(settings: Settings) -> None:
    running = json.loads((ROOT / "current/release.json").read_text())
    hold = "off" if settings.hold is None else f"{settings.hold[0]:%H:%M}-{settings.hold[1]:%H:%M} New York, weekdays"
    print(f"Automatic deployment: {'on' if settings.enabled else 'off'} (market-hours hold {hold})")
    print(f"Running: {running['release_id']} (commit {running['commit'][:12]})")
    try:
        build = newest_build(github(settings, "/releases?per_page=20"))
        print(f"Newest verified build: {build.release_id} (commit {build.commit[:12]}): {build.title}" if build else "Newest verified build: none published")
    except Waiting as exc:
        print(f"Newest verified build: unknown; {exc}")
    state = load_state()
    if state:
        print(f"Last decision: {state['outcome']} for {state['commit'][:12]} at {state['at']}\n  {state['detail']}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="action", required=True)
    run_parser = commands.add_parser("run", help="deploy the newest verified build when it is time")
    run_parser.add_argument("--now", action="store_true", help="ignore the market-hours hold")
    run_parser.add_argument("--allow-migration", action="store_true", help="back up, migrate and activate a build that changes the schema")
    commands.add_parser("status", help="show the running release, the newest build and the last decision")
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error("Run with sudo")
    settings = load_settings()
    if settings is None:
        print(f"Automatic deployment is not configured ({CONFIG} does not exist)")
        return
    if args.action == "status":
        status(settings)
        return
    if not settings.enabled:
        print("Automatic deployment is off (AUTODEPLOY_ENABLED is not true)")
        return
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (STATE / "run.lock").open("a+b") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("Another automatic deployment run is active")
            return
        try:
            print(deploy(settings, now=datetime.now(timezone.utc), ignore_hold=args.now, allow_migration=args.allow_migration), flush=True)
        except Waiting as exc:
            print(f"Waiting: {exc}", flush=True)
        except Failed as exc:
            raise SystemExit(str(exc)) from None


if __name__ == "__main__":
    main()
