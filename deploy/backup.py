#!/usr/bin/env python3
"""Create and verify restricted TradeJournal application backups.

The VPS image backup protects the whole disk. This helper adds dated logical
Postgres dumps and persistent-state archives so one image contains several
application restore points. Run it as root from systemd; secrets are read from
the existing root-only deployment configuration and are never written to the
backup metadata or command line.
"""

import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile

from dotenv import dotenv_values
from sqlalchemy.engine import URL, make_url

from database import target

BACKUP_ROOT = Path("/var/backups/tradejournal")
STATE_ROOT = Path("/var/lib/tradejournal")
CONFIG_ROOT = Path("/etc/tradejournal")
RETENTION = 7
BACKUP_NAME = re.compile(r"^\d{8}T\d{6}Z$")
CONFIG_FILES = ("backend.env", "migration.env")


def sha256(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def database_urls() -> tuple[str, str]:
    app_url = dotenv_values(CONFIG_ROOT / "backend.env", interpolate=False).get("DATABASE_URL")
    owner_url = dotenv_values(CONFIG_ROOT / "migration.env", interpolate=False).get("MIGRATION_DATABASE_URL")
    if not app_url or not owner_url:
        raise RuntimeError("DATABASE_URL and MIGRATION_DATABASE_URL are required for backup")
    if target(app_url) != target(owner_url):
        raise RuntimeError("Migration and application URLs must name the same database endpoint")
    return app_url, owner_url


def redacted_identity(url: str) -> str:
    value = make_url(url)
    host = value.host or ""
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    port = f":{value.port}" if value.port else ""
    return f"{host}{port}/{value.database or ''}"


def pg_dump_url(url: str) -> tuple[str, str]:
    value = make_url(url)
    if not value.password:
        raise RuntimeError("The migration database URL must include a password")
    safe = URL.create(
        drivername="postgresql",
        username=value.username,
        host=value.host,
        port=value.port,
        database=value.database,
        query=value.query,
    )
    return safe.render_as_string(hide_password=False), value.password


def dump_database(owner_url: str, destination: Path) -> None:
    executable = shutil.which("pg_dump")
    if not executable:
        raise RuntimeError("pg_dump is not installed")
    safe_url, password = pg_dump_url(owner_url)
    environment = {
        "HOME": "/var/lib/tradejournal",
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "PGPASSWORD": password,
    }
    with destination.open("wb") as output:
        result = subprocess.run(
            [
                "runuser", "-u", "tradejournal", "--", executable,
                "--format=custom", "--compress=6", "--no-owner", "--no-privileges",
                f"--dbname={safe_url}",
            ],
            stdout=output,
            stderr=subprocess.PIPE,
            env=environment,
            text=False,
            check=False,
        )
    if result.returncode:
        message = result.stderr.decode(errors="replace").strip()
        raise RuntimeError(f"pg_dump failed: {message}")


def archive_state(destination: Path) -> None:
    with tarfile.open(destination, "w:gz", compresslevel=6) as bundle:
        for name in ("data", "oauth"):
            source = STATE_ROOT / name
            if not source.is_dir():
                raise RuntimeError(f"Missing persistent state directory: {source}")
            bundle.add(source, arcname=name, recursive=True)
        for name in CONFIG_FILES:
            source = CONFIG_ROOT / name
            if not source.is_file():
                raise RuntimeError(f"Missing deployment configuration: {source}")
            bundle.add(source, arcname=f"config/{name}", recursive=False)


def verify_backup(directory: Path) -> dict:
    manifest = json.loads((directory / "manifest.json").read_text())
    for name in ("database.dump", "state.tar.gz"):
        expected = manifest["files"][name]["sha256"]
        if sha256(directory / name) != expected:
            raise RuntimeError(f"Checksum mismatch: {name}")
    restore = shutil.which("pg_restore")
    if not restore:
        raise RuntimeError("pg_restore is not installed")
    subprocess.run([restore, "--list", directory / "database.dump"], check=True, stdout=subprocess.DEVNULL)
    with tarfile.open(directory / "state.tar.gz") as bundle:
        members = {member.name: member for member in bundle.getmembers()}
        roots = {Path(name).parts[0] for name in members if name}
    if not {"data", "oauth"}.issubset(roots):
        raise RuntimeError("State archive is missing data or OAuth")
    if manifest.get("format_version", 1) >= 2:
        if any(not members.get(f"config/{name}", None) or not members[f"config/{name}"].isfile()
               for name in CONFIG_FILES):
            raise RuntimeError("State archive is missing deployment configuration")
    return manifest


def prune_backups(retention: int = RETENTION) -> list[Path]:
    backups = sorted(
        path for path in BACKUP_ROOT.iterdir()
        if path.is_dir() and BACKUP_NAME.fullmatch(path.name)
    )
    removed = backups[:-retention]
    for path in removed:
        shutil.rmtree(path)
    return removed


def create_backup() -> Path:
    if os.geteuid() != 0:
        raise RuntimeError("Run backup as root")
    os.umask(0o077)
    BACKUP_ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    app_url, owner_url = database_urls()
    name = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = BACKUP_ROOT / name
    if destination.exists():
        raise RuntimeError(f"Backup already exists: {destination}")
    with tempfile.TemporaryDirectory(prefix=".pending-", dir=BACKUP_ROOT) as temporary:
        pending = Path(temporary)
        dump_database(owner_url, pending / "database.dump")
        archive_state(pending / "state.tar.gz")
        release = json.loads((Path("/opt/tradejournal/current") / "release.json").read_text())
        files = {
            path.name: {"bytes": path.stat().st_size, "sha256": sha256(path)}
            for path in (pending / "database.dump", pending / "state.tar.gz")
        }
        manifest = {
            "format_version": 2,
            "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "database_identity": redacted_identity(app_url),
            "release_id": release["release_id"],
            "commit": release["commit"],
            "files": files,
        }
        (pending / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        verify_backup(pending)
        pending.rename(destination)
    latest = BACKUP_ROOT / "latest"
    replacement = BACKUP_ROOT / f".latest-{os.getpid()}"
    replacement.symlink_to(destination.name)
    replacement.replace(latest)
    prune_backups()
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    commands.add_parser("create")
    verify = commands.add_parser("verify")
    verify.add_argument("directory", type=Path)
    args = parser.parse_args()
    BACKUP_ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (BACKUP_ROOT / ".lock").open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.action == "create":
            path = create_backup()
            print(f"Backup verified: {path}")
        else:
            verify_backup(args.directory.resolve())
            print(f"Backup verified: {args.directory.resolve()}")


if __name__ == "__main__":
    main()
