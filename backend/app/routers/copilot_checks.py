"""Check a call on the desk (``engine/call_check.py``, docs/copilot-lab.md § Check a call): ``POST /copilot/checks``
checks a pasted call (one bounded ``check_call`` copilot turn under the turn and daily budgets) and keeps it;
``GET /copilot/checks`` reads a New York day's checked calls (today by default), newest first, each with the
underlying's price and the contract's quote at the check and whether a plan was saved from it, for the tab's Checked
today list and a later evening report; ``POST /copilot/checks/{id}/pass`` records his Pass.

Owner-only like every ``/copilot`` route; refuses while the lab is off. Nothing here places, sizes or proposes an order:
Plan it is a link to the existing plan flow.
"""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.ai import copilot
from app.database import get_session
from app.engine import call_check

router = APIRouter()


def _on() -> None:
    if not copilot.settings().enabled:
        raise HTTPException(503, "Copilot Lab is off.")


class CheckBody(BaseModel):
    text: str = Field(min_length=1, max_length=call_check.RAW_MAX)


@router.post("/checks")
async def check_call(body: CheckBody):
    """Check one pasted call; the saved check. 409 with the reason when it could not run (the budget spent, the model
    failed)."""
    _on()
    try:
        return await call_check.run(body.text, source="desk")
    except call_check.CheckRefused as exc:
        raise HTTPException(409, str(exc)) from None


@router.get("/checks")
def checks(day: date | None = None, db: Session = Depends(get_session)):
    _on()
    day = day or call_check.today()
    return {"day": day.isoformat(), "checks": call_check.day_checks(db, day)}


@router.post("/checks/{check_id}/pass")
def pass_check(check_id: str, db: Session = Depends(get_session)):
    _on()
    _, chosen = call_check.pass_check(db, check_id)
    if chosen is None:
        raise HTTPException(404, "That checked call is not in the journal.")
    return call_check.get(db, check_id)
