"""Single-host job execution shared by the API and supervised workers.

The database is the queue. A kernel lock covers the *whole* execution, including
provider calls and commits, so a paused worker cannot be mistaken for a dead one.
All processes using a database must share JOB_LOCK_DIR on the same local disk.
Do not unlink lock files: doing so could create two locks for the same job.
"""

from __future__ import annotations

import fcntl
import hashlib
import logging
import os
import socket
import threading
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime
from pathlib import Path

from sqlalchemy import update
from sqlmodel import Session, select

from app.database import engine
from app.models import JobRun

log = logging.getLogger(__name__)
LANES = ("sync", "polygon", "webull")
_current_lane: ContextVar[str | None] = ContextVar("job_lane", default=None)


def execution_mode() -> str:
    mode = os.environ.get("JOB_EXECUTION_MODE", "embedded")
    if mode not in {"embedded", "external"}:
        raise ValueError("JOB_EXECUTION_MODE must be embedded or external")
    return mode


def lock_directory(db_engine=None) -> Path:
    db_engine = db_engine if db_engine is not None else engine
    configured = os.environ.get("JOB_LOCK_DIR")
    if execution_mode() == "external" and not configured:
        raise ValueError("External job execution requires a shared absolute JOB_LOCK_DIR")
    root = Path(configured) if configured else Path(__file__).resolve().parents[2] / "data" / "job-locks"
    if not root.is_absolute():
        raise ValueError("JOB_LOCK_DIR must be an absolute path")
    # Credentials and driver choice do not change the database's identity.
    url = db_engine.url
    database = str(Path(url.database).resolve()) if url.get_backend_name() == "sqlite" and url.database else url.database
    identity = repr((url.get_backend_name(), url.host, url.port, database))
    directory = root.resolve() / hashlib.sha256(identity.encode()).hexdigest()[:24]
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def job_lane(job_type: str) -> str:
    return {"polygon_enrich": "polygon", "webull_listener": "webull"}.get(job_type, "sync")


def _lane_filter(lane: str):
    if lane == "sync":
        return JobRun.job_type.notin_(["polygon_enrich", "webull_listener"])
    if lane not in LANES:
        raise ValueError(f"Unknown job lane: {lane}")
    return JobRun.job_type == {"polygon": "polygon_enrich", "webull": "webull_listener"}[lane]


def in_sync_worker() -> bool:
    return _current_lane.get() == "sync"


@contextmanager
def _lock(directory: Path, name: str):
    with (directory / f"{name}.lock").open("a+b") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


@contextmanager
def _lane_lock(directory: Path, lane: str):
    # Pipeline children run synchronously while their parent retains the lane.
    if _current_lane.get() == lane:
        yield True
        return
    with _lock(directory, f"lane-{lane}") as acquired:
        token = _current_lane.set(lane) if acquired else None
        try:
            yield acquired
        finally:
            if token is not None:
                _current_lane.reset(token)


def _fail(session: Session, job: JobRun, message: str) -> None:
    job.status = "failed"
    job.phase = "failed"
    job.error = message
    job.current = message
    job.wait_provider = job.wait_reason = None
    job.wait_until = None
    job.finished_at = job.updated_at = datetime.utcnow()
    session.add(job)
    session.commit()


def recover_interrupted(*, lane: str | None = None, unowned: bool = False, db_engine=None) -> int:
    """Fail dead owners, never replay effects. Queued jobs are left runnable.

    Legacy rows without ownership require an explicit operator recovery after
    stopping old executors. Foreign hosts/lock directories are never reclaimed.
    """
    db_engine = db_engine if db_engine is not None else engine
    directory = lock_directory(db_engine)
    recovered = 0
    with Session(db_engine) as session:
        # params_json can contain thousands of fill IDs. Idle polling only
        # needs ownership metadata, especially when the database meters egress.
        query = select(JobRun.id, JobRun.owner_id, JobRun.owner_host, JobRun.owner_lock_dir, JobRun.status).where(
            JobRun.status.in_(["running", "queued_stop"])
        )
        if lane is not None:
            query = query.where(_lane_filter(lane))
        candidates = session.exec(query).all()
        for candidate in candidates:
            if candidate.owner_id:
                if candidate.owner_host != socket.gethostname() or candidate.owner_lock_dir != str(directory):
                    continue
            elif not unowned:
                # A stop request for an unclaimed listener is safe to cancel.
                if candidate.status != "queued_stop":
                    continue
            with _lock(directory, f"job-{candidate.id}") as acquired:
                if not acquired:
                    continue
                candidate = session.get(JobRun, candidate.id)
                if candidate is None:
                    continue
                if candidate.status not in {"running", "queued_stop"}:
                    continue
                if candidate.status == "queued_stop":
                    candidate.status = "succeeded"
                    candidate.phase = "complete"
                    candidate.current = "Listener stopped"
                    candidate.finished_at = candidate.updated_at = datetime.utcnow()
                    session.add(candidate)
                    session.commit()
                else:
                    _fail(session, candidate, "Worker interrupted; partial work may be committed. Review and start a new run.")
                recovered += 1
    return recovered


