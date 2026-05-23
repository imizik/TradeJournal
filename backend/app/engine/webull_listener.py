"""
Webull TRADE event listener.

Architecture:
  - One JobRun row of type 'webull_listener' tracks the listener's state
    (queued/running/queued_stop/succeeded/failed). Survives uvicorn reloads
    via the orphan-cleanup pass in app/main.py.
  - run_listener(job_id) is invoked either from:
      a) the HTTP route /webull/events/start (spawns a thread — dev only), or
      b) `python -m app.jobs.run --type webull_listener` (production worker).
  - The actual Webull stream wire-up is intentionally a TODO. Until then the
    loop sleeps between cooperative stop checks so the surrounding job
    lifecycle code can still be exercised end-to-end.

NO live trading. NO secrets logged. Each received event is routed through
engine.webull.ingest_event(), which saves raw first and dedupes by event_id.
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime
from typing import Callable, Iterable, Optional

from sqlmodel import Session, select

from app.database import engine
from app.engine.webull import ingest_event, webull_configured
from app.models import JobRun

log = logging.getLogger(__name__)

_POLL_INTERVAL_SECONDS = 2.0
_STOP_STATUSES = {"queued_stop", "succeeded", "failed"}


def request_stop(job_id: uuid.UUID) -> bool:
    """Cooperatively ask a running listener to stop. Returns True if the row was updated."""
    with Session(engine) as session:
        job = session.get(JobRun, job_id)
        if not job or job.status not in {"queued", "running"}:
            return False
        job.status = "queued_stop"
        job.updated_at = datetime.utcnow()
        session.add(job)
        session.commit()
        return True


def _check_stop(job_id: uuid.UUID) -> bool:
    with Session(engine) as session:
        job = session.get(JobRun, job_id)
        if job is None:
            return True
        return job.status in _STOP_STATUSES


def _mark_running(job_id: uuid.UUID) -> None:
    with Session(engine) as session:
        job = session.get(JobRun, job_id)
        if job is None:
            return
        job.status = "running"
        job.started_at = job.started_at or datetime.utcnow()
        job.updated_at = datetime.utcnow()
        job.current = "listening"
        session.add(job)
        session.commit()


def _mark_finished(job_id: uuid.UUID, *, status: str, error: Optional[str], enriched: int) -> None:
    with Session(engine) as session:
        job = session.get(JobRun, job_id)
        if job is None:
            return
        job.status = status
        job.error = error
        job.enriched = enriched
        job.current = None
        job.finished_at = datetime.utcnow()
        job.updated_at = datetime.utcnow()
        session.add(job)
        session.commit()


def _bump_progress(job_id: uuid.UUID, *, done_delta: int, enriched_delta: int, label: str) -> None:
    with Session(engine) as session:
        job = session.get(JobRun, job_id)
        if job is None:
            return
        job.done = (job.done or 0) + done_delta
        job.enriched = (job.enriched or 0) + enriched_delta
        job.current = label
        job.updated_at = datetime.utcnow()
        session.add(job)
        session.commit()


# ---------------------------------------------------------------------------
# Wire-up placeholder
# ---------------------------------------------------------------------------

def _pull_events_once() -> Iterable[dict]:
    """
    TODO: Replace with the actual Webull TRADE event source (long-poll or
    websocket). Until that's wired this returns an empty iterable so the
    listener loop is a no-op heartbeat.
    """
    return []


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def run_listener(
    job_id: uuid.UUID,
    *,
    pull_fn: Callable[[], Iterable[dict]] = _pull_events_once,
    poll_interval: float = _POLL_INTERVAL_SECONDS,
    max_iterations: Optional[int] = None,
) -> int:
    """
    Run the listener loop until the JobRun row asks us to stop.

    Args:
      job_id: the JobRun row to track against.
      pull_fn: dependency-injected event source. Default is the real (TODO)
        Webull source; tests inject a fake iterable.
      poll_interval: seconds to sleep between empty polls.
      max_iterations: optional cap (for tests). None = run forever.

    Returns the number of fills successfully normalized.
    """
    if not webull_configured():
        _mark_finished(job_id, status="failed", error="WEBULL_APP_KEY/SECRET not set", enriched=0)
        return 0

    _mark_running(job_id)
    enriched_total = 0
    iterations = 0
    err: Optional[str] = None

    try:
        while True:
            if _check_stop(job_id):
                break
            try:
                events = list(pull_fn() or [])
            except Exception as exc:  # never let one pull crash the loop
                log.exception("Webull pull_fn raised — sleeping then retrying")
                _bump_progress(job_id, done_delta=0, enriched_delta=0, label=f"pull_error: {type(exc).__name__}")
                time.sleep(poll_interval)
                iterations += 1
                if max_iterations is not None and iterations >= max_iterations:
                    break
                continue

            if not events:
                time.sleep(poll_interval)
                iterations += 1
                if max_iterations is not None and iterations >= max_iterations:
                    break
                continue

            for evt in events:
                try:
                    with Session(engine) as session:
                        result = ingest_event(evt, session)
                    label = f"{result.result}:{result.event_id or '?'}"
                    enriched = 1 if result.result == "normalized" else 0
                    enriched_total += enriched
                    _bump_progress(job_id, done_delta=1, enriched_delta=enriched, label=label)
                except Exception as exc:
                    log.exception("Webull ingest_event raised — continuing")
                    _bump_progress(
                        job_id, done_delta=1, enriched_delta=0,
                        label=f"ingest_error: {type(exc).__name__}",
                    )

            iterations += 1
            if max_iterations is not None and iterations >= max_iterations:
                break

    except Exception as exc:
        err = str(exc)
        log.exception("Webull listener crashed")

    final_status = "failed" if err else "succeeded"
    _mark_finished(job_id, status=final_status, error=err, enriched=enriched_total)
    return enriched_total


def latest_listener_job(session: Session) -> Optional[JobRun]:
    return session.exec(
        select(JobRun)
        .where(JobRun.job_type == JOB_WEBULL_LISTENER)
        .order_by(JobRun.created_at.desc())
    ).first()


def running_listener_job(session: Session) -> Optional[JobRun]:
    return session.exec(
        select(JobRun)
        .where(JobRun.job_type == JOB_WEBULL_LISTENER)
        .where(JobRun.status.in_(["queued", "running", "queued_stop"]))
        .order_by(JobRun.created_at.desc())
    ).first()


# Avoid a circular import at module load: JOB_WEBULL_LISTENER lives in engine.jobs
# but engine.jobs imports nothing from this file at module level, so a top-level
# import here is safe.
from app.engine.jobs import JOB_WEBULL_LISTENER  # noqa: E402
