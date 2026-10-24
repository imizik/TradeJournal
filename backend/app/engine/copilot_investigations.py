"""Saved Copilot Lab investigations and research results (docs/copilot-lab.md).

One record for two writers: the interactive copilot (``source="copilot"``, saved by the lab page) and background
research jobs (``source="research_job"``, saved in-process with ``save_research_result``). A record holds text and
references only: a transcript, evidence references (tool + as-of, never the data) and optional cited findings.
Nothing here creates or links follow-ups, plans, decisions, memories or watches.

Plain Python, no HTTP: pass a ``Session`` or let each call open its own.
"""
from __future__ import annotations

import json
import uuid
from contextlib import contextmanager
from datetime import datetime
from typing import Iterator, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlmodel import Session, select

from app.models import CopilotInvestigation

SYMBOL_PATTERN = r"^[A-Z][A-Z0-9.\-]{0,9}$"
MAX_TRANSCRIPT_CHARS = 400_000
Source = Literal["copilot", "research_job"]


class InvestigationError(ValueError):
    """``code`` is ``not_found``, ``stale`` or ``too_long``."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SavedMessage(_Strict):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=20_000)


class EvidenceRef(_Strict):
    """Which tool a result relied on and how old its data was; never the data."""
    tool: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    as_of: str | float | None = None
    # "proposal" only so a page saved before proposals were left out of evidence still saves.
    kind: Literal["recorded", "fetched", "cached", "simulated", "replay", "saved", "proposal"] | None = None
    message: int | None = Field(None, ge=0)  # transcript index of the answer that used it


class Citation(_Strict):
    url: str = Field(max_length=500)
    publisher: str | None = Field(None, max_length=120)
    published_at: str | None = Field(None, max_length=40)
    title: str | None = Field(None, max_length=300)

    @field_validator("url")
    @classmethod
    def web_url(cls, value: str) -> str:
        if not value.startswith(("https://", "http://")):
            raise ValueError("citation url must be http(s)")
        return value


class Findings(_Strict):
    summary: str = Field(min_length=1, max_length=2000)
    key_findings: list[str] = Field(default_factory=list, max_length=12)
    counterpoints: list[str] = Field(default_factory=list, max_length=12)
    what_would_change: list[str] = Field(default_factory=list, max_length=8)
    citations: list[Citation] = Field(default_factory=list, max_length=30)
    # The market moment the evidence describes, when it is not "now" (a replay job): ISO 8601 with an offset.
    evidence_at: str | None = Field(None, max_length=40)

    @field_validator("evidence_at")
    @classmethod
    def aware_time(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError("evidence_at must be an ISO 8601 time")
        if parsed.tzinfo is None:
            raise ValueError("evidence_at needs a UTC offset")
        return parsed.isoformat()

    @field_validator("key_findings", "counterpoints", "what_would_change")
    @classmethod
    def short_items(cls, items: list[str]) -> list[str]:
        if any(len(item) > 500 for item in items):
            raise ValueError("each item is at most 500 characters")
        return items


class InvestigationFields(_Strict):
    title: str = Field(min_length=1, max_length=120)
    symbol: str | None = Field(None, pattern=SYMBOL_PATTERN)
    status: Literal["open", "closed"] = "open"
    conclusion: str | None = Field(None, max_length=280)
    transcript: list[SavedMessage] = Field(default_factory=list, max_length=200)
    evidence: list[EvidenceRef] = Field(default_factory=list, max_length=400)
    findings: Findings | None = None  # None on an update keeps the saved findings


@contextmanager
def _session(session: Session | None) -> Iterator[Session]:
    if session is not None:
        yield session
        return
    from app.database import engine
    with Session(engine) as own:
        yield own


def summary(row: CopilotInvestigation) -> dict:
    return {"id": str(row.id), "source": row.source, "title": row.title, "symbol": row.symbol, "status": row.status,
            "conclusion": row.conclusion, "revision": row.revision, "message_count": len(json.loads(row.transcript_json)),
            "has_findings": row.findings_json is not None,
            "created_at": row.created_at.isoformat() + "Z", "updated_at": row.updated_at.isoformat() + "Z"}


def full(row: CopilotInvestigation) -> dict:
    return {**summary(row), "transcript": json.loads(row.transcript_json), "evidence": json.loads(row.evidence_json),
            "findings": json.loads(row.findings_json) if row.findings_json else None}


def _fill(row: CopilotInvestigation, fields: InvestigationFields) -> None:
    transcript = [m.model_dump() for m in fields.transcript]
    if sum(len(m["content"]) for m in transcript) > MAX_TRANSCRIPT_CHARS:
        raise InvestigationError("too_long", "This investigation is too long to save; start a new one.")
    row.title, row.symbol, row.status = fields.title.strip() or "Untitled", fields.symbol, fields.status
    row.conclusion = (fields.conclusion or "").strip() or None
    row.transcript_json = json.dumps(transcript)
    row.evidence_json = json.dumps([e.model_dump(exclude_none=True) for e in fields.evidence])
    if fields.findings is not None:
        row.findings_json = json.dumps(fields.findings.model_dump(exclude_none=True))


def _row(db: Session, investigation_id: str | uuid.UUID) -> CopilotInvestigation:
    try:
        key = investigation_id if isinstance(investigation_id, uuid.UUID) else uuid.UUID(str(investigation_id))
    except ValueError:
        raise InvestigationError("not_found", "No such investigation.")
    row = db.get(CopilotInvestigation, key)
    if row is None:
        raise InvestigationError("not_found", "No such investigation.")
    return row


def create(fields: InvestigationFields, source: Source = "copilot", session: Session | None = None) -> dict:
    with _session(session) as db:
        row = CopilotInvestigation(source=source, title=fields.title, transcript_json="[]", evidence_json="[]")
        _fill(row, fields)
        db.add(row)
        db.commit()
        db.refresh(row)
        return full(row)


def update(investigation_id: str | uuid.UUID, fields: InvestigationFields, revision: int,
           session: Session | None = None) -> dict:
    """Replace the record's fields; ``revision`` must be the one it was read at. The source never changes."""
    with _session(session) as db:
        row = _row(db, investigation_id)
        if revision != row.revision:
            raise InvestigationError("stale", "This investigation changed in another window. Reload it before saving.")
        _fill(row, fields)
        row.revision += 1
        row.updated_at = datetime.utcnow()
        db.add(row)
        db.commit()
        db.refresh(row)
        return full(row)


