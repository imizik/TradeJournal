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
# The idea model is Claude Code headless (`claude -p`, Opus, no tools) on the
# Claude plan, never on API credits: the script writes the brief, Claude answers
# it in the brief's JSON format, the answer is saved under
# backend/data/factory/claude/, and the factory judges it as it would any
# `--answer`. The token from `claude setup-token` is CLAUDE_CODE_OAUTH_TOKEN in
# FACTORY_ENV_FILE (backend/.env, which the factory checkout links to the main
# one); the credentials, endpoints and provider switches that would outrank or
# receive it are removed for the call, and the run stops, with the failure on
# the phone, unless Claude Code itself reports the plan token as its sign-in.
# By hand, a Claude Code session can answer instead (/factory-week).
#
#   bash scripts/factory_week.sh                       run the week now (claude -p on the plan)
#   bash scripts/factory_week.sh --brief FILE          write the brief to FILE and stop
#   bash scripts/factory_week.sh --answer FILE [--answer-by NAME]
#                                                      judge the ideas in FILE, record, notify
#   bash scripts/factory_week.sh --use-api             ask the Anthropic API instead (API credits)
#   --budget N (with any)                              N candidates, past this week's three
#
# FACTORY_CLAUDE (claude on PATH, else ~/.local/node/bin/claude),
# FACTORY_CLAUDE_MODEL (opus), FACTORY_CLAUDE_BUDGET_USD (10) and
# FACTORY_CLAUDE_TIME_LIMIT (1800 seconds) bound the claude -p call.
#
# Never touches main or any database. The branch is never merged.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BRIEF=""
ANSWER=""
USE_API=""
WEEK_ARGS=()
BUDGET_ARGS=()
absolute() { case "$1" in /*) echo "$1" ;; *) echo "$PWD/$1" ;; esac; }  # the run moves to $ROOT
while [ $# -gt 0 ]; do
  if [ "$1" = --use-api ]; then
    USE_API=1
    WEEK_ARGS+=("$1")
    shift
    continue
  fi
  case "$1" in
    --brief|--answer|--answer-by|--budget) ;;
    *) echo "Unknown option $1; see the top of $0." >&2; exit 2 ;;
  esac
  [ $# -ge 2 ] || { echo "$1 needs a value; see the top of $0." >&2; exit 2; }
  case "$1" in
    --brief) BRIEF="$(absolute "$2")" ;;
    --answer) ANSWER=1; WEEK_ARGS+=("$1" "$(absolute "$2")") ;;
    --budget) BUDGET_ARGS+=("$1" "$2"); WEEK_ARGS+=("$1" "$2") ;;
    *) WEEK_ARGS+=("$1" "$2") ;;
  esac
  shift 2
done
if [ -n "$USE_API" ] && [ -n "$BRIEF$ANSWER" ]; then
  echo "--use-api goes with neither --brief nor --answer; see the top of $0." >&2
  exit 2
fi
PYTHON="$ROOT/backend/.venv/bin/python"
FACTORY=("$PYTHON" "$ROOT/backend/scripts/strategy_factory.py")
LOCK="$ROOT/backend/data/factory/week.lock"
ENV_FILE="${FACTORY_ENV_FILE:-$ROOT/backend/.env}"
CLAUDE_MODEL="${FACTORY_CLAUDE_MODEL:-opus}"
CLAUDE_BUDGET_USD="${FACTORY_CLAUDE_BUDGET_USD:-10}"
CLAUDE_TIME_LIMIT="${FACTORY_CLAUDE_TIME_LIMIT:-1800}"
# The weekly run's own idea model: claude -p on the plan, unless told otherwise.
ON_PLAN=""
[ -z "$BRIEF$ANSWER$USE_API" ] && ON_PLAN=1

say() { printf '\n==> %s (%s)\n' "$1" "$(date '+%F %T')"; }

# A value from the env file, read the way the app reads it; empty when absent.
setting() {
  [ -f "$ENV_FILE" ] || return 0
  "$PYTHON" -c 'import sys; from dotenv import dotenv_values; print(dotenv_values(sys.argv[1]).get(sys.argv[2]) or "")' \
    "$ENV_FILE" "$1"
}

# The plan token and nothing that outranks it: an auth token, an API key or a
# cloud provider would bill instead, and another base URL or socket would
# receive it (the sign-in check cannot see a socket). The token itself goes in
# as a prefix assignment at each call, never as an argument: ps and exec
# auditing would show an argument. Same as scripts/docs_drift_week.sh.
PLAN_ENV=(env -u ANTHROPIC_AUTH_TOKEN -u ANTHROPIC_API_KEY -u ANTHROPIC_BASE_URL -u ANTHROPIC_UNIX_SOCKET
  -u CLAUDE_CODE_USE_BEDROCK -u CLAUDE_CODE_USE_VERTEX -u CLAUDE_CODE_USE_FOUNDRY -u CLAUDE_CODE_USE_GATEWAY
  -u CLAUDE_CODE_USE_ANTHROPIC_AWS -u CLAUDE_CODE_USE_ANTHROPIC_GOOGLE_CLOUD -u CLAUDE_CODE_USE_MANTLE
  -u CLAUDE_CODE_API_KEY_FILE_DESCRIPTOR -u CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR)
TOKEN=""
# launchd's PATH is short; Claude Code's own installer puts it in ~/.local/node/bin on this Mac.
CLAUDE="${FACTORY_CLAUDE:-$(command -v claude || echo "$HOME/.local/node/bin/claude")}"

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

if [ -n "$ON_PLAN" ]; then
  say "preflight: the Claude plan token"
  [ -x "$CLAUDE" ] || fail "Claude Code is not installed at $CLAUDE (set FACTORY_CLAUDE); the run did not start"
  TOKEN="$(setting CLAUDE_CODE_OAUTH_TOKEN)"
  [ -n "$TOKEN" ] || fail "no CLAUDE_CODE_OAUTH_TOKEN in $ENV_FILE (run \`claude setup-token\` and add it there); the run did not start"
  # Whatever else could still win, Claude Code names the sign-in it would use;
  # anything but the plan token stops the run. A key it holds besides the token
  # (a managed apiKeyHelper, a saved key) leaves the method at oauth_token and
  # shows only as apiKeySource, yet a helper switches the plan off, so any
  # apiKeySource stops the run too.
  signin="$(CLAUDE_CODE_OAUTH_TOKEN="$TOKEN" "${PLAN_ENV[@]}" "$CLAUDE" auth status --json 2> /dev/null | "$PYTHON" -c '
import json, sys
try:
    status = json.load(sys.stdin)
except ValueError:
    status = {}
if not isinstance(status, dict):
    status = {}
method, provider = status.get("authMethod"), status.get("apiProvider", "firstParty")
key = status.get("apiKeySource")
print(f"{method}/{provider}" + (f" with an API key from {key}" if key else ""))
sys.exit(0 if method == "oauth_token" and provider == "firstParty" and not key else 1)')" \
    || fail "Claude would not sign in with the plan token (claude auth status: $signin); the run did not start"
fi

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

if [ -n "$ON_PLAN" ]; then
  RUN_DIR="$ROOT/backend/data/factory/claude/$(date +%Y-%m-%d-%H%M%S)"
  mkdir -p "$RUN_DIR" || fail "could not create $RUN_DIR"
  say "brief: for Claude on the plan"
  "${FACTORY[@]}" week --dry-run --brief-out "$RUN_DIR/brief.md" --schema-out "$RUN_DIR/schema.json" \
    ${BUDGET_ARGS[@]+"${BUDGET_ARGS[@]}"} || fail "writing the brief failed"
  if [ ! -s "$RUN_DIR/brief.md" ]; then
    say "done: this week's candidates are used; nothing to ask"
    exit 0
  fi

  say "ideas: claude -p ($CLAUDE_MODEL) on the Claude plan answers the brief"
  # No tools: the brief is everything the idea model may see. --bare is left
  # off because it never reads the plan token.
  CLAUDE_CODE_OAUTH_TOKEN="$TOKEN" "${PLAN_ENV[@]}" "$CLAUDE" -p --restricted --strict-mcp-config --tools "" \
    --model "$CLAUDE_MODEL" --effort high \
    --system-prompt "You are the idea model of a trading strategy factory. The message is this week's brief: follow its rules and answer in its JSON format." \
    --json-schema "$(cat "$RUN_DIR/schema.json")" \
    --permission-mode dontAsk --permission-prompts none --max-budget-usd "$CLAUDE_BUDGET_USD" \
    --no-session-persistence --output-format json < "$RUN_DIR/brief.md" > "$RUN_DIR/claude.json" 2> "$RUN_DIR/claude.stderr" &
  pid=$!
  # Keep the watchdog's descriptors out of callers that capture this script's
  # output, and stop its sleep when Claude finishes before the time limit.
  (
    sleep "$CLAUDE_TIME_LIMIT" &
    sleeper=$!
    trap 'kill "$sleeper" 2>/dev/null; wait "$sleeper" 2>/dev/null; exit 0' TERM
    wait "$sleeper" || exit 0
    kill "$pid" 2>/dev/null
  ) > /dev/null 2>&1 &
  watchdog=$!
  wait "$pid"
  status=$?
  kill "$watchdog" 2> /dev/null
  wait "$watchdog" 2> /dev/null || true
  [ "$status" -eq 0 ] || fail "claude -p stopped with exit $status (one past ${CLAUDE_TIME_LIMIT}s is stopped); see $RUN_DIR"
  # The answer, and who gave it: the model Claude Code reports, on the plan.
  author="$("$PYTHON" - "$RUN_DIR/claude.json" "$RUN_DIR/answer.json" <<'EOF'
import json, sys
run = json.load(open(sys.argv[1]))
answer = run.get("structured_output")
if run.get("is_error") or run.get("subtype") != "success" or not isinstance(answer, dict):
    sys.exit(f"{run.get('subtype')}: {str(run.get('result') or '')[:300]}")
json.dump(answer, open(sys.argv[2], "w"), indent=2)
models = run.get("modelUsage") or {}
model = max(models, key=lambda name: models[name].get("outputTokens", 0)) if models else "Claude"
print(f"{model} through claude -p on the Claude plan "
      f"(about ${run.get('total_cost_usd') or 0:.2f} at API prices)")
EOF
)" || fail "claude -p gave no answer ($(tail -1 "$RUN_DIR/claude.stderr" 2> /dev/null)); see $RUN_DIR"
  WEEK_ARGS=(--answer "$RUN_DIR/answer.json" --answer-by "$author" ${BUDGET_ARGS[@]+"${BUDGET_ARGS[@]}"})
fi

say "ideas: judge"
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
