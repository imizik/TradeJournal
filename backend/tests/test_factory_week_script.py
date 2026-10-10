"""scripts/factory_week.sh against a throwaway repository and a stub factory.

The stub stands in for `backend/.venv/bin/python scripts/strategy_factory.py`:
it logs each command, and its `week` writes a report and a ledger line the
way the real one does (then fails when told to); the Python the script runs
itself (reading the settings, Claude's answer) is the test's own. Stubs for
`claude` and `env` stand in for the idea model on the Claude plan. The
repository pushes to a bare remote, so the commits and pushes are real.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
WRAPPER = REPO / "scripts" / "factory_week.sh"

pytestmark = pytest.mark.skipif(not shutil.which("git") or not shutil.which("bash"), reason="needs git and bash")

STUB = """#!/bin/bash
case "$1" in -c|-) exec "PYTHON" "$@" ;; esac
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
echo "$2 $3 $4" >> "$ROOT/../stub.log"
shift
printf '%s\\n' "$*" >> "$ROOT/../stub.args"
set -- "" "$@"
case "$2" in
  prepare) exit "${STUB_PREPARE:-0}" ;;
  week)
    if [ "$3" = --dry-run ]; then
      [ -n "${STUB_NO_BRIEF:-}" ] || echo "the brief" > "$5"
      [ "$6" = --schema-out ] && echo '{"type": "object"}' > "$7"
      exit 0
    fi
    mkdir -p "$ROOT/research/reports"
    echo "a report" > "$ROOT/research/reports/week.md"
    echo '{"id": "judged"}' >> "$ROOT/research/ledger.jsonl"
    exit "${STUB_WEEK:-0}" ;;
  notify) exit 0 ;;
esac
exit 3
""".replace("PYTHON", sys.executable)

ANSWER = {"ideas": [], "lessons": "Nothing new.", "wanted": []}

# Claude Code: `auth status` names the sign-in by its precedence; a key the
# script cannot strip (STUB_KEY_SOURCE, a managed apiKeyHelper) leaves the method
# at oauth_token and shows only as apiKeySource, as the real CLI reports it.
# `-p` answers the brief.
STUB_CLAUDE = """#!/bin/bash
seen() {
  printf '%s\\n' "token=${CLAUDE_CODE_OAUTH_TOKEN:-}" "key=${ANTHROPIC_API_KEY:-}" "bearer=${ANTHROPIC_AUTH_TOKEN:-}" \\
    "base=${ANTHROPIC_BASE_URL:-}${ANTHROPIC_UNIX_SOCKET:-}" "provider=$(providers)" \\
    "fd=${CLAUDE_CODE_API_KEY_FILE_DESCRIPTOR:-}${CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR:-}"
}
providers() {
  printf '%s' "${CLAUDE_CODE_USE_BEDROCK:-}${CLAUDE_CODE_USE_VERTEX:-}${CLAUDE_CODE_USE_FOUNDRY:-}" \\
    "${CLAUDE_CODE_USE_GATEWAY:-}${CLAUDE_CODE_USE_ANTHROPIC_AWS:-}${CLAUDE_CODE_USE_ANTHROPIC_GOOGLE_CLOUD:-}" \\
    "${CLAUDE_CODE_USE_MANTLE:-}"
}
if [ "$1 $2" = "auth status" ]; then
  seen > "$STUB_LOG/auth.env"
  if [ -n "$(providers)" ]; then method=third_party; provider=bedrock
  elif [ -n "${ANTHROPIC_AUTH_TOKEN:-}${ANTHROPIC_API_KEY:-}" ]; then method=api_key; provider=firstParty
  elif [ -n "${CLAUDE_CODE_OAUTH_TOKEN:-}" ]; then method=oauth_token; provider=firstParty
  else echo '{"loggedIn": false, "authMethod": "none"}'; exit 1
  fi
  key=""
  [ -n "${STUB_KEY_SOURCE:-}" ] && key=", \\"apiKeySource\\": \\"$STUB_KEY_SOURCE\\""
  printf '{"loggedIn": true, "authMethod": "%s", "apiProvider": "%s"%s}\\n' "$method" "$provider" "$key"
  exit 0
