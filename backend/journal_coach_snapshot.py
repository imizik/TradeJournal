"""Strict, curated snapshot format for the local journal-coach export."""

from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

SCHEMA_VERSION = "journal-coach-snapshot-v1"
MAX_SNAPSHOT_BYTES = 1024 * 1024
MAX_TRADES = 500
_DECIMAL = re.compile(r"^-?(?:0|[1-9][0-9]{0,11})(?:\.[0-9]{1,6})?$")
_TICKER = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,14}$")


def _decimal(value: str | None, *, nonnegative: bool = False) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not _DECIMAL.fullmatch(value):
        raise ValueError("must be a plain finite DECIMAL(18,6) string")
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("must be a plain finite DECIMAL(18,6) string") from exc
    if not number.is_finite() or (nonnegative and number < 0):
        raise ValueError("decimal is outside the DECIMAL(18,6) range")
    return value


class SnapshotTrade(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    id: str
    ticker: str
    instrument_type: Literal["stock", "option"]
    quantity: str
    realized_pnl: str | None
    status: Literal["closed", "expired"]
    opened_at: datetime
    closed_at: datetime

    @field_validator("id")
    @classmethod
    def canonical_uuid(cls, value: str) -> str:
        try:
            parsed = UUID(value)
        except (ValueError, AttributeError) as exc:
            raise ValueError("id must be a canonical UUID") from exc
        if str(parsed) != value:
            raise ValueError("id must be a canonical UUID")
        return value

    @field_validator("ticker")
    @classmethod
    def valid_ticker(cls, value: str) -> str:
        if not _TICKER.fullmatch(value):
            raise ValueError("ticker is invalid")
        return value

    @field_validator("quantity")
    @classmethod
    def valid_quantity(cls, value: str) -> str:
        return _decimal(value, nonnegative=True)  # type: ignore[return-value]

    @field_validator("realized_pnl")
    @classmethod
    def valid_pnl(cls, value: str | None) -> str | None:
        return _decimal(value)

    @field_validator("opened_at", "closed_at")
    @classmethod
    def naive_et_wall_clock(cls, value: datetime) -> datetime:
        if value.tzinfo is not None and value.utcoffset() is not None:
            raise ValueError("timestamps must be naive America/New_York wall clocks")
        return value

    @model_validator(mode="after")
    def chronological(self) -> "SnapshotTrade":
        if self.opened_at > self.closed_at:
            raise ValueError("opened_at must not be after closed_at")
        return self


class JournalCoachSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal["journal-coach-snapshot-v1"]
    generated_at: datetime
    start_day: date
    end_day: date
    source: Literal["approved_journal_export"]
    sample_data: bool
    trades: list[SnapshotTrade]

    @field_validator("generated_at")
    @classmethod
    def aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None or value.utcoffset() != timedelta(0):
            raise ValueError("generated_at must be timezone-aware UTC")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def valid_window_and_rows(self) -> "JournalCoachSnapshot":
        if self.start_day > self.end_day:
            raise ValueError("start_day must not be after end_day")
        if (self.end_day - self.start_day).days + 1 > 31:
            raise ValueError("window must be at most 31 inclusive days")
        if len(self.trades) > MAX_TRADES:
            raise ValueError("too many trades")
        ids = [trade.id for trade in self.trades]
        if len(ids) != len(set(ids)):
            raise ValueError("trade ids must be unique")
        for trade in self.trades:
            if not self.start_day <= trade.closed_at.date() <= self.end_day:
                raise ValueError("closed_at is outside the requested window")
        return self


# Short alias for callers that prefer the format name.
Snapshot = JournalCoachSnapshot


def load_snapshot(
    path: str | Path,
    expected_sha256: str,
    max_age_seconds: int = 3600,
    now: datetime | None = None,
) -> Snapshot:
    """Read, hash, validate and freshness-check a bounded snapshot file."""
    if not re.fullmatch(r"[0-9a-fA-F]{64}", expected_sha256):
        raise ValueError("expected_sha256 must be a SHA-256 hex digest")
    if isinstance(max_age_seconds, bool) or not isinstance(max_age_seconds, int) or max_age_seconds < 0:
        raise ValueError("max_age_seconds must be a nonnegative integer")
    try:
        with Path(path).open("rb") as stream:
            raw = stream.read(MAX_SNAPSHOT_BYTES + 1)
    except OSError as exc:
        raise ValueError("snapshot could not be read") from exc
    if len(raw) > MAX_SNAPSHOT_BYTES:
        raise ValueError("snapshot exceeds the 1 MiB limit")
    if hashlib.sha256(raw).hexdigest().lower() != expected_sha256.lower():
        raise ValueError("snapshot SHA-256 does not match")
    try:
        snapshot = Snapshot.model_validate_json(raw)
    except Exception as exc:
        raise ValueError("snapshot data is invalid") from exc
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    current = current.astimezone(timezone.utc)
    age = (current - snapshot.generated_at).total_seconds()
    if age < 0:
        raise ValueError("snapshot is from the future")
    if age > max_age_seconds:
        raise ValueError("snapshot is stale")
    return snapshot


def summary(snapshot: Snapshot) -> dict[str, object]:
    """Summarize only observed realized PnL; missing values remain missing.

    Win rate is a six-decimal ratio (not a percentage) over known realized
    PnL; breakeven trades are included in that denominator. The total is null
    when no PnL is known, so missing values never appear as a zero total.
    """
    known = [Decimal(trade.realized_pnl) for trade in snapshot.trades if trade.realized_pnl is not None]
    wins = sum(value > 0 for value in known)
    losses = sum(value < 0 for value in known)
    breakeven = sum(value == 0 for value in known)
    with localcontext() as context:
        # At most 500 DECIMAL(18,6) values contribute; precision 30 keeps the
        # exact sum of their maximum magnitudes and scales.
        context.prec = 30
        total = sum(known, Decimal(0)) if known else None
        rate = (
            (Decimal(wins) / Decimal(len(known))).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
            if known else None
        )
    return {
        "start_day": snapshot.start_day.isoformat(),
        "end_day": snapshot.end_day.isoformat(),
        "trade_count": len(snapshot.trades),
        "known_pnl_count": len(known),
        "missing_pnl_count": len(snapshot.trades) - len(known),
        "win_count": wins,
        "loss_count": losses,
        "breakeven_count": breakeven,
        "win_rate": format(rate, "f") if rate is not None else None,
        "realized_pnl_total": format(total, "f") if total is not None else None,
    }
