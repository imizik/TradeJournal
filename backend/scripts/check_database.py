"""
Read-only preflight: which database is this, and is its schema ready?

Written for the moment you point a worktree at a Neon branch for the first
time. Two things can be true and invisible: you may be connected to a
different database than you think, and its schema may have been built by
`create_all` at startup rather than by Alembic -- in which case the
alembic_version table is empty and `alembic upgrade head` will try to create
tables that already exist.

This script answers both without writing anything. It never creates, alters,
or drops. Run it before the first migration and before anything destructive.

    python scripts/check_database.py
    python scripts/check_database.py --url postgresql+psycopg://...

Exit code 0 means ready to use; 1 means something needs a decision first.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from urllib.parse import urlparse

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import UniqueConstraint, create_engine, inspect, text  # noqa: E402
from sqlmodel import SQLModel  # noqa: E402

import app.models  # noqa: F401,E402  -- registers every table on the metadata
from app.environment import describe, resolve_database_url  # noqa: E402
from app.schema import alembic_head, stamped_revision  # noqa: E402,F401

def _types_differ(live, model, dialect=None) -> bool:
    """
    Compare what the type *is*, not how it is spelled.

    The same column renders differently depending on who created it and which
    backend it lives on: create_all writes VARCHAR where a migration wrote
    TEXT, Postgres reflects FLOAT as DOUBLE PRECISION and DATETIME as
    TIMESTAMP, and a UUID is CHAR(32) on SQLite. None of those are drift.
    SQLAlchemy's type affinity collapses all of them while keeping genuine
    changes -- String to Integer, say -- distinct.

    Affinity alone is not enough here. This codebase has TypeDecorator columns
    -- ExactDecimal is String(48) on SQLite and Numeric on Postgres, and a
    UUID is stored as CHAR(32) -- whose declared affinity does not match what
    the backend reflects back even when the column is byte-for-byte correct.
    So a column is also considered unchanged when both sides compile to the
    same SQL on this dialect, which is the more precise test when it applies.

    What this deliberately does not catch: a widened length or precision
    (VARCHAR(50) -> VARCHAR(200), Integer -> BigInteger). Those share an
    affinity. This check answers "is the schema the one the models describe",
    not "is every storage detail identical".
    """
    if dialect is not None:
        try:
            if live.compile(dialect) == model.compile(dialect):
                return False
        except Exception:
            pass
    try:
        return live._type_affinity is not model._type_affinity
    except AttributeError:
        return str(live) != str(model)


def driver_problem(url: str) -> str | None:
    """
    Catch the URL that names no driver, before SQLAlchemy picks one for us.

    Neon (and every other Postgres host) hands out `postgresql://...`. Pasted
    verbatim, SQLAlchemy defaults that to the psycopg2 dialect, which this
    project does not install -- it uses psycopg v3. The resulting error is
    `No module named 'psycopg2'`, which reads as a missing dependency and
    invites `pip install psycopg2` rather than the one-word fix to the URL.
    """
    scheme = urlparse(url).scheme
    if scheme == "postgresql":
        fixed = url.replace("postgresql://", "postgresql+psycopg://", 1)
        return (
            "The URL names no driver, so SQLAlchemy would default to psycopg2, "
            "which this project does not install (it uses psycopg v3).\n"
            "This is the raw form a hosting provider gives you; add the driver:\n"
            f"  {fixed.split('@')[-1] if '@' in fixed else fixed}\n"
            "  ^ set DATABASE_URL to postgresql+psycopg://... in backend/.env"
        )
    if scheme in {"postgres", "postgresql+psycopg2"}:
        return (
            f"Unsupported scheme {scheme!r}. This project uses psycopg v3: "
            "set DATABASE_URL to postgresql+psycopg://... in backend/.env"
        )
    return None


def _live_unique_column_sets(inspector, table: str) -> set[frozenset[str]]:
    """
    Every uniqueness guarantee on a table, as sets of column names.

    Constraints and unique indexes are unioned rather than compared apart:
    the same `unique=True` renders as a UNIQUE constraint on one backend and
    a unique index on another, and comparing by name would flag a database
    that is correct. What matters is which column combinations are guaranteed
    unique, not what the object enforcing it is called.
    """
    sets: set[frozenset[str]] = set()
    for constraint in inspector.get_unique_constraints(table):
        sets.add(frozenset(constraint["column_names"]))
    for index in inspector.get_indexes(table):
        if index.get("unique") and index.get("column_names"):
            sets.add(frozenset(c for c in index["column_names"] if c))
    return sets


def _model_unique_column_sets(table) -> set[frozenset[str]]:
    """The same, as the models declare it."""
    sets: set[frozenset[str]] = set()
    for constraint in table.constraints:
        if isinstance(constraint, UniqueConstraint):
            sets.add(frozenset(column.name for column in constraint.columns))
    for index in table.indexes:
        if index.unique:
            sets.add(frozenset(column.name for column in index.columns))
    for column in table.columns:
        if column.unique:
            sets.add(frozenset([column.name]))
    return sets


def schema_drift(engine) -> list[str]:
    """
    Differences between the live schema and what the models declare.

    Tables and columns are the obvious half. Constraints are the half that
    decides whether a stamp is safe: a database can have every table and every
    column and still have lost the unique constraint on fill.raw_email_id,
    which is what stops the same brokerage email being imported twice. Stamping
    such a database records "already migrated" and permanently skips the
    migration that would restore it, so duplicate fills accumulate silently and
    PnL is wrong. Presence is not correctness.
    """
    inspector = inspect(engine)
    live_tables = set(inspector.get_table_names()) - {"alembic_version"}
    model_tables = set(SQLModel.metadata.tables)

    problems = []
    for name in sorted(model_tables - live_tables):
        problems.append(f"table missing from the database: {name}")
    for name in sorted(live_tables - model_tables):
        problems.append(f"table present but not in the models: {name}")

    for name in sorted(live_tables & model_tables):
        table = SQLModel.metadata.tables[name]
        live = {c["name"]: c for c in inspector.get_columns(name)}

        for column in table.columns:
            if column.name not in live:
                problems.append(f"{name}.{column.name}: column missing from the database")
                continue
            actual = live[column.name]["type"]
            if _types_differ(actual, column.type, engine.dialect):
                problems.append(
                    f"{name}.{column.name}: database has {actual}, models declare {column.type}"
                )
            # A column that has become nullable has lost a guarantee the
            # application relies on, exactly like a dropped constraint.
            if bool(live[column.name]["nullable"]) and not bool(column.nullable):
                problems.append(f"{name}.{column.name}: nullable in the database, NOT NULL in the models")

        live_unique = _live_unique_column_sets(inspector, name)
        model_unique = _model_unique_column_sets(table)
        for missing in sorted(model_unique - live_unique, key=sorted):
            problems.append(
                f"{name}: no uniqueness guarantee on ({', '.join(sorted(missing))}) -- "
                "the models declare one"
            )
        for extra in sorted(live_unique - model_unique, key=sorted):
            problems.append(
                f"{name}: database enforces uniqueness on ({', '.join(sorted(extra))}) -- "
                "the models do not"
            )

        live_pk = frozenset(inspector.get_pk_constraint(name).get("constrained_columns") or [])
        model_pk = frozenset(column.name for column in table.primary_key)
        if live_pk != model_pk:
            problems.append(
                f"{name}: primary key is ({', '.join(sorted(live_pk)) or 'none'}), "
                f"models declare ({', '.join(sorted(model_pk)) or 'none'})"
            )
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", help="database URL; defaults to the configured DATABASE_URL")
    args = parser.parse_args()

    url = args.url or resolve_database_url()
    environment = describe(url)

    print("Database")
    print(f"  environment  {environment.name}")
    print(f"  backend      {environment.backend}")
    print(f"  identity     {environment.identity}")
    print(f"  confirmation required for destructive ops: "
          f"{'yes' if environment.destructive_requires_confirmation else 'no'}")

    problem = driver_problem(url)
    if problem:
        print(f"\n{problem}")
        return 1

    try:
        engine = create_engine(url)
        with engine.connect():
            pass
    except Exception as error:
        print(f"\nCannot connect: {type(error).__name__}: {error}")
        return 1

    inspector = inspect(engine)
    live_tables = set(inspector.get_table_names()) - {"alembic_version"}
    head = alembic_head()
    stamped = stamped_revision(engine)

    print("\nSchema")
    print(f"  tables present        {len(live_tables)}")
    print(f"  tables in the models  {len(SQLModel.metadata.tables)}")
    print(f"  alembic head on disk  {head or 'could not determine'}")
    print(f"  alembic_version says  {stamped or 'nothing (table absent or empty)'}")

    drift = [] if not live_tables else schema_drift(engine)
    if not live_tables:
        print("\nDrift: not checked -- the database is empty")
    elif drift:
        print(f"\nDrift ({len(drift)}):")
        for problem in drift[:25]:
            print(f"  - {problem}")
        if len(drift) > 25:
            print(f"  ... and {len(drift) - 25} more")
    else:
        print("\nDrift: none -- the live schema matches the models")

    print("\nVerdict")
    if not live_tables:
        print("  Empty database. Run:  alembic upgrade head")
        return 1
    if drift:
        print("  The schema does not match the models. Do NOT stamp -- stamping would")
        print("  record a migration state that is not true. Investigate the differences")
        print("  above before running anything.")
        return 1
    if stamped is None:
        print("  Schema is correct but Alembic has no record of it -- built by create_all,")
        print("  not by migrations. `alembic upgrade head` would fail trying to re-create")
        print("  existing tables. Run instead:  alembic stamp head")
        return 1
    if head and stamped != head:
        print(f"  Behind by at least one migration ({stamped} -> {head}). Run:  alembic upgrade head")
        return 1
    print("  Ready. Schema matches the models and Alembic is at head.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
