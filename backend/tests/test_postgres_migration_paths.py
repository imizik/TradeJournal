"""
The states a real database is actually found in, on Postgres.

CI already runs `alembic upgrade head` against an *empty* container
(test_postgres_parity.py). Real databases have history, and the gap between
those two is not theoretical: the Neon dev branch turned up stamped at
a4b5c6d7e8f9 with later tables already present, because startup used to call
create_all(). Working out whether that needed `upgrade` or `stamp` meant
reproducing it by hand on Postgres, because nothing in CI covered it.

This module covers it. Each test builds one of those states and asserts what
the migration chain and the preflight do with it:

- unstamped, built by create_all  -> `upgrade` fails; the preflight says stamp
- stamped part-way, then create_all -> `upgrade` succeeds
- stamped at head                  -> `upgrade` is a no-op

The middle one is the one that matters and the one CI never had. Migrations
from f1a2b3c4d5e6 onward guard every object with `if not _table_exists(...)`
precisely so Alembic can follow create_all; this proves those guards hold on
Postgres, not just SQLite, and will keep holding.

Schema lifetime is per test, not per module, which is why these do not live in
test_postgres_parity.py. The disposability guard is shared with that module
rather than copied -- see tests/postgres_support.py.
"""

from __future__ import annotations

import subprocess
import sys

import pytest
from sqlalchemy import create_engine, inspect
from sqlmodel import SQLModel

import app.models  # noqa: F401  -- registers every table
from app.schema import alembic_head, stamped_revision
from tests.postgres_support import (
    BACKEND_DIR,
    TEST_DATABASE_URL,
    refuse_if_not_disposable,
    requires_postgres,
    reset_schema,
    run_alembic,
)

pytestmark = requires_postgres

# The revision immediately before add_strategy_lab (f1a2b3c4d5e6), which is the
# first migration written to tolerate create_all having already run. A database
# stamped here with later tables present is exactly the shape the Neon dev
# branch was in.
BEFORE_THE_GUARDED_MIGRATIONS = "a4b5c6d7e8f9"


@pytest.fixture
def clean_database():
    """A freshly emptied Postgres schema, per test."""
    engine = create_engine(TEST_DATABASE_URL)
    refuse_if_not_disposable(engine)
    reset_schema(engine)
    yield engine
    reset_schema(engine)
    engine.dispose()


def _create_all(engine) -> None:
    """Build the schema the way app startup used to, before Alembic owned it."""
    SQLModel.metadata.create_all(engine)


def _preflight(url: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "scripts/check_database.py", "--url", url],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
        check=False,
    )


def test_upgrade_fails_on_an_unstamped_create_all_database(clean_database):
    """
    001_initial calls op.create_table unguarded, so it collides with anything
    create_all already made. Asserting the failure is the point: it is why the
    preflight exists, and why `stamp` rather than `upgrade` is the answer here.
    """
    _create_all(clean_database)
    assert stamped_revision(clean_database) is None

    result = run_alembic("upgrade", "head", url=TEST_DATABASE_URL)

    assert result.returncode != 0, "expected upgrade to collide with existing tables"
    assert "already exists" in (result.stdout + result.stderr)


def test_the_preflight_says_stamp_for_that_database(clean_database):
    """The recovery path a human is sent down, on the dialect that matters."""
    _create_all(clean_database)

    result = _preflight(TEST_DATABASE_URL)

    assert "alembic stamp head" in result.stdout, result.stdout
    assert "Drift: none" in result.stdout, result.stdout
    assert result.returncode == 1, "a database needing action must not exit 0"


def test_upgrade_succeeds_on_a_database_stamped_partway_then_extended(clean_database):
    """
    The state CI never covered, and the one a real database was found in.

    Stamped at a4b5c6d7e8f9, with the tables the remaining migrations create
    already present because create_all made them. `upgrade head` has to walk
    through those migrations without colliding -- which only works because they
    guard each object. If a future migration is written without that guard,
    this test is what fails.
    """
    first = run_alembic("upgrade", BEFORE_THE_GUARDED_MIGRATIONS, url=TEST_DATABASE_URL)
    assert first.returncode == 0, first.stdout + first.stderr

    before = set(inspect(clean_database).get_table_names())
    _create_all(clean_database)
    added = set(inspect(clean_database).get_table_names()) - before
    assert added, "create_all should have added the tables the later migrations create"

    result = run_alembic("upgrade", "head", url=TEST_DATABASE_URL)

    assert result.returncode == 0, (
        "upgrade head failed on a database create_all had extended. The "
        "migrations after "
        f"{BEFORE_THE_GUARDED_MIGRATIONS} guard each object with _table_exists "
        "for exactly this case.\n\n" + result.stdout + result.stderr
    )
    assert stamped_revision(clean_database) == alembic_head()

    inspector = inspect(clean_database)
    expected = set(SQLModel.metadata.tables) - {"alembic_version"}
    assert expected <= set(inspector.get_table_names())


def test_stamping_then_upgrading_reaches_head(clean_database):
    """Completes the recovery path: stamp, then upgrade is a clean no-op."""
    _create_all(clean_database)

    stamp = run_alembic("stamp", "head", url=TEST_DATABASE_URL)
    assert stamp.returncode == 0, stamp.stdout + stamp.stderr
    assert stamped_revision(clean_database) == alembic_head()

    result = run_alembic("upgrade", "head", url=TEST_DATABASE_URL)
    assert result.returncode == 0, result.stdout + result.stderr

    preflight = _preflight(TEST_DATABASE_URL)
    assert "Ready." in preflight.stdout, preflight.stdout
    assert preflight.returncode == 0


def test_the_preflight_reports_an_empty_database(clean_database):
    """The other end of the range, so the verdicts are pinned on Postgres too."""
    result = _preflight(TEST_DATABASE_URL)

    assert "Empty database" in result.stdout, result.stdout
    assert "alembic upgrade head" in result.stdout
    assert result.returncode == 1
