#!/usr/bin/env bash
#
# docs_drift_week.sh - the weekly documentation drift pass, unattended
# (.claude/skills/docs-drift/SKILL.md).
#
# Runs in the docs checkout, a worktree of this repository kept detached at
# main. Once 20 code commits have landed since docs/agent/last-reconciled.json
# (test_docs_freshness.py fails past 30), it has Claude run the drift pass on
# a new branch, checks that only existing documentation changed and that the
# marker moved to the commit that was read, runs the docs tests, pushes the
# branch and opens a pull request for review. The phone hears about the pull
# request, one still waiting for review, or a failure. launchd starts it every
# Saturday (~/Library/LaunchAgents/com.tradejournal.docs-drift.plist).
#
#   bash scripts/docs_drift_week.sh                     run it now, if due
#   DOCS_DRIFT_MIN_COMMITS=1 bash scripts/docs_drift_week.sh   run the pass anyway
#   DOCS_DRIFT_DRY_RUN=1 bash scripts/docs_drift_week.sh       no push, pull request or phone
#
# Claude runs headless with the Anthropic key in DOCS_DRIFT_ENV_FILE (the main
# checkout's backend/.env). It may read anything, edit only files under docs/,
# README.md, AGENTS.md and CLAUDE.md, and run only git log, diff and show;
# everything else is refused without asking, so the run cannot stall waiting
# for a person. This script commits, pushes and opens the pull request. It
# never merges and never pushes main.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="$ROOT/backend/.venv/bin/python"
ENV_FILE="${DOCS_DRIFT_ENV_FILE:-$ROOT/backend/.env}"
REF="${DOCS_DRIFT_REF:-origin/main}"
MIN_COMMITS="${DOCS_DRIFT_MIN_COMMITS:-20}"
BUDGET_USD="${DOCS_DRIFT_BUDGET_USD:-20}"
TIME_LIMIT="${DOCS_DRIFT_TIME_LIMIT:-3600}"
DRY_RUN="${DOCS_DRIFT_DRY_RUN:-}"
LOG_DIR="${DOCS_DRIFT_LOG_DIR:-$HOME/Library/Logs}"
CHECK="${DOCS_DRIFT_CHECK:-cd backend && .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_docs_links.py tests/test_docs_freshness.py}"
LOCK="$ROOT/backend/data/docs-drift.lock"
BRANCH_PREFIX="docs/drift-"
# What a pass may change: existing documentation, and the marker.
ALLOWED='(docs/.+\.md|docs/agent/last-reconciled\.json|README\.md|AGENTS\.md|CLAUDE\.md)'
STARTED=""
START=""

say() { printf '\n==> %s (%s)\n' "$1" "$(date '+%F %T')"; }

# A value from the env file, read the way the app reads it; empty when absent.
setting() {
  [ -f "$ENV_FILE" ] || return 0
  "$PYTHON" -c 'import sys; from dotenv import dotenv_values; print(dotenv_values(sys.argv[1]).get(sys.argv[2]) or "")' \
    "$ENV_FILE" "$1"
}

marker() {
  "$PYTHON" -c 'import json, sys; print(json.load(open(sys.argv[1]))["commit"])' docs/agent/last-reconciled.json
}

# notify TITLE MESSAGE PRIORITY: a push to the phone through the ntfy topic
# the strategy factory uses.
notify() {
  if [ -n "$DRY_RUN" ]; then
    echo "(dry run, not sent) $1: $2"
    return 0
  fi
  local url token
  url="$(setting FACTORY_NTFY_URL)"
  if [ -z "$url" ]; then
    echo "(no FACTORY_NTFY_URL, not sent) $1: $2"
    return 0
  fi
  token="$(setting FACTORY_NTFY_TOKEN)"
  local args=(-fsS -o /dev/null -m 30 -H "Title: $1" -H "Priority: $3" -H "Tags: memo")
  [ -n "$token" ] && args+=(-H "Authorization: Bearer $token")
  curl "${args[@]}" -d "$2" "$url"
}

# Back to a clean checkout detached at $REF. The pass's branch lives on the
# remote if it got that far; the local one goes.
tidy() {
  local branch
  branch="$(git rev-parse --abbrev-ref HEAD 2>/dev/null)"
  git reset -q --hard
  git checkout -q --detach "$REF" 2>/dev/null || git checkout -q --detach
  case "$branch" in "$BRANCH_PREFIX"*) git branch -q -D "$branch" ;; esac
}

