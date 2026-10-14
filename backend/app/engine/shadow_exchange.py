"""File exchange for the isolated Shadow S1 decision loop.

The exchange is deliberately a small I/O boundary: files use canonical JSON,
are content addressed, and are replaced atomically so the check service never
observes a partial setup or decision.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

SETUP_FORMAT = "shadow-setup-v1"
DECISION_FORMAT = "shadow-decision-v1"


class ShadowExchangeError(ValueError):
    """A setup or decision file does not match the frozen exchange format."""


def canonical(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def digest(value: dict) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def utc_z(value: datetime) -> str:
    aware = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return aware.isoformat(timespec="microseconds").replace("+00:00", "Z")


def setup_payload(candidate, candles=None, *, version=SETUP_FORMAT) -> dict:
    payload = {
        "format": version,
        "candidate_id": str(candidate.id),
        "scanner_version": candidate.scanner_version,
        "params_hash": candidate.params_hash,
        "session_date": candidate.session_date.isoformat(),
        "symbol": candidate.symbol,
        "setup": candidate.setup,
        "direction": candidate.direction,
        "bar_start": utc_z(candidate.bar_start),
        "bar_end": utc_z(candidate.bar_end),
        "detected_at": utc_z(candidate.detected_at),
        "expires_at": utc_z(candidate.expires_at),
        "stop": candidate.stop,
        "target": candidate.target,
        "flags": json.loads(candidate.flags_json),
        "facts": json.loads(candidate.facts_json),
        "contract": json.loads(candidate.contract_json),
    }
    if version == "shadow-setup-v2":
        payload.update({"candles": candles, "candles_as_of": candles.get("last_bar_time") if candles else None})
        if not candles:
            payload["candles_unavailable"] = "scanner bars were not frozen at detection"
    payload["content_sha256"] = digest(payload)
    return payload


def atomic_write(path: Path, value: dict) -> None:
    """Write canonical JSON with mode 0640 and durable rename semantics."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp = Path(temp_name)
    try:
        os.fchmod(fd, 0o640)
        with os.fdopen(fd, "wb") as stream:
            stream.write(canonical(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
        dir_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except BaseException:
        try:
            temp.unlink(missing_ok=True)
        finally:
            raise


def write_setup(directory: str | Path, candidate, candles=None) -> dict:
    payload = setup_payload(candidate, candles, version="shadow-setup-v2")
    atomic_write(Path(directory) / f"setup-{candidate.id}.json", payload)
    return payload


def read_decision(directory: str | Path, candidate, candles=None) -> dict | None:
    path = Path(directory) / f"decision-{candidate.id}.json"
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return None
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ShadowExchangeError("decision file is not valid JSON") from exc
    if not isinstance(value, dict):
        raise ShadowExchangeError("decision file must contain an object")
    supplied_hash = value.get("content_sha256")
    unhashed = {key: item for key, item in value.items() if key != "content_sha256"}
    if value.get("format") != DECISION_FORMAT:
        raise ShadowExchangeError("decision format is invalid")
    if value.get("candidate_id") != str(candidate.id) or path.name != f"decision-{candidate.id}.json":
        raise ShadowExchangeError("decision candidate ID or filename is invalid")
    if not isinstance(supplied_hash, str) or supplied_hash != digest(unhashed):
        raise ShadowExchangeError("decision content hash is invalid")
    expected_hashes = {setup_payload(candidate)["content_sha256"],
        setup_payload(candidate, candles, version="shadow-setup-v2")["content_sha256"]}
    if value.get("setup_sha256") not in expected_hashes:
        raise ShadowExchangeError("decision setup hash does not match the saved candidate")
    if value.get("decision") not in ("take", "skip") or value.get("timing") not in ("on_time", "late"):
        raise ShadowExchangeError("decision or timing value is invalid")
    if not isinstance(value.get("labels"), list):
        raise ShadowExchangeError("decision labels are invalid")
    try:
        datetime.fromisoformat(value["committed_at"].replace("Z", "+00:00"))
    except (KeyError, AttributeError, ValueError) as exc:
        raise ShadowExchangeError("decision commit time is invalid") from exc
    return value



def candle_packet(minutes, five_minutes, cutoff, *, limit):
    """Copy observed completed rows only; no resampling or filling missing minutes."""
    one = [dict(row) for row in minutes if row["end_time"] <= cutoff][-limit:]
    five = [dict(row) for row in five_minutes if row["end"] <= cutoff]
    if not one:
        return None
    return {"source": "tradier_timesales_1min", "feed": "full_market",
        "last_bar_time": utc_z(datetime.fromtimestamp(one[-1]["end_time"], UTC)),
        "1m": one, "5m": five}
