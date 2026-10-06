"""Pre-trade captures (Charts C3.4, C3.5): rules, private file storage and rows.

A capture is the user's own durable record. What was submitted is never edited:
later transcript corrections and reflections are separate notes, and a template
edit never reaches a capture, which keeps its own copy of the wording.

Audio and chart images are files under ``CAPTURE_STORAGE_DIR`` (by default
``backend/data/captures``; on the server ``backend/data`` is the backed-up
``/var/lib/tradejournal/data``). Each file is written to a temporary name,
flushed to disk and renamed before its row is committed, so a row never points
at a half-written file. Only the private API serves them.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.models import Account, CaptureProfile, CaptureTemplate, JobRun, TradeCapture, TradeCaptureNote

# The explicit opening sides. Buy or sell exposure is never inferred from call/put alone.
SIDES: dict[str, str] = {
    "buy_calls": "option", "buy_puts": "option", "buy_stock": "stock",
    "short_stock": "stock", "sell_calls": "option", "sell_puts": "option",
}
MODES = ("template", "discretionary", "voice")
MAX_TEMPLATES = 3
LABEL_MAX = 40
WORDING_MAX = 400
NOTE_MAX = 500
CONTEXT_MAX = 64_000
IMAGE_MAX = 1_500_000
AUDIO_MAX = 3_000_000
AUDIO_MIN = 1_000  # anything smaller holds no usable speech
CLIP_MS = 30_000
SYMBOL = re.compile(r"^[A-Z][A-Z0-9./-]{0,14}$")
CLIENT_ID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")

# What each upload may be, by its first bytes, never by the browser's word alone.
AUDIO_TYPES = {"audio/webm": "webm", "audio/ogg": "ogg", "audio/mp4": "m4a", "audio/wav": "wav"}
IMAGE_TYPES = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}


class CaptureError(ValueError):
    """A request the user can fix; the message says how."""


def storage_root() -> Path:
    configured = os.environ.get("CAPTURE_STORAGE_DIR")
    root = Path(configured) if configured else Path(__file__).resolve().parents[2] / "data" / "captures"
    return root


def _media_type(head: bytes, kinds: dict[str, str]) -> str | None:
    """The upload's real type from its leading bytes, if it is one ``kinds`` allows."""
    if head.startswith(b"\x1a\x45\xdf\xa3"):
        found = "audio/webm"
    elif head.startswith(b"OggS"):
        found = "audio/ogg"
    elif head[4:8] == b"ftyp":
        found = "audio/mp4"
    elif head.startswith(b"RIFF") and head[8:12] == b"WAVE":
        found = "audio/wav"
    elif head.startswith(b"\x89PNG\r\n\x1a\n"):
        found = "image/png"
    elif head.startswith(b"\xff\xd8\xff"):
        found = "image/jpeg"
    elif head.startswith(b"RIFF") and head[8:12] == b"WEBP":
        found = "image/webp"
    else:
        return None
    return found if found in kinds else None


def sniff_audio(data: bytes) -> str:
    if len(data) < AUDIO_MIN:
        raise CaptureError("The recording is empty. Record again, or save the plan without audio.")
    if len(data) > AUDIO_MAX:
        raise CaptureError("The recording is too large; clips are limited to 30 seconds.")
    kind = _media_type(data[:16], AUDIO_TYPES)
    if kind is None:
        raise CaptureError("That file is not a recording this app can keep (WebM, Ogg, MP4 or WAV audio).")
    return kind


def sniff_image(data: bytes) -> str:
    if not data:
        raise CaptureError("The chart image is empty.")
    if len(data) > IMAGE_MAX:
        raise CaptureError("The chart image is larger than 1.5 MB.")
    kind = _media_type(data[:16], IMAGE_TYPES)
    if kind is None:
        raise CaptureError("The chart image must be PNG, JPEG or WebP.")
    return kind


def _path(capture: TradeCapture, what: str, kind: str) -> Path:
    # By the capture's ID alone: nothing that is set after the file is written may move it.
    extension = (AUDIO_TYPES | IMAGE_TYPES)[kind]
    return storage_root() / capture.id.hex[:2] / f"{capture.id}.{what}.{extension}"


