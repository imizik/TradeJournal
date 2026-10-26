"""Owner-only Copilot Lab (docs/copilot-lab.md): status, open threads, one streamed, read-only conversation turn,
hold-to-talk transcription, and saved investigations.

Off unless ``COPILOT_ENABLED=true``. Owner-only through the access middleware
(no route is in an assistant grant) and the frontend proxy. Prompts and answers
are never logged; only per-turn metrics are. A conversation is stored only as a
saved investigation the page writes: text transcript and evidence references. A spoken message's audio is deleted
as soon as it is transcribed and never logged.
"""
import asyncio
from datetime import datetime
import json
import logging
import time
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.ai import copilot
from app.database import engine, get_session
from app.engine import captures, spoken_tickers, transcribe
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
    model: str | None = Field(None, pattern=r"^[a-z0-9][a-z0-9.\-]{0,60}$")  # one of GET /status's ``models``


@router.get("/status")
def status():
    cfg = copilot.settings()
    if not cfg.enabled:
        return {"enabled": False, "reason": "Copilot Lab is off. Set COPILOT_ENABLED=true on the private backend to try it."}
    out = cfg.public()
    speech = transcribe.status()
    out["capabilities"] = {"copilot_alerts": copilot_alerts_supported(),
                           "transcriber": {"configured": speech.configured, "provider": speech.provider}}
    if cfg.evidence == "replay":
        try:
            out["replay"] = copilot.evidence_for(cfg).describe()
        except copilot.CopilotError as exc:
            out["replay"] = {"error": exc.message}
    return out


def copilot_alerts_supported() -> bool:
    """Whether the level-alert route accepts alerts the owner confirms here (``source_kind="copilot"``). Asked of the
    route's own request model, so the lab's Confirm turns on by itself once that route allows it."""
    from pydantic import ValidationError
    from app.routers.level_alerts import AlertCreate
    try:
        AlertCreate(symbol="SPY", price=1.0, reference=2.0, condition="touches", source_kind="copilot",
                    source_id="00000000-0000-4000-8000-000000000000")  # shaped like the investigation id Confirm sends
    except ValidationError:
        return False
    return True


QUOTE_FRESH_S = 60


@router.get("/quote")
def quote(symbol: str = Query(..., pattern=r"^[A-Z][A-Z0-9.\-]{0,9}$")):
    """A fresh last price for confirming a watch: the side an alert waits on comes from it. ``fresh`` is false when
    the read is older than a minute (a provider outage serving a kept copy) or there is no price."""
    from app.engine.chart_feed import ChartFeedError, chart_feed
    _enabled()
    try:
        rows, fetched_at, issue = chart_feed.quote_rows([symbol])
    except ChartFeedError as exc:
        raise HTTPException(503, str(exc)) from None
    row = next((r for r in rows if r.get("symbol") == symbol), {})
    last = row.get("last")
    age = None if fetched_at is None else max(0.0, time.time() - fetched_at)
    fresh = isinstance(last, (int, float)) and last > 0 and age is not None and age <= QUOTE_FRESH_S and not issue
    return {"symbol": symbol, "last": last, "trade_time": row.get("trade_time"), "fetched_at": fetched_at,
            "age_s": None if age is None else round(age, 1), "issue": issue, "fresh": fresh}


# What the lab's home shows of a position: no account, no plan wording, no entry/mark detail.
THREAD_POSITION_FIELDS = ("symbol", "instrument", "option", "direction", "quantity", "unrealized_pct", "giveback",
                          "peak_gain_pct", "days_to_expiry", "expires_today", "days_held", "held_minutes")


@router.get("/threads")
def threads():
    """The lab's Open threads: the no-symbol owner context pack's positions, open investigations and watches (armed
    level alerts and waiting research jobs). Never memories or habits; the only ids are investigations'. Fixture mode
    serves the simulated pack and replay says it is unavailable, as for a turn. A page read, not a turn, so the pack's
    size cap does not apply (``bounded=False``); its sections keep their row caps."""
    _enabled()
    try:
        pack = copilot.evidence_for(copilot.settings()).owner_context(None, bounded=False)
    except copilot.CopilotError as exc:
        raise HTTPException(503, exc.message) from None

    def section(name: str) -> dict:
        part = pack.get(name)
        if not isinstance(part, dict) or part.get("state") != "ok":
            return {"state": "unavailable"}
        return {"state": "ok", name: part.get(name, [])}

    held, investigations_, watches = section("positions"), section("investigations"), section("watches")
    if held["state"] == "ok":
        held.update(count=pack["positions"].get("count", 0),
                    positions=[{k: row[k] for k in THREAD_POSITION_FIELDS if k in row} for row in held["positions"]])
    if investigations_["state"] == "ok" and investigations_["investigations"]:
        # The last few thesis-watch triggers for each open investigation (docs/copilot-lab.md § Thesis watch).
        try:
            from app.engine import thesis_watch
            with Session(engine) as db:
                recent = thesis_watch.recent_for(db, [r["id"] for r in investigations_["investigations"]])
            for row in investigations_["investigations"]:
                row["watch"] = recent.get(row["id"], [])
        except Exception:  # the triggers are extra; the threads stand
            logging.getLogger(__name__).warning("Open threads: thesis watch triggers unavailable", exc_info=True)
    return {"positions": held, "investigations": investigations_, "watches": watches, "as_of": pack.get("as_of")}


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
        cfg = copilot.with_model(cfg, body.model)
    except copilot.CopilotError as exc:
        raise HTTPException(422, exc.message)
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


# --------------------------------------------------------------------------- hold-to-talk

@router.post("/transcribe")
async def transcribe_message(audio: UploadFile | None = File(None), audio_ms: int | None = Form(None),
                             text: str | None = Form(None, max_length=4000), session: Session = Depends(get_session)):
    """A spoken message as text for the composer, spoken tickers written as symbols. ``audio`` (a 30-second clip at
    most, as for voice plans) goes through this server's transcriber and is deleted; ``text`` is what the browser's
    own speech recognition heard, when the server has no transcriber, and only has its tickers mapped."""
    _enabled()
    if (audio is None) == (text is None):
        raise HTTPException(422, "Send either a recording or the browser's transcript.")
    traded = spoken_tickers.traded(session)
    known = spoken_tickers.known_symbols(traded)
    provider = "browser"
    if audio is not None:
        speech = transcribe.status()
        if not speech.configured:
            raise HTTPException(503, speech.note.replace(" Recordings are saved and can be played back.", " Type the message instead."))
        data = await audio.read(captures.AUDIO_MAX + 1)
        try:
            kind = captures.sniff_audio(data)
            captures.check_clip_ms(audio_ms)
        except captures.CaptureError as exc:
            raise HTTPException(413 if len(data) > captures.AUDIO_MAX else 422, str(exc)) from None
        try:
            text = await asyncio.to_thread(transcribe.transcribe_bytes, data, captures.AUDIO_TYPES[kind],
                                           spoken_tickers.prompt_for(known, traded))
        except transcribe.TranscriptionError as exc:
            raise HTTPException(502, str(exc)) from None
        provider = speech.provider
    heard = (text or "").strip()
    mapped, tickers = spoken_tickers.map_tickers(heard, known)
    return {"text": mapped, "heard": heard, "tickers": tickers, "provider": provider}


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
