"""Plant failures in the owner/reviewer boundary, without real credentials."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/pr_review.py"
spec = importlib.util.spec_from_file_location("pr_review", SCRIPT)
reviewer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reviewer)


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-qb", "main")
    git(root, "config", "user.email", "test@example.com")
    git(root, "config", "user.name", "Test")
    (root / ".gitignore").write_text(".review-loop/\n.env\n")
    (root / "a.py").write_text("value = 1\n")
    (root / "CLAUDE.md").write_text("Review correctness.\n")
    git(root, "add", ".")
    git(root, "commit", "-qm", "base")
    git(root, "update-ref", "refs/remotes/origin/main", "HEAD")
    git(root, "remote", "add", "origin", "git@github.com:owner/repo.git")
    git(root, "switch", "-qc", "codex/task")
    (root / "a.py").write_text("value = 2\n")
    git(root, "commit", "-qam", "change")
    return root


@pytest.fixture
def cli(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    code = f"#!{sys.executable}\n" + '''
import json, os, pathlib, sys, time
name = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
if name == 'claude' and args[:2] == ['auth', 'status']:
    print(json.dumps({'loggedIn': os.getenv('FAKE_AUTH') != 'missing', 'authMethod': os.getenv('FAKE_AUTH', 'claude.ai'), 'apiProvider': 'firstParty'}))
elif name == 'codex' and args[:2] == ['login', 'status']:
    print('Logged in using ' + ('API key' if os.getenv('FAKE_AUTH') == 'api' else 'ChatGPT'))
else:
    prompt = sys.stdin.read()
    if os.getenv('FAKE_LIMIT'):
        print(json.dumps({'type': 'result', 'subtype': 'success', 'is_error': True, 'result': "You've hit your session limit · resets 8:40pm (America/New_York)"}))
        sys.exit(1)
    if os.getenv('FAKE_SLEEP'): time.sleep(20)
    assert os.getenv('TJ_REVIEW_ROLE') == 'reviewer'
    assert not os.getenv('ANTHROPIC_API_KEY') and not os.getenv('OPENAI_API_KEY') and not os.getenv('GH_TOKEN')
    assert not pathlib.Path('.env').exists() and not pathlib.Path('head/.env').exists()
    assert pathlib.Path('head/a.py').read_text() == 'value = 2\\n'
    assert pathlib.Path('base/a.py').read_text() == 'value = 1\\n'
    assert 'value = 2' in pathlib.Path('diff.patch').read_text()
    assert 'independent reviewer' in prompt
    result = {'verdict': os.getenv('FAKE_VERDICT', 'clean'), 'summary': 'Checked the complete diff', 'findings': []}
    if result['verdict'] == 'findings': result['findings'] = [{'priority': 'P2', 'path': 'a.py', 'line': 1, 'title': 'Incorrect value', 'body': 'Requirement says value must be one.'}]
    if os.getenv('FAKE_MALFORMED'): result.pop('summary')
    if name == 'claude':
        assert '--bare' not in args and '--restricted' in args
        assert args[args.index('--tools') + 1] == 'Read,Grep,Glob'
        print(json.dumps({'type': 'system', 'subtype': 'init'}))
        print(json.dumps({'type': 'result', 'subtype': 'success', 'is_error': False, 'permission_denials': ['Read'] if os.getenv('FAKE_DENIAL') else [], 'structured_output': result}))
    else:
        assert args[args.index('--sandbox') + 1] == 'read-only'
        pathlib.Path(args[args.index('--output-last-message') + 1]).write_text(json.dumps(result))
        print(json.dumps({'type': 'turn.failed' if os.getenv('FAKE_FAILED') else 'turn.completed'}))
'''
    for name in ("claude", "codex"):
        path = bin_dir / name
        path.write_text(code)
        path.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("ANTHROPIC_API_KEY", "do-not-send")
    monkeypatch.setenv("OPENAI_API_KEY", "do-not-send")
    monkeypatch.setenv("GH_TOKEN", "do-not-send")
    return bin_dir


def args(owner="codex", session="owner-session", **kwargs):
    return SimpleNamespace(owner=owner, session=session, base="origin/main", contract="CLAUDE.md", pr=None, **kwargs)


def state(repo):
    return reviewer.load_json(reviewer.state_path(repo))


@pytest.mark.parametrize("owner", ["codex", "claude"])
def test_both_directions_use_complete_isolated_snapshot_and_subscription(repo, cli, owner):
    (repo / ".env").write_text("SECRET=do-not-send\n")
    reviewer.review(repo, args(owner))
    receipt = state(repo)
    assert receipt["phase"] == "clean"
    assert receipt["passes"][0]["reviewer"] == ("claude" if owner == "codex" else "codex")
    reviewer.review(repo, args(owner))
    assert len(state(repo)["passes"]) == 1


@pytest.mark.parametrize("owner,setting,value", [
    ("codex", "FAKE_AUTH", "missing"), ("codex", "FAKE_AUTH", "api"),
    ("claude", "FAKE_AUTH", "api"), ("codex", "FAKE_DENIAL", "1"),
    ("codex", "FAKE_MALFORMED", "1"), ("claude", "FAKE_FAILED", "1"),
    ("codex", "FAKE_VERDICT", "incomplete"),
])
def test_missing_auth_denied_tools_invalid_and_incomplete_output_never_pass(repo, cli, monkeypatch, owner, setting, value):
    monkeypatch.setenv(setting, value)
    if setting == "FAKE_VERDICT":
        reviewer.review(repo, args(owner))
        assert state(repo)["phase"] == "attention"
    else:
        with pytest.raises(reviewer.ReviewError):
            reviewer.review(repo, args(owner))
        assert state(repo)["phase"] == "error"
    assert len(state(repo)["passes"]) == 1
    with pytest.raises(reviewer.ReviewError):
        reviewer.review(repo, args(owner))
    assert len(state(repo)["passes"]) == 1


def test_budget_exhaustion_is_terminal_and_preserves_findings(repo, cli, monkeypatch):
    monkeypatch.setenv("FAKE_VERDICT", "findings")
    for _ in range(3):
        reviewer.review(repo, args())
    assert state(repo)["phase"] == "exhausted"
    with pytest.raises(reviewer.ReviewError, match="Human intervention"):
        reviewer.review(repo, args())
    assert len(state(repo)["passes"]) == 3
    assert state(repo)["passes"][-1]["result"]["findings"]


def test_real_claude_quota_envelope_is_an_explicit_failure(repo, cli, monkeypatch):
    monkeypatch.setenv("FAKE_LIMIT", "1")
    with pytest.raises(reviewer.ReviewError, match="subscription allowance is exhausted"):
        reviewer.review(repo, args())
    assert state(repo)["phase"] == "error"
    assert "no API fallback" in state(repo)["error"]


def test_new_commit_dirty_files_and_updated_base_invalidate_receipt(repo, cli):
    reviewer.review(repo, args())
    receipt = state(repo)
    (repo / "new.py").write_text("value = 3\n")
    assert not reviewer.matches(receipt, reviewer.identity(repo, "origin/main"))
    with pytest.raises(reviewer.ReviewError, match="Commit"):
        reviewer.review(repo, args())
    git(repo, "add", "new.py")
    git(repo, "commit", "-qm", "fix")
    assert not reviewer.matches(receipt, reviewer.identity(repo, "origin/main"))
    git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    assert not reviewer.matches(receipt, reviewer.identity(repo, "origin/main"))


def test_change_during_review_cannot_return_clean(repo, monkeypatch):
    def mutate(*unused):
        (repo / "a.py").write_text("value = 9\n")
        return {"verdict": "clean", "summary": "fine", "findings": []}, "claude"
    monkeypatch.setattr(reviewer, "invoke_reviewer", mutate)
    with pytest.raises(reviewer.ReviewError, match="changed during"):
        reviewer.review(repo, args())
    assert state(repo)["phase"] == "error"


def test_another_session_cannot_take_ownership(repo):
    reviewer.owner_state(repo, "codex", "first")
    with pytest.raises(reviewer.ReviewError, match="another owning session"):
        reviewer.owner_state(repo, "codex", "second")


def test_corrupted_state_cannot_certify_readiness(repo):
    reviewer.atomic_json(reviewer.state_path(repo), {"phase": "ready", "version": 1})
    with pytest.raises(reviewer.ReviewError, match="corrupt"):
        reviewer.owner_state(repo, "codex", "owner-session")


def test_another_read_only_session_is_not_forced_to_take_over(repo):
    reviewer.owner_state(repo, "codex", "first")
    payload = {"session_id": "second", "hook_event_name": "SessionStart"}
    reviewer.hook(repo, args(), payload)
    payload["hook_event_name"] = "Stop"
    assert reviewer.hook(repo, args(), payload) == {}
    (repo / "a.py").write_text("changed by second session\n")
    with pytest.raises(reviewer.ReviewError, match="another owning session"):
        reviewer.hook(repo, args(), payload)


def test_outdated_branch_must_integrate_base_before_spending_a_pass(repo, cli):
    original_head = git(repo, "rev-parse", "HEAD")
    git(repo, "switch", "-q", "main")
    (repo / "new.py").write_text("new base contract\n")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "base advanced")
    git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    git(repo, "switch", "-q", "codex/task")
    assert git(repo, "rev-parse", "HEAD") == original_head
    with pytest.raises(reviewer.ReviewError, match="latest base"):
        reviewer.review(repo, args())
    assert state(repo)["passes"] == []


def test_hook_returns_work_to_owner_but_leaves_read_only_sessions_alone(repo):
    payload = {"session_id": "owner-session", "hook_event_name": "SessionStart"}
    reviewer.hook(repo, args(), payload)
    payload["hook_event_name"] = "Stop"
    assert reviewer.hook(repo, args(), payload) == {}
    (repo / "a.py").write_text("value = 3\n")
    feedback = reviewer.hook(repo, args(), payload)
    assert feedback["decision"] == "block"
    assert "Commit" in feedback["reason"] or "commit" in feedback["reason"]
    assert state(repo)["session"] == "owner-session"


def test_detached_start_still_enrolls_changes_after_branch_creation(repo):
    git(repo, "checkout", "-q", "--detach")
    payload = {"session_id": "owner-session", "hook_event_name": "SessionStart"}
    reviewer.hook(repo, args(), payload)
    git(repo, "switch", "-qc", "codex/from-detached")
    (repo / "a.py").write_text("value = 3\n")
    payload["hook_event_name"] = "Stop"
    assert reviewer.hook(repo, args(), payload)["decision"] == "block"
    assert state(repo)["session"] == "owner-session"


def test_contract_is_required_and_can_be_supplied_after_auto_enrollment(repo, cli):
    reviewer.owner_state(repo, "codex", "owner-session")
    a = args()
    a.contract = ""
    with pytest.raises(reviewer.ReviewError, match="agreed task requirements"):
        reviewer.review(repo, a)
    assert state(repo)["passes"] == []
    reviewer.review(repo, args())
    assert state(repo)["contract"] == "CLAUDE.md"
    with pytest.raises(reviewer.ReviewError, match="Do not change"):
        reviewer.owner_state(repo, "codex", "owner-session", contract="Different requirements")


def test_hook_terminal_failure_reports_once_then_stops(repo):
    path, s = reviewer.owner_state(repo, "codex", "owner-session")
    s.update(phase="error", error="quota exceeded")
    reviewer.save(path, s)
    payload = {"session_id": "owner-session", "hook_event_name": "Stop"}
    assert reviewer.hook(repo, args(), payload)["decision"] == "block"
    assert "decision" not in reviewer.hook(repo, args(), payload)


def test_disappeared_reviewer_is_not_success(repo):
    path, s = reviewer.owner_state(repo, "codex", "owner-session")
    s["phase"] = "reviewing"
    reviewer.save(path, s)
    reviewer.hook(repo, args(), {"session_id": "owner-session", "hook_event_name": "Stop"})
    assert state(repo)["phase"] == "error"


def test_reviewer_cannot_recursively_enroll(repo, monkeypatch):
    monkeypatch.setenv("TJ_REVIEW_ROLE", "reviewer")
    assert reviewer.hook(repo, args(), {"hook_event_name": "Stop"}) == {}
    assert state(repo) is None


def test_real_process_deadline_kills_the_review(tmp_path):
    with pytest.raises(reviewer.ReviewError, match="deadline"):
        reviewer.model_process([sys.executable, "-c", "import time; time.sleep(20)"],
                               tmp_path, os.environ, "", tmp_path, 0.1)


def test_snapshot_rejects_symlinks(repo, tmp_path):
    (repo / "escape").symlink_to("/etc/passwd")
    git(repo, "add", "escape")
    git(repo, "commit", "-qm", "unsafe link")
    with pytest.raises(reviewer.ReviewError, match="link"):
        reviewer.unpack(repo, "HEAD", tmp_path / "snapshot")


def test_fabricated_line_or_contradictory_clean_fails(tmp_path):
    (tmp_path / "head").mkdir()
    (tmp_path / "head/a.py").write_text("one line\n")
    finding = {"priority": "P1", "path": "a.py", "line": 9, "title": "issue", "body": "evidence"}
    with pytest.raises(reviewer.ReviewError, match="real reviewed"):
        reviewer.validate_result({"verdict": "findings", "summary": "bad", "findings": [finding]}, tmp_path)
    with pytest.raises(reviewer.ReviewError, match="contradicts"):
        reviewer.validate_result({"verdict": "clean", "summary": "bad", "findings": [finding]}, tmp_path)


def test_finish_refuses_head_drift_without_publishing_success(repo, cli, monkeypatch):
    reviewer.review(repo, args())
    monkeypatch.setattr(reviewer, "pr_info", lambda *a: {
        "state": "OPEN", "headRefName": "codex/task", "headRefOid": "different", "baseRefOid": "different", "number": 1,
    })
    monkeypatch.setattr(reviewer, "api", lambda *a: pytest.fail("must not publish"))
    with pytest.raises(reviewer.ReviewError, match="differs"):
        reviewer.publish(repo, args(), finish=True)


@pytest.mark.parametrize("checks", [[], [{"name": "Only one job", "bucket": "pass"}], [{"name": "Backend", "bucket": "fail"}]])
def test_missing_and_failed_ci_cannot_mark_ready(repo, monkeypatch, checks):
    monkeypatch.setattr(reviewer.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=0, stdout=json.dumps(checks)))
    with pytest.raises(reviewer.ReviewError):
        reviewer.wait_checks(repo, 1, 0)
