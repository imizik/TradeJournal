from datetime import date, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Session

from app.database import get_session
from app.engine import day_journal

router = APIRouter()


class EntryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_id: str = Field(min_length=1, max_length=100)
    kind: Literal["outlook", "update", "idea", "reflection", "decision"]
    text: str = Field(min_length=1, max_length=day_journal.MAX_TEXT)
    symbol: str | None = Field(default=None, max_length=16)
    not_traded: bool = False


class EntryResponse(BaseModel):
    id: str
    operation_id: str
    day: str
    kind: str
    text: str
    symbol: str | None
    not_traded: bool
    created_at: str
    actor: str


def _serialize(row):
    created = row.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return {"id": str(row.id), "operation_id": row.operation_id, "day": row.day.isoformat(), "kind": row.kind,
            "text": row.text, "symbol": row.symbol, "not_traded": row.not_traded,
            "created_at": created.isoformat().replace("+00:00", "Z"), "actor": "owner"}


@router.get("/{day}")
def get_day_journal(day: date, session: Session = Depends(get_session)):
    from app.ai import daily_review_service, review_context

    trade_ids = daily_review_service.day_trade_ids(session, day)
    trades, _ = daily_review_service.load_trades(session, trade_ids)
    return {"day": day.isoformat(), "entries": [_serialize(row) for row in day_journal.entries(session, day)],
            "trade_plans": review_context.plans(session, day, trades)}


@router.post("/{day}/entries", response_model=EntryResponse)
def create_day_entry(day: date, body: EntryCreate, session: Session = Depends(get_session)):
    try:
        row = day_journal.append(session, day=day, operation_id=body.operation_id, kind=body.kind,
                                 text=body.text, symbol=body.symbol, not_traded=body.not_traded)
    except day_journal.EntryConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except day_journal.EntryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _serialize(row)
