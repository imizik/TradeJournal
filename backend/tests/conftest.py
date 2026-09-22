"""
Session-wide isolation for the test database.

app.database resolves DATABASE_URL from the environment, then backend/.env,
then the repo-root .env -- and backend/.env is exactly where the hosted
Neon URL is documented to live. Several tests exercise the real
app.main:app through TestClient, whose lifespan runs ensure_current(),
_seed_and_normalize_roth_account() (which can move
fills between accounts and trigger a full trade rebuild) and
restore_manual_fills_from_backup().

Without this file, running `pytest` on a normally configured machine performs
those writes against the developer's real database. Verified before the fix:
a plain `pytest tests/test_fill_import.py` created 19 tables and inserted an
account row into whatever DATABASE_URL pointed at.

Pinning DATABASE_URL here happens before any test module imports app.database,
and load_dotenv() never overrides an already-exported variable, so this wins
over both .env files. Individual tests that want their own engine are
unaffected -- they build one explicitly.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

_TEST_DB_DIR = tempfile.mkdtemp(prefix="trade-journal-tests-")
_TEST_DB_PATH = Path(_TEST_DB_DIR) / "test.db"

# Set unconditionally: inheriting a developer's or CI runner's DATABASE_URL is
# the exact failure this guards against.
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB_PATH}"

# And MIGRATION_DATABASE_URL, which alembic prefers over DATABASE_URL once
# database roles are split (app/schema.py). Several test helpers run alembic
# in a subprocess with a temporary DATABASE_URL -- including upgrade, stamp and
# downgrade -- and an exported MIGRATION_DATABASE_URL would take precedence
# inside alembic and point those commands at the hosted schema owner instead.
# The documented split-role setup exports exactly that variable, so this is not
# hypothetical. Helpers that mean to migrate a named database override both.
os.environ["MIGRATION_DATABASE_URL"] = f"sqlite:///{_TEST_DB_PATH}"

# TestClient lifespans must not dispatch jobs left by another test. Individual
# worker tests execute jobs explicitly and use isolated lock directories.
os.environ["JOB_EXECUTION_MODE"] = "external"
os.environ["JOB_LOCK_DIR"] = str(Path(_TEST_DB_DIR) / "job-locks")

# Keep optional integrations dormant. Each is already opt-in, but an exported
# value from a developer shell should not change what the suite exercises.
for _flag in (
    "GMAIL_WATCH_AUTOSTART",
    "GMAIL_LISTENER_ENABLED",
    "WEBULL_LISTENER_AUTOSTART",
    "TRADINGVIEW_ANALYSIS_AUTOSTART",
):
    os.environ[_flag] = "false"

# Same reasoning for the live-quote provider: a developer shell that exports
# QUOTES_PROVIDER=tradier would otherwise change which code path the suite
# exercises. Tests that mean to exercise a provider set it themselves.
os.environ["QUOTES_PROVIDER"] = "yfinance"
os.environ.pop("WEBULL_LISTENER_ACCOUNTS", None)

# The application no longer builds the schema. Alembic does (app/schema.py),
# and app.main refuses to start on a database that is not at head -- which is
# how several tests here get their database, via TestClient(app.main.app).
#
# Running the real migration chain rather than create_all() is deliberate. The
# whole point of the change is that those two are not interchangeable, so a
# suite that built its schema from the models and stamped it would be asserting
# against a database no migration ever produces. It costs about a second once
# per session, and it means a migration that breaks the schema fails the suite
# rather than only the two modules that test migrations directly.
_BACKEND_DIR = Path(__file__).resolve().parents[1]


def _migrate_test_database() -> None:
    from alembic import command
    from alembic.config import Config

    # Config() with no file name: alembic.ini's fileConfig() would reconfigure
    # logging out from under pytest.
    config = Config()
    config.set_main_option("script_location", str(_BACKEND_DIR / "alembic"))
    command.upgrade(config, "head")


_migrate_test_database()


@pytest.fixture(autouse=True)
def _isolate_gmail_state(tmp_path, monkeypatch):
    """Gmail sidecar files default to backend/data, the developer's real state.

    Any test that reaches the poller, OAuth or listener code writes here instead.
    """
    from app.engine import gmail_listener, gmail_poller
    from app.engine.job_runtime import shutdown_requested

    state = tmp_path / "gmail-state"
    for name, filename in (
        ("CREDENTIALS_FILE", "credentials.json"),
        ("TOKEN_FILE", "token.json"),
        ("OAUTH_STATE_FILE", "gmail_oauth_states.json"),
        ("GMAIL_WATCH_STATE_FILE", "gmail_watch_state.json"),
        ("GMAIL_SKIPPED_MESSAGE_IDS_FILE", "gmail_skipped_message_ids.json"),
        ("GMAIL_HISTORY_CURSOR_FILE", "gmail_history_cursor.json"),
        ("GMAIL_AUTH_STATE_FILE", "gmail_auth_state.json"),
    ):
        monkeypatch.setattr(gmail_poller, name, state / filename)
    monkeypatch.setattr(gmail_listener, "LISTENER_STATE_FILE", state / "gmail_listener_state.json")
    shutdown_requested.clear()
    yield
    shutdown_requested.clear()
