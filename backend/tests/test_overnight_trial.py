"""Offline overnight integration: identity, recovery, limits and truthful reports."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import uuid

import pytest

from scripts import overnight_trial as trial


@pytest.fixture
def root(tmp_path):
    path = tmp_path / "overnight"
    receipt = trial.initialize(path)
    assert receipt["state"] == "queued", receipt.get("failure")
    return path


def test_completed_run_reuses_identity_attempt_and_exposure(root):
    before = trial.read(root / "receipt.json")
    receipt = trial.execute(root, "run")
    assert receipt["state"] == "completed", receipt.get("failure")
    assert receipt["research"]["attempt"] == 1
    assert receipt["research"]["exposures"] == 1
    assert receipt["result_summary"]["event_n"] == 7
    assert receipt["result_summary"]["uncertainty"]["unavailable_reason"] == "insufficient_weeks"
    assert receipt["coverage"]["MU"]["non_present_sessions"] == 0
    raw = (root / "research" / receipt["research"]["run_id"] / "result.json").read_bytes()
    for action in ("run", "report"):
        again = trial.execute(root, action)
        assert again["run_id"] == before["run_id"]
        assert again["research"] == receipt["research"]
        assert again["finished_at"] == receipt["finished_at"]
        assert again["history"] == receipt["history"]
    assert (root / "research" / receipt["research"]["run_id"] / "result.json").read_bytes() == raw
    report = (root / "morning.md").read_text()
    assert "invented data only" in report
    assert "No hypothesis accepted or rejected" in report
    assert "no code changes, tests or PRs produced" in report
    assert "provider calls: 0" in report
    assert receipt["usage"] == {"model_calls": 0, "tokens": 0, "api_cost_usd": 0, "provider_calls": 0}


def fail(*args, **kwargs):
    raise ValueError("invented failure")


def test_failed_work_is_not_replayed_and_retry_is_bounded_idempotent(root):
    store = trial.store_for(root)
    store.work_once(compute=fail)
    receipt = trial.execute(root, "run")
    assert receipt["state"] == "failed"
    assert receipt["research"]["attempt"] == 1
    assert "No completed result" in (root / "morning.md").read_text()
    op = str(uuid.uuid4())
    assert trial.execute(root, "retry", op)["research"]["attempt"] == 2
    assert trial.execute(root, "retry", op)["research"]["attempt"] == 2
    store.work_once(compute=fail)
    with pytest.raises(ValueError, match="budget exhausted"):
        trial.execute(root, "retry", str(uuid.uuid4()))
    assert trial.execute(root, "retry", op)["research"]["attempt"] == 2
    assert store.status(receipt["research"]["run_id"])["attempt"] == 2


def test_deadline_kills_calculation_child_and_preserves_failed_attempt(root, monkeypatch):
    store = trial.store_for(root)
    child_pids = []
    original = trial.ResearchStore._child

    def delayed(self, request, payload, run_id, worker_fd, on_started=None):
        # Real calculation subprocess, interrupted while its parent waits.
        def started():
            time.sleep(.2)
        return original(self, request, payload, run_id, worker_fd, started)

    from app.engine import research_studio_store as module
    popen = module.subprocess.Popen

    def capture(*args, **kwargs):
        process = popen(*args, **kwargs)
        child_pids.append(process)
        return process

    monkeypatch.setattr(module.subprocess, "Popen", capture)
    monkeypatch.setattr(trial.ResearchStore, "_child", delayed)
    with trial.deadline(.05):
        receipt = store.work_once()
    assert receipt["status"] == "failed"
    assert "TimeoutError" in receipt["reason"]
    assert child_pids and all(p.poll() is not None for p in child_pids)
    assert trial.execute(root, "report")["state"] == "failed"


def test_real_parent_death_recovery_never_replays(root, tmp_path):
    marker = tmp_path / "started"
    code = """
import sys, time
from pathlib import Path
from scripts.overnight_trial import store_for
def compute(*args, **kwargs):
    Path(sys.argv[2]).write_text('started')
    time.sleep(60)
