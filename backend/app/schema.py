"""
Alembic is the only thing that builds this schema.

Startup used to call SQLModel.metadata.create_all(), which meant two
authorities disagreed about what the schema is. A database could end up
stamped at one revision with later tables added by create_all -- a state no
migration produces and no clean test reproduces, where `alembic upgrade head`
and `alembic stamp head` are both plausible and only one is right. It also
forced every migration since f1a2b3c4d5e6 to guard each object with
`if not _table_exists(...)`, and made `scripts/setup.sh` carry a stamp-or-
upgrade branch with its own database-resolution logic to decide between them.

So the app no longer creates anything. It checks, and refuses to start on a
database that migrations have not brought to head -- pointing at
`scripts/check_database.py`, which diagnoses the difference between "never
migrated", "behind", and "drifted" and names the right command for each.

Refusing is the point. Silently repairing a schema is how a database drifts
from its migrations without anyone noticing; that is the failure this module
exists to make loud.

These functions take an engine rather than importing app.database, which
builds its engine at import time -- a diagnostic that cannot run when the
database URL is broken is useless, and scripts/check_database.py imports from
here.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import inspect, text

BACKEND_DIR = Path(__file__).resolve().parent.parent


class SchemaNotCurrent(RuntimeError):
    """The database is not at the migration head; the message says what to run."""


def alembic_head() -> str | None:
    """The single head revision the migration scripts define, if there is one."""
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        config = Config(str(BACKEND_DIR / "alembic.ini"))
        config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
        heads = ScriptDirectory.from_config(config).get_heads()
        return heads[0] if len(heads) == 1 else None
    except Exception:
        return None


def stamped_revision(engine) -> str | None:
    """What alembic_version says, or None if the table is absent or empty."""
    if not inspect(engine).has_table("alembic_version"):
        return None
    with engine.connect() as connection:
        row = connection.execute(text("SELECT version_num FROM alembic_version")).first()
    return row[0] if row else None


def has_any_tables(engine) -> bool:
    return bool(set(inspect(engine).get_table_names()) - {"alembic_version"})


def ensure_current(engine) -> None:
    """
    Raise unless migrations have brought this database to head.

    Deliberately cheap: it reads alembic_version and compares. Whether the
    schema *matches the models* is a slower, more thorough question that
    scripts/check_database.py answers, and the messages here send you there
    rather than guessing on your behalf.
    """
    head = alembic_head()
    if head is None:
        # Multiple heads, or the migration scripts are unreadable. Not
        # something to fail startup over -- but not something to claim is fine.
        return

    stamped = stamped_revision(engine)
    if stamped == head:
        return

    if stamped is None and not has_any_tables(engine):
        raise SchemaNotCurrent(
            "The database is empty. Migrations build the schema now -- the app "
            "does not.\n"
            "  cd backend && .venv/bin/alembic upgrade head"
        )
    if stamped is None:
        raise SchemaNotCurrent(
            "The database has tables but no migration history, so Alembic does "
            "not know what state it is in. This is a database built by an older "
            "version of this app, which created tables at startup.\n"
            "  cd backend && .venv/bin/python scripts/check_database.py\n"
            "It will tell you whether to stamp or to upgrade, and refuses to "
            "recommend a stamp if the schema does not match the models."
        )
    raise SchemaNotCurrent(
        f"The database is at revision {stamped}, and the migrations are at {head}.\n"
        "  cd backend && .venv/bin/alembic upgrade head"
    )
