"""Bounded sample-only choice read/write routes for the D2 connector."""
from datetime import datetime, timezone
import json
import math
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool
from sqlmodel import Session, select

from app.database import get_session
from app.engine import decisions, sample_practice
from app.engine.cloud_practice_access import require_choice_write, require_sample
from app.models import DecisionContext, DecisionRecord, PracticeOpportunity, PracticeRun
from cloud_mcp_d1_common import MAX_RESPONSE_BYTES
from cloud_mcp_d2_common import MAX_CHOICE_BYTES, PracticeChoice

router = APIRouter()
SCHEMA_VERSION = "d2-sample-choice-v1"
# A saved row repeats the canonical context, adds at most the 16 KiB accepted
# request, and adds three fact provenance objects. Each full selected fact is
# capped at 4 KiB and its duplicated reference name at 256 bytes; the remaining
# reserve covers the response envelope and fixed decision fields.
RESPONSE_OVERHEAD_RESERVE = 16384
MAX_RECORD_CONTEXT_BYTES = MAX_RESPONSE_BYTES - MAX_CHOICE_BYTES - RESPONSE_OVERHEAD_RESERVE


def _bad(status: int, message: str):
    raise HTTPException(status, message)


def _reject_nonfinite(value):
    raise ValueError("Non-finite JSON numbers are not supported")


