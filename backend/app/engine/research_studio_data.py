"""Explicit-root, read-only R1 minute snapshots. No provider, environment or DB.

Only fixed roster filenames are opened, via no-follow directory descriptors.
Selected bytes are parsed/hashed once into an in-memory immutable snapshot;
no existing Factory pickle/evidence cache is consulted or created.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import stat

from app.engine.market_map import Bar, ET, resample
from app.engine.research_studio import (
    CORE_UNIVERSE, DISCOVERY_START, MARKET, Coverage, Snapshot, SymbolSnapshot,
    session_close, session_dates, validate_source_date, validate_symbol,
)

MAX_FILE_BYTES = 8 * 1024 * 1024


def engine_fingerprint() -> str:
    root = Path(__file__).resolve().parent
    fingerprint = hashlib.sha256()
    for name in ("research_studio.py", "research_studio_data.py", "factory_data.py", "factory_rules.py", "market_map.py"):
        fingerprint.update(name.encode())
        fingerprint.update((root / name).read_bytes())
    return fingerprint.hexdigest()


def _decode(payload: bytes, day: date) -> tuple[list[Bar], Coverage]:
    raw = json.loads(payload)
    if not isinstance(raw, list):
        raise ValueError("minute cache must contain a list")
    slots = {}
    repeated = set()
    invalid = off_grid = 0
    for row in raw:
        if not isinstance(row, dict) or not isinstance(row.get("t"), str):
            raise ValueError("minute row needs an explicit timestamp")
        moment = datetime.fromisoformat(row["t"].replace("Z", "+00:00"))
        if moment.tzinfo is None or moment.utcoffset() is None:
            raise ValueError("minute timestamp needs an explicit timezone")
        local = moment.astimezone(ET)
        if local.date() != day:
            raise ValueError("minute timestamp differs from bounded filename day")
        minute = local.hour * 60 + local.minute
        if not 570 <= minute < session_close(day):
            continue
        if local.second or local.microsecond:
            off_grid += 1
            continue
        if minute in slots:
            repeated.add(minute)
        values = tuple(row.get(name) for name in ("o", "h", "l", "c", "v"))
        valid = (all(type(x) in (int, float) and math.isfinite(x) for x in values)
                 and min(values[:4]) > 0 and values[4] >= 0
                 and values[1] >= max(values[0], values[2], values[3])
                 and values[2] <= min(values[0], values[1], values[3]))
        if not valid:
            invalid += 1
        slots[minute] = Bar(moment.astimezone(timezone.utc), *map(float, values)) if valid else None
    # Duplicate/invalid observations never become a complete research minute.
    minutes = [b for m, b in sorted(slots.items()) if b is not None and m not in repeated]
    mask = sum(1 << (b.time.astimezone(ET).hour * 60 + b.time.astimezone(ET).minute - 570) for b in minutes)
    coverage = Coverage(day, "present" if raw else "empty", mask, invalid, len(repeated), off_grid)
    return resample(minutes, 5), coverage


class DiscoveryCache:
    """Operator-approved SIP root. Requests cannot choose a file/cache path.

    Root selection is a local operator responsibility, not an HTTP argument.
    POSIX no-follow support is required; unsupported platforms fail closed.
    """

    def __init__(self, approved_root: Path, *, allow_newer_mu: bool = False):
        if type(allow_newer_mu) is not bool:
            raise ValueError("explicit newer MU approval required")
        self.allow_newer_mu = allow_newer_mu
        self.root = Path(approved_root).resolve(strict=True)
        if self.root.name != "sip":
            raise ValueError("approved root must be the SIP minute-cache directory")
        if not hasattr(os, "O_NOFOLLOW") or os.open not in os.supports_dir_fd:
            raise ValueError("cache reader requires POSIX no-follow directory descriptors")
        # Resolution allows the operator's existing cache alias. Binding must
        # not follow an ancestor replaced after that resolution.
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        directory = os.open(self.root.anchor, flags)
        try:
            for part in self.root.parts[1:]:
                child = os.open(part, flags, dir_fd=directory)
                os.close(directory)
                directory = child
            approved = os.fstat(directory)
            self._root_identity = (approved.st_dev, approved.st_ino)
        finally:
            os.close(directory)

    def _read(self, symbol: str, day: date, *, version: int = 1) -> bytes | None:
        validate_symbol(symbol, market=True)
        validate_source_date(day, version=version)
        if version == 2 and (not self.allow_newer_mu or symbol not in ("MU", MARKET)):
            raise ValueError("newer MU source is not operator-approved")
        # A payload read is impossible until both request boundaries validate.
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        root_fd = os.open(self.root, flags)
        try:
            opened = os.fstat(root_fd)
            if (opened.st_dev, opened.st_ino) != self._root_identity:
                raise ValueError("approved root directory changed; create a new reader")
            try:
                symbol_fd = os.open(symbol, flags, dir_fd=root_fd)
            except FileNotFoundError:
                return None
            try:
                try:
                    fd = os.open(day.isoformat() + ".json", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                                 dir_fd=symbol_fd)
                except FileNotFoundError:
                    return None
                with os.fdopen(fd, "rb") as handle:
                    info = os.fstat(handle.fileno())
                    if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_FILE_BYTES:
                        raise ValueError("minute cache must be a bounded regular file")
                    payload = handle.read(MAX_FILE_BYTES + 1)
                    if len(payload) > MAX_FILE_BYTES:
                        raise ValueError("minute cache exceeded snapshot byte bound")
                    return payload
            finally:
                os.close(symbol_fd)
        finally:
            os.close(root_fd)

    def snapshot(self, symbols: tuple[str, ...] = CORE_UNIVERSE, *, through: date,
                 cursor: date | None = None, version: int = 1) -> Snapshot:
        validate_source_date(through, version=version)
        if version == 2 and (not self.allow_newer_mu or symbols != ("MU",)):
            raise ValueError("newer MU source is not operator-approved")
        if cursor is not None:
            validate_source_date(cursor, version=version)
            if cursor < DISCOVERY_START or cursor > through:
                raise ValueError("cursor outside requested discovery interval")
            through = cursor
        if type(symbols) is not tuple or not symbols or len(set(symbols)) != len(symbols):
            raise ValueError("distinct target symbols required")
        for symbol in symbols:
            validate_symbol(symbol)
        dates = session_dates(through, version=version)
        sources, manifest = [], []
        for symbol in (*sorted(symbols), MARKET):
            bars, coverage = [], []
            for day in dates:
                payload = self._read(symbol, day) if version == 1 else self._read(symbol, day, version=version)
                if payload is None:
                    manifest.append((symbol, str(day), "missing", 0))
                    coverage.append(Coverage(day, "missing"))
                else:
                    manifest.append((symbol, str(day), hashlib.sha256(payload).hexdigest(), len(payload)))
                    rows, cov = _decode(payload, day)
                    bars.extend(rows)
                    coverage.append(cov)
            sources.append(SymbolSnapshot(symbol, tuple(bars), tuple(coverage)))
        return Snapshot(through, tuple(sources), tuple(manifest), engine_fingerprint(), source_version=version)
