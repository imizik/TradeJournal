"""Copy the local SQLite database into an empty Postgres database.

Usage:
    python scripts/migrate_sqlite_to_postgres.py --target "$DATABASE_URL"

Run Alembic against the target first so the schema exists:
    DATABASE_URL="$DATABASE_URL" alembic upgrade head

Table coverage is derived from the SQLModel models, in foreign-key dependency
order. It used to be a hand-maintained list, which had silently fallen three
tables behind the schema (research_workspace, tradingview_alert,
webull_raw_event) -- and because the copy loop only iterated that list, those
tables produced no error and no output. Anyone migrating to Postgres would
have lost their TradingView alert history, raw Webull events, and research
workspace without a single warning.

A source table this script cannot account for is now a hard failure, not a
silent skip.
"""

from __future__ import annotations

import argparse
import sys
import uuid
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import MetaData, create_engine, delete, select
from sqlalchemy.sql.sqltypes import Date, DateTime

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from sqlmodel import SQLModel  # noqa: E402

from app import models as _models  # noqa: E402,F401  (registers every table)


DEFAULT_SQLITE_URL = f"sqlite:///{Path(__file__).resolve().parent.parent / 'data' / 'trade_journal.db'}"

# Alembic owns this on the target; it is not application data.
_NOT_APPLICATION_DATA = {"alembic_version"}


def table_order() -> list[str]:
    """
    Every model table, parents before children.

    sorted_tables resolves foreign-key dependencies, which is exactly the
    order rows must be inserted in (and the reverse of the order they must be
    deleted in). Deriving it from the models means adding a table to the
    schema cannot leave this script behind.
    """
    return [
        table.name
        for table in SQLModel.metadata.sorted_tables
        if table.name not in _NOT_APPLICATION_DATA
    ]


def uncovered_source_tables(source_meta: MetaData) -> list[str]:
    """Tables holding data in the source that this script would not copy."""
    covered = set(table_order()) | _NOT_APPLICATION_DATA
    return sorted(name for name in source_meta.tables if name not in covered)


def _coerce_value(value, target_column):
    if value is None:
        return None
    type_name = target_column.type.__class__.__name__.lower()
    if "uuid" in type_name and isinstance(value, str):
        return uuid.UUID(value)
    if isinstance(target_column.type, DateTime) and isinstance(value, str):
        return datetime.fromisoformat(value)
    if isinstance(target_column.type, Date) and not isinstance(target_column.type, DateTime) and isinstance(value, str):
        return date.fromisoformat(value)
    return value


def _coerce_row(row: dict, target_table) -> dict:
    return {
        column.name: _coerce_value(row[column.name], column)
        for column in target_table.columns
        if column.name in row
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate Trade Journal SQLite data to Postgres.")
    parser.add_argument("--source", default=DEFAULT_SQLITE_URL)
    parser.add_argument("--target", required=True)
    parser.add_argument("--replace", action="store_true", help="Delete target rows before copying")
    args = parser.parse_args()

    source_engine = create_engine(args.source)
    target_engine = create_engine(args.target)

    source_meta = MetaData()
    target_meta = MetaData()
    source_meta.reflect(bind=source_engine)
    target_meta.reflect(bind=target_engine)

    order = table_order()

    # A table with rows in the source that this script does not know about is
    # silent data loss -- the failure mode this script previously had. Refuse.
    unknown = uncovered_source_tables(source_meta)
    if unknown:
        print("ERROR: source tables this script cannot copy:", file=sys.stderr)
        for name in unknown:
            print(f"  - {name}", file=sys.stderr)
        print(
            "\nThey are not SQLModel tables, so they are outside the app schema.\n"
            "Copy them by hand or drop them, then re-run.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    missing_in_target = [n for n in order if n not in target_meta.tables]
    if missing_in_target:
        print("ERROR: target is missing tables:", file=sys.stderr)
        for name in missing_in_target:
            print(f"  - {name}", file=sys.stderr)
        print(
            '\nRun `DATABASE_URL="..." alembic upgrade head` against the target '
            "first.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    copied = 0
    with source_engine.connect() as source_conn, target_engine.begin() as target_conn:
        if args.replace:
            for table_name in reversed(order):
                target_conn.execute(delete(target_meta.tables[table_name]))

        for table_name in order:
            if table_name not in source_meta.tables:
                # In the models and the target, but never created in the
                # source. Worth saying out loud rather than passing silently.
                print(f"{table_name}: absent from source, skipped")
                continue
            source_table = source_meta.tables[table_name]
            target_table = target_meta.tables[table_name]
            rows = [
                _coerce_row(dict(row._mapping), target_table)
                for row in source_conn.execute(select(source_table))
            ]
            if not rows:
                print(f"{table_name}: 0")
                continue
            target_conn.execute(target_table.insert(), rows)
            copied += len(rows)
            print(f"{table_name}: {len(rows)}")

    print(f"\n{copied} row(s) copied across {len(order)} table(s).")


if __name__ == "__main__":
    main()