def get(investigation_id: str | uuid.UUID, session: Session | None = None) -> dict:
    with _session(session) as db:
        return full(_row(db, investigation_id))


def list_investigations(symbol: str | None = None, source: Source | None = None, limit: int = 20,
                        before: datetime | None = None, session: Session | None = None) -> list[dict]:
    """Newest first, summaries only. ``before`` (naive UTC) keeps records created at or before that moment."""
    query = select(CopilotInvestigation)
    if symbol:
        query = query.where(CopilotInvestigation.symbol == symbol.upper())
    if source:
        query = query.where(CopilotInvestigation.source == source)
    if before is not None:
        query = query.where(CopilotInvestigation.created_at <= before)
    query = query.order_by(CopilotInvestigation.updated_at.desc()).limit(max(1, min(limit, 50)))
    with _session(session) as db:
        return [summary(r) for r in db.exec(query).all()]


def save_research_result(*, title: str, symbol: str | None, findings: Findings | dict,
                         evidence: list[EvidenceRef | dict] = (), transcript: list[SavedMessage | dict] = (),
                         conclusion: str | None = None, evidence_at: str | None = None,
                         session: Session | None = None) -> dict:
    """Save one finished background research job as an open record for the owner to review. ``evidence_at`` is the
    frozen moment of a replay job, so a replay of that moment can see it. Validates everything; raises
    pydantic.ValidationError on bad input."""
    if evidence_at is not None:
        findings = {**(findings.model_dump(exclude_none=True) if isinstance(findings, Findings) else findings),
                    "evidence_at": evidence_at}
    fields = InvestigationFields(title=title, symbol=symbol, conclusion=conclusion, findings=findings,
                                 evidence=list(evidence), transcript=list(transcript))
    return create(fields, source="research_job", session=session)
