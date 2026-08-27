"""
Session-wide isolation for the test database.

app.database resolves DATABASE_URL from the environment, then backend/.env,
then the repo-root .env -- and backend/.env is exactly where the hosted
Neon URL is documented to live. Several tests exercise the real
app.main:app through TestClient, whose lifespan runs create_db_and_tables(),
_cleanup_orphaned_jobs(), _seed_and_normalize_roth_account() (which can move
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

_TEST_DB_DIR = tempfile.mkdtemp(prefix="trade-journal-tests-")
_TEST_DB_PATH = Path(_TEST_DB_DIR) / "test.db"

# Set unconditionally: inheriting a developer's or CI runner's DATABASE_URL is
# the exact failure this guards against.
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB_PATH}"

# Keep optional integrations dormant. Each is already opt-in, but an exported
# value from a developer shell should not change what the suite exercises.
for _flag in (
    "GMAIL_WATCH_AUTOSTART",
    "WEBULL_LISTENER_AUTOSTART",
    "TRADINGVIEW_ANALYSIS_AUTOSTART",
):
    os.environ[_flag] = "false"
os.environ.pop("WEBULL_LISTENER_ACCOUNTS", None)
