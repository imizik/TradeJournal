#!/usr/bin/env bash
#
# session-start.sh - SessionStart hook: make a Claude Code on the web session
# runnable before its first check.
#
# A cloud session starts from a bare clone with no backend/.venv or
# frontend/node_modules, and without them every check fails on missing tools
# rather than on the change. This runs scripts/setup.sh -- the one clean-clone
# entry point, not a second copy of it -- and tells the session in one line
# whether it worked. The full output goes to .claude/session-start.log.
#
# Local sessions are left alone; there the environment is yours to manage.
# Registered in .claude/settings.json for startup and resume, because a resumed
# cloud session can land in a fresh container. Always exits 0: a failed setup
# is reported to the session, never allowed to block it.
set -uo pipefail

[ "${CLAUDE_CODE_REMOTE:-}" = "true" ] || exit 0

ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
LOG="$ROOT/.claude/session-start.log"
SKIP="so scripts/setup.sh was not run automatically: it would migrate that database. See docs/agent/environments.md before running it yourself."

# setup.sh migrates whatever database DATABASE_URL resolves to. In an ordinary
# cloud session that is the worktree's SQLite file. Anything else is a real
# database, and migrating one is not something to do unattended at startup.
for var in DATABASE_URL MIGRATION_DATABASE_URL; do
  url="${!var:-}"
  if [ -n "$url" ] && [[ "$url" != sqlite* ]]; then
    echo "SessionStart hook: $var names a non-SQLite database, $SKIP"
    exit 0
  fi
done
# app.database also reads these files. A fresh clone has neither; if one
# appears and mentions a database at all, fail closed rather than parse it.
for env_file in backend/.env .env; do
  if [ -f "$ROOT/$env_file" ] && grep -q "DATABASE_URL" "$ROOT/$env_file"; then
    echo "SessionStart hook: $env_file sets a database URL, $SKIP"
    exit 0
  fi
done

start=$SECONDS
if bash "$ROOT/scripts/setup.sh" >"$LOG" 2>&1; then
  echo "SessionStart hook: scripts/setup.sh finished in $((SECONDS - start))s." \
    "backend/.venv, frontend/node_modules and the local SQLite database are ready."
else
  status=$?
  echo "SessionStart hook: scripts/setup.sh FAILED (exit $status), so checks will" \
    "fail on missing tools until it succeeds. Run 'bash scripts/setup.sh' to see why." \
    "Last lines of .claude/session-start.log:"
  tail -n 15 "$LOG"
fi
exit 0
