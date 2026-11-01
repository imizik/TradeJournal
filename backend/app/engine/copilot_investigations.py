"""Saved Copilot Lab investigations and research results (docs/copilot-lab.md).

One record for three writers: the interactive copilot (``source="copilot"``, saved by the lab page), background
research jobs (``source="research_job"``, saved in-process with ``save_research_result``) and Jo's imported research
(``source="jo"``, ``save_jo_result``; docs/agent/dots-integration.md § Jo research role). A record holds text and
references only: a transcript, evidence references (tool + as-of, never the data) and optional cited findings.
An answer's proposal cards ride in its message with what the owner did with each (``outcome``), so a card comes back
after a reload as it was left. Nothing here creates or links follow-ups, plans, decisions, memories or watches: a
stored card is only a card, and Confirm on the page is still the only way anything is made.

Plain Python, no HTTP: pass a ``Session`` or let each call open its own.
"""
from __future__ import annotations

import json
import math
import re
import uuid
from contextlib import contextmanager
from datetime import datetime
from typing import Iterator, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import or_
from sqlmodel import Session, select

from app.models import CopilotInvestigation

SYMBOL_PATTERN = r"^[A-Z][A-Z0-9.\-]{0,9}$"
MAX_TRANSCRIPT_CHARS = 400_000  # message text and stored cards together
MAX_PROPOSALS = 4  # per answer: it may make two, and a week review's practice card can join them
PROPOSAL_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,120}$")
CLIENT_ID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")  # what the capture, time-stop and memory saves replay on
Source = Literal["copilot", "research_job", "jo"]


