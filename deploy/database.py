"""Explicit target checks and migrations, invoked by control.py as root.

Only this short-lived helper reads migration.env. It drops root before opening
any database connection; application services never receive owner credentials.
"""

import argparse
import os
from pathlib import Path
import pwd
import sys

from dotenv import dotenv_values
from sqlalchemy.engine import make_url

RELEASE = Path(__file__).resolve().parents[1]


def target(url: str) -> tuple:
    value = make_url(url)
    return value.get_backend_name(), value.host, value.port or 5432, value.database, value.query


def drop_to_service_account(name: str = "tradejournal") -> None:
    account = pwd.getpwnam(name)
    # setuid() does not update the inherited login environment. Leaving
    # HOME=/root makes libpq look for client certificates under /root after
    # privileges have been dropped, which fails before it can connect.
    os.environ.update({"HOME": account.pw_dir, "USER": account.pw_name, "LOGNAME": account.pw_name})
    if os.geteuid() == 0:
        os.initgroups(account.pw_name, account.pw_gid)
        os.setgid(account.pw_gid)
        os.setuid(account.pw_uid)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["identity", "check", "migration-check", "migrate"])
    parser.add_argument("--confirm-database")
    args = parser.parse_args()
    settings = dotenv_values("/etc/tradejournal/backend.env", interpolate=False)
    url = settings.get("DATABASE_URL")
    if not url:
        raise SystemExit("Set DATABASE_URL in /etc/tradejournal/backend.env")
    owner_url = None
    if args.action in {"migration-check", "migrate"}:
        owner_url = dotenv_values("/etc/tradejournal/migration.env", interpolate=False).get("MIGRATION_DATABASE_URL")
        if not owner_url or target(owner_url) != target(url):
            raise SystemExit("Migration and application URLs must name the same database endpoint")
    # Inherited shell credentials cannot redirect a deployment operation.
    for name in ("DATABASE_URL", "MIGRATION_DATABASE_URL", "PYTHONPATH", "PYTHONHOME"):
        os.environ.pop(name, None)
    os.environ.update({key: value for key, value in settings.items() if value is not None})
    os.environ.pop("MIGRATION_DATABASE_URL", None)
    if owner_url:
        os.environ["MIGRATION_DATABASE_URL"] = owner_url
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    drop_to_service_account()
    os.chdir(RELEASE / "backend")
    sys.path.insert(0, str(RELEASE / "backend"))
    from app.environment import describe
    identity = describe(url).identity
    print(identity, flush=True)
    if args.action == "identity":
        return
    if args.confirm_database != identity:
        raise SystemExit("Database confirmation does not match; use the exact identity printed above")
    if args.action == "migration-check":
        from sqlalchemy import create_engine, text
        with create_engine(owner_url).connect() as connection:
            connection.execute(text("SELECT 1"))
    elif args.action == "migrate":
        from alembic import command
        from alembic.config import Config
        command.upgrade(Config("alembic.ini"), "head")
    else:
        from app.database import engine
        from app.schema import ensure_current
        ensure_current(engine)


if __name__ == "__main__":
    main()
