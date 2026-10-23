"""Exit habits: what happened after each phone alert, and the audit's four exit habits vs. baseline; see app/engine/exit_habits.py."""

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.database import get_session
from app.engine import exit_habits

router = APIRouter()


@router.get("/exit-habits")
def get_exit_habits(db: Session = Depends(get_session)):
    return exit_habits.build(db)
