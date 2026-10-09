"""Sample-only domain reads, with independent backend bearer authentication."""
from datetime import date, datetime, timezone
import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlmodel import Session, select

from app.database import get_session
from app.engine import decisions, sample_practice
from app.engine.cloud_practice_access import require_sample
from app.models import PracticeRun
from cloud_mcp_d1_common import MAX_RESPONSE_BYTES

router = APIRouter()


def packet(request, db, run, *, details):
    require_sample(request)
    who = request.state.access
    if str(run.id) not in who.grants["run_ids"]:
        raise HTTPException(404, "Sample run not found")
    try:
        return sample_practice.view(db, run, who.identifier, who.grants["symbols"], details=details)
    except (decisions.DecisionError, ValueError, TypeError, KeyError):
        raise HTTPException(404, "Sample run not found") from None


def response(data, day):
    result = {"schema_version": "d1-sample-practice-v1", "sample_data": True,
        "read_at": datetime.now(timezone.utc).isoformat(), "time_zone": "America/New_York",
        "ui_path": f"/daily/{day.isoformat()}", **data}
    if len(json.dumps(result).encode()) > MAX_RESPONSE_BYTES:
        raise HTTPException(503, "Sample read exceeds its response limit")
    return result


@router.get("/runs")
def runs(request: Request, day: date, db: Session = Depends(get_session)):
    require_sample(request)
    if set(request.query_params) != {"day"} or len(request.query_params.getlist("day")) != 1 or request.query_params["day"] != day.isoformat():
        raise HTTPException(422, "Use one New York date in YYYY-MM-DD format")
    allowed = [uuid.UUID(value) for value in request.state.access.grants["run_ids"]]
    selected = db.exec(select(PracticeRun).where(PracticeRun.id.in_(allowed), PracticeRun.day == day).limit(1)).all()
    return response({"runs": [packet(request, db, run, details=False) for run in selected if sample_practice.eligible(run)]}, day)


@router.get("/runs/{run_id}")
def get_run(run_id: uuid.UUID, request: Request, db: Session = Depends(get_session)):
    require_sample(request)
    if request.query_params or str(run_id) not in request.state.access.grants["run_ids"]:
        raise HTTPException(404, "Sample run not found")
    run = db.get(PracticeRun, run_id)
    if run is None:
        raise HTTPException(404, "Sample run not found")
    return response({"run": packet(request, db, run, details=True)}, run.day)
