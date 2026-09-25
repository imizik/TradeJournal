#!/usr/bin/env python3
"""Install and switch prebuilt TradeJournal releases on Ubuntu 24.04.

No builds or automatic schema downgrades run on the server. Run with sudo.
"""

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import pwd
import re
import shutil
import subprocess
import tarfile
import tempfile
import time
import urllib.request

ROOT = Path("/opt/tradejournal")
STATE = Path("/var/lib/tradejournal")
CONFIG = Path("/etc/tradejournal")
UNITS = Path("/etc/systemd/system")
SERVICES = ["tradejournal-api", "tradejournal-frontend", *[f"tradejournal-worker@{lane}" for lane in ("sync", "polygon", "webull", "gmail")]]
AUTOMATION_SERVICES = ["tradejournal-backup", "tradejournal-offsite-backup", "tradejournal-gmail-sync", "tradejournal-sync-pipeline", "tradejournal-alerts"]
TIMERS = [f"{name}.timer" for name in AUTOMATION_SERVICES]
OPTIONAL_UNITS = [*[f"{name}.service" for name in AUTOMATION_SERVICES], *TIMERS]
INGRESS_SERVICE = "tradejournal-ingress"
OPTIONAL_UNITS.append(f"{INGRESS_SERVICE}.service")
# The alert check keeps running through a deployment, so a release that fails
# to come back up still reaches the phone.
ALERT_UNITS = {"tradejournal-alerts.timer", "tradejournal-alerts.service"}
BACKUPS = Path("/var/backups/tradejournal")


def run(*command, **kwargs):
    return subprocess.run([str(value) for value in command], check=True, **kwargs)


def release_path(name: str) -> Path:
    if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{0,95}", name):
        raise ValueError("Invalid release ID")
    return ROOT / "releases" / name


def atomic_link(target: Path, link: Path) -> None:
    pending = link.with_name(f".{link.name}-{os.getpid()}")
    try:
        pending.symlink_to(target)
        pending.replace(link)
    finally:
        pending.unlink(missing_ok=True)


def current(name="current") -> Path | None:
    link = ROOT / name
    if not link.is_symlink():
        return None
    target = link.resolve(strict=True)
    if target.parent != (ROOT / "releases").resolve():
        raise ValueError(f"{name} points outside the release directory")
    return target


def validate_platform(metadata: dict) -> None:
    release = platform.freedesktop_os_release()
    expected = {"os": "ubuntu", "version": "24.04", "arch": platform.machine(), "python": "3.12"}
    if release.get("ID") != "ubuntu" or release.get("VERSION_ID") != "24.04" or metadata.get("platform") != expected:
        raise ValueError("Artifact and host must match Ubuntu 24.04, CPU architecture and Python 3.12")