def audio_path(capture: TradeCapture) -> Path | None:
    return _path(capture, "audio", capture.audio_type) if capture.audio_type else None


def image_path(capture: TradeCapture) -> Path | None:
    return _path(capture, "image", capture.image_type) if capture.image_type else None


def _write(path: Path, data: bytes) -> None:
    """Whole file on disk before anything points at it: temporary name, fsync, rename."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.part")
    with temporary.open("wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _utc(value: Any) -> datetime | None:
    """Epoch milliseconds from the browser as naive UTC, like every other stored time."""
    if value is None:
        return None
    try:
        stamp = float(value) / 1000
    except (TypeError, ValueError):
        return None
    if not math.isfinite(stamp) or stamp <= 0:
        return None
    return datetime.fromtimestamp(stamp, timezone.utc).replace(tzinfo=None)


def epoch(value: datetime | None) -> float | None:
    return value.replace(tzinfo=timezone.utc).timestamp() if value else None


def account_label(account: Account) -> str:
    return f"{account.name} ··{account.last4}" if account.last4 and account.last4.isdigit() else account.name


# ---------------------------------------------------------------- setup

def profile(db: Session) -> CaptureProfile:
    row = db.get(CaptureProfile, 1)
    return row if row is not None else CaptureProfile(id=1, default_account_id=None)


def active_templates(db: Session) -> list[CaptureTemplate]:
    return list(db.exec(select(CaptureTemplate).where(CaptureTemplate.archived_at == None)  # noqa: E711
                        .order_by(CaptureTemplate.position, CaptureTemplate.created_at)).all())


def _clean_template(setup_label: str, wording: str) -> tuple[str, str]:
    label, words = setup_label.strip(), wording.strip()
    if not label or not words:
        raise CaptureError("A template needs a setup name and your own exit or invalidation wording.")
    if len(label) > LABEL_MAX or len(words) > WORDING_MAX:
        raise CaptureError(f"Keep the name under {LABEL_MAX} characters and the wording under {WORDING_MAX}.")
    return label, words


def add_template(db: Session, setup_label: str, wording: str) -> CaptureTemplate:
    label, words = _clean_template(setup_label, wording)
    existing = active_templates(db)
    if len(existing) >= MAX_TEMPLATES:
        raise CaptureError(f"Up to {MAX_TEMPLATES} favorite templates. Remove one first.")
    row = CaptureTemplate(setup_label=label, wording=words, position=max((t.position for t in existing), default=-1) + 1)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def edit_template(db: Session, template: CaptureTemplate, setup_label: str, wording: str) -> CaptureTemplate:
    label, words = _clean_template(setup_label, wording)
    if (label, words) != (template.setup_label, template.wording):
        template.setup_label, template.wording = label, words
        template.revision += 1
        template.updated_at = datetime.utcnow()
        db.add(template)
        db.commit()
        db.refresh(template)
    return template


def archive_template(db: Session, template: CaptureTemplate) -> None:
    template.archived_at = datetime.utcnow()
    db.add(template)
    db.commit()


def set_default_account(db: Session, account_id: uuid.UUID | None) -> CaptureProfile:
    if account_id is not None and db.get(Account, account_id) is None:
        raise CaptureError("That account no longer exists.")
    row = db.get(CaptureProfile, 1) or CaptureProfile(id=1)
    row.default_account_id = account_id
    row.updated_at = datetime.utcnow()
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def template_row(template: CaptureTemplate) -> dict:
    return {"id": str(template.id), "setup_label": template.setup_label, "wording": template.wording,
            "revision": template.revision, "position": template.position}


# ---------------------------------------------------------------- captures

def _number(value: Any, name: str) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise CaptureError(f"The {name} must be a number.") from None
    if not math.isfinite(number) or number <= 0:
        raise CaptureError(f"The {name} must be a positive number.")
    return number


def _expiration(value: Any) -> date | None:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise CaptureError("The expiration must be a date (YYYY-MM-DD).") from None


def build(db: Session, body: dict, *, mode_override: str | None = None) -> TradeCapture:
    """A validated, unsaved capture from the browser's submission. Raises CaptureError."""
    client_id = str(body.get("client_id") or "")
    if not CLIENT_ID.fullmatch(client_id):
        raise CaptureError("The capture is missing its request ID. Reload the page and try again.")
    symbol = str(body.get("underlying") or "").strip().upper()
    if not SYMBOL.fullmatch(symbol):
        raise CaptureError("Use a US stock or ETF ticker.")
    side = str(body.get("side") or "")
    if side not in SIDES:
        raise CaptureError("Choose what you are taking: calls, puts or stock, bought or sold.")
    try:
        account = db.get(Account, uuid.UUID(str(body.get("account_id"))))
    except ValueError:
        account = None
    if account is None:
        raise CaptureError("Choose the journal account this plan is for.")
    mode = mode_override or str(body.get("mode") or "")
    if mode not in MODES or (mode == "voice") != (mode_override == "voice"):
        raise CaptureError("Choose a template, Discretionary, or record a voice note.")
    note = str(body.get("note") or "").strip() or None
    if note and len(note) > NOTE_MAX:
        raise CaptureError(f"Keep the note under {NOTE_MAX} characters.")
    template = None
    if body.get("template_id"):
        try:
            template = db.get(CaptureTemplate, uuid.UUID(str(body["template_id"])))
        except ValueError:
            template = None
        if template is None or template.archived_at is not None:
            raise CaptureError("That template was removed. Choose another.")
        # The wording the user saw is what is kept: a template edited on another device meanwhile is not silently swapped in.
        if body.get("template_revision") is not None and str(body["template_revision"]) != str(template.revision):
            raise CaptureError("That template was just edited on another device. Check its wording and save again.")
    if mode == "template" and template is None:
        raise CaptureError("Choose a template, or use Discretionary.")
    if mode == "discretionary" and template is not None:
        raise CaptureError("A discretionary plan has no template.")
    context = body.get("context")
    context_text = json.dumps(context, separators=(",", ":")) if isinstance(context, dict) else "{}"
    if len(context_text) > CONTEXT_MAX:
        raise CaptureError("The chart snapshot is too large.")
    context_state = "captured" if isinstance(context, dict) and context.get("state") == "captured" else "unavailable"
    return TradeCapture(
        client_id=client_id, received_at=datetime.utcnow(), client_captured_at=_utc(body.get("client_captured_at")),
        account_id=account.id, account_label=account_label(account), underlying=symbol, side=side, instrument=SIDES[side],
        mode=mode, template_id=template.id if template else None, template_revision=template.revision if template else None,
        setup_label=template.setup_label if template else None, wording=template.wording if template else None, note=note,
        strike=_number(body.get("strike"), "strike") if SIDES[side] == "option" else None,
        expiration=_expiration(body.get("expiration")) if SIDES[side] == "option" else None,
        quantity=_number(body.get("quantity"), "quantity"),
        context_state=context_state, context_json=context_text,
        image_state="pending" if body.get("image") and context_state == "captured" else "unavailable",
        image_note=(str(body.get("image_note") or "").strip()[:300] or None),
    )


