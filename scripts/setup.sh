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
# hits this. Stamp that case instead of failing -- but only for the default
# local SQLite file, never for a DATABASE_URL someone has pointed at a real
# (possibly hosted) database.
if [ -z "${DATABASE_URL:-}" ] && "$VENV/bin/python" - "$ROOT/backend/data/trade_journal.db" <<'PYEOF'
import sqlite3, sys
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
        stamped = connection.execute("SELECT COUNT(*) FROM alembic_version").fetchone()[0]
        if stamped:
            sys.exit(1)
sys.exit(0)  # tables exist, but nothing is stamped
PYEOF
then
  echo "    existing unstamped database (created by the app, not by Alembic) - stamping"
  (cd "$ROOT/backend" && "$VENV/bin/python" -m alembic stamp head >/dev/null)
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
