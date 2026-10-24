"""Copilot Lab research queue (docs/copilot-lab.md § Research queue).

Queued background research jobs, run one at a time inside the API process by
``QueueRunner`` when ``RESEARCH_QUEUE_ENABLED=true`` (default off). A job is a
question, a Radar event, or a saved investigation to reassess. It runs through
``app.ai.research_job`` and its result is saved as a saved investigation. The
runner retries transient failures with backoff, honours cancel, caps each job's
budget and the day's total (``RESEARCH_DAILY_BUDGET_USD``, default $2), and
records failures on the job.

Two optional triggers enqueue work, both off by default:

- ``RESEARCH_RADAR_TRIGGER=true``: each new Radar event in today's session,
  read only from ``RADAR_STORE``, gets one ``radar_event`` job.
- ``RESEARCH_REASSESS_AFTER_HOURS=N``: each open investigation last updated more
  than N hours ago gets at most one ``reassess`` job a day.

Nothing here notifies, alerts, trades or writes plans, watches or memories.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterator

from sqlmodel import Session, col, select

from app.models import CopilotInvestigation, ResearchJob

log = logging.getLogger(__name__)

KINDS = ("question", "radar_event", "reassess")
ACTIVE = ("queued", "running")
MAX_ATTEMPTS = 3
BACKOFF_S = (60, 300)  # before the 2nd and 3rd attempt
# Failures worth another attempt; anything else (auth, budget, bad input) fails at once.
RETRYABLE = {"timeout", "sdk", "no_result", "no_assessment"}


class QueueError(ValueError):
    """``code`` is ``not_found`` or ``bad_input``."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class QueueSettings:
    enabled: bool
    daily_budget_usd: float
    radar_trigger: bool
    reassess_after_hours: int  # 0 = off
    idle_s: float = 15.0
    trigger_every_s: float = 300.0


def settings() -> QueueSettings:
    return QueueSettings(
        enabled=os.environ.get("RESEARCH_QUEUE_ENABLED") == "true",
        daily_budget_usd=float(os.environ.get("RESEARCH_DAILY_BUDGET_USD") or 2.0),
        radar_trigger=os.environ.get("RESEARCH_RADAR_TRIGGER") == "true",
        reassess_after_hours=int(os.environ.get("RESEARCH_REASSESS_AFTER_HOURS") or 0),
    )


@contextmanager
def _session(session: Session | None) -> Iterator[Session]:
    if session is not None:
        yield session
        return
    from app.database import engine
    with Session(engine) as own:
        yield own


def view(job: ResearchJob) -> dict:
    return {"id": str(job.id), "kind": job.kind, "input": json.loads(job.input_json), "status": job.status,
            "attempts": job.attempts, "error": job.error, "cost_usd": job.cost_usd,
            "investigation_id": str(job.investigation_id) if job.investigation_id else None,
            "created_at": job.created_at.isoformat(), "next_attempt_at": job.next_attempt_at.isoformat(),
            "started_at": job.started_at and job.started_at.isoformat(),
            "finished_at": job.finished_at and job.finished_at.isoformat()}


def _today() -> str:
    from app.engine.chart_math import ET
    return datetime.now(ET).date().isoformat()