fi
printf '%s\\n' "$@" > "$STUB_LOG/claude.args"
seen > "$STUB_LOG/claude.env"
cat > "$STUB_LOG/claude.stdin"
case "${STUB_CLAUDE:-good}" in
  stall) exec sleep 30 ;;
  crash) echo "boom" >&2; exit 1 ;;
  unfinished) echo '{"type": "result", "subtype": "error_max_budget_usd", "is_error": true, "result": ""}' ;;
  # How the CLI reports a refused key or login: "success", with the error as the answer.
  refused) echo '{"type": "result", "subtype": "success", "is_error": true, "result": "Failed to authenticate. API Error: 401"}' ;;
  prose) echo '{"type": "result", "subtype": "success", "is_error": false, "result": "Here are some ideas."}' ;;
  *) printf '{"type": "result", "subtype": "success", "is_error": false, "result": "", "structured_output": %s,
     "total_cost_usd": 2.5, "modelUsage": {"claude-haiku-4-5": {"outputTokens": 10},
     "claude-opus-5-5": {"outputTokens": 9000}}}\\n' "$STUB_ANSWER" ;;
esac
"""

# env(1) passes through, keeping its arguments: anything there is visible to ps.
STUB_ENV = """#!/bin/bash
printf '%s\\n' "$@" >> "$STUB_LOG/env.args"
exec /usr/bin/env "$@"
"""



def git(cwd: Path, env: dict, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def checkout(tmp_path: Path) -> tuple[Path, dict]:
    stubs, log = tmp_path / "stubs", tmp_path / "log"
    stubs.mkdir()
    log.mkdir()
    for name, text in (("claude", STUB_CLAUDE), ("env", STUB_ENV)):
        (stubs / name).write_text(text)
        (stubs / name).chmod(0o755)
    settings = tmp_path / "backend.env"
    # The real file also holds the API key, which the weekly run must never use.
    settings.write_text("CLAUDE_CODE_OAUTH_TOKEN=test-token  # a comment the token must not include\n"
                        "ANTHROPIC_API_KEY=file-key\n")
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
           "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "test@example.com",
           "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "test@example.com",
           "PATH": f"{stubs}:/usr/bin:/bin", "STUB_LOG": str(log), "FACTORY_ENV_FILE": str(settings),
           "STUB_ANSWER": json.dumps(ANSWER),
           # What launchd's environment may carry: each would outrank the plan token or receive it.
           "ANTHROPIC_API_KEY": "env-key", "ANTHROPIC_AUTH_TOKEN": "env-bearer",
           "ANTHROPIC_BASE_URL": "https://gateway.example", "ANTHROPIC_UNIX_SOCKET": "/tmp/gateway.sock",
           "CLAUDE_CODE_API_KEY_FILE_DESCRIPTOR": "3", "CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR": "4",
           **{f"CLAUDE_CODE_USE_{name}": "1" for name in
              ("BEDROCK", "VERTEX", "FOUNDRY", "GATEWAY", "ANTHROPIC_AWS", "ANTHROPIC_GOOGLE_CLOUD", "MANTLE")}}
    remote, work = tmp_path / "remote.git", tmp_path / "work"
    git(tmp_path, env, "init", "-q", "--bare", "-b", "main", str(remote))
    git(tmp_path, env, "init", "-q", "-b", "main", str(work))
    (work / "scripts").mkdir()
    shutil.copy(WRAPPER, work / "scripts" / "factory_week.sh")
    (work / "research").mkdir()
    (work / "research" / "ledger.jsonl").write_text('{"id": "seed"}\n')
    (work / ".gitignore").write_text("backend/.venv/\nbackend/data/\n")
    git(work, env, "add", ".")
    git(work, env, "commit", "-q", "-m", "seed")
    git(work, env, "remote", "add", "origin", str(remote))
    git(work, env, "push", "-q", "origin", "main")
    git(work, env, "checkout", "-q", "-b", "factory/ledger")
    git(work, env, "push", "-q", "-u", "origin", "factory/ledger")
    stub = work / "backend" / ".venv" / "bin" / "python"
    stub.parent.mkdir(parents=True)
    stub.write_text(STUB)
    stub.chmod(0o755)
    return work, env


def run(work: Path, env: dict, *options: str, **stub: str) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(work / "scripts" / "factory_week.sh"), *options], cwd=work,
                          env={**env, **stub}, capture_output=True, text=True, timeout=60)


def calls(work: Path, name: str = "stub.log") -> list[str]:
    log = work.parent / name
    return [line.strip() for line in log.read_text().splitlines()] if log.exists() else []


def logged(env: dict, name: str) -> str:
    path = Path(env["STUB_LOG"]) / name
    return path.read_text() if path.exists() else ""


def claude_runs(work: Path) -> list[Path]:
    return sorted((work / "backend" / "data" / "factory" / "claude").glob("*"))


def pushed(work: Path, env: dict) -> list[str]:
    git(work, env, "fetch", "-q", "origin")
    return git(work, env, "log", "--format=%s", "origin/factory/ledger").splitlines()


def test_a_week_is_answered_on_the_claude_plan_judged_pushed_and_announced(checkout):
    work, env = checkout
    result = run(work, env, "--budget", "2")
    assert result.returncode == 0, result.stderr
    subjects = pushed(work, env)
    assert subjects[0].startswith("Strategy factory: week of ") and "incomplete" not in subjects[0]
    assert git(work, env, "show", "origin/factory/ledger:research/reports/week.md") == "a report"
    (run_dir,) = claude_runs(work)
    assert calls(work) == ["prepare", "week --dry-run --brief-out", f"week --answer {run_dir}/answer.json", "notify"]
    # The brief is Claude's whole input, its answer is saved, and the factory judges that file.
    assert logged(env, "claude.stdin") == "the brief\n"
    assert json.loads((run_dir / "answer.json").read_text()) == ANSWER
    judge = calls(work, "stub.args")[2]
    assert judge.endswith(f"week --answer {run_dir}/answer.json --answer-by claude-opus-5-5 through claude -p on the "
                          "Claude plan (about $2.50 at API prices) --budget 2")
    assert calls(work, "stub.args")[1].endswith(f"--schema-out {run_dir}/schema.json --budget 2")
    # Headless, Opus, no tools, held to the brief's schema.
    args = logged(env, "claude.args").splitlines()
    assert args[:6] == ["-p", "--restricted", "--strict-mcp-config", "--tools", "", "--model"]
    assert args[6] == "opus" and args[args.index("--json-schema") + 1] == '{"type": "object"}'
    for expected in ("--permission-mode", "dontAsk", "--permission-prompts", "none", "--max-budget-usd",
                     "--no-session-persistence"):
        assert expected in args
    # On the Claude plan, never API credits: --bare would ignore the plan token, and no key reaches Claude.
    assert "--bare" not in args
    plan_only = "token=test-token\nkey=\nbearer=\nbase=\nprovider=\nfd=\n"
    assert logged(env, "auth.env") == plan_only and logged(env, "claude.env") == plan_only
    # Both reach Claude through env(1), and the token is never one of its arguments.
    env_args = logged(env, "env.args")
    assert env_args.count("claude\n") == 2 and "-u\nANTHROPIC_API_KEY\n" in env_args
    assert "test-token" not in env_args
    assert not (work / "backend" / "data" / "factory" / "week.lock").exists()
    assert git(work, env, "status", "--porcelain") == ""


def test_no_plan_token_stops_the_run_before_anything_happens(checkout, tmp_path):
    work, env = checkout
    settings = tmp_path / "key-only.env"
    settings.write_text("ANTHROPIC_API_KEY=file-key\n")
    result = run(work, env, FACTORY_ENV_FILE=str(settings))
    assert result.returncode == 1 and "no CLAUDE_CODE_OAUTH_TOKEN" in result.stderr
    (notice,) = calls(work)  # no bars fetched, no API asked
    assert notice.startswith("notify --failure no CLAUDE_CODE_OAUTH_TOKEN in")
    assert logged(env, "claude.args") == "" and pushed(work, env) == ["seed"]


def test_a_sign_in_other_than_the_plan_stops_the_run(checkout):
    work, env = checkout
    result = run(work, env, STUB_KEY_SOURCE="apiKeyHelper")
    assert result.returncode == 1
    assert calls(work) == ["notify --failure Claude would not sign in with the plan token (claude auth status: "
                           "oauth_token/firstParty with an API key from apiKeyHelper); the run did not start"]
    assert logged(env, "claude.args") == "" and pushed(work, env) == ["seed"]


@pytest.mark.parametrize("mode, reason", [
    ("unfinished", "claude -p gave no answer"),
    ("refused", "claude -p gave no answer"),
    ("prose", "claude -p gave no answer"),
    ("crash", "claude -p stopped with exit 1"),
])
def test_no_answer_from_claude_judges_nothing(checkout, mode, reason):
    work, env = checkout
    result = run(work, env, STUB_CLAUDE=mode)
    assert result.returncode == 1 and reason in result.stderr
    assert calls(work)[:2] == ["prepare", "week --dry-run --brief-out"]
    assert calls(work)[-1].startswith(f"notify --failure {reason}") and len(calls(work)) == 3
    assert pushed(work, env) == ["seed"]
    (run_dir,) = claude_runs(work)
    assert (run_dir / "claude.json").exists()  # kept to look at
    assert not (work / "backend" / "data" / "factory" / "week.lock").exists()


def test_time_limit_stops_a_stalled_claude(checkout):
    work, env = checkout
    result = run(work, env, STUB_CLAUDE="stall", FACTORY_CLAUDE_TIME_LIMIT="1")
    assert result.returncode == 1 and "claude -p stopped with exit" in result.stderr
    assert pushed(work, env) == ["seed"]


def test_no_claude_stops_the_run(checkout, tmp_path):
    work, env = checkout
    result = run(work, env, FACTORY_CLAUDE=str(tmp_path / "missing"))
    assert result.returncode == 1
    assert calls(work)[0].startswith("notify --failure Claude Code is not installed at")
    assert pushed(work, env) == ["seed"]


def test_a_used_week_asks_claude_nothing(checkout):
    work, env = checkout
    result = run(work, env, STUB_NO_BRIEF="1")
    assert result.returncode == 0, result.stderr
    assert calls(work) == ["prepare", "week --dry-run --brief-out"]
    assert logged(env, "claude.args") == ""


def test_the_api_is_used_only_when_asked(checkout):
    work, env = checkout
    result = run(work, env, "--use-api")
    assert result.returncode == 0, result.stderr
    assert calls(work) == ["prepare", "week --use-api", "notify"]
    assert logged(env, "auth.env") == "" and logged(env, "claude.args") == ""
    assert run(work, env, "--use-api", "--answer", "a.json").returncode == 2


def test_a_failed_week_keeps_what_it_judged(checkout):
    work, env = checkout
    result = run(work, env, STUB_WEEK="1")
    assert result.returncode == 1
    assert pushed(work, env)[0].endswith(", incomplete")
    assert '{"id": "judged"}' in git(work, env, "show", "origin/factory/ledger:research/ledger.jsonl")
    *_, notice = calls(work)
    assert notice.startswith("notify --failure the weekly run failed while proposing or judging")


def test_leftover_files_stop_the_run_before_anything_happens(checkout):
    work, env = checkout
    (work / "research" / "specs").mkdir()
    (work / "research" / "specs" / "leftover.json").write_text("{}")
    assert run(work, env).returncode == 1
    assert calls(work) == ["notify --failure the factory checkout has uncommitted or untracked files (git status); "
                           "the run did not start"]
    assert pushed(work, env) == ["seed"]


def test_the_wrong_branch_or_a_failed_fetch_stops_the_run(checkout):
    work, env = checkout
    assert run(work, env, STUB_PREPARE="1").returncode == 1
    assert calls(work) == ["prepare", "notify --failure fetching bars from Alpaca failed"]
    git(work, env, "checkout", "-q", "main")
    assert run(work, env).returncode == 1
    assert calls(work)[-1].startswith("notify --failure the factory checkout at")
    assert pushed(work, env) == ["seed"]


def test_a_brief_for_a_claude_code_session_is_written_and_nothing_is_recorded(checkout, tmp_path):
    work, env = checkout
    brief = tmp_path / "brief.md"
    result = run(work, env, "--brief", str(brief), "--budget", "2")
    assert result.returncode == 0, result.stderr
    assert brief.read_text() == "the brief\n"
    assert calls(work) == ["prepare", "week --dry-run --brief-out"]  # the stub logs three words
    assert pushed(work, env) == ["seed"]  # nothing judged, nothing pushed, nothing sent


def test_no_brief_when_the_week_is_used_up(checkout, tmp_path):
    work, env = checkout
    result = run(work, env, "--brief", str(tmp_path / "brief.md"), STUB_NO_BRIEF="1")
    assert result.returncode == 3 and "Add --budget N" in result.stderr
    assert calls(work) == ["prepare", "week --dry-run --brief-out"]


def test_an_answer_is_judged_recorded_and_announced(checkout):
    work, env = checkout
    result = run(work, env, "--answer", "answer.json", "--answer-by", "Claude", "--budget", "3")
    assert result.returncode == 0, result.stderr
    # A relative path is taken from where the command ran, not from the checkout the run moves to.
    assert calls(work) == ["prepare", f"week --answer {work}/answer.json", "notify"]
    assert pushed(work, env)[0].startswith("Strategy factory: week of ")


def test_an_unknown_option_stops_the_run(checkout):
    work, env = checkout
    assert run(work, env, "--brief").returncode == 2  # no file after it
    assert run(work, env, "--answers", "x").returncode == 2
    assert calls(work) == []
