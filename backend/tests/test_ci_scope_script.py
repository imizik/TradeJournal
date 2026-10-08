"""scripts/ci_scope.sh against a throwaway repository.

Both CI and Deployment package skip their disposable environments on what this
script calls a documentation-only diff, so what it lets through is checked
here rather than only on a pull request's CI run.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "ci_scope.sh"

pytestmark = pytest.mark.skipif(not shutil.which("git") or not shutil.which("bash"), reason="needs git and bash")


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


def write(repo: Path, path: str, text: str = "x\n") -> None:
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "config", "user.email", "test@example.com")
    git(tmp_path, "config", "user.name", "Test")
    for path in ["README.md", "docs/guide.md", "backend/app.py", "frontend/page.tsx"]:
        write(tmp_path, path)
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-qm", "base")
    return tmp_path


def scope(repo: Path, *args: str) -> dict[str, str]:
    result = subprocess.run(["bash", str(SCRIPT), *args], cwd=repo, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return dict(line.split("=", 1) for line in result.stdout.splitlines())


def change(repo: Path, *paths: str) -> None:
    for path in paths:
        write(repo, path, f"changed {path}\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "change")


@pytest.mark.parametrize(
    "paths",
    [
        ["docs/guide.md"],
        ["docs/agent/deep/new.md", "README.md", "AGENTS.md", "CLAUDE.md"],
        [".github/pull_request_template.md"],
    ],
)
def test_documentation_only_diffs_skip_runtime(repo: Path, paths: list[str]) -> None:
    change(repo, *paths)
    assert scope(repo) == {"runtime": "false", "frontend": "false"}


@pytest.mark.parametrize(
    "path",
    ["backend/app.py", "docs/agent/last-reconciled.json", "deploy/README.md", ".github/workflows/ci.yml", "scripts/ci_scope.sh"],
)
def test_anything_else_runs_runtime(repo: Path, path: str) -> None:
    change(repo, "docs/guide.md", path)
    assert scope(repo)["runtime"] == "true"


def test_frontend_changes_are_reported(repo: Path) -> None:
    change(repo, "frontend/page.tsx")
    assert scope(repo) == {"runtime": "true", "frontend": "true"}


def test_moving_runtime_code_into_docs_counts_the_removal(repo: Path) -> None:
    (repo / "docs").mkdir(exist_ok=True)
    git(repo, "mv", "backend/app.py", "docs/app.md")
    git(repo, "commit", "-qm", "move")
    assert scope(repo)["runtime"] == "true"


def test_merge_commit_ignores_what_main_did_since_the_branch(repo: Path) -> None:
    # GitHub checks out a merge of the pull request into the current base.
    # Runtime commits that landed on main after the branch was cut must not
    # make a documentation-only pull request look like a runtime change.
    git(repo, "switch", "-qc", "docs-only")
    change(repo, "docs/guide.md")
    git(repo, "switch", "-q", "main")
    change(repo, "backend/app.py", "frontend/page.tsx")
    git(repo, "merge", "-q", "--no-ff", "-m", "merge", "docs-only")
    assert scope(repo) == {"runtime": "false", "frontend": "false"}


def test_a_failed_diff_fails(repo: Path) -> None:
    result = subprocess.run(["bash", str(SCRIPT), "no-such-ref", "HEAD"], cwd=repo, capture_output=True, text=True)
    assert result.returncode != 0
    assert "runtime=" not in result.stdout