def _dispatch(job: JobRun) -> int:
    if job.job_type == "webull_listener":
        from app.engine.webull_listener import _run_listener
        return _run_listener(job.id)
    if job.job_type in {"polygon_enrich", "alpaca_enrich", "trade_path"}:
        from app.engine.jobs import _run_job
        return _run_job(job.id)
    from app.routers.sync import execute_sync_job
    execute_sync_job(job)
    return 0


def execute_job(job_id: uuid.UUID, *, runner=None, db_engine=None) -> int:
    """Claim a queued row once. Duplicate invocations have no side effects."""
    db_engine = db_engine if db_engine is not None else engine
    directory = lock_directory(db_engine)
    with Session(db_engine) as session:
        job_type = session.exec(select(JobRun.job_type).where(JobRun.id == job_id)).first()
        if job_type is None:
            raise ValueError(f"Job not found: {job_id}")
        lane = job_lane(job_type)
    with _lane_lock(directory, lane) as lane_acquired:
        if not lane_acquired:
            return 0
        with _lock(directory, f"job-{job_id}") as acquired:
            if not acquired:
                return 0
            with Session(db_engine) as session:
                now = datetime.utcnow()
                result = session.execute(
                    update(JobRun).where(JobRun.id == job_id, JobRun.status == "queued").values(
                        status="running", phase="starting", started_at=now, updated_at=now,
                        owner_id=f"{os.getpid()}:{uuid.uuid4()}", owner_host=socket.gethostname(),
                        owner_lock_dir=str(directory), error=None,
                    )
                )
                session.commit()
                if result.rowcount != 1:
                    return 0
                job = session.get(JobRun, job_id)
            try:
                return runner() if runner is not None else _dispatch(job)
            except Exception as exc:
                with Session(db_engine) as session:
                    _fail(session, session.get(JobRun, job_id), str(exc))
                raise
            finally:
                # A handler must leave a terminal state, even on an early return.
                # SIGKILL bypasses this; recovery on the next worker tick handles it.
                with Session(db_engine) as session:
                    job = session.get(JobRun, job_id)
                    if job.status in {"running", "queued_stop"}:
                        _fail(session, job, "Worker exited without completing the job; review before retrying.")


def submit_job(job_id: uuid.UUID) -> None:
    """Rows are already committed; external mode leaves them for the worker."""
    lock_directory()  # Validate deployment configuration before accepting work.
    if execution_mode() == "external":
        return

    def run() -> None:
        # Another sync can own the lane; retain queued work until it is free.
        while True:
            try:
                execute_job(job_id)
                with Session(engine) as session:
                    status = session.exec(select(JobRun.status).where(JobRun.id == job_id)).first()
                    if status != "queued":
                        return
            except Exception:
                log.exception("Job execution failed: %s", job_id)
                return
            threading.Event().wait(1)

    threading.Thread(target=run, daemon=True, name=f"job-{job_id}").start()


def resume_embedded_jobs() -> None:
    lock_directory()
    if execution_mode() != "embedded":
        return
    recover_interrupted()
    with Session(engine) as session:
        ids = session.exec(select(JobRun.id).where(JobRun.status == "queued").order_by(JobRun.created_at)).all()
    for job_id in ids:
        submit_job(job_id)


def worker_tick(lane: str) -> bool:
    recover_interrupted(lane=lane)
    with Session(engine) as session:
        job_id = session.exec(
            select(JobRun.id).where(JobRun.status == "queued", _lane_filter(lane)).order_by(JobRun.created_at).limit(1)
        ).first()
    if job_id is None:
        return False
    execute_job(job_id)
    return True
