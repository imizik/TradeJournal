"""
Shared Postgres test plumbing.

Two modules need a disposable Postgres database: test_postgres_parity.py for
dialect behaviour, and test_postgres_migration_paths.py for the states a real
database is actually found in. They need different schema lifetimes -- parity
builds the migrated schema once per module, migration paths rebuild it per test
-- so they cannot share fixtures, but they must share the guard.

Not a test module by name, so pytest does not collect it (testpaths collects
test_*.py). Deliberately not a conftest: this is imported explicitly, which
makes the dependency visible in each module that uses it.

The reason this file exists rather than a copy-paste: _refuse_if_not_disposable
stands between `DROP SCHEMA public CASCADE` and someone's database. Two copies
of a data-loss guard is how they drift, and this repository has already hit
that shape more than once.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import inspect, text

BACKEND_DIR = Path(__file__).resolve().parents[1]

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "").strip()

requires_postgres = pytest.mark.skipif(
    not TEST_DATABASE_URL.startswith("postgresql"),
    reason="set TEST_DATABASE_URL to a Postgres URL to run these tests",
)

# Postgres bookkeeping these modules did not create and do not count as data.
BOOKKEEPING_TABLES = {"alembic_version"}

ALLOW_DESTRUCTIVE = os.environ.get(
    "TEST_DATABASE_ALLOW_DESTRUCTIVE", ""
).strip().lower() in {"1", "true", "yes"}


def populated_tables(engine) -> list[str]:
    """
    Every table in `public` holding rows -- not just the ones in
    SQLModel.metadata.

    DROP SCHEMA public CASCADE destroys the whole schema, so the guard has to
    look at the whole schema. A legacy table left by an older version of the
    app, or anything else someone put there, is invisible to a model-driven
    check and would be destroyed silently.
    """
    inspector = inspect(engine)
    populated: list[str] = []
    with engine.connect() as connection:
        for table in sorted(inspector.get_table_names()):
            if table in BOOKKEEPING_TABLES:
                continue
            count = connection.execute(text(f'SELECT COUNT(*) FROM "{table}"')).scalar_one()
            if count:
                populated.append(f"{table} ({count} row(s))")
    return populated


def refuse_if_not_disposable(engine) -> None:
    """
    These tests run DROP SCHEMA public CASCADE. Refuse a database that has
    anything in it, unless a human has explicitly said to destroy it.

    Deliberately not clever. Earlier versions tried to infer disposability --
    first from the fill table alone, then from a marker table left behind by a
    previous run -- and both inferences were wrong in a way that ends in data
    loss: a database with no fills can still hold irreplaceable TradingView
    alerts, and a marker left by an interrupted run keeps authorizing
    destruction long after the database has been repurposed.

    So there is no inference. Empty is safe. Non-empty needs
    TEST_DATABASE_ALLOW_DESTRUCTIVE, which someone has to set on purpose.
    CI never needs it: its service container starts empty every run, which
    also means this guard doubles as proof the container really is fresh.
    """
    populated = populated_tables(engine)
    if not populated:
        return
    if ALLOW_DESTRUCTIVE:
        return
    raise AssertionError(
        "TEST_DATABASE_URL points at a database that is not empty:\n"
        + "\n".join(f"  - {entry}" for entry in populated)
        + "\n\nThese tests run DROP SCHEMA public CASCADE. Point them at an "
        "empty database, or set TEST_DATABASE_ALLOW_DESTRUCTIVE=1 to confirm "
        "you want this one destroyed."
    )


def reset_schema(engine) -> None:
    """Drop and recreate `public`. Callers must have passed the guard first."""
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))


def run_alembic(*args: str, url: str) -> subprocess.CompletedProcess:
    """
    Alembic against a chosen database, out of process.

    alembic/env.py reads the URL through `from app.database import
    DATABASE_URL`, which binds at import time -- in-process, it would target
    whichever database that module already resolved rather than this one.
    """
    return subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", *args],
        cwd=BACKEND_DIR,
        env={**os.environ, "DATABASE_URL": url},
        capture_output=True,
        text=True,
        check=False,
    )
