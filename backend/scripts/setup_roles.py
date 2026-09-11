"""
Create the application and ingress database roles, and prove they are limited.

Three roles (`docs/agent/environments.md`): the owner runs migrations, the app
runs the private API with no DDL, and the ingress can touch only
`tradingview_alert`. This script builds the second and third, and then checks
them the only way that means anything -- by connecting as each one and trying
what it must not be allowed to do.

    python scripts/setup_roles.py --confirm-host <host>    create and verify
    python scripts/setup_roles.py --confirm-host <host> --verify
    python scripts/setup_roles.py --confirm-host <host> --release

`--confirm-host` must equal the host inside the owner URL. Neon branch names
are random words and a dev branch is indistinguishable from production at a
glance, so the target is named rather than inferred -- the same reason
`resync-all` refuses a hosted database it was not asked for by name.

**On Neon, create these roles here rather than in the console.** A
console-created role is a member of `neon_superuser` and reaches the schema
owner through it, and the owner holds no admin option on it -- REVOKE, ALTER
ROLE, DROP ROLE and even ALTER ROLE ... PASSWORD are all refused. It cannot be
narrowed, only deleted in the console and replaced. `--release` frees its
grants so that deletion can succeed.

Passwords are generated, printed once, and not stored. Neon cannot show a
SQL-created role's password either, so a copy kept here would be a second
source of truth that goes stale.

Exit code 0 means the roles are in place and verified; 1 means something needs
a decision first.
"""

from __future__ import annotations

import argparse
import os
import secrets
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

from app.environment import load_env_files  # noqa: E402
from app.schema import migration_database_url  # noqa: E402

APP_ROLE = "tj_app"
INGRESS_ROLE = "tj_ingress"
INGRESS_TABLE = "tradingview_alert"

# The only SQLSTATE that means "refused for lack of privilege". Anything else
# is a different failure wearing the same costume: an INSERT naming one column
# of a table with eighteen NOT NULLs raises a constraint violation, and a probe
# that treats every exception as a refusal reports that as a working boundary.
PRIVILEGE_DENIED = "42501"


def grant_statements(owner_role: str) -> list[str]:
    """
    What each role is allowed. Four verbs for the app and nothing more: it runs
    no TRUNCATE (which DELETE would not cover), no DDL, and needs no sequence
    grant -- every key is a UUID and the schema has no sequences.

    ALTER DEFAULT PRIVILEGES is the line easiest to omit and most expensive to
    omit: without it every future migration produces a table the application
    cannot read, and the failure surfaces long after the migration ran.
    """
    return [
        f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}",
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {APP_ROLE}",
        f"ALTER DEFAULT PRIVILEGES FOR ROLE {owner_role} IN SCHEMA public "
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {APP_ROLE}",
        f"GRANT USAGE ON SCHEMA public TO {INGRESS_ROLE}",
        f"GRANT SELECT, INSERT, UPDATE ON {INGRESS_TABLE} TO {INGRESS_ROLE}",
    ]


def release_statements(owner_role: str, roles: list[str]) -> list[str]:
    """
    Everything a DROP ROLE needs cleared. Verified by dropping a role the owner
    *could* drop, which failed on `privileges for schema public` until every
    line below had run.
    """
    statements = []
    if APP_ROLE in roles:
        statements.append(
            f"ALTER DEFAULT PRIVILEGES FOR ROLE {owner_role} IN SCHEMA public "
            f"REVOKE ALL ON TABLES FROM {APP_ROLE}"
        )
    joined = ", ".join(roles)
    statements += [
        f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {joined}",
        f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {joined}",
        f"REVOKE ALL ON SCHEMA public FROM {joined}",
    ]
    return statements