fail() {
  echo "FAILED: $1" >&2
  if [ -n "$STARTED" ]; then
    # Everything the pass changed against the commit it read, staged and committed included.
    git diff "$START" > "$SAVED_DIFF" 2>/dev/null
    [ -s "$SAVED_DIFF" ] && echo "The pass's edits are saved in $SAVED_DIFF" >&2
    tidy
  fi
  notify "Docs drift pass failed" "$1" 4 || echo "(the failure notification did not send either)" >&2
  exit 1
}

# One run at a time; a lock left by a run that died is taken over.
take_lock() {
  mkdir -p "$(dirname "$LOCK")"
  if ! mkdir "$LOCK" 2>/dev/null; then
    local holder
    holder="$(cat "$LOCK/pid" 2>/dev/null)"
    if [ -n "$holder" ] && kill -0 "$holder" 2>/dev/null; then
      return 1
    fi
    rm -rf "$LOCK"
    mkdir "$LOCK" 2>/dev/null || return 1
  fi
  echo $$ > "$LOCK/pid"
}

main() {
  cd "$ROOT" || exit 1
  if ! take_lock; then
    echo "Another run holds $LOCK." >&2
    exit 0
  fi
  trap 'rm -rf "$LOCK"' EXIT
  mkdir -p "$LOG_DIR"
  local stamp branch
  stamp="$(date +%Y-%m-%d-%H%M)"
  branch="$BRANCH_PREFIX$stamp"
  SAVED_DIFF="$LOG_DIR/tradejournal-docs-drift-$stamp.diff"
  local result="$LOG_DIR/tradejournal-docs-drift-$stamp.json"

  # Untracked files count too: they would ride along into the pull request.
  [ -z "$(git status --porcelain)" ] \
    || fail "the docs checkout at $ROOT has uncommitted or untracked files (git status); the run did not start"

  say "code: fetch $REF"
  git fetch -q origin || fail "git fetch failed"
  git checkout -q --detach "$REF" || fail "could not check out $REF"
  local since count
  START="$(git rev-parse HEAD)"
  since="$(marker)" || fail "could not read docs/agent/last-reconciled.json"
  count="$(git rev-list --count --no-merges "$since..HEAD" -- . ':(exclude)*.md')" \
    || fail "could not count the commits since ${since:0:7}"
  if [ "$count" -lt "$MIN_COMMITS" ]; then
    say "not due: $count code commits since the docs were reconciled at ${since:0:7}; a pass runs at $MIN_COMMITS"
    return 0
  fi

  local waiting
  waiting="$(gh pr list --state open --json headRefName,url \
    --jq ".[] | select(.headRefName | startswith(\"$BRANCH_PREFIX\")) | .url")" \
    || fail "gh could not list the open pull requests"
  if [ -n "$waiting" ]; then
    say "the last pass is still waiting for review: $waiting"
    # While it waits no pass runs, so a reminder that did not send is a failed run.
    notify "Docs drift pass waiting" \
      "$count code commits since the docs were reconciled, and the last pass is still waiting for review: $waiting" 3 \
      || { echo "FAILED: the reminder that $waiting is waiting for review did not send" >&2; exit 1; }
    return 0
  fi

  say "preflight: GitHub and the Anthropic key"
  git push -q --dry-run origin "HEAD:refs/heads/$branch" || fail "git cannot push to origin (git push --dry-run failed)"
  gh auth status > /dev/null 2>&1 || fail "gh is not logged in (gh auth status)"
  local key
  key="$(setting ANTHROPIC_API_KEY)"
  [ -n "$key" ] || fail "no ANTHROPIC_API_KEY in $ENV_FILE"

  git checkout -q -b "$branch" || fail "could not create the branch $branch"
  STARTED=1
  say "pass: Claude reconciles ${since:0:7}..${START:0:7} ($count code commits)"
  local prompt
  prompt="You are running the TradeJournal documentation drift pass unattended: nobody is watching, and nobody can answer a question or approve anything.

Read CLAUDE.md, then .claude/skills/docs-drift/SKILL.md, and do the pass it describes over the range $since..$START ($count code commits). HEAD is $START.

For this run:
- Change only existing documentation: files under docs/, README.md, AGENTS.md and CLAUDE.md. You cannot create files, run tests, commit or push, and anything that would need permission is refused. The script that started you checks your edits, runs the docs tests, commits, pushes and opens the pull request, so skip the skill's verify.sh step and do the rest.
- Of the shell you have git log, git diff and git show; read files with your own tools.
- When the pass is done, set docs/agent/last-reconciled.json to {\"commit\": \"$START\", \"date\": \"$(date +%F)\", \"note\": \"<one line: what this pass covered>\"}. If nothing needed changing, still move the marker; that is a good outcome.
- Your final message becomes the pull request's description, in Markdown, for a trader who does not read code: what you checked, what you changed and why, anything you deliberately left alone, and that prose accuracy is not machine-verifiable (each claim was re-read against the code it describes). No preamble."
  ANTHROPIC_API_KEY="$key" claude -p "$prompt" --bare --restricted --model "${DOCS_DRIFT_MODEL:-opus}" \
    --tools "Read,Grep,Glob,Edit,Bash" \
    --allowedTools "Read" "Grep" "Glob" "Edit(docs/**)" "Edit(README.md)" "Edit(AGENTS.md)" "Edit(CLAUDE.md)" \
      "Bash(git log *)" "Bash(git diff *)" "Bash(git show *)" \
    --permission-mode dontAsk --permission-prompts none --max-budget-usd "$BUDGET_USD" \
    --no-session-persistence --output-format json < /dev/null > "$result" 2> "$result.stderr" &
  local pid=$!
  ( sleep "$TIME_LIMIT" && kill "$pid" 2> /dev/null ) &
  local watchdog=$!
  wait "$pid"
  local status=$?
  pkill -P "$watchdog" 2> /dev/null
  kill "$watchdog" 2> /dev/null
  [ "$status" -eq 0 ] || fail "Claude stopped with exit $status (a run past ${TIME_LIMIT}s is stopped); see $result"
  local body
  body="$("$PYTHON" - "$result" <<'EOF'
import json, sys
run = json.load(open(sys.argv[1]))
text = (run.get("result") or "").strip()
if run.get("is_error") or run.get("subtype") != "success" or not text:
    sys.exit(f"{run.get('subtype')}: {text[:300]}")
print(text)
print(f"\n_The pass took Claude {run.get('num_turns')} turns and ${run.get('total_cost_usd') or 0:.2f}._")
EOF
)" || fail "Claude's pass did not finish ($(tail -1 "$result.stderr" 2> /dev/null)); see $result"

  say "check: only documentation changed, and the marker moved"
  local changed outside
  changed="$(git status --porcelain --untracked-files=all)"
  outside="$(printf '%s\n' "$changed" | grep -Ev "^ M $ALLOWED\$" | sed 's/^...//' | tr '\n' ' ')"
  [ -z "${outside// /}" ] || fail "the pass changed files it may not: $outside"
  [ "$(marker)" = "$START" ] || fail "the pass did not set the marker to the commit it read (${START:0:7})"
  bash -c "$CHECK" || fail "the docs tests failed after the pass; see the log"

  if [ -n "$DRY_RUN" ]; then
    say "dry run: the pull request that would open"
    printf '%s\n' "$body"
    git --no-pager diff --stat
    git diff "$START" > "$SAVED_DIFF"
    echo "The diff is saved in $SAVED_DIFF"
    STARTED=""
    tidy
    return 0
  fi

  say "record: commit, push, pull request"
  git add -u || fail "git add failed"
  git commit -q -F - <<EOF || fail "git commit failed"
Documentation drift pass through ${START:0:7}

Reconciles the documentation with the $count code commits since ${since:0:7},
run unattended by scripts/docs_drift_week.sh.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
  git push -q -u origin "$branch" || fail "git push failed"
  local url
  url="$(gh pr create --base main --head "$branch" --title "Documentation drift pass ($count code commits)" \
    --body "$body

🤖 Generated with [Claude Code](https://claude.com/claude-code)")" \
    || fail "the branch $branch is pushed, but gh could not open the pull request"
  say "pull request: $url"
  STARTED=""
  tidy
  notify "Docs drift pass ready for review" "$count code commits reconciled. Review and merge: $url" 3 \
    || echo "(the notification did not send)" >&2
}

main "$@"; exit $?
