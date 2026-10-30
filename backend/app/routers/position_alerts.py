"""Open-trade phone alerts for one trade (give-back, last-day expiry, and the plan pings), and the
one-tap plan link page's data, and fill-time pattern interrupts; see app/engine/position_alerts.py,
app/engine/plan_nudges.py and app/engine/fill_interrupts.py."""

import time
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Session

from app.database import get_session
from app.engine import alert_feedback, fill_interrupts, notification_policy, outcomes, plan_nudges, position_alerts
from app.models import Trade

router = APIRouter()


class FeedbackBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rating: Literal["prompted_review", "already_aware", "too_late", "not_useful"]
    reason: str | None = Field(default=None, max_length=500)
    base_version: int = Field(ge=0, strict=True)


@router.put("/{trade_id}/phone-alerts/{alert_id}/feedback")
def save_feedback(trade_id: uuid.UUID, alert_id: uuid.UUID, body: FeedbackBody, db: Session = Depends(get_session)):
    """Owner-only via the route boundary; bind to the position's current source identity."""
    trade = db.get(Trade, trade_id)
    if trade is None:
        raise HTTPException(404, "That trade is no longer in the journal.")
    alert = next((a for a in position_alerts.for_trade(db, trade)["alerts"] if a["id"] == str(alert_id)), None)
    if alert is None:
        raise HTTPException(404, "This alert is unavailable for this position.")
    if alert["delivery"] not in alert_feedback.ELIGIBLE_DELIVERIES:
        raise HTTPException(409, "Feedback is only available for sent or delivery-unconfirmed position alerts.")
    return alert_feedback.save(db, alert_id, body.rating, body.reason, body.base_version)


@router.get("/{trade_id}/phone-alerts")
def trade_alerts(trade_id: uuid.UUID, db: Session = Depends(get_session)):
    trade = db.get(Trade, trade_id)
    if trade is None:
        raise HTTPException(404, "That trade is no longer in the journal.")
    body = position_alerts.for_trade(db, trade)
    body["alerts"] = outcomes.annotate(db, notification_policy.annotate(
        db, sorted(body["alerts"] + plan_nudges.for_trade(db, trade), key=lambda a: a["detected_at"])))
    return body


@router.get("/{trade_id}/plan-link")
def plan_link(trade_id: uuid.UUID, db: Session = Depends(get_session)):
    """What the link ping opens: the position and the plans suggested for it. Linking is the capture link route."""
    trade = db.get(Trade, trade_id)
    body = plan_nudges.link_page(db, trade, time.time()) if trade is not None else None
    if body is None:
        raise HTTPException(404, "That trade is no longer in the journal.")
    return body


@router.get("/{trade_id}/fill-interrupts")
def trade_interrupts(trade_id: uuid.UUID, db: Session = Depends(get_session)):
    """This position's fill-time pattern interrupts that fired."""
    trade = db.get(Trade, trade_id)
    if trade is None:
        raise HTTPException(404, "That trade is no longer in the journal.")
    return {"interrupts": fill_interrupts.for_trade(db, trade)}


@router.post("/{trade_id}/fill-interrupts/{interrupt_id}/noted")
def note_interrupt(trade_id: uuid.UUID, interrupt_id: uuid.UUID, db: Session = Depends(get_session)):
    """The message's Noted button: recorded once, owner-only via the route boundary."""
    trade = db.get(Trade, trade_id)
    if trade is None:
        raise HTTPException(404, "That trade is no longer in the journal.")
    row = fill_interrupts.note(db, trade, interrupt_id, time.time())
    if row is None:
        raise HTTPException(404, "This message is unavailable for this position.")
    return row
