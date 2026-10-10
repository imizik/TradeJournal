"""Private level alerts on the chart (Charts C5.1): list, create, re-arm and remove.

The monitor in the API process (``engine/level_alert_monitor.py``) judges them;
these routes only change rows and tell it to reload.
"""

import math
import re
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlmodel import Session, delete

from app.database import get_session
from app.engine import ntfy
from app.engine.level_alert_monitor import alert_rows, create_alert, rearm_alert
from app.models import LevelAlert, LevelAlertEvent

router = APIRouter()
SYMBOL = re.compile(r"^[A-Z][A-Z0-9./-]{0,14}$")


class AlertCreate(BaseModel):
    symbol: str = Field(max_length=15)
    price: float
    reference: float  # the chart's latest price: which side the alert waits on
    condition: str
    interval: str | None = None
    session: str = "regular"
    source_kind: str = Field(pattern="^(level|drawing|auto)$")
    source_id: str | None = Field(default=None, max_length=80)
    label: str = Field(default="", max_length=120)


class AlertRearm(BaseModel):
    price: float  # on today's basis
    reference: float


def _positive(*values: float) -> None:
    if not all(math.isfinite(value) and value > 0 for value in values):
        raise HTTPException(422, "Prices must be positive numbers.")


def listing(db: Session) -> dict:
    return {"alerts": alert_rows(db), "phone": ntfy.configured()}


def _changed(request: Request) -> None:
    monitor = getattr(request.app.state, "level_alerts", None)
    if monitor is not None:
        monitor.changed()


@router.get("/alerts")
def list_alerts(db: Session = Depends(get_session)):
    return listing(db)


@router.post("/alerts")
def add_alert(body: AlertCreate, request: Request, db: Session = Depends(get_session)):
    symbol = body.symbol.strip().upper()
    if not SYMBOL.fullmatch(symbol):
        raise HTTPException(422, "Use a US stock or ETF ticker.")
    _positive(body.price, body.reference)
    try:
        create_alert(db, symbol=symbol, price=body.price, reference=body.reference, condition=body.condition, interval=body.interval,
                     session=body.session, source_kind=body.source_kind, source_id=body.source_id, label=body.label.strip(), now=time.time())
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None
    _changed(request)
    return listing(db)


@router.post("/alerts/{alert_id}/rearm")
def rearm(alert_id: uuid.UUID, body: AlertRearm, request: Request, db: Session = Depends(get_session)):
    _positive(body.price, body.reference)
    alert = db.get(LevelAlert, alert_id)
    if alert is None:
        raise HTTPException(404, "That alert no longer exists.")
    try:
        rearm_alert(db, alert, price=body.price, reference=body.reference, now=time.time())
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None
    _changed(request)
    return listing(db)


@router.delete("/alerts/{alert_id}")
def remove(alert_id: uuid.UUID, request: Request, db: Session = Depends(get_session)):
    # Explicitly, rather than by the foreign key's cascade, which SQLite enforces only when asked.
    db.exec(delete(LevelAlertEvent).where(LevelAlertEvent.alert_id == alert_id))
    db.exec(delete(LevelAlert).where(LevelAlert.id == alert_id))
    db.commit()
    _changed(request)
    return listing(db)
