"""Database boundary for the webhook-only TradingView ingress.

Locally this independently opens the same default SQLite file. When the
private app uses another database, ``TRADINGVIEW_DATABASE_URL`` must point to
that database, preferably through a role that can access only the
``tradingview_alert`` table. Schema migrations remain a separate privileged
deployment step.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import event
from sqlmodel import Session, create_engine


_BACKEND_DIR = Path(__file__).resolve().parent.parent
# Never load the private application's shared .env into the public process.
# Local ingress configuration belongs in this dedicated file; production
# should inject a service-specific environment instead.
load_dotenv(_BACKEND_DIR / ".env.tradingview")

_default_sqlite_path = _BACKEND_DIR / "data" / "trade_journal.db"
_default_sqlite_path.parent.mkdir(parents=True, exist_ok=True)
_fallback_database_url = (
    os.getenv("DATABASE_URL", "").strip()
    or f"sqlite:///{_default_sqlite_path}"
)
TRADINGVIEW_DATABASE_URL = (
    os.getenv("TRADINGVIEW_DATABASE_URL", "").strip()
    or _fallback_database_url
)

_connect_args = (
    {"check_same_thread": False, "timeout": 30}
    if TRADINGVIEW_DATABASE_URL.startswith("sqlite")
    else {}
)
tradingview_engine = create_engine(
    TRADINGVIEW_DATABASE_URL,
    connect_args=_connect_args,
)
if TRADINGVIEW_DATABASE_URL.startswith("sqlite"):

    @event.listens_for(tradingview_engine, "connect")
    def _set_sqlite_wal(dbapi_conn, _record) -> None:
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()


def get_tradingview_session_factory() -> Callable[[], Session]:
    """Return a lazy session constructor without checking out a connection."""

    return lambda: Session(tradingview_engine)