def probe_plan(owner_role: str) -> list[tuple[str, str, bool]]:
    """
    (role, statement, must_be_denied), checked in both directions.

    Both directions because a role that can do nothing looks exactly like a
    role that is correctly restricted, and only one of those is working.

    `SET ROLE` is the line that separates a boundary from a speed bump: a role
    that inherits nothing but may still become the owner is one statement away
    from unrestricted.
    """
    return [
        (INGRESS_ROLE, "SELECT count(*) FROM fill", True),
        (INGRESS_ROLE, "SELECT count(*) FROM account", True),
        (INGRESS_ROLE, f"SELECT count(*) FROM {INGRESS_TABLE}", False),
        (INGRESS_ROLE, f"INSERT INTO {INGRESS_TABLE} SELECT * FROM {INGRESS_TABLE} WHERE false", False),
        (INGRESS_ROLE, f"DELETE FROM {INGRESS_TABLE} WHERE false", True),
        (INGRESS_ROLE, f"SET ROLE {owner_role}", True),
        (APP_ROLE, "SELECT count(*) FROM fill", False),
        (APP_ROLE, f"INSERT INTO {INGRESS_TABLE} SELECT * FROM {INGRESS_TABLE} WHERE false", False),
        (APP_ROLE, "CREATE TABLE setup_roles_probe (i int)", True),
        (APP_ROLE, "DROP TABLE fill", True),
        (APP_ROLE, f"SET ROLE {owner_role}", True),
    ]


def role_url(base, role: str, password: str) -> str:
    """
    A connection string for one role, with the password intact.

    render_as_string(hide_password=False) rather than str(): SQLAlchemy's
    __str__ masks the password as `***`, which still parses and still connects
    against a trust-auth server -- and is then rejected by any server that
    actually checks. One helper because the probes and the printed .env lines
    both need it, and two copies of this is how one of them goes back to str().
    """
    return base.set(username=role,
                    password=password).render_as_string(hide_password=False)


def run_probe(url: str, statement: str) -> str:
    """
    "allowed", "denied", or "other(<sqlstate>)".

    Always inside a transaction that is rolled back. `DROP TABLE fill` is one
    of the probes, so a probe that is wrongly *allowed* must still leave
    nothing behind.

    The engine is disposed rather than left to its pool. Closing a connection
    returns it to the pool and keeps the server session open, which would leave
    a session per probe sitting as the very role `--release` checks for before
    it revokes anything.
    """
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            connection.execute(text(statement))
            transaction.rollback()
        return "allowed"
    except Exception as error:  # noqa: BLE001 -- the SQLSTATE is the signal
        sqlstate = getattr(getattr(error, "orig", None), "sqlstate", None)
        return "denied" if sqlstate == PRIVILEGE_DENIED else f"other({sqlstate})"
    finally:
        engine.dispose()


def verify(urls: dict[str, str], owner_role: str) -> bool:
    """Run every probe and print a line per row. True when all of them pass."""
    passed = True
    for role, statement, must_be_denied in probe_plan(owner_role):
        url = urls.get(role)
        if not url:
            print(f"  SKIP   {role:<11} no URL configured for this role")
            passed = False
            continue
        result = run_probe(url, statement)
        wanted = "denied" if must_be_denied else "allowed"
        ok = result == wanted
        passed = passed and ok
        print(f"  {'pass' if ok else 'FAIL'}   {role:<11} {statement[:44]:<44} "
              f"{result:<12} (wanted {wanted})")
        if result.startswith("other"):
            print("           ^ not a privilege error -- investigate before trusting this row")
    return passed


