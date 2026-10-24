"""Owner-only Copilot Lab (docs/copilot-lab.md): status, one streamed, read-only conversation turn, and saved
investigations.

Off unless ``COPILOT_ENABLED=true``. Owner-only through the access middleware
(no route is in an assistant grant) and the frontend proxy. Prompts and answers
are never logged; only per-turn metrics are. A conversation is stored only as a
saved investigation the page writes: text transcript and evidence references.
"""
import asyncio
from datetime import datetime
import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.ai import copilot
from app.database import get_session
from app.engine import copilot_investigations as investigations
from app.engine.chart_math import ET

router = APIRouter()

MAX_HISTORY_CHARS = 40_000


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class ChatBody(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=24)
    symbol: str | None = Field(None, pattern=r"^[A-Z][A-Z0-9.\-]{0,9}$")


@router.get("/status")
def status():
    cfg = copilot.settings()
    if not cfg.enabled:
        return {"enabled": False, "reason": "Copilot Lab is off. Set COPILOT_ENABLED=true on the private backend to try it."}
    out = cfg.public()
    if cfg.evidence == "replay":
        try:
            out["replay"] = copilot.evidence_for(cfg).describe()
        except copilot.CopilotError as exc:
            out["replay"] = {"error": exc.message}
    return out


@router.post("/chat")
async def chat(body: ChatBody):
    cfg = copilot.settings()
    if not cfg.enabled:
        raise HTTPException(503, "Copilot Lab is off.")
    roles = [m.role for m in body.messages]
    if roles[-1] != "user" or any(r == roles[i - 1] for i, r in enumerate(roles) if i) or roles[0] != "user":
        raise HTTPException(422, "Messages must alternate, starting and ending with the trader.")
    if sum(len(m.content) for m in body.messages) > MAX_HISTORY_CHARS:
        raise HTTPException(413, "This conversation is too long for the lab; start a new one.")
    try:
        # The plan backend asks Claude Code for its sign-in once per process; keep that off the event loop.
        adapter = await asyncio.to_thread(copilot.adapter_for, cfg)
        evidence = copilot.evidence_for(cfg)
    except copilot.CopilotError as exc:
        raise HTTPException(503, exc.message)
    history = [m.model_dump() for m in body.messages]

    async def events():
        try:
            now = datetime.now(ET)
            # The plan backend's SDK runs its own tool loop, so it supplies the whole turn.
            turn = (adapter.run_turn(history, body.symbol, cfg, evidence, now) if hasattr(adapter, "run_turn")
                    else copilot.run_turn(history, body.symbol, cfg, adapter, evidence, now))
            async for event in turn:
                yield f"event: {event['type']}\ndata: {json.dumps(event, default=str)}\n\n"
        finally:
            if hasattr(adapter, "aclose"):
                await adapter.aclose()

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


# --------------------------------------------------------------------------- saved investigations

class InvestigationUpdate(investigations.InvestigationFields):
    revision: int  # the revision this save was based on


def _enabled():
    if not copilot.settings().enabled:
        raise HTTPException(503, "Copilot Lab is off.")


def _http(exc: investigations.InvestigationError) -> HTTPException:
    return HTTPException({"not_found": 404, "stale": 409, "too_long": 413}[exc.code], str(exc))


@router.get("/investigations")
def list_investigations(limit: int = 20, symbol: str | None = None, session: Session = Depends(get_session)):
    _enabled()
    return {"investigations": investigations.list_investigations(symbol=symbol, limit=limit, session=session)}


@router.post("/investigations", status_code=201)
def create_investigation(body: investigations.InvestigationFields, session: Session = Depends(get_session)):
    """The lab page saves interactive conversations only; research jobs save in-process."""
    _enabled()
    try:
        return investigations.create(body, source="copilot", session=session)
    except investigations.InvestigationError as exc:
        raise _http(exc)


@router.get("/investigations/{investigation_id}")
def get_investigation(investigation_id: str, session: Session = Depends(get_session)):
    _enabled()
    try:
        return investigations.get(investigation_id, session=session)
    except investigations.InvestigationError as exc:
        raise _http(exc)


@router.put("/investigations/{investigation_id}")
def update_investigation(investigation_id: str, body: InvestigationUpdate, session: Session = Depends(get_session)):
    _enabled()
    fields = investigations.InvestigationFields(**body.model_dump(exclude={"revision"}))
    try:
        return investigations.update(investigation_id, fields, body.revision, session=session)
    except investigations.InvestigationError as exc:
        raise _http(exc)
