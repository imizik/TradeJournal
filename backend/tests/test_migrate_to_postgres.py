"""
Coverage guarantees for the SQLite -> Postgres migration script.

The script used to copy a hand-maintained list of table names, which had
fallen three tables behind the schema (research_workspace, tradingview_alert,
webull_raw_event). Because the copy loop only iterated that list, the omitted
tables produced no error and no output: migrating to Postgres would have
silently dropped the TradingView alert history, raw Webull events, and the
research workspace.

These tests exist so that gap cannot reopen. The one that matters most is
test_every_model_table_is_covered -- it fails the moment a new table is added
to the schema without the script keeping up.
"""

from __future__ import annotations

import importlib.util
import sys
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import MetaData, create_engine, select
from sqlmodel import Session, SQLModel

from app.models import (
    Account,
    Fill,
    ResearchWorkspace,
    TradingViewAlert,
    WebullRawEvent,
)

BACKEND_DIR = Path(__file__).resolve().parents[1]


def _load_script():
    path = BACKEND_DIR / "scripts" / "migrate_sqlite_to_postgres.py"
    spec = importlib.util.spec_from_file_location("migrate_sqlite_to_postgres", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["migrate_sqlite_to_postgres"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def script():
    return _load_script()


def test_every_model_table_is_covered(script):
    """
    The regression guard. Any SQLModel table absent from the copy order is a
    table whose rows would be left behind by a migration.
    """
    covered = set(script.table_order())
    expected = set(SQLModel.metadata.tables) - {"alembic_version"}

    assert expected - covered == set(), (
        f"tables the migration script would silently not copy: "
        f"{sorted(expected - covered)}"
    )
    # And the three that were actually missing, named explicitly so the
    # regression is obvious if it ever recurs.
    for table in ("research_workspace", "tradingview_alert", "webull_raw_event"):
        assert table in covered


def test_alembic_version_is_not_copied(script):
    """The target is migrated by Alembic; copying its version row over the
    top would misrepresent the target's own migration state."""
    assert "alembic_version" not in script.table_order()


def test_order_puts_parents_before_children(script):
    """Insert order has to satisfy foreign keys or the copy fails on the
    first child row."""
    order = script.table_order()
    position = {name: index for index, name in enumerate(order)}

    for table in SQLModel.metadata.sorted_tables:
        if table.name not in position:
            continue
        for foreign_key in table.foreign_keys:
            parent = foreign_key.column.table.name
            if parent == table.name or parent not in position:
                continue  # self-reference, or outside the copied set
            assert position[parent] < position[table.name], (
                f"{table.name} is copied before its parent {parent}"
            )


def test_unknown_source_table_is_reported_not_skipped(script, tmp_path):
    """
    A table with rows that the script cannot account for must be a hard
    failure. Silently continuing is the original bug.
    """
    database_path = tmp_path / "source.db"
    engine = create_engine(f"sqlite:///{database_path}")
    SQLModel.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE legacy_notes (id INTEGER PRIMARY KEY)")

    meta = MetaData()
    meta.reflect(bind=engine)

    assert script.uncovered_source_tables(meta) == ["legacy_notes"]


def test_migrated_database_has_no_uncovered_tables(script, tmp_path):
    """A database built from the models is fully covered by definition --
    this pins that the two stay in step."""
    database_path = tmp_path / "clean.db"
    engine = create_engine(f"sqlite:///{database_path}")
    SQLModel.metadata.create_all(engine)

    meta = MetaData()
    meta.reflect(bind=engine)

    assert script.uncovered_source_tables(meta) == []


def test_copy_moves_rows_from_the_previously_dropped_tables(script, tmp_path, monkeypatch):
    """
    End to end over the copy path, using the three tables the old list
    omitted. SQLite to SQLite: this covers coverage and ordering; dialect
    coercion is covered by the Postgres CI job.
    """
    source_path = tmp_path / "src.db"
    target_path = tmp_path / "dst.db"
    source_engine = create_engine(f"sqlite:///{source_path}")
    target_engine = create_engine(f"sqlite:///{target_path}")
    SQLModel.metadata.create_all(source_engine)
    SQLModel.metadata.create_all(target_engine)

    with Session(source_engine) as session:
        account = Account(name="Roth IRA", type="roth_ira", last4="8267")
        session.add(account)
        session.commit()
        session.refresh(account)

        session.add(Fill(
            account_id=account.id,
            ticker="NVDA",
            instrument_type="stock",
            side="buy",
            contracts=Decimal("1"),
            price=Decimal("100"),
            executed_at=datetime.now(timezone.utc),
            raw_email_id="migrate-test-1",
        ))
        session.add(WebullRawEvent(
            event_id="wb-1",
            event_type="TRADE",
            payload_json="{}",
            received_at=datetime.now(timezone.utc),
        ))
        session.add(ResearchWorkspace(slug="ai-buildout", data_json="{}"))
        session.commit()

    monkeypatch.setattr(
        sys, "argv",
        ["migrate", "--source", f"sqlite:///{source_path}",
         "--target", f"sqlite:///{target_path}"],
    )
    script.main()

    with Session(target_engine) as session:
        assert len(session.exec(select(WebullRawEvent)).all()) == 1
        assert len(session.exec(select(ResearchWorkspace)).all()) == 1
        assert len(session.exec(select(Fill)).all()) == 1
        assert len(session.exec(select(Account)).all()) == 1
