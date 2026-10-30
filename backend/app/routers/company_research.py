"""Private owner company research endpoints."""
import uuid
from typing import Literal, Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Session, select

from app.database import get_session
from app.company_research_models import ResearchCompany
from app.engine import company_research as service
from app.engine.job_runtime import submit_job
from app.engine.jobs import job_status

from app.engine import company_research_assignments as assignments
from app.company_research_models import ResearchAssignment, ResearchFinding

router = APIRouter()


class AddCompany(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbol: str = Field(min_length=1, max_length=15)


class EditCompany(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=0)
    thesis: str = Field(max_length=6000)
    assumptions: list[Annotated[str, Field(min_length=1, max_length=1000)]] = Field(max_length=5)
    followed: bool


@router.get("/companies")
def companies(db: Session = Depends(get_session)):
    return [service.view(db, r) for r in db.exec(select(ResearchCompany).order_by(ResearchCompany.symbol)).all()]


@router.post("/companies")
def add(body: AddCompany, db: Session = Depends(get_session)):
    row = service.add(db, body.symbol)
    return service.view(db, row)


@router.get("/companies/{identifier}")
def detail(identifier: uuid.UUID, db: Session = Depends(get_session)):
    return service.view(db, service.company(db, identifier))


@router.patch("/companies/{identifier}")
def edit(identifier: uuid.UUID, body: EditCompany, db: Session = Depends(get_session)):
    row = service.patch(db, identifier, **body.model_dump())
    if not row.followed:
        from app.engine.company_research_bridge import revoke_company
        revoke_company(db, identifier)
    return service.view(db, row)


@router.get("/companies/{identifier}/history")
def history(identifier: uuid.UUID, limit: int = Query(100, ge=1, le=200), offset: int = Query(0, ge=0), db: Session = Depends(get_session)):
    return service.history(db, identifier, limit, offset)


@router.post("/companies/{identifier}/refresh")
def refresh(identifier: uuid.UUID, db: Session = Depends(get_session)):
    job = service.queue_refresh(db, service.company(db, identifier))
    submit_job(job.id)
    return job_status(job)


@router.get("/jobs/{identifier}")
def job(identifier: uuid.UUID, db: Session = Depends(get_session)):
    from fastapi import HTTPException
    from app.models import JobRun
    row = db.get(JobRun, identifier)
    if row is None or row.job_type != "company_research_refresh":
        raise HTTPException(404, "Refresh not found")
    return job_status(row)


class AssignmentBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    company_id: uuid.UUID
    question: str = Field(min_length=1, max_length=2000)
    actor: str = Field(default="manual", max_length=50)


class ImportBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    result: assignments.FindingBody
    confirmation: str | None = None


@router.post("/assignments")
def create_assignment(body: AssignmentBody, db: Session = Depends(get_session)):
    from fastapi import HTTPException
    from app.engine.company_research_bridge import researchers, configuration
    if body.actor != "manual" and body.actor not in {r["id"] for r in researchers()}:
        raise HTTPException(422, "Researcher is not configured and approved")
    packet = assignments.create(db, body.company_id, body.question, body.actor)
    if body.actor != "manual":
        from app.jobs.company_research import publish
        publish(db, uuid.UUID(packet["id"]), body.actor, configuration())
    return packet


@router.get("/researchers")
def researchers():
    from app.engine.company_research_bridge import researchers
    return researchers()


@router.get("/assignments/{identifier}")
def assignment(identifier: uuid.UUID, db: Session = Depends(get_session)):
    return assignments.packet(assignments.get(db, identifier))


@router.get("/companies/{identifier}/assignments")
def list_assignments(identifier: uuid.UUID, db: Session = Depends(get_session)):
    service.company(db, identifier)
    return [assignments.packet(r) for r in db.exec(select(ResearchAssignment).where(
        ResearchAssignment.company_id == identifier).order_by(ResearchAssignment.created_at.desc()).limit(30)).all()]


@router.post("/assignments/{identifier}/import")
def import_result(identifier: uuid.UUID, body: ImportBody, db: Session = Depends(get_session)):
    return assignments.import_result(db, identifier, body.result, body.confirmation)


@router.get("/companies/{identifier}/findings")
def findings(identifier: uuid.UUID, db: Session = Depends(get_session)):
    import json
    service.company(db, identifier)
    return [{"id": str(r.id), "actor": r.actor, "disposition": r.disposition, "digest": r.digest, "data": json.loads(r.payload_json)}
            for r in db.exec(select(ResearchFinding).where(ResearchFinding.company_id == identifier).order_by(
                ResearchFinding.created_at.desc()).limit(100)).all()]


class DispositionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    disposition: Literal["accepted", "rejected", "reviewed"]


@router.patch("/findings/{identifier}")
def disposition(identifier: uuid.UUID, body: DispositionBody, db: Session = Depends(get_session)):
    return assignments.disposition(db, identifier, body.digest, body.disposition)


@router.get("/companies/{identifier}/numbers")
def numbers(identifier: uuid.UUID, db: Session = Depends(get_session)):
    return service.sourced_numbers(db, identifier)


@router.get("/companies/{identifier}/comparisons")
def comparisons(identifier: uuid.UUID, db: Session = Depends(get_session)):
    from app.engine.company_research_math import earnings_comparison
    numbers = service.sourced_numbers(db, identifier)
    out = []
    for actual in [n for n in numbers if n["role"] == "actual"]:
        candidates = [{"actual": actual, "reference": reference, "comparison": earnings_comparison(actual, reference)}
                      for reference in numbers if reference["role"] in {"estimate", "guidance"}
                      and reference["metric"] == actual["metric"] and reference["period_end"] == actual["period_end"]]
        eligible = [item for item in candidates if item["comparison"]["state"] == "ready"]
        out.extend((eligible or candidates)[:2])
    return out[:100]