def by_client_id(db: Session, client_id: str) -> TradeCapture | None:
    return db.exec(select(TradeCapture).where(TradeCapture.client_id == client_id)).first()


def save(db: Session, capture: TradeCapture, audio: bytes | None = None, audio_ms: int | None = None) -> tuple[TradeCapture, bool]:
    """Store a capture once. A repeated client ID returns the first one (and False).

    For voice the whole audio file reaches disk before the row exists, and
    ``received_at`` is taken after it has: that is when the intent was complete.
    """
    existing = by_client_id(db, capture.client_id)
    if existing is not None:
        return existing, False
    if audio is not None:
        capture.audio_type = sniff_audio(audio)
        if audio_ms is not None and not 0 < audio_ms <= CLIP_MS + 1500:
            raise CaptureError("Clips are limited to 30 seconds.")
        capture.audio_ms = audio_ms
        capture.audio_bytes = len(audio)
        capture.audio_sha256 = hashlib.sha256(audio).hexdigest()
        _write(audio_path(capture), audio)
        capture.received_at = datetime.utcnow()
    db.add(capture)
    try:
        db.commit()
    except IntegrityError:
        # Two copies of one request raced; the other one was stored first.
        db.rollback()
        winner = by_client_id(db, capture.client_id)
        if winner is None:
            raise
        return winner, False
    db.refresh(capture)
    return capture, True


