"""A1 immutable Practice decisions; records are always drafts and unarmed."""
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Session

from app.database import get_session
from app.engine import decisions
from app.engine.analyzer import build_ticker_analysis
from app.engine.chart_calendar import chart_calendar
from app.engine.chart_math import ET

router = APIRouter()


class DecisionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_id: str = Field(min_length=1, max_length=128)
    opportunity_id: str = Field(min_length=1, max_length=128)
    actor: str = Field(min_length=1, max_length=128)
    decision: str
    symbol: str = Field(min_length=1, max_length=15)
    context_id: str
    plan: dict | None = None
    rationale: str = Field(default="", max_length=2000)
    wait_condition: str | None = Field(default=None, max_length=500)
    wait_expiry: str | None = None


class ContextCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_id: str = Field(min_length=1, max_length=128)


@router.post("/context/{symbol}")
def context(symbol: str, body: ContextCreate, db: Session = Depends(get_session)):
    """Return the current bounded ticker packet for a decision opportunity."""
    try:
        previous = decisions.saved_context(db, body.operation_id, symbol)
    except decisions.DecisionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if previous:
        return decisions.context_row(*previous)
    try:
        packet = build_ticker_analysis(symbol)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError:
        # An explicit unavailable context still lets a person record WAIT/SKIP
        # with an honest gap; it has no facts capable of validating a TAKE.
        packet = {"symbol": symbol.strip().upper(), "generated_at": None,
                  "data_source": "unavailable", "missing": ["market context unavailable"],
                  "recent_minute_bars": [], "context_error": "market provider unavailable"}
    session_day = datetime.now(ET).date()
    session = chart_calendar.hours(session_day)
    packet["session_calendar"] = session or {
        "date": session_day.isoformat(), "status": "unavailable", "open": None,
        "close": None, "description": "Market calendar unavailable", "source": None,
    }
    try:
        item, evidence = decisions.freeze_context(db, body.operation_id, symbol, packet)
    except decisions.DecisionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return decisions.context_row(item, evidence)


@router.post("", status_code=201)
def create(body: DecisionCreate, response: Response, db: Session = Depends(get_session)):
    try:
        item, created = decisions.create(db, body.model_dump())
    except decisions.DecisionError as exc:
        raise HTTPException(status_code=409 if "operation_id" in str(exc) else 422, detail=str(exc)) from exc
    response.status_code = 201 if created else 200
    return decisions.row(item)


@router.get("")
def list_decisions(limit: int = Query(30, ge=1, le=100), db: Session = Depends(get_session)):
    return {"decisions": [decisions.row(item) for item in decisions.recent(db, limit)]}


@router.get("/{record_id}")
def get_decision(record_id: uuid.UUID, db: Session = Depends(get_session)):
    item = decisions.get(db, record_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Decision record not found")
    return decisions.row(item)
