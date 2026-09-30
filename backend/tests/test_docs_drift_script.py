"""scripts/docs_drift_week.sh against a throwaway repository and stubs.

The stubs stand in for `claude` (it edits the docs the way a pass would and
answers in the CLI's JSON), `gh` (open pull requests, and opening one) and
`curl` (the phone). The repository pushes to a bare remote, so the branch,
the commit and the push are real, and the Python that reads the settings and
the marker is the test's own.
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
SCRIPT = REPO / "scripts" / "docs_drift_week.sh"

pytestmark = pytest.mark.skipif(not shutil.which("git") or not shutil.which("bash"), reason="needs git and bash")

STUB_CLAUDE = """#!/bin/bash
printf '%s\\n' "$@" > "$STUB_LOG/claude.args"
mode="${STUB_CLAUDE:-good}"
echo "A corrected sentence." >> docs/guide.md
[ "$mode" = code ] && echo "x = 2" >> app.py
[ "$mode" = nomarker ] || printf '{"commit": "%s", "date": "2026-10-03", "note": "stub"}\\n' "$(git rev-parse HEAD)" \\
  > docs/agent/last-reconciled.json
case "$mode" in
  unfinished) echo '{"type": "result", "subtype": "error_max_budget_usd", "is_error": true, "result": ""}' ;;
  # How the CLI reports a refused key or login: "success", with the error as the answer.
  refused) echo '{"type": "result", "subtype": "success", "is_error": true, "result": "Failed to authenticate. API Error: 401"}' ;;
  *) echo '{"type": "result", "subtype": "success", "is_error": false, "result": "Checked the guide; fixed one sentence.", "num_turns": 4, "total_cost_usd": 1.25}' ;;
esac
"""

STUB_GH = """#!/bin/bash
printf '%s\\n' "gh $*" >> "$STUB_LOG/gh.log"
case "$1 $2" in
  "pr list") [ -n "${STUB_OPEN_PR:-}" ] && echo "$STUB_OPEN_PR"; exit 0 ;;
  "pr create") echo "https://github.com/example/repo/pull/99"; exit 0 ;;
  "auth status") exit 0 ;;