def install(archive: Path, digest: str) -> Path:
    if not re.fullmatch(r"[a-fA-F0-9]{64}", digest):
        raise ValueError("--sha256 must be the artifact's full SHA256 digest")
    with archive.open("rb") as source:
        actual = hashlib.file_digest(source, "sha256").hexdigest()
    if actual != digest.lower():
        raise ValueError("Artifact checksum does not match")
    with tarfile.open(archive) as bundle:
        members = bundle.getmembers()
        roots = {member.name.split("/")[0] for member in members}
        if len(roots) != 1:
            raise ValueError("Artifact must contain one release directory")
        destination = release_path(roots.pop())
        metadata = json.load(bundle.extractfile(f"{destination.name}/release.json"))
        if metadata["release_id"] != destination.name:
            raise ValueError("Artifact release ID mismatch")
        validate_platform(metadata)
        if destination.exists():
            raise ValueError("Release already exists; releases are immutable")
        (ROOT / "releases").mkdir(parents=True, exist_ok=True)
        # Isolate extraction from existing releases, then publish atomically.
        # The data filter rejects unsafe links and device nodes as well.
        with tempfile.TemporaryDirectory(prefix=".install-", dir=ROOT / "releases") as staging:
            for member in members:
                if ".." in Path(member.name).parts:
                    raise tarfile.FilterError("Parent traversal in artifact")

            def release_filter(member, target):
                safe = tarfile.data_filter(member, target)
                if safe.issym() or safe.islnk():
                    base = Path(target) / safe.name if safe.issym() else Path(target) / "placeholder"
                    linked = (base.parent / safe.linkname).resolve()
                    if not linked.is_relative_to((Path(target) / destination.name).resolve()):
                        raise tarfile.FilterError("Artifact link leaves its release")
                return safe

            bundle.extractall(staging, filter=release_filter)
            (Path(staging) / destination.name).rename(destination)
    try:
        try:
            account = pwd.getpwnam("tradejournal")
        except KeyError:
            run("useradd", "--system", "--user-group", "--home-dir", STATE, "--shell", "/usr/sbin/nologin", "tradejournal")
            account = pwd.getpwnam("tradejournal")
        if (destination / "deploy/systemd" / f"{INGRESS_SERVICE}.service").is_file():
            try:
                pwd.getpwnam("tradejournal-ingress")
            except KeyError:
                run("useradd", "--system", "--user-group", "--home-dir", "/nonexistent", "--shell", "/usr/sbin/nologin", "tradejournal-ingress")
        for directory in (STATE, STATE / "data", STATE / "oauth", STATE / "job-locks", STATE / "frontend-cache", STATE / "frontend-cache" / destination.name):
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.chown(directory, account.pw_uid, account.pw_gid)
        BACKUPS.mkdir(parents=True, exist_ok=True, mode=0o700)
        BACKUPS.chmod(0o700)
        backend = destination / "backend"
        (backend / "data").symlink_to(STATE / "data")
        for filename in ("credentials.json", "token.json"):
            (backend / filename).symlink_to(STATE / "oauth" / filename)
        cache = destination / "frontend/.next/cache"
        if cache.exists():
            shutil.rmtree(cache)
        cache.symlink_to(STATE / "frontend-cache" / destination.name)
        run("/usr/bin/python3.12", "-m", "venv", backend / ".venv")
        run(backend / ".venv/bin/python", "-m", "pip", "install", "--no-index", "--find-links", destination / "wheels", "trade-journal-backend==0.1.0")
        CONFIG.mkdir(parents=True, exist_ok=True, mode=0o700)
        for filename in ("backend.env", "migration.env", "tradingview.env"):
            target = CONFIG / filename
            example = destination / "deploy" / f"{filename}.example"
            if not target.exists() and example.is_file():
                shutil.copyfile(example, target)
                target.chmod(0o600)
        print(f"Installed {destination.name}; configure {CONFIG} before migration or activation")
        return destination
    except BaseException:
        # Only remove the fresh release created by this invocation, never state.
        shutil.rmtree(destination)
        raise


def database(release: Path, action: str, confirmation: str | None = None) -> None:
    command = [release / "backend/.venv/bin/python", release / "deploy/database.py", action]
    if confirmation:
        command.extend(["--confirm-database", confirmation])
    run(*command)


def install_units(release: Path) -> None:
    bundled = {
        unit.name: unit
        for pattern in ("*.service", "*.timer")
        for unit in (release / "deploy/systemd").glob(pattern)
    }
    for name in OPTIONAL_UNITS:
        target = UNITS / name
        if name not in bundled and target.exists():
            subprocess.run(["systemctl", "disable", "--now", name], check=False)
            target.unlink()
    for unit in bundled.values():
        shutil.copyfile(unit, UNITS / unit.name)
        (UNITS / unit.name).chmod(0o644)
    run("systemctl", "daemon-reload")


def stop_services() -> None:
    # Missing units on first install are harmless; a failed stop is not.
    for service in [INGRESS_SERVICE, *TIMERS, *[f"{name}.service" for name in AUTOMATION_SERVICES], *SERVICES]:
        if service in ALERT_UNITS:
            continue
        result = subprocess.run(["systemctl", "show", service, "--property=LoadState", "--value"], capture_output=True, text=True, check=False)
        if result.stdout.strip() == "not-found":
            continue
        result.check_returncode()
        run("systemctl", "stop", service)


def health(release: Path, confirmation: str, timeout: float = 60) -> None:
    deadline = time.monotonic() + timeout
    while True:
        try:
            with urllib.request.urlopen("http://127.0.0.1:8080/health", timeout=3) as response:
                backend = json.load(response)
            with urllib.request.urlopen("http://127.0.0.1:3000/deployment.json", timeout=3) as response:
                frontend = json.load(response)
            with urllib.request.urlopen("http://127.0.0.1:3000/api/backend/health", timeout=3) as response:
                proxied = json.load(response)
            if backend["environment"]["identity"] != confirmation or proxied["environment"]["identity"] != confirmation:
                raise ValueError("Running API targets a different database")
            if frontend["release_id"] != release.name:
                raise ValueError("Frontend is serving a different release")
            if backend.get("release") != release.name:
                raise ValueError("API is serving a different release")
            # Liveness alone does not prove the application can query its DB.
            with urllib.request.urlopen("http://127.0.0.1:3000/api/backend/sync/summary", timeout=3) as response:
                json.load(response)
            return
        except (OSError, KeyError, ValueError) as exc:
            if time.monotonic() >= deadline:
                raise RuntimeError("Deployment health checks did not pass") from exc
            time.sleep(1)


