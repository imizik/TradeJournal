from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

from sqlalchemy import inspect
from sqlmodel import SQLModel, create_engine

from app import models as _models  # register all SQLModel tables for create_all


BACKEND_DIR = Path(__file__).resolve().parents[1]
PREVIOUS_HEAD = "f1a2b3c4d5e6"
TRADINGVIEW_REVISION = "2e6f9a1b4c7d"

EXPECTED_COLUMNS = {
    "alert_id",
    "contract_version",
    "parser_revision",
    "indicator_version",
    "content_sha256",
    "raw_payload_sha256",
    "symbol",
    "timeframe",
    "setup",
    "side",
    "price",
    "bar_time_ms",
    "bar_time",
    "received_at",
    "updated_at",
    "payload_json",
    "levels_json",
    "context_json",
    "analysis_status",
    "analysis_attempts",
    "analysis_started_at",
    "analysis_completed_at",
    "scorer_revision",
    "verdict",
    "confidence",
    "assessment_json",
    "analysis_error_code",
    "analysis_error",
}

EXPECTED_INDEXES = {
    "ix_tradingview_alert_received_at",
    "ix_tradingview_alert_bar_time",
    "ix_tradingview_alert_symbol_received_at",
    "ix_tradingview_alert_setup_received_at",
    "ix_tradingview_alert_analysis_status_updated_at",
}


def _database_url(database_path: Path) -> str:
    return f"sqlite:///{database_path}"


def _alembic(
    database_path: Path,
    *arguments: str,
    expect_success: bool = True,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    # Exported values win over backend/.env, keeping tests off the configured
    # developer/hosted database.
    env["DATABASE_URL"] = _database_url(database_path)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "alembic",
            "-c",
            "alembic.ini",
            *arguments,
        ],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if expect_success:
        assert result.returncode == 0, result.stdout + result.stderr
    return result


def _rewrite_create_all_table(
    engine,
    *,
    old_sql: str,
    new_sql: str,
) -> None:
    with engine.begin() as connection:
        table_sql = connection.exec_driver_sql(
            "SELECT sql FROM sqlite_master "
            "WHERE type = 'table' AND name = 'tradingview_alert'"
        ).scalar_one()
        assert old_sql in table_sql
        connection.exec_driver_sql(
            "ALTER TABLE tradingview_alert "
            "RENAME TO tradingview_alert_original"
        )
        connection.exec_driver_sql(table_sql.replace(old_sql, new_sql))
        connection.exec_driver_sql(
            "DROP TABLE tradingview_alert_original"
        )


def test_migration_is_the_only_head_and_round_trips(tmp_path):
    database_path = tmp_path / "fresh.sqlite"

    heads = _alembic(database_path, "heads")
    assert heads.stdout.strip() == f"{TRADINGVIEW_REVISION} (head)"

    _alembic(database_path, "upgrade", "head")
    engine = create_engine(_database_url(database_path))
    inspector = inspect(engine)

    assert {
        column["name"]
        for column in inspector.get_columns("tradingview_alert")
    } == EXPECTED_COLUMNS
    assert inspector.get_pk_constraint("tradingview_alert")[
        "constrained_columns"
    ] == ["alert_id"]
    assert {
        index["name"]
        for index in inspector.get_indexes("tradingview_alert")
    } == EXPECTED_INDEXES

    _alembic(database_path, "downgrade", PREVIOUS_HEAD)
    tables_after_downgrade = set(inspect(engine).get_table_names())
    assert "tradingview_alert" not in tables_after_downgrade
    assert "strategy_definition" in tables_after_downgrade

    _alembic(database_path, "upgrade", "head")
    assert "tradingview_alert" in inspect(engine).get_table_names()


def test_migration_repairs_missing_index_after_create_all(tmp_path):
    database_path = tmp_path / "create-all-first.sqlite"
    engine = create_engine(_database_url(database_path))
    SQLModel.metadata.create_all(engine)

    missing_index = "ix_tradingview_alert_symbol_received_at"
    with engine.begin() as connection:
        connection.exec_driver_sql(f"DROP INDEX {missing_index}")

    _alembic(database_path, "stamp", PREVIOUS_HEAD)
    _alembic(database_path, "upgrade", "head")

    indexes = {
        index["name"]
        for index in inspect(engine).get_indexes("tradingview_alert")
    }
    assert indexes == EXPECTED_INDEXES


def test_migration_refuses_to_stamp_an_incompatible_existing_table(tmp_path):
    database_path = tmp_path / "malformed.sqlite"
    engine = create_engine(_database_url(database_path))
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE tradingview_alert "
            "(alert_id VARCHAR(200) PRIMARY KEY)"
        )

    _alembic(database_path, "stamp", PREVIOUS_HEAD)
    result = _alembic(
        database_path,
        "upgrade",
        "head",
        expect_success=False,
    )

    assert result.returncode != 0
    assert "missing column(s)" in result.stdout + result.stderr


def test_migration_refuses_an_existing_index_with_the_wrong_columns(tmp_path):
    database_path = tmp_path / "wrong-index.sqlite"
    engine = create_engine(_database_url(database_path))
    SQLModel.metadata.create_all(engine)

    index_name = "ix_tradingview_alert_symbol_received_at"
    with engine.begin() as connection:
        connection.exec_driver_sql(f"DROP INDEX {index_name}")
        connection.exec_driver_sql(
            f"CREATE INDEX {index_name} "
            "ON tradingview_alert (setup, received_at)"
        )

    _alembic(database_path, "stamp", PREVIOUS_HEAD)
    result = _alembic(
        database_path,
        "upgrade",
        "head",
        expect_success=False,
    )

    assert result.returncode != 0
    assert "index is incompatible" in result.stdout + result.stderr


def test_migration_refuses_wrong_existing_column_type_or_nullability(tmp_path):
    database_path = tmp_path / "wrong-column.sqlite"
    engine = create_engine(_database_url(database_path))
    SQLModel.metadata.create_all(engine)
    _rewrite_create_all_table(
        engine,
        old_sql="bar_time_ms BIGINT NOT NULL",
        new_sql="bar_time_ms TEXT",
    )

    _alembic(database_path, "stamp", PREVIOUS_HEAD)
    result = _alembic(
        database_path,
        "upgrade",
        "head",
        expect_success=False,
    )

    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "column bar_time_ms" in output


def test_migration_refuses_same_name_noop_check_constraint(tmp_path):
    database_path = tmp_path / "wrong-check.sqlite"
    engine = create_engine(_database_url(database_path))
    SQLModel.metadata.create_all(engine)
    _rewrite_create_all_table(
        engine,
        old_sql="side IN ('long', 'short')",
        new_sql="1 = 1",
    )

    _alembic(database_path, "stamp", PREVIOUS_HEAD)
    result = _alembic(
        database_path,
        "upgrade",
        "head",
        expect_success=False,
    )

    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "ck_tradingview_alert_side has the wrong expression" in output
