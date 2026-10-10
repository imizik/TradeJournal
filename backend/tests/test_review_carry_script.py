"""scripts/review_carry.sh against a throwaway repository.

The review policy lets a clean review survive integrating main only when this
script finds the feature's own patch unchanged, so every way the patch can
change underneath an unchanged-looking branch is checked here.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "review_carry.sh"

pytestmark = pytest.mark.skipif(not shutil.which("git") or not shutil.which("bash"), reason="needs git and bash")


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


def write(repo: Path, path: str, text: str) -> None:
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)


def commit(repo: Path, message: str) -> str:
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", message)
    return git(repo, "rev-parse", "HEAD")


def carry(repo: Path, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["bash", str(SCRIPT), *args], cwd=cwd or repo, capture_output=True, text=True)


SHARED = "".join(f"line {n}\n" for n in range(1, 31))


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "config", "user.email", "test@example.com")
    git(tmp_path, "config", "user.name", "Test")
    write(tmp_path, "backend/app.py", "def run():\n    return 1\n")
    write(tmp_path, "backend/shared.py", SHARED)
    write(tmp_path, "docs/guide.md", "guide\n")
    commit(tmp_path, "base")
    git(tmp_path, "checkout", "-qb", "feature")
    write(tmp_path, "backend/app.py", "def run():\n    return 2\n")
    commit(tmp_path, "feature")
    return tmp_path


def reviewed(repo: Path) -> tuple[str, str]:
    return git(repo, "rev-parse", "main"), git(repo, "rev-parse", "feature")


def advance_main(repo: Path, path: str, text: str) -> None:
    git(repo, "checkout", "-q", "main")
    write(repo, path, text)
    commit(repo, f"main changes {path}")
    git(repo, "checkout", "-q", "feature")


def integrate(repo: Path) -> None:
    git(repo, "merge", "-q", "--no-edit", "main")


def test_unrelated_integration_keeps_the_patch(repo: Path) -> None:
    base, head = reviewed(repo)
    advance_main(repo, "docs/guide.md", "guide, revised\n")
    integrate(repo)

    result = carry(repo, base, head, "main", "HEAD")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "result: identical" in result.stdout
    assert "head contains base: yes" in result.stdout
    assert "incoming files since review: 1\n  docs/guide.md" in result.stdout


def test_defaults_compare_against_origin_main_and_head(repo: Path) -> None:
    base, head = reviewed(repo)
    advance_main(repo, "docs/guide.md", "guide, revised\n")
    integrate(repo)
    git(repo, "update-ref", "refs/remotes/origin/main", "main")
    # A local branch spelled origin/main would win a plain ref lookup.
    git(repo, "branch", "origin/main", base)

    result = carry(repo, base, head)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "result: identical" in result.stdout


def test_main_touching_a_feature_file_elsewhere_changes_the_patch(repo: Path) -> None:
    write(repo, "backend/shared.py", SHARED.replace("line 2\n", "line two\n"))
    commit(repo, "feature also edits shared")
    base, head = reviewed(repo)
    # Far from the feature's hunk, so the merge is clean and the hunk text is
    # the same; only the file's content around it moved.
    advance_main(repo, "backend/shared.py", SHARED.replace("line 29\n", "line twenty-nine\n"))
    integrate(repo)

    result = carry(repo, base, head, "main", "HEAD")

    assert result.returncode == 1
    assert "result: changed" in result.stdout


def test_a_whitespace_only_feature_commit_changes_the_patch(repo: Path) -> None:
    base, head = reviewed(repo)
    write(repo, "backend/app.py", "def run():\n        return 2\n")
    commit(repo, "reindent")

    result = carry(repo, base, head, "main", "HEAD")

    assert result.returncode == 1
    assert "result: changed" in result.stdout
    assert "head contains base: yes" in result.stdout


def test_a_merge_that_alters_main_side_files_changes_the_patch(repo: Path) -> None:
    base, head = reviewed(repo)
    advance_main(repo, "docs/guide.md", "guide, revised\n")
    git(repo, "merge", "-q", "--no-commit", "main")
    write(repo, "docs/guide.md", "guide, quietly different\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "merge main")

    result = carry(repo, base, head, "main", "HEAD")

    assert result.returncode == 1
    assert "result: changed" in result.stdout


def test_an_unintegrated_branch_is_refused(repo: Path) -> None:
    base, head = reviewed(repo)
    advance_main(repo, "backend/shared.py", SHARED.replace("line 29\n", "line twenty-nine\n"))

    result = carry(repo, base, head, "main", "HEAD")

    assert result.returncode == 1
    assert "head contains base: no" in result.stdout
    assert "result: not integrated" in result.stdout


def test_catching_up_to_an_older_main_is_refused(repo: Path) -> None:
    base, head = reviewed(repo)
    advance_main(repo, "docs/guide.md", "guide, revised\n")
    integrate(repo)
    advance_main(repo, "backend/app.py", "def run():\n    return 3\n")

    result = carry(repo, base, head, "main", "HEAD")

    assert result.returncode == 1
    assert "result: not integrated" in result.stdout


def test_diff_relative_config_cannot_hide_paths(repo: Path) -> None:
    write(repo, "backend/shared.py", SHARED.replace("line 2\n", "line two\n"))
    commit(repo, "feature also edits shared")
    base, head = reviewed(repo)
    advance_main(repo, "backend/shared.py", SHARED.replace("line 29\n", "line twenty-nine\n"))
    integrate(repo)
    git(repo, "config", "diff.relative", "true")

    result = carry(repo, base, head, "main", "HEAD", cwd=repo / "docs")

    assert result.returncode == 1
    assert "result: changed" in result.stdout
    assert "  backend/shared.py" in result.stdout


def test_a_rewritten_target_branch_needs_re_review(repo: Path) -> None:
    base, head = reviewed(repo)
    git(repo, "checkout", "-q", "main")
    write(repo, "docs/guide.md", "guide, revised\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "--amend", "-m", "rewritten base")
    git(repo, "checkout", "-q", "feature")
    git(repo, "rebase", "-q", "--onto", "main", base)

    result = carry(repo, base, head, "main", "HEAD")

    assert result.returncode == 1
    assert "target branch was rewritten" in result.stdout


def test_unknown_commits_and_wrong_arguments_are_errors(repo: Path) -> None:
    base, head = reviewed(repo)

    assert carry(repo, base).returncode == 2
    assert carry(repo, base, head, "main").returncode == 2
    missing = carry(repo, base, "0" * 40, "main", "HEAD")
    assert missing.returncode == 2
    assert "not a commit" in missing.stderr
