"""Finite publisher of per-trade feature rows for the pre-trade check service.

Runs as its own UID with a read-only database credential delivered by systemd
LoadCredential; selects only the narrow view (deploy/check_scope.py) inside a
read-only transaction and writes a content-addressed feature file. It never
serves, never holds a provider credential and never writes the journal.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

VIEW = "pretrade_feature_source"
_CREDENTIAL_LIMIT = 8192


def _clean_environment():
    from cloud_mcp_d0 import reject_model_credentials

    reject_model_credentials()
    if any(name in os.environ for name in ("DATABASE_URL", "MIGRATION_DATABASE_URL", "JOURNAL_EXPORT_DATABASE_URL")) \
            or any(name.startswith(("PG", "ALPACA_", "APCA_")) for name in os.environ):
        raise ValueError("Ambient database/provider environment is forbidden")


POSITION_VIEW = "pretrade_position_source"
CAPTURE_VIEW = "pretrade_capture_source"


def read_view(database_url: str, view: str = VIEW) -> list[dict]:
    from sqlalchemy import create_engine, text

    engine = create_engine(database_url, pool_pre_ping=False, connect_args={"connect_timeout": 10}
        if database_url.startswith("postgresql") else {})
    try:
        with engine.connect() as connection:
            if connection.dialect.name == "postgresql":
                connection.execute(text("SET TRANSACTION READ ONLY"))
            return [dict(row) for row in connection.execute(text(f"SELECT * FROM {view}")).mappings()]
    finally:
        engine.dispose()


def run(pointer_file: Path, database_url_file: Path) -> dict:
    _clean_environment()
    from journal_coach_refresh import _regular_private_file
    from pretrade_features import CAPTURE_KEYS, POSITION_KEYS, context_rows, publish, publish_context, rows_from_view

    url = _regular_private_file(database_url_file, _CREDENTIAL_LIMIT, "database credential").decode().strip()
    if not url or "\n" in url or "\r" in url:
        raise ValueError("Database credential is invalid")
    result = publish(rows_from_view(read_view(url)), pointer_file)
    try:
        positions = context_rows(read_view(url, POSITION_VIEW), POSITION_KEYS)
        captures = context_rows(read_view(url, CAPTURE_VIEW), CAPTURE_KEYS)
    except Exception:
        # Context views are applied separately; history still publishes without them.
        result["context"] = "unavailable"
        return result
    result["context"] = publish_context(positions, captures, pointer_file.parent / "context.json")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pointer", type=Path, required=True)
    parser.add_argument("--database-url-file", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = run(args.pointer, args.database_url_file)
    except Exception:
        # Errors can carry connection strings or row values; never log them.
        print("Pre-trade feature publication failed", file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
