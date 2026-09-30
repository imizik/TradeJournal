#!/usr/bin/env bash
#
# factory_week.sh - the strategy factory's weekly run (docs/strategy-factory.md).
#
# Runs in the factory checkout, a worktree on branch factory/ledger: takes
# main's latest code, fetches the week's SIP bars, lets the idea model propose
# up to three candidates and judges them, commits the specs, ledger lines and
# report to the branch, pushes it, and sends the summary to the phone. Any
# failed step sends the failure to the phone instead. launchd starts it every
# Sunday (~/Library/LaunchAgents/com.tradejournal.strategy-factory.plist), and
# the idea model is then Claude through the Anthropic API.
#
# By hand, a Claude Code session can be the idea model instead, on the user's
# Claude plan (/factory-week): write the brief, answer it, judge the answer.
#
#   bash scripts/factory_week.sh                       run the week now (the API)
#   bash scripts/factory_week.sh --brief FILE          write the brief to FILE and stop
#   bash scripts/factory_week.sh --answer FILE [--answer-by NAME]
#                                                      judge the ideas in FILE, record, notify
#   --budget N (with either)                           N candidates, past this week's three
#
# Never touches main or any database. The branch is never merged.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BRIEF=""
WEEK_ARGS=()
absolute() { case "$1" in /*) echo "$1" ;; *) echo "$PWD/$1" ;; esac; }  # the run moves to $ROOT
while [ $# -gt 0 ]; do
  case "$1" in
    --brief|--answer|--answer-by|--budget) ;;
    *) echo "Unknown option $1; see the top of $0." >&2; exit 2 ;;
  esac
  [ $# -ge 2 ] || { echo "$1 needs a value; see the top of $0." >&2; exit 2; }
  case "$1" in
    --brief) BRIEF="$(absolute "$2")" ;;
    --answer) WEEK_ARGS+=("$1" "$(absolute "$2")") ;;
    *) WEEK_ARGS+=("$1" "$2") ;;
  esac
  shift 2
done
FACTORY=("$ROOT/backend/.venv/bin/python" "$ROOT/backend/scripts/strategy_factory.py")
LOCK="$ROOT/backend/data/factory/week.lock"

say() { printf '\n==> %s (%s)\n' "$1" "$(date '+%F %T')"; }

fail() {
  echo "FAILED: $1" >&2
  "${FACTORY[@]}" notify --failure "$1" || echo "(the failure notification did not send either)" >&2
  exit 1
}

# Commit and push what the week wrote under research/. Candidates judged
# before a failure are in the ledger and count toward the bar, so they are
# kept whether or not the week finished.
record() {
  git add research || return 1
  if ! git diff --cached --quiet; then
    git commit -q -m "$1" || return 1
  fi
  git push -q origin factory/ledger
}

cd "$ROOT" || exit 1
mkdir -p "$(dirname "$LOCK")"
if ! mkdir "$LOCK" 2>/dev/null; then
  echo "Another run holds $LOCK; if none is running, remove it." >&2
  exit 0
fi
trap 'rmdir "$LOCK" 2>/dev/null' EXIT

[ "$(git rev-parse --abbrev-ref HEAD)" = "factory/ledger" ] || fail "the factory checkout at $ROOT is not on branch factory/ledger"
# Untracked files count too: whatever is under research/ gets committed with the week.
[ -z "$(git status --porcelain)" ] || fail "the factory checkout has uncommitted or untracked files (git status); the run did not start"

say "code: merge main"
git fetch -q origin || fail "git fetch failed"
if ! git merge -q --no-edit origin/main; then
  git merge --abort
  fail "merging main into factory/ledger conflicted; the run did not start"
fi

say "bars: fetch the week"
"${FACTORY[@]}" prepare || fail "fetching bars from Alpaca failed"

if [ -n "$BRIEF" ]; then
  say "brief: for a Claude Code session to answer"
  rm -f "$BRIEF"
  "${FACTORY[@]}" week --dry-run --brief-out "$BRIEF" ${WEEK_ARGS[@]+"${WEEK_ARGS[@]}"} || fail "writing the brief failed"
  if [ ! -s "$BRIEF" ]; then
    echo "No brief was written: this week's candidates are used (see above). Add --budget N to run N more." >&2
    exit 3
  fi
  say "done: the brief is in $BRIEF"
  exit 0
fi

say "ideas: propose and judge"
if ! "${FACTORY[@]}" week ${WEEK_ARGS[@]+"${WEEK_ARGS[@]}"}; then
  record "Strategy factory: week of $(date +%F), incomplete" \
    || fail "the weekly run failed, and what it had judged could not be committed and pushed"
  fail "the weekly run failed while proposing or judging; anything it judged is pushed; see ~/Library/Logs/tradejournal-strategy-factory.log"
fi

say "record: commit and push"
record "Strategy factory: week of $(date +%F)" || fail "committing or pushing the week's results failed"

say "phone: send the summary"
"${FACTORY[@]}" notify || fail "the summary did not send"
say "done"
