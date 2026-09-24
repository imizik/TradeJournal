"""One plain-language answer to "are new Robinhood fills arriving?".

Read by GET /gmail/health, which the frontend polls for its status banner and
deploy/alerts.py turns into a phone alert.
It reads local state files and a few indexed rows; it never calls Google.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

from sqlalchemy import func
from sqlmodel import Session, select

from app.engine import gmail_poller
from app.engine.gmail_listener import listener_config_error, listener_enabled, listener_state
from app.engine.jobs import JOB_GMAIL_LISTENER
from app.models import Fill, JobRun

# The listener heartbeats every minute.
_HEARTBEAT_STALE_SECONDS = 3 * 60
_HEARTBEAT_DEAD_SECONDS = 10 * 60
_WATCH_WARNING_SECONDS = 48 * 3600
# Jobs whose completion can change fills or trades on screen.
_DATA_JOB_TYPES = ("gmail_push", "trade_rebuild", "full_pipeline", "resync_all")


def _iso(epoch: float | int | None) -> str | None:
    if not epoch:
        return None
    return datetime.fromtimestamp(float(epoch), tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _utc_iso(value: datetime | None) -> str | None:
    return value.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z") if value else None


def _data_version(session: Session) -> str:
    fill_count, latest_fill = session.exec(select(func.count(Fill.id), func.max(Fill.executed_at))).one()
    latest_job = session.exec(
        select(func.max(JobRun.finished_at)).where(JobRun.job_type.in_(_DATA_JOB_TYPES), JobRun.status == "succeeded")
    ).one()
    return f"{fill_count}:{latest_fill}:{latest_job}"


def gmail_health(session: Session) -> dict[str, object]:
    now = time.time()
    auth = gmail_poller.gmail_auth_state() or {}
    watch = gmail_poller.gmail_watch_state() or {}
    state = listener_state()
    row = session.exec(
        select(JobRun).where(JobRun.job_type == JOB_GMAIL_LISTENER).order_by(JobRun.created_at.desc()).limit(1)
    ).first()
    try:
        watch_expires = int(watch.get("expiration") or 0) / 1000 or None
    except (TypeError, ValueError):
        watch_expires = None
    heartbeat = state.get("heartbeat_at") if isinstance(state.get("heartbeat_at"), (int, float)) else None

    status, message, action = "live", "Live: new Robinhood fills import within seconds.", None
    if not gmail_poller.TOKEN_FILE.exists() or auth.get("status") == "needs_reconnect":
        status, action = "down", "reconnect_gmail"
        message = "Gmail is disconnected, so new Robinhood fills can't be imported. Reconnect Gmail."
    elif not listener_enabled():
        status, message = "off", "Real-time Gmail sync is off; fills arrive with the next scheduled check."
    elif (config_error := listener_config_error()) is not None:
        status, message = "down", f"Real-time Gmail sync is misconfigured: {config_error}."
    elif row is None or row.status == "queued":
        status, message = "degraded", "Real-time Gmail sync is starting."
    elif row.status == "failed":
        status = "down"
        message = f"Real-time Gmail sync stopped and will retry automatically: {row.error or 'unknown error'}"
    elif heartbeat is None or now - heartbeat > _HEARTBEAT_DEAD_SECONDS:
        status, message = "down", "Real-time Gmail sync is not responding."
    elif state.get("state") == "reconnecting" or now - heartbeat > _HEARTBEAT_STALE_SECONDS:
        status, message = "degraded", "Real-time Gmail sync is reconnecting to Google."
    elif watch_expires is None or watch_expires < now:
        status, message = "degraded", "Waiting for Gmail to confirm notifications."
    elif watch_expires - now < _WATCH_WARNING_SECONDS:
        status, message = "degraded", "Gmail notifications expire soon and renewal is failing."

    return {
        "status": status,
        "message": message,
        "action": action,
        "listener_enabled": listener_enabled(),
        "listener_status": row.status if row else None,
        "listener_error": row.error if row and row.status == "failed" else None,
        "heartbeat_at": _iso(heartbeat),
        "last_notification_at": _iso(state.get("last_message_at")),  # type: ignore[arg-type]
        "notifications_received": state.get("messages"),
        "watch_expires_at": _iso(watch_expires),
        "auth_status": "needs_reconnect" if action else auth.get("status", "unknown"),
        "last_import_at": _utc_iso(
            session.exec(
                select(func.max(JobRun.finished_at)).where(
                    JobRun.job_type.in_(("gmail_push", "gmail_sync", "full_pipeline")), JobRun.status == "succeeded"
                )
            ).one()
        ),
        "data_version": _data_version(session),
    }