def ingress_enabled(release: Path) -> bool:
    helper = release / "deploy/ingress.py"
    if not helper.is_file():
        return False  # Rollback to a release predating ingress support.
    result = subprocess.run([str(release / "backend/.venv/bin/python"), str(helper)], capture_output=True, text=True, check=False)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "Ingress preflight failed")
    return json.loads(result.stdout)["enabled"]


def ingress_health(timeout: float = 30) -> None:
    deadline = time.monotonic() + timeout
    while True:
        try:
            with urllib.request.urlopen("http://127.0.0.1:8090/health", timeout=3) as response:
                if json.load(response) != {"status": "ready"}:
                    raise ValueError("Ingress is not ready")
            return
        except (OSError, ValueError):
            if time.monotonic() >= deadline:
                raise RuntimeError("TradingView ingress readiness did not pass") from None
            time.sleep(1)


def start_services(release: Path, confirmation: str) -> None:
    enabled = ingress_enabled(release)
    install_units(release)
    run("systemctl", "enable", *SERVICES)
    run("systemctl", "start", *SERVICES[:2])
    health(release, confirmation)
    run("systemctl", "start", *SERVICES[2:])
    time.sleep(2)
    run("systemctl", "is-active", *SERVICES)
    if enabled:
        run("systemctl", "enable", "--now", INGRESS_SERVICE)
        ingress_health()
        run("systemctl", "is-active", INGRESS_SERVICE)
    elif (release / "deploy/systemd" / f"{INGRESS_SERVICE}.service").is_file():
        run("systemctl", "disable", "--now", INGRESS_SERVICE)
    available_timers = [timer for timer in TIMERS if (release / "deploy/systemd" / timer).is_file()]
    if available_timers:
        run("systemctl", "enable", "--now", *available_timers)
        run("systemctl", "is-active", *available_timers)


def activate(release: Path, confirmation: str) -> None:
    # A schema-incompatible rollback refuses BEFORE disturbing healthy services.
    database(release, "check", confirmation)
    ingress_enabled(release)
    previous = current()
    stop_services()
    atomic_link(release, ROOT / "current")
    try:
        start_services(release, confirmation)
    except BaseException:
        stop_services()
        if previous and previous != release:
            database(previous, "check", confirmation)
            atomic_link(previous, ROOT / "current")
            start_services(previous, confirmation)
            print(f"Activation failed; restored {previous.name}")
        raise
    if previous and previous != release:
        atomic_link(previous, ROOT / "previous")
    print(f"Active release: {release.name}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    install_parser = commands.add_parser("install")
    install_parser.add_argument("archive", type=Path)
    install_parser.add_argument("--sha256", required=True)
    for action in ("identity", "migrate", "activate"):
        sub = commands.add_parser(action)
        sub.add_argument("release_id")
        if action != "identity":
            sub.add_argument("--confirm-database", required=True)
    commands.add_parser("rollback").add_argument("--confirm-database", required=True)
    commands.add_parser("status")
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error("Run with sudo")
    os.umask(0o022)
    ROOT.mkdir(parents=True, exist_ok=True)
    with (ROOT / "deployment.lock").open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.action == "install":
            install(args.archive, args.sha256)
        elif args.action == "rollback":
            previous = current("previous")
            if previous is None:
                parser.error("No previous release is recorded")
            activate(previous, args.confirm_database)
        elif args.action == "status":
            print(f"Current: {current()}\nPrevious: {current('previous')}")
            run("systemctl", "--no-pager", "status", *SERVICES)
            if (UNITS / f"{INGRESS_SERVICE}.service").is_file():
                subprocess.run(["systemctl", "--no-pager", "status", INGRESS_SERVICE], check=False)
        else:
            release = release_path(args.release_id)
            if args.action == "identity":
                database(release, "identity")
            elif args.action == "migrate":
                database(release, "migration-check", args.confirm_database)
                stop_services()
                database(release, "migrate", args.confirm_database)
                print("Migration complete; services remain stopped until activate")
            else:
                activate(release, args.confirm_database)


if __name__ == "__main__":
    main()
