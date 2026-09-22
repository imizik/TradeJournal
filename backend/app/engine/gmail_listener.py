"""
Gmail Pub/Sub pull listener: job type ``gmail_listener`` in the ``gmail`` lane.

Gmail publishes a tiny ``{emailAddress, historyId}`` message to Pub/Sub when
the watched label changes. This process holds a StreamingPull open -- an
outbound HTTPS connection, so nothing listens on the host -- and turns each
message into one coalesced ``gmail_push`` request for the sync lane. It never
calls the Gmail API or touches token.json: Gmail work and every OAuth refresh
stay in the sync lane, and a Gmail sign-out cannot stop the listener.

Lifecycle:
  - The gmail lane worker calls ensure_listener_request() before each poll.
    With GMAIL_LISTENER_ENABLED on and configured, and no listener queued or
    running, it queues one, backing off after consecutive failures.
  - SIGTERM (job_runtime.shutdown_requested) ends it cleanly as succeeded.
    Credential and subscription errors are terminal and fail the row with an
    operator-readable message; stream errors resubscribe in place.
  - While running it heartbeats to data/gmail_listener_state.json and queues
    ``gmail_watch_renew`` in the sync lane when the watch is missing, due, or
    close to Gmail's 7-day expiry.

A message is acked only after its request is committed, so a failed commit
is redelivered. Duplicates are harmless: requests coalesce and fills dedupe.
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Callable, Protocol

from sqlmodel import Session, select

from app.database import engine
from app.engine import gmail_poller
from app.engine.job_runtime import shutdown_requested, submit_job
from app.engine.jobs import JOB_GMAIL_LISTENER, JOB_GMAIL_WATCH_RENEW, create_job, latest_job, running_job
from app.models import JobRun

log = logging.getLogger(__name__)

LISTENER_STATE_FILE = gmail_poller._BACKEND_DIR / "data" / "gmail_listener_state.json"
DEFAULT_CREDENTIALS_FILE = gmail_poller._BACKEND_DIR / "pubsub-subscriber.json"

# Delay before re-queueing after 1, 2, 3... consecutive failed listener runs.
_RESTART_BACKOFF_SECONDS = (10, 30, 120, 600, 1800)
_RESUBSCRIBE_BACKOFF_MAX_SECONDS = 300
_WATCH_RENEW_MARGIN_SECONDS = 48 * 3600
_WATCH_RETRY_SECONDS = 15 * 60
_STOP_CHECK_SECONDS = 10
_TERMINAL_ERRORS = {
    "PermissionDenied",
    "NotFound",
    "Unauthenticated",
    "InvalidArgument",
    "DefaultCredentialsError",
    "MalformedError",
    "RefreshError",
}

_logged_reason: str | None = None


def listener_enabled() -> bool:
    return os.environ.get("GMAIL_LISTENER_ENABLED", "false").strip().lower() in {"1", "true", "yes"}


def credentials_file() -> Path:
    configured = os.environ.get("GMAIL_PUBSUB_CREDENTIALS_FILE", "").strip()
    return Path(configured) if configured else DEFAULT_CREDENTIALS_FILE


def subscription_name() -> str:
    return os.environ.get("GMAIL_PUBSUB_SUBSCRIPTION", "").strip()


def listener_config_error() -> str | None:
    if not subscription_name():
        return "GMAIL_PUBSUB_SUBSCRIPTION is not set"
    if not credentials_file().is_file():
        return f"Pub/Sub credentials file not found: {credentials_file()}"
    return None


def listener_state() -> dict[str, object]:
    return gmail_poller._read_json_object(LISTENER_STATE_FILE) or {}


def ensure_listener_request(*, ignore_backoff: bool = False) -> uuid.UUID | None:
    """Queue a listener when enabled and none is queued or running."""
    global _logged_reason
    reason = None if listener_enabled() else "GMAIL_LISTENER_ENABLED is off"
    reason = reason or listener_config_error()
    if reason:
        if reason != _logged_reason:
            log.info("Gmail listener not started: %s", reason)
            _logged_reason = reason
        return None
    _logged_reason = None

    now = datetime.utcnow()
    with Session(engine) as session:
        if running_job(session, JOB_GMAIL_LISTENER) is not None:
            return None
        recent = session.exec(
            select(JobRun.status, JobRun.finished_at)
            .where(JobRun.job_type == JOB_GMAIL_LISTENER)
            .order_by(JobRun.created_at.desc())
            .limit(len(_RESTART_BACKOFF_SECONDS))
        ).all()
        failures = 0
        for status, _finished_at in recent:
            if status != "failed":
                break
            failures += 1
        if failures and not ignore_backoff and recent[0].finished_at is not None:
            delay = _RESTART_BACKOFF_SECONDS[failures - 1]
            if (now - recent[0].finished_at).total_seconds() < delay:
                return None
        job = JobRun(
            id=uuid.uuid4(),
            job_type=JOB_GMAIL_LISTENER,
            status="queued",
            params_json=json.dumps({"subscription": subscription_name()}),
            total=0,
            current="Queued Gmail notification listener",
            updated_at=now,
        )
        session.add(job)
        session.commit()
        log.info("Gmail listener queued (job_id=%s, previous failures=%d)", job.id, failures)
        return job.id


# ---------------------------------------------------------------------------
# Pub/Sub client
# ---------------------------------------------------------------------------


class PullFuture(Protocol):
    def done(self) -> bool: ...
    def result(self, timeout: float | None = None): ...
    def cancel(self) -> bool: ...


class PullClient(Protocol):
    def subscribe(self, subscription: str, callback: Callable) -> PullFuture: ...
    def close(self) -> None: ...


class _PubSubClient:
    """StreamingPull through the official client (lease renewal, reconnects)."""

    def __init__(self, credentials_path: Path):
        from google.cloud import pubsub_v1
        from google.oauth2 import service_account

        credentials = service_account.Credentials.from_service_account_file(
            str(credentials_path), scopes=["https://www.googleapis.com/auth/pubsub"]
        )
        self._flow_control = pubsub_v1.types.FlowControl(max_messages=10)
        self._client = pubsub_v1.SubscriberClient(credentials=credentials)

    def subscribe(self, subscription: str, callback: Callable) -> PullFuture:
        return self._client.subscribe(subscription, callback=callback, flow_control=self._flow_control)

    def close(self) -> None:
        self._client.close()


def decode_notification(data: bytes) -> dict[str, object]:
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"not JSON: {exc}") from exc
    if not isinstance(payload, dict) or "historyId" not in payload:
        raise ValueError("missing historyId")
    return payload


# ---------------------------------------------------------------------------
# Listener loop
# ---------------------------------------------------------------------------


class _Listener:
    def __init__(self, job_id: uuid.UUID, *, heartbeat_seconds: float):
        self.job_id = job_id
        self.heartbeat_seconds = heartbeat_seconds
        self.messages = 0
        self.state: dict[str, object] = {
            "job_id": str(job_id),
            "state": "starting",
            "started_at": int(time.time()),
            "heartbeat_at": None,
            "last_message_at": None,
            "messages": 0,
            "last_error": None,
        }
        self._last_heartbeat = 0.0
        self._last_stop_check = 0.0
        self._stopped_by_row = False

    # -- state -------------------------------------------------------------

    def write_state(self, **values: object) -> None:
        self.state.update(values, heartbeat_at=int(time.time()), messages=self.messages)
        try:
            gmail_poller.write_private_file(LISTENER_STATE_FILE, json.dumps(self.state, indent=2))
        except OSError as exc:
            log.warning("Could not write Gmail listener state: %s", exc)

    def update_row(self, **values: object) -> None:
        with Session(engine) as session:
            job = session.get(JobRun, self.job_id)
            if job is None:
                return
            for key, value in values.items():
                setattr(job, key, value)
            job.updated_at = datetime.utcnow()
            session.add(job)
            session.commit()

    def heartbeat(self, *, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_heartbeat < self.heartbeat_seconds:
            return
        self._last_heartbeat = now
        self.write_state()
        label = f"Listening for Gmail notifications ({self.messages} received)"
        self.update_row(phase="listening", done=self.messages, current=label)
        _maybe_queue_watch_renewal()

    def should_stop(self) -> bool:
        if shutdown_requested.is_set():
            return True
        now = time.monotonic()
        if now - self._last_stop_check >= _STOP_CHECK_SECONDS:
            self._last_stop_check = now
            with Session(engine) as session:
                status = session.exec(select(JobRun.status).where(JobRun.id == self.job_id)).first()
            # queued_stop is a stop request; a terminal status means recovery
            # or an operator already ended this run.
            self._stopped_by_row = status != "running"
        return self._stopped_by_row

    # -- messages ----------------------------------------------------------

    def on_message(self, message) -> None:
        try:
            payload = decode_notification(message.data)
        except ValueError as exc:
            # Acked: a poison message must not redeliver forever.
            log.warning("Ignoring malformed Gmail notification: %s", exc)
            message.ack()
            return
        try:
            from app.routers.sync import queue_gmail_push_pipeline

            with Session(engine) as session:
                queue_gmail_push_pipeline(
                    session,
                    history_id=str(payload.get("historyId")),
                    email_address=str(payload.get("emailAddress") or "") or None,
                    trigger="pubsub",
                )
        except Exception:
            log.exception("Could not queue Gmail push; Pub/Sub will redeliver")
            message.nack()
            return
        message.ack()
        self.messages += 1
        self.state["last_message_at"] = int(time.time())


def _is_terminal(exc: BaseException) -> bool:
    return isinstance(exc, (FileNotFoundError, PermissionError)) or type(exc).__name__ in _TERMINAL_ERRORS


def _wait(seconds: float) -> None:
    shutdown_requested.wait(seconds)


def run_listener(
    job_id: uuid.UUID,
    *,
    client_factory: Callable[[Path], PullClient] = _PubSubClient,
    tick_seconds: float = 2.0,
    heartbeat_seconds: float = 60.0,
) -> int:
    """Hold the subscription until shutdown; returns notifications received."""
    listener = _Listener(job_id, heartbeat_seconds=heartbeat_seconds)
    error = listener_config_error()
    if error:
        _finish(listener, "failed", error)
        return 0

    subscription = subscription_name()
    listener.update_row(phase="connecting", current="Connecting to Gmail notifications")
    backoff = 1.0
    try:
        while not listener.should_stop():
            client = future = None
            try:
                client = client_factory(credentials_file())
                future = client.subscribe(subscription, listener.on_message)
                listener.write_state(state="listening", last_error=None)
                listener.heartbeat(force=True)
                log.info("Gmail listener subscribed to %s", subscription)
                backoff = 1.0
                while not listener.should_stop():
                    if future.done():
                        future.result()
                        raise RuntimeError("Pub/Sub stream closed without an error")
                    listener.heartbeat()
                    _wait(tick_seconds)
            except Exception as exc:
                if _is_terminal(exc):
                    raise
                log.warning("Gmail listener stream error; resubscribing in %.0fs: %s", backoff, exc)
                listener.write_state(state="reconnecting", last_error=f"{type(exc).__name__}: {exc}")
                listener.update_row(phase="reconnecting", current=f"Reconnecting after {type(exc).__name__}")
                _wait(backoff)
                backoff = min(backoff * 2, _RESUBSCRIBE_BACKOFF_MAX_SECONDS)
            finally:
                if future is not None:
                    future.cancel()
                    try:
                        future.result(timeout=10)
                    except Exception:
                        pass
                if client is not None:
                    client.close()
    except Exception as exc:
        message = (
            f"{type(exc).__name__}: {exc}. Check GMAIL_PUBSUB_SUBSCRIPTION ({subscription}) and that "
            f"the key in {credentials_file()} has Pub/Sub Subscriber on it."
        )
        log.error("Gmail listener stopped: %s", message)
        _finish(listener, "failed", message)
        return listener.messages

    reason = "Stopped for shutdown" if shutdown_requested.is_set() else "Listener stopped"
    _finish(listener, "succeeded", None, current=reason)
    return listener.messages


def _finish(listener: _Listener, status: str, error: str | None, *, current: str | None = None) -> None:
    listener.write_state(state="stopped" if status == "succeeded" else "failed", last_error=error)
    now = datetime.utcnow()
    listener.update_row(
        status=status,
        phase="complete" if status == "succeeded" else "failed",
        error=error,
        current=current or error,
        done=listener.messages,
        enriched=listener.messages,
        finished_at=now,
    )


# ---------------------------------------------------------------------------
# Watch renewal scheduling (the renewal itself runs in the sync lane)
# ---------------------------------------------------------------------------


def watch_renewal_due(now: float | None = None) -> bool:
    now = time.time() if now is None else now
    state = gmail_poller.gmail_watch_state() or {}
    topic = os.environ.get("GMAIL_PUBSUB_TOPIC", "").strip()
    if state.get("topic_name") != topic:
        return True
    try:
        expires_at = int(state.get("expiration") or 0) / 1000
        registered_at = int(state.get("registered_at") or 0)
    except (TypeError, ValueError):
        return True
    interval = int(os.environ.get("GMAIL_WATCH_RENEW_SECONDS", str(24 * 3600)))
    return expires_at - now < _WATCH_RENEW_MARGIN_SECONDS or now - registered_at >= interval


def _maybe_queue_watch_renewal() -> uuid.UUID | None:
    if not os.environ.get("GMAIL_PUBSUB_TOPIC", "").strip() or not watch_renewal_due():
        return None
    with Session(engine) as session:
        if running_job(session, JOB_GMAIL_WATCH_RENEW) is not None:
            return None
        latest = latest_job(session, JOB_GMAIL_WATCH_RENEW)
        if (
            latest is not None
            and latest.status == "failed"
            and latest.finished_at is not None
            and (datetime.utcnow() - latest.finished_at).total_seconds() < _WATCH_RETRY_SECONDS
        ):
            return None
        job = create_job(session, JOB_GMAIL_WATCH_RENEW, {"source": "gmail_listener"}, total=1, current="Queued Gmail watch renewal")
    submit_job(job.id)
    log.info("Queued Gmail watch renewal (job_id=%s)", job.id)
    return job.id
