"""The Copilot Lab's Plans board (``engine/copilot_plans.py``): confirmed copilot plans still armed, nearest first,
and the Dashboard's Plans card (``engine/plan_positions.py``): each open position beside the plan it was entered under.

Owner-only like every ``/copilot`` route; refuses while the lab is off. Read-only.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.ai import copilot
from app.database import get_session
from app.engine import copilot_plans, plan_positions

router = APIRouter()


@router.get("/plans")
def plans(db: Session = Depends(get_session)):
    if not copilot.settings().enabled:
        raise HTTPException(503, "Copilot Lab is off.")
    return copilot_plans.board(db)


@router.get("/plans/positions")
def plan_positions_view(db: Session = Depends(get_session)):
    if not copilot.settings().enabled:
        raise HTTPException(503, "Copilot Lab is off.")
    return plan_positions.positions(db)
