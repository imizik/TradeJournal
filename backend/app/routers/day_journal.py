from datetime import date, timezone
import time
from typing import Literal
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Session

from app.database import get_session
from app.engine import day_journal, hold_check_ins
from app.engine.chart_journal import contract_label

router = APIRouter()


class CheckIn(BaseModel):
    """The ping card's Keep holding: ping again after ``minutes`` if the pinged position is still open
    (``engine/hold_check_ins.py``). One ping: an open-trade alert or a fill-time pattern interrupt."""
    model_config = ConfigDict(extra="forbid")
    minutes: Literal[15, 30]
    alert: uuid.UUID | None = None
    interrupt: uuid.UUID | None = None


class EntryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_id: str = Field(min_length=1, max_length=100)
    kind: Literal["outlook", "update", "idea", "reflection", "decision", "horizon", "plan_ask", "plan_done", "follow"]
    text: str = Field(min_length=1, max_length=day_journal.MAX_TEXT)
    symbol: str | None = Field(default=None, max_length=16)
    not_traded: bool = False
    check_in: CheckIn | None = None


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
    from app.engine import trade_notes
    # Notes he wrote on the desk about a trade with no plan (a plan's own notes show under the plan).
    notes = trade_notes.anchored_only(session, [trade.id for trade in trades])
    return {"day": day.isoformat(), "entries": [_serialize(row) for row in day_journal.entries(session, day)],
            "trade_plans": review_context.plans(session, day, trades),
            "trade_notes": [{"trade_id": str(trade.id), "contract": contract_label(trade.ticker, trade.instrument_type, trade.option_type,
                                                                                trade.strike, trade.expiration), "notes": notes[str(trade.id)]}
                            for trade in trades if str(trade.id) in notes]}


@router.post("/{day}/entries", response_model=EntryResponse)
def create_day_entry(day: date, body: EntryCreate, session: Session = Depends(get_session)):
    context = None
    if body.check_in is not None:
        found = body.check_in
        if body.kind != "decision" or not body.symbol or (found.alert is None) == (found.interrupt is None):
            raise HTTPException(status_code=422, detail="A check-in rides on a decision with a symbol and names one alert or interrupt")
        context = hold_check_ins.context(found.minutes, found.alert, found.interrupt, time.time())
    try:
        row = day_journal.append(session, day=day, operation_id=body.operation_id, kind=body.kind,
                                 text=body.text, symbol=body.symbol, not_traded=body.not_traded, context=context)
    except day_journal.EntryConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except day_journal.EntryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _serialize(row)
