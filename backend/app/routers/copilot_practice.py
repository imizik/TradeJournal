"""The practice goal (``engine/practice_goal.py``, docs/copilot-lab.md § Review my week): the owner confirms the one
thing to practice from a Review my week card, and the lab home and Dashboard show it with this week's count.

Owner-only like every ``/copilot`` route; refuses while the lab is off. ``POST`` writes one ``practice_goal`` row and ends
the previous active one; nothing else.
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.ai import copilot
from app.database import get_session
from app.engine import practice_goal
from app.engine.chart_math import ET

router = APIRouter()
UUID = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"


class PracticeBody(BaseModel):
    text: str = Field(min_length=1, max_length=practice_goal.TEXT_MAX)
    measure: str
    target: float | None = None
    investigation_id: str | None = Field(None, pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def _enabled():
    if not copilot.settings().enabled:
        raise HTTPException(503, "Copilot Lab is off.")


@router.get("/practice")
def current(investigation: str | None = Query(None, pattern=UUID), db: Session = Depends(get_session)):
    """With ``investigation``: also ``proposed``, the practice card an automatic week review saved there and the owner
    has not confirmed (``engine/week_review_auto.py``), or null."""
    _enabled()
    out = practice_goal.current(db, datetime.now(ET).date())
    if investigation is not None:
        from app.engine import week_review_auto
        out["proposed"] = week_review_auto.proposed(db, investigation)
    return out


@router.post("/practice", status_code=201)
def confirm(body: PracticeBody, db: Session = Depends(get_session)):
    """The confirmed card becomes the one active goal; a goal already active ends."""
    _enabled()
    today = datetime.now(ET).date()
    try:
        practice_goal.save(db, text=body.text, measure=body.measure, target=body.target,
                           investigation_id=body.investigation_id, today=today)
    except practice_goal.PracticeError as exc:
        raise HTTPException(422, str(exc)) from None
    return practice_goal.current(db, today)
