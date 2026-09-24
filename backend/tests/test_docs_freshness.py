"""The documentation drift pass, overdue.

`test_docs_links.py` catches a document naming a file that no longer exists.
Nothing catches the other half -- a sentence that is still well-formed and no
longer true -- because that needs judgement, and judgement only happens when
something asks for it. Nothing did: `roadmap.md` described Neon as hosting the
database for the whole of the week after the VPS cutover, and deployment as
"deliberately unspecified" while six systemd services were running.

So this asks. It counts the commits that touched code since the last recorded
reconciliation, and fails once that number passes a threshold. The fix is the
pass itself -- `.claude/skills/docs-drift/SKILL.md` -- followed by writing the
commit reconciled to into `docs/agent/last-reconciled.json`.

What it cannot check is that the pass actually happened: nothing stops someone
editing the marker and moving on. It is a prompt at the right moment, not a
proof. The commit range it hands over is what makes the pass cheap enough to
do rather than skip.

Doc-only commits do not count. Reconciling documentation would otherwise start
its own clock, and a week of prose edits would demand another pass.
"""

from __future__ import annotations

import json
import subprocess
from datetime import date
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MARKER = REPO_ROOT / "docs" / "agent" / "last-reconciled.json"
SKILL = ".claude/skills/docs-drift/SKILL.md"

# Roughly a week of this repository's traffic (67 code commits in the 30 days
# before this was written). Long enough that an ordinary pull request never
# trips it, short enough that a reconciliation covers a range someone can still
# remember. Raise it if it fires on noise; do not delete it.
THRESHOLD = 30


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True
    )


def code_commits_since(sha: str) -> int:
    """Non-merge commits since `sha` that touched something other than Markdown."""
    result = _git(
        "rev-list", "--count", "--no-merges", f"{sha}..HEAD",
        "--", ".", ":(exclude)*.md",
    )
    if result.returncode != 0:
        raise RuntimeError(f"git rev-list failed: {result.stderr.strip()}")
    return int(result.stdout.strip())


def _history_reaches(sha: str) -> bool:
    """Whether this checkout has the marker commit and descends from it.

    A shallow clone (`actions/checkout` fetches one commit by default) does
    not, which is why the backend CI job asks for full history. A branch cut
    before the marker does not either.
    """
    if _git("cat-file", "-e", f"{sha}^{{commit}}").returncode != 0:
        return False
    return _git("merge-base", "--is-ancestor", sha, "HEAD").returncode == 0


def test_the_drift_pass_is_not_overdue() -> None:
    marker = json.loads(MARKER.read_text(encoding="utf-8"))
    sha = marker["commit"]

    if not _history_reaches(sha):
        pytest.skip(
            f"{sha} is not in this checkout's history (shallow clone, or a "
            f"branch cut before it) -- nothing to count against"
        )

    behind = code_commits_since(sha)
    assert behind <= THRESHOLD, (
        f"{behind} code commits have landed since documentation was last "
        f"reconciled at {sha} ({marker['date']}); the threshold is "
        f"{THRESHOLD}.\n\n"
        f"Run the drift pass -- {SKILL} -- over that range:\n"
        f"    git log --oneline {sha}..HEAD\n"
        f"    git diff --stat {sha}..HEAD\n\n"
        f"Then record what you reconciled to in "
        f"{MARKER.relative_to(REPO_ROOT)}:\n"
        f'    {{"commit": "<sha>", "date": "<YYYY-MM-DD>", "note": "..."}}\n\n'
        f"Bumping the marker without reading the documents is the one thing "
        f"this check cannot detect, and the only way it stops working."
    )


def test_the_marker_is_shaped_the_way_the_failure_message_says() -> None:
    """A malformed marker would skip the check silently rather than fail it."""
    marker = json.loads(MARKER.read_text(encoding="utf-8"))
    assert set(marker) >= {"commit", "date", "note"}, marker
    assert len(marker["commit"]) >= 7, "a short sha collides sooner than it looks"
    date.fromisoformat(marker["date"])


# --- the check catches what it claims to -------------------------------------


def test_counting_ignores_merges_and_documentation(tmp_path: Path) -> None:
    """Built as a real repository: the pathspec and --no-merges are git's, not
    ours, and a hand-rolled fake would be testing the fake."""
    repo = tmp_path / "repo"
    repo.mkdir()

    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)

    git("init", "-q", "-b", "main")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "t")

    def commit(name: str) -> str:
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(name, encoding="utf-8")
        git("add", name)
        git("commit", "-qm", name)
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True
        ).stdout.strip()

    base = commit("base.py")
    commit("docs.md")          # documentation only -- must not count
    commit("app.py")           # code -- must count
    commit("nested/thing.md")  # documentation at depth -- must not count

    counted = subprocess.run(
        ["git", "rev-list", "--count", "--no-merges", f"{base}..HEAD",
         "--", ".", ":(exclude)*.md"],
        cwd=repo, capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert counted == "1", "doc-only commits must not start the clock"


def test_a_marker_this_checkout_does_not_have_is_not_counted() -> None:
    assert not _history_reaches("0" * 40)
    assert _history_reaches(
        _git("rev-parse", "HEAD").stdout.strip()
    ), "HEAD must always be reachable, or every run would skip"
