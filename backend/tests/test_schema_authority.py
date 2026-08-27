"""
Alembic is the only thing that builds the schema.

Startup used to call create_all(), so the app repaired its own database on
every boot. That is why a database could be stamped at one revision with later
tables added by create_all -- a state no migration produces, where `upgrade`
and `stamp` are both plausible. It is also why removing the call immediately
exposed a test-isolation leak that had been silently absorbed for as long as it
existed (see the fixture in test_environment_guard.py).

These tests pin the replacement: the app checks, refuses, and says what to run.
The refusal is the feature -- a schema that repairs itself is a schema that
drifts from its migrations without anyone noticing.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlmodel import SQLModel

import app.models  # noqa: F401  -- registers every table
from app.schema import SchemaNotCurrent, alembic_head, ensure_current, stamped_revision

BACKEND_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def migrated_template(tmp_path_factory) -> Path:
    """
    One database built the way the application now requires: by migrations.

    Built in a subprocess. alembic/env.py reads the URL through
    `from app.database import DATABASE_URL`, and that module binds it at import
    time -- by the time a test runs, it is already bound to the database
    conftest pinned, so setting the environment variable in-process migrates
    the wrong database and leaves the intended one empty.

    Module-scoped and copied per test: the migration chain costs about a second
    and nothing here needs it run more than once.
    """
    database = tmp_path_factory.mktemp("migrated") / "head.db"
    result = subprocess.run(
        [BACKEND_DIR / ".venv" / "bin" / "alembic", "upgrade", "head"],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
        env={**os.environ, "DATABASE_URL": f"sqlite:///{database}"},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return database


def _copy_of(template: Path, destination: Path):
    shutil.copy(template, destination)
    return create_engine(f"sqlite:///{destination}")


def test_a_migrated_database_is_accepted(migrated_template, tmp_path):
    ensure_current(_copy_of(migrated_template, tmp_path / "ok.db"))  # must not raise


def test_an_empty_database_is_refused_with_the_command(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/empty.db")
    with pytest.raises(SchemaNotCurrent) as raised:
        ensure_current(engine)
    assert "empty" in str(raised.value)
    assert "alembic upgrade head" in str(raised.value)


def test_a_create_all_database_is_refused_and_sent_to_the_preflight(tmp_path):
    """
    The state every database built by the old startup path is in: correct
    tables, no migration history. `alembic upgrade head` fails on it and
    `stamp` is only right if the schema really matches, so the app must not
    guess -- it points at the tool that decides.
    """
    engine = create_engine(f"sqlite:///{tmp_path}/create_all.db")
    SQLModel.metadata.create_all(engine)

    with pytest.raises(SchemaNotCurrent) as raised:
        ensure_current(engine)
    message = str(raised.value)
    assert "no migration history" in message
    assert "check_database.py" in message
    assert "upgrade head" not in message, "must not recommend a command that fails here"


def test_a_database_behind_head_is_refused_naming_both_revisions(migrated_template, tmp_path):
    engine = _copy_of(migrated_template, tmp_path / "behind.db")
    with engine.begin() as connection:
        connection.execute(text("UPDATE alembic_version SET version_num = '001_initial'"))

    with pytest.raises(SchemaNotCurrent) as raised:
        ensure_current(engine)
    message = str(raised.value)
    assert "001_initial" in message and (alembic_head() or "") in message
    assert "alembic upgrade head" in message


def test_the_application_refuses_to_start_on_an_unmigrated_database(tmp_path):
    """
    The integration proof. Unit-testing ensure_current() says the function
    works; this says the application actually calls it and will not serve
    requests against a database migrations have not built.

    Out of process because conftest pins DATABASE_URL for the whole session and
    app.database binds its engine at import.
    """
    database = tmp_path / "unmigrated.db"
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import os, sys\n"
            "sys.path.insert(0, '.')\n"
            f"os.environ['DATABASE_URL'] = 'sqlite:///{database}'\n"
            "from fastapi.testclient import TestClient\n"
            "from app.main import app\n"
            "try:\n"
            "    with TestClient(app) as client:\n"
            "        client.get('/health')\n"
            "except Exception as error:\n"
            "    print(type(error).__name__); print(error)\n"
            "    sys.exit(0)\n"
            "sys.exit('the app started against an unmigrated database')\n",
        ],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "SchemaNotCurrent" in result.stdout
    assert "alembic upgrade head" in result.stdout


def test_the_head_is_unambiguous():
    """Two heads would make `upgrade head` ambiguous and the check unsound."""
    assert alembic_head() is not None


def test_stamped_revision_reads_back_what_migrations_wrote(migrated_template, tmp_path):
    engine = _copy_of(migrated_template, tmp_path / "stamped.db")
    assert stamped_revision(engine) == alembic_head()