def attach_image(db: Session, capture: TradeCapture, data: bytes) -> TradeCapture:
    """The frozen chart image, once. A capture whose image is saved, or was never coming, takes no other."""
    if capture.image_state == "saved":
        return capture
    if capture.image_state != "pending":
        raise CaptureError("This plan was saved without a chart image.")
    capture.image_type = sniff_image(data)
    capture.image_bytes = len(data)
    _write(image_path(capture), data)
    capture.image_state = "saved"
    capture.image_received_at = datetime.utcnow()
    db.add(capture)
    db.commit()
    db.refresh(capture)
    return capture


def mark_not_taken(db: Session, capture: TradeCapture) -> TradeCapture:
    if capture.not_taken_at is None:
        capture.not_taken_at = datetime.utcnow()
        db.add(capture)
        db.commit()
        db.refresh(capture)
    return capture


def add_note(db: Session, capture: TradeCapture, kind: str, text: str) -> TradeCaptureNote:
    if kind not in ("transcript_correction", "note"):
        raise CaptureError("Unknown kind of note.")
    words = text.strip()
    if not words or len(words) > 2000:
        raise CaptureError("Write between 1 and 2,000 characters.")
    if kind == "transcript_correction" and capture.mode != "voice":
        raise CaptureError("Only a voice plan has a transcript to correct.")
    row = TradeCaptureNote(capture_id=capture.id, kind=kind, text=words)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


# ---------------------------------------------------------------- listing

def _transcript(capture: TradeCapture, job: dict | None) -> dict | None:
    if capture.mode != "voice":
        return None
    status, error = capture.transcript_status, capture.transcript_error
    # A worker that died mid-job left the row saying "transcribing"; its job says what happened.
    if status in ("pending", "transcribing") and job and job["status"] == "failed":
        status, error = "failed", job["error"] or "Transcription was interrupted."
    return {"status": status, "text": capture.transcript_text, "provider": capture.transcript_provider,
            "error": error, "transcribed_at": epoch(capture.transcribed_at)}


def rows(db: Session, captures: list[TradeCapture]) -> list[dict]:
    """Captures as the browser shows them, with their notes and transcription jobs in two queries."""
    ids = [capture.id for capture in captures]
    notes: dict[uuid.UUID, list[dict]] = {}
    if ids:
        for note in db.exec(select(TradeCaptureNote).where(TradeCaptureNote.capture_id.in_(ids)).order_by(TradeCaptureNote.created_at)).all():
            notes.setdefault(note.capture_id, []).append({"id": str(note.id), "kind": note.kind, "text": note.text, "created_at": epoch(note.created_at)})
    job_ids = [capture.transcript_job_id for capture in captures if capture.transcript_job_id]
    jobs = {}
    if job_ids:
        for job_id, status, error in db.exec(select(JobRun.id, JobRun.status, JobRun.error).where(JobRun.id.in_(job_ids))).all():
            jobs[job_id] = {"status": status, "error": error}
    out = []
    for capture in captures:
        try:
            context = json.loads(capture.context_json or "{}")
        except json.JSONDecodeError:
            context = {}
        out.append({
            "id": str(capture.id), "client_id": capture.client_id, "received_at": epoch(capture.received_at),
            "client_captured_at": epoch(capture.client_captured_at), "account_id": str(capture.account_id),
            "account_label": capture.account_label, "underlying": capture.underlying, "side": capture.side,
            "instrument": capture.instrument, "mode": capture.mode, "template_id": str(capture.template_id) if capture.template_id else None,
            "template_revision": capture.template_revision, "setup_label": capture.setup_label, "wording": capture.wording,
            "note": capture.note, "strike": capture.strike, "expiration": capture.expiration.isoformat() if capture.expiration else None,
            "quantity": capture.quantity, "context_state": capture.context_state, "context": context,
            "image": {"state": capture.image_state, "note": capture.image_note, "bytes": capture.image_bytes},
            "audio": {"type": capture.audio_type, "ms": capture.audio_ms, "bytes": capture.audio_bytes} if capture.audio_type else None,
            "transcript": _transcript(capture, jobs.get(capture.transcript_job_id)),
            "not_taken_at": epoch(capture.not_taken_at), "notes": notes.get(capture.id, []),
        })
    return out


