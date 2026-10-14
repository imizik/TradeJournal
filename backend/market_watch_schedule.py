"""Opt-in MW-2 publisher for the four fixed Jo market-read slots.

This process publishes only the existing MW-1 snapshot. It does not wake Jo,
submit a read, send a message, or create a trade. Units under deploy/market-watch
are deliberately excluded from the ordinary installer and deployment flow.
"""
from __future__ import annotations

import argparse
from datetime import UTC, date, datetime, timedelta
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
PUBLISH_SLOTS = ("09:49", "10:59", "12:29", "13:59")
PUBLIC_DIRECTORY = Path("/var/lib/tradejournal-market-watch-public")
RECEIPT_DIRECTORY = Path("/var/lib/tradejournal/market-watch/schedule-receipts")
READ_MINUTES = 1
MAX_START_LATE_SECONDS = 180
MAX_PRICE_AGE_SECONDS = 180
ENV_ALLOWLIST = frozenset({
    "DATABASE_URL", "ALPACA_API_KEY", "ALPACA_API_SECRET", "TRADIER_API_KEY",
    "TRADIER_BASE_URL", "ALPACA_DATA_FEED",
})


class ScheduleRefused(RuntimeError):
    """A safe refusal that must not be converted into a provider retry."""


def _canonical(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def _seal_receipt(value: dict) -> dict:
    result = dict(value)
    result["receipt_sha256"] = hashlib.sha256(_canonical(result)).hexdigest()
    return result


def _read_json(path: Path) -> dict:
    raw = path.read_bytes()
    if len(raw) > 64 * 1024:
        raise ValueError("receipt_too_large")
    value = json.loads(raw)
    claimed = value.pop("receipt_sha256", None)
    if claimed != hashlib.sha256(_canonical(value)).hexdigest():
        raise ValueError("receipt_hash_mismatch")
    value["receipt_sha256"] = claimed
    return value


def _write_immutable(path: Path, record: dict) -> None:
    """Write one receipt atomically; existing paths are never replaced."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.parent.is_symlink() or path.is_symlink():
        raise ScheduleRefused("receipt_path_is_symlink")
    data = _canonical(_seal_receipt(record))
    fd, name = tempfile.mkstemp(prefix=".mw-schedule-", suffix=".tmp", dir=path.parent)
    tmp = Path(name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(tmp, path, follow_symlinks=False)
        tmp.unlink()
        dirfd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(dirfd)
        finally:
            os.close(dirfd)
    finally:
        tmp.unlink(missing_ok=True)


def scheduled_slot(now: datetime) -> tuple[date, str] | None:
    """Return today's slot only during its three-minute start grace window."""
    if now.tzinfo is None:
        raise ValueError("scheduler clock must be timezone-aware")
    local = now.astimezone(ET)
    if local.weekday() >= 5:
        return None
    for clock in PUBLISH_SLOTS:
        hour, minute = (int(part) for part in clock.split(":"))
        expected = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
        late = (local - expected).total_seconds()
        if 0 <= late <= MAX_START_LATE_SECONDS:
            return local.date(), clock.replace(":", "-")
    return None


def _slot_rth_status(day: date, slot: str, calendar_reader) -> str:
    """Use the exchange calendar's actual hours; unknown hours fail closed."""
    hours = calendar_reader(day)
    if not isinstance(hours, dict):
        return "exchange_calendar_unavailable"
    if hours.get("status") == "closed":
        return "exchange_closed"
    if hours.get("status") != "open" or type(hours.get("open")) is not int or type(hours.get("close")) is not int:
        return "exchange_calendar_unavailable"
    hour, minute = (int(part) for part in slot.split("-"))
    read_minute = hour * 60 + minute + READ_MINUTES
    if read_minute < hours["open"] or read_minute >= hours["close"]:
        return "outside_regular_session"
    return "eligible"


def _snapshot_quality(snapshot: dict, now: datetime, *, slot: str) -> tuple[str, ...]:
    """Return explicit source flags while allowing valid partial MW-1 packets."""
    if snapshot.get("market_phase") != "regular_session":
        raise ScheduleRefused("snapshot_not_regular_session")
    if snapshot.get("session_date") != now.astimezone(ET).date().isoformat():
        raise ScheduleRefused("snapshot_session_date_mismatch")
    try:
        finished = datetime.fromisoformat(str(snapshot["collection_finished_at"]).replace("Z", "+00:00"))
        if finished.tzinfo is None:
            raise ValueError
        checked_at = finished.astimezone(UTC)
    except (KeyError, TypeError, ValueError):
        raise ScheduleRefused("collection_timestamp_invalid") from None
    # Re-run the MW-1 validator before publishing. This rejects hash tampering,
    # future observations, invalid schemas and unclosed bars; ordinary missing
    # or stale source groups remain valid and are preserved.
    from market_watch_common import validate_snapshot
    validate_snapshot(snapshot)
    flags = []
    if snapshot.get("gaps"):
        flags.extend(f"gap:{str(gap.get('group', 'source'))[:80]}:{str(gap.get('reason', 'unavailable'))[:80]}"
                     for gap in snapshot["gaps"] if isinstance(gap, dict))
    local = now.astimezone(ET)
    hour, minute = (int(part) for part in slot.split("-"))
    deadline = local.replace(hour=hour, minute=minute, second=0, microsecond=0) + timedelta(
        seconds=MAX_START_LATE_SECONDS)
    if checked_at > deadline.astimezone(UTC):
        raise ScheduleRefused("snapshot_collection_late")
    for symbol in ("SPY", "QQQ"):
        index = snapshot.get("indices", {}).get(symbol, {})
        price = index.get("price", {})
        status = price.get("status", "missing")
        if price.get("value") is None:
            flags.append(f"{symbol.lower()}_price_{status}")
        try:
            stamp = datetime.fromisoformat(str(price["at"]).replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                raise ValueError
            age = (checked_at - stamp.astimezone(UTC)).total_seconds()
        except (KeyError, TypeError, ValueError):
            age = None
        if age is None:
            flags.append(f"{symbol.lower()}_price_timestamp_missing")
        elif age < 0:
            raise ScheduleRefused(f"{symbol.lower()}_price_timestamp_future")
        elif age > MAX_PRICE_AGE_SECONDS and f"{symbol.lower()}_price_stale" not in flags:
            flags.append(f"{symbol.lower()}_price_stale")
        elif status != "fresh" and not any(flag.startswith(f"{symbol.lower()}_price_") for flag in flags):
            flags.append(f"{symbol.lower()}_price_{status}")
    for group in ("volatility", "calendar", "headlines"):
        status = snapshot.get(group, {}).get("status", "missing")
        if status != "fresh" and not any(flag.startswith(f"gap:{group}:") for flag in flags):
            flags.append(f"{group}_{status}")
    return tuple(dict.fromkeys(flags))


def _attempt_records(attempt_dir: Path) -> list[dict]:
    if not attempt_dir.exists():
        return []
    records = [_read_json(path) for path in attempt_dir.glob("attempt-*.json")]
    rank = {"started": 0, "failed": 1, "skipped": 1, "published": 1,
            "recovered_published": 1}
    return sorted(records, key=lambda row: (row.get("attempt", 0), rank.get(row.get("phase"), 0)))


def run_slot(now: datetime, public_directory: str | Path, receipt_directory: str | Path, *,
             calendar_reader, snapshot_builder, publisher, retry_failed: bool = False,
             receipt_clock=None) -> dict:
    """Publish once for the current slot, keeping append-only per-attempt receipts."""
    slot_info = scheduled_slot(now)
    if slot_info is None:
        raise ScheduleRefused("outside_scheduled_slot")
    day, slot = slot_info
    public = Path(public_directory)
    receipts = Path(receipt_directory)
    if not public.is_absolute() or not receipts.is_absolute():
        raise ScheduleRefused("directories_must_be_absolute")
    if public.is_symlink() or receipts.is_symlink():
        raise ScheduleRefused("publication_directory_is_symlink")
    receipt_clock = receipt_clock or (lambda: datetime.now(UTC))
    receipts.mkdir(parents=True, exist_ok=True, mode=0o700)
    day_dir = receipts / day.isoformat() / slot
    day_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    if day_dir.is_symlink():
        raise ScheduleRefused("receipt_path_is_symlink")
    lock_path = receipts / ".market-watch-schedule.lock"
    if lock_path.is_symlink():
        raise ScheduleRefused("receipt_lock_is_symlink")
    lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        history = _attempt_records(day_dir)
        latest = history[-1] if history else None
        attempt = latest.get("attempt", 0) if latest else 0
        if latest:
            status = latest.get("status")
            if status in {"published", "published_partial"} or status.startswith("skipped_"):
                return {"status": "already_recorded", "slot": slot, "session_date": day.isoformat(),
                        "snapshot_id": latest.get("snapshot_id")}
            if status == "started":
                raise ScheduleRefused("prior_attempt_incomplete_owner_recovery_required")
            if status == "failed" and not retry_failed:
                raise ScheduleRefused("failed_attempt_requires_explicit_retry")
            if status != "failed":
                raise ScheduleRefused("unknown_prior_receipt_state")
        elif retry_failed:
            raise ScheduleRefused("no_failed_attempt_to_retry")

        attempt += 1
        read_hour, read_minute = divmod(int(slot[:2]) * 60 + int(slot[3:]) + READ_MINUTES, 60)
        common = {"schema_version": 1, "session_date": day.isoformat(), "slot": slot,
                  "scheduled_read_slot": f"{read_hour:02d}:{read_minute:02d} ET", "attempt": attempt,
                  "recorded_at": now.astimezone(UTC).isoformat().replace("+00:00", "Z")}
        stem = f"attempt-{attempt:02d}"
        _write_immutable(day_dir / f"{stem}-started.json", {**common, "phase": "started", "status": "started"})
        try:
            gate = _slot_rth_status(day, slot, calendar_reader)
            if gate == "exchange_calendar_unavailable":
                raise ScheduleRefused(gate)
            if gate != "eligible":
                result = {**common, "recorded_at": receipt_clock().astimezone(UTC).isoformat().replace("+00:00", "Z"),
                          "phase": "skipped", "status": f"skipped_{gate}"}
                _write_immutable(day_dir / f"{stem}-skipped.json", result)
                return result
            snapshot = snapshot_builder()
            quality_flags = _snapshot_quality(snapshot, now, slot=slot)
            path = publisher(public, snapshot)
            result = {**common, "recorded_at": receipt_clock().astimezone(UTC).isoformat().replace("+00:00", "Z"),
                      "phase": "published", "status": "published_partial" if quality_flags else "published",
                      "snapshot_id": snapshot["snapshot_id"], "content_sha256": snapshot["content_sha256"],
                      "published_path": Path(path).name, "quality_flags": list(quality_flags),
                      "error_reason": "snapshot_has_explicit_gaps" if quality_flags else None}
            _write_immutable(day_dir / f"{stem}-published.json", result)
            return result
        except Exception as exc:
            # Exception text can contain credentials or URLs; retain only stable codes.
            code = str(exc) if isinstance(exc, ScheduleRefused) else f"source_error:{type(exc).__name__}"
            result = {**common, "recorded_at": receipt_clock().astimezone(UTC).isoformat().replace("+00:00", "Z"),
                      "phase": "failed", "status": "failed", "error_code": code[:120]}
            _write_immutable(day_dir / f"{stem}-failed.json", result)
            if isinstance(exc, ScheduleRefused):
                raise
            return result
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)


def _parse_dotenv(path: Path) -> dict[str, str]:
    """Parse the existing env file without interpolation, then apply the allowlist."""
    from dotenv import dotenv_values
    parsed = dotenv_values(path, interpolate=False)
    return {key: value for key, value in parsed.items()
            if key in ENV_ALLOWLIST and isinstance(value, str) and value}


def _runtime_env(credential: Path) -> dict[str, str]:
    allowed = _parse_dotenv(credential)
    required = {"DATABASE_URL", "ALPACA_API_KEY", "ALPACA_API_SECRET", "TRADIER_API_KEY"}
    if required - allowed.keys():
        raise ScheduleRefused("required_market_data_credentials_missing")
    return {"PATH": "/usr/bin:/bin", "PYTHON_DOTENV_DISABLED": "1",
            "PGOPTIONS": "-c default_transaction_read_only=on", **allowed,
            # The existing snapshot builder enforces the active feed setting.
            # Override only this child invocation to its explicitly requested IEX policy.
            "ALPACA_DATA_FEED": "iex"}


_CHILD_COLLECTOR = r'''
import json, sys
from datetime import date, timedelta
from pathlib import Path
from app.engine.chart_calendar import chart_calendar
day = date.fromisoformat(sys.argv[1])
slot = sys.argv[2]
chart_calendar.root = Path("/var/lib/tradejournal/market-watch/chart-calendar-cache")
hours = chart_calendar.hours(day)
if hours is None:
    print(json.dumps({"hours": None, "snapshot": None}))
    raise SystemExit(0)
for offset in range(1, 15):
    previous = chart_calendar.hours(day - timedelta(days=offset))
    if previous and previous.get("status") == "open":
        break
hour, minute = (int(part) for part in slot.split("-"))
read_minute = hour * 60 + minute + 1
eligible = hours.get("status") == "open" and type(hours.get("open")) is int and type(hours.get("close")) is int and hours["open"] <= read_minute < hours["close"]
if not eligible:
    print(json.dumps({"hours": hours, "snapshot": None}))
    raise SystemExit(0)
from app.database import engine
if engine.dialect.name != "postgresql":
    raise RuntimeError("market-watch publisher requires PostgreSQL")
with engine.connect() as connection:
    readonly = connection.exec_driver_sql("SHOW transaction_read_only").scalar_one()
if str(readonly).lower() not in {"on", "true", "1"}:
    raise RuntimeError("PostgreSQL transaction is not read-only")
from app.engine.market_watch_snapshot import build_snapshot
snapshot = build_snapshot()
print(json.dumps({"hours": hours, "snapshot": snapshot}, separators=(",", ":"), allow_nan=False))
'''


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--public-directory", required=True)
    parser.add_argument("--receipt-directory", required=True)
    parser.add_argument("--retry-failed", action="store_true", help="Explicitly retry a typed failed attempt")
    args = parser.parse_args(argv)
    if (Path(args.public_directory) != PUBLIC_DIRECTORY
            or Path(args.receipt_directory) != RECEIPT_DIRECTORY):
        print(json.dumps({"status": "refused", "error_code": "unapproved_directory"}))
        return 2
    now = datetime.now(UTC)
    slot_info = scheduled_slot(now)
    if slot_info is None:
        print(json.dumps({"status": "refused", "error_code": "outside_scheduled_slot"}))
        return 2
    try:
        day, slot = slot_info
        collected = {}
        child_env = {}

        def collect():
            if collected:
                return
            if not child_env:
                credential_dir = os.environ.get("CREDENTIALS_DIRECTORY")
                if not credential_dir:
                    raise ScheduleRefused("credentials_unavailable")
                child_env.update(_runtime_env(Path(credential_dir) / "backend.env"))
            child = subprocess.run(
                [sys.executable, "-c", _CHILD_COLLECTOR, day.isoformat(), slot],
                cwd=Path(__file__).resolve().parent, env=child_env, check=False,
                capture_output=True, text=True, timeout=240)
            if child.returncode != 0:
                raise ScheduleRefused("snapshot_collection_failed")
            try:
                collected.update(json.loads(child.stdout))
            except (TypeError, ValueError) as exc:
                raise ScheduleRefused("snapshot_collection_invalid_response") from exc

        def calendar_reader(_day):
            collect()
            return collected.get("hours")

        def snapshot_builder():
            collect()
            snapshot = collected.get("snapshot")
            if snapshot is None:
                raise ScheduleRefused("snapshot_unavailable")
            return snapshot

        def publisher(public, snapshot):
            from app.engine.market_watch_snapshot import publish_snapshot
            return publish_snapshot(public, snapshot)

        result = run_slot(now, args.public_directory, args.receipt_directory,
                          calendar_reader=calendar_reader, snapshot_builder=snapshot_builder,
                          publisher=publisher, retry_failed=args.retry_failed)
        print(json.dumps(result, sort_keys=True))
        return 0 if result["status"] in {"published", "published_partial", "already_recorded"} or result["status"].startswith("skipped_") else 1
    except Exception as exc:
        code = str(exc) if isinstance(exc, ScheduleRefused) else f"source_error:{type(exc).__name__}"
        print(json.dumps({"status": "failed", "error_code": code[:120]}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
