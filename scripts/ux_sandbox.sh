#!/usr/bin/env bash
#
# ux_sandbox.sh — the app with real market data and nothing real to break.
#
# For looking at and trying the UI (the trade-chart-ux skill): real candles,
# quotes and news from the provider keys, but its own seeded SQLite database,
# so toggling studies, saving layouts, adding levels or plans touches only
# that file. Chart settings sync through the database, so the user's real
# devices never see what happens here.
#
#   bash scripts/ux_sandbox.sh                    # keys from the main checkout's backend/.env
#   bash scripts/ux_sandbox.sh --keys-from FILE   # keys from another env file
#   bash scripts/ux_sandbox.sh --no-keys          # seeded records only, no candles
#
# Only market-data keys are read from that file; its database URL, Gmail,
# Webull, phone-alert and model settings are never loaded. The script refuses
# to run in a checkout that has its own backend/.env or .env, because the
# backend would load every setting in it. Use a worktree or a clean clone.
#
# Backend 8098, frontend 3098 (UX_BACKEND_PORT / UX_FRONTEND_PORT). Ctrl+C
# stops both. Data lives in backend/data/ux_sandbox/; delete it to start over.

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_PORT="${UX_BACKEND_PORT:-8098}"
FRONTEND_PORT="${UX_FRONTEND_PORT:-3098}"
SANDBOX="$ROOT/backend/data/ux_sandbox"
DB_FILE="$SANDBOX/ux_sandbox.db"
KEY_NAMES=(ALPACA_API_KEY ALPACA_API_SECRET ALPACA_DATA_FEED ALPACA_OPTIONS_FEED
  TRADIER_API_KEY TRADIER_BASE_URL POLYGON_API_KEY POLYGON_CALLS_PER_MINUTE)

die() { echo "ux_sandbox: $*" >&2; exit 1; }

