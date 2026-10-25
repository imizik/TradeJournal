"""A confirmed copilot plan's time stop: preview the owner's words, save it, and list an investigation's.

``engine/plan_time_stops.py`` judges and sends them, only while
``PLAN_TIME_STOPS_ENABLED=true``; these routes work either way and say which.
"""

import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlmodel import Session

from app.ai import copilot
from app.database import get_session
from app.engine import plan_time_stops

router = APIRouter()


def _enabled():
    if not copilot.settings().enabled:
        raise HTTPException(503, "Copilot Lab is off.")


def _calendar():
    from app.engine.chart_calendar import chart_calendar
    return chart_calendar


class TimeStopCreate(BaseModel):
    client_id: str = Field(min_length=8, max_length=80)
    investigation_id: str
    symbol: str = Field(pattern=r"^[A-Z][A-Z0-9.\-]{0,9}$")
    text: str = Field(min_length=1, max_length=80)

    @field_validator("investigation_id")
    @classmethod
    def a_real_investigation(cls, value: str) -> str:
        return str(uuid.UUID(value))


@router.get("/time-stops/preview")
def preview(text: str = Query(..., max_length=80)):
    """When the owner's words would ping, for the plan card before Confirm."""
    _enabled()
    return {**plan_time_stops.parse(text, time.time(), _calendar()), "enabled": plan_time_stops.enabled()}


@router.post("/time-stops", status_code=201)
def create(body: TimeStopCreate, db: Session = Depends(get_session)):
    _enabled()
    try:
        plan_time_stops.create(db, client_id=body.client_id, investigation_id=body.investigation_id, symbol=body.symbol,
                               text=body.text, now=time.time(), calendar=_calendar())
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    return {"time_stops": plan_time_stops.rows(db, body.investigation_id), "enabled": plan_time_stops.enabled()}


@router.get("/time-stops")
def listing(investigation: uuid.UUID, db: Session = Depends(get_session)):
    _enabled()
    return {"time_stops": plan_time_stops.rows(db, str(investigation)), "enabled": plan_time_stops.enabled()}
