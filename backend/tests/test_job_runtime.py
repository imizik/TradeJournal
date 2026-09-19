"""Real process contention/restarts, with provider calls replaced by fixtures."""

import asyncio
import json
from pathlib import Path
import socket
import subprocess
import sys
import time
import uuid
from datetime import datetime
from decimal import Decimal

import pytest
from sqlmodel import Session, create_engine, select

from app.engine import job_runtime as runtime, jobs
from app.models import FILL_LIGHT, Fill, JobRun, Trade
from app.routers import sync

BACKEND = Path(__file__).resolve().parents[1]


@pytest.fixture
def database(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'jobs.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("MIGRATION_DATABASE_URL", url)
    monkeypatch.setenv("JOB_EXECUTION_MODE", "external")
    monkeypatch.setenv("JOB_LOCK_DIR", str(tmp_path / "locks"))
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND, check=True, capture_output=True)
    test_engine = create_engine(url, connect_args={"check_same_thread": False})
    for module in (runtime, jobs, sync):
        monkeypatch.setattr(module, "engine", test_engine)
    yield test_engine
    test_engine.dispose()


def create_run(database, job_type="fill_import_check", **values):
    with Session(database) as session:
        job = jobs.create_job(session, job_type, total=1)
        for key, value in values.items():
            setattr(job, key, value)
        session.add(job)
        session.commit()
        return job.id


def read_job(database, job_id):
    with Session(database) as session:
        return session.get(JobRun, job_id)


def run_python(code):
    return subprocess.run([sys.executable, "-c", code], cwd=BACKEND, capture_output=True, text=True, timeout=30)


def wait_until_inside(database, job_id, process):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if read_job(database, job_id).current == "inside test handler":
            return
        if process.poll() is not None:
            pytest.fail(str(process.communicate()))
        time.sleep(0.025)
    pytest.fail("Worker did not enter the handler")


def held_worker(job_id, gate, effects):
    code = f'''
import time, uuid
from pathlib import Path
from app.engine.job_runtime import execute_job
from app.routers import sync
original = sync._run_fill_check
def hold(session, job_id):
    with Path({str(effects)!r}).open("a") as handle:
        handle.write("executed\\n")
    sync._set_job(job_id, current="inside test handler")
    while not Path({str(gate)!r}).exists():
        time.sleep(0.025)
    return original(session, job_id)
sync._run_fill_check = hold
execute_job(uuid.UUID({str(job_id)!r}))
'''
    return subprocess.Popen([sys.executable, "-c", code], cwd=BACKEND, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def test_competing_processes_and_api_restarts_leave_live_owner_alone(database, tmp_path):
    job_id = create_run(database)
    gate, effects = tmp_path / "release", tmp_path / "effects"
    first = held_worker(job_id, gate, effects)
    second = held_worker(job_id, gate, effects)
    try:
        deadline = time.monotonic() + 15
        while read_job(database, job_id).current != "inside test handler":
            assert time.monotonic() < deadline
            time.sleep(0.025)
        owner = read_job(database, job_id).owner_id
        assert owner and read_job(database, job_id).owner_host == socket.gethostname()
        # Recovery has direct evidence that the owner is still alive, regardless
        # of how long a provider call takes or when progress last changed.
        assert runtime.recover_interrupted() == 0
        result = run_python('''
import os
from fastapi.testclient import TestClient
from app import main
# Startup data maintenance is unrelated to job ownership and must not read
# developer backup files during this test.
main._seed_and_normalize_roth_account = lambda: None
main.restore_manual_fills_from_backup = lambda session: 0
for mode in ("external", "embedded"):
    os.environ["JOB_EXECUTION_MODE"] = mode
    with TestClient(main.app) as client:
        assert client.get("/health").status_code == 200
''')
        assert result.returncode == 0, result.stderr
        job = read_job(database, job_id)
        assert (job.status, job.owner_id) == ("running", owner)
        assert effects.read_text() == "executed\n"
        gate.touch()
        for process in (first, second):
            _, stderr = process.communicate(timeout=15)
            assert process.returncode == 0, stderr
        assert read_job(database, job_id).status == "succeeded"
        # Neither a completed row nor a duplicate CLI invocation is replayed.
        runtime.execute_job(job_id)
        assert effects.read_text() == "executed\n"
    finally:
        for process in (first, second):
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=5)


