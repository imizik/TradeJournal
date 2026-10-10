"""Atomic, read-only publication pointer for journal coach snapshots."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from journal_coach_snapshot import MAX_SNAPSHOT_BYTES, Snapshot, load_snapshot_bytes

_ET = ZoneInfo("America/New_York")
_HEX = re.compile(r"^[0-9a-f]{64}$")
_POINTER_MAX = 256


def rolling_window(now: datetime, days: int) -> tuple[date, date]:
    """Return inclusive Eastern calendar dates ending at ``now``."""
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 31:
        raise ValueError("days must be an integer from 1 through 31")
    end = now.astimezone(_ET).date()
    return end - timedelta(days=days - 1), end


def _safe_path(path: str | Path) -> Path:
    raw_path = os.fspath(path)
    p = Path(path)
    if not p.is_absolute() or ".." in p.parts or os.path.normpath(raw_path) != raw_path:
        raise ValueError("publication path must be canonical and absolute")
    # Inspect every existing component without following a symlink.
    for component in (p, *p.parents):
        try:
            info = component.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode):
            raise ValueError("publication path contains a symlink")
    return p


def _read_regular(path: Path, limit: int) -> bytes:
    try:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        fd = os.open(path, flags)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode):
                raise ValueError("publication file is not regular")
            if info.st_size > limit:
                raise ValueError("publication file is oversized")
            chunks = bytearray()
            while len(chunks) <= limit:
                part = os.read(fd, min(65536, limit + 1 - len(chunks)))
                if not part:
                    break
                chunks.extend(part)
            if len(chunks) > limit:
                raise ValueError("publication file is oversized")
            return bytes(chunks)
        finally:
            os.close(fd)
    except OSError as exc:
        raise ValueError("publication file could not be read") from exc


def publication_digest(path: str | Path) -> str:
    """Read a small strict JSON pointer and return its snapshot digest."""
    p = _safe_path(path)
    raw = _read_regular(p, _POINTER_MAX)
    def no_duplicates(pairs):
        result = {}
        for key, item in pairs:
            if key in result:
                raise ValueError("publication pointer contains duplicate fields")
            result[key] = item
        return result

    try:
        value = json.loads(raw, object_pairs_hook=no_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("publication pointer is invalid JSON") from exc
    if not isinstance(value, dict) or set(value) != {"snapshot_sha256"}:
        raise ValueError("publication pointer has an invalid shape")
    digest = value["snapshot_sha256"]
    if not isinstance(digest, str) or not _HEX.fullmatch(digest):
        raise ValueError("publication pointer digest is invalid")
    return digest


def read_publication(path: str | Path, now: datetime | None = None) -> tuple[Snapshot, str]:
    p = _safe_path(path)
    digest = publication_digest(p)
    snapshot_path = _safe_path(p.parent / f"snapshot-{digest}.json")
    raw = _read_regular(snapshot_path, MAX_SNAPSHOT_BYTES)
    snapshot = load_snapshot_bytes(raw, digest, now=now)
    return snapshot, digest


def _atomic_file(directory: Path, payload: bytes, *, mode: int) -> Path:
    fd, name = tempfile.mkstemp(prefix=".journal-publication-", dir=directory)
    tmp = Path(name)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        return tmp
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        tmp.unlink(missing_ok=True)
        raise


def _install_immutable(directory: Path, target: Path, payload: bytes) -> bool:
    if target.exists() or target.is_symlink():
        _safe_path(target)
        existing = _read_regular(target, MAX_SNAPSHOT_BYTES)
        if existing != payload:
            raise ValueError("content-addressed snapshot differs from expected bytes")
        return False
    temp = _atomic_file(directory, payload, mode=0o640)
    try:
        try:
            os.link(temp, target, follow_symlinks=False)
            dir_fd = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
            return True
        except FileExistsError:
            _safe_path(target)
            if _read_regular(target, MAX_SNAPSHOT_BYTES) != payload:
                raise ValueError("content-addressed snapshot differs from expected bytes")
            return False
    finally:
        temp.unlink(missing_ok=True)


def _cleanup(directory: Path, current: str) -> None:
    """Best-effort retention: current plus two newest owned regular files."""
    try:
        candidates: list[tuple[float, Path]] = []
        for entry in directory.iterdir():
            match = re.fullmatch(r"snapshot-([0-9a-f]{64})\.json", entry.name)
            if not match or match.group(1) == current:
                continue
            try:
                info = entry.lstat()
                if stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid():
                    candidates.append((info.st_mtime, entry))
            except OSError:
                continue
        candidates.sort(key=lambda item: (item[0], item[1].name), reverse=True)
        for _, entry in candidates[2:]:
            try:
                info = entry.lstat()
                if stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid():
                    entry.unlink()
            except OSError:
                continue
    except OSError:
        return


def publish_snapshot(snapshot: Snapshot, publication_file: str | Path) -> dict[str, object]:
    """Atomically publish an immutable snapshot and its small digest pointer."""
    if not isinstance(snapshot, Snapshot):
        raise ValueError("snapshot must be a validated Snapshot")
    pointer = _safe_path(publication_file)
    directory = pointer.parent
    try:
        info = directory.lstat()
    except OSError as exc:
        raise ValueError("publication directory must already exist") from exc
    if not stat.S_ISDIR(info.st_mode):
        raise ValueError("publication parent is not a directory")
    payload = snapshot.model_dump_json().encode("utf-8")
    if len(payload) > MAX_SNAPSHOT_BYTES:
        raise ValueError("snapshot exceeds the 1 MiB limit")
    digest = hashlib.sha256(payload).hexdigest()
    now = datetime.now(timezone.utc)
    load_snapshot_bytes(payload, digest, now=now)
    target = directory / f"snapshot-{digest}.json"
    created = _install_immutable(directory, target, payload)
    pointer_payload = json.dumps({"snapshot_sha256": digest}, separators=(",", ":")).encode()
    temp = _atomic_file(directory, pointer_payload, mode=0o640)
    try:
        os.replace(temp, pointer)
        try:
            dir_fd = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError:
            # replace committed the new pointer; a durability warning must not
            # make the caller report that publication failed.
            pass
    finally:
        temp.unlink(missing_ok=True)
    _cleanup(directory, digest)
    return {"snapshot_sha256": digest, "snapshot_file": target.name, "created": created}
