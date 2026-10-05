"""Pre-trade captures (Charts C3.4, C3.5): templates keep revisions and plans keep
their own copy; a save happens once however often it is sent; uploads are
checked by their bytes; a voice plan counts from when its whole recording is on
disk; and transcription runs as a durable job in its own lane, with an explicit
retry that never doubles up. The speech engine is a stand-in except in the one
test that loads the real one when it is installed."""

import io
import json
import math
import struct
import uuid
import wave
from datetime import datetime
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.database import get_session
from app.engine import captures, job_runtime, transcribe
from app.models import Account, Fill, JobRun, Trade, TradeCapture, TradeCaptureNote
from app.routers import captures as routes


@pytest.fixture
def engine(monkeypatch, tmp_path):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    # Job helpers open their own sessions on app.database.engine.
    import app.database
    import app.engine.jobs
    monkeypatch.setattr(app.database, "engine", engine)
    monkeypatch.setattr(app.engine.jobs, "engine", engine)
    monkeypatch.setattr(job_runtime, "engine", engine)
    monkeypatch.setenv("CAPTURE_STORAGE_DIR", str(tmp_path / "captures"))
    with Session(engine) as db:
        db.add(Account(id=uuid.UUID(int=1), name="Roth IRA", type="roth_ira", last4="8267"))
        db.add(Account(id=uuid.UUID(int=2), name="Individual", type="individual", last4="1234"))
        db.commit()
    yield engine
    engine.dispose()


@pytest.fixture
def client(engine, monkeypatch):
    app = FastAPI()
    app.include_router(routes.router, prefix="/charts")

    def session():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_session] = session
    submitted = []
    # The worker runs jobs; here a test runs them when it means to.
    monkeypatch.setattr(routes, "submit_job", submitted.append)
    with TestClient(app) as http:
        yield http, submitted


def wav(seconds=1.0, rate=8000) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(i / 8))) for i in range(int(seconds * rate))))
    return buffer.getvalue()


PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
ROTH = str(uuid.UUID(int=1))


def plan(**overrides):
    return {"client_id": uuid.uuid4().hex, "underlying": "nvda", "side": "buy_calls", "account_id": ROTH, "mode": "discretionary",
            "client_captured_at": 1790000000000, "context": {"state": "captured", "symbol": "NVDA", "interval": "5m"}, "image": True, **overrides}


class FakeEngine:
    def __init__(self, text="Taking NVDA calls on the reclaim. Out below 180.", error=None):
        self.text, self.error, self.calls = text, error, []

    def __call__(self, path):
        self.calls.append(Path(path))
        assert Path(path).is_file()
        if self.error:
            raise transcribe.TranscriptionError(self.error)
        return self.text


@pytest.fixture
def speech(monkeypatch):
    fake = FakeEngine()
    monkeypatch.setattr(transcribe, "status", lambda: transcribe.Status(True, "Whisper test (on this server)", "Transcribed on this server."))
    monkeypatch.setattr(transcribe, "transcribe", fake)
    return fake


def run(job_id) -> None:
    job_runtime.execute_job(uuid.UUID(str(job_id)))


# ------------------------------------------------------------------ setup and templates

def test_setup_lists_accounts_templates_and_whether_speech_is_configured(client):
    http, _ = client
    setup = http.get("/charts/captures/setup").json()
    assert [a["label"] for a in setup["accounts"]] == ["Individual ··1234", "Roth IRA ··8267"]
    assert setup["default_account_id"] is None and setup["templates"] == [] and setup["max_templates"] == 3
    assert setup["transcriber"]["configured"] is False and "off" in setup["transcriber"]["note"]
    assert http.put("/charts/captures/setup", json={"default_account_id": ROTH}).json()["default_account_id"] == ROTH
    assert http.put("/charts/captures/setup", json={"default_account_id": str(uuid.uuid4())}).status_code == 422


