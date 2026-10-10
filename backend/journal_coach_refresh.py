"""Bounded, credential-file-only publisher for approved journal snapshots."""

from __future__ import annotations

import json
import fcntl
import os
import stat
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from journal_coach_publication import publish_snapshot, rolling_window

_CONFIG_LIMIT = 4096
_CREDENTIAL_LIMIT = 8192
_LOCK_LIMIT = 128


class RefreshError(Exception):
    """Expected safe refresh refusal."""


def _regular_private_file(path: str | Path, limit: int, label: str) -> bytes:
    p = Path(path)
    if not p.is_absolute() or ".." in p.parts or os.path.normpath(str(p)) != str(p):
        raise RefreshError(f"{label} path must be canonical and absolute")
    for component in (p, *p.parents):
        try:
            if stat.S_ISLNK(component.lstat().st_mode):
                raise RefreshError(f"{label} path contains a symlink")
        except FileNotFoundError:
            continue
    try:
        fd = os.open(p, os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0))
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) not in (0o400, 0o600):
                raise RefreshError(f"{label} file must be regular and owner-only mode 0400 or 0600")
            if info.st_size > limit:
                raise RefreshError(f"{label} file is oversized")
            content = bytearray()
            while len(content) <= limit:
                part = os.read(fd, min(4096, limit + 1 - len(content)))
                if not part:
                    break
                content.extend(part)
            if len(content) > limit:
                raise RefreshError(f"{label} file is oversized")
            return bytes(content)
        finally:
            os.close(fd)
    except RefreshError:
        raise
    except OSError as exc:
        raise RefreshError(f"{label} file could not be read") from exc


def _config(path: str | Path) -> tuple[UUID, int, Path]:
    try:
        raw = _regular_private_file(path, _CONFIG_LIMIT, "configuration")
        value = json.loads(raw, object_pairs_hook=_unique_object)
        if not isinstance(value, dict) or set(value) != {"account_ids", "rolling_days", "publication_file"}:
            raise ValueError
        accounts = value["account_ids"]
        days = value["rolling_days"]
        destination = value["publication_file"]
        if not isinstance(accounts, list) or len(accounts) != 1 or not isinstance(accounts[0], str):
            raise ValueError
        account = UUID(accounts[0])
        if str(account) != accounts[0]:
            raise ValueError
        if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 31:
            raise ValueError
        if (not isinstance(destination, str) or not Path(destination).is_absolute()
                or ".." in Path(destination).parts
                or os.path.normpath(destination) != destination):
            raise ValueError
        dest = Path(destination)
        for component in (dest, *dest.parents):
            try:
                if stat.S_ISLNK(component.lstat().st_mode):
                    raise ValueError
            except FileNotFoundError:
                continue
        return account, days, dest
    except RefreshError:
        raise
    except Exception as exc:
        raise RefreshError("configuration is invalid") from exc


def _assert_clean_environment() -> None:
    forbidden = {"DATABASE_URL", "MIGRATION_DATABASE_URL", "JOURNAL_EXPORT_DATABASE_URL"}
    if any(name in os.environ for name in forbidden) or any(name.startswith("PG") for name in os.environ):
        raise RefreshError("database environment variables are forbidden")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


@contextmanager
def _refresh_lock(directory: Path):
    """Hold the private publication-directory lock for one complete refresh."""
    path = directory / ".refresh.lock"
    try:
        fd = os.open(
            path,
            os.O_CREAT | os.O_RDWR | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
    except OSError as exc:
        raise RefreshError("refresh lock could not be opened") from exc
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600
                or info.st_size > _LOCK_LIMIT):
            raise RefreshError("refresh lock must be a bounded private regular file")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RefreshError("another refresh is already running") from exc
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def refresh(config_path: str | Path, database_url_file: str | Path, now: datetime | None = None) -> dict[str, object]:
    """Export the approved rolling window and atomically update its digest pointer."""
    _assert_clean_environment()
    try:
        from cloud_mcp_d0 import reject_model_credentials
        reject_model_credentials()
    except Exception as exc:
        raise RefreshError("model or tunnel credentials are forbidden") from exc
    account, days, publication_file = _config(config_path)
    credential_path = Path(database_url_file).absolute()
    if publication_file == Path(config_path).absolute() or publication_file == credential_path:
        raise RefreshError("publication path conflicts with a private input")
    try:
        raw_url = _regular_private_file(database_url_file, _CREDENTIAL_LIMIT, "database credential").decode("utf-8").strip()
    except UnicodeDecodeError as exc:
        raise RefreshError("database credential is invalid") from exc
    if not raw_url or "\n" in raw_url or "\r" in raw_url:
        raise RefreshError("database credential is invalid")
    current = now or datetime.now(timezone.utc)
    try:
        start_day, end_day = rolling_window(current, days)
    except Exception as exc:
        raise RefreshError("refresh time or window is invalid") from exc
    # Import only the existing standalone exporter; no app/database startup path.
    from scripts.export_journal_coach import export_snapshot

    try:
        with _refresh_lock(publication_file.parent):
            snapshot = export_snapshot(raw_url, [account], start_day, end_day, scoped_view=True)
            if snapshot.sample_data is not False or snapshot.start_day != start_day or snapshot.end_day != end_day:
                raise RefreshError("export did not match the approved publication scope")
            published = publish_snapshot(snapshot, publication_file)
            return {**published, "generated_at": snapshot.generated_at.isoformat(), "trade_count": len(snapshot.trades)}
    except RefreshError:
        raise
    except Exception as exc:
        raise RefreshError("snapshot refresh failed") from exc

