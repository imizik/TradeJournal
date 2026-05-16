"""Copy the local SQLite database into an empty Postgres database.

Usage:
    python scripts/migrate_sqlite_to_postgres.py --target "$DATABASE_URL"

Run Alembic against the target first so the schema exists:
    DATABASE_URL="$DATABASE_URL" alembic upgrade head
"""

from __future__ import annotations

import argparse
import uuid
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import MetaData, create_engine, delete, select
from sqlalchemy.sql.sqltypes import Date, DateTime


DEFAULT_SQLITE_URL = f"sqlite:///{Path(__file__).resolve().parent.parent / 'data' / 'trade_journal.db'}"

TABLE_ORDER = [
    "account",
    "fill",
    "dailyreview",
    "tag",
    "trade",
    "tradefill",
    "tradetag",
    "fill_market_context",
    "trade_path_metrics",
    "job_run",
]


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

    with source_engine.connect() as source_conn, target_engine.begin() as target_conn:
        if args.replace:
            for table_name in reversed(TABLE_ORDER):
                if table_name in target_meta.tables:
                    target_conn.execute(delete(target_meta.tables[table_name]))

        for table_name in TABLE_ORDER:
            if table_name not in source_meta.tables or table_name not in target_meta.tables:
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
            print(f"{table_name}: {len(rows)}")


if __name__ == "__main__":
    main()
