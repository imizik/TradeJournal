#!/usr/bin/env bash
#
# startdev.sh — macOS/Linux equivalent of startdev.ps1
#
# Launches the private FastAPI backend (port 8080), webhook-only TradingView
# ingress (port 8090), and Next.js frontend (port 3000) together in one
# terminal, streams their logs, and stops all three on Ctrl+C.
#
# The private API reads DATABASE_URL from backend/.env. The public ingress
# separately reads backend/.env.tradingview; when the private API uses Neon or
# any non-default DB, TRADINGVIEW_DATABASE_URL must target the same logical
# database/schema (preferably through a restricted ingress role).
#
# Usage:   bash startdev.sh
# Override ports/python:
# BACKEND_PORT=8000 TRADINGVIEW_INGRESS_PORT=8090 PYTHON=python3.10 bash startdev.sh

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_PORT="${BACKEND_PORT:-8080}"
TRADINGVIEW_INGRESS_PORT="${TRADINGVIEW_INGRESS_PORT:-8090}"
FRONTEND_PORT="${FRONTEND_PORT:-3000}"

# Python: honor an explicit $PYTHON, else prefer the project venv (so uvicorn is
# available without activating it), else fall back to system python3.
if [[ -z "${PYTHON:-}" ]]; then
  if [[ -x "$ROOT/backend/.venv/bin/python" ]]; then
    PYTHON="$ROOT/backend/.venv/bin/python"
  else
    PYTHON="python3"
  fi
fi

# Node: this setup keeps Node outside the default PATH. If npm isn't already on
# PATH, find it in the usual install locations and prepend it.
if ! command -v npm >/dev/null 2>&1; then
  for d in "$HOME/.local/node/bin" "$HOME/.volta/bin" "/opt/homebrew/bin" "/usr/local/bin"; do
    if [[ -x "$d/npm" ]]; then PATH="$d:$PATH"; break; fi
  done
  export PATH
fi

# --- Preflight --------------------------------------------------------------
[[ -f "$ROOT/backend/.env" ]] || \
  echo "WARNING: backend/.env not found — backend will fall back to local SQLite."
[[ -f "$ROOT/backend/.env.tradingview" ]] || \
  echo "WARNING: backend/.env.tradingview not found — TradingView ingress readiness will fail."
[[ -d "$ROOT/frontend/node_modules" ]] || \
  echo "WARNING: frontend/node_modules missing — run 'npm install' in frontend/ first."
command -v npm >/dev/null 2>&1 || \
  echo "WARNING: npm not found on PATH — frontend will not start. Add your Node bin dir to PATH."
"$PYTHON" -c "import uvicorn" >/dev/null 2>&1 || \
  echo "WARNING: uvicorn not importable by '$PYTHON' — backend will not start. Check backend/.venv."

# Refuse the easy-to-miss split where the private API reads a hosted
# DATABASE_URL from .env but ingress silently falls back to local SQLite.
if ! TRADEJOURNAL_ROOT="$ROOT" "$PYTHON" -c '
import os
import sys
from pathlib import Path
from dotenv import dotenv_values

root = Path(os.environ["TRADEJOURNAL_ROOT"])
private_url = os.getenv("DATABASE_URL", "").strip()
if not private_url:
    for path in (root / "backend" / ".env", root / ".env"):
        private_url = str(
            dotenv_values(path).get("DATABASE_URL") or ""
        ).strip()
        if private_url:
            break
ingress_url = (
    os.getenv("TRADINGVIEW_DATABASE_URL", "").strip()
    or os.getenv("DATABASE_URL", "").strip()
    or str(
        dotenv_values(
            root / "backend" / ".env.tradingview"
        ).get("TRADINGVIEW_DATABASE_URL")
        or ""
    ).strip()
)
sys.exit(1 if private_url and not ingress_url else 0)
'; then
  echo "ERROR: private DATABASE_URL is configured, but TRADINGVIEW_DATABASE_URL is blank."
  echo "Set it in backend/.env.tradingview to the same logical database, then retry."
  exit 1
fi

# --- Clean shutdown ---------------------------------------------------------
pids=()
cleanup() {
  trap '' INT TERM          # ignore repeat Ctrl+C while tearing down
  echo
  echo "Stopping dev servers..."
  kill "${pids[@]}" 2>/dev/null
  wait 2>/dev/null
}
trap cleanup INT TERM EXIT

# --- Backend (uvicorn --reload on $BACKEND_PORT) ----------------------------
(
  cd "$ROOT/backend" || exit 1
  FRONTEND_PUBLIC_URL="http://localhost:${FRONTEND_PORT}" \
    exec "$PYTHON" -m uvicorn app.main:app --reload --host 127.0.0.1 --port "$BACKEND_PORT"
) &
pids+=("$!")

# --- Restricted TradingView ingress (safe port to tunnel) -------------------
(
  cd "$ROOT/backend" || exit 1
  exec "$PYTHON" -m uvicorn app.tradingview_ingress:app \
    --reload --no-access-log --host 127.0.0.1 \
    --port "$TRADINGVIEW_INGRESS_PORT"
) &
pids+=("$!")

# --- Frontend (next dev on $FRONTEND_PORT, pointed at the backend) ----------
(
  cd "$ROOT/frontend" || exit 1
  NEXT_PUBLIC_API_URL="http://localhost:${BACKEND_PORT}" \
    exec npm run dev
) &
pids+=("$!")

echo "Backend   -> http://localhost:${BACKEND_PORT}"
echo "TV ingress-> http://localhost:${TRADINGVIEW_INGRESS_PORT}"
echo "Frontend  -> http://localhost:${FRONTEND_PORT}"
echo "Tunnel only the TV ingress port; never tunnel the private backend."
echo "Press Ctrl+C to stop all services."

wait
