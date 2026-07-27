"""Authenticated webhook-only ingestion for TradingView live alerts."""

from __future__ import annotations

import logging
import os
import secrets
from collections.abc import Callable

from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Query,
    Request,
)
from pydantic import BaseModel
from sqlmodel import Session

from app.engine.tradingview import (
    MAX_ALERT_BODY_BYTES,
    TradingViewContractError,
    parse_alert_bytes,
)
from app.engine.tradingview_alerts import (
    TradingViewAlertCollisionError,
    TradingViewPersistenceBusyError,
    TradingViewPersistenceError,
    persist_alert,
)
from app.tradingview_database import get_tradingview_session_factory


log = logging.getLogger(__name__)
router = APIRouter()

MIN_WEBHOOK_TOKEN_BYTES = 32
RETRY_AFTER_SECONDS = 2


class TradingViewWebhookReceipt(BaseModel):
    accepted: bool
    dup: bool
    alert_id: str
    analysis_status: str


def _configured_webhook_token() -> str:
    return os.getenv("TRADINGVIEW_WEBHOOK_TOKEN", "").strip()


def _bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, separator, credential = authorization.partition(" ")
    if not separator or scheme.lower() != "bearer":
        return None
    token = credential.strip()
    return token or None


def _constant_time_match(expected: str, candidate: str | None) -> bool:
    candidate_bytes = (candidate or "").encode("utf-8")
    return secrets.compare_digest(
        expected.encode("utf-8"),
        candidate_bytes,
    )


async def verify_tradingview_webhook(
    token: str | None = Query(default=None),
    authorization: str | None = Header(default=None),
) -> None:
    """Fail closed before request streaming or database-session acquisition."""

    expected = _configured_webhook_token()
    if len(expected.encode("utf-8")) < MIN_WEBHOOK_TOKEN_BYTES:
        raise HTTPException(
            status_code=503,
            detail="TradingView webhook is disabled",
        )
    bearer = _bearer_token(authorization)
    query_matches = _constant_time_match(expected, token)
    bearer_matches = _constant_time_match(expected, bearer)
    if not query_matches and not bearer_matches:
        raise HTTPException(
            status_code=401,
            detail="Invalid TradingView webhook token",
        )


def _authenticated_session_factory(
    _verified: None = Depends(verify_tradingview_webhook),
    session_factory: Callable[[], Session] = Depends(
        get_tradingview_session_factory
    ),
) -> Callable[[], Session]:
    # Auth is resolved before returning a lazy constructor. The handler does
    # not open the session until the bounded body passes the frozen parser.
    return session_factory


async def _read_bounded_body(request: Request) -> bytes:
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            declared_size = int(declared)
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail="Invalid Content-Length header",
            ) from exc
        if declared_size < 0:
            raise HTTPException(
                status_code=400,
                detail="Invalid Content-Length header",
            )
        if declared_size > MAX_ALERT_BODY_BYTES:
            raise HTTPException(
                status_code=413,
                detail=(
                    "TradingView alert body exceeds "
                    f"{MAX_ALERT_BODY_BYTES} bytes"
                ),
            )

    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        if not chunk:
            continue
        total += len(chunk)
        if total > MAX_ALERT_BODY_BYTES:
            raise HTTPException(
                status_code=413,
                detail=(
                    "TradingView alert body exceeds "
                    f"{MAX_ALERT_BODY_BYTES} bytes"
                ),
            )
        chunks.append(chunk)
    return b"".join(chunks)


@router.post(
    "/webhook",
    response_model=TradingViewWebhookReceipt,
)
async def tradingview_webhook(
    request: Request,
    session_factory: Callable[[], Session] = Depends(
        _authenticated_session_factory
    ),
) -> TradingViewWebhookReceipt:
    raw_body = await _read_bounded_body(request)
    try:
        parsed = parse_alert_bytes(raw_body)
    except TradingViewContractError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    with session_factory() as session:
        try:
            result = persist_alert(session, parsed, raw_body)
        except TradingViewAlertCollisionError as exc:
            raise HTTPException(
                status_code=409,
                detail="TradingView alert identity collision",
            ) from exc
        except TradingViewPersistenceBusyError as exc:
            raise HTTPException(
                status_code=503,
                detail="TradingView alert persistence is temporarily busy",
                headers={"Retry-After": str(RETRY_AFTER_SECONDS)},
            ) from exc
        except TradingViewPersistenceError as exc:
            log.error(
                "TradingView persistence rejected validated alert "
                "(alert_id=%s error_type=%s)",
                parsed.alert_id,
                type(exc).__name__,
            )
            raise HTTPException(
                status_code=500,
                detail="Unable to persist TradingView alert",
            ) from exc
        except Exception as exc:
            # Do not stringify SQL/driver exceptions: bound parameters can
            # include the immutable raw payload.
            log.error(
                "TradingView persistence failed "
                "(alert_id=%s error_type=%s)",
                parsed.alert_id,
                type(exc).__name__,
            )
            raise HTTPException(
                status_code=500,
                detail="Unable to persist TradingView alert",
            ) from exc
        duplicate = result.duplicate
        alert_id = result.alert.alert_id
        status = result.alert.analysis_status

    return TradingViewWebhookReceipt(
        accepted=True,
        dup=duplicate,
        alert_id=alert_id,
        analysis_status=status,
    )
