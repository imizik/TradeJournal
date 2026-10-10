"""Private owner preparation/review only; demo shadow uses a separate app."""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Session

from app.database import get_session
from app.engine import advisor_shadow, decisions

router = APIRouter()


class Question(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=2000)
    user_plan: str = Field(min_length=1, max_length=2000)


class Reference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    opportunity_id: uuid.UUID
    fact_name: str = Field(max_length=128)


class Answer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: str = Field(min_length=1, max_length=2000)
    interpretation: str = Field(min_length=1, max_length=2000)
    risks: str = Field(min_length=1, max_length=2000)
    conditions: str = Field(min_length=1, max_length=2000)
    gaps: str = Field(min_length=1, max_length=2000)
    references: list[Reference] = Field(max_length=10)


@router.get("/runs/{run_id}")
def review(run_id: uuid.UUID, db: Session = Depends(get_session)):
    try:
        return advisor_shadow.owner_view(db, run_id)
    except decisions.DecisionError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/runs/{run_id}/advisor-packet")
def packet(run_id: uuid.UUID, body: Question, db: Session = Depends(get_session)):
    try:
        return advisor_shadow.advisor_packet(db, run_id, body.model_dump())
    except decisions.DecisionError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/runs/{run_id}/advisor-output")
def answer(run_id: uuid.UUID, body: Answer, db: Session = Depends(get_session)):
    try:
        return advisor_shadow.advisor_output(db, run_id, body.model_dump(mode="json"))
    except decisions.DecisionError as exc:
        raise HTTPException(409, str(exc)) from exc