class InvestigationError(ValueError):
    """``code`` is ``not_found``, ``stale`` or ``too_long``."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PartResult(_Strict):
    state: Literal["done", "failed"]
    text: str = Field("", max_length=500)


class PlanFields(_Strict):
    """A confirmed plan card's fields as the owner left them (the inputs' text)."""
    thesis: str = Field("", max_length=300)
    contract: str = Field("", max_length=80)
    entry: str = Field("", max_length=24)
    invalidation: str = Field("", max_length=24)
    time_stop: str = Field("", max_length=80)
    size_note: str = Field("", max_length=120)
    horizon: Literal["", "day", "swing", "long"] = ""  # how often the desk checks in (day_journal.HORIZONS)


class ProposalOutcome(_Strict):
    """What the owner did with a card. ``confirmed``: Confirm ran (``note`` is what it said, ``text`` the words a memory
    or practice saved; a plan card keeps each part's result and its fields). ``dismissed``: the card stays hidden."""
    state: Literal["confirmed", "dismissed"]
    note: str | None = Field(None, max_length=500)
    text: str | None = Field(None, max_length=4000)
    parts: dict[Literal["plan", "entry", "invalidation", "timeStop"], PartResult] | None = None
    fields: PlanFields | None = None


def _saved_proposal(card: dict) -> dict:
    """One stored card: the proposal as propose_plan validated it, its id, the price it was drafted at, the card's
    client id and its outcome. Raises ValueError for anything else."""
    from app.ai import copilot_tools
    if not isinstance(card, dict):
        raise ValueError("a proposal is an object")
    rest = dict(card)
    pid, client_id, outcome = rest.pop("id", None), rest.pop("client_id", None), rest.pop("outcome", None)
    last, as_of = rest.pop("last", None), rest.pop("as_of", None)
    if not isinstance(pid, str) or not PROPOSAL_ID.match(pid):
        raise ValueError("a proposal needs its id")
    if client_id is not None and (not isinstance(client_id, str) or not CLIENT_ID.match(client_id)):
        raise ValueError("a proposal's client_id is 8-64 letters, digits, - or _")
    if last is not None and (isinstance(last, bool) or not isinstance(last, (int, float)) or not math.isfinite(last) or last <= 0):
        raise ValueError("a proposal's last price must be positive")
    if as_of is not None and not (isinstance(as_of, (int, float)) and not isinstance(as_of, bool) or isinstance(as_of, str) and len(as_of) <= 40):
        raise ValueError("a proposal's as_of is a time")
    if rest.get("kind") == "practice":
        rest.pop("label", None)  # derived from the measure and target
    try:
        out = {"id": pid, **copilot_tools._proposal(rest)}
    except copilot_tools.ToolInputError as exc:
        raise ValueError(f"proposal {pid}: {exc}") from None
    if out["kind"] in ("watch", "trade_plan"):
        out.update({k: v for k, v in (("last", last), ("as_of", as_of)) if v is not None})
    if client_id is not None:
        out["client_id"] = client_id
    if outcome is not None:
        try:
            out["outcome"] = ProposalOutcome.model_validate(outcome).model_dump(exclude_none=True)
        except ValidationError as exc:
            raise ValueError(f"proposal {pid} outcome: {exc.errors()[0]['msg']}") from None
    return out


class AnswerMetrics(_Strict):
    """How one answer went: the speed, model and tool names of its turn, and the error code if it ended in one."""
    first_text_ms: int | None = Field(None, ge=0, le=3_600_000)
    total_ms: int | None = Field(None, ge=0, le=3_600_000)
    rounds: int | None = Field(None, ge=0, le=1000)
    model: str | None = Field(None, max_length=80)
    backend: str | None = Field(None, max_length=40)
    tools: list[str] | None = Field(None, max_length=50)
    error: str | None = Field(None, max_length=80)

    @field_validator("tools")
    @classmethod
    def short_names(cls, names: list[str] | None) -> list[str] | None:
        if names and any(len(n) > 64 for n in names):
            raise ValueError("a tool name is at most 64 characters")
        return names


class SavedMessage(_Strict):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=20_000)
    rating: Literal["helped", "didnt"] | None = None  # the owner's one-tap verdict on an answer; absent on older records
    metrics: AnswerMetrics | None = None
    proposals: list[dict] | None = Field(None, max_length=MAX_PROPOSALS)  # an answer's cards; absent on older records

    @field_validator("proposals")
    @classmethod
    def valid_cards(cls, cards: list[dict] | None) -> list[dict] | None:
        if not cards:
            return None
        return [_saved_proposal(card) for card in cards]


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
    # Jo's full research text (source "jo"): kept here, a tool result, never as a transcript answer.
    report: str | None = Field(None, max_length=12_000)
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

    @field_validator("transcript")
    @classmethod
    def one_card_per_id(cls, transcript: list[SavedMessage]) -> list[SavedMessage]:
        ids = [p["id"] for m in transcript for p in m.proposals or ()]
        if len(set(ids)) != len(ids):
            raise ValueError("each proposal in an investigation has its own id")  # its outcome is recorded by id
        return transcript


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


def _outcomes(transcript: list[dict]) -> dict[str, dict]:
    return {p["id"]: p["outcome"] for m in transcript for p in m.get("proposals") or () if p.get("outcome")}


def _kept(outcome: dict | None, stored: dict | None) -> dict | None:
    """A saved outcome is never lost to a save from a window that had not seen it, and a confirmed card stays
    confirmed (a dismiss elsewhere cannot hide what was made)."""
    if stored is None or (outcome is not None and (outcome["state"] == "confirmed" or stored["state"] == "dismissed")):
        return outcome
    return stored


def _fill(row: CopilotInvestigation, fields: InvestigationFields, stored: dict[str, dict] | None = None,
          stored_ratings: dict[int, tuple[str, str]] | None = None) -> None:
    transcript = [m.model_dump(exclude_none=True) for m in fields.transcript]
    for i, m in enumerate(transcript):  # a rating tapped in another window is not lost to a save that had not seen it
        kept = (stored_ratings or {}).get(i)
        if kept and "rating" not in m and m["role"] == "assistant" and m["content"] == kept[1]:
            m["rating"] = kept[0]
    for card in (p for m in transcript for p in m.get("proposals") or ()):
        if (outcome := _kept(card.get("outcome"), (stored or {}).get(card["id"]))) is not None:
            card["outcome"] = outcome
    size = sum(len(m["content"]) + (len(json.dumps(m["proposals"])) if "proposals" in m else 0) for m in transcript)
    if size > MAX_TRANSCRIPT_CHARS:
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
        stored = json.loads(row.transcript_json)
        _fill(row, fields, _outcomes(stored), {i: (m["rating"], m["content"]) for i, m in enumerate(stored) if m.get("rating")})
        row.revision += 1
        row.updated_at = datetime.utcnow()
        db.add(row)
        db.commit()
        db.refresh(row)
        return full(row)


