#!/usr/bin/env bash
#
# verify.sh - the checks that decide whether a change is good.
#
#   bash scripts/verify.sh              everything (what CI runs)
#   bash scripts/verify.sh --fast       tests + typecheck, no builds
#   bash scripts/verify.sh --backend    backend only
#   bash scripts/verify.sh --frontend   frontend only
#   bash scripts/verify.sh --e2e        browser smoke tests only (slowest)
#
# The default run includes the browser tests. They are the only check that
# proves a page renders: typecheck, lint and build all pass on a component
# that is broken at runtime.
#
# Needs no credentials and touches no real data. The backend suite pins itself
# to a throwaway SQLite database in backend/tests/conftest.py, so an exported
# DATABASE_URL (including a hosted Neon one) is ignored.
#
# Every check runs even after one fails, so a single run reports every problem
# rather than only the first. Exit status is non-zero if any check failed.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PY="$ROOT/backend/.venv/bin/python"
[ -x "$VENV_PY" ] || VENV_PY="${PYTHON:-python3}"

MODE="all"
case "${1:-}" in
  --fast)     MODE="fast" ;;
  --backend)  MODE="backend" ;;
  --frontend) MODE="frontend" ;;
  --e2e)      MODE="e2e" ;;
  "")         MODE="all" ;;
  -h|--help)  sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
  *)          echo "unknown option: $1 (try --help)" >&2; exit 2 ;;
esac

FAILED=()
PASSED=()

run() {
  local name="$1"; shift
  printf '\n\033[1m==> %s\033[0m\n' "$name"
  if "$@"; then
    PASSED+=("$name")
  else
    FAILED+=("$name")
    printf '\033[31mFAILED: %s\033[0m\n' "$name"
  fi
}

# Record a failure for a check that could not run at all. A verification tool
# that reports success without verifying is worse than no tool.
fail() {
  local name="$1" reason="$2"
  printf '\n\033[1m==> %s\033[0m\n' "$name"
  echo "$reason"
  FAILED+=("$name")
  printf '\033[31mFAILED: %s\033[0m\n' "$name"
}

backend() { (cd "$ROOT/backend" && "$@"); }
frontend() { (cd "$ROOT/frontend" && "$@"); }

want_backend()  { [ "$MODE" = all ] || [ "$MODE" = fast ] || [ "$MODE" = backend ]; }
want_frontend() { [ "$MODE" = all ] || [ "$MODE" = fast ] || [ "$MODE" = frontend ]; }
want_slow()     { [ "$MODE" != fast ]; }
# --fast skips it (it rebuilds the frontend and boots both servers, ~40s).
want_e2e()      { [ "$MODE" = all ] || [ "$MODE" = e2e ]; }

if want_backend; then
  if [ ! -x "$ROOT/backend/.venv/bin/python" ]; then
    echo "note: backend/.venv not found, using $VENV_PY (run scripts/setup.sh for a clean env)"
  fi
  # Covers the FIFO reconstructor, parsers, routes, Strategy Lab, TradingView,
  # and the Alembic-vs-models schema drift guard.
  run "backend tests" backend "$VENV_PY" -m pytest -q
fi

if want_frontend; then
  if [ ! -d "$ROOT/frontend/node_modules" ]; then
    fail "frontend dependencies" \
      "frontend/node_modules is missing, so typecheck, lint and build cannot run. Run scripts/setup.sh."
  else
    run "frontend typecheck" frontend npm run --silent typecheck
    if want_slow; then
      # Warnings are allowed; see frontend/eslint.config.mjs for the policy.
      run "frontend lint" frontend npm run --silent lint
      # Catches server-component and route errors that typecheck alone misses.
      run "frontend build" frontend npm run --silent build
    fi
  fi
fi

if want_e2e; then
  if [ ! -d "$ROOT/frontend/node_modules" ]; then
    fail "browser tests" \
      "frontend/node_modules is missing, so the browser tests cannot run. Run scripts/setup.sh."
  elif [ ! -d "$ROOT/frontend/node_modules/@playwright" ]; then
    fail "browser tests" \
      "@playwright/test is not installed. Run 'npm install' in frontend/."
  else
    # Seeds its own database, boots the backend and a fresh frontend build on
    # dedicated ports (8099/3099), and asserts real values reach the DOM.
    # Needs a browser: CI installs one, and a sandbox with a preinstalled
    # browser can point at it with PLAYWRIGHT_CHROMIUM_PATH.
    run "browser tests" frontend npm run --silent e2e
  fi
fi

printf '\n\033[1m==================== summary ====================\033[0m\n'
for name in "${PASSED[@]:-}"; do [ -n "$name" ] && printf '  \033[32mpass\033[0m  %s\n' "$name"; done
for name in "${FAILED[@]:-}"; do [ -n "$name" ] && printf '  \033[31mFAIL\033[0m  %s\n' "$name"; done

if [ "${#FAILED[@]}" -gt 0 ]; then
  printf '\n\033[31m%d check(s) failed.\033[0m\n' "${#FAILED[@]}"
  exit 1
fi
printf '\n\033[32mAll checks passed.\033[0m\n'
