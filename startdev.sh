#!/usr/bin/env bash
#
# startdev.sh — macOS/Linux equivalent of startdev.ps1
#
# Launches the FastAPI backend (port 8080) and the Next.js frontend (port 3000)
# together in one terminal, streams both logs, and stops both on Ctrl+C.
#
# DATABASE_URL is read from backend/.env (see app/database.py), so this script
# does not set it — point .env at Neon and both machines share the same DB.
#
# Usage:   bash startdev.sh
# Override ports/python:  BACKEND_PORT=8000 PYTHON=python3.10 bash startdev.sh

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_PORT="${BACKEND_PORT:-8080}"
FRONTEND_PORT="${FRONTEND_PORT:-3000}"
PYTHON="${PYTHON:-python3}"

# --- Preflight --------------------------------------------------------------
[[ -f "$ROOT/backend/.env" ]] || \
  echo "WARNING: backend/.env not found — backend will fall back to local SQLite."
[[ -d "$ROOT/frontend/node_modules" ]] || \
  echo "WARNING: frontend/node_modules missing — run 'npm install' in frontend/ first."

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
    exec "$PYTHON" -m uvicorn app.main:app --reload --host 0.0.0.0 --port "$BACKEND_PORT"
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
echo "Frontend  -> http://localhost:${FRONTEND_PORT}"
echo "Press Ctrl+C to stop both."

wait
