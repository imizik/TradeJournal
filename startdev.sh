#!/usr/bin/env bash
#
# startdev.sh — macOS/Linux launcher for the private backend and frontend.
#
# Starts FastAPI (port 8080) and Next.js (port 3000), streams their logs, and
# stops both on Ctrl+C.

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_PORT="${BACKEND_PORT:-8080}"
FRONTEND_PORT="${FRONTEND_PORT:-3000}"

# Python: honor an explicit PYTHON, else prefer the project venv, then system python3.
if [[ -z "${PYTHON:-}" ]]; then
  if [[ -x "$ROOT/backend/.venv/bin/python" ]]; then
    PYTHON="$ROOT/backend/.venv/bin/python"
  else
    PYTHON="python3"
  fi
fi

if ! command -v npm >/dev/null 2>&1; then
  for d in "$HOME/.local/node/bin" "$HOME/.volta/bin" "/opt/homebrew/bin" "/usr/local/bin"; do
    if [[ -x "$d/npm" ]]; then PATH="$d:$PATH"; break; fi
  done
  export PATH
fi

[[ -f "$ROOT/backend/.env" ]] || \
  echo "WARNING: backend/.env not found — backend will fall back to local SQLite."
[[ -d "$ROOT/frontend/node_modules" ]] || \
  echo "WARNING: frontend/node_modules missing — run 'npm install' in frontend/ first."
command -v npm >/dev/null 2>&1 || \
  echo "WARNING: npm not found on PATH — frontend will not start. Add your Node bin dir to PATH."
"$PYTHON" -c "import uvicorn" >/dev/null 2>&1 || \
  echo "WARNING: uvicorn not importable by '$PYTHON' — backend will not start. Check backend/.venv."

pids=()
cleanup() {
  trap '' INT TERM
  echo
  echo "Stopping dev servers..."
  kill "${pids[@]}" 2>/dev/null
  wait 2>/dev/null
}
trap cleanup INT TERM EXIT

(
  cd "$ROOT/backend" || exit 1
  FRONTEND_PUBLIC_URL="http://localhost:${FRONTEND_PORT}" \
    exec "$PYTHON" -m uvicorn app.main:app --reload --host 127.0.0.1 --port "$BACKEND_PORT"
) &
pids+=("$!")

(
  cd "$ROOT/frontend" || exit 1
  NEXT_PUBLIC_API_URL="http://localhost:${BACKEND_PORT}" \
    exec npm run dev
) &
pids+=("$!")

echo "Backend  -> http://localhost:${BACKEND_PORT}"
echo "Frontend -> http://localhost:${FRONTEND_PORT}"
echo "Press Ctrl+C to stop both services."

wait
