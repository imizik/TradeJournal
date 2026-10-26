"""Exit habits: what happened after each phone alert, and the audit's four exit habits vs. baseline; see app/engine/exit_habits.py.
Plan proof: planned against unplanned trades since the plan card went live; see app/engine/plan_proof.py."""

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.database import get_session
from app.engine import exit_habits, plan_proof

router = APIRouter()


@router.get("/exit-habits")
def get_exit_habits(db: Session = Depends(get_session)):
    return exit_habits.build(db)


@router.get("/plan-proof")
def get_plan_proof(db: Session = Depends(get_session)):
    return plan_proof.build(db)
