#!/usr/bin/env bash
#
# setup.sh - clean clone to runnable, in one command.
#
#   bash scripts/setup.sh
#
# Creates backend/.venv, installs the backend with its dev extra, installs
# frontend dependencies, and migrates a local SQLite database. Touches nothing
# outside the repo and needs no credentials: every external integration
# (Gmail, Polygon, Alpaca, Anthropic, Webull, TradingView) is optional and
# stays dormant until its environment variables are set.
#
# Override the interpreter with PYTHON=python3.12 bash scripts/setup.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-python3}"
VENV="$ROOT/backend/.venv"

echo "==> Backend virtualenv ($PYTHON)"
[ -d "$VENV" ] || "$PYTHON" -m venv "$VENV"
"$VENV/bin/python" -m pip install --quiet --upgrade pip
"$VENV/bin/python" -m pip install --quiet -e "$ROOT/backend[dev]"

echo "==> Database migrations (local SQLite unless DATABASE_URL is set)"
# Starting the app calls SQLModel's create_all(), which builds every table but
# writes no alembic_version row. `alembic upgrade head` then fails on
# "table account already exists". Anyone who runs the app before migrating
# hits this. Stamp that case instead of failing.
#
# Stamping marks migrations applied WITHOUT running them, so it must only ever
# touch the default local SQLite file. Testing the shell's $DATABASE_URL is not
# enough: app.database also reads backend/.env and the repo-root .env, so a
# hosted URL configured there is invisible to the shell but is exactly what
# `alembic stamp` would target. Resolve the effective URL the same way
# app.database does (and startdev.sh already does), and pin the stamp to the
# file that was actually inspected.
LOCAL_DB="$ROOT/backend/data/trade_journal.db"

effective_database_url() {
  TRADEJOURNAL_ROOT="$ROOT" "$VENV/bin/python" - <<'PYEOF'
import os
from pathlib import Path

from dotenv import dotenv_values

root = Path(os.environ["TRADEJOURNAL_ROOT"])
url = os.getenv("DATABASE_URL", "").strip()
if not url:
    for path in (root / "backend" / ".env", root / ".env"):
        url = str(dotenv_values(path).get("DATABASE_URL") or "").strip()
        if url:
            break
print(url)
PYEOF
}

needs_stamp() {
  "$VENV/bin/python" - "$LOCAL_DB" <<'PYEOF'
import sqlite3
import sys
from pathlib import Path

path = Path(sys.argv[1])
if not path.exists():
    sys.exit(1)
with sqlite3.connect(path) as connection:
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    if "account" not in tables:
        sys.exit(1)
    if "alembic_version" in tables:
        stamped = connection.execute(
            "SELECT COUNT(*) FROM alembic_version"
        ).fetchone()[0]
        if stamped:
            sys.exit(1)
sys.exit(0)  # tables exist, but nothing is stamped
PYEOF
}

EFFECTIVE_DATABASE_URL="$(effective_database_url)"
if [ -n "$EFFECTIVE_DATABASE_URL" ]; then
  echo "    DATABASE_URL is configured - migrating that database, no stamping"
elif needs_stamp; then
  echo "    existing unstamped local database (created by the app, not by Alembic) - stamping"
  (cd "$ROOT/backend" && DATABASE_URL="sqlite:///$LOCAL_DB" \
    "$VENV/bin/python" -m alembic stamp head >/dev/null)
fi
(cd "$ROOT/backend" && "$VENV/bin/python" -m alembic upgrade head >/dev/null)

echo "==> Frontend dependencies"
if command -v npm >/dev/null 2>&1; then
  (cd "$ROOT/frontend" && npm install --no-audit --no-fund --silent)
else
  echo "    npm not found on PATH - skipping. Frontend checks will not run."
fi

cat <<'DONE'

Setup complete.

  bash scripts/verify.sh        run every check
  bash startdev.sh              run the app (backend 8080, ingress 8090, web 3000)

Optional integrations are configured in backend/.env; see backend/.env.example.
DONE
