"""Open-trade phone alerts for one trade (give-back, last-day expiry, and the plan pings), and the
one-tap plan link page's data; see app/engine/position_alerts.py and app/engine/plan_nudges.py."""

import time
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.database import get_session
from app.engine import notification_policy, plan_nudges, position_alerts
from app.models import Trade

router = APIRouter()


@router.get("/{trade_id}/phone-alerts")
def trade_alerts(trade_id: uuid.UUID, db: Session = Depends(get_session)):
    trade = db.get(Trade, trade_id)
    if trade is None:
        raise HTTPException(404, "That trade is no longer in the journal.")
    body = position_alerts.for_trade(db, trade)
    body["alerts"] = notification_policy.annotate(db, sorted(body["alerts"] + plan_nudges.for_trade(db, trade), key=lambda a: a["detected_at"]))
    return body


@router.get("/{trade_id}/plan-link")
def plan_link(trade_id: uuid.UUID, db: Session = Depends(get_session)):
    """What the link ping opens: the position and the plans suggested for it. Linking is the capture link route."""
    trade = db.get(Trade, trade_id)
    body = plan_nudges.link_page(db, trade, time.time()) if trade is not None else None
    if body is None:
        raise HTTPException(404, "That trade is no longer in the journal.")
    return body
