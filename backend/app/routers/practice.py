"""Private owner UI endpoints. No externally accessible runner API exists."""
from datetime import date
import json
import os
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Session, select

from app.database import get_session
from app.engine import decisions, practice
from app.engine.job_runtime import submit_job
from app.models import PracticeOpportunity, PracticeRun

router = APIRouter()


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Preparation(Strict):
    mode: str = "manual"
    comparison: str = "independent"
    revision: int = Field(default=0, ge=0, le=10)
    parent_id: uuid.UUID | None = None


class Choice(Strict):
    decision: str
    rationale: str = Field(default="", max_length=2000)
    wait_condition: str | None = Field(default=None, max_length=500)
    wait_expiry: str | None = None
    plan: dict | None = None


class Timing(Strict):
    phase: str
    seconds: float = Field(ge=0, le=86400, allow_inf_nan=False)
    reason: str = Field(default="", max_length=500)


class Feedback(Strict):
    rating: str
    phone_received: bool | None = None


def run_or_404(db, run_id):
    run = db.get(PracticeRun, run_id)
    if not run:
        raise HTTPException(404, "Daily run not found")
    return run


def opp_or_404(db, opp_id):
    opp = db.get(PracticeOpportunity, opp_id)
    if not opp:
        raise HTTPException(404, "Opportunity not found")
    return opp


@router.post("/prepare")
def prepare(body: Preparation, db: Session = Depends(get_session)):
    if body.mode == "scheduled" and os.environ.get("PRACTICE_SCHEDULE_ENABLED") != "true":
        raise HTTPException(403, "Scheduling disabled pending explicit approval")
    if body.revision and body.parent_id is None:
        raise HTTPException(422, "An explicit revision requires its selected original run")
    try:
        run = practice.start(db, mode=body.mode, comparison=body.comparison, revision=body.revision, parent_id=body.parent_id)
    except decisions.DecisionError as exc:
        raise HTTPException(409, str(exc)) from exc
    submit_job(run.job_id)
    return practice.view(db, run)


@router.get("/runs")
def runs(day: date | None = None, db: Session = Depends(get_session)):
    query = select(PracticeRun).order_by(PracticeRun.created_at.desc()).limit(30)
    if day:
        query = query.where(PracticeRun.day == day)
    return {"runs": [practice.view(db, r, details=False) for r in db.exec(query).all()]}


@router.get("/runs/{run_id}")
def get_run(run_id: uuid.UUID, db: Session = Depends(get_session)):
    return practice.view(db, run_or_404(db, run_id))


@router.post("/opportunities/{opp_id}/choice")
def choice(opp_id: uuid.UUID, body: Choice, db: Session = Depends(get_session)):
    opp = opp_or_404(db, opp_id)
    try:
        practice.choose(db, opp, body.model_dump())
    except decisions.DecisionError as exc:
        raise HTTPException(409, str(exc)) from exc
    return practice.view(db, run_or_404(db, opp.run_id))


@router.post("/opportunities/{opp_id}/reveal")
def reveal(opp_id: uuid.UUID, body: Strict, db: Session = Depends(get_session)):
    opp = opp_or_404(db, opp_id)
    try:
        practice.reveal(db, opp)
    except decisions.DecisionError as exc:
        raise HTTPException(409, str(exc)) from exc
    return practice.view(db, run_or_404(db, opp.run_id))


@router.post("/runs/{run_id}/timing")
def timing(run_id: uuid.UUID, body: Timing, db: Session = Depends(get_session)):
    run = run_or_404(db, run_id)
    if body.phase not in {"morning", "review"}:
        raise HTTPException(422, "Timing phase must be morning or review")
    timings = json.loads(run.timings_json)
    timings[body.phase] = {"seconds": body.seconds, "reason": body.reason, "reported_at": practice.iso(practice.now_utc())}
    run.timings_json = json.dumps(timings)
    db.add(run)
    db.commit()
    return practice.view(db, run)


@router.post("/opportunities/{opp_id}/feedback")
def feedback(opp_id: uuid.UUID, body: Feedback, db: Session = Depends(get_session)):
    if body.rating not in {"useful", "not_useful", "unrated"}:
        raise HTTPException(422, "Invalid alert rating")
    opp = opp_or_404(db, opp_id)
    opp.feedback_json = json.dumps(body.model_dump())
    db.add(opp)
    db.commit()
    return practice.view(db, run_or_404(db, opp.run_id))


@router.post("/runs/{run_id}/benchmark")
def collect_benchmark(run_id: uuid.UUID, body: Strict, db: Session = Depends(get_session)):
    from app.engine.chart_feed import chart_feed
    from app.engine.chart_splits import chart_splits
    run = run_or_404(db, run_id)
    practice.collect_benchmarks(db, run, feed=chart_feed, splits=chart_splits)
    return practice.view(db, run)
