import os
from collections.abc import Generator
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine

# Load .env before reading DATABASE_URL. database.py is imported first by
# app.main (before any module that calls load_dotenv), so without this the
# DATABASE_URL set in backend/.env is ignored and the app silently falls back
# to SQLite. load_dotenv does not override already-exported env vars.
_BACKEND_DIR = Path(__file__).resolve().parent.parent
load_dotenv(_BACKEND_DIR / ".env")
load_dotenv(_BACKEND_DIR.parent / ".env")

db_path = Path(__file__).parent.parent / "data" / "trade_journal.db"
db_path.parent.mkdir(parents=True, exist_ok=True)

DEFAULT_DATABASE_URL = f"sqlite:///{db_path}"
DATABASE_URL = os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)

connect_args = {"check_same_thread": False, "timeout": 30} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)

if DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _set_sqlite_wal(dbapi_conn, _rec):
        """
        WAL mode: readers never block writers, writers never block readers.
        Eliminates 'database is locked' errors when concurrent background jobs
        and API polling hit SQLite at the same time.
        NORMAL sync is safe with WAL and ~3x faster than FULL.
        """
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.close()


def create_db_and_tables() -> None:
    """
    Build the schema directly from the models, bypassing migrations.

    No longer called at startup -- Alembic owns the schema (app/schema.py).
    This remains for the places where building from the models is the correct
    thing and migrations would only be overhead: the test suite, which pins its
    own throwaway database, and scripts that construct a database to work on.
    Do not reintroduce it into an application code path.
    """
    SQLModel.metadata.create_all(engine)


def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session
