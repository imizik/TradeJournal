"""Navigation documents that name a file or a heading which no longer exists.

The mechanical half of documentation rot. A renamed module leaves every
sentence about it well-formed, and a retitled heading silently turns every link
to it into a scroll to the top of the page -- which for an agent following
`domain-rules.md#known-same-timestamp-ordering-is-arbitrary` means landing
nowhere and reading whatever happens to be there.

What this does NOT catch is the other half: a claim that is still well-formed
and no longer true -- a stale rate, a decision still labelled open, a command
whose flags changed. None of the four documents fixed in #34 would have failed
here, and adding checks until they did would be fitting the test to one
afternoon's mistakes. That pass is judgement;
`.claude/skills/docs-drift/SKILL.md` is how to run it.

Scope is the **navigation surface**: Markdown at the repository root plus
`docs/agent/`. Those are the documents that tell a reader where to look, so a
name that does not resolve is a dead end. Plan and contract documents
elsewhere under `docs/` are excluded on purpose -- naming a file that does not
exist yet is what a plan is for, and `tradingview-signal-loop-plan.md` names
several.

Within that scope the universe comes from git, not a list here: a document
added to `docs/agent/` tomorrow is covered without anyone remembering it.

Lives in `backend/tests/` because that is where pytest runs; it is about the
repository, not the backend.
"""

from __future__ import annotations

import re
import subprocess
from functools import lru_cache
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# feature-map.md: "Backend paths are relative to backend/, frontend paths to
# frontend/." A path may be written from any of these roots.
PREFIXES = ("", "backend/", "frontend/")

_EXTENSIONS = re.compile(
    r"\.(py|md|sh|ps1|ts|tsx|js|jsx|json|jsonl|ya?ml|toml|example|txt|db|csv|xlsx|ini|cfg)$"
)
_BACKTICKED = re.compile(r"`([^`\n]+)`")
_MD_LINK = re.compile(r"\]\(([^)\s]+)\)")
_NOT_IN_A_PATH = set(" \t\"'{}()[]|<>=,:;&%!?@\\")