esac
exit 3
"""

STUB_CURL = """#!/bin/bash
printf '%s\\n' "$*" >> "$STUB_LOG/curl.log"
"""


def git(cwd: Path, env: dict, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True, text=True, check=True).stdout.strip()


def commit(work: Path, env: dict, message: str) -> None:
    git(work, env, "add", ".")
    git(work, env, "commit", "-q", "-m", message)


@pytest.fixture
def checkout(tmp_path: Path) -> tuple[Path, dict]:
    stubs, log = tmp_path / "stubs", tmp_path / "log"
    stubs.mkdir()
    log.mkdir()
    for name, text in (("claude", STUB_CLAUDE), ("gh", STUB_GH), ("curl", STUB_CURL)):
        (stubs / name).write_text(text)
        (stubs / name).chmod(0o755)
    settings = tmp_path / "backend.env"
    settings.write_text("ANTHROPIC_API_KEY=test-key  # a comment the key must not include\n"
                        "FACTORY_NTFY_URL=https://ntfy.example/topic\n")
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
           "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "test@example.com",
           "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "test@example.com",
           "PATH": f"{stubs}:/usr/bin:/bin", "STUB_LOG": str(log), "DOCS_DRIFT_ENV_FILE": str(settings),
           "DOCS_DRIFT_LOG_DIR": str(log), "DOCS_DRIFT_MIN_COMMITS": "4",  # exactly the commits below
           "DOCS_DRIFT_CHECK": f'echo checked >> "{log}/check.log"'}
    remote, work = tmp_path / "remote.git", tmp_path / "work"
    git(tmp_path, env, "init", "-q", "--bare", "-b", "main", str(remote))
    git(tmp_path, env, "init", "-q", "-b", "main", str(work))
    (work / "scripts").mkdir()
    shutil.copy(SCRIPT, work / "scripts" / "docs_drift_week.sh")
    (work / "docs" / "agent").mkdir(parents=True)
    (work / "docs" / "guide.md").write_text("The guide.\n")
    (work / "app.py").write_text("x = 1\n")
    (work / ".gitignore").write_text("backend/.venv/\nbackend/data/\n")
    commit(work, env, "seed")
    seed = git(work, env, "rev-parse", "HEAD")
    (work / "docs" / "agent" / "last-reconciled.json").write_text(json.dumps({"commit": seed, "date": "2026-09-29"}))
    commit(work, env, "the marker")
    for k in range(2, 5):
        (work / "app.py").write_text(f"x = {k}\n")
        commit(work, env, f"code change {k}")
    git(work, env, "remote", "add", "origin", str(remote))
    git(work, env, "push", "-q", "origin", "main")
    git(work, env, "fetch", "-q", "origin")
    git(work, env, "checkout", "-q", "--detach", "origin/main")
    python = work / "backend" / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text(f'#!/bin/bash\nexec "{sys.executable}" "$@"\n')
    python.chmod(0o755)
    return work, env


def run(work: Path, env: dict, **extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(work / "scripts" / "docs_drift_week.sh")], cwd=work, env={**env, **extra},
                          capture_output=True, text=True)


def logged(env: dict, name: str) -> str:
    path = Path(env["STUB_LOG"]) / name
    return path.read_text() if path.exists() else ""


def remote_branches(work: Path, env: dict) -> list[str]:
    out = git(work, env, "ls-remote", "--heads", "origin")
    return [line.split("refs/heads/")[1] for line in out.splitlines()]


def assert_tidy(work: Path, env: dict) -> None:
    assert git(work, env, "status", "--porcelain") == ""
    assert git(work, env, "rev-parse", "HEAD") == git(work, env, "rev-parse", "origin/main")
    assert git(work, env, "branch", "--list", "docs/drift-*") == ""
    assert not (work / "backend" / "data" / "docs-drift.lock").exists()


def test_nothing_happens_before_the_pass_is_due(checkout):
    work, env = checkout
    result = run(work, env, DOCS_DRIFT_MIN_COMMITS="5")
    assert result.returncode == 0, result.stderr
    assert "not due: 4 code commits" in result.stdout  # the marker commit counts; Markdown-only ones would not
    assert logged(env, "claude.args") == "" and logged(env, "gh.log") == "" and logged(env, "curl.log") == ""
    assert remote_branches(work, env) == ["main"]
    assert_tidy(work, env)


def test_a_due_pass_is_pushed_and_opened_for_review(checkout):
    work, env = checkout
    result = run(work, env)
    assert result.returncode == 0, result.stderr
    (branch,) = [b for b in remote_branches(work, env) if b != "main"]
    assert branch.startswith("docs/drift-")
    changed = git(work, env, "diff", "--name-only", "origin/main", f"origin/{branch}").splitlines()
    assert changed == ["docs/agent/last-reconciled.json", "docs/guide.md"]
    marker = json.loads(git(work, env, "show", f"origin/{branch}:docs/agent/last-reconciled.json"))
    assert marker["commit"] == git(work, env, "rev-parse", "origin/main")
    assert git(work, env, "log", "-1", "--format=%s", f"origin/{branch}").startswith("Documentation drift pass through ")
    # Claude ran headless and locked down: docs edits and read-only git, nothing that could wait for a person.
    args = logged(env, "claude.args").splitlines()
    for expected in ("-p", "--bare", "--restricted", "--permission-prompts", "none", "--permission-mode", "dontAsk",
                     "Edit(docs/**)", "Bash(git log *)", "--max-budget-usd"):
        assert expected in args
    assert not [a for a in args if a.startswith("Bash(") and not a.startswith(("Bash(git log", "Bash(git diff", "Bash(git show"))]
    gh = logged(env, "gh.log")
    assert "gh pr create --base main --head " + branch in gh
    assert "Checked the guide; fixed one sentence." in gh and "$1.25" in gh and "Generated with [Claude Code]" in gh
    assert "https://github.com/example/repo/pull/99" in logged(env, "curl.log")
    assert logged(env, "check.log") == "checked\n"
    assert_tidy(work, env)


@pytest.mark.parametrize("mode, reason", [
    ("code", "changed files it may not: app.py"),
    ("nomarker", "did not set the marker"),
    ("unfinished", "did not finish"),
    ("refused", "did not finish"),
])
def test_a_bad_pass_is_refused_and_nothing_is_pushed(checkout, mode, reason):
    work, env = checkout
    result = run(work, env, STUB_CLAUDE=mode)
    assert result.returncode == 1
    assert reason in result.stderr
    assert remote_branches(work, env) == ["main"]
    assert "pr create" not in logged(env, "gh.log")
    assert "Docs drift pass failed" in logged(env, "curl.log")
    assert list(Path(env["STUB_LOG"]).glob("tradejournal-docs-drift-*.diff"))  # the edits are kept to look at
    assert_tidy(work, env)


def test_failed_docs_tests_stop_the_push(checkout):
    work, env = checkout
    result = run(work, env, DOCS_DRIFT_CHECK="exit 1")
    assert result.returncode == 1 and "the docs tests failed" in result.stderr
    assert remote_branches(work, env) == ["main"]
    assert_tidy(work, env)


def test_a_pass_waiting_for_review_holds_the_next_one(checkout):
    work, env = checkout
    result = run(work, env, STUB_OPEN_PR="https://github.com/example/repo/pull/98")
    assert result.returncode == 0
    assert logged(env, "claude.args") == ""
    assert "still waiting for review: https://github.com/example/repo/pull/98" in logged(env, "curl.log")
    assert_tidy(work, env)


def test_a_dry_run_opens_nothing(checkout):
    work, env = checkout
    result = run(work, env, DOCS_DRIFT_DRY_RUN="1")
    assert result.returncode == 0, result.stderr
    assert "Checked the guide; fixed one sentence." in result.stdout
    assert remote_branches(work, env) == ["main"]
    assert "pr create" not in logged(env, "gh.log") and logged(env, "curl.log") == ""
    assert_tidy(work, env)


def test_leftover_files_stop_the_run_before_anything_happens(checkout):
    work, env = checkout
    (work / "docs" / "stray.md").write_text("left behind\n")
    result = run(work, env)
    assert result.returncode == 1 and "uncommitted or untracked files" in result.stderr
    assert logged(env, "claude.args") == ""
    assert (work / "docs" / "stray.md").exists()  # never cleaned away: it may be someone's work


def test_a_lock_left_by_a_dead_run_is_taken_over(checkout):
    work, env = checkout
    lock = work / "backend" / "data" / "docs-drift.lock"
    lock.mkdir(parents=True)
    dead = subprocess.run(["bash", "-c", "echo $$"], capture_output=True, text=True).stdout.strip()
    (lock / "pid").write_text(dead)
    assert run(work, env).returncode == 0
    assert logged(env, "claude.args") != ""
    lock.mkdir(parents=True)
    (lock / "pid").write_text(str(os.getpid()))  # a live holder
    held = run(work, env)
    assert held.returncode == 0 and "Another run holds" in held.stderr
