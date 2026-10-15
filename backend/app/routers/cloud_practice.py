"""Sample-only domain reads, with independent backend bearer authentication."""
from datetime import date, datetime, timezone
import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlmodel import Session, select

from app.database import get_session
from app.engine import access, decisions, sample_practice, historical_replay, scanner_replay
from app.engine.cloud_practice_access import require_sample, historical_mode, require_historical, scanner_mode, require_scanner
from app.models import PracticeRun
from cloud_mcp_d1_common import MAX_RESPONSE_BYTES

router = APIRouter()


def packet(request, db, run, *, details, resume=False):
    require_sample(request)
    who = request.state.access
    if str(run.id) not in who.grants["run_ids"]:
        raise HTTPException(404, "Sample run not found")
    try:
        if scanner_mode():
            require_scanner(request)
            with access._LOCK:
                access._serialized(db)
                db.expire_all()
                db.refresh(run)
                result = scanner_replay.view(db, run, who.identifier, who.grants["symbols"], details=details, resume=resume)
                # Summary-only/terminal views do not write first-served time.
                # End this transaction before projecting the next listed run.
                db.commit()
                return result
        if historical_mode():
            require_historical(request)
            return historical_replay.view(db, run, who.identifier, who.grants["symbols"],
                                          details=details, include_replay=False)
        return sample_practice.view(db, run, who.identifier, who.grants["symbols"], details=details)
    except (decisions.DecisionError, ValueError, TypeError, KeyError):
        raise HTTPException(404, "Sample run not found") from None


def response(data, day):
    historical = historical_mode()
    scanner = scanner_mode()
    result = {"schema_version": scanner_replay.SCHEMA if scanner else "historical-demo-practice-v1" if historical else "d1-sample-practice-v1",
        "sample_data": not (historical or scanner), **({"historical_replay": True, "demo_only": True} if historical or scanner else {}),
        "read_at": datetime.now(timezone.utc).isoformat(), "time_zone": "America/New_York",
        "ui_path": None if scanner else f"/daily/{day.isoformat()}", **data}
    if len(json.dumps(result).encode()) > MAX_RESPONSE_BYTES:
        raise HTTPException(503, "Sample read exceeds its response limit")
    return result


@router.get("/runs")
def runs(request: Request, day: date | None = None, db: Session = Depends(get_session)):
    require_sample(request)
    if scanner_mode() and day is None:
        if request.query_params:
            raise HTTPException(422, "Use no query or one historical session date")
        allowed = [uuid.UUID(value) for value in request.state.access.grants["run_ids"]]
        selected = db.exec(select(PracticeRun).where(PracticeRun.id.in_(allowed)).order_by(PracticeRun.day)).all()
        selected = [r for r in selected if scanner_replay.eligible(r)]
        next_run = next((r for phase in ("practice", "exam") for r in selected
                         if r.status == "prepared" and scanner_replay.metadata(r)["phase"] == phase), None)
        return response({"runs": [packet(request, db, r, details=False) for r in
                                 ([next_run] if next_run else selected)]}, None)
    if day is None:
        raise HTTPException(422, "Use one New York date")
    if set(request.query_params) != {"day"} or len(request.query_params.getlist("day")) != 1 or request.query_params["day"] != day.isoformat():
        raise HTTPException(422, "Use one New York date in YYYY-MM-DD format")
    allowed = [uuid.UUID(value) for value in request.state.access.grants["run_ids"]]
    selected = db.exec(select(PracticeRun).where(PracticeRun.id.in_(allowed), PracticeRun.day == day).limit(1)).all()
    eligible = scanner_replay.eligible if scanner_mode() else historical_replay.eligible if historical_mode() else sample_practice.eligible
    return response({"runs": [packet(request, db, run, details=False) for run in selected if eligible(run)]}, day)


@router.get("/runs/{run_id}")
def get_run(run_id: uuid.UUID, request: Request, db: Session = Depends(get_session)):
    require_sample(request)
    resume = False
    if scanner_mode() and request.query_params:
        if (set(request.query_params) != {"resume"} or len(request.query_params.getlist("resume")) != 1
                or request.query_params["resume"] != "true"):
            raise HTTPException(422, "Use only resume=true for an interrupted scanner run")
        resume = True
    elif request.query_params:
        raise HTTPException(404, "Sample run not found")
    if str(run_id) not in request.state.access.grants["run_ids"]:
        raise HTTPException(404, "Sample run not found")
    run = db.get(PracticeRun, run_id)
    if run is None:
        raise HTTPException(404, "Sample run not found")
    return response({"run": packet(request, db, run, details=True, resume=resume)}, run.day)
