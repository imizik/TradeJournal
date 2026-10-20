"""Owner links from saved Jo checks to later journal activity (Dots step 5).

The owner's page supplies the facts of the check it shows; the check itself
stays in the Check ledger. See app/engine/check_links.py.
"""

import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.database import get_session
from app.engine import check_links
from app.engine.check_links import CheckFacts, LinkError

router = APIRouter()


class Facts(BaseModel):
    ticker: str | None = Field(default=None, max_length=12)
    received_at: datetime | None = None
    instrument: str | None = None
    option_type: str | None = None
    strike: float | None = None
    expiration: date | None = None


class LinkBody(Facts):
    trade_id: uuid.UUID | None = None
    fill_id: uuid.UUID | None = None


def _facts(check_id: str, body: Facts) -> CheckFacts:
    try:
        return CheckFacts.build(check_id, body.ticker, body.received_at, body.instrument, body.option_type, body.strike, body.expiration)
    except LinkError as exc:
        raise HTTPException(422, str(exc)) from None


@router.get("/for-trade/{trade_id}")
def for_trade(trade_id: uuid.UUID, db: Session = Depends(get_session)):
    """Saved checks the owner linked to this trade or one of its fills."""
    return {"links": check_links.for_trade(db, trade_id)}


@router.get("/{check_id}/activity")
def activity(check_id: str, facts: Facts = Query(), db: Session = Depends(get_session)):
    """Linked activity and possible later activity (review needed) for one saved check."""
    return check_links.activity(db, _facts(check_id, facts))


@router.post("/{check_id}/link")
def link(check_id: str, body: LinkBody, db: Session = Depends(get_session)):
    facts = _facts(check_id, body)
    try:
        check_links.link(db, facts, trade_id=body.trade_id, fill_id=body.fill_id)
    except LinkError as exc:
        raise HTTPException(422, str(exc)) from None
    return check_links.activity(db, facts)


@router.post("/{check_id}/links/{link_id}/unlink")
def unlink(check_id: str, link_id: uuid.UUID, body: Facts, db: Session = Depends(get_session)):
    facts = _facts(check_id, body)
    try:
        check_links.unlink(db, check_id, link_id)
    except LinkError as exc:
        raise HTTPException(404, str(exc)) from None
    return check_links.activity(db, facts)
