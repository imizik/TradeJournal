"""Open-trade phone alerts for one trade (give-back and last-day expiry); see app/engine/position_alerts.py."""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.database import get_session
from app.engine import position_alerts
from app.models import Trade

router = APIRouter()


@router.get("/{trade_id}/phone-alerts")
def trade_alerts(trade_id: uuid.UUID, db: Session = Depends(get_session)):
    trade = db.get(Trade, trade_id)
    if trade is None:
        raise HTTPException(404, "That trade is no longer in the journal.")
    return position_alerts.for_trade(db, trade)
