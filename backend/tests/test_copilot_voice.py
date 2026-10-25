"""Copilot Lab hold-to-talk: POST /copilot/transcribe and spoken tickers. The speech engine is stubbed; no network."""
import logging
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.engine import captures, spoken_tickers, transcribe
from app.main import app
from app.models import Account, Trade
from tests.test_browser_access import boundary, signin  # noqa: F401  (the shared access fixture)
from tests.test_captures import engine, wav  # noqa: F401  (an in-memory database with two accounts)

WAV = wav(1.0)


@pytest.fixture
def lab(monkeypatch):
    monkeypatch.setenv("COPILOT_ENABLED", "true")
    monkeypatch.delenv("COPILOT_BACKEND", raising=False)
    with TestClient(app) as client:
        yield client


@pytest.fixture
def speech(monkeypatch):
    heard = {"text": "I want en bis calls if it holds 100", "paths": [], "prompts": []}

    def fake(path, prompt=None):
        assert Path(path).is_file()
        heard["paths"].append(Path(path))
        heard["prompts"].append(prompt)
        return heard["text"]

    monkeypatch.setattr(transcribe, "status", lambda: transcribe.Status(True, "Whisper test (on this server)", "Transcribed here."))
    monkeypatch.setattr(transcribe, "transcribe", fake)
    return heard


def _post(client, audio=WAV, **form):
    return client.post("/copilot/transcribe", files={"audio": ("clip.wav", audio, "audio/wav")}, data=form)


def test_a_clip_comes_back_as_text_with_tickers_mapped_and_the_audio_is_gone(lab, speech, caplog):
    with caplog.at_level(logging.DEBUG):
        response = _post(lab, audio_ms="2500")
    assert response.status_code == 200
    body = response.json()
    assert body == {"text": "I want NBIS calls if it holds 100", "heard": speech["text"],
                    "tickers": [{"heard": "en bis", "symbol": "NBIS"}], "provider": "Whisper test (on this server)"}
    # Nothing is kept: the temporary clip is deleted, and neither audio nor words reach the log.
    assert speech["paths"] and not any(path.exists() for path in speech["paths"])
    assert speech["text"] not in caplog.text
    # Whisper is told which symbols to expect.
    assert speech["prompts"][0].startswith("Tickers: AAOI, AAPL")


def test_size_and_duration_are_capped_like_voice_plans(lab, speech):
    big = WAV + b"\x00" * (captures.AUDIO_MAX + 10 - len(WAV))
    assert _post(lab, audio=big).status_code == 413
    assert _post(lab, audio=b"RIFF").status_code == 422  # empty
    assert _post(lab, audio=b"not audio" * 400).status_code == 422
    too_long = _post(lab, audio_ms=str(captures.CLIP_MS + 5000))
    assert too_long.status_code == 422 and "30 seconds" in too_long.json()["detail"]
    assert speech["paths"] == []
    assert lab.post("/copilot/transcribe", data={}).status_code == 422  # neither audio nor text


def test_an_unconfigured_transcriber_answers_clearly_and_browser_text_still_maps(lab, monkeypatch):
    monkeypatch.setenv("CAPTURE_TRANSCRIBER", "off")
    status = lab.get("/copilot/status").json()
    assert status["capabilities"]["transcriber"] == {"configured": False, "provider": "none"}
    response = _post(lab)
    assert response.status_code == 503 and "turned off" in response.json()["detail"] and "Type the message" in response.json()["detail"]
    # The browser's own recognition: only the tickers change.
    text = lab.post("/copilot/transcribe", data={"text": "N-B-I-S over the high, nebius looks strong"}).json()
    assert text["text"] == "NBIS over the high, NBIS looks strong" and text["provider"] == "browser"


def test_the_route_is_off_with_the_lab(monkeypatch, speech):
    monkeypatch.delenv("COPILOT_ENABLED", raising=False)
    with TestClient(app) as client:
        assert _post(client).status_code == 503
    assert speech["paths"] == []


def test_assistant_sessions_cannot_transcribe(boundary, speech):  # noqa: F811
    boundary.patch.setenv("COPILOT_ENABLED", "true")
    form = {"files": {"audio": ("clip.wav", WAV, "audio/wav")}}
    assert boundary.owner.post("/copilot/transcribe", **form).status_code == 200
    assert signin(boundary).status_code == 200
    assert boundary.public.post("/copilot/transcribe", **form).status_code == 403
    assert boundary.public.post("/copilot/transcribe", data={"text": "en bis"}).status_code == 403


KNOWN = spoken_tickers.known_symbols(["TQQQ"])


@pytest.mark.parametrize("heard,expected", [
    ("I want en bis calls above 100", "I want NBIS calls above 100"),
    ("N-B-I-S looks strong", "NBIS looks strong"),
    ("en bee eye ess", "NBIS"),
    ("N-BIS reclaim", "NBIS reclaim"),
    ("Nebius is breaking out", "NBIS is breaking out"),
    ("applied digital puts", "APLD puts"),
    ("C-R-W-V and palantir", "CRWV and PLTR"),
    ("T-Q-Q-Q", "TQQQ"),  # a traded ticker outside Radar
])
def test_spoken_tickers_map_to_known_symbols(heard, expected):
    assert spoken_tickers.map_tickers(heard, KNOWN)[0] == expected


@pytest.mark.parametrize("heard", [
    "I see you are why", "applied to everything", "the setup isn't coherent", "a b", "em you",
    "X-Y-Z-Q is not a symbol", "SPY puts", "spy on the open",
])
def test_unclear_speech_is_left_as_heard(heard):
    assert spoken_tickers.map_tickers(heard, KNOWN) == (heard, [])


def test_traded_tickers_count_as_known_most_traded_first(engine):  # noqa: F811
    with Session(engine) as db:
        account = db.exec(select(Account)).first()
        for ticker in ["TQQQ", "TQQQ", "NBIS", "BRK.B"]:
            db.add(Trade(account_id=account.id, ticker=ticker, instrument_type="stock", contracts=1, avg_entry_premium=1,
                         total_premium_paid=1, status="closed", opened_at=datetime(2026, 10, 1)))
        db.commit()
        traded = spoken_tickers.traded(db)
    assert traded[:2] == ["TQQQ", "NBIS"] and "BRK.B" not in traded
    assert "TQQQ" in spoken_tickers.known_symbols(traded)
    assert spoken_tickers.prompt_for(spoken_tickers.known_symbols(traded), traded).startswith("Tickers: TQQQ, NBIS, AAOI")
