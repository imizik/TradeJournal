from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session

from app.database import get_session
from app.engine import weekly_review

router = APIRouter()


class ChooseRequest(BaseModel):
    rule_key: str | None = None  # None skips the week
    note: str | None = None


class ResultRequest(BaseModel):
    result: str


def _week(value: str) -> date:
    try:
        return weekly_review.check_week(date.fromisoformat(value))
    except weekly_review.ReviewError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="week must be YYYY-MM-DD") from exc


@router.get("/{week_start}")
def get_weekly_review(week_start: str, session: Session = Depends(get_session)):
    """The week's exit leaks, last week's rule checked against later trades, and this week's choice."""
    return weekly_review.view(session, _week(week_start))


@router.put("/{week_start}")
def choose_rule(week_start: str, body: ChooseRequest, session: Session = Depends(get_session)):
    week = _week(week_start)
    try:
        weekly_review.choose(session, week, body.rule_key, body.note)
    except weekly_review.ReviewError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return weekly_review.view(session, week)


@router.put("/{week_start}/result")
def confirm_result(week_start: str, body: ResultRequest, session: Session = Depends(get_session)):
    week = _week(week_start)
    try:
        weekly_review.confirm(session, week, body.result)
    except weekly_review.ReviewError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return weekly_review.view(session, week)