def _digest(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()[:24]


# --------------------------------------------------------------------------- enqueue / list / cancel

def enqueue(kind: str, payload: dict, dedupe_key: str, session: Session | None = None) -> tuple[dict, bool]:
    """Queue a job unless one with the same dedupe key exists. Returns (job, created)."""
    if kind not in KINDS:
        raise QueueError("bad_input", f"unknown job kind {kind!r}")
    with _session(session) as db:
        existing = db.exec(select(ResearchJob).where(ResearchJob.dedupe_key == dedupe_key)).first()
        if existing is not None:
            return view(existing), False
        job = ResearchJob(kind=kind, input_json=json.dumps(payload), dedupe_key=dedupe_key)
        db.add(job)
        db.commit()
        db.refresh(job)
        return view(job), True


def enqueue_question(question: str, symbols: list[str], session: Session | None = None) -> tuple[dict, bool]:
    """The same question and symbols are queued at most once per day."""
    question = question.strip()
    if not question:
        raise QueueError("bad_input", "question is empty")
    return enqueue("question", {"question": question, "symbols": symbols},
                   f"question:{_today()}:{_digest(question, ','.join(symbols))}", session)


def list_jobs(status: str | None = None, limit: int = 50, session: Session | None = None) -> list[dict]:
    with _session(session) as db:
        query = select(ResearchJob).order_by(col(ResearchJob.created_at).desc()).limit(max(1, min(limit, 200)))
        if status:
            query = query.where(ResearchJob.status == status)
        return [view(job) for job in db.exec(query)]


def _job(db: Session, job_id: str | uuid.UUID) -> ResearchJob:
    try:
        job = db.get(ResearchJob, uuid.UUID(str(job_id)))
    except ValueError:
        job = None
    if job is None:
        raise QueueError("not_found", "No such research job.")
    return job


def get(job_id: str | uuid.UUID, session: Session | None = None) -> dict:
    with _session(session) as db:
        return view(_job(db, job_id))


def cancel(job_id: str | uuid.UUID, session: Session | None = None) -> dict:
    """Cancel a queued or running job; a running job is stopped by the runner. Finished jobs are unchanged."""
    with _session(session) as db:
        job = _job(db, job_id)
        if job.status in ACTIVE:
            job.status, job.finished_at = "cancelled", datetime.utcnow()
            db.add(job)
            db.commit()
            db.refresh(job)
        return view(job)


# --------------------------------------------------------------------------- the runner's side

def spent_today(session: Session | None = None) -> float:
    """Cost of jobs finished since midnight UTC (API-equivalent on the plan)."""
    start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    with _session(session) as db:
        jobs = db.exec(select(ResearchJob).where(col(ResearchJob.finished_at) >= start))
        return round(sum(job.cost_usd or 0.0 for job in jobs), 6)


def requeue_interrupted(session: Session | None = None) -> int:
    """Jobs left running by a stopped process go back to the queue (their attempt still counts)."""
    with _session(session) as db:
        jobs = list(db.exec(select(ResearchJob).where(ResearchJob.status == "running")))
        for job in jobs:
            job.status, job.error, job.next_attempt_at = "queued", "interrupted by a restart", datetime.utcnow()
            if job.attempts >= MAX_ATTEMPTS:
                job.status, job.finished_at = "failed", datetime.utcnow()
            db.add(job)
        db.commit()
        return len(jobs)


def claim_next(session: Session | None = None) -> dict | None:
    with _session(session) as db:
        job = db.exec(select(ResearchJob).where(ResearchJob.status == "queued", col(ResearchJob.next_attempt_at) <= datetime.utcnow())
                      .order_by(col(ResearchJob.created_at)).limit(1)).first()
        if job is None:
            return None
        job.status, job.attempts, job.started_at = "running", job.attempts + 1, datetime.utcnow()
        db.add(job)
        db.commit()
        db.refresh(job)
        return view(job)


def status_of(job_id: str, session: Session | None = None) -> str:
    with _session(session) as db:
        return _job(db, job_id).status


def record_outcome(job_id: str, *, cost_usd: float | None, investigation_id: str | None, error: dict | None,
                   session: Session | None = None) -> dict:
    """Done, retry later, or failed. A job cancelled while it ran stays cancelled but keeps its cost and result."""
    with _session(session) as db:
        job = _job(db, job_id)
        job.cost_usd = round((job.cost_usd or 0.0) + (cost_usd or 0.0), 6) if cost_usd is not None else job.cost_usd
        if investigation_id:
            job.investigation_id = uuid.UUID(investigation_id)
        now = datetime.utcnow()
        if job.status == "running":
            if error is None:
                job.status, job.error, job.finished_at = "done", None, now
            else:
                job.error = f"{error.get('code')}: {error.get('message')}"[:500]
                if error.get("code") in RETRYABLE and job.attempts < MAX_ATTEMPTS:
                    job.status = "queued"
                    job.next_attempt_at = now + timedelta(seconds=BACKOFF_S[min(job.attempts, len(BACKOFF_S)) - 1])
                else:
                    job.status, job.finished_at = "failed", now
        db.add(job)
        db.commit()
        db.refresh(job)
        return view(job)


# --------------------------------------------------------------------------- triggers

def enqueue_radar_events(store_path: str, session_date: str | None = None, session: Session | None = None) -> int:
    """One radar_event job per event in the session (default today), read only from the Radar store."""
    from app.engine.radar_store import RadarStore
    created = 0
    for event in RadarStore(store_path, read_only=True).events(session_date or _today()):
        _, new = enqueue("radar_event", {"event_id": event["event_id"]}, f"radar_event:{event['event_id']}", session)
        created += new
    return created


def enqueue_reassessments(after_hours: int, session: Session | None = None) -> int:
    """At most one reassess job a day for each open investigation not updated in ``after_hours``."""
    cutoff = datetime.utcnow() - timedelta(hours=after_hours)
    with _session(session) as db:
        stale = [str(row.id) for row in db.exec(select(CopilotInvestigation).where(
            CopilotInvestigation.status == "open", col(CopilotInvestigation.updated_at) < cutoff))]
    created = 0
    for investigation_id in stale:
        _, new = enqueue("reassess", {"investigation_id": investigation_id},
                         f"reassess:{investigation_id}:{_today()}", session)
        created += new
    return created


# --------------------------------------------------------------------------- what a job asks

def assignment(job: dict) -> tuple[str, list[str], str]:
    """(question, symbols, title) for a job. Raises QueueError when its input no longer exists."""
    data = job["input"]
    if job["kind"] == "question":
        return data["question"], data.get("symbols", []), data["question"][:120]
    if job["kind"] == "radar_event":
        from app.engine.radar_store import RadarStore
        store = os.environ.get("RADAR_STORE", "").strip()
        event = RadarStore(store, read_only=True).event(data["event_id"]) if store else None
        if event is None:
            raise QueueError("not_found", f"Radar event {data['event_id']} is not in the Radar store.")
        symbols = [s for s in event.get("symbols", []) if isinstance(s, str)][:8]
        question = (f"Radar recorded this event at {event.get('first_seen_at')} (session {event.get('session_date')}): "
                    f"{event.get('kind')} {event.get('direction')} in {', '.join(symbols) or 'unknown symbols'} versus "
                    f"{event.get('benchmark')}. Summary: {event.get('summary')}. Measures: {json.dumps(event.get('measures'))}. "
                    "Investigate what explains it: search for a catalyst, check whether peers and the sector moved too, "
                    "and say whether the move looks company-specific, sector-wide or noise.")
        return question, symbols, f"Radar: {event.get('summary') or event.get('kind')}"[:120]
    from app.engine import copilot_investigations as inv
    try:
        saved = inv.get(data["investigation_id"])
    except inv.InvestigationError as exc:
        raise QueueError("not_found", str(exc)) from exc
    findings = saved.get("findings") or {}
    earlier = findings.get("summary") or (saved.get("conclusion") or "no saved summary")
    points = "; ".join(findings.get("key_findings", [])[:6])
    question = (f"Reassess a saved investigation, '{saved['title']}', last updated {saved.get('updated_at')}. "
                f"Earlier assessment: {earlier} Earlier key findings: {points or 'none saved'}. "
                "Check whether it still holds with current evidence and news, say what changed since, and cite new sources.")
    return question, [saved["symbol"]] if saved.get("symbol") else [], f"Reassess: {saved['title']}"[:120]


# --------------------------------------------------------------------------- the loop

class QueueRunner:
    """One job at a time in the API process. ``run_job`` is research_job.run_job (injectable for tests)."""

    def __init__(self, cfg: QueueSettings, run_job=None, evidence_factory=None, cancel_poll_s: float = 5.0):
        self.cfg, self.cancel_poll_s = cfg, cancel_poll_s
        self._run_job, self._evidence = run_job, evidence_factory
        self.last_error: str | None = None
        self._last_trigger = 0.0

    def _evidence_for_job(self):
        if self._evidence is not None:
            return self._evidence()
        from app.ai.copilot_tools import LiveEvidence
        return LiveEvidence()

    async def triggers(self, now: float) -> None:
        if now - self._last_trigger < self.cfg.trigger_every_s:
            return
        self._last_trigger = now
        store = os.environ.get("RADAR_STORE", "").strip()
        if self.cfg.radar_trigger and store:
            await asyncio.to_thread(enqueue_radar_events, store)
        if self.cfg.reassess_after_hours > 0:
            await asyncio.to_thread(enqueue_reassessments, self.cfg.reassess_after_hours)

    async def run_once(self) -> dict | None:
        """Claim and run one job if the day's budget allows. Returns the finished job view, or None."""
        from app.ai import research_job
        lim = research_job.limits()
        remaining = self.cfg.daily_budget_usd - await asyncio.to_thread(spent_today)
        if remaining <= 0.05:  # the day's cap is (nearly) used up; nothing runs until tomorrow (UTC)
            return None
        job = await asyncio.to_thread(claim_next)
        if job is None:
            return None
        try:
            question, symbols, title = await asyncio.to_thread(assignment, job)
        except QueueError as exc:
            return await asyncio.to_thread(record_outcome, job["id"], cost_usd=None, investigation_id=None,
                                           error={"code": exc.code, "message": str(exc)})
        from app.engine.chart_math import ET
        run = self._run_job or research_job.run_job
        task = asyncio.create_task(run(question, symbols, self._evidence_for_job(), now=datetime.now(ET), title=title,
                                       lim=research_job.JobLimits(budget_usd=min(lim.budget_usd, remaining))))
        while not task.done():
            await asyncio.wait({task}, timeout=self.cancel_poll_s)
            if not task.done() and await asyncio.to_thread(status_of, job["id"]) == "cancelled":
                task.cancel()
        try:
            record = task.result()
        except asyncio.CancelledError:
            return await asyncio.to_thread(get, job["id"])
        except research_job.ResearchError as exc:
            record = {"error": {"code": exc.code, "message": exc.message}}
        except Exception as exc:  # noqa: BLE001 - recorded on the job; the loop goes on
            record = {"error": {"code": "internal", "message": type(exc).__name__}}
        error = record.get("error") or (None if record.get("saved_id") else
                                        {"code": "save_failed", "message": record.get("save_error") or "not saved"})
        return await asyncio.to_thread(record_outcome, job["id"], cost_usd=(record.get("metrics") or {}).get("cost_usd"),
                                       investigation_id=record.get("saved_id"), error=error)

    async def loop(self) -> None:
        import time
        await asyncio.to_thread(requeue_interrupted)
        while True:
            ran = None
            try:
                await self.triggers(time.monotonic())
                ran = await self.run_once()
                self.last_error = None
            except Exception:
                self.last_error = "Research queue pass failed"
                log.exception("Research queue pass failed")
            if ran is None:
                await asyncio.sleep(self.cfg.idle_s)