def set_outcome(investigation_id: str | uuid.UUID, proposal_id: str, outcome: ProposalOutcome,
                session: Session | None = None) -> dict:
    """Record what the owner did with one saved card (Confirm or Dismiss). It records a result and changes nothing
    the owner wrote, so it needs no revision and does not bump it: an open window's next save still fits, and keeps
    this outcome (``_kept``)."""
    with _session(session) as db:
        row = _row(db, investigation_id)
        transcript = json.loads(row.transcript_json)
        card = next((p for m in transcript for p in m.get("proposals") or () if p.get("id") == proposal_id), None)
        if card is None:
            raise InvestigationError("not_found", "That card is not saved with this investigation.")
        kept = _kept(outcome.model_dump(exclude_none=True), card.get("outcome"))
        if kept != card.get("outcome"):
            card["outcome"] = kept
            row.transcript_json = json.dumps(transcript)
            row.updated_at = datetime.utcnow()
            db.add(row)
            db.commit()
            db.refresh(row)
        return full(row)


def set_rating(investigation_id: str | uuid.UUID, index: int, rating: str | None, session: Session | None = None) -> dict:
    """Record (or clear, with None) the owner's rating of the saved answer at ``index``. Like ``set_outcome`` it needs
    no revision and does not bump it; the next save from an open window keeps it."""
    with _session(session) as db:
        row = _row(db, investigation_id)
        transcript = json.loads(row.transcript_json)
        if not 0 <= index < len(transcript) or transcript[index]["role"] != "assistant":
            raise InvestigationError("not_found", "That answer is not saved with this investigation.")
        if transcript[index].get("rating") != rating:
            if rating is None:
                transcript[index].pop("rating", None)
            else:
                transcript[index]["rating"] = rating
            row.transcript_json = json.dumps(transcript)
            row.updated_at = datetime.utcnow()
            db.add(row)
            db.commit()
            db.refresh(row)
        return full(row)


def get(investigation_id: str | uuid.UUID, session: Session | None = None) -> dict:
    with _session(session) as db:
        return full(_row(db, investigation_id))


def list_investigations(symbol: str | None = None, source: Source | None = None, limit: int = 20,
                        before: datetime | None = None, search: str | None = None, session: Session | None = None) -> list[dict]:
    """Newest first, summaries only. ``before`` (naive UTC) keeps records created at or before that moment. ``search``
    keeps records whose title, symbol or conclusion holds every word, ignoring case."""
    query = select(CopilotInvestigation)
    for word in (search or "").split():
        pattern = "%" + word.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        query = query.where(or_(*(column.ilike(pattern, escape="\\") for column in (
            CopilotInvestigation.title, CopilotInvestigation.symbol, CopilotInvestigation.conclusion))))
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


def save_jo_result(*, investigation_id: uuid.UUID, title: str, symbol: str | None, findings: Findings | dict,
                   transcript: list[SavedMessage | dict], conclusion: str | None = None, also: list = (),
                   session: Session) -> dict:
    """Save one imported Jo research submission as a closed record (source ``jo``), committed together with ``also``
    (its import row and, for a red team, the answered request). Closed, because open records are what the thesis
    watch pings about, the research queue reassesses and the desk lists as the owner's threads; Jo's research is read
    through ``get_saved_research`` and the plan card instead. Raises pydantic.ValidationError on bad input."""
    fields = InvestigationFields(title=title, symbol=symbol, status="closed", conclusion=conclusion, findings=findings,
                                 transcript=list(transcript))
    row = CopilotInvestigation(id=investigation_id, source="jo", title=fields.title, transcript_json="[]", evidence_json="[]")
    _fill(row, fields)
    session.add(row)
    session.add_all(list(also))
    session.commit()
    session.refresh(row)
    return full(row)
