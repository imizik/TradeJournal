"""
Guards on the migration chain itself.

The app calls SQLModel's create_all() at startup, so a model change with no
matching Alembic revision works perfectly on a fresh local SQLite file and
only fails on a database that was provisioned by `alembic upgrade head` --
which is how the hosted Postgres/Neon database is built. These tests close
that gap by comparing both provisioning paths in CI.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

from sqlalchemy import create_engine as sa_create_engine, inspect
from sqlmodel import SQLModel, create_engine

from app import models as _models  # noqa: F401  (registers every table)

BACKEND_DIR = Path(__file__).resolve().parents[1]

# Uniqueness that the application depends on for correctness, independent of
# whether a given path expresses it as a UNIQUE constraint or a unique index.
# fill.raw_email_id is the import dedupe key; account.last4 is account identity.
REQUIRED_UNIQUE_COLUMNS = {
    "fill": "raw_email_id",
    "account": "last4",
}


def _alembic(database_path: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    # Exported values win over backend/.env, keeping tests off the configured
    # developer/hosted database.
    env["DATABASE_URL"] = f"sqlite:///{database_path}"
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", *arguments],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result


def _normalize_type(raw: str) -> str:
    """
    Collapse spellings that mean the same thing to the database.

    Alembic revisions use sa.String() (VARCHAR) where a few SQLModel fields
    render as TEXT. Both are text affinity in SQLite and both map to text in
    Postgres, so the difference is cosmetic and not worth failing on.
    """
    upper = raw.upper()
    if upper.startswith("VARCHAR") or upper == "TEXT":
        return "TEXT"
    return upper


def _schema(url: str) -> dict[str, dict[str, str]]:
    inspector = inspect(sa_create_engine(url))
    return {
        table: {
            column["name"]: _normalize_type(str(column["type"]))
            for column in inspector.get_columns(table)
        }
        for table in inspector.get_table_names()
        if table != "alembic_version"
    }


def _unique_columns(url: str, table: str) -> set[str]:
    """Columns made unique by either a unique index or a UNIQUE constraint."""
    inspector = inspect(sa_create_engine(url))
    unique: set[str] = set()
    for index in inspector.get_indexes(table):
        if index.get("unique") and len(index["column_names"]) == 1:
            unique.add(index["column_names"][0])
    for constraint in inspector.get_unique_constraints(table):
        if len(constraint["column_names"]) == 1:
            unique.add(constraint["column_names"][0])
    return unique


def test_migration_chain_has_exactly_one_head(tmp_path):
    """
    Two heads means two branches added revisions in parallel and nobody merged
    them; `alembic upgrade head` then fails for everyone. Worth catching on the
    pull request rather than on a deploy.
    """
    result = _alembic(tmp_path / "heads.sqlite", "heads")
    heads = [line for line in result.stdout.splitlines() if line.strip()]
    assert len(heads) == 1, f"expected a single Alembic head, got:\n{result.stdout}"


def test_migrations_produce_the_same_tables_and_columns_as_the_models(tmp_path):
    """
    The check that catches a model field added without a migration: it works
    locally through create_all() and is silently missing on Neon.
    """
    migrated_path = tmp_path / "migrated.sqlite"
    _alembic(migrated_path, "upgrade", "head")
    migrated = _schema(f"sqlite:///{migrated_path}")

    model_path = tmp_path / "models.sqlite"
    model_url = f"sqlite:///{model_path}"
    SQLModel.metadata.create_all(create_engine(model_url))
    from_models = _schema(model_url)

    assert set(migrated) == set(from_models), (
        "table drift between Alembic and the SQLModel models.\n"
        f"  only in migrations: {sorted(set(migrated) - set(from_models))}\n"
        f"  only in models:     {sorted(set(from_models) - set(migrated))}\n"
        "Add the missing Alembic revision, or drop the stale table."
    )

    for table in sorted(migrated):
        migrated_columns = migrated[table]
        model_columns = from_models[table]
        assert set(migrated_columns) == set(model_columns), (
            f"column drift on {table!r}.\n"
            f"  only in migrations: {sorted(set(migrated_columns) - set(model_columns))}\n"
            f"  only in models:     {sorted(set(model_columns) - set(migrated_columns))}\n"
            "A model field with no Alembic revision works locally through "
            "create_all() and is missing on any migrated database."
        )
        mismatched = {
            column: (migrated_columns[column], model_columns[column])
            for column in migrated_columns
            if migrated_columns[column] != model_columns[column]
        }
        assert not mismatched, f"column type drift on {table!r}: {mismatched}"


def test_migrated_schema_enforces_the_dedupe_and_identity_keys(tmp_path):
    """
    Indexes are deliberately not compared wholesale: the models declare
    unique=True (a unique index) where revision 003 creates named UNIQUE
    constraints, which inspect() reports differently while enforcing the same
    thing. What actually matters is that uniqueness exists on a migrated
    database, however it is spelled.
    """
    migrated_path = tmp_path / "unique.sqlite"
    _alembic(migrated_path, "upgrade", "head")
    url = f"sqlite:///{migrated_path}"

    for table, column in REQUIRED_UNIQUE_COLUMNS.items():
        assert column in _unique_columns(url, table), (
            f"{table}.{column} is not unique on a migrated database. "
            "Fill import dedupe and account identity both depend on it."
        )
