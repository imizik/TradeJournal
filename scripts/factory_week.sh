#!/usr/bin/env bash
#
# factory_week.sh - the strategy factory's weekly run (docs/strategy-factory.md).
#
# Runs in the factory checkout, a worktree on branch factory/ledger: takes
# main's latest code, fetches the week's SIP bars, lets the idea model propose
# up to three candidates and judges them, commits the specs, ledger lines and
# report to the branch, pushes it, and sends the summary to the phone. Any
# failed step sends the failure to the phone instead. launchd starts it every
# Sunday (~/Library/LaunchAgents/com.tradejournal.strategy-factory.plist).
#
#   bash scripts/factory_week.sh      run the week now
#
# Never touches main or any database. The branch is never merged.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FACTORY=("$ROOT/backend/.venv/bin/python" "$ROOT/backend/scripts/strategy_factory.py")
LOCK="$ROOT/backend/data/factory/week.lock"

say() { printf '\n==> %s (%s)\n' "$1" "$(date '+%F %T')"; }

fail() {
  echo "FAILED: $1" >&2
  "${FACTORY[@]}" notify --failure "$1" || echo "(the failure notification did not send either)" >&2
  exit 1
}

cd "$ROOT" || exit 1
mkdir -p "$(dirname "$LOCK")"
if ! mkdir "$LOCK" 2>/dev/null; then
  echo "Another run holds $LOCK; if none is running, remove it." >&2
  exit 0
fi
trap 'rmdir "$LOCK" 2>/dev/null' EXIT

[ "$(git rev-parse --abbrev-ref HEAD)" = "factory/ledger" ] || fail "the factory checkout at $ROOT is not on branch factory/ledger"
git diff --quiet && git diff --cached --quiet || fail "the factory checkout has uncommitted changes; the run did not start"

say "code: merge main"
git fetch -q origin || fail "git fetch failed"
if ! git merge -q --no-edit origin/main; then
  git merge --abort
  fail "merging main into factory/ledger conflicted; the run did not start"
fi

say "bars: fetch the week"
"${FACTORY[@]}" prepare || fail "fetching bars from Alpaca failed"

say "ideas: propose and judge"
"${FACTORY[@]}" week || fail "the weekly run failed while proposing or judging; see ~/Library/Logs/tradejournal-strategy-factory.log"

say "record: commit and push"
git add research
if ! git diff --cached --quiet; then
  git commit -q -m "Strategy factory: week of $(date +%F)" || fail "committing the week's results failed"
fi
git push -q origin factory/ledger || fail "pushing factory/ledger failed; the results are committed locally"

say "phone: send the summary"
"${FACTORY[@]}" notify || fail "the summary did not send"
say "done"
