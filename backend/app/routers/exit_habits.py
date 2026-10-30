"""Exit habits: what happened after each phone alert, and the audit's four exit habits vs. baseline; see app/engine/exit_habits.py.
Plan proof: planned against unplanned trades since the plan card went live; see app/engine/plan_proof.py.
Outcomes: what followed each ping, plan, Radar event, Jo research record and Shadow decision; see app/engine/outcomes.py."""

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from app.database import get_session
from app.engine import exit_habits, outcomes, plan_proof

router = APIRouter()


@router.get("/exit-habits")
def get_exit_habits(db: Session = Depends(get_session)):
    return exit_habits.build(db)


@router.get("/plan-proof")
def get_plan_proof(db: Session = Depends(get_session)):
    return plan_proof.build(db)


@router.get("/outcomes")
def get_outcomes(kind: Literal["ping", "plan", "radar_event", "research", "shadow_decision", "companion_update"] | None = None,
                 since: date | None = None, symbol: str | None = Query(default=None, max_length=15),
                 db: Session = Depends(get_session)):
    return outcomes.build(db, kind, since, symbol)
