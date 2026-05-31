"""
Webull OpenAPI HTTP routes.

Phase 1 — read/listen/import only. No live trading.

Endpoints:
  GET  /webull/health
  GET  /webull/accounts
  GET  /webull/orders/recent
  GET  /webull/orders/{order_id}
  POST /webull/events/test-ingest
  POST /webull/events/start
  POST /webull/events/stop
  GET  /webull/events/status

The long-running listener should run as `python -m app.jobs.run --type webull_listener`
in production. /events/start spawns a dev convenience thread; the JobRun row is
the source of truth either way.
"""

from __future__ import annotations

import logging
import threading
import uuid
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.database import get_session
from app.engine.jobs import (
    JOB_WEBULL_LISTENER,
    create_webull_listener_job,
    job_status,
    latest_job,
    running_job,
)
from app.engine.webull import (
    WEBULL_ALLOW_TEST_INGEST,
    resolve_local_webull_accounts,
    WebullClientError,
    get_order_detail_remote,
    health_check,
    ingest_event,
    list_accounts_remote,
    list_recent_orders_remote,
    webull_configured,
)
from app.engine.webull_listener import request_stop, run_listener
from app.models import Account, JobRun, WebullRawEvent

log = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Health + accounts
# ---------------------------------------------------------------------------

@router.get("/health")
def webull_health() -> dict[str, Any]:
    """Configured + reachable check. Never returns secret material."""
    return health_check()


@router.get("/accounts")
def webull_accounts(session: Session = Depends(get_session)) -> dict[str, Any]:
    """
    Returns:
      - local: Account rows we've already created for broker='webull'
      - remote: live Webull account list (best-effort; 501 if endpoint not yet wired)
    """
    local_rows = session.exec(
        select(Account).where(Account.broker == "webull")
    ).all()
    local = [
        {
            "id": str(a.id),
            "name": a.name,
            "type": a.type,
            "last4": a.last4,
            "broker_account_id": a.broker_account_id,
        }
        for a in local_rows
    ]

    remote: list[dict[str, Any]] = []
    remote_error: str | None = None
    try:
        remote = list_accounts_remote()
    except WebullClientError as exc:
        remote_error = str(exc)

    return {"local": local, "remote": remote, "remote_error": remote_error}


# ---------------------------------------------------------------------------
# Orders (best-effort wrappers)
# ---------------------------------------------------------------------------

@router.get("/orders/recent")
def webull_recent_orders(account_id: str, limit: int = 50) -> dict[str, Any]:
    if not webull_configured():
        raise HTTPException(status_code=400, detail="Webull credentials are not configured")
    try:
        return {"orders": list_recent_orders_remote(account_id, limit=limit)}
    except WebullClientError as exc:
        raise HTTPException(status_code=501, detail=str(exc))


@router.get("/orders/{order_id}")
def webull_order_detail(order_id: str, account_id: str) -> dict[str, Any]:
    if not webull_configured():
        raise HTTPException(status_code=400, detail="Webull credentials are not configured")
    try:
        return get_order_detail_remote(account_id, order_id)
    except WebullClientError as exc:
        raise HTTPException(status_code=501, detail=str(exc))


# ---------------------------------------------------------------------------
# Event ingest
# ---------------------------------------------------------------------------

@router.post("/events/test-ingest")
def webull_test_ingest(
    event: dict[str, Any] = Body(...),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """
    Dev workhorse: paste one Webull TRADE event JSON and route it through the
    normal ingest pipeline. Gated by WEBULL_ALLOW_TEST_INGEST so production
    deploys can disable arbitrary writes.
    """
    if not WEBULL_ALLOW_TEST_INGEST:
        raise HTTPException(status_code=403, detail="Test ingest is disabled (WEBULL_ALLOW_TEST_INGEST=false)")
    result = ingest_event(event, session)
    return result.to_dict()


# ---------------------------------------------------------------------------
# Listener control
# ---------------------------------------------------------------------------

def _spawn_listener_thread(job_id: uuid.UUID) -> None:
    """Dev-only convenience. Production should run the CLI worker instead."""
    thread = threading.Thread(target=run_listener, args=(job_id,), daemon=True, name=f"webull-listener-{job_id}")
    thread.start()


class _StartEventsRequest(BaseModel):
    accounts: list[str] | None = None  # Webull broker_account_id list to subscribe


@router.post("/events/start")
def webull_events_start(
    body: _StartEventsRequest | None = Body(default=None),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    if not webull_configured():
        raise HTTPException(status_code=400, detail="Webull credentials are not configured")

    existing = running_job(session, JOB_WEBULL_LISTENER)
    if existing is not None:
        return {
            "started": False,
            "reason": "already_running",
            "status": job_status(existing),
        }

    # Resolve account list: explicit body > all local Webull accounts.
    accounts: list[str] = list(body.accounts) if (body and body.accounts) else resolve_local_webull_accounts(session)
    if not accounts:
        raise HTTPException(
            status_code=400,
            detail="No Webull accounts to subscribe to. Provide {'accounts': [...]} or seed an Account row first.",
        )

    job = create_webull_listener_job(session, accounts=accounts)
    _spawn_listener_thread(job.id)
    log.info("Webull listener started (job_id=%s, accounts=%d)", job.id, len(accounts))
    return {"started": True, "accounts": accounts, "status": job_status(job)}


@router.post("/events/stop")
def webull_events_stop(session: Session = Depends(get_session)) -> dict[str, Any]:
    existing = running_job(session, JOB_WEBULL_LISTENER)
    if existing is None:
        return {"stopped": False, "reason": "not_running"}
    ok = request_stop(existing.id)
    return {"stopped": ok, "job_id": str(existing.id)}


@router.get("/events/status")
def webull_events_status(session: Session = Depends(get_session)) -> dict[str, Any]:
    job = latest_job(session, JOB_WEBULL_LISTENER)
    raw_total = session.exec(select(WebullRawEvent.event_id)).all()
    fills_normalized = session.exec(
        select(WebullRawEvent.event_id).where(WebullRawEvent.fill_id != None)  # noqa: E711
    ).all()
    return {
        "job": job_status(job),
        "raw_event_count": len(raw_total),
        "normalized_fill_count": len(fills_normalized),
    }
