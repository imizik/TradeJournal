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
CONTEXT_FORMAT = "pretrade-context-v1"
CONTEXT_MAX = 4 * 1024 * 1024
POSITION_KEYS = frozenset({
    "ticker", "instrument_type", "option_type", "strike", "expiration", "contracts", "avg_entry_premium",
    "total_premium_paid", "opened_at", "entry_time_bucket", "account_name", "account_type",
})
MARKET_FORMAT = "pretrade-market-v1"
MARKET_KEYS = frozenset({
    "kind", "symbol", "event_date", "status", "label", "value", "change_pct", "observed_at", "fetched_at", "source",
})
CAPTURE_KEYS = frozenset({
    "received_at", "underlying", "side", "instrument", "mode", "setup_label", "wording", "note", "strike",
    "expiration", "quantity", "transcript_text", "not_taken_at", "account_name", "account_type", "latest_note",
    "linked",
})


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


def _plain(value):
    """JSON-safe scalar: dates/times as ISO strings, decimals as floats."""
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return float(value)


def context_rows(records, keys) -> list[dict]:
    rows = []
    for item in records:
        item = dict(item)
        if set(item) != keys:
            raise ValueError("Context rows must have the exact approved fields")
        rows.append({key: _plain(item[key]) for key in sorted(keys)})
    return rows


def _publish_addressed(pointer_file, prefix: str, payload: bytes, limit: int) -> str:
    """Write <prefix>-<sha>.json once, then atomically repoint the pointer file at it."""
    pointer = _safe_path(pointer_file)
    directory = pointer.parent
    if not stat.S_ISDIR(directory.lstat().st_mode):
        raise ValueError("Context directory must already exist")
    if len(payload) > limit:
        raise ValueError("Context file exceeds its bound")
    digest = hashlib.sha256(payload).hexdigest()
    target = directory / f"{prefix}-{digest}.json"
    if target.exists() or target.is_symlink():
        if _read_regular(_safe_path(target), limit) != payload:
            raise ValueError("Content-addressed context file differs from its name")
    else:
        temporary = _atomic_file(directory, payload, mode=0o640)
        try:
            os.link(temporary, target, follow_symlinks=False)
        finally:
            temporary.unlink(missing_ok=True)
    temporary = _atomic_file(directory, json.dumps({f"{prefix}_sha256": digest}).encode(), mode=0o640)
    try:
        os.replace(temporary, pointer)
    finally:
        temporary.unlink(missing_ok=True)
    _fsync_directory(directory)
    _retain(directory, digest, prefix=prefix)
    return digest


def _read_addressed(pointer_file, prefix: str, limit: int, fields: set, now: datetime) -> tuple[dict, float]:
    """The document the pointer names, verified against its digest; raises on anything unexpected."""
    pointer = _safe_path(pointer_file)
    value = json.loads(_read_regular(pointer, POINTER_MAX))
    key = f"{prefix}_sha256"
    if not isinstance(value, dict) or set(value) != {key} or not _HEX.fullmatch(str(value[key])):
        raise ValueError("Invalid context pointer")
    digest = value[key]
    raw = _read_regular(_safe_path(pointer.parent / f"{prefix}-{digest}.json"), limit)
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError("Context file does not match its digest")
    document = json.loads(raw)
    if not isinstance(document, dict) or set(document) != fields:
        raise ValueError("Invalid context file")
    generated = datetime.fromisoformat(document["generated_at"])
    if generated.tzinfo is None or (now - generated).total_seconds() < -60:
        raise ValueError("Invalid context time")
    return document, (now - generated).total_seconds()


_UNREADABLE = (OSError, ValueError, TypeError, KeyError, UnicodeDecodeError, AttributeError)


def publish_context(positions: list[dict], captures: list[dict], pointer_file, *, now: datetime | None = None) -> dict:
    """Open positions and recent captures: context-<sha>.json, then atomically repoint context.json."""
    if any(set(row) != POSITION_KEYS for row in positions) or any(set(row) != CAPTURE_KEYS for row in captures):
        raise ValueError("Context rows must have the exact approved fields")
    payload = json.dumps({"format": CONTEXT_FORMAT, "generated_at": (now or datetime.now(timezone.utc)).astimezone(
        timezone.utc).isoformat(), "positions": positions, "captures": captures}, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode()
    digest = _publish_addressed(pointer_file, "context", payload, CONTEXT_MAX)
    return {"context_sha256": digest, "positions": len(positions), "captures": len(captures)}


def read_context(pointer_file, *, max_age_seconds: int, now: datetime | None = None) -> dict:
    """Return {state, positions, captures, generated_at, age_seconds}; missing means none, never invented."""
    now = now or datetime.now(timezone.utc)
    try:
        document, age = _read_addressed(pointer_file, "context", CONTEXT_MAX,
            {"format", "generated_at", "positions", "captures"}, now)
        if (document["format"] != CONTEXT_FORMAT
                or any(not isinstance(r, dict) or set(r) != POSITION_KEYS for r in document["positions"])
                or any(not isinstance(r, dict) or set(r) != CAPTURE_KEYS for r in document["captures"])):
            raise ValueError("Invalid context file")
    except _UNREADABLE:
        return {"state": "missing", "positions": None, "captures": None, "generated_at": None, "age_seconds": None}
    return {"state": "stale" if age > max_age_seconds else "fresh", "positions": document["positions"],
        "captures": document["captures"], "generated_at": document["generated_at"], "age_seconds": max(0, int(age))}


def publish_market(items: list[dict], pointer_file, *, now: datetime | None = None) -> dict:
    """Earnings dates and VIX from the private backend's snapshot: market-<sha>.json, then repoint market.json."""
    if any(set(row) != MARKET_KEYS for row in items):
        raise ValueError("Market rows must have the exact approved fields")
    payload = json.dumps({"format": MARKET_FORMAT, "generated_at": (now or datetime.now(timezone.utc)).astimezone(
        timezone.utc).isoformat(), "items": items}, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return {"market_sha256": _publish_addressed(pointer_file, "market", payload, CONTEXT_MAX), "items": len(items)}


def read_market(pointer_file, *, max_age_seconds: int, now: datetime | None = None) -> dict:
    """Return {state, items, generated_at, age_seconds}; missing means none, never invented."""
    now = now or datetime.now(timezone.utc)
    try:
        document, age = _read_addressed(pointer_file, "market", CONTEXT_MAX, {"format", "generated_at", "items"}, now)
        if document["format"] != MARKET_FORMAT or any(not isinstance(r, dict) or set(r) != MARKET_KEYS
                                                      for r in document["items"]):
            raise ValueError("Invalid market file")
    except _UNREADABLE:
        return {"state": "missing", "items": None, "generated_at": None, "age_seconds": None}
    return {"state": "stale" if age > max_age_seconds else "fresh", "items": document["items"],
        "generated_at": document["generated_at"], "age_seconds": max(0, int(age))}


def _retain(directory: Path, current: str, prefix: str = "features"):
    """Best effort: keep the current file and the two newest previous ones we own."""
    owned = []
    for entry in directory.iterdir():
        match = re.fullmatch(prefix + r"-([0-9a-f]{64})\.json", entry.name)
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