def test_killed_worker_releases_lock_and_restart_runs_queued_work(database, tmp_path):
    interrupted = create_run(database)
    worker = held_worker(interrupted, tmp_path / "release", tmp_path / "effects")
    try:
        wait_until_inside(database, interrupted, worker)
        # A different sync job cannot execute while this worker owns the lane.
        queued = create_run(database)
        runtime.execute_job(queued)
        assert read_job(database, queued).status == "queued"
    finally:
        worker.kill()
        worker.communicate(timeout=5)
    result = subprocess.run(
        [sys.executable, "-m", "app.jobs.worker", "--lane", "sync", "--once"],
        cwd=BACKEND, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    failed = read_job(database, interrupted)
    assert failed.status == "failed"
    assert "partial work may be committed" in failed.error
    assert read_job(database, queued).status == "succeeded"
    assert (tmp_path / "effects").read_text() == "executed\n"


def test_external_api_commits_queue_without_spawning_thread_and_worker_consumes_it(database, monkeypatch):
    monkeypatch.setattr(runtime.threading, "Thread", lambda **_: pytest.fail("API spawned a job thread"))
    with Session(database) as session:
        result = asyncio.run(sync.run_sync_job("fill_import_check", session=session))
    job_id = uuid.UUID(result["run_id"])
    assert read_job(database, job_id).status == "queued"
    assert runtime.worker_tick("sync")
    assert read_job(database, job_id).status == "succeeded"


def test_gmail_notification_is_queued_even_when_another_sync_is_active(database):
    create_run(database)
    with Session(database) as session:
        job, queued = sync.queue_gmail_push_pipeline(session, history_id="123", email_address="fixture@example.test")
        assert queued
        assert job.status == "queued"
        assert json.loads(job.params_json)["history_id"] == "123"


def test_pipeline_children_execute_without_deadlock_and_polygon_stays_independent(database, monkeypatch):
    monkeypatch.setattr(sync, "_import_fills_from_gmail", lambda *_args, **_kwargs: {"saved": 1, "skipped": 0})
    monkeypatch.setattr(sync, "_run_trade_rebuild", lambda *_: (1, "rebuilt"))
    for attr, kind in (
        ("create_polygon_enrichment_job", "polygon_enrich"),
        ("create_alpaca_enrichment_job", "alpaca_enrich"),
        ("create_trade_path_job", "trade_path"),
    ):
        monkeypatch.setattr(sync, attr, lambda session, _kind=kind, **_: jobs.create_job(session, _kind, total=1))
    monkeypatch.setattr(jobs, "run_alpaca_enrichment_job", lambda _: 1)
    monkeypatch.setattr(jobs, "run_trade_path_job", lambda _: 1)
    monkeypatch.setattr(jobs, "run_polygon_enrichment_job", lambda _: pytest.fail("Pipeline blocked on Polygon"))
    job_id = create_run(database, "full_pipeline")
    runtime.execute_job(job_id)
    assert read_job(database, job_id).status == "succeeded"
    with Session(database) as session:
        polygon = jobs.latest_job(session, "polygon_enrich")
        assert polygon.status == "queued"
        assert jobs.latest_job(session, "alpaca_enrich").status == "succeeded"
        assert jobs.latest_job(session, "trade_path").status == "succeeded"
        assert jobs.latest_job(session, "daily_review") is None

    # A second push/pipeline does not fail just because the previous Polygon
    # request is still queued or running independently.
    next_id = create_run(database, "full_pipeline")
    runtime.execute_job(next_id)
    assert read_job(database, next_id).status == "succeeded"


def test_later_pipeline_queues_new_polygon_fills_without_repeating_active_work(database, monkeypatch):
    first_id, second_id = uuid.uuid4(), uuid.uuid4()
    pending = [first_id]
    monkeypatch.setattr(jobs, "_polygon_fill_ids", lambda *_: pending)
    with Session(database) as session:
        first = jobs.create_polygon_enrichment_job(session, reuse_active=True)
        assert jobs.create_polygon_enrichment_job(session, reuse_active=True).id == first.id
        pending.append(second_id)
        second = jobs.create_polygon_enrichment_job(session, reuse_active=True)
        assert second.id != first.id
        assert json.loads(second.params_json)["fill_ids"] == [str(second_id)]
        assert json.loads(first.params_json)["fill_ids"] == [str(first_id)]


def test_retry_after_partial_import_preserves_fill_dedupe_and_fifo(database, monkeypatch):
    from app.engine.email_parser import ParsedFill
    from app.engine import gmail_poller
    from app.routers import fills

    parsed = [
        ParsedFill("TEST", "buy", Decimal("2"), Decimal("10"), datetime(2026, 9, 1), "stock", "test-buy", "1111", "individual"),
        ParsedFill("TEST", "sell", Decimal("2"), Decimal("12"), datetime(2026, 9, 2), "stock", "test-sell", "1111", "individual"),
    ]
    monkeypatch.setattr(gmail_poller, "poll_new_fills", lambda **_: parsed)
    interrupted = create_run(database, "gmail_sync")

    def commit_then_fail():
        with Session(database) as session:
            fills._import_fills_from_gmail(session, start_enrichment=False)
        raise RuntimeError("simulated interruption after import commit")

    with pytest.raises(RuntimeError):
        runtime.execute_job(interrupted, runner=commit_then_fail)
    # Recovery never replays the interrupted row. A new explicit sync and
    # rebuild use the existing import dedupe and FIFO implementation.
    runtime.execute_job(create_run(database, "gmail_sync"))
    runtime.execute_job(create_run(database, "trade_rebuild"))
    with Session(database) as session:
        saved = session.exec(select(Fill).options(*FILL_LIGHT)).all()
        trades = session.exec(select(Trade)).all()
        assert len(saved) == 2
        assert len(trades) == 1
        assert trades[0].realized_pnl == Decimal("4")


def test_foreign_owners_and_legacy_jobs_are_not_assumed_dead(database):
    directory = str(runtime.lock_directory())
    foreign = create_run(database, status="running", owner_id="test", owner_host="another-host", owner_lock_dir=directory)
    legacy = create_run(database, status="running")
    wrong_directory = create_run(database, status="running", owner_id="test", owner_host=socket.gethostname(), owner_lock_dir="/another/location")
    assert runtime.recover_interrupted() == 0
    assert runtime.recover_interrupted(unowned=True) == 1
    assert read_job(database, legacy).status == "failed"
    assert read_job(database, foreign).status == "running"
    assert read_job(database, wrong_directory).status == "running"


def test_destructive_job_without_persisted_confirmation_does_not_delete_fills(database, monkeypatch):
    monkeypatch.setattr(sync, "_clear_derived_trade_data", lambda _: pytest.fail("Unconfirmed deletion"))
    job_id = create_run(database, "resync_all")
    runtime.execute_job(job_id)
    job = read_job(database, job_id)
    assert job.status == "failed"
    assert "no recorded database confirmation" in job.error


def test_stopping_a_queued_listener_does_not_start_it(database):
    job_id = create_run(database, "webull_listener", status="queued_stop")
    assert runtime.recover_interrupted(lane="webull") == 1
    assert read_job(database, job_id).status == "succeeded"