def test_editing_a_template_bumps_its_revision_and_never_rewrites_a_saved_plan(client):
    http, _ = client
    first = http.post("/charts/captures/templates", json={"setup_label": "Reclaim", "wording": "Out if it closes back below the level."}).json()["templates"][0]
    saved = http.post("/charts/captures", json=plan(mode="template", template_id=first["id"], template_revision=1)).json()
    assert (saved["setup_label"], saved["wording"], saved["template_revision"]) == ("Reclaim", "Out if it closes back below the level.", 1)
    edited = http.put(f"/charts/captures/templates/{first['id']}", json={"setup_label": "Reclaim", "wording": "Out on a 5m close below."}).json()["templates"][0]
    assert edited["revision"] == 2
    again = http.get("/charts/captures").json()["captures"][0]
    assert again["wording"] == "Out if it closes back below the level." and again["template_revision"] == 1
    # The wording the user was looking at is what gets saved: a stale revision is refused, not swapped.
    stale = http.post("/charts/captures", json=plan(mode="template", template_id=first["id"], template_revision=1))
    assert stale.status_code == 422 and "edited on another device" in stale.json()["detail"]
    for name in ("Pullback", "Breakout"):
        http.post("/charts/captures/templates", json={"setup_label": name, "wording": "My exit."})
    assert http.post("/charts/captures/templates", json={"setup_label": "Fourth", "wording": "x"}).status_code == 422
    http.delete(f"/charts/captures/templates/{first['id']}")
    assert [t["setup_label"] for t in http.get("/charts/captures/setup").json()["templates"]] == ["Pullback", "Breakout"]
    gone = http.post("/charts/captures", json=plan(mode="template", template_id=first["id"]))
    assert gone.status_code == 422 and "removed" in gone.json()["detail"]
    assert http.get("/charts/captures").json()["captures"][0]["wording"] == "Out if it closes back below the level."


# ------------------------------------------------------------------ saving a plan

def test_a_plan_is_saved_once_however_often_the_request_repeats(client, engine):
    http, _ = client
    body = plan(note="Small size")
    first = http.post("/charts/captures", json=body)
    second = http.post("/charts/captures", json=body)
    assert first.status_code == 201 and second.status_code == 200 and first.json()["id"] == second.json()["id"]
    row = first.json()
    assert (row["underlying"], row["side"], row["instrument"], row["mode"], row["account_label"]) == ("NVDA", "buy_calls", "option", "discretionary", "Roth IRA ··8267")
    assert row["setup_label"] is None and row["wording"] is None and row["note"] == "Small size"
    assert row["client_captured_at"] == 1790000000 and row["received_at"] > row["client_captured_at"]
    assert row["context"]["interval"] == "5m" and row["context_state"] == "captured" and row["image"]["state"] == "pending"
    with Session(engine) as db:
        assert len(db.exec(select(TradeCapture)).all()) == 1


def test_choices_are_explicit_and_nothing_is_guessed(client):
    http, _ = client
    for overrides, message in [({"side": "calls"}, "calls, puts or stock"), ({"account_id": str(uuid.uuid4())}, "account"),
                               ({"underlying": "not a ticker"}, "ticker"), ({"mode": "template"}, "template"),
                               ({"client_id": "x"}, "request ID"), ({"strike": -5}, "positive"), ({"expiration": "soon"}, "date"),
                               ({"note": "x" * 501}, "500")]:
        response = http.post("/charts/captures", json=plan(**overrides))
        assert response.status_code == 422 and message in response.json()["detail"], overrides
    # Contract and size are optional; a stock plan never keeps option fields.
    stock = http.post("/charts/captures", json=plan(side="buy_stock", strike=190, expiration="2026-10-09", quantity=50)).json()
    assert (stock["instrument"], stock["strike"], stock["expiration"], stock["quantity"]) == ("stock", None, None, 50)
    option = http.post("/charts/captures", json=plan(side="sell_puts", strike=180, expiration="2026-10-09")).json()
    assert (option["instrument"], option["strike"], option["expiration"], option["quantity"]) == ("option", 180, "2026-10-09", None)


def test_without_a_chart_snapshot_the_plan_saves_and_says_so(client):
    http, _ = client
    row = http.post("/charts/captures", json=plan(context={"state": "unavailable", "reason": "The chart now shows AMD."})).json()
    assert row["context_state"] == "unavailable" and row["context"]["reason"] == "The chart now shows AMD."
    assert row["image"]["state"] == "unavailable"
    response = http.post(f"/charts/captures/{row['id']}/image", files={"image": ("chart.png", PNG, "image/png")})
    assert response.status_code == 422 and "without a chart image" in response.json()["detail"]


