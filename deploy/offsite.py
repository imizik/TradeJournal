#!/usr/bin/env python3
"""Encrypt and verify a dated application backup in a private R2 bucket.

The R2 S3 credentials stay in a root-only config file. Restic holds the
encryption key separately; recovery requires a copy of that key off the VPS.
"""

import argparse
import os
import secrets
import stat
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

from backup import BACKUP_ROOT, verify_backup
from dotenv import dotenv_values

CONFIG = Path("/etc/tradejournal/offsite.env")
PASSWORD_FILE = Path("/etc/tradejournal/restic-password")
RESTIC = "/usr/bin/restic"


def _root_only(path: Path) -> None:
    info = path.stat()
    if info.st_uid != 0 or stat.S_IMODE(info.st_mode) != 0o600:
        raise RuntimeError(f"Expected a root-owned 0600 file: {path}")


def restic_environment() -> dict[str, str]:
    if os.geteuid() != 0:
        raise RuntimeError("Run offsite backup as root")
    _root_only(CONFIG)
    _root_only(PASSWORD_FILE)
    values = dotenv_values(CONFIG, interpolate=False)
    required = ("RESTIC_REPOSITORY", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY")
    if any(not values.get(name) for name in required):
        raise RuntimeError("Offsite configuration is incomplete")
    repository = values["RESTIC_REPOSITORY"]
    if not repository.startswith("s3:"):
        raise RuntimeError("Offsite repository must use the R2 S3 API")
    endpoint = urlsplit(repository[3:])
    if (endpoint.scheme != "https" or not endpoint.hostname or endpoint.username or
            endpoint.password or endpoint.port or
            not endpoint.hostname.endswith(".r2.cloudflarestorage.com") or
            not endpoint.path.strip("/") or endpoint.query or endpoint.fragment):
        raise RuntimeError("Offsite repository must name an R2 bucket over HTTPS")
    return {
        "HOME": str(BACKUP_ROOT),
        "LANG": "C.UTF-8",
        "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "RESTIC_REPOSITORY": repository,
        "RESTIC_PASSWORD_FILE": str(PASSWORD_FILE),
        "RESTIC_CACHE_DIR": str(BACKUP_ROOT / ".restic-cache"),
        "AWS_DEFAULT_REGION": "auto",
        "AWS_ACCESS_KEY_ID": values["AWS_ACCESS_KEY_ID"],
        "AWS_SECRET_ACCESS_KEY": values["AWS_SECRET_ACCESS_KEY"],
    }


def restic(environment: dict[str, str], *args: str) -> None:
    subprocess.run([RESTIC, *args], env=environment, check=True)


def latest_backup() -> Path:
    directory = (BACKUP_ROOT / "latest").resolve(strict=True)
    if directory.parent != BACKUP_ROOT or not directory.is_dir():
        raise RuntimeError("Latest backup points outside the dated backup directory")
    manifest = verify_backup(directory)
    created = datetime.fromisoformat(manifest["created_at"].replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)
    age = now - created
    if created.date() != now.date() or not timedelta(0) <= age <= timedelta(hours=12):
        raise RuntimeError("Latest verified backup was not created today")
    return directory


def backup_offsite(environment: dict[str, str]) -> None:
    directory = latest_backup()
    restic(environment, "backup", "--tag", "tradejournal", str(directory))
    restic(environment, "forget", "--keep-daily", "30", "--prune")
    restic(environment, "check")
    print(f"Encrypted offsite backup verified: {directory.name}")


def restore_database(dump: Path) -> tuple[str, str]:
    name = f"tradejournal_offsite_drill_{os.getpid()}_{secrets.token_hex(3)}"
    command = ["runuser", "-u", "postgres", "--"]
    subprocess.run([*command, "createdb", name], check=True)
    try:
        # Root opens the restricted dump; pg_restore gets only an inherited
        # read-only descriptor, never access to the credential archive.
        with dump.open("rb") as source:
            subprocess.run(
                [*command, "pg_restore", "--single-transaction", "--exit-on-error",
                 "--no-owner", "--no-acl", "--dbname", name],
                stdin=source, check=True,
            )
        tables = subprocess.run(
            [*command, "psql", "-At", "-d", name, "-c",
             "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'"],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
        revision = subprocess.run(
            [*command, "psql", "-At", "-d", name, "-c",
             "SELECT version_num FROM alembic_version"],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
        if int(tables) < 2 or not revision:
            raise RuntimeError("Offsite database restore has no application tables or revision")
        return tables, revision
    finally:
        subprocess.run([*command, "dropdb", "--if-exists", name], check=True)


def restore_drill(environment: dict[str, str]) -> None:
    BACKUP_ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory(prefix=".offsite-restore-", dir=BACKUP_ROOT) as temporary:
        restic(environment, "restore", "latest", "--target", temporary)
        restored_root = Path(temporary) / BACKUP_ROOT.relative_to("/")
        backups = sorted(path for path in restored_root.iterdir() if path.is_dir())
        if len(backups) != 1:
            raise RuntimeError("Offsite restore did not contain exactly one dated backup")
        verify_backup(backups[0])
        tables, revision = restore_database(backups[0] / "database.dump")
        print(f"Encrypted offsite restore verified: {backups[0].name}; {tables} tables, revision {revision}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("init", "backup", "restore-drill"))
    args = parser.parse_args()
    environment = restic_environment()
    if args.action == "init":
        restic(environment, "init")
    elif args.action == "backup":
        backup_offsite(environment)
    else:
        restore_drill(environment)


if __name__ == "__main__":
    main()