def _finite_float(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("Non-finite JSON numbers are not supported")
    return number


def _opportunity(request: Request, db: Session, raw_id: str):
    """Validate the assigned sample resource before looking up any choice."""
    require_sample(request)
    who = request.state.access
    try:
        opportunity_id = uuid.UUID(raw_id)
    except (ValueError, TypeError, AttributeError):
        _bad(422, "Use a canonical opportunity UUID")
    if str(opportunity_id) != raw_id:
        _bad(422, "Use a canonical opportunity UUID")
    run_ids = who.grants.get("run_ids", [])
    if not isinstance(run_ids, list) or len(run_ids) != 1:
        _bad(404, "Sample opportunity not found")
    try:
        assigned_run_id = uuid.UUID(run_ids[0])
    except (ValueError, TypeError, AttributeError):
        _bad(404, "Sample opportunity not found")
    opportunity = db.get(PracticeOpportunity, opportunity_id)
    if opportunity is None or opportunity.run_id != assigned_run_id:
        _bad(404, "Sample opportunity not found")
    run = db.get(PracticeRun, assigned_run_id)
    if run is None or not sample_practice.eligible(run):
        _bad(404, "Sample opportunity not found")
    symbols = who.grants.get("symbols", [])
    if opportunity.symbol not in symbols or opportunity.context_id is None:
        _bad(404, "Sample opportunity not found")
    context = db.get(DecisionContext, opportunity.context_id)
    if context is None or context.provider != "sample_fixture" or context.symbol != opportunity.symbol:
        _bad(404, "Sample opportunity not found")
    try:
        evidence = json.loads(context.data_json, parse_constant=_reject_nonfinite,
                              parse_float=_finite_float)
        packet = evidence.get("packet")
        valid = (isinstance(packet, dict) and packet.get("sample_data") is True
                 and packet.get("data_source") == "sample_fixture"
                 and packet.get("sample_run_id") == str(run.id)
                 and packet.get("symbol") == opportunity.symbol)
    except (ValueError, TypeError, AttributeError):
        valid = False
    if not valid:
        _bad(404, "Sample opportunity not found")
    return who, run, opportunity, context, evidence


def _response(run: PracticeRun, opportunity: PracticeOpportunity, choice: DecisionRecord | None):
    result = {
        "schema_version": SCHEMA_VERSION,
        "sample_data": True,
        "read_at": datetime.now(timezone.utc).isoformat(),
        "time_zone": "America/New_York",
        "ui_path": f"/daily/{run.day.isoformat()}",
        "run_id": str(run.id),
        "opportunity_id": str(opportunity.id),
        "status": "recorded" if choice else "not_recorded",
        "choice": decisions.row(choice) if choice else None,
    }
    if len(json.dumps(result, separators=(",", ":"), ensure_ascii=False).encode("utf-8")) > MAX_RESPONSE_BYTES:
        _bad(503, "Sample choice response exceeds its size limit")
    return result


def _reject_query(request: Request):
    if request.query_params:
        _bad(422, "Query parameters are not supported")


def _own_choice(db: Session, opportunity: PracticeOpportunity, principal_id: str):
    return db.exec(select(DecisionRecord).where(
        DecisionRecord.opportunity_id == f"a3:{opportunity.id}",
        DecisionRecord.actor == sample_practice.actor(str(principal_id)),
    )).first()


@router.get("/opportunities/{opportunity_id}/choice")
def get_choice(opportunity_id: str, request: Request, db: Session = Depends(get_session)):
    who, run, opportunity, _context, _evidence = _opportunity(request, db, opportunity_id)
    _reject_query(request)
    choice = _own_choice(db, opportunity, str(who.identifier))
    return _response(run, opportunity, choice)


def _write_preflight(request: Request, db: Session, opportunity_id: str):
    who, run, opportunity, context, evidence = _opportunity(request, db, opportunity_id)
    _reject_query(request)
    require_choice_write(request)
    # data_json is already compact canonical JSON. The saved choice returns
    # this evidence as a JSON object, so its byte size plus the bounded request
    # and fixed projection reserve bounds the exact serialized receipt before
    # sample_practice.choose can commit it.
    if len(context.data_json.encode("utf-8")) > MAX_RECORD_CONTEXT_BYTES:
        _bad(503, "Sample choice evidence exceeds its response limit")

    return who, run, opportunity, context, evidence


async def _bounded_body(request: Request) -> bytes:
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_CHOICE_BYTES:
                _bad(422, "Sample choice exceeds its input size limit")
        except ValueError:
            _bad(422, "Invalid request size")
    chunks = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > MAX_CHOICE_BYTES:
            _bad(422, "Sample choice exceeds its input size limit")
        chunks.append(chunk)
    return b"".join(chunks)


def _parse_choice(raw: bytes) -> PracticeChoice:
    try:
        data = json.loads(raw, parse_constant=_reject_nonfinite,
                          parse_float=_finite_float)
        return PracticeChoice.model_validate(data)
    except (ValidationError, ValueError, UnicodeDecodeError, TypeError):
        _bad(422, "Invalid sample choice")


def _bound_selected_facts(evidence: dict, payload: PracticeChoice):
    """Bound every immutable fact copied into a TAKE receipt's plan sources."""
    if payload.decision != "take" or not isinstance(payload.plan, dict):
        return
    references = [payload.plan.get(key) for key in ("trigger_fact", "stop_fact", "target_fact")]
    if any(not isinstance(name, str) for name in references):
        return  # The decision engine will return its ordinary validation error.
    facts = evidence.get("price_facts")
    if not isinstance(facts, list):
        return
    by_name = {fact.get("name"): fact for fact in facts if isinstance(fact, dict)}
    for name in references:
        fact = by_name.get(name)
        if fact is None:
            continue  # The decision engine will reject an unknown frozen fact.
        if len(name.encode("utf-8")) > 256:
            _bad(422, "Selected sample evidence exceeds its size limit")
        try:
            size = len(json.dumps(fact, separators=(",", ":"), ensure_ascii=False,
                                  allow_nan=False).encode("utf-8"))
        except (TypeError, ValueError):
            _bad(422, "Selected sample evidence is invalid")
        if size > 4096:
            _bad(422, "Selected sample evidence exceeds its size limit")


def _save_choice(db: Session, who, run: PracticeRun, opportunity: PracticeOpportunity,
                 payload: PracticeChoice):
    try:
        return sample_practice.choose(db, run, opportunity, str(who.identifier), payload.model_dump())
    except decisions.DecisionError as exc:
        message = str(exc)
        if "different content" in message or "different policy" in message:
            _bad(409, "Opportunity already has a different immutable choice")
        _bad(422, "Sample choice is invalid or unavailable")
    except (ValueError, TypeError, KeyError):
        _bad(422, "Sample choice is invalid")


@router.post("/opportunities/{opportunity_id}/choice")
async def post_choice(opportunity_id: str, request: Request, response: Response,
                      db: Session = Depends(get_session)):
    # Identity, assignment, sample evidence and write permission are checked
    # before the request body is consumed. The DB/auth work and persistence run
    # off the ASGI loop; body reception remains async and bounded.
    who, run, opportunity, _context, evidence = await run_in_threadpool(
        _write_preflight, request, db, opportunity_id)
    raw = await _bounded_body(request)
    payload = _parse_choice(raw)
    _bound_selected_facts(evidence, payload)
    choice, created = await run_in_threadpool(
        _save_choice, db, who, run, opportunity, payload)
    result = _response(run, opportunity, choice)
    result["created"] = created
    response.status_code = 201 if created else 200
    return result
