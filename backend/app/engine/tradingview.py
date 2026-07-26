"""Frozen TradingView webhook wire contract.

Step 1 intentionally contains no database, network, or FastAPI code.  The
version-specific parser is kept pure so later persistence migrations can
continue to interpret v1 payloads with the exact rules that accepted them.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
import re
from types import MappingProxyType
from typing import Any, Mapping, TypeAlias


CONTRACT_VERSION_V1 = 1
PARSER_REVISION_V1 = "tv-alert-v1-r1"
SUPPORTED_CONTRACT_VERSIONS = frozenset({CONTRACT_VERSION_V1})

# The future HTTP receiver must enforce this limit on raw bytes before JSON
# decoding.  Keeping it beside the parser prevents the transport contract and
# the versioned payload contract from drifting apart.
MAX_ALERT_BODY_BYTES = 16 * 1024

MAX_ALERT_ID_LENGTH = 200
MAX_INDICATOR_VERSION_LENGTH = 32
MAX_SYMBOL_LENGTH = 32
MAX_TIMEFRAME_LENGTH = 16
MAX_SETUP_LENGTH = 64
MAX_SNAPSHOT_ENTRIES = 32
MAX_SNAPSHOT_KEY_LENGTH = 64
MAX_SNAPSHOT_STRING_LENGTH = 256
MAX_NUMERIC_DIGITS = 24
MAX_DECIMAL_PLACES = 12
MAX_ABS_NUMBER = Decimal("1000000000000000")

# Keep the v1 epoch domain deterministic and platform-independent.  Freshness
# is a later worker concern; the parser only rejects nonsensical wire values.
MIN_BAR_TIME_MS = 946_684_800_000  # 2000-01-01T00:00:00Z
MAX_BAR_TIME_MS = 4_102_444_800_000  # 2100-01-01T00:00:00Z (exclusive)

_EPOCH_UTC = datetime(1970, 1, 1, tzinfo=timezone.utc)
_INDICATOR_VERSION_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_SYMBOL_RE = re.compile(r"[A-Z0-9][A-Z0-9._-]*")
_TIMEFRAME_RE = re.compile(r"[0-9A-Z]+")
_SETUP_RE = re.compile(r"[a-z][a-z0-9_]*")
_SNAPSHOT_KEY_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]*")

_V1_REQUIRED_FIELDS = frozenset(
    {
        "v",
        "indicator_version",
        "alert_id",
        "symbol",
        "timeframe",
        "setup",
        "side",
        "price",
        "bar_time_ms",
    }
)
_V1_OPTIONAL_FIELDS = frozenset({"levels", "context"})
_V1_ALLOWED_FIELDS = _V1_REQUIRED_FIELDS | _V1_OPTIONAL_FIELDS

ScalarValue: TypeAlias = None | bool | str | Decimal


class TradingViewContractError(ValueError):
    """Raised when a webhook body does not satisfy its declared contract."""


@dataclass(frozen=True, slots=True)
class ParsedAlert:
    """Immutable normalized representation of one accepted webhook alert."""

    contract_version: int
    parser_revision: str
    indicator_version: str
    alert_id: str
    symbol: str
    timeframe: str
    setup: str
    side: str
    price: Decimal
    bar_time_ms: int
    bar_time: datetime
    levels: Mapping[str, ScalarValue]
    context: Mapping[str, ScalarValue]
    canonical_fingerprint_json: str
    content_sha256: str
    raw_payload_sha256: str | None = None


def parse_alert_bytes(raw_body: bytes) -> ParsedAlert:
    """Decode bounded v1+ JSON bytes without losing wire-level evidence.

    The future receiver must use this entry point instead of ``request.json()``:
    default JSON decoding rounds decimals through binary floats and silently
    accepts duplicate object keys before the frozen parser can inspect them.
    """

    if not isinstance(raw_body, bytes):
        raise TradingViewContractError("raw alert body must be bytes")
    if not raw_body:
        raise TradingViewContractError("raw alert body must not be empty")
    if len(raw_body) > MAX_ALERT_BODY_BYTES:
        raise TradingViewContractError(
            f"raw alert body exceeds {MAX_ALERT_BODY_BYTES} bytes"
        )
    try:
        text = raw_body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise TradingViewContractError("raw alert body must be valid UTF-8") from exc

    try:
        body = json.loads(
            text,
            parse_float=Decimal,
            object_pairs_hook=_json_object_without_duplicates,
            parse_constant=_reject_json_constant,
        )
    except TradingViewContractError:
        raise
    except (json.JSONDecodeError, ValueError) as exc:
        raise TradingViewContractError(f"raw alert body is invalid JSON: {exc}") from exc

    parsed = parse_alert(body)
    return replace(
        parsed,
        raw_payload_sha256=sha256(raw_body).hexdigest(),
    )


def parse_alert(body: dict[str, Any]) -> ParsedAlert:
    """Dispatch a webhook object to its frozen version-specific parser."""

    if not isinstance(body, dict):
        raise TradingViewContractError("alert body must be a JSON object")

    version = body.get("v")
    if isinstance(version, bool) or not isinstance(version, int):
        raise TradingViewContractError("v must be the integer 1")
    if version == CONTRACT_VERSION_V1:
        return parse_alert_v1(body)
    raise TradingViewContractError(f"unsupported alert contract version: {version}")


def parse_alert_v1(body: dict[str, Any]) -> ParsedAlert:
    """Parse v1 without consulting any current/future contract defaults."""

    if not isinstance(body, dict):
        raise TradingViewContractError("alert body must be a JSON object")
    if any(not isinstance(key, str) for key in body):
        raise TradingViewContractError("all top-level field names must be strings")

    missing = sorted(_V1_REQUIRED_FIELDS - body.keys())
    if missing:
        raise TradingViewContractError(
            f"missing required field(s): {', '.join(missing)}"
        )
    extra = sorted(body.keys() - _V1_ALLOWED_FIELDS)
    if extra:
        raise TradingViewContractError(
            f"unknown top-level field(s): {', '.join(extra)}"
        )

    version = body["v"]
    if (
        isinstance(version, bool)
        or not isinstance(version, int)
        or version != CONTRACT_VERSION_V1
    ):
        raise TradingViewContractError("v must be the integer 1")

    indicator_version = _bounded_text(
        body["indicator_version"],
        field="indicator_version",
        max_length=MAX_INDICATOR_VERSION_LENGTH,
        pattern=_INDICATOR_VERSION_RE,
    )
    symbol = _bounded_text(
        body["symbol"],
        field="symbol",
        max_length=MAX_SYMBOL_LENGTH,
        pattern=_SYMBOL_RE,
        normalize=str.upper,
    )
    timeframe = _bounded_text(
        body["timeframe"],
        field="timeframe",
        max_length=MAX_TIMEFRAME_LENGTH,
        pattern=_TIMEFRAME_RE,
        normalize=str.upper,
    )
    setup = _bounded_text(
        body["setup"],
        field="setup",
        max_length=MAX_SETUP_LENGTH,
        pattern=_SETUP_RE,
        normalize=str.lower,
    )
    side = _bounded_text(
        body["side"],
        field="side",
        max_length=5,
        normalize=str.lower,
    )
    if side not in {"long", "short"}:
        raise TradingViewContractError("side must be 'long' or 'short'")

    bar_time_ms = _bar_time_ms(body["bar_time_ms"])
    bar_time = (_EPOCH_UTC + timedelta(milliseconds=bar_time_ms)).replace(
        tzinfo=None
    )
    price = _number(body["price"], field="price", positive=True)
    levels = _snapshot(body.get("levels", {}), field="levels")
    context = _snapshot(body.get("context", {}), field="context")

    expected_alert_id = canonical_alert_id(
        indicator_version=indicator_version,
        symbol=symbol,
        timeframe=timeframe,
        bar_time_ms=bar_time_ms,
        setup=setup,
        side=side,
    )
    alert_id = _bounded_text(
        body["alert_id"],
        field="alert_id",
        max_length=MAX_ALERT_ID_LENGTH,
        strip=False,
    )
    if alert_id != expected_alert_id:
        raise TradingViewContractError(
            f"alert_id must equal the canonical id {expected_alert_id!r}"
        )

    canonical = _canonical_fingerprint_json(
        contract_version=CONTRACT_VERSION_V1,
        indicator_version=indicator_version,
        alert_id=alert_id,
        symbol=symbol,
        timeframe=timeframe,
        setup=setup,
        side=side,
        price=price,
        bar_time_ms=bar_time_ms,
        levels=levels,
        context=context,
    )
    return ParsedAlert(
        contract_version=CONTRACT_VERSION_V1,
        parser_revision=PARSER_REVISION_V1,
        indicator_version=indicator_version,
        alert_id=alert_id,
        symbol=symbol,
        timeframe=timeframe,
        setup=setup,
        side=side,
        price=price,
        bar_time_ms=bar_time_ms,
        bar_time=bar_time,
        levels=levels,
        context=context,
        canonical_fingerprint_json=canonical,
        content_sha256=sha256(canonical.encode("utf-8")).hexdigest(),
    )


def canonical_alert_id(
    *,
    indicator_version: str,
    symbol: str,
    timeframe: str,
    bar_time_ms: int,
    setup: str,
    side: str,
) -> str:
    """Return the only valid v1 idempotency key for the supplied identity."""

    normalized_indicator_version = _bounded_text(
        indicator_version,
        field="indicator_version",
        max_length=MAX_INDICATOR_VERSION_LENGTH,
        pattern=_INDICATOR_VERSION_RE,
    )
    normalized_symbol = _bounded_text(
        symbol,
        field="symbol",
        max_length=MAX_SYMBOL_LENGTH,
        pattern=_SYMBOL_RE,
        normalize=str.upper,
    )
    normalized_timeframe = _bounded_text(
        timeframe,
        field="timeframe",
        max_length=MAX_TIMEFRAME_LENGTH,
        pattern=_TIMEFRAME_RE,
        normalize=str.upper,
    )
    normalized_setup = _bounded_text(
        setup,
        field="setup",
        max_length=MAX_SETUP_LENGTH,
        pattern=_SETUP_RE,
        normalize=str.lower,
    )
    normalized_side = _bounded_text(
        side,
        field="side",
        max_length=5,
        normalize=str.lower,
    )
    if normalized_side not in {"long", "short"}:
        raise TradingViewContractError("side must be 'long' or 'short'")
    normalized_bar_time_ms = _bar_time_ms(bar_time_ms)

    result = (
        f"v{CONTRACT_VERSION_V1}:{normalized_indicator_version}:{normalized_symbol}:"
        f"{normalized_timeframe}:{normalized_bar_time_ms}:"
        f"{normalized_setup}:{normalized_side}"
    )
    if len(result) > MAX_ALERT_ID_LENGTH:
        raise TradingViewContractError(
            f"canonical alert_id exceeds {MAX_ALERT_ID_LENGTH} characters"
        )
    return result


def _bounded_text(
    value: Any,
    *,
    field: str,
    max_length: int,
    pattern: re.Pattern[str] | None = None,
    normalize=None,
    strip: bool = True,
) -> str:
    if not isinstance(value, str):
        raise TradingViewContractError(f"{field} must be a string")
    result = value.strip() if strip else value
    if normalize is not None:
        result = normalize(result)
    if not result or not result.strip():
        raise TradingViewContractError(f"{field} must not be blank")
    if len(result) > max_length:
        raise TradingViewContractError(
            f"{field} must be at most {max_length} characters"
        )
    if any(ord(char) < 32 or ord(char) == 127 for char in result):
        raise TradingViewContractError(f"{field} contains control characters")
    if pattern is not None and pattern.fullmatch(result) is None:
        raise TradingViewContractError(f"{field} has an invalid format")
    return result


def _bar_time_ms(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TradingViewContractError("bar_time_ms must be an integer epoch in ms")
    if value < MIN_BAR_TIME_MS or value >= MAX_BAR_TIME_MS:
        raise TradingViewContractError(
            "bar_time_ms must fall between 2000-01-01 and 2100-01-01 UTC"
        )
    return value


def _number(value: Any, *, field: str, positive: bool = False) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise TradingViewContractError(f"{field} must be a JSON number")
    try:
        parsed = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise TradingViewContractError(f"{field} must be a valid number") from None
    if not parsed.is_finite():
        raise TradingViewContractError(f"{field} must be finite")
    if positive and parsed <= 0:
        raise TradingViewContractError(f"{field} must be greater than zero")
    if abs(parsed) > MAX_ABS_NUMBER:
        raise TradingViewContractError(
            f"{field} exceeds the v1 numeric magnitude limit"
        )
    normalized = _normalize_decimal(parsed)
    sign, digits, exponent = normalized.as_tuple()
    del sign
    if len(digits) > MAX_NUMERIC_DIGITS:
        raise TradingViewContractError(
            f"{field} exceeds the v1 numeric precision limit"
        )
    if exponent < -MAX_DECIMAL_PLACES:
        raise TradingViewContractError(
            f"{field} exceeds {MAX_DECIMAL_PLACES} decimal places"
        )
    return normalized


def _snapshot(value: Any, *, field: str) -> Mapping[str, ScalarValue]:
    if not isinstance(value, dict):
        raise TradingViewContractError(f"{field} must be a flat JSON object")
    if len(value) > MAX_SNAPSHOT_ENTRIES:
        raise TradingViewContractError(
            f"{field} must contain at most {MAX_SNAPSHOT_ENTRIES} entries"
        )

    normalized: dict[str, ScalarValue] = {}
    for key, item in value.items():
        normalized_key = _bounded_text(
            key,
            field=f"{field} key",
            max_length=MAX_SNAPSHOT_KEY_LENGTH,
            pattern=_SNAPSHOT_KEY_RE,
            strip=False,
        )
        if normalized_key in normalized:
            raise TradingViewContractError(
                f"{field} contains duplicate normalized key {normalized_key!r}"
            )
        if item is None or isinstance(item, bool):
            normalized_item: ScalarValue = item
        elif isinstance(item, str):
            if len(item) > MAX_SNAPSHOT_STRING_LENGTH:
                raise TradingViewContractError(
                    f"{field}.{normalized_key} must be at most "
                    f"{MAX_SNAPSHOT_STRING_LENGTH} characters"
                )
            if any(ord(char) < 32 or ord(char) == 127 for char in item):
                raise TradingViewContractError(
                    f"{field}.{normalized_key} contains control characters"
                )
            normalized_item = item
        elif isinstance(item, (int, float, Decimal)) and not isinstance(item, bool):
            normalized_item = _number(
                item,
                field=f"{field}.{normalized_key}",
            )
        else:
            raise TradingViewContractError(
                f"{field}.{normalized_key} must be a flat JSON scalar"
            )
        normalized[normalized_key] = normalized_item

    return MappingProxyType(dict(sorted(normalized.items())))


def _decimal_text(value: Decimal) -> str:
    normalized = _normalize_decimal(value)
    sign, digits, exponent = normalized.as_tuple()
    if not digits or not any(digits):
        return "0"

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


def _normalize_decimal(value: Decimal) -> Decimal:
    """Strip insignificant trailing zeros without consulting Decimal context."""

    if not value:
        return Decimal(0)
    sign, raw_digits, exponent = value.as_tuple()
    digits = list(raw_digits)
    while digits and digits[-1] == 0:
        digits.pop()
        exponent += 1
    return Decimal((sign, tuple(digits), exponent))


def _tagged_scalar(value: ScalarValue) -> list[Any]:
    if value is None:
        return ["null", None]
    if isinstance(value, bool):
        return ["bool", value]
    if isinstance(value, Decimal):
        return ["number", _decimal_text(value)]
    return ["string", value]


def _tagged_snapshot(value: Mapping[str, ScalarValue]) -> dict[str, list[Any]]:
    return {key: _tagged_scalar(item) for key, item in sorted(value.items())}


def _canonical_fingerprint_json(
    *,
    contract_version: int,
    indicator_version: str,
    alert_id: str,
    symbol: str,
    timeframe: str,
    setup: str,
    side: str,
    price: Decimal,
    bar_time_ms: int,
    levels: Mapping[str, ScalarValue],
    context: Mapping[str, ScalarValue],
) -> str:
    # Type tags keep a JSON string "1" distinct from the JSON number 1 while
    # still treating 1, 1.0, and 1e0 as the same semantic numeric value.
    payload = {
        "alert_id": alert_id,
        "bar_time_ms": bar_time_ms,
        "context": _tagged_snapshot(context),
        "indicator_version": indicator_version,
        "levels": _tagged_snapshot(levels),
        "price": _tagged_scalar(price),
        "setup": setup,
        "side": side,
        "symbol": symbol,
        "timeframe": timeframe,
        "v": contract_version,
    }
    return json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _json_object_without_duplicates(
    pairs: list[tuple[str, Any]],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise TradingViewContractError(f"duplicate JSON object key: {key!r}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise TradingViewContractError(f"invalid non-finite JSON number: {value}")
