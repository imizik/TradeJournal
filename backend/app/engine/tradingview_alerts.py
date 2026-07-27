"""Persistence and read services for normalized TradingView live alerts.

The frozen wire parser stays in :mod:`app.engine.tradingview`. This module is
the database boundary: it stores parser output, classifies idempotent retries
versus identity collisions, and exposes egress-safe reads. It performs no
market-data calls and never writes journal or Strategy Lab tables.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from hashlib import sha256
import json
from typing import Mapping

from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import undefer
from sqlmodel import Session, select

from app.engine.tradingview import ParsedAlert, ScalarValue
from app.models import (
    TRADINGVIEW_ALERT_LIGHT,
    TradingViewAlert,
)


MAX_ALERT_LIST_LIMIT = 200
ANALYSIS_STATUSES = frozenset(
    {"pending", "running", "done", "skipped", "error"}
)


class TradingViewPersistenceError(RuntimeError):
    """Raised when validated parser output cannot be safely persisted."""


class TradingViewAlertCollisionError(TradingViewPersistenceError):
    """The canonical identity exists with different semantic content."""

    def __init__(
        self,
        *,
        alert_id: str,
        stored_content_sha256: str,
        incoming_content_sha256: str,
    ) -> None:
        super().__init__(
            f"TradingView alert identity collision for {alert_id!r}"
        )
        self.alert_id = alert_id
        self.stored_content_sha256 = stored_content_sha256
        self.incoming_content_sha256 = incoming_content_sha256


class TradingViewPersistenceBusyError(TradingViewPersistenceError):
    """SQLite could not acquire its write lock within the configured timeout."""


@dataclass(frozen=True, slots=True)
class PersistAlertResult:
    alert: TradingViewAlert
    created: bool

    @property
    def duplicate(self) -> bool:
        return not self.created


def serialize_snapshot(snapshot: Mapping[str, ScalarValue]) -> str:
    """Return deterministic flat JSON while preserving Decimal number types."""

    if any(not isinstance(key, str) for key in snapshot):
        raise TradingViewPersistenceError(
            "TradingView snapshot keys must be strings"
        )
    parts: list[str] = []
    for key, value in sorted(snapshot.items()):
        encoded_key = json.dumps(
            key,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )
        parts.append(f"{encoded_key}:{_serialize_scalar(value)}")
    return "{" + ",".join(parts) + "}"


def deserialize_snapshot(value: str) -> dict[str, ScalarValue]:
    """Decode normalized stored snapshots back into contract scalar types."""

    parsed = json.loads(
        value,
        parse_float=Decimal,
        parse_int=Decimal,
        parse_constant=_reject_nonfinite,
    )
    if not isinstance(parsed, dict):
        raise TradingViewPersistenceError(
            "stored TradingView snapshot must be a JSON object"
        )
    if any(
        not isinstance(key, str)
        or item is not None
        and not isinstance(item, (bool, str, Decimal))
        for key, item in parsed.items()
    ):
        raise TradingViewPersistenceError(
            "stored TradingView snapshot must remain flat scalar JSON"
        )
    return dict(sorted(parsed.items()))


def persist_alert(
    session: Session,
    parsed: ParsedAlert,
    raw_body: bytes,
) -> PersistAlertResult:
    """Insert once, then classify primary-key conflicts by semantic hash.

    Same identity and semantic content is a true retry even when whitespace or
    JSON number spelling changed. Same identity with different semantic
    content is a collision and never overwrites the first immutable evidence.
    """

    payload_json = _verified_raw_payload_text(parsed, raw_body)
    row = TradingViewAlert(
        alert_id=parsed.alert_id,
        contract_version=parsed.contract_version,
        parser_revision=parsed.parser_revision,
        indicator_version=parsed.indicator_version,
        content_sha256=parsed.content_sha256,
        raw_payload_sha256=parsed.raw_payload_sha256,
        symbol=parsed.symbol,
        timeframe=parsed.timeframe,
        setup=parsed.setup,
        side=parsed.side,
        price=parsed.price,
        bar_time_ms=parsed.bar_time_ms,
        bar_time=parsed.bar_time,
        payload_json=payload_json,
        levels_json=serialize_snapshot(parsed.levels),
        context_json=serialize_snapshot(parsed.context),
    )

    try:
        session.add(row)
        session.commit()
        session.refresh(row)
        return PersistAlertResult(alert=row, created=True)
    except IntegrityError as exc:
        session.rollback()
        try:
            stored = session.get(TradingViewAlert, parsed.alert_id)
        except OperationalError as lookup_exc:
            session.rollback()
            if _is_sqlite_busy(lookup_exc):
                raise TradingViewPersistenceBusyError(
                    "TradingView alert persistence is temporarily busy"
                ) from lookup_exc
            raise
        if stored is None:
            # The failure was not the canonical-id conflict this function can
            # classify (for example, a malformed/out-of-date schema).
            raise
        if stored.content_sha256 == parsed.content_sha256:
            return PersistAlertResult(alert=stored, created=False)
        raise TradingViewAlertCollisionError(
            alert_id=parsed.alert_id,
            stored_content_sha256=stored.content_sha256,
            incoming_content_sha256=parsed.content_sha256,
        ) from exc
    except OperationalError as exc:
        session.rollback()
        if _is_sqlite_busy(exc):
            raise TradingViewPersistenceBusyError(
                "TradingView alert persistence is temporarily busy"
            ) from exc
        raise


def get_alert(
    session: Session,
    alert_id: str,
) -> TradingViewAlert | None:
    """Return one full alert, including immutable raw and analysis payloads."""

    query = (
        select(TradingViewAlert)
        .options(undefer("*"))
        .where(TradingViewAlert.alert_id == alert_id)
        .execution_options(populate_existing=True)
    )
    return session.exec(query).first()


def list_alerts(
    session: Session,
    *,
    limit: int = 50,
    offset: int = 0,
    symbol: str | None = None,
    setup: str | None = None,
    analysis_status: str | None = None,
) -> list[TradingViewAlert]:
    """Return newest-first rows with all large JSON/text fields deferred."""

    if isinstance(limit, bool) or not isinstance(limit, int):
        raise ValueError("limit must be an integer")
    if limit < 1 or limit > MAX_ALERT_LIST_LIMIT:
        raise ValueError(
            f"limit must be between 1 and {MAX_ALERT_LIST_LIMIT}"
        )
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise ValueError("offset must be a non-negative integer")

    query = select(TradingViewAlert).options(*TRADINGVIEW_ALERT_LIGHT)
    if symbol is not None:
        normalized_symbol = symbol.strip().upper()
        if not normalized_symbol:
            raise ValueError("symbol must not be blank")
        query = query.where(TradingViewAlert.symbol == normalized_symbol)
    if setup is not None:
        normalized_setup = setup.strip().lower()
        if not normalized_setup:
            raise ValueError("setup must not be blank")
        query = query.where(TradingViewAlert.setup == normalized_setup)
    if analysis_status is not None:
        normalized_status = analysis_status.strip().lower()
        if normalized_status not in ANALYSIS_STATUSES:
            raise ValueError("analysis_status is invalid")
        query = query.where(
            TradingViewAlert.analysis_status == normalized_status
        )

    query = (
        query.order_by(
            TradingViewAlert.received_at.desc(),
            TradingViewAlert.alert_id.desc(),
        )
        .offset(offset)
        .limit(limit)
    )
    return list(session.exec(query).all())


def _verified_raw_payload_text(
    parsed: ParsedAlert,
    raw_body: bytes,
) -> str:
    if not isinstance(raw_body, bytes):
        raise TradingViewPersistenceError("raw_body must be bytes")
    if parsed.raw_payload_sha256 is None:
        raise TradingViewPersistenceError(
            "persist_alert requires output from parse_alert_bytes()"
        )
    actual_sha256 = sha256(raw_body).hexdigest()
    if actual_sha256 != parsed.raw_payload_sha256:
        raise TradingViewPersistenceError(
            "raw_body does not match the parsed alert evidence hash"
        )
    try:
        return raw_body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise TradingViewPersistenceError(
            "raw_body must be valid UTF-8"
        ) from exc


def _serialize_scalar(value: ScalarValue) -> str:
    if isinstance(value, Decimal):
        return _decimal_text(value)
    if value is not None and not isinstance(value, (bool, str)):
        raise TradingViewPersistenceError(
            "TradingView snapshot values must be flat scalars"
        )
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )


def _decimal_text(value: Decimal) -> str:
    if not value.is_finite():
        raise TradingViewPersistenceError(
            "TradingView snapshot numbers must be finite"
        )
    if not value:
        return "0"
    sign, raw_digits, exponent = value.as_tuple()
    digits = list(raw_digits)
    while digits and digits[-1] == 0:
        digits.pop()
        exponent += 1
    digit_text = "".join(str(digit) for digit in digits)
    if exponent >= 0:
        text = digit_text + ("0" * exponent)
    else:
        point = len(digit_text) + exponent
        if point > 0:
            text = f"{digit_text[:point]}.{digit_text[point:]}"
        else:
            text = f"0.{('0' * -point)}{digit_text}"
    return f"-{text}" if sign else text


def _reject_nonfinite(value: str) -> None:
    raise TradingViewPersistenceError(
        f"stored TradingView snapshot contains non-finite number {value!r}"
    )


def _is_sqlite_busy(exc: OperationalError) -> bool:
    original = getattr(exc, "orig", None)
    error_code = getattr(original, "sqlite_errorcode", None)
    if error_code in {5, 6}:  # SQLITE_BUSY, SQLITE_LOCKED
        return True
    message = str(exc).lower()
    return (
        "database is locked" in message
        or "database table is locked" in message
    )