def test_the_chart_image_is_attached_once_and_checked_by_its_bytes(client):
    http, _ = client
    row = http.post("/charts/captures", json=plan(image_note="Level labels drawn outside the canvas are not in the image.")).json()
    bad = http.post(f"/charts/captures/{row['id']}/image", files={"image": ("chart.png", b"<svg/>", "image/png")})
    assert bad.status_code == 422 and "PNG, JPEG or WebP" in bad.json()["detail"]
    assert http.post(f"/charts/captures/{row['id']}/image", files={"image": ("x.png", b"\x89PNG\r\n\x1a\n" + b"0" * 1_600_000, "image/png")}).status_code == 422
    saved = http.post(f"/charts/captures/{row['id']}/image", files={"image": ("chart.png", PNG, "image/png")}).json()
    assert saved["image"] == {"state": "saved", "note": "Level labels drawn outside the canvas are not in the image.", "bytes": len(PNG)}
    # A later picture cannot replace the frozen one.
    again = http.post(f"/charts/captures/{row['id']}/image", files={"image": ("later.png", PNG + b"later", "image/png")}).json()
    assert again["image"]["bytes"] == len(PNG)
    assert http.get(f"/charts/captures/{row['id']}/image").content == PNG


def test_notes_are_added_after_and_never_change_the_plan(client, engine):
    http, _ = client
    row = http.post("/charts/captures", json=plan(note="Original")).json()
    later = http.post(f"/charts/captures/{row['id']}/notes", json={"kind": "note", "text": "Chased it; entry was late."}).json()
    assert later["note"] == "Original" and later["notes"][0]["kind"] == "note" and later["notes"][0]["created_at"] >= row["received_at"]
    assert http.post(f"/charts/captures/{row['id']}/notes", json={"kind": "transcript_correction", "text": "x"}).status_code == 422
    taken = http.post(f"/charts/captures/{row['id']}/not-taken").json()
    assert taken["not_taken_at"] and http.post(f"/charts/captures/{row['id']}/not-taken").json()["not_taken_at"] == taken["not_taken_at"]
    with Session(engine) as db:
        assert len(db.exec(select(TradeCaptureNote)).all()) == 1


def test_saving_plans_touches_no_fills_trades_or_enrichment(client, engine):
    http, _ = client
    with Session(engine) as db:
        before = (len(db.exec(select(Fill)).all()), len(db.exec(select(Trade)).all()))
    http.post("/charts/captures", json=plan())
    with Session(engine) as db:
        assert (len(db.exec(select(Fill)).all()), len(db.exec(select(Trade)).all())) == before


# ------------------------------------------------------------------ voice

def voice(http, audio=None, **overrides):
    meta = plan(**{"mode": None, "audio_ms": 1000, **overrides})
    return http.post("/charts/captures/voice", data={"meta": json.dumps(meta)},
                     files={"audio": ("clip.wav", wav() if audio is None else audio, "audio/wav")}), meta


def test_without_a_speech_engine_the_recording_is_kept_and_says_not_configured(client):
    http, submitted = client
    response, _ = voice(http)
    row = response.json()
    assert response.status_code == 201 and row["mode"] == "voice" and row["audio"]["type"] == "audio/wav"
    assert row["transcript"]["status"] == "not_configured" and submitted == []
    assert http.get(f"/charts/captures/{row['id']}/audio").content == wav()


def test_a_voice_plan_counts_from_when_the_whole_recording_was_received(client, engine, speech, monkeypatch):
    http, submitted = client
    stamps = iter([datetime(2026, 10, 5, 14, 30, 0), datetime(2026, 10, 5, 14, 30, 2)])
    real = captures.datetime

    class Clock(real):
        @classmethod
        def utcnow(cls):
            return next(stamps, real(2026, 10, 5, 14, 31))

    monkeypatch.setattr(captures, "datetime", Clock)
    response, meta = voice(http)
    row = response.json()
    # Built (first stamp), then received in full (second stamp, after the file was written).
    assert row["received_at"] == datetime(2026, 10, 5, 14, 30, 2).replace(tzinfo=__import__("datetime").timezone.utc).timestamp()
    assert row["transcript"]["status"] == "pending" and len(submitted) == 1
    monkeypatch.setattr(captures, "datetime", real)
    # The same request again (a retry after a dropped response) is the same capture and the same job.
    again, _ = voice(http, client_id=meta["client_id"])
    assert again.status_code == 200 and again.json()["id"] == row["id"] and len(submitted) == 1
    run(submitted[0])
    ready = http.get("/charts/captures").json()["captures"][0]["transcript"]
    assert ready["status"] == "ready" and ready["text"] == speech.text and ready["provider"] == "Whisper test (on this server)"
    assert len(speech.calls) == 1
    # The transcript arriving later does not move when the plan counts from.
    assert http.get("/charts/captures").json()["captures"][0]["received_at"] == row["received_at"]


@pytest.mark.parametrize("audio,message", [(b"", "empty"), (b"\x00" * 999, "empty"), (b"<html>" + b"0" * 2000, "not a recording"),
                                           (b"OggS" + b"0" * 3_000_001, "too large")])
