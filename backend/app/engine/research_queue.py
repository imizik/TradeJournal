"""Copilot Lab research queue (docs/copilot-lab.md § Research queue).

Queued background research jobs, run one at a time inside the API process by
``QueueRunner`` when ``RESEARCH_QUEUE_ENABLED=true`` (default off). A job is a
question, a Radar event, or a saved investigation to reassess. It runs through
``app.ai.research_job`` and its result is saved as a saved investigation. The
runner retries transient failures with backoff, honours cancel, caps each job's
budget and the day's total (``RESEARCH_DAILY_BUDGET_USD``, default $2), and
records failures on the job.

Spend is charged per attempt. When an attempt starts, its whole budget is charged
as an estimate; it is replaced by the real cost once one is known. An attempt
that times out, fails, is cancelled or is cut off by a restart keeps the
estimate, so the daily cap never misses spend.

Two optional triggers enqueue work, both off by default:

- ``RESEARCH_RADAR_TRIGGER=true``: each new Radar event in today's session,
  read only from ``RADAR_STORE``, gets one ``radar_event`` job.
- ``RESEARCH_REASSESS_AFTER_HOURS=N``: each original open investigation (not a
  reassessment's own output) not updated and not reassessed in N hours gets one
  ``reassess`` job, at most one a day.

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
from datetime import UTC, datetime, timedelta
from typing import Iterator

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from app.models import CopilotInvestigation, ResearchJob

log = logging.getLogger(__name__)

KINDS = ("question", "radar_event", "reassess")
ACTIVE = ("queued", "running")
MAX_ATTEMPTS = 3
BACKOFF_S = (60, 300)  # before the 2nd and 3rd attempt
# Failures worth another attempt; anything else (auth, budget, bad input) fails at once.
RETRYABLE = {"timeout", "sdk", "no_result", "no_assessment"}
MIN_JOB_BUDGET_USD = 0.05  # below what is left of the day, nothing starts


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


def _number(name: str, default, cast):
    """A malformed value falls back with a warning instead of stopping the API."""
    raw = os.environ.get(name)
    if raw in (None, ""):
        return default
    try:
        return cast(raw)
    except ValueError:
        log.warning("%s=%r is not a number; using %s", name, raw, default)
        return default


def settings() -> QueueSettings:
    return QueueSettings(
        enabled=os.environ.get("RESEARCH_QUEUE_ENABLED") == "true",
        daily_budget_usd=_number("RESEARCH_DAILY_BUDGET_USD", 2.0, float),
        radar_trigger=os.environ.get("RESEARCH_RADAR_TRIGGER") == "true",
        reassess_after_hours=_number("RESEARCH_REASSESS_AFTER_HOURS", 0, int),
    )


@contextmanager
def _session(session: Session | None) -> Iterator[Session]:
    if session is not None:
        yield session
        return
    from app.database import engine
    with Session(engine) as own:
        yield own


def _utcnow() -> datetime:
    """Naive UTC, like the model's timestamps. One clock for the module, so tests can move it."""
    return datetime.now(UTC).replace(tzinfo=None)


def _today() -> str:
    from app.engine.chart_math import ET
    return _utcnow().replace(tzinfo=UTC).astimezone(ET).date().isoformat()


