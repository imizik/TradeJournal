"""Content-addressed per-trade feature file for the pre-trade check service.

The finite publisher (pretrade_feature_publish.py) writes it; the check
service only reads it. No database, credential or network access here. A
missing or invalid file means "no history", never invented rows.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from types import SimpleNamespace

from journal_coach_publication import _atomic_file, _read_regular, _safe_path

FORMAT = "pretrade-features-v1"
POINTER_MAX = 256
FEATURES_MAX = 16 * 1024 * 1024
KEEP_PREVIOUS = 2
FEATURE_KEYS = frozenset({
    "closed_at", "opened_at", "underlying", "side", "time_bucket", "vwap_bucket", "trend_aligned", "chase",
    "late_move", "rvol_bucket", "dte_bucket", "realized_pnl", "pnl_pct", "mfe_pct", "mae_pct", "giveback_pct",
    "source_fill_key",
})
_HEX = re.compile(r"^[0-9a-f]{64}$")


def _when(value):
    return datetime.fromisoformat(value) if isinstance(value, str) else value


def rows_from_view(records) -> list[dict]:
    """Map narrow-view rows to the engine's feature rows (one mapping, the engine's)."""
    from app.engine.pretrade_check import feature_row

    rows = []
    for item in records:
        item = dict(item)
        trade = SimpleNamespace(closed_at=_when(item["closed_at"]), opened_at=_when(item["opened_at"]),
            ticker=item["ticker"], instrument_type=item["instrument_type"], option_type=item["option_type"],
            entry_time_bucket=item["trade_time_bucket"], realized_pnl=item["realized_pnl"], pnl_pct=item["pnl_pct"])
        # The view already replaced the raw fill key with its SHA-256.
        entry = SimpleNamespace(raw_email_id=item["source_fill_key"])
        context = None if not item["has_context"] else SimpleNamespace(
            entry_time_bucket=item["context_time_bucket"], entry_vs_vwap_pct=item["entry_vs_vwap_pct"],
            is_trend_aligned=item["is_trend_aligned"], is_chase_entry=item["is_chase_entry"],
            is_late_move=item["is_late_move"], rvol_time_adjusted=item["rvol_time_adjusted"],
            dte_bucket=item["dte_bucket"])
        path = None if not item["has_path"] else SimpleNamespace(
            underlying_mfe_pct=item["underlying_mfe_pct"], underlying_mae_pct=item["underlying_mae_pct"],
            underlying_giveback_pct=item["underlying_giveback_pct"])
        rows.append(feature_row(trade, entry, context, path))
    return sorted(rows, key=lambda row: (row["closed_at"], row["source_fill_key"]))


def _payload(rows: list[dict], generated_at: datetime) -> bytes:
    for row in rows:
        if set(row) != FEATURE_KEYS or not _HEX.fullmatch(str(row["source_fill_key"])):
            raise ValueError("Feature rows must have the exact approved fields and hashed fill keys")
    body = json.dumps({"format": FORMAT, "generated_at": generated_at.astimezone(timezone.utc).isoformat(),
        "row_count": len(rows), "rows": rows}, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    if len(body) > FEATURES_MAX:
        raise ValueError("Feature file exceeds its bound")
    return body


def _fsync_directory(directory: Path):
    descriptor = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def publish(rows: list[dict], pointer_file, *, now: datetime | None = None) -> dict:
    """Write features-<sha>.json once, then atomically repoint current.json."""
    pointer = _safe_path(pointer_file)
    directory = pointer.parent
    if not stat.S_ISDIR(directory.lstat().st_mode):
        raise ValueError("Feature directory must already exist")
    payload = _payload(rows, now or datetime.now(timezone.utc))
    digest = hashlib.sha256(payload).hexdigest()
    target = directory / f"features-{digest}.json"
    if target.exists() or target.is_symlink():
        if _read_regular(_safe_path(target), FEATURES_MAX) != payload:
            raise ValueError("Content-addressed feature file differs from its name")
    else:
        temporary = _atomic_file(directory, payload, mode=0o640)
        try:
            os.link(temporary, target, follow_symlinks=False)
        finally:
            temporary.unlink(missing_ok=True)
    temporary = _atomic_file(directory, json.dumps({"features_sha256": digest}).encode(), mode=0o640)
    try:
        os.replace(temporary, pointer)
    finally:
        temporary.unlink(missing_ok=True)
    _fsync_directory(directory)
    _retain(directory, digest)
    return {"features_sha256": digest, "row_count": len(rows)}


def _retain(directory: Path, current: str):
    """Best effort: keep the current file and the two newest previous ones we own."""
    owned = []
    for entry in directory.iterdir():
        match = re.fullmatch(r"features-([0-9a-f]{64})\.json", entry.name)
        if not match or match.group(1) == current:
            continue
        info = entry.lstat()
        if stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid():
            owned.append((info.st_mtime, entry))
    for _, entry in sorted(owned, reverse=True)[KEEP_PREVIOUS:]:
        entry.unlink(missing_ok=True)


def read_current(pointer_file, *, max_age_seconds: int, now: datetime | None = None) -> dict:
    """Return {state, rows, ...}: fresh/stale rows, or missing with rows None."""
    now = now or datetime.now(timezone.utc)
    try:
        pointer = _safe_path(pointer_file)
        value = json.loads(_read_regular(pointer, POINTER_MAX))
        if not isinstance(value, dict) or set(value) != {"features_sha256"} or not _HEX.fullmatch(str(value["features_sha256"])):
            raise ValueError("Invalid feature pointer")
        digest = value["features_sha256"]
        raw = _read_regular(_safe_path(pointer.parent / f"features-{digest}.json"), FEATURES_MAX)
        if hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError("Feature file does not match its digest")
        document = json.loads(raw)
        if (not isinstance(document, dict) or set(document) != {"format", "generated_at", "row_count", "rows"}
                or document["format"] != FORMAT or not isinstance(document["rows"], list)
                or document["row_count"] != len(document["rows"])
                or any(not isinstance(row, dict) or set(row) != FEATURE_KEYS for row in document["rows"])):
            raise ValueError("Invalid feature file")
        generated = datetime.fromisoformat(document["generated_at"])
        if generated.tzinfo is None:
            raise ValueError("Feature file time must be timezone-aware")
        age = (now - generated).total_seconds()
        if age < -60:
            raise ValueError("Feature file is from the future")
    except (OSError, ValueError, TypeError, KeyError, UnicodeDecodeError):
        return {"state": "missing", "rows": None, "features_sha256": None, "generated_at": None, "age_seconds": None}
    return {"state": "stale" if age > max_age_seconds else "fresh", "rows": document["rows"],
        "features_sha256": digest, "generated_at": document["generated_at"], "age_seconds": max(0, int(age))}