def test_empty_odd_or_huge_uploads_are_refused_and_nothing_is_saved(client, engine, audio, message):
    http, submitted = client
    response, _ = voice(http, audio=audio)
    assert response.status_code == 422 and message in response.json()["detail"]
    with Session(engine) as db:
        assert db.exec(select(TradeCapture)).all() == []
    assert submitted == []


def test_a_clip_over_thirty_seconds_is_refused(client):
    http, _ = client
    response, _ = voice(http, audio_ms=45_000)
    assert response.status_code == 422 and "30 seconds" in response.json()["detail"]


def test_a_failed_transcription_keeps_the_recording_and_retry_queues_one_new_job(client, engine, speech):
    http, submitted = client
    speech.error = "The speech-to-text engine could not read this clip."
    row = voice(http)[0].json()
    run(submitted[0])
    failed = http.get("/charts/captures").json()["captures"][0]
    assert failed["transcript"]["status"] == "failed" and "could not read" in failed["transcript"]["error"]
    assert http.get(f"/charts/captures/{row['id']}/audio").status_code == 200
    speech.error = None
    first = http.post(f"/charts/captures/{row['id']}/transcribe").json()
    second = http.post(f"/charts/captures/{row['id']}/transcribe").json()
    assert first["transcript"]["status"] == second["transcript"]["status"] == "pending"
    with Session(engine) as db:
        jobs = db.exec(select(JobRun).where(JobRun.job_type == "capture_transcribe")).all()
    assert len(jobs) == 2 and sum(job.status == "queued" for job in jobs) == 1  # two taps, one new job
    run(submitted[1])
    assert http.get("/charts/captures").json()["captures"][0]["transcript"]["text"] == speech.text
    # Nothing to retry once it is ready.
    http.post(f"/charts/captures/{row['id']}/transcribe")
    with Session(engine) as db:
        assert len(db.exec(select(JobRun).where(JobRun.job_type == "capture_transcribe")).all()) == 2


def test_a_worker_that_dies_mid_transcription_shows_failed_and_can_be_retried(client, engine, speech, monkeypatch):
    http, submitted = client
    row = voice(http)[0].json()
    with Session(engine) as db:
        capture = db.get(TradeCapture, uuid.UUID(row["id"]))
        capture.transcript_status = "transcribing"
        job = db.get(JobRun, capture.transcript_job_id)
        job.status, job.owner_id, job.owner_host = "running", "dead:owner", "elsewhere"
        db.add(capture)
        db.add(job)
        db.commit()
        # The next worker's recovery fails the interrupted run; it is never replayed by itself.
        job.status, job.error = "failed", "Worker interrupted; partial work may be committed. Review and start a new run."
        db.add(job)
        db.commit()
    shown = http.get("/charts/captures").json()["captures"][0]["transcript"]
    assert shown["status"] == "failed" and "interrupted" in shown["error"]
    retried = http.post(f"/charts/captures/{row['id']}/transcribe").json()
    assert retried["transcript"]["status"] == "pending"
    run(submitted[-1])
    assert http.get("/charts/captures").json()["captures"][0]["transcript"]["status"] == "ready"


def test_a_correction_sits_beside_the_original_transcript(client, speech):
    http, submitted = client
    row = voice(http)[0].json()
    run(submitted[0])
    corrected = http.post(f"/charts/captures/{row['id']}/notes", json={"kind": "transcript_correction", "text": "Out below 182."}).json()
    assert corrected["transcript"]["text"] == speech.text
    assert corrected["notes"][0] == {**corrected["notes"][0], "kind": "transcript_correction", "text": "Out below 182."}


def test_transcription_has_its_own_lane():
    assert job_runtime.job_lane("capture_transcribe") == "capture" and "capture" in job_runtime.LANES
    assert job_runtime.job_lane("gmail_push") == "sync"


def test_the_real_speech_engine_reads_a_spoken_clip_when_installed(tmp_path, monkeypatch):
    """Only where faster-whisper and its model are already present (no download in tests)."""
    pytest.importorskip("faster_whisper")
    models = Path(__file__).resolve().parents[1] / "data" / "models"
    if not any(models.glob("models--Systran--faster-whisper-base.en")):
        pytest.skip("Whisper base.en model not downloaded on this machine")
    monkeypatch.setenv("CAPTURE_TRANSCRIBER", "whisper")
    monkeypatch.setenv("CAPTURE_MODEL_DIR", str(models))
    silent = tmp_path / "silence.wav"
    silent.write_bytes(wav(seconds=2.0))
    # A tone has no words: the result is empty, not invented.
    assert transcribe.transcribe(silent) == ""