def _digest(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()[:24]


def _spend(job: ResearchJob) -> list[dict]:
    return json.loads(job.spend_json or "[]")


def view(job: ResearchJob) -> dict:
    return {"id": str(job.id), "kind": job.kind, "input": json.loads(job.input_json), "status": job.status,
            "attempts": job.attempts, "error": job.error, "cost_usd": job.cost_usd, "spend": _spend(job),
            "investigation_id": str(job.investigation_id) if job.investigation_id else None,
            "created_at": job.created_at.isoformat(), "next_attempt_at": job.next_attempt_at.isoformat(),
            "started_at": job.started_at and job.started_at.isoformat(),
            "finished_at": job.finished_at and job.finished_at.isoformat()}


# --------------------------------------------------------------------------- enqueue / list / cancel

def enqueue(kind: str, payload: dict, dedupe_key: str, session: Session | None = None) -> tuple[dict, bool]:
    """Queue a job unless one with the same dedupe key exists. Returns (job, created)."""
    if kind not in KINDS:
        raise QueueError("bad_input", f"unknown job kind {kind!r}")
    with _session(session) as db:
        existing = db.exec(select(ResearchJob).where(ResearchJob.dedupe_key == dedupe_key)).first()
        if existing is not None:
            return view(existing), False
        now = _utcnow()
        job = ResearchJob(kind=kind, input_json=json.dumps(payload), dedupe_key=dedupe_key, created_at=now,
                          next_attempt_at=now)
        db.add(job)
        try:
            db.commit()
        except IntegrityError:  # another writer queued the same key between the read and the insert
            db.rollback()
            return view(db.exec(select(ResearchJob).where(ResearchJob.dedupe_key == dedupe_key)).one()), False
        db.refresh(job)
        return view(job), True


def enqueue_question(question: str, symbols: list[str], session: Session | None = None,
                     from_investigation: str | None = None) -> tuple[dict, bool]:
    """The same question and symbols are queued at most once per day. ``from_investigation`` only records the saved
    investigation the owner asked from, so the lab can show the job there; the job does not read it."""
    question = question.strip()
    if not question:
        raise QueueError("bad_input", "question is empty")
    payload = {"question": question, "symbols": symbols, **({"from_investigation": from_investigation} if from_investigation else {})}
    return enqueue("question", payload,
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
            job.status, job.finished_at = "cancelled", _utcnow()
            db.add(job)
            db.commit()
            db.refresh(job)
        return view(job)


# --------------------------------------------------------------------------- spend and claiming

def _day_start() -> datetime:
    return _utcnow().replace(hour=0, minute=0, second=0, microsecond=0)


def spent_today(session: Session | None = None) -> float:
    """Spend charged for attempts started since midnight UTC, estimates included (API-equivalent on the plan)."""
    start = _day_start()
    with _session(session) as db:
        jobs = db.exec(select(ResearchJob).where(col(ResearchJob.started_at) >= start))
        return round(sum(entry["usd"] for job in jobs for entry in _spend(job)
                         if datetime.fromisoformat(entry["at"]) >= start), 6)


def claim_next(job_budget_usd: float, daily_budget_usd: float, session: Session | None = None) -> dict | None:
    """Start the next due attempt if the day's cap allows, charging its budget as an estimate. The view's
    ``budget_usd`` is that attempt's budget (the per-job budget, capped by what is left of the day)."""
    with _session(session) as db:
        remaining = daily_budget_usd - spent_today(db)
        if remaining < MIN_JOB_BUDGET_USD:
            return None
        now = _utcnow()
        job = db.exec(select(ResearchJob).where(ResearchJob.status == "queued", col(ResearchJob.next_attempt_at) <= now)
                      .order_by(col(ResearchJob.created_at)).limit(1)).first()
        if job is None:
            return None
        budget = round(min(job_budget_usd, remaining), 6)
        spend = [*_spend(job), {"at": now.isoformat(), "usd": budget, "estimated": True}]
        # Conditional, so two claimers can never both start the same attempt.
        claimed = db.exec(update(ResearchJob).where(col(ResearchJob.id) == job.id, col(ResearchJob.status) == "queued")
                          .values(status="running", attempts=job.attempts + 1, started_at=now,
                                  spend_json=json.dumps(spend), cost_usd=round(sum(e["usd"] for e in spend), 6)))
        db.commit()
        if claimed.rowcount != 1:
            return None
        db.refresh(job)
        return {**view(job), "budget_usd": budget}


def status_of(job_id: str, session: Session | None = None) -> str:
    with _session(session) as db:
        return _job(db, job_id).status


def _settle(job: ResearchJob, cost_usd: float | None) -> None:
    """Replace the current attempt's estimate with its real cost, when one is known."""
    spend = _spend(job)
    if cost_usd is not None and spend and spend[-1].get("estimated"):
        spend[-1] = {**spend[-1], "usd": round(float(cost_usd), 6), "estimated": False}
    job.spend_json = json.dumps(spend)
    job.cost_usd = round(sum(e["usd"] for e in spend), 6) if spend else job.cost_usd


def record_outcome(job_id: str, *, cost_usd: float | None, investigation_id: str | None, error: dict | None,
                   session: Session | None = None) -> dict:
    """Done, retry later, or failed. A job cancelled while it ran stays cancelled but keeps its spend and result.
    ``cost_usd`` None means unknown: the attempt keeps its estimated charge."""
    with _session(session) as db:
        job = _job(db, job_id)
        _settle(job, cost_usd)
        if investigation_id:
            job.investigation_id = uuid.UUID(investigation_id)
        now = _utcnow()
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


def _interrupt(job: ResearchJob, reason: str) -> None:
    job.error, job.next_attempt_at = reason, _utcnow()
    job.status = "queued" if job.attempts < MAX_ATTEMPTS else "failed"
    if job.status == "failed":
        job.finished_at = _utcnow()


def interrupt(job_id: str, reason: str, session: Session | None = None) -> dict:
    """A running attempt cut off by a shutdown goes back to the queue; its estimated charge stays."""
    with _session(session) as db:
        job = _job(db, job_id)
        if job.status == "running":
            _interrupt(job, reason)
            db.add(job)
            db.commit()
            db.refresh(job)
        return view(job)


def requeue_interrupted(session: Session | None = None) -> int:
    """Jobs left running by a stopped process go back to the queue (their attempt and its charge still count)."""
    with _session(session) as db:
        jobs = list(db.exec(select(ResearchJob).where(ResearchJob.status == "running")))
        for job in jobs:
            _interrupt(job, "interrupted by a restart")
            db.add(job)
        db.commit()
        return len(jobs)


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
    """One reassess job for each original open investigation that has been neither updated nor reassessed for
    ``after_hours``, and has no job waiting. A reassessment's own output is never reassessed; at most one a day."""
    cutoff = _utcnow() - timedelta(hours=after_hours)
    with _session(session) as db:
        jobs = list(db.exec(select(ResearchJob).where(ResearchJob.kind == "reassess")))
        outputs = {str(job.investigation_id) for job in jobs if job.investigation_id}
        recent = {json.loads(job.input_json)["investigation_id"] for job in jobs
                  if job.status in ACTIVE or job.created_at >= cutoff}
        stale = [str(row.id) for row in db.exec(select(CopilotInvestigation).where(
            CopilotInvestigation.status == "open", col(CopilotInvestigation.updated_at) < cutoff))]
    created = 0
    for investigation_id in stale:
        if investigation_id in outputs or investigation_id in recent:
            continue
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
        if not store or not os.path.isabs(store) or not os.path.isfile(store):
            raise QueueError("not_found", "RADAR_STORE is not an existing absolute path.")
        event = RadarStore(store, read_only=True).event(data["event_id"])
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
        self._last_trigger: float | None = None

    def _evidence_for_job(self):
        if self._evidence is not None:
            return self._evidence()
        from app.ai.copilot_tools import LiveEvidence
        return LiveEvidence()

    async def triggers(self, now: float) -> None:
        if self._last_trigger is not None and now - self._last_trigger < self.cfg.trigger_every_s:
            return
        self._last_trigger = now
        store = os.environ.get("RADAR_STORE", "").strip()
        if self.cfg.radar_trigger and store:
            await asyncio.to_thread(enqueue_radar_events, store)
        if self.cfg.reassess_after_hours > 0:
            await asyncio.to_thread(enqueue_reassessments, self.cfg.reassess_after_hours)

    async def _outcome(self, job_id: str, *, cost_usd=None, investigation_id=None, error=None) -> dict:
        return await asyncio.to_thread(record_outcome, job_id, cost_usd=cost_usd, investigation_id=investigation_id,
                                       error=error)

    async def run_once(self) -> dict | None:
        """Start one attempt if one is due and the day's cap allows. Returns the job view after it, or None."""
        from app.ai import research_job
        job = await asyncio.to_thread(claim_next, research_job.limits().budget_usd, self.cfg.daily_budget_usd)
        if job is None:
            return None
        try:
            question, symbols, title = await asyncio.to_thread(assignment, job)
            evidence = self._evidence_for_job()
        except QueueError as exc:  # nothing ran: no cost
            return await self._outcome(job["id"], cost_usd=0.0, error={"code": exc.code, "message": str(exc)})
        except Exception as exc:  # noqa: BLE001 - a broken input or store fails the job instead of leaving it running
            return await self._outcome(job["id"], cost_usd=0.0,
                                       error={"code": "input_error", "message": f"{type(exc).__name__}: {exc}"[:300]})
        from app.engine.chart_math import ET
        run = self._run_job or research_job.run_job
        task = asyncio.create_task(run(question, symbols, evidence, now=datetime.now(ET), title=title,
                                       lim=research_job.JobLimits(budget_usd=job["budget_usd"])))
        try:
            while not task.done():
                await asyncio.wait({task}, timeout=self.cancel_poll_s)
                if not task.done() and await asyncio.to_thread(status_of, job["id"]) == "cancelled":
                    task.cancel()
        except asyncio.CancelledError:
            # The API is shutting down: stop the attempt, and put the job back with its charge kept.
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await asyncio.shield(asyncio.to_thread(interrupt, job["id"], "interrupted by a shutdown"))
            raise
        try:
            record = task.result()
        except asyncio.CancelledError:  # cancelled by the owner; the attempt's cost is unknown, its estimate stays
            return await self._outcome(job["id"], error={"code": "cancelled", "message": "cancelled while running"})
        except research_job.ResearchError as exc:  # refused before any model call
            return await self._outcome(job["id"], cost_usd=0.0, error={"code": exc.code, "message": exc.message})
        except Exception as exc:  # noqa: BLE001 - recorded on the job; the loop goes on
            return await self._outcome(job["id"], error={"code": "internal", "message": type(exc).__name__})
        error = record.get("error") or (None if record.get("saved_id") else
                                        {"code": "save_failed", "message": record.get("save_error") or "not saved"})
        return await self._outcome(job["id"], cost_usd=(record.get("metrics") or {}).get("cost_usd"),
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
            except asyncio.CancelledError:
                raise
            except Exception:
                self.last_error = "Research queue pass failed"
                log.exception("Research queue pass failed")
            if ran is None:
                await asyncio.sleep(self.cfg.idle_s)
