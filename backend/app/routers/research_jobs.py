"""Owner-only Copilot Lab research queue (docs/copilot-lab.md § Research queue): enqueue, list and cancel jobs.

In no assistant grant. Queuing works with the runner off; jobs then wait until ``RESEARCH_QUEUE_ENABLED=true``.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.ai import copilot_tools
from app.database import get_session
from app.engine import research_queue

router = APIRouter()


class QuestionJob(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    symbols: list[str] = Field(default_factory=list, max_length=copilot_tools.MAX_SYMBOLS)
    investigation_id: uuid.UUID | None = None  # the saved investigation it was asked from (shown there, not read)


class RevisitJob(BaseModel):
    investigation_id: uuid.UUID
    question: str = Field(min_length=1, max_length=500)
    after_days: int = Field(0, ge=0, le=30)


def _http(exc: research_queue.QueueError) -> HTTPException:
    return HTTPException(404 if exc.code == "not_found" else 422, str(exc))


@router.post("", status_code=201)
def enqueue_question(body: QuestionJob, session: Session = Depends(get_session)):
    try:
        symbols = copilot_tools.validate("get_quotes", {"symbols": body.symbols})["symbols"] if body.symbols else []
        job, created = research_queue.enqueue_question(
            body.question, symbols, session=session,
            from_investigation=str(body.investigation_id) if body.investigation_id else None)
    except copilot_tools.ToolInputError as exc:
        raise HTTPException(422, str(exc))
    except research_queue.QueueError as exc:
        raise _http(exc)
    return {"job": job, "created": created, "queue_enabled": research_queue.settings().enabled}


@router.post("/reassess", status_code=201)
def enqueue_revisit(body: RevisitJob, session: Session = Depends(get_session)):
    """The owner confirmed "revisit this question" for a saved investigation."""
    try:
        job, created = research_queue.enqueue_revisit(str(body.investigation_id), body.question, body.after_days, session=session)
    except research_queue.QueueError as exc:
        raise _http(exc)
    return {"job": job, "created": created, "queue_enabled": research_queue.settings().enabled}


@router.get("")
def list_jobs(status: str | None = None, limit: int = 50, session: Session = Depends(get_session)):
    cfg = research_queue.settings()
    return {"jobs": research_queue.list_jobs(status=status, limit=limit, session=session), "queue_enabled": cfg.enabled,
            "daily_budget_usd": cfg.daily_budget_usd, "spent_today_usd": research_queue.spent_today(session=session)}


@router.post("/{job_id}/cancel")
def cancel_job(job_id: str, session: Session = Depends(get_session)):
    try:
        return {"job": research_queue.cancel(job_id, session=session)}
    except research_queue.QueueError as exc:
        raise _http(exc)