@lru_cache(maxsize=1)
def _tracked() -> tuple[frozenset[str], frozenset[str]]:
    """(every tracked path, every tracked basename), straight from git."""
    listed = subprocess.run(
        ["git", "ls-files"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    ).stdout.split()
    assert listed, "git listed no files; every check here would pass vacuously"
    return frozenset(listed), frozenset(Path(p).name for p in listed)


def documents() -> list[Path]:
    """The navigation surface: root Markdown plus docs/agent/."""
    tracked, _ = _tracked()
    docs = sorted(
        REPO_ROOT / name
        for name in tracked
        if name.endswith(".md") and ("/" not in name or name.startswith("docs/agent/"))
    )
    assert docs, "found no navigation documents; the check would pass vacuously"
    return docs


def _looks_like_a_path(token: str) -> bool:
    """Whether a backticked token is claiming to name a file in this repository.

    Prose, routes, URLs, timezones and dotted module names are not paths. A
    slashed token counts only when its first segment is a real directory here,
    which is what separates `backend/data/polygon_cache/` from `America/New_York`.
    """
    if not token or token.startswith(("http", "/", "-", "$", "#", "~")):
        return False
    if _NOT_IN_A_PATH & set(token):
        return False
    if "/" in token:
        head = token.split("/")[0]
        return any((REPO_ROOT / prefix / head).exists() for prefix in PREFIXES)
    return bool(_EXTENSIONS.search(token))


def _resolves(token: str) -> bool:
    _, basenames = _tracked()
    token = token.rstrip("/")
    for prefix in PREFIXES:
        candidate = prefix + token
        if "*" in candidate:
            if next(REPO_ROOT.glob(candidate), None) is not None:
                return True
        elif (REPO_ROOT / candidate).exists():
            return True
    # Documents name files by bare name all the time ("see `verify.sh`", which
    # lives in scripts/). The reader resolves that by name, so this does too.
    return "/" not in token and token in basenames


def _deliberately_ignored(token: str) -> bool:
    """True when git says the path is gitignored, so its absence is by design.

    Generated caches and per-machine env files are named in the docs on purpose
    and never tracked. Asking git beats keeping an exception list here, which
    would go stale exactly the way the documents do.

    Each candidate is asked twice, bare and with a trailing slash. Most ignore
    patterns here are directory-only (`.venv/`, `backend/data/`), and git will
    not treat a path it cannot see on disk as a directory -- so the bare form
    of an absent directory comes back "not ignored". That is how this shipped
    green locally, where `backend/.venv` exists, and failed in CI, where it
    does not.
    """
    bare = [prefix + token.rstrip("/") for prefix in PREFIXES]
    candidates = bare + [c + "/" for c in bare]
    result = subprocess.run(
        ["git", "check-ignore", "--stdin"],
        cwd=REPO_ROOT, input="\n".join(candidates), capture_output=True, text=True,
    )
    if result.returncode not in (0, 1):
        raise RuntimeError(f"git check-ignore failed: {result.stderr.strip()}")
    return bool(result.stdout.strip())


def missing_paths(text: str) -> list[str]:
    """Paths a document names that neither exist nor are deliberately ignored."""
    tokens = {t for t in _BACKTICKED.findall(text) if _looks_like_a_path(t)}
    unresolved = sorted(t for t in tokens if not _resolves(t))
    return [t for t in unresolved if not _deliberately_ignored(t)]


def _headings(markdown: str) -> set[str]:
    """GitHub's anchor slug for every heading.

    GitHub replaces each space with a hyphen rather than collapsing runs, so
    "Phase 3 - Environments" (em dash) slugs with a double hyphen once the dash
    is stripped. Collapsing here would accept anchors GitHub rejects.
    """
    slugs = set()
    for heading in re.findall(r"^#{1,6}\s+(.+?)\s*$", markdown, re.M):
        slug = re.sub(r"[^\w\s-]", "", heading.strip().lower())
        slugs.add(re.sub(r"\s", "-", slug))
    return slugs


def broken_links(doc: Path, text: str) -> list[str]:
    """Relative links to a document that is missing, or to a heading that is."""
    broken = []
    for target in _MD_LINK.findall(text):
        if target.startswith(("http", "/", "#", "mailto")):
            continue
        path_part, _, anchor = target.partition("#")
        resolved = (doc.parent / path_part).resolve() if path_part else doc
        if not resolved.exists():
            broken.append(f"{doc.name} -> {target} (no such file)")
        elif anchor and anchor not in _headings(resolved.read_text(encoding="utf-8")):
            broken.append(f"{doc.name} -> {target} (no such heading)")
    return broken


# --- the real documents ------------------------------------------------------


@pytest.mark.parametrize("doc", documents(), ids=lambda d: str(d.relative_to(REPO_ROOT)))
def test_every_path_a_document_names_exists(doc: Path) -> None:
    missing = missing_paths(doc.read_text(encoding="utf-8"))
    assert not missing, (
        f"{doc.relative_to(REPO_ROOT)} names paths that neither exist nor are "
        f"gitignored: {missing}\nRename or drop the reference -- a document "
        f"pointing at a moved file sends the next reader nowhere."
    )


@pytest.mark.parametrize("doc", documents(), ids=lambda d: str(d.relative_to(REPO_ROOT)))
def test_every_cross_document_link_and_anchor_resolves(doc: Path) -> None:
    broken = broken_links(doc, doc.read_text(encoding="utf-8"))
    assert not broken, (
        "broken links:\n  " + "\n  ".join(broken)
        + "\nA link to a retitled heading does not error -- it lands at the top "
          "of the page and the reader gets the wrong section."
    )


def test_the_scope_covers_the_documents_agents_are_told_to_read() -> None:
    """CLAUDE.md sends agents to these five; none may fall out of scope silently."""
    covered = {d.relative_to(REPO_ROOT).as_posix() for d in documents()}
    for required in (
        "README.md", "CLAUDE.md", "AGENTS.md",
        "docs/agent/architecture.md", "docs/agent/domain-rules.md",
        "docs/agent/verification.md", "docs/agent/environments.md",
        "docs/agent/feature-map.md", "docs/agent/roadmap.md",
    ):
        assert required in covered, f"{required} is not being checked"


# --- the checks catch what they claim to -------------------------------------
#
# A checker that passes over clean documents proves nothing about a dirty one.


def test_a_path_that_does_not_exist_is_reported() -> None:
    assert missing_paths("see `backend/app/engine/nonexistent_module.py`") == [
        "backend/app/engine/nonexistent_module.py"
    ]
    assert missing_paths("see `test_nothing_like_this.py`") == ["test_nothing_like_this.py"]


def test_a_path_written_relative_to_backend_resolves() -> None:
    # feature-map.md writes them this way; flagging it would make the check
    # unusable on the document it matters most for.
    assert missing_paths("start at `app/engine/reconstructor.py`") == []


def test_a_bare_filename_resolves_by_name() -> None:
    # "see `verification.md`" and "`test_scalper.py` covers it" are how these
    # documents actually refer to files.
    assert missing_paths("see `verify.sh` and `test_scalper.py`") == []


def test_a_glob_resolves_when_something_matches_and_not_otherwise() -> None:
    assert missing_paths("`app/engine/webull*.py`") == []
    assert missing_paths("`app/engine/nosuchprefix*.py`") == ["app/engine/nosuchprefix*.py"]


def test_a_gitignored_path_is_not_reported() -> None:
    # Named in feature-map.md on purpose; never tracked.
    assert missing_paths("caches live at `backend/data/polygon_cache/`") == []


def test_an_absent_gitignored_directory_is_still_recognised() -> None:
    """The path used here cannot exist on any machine, so this exercises the
    absent-directory branch everywhere rather than only where it is missing.

    `.venv/` and `backend/data/` are directory-only patterns. Asking git about
    the bare name of a directory that is not on disk answers "not ignored",
    because git cannot know it is a directory -- so environments.md's
    `backend/.venv` (in a sentence about it *not existing yet*) read as a
    broken reference on a machine without one. Every developer has the
    directory; CI does not.
    """
    # Both unanchored directory patterns, so they hold at any depth.
    assert _deliberately_ignored("backend/nowhere-in-particular/.venv")
    assert _deliberately_ignored("backend/nowhere-in-particular/node_modules")
    # Still says no to something genuinely unignored, or it would pass everything.
    assert not _deliberately_ignored("backend/nowhere-in-particular/app.py")
    # And path-anchored patterns stay anchored: backend/data/ is ignored,
    # a `data` directory somewhere else is not.
    assert _deliberately_ignored("backend/data")
    assert not _deliberately_ignored("backend/nowhere-in-particular/data")


def test_things_that_are_not_paths_are_left_alone() -> None:
    assert missing_paths(
        "`GET /health`, `app.engine.jobs`, `http://localhost:8080`, "
        "`America/New_York`, `next/font`, `attr_delta/gamma/theta`"
    ) == []


def test_a_link_to_a_missing_document_is_reported(tmp_path: Path) -> None:
    doc = tmp_path / "a.md"
    doc.write_text("see [gone](gone.md)", encoding="utf-8")
    assert broken_links(doc, doc.read_text()) == ["a.md -> gone.md (no such file)"]


def test_a_link_to_a_missing_heading_is_reported(tmp_path: Path) -> None:
    (tmp_path / "b.md").write_text("# Real Heading\n", encoding="utf-8")
    doc = tmp_path / "a.md"
    doc.write_text("[x](b.md#retitled-heading) and [y](b.md#real-heading)", encoding="utf-8")
    assert broken_links(doc, doc.read_text()) == ["a.md -> b.md#retitled-heading (no such heading)"]


def test_anchor_slugs_match_the_headings_this_repo_actually_links_to() -> None:
    slugs = _headings(
        "### Known: same-timestamp ordering is arbitrary\n"
        "## Two rules every check must satisfy\n"
        "## Phase 3 — Environments\n"
    )
    assert "known-same-timestamp-ordering-is-arbitrary" in slugs
    assert "two-rules-every-check-must-satisfy" in slugs
    # The em dash is stripped, leaving both of its spaces: a double hyphen.
    assert "phase-3--environments" in slugs