def configured_urls() -> dict[str, str]:
    """
    What `.env` and `.env.tradingview` currently point at.

    The ingress process deliberately never loads the private `.env`; reading
    both here is the point, since this is the tool that compares them.
    """
    from dotenv import load_dotenv

    load_env_files()
    load_dotenv(BACKEND_DIR / ".env.tradingview")
    return {
        APP_ROLE: os.environ.get("DATABASE_URL", "").strip(),
        INGRESS_ROLE: os.environ.get("TRADINGVIEW_DATABASE_URL", "").strip(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm-host", required=True,
                        help="must equal the host inside the owner URL")
    parser.add_argument("--url", help="owner URL; defaults to MIGRATION_DATABASE_URL")
    parser.add_argument("--verify", action="store_true",
                        help="only probe the roles .env currently points at")
    parser.add_argument("--release", action="store_true",
                        help="revoke grants so console-created roles can be deleted")
    args = parser.parse_args()

    if args.verify and args.release:
        print("--verify and --release do different things; pick one.")
        return 1

    raw = args.url or migration_database_url()
    try:
        url = make_url(raw)
    except Exception as error:  # noqa: BLE001
        print(f"Could not parse the owner URL: {error}")
        return 1

    if url.host != args.confirm_host:
        print("Refusing.\n"
              f"  owner URL points at : {url.host}\n"
              f"  --confirm-host is   : {args.confirm_host}\n"
              "Name the same host to confirm which database you mean.")
        return 1

    owner_role = url.username or ""
    print(f"target: {owner_role}@{url.host}/{url.database}\n")

    if args.verify:
        urls = configured_urls()
        # --confirm-host validated the owner URL. These come from .env, which
        # can name a different database entirely -- and a stale one is exactly
        # how a dev branch gets verified while production is what is running.
        for role, configured in urls.items():
            if not configured:
                continue
            host = make_url(configured).host
            if host != args.confirm_host:
                print(f"Refusing: {role} is configured against {host}, "
                      f"not {args.confirm_host}.")
                return 1
        print("verification, both directions")
        return 0 if verify(urls, owner_role) else 1

    engine = create_engine(raw, isolation_level="AUTOCOMMIT")
    with engine.connect() as connection:
        present = [row[0] for row in connection.execute(
            text("SELECT rolname FROM pg_roles WHERE rolname = ANY(:names) ORDER BY 1"),
            {"names": [APP_ROLE, INGRESS_ROLE]})]

        if present:
            print(f"roles already present: {present}")
            memberships = connection.execute(text("""
                SELECT m.rolname AS member, g.rolname AS granted, a.admin_option AS admin
                  FROM pg_auth_members a
                  JOIN pg_roles m ON m.oid = a.member
                  JOIN pg_roles g ON g.oid = a.roleid
                 WHERE m.rolname = ANY(:names)
                 ORDER BY 1, 2"""), {"names": present}).all()
            for row in memberships:
                print(f"  {row.member} is a member of {row.granted} (admin={row.admin})")
            if memberships:
                print("\nA role with a membership reaches privileges these grants cannot take\n"
                      "away, and the owner cannot narrow it. Delete both in the provider\n"
                      "console and re-run this script, which will create them in SQL.\n"
                      "Run with --release first to free their grants, or the delete fails.")
            else:
                print("\nNo memberships -- these look SQL-created. Nothing to rebuild.\n"
                      "Run with --verify to check what they can actually do.")

            if not args.release:
                return 1

            live = connection.execute(
                text("SELECT usename, count(*) FROM pg_stat_activity "
                     "WHERE usename = ANY(:names) GROUP BY 1"), {"names": present}).all()
            if live:
                print(f"\nRefusing to release: connected as {dict(live)}. "
                      "Stop it first, or this breaks it mid-flight.")
                return 1

            print("\nreleasing grants")
            for statement in release_statements(owner_role, present):
                try:
                    connection.execute(text(statement))
                    print(f"  ok      {statement[:74]}")
                except Exception as error:  # noqa: BLE001
                    print(f"  FAILED  {statement[:74]}\n          {str(error).splitlines()[0][:84]}")
            print(f"\nNow delete {present} in the provider console for {url.host}, "
                  "then re-run without --release.")
            return 1

        if args.release:
            print("Nothing to release: neither role exists.")
            return 1

        if not connection.execute(
                text(f"SELECT to_regclass('public.{INGRESS_TABLE}')")).scalar():
            print(f"Stop: {INGRESS_TABLE} does not exist, so this database is behind head.\n"
                  "  alembic upgrade head   (with MIGRATION_DATABASE_URL set to this owner URL)")
            return 1

        passwords = {APP_ROLE: secrets.token_urlsafe(24),
                     INGRESS_ROLE: secrets.token_urlsafe(24)}
        print("creating roles")
        for role in (APP_ROLE, INGRESS_ROLE):
            connection.execute(text(
                f"CREATE ROLE {role} LOGIN PASSWORD '{passwords[role]}' "
                "NOCREATEDB NOCREATEROLE"))
            print(f"  ok      CREATE ROLE {role}")
        for statement in grant_statements(owner_role):
            connection.execute(text(statement))
            print(f"  ok      {statement[:74]}")

    urls = {role: role_url(url, role, password)
            for role, password in passwords.items()}

    print("\nverification, both directions")
    if not verify(urls, owner_role):
        print("\nSomething failed. Do not point .env at these roles yet.")
        return 1

    print("\nAll checks passed. These are printed once and not stored:\n")
    print("--- backend/.env ---")
    print(f"DATABASE_URL={urls[APP_ROLE]}")
    print(f"MIGRATION_DATABASE_URL={raw}")
    print("--- backend/.env.tradingview ---")
    print(f"TRADINGVIEW_DATABASE_URL={urls[INGRESS_ROLE]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
