"""scripts/factory_week.sh against a throwaway repository and a stub factory.

The stub stands in for `backend/.venv/bin/python scripts/strategy_factory.py`:
it logs each command, and its `week` writes a report and a ledger line the
way the real one does (then fails when told to). The repository pushes to a
bare remote, so the commits and pushes are real.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
WRAPPER = REPO / "scripts" / "factory_week.sh"

pytestmark = pytest.mark.skipif(not shutil.which("git") or not shutil.which("bash"), reason="needs git and bash")

STUB = """#!/bin/bash
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
echo "$2 $3 $4" >> "$ROOT/../stub.log"
case "$2" in
  prepare) exit "${STUB_PREPARE:-0}" ;;
  week)
    mkdir -p "$ROOT/research/reports"
    echo "a report" > "$ROOT/research/reports/week.md"
    echo '{"id": "judged"}' >> "$ROOT/research/ledger.jsonl"
    exit "${STUB_WEEK:-0}" ;;
  notify) exit 0 ;;
esac
exit 3
"""


def git(cwd: Path, env: dict, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def checkout(tmp_path: Path) -> tuple[Path, dict]:
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
           "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "test@example.com",
           "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "test@example.com"}
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


def run(work: Path, env: dict, **stub: str) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(work / "scripts" / "factory_week.sh")], cwd=work, env={**env, **stub},
                          capture_output=True, text=True)


def calls(work: Path) -> list[str]:
    log = work.parent / "stub.log"
    return [line.strip() for line in log.read_text().splitlines()] if log.exists() else []


def pushed(work: Path, env: dict) -> list[str]:
    git(work, env, "fetch", "-q", "origin")
    return git(work, env, "log", "--format=%s", "origin/factory/ledger").splitlines()


def test_a_week_is_committed_pushed_and_announced(checkout):
    work, env = checkout
    result = run(work, env)
    assert result.returncode == 0, result.stderr
    subjects = pushed(work, env)
    assert subjects[0].startswith("Strategy factory: week of ") and "incomplete" not in subjects[0]
    assert git(work, env, "show", "origin/factory/ledger:research/reports/week.md") == "a report"
    assert calls(work) == ["prepare", "week", "notify"]
    assert not (work / "backend" / "data" / "factory" / "week.lock").exists()
    assert git(work, env, "status", "--porcelain") == ""


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
