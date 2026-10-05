"""Pre-trade captures (Charts C3.4, C3.5): setup, saving plans, voice and the chart image.

Every save is idempotent on the browser's ``client_id``. A voice plan arrives
as one request holding its audio, so it is saved, with its qualifying time,
only when the whole recording is on disk. Transcription is queued, never done
inside the request.
"""

import json
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.database import get_session
from app.engine import captures, transcribe
from app.engine.captures import CaptureError
from app.engine.job_runtime import submit_job
from app.models import Account, CaptureTemplate, TradeCapture

router = APIRouter()


class TemplateBody(BaseModel):
    setup_label: str = Field(max_length=200)
    wording: str = Field(max_length=2000)


class SetupBody(BaseModel):
    default_account_id: uuid.UUID | None = None


class NoteBody(BaseModel):
    kind: str
    text: str = Field(max_length=4000)


def _setup(db: Session) -> dict:
    accounts = sorted(db.exec(select(Account)).all(), key=lambda account: account.name)
    state = transcribe.status()
    return {
        "accounts": [{"id": str(account.id), "label": captures.account_label(account), "broker": account.broker or "robinhood"} for account in accounts],
        "default_account_id": str(captures.profile(db).default_account_id) if captures.profile(db).default_account_id else None,
        "templates": [captures.template_row(template) for template in captures.active_templates(db)],
        "max_templates": captures.MAX_TEMPLATES,
        "transcriber": {"configured": state.configured, "provider": state.provider, "note": state.note},
    }


def _fail(exc: CaptureError):
    raise HTTPException(422, str(exc)) from None


def _capture(db: Session, capture_id: uuid.UUID) -> TradeCapture:
    capture = db.get(TradeCapture, capture_id)
    if capture is None:
        raise HTTPException(404, "That plan no longer exists.")
    return capture


def _one(db: Session, capture: TradeCapture, status: Response | None = None, created: bool = True) -> dict:
    if status is not None and not created:
        status.status_code = 200
    return captures.rows(db, [capture])[0]


@router.get("/captures/setup")
def get_setup(db: Session = Depends(get_session)):
    return _setup(db)


@router.put("/captures/setup")
def put_setup(body: SetupBody, db: Session = Depends(get_session)):
    try:
        captures.set_default_account(db, body.default_account_id)
    except CaptureError as exc:
        _fail(exc)
    return _setup(db)


@router.post("/captures/templates")
def add_template(body: TemplateBody, db: Session = Depends(get_session)):
    try:
        captures.add_template(db, body.setup_label, body.wording)
    except CaptureError as exc:
        _fail(exc)
    return _setup(db)


@router.put("/captures/templates/{template_id}")
def edit_template(template_id: uuid.UUID, body: TemplateBody, db: Session = Depends(get_session)):
    template = db.get(CaptureTemplate, template_id)
    if template is None or template.archived_at is not None:
        raise HTTPException(404, "That template was removed.")
    try:
        captures.edit_template(db, template, body.setup_label, body.wording)
    except CaptureError as exc:
        _fail(exc)
    return _setup(db)


@router.delete("/captures/templates/{template_id}")
def remove_template(template_id: uuid.UUID, db: Session = Depends(get_session)):
    template = db.get(CaptureTemplate, template_id)
    if template is not None and template.archived_at is None:
        captures.archive_template(db, template)
    return _setup(db)


@router.get("/captures")
def list_captures(limit: int = 20, db: Session = Depends(get_session)):
    return {"captures": captures.rows(db, captures.recent(db, max(1, min(limit, 100))))}


@router.post("/captures", status_code=201)
def create(body: dict, response: Response, db: Session = Depends(get_session)):
    try:
        capture, created = captures.save(db, captures.build(db, body))
    except CaptureError as exc:
        _fail(exc)
    return _one(db, capture, response, created)


@router.post("/captures/voice", status_code=201)
async def create_voice(response: Response, meta: str = Form(...), audio: UploadFile = File(...), db: Session = Depends(get_session)):
    try:
        body = json.loads(meta)
    except json.JSONDecodeError:
        raise HTTPException(422, "The recording arrived without its plan details.") from None
    if not isinstance(body, dict):
        raise HTTPException(422, "The recording arrived without its plan details.")
    existing = captures.by_client_id(db, str(body.get("client_id") or ""))
    if existing is not None:
        return _one(db, existing, response, False)
    data = await audio.read(captures.AUDIO_MAX + 1)
    try:
        capture = captures.build(db, body, mode_override="voice")
        ms = body.get("audio_ms")
        capture, created = captures.save(db, capture, audio=data, audio_ms=int(ms) if isinstance(ms, (int, float)) else None)
    except CaptureError as exc:
        _fail(exc)
    if created:
        job = captures.queue_transcription(db, capture)
        if job is not None:
            submit_job(job.id)
        db.refresh(capture)
    return _one(db, capture, response, created)


@router.post("/captures/{capture_id}/image")
async def add_image(capture_id: uuid.UUID, image: UploadFile = File(...), db: Session = Depends(get_session)):
    capture = _capture(db, capture_id)
    data = await image.read(captures.IMAGE_MAX + 1)
    try:
        captures.attach_image(db, capture, data)
    except CaptureError as exc:
        _fail(exc)
    return _one(db, capture)


@router.post("/captures/{capture_id}/not-taken")
def not_taken(capture_id: uuid.UUID, db: Session = Depends(get_session)):
    return _one(db, captures.mark_not_taken(db, _capture(db, capture_id)))


@router.post("/captures/{capture_id}/notes")
def add_note(capture_id: uuid.UUID, body: NoteBody, db: Session = Depends(get_session)):
    capture = _capture(db, capture_id)
    try:
        captures.add_note(db, capture, body.kind, body.text)
    except CaptureError as exc:
        _fail(exc)
    return _one(db, capture)


@router.post("/captures/{capture_id}/transcribe")
def retry_transcription(capture_id: uuid.UUID, db: Session = Depends(get_session)):
    capture = _capture(db, capture_id)
    if capture.mode != "voice":
        raise HTTPException(422, "Only a voice plan has a recording to transcribe.")
    job = captures.queue_transcription(db, capture)
    if job is not None and job.status == "queued":
        submit_job(job.id)
    db.refresh(capture)
    return _one(db, capture)


def _file(path, media_type: str | None) -> FileResponse:
    if path is None or not path.is_file():
        raise HTTPException(404, "The file is not on this server.")
    return FileResponse(path, media_type=media_type, headers={"Cache-Control": "private, max-age=3600"})


@router.get("/captures/{capture_id}/audio")
def get_audio(capture_id: uuid.UUID, db: Session = Depends(get_session)):
    capture = _capture(db, capture_id)
    return _file(captures.audio_path(capture), capture.audio_type)


@router.get("/captures/{capture_id}/image")
def get_image(capture_id: uuid.UUID, db: Session = Depends(get_session)):
    capture = _capture(db, capture_id)
    return _file(captures.image_path(capture) if capture.image_state == "saved" else None, capture.image_type)
