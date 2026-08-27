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
# Alembic builds the schema. The app used to call create_all() at startup and
# repair its own database, which is why this step needed ~70 lines to work out
# whether to stamp or to upgrade -- and its own copy of app.database's .env
# resolution to make that decision safely. It no longer creates anything
# (backend/app/schema.py), so a fresh worktree just migrates.
#
# A database from before that change still has tables and no alembic_version.
# check_database.py decides that case properly -- it compares the live schema
# against the models, including constraints, and refuses to recommend a stamp
# when they disagree. Route to it rather than reimplementing a weaker version.
if ! (cd "$ROOT/backend" && "$VENV/bin/python" -m alembic upgrade head >/dev/null 2>&1); then
  echo "    migrations did not apply cleanly - diagnosing:"
  echo ""
  (cd "$ROOT/backend" && "$VENV/bin/python" scripts/check_database.py) || true
  echo ""
  echo "    Run the command named above, then re-run scripts/setup.sh."
  exit 1
fi

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
