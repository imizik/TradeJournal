"""Private owner UI endpoints. No externally accessible runner API exists."""
from datetime import date
import json
import os
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Session, select

from app.database import get_session
from app.engine import decisions, practice, access, sample_practice, sample_replay, market_practice
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


def inspector_view(request, db, run, *, details=True):
    if market_practice.eligible(run):
        who = getattr(request.state, "access", None)
        restricted = access.permitted_runs(request) is not None
        try:
            return market_practice.view(db, run, who.identifier if restricted else None,
                who.grants.get("symbols", []) if restricted else market_practice.SYMBOLS, details=details)
        except decisions.DecisionError as exc:
            raise HTTPException(409, str(exc)) from exc
    if access.market_writer(request):
        raise HTTPException(404, "Market session not found")
    if access.decision_writer(request) or (access.permitted_runs(request) is not None and
            (run.session_key.startswith(sample_replay.PREFIX) or run.policy_version == decisions.REPLAY_POLICY_VERSION)):
        try:
            return sample_practice.view(db, run, request.state.access.identifier,
                request.state.access.grants["symbols"], details=details)
        except decisions.DecisionError as exc:
            raise HTTPException(404, "Sample run not found") from exc
    restricted = access.permitted_runs(request) is not None
    result = practice.view(db, run, details=details, recover=not restricted)
    if restricted:
        result["error"] = "Preparation unavailable" if result["error"] else None
        result["agent"]["error"] = "Agent output unavailable" if result["agent"]["error"] else None
        result["agent"]["limits"] = None
    return result


@router.get("/runs")
def runs(request: Request, day: date | None = None, db: Session = Depends(get_session)):
    query = select(PracticeRun).order_by(PracticeRun.created_at.desc()).limit(30)
    allowed = access.permitted_runs(request)
    if allowed is not None:
        query = query.where(PracticeRun.id.in_([uuid.UUID(value) for value in allowed]))
    if access.decision_writer(request):
        query = query.where(PracticeRun.policy_version.in_([decisions.SAMPLE_POLICY_VERSION, decisions.REPLAY_POLICY_VERSION]),
            PracticeRun.session_key.startswith(sample_practice.PREFIX))
    if access.market_writer(request):
        query = query.where(PracticeRun.policy_version == decisions.MARKET_POLICY_VERSION,
            PracticeRun.session_key.startswith(market_practice.PREFIX))
    if day:
        query = query.where(PracticeRun.day == day)
    return {"runs": [inspector_view(request, db, r, details=False) for r in db.exec(query).all()]}


@router.get("/runs/{run_id}")
def get_run(run_id: uuid.UUID, request: Request, db: Session = Depends(get_session)):
    allowed = access.permitted_runs(request)
    if allowed is not None and str(run_id) not in allowed:
        raise HTTPException(404, "Daily run not found")
    return inspector_view(request, db, run_or_404(db, run_id))


@router.post("/opportunities/{opp_id}/choice")
def choice(opp_id: uuid.UUID, body: Choice, db: Session = Depends(get_session)):
    opp = opp_or_404(db, opp_id)
    try:
        practice.choose(db, opp, body.model_dump())
    except decisions.DecisionError as exc:
        raise HTTPException(409, str(exc)) from exc
    return practice.view(db, run_or_404(db, opp.run_id))


@router.post("/opportunities/{opp_id}/agent-choice", status_code=201)
def agent_choice(opp_id: uuid.UUID, body: Choice, request: Request, response: Response, db: Session = Depends(get_session)):
    market = access.market_writer(request)
    if not access.decision_writer(request) and not market:
        raise HTTPException(403, "Scoped decision writer required")
    if market:
        try:
            run, created = market_practice.submit(db, request, opp_id, body.model_dump())
        except decisions.DecisionError as exc:
            raise HTTPException(409 if "operation_id" in str(exc) else 422, str(exc)) from exc
        response.status_code = 201 if created else 200
        return inspector_view(request, db, run)
    opp = opp_or_404(db, opp_id)
    if str(opp.run_id) not in access.permitted_runs(request) or opp.symbol not in request.state.access.grants["symbols"]:
        raise HTTPException(404, "Opportunity not found")
    run = run_or_404(db, opp.run_id)
    service = sample_practice
    if not service.eligible(run):
        raise HTTPException(404, "Sample run not found")
    try:
        _, created = service.choose(db, run, opp, request.state.access.identifier, body.model_dump())
    except decisions.DecisionError as exc:
        raise HTTPException(409 if "operation_id" in str(exc) else 422, str(exc)) from exc
    response.status_code = 201 if created else 200
    return inspector_view(request, db, run)


@router.post("/opportunities/{opp_id}/sample-replay", status_code=201)
def start_sample_replay(opp_id: uuid.UUID, body: Strict, request: Request, response: Response, db: Session = Depends(get_session)):
    if not access.replay_writer(request):
        raise HTTPException(403, "Scoped sample replay writer required")
    try:
        run, created = sample_replay.start(db, opp_id, request.state.access)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except (decisions.DecisionError, ValueError, KeyError) as exc:
        raise HTTPException(422, str(exc) if isinstance(exc, decisions.DecisionError) else "Invalid sealed replay") from exc
    response.status_code = 201 if created else 200
    return inspector_view(request, db, run)


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
