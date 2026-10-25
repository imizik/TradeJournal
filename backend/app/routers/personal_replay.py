"""Personal replay API backed only by a fixed synthetic scenario."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Session, select

from app.database import get_session
from app.engine import personal_replay
from app.models import PracticeReplayAttempt

router = APIRouter()

class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")

class StartAttempt(Strict):
    operation_id: uuid.UUID

class Choice(Strict):
    checkpoint_id: str
    decision: str
    rationale: str | None = Field(default=None, max_length=500)

class Reveal(Strict):
    checkpoint_id: str

@router.get("/replay/scenarios")
def scenarios(db: Session = Depends(get_session)):
    latest = db.exec(select(PracticeReplayAttempt).order_by(PracticeReplayAttempt.created_at.desc()).limit(1)).first()
    return {"scenarios": [{**personal_replay.SCENARIO,
        "repeat_status": "repeat" if latest else "new",
        "latest_attempt_id": str(latest.id) if latest else None}]}

@router.post("/replay/attempts", status_code=201)
def start_attempt(body: StartAttempt, db: Session = Depends(get_session)):
    return personal_replay.create_attempt(db, body.operation_id)

@router.get("/replay/attempts/{attempt_id}")
def attempt(attempt_id: uuid.UUID, db: Session = Depends(get_session)):
    result = personal_replay.get_attempt(db, attempt_id)
    if result is None:
        raise HTTPException(404, "Replay attempt not found")
    return result

@router.post("/replay/attempts/{attempt_id}/choice")
def choice(attempt_id: uuid.UUID, body: Choice, db: Session = Depends(get_session)):
    try:
        result = personal_replay.save_choice(db, attempt_id, body.checkpoint_id, body.decision, body.rationale)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    if result is None:
        raise HTTPException(404, "Replay attempt not found")
    return result

@router.post("/replay/attempts/{attempt_id}/reveal")
def reveal(attempt_id: uuid.UUID, body: Reveal, db: Session = Depends(get_session)):
    try:
        result = personal_replay.reveal(db, attempt_id, body.checkpoint_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    if result is None:
        raise HTTPException(404, "Replay attempt not found")
    return result
