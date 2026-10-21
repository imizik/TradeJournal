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
#   UX_BACKEND_PYTHON=/path/to/python UX_FRONTEND_NODE_MODULES_DIR=/path/to/node_modules bash scripts/ux_sandbox.sh --no-keys
#
# Both servers start from an empty environment: only the allow-listed
# market-data keys from that file and the sandbox's own settings reach them,
# never the database URL, Gmail, Webull, phone-alert, access or model
# settings, from the file or from the calling shell. The script refuses a
# checkout that has its own backend/.env, .env or Gmail credential files.
# Use a worktree or a clean clone.
#
# Backend 8098, frontend 3098 (UX_BACKEND_PORT / UX_FRONTEND_PORT). The
# frontend uses webpack so an explicitly shared node_modules symlink works
# from a worktree. That temporary symlink is removed when the sandbox stops.
# Ctrl+C
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

TEMP_NODE_MODULES_LINK=0
pids=()
stopped=0
cleanup() {
  [[ $stopped -eq 1 ]] && return
  stopped=1
  [[ ${#pids[@]} -gt 0 ]] && kill "${pids[@]}" 2>/dev/null
  wait 2>/dev/null
  if [[ $TEMP_NODE_MODULES_LINK -eq 1 ]]; then
    rm "$ROOT/frontend/node_modules"
  fi
}
trap 'cleanup; exit 130' INT TERM
trap cleanup EXIT

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

for env_file in "$ROOT/backend/.env" "$ROOT/.env" "$ROOT/backend/token.json" \
  "$ROOT/backend/credentials.json" "$ROOT/backend/pubsub-subscriber.json"; do
  [[ -e "$env_file" ]] && die "$env_file exists; the backend would use it (database, Gmail, alerts). Run from a worktree or clean clone without it."
done

PYTHON="${UX_BACKEND_PYTHON:-$ROOT/backend/.venv/bin/python}"
[[ -x "$PYTHON" ]] || die "backend/.venv is missing; run bash scripts/setup.sh"
if [[ ! -d "$ROOT/frontend/node_modules" && -n "${UX_FRONTEND_NODE_MODULES_DIR:-}" ]]; then
  [[ -d "$UX_FRONTEND_NODE_MODULES_DIR" ]] || die "UX_FRONTEND_NODE_MODULES_DIR is not a directory"
  [[ ! -e "$ROOT/frontend/node_modules" && ! -L "$ROOT/frontend/node_modules" ]] || die "frontend/node_modules already exists"
  ln -s "$UX_FRONTEND_NODE_MODULES_DIR" "$ROOT/frontend/node_modules" || die "could not link the supplied frontend dependencies"
  TEMP_NODE_MODULES_LINK=1
fi
[[ -d "$ROOT/frontend/node_modules" ]] || die "frontend/node_modules is missing; run bash scripts/setup.sh"
if ! command -v node >/dev/null 2>&1; then
  for d in "$HOME/.local/node/bin" "$HOME/.volta/bin" "/opt/homebrew/bin" "/usr/local/bin"; do
    if [[ -x "$d/node" ]]; then PATH="$d:$PATH"; break; fi
  done
  export PATH
fi
command -v node >/dev/null 2>&1 || die "node not found on PATH"

for port in "$BACKEND_PORT" "$FRONTEND_PORT"; do
  if lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
    die "port $port is in use; stop that process or set UX_BACKEND_PORT / UX_FRONTEND_PORT"
  fi
done

# The only environment the seeder and both servers get (env -i below):
# nothing the calling shell exported reaches them unless it is listed here.
CHILD_ENV=(PATH="$PATH" HOME="$HOME" USER="${USER:-}" TMPDIR="${TMPDIR:-/tmp}"
  LANG="${LANG:-en_US.UTF-8}" TERM="${TERM:-dumb}" PYTHON_DOTENV_DISABLED=1)
[[ -n "${SSL_CERT_FILE:-}" ]] && CHILD_ENV+=(SSL_CERT_FILE="$SSL_CERT_FILE")
KEY_ENV=()  # market-data keys: the backend only

if [[ $USE_KEYS -eq 1 ]]; then
  if [[ -z "$KEYS_FROM" ]]; then
    common="$(git -C "$ROOT" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)"
    [[ -n "$common" ]] && KEYS_FROM="$(dirname "$common")/backend/.env"
  fi
  [[ -n "$KEYS_FROM" && -f "$KEYS_FROM" ]] || die "no key file found; pass --keys-from FILE or --no-keys"
  imported=()
  # Parsed the way the app parses .env (python-dotenv), filtered to the
  # allow-list; values go straight into KEY_ENV and are never printed.
  while IFS=$'\t' read -r name value; do
    [[ -n "$name" ]] || continue
    KEY_ENV+=("$name=$value")
    imported+=("$name")
  done < <(env -i PATH="$PATH" "$PYTHON" -I -c '
import sys
from dotenv import dotenv_values
allowed = set(sys.argv[2:])
for name, value in dotenv_values(sys.argv[1]).items():
    if name in allowed and value and "\n" not in value and "\t" not in value:
        print(f"{name}\t{value}")
' "$KEYS_FROM" "${KEY_NAMES[@]}")
  echo "Market-data keys loaded: ${imported[*]:-none}"
fi

mkdir -p "$SANDBOX/captures"
DATABASE_URL="sqlite:///$DB_FILE"
BACKEND_ENV=("${CHILD_ENV[@]}" ${KEY_ENV[@]+"${KEY_ENV[@]}"} DATABASE_URL="$DATABASE_URL"
  TJ_MANUAL_FILLS_BACKUP="$SANDBOX/manual_fills.json" CAPTURE_STORAGE_DIR="$SANDBOX/captures"
  FRONTEND_PUBLIC_URL="http://127.0.0.1:$FRONTEND_PORT"
  GMAIL_WATCH_AUTOSTART=false GMAIL_LISTENER_ENABLED=false WEBULL_LISTENER_AUTOSTART=false
  LEVEL_ALERTS_AUTOSTART=false PRACTICE_AGENT_ENABLED=false PRACTICE_SCHEDULE_ENABLED=false
  CAPTURE_TRANSCRIBER=off)
# Same-origin proxy pinned to this backend, so nothing falls back to 8080.
FRONTEND_ENV=("${CHILD_ENV[@]}" NEXT_PUBLIC_API_URL=/api/backend PORT="$FRONTEND_PORT"
  API_PROXY_TARGET="http://127.0.0.1:$BACKEND_PORT" API_INTERNAL_URL="http://127.0.0.1:$BACKEND_PORT")

# The seeder migrates the file and refuses one that holds any real fill.
(cd "$ROOT/backend" && env -i "${BACKEND_ENV[@]}" "$PYTHON" scripts/seed_dev_data.py --database-url "$DATABASE_URL") \
  || die "seeding $DB_FILE failed; if you added fills by hand there, delete $SANDBOX to start over"

(cd "$ROOT/backend" && exec env -i "${BACKEND_ENV[@]}" "$PYTHON" -m uvicorn app.main:app --host 127.0.0.1 --port "$BACKEND_PORT") &
pids+=("$!")
(cd "$ROOT/frontend" && exec env -i "${FRONTEND_ENV[@]}" ./node_modules/.bin/next dev --webpack --port "$FRONTEND_PORT" --hostname 127.0.0.1) &
pids+=("$!")

alive() { kill -0 "${pids[0]}" 2>/dev/null && kill -0 "${pids[1]}" 2>/dev/null; }

# Prove the browser path reaches this sandbox's database before saying it is up.
health=""
for _ in $(seq 1 90); do
  alive || die "a server exited during startup; see the output above"
  health="$(curl -fsS "http://127.0.0.1:$FRONTEND_PORT/api/backend/health" 2>/dev/null)" && break
  sleep 2
done
[[ "$health" == *"ux_sandbox.db"* ]] || die "the frontend did not reach the sandbox database; stopping"

echo "UX sandbox ready (database: $DB_FILE)"
echo "  App     -> http://127.0.0.1:$FRONTEND_PORT"
echo "  Charts  -> http://127.0.0.1:$FRONTEND_PORT/charts"
echo "Press Ctrl+C to stop."
while alive; do sleep 2; done
echo "ux_sandbox: a server exited; stopping the other." >&2
