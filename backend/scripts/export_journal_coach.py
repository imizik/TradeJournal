#!/usr/bin/env python3
"""Export an explicitly scoped, read-only journal-coach snapshot."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import bindparam, create_engine, text  # noqa: E402

from journal_coach_snapshot import MAX_TRADES, JournalCoachSnapshot, SCHEMA_VERSION  # noqa: E402

MAX_EXPORT_ROWS = MAX_TRADES + 1
TRADE_QUERY = text("""
    SELECT id, ticker, instrument_type, contracts, realized_pnl, status, opened_at, closed_at
    FROM trade
    WHERE account_id IN :account_ids
      AND status IN ('closed', 'expired')
      AND closed_at >= :start_at
      AND closed_at < :after_end_at
    ORDER BY closed_at, id
    LIMIT :row_limit
""").bindparams(bindparam("account_ids", expanding=True))


class ExportError(Exception):
    """Expected safe-to-display export failure."""


def _validate_role(connection) -> None:
    role = connection.execute(text("""
        SELECT rolsuper, rolbypassrls, rolcreatedb, rolcreaterole
        FROM pg_roles
        WHERE rolname = current_user
    """)).one_or_none()
    if role is None or any(role):
        raise ExportError("database role is not restricted")
    membership = connection.execute(text("""
        SELECT r.rolname
        FROM pg_roles AS r
        WHERE r.oid <> (SELECT oid FROM pg_roles WHERE rolname = current_user)
          AND pg_has_role(current_user, r.oid, 'MEMBER')
        LIMIT 1
    """)).first()
    if membership:
        raise ExportError("database role has role memberships")
    schema_create = connection.execute(text("""
        SELECT n.nspname
        FROM pg_namespace AS n
        WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
          AND has_schema_privilege(current_user, n.oid, 'CREATE')
        LIMIT 1
    """)).first()
    if schema_create:
        raise ExportError("database role can create schema objects")
    owned_schema = connection.execute(text("""
        SELECT n.nspname
        FROM pg_namespace AS n
        WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
          AND n.nspowner = (SELECT oid FROM pg_roles WHERE rolname = current_user)
        LIMIT 1
    """)).first()
    if owned_schema:
        raise ExportError("database role owns a user schema")
    writable = connection.execute(text("""
        SELECT c.relname
        FROM pg_class AS c
        JOIN pg_namespace AS n ON n.oid = c.relnamespace
        WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
          AND c.relkind IN ('r', 'p', 'v', 'm', 'f')
          AND (
            c.relowner = (SELECT oid FROM pg_roles WHERE rolname = current_user) OR
            has_table_privilege(current_user, c.oid, 'INSERT') OR
            has_table_privilege(current_user, c.oid, 'UPDATE') OR
            has_table_privilege(current_user, c.oid, 'DELETE') OR
            has_table_privilege(current_user, c.oid, 'TRUNCATE') OR
            has_table_privilege(current_user, c.oid, 'REFERENCES') OR
            has_table_privilege(current_user, c.oid, 'TRIGGER') OR
            has_any_column_privilege(current_user, c.oid, 'INSERT') OR
            has_any_column_privilege(current_user, c.oid, 'UPDATE') OR
            has_any_column_privilege(current_user, c.oid, 'REFERENCES')
          )
        LIMIT 1
    """)).first()
    if writable:
        raise ExportError("database role has write privileges")


def _safe_output(path: Path, content: bytes, replace_existing: bool) -> None:
    path = path.expanduser().absolute()
    parent = path.parent
    if not parent.is_dir():
        raise ExportError("output directory does not exist")
    if path.is_symlink():
        raise ExportError("output path must not be a symlink")
    if path.exists() and not replace_existing:
        raise ExportError("output already exists; pass --replace to replace it")
    fd, temp_name = tempfile.mkstemp(prefix=".journal-coach-", dir=parent)
    temp_path = Path(temp_name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if replace_existing:
            if path.is_symlink():
                raise ExportError("output path must not be a symlink")
            os.replace(temp_path, path)
        else:
            # link() is an atomic no-clobber install; unlike open("x"), it
            # cannot follow a destination symlink inserted after our check.
            os.link(temp_path, path)
            temp_path.unlink()
    except FileExistsError as exc:
        raise ExportError("output already exists; pass --replace to replace it") from exc
    finally:
        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass


def export_snapshot(database_url: str, account_ids: list[UUID], start_day: date, end_day: date) -> JournalCoachSnapshot:
    parsed = urlparse(database_url)
    if parsed.scheme != "postgresql+psycopg" or not parsed.hostname:
        raise ExportError("JOURNAL_EXPORT_DATABASE_URL must be a PostgreSQL psycopg URL")
    if not account_ids:
        raise ExportError("at least one account id is required")
    if start_day > end_day or (end_day - start_day).days + 1 > 31:
        raise ExportError("date window must be ordered and at most 31 inclusive days")
    engine = None
    try:
        engine = create_engine(
            database_url,
            pool_pre_ping=True,
            connect_args={"connect_timeout": 10, "options": "-c statement_timeout=10000"},
        )
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                connection.exec_driver_sql("SET TRANSACTION READ ONLY")
                _validate_role(connection)
                rows = connection.execute(TRADE_QUERY, {
                    "account_ids": [str(account_id) for account_id in account_ids],
                    "start_at": datetime.combine(start_day, time.min),
                    "after_end_at": datetime.combine(end_day + timedelta(days=1), time.min),
                    "row_limit": MAX_EXPORT_ROWS,
                }).mappings().all()
                if len(rows) > MAX_TRADES:
                    raise ExportError("matching trades exceed the 500 row export limit")
                trades = []
                for row in rows:
                    trades.append({
                        "id": str(row["id"]),
                        "ticker": row["ticker"],
                        "instrument_type": row["instrument_type"],
                        "quantity": str(row["contracts"]),
                        "realized_pnl": None if row["realized_pnl"] is None else str(row["realized_pnl"]),
                        "status": row["status"],
                        "opened_at": row["opened_at"],
                        "closed_at": row["closed_at"],
                    })
                snapshot = JournalCoachSnapshot.model_validate({
                    "schema_version": SCHEMA_VERSION,
                    "generated_at": datetime.now(timezone.utc),
                    "start_day": start_day,
                    "end_day": end_day,
                    "source": "approved_journal_export",
                    "sample_data": False,
                    "trades": trades,
                })
            finally:
                transaction.rollback()
        return snapshot
    except ExportError:
        raise
    except Exception as exc:
        raise ExportError("database export failed") from exc
    finally:
        if engine is not None:
            engine.dispose()


def _parse_day(value: str) -> date:
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an ISO date (YYYY-MM-DD)") from exc
    if parsed.isoformat() != value:
        raise argparse.ArgumentTypeError("must be an ISO date (YYYY-MM-DD)")
    return parsed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account-id", action="append", required=True, help="authorized account UUID; may be repeated")
    parser.add_argument("--start-day", required=True, type=_parse_day)
    parser.add_argument("--end-day", required=True, type=_parse_day)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--replace", action="store_true", help="atomically replace an existing regular file")
    args = parser.parse_args(argv)
    raw_url = os.environ.get("JOURNAL_EXPORT_DATABASE_URL")
    if not raw_url:
        print("error: JOURNAL_EXPORT_DATABASE_URL is required", file=sys.stderr)
        return 2
    if "DATABASE_URL" in os.environ and raw_url == os.environ["DATABASE_URL"]:
        print("error: JOURNAL_EXPORT_DATABASE_URL must be configured separately", file=sys.stderr)
        return 2
    try:
        account_ids = [UUID(value) for value in args.account_id]
        if any(str(account_id) != value for account_id, value in zip(account_ids, args.account_id)):
            raise ValueError
        snapshot = export_snapshot(raw_url, account_ids, args.start_day, args.end_day)
        payload = (snapshot.model_dump_json(indent=2) + "\n").encode("utf-8")
        _safe_output(args.output, payload, args.replace)
        print(json.dumps({
            "sha256": hashlib.sha256(payload).hexdigest(),
            "generated_at": snapshot.generated_at.isoformat(),
            "trade_count": len(snapshot.trades),
        }, separators=(",", ":")))
        return 0
    except (ValueError, ExportError) as exc:
        print(f"error: {exc if isinstance(exc, ExportError) else 'account id must be a canonical UUID'}", file=sys.stderr)
        return 2
    except Exception:
        print("error: export failed", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