def recent(db: Session, limit: int = 20) -> list[TradeCapture]:
    return list(db.exec(select(TradeCapture).order_by(TradeCapture.received_at.desc()).limit(limit)).all())


# ---------------------------------------------------------------- transcription

JOB_TRANSCRIBE = "capture_transcribe"


def queue_transcription(db: Session, capture: TradeCapture) -> JobRun | None:
    """One transcription job for a voice capture, unless one is already waiting or running.

    Nothing retries by itself: after a failure or an interruption only the
    user's Retry queues another, so a doubtful provider answer is never paid
    for over and over.
    """
    from app.engine import transcribe

    if capture.mode != "voice" or capture.transcript_status == "ready":
        return None
    if capture.transcript_job_id:
        current = db.get(JobRun, capture.transcript_job_id)
        if current is not None and current.status in ("queued", "running"):
            return current
    if not transcribe.status().configured:
        capture.transcript_status = "not_configured"
        capture.transcript_error = transcribe.status().note
        db.add(capture)
        db.commit()
        return None
    # The job and the capture's link to it commit together: a worker that sees
    # the queued job always finds the capture pointing at it.
    now = datetime.utcnow()
    job = JobRun(id=uuid.uuid4(), job_type=JOB_TRANSCRIBE, status="queued", phase="queued", params_json=json.dumps({"capture_id": str(capture.id)}),
                 total=1, current=f"Transcribe {capture.underlying} plan", updated_at=now)
    capture.transcript_job_id = job.id
    capture.transcript_status = "pending"
    capture.transcript_error = None
    db.add(job)
    db.add(capture)
    db.commit()
    db.refresh(job)
    return job


def run_transcription_job(job_id: uuid.UUID) -> int:
    """Job handler, after the runtime has claimed ``job_id`` in the capture lane."""
    from app.database import engine
    from app.engine import transcribe
    from app.engine.jobs import _fail_job, _finish_job, _params, _set_job

    with Session(engine) as db:
        job = db.get(JobRun, job_id)
        capture = db.get(TradeCapture, uuid.UUID(_params(job).get("capture_id", ""))) if job else None
        # A later Retry owns the capture now, or it is already done: nothing to do.
        if capture is None or capture.transcript_job_id != job_id or capture.transcript_status == "ready":
            _finish_job(job_id, 0, 1)
            return 0
        capture.transcript_status = "transcribing"
        db.add(capture)
        db.commit()
        path = audio_path(capture)
        provider = transcribe.status().provider
    _set_job(job_id, phase="processing", current="Transcribing")
    try:
        text = transcribe.transcribe(path)
    except Exception as exc:
        with Session(engine) as db:
            capture = db.get(TradeCapture, capture.id)
            if capture.transcript_job_id == job_id:
                capture.transcript_status = "failed"
                capture.transcript_error = str(exc)
                db.add(capture)
                db.commit()
        _fail_job(job_id, exc)
        return 0
    with Session(engine) as db:
        capture = db.get(TradeCapture, capture.id)
        if capture.transcript_job_id == job_id:
            capture.transcript_status = "ready"
            capture.transcript_text = text
            capture.transcript_provider = provider
            capture.transcript_error = None
            capture.transcribed_at = datetime.utcnow()
            db.add(capture)
            db.commit()
    _finish_job(job_id, 1, 1)
    return 1