KEYS_FROM=""
USE_KEYS=1
while [[ $# -gt 0 ]]; do
  case "$1" in
    --keys-from) [[ $# -ge 2 ]] || die "--keys-from needs a file"; KEYS_FROM="$2"; shift 2 ;;
    --no-keys) USE_KEYS=0; shift ;;
    -h|--help) sed -n '3,22p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) die "unknown argument: $1 (see --help)" ;;
  esac
done

for env_file in "$ROOT/backend/.env" "$ROOT/.env"; do
  [[ -e "$env_file" ]] && die "$env_file exists; the backend would load all of it (database, Gmail, alerts). Run from a worktree or clean clone without it."
done

PYTHON="$ROOT/backend/.venv/bin/python"
[[ -x "$PYTHON" ]] || die "backend/.venv is missing; run bash scripts/setup.sh"
[[ -d "$ROOT/frontend/node_modules" ]] || die "frontend/node_modules is missing; run bash scripts/setup.sh"
if ! command -v npm >/dev/null 2>&1; then
  for d in "$HOME/.local/node/bin" "$HOME/.volta/bin" "/opt/homebrew/bin" "/usr/local/bin"; do
    if [[ -x "$d/npm" ]]; then PATH="$d:$PATH"; break; fi
  done
  export PATH
fi
command -v npm >/dev/null 2>&1 || die "npm not found on PATH"

for port in "$BACKEND_PORT" "$FRONTEND_PORT"; do
  if lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
    die "port $port is in use; stop that process or set UX_BACKEND_PORT / UX_FRONTEND_PORT"
  fi
done

# Clear anything the calling shell exported that could point elsewhere.
unset DATABASE_URL MIGRATION_DATABASE_URL APP_ENV NTFY_URL NTFY_TOKEN ALERT_APP_URL \
  GMAIL_PUBSUB_TOPIC GMAIL_PUBSUB_SUBSCRIPTION GMAIL_PUBSUB_CREDENTIALS_FILE \
  TJ_ACCESS_PROFILE TJ_GATEWAY_KEY TJ_WEB_ORIGIN "${KEY_NAMES[@]}"

if [[ $USE_KEYS -eq 1 ]]; then
  if [[ -z "$KEYS_FROM" ]]; then
    common="$(git -C "$ROOT" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)"
    [[ -n "$common" ]] && KEYS_FROM="$(dirname "$common")/backend/.env"
  fi
  [[ -n "$KEYS_FROM" && -f "$KEYS_FROM" ]] || die "no key file found; pass --keys-from FILE or --no-keys"
  imported=()
  # Read KEY=value lines; take only the allow-listed names; never print values.
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line#export }"
    name="${line%%=*}"
    [[ "$line" == *=* ]] || continue
    for allowed in "${KEY_NAMES[@]}"; do
      if [[ "$name" == "$allowed" ]]; then
        value="${line#*=}"
        value="${value%\"}"; value="${value#\"}"; value="${value%\'}"; value="${value#\'}"
        export "$name=$value"
        imported+=("$name")
      fi
    done
  done < "$KEYS_FROM"
  echo "Market-data keys loaded: ${imported[*]:-none}"
fi

mkdir -p "$SANDBOX/captures"
export DATABASE_URL="sqlite:///$DB_FILE"
export TJ_MANUAL_FILLS_BACKUP="$SANDBOX/manual_fills.json"
export CAPTURE_STORAGE_DIR="$SANDBOX/captures"
export FRONTEND_PUBLIC_URL="http://127.0.0.1:$FRONTEND_PORT"
export GMAIL_WATCH_AUTOSTART=false GMAIL_LISTENER_ENABLED=false WEBULL_LISTENER_AUTOSTART=false \
  LEVEL_ALERTS_AUTOSTART=false TRADINGVIEW_ANALYSIS_AUTOSTART=false \
  PRACTICE_AGENT_ENABLED=false PRACTICE_SCHEDULE_ENABLED=false CAPTURE_TRANSCRIBER=off

# The seeder migrates the file and refuses one that holds any real fill.
(cd "$ROOT/backend" && "$PYTHON" scripts/seed_dev_data.py --database-url "$DATABASE_URL") \
  || die "seeding $DB_FILE failed"

pids=()
cleanup() {
  trap '' INT TERM
  echo
  echo "Stopping the UX sandbox..."
  kill "${pids[@]}" 2>/dev/null
  wait 2>/dev/null
}
trap cleanup INT TERM EXIT

(
  cd "$ROOT/backend" || exit 1
  exec "$PYTHON" -m uvicorn app.main:app --host 127.0.0.1 --port "$BACKEND_PORT"
) &
pids+=("$!")

(
  cd "$ROOT/frontend" || exit 1
  # Same-origin proxy pinned to this backend, so nothing falls back to 8080.
  NEXT_PUBLIC_API_URL=/api/backend API_PROXY_TARGET="http://127.0.0.1:$BACKEND_PORT" \
    API_INTERNAL_URL="http://127.0.0.1:$BACKEND_PORT" PORT="$FRONTEND_PORT" \
    exec npx next dev --port "$FRONTEND_PORT" --hostname 127.0.0.1
) &
pids+=("$!")

# Prove the browser path reaches the sandbox database before saying it is up.
health=""
for _ in $(seq 1 90); do
  health="$(curl -fsS "http://127.0.0.1:$FRONTEND_PORT/api/backend/health" 2>/dev/null)" && break
  sleep 2
done
if [[ "$health" != *"ux_sandbox.db"* ]]; then
  echo "ux_sandbox: the frontend did not reach the sandbox database; stopping." >&2
  exit 1
fi

echo "UX sandbox ready (database: $DB_FILE)"
echo "  App     -> http://127.0.0.1:$FRONTEND_PORT"
echo "  Charts  -> http://127.0.0.1:$FRONTEND_PORT/charts"
echo "Press Ctrl+C to stop."
wait
