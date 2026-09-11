"""
What `scripts/setup_roles.py` must get right.

The script's whole value is that its verification is honest, so most of what
is asserted here is about the check rather than the grants: that every role is
probed in both directions, that a non-privilege failure is never reported as a
working restriction, and that the target has to be named before anything runs.

The Postgres tests use throwaway role names rather than the real constants.
Roles are cluster-wide, so a test that created `tj_app` and dropped it at the
end would destroy a real one on a developer's machine.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from tests.postgres_support import (
    TEST_DATABASE_URL,
    refuse_if_not_disposable,
    requires_postgres,
    reset_schema,
    run_alembic,
)

BACKEND_DIR = Path(__file__).resolve().parents[1]


def _load_script():
    """`scripts/` is not a package; load by path as test_check_database does."""
    path = BACKEND_DIR / "scripts" / "setup_roles.py"
    spec = importlib.util.spec_from_file_location("setup_roles", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["setup_roles"] = module
    spec.loader.exec_module(module)
    return module


setup_roles = _load_script()

TEST_APP = "tj_app_pytest"
TEST_INGRESS = "tj_ingress_pytest"


# --------------------------------------------------------------------------
# No database required.
# --------------------------------------------------------------------------

def test_the_grants_cover_tables_that_do_not_exist_yet():
    """
    ALTER DEFAULT PRIVILEGES is the line easiest to omit, and omitting it means
    every future migration produces a table the application cannot read.
    """
    statements = setup_roles.grant_statements("owner")
    assert any("ALTER DEFAULT PRIVILEGES" in s for s in statements)


def test_the_app_is_granted_no_ddl_and_no_truncate():
    granted = " ".join(setup_roles.grant_statements("owner")).upper()
    for forbidden in ("TRUNCATE", "CREATE TABLE", "REFERENCES", "ALL PRIVILEGES"):
        assert forbidden not in granted


def test_the_ingress_is_granted_only_its_own_table():
    statements = setup_roles.grant_statements("owner")
    ingress = [s for s in statements if setup_roles.INGRESS_ROLE in s]
    tables = [s for s in ingress if "ON SCHEMA" not in s]
    assert len(tables) == 1
    assert setup_roles.INGRESS_TABLE in tables[0]
    assert "fill" not in " ".join(ingress)


def test_the_release_list_covers_everything_a_drop_needs():
    """
    Established by dropping a role the owner could drop: it failed on
    `privileges for schema public` until every one of these had run.
    """
    statements = " ".join(
        setup_roles.release_statements("owner", [setup_roles.APP_ROLE, setup_roles.INGRESS_ROLE]))
    assert "ALTER DEFAULT PRIVILEGES" in statements
    assert "ON ALL TABLES" in statements
    assert "ON ALL SEQUENCES" in statements
    assert "ON SCHEMA public" in statements


def test_release_skips_default_privileges_when_the_app_role_is_absent():
    """Revoking default privileges from a role that does not exist errors."""
    statements = setup_roles.release_statements("owner", [setup_roles.INGRESS_ROLE])
    assert not any("ALTER DEFAULT PRIVILEGES" in s for s in statements)


def test_every_role_is_probed_in_both_directions():
    """
    A role that can do nothing looks exactly like a role that is correctly
    restricted. Only checking both tells them apart.
    """
    plan = setup_roles.probe_plan("owner")
    for role in (setup_roles.APP_ROLE, setup_roles.INGRESS_ROLE):
        outcomes = {denied for probed, _, denied in plan if probed == role}
        assert outcomes == {True, False}, f"{role} is only checked one way"


def test_both_roles_are_checked_for_set_role():
    """
    Inheriting nothing is not the same as being unable to become the owner.
    A role that may still SET ROLE is one statement from unrestricted.
    """
    plan = setup_roles.probe_plan("theowner")
    for role in (setup_roles.APP_ROLE, setup_roles.INGRESS_ROLE):
        assert any(probed == role and statement == "SET ROLE theowner" and denied
                   for probed, statement, denied in plan)


def test_a_host_mismatch_refuses_before_connecting(monkeypatch):
    """The URL is unreachable; refusing first is what makes that irrelevant."""
    monkeypatch.setattr(sys, "argv", [
        "setup_roles.py",
        "--url", "postgresql+psycopg://owner:pw@real-host.example/db",
        "--confirm-host", "some-other-host",
    ])
    assert setup_roles.main() == 1


def test_verify_and_release_are_not_combinable(monkeypatch):
    monkeypatch.setattr(sys, "argv", [
        "setup_roles.py",
        "--url", "postgresql+psycopg://owner:pw@h/db",
        "--confirm-host", "h", "--verify", "--release",
    ])
    assert setup_roles.main() == 1


# --------------------------------------------------------------------------
# Postgres required: roles are a server feature, SQLite has none.
# --------------------------------------------------------------------------

def _drop_test_roles(engine) -> None:
    """
    DROP OWNED BY rather than a hand-written revoke list.

    Default privileges survive DROP SCHEMA public CASCADE -- they are catalog
    entries keyed by schema name, so a recreated `public` inherits them and
    grants leak into the next test. DROP OWNED BY clears those too, and a list
    maintained by hand here would be a second copy of release_statements() free
    to drift from it.
    """
    with engine.connect() as connection:
        for role in (TEST_APP, TEST_INGRESS):
            for statement in (f"DROP OWNED BY {role}", f"DROP ROLE IF EXISTS {role}"):
                try:
                    connection.execute(text(statement))
                except Exception:  # noqa: BLE001,S110 -- absent role, nothing to clean
                    pass


@pytest.fixture
def migrated_database():
    engine = create_engine(TEST_DATABASE_URL, isolation_level="AUTOCOMMIT")
    refuse_if_not_disposable(engine)
    # Also before, not just after: a crashed earlier run leaves roles behind,
    # and every test here starts by asserting they do not exist yet.
    _drop_test_roles(engine)
    reset_schema(engine)
    result = run_alembic("upgrade", "head", url=TEST_DATABASE_URL)
    assert result.returncode == 0, result.stderr
    yield engine
    _drop_test_roles(engine)
    engine.dispose()


@pytest.fixture
def throwaway_role_names(monkeypatch):
    monkeypatch.setattr(setup_roles, "APP_ROLE", TEST_APP)
    monkeypatch.setattr(setup_roles, "INGRESS_ROLE", TEST_INGRESS)


def _run(monkeypatch, *extra: str) -> int:
    from sqlalchemy.engine import make_url
    host = make_url(TEST_DATABASE_URL).host
    monkeypatch.setattr(sys, "argv", [
        "setup_roles.py", "--url", TEST_DATABASE_URL, "--confirm-host", host, *extra])
    return setup_roles.main()


@requires_postgres
def test_it_creates_roles_that_are_genuinely_limited(
        migrated_database, throwaway_role_names, monkeypatch, capsys):
    assert _run(monkeypatch) == 0
    output = capsys.readouterr().out
    assert "All checks passed" in output
    assert "FAIL" not in output
    # The credentials are printed for pasting, and printed only once.
    assert "DATABASE_URL=" in output and "TRADINGVIEW_DATABASE_URL=" in output


@requires_postgres
def test_a_second_run_refuses_instead_of_rebuilding(
        migrated_database, throwaway_role_names, monkeypatch, capsys):
    assert _run(monkeypatch) == 0
    capsys.readouterr()
    assert _run(monkeypatch) == 1
    assert "already present" in capsys.readouterr().out


@requires_postgres
def test_release_is_opt_in(migrated_database, throwaway_role_names, monkeypatch, capsys):
    """
    Finding existing roles must not strip their privileges. Someone running
    this to look around would break whatever is using them.
    """
    assert _run(monkeypatch) == 0
    capsys.readouterr()
    assert _run(monkeypatch) == 1
    assert "REVOKE" not in capsys.readouterr().out

    with migrated_database.connect() as connection:
        still = connection.execute(text(
            "SELECT count(*) FROM information_schema.table_privileges "
            "WHERE grantee = :role"), {"role": TEST_APP}).scalar()
    assert still, "a plain run revoked privileges it was not asked to touch"


@requires_postgres
def test_release_clears_enough_for_the_role_to_be_dropped(
        migrated_database, throwaway_role_names, monkeypatch):
    assert _run(monkeypatch) == 0
    assert _run(monkeypatch, "--release") == 1
    with migrated_database.connect() as connection:
        connection.execute(text(f"DROP ROLE {TEST_APP}"))
        connection.execute(text(f"DROP ROLE {TEST_INGRESS}"))


@requires_postgres
def test_a_constraint_violation_is_not_reported_as_a_privilege_refusal(migrated_database):
    """
    The first version of this harness reported a false pass: an INSERT naming
    one column of a table with eighteen NOT NULLs raises a constraint
    violation, and catching every exception called that a working restriction.
    """
    result = setup_roles.run_probe(
        TEST_DATABASE_URL,
        f"INSERT INTO {setup_roles.INGRESS_TABLE} (alert_id) VALUES ('probe')")
    assert result.startswith("other("), result
    assert result != "denied"


@requires_postgres
def test_a_probe_that_is_wrongly_allowed_still_changes_nothing(migrated_database):
    """
    Every probe runs in a transaction that is rolled back, so a probe that is
    wrongly permitted leaves nothing behind. Checked with a statement the owner
    really can perform -- `DROP TABLE fill` is not one, since it fails on
    dependent foreign keys before privileges ever come into it.
    """
    assert setup_roles.run_probe(
        TEST_DATABASE_URL, "CREATE TABLE setup_roles_probe (i int)") == "allowed"
    with migrated_database.connect() as connection:
        assert connection.execute(
            text("SELECT to_regclass('public.setup_roles_probe')")).scalar() is None


@requires_postgres
def test_dropping_fill_is_refused_for_privilege_before_dependencies(
        migrated_database, throwaway_role_names, monkeypatch, capsys):
    """
    `DROP TABLE fill` earns its place in the plan only if the restricted role
    is refused for *privilege*. As the owner the same statement fails on
    dependent foreign keys (2BP01), which would make the row meaningless.
    """
    assert _run(monkeypatch) == 0
    capsys.readouterr()
    from sqlalchemy.engine import make_url

    app_url = make_url(TEST_DATABASE_URL).set(username=TEST_APP)
    with migrated_database.connect() as connection:
        exists = connection.execute(text(
            "SELECT 1 FROM pg_roles WHERE rolname = :role"), {"role": TEST_APP}).scalar()
        assert exists, "setup did not create the app role"
        # The generated password is printed, never stored, so set a known one.
        connection.execute(text(f"ALTER ROLE {TEST_APP} PASSWORD 'probe'"))
    assert setup_roles.run_probe(str(app_url.set(password="probe")),
                                 "DROP TABLE fill") == "denied"


@requires_postgres
def test_the_probes_leave_no_sessions_open(
        migrated_database, throwaway_role_names, monkeypatch, capsys):
    """
    Closing a pooled connection keeps the server session alive. Eleven probes
    would leave eleven sessions sitting as the very roles --release inspects
    before it revokes anything, and the guard would then refuse against the
    script's own leftovers.
    """
    assert _run(monkeypatch) == 0
    capsys.readouterr()
    with migrated_database.connect() as connection:
        live = connection.execute(
            text("SELECT count(*) FROM pg_stat_activity WHERE usename = ANY(:names)"),
            {"names": [TEST_APP, TEST_INGRESS]}).scalar()
    assert live == 0, f"{live} session(s) left open by the probes"


def test_verify_refuses_when_env_names_a_different_database(monkeypatch, capsys):
    """
    --confirm-host validates the owner URL, but --verify probes whatever .env
    names, which can be a different database entirely. A stale .env is exactly
    how a dev branch gets verified while production is what is running.

    Asserted on the message, not the exit code: an unreachable host fails every
    probe and returns 1 anyway, so the code alone cannot tell a refusal from a
    connection error.
    """
    monkeypatch.setattr(setup_roles, "configured_urls", lambda: {
        setup_roles.APP_ROLE: "postgresql+psycopg://tj_app:pw@elsewhere.example/db",
        setup_roles.INGRESS_ROLE: "",
    })
    monkeypatch.setattr(sys, "argv", [
        "setup_roles.py",
        "--url", "postgresql+psycopg://owner:pw@named-host.example/db",
        "--confirm-host", "named-host.example", "--verify",
    ])
    assert setup_roles.main() == 1
    output = capsys.readouterr().out
    assert "elsewhere.example" in output and "Refusing" in output
    assert "verification, both directions" not in output, "it probed anyway"
