"""Private read API for persisted TradingView live alerts."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import json
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlmodel import Session

from app.database import get_session
from app.engine.tradingview_alerts import (
    TradingViewPersistenceError,
    deserialize_snapshot,
    get_alert,
    list_alerts,
)
from app.models import TradingViewAlert


router = APIRouter()
AnalysisStatus = Literal["pending", "running", "done", "skipped", "error"]


class TradingViewAlertListOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    alert_id: str
    contract_version: int
    parser_revision: str
    indicator_version: str
    content_sha256: str
    raw_payload_sha256: str
    symbol: str
    timeframe: str
    setup: str
    side: str
    price: Decimal
    bar_time_ms: int
    bar_time: datetime
    received_at: datetime
    updated_at: datetime
    analysis_status: AnalysisStatus
    analysis_attempts: int
    analysis_started_at: datetime | None
    analysis_completed_at: datetime | None
    scorer_revision: str | None
    verdict: str | None
    confidence: str | None
    analysis_error_code: str | None


class TradingViewSnapshotValueOut(BaseModel):
    type: Literal["null", "boolean", "string", "number"]
    value: bool | str | None


class TradingViewAlertDetailOut(TradingViewAlertListOut):
    payload_json: str
    levels: dict[str, TradingViewSnapshotValueOut]
    context: dict[str, TradingViewSnapshotValueOut]
    assessment: dict[str, Any] | None
    analysis_error: str | None


def _decode_object(value: str, *, label: str) -> dict[str, Any]:
    try:
        decoded = json.loads(value)
    except (TypeError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Stored TradingView {label} is invalid",
        ) from exc
    if not isinstance(decoded, dict):
        raise HTTPException(
            status_code=500,
            detail=f"Stored TradingView {label} is invalid",
        )
    return decoded


def _decode_snapshot(
    value: str,
    *,
    label: str,
) -> dict[str, TradingViewSnapshotValueOut]:
    try:
        decoded = deserialize_snapshot(value)
    except (
        TypeError,
        ValueError,
        json.JSONDecodeError,
        TradingViewPersistenceError,
    ) as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Stored TradingView {label} is invalid",
        ) from exc
    tagged: dict[str, TradingViewSnapshotValueOut] = {}
    for key, item in decoded.items():
        if item is None:
            tagged[key] = TradingViewSnapshotValueOut(
                type="null",
                value=None,
            )
        elif isinstance(item, bool):
            tagged[key] = TradingViewSnapshotValueOut(
                type="boolean",
                value=item,
            )
        elif isinstance(item, Decimal):
            tagged[key] = TradingViewSnapshotValueOut(
                type="number",
                value=format(item, "f"),
            )
        else:
            tagged[key] = TradingViewSnapshotValueOut(
                type="string",
                value=item,
            )
    return tagged


def _detail_out(row: TradingViewAlert) -> TradingViewAlertDetailOut:
    summary = TradingViewAlertListOut.model_validate(row)
    assessment = (
        _decode_object(row.assessment_json, label="assessment")
        if row.assessment_json is not None
        else None
    )
    return TradingViewAlertDetailOut(
        **summary.model_dump(),
        payload_json=row.payload_json,
        levels=_decode_snapshot(row.levels_json, label="levels"),
        context=_decode_snapshot(row.context_json, label="context"),
        assessment=assessment,
        analysis_error=row.analysis_error,
    )


@router.get(
    "/alerts",
    response_model=list[TradingViewAlertListOut],
)
async def read_tradingview_alerts(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    symbol: str | None = Query(default=None),
    setup: str | None = Query(default=None),
    analysis_status: AnalysisStatus | None = Query(default=None),
    session: Session = Depends(get_session),
) -> list[TradingViewAlertListOut]:
    try:
        rows = list_alerts(
            session,
            limit=limit,
            offset=offset,
            symbol=symbol,
            setup=setup,
            analysis_status=analysis_status,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return [
        TradingViewAlertListOut.model_validate(row)
        for row in rows
    ]


@router.get(
    "/alerts/{alert_id}",
    response_model=TradingViewAlertDetailOut,
)
async def read_tradingview_alert_detail(
    alert_id: str,
    session: Session = Depends(get_session),
) -> TradingViewAlertDetailOut:
    row = get_alert(session, alert_id)
    if row is None:
        raise HTTPException(
            status_code=404,
            detail="TradingView alert not found",
        )
    return _detail_out(row)