store_for(Path(sys.argv[1])).work_once(compute=compute)
"""
    process = subprocess.Popen([sys.executable, "-c", code, str(root), str(marker)],
                               cwd=Path(__file__).resolve().parents[1])
    try:
        until = time.monotonic() + 10
        while not marker.exists() and time.monotonic() < until:
            time.sleep(.02)
        assert marker.exists()
        with pytest.raises(ValueError, match="already active"):
            trial.execute(root, "run")
        process.kill()
        process.wait(timeout=5)
        receipt = trial.execute(root, "run")
        assert receipt["state"] == "failed"
        assert receipt["research"]["attempt"] == 1
        assert "interrupted worker" in receipt["failure"]
        assert "result_summary" not in receipt
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)


def test_duplicate_coordinator_and_initialization_refuse(root):
    before = (root / "receipt.json").read_bytes()
    with trial.locked(root), pytest.raises(BlockingIOError):
        trial.execute(root, "run")
    with pytest.raises(FileExistsError):
        trial.initialize(root)
    assert (root / "receipt.json").read_bytes() == before


def test_rejected_retries_preserve_completed_receipt_report_and_ledger(root):
    completed = trial.execute(root, "run")
    receipt = (root / "receipt.json").read_bytes()
    report = (root / "morning.md").read_bytes()
    for operation_id in (None, "malformed", str(uuid.uuid4())):
        command = [sys.executable, trial.__file__, "retry", "--root", str(root)]
        if operation_id:
            command += ["--operation-id", operation_id]
        refused = subprocess.run(command, capture_output=True, text=True, timeout=10)
        assert refused.returncode == 2, refused.stdout + refused.stderr
        assert (root / "receipt.json").read_bytes() == receipt
        assert (root / "morning.md").read_bytes() == report
        assert trial.store_for(root).status(completed["research"]["run_id"]) == completed["research"]


def test_incomplete_initialization_and_changed_code_are_reported(tmp_path, monkeypatch):
    root = tmp_path / "broken"
    monkeypatch.setattr(trial, "seed", fail)
    receipt = trial.initialize(root)
    assert receipt["state"] == "failed"
    assert trial.execute(root, "run")["state"] == "failed"
    assert "No completed result" in (root / "morning.md").read_text()


def test_code_drift_does_not_execute_old_request(root, monkeypatch):
    monkeypatch.setattr(trial, "code_identity", lambda: "changed")
    receipt = trial.execute(root, "run")
    assert receipt["state"] == "failed"
    assert "trial code changed" in receipt["failure"]
    assert trial.store_for(root).status(receipt["research"]["run_id"])["status"] == "queued"


def test_modified_result_never_appears_successful(root):
    receipt = trial.execute(root, "run")
    path = root / "research" / receipt["research"]["run_id"] / "result.json"
    path.write_text('{}')
    receipt = trial.execute(root, "report")
    assert receipt["state"] == "failed"
    assert "result_summary" not in receipt
    assert "No completed result" in (root / "morning.md").read_text()


def test_root_and_store_redirection_refuse(root, tmp_path):
    # The platform temp path may include /var -> /private/var on macOS.
    platform_path = Path(tempfile.gettempdir()) / ("trial-" + str(uuid.uuid4()))
    assert trial.root_path(platform_path) == platform_path.resolve()
    with pytest.raises(ValueError, match="temporary"):
        trial.root_path(Path.home() / "research")
    alias = tmp_path / "alias"
    alias.symlink_to(root, target_is_directory=True)
    with pytest.raises(ValueError, match="symlinks"):
        trial.root_path(alias)
    research = root / "research"
    research.rename(root / "saved")
    research.symlink_to(root / "saved", target_is_directory=True)
    with pytest.raises(ValueError, match="inside"):
        trial.store_for(root)


def test_cli_failure_exit_and_no_external_environment_usage(tmp_path):
    root = tmp_path / "cli"
    script = Path(trial.__file__)
    env = dict(os.environ, DATABASE_URL="postgresql://invalid.invalid/forbidden",
               ALPACA_API_KEY="fixture-must-not-be-used", ANTHROPIC_API_KEY="fixture-must-not-be-used")
    init = subprocess.run([sys.executable, str(script), "init", "--root", str(root)],
                          env=env, capture_output=True, text=True, timeout=15)
    assert init.returncode == 0, init.stderr
    receipt = json.loads((root / "receipt.json").read_text())
    trial.store_for(root).work_once(compute=fail)
    run = subprocess.run([sys.executable, str(script), "run", "--root", str(root)],
                         env=env, capture_output=True, text=True, timeout=15)
    assert run.returncode == 1
    assert json.loads(run.stdout)["run_id"] == receipt["run_id"]
