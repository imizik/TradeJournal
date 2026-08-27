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

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import create_engine, inspect, text  # noqa: E402
from sqlmodel import SQLModel  # noqa: E402

import app.models  # noqa: F401,E402  -- registers every table on the metadata
from app.environment import describe  # noqa: E402

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


def alembic_head() -> str | None:
    """The single head revision the migration scripts define, if there is one."""
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        config = Config(str(BACKEND_DIR / "alembic.ini"))
        config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
        heads = ScriptDirectory.from_config(config).get_heads()
        return heads[0] if len(heads) == 1 else None
    except Exception:
        return None


def stamped_revision(engine) -> str | None:
    """What alembic_version says, or None if the table is absent or empty."""
    if not inspect(engine).has_table("alembic_version"):
        return None
    with engine.connect() as connection:
        row = connection.execute(text("SELECT version_num FROM alembic_version")).first()
    return row[0] if row else None


def schema_drift(engine) -> list[str]:
    """Differences between the live schema and what the models declare."""
    inspector = inspect(engine)
    live_tables = set(inspector.get_table_names()) - {"alembic_version"}
    model_tables = set(SQLModel.metadata.tables)

    problems = []
    for name in sorted(model_tables - live_tables):
        problems.append(f"table missing from the database: {name}")
    for name in sorted(live_tables - model_tables):
        problems.append(f"table present but not in the models: {name}")

    for name in sorted(live_tables & model_tables):
        live = {c["name"]: c for c in inspector.get_columns(name)}
        model = SQLModel.metadata.tables[name].columns
        for column in model:
            if column.name not in live:
                problems.append(f"{name}.{column.name}: column missing from the database")
                continue
            actual = live[column.name]["type"]
            if _types_differ(actual, column.type, engine.dialect):
                problems.append(
                    f"{name}.{column.name}: database has {actual}, models declare {column.type}"
                )
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", help="database URL; defaults to the configured DATABASE_URL")
    args = parser.parse_args()

    environment = describe(args.url) if args.url else describe()
    url = args.url
    if url is None:
        from app.database import DATABASE_URL

        url = DATABASE_URL

    print("Database")
    print(f"  environment  {environment.name}")
    print(f"  backend      {environment.backend}")
    print(f"  identity     {environment.identity}")
    print(f"  confirmation required for destructive ops: "
          f"{'yes' if environment.destructive_requires_confirmation else 'no'}")

    engine = create_engine(url)
    try:
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
