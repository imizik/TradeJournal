"""
Webull TRADE event listener.

Architecture:
  - One JobRun row of type 'webull_listener' tracks the listener's state
    (queued/running/queued_stop/succeeded/failed). Survives uvicorn reloads
    via the orphan-cleanup pass in app/main.py.
  - run_listener(job_id) is invoked either from:
      a) the HTTP route /webull/events/start (spawns a thread — dev only), or
      b) `python -m app.jobs.run --type webull_listener` (production worker).
  - Subscribes to the Webull TRADE event service via gRPC server streaming
    (see engine.webull_events). Each received data event is routed through
    engine.webull.ingest_event() — raw save first, then normalize to Fill.

Cooperative cancel:
  - The HTTP route /webull/events/stop sets the JobRun status to 'queued_stop'.
  - The streaming subscriber polls stop_check() between every received message
    and exits cleanly. We also cancel the gRPC call as a belt-and-suspenders.

Reconnect:
  - On grpc.RpcError or other transient transport failure, the listener
    backs off and reconnects up to MAX_RECONNECTS times. AuthError /
    NumOfConnExceed / SubscribeExpired are terminal and stop the listener.

NO live trading. NO secrets logged.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime
from typing import Callable, Iterable, List, Optional

from sqlmodel import Session, select

from app.database import engine
from app.engine.webull import ingest_event, webull_configured
from app.models import JobRun

log = logging.getLogger(__name__)

# Cooperative stop / reconnect tuning
_STOP_STATUSES = {"queued_stop", "succeeded", "failed"}
_RECONNECT_BACKOFF_SECONDS = [1, 2, 5, 10, 30]
_MAX_RECONNECTS = len(_RECONNECT_BACKOFF_SECONDS)


# ---------------------------------------------------------------------------
# JobRun helpers
# ---------------------------------------------------------------------------

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


def _read_params(job_id: uuid.UUID) -> dict:
    with Session(engine) as session:
        job = session.get(JobRun, job_id)
        if job is None:
            return {}
        try:
            return json.loads(job.params_json or "{}")
        except json.JSONDecodeError:
            return {}


def _mark_running(job_id: uuid.UUID, label: str = "listening") -> None:
    with Session(engine) as session:
        job = session.get(JobRun, job_id)
        if job is None:
            return
        job.status = "running"
        job.started_at = job.started_at or datetime.utcnow()
        job.updated_at = datetime.utcnow()
        job.current = label
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
# Subscriber abstraction
# ---------------------------------------------------------------------------

SubscriberFn = Callable[
    [List[str], Callable[[dict], None], Callable[[], bool]],
    None,
]
"""
A subscriber is anything that, given (accounts, on_event, stop_check),
runs a stream and calls on_event(envelope) for every event. Tests
substitute a synchronous fake.
"""


def _default_subscriber(
    accounts: List[str],
    on_event: Callable[[dict], None],
    stop_check: Callable[[], bool],
) -> None:
    """Production subscriber — opens a real gRPC stream to events-api."""
    from app.engine.webull_events import subscribe_events
    subscribe_events(accounts=accounts, on_event=on_event, stop_check=stop_check)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def run_listener(
    job_id: uuid.UUID,
    *,
    subscriber: SubscriberFn = _default_subscriber,
    # Legacy: tests that pre-date the gRPC client inject a generator-style
    # `pull_fn` instead of a subscriber. Kept for backward compatibility.
    pull_fn: Optional[Callable[[], Iterable[dict]]] = None,
    poll_interval: float = 2.0,
    max_iterations: Optional[int] = None,
) -> int:
    """
    Run the listener loop until the JobRun row asks us to stop.

    Two execution modes:
      - **Streaming (default):** the `subscriber` is called once and yields
        events for the lifetime of the connection. This is the gRPC path.
      - **Polling (legacy):** if `pull_fn` is provided, the loop polls it
        in a sleep cycle. Reserved for tests that fake the event source as
        a list.

    Returns the number of fills successfully normalized.
    """
    if not webull_configured():
        _mark_finished(job_id, status="failed", error="WEBULL_APP_KEY/SECRET not set", enriched=0)
        return 0

    params = _read_params(job_id)
    accounts = params.get("accounts") or []
    if not accounts and pull_fn is None:
        _mark_finished(
            job_id, status="failed",
            error="No 'accounts' specified in JobRun.params_json — listener cannot subscribe",
            enriched=0,
        )
        return 0

    _mark_running(job_id)
    enriched_total = 0
    err: Optional[str] = None

    # On-event handler — shared by both modes.
    def _on_event(envelope: dict) -> None:
        nonlocal enriched_total
        try:
            with Session(engine) as session:
                result = ingest_event(envelope, session)
            label = f"{result.result}:{result.event_id or '?'}"
            enriched_delta = 1 if result.result == "normalized" else 0
            enriched_total += enriched_delta
            _bump_progress(job_id, done_delta=1, enriched_delta=enriched_delta, label=label)
        except Exception as exc:
            log.exception("Webull ingest_event raised — continuing")
            _bump_progress(
                job_id, done_delta=1, enriched_delta=0,
                label=f"ingest_error: {type(exc).__name__}",
            )

    try:
        if pull_fn is not None:
            _run_polling_loop(
                job_id, pull_fn=pull_fn, on_event=_on_event,
                poll_interval=poll_interval, max_iterations=max_iterations,
            )
        else:
            _run_streaming_loop(
                job_id, subscriber=subscriber, accounts=list(accounts),
                on_event=_on_event,
            )
    except Exception as exc:
        err = str(exc)
        log.exception("Webull listener crashed")

    final_status = "failed" if err else "succeeded"
    _mark_finished(job_id, status=final_status, error=err, enriched=enriched_total)
    return enriched_total


# ---------------------------------------------------------------------------
# Streaming loop (production)
# ---------------------------------------------------------------------------

def _run_streaming_loop(
    job_id: uuid.UUID,
    *,
    subscriber: SubscriberFn,
    accounts: List[str],
    on_event: Callable[[dict], None],
) -> None:
    """
    Open a streaming subscriber. On transient transport failure, reconnect
    with bounded backoff. Terminal server errors propagate and stop the loop.
    """
    from app.engine.webull_events import WebullEventsTerminalError  # local import to avoid grpc dep at module load

    attempts = 0
    while True:
        if _check_stop(job_id):
            return
        try:
            subscriber(accounts, on_event, lambda: _check_stop(job_id))
            # Subscriber returned cleanly (either stop_check fired or server
            # ended the stream). Don't auto-reconnect — let the operator
            # decide whether to restart.
            return
        except WebullEventsTerminalError as exc:
            log.error("Webull events terminal: %s — stopping listener", exc)
            raise
        except Exception as exc:
            attempts += 1
            # Truncate the message so it fits comfortably in JobRun.current.
            err_short = (str(exc) or type(exc).__name__).splitlines()[0][:180]
            if attempts > _MAX_RECONNECTS:
                log.error("Webull events: exceeded %d reconnects, giving up: %s", _MAX_RECONNECTS, err_short)
                raise
            backoff = _RECONNECT_BACKOFF_SECONDS[attempts - 1]
            log.warning(
                "Webull events: transport error (%s); reconnect %d/%d in %ds — %s",
                type(exc).__name__, attempts, _MAX_RECONNECTS, backoff, err_short,
            )
            _bump_progress(
                job_id, done_delta=0, enriched_delta=0,
                label=f"reconnecting ({attempts}/{_MAX_RECONNECTS}): {err_short}",
            )
            time.sleep(backoff)


# ---------------------------------------------------------------------------
# Polling loop (legacy — used only by existing/future fake tests)
# ---------------------------------------------------------------------------

def _run_polling_loop(
    job_id: uuid.UUID,
    *,
    pull_fn: Callable[[], Iterable[dict]],
    on_event: Callable[[dict], None],
    poll_interval: float,
    max_iterations: Optional[int],
) -> None:
    iterations = 0
    while True:
        if _check_stop(job_id):
            return
        try:
            events = list(pull_fn() or [])
        except Exception as exc:
            log.exception("Webull pull_fn raised — sleeping then retrying")
            _bump_progress(job_id, done_delta=0, enriched_delta=0, label=f"pull_error: {type(exc).__name__}")
            time.sleep(poll_interval)
            iterations += 1
            if max_iterations is not None and iterations >= max_iterations:
                return
            continue

        for evt in events:
            on_event(evt)

        if not events:
            time.sleep(poll_interval)
        iterations += 1
        if max_iterations is not None and iterations >= max_iterations:
            return


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------

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
