"""Speech to text for voice captures (Charts C3.5): one configured provider.

The provider is Whisper run on this server through ``faster-whisper``: no
account, no per-clip charge, and the audio never leaves TradeJournal. The
model (``CAPTURE_WHISPER_MODEL``, ``base.en`` by default, about 150 MB) is
downloaded once from Hugging Face into ``CAPTURE_MODEL_DIR``; only the model
travels, never a recording. ``CAPTURE_TRANSCRIBER=off`` turns transcription
off; recordings are still saved and say so.

Output is literal: no rewording, no summary, and nothing about ticker, account
or side is changed by what was heard. Unclear speech stays unclear.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)
TIME_LIMIT = 180  # seconds for one 30-second clip; a slower run is abandoned, never retried by itself

_model = None
_model_name: str | None = None
_lock = threading.Lock()


@dataclass(frozen=True)
class Status:
    configured: bool
    provider: str
    note: str


def model_name() -> str:
    return os.environ.get("CAPTURE_WHISPER_MODEL", "base.en")


def model_dir() -> Path:
    configured = os.environ.get("CAPTURE_MODEL_DIR")
    return Path(configured) if configured else Path(__file__).resolve().parents[2] / "data" / "models"


def status() -> Status:
    if os.environ.get("CAPTURE_TRANSCRIBER", "whisper").lower() in ("off", "false", "0", "none"):
        return Status(False, "none", "Transcription is turned off on this server. Recordings are saved and can be played back.")
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        return Status(False, "none", "The speech-to-text engine is not installed on this server. Recordings are saved and can be played back.")
    return Status(True, f"Whisper {model_name()} (on this server)",
                  "Transcribed on this server by Whisper; your audio never leaves TradeJournal.")


class TranscriptionError(RuntimeError):
    pass


def _load():
    global _model, _model_name
    with _lock:
        if _model is None or _model_name != model_name():
            from faster_whisper import WhisperModel
            directory = model_dir()
            directory.mkdir(parents=True, exist_ok=True)
            _model = WhisperModel(model_name(), device="cpu", compute_type="int8", download_root=str(directory))
            _model_name = model_name()
        return _model


def transcribe(path: Path) -> str:
    """The words in one clip, as heard. Raises TranscriptionError."""
    if not status().configured:
        raise TranscriptionError(status().note)
    started = time.monotonic()
    try:
        model = _load()
        segments, _ = model.transcribe(str(path), beam_size=5, vad_filter=True, condition_on_previous_text=False)
        words = []
        for segment in segments:
            if time.monotonic() - started > TIME_LIMIT:
                raise TranscriptionError(f"Transcription took longer than {TIME_LIMIT} seconds and was stopped.")
            words.append(segment.text.strip())
    except TranscriptionError:
        raise
    except Exception as exc:  # decoding, model download or runtime failures
        log.exception("Transcription failed for %s", path.name)
        raise TranscriptionError(f"The speech-to-text engine could not read this clip: {exc}") from exc
    return " ".join(word for word in words if word)
