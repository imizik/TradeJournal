"""
The preflight that decides whether `alembic stamp head` is honest.

Context: app/database.py calls create_all() at startup, so a database can have
a complete, correct schema and an empty alembic_version table. On that
database `alembic upgrade head` fails trying to re-create existing tables, and
the fix is `stamp`, not `upgrade`. But stamping a database whose schema has
genuinely drifted records a migration state that is not true.

So the whole value of this script is the distinction between a rendering
difference and a real difference. The tests that matter are the ones proving
it still refuses: a check that always says "fine" would be worse than nothing,
which is the failure this repository already hit twice in the parity guard.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from sqlalchemy import (
    BigInteger,
    Float,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.dialects.postgresql import DOUBLE_PRECISION
from sqlmodel import SQLModel

BACKEND_DIR = Path(__file__).resolve().parents[1]


def _load_script():
    path = BACKEND_DIR / "scripts" / "check_database.py"
    spec = importlib.util.spec_from_file_location("check_database", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_database"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def script():
    return _load_script()


@pytest.fixture
def clean_engine(tmp_path):
    """A database built the way app startup builds one: create_all, no alembic."""
    engine = create_engine(f"sqlite:///{tmp_path}/clean.db")
    SQLModel.metadata.create_all(engine)
    return engine


@pytest.mark.parametrize(
    "live, model",
    [
        (Text(), String()),                 # migration wrote TEXT, create_all writes VARCHAR
        (DOUBLE_PRECISION(), Float()),      # Postgres reflects FLOAT as DOUBLE PRECISION
        (String(50), String(200)),          # a widened length shares an affinity
        (BigInteger(), Integer()),          # as does a widened integer
    ],
)
def test_rendering_differences_are_not_drift(script, live, model):
    """
    The same column spelled differently by two backends, or by create_all
    versus a migration. Reporting these would make every real database look
    broken and train the operator to ignore the output.
    """
    assert not script._types_differ(live, model)


@pytest.mark.parametrize(
    "live, model",
    [
        (Integer(), String()),
        (String(), Integer()),
        (Float(), String()),
    ],
)
def test_genuine_type_changes_are_still_drift(script, live, model):
    """The check has to keep refusing, or it is decoration."""
    assert script._types_differ(live, model)


def test_a_freshly_created_database_shows_no_drift(script, clean_engine):
    assert script.schema_drift(clean_engine) == []


def test_a_missing_column_is_drift(script, clean_engine):
    """The failure that matters: stamping here would hide a broken schema."""
    with clean_engine.begin() as connection:
        connection.exec_driver_sql("ALTER TABLE trade DROP COLUMN ai_review")

    problems = script.schema_drift(clean_engine)
    assert any("trade.ai_review" in problem for problem in problems), problems


def test_a_missing_table_is_drift(script, clean_engine):
    with clean_engine.begin() as connection:
        connection.exec_driver_sql("DROP TABLE tradingview_alert")

    problems = script.schema_drift(clean_engine)
    assert any("tradingview_alert" in problem for problem in problems), problems


def test_a_table_the_models_do_not_know_about_is_drift(script, clean_engine):
    with clean_engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE stray_table (id INTEGER PRIMARY KEY)")

    problems = script.schema_drift(clean_engine)
    assert any("stray_table" in problem for problem in problems), problems


def test_alembic_version_is_never_reported_as_a_stray_table(script, clean_engine):
    """Alembic owns that table; it is not part of the models by design."""
    with clean_engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE alembic_version (version_num VARCHAR(32))")

    assert script.schema_drift(clean_engine) == []


def test_unstamped_database_reports_no_revision(script, clean_engine):
    """A create_all-built database: correct schema, no migration record."""
    assert script.stamped_revision(clean_engine) is None


def test_stamped_revision_is_read_back(script, clean_engine):
    with clean_engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE alembic_version (version_num VARCHAR(32))")
        connection.exec_driver_sql("INSERT INTO alembic_version VALUES ('2e6f9a1b4c7d')")

    assert script.stamped_revision(clean_engine) == "2e6f9a1b4c7d"


def test_there_is_exactly_one_migration_head(script):
    """Two heads mean `upgrade head` is ambiguous and the verdict is unsound."""
    assert script.alembic_head() is not None


def test_typedecorator_columns_are_not_reported_as_drift(script, clean_engine):
    """
    Regression. ExactDecimal is String(48) on SQLite and Numeric on Postgres,
    and a UUID primary key is stored as CHAR(32); comparing declared affinity
    alone flagged every one of those on a database that was entirely correct.
    Postgres hid this because it reflects native types back; SQLite exposed it.
    """
    problems = [p for p in script.schema_drift(clean_engine) if ".id:" in p or "price" in p]
    assert problems == [], problems
