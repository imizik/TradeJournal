"""Defensive parser for TradingView Strategy Tester trade-list exports.

TradingView emits one entry row and one exit row for each simulated trade.  A
run import must stay separate from the journal's real fill/FIFO pipeline, so
this module only turns CSV bytes into plain Python values and diagnostics.
"""

from __future__ import annotations

import csv
import hashlib
import io
import math
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


MAX_CSV_BYTES = 5 * 1024 * 1024
_MAX_SIGNED_INT = 2_147_483_647
_NUMERIC_QUANTUM = Decimal("0.000001")
_NUMERIC_MAX = Decimal("999999999999.999999")
_DIAGNOSTIC_VALUE_LIMIT = 160


def _short_repr(value: Any, limit: int = _DIAGNOSTIC_VALUE_LIMIT) -> str:
    """Bound untrusted values embedded in API or persisted diagnostics."""

    rendered = repr(value)
    if len(rendered) <= limit:
        return rendered
    return rendered[: limit - 3] + "..."


class TradingViewCSVError(ValueError):
    """A file-level error that prevents a trustworthy preview."""

    def __init__(self, message: str, code: Optional[str] = None):
        super().__init__(message)
        self.code = code or "invalid_csv"


@dataclass(frozen=True)
class ImportIssue:
    level: str
    code: str
    message: str
    trade_number: Optional[int] = None
    row_number: Optional[int] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "code": self.code,
            "message": self.message,
            "trade_number": self.trade_number,
            "row_number": self.row_number,
        }


@dataclass
class RejectedTrade:
    trade_number: Optional[int]
    issues: list[ImportIssue]
    raw_rows: list[dict[str, str]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "trade_number": self.trade_number,
            "issues": [issue.to_dict() for issue in self.issues],
            "raw_rows": self.raw_rows,
        }


def _json_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


@dataclass
class ParsedTrade:
    trade_number: int
    direction: str
    entry_at: datetime
    exit_at: datetime
    entry_at_raw: str
    exit_at_raw: str
    entry_price: Decimal
    exit_price: Decimal
    quantity: Decimal
    net_pnl: Optional[Decimal]
    return_pct: Optional[Decimal]
    mfe: Optional[Decimal]
    mfe_pct: Optional[Decimal]
    mae: Optional[Decimal]
    mae_pct: Optional[Decimal]
    cumulative_pnl: Optional[Decimal]
    cumulative_return_pct: Optional[Decimal]
    duration_bars: Optional[int]
    duration_minutes: int
    entry_signal: Optional[str]
    exit_signal: Optional[str]
    entry_comment: Optional[str]
    exit_comment: Optional[str]
    feature_snapshot: dict[str, Any]
    raw_entry_row: dict[str, str]
    raw_exit_row: dict[str, str]
    warnings: list[ImportIssue] = field(default_factory=list)

    def preview_dict(self) -> dict[str, Any]:
        keys = (
            "trade_number",
            "direction",
            "entry_at",
            "exit_at",
            "entry_at_raw",
            "exit_at_raw",
            "entry_price",
            "exit_price",
            "quantity",
            "net_pnl",
            "return_pct",
            "mfe",
            "mfe_pct",
            "mae",
            "mae_pct",
            "cumulative_pnl",
            "cumulative_return_pct",
            "duration_bars",
            "duration_minutes",
            "entry_signal",
            "exit_signal",
            "entry_comment",
            "exit_comment",
            "feature_snapshot",
            "raw_entry_row",
            "raw_exit_row",
        )
        result = {key: _json_value(getattr(self, key)) for key in keys}
        result["warnings"] = [issue.to_dict() for issue in self.warnings]
        return result


@dataclass
class TradingViewParseResult:
    source_sha256: str
    encoding: str
    headers: list[str]
    mapping: dict[str, str]
    row_count: int
    trades: list[ParsedTrade]
    rejected_trades: list[RejectedTrade]
    warnings: list[ImportIssue]

    @property
    def accepted_count(self) -> int:
        return len(self.trades)

    @property
    def rejected_count(self) -> int:
        return len(self.rejected_trades)

    @property
    def total_group_count(self) -> int:
        return self.accepted_count + self.rejected_count

    @property
    def warning_count(self) -> int:
        return len(self.warnings)

    @property
    def error_count(self) -> int:
        return sum(
            issue.level == "error"
            for rejected in self.rejected_trades
            for issue in rejected.issues
        )

    def preview_dict(self) -> dict[str, Any]:
        return {
            "source_sha256": self.source_sha256,
            "encoding": self.encoding,
            "headers": self.headers,
            "mapping": self.mapping,
            "row_count": self.row_count,
            "total_group_count": self.total_group_count,
            "accepted_count": self.accepted_count,
            "rejected_count": self.rejected_count,
            "warning_count": self.warning_count,
            "error_count": self.error_count,
            "warnings": [issue.to_dict() for issue in self.warnings],
            "trades": [trade.preview_dict() for trade in self.trades],
            "rejected_trades": [trade.to_dict() for trade in self.rejected_trades],
        }


def _header_key(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).strip().lower()
    value = value.replace("p&l", "pnl").replace("&", " and ")
    value = value.replace("#", " number ").replace("%", " percent ")
    return " ".join(re.findall(r"[a-z0-9]+", value))


_HEADER_ALIASES: dict[str, tuple[str, ...]] = {
    "trade_number": (
        "trade number",
        "trade no",
        "trade id",
        "trade",
    ),
    "type": ("type", "order type", "trade type"),
    "timestamp": (
        "date and time",
        "date time",
        "datetime",
        "timestamp",
        "time",
    ),
    "signal": ("signal", "signal name", "order", "order name"),
    "comment": ("comment", "comments", "order comment", "trade comment"),
    "price": ("price usd", "price", "fill price", "execution price"),
    "quantity": (
        "size qty",
        "quantity",
        "qty",
        "contracts",
        "shares",
    ),
    "size_value": ("size value", "position value", "value"),
    "net_pnl": (
        "net pnl usd",
        "net pnl",
        "net profit usd",
        "net profit",
        "profit usd",
        "profit",
    ),
    "return_pct": (
        "return percent",
        "net pnl percent",
        "net profit percent",
        "profit percent",
    ),
    "mfe": (
        "favorable excursion usd",
        "favourable excursion usd",
        "favorable excursion",
        "favourable excursion",
        "mfe usd",
        "mfe",
        "run up usd",
        "run up",
        "runup usd",
        "runup",
    ),
    "mfe_pct": (
        "favorable excursion percent",
        "favourable excursion percent",
        "mfe percent",
        "run up percent",
        "runup percent",
    ),
    "mae": (
        "adverse excursion usd",
        "adverse excursion",
        "mae usd",
        "mae",
        "drawdown usd",
        "drawdown",
    ),
    "mae_pct": (
        "adverse excursion percent",
        "mae percent",
        "drawdown percent",
    ),
    "cumulative_pnl": (
        "cumulative pnl usd",
        "cumulative pnl",
        "cumulative profit usd",
        "cumulative profit",
    ),
    "cumulative_return_pct": (
        "cumulative pnl percent",
        "cumulative return percent",
        "cumulative profit percent",
    ),
    "duration_bars": (
        "duration bars",
        "bars held",
        "bars",
        "duration",
    ),
}

_ALIAS_TO_FIELD = {
    _header_key(alias): canonical
    for canonical, aliases in _HEADER_ALIASES.items()
    for alias in aliases
}
_REQUIRED_FIELDS = (
    "trade_number",
    "type",
    "timestamp",
    "price",
    "quantity",
)


@dataclass(frozen=True)
class _SourceRow:
    row_number: int
    raw: dict[str, str]


class _ValueErrorWithCode(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _build_mapping(headers: list[str]) -> dict[str, str]:
    seen_headers: set[str] = set()
    mapping: dict[str, str] = {}
    for header in headers:
        normalized = _header_key(header)
        if not normalized:
            raise TradingViewCSVError("CSV contains a blank header", "invalid_header")
        if normalized in seen_headers:
            raise TradingViewCSVError(
                f"CSV contains a duplicate header: {_short_repr(header)}",
                "duplicate_header",
            )
        seen_headers.add(normalized)
        canonical = _ALIAS_TO_FIELD.get(normalized)
        if canonical is None:
            continue
        if canonical in mapping:
            raise TradingViewCSVError(
                f"Multiple columns map to {canonical!r}", "duplicate_header"
            )
        mapping[canonical] = header

    missing = [field for field in _REQUIRED_FIELDS if field not in mapping]
    if missing:
        raise TradingViewCSVError(
            "CSV is missing required TradingView column(s): " + ", ".join(missing),
            "missing_header",
        )
    return mapping


_BLANK_VALUES = {"", "-", "--", "n/a", "na", "null", "none", "—"}


def _decimal(value: Optional[str]) -> Optional[Decimal]:
    if value is None:
        return None
    cleaned = unicodedata.normalize("NFKC", value).strip()
    if cleaned.lower() in _BLANK_VALUES:
        return None
    negative = cleaned.startswith("(") and cleaned.endswith(")")
    if negative:
        cleaned = cleaned[1:-1].strip()
    cleaned = re.sub(r"(?i)\b(?:usd|usdt|eur|gbp|cad|aud)\b", "", cleaned)
    cleaned = cleaned.replace(",", "").replace("%", "")
    cleaned = cleaned.replace("$", "").replace("€", "").replace("£", "")
    cleaned = cleaned.replace("¥", "").strip()
    if negative:
        cleaned = "-" + cleaned.lstrip("+")
    try:
        result = Decimal(cleaned)
    except (InvalidOperation, ValueError):
        raise _ValueErrorWithCode(
            "invalid_decimal", f"Invalid numeric value {_short_repr(value)}"
        )
    if not result.is_finite():
        raise _ValueErrorWithCode(
            "invalid_decimal", f"Non-finite numeric value {_short_repr(value)}"
        )
    return result


def _storage_decimal(value: Decimal) -> Decimal:
    """Return a value that PostgreSQL ``NUMERIC(18,6)`` stores exactly."""

    if abs(value) > _NUMERIC_MAX:
        raise _ValueErrorWithCode(
            "numeric_out_of_range",
            f"Numeric value {_short_repr(value)} exceeds NUMERIC(18,6)",
        )
    try:
        quantized = value.quantize(_NUMERIC_QUANTUM)
    except InvalidOperation:
        raise _ValueErrorWithCode(
            "numeric_out_of_range",
            f"Numeric value {_short_repr(value)} cannot be represented as NUMERIC(18,6)",
        )
    if quantized != value:
        raise _ValueErrorWithCode(
            "numeric_scale",
            f"Numeric value {_short_repr(value)} has more than 6 significant decimal places",
        )
    return quantized


def _positive_decimal(value: Optional[str], label: str) -> Decimal:
    try:
        result = _decimal(value)
        if result is not None:
            result = _storage_decimal(result)
    except _ValueErrorWithCode as exc:
        raise _ValueErrorWithCode(
            f"invalid_{label}",
            f"Invalid {label.replace('_', ' ')}: {exc}",
        )
    if result is None:
        raise _ValueErrorWithCode(
            f"missing_{label}", f"{label.replace('_', ' ').title()} is required"
        )
    if result <= 0:
        raise _ValueErrorWithCode(
            f"invalid_{label}", f"{label.replace('_', ' ').title()} must be positive"
        )
    return result


def _trade_number(value: Optional[str]) -> int:
    try:
        number = _decimal(value)
    except _ValueErrorWithCode:
        number = None
    if (
        number is None
        or number != number.to_integral_value()
        or number <= 0
        or number > _MAX_SIGNED_INT
    ):
        raise _ValueErrorWithCode(
            "invalid_trade_number", f"Invalid trade number {_short_repr(value)}"
        )
    return int(number)


def _row_value(row: _SourceRow, mapping: dict[str, str], key: str) -> Optional[str]:
    header = mapping.get(key)
    if header is None:
        return None
    value = row.raw.get(header)
    return value.strip() if value is not None else None


def _row_kind(row: _SourceRow, mapping: dict[str, str]) -> tuple[str, str]:
    value = _row_value(row, mapping, "type") or ""
    words = set(re.findall(r"[a-z]+", value.lower()))
    kinds = words.intersection({"entry", "exit"})
    directions = words.intersection({"long", "short"})
    if len(kinds) != 1 or len(directions) != 1:
        raise _ValueErrorWithCode(
            "invalid_type",
            "Type must identify Entry/Exit and long/short; got "
            + _short_repr(value),
        )
    return next(iter(kinds)), next(iter(directions))


_TIMESTAMP_FORMATS = (
    "%Y-%m-%d %H:%M:%S.%f",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%m/%d/%Y %H:%M:%S",
    "%m/%d/%Y %H:%M",
    "%Y/%m/%d %H:%M:%S",
    "%Y/%m/%d %H:%M",
)


def _wall_time_to_utc(
    value: Optional[str],
    source_zone: ZoneInfo,
) -> tuple[datetime, Optional[str]]:
    raw = (value or "").strip()
    if not raw:
        raise _ValueErrorWithCode("missing_timestamp", "Date and time is required")

    parsed: Optional[datetime] = None
    iso_value = raw[:-1] + "+00:00" if raw.endswith(("Z", "z")) else raw
    try:
        parsed = datetime.fromisoformat(iso_value)
    except ValueError:
        for fmt in _TIMESTAMP_FORMATS:
            try:
                parsed = datetime.strptime(raw, fmt)
                break
            except ValueError:
                pass
    if parsed is None:
        raise _ValueErrorWithCode(
            "invalid_timestamp",
            f"Unsupported date and time {_short_repr(raw)}",
        )
    if parsed.tzinfo is not None:
        return parsed.astimezone(timezone.utc).replace(tzinfo=None), None

    candidates: list[tuple[int, datetime, datetime]] = []
    for fold in (0, 1):
        aware = parsed.replace(tzinfo=source_zone, fold=fold)
        utc_value = aware.astimezone(timezone.utc)
        round_trip = utc_value.astimezone(source_zone).replace(tzinfo=None)
        if round_trip == parsed:
            candidates.append((fold, aware, utc_value))
    if not candidates:
        raise _ValueErrorWithCode(
            "nonexistent_local_time",
            f"Local time {_short_repr(raw)} does not exist in "
            f"{_short_repr(source_zone.key)}",
        )

    offsets = {candidate[1].utcoffset() for candidate in candidates}
    warning = None
    if len(offsets) > 1:
        warning = (
            f"Local time {_short_repr(raw)} is ambiguous in "
            f"{_short_repr(source_zone.key)}; "
            "using fold=0 (the earlier instant)"
        )
    chosen = next((candidate for candidate in candidates if candidate[0] == 0), candidates[0])
    return chosen[2].replace(tzinfo=None), warning


def _optional_decimal(
    row: _SourceRow,
    mapping: dict[str, str],
    key: str,
    trade_number: int,
    warnings: list[ImportIssue],
) -> Optional[Decimal]:
    raw = _row_value(row, mapping, key)
    try:
        value = _decimal(raw)
        return _storage_decimal(value) if value is not None else None
    except _ValueErrorWithCode as exc:
        warnings.append(
            ImportIssue(
                "warning",
                "invalid_optional_value",
                f"Ignoring invalid {key} value {_short_repr(raw)}: {exc}",
                trade_number,
                row.row_number,
            )
        )
        return None


def _optional_integer(
    row: _SourceRow,
    mapping: dict[str, str],
    key: str,
    trade_number: int,
    warnings: list[ImportIssue],
) -> Optional[int]:
    value = _optional_decimal(row, mapping, key, trade_number, warnings)
    if value is None:
        return None
    if (
        value != value.to_integral_value()
        or value < 0
        or value > _MAX_SIGNED_INT
    ):
        warnings.append(
            ImportIssue(
                "warning",
                "invalid_optional_value",
                f"Ignoring non-integer {key} value {str(value)!r}",
                trade_number,
                row.row_number,
            )
        )
        return None
    return int(value)


def _feature_value(value: str) -> Any:
    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered in {"null", "none"}:
        return None
    if re.fullmatch(r"[+-]?\d+", value):
        try:
            return int(value)
        except ValueError:
            pass
    if re.fullmatch(r"[+-]?(?:\d+\.\d*|\.\d+|\d+[eE][+-]?\d+|\d+\.\d*[eE][+-]?\d+)", value):
        try:
            number = float(value)
            if math.isfinite(number):
                return number
        except ValueError:
            pass
    return value


def _feature_tokens(
    text: Optional[str],
    trade_number: int,
    row_number: int,
    warnings: list[ImportIssue],
) -> list[tuple[str, Any]]:
    if not text:
        return []
    match = re.search(r"(?i)(?:^|\s)sl1\|", text)
    if match is None:
        return []
    payload = text[match.end() :]
    values: list[tuple[str, Any]] = []
    for token in payload.split("|"):
        token = token.strip()
        if not token or "=" not in token:
            warnings.append(
                ImportIssue(
                    "warning",
                    "malformed_feature_token",
                    "Ignoring malformed sl1 feature token " + _short_repr(token),
                    trade_number,
                    row_number,
                )
            )
            continue
        key, raw_value = (part.strip() for part in token.split("=", 1))
        key = key.lower()
        if not re.fullmatch(r"[a-z][a-z0-9_.-]{0,63}", key) or not raw_value:
            warnings.append(
                ImportIssue(
                    "warning",
                    "malformed_feature_token",
                    "Ignoring malformed sl1 feature token " + _short_repr(token),
                    trade_number,
                    row_number,
                )
            )
            continue
        values.append((key, _feature_value(raw_value)))
    return values


def _parse_group(
    trade_number: int,
    rows: list[_SourceRow],
    mapping: dict[str, str],
    source_zone: ZoneInfo,
) -> tuple[Optional[ParsedTrade], list[ImportIssue]]:
    errors: list[ImportIssue] = []
    warnings: list[ImportIssue] = []
    entries: list[tuple[_SourceRow, str]] = []
    exits: list[tuple[_SourceRow, str]] = []

    for row in rows:
        try:
            kind, direction = _row_kind(row, mapping)
        except _ValueErrorWithCode as exc:
            errors.append(
                ImportIssue("error", exc.code, str(exc), trade_number, row.row_number)
            )
            continue
        (entries if kind == "entry" else exits).append((row, direction))

    if not entries:
        errors.append(
            ImportIssue("error", "missing_entry", "Trade has no Entry row", trade_number)
        )
    elif len(entries) > 1:
        errors.append(
            ImportIssue(
                "error",
                "duplicate_entry",
                f"Trade has {len(entries)} Entry rows; exactly one is required",
                trade_number,
            )
        )
    if not exits:
        errors.append(
            ImportIssue("error", "missing_exit", "Trade has no Exit row", trade_number)
        )
    elif len(exits) > 1:
        errors.append(
            ImportIssue(
                "error",
                "duplicate_exit",
                f"Trade has {len(exits)} Exit rows; exactly one is required",
                trade_number,
            )
        )
    if errors:
        return None, errors + warnings

    entry_row, entry_direction = entries[0]
    exit_row, exit_direction = exits[0]
    if entry_direction != exit_direction:
        errors.append(
            ImportIssue(
                "error",
                "direction_mismatch",
                f"Entry is {entry_direction} but Exit is {exit_direction}",
                trade_number,
            )
        )

    parsed_times: dict[str, datetime] = {}
    for label, row in (("entry", entry_row), ("exit", exit_row)):
        raw = _row_value(row, mapping, "timestamp")
        try:
            parsed_times[label], ambiguous_warning = _wall_time_to_utc(raw, source_zone)
            if ambiguous_warning:
                warnings.append(
                    ImportIssue(
                        "warning",
                        "ambiguous_local_time",
                        ambiguous_warning,
                        trade_number,
                        row.row_number,
                    )
                )
        except _ValueErrorWithCode as exc:
            errors.append(
                ImportIssue("error", exc.code, str(exc), trade_number, row.row_number)
            )

    parsed_prices: dict[str, Decimal] = {}
    for label, row in (("entry", entry_row), ("exit", exit_row)):
        for key in ("price", "quantity"):
            try:
                value = _positive_decimal(_row_value(row, mapping, key), key)
                if key == "price":
                    parsed_prices[label] = value
                elif label == "entry":
                    entry_quantity = value
                else:
                    exit_quantity = value
            except _ValueErrorWithCode as exc:
                errors.append(
                    ImportIssue("error", exc.code, str(exc), trade_number, row.row_number)
                )

    if errors:
        return None, errors + warnings

    if parsed_times["exit"] < parsed_times["entry"]:
        errors.append(
            ImportIssue(
                "error",
                "exit_before_entry",
                "Exit time is before Entry time after timezone normalization",
                trade_number,
                exit_row.row_number,
            )
        )
        return None, errors + warnings

    elapsed = parsed_times["exit"] - parsed_times["entry"]
    duration_minutes = elapsed.days * 1440 + elapsed.seconds // 60
    if duration_minutes > _MAX_SIGNED_INT:
        errors.append(
            ImportIssue(
                "error",
                "duration_minutes_out_of_range",
                "Computed duration_minutes exceeds a signed 32-bit integer",
                trade_number,
                exit_row.row_number,
            )
        )
        return None, errors + warnings

    if entry_quantity != exit_quantity:
        warnings.append(
            ImportIssue(
                "warning",
                "duplicate_value_mismatch",
                f"Entry quantity {entry_quantity} differs from Exit quantity {exit_quantity}; using Exit",
                trade_number,
                exit_row.row_number,
            )
        )

    metrics: dict[str, Optional[Decimal]] = {}
    metric_fields = (
        "net_pnl",
        "return_pct",
        "mfe",
        "mfe_pct",
        "mae",
        "mae_pct",
        "cumulative_pnl",
        "cumulative_return_pct",
    )
    for key in metric_fields:
        metrics[key] = _optional_decimal(
            exit_row, mapping, key, trade_number, warnings
        )
        entry_value = _optional_decimal(
            entry_row, mapping, key, trade_number, warnings
        )
        if (
            metrics[key] is not None
            and entry_value is not None
            and metrics[key] != entry_value
        ):
            warnings.append(
                ImportIssue(
                    "warning",
                    "duplicate_value_mismatch",
                    f"Entry {key} {entry_value} differs from Exit {key} {metrics[key]}; using Exit",
                    trade_number,
                    entry_row.row_number,
                )
            )

    duration_bars = _optional_integer(
        exit_row, mapping, "duration_bars", trade_number, warnings
    )
    entry_duration = _optional_integer(
        entry_row, mapping, "duration_bars", trade_number, warnings
    )
    if (
        duration_bars is not None
        and entry_duration is not None
        and duration_bars != entry_duration
    ):
        warnings.append(
            ImportIssue(
                "warning",
                "duplicate_value_mismatch",
                f"Entry duration_bars {entry_duration} differs from Exit duration_bars {duration_bars}; using Exit",
                trade_number,
                entry_row.row_number,
            )
        )

    entry_signal = _row_value(entry_row, mapping, "signal") or None
    exit_signal = _row_value(exit_row, mapping, "signal") or None
    entry_comment = _row_value(entry_row, mapping, "comment") or None
    exit_comment = _row_value(exit_row, mapping, "comment") or None
    feature_snapshot: dict[str, Any] = {}
    feature_sources = (
        (entry_signal, entry_row.row_number),
        (entry_comment, entry_row.row_number),
        (exit_signal, exit_row.row_number),
        (exit_comment, exit_row.row_number),
    )
    for text, row_number in feature_sources:
        for key, value in _feature_tokens(
            text, trade_number, row_number, warnings
        ):
            if key not in feature_snapshot:
                feature_snapshot[key] = value
            elif feature_snapshot[key] != value:
                warnings.append(
                    ImportIssue(
                        "warning",
                        "feature_conflict",
                        f"Feature {key!r} has conflicting values; keeping the first",
                        trade_number,
                        row_number,
                    )
                )

    trade = ParsedTrade(
        trade_number=trade_number,
        direction=entry_direction,
        entry_at=parsed_times["entry"],
        exit_at=parsed_times["exit"],
        entry_at_raw=_row_value(entry_row, mapping, "timestamp") or "",
        exit_at_raw=_row_value(exit_row, mapping, "timestamp") or "",
        entry_price=parsed_prices["entry"],
        exit_price=parsed_prices["exit"],
        quantity=exit_quantity,
        net_pnl=metrics["net_pnl"],
        return_pct=metrics["return_pct"],
        mfe=metrics["mfe"],
        mfe_pct=metrics["mfe_pct"],
        mae=metrics["mae"],
        mae_pct=metrics["mae_pct"],
        cumulative_pnl=metrics["cumulative_pnl"],
        cumulative_return_pct=metrics["cumulative_return_pct"],
        duration_bars=duration_bars,
        duration_minutes=duration_minutes,
        entry_signal=entry_signal,
        exit_signal=exit_signal,
        entry_comment=entry_comment,
        exit_comment=exit_comment,
        feature_snapshot=feature_snapshot,
        raw_entry_row=entry_row.raw,
        raw_exit_row=exit_row.raw,
        warnings=warnings,
    )
    return trade, warnings


def parse_tradingview_csv(
    data: bytes,
    source_timezone: str,
) -> TradingViewParseResult:
    """Parse TradingView paired trade rows without persisting anything."""

    if not isinstance(data, bytes):
        raise TradingViewCSVError("CSV input must be bytes", "invalid_input")
    if not data:
        raise TradingViewCSVError("CSV file is empty", "empty_file")
    if len(data) > MAX_CSV_BYTES:
        raise TradingViewCSVError(
            f"CSV exceeds the {MAX_CSV_BYTES}-byte upload limit", "file_too_large"
        )
    try:
        source_zone = ZoneInfo(source_timezone.strip())
    except (
        AttributeError,
        OSError,
        TypeError,
        ValueError,
        ZoneInfoNotFoundError,
    ):
        raise TradingViewCSVError(
            f"Unknown IANA source timezone {_short_repr(source_timezone)}",
            "invalid_timezone",
        )

    has_bom = data.startswith(b"\xef\xbb\xbf")
    encoding = "utf-8-sig" if has_bom else "utf-8"
    try:
        text = data.decode("utf-8-sig" if has_bom else "utf-8")
    except UnicodeDecodeError as exc:
        raise TradingViewCSVError(
            f"CSV must be UTF-8 encoded: {exc}", "invalid_encoding"
        )
    if not text.strip():
        raise TradingViewCSVError("CSV file is empty", "empty_file")
    if "\x00" in text:
        raise TradingViewCSVError("CSV contains NUL bytes", "invalid_encoding")

    try:
        reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
        original_headers = reader.fieldnames
        if not original_headers:
            raise TradingViewCSVError("CSV has no header row", "missing_header")
        headers = [header.strip() for header in original_headers]
        mapping = _build_mapping(headers)

        source_rows: list[_SourceRow] = []
        for row_number, source in enumerate(reader, start=2):
            if None in source:
                raw_extra = source.get(None)
                raise TradingViewCSVError(
                    f"CSV row {row_number} has extra column value(s): "
                    f"{_short_repr(raw_extra)}",
                    "invalid_row",
                )
            raw = {
                headers[index]: (source.get(original_headers[index]) or "")
                for index in range(len(headers))
            }
            if not any(value.strip() for value in raw.values()):
                continue
            source_rows.append(_SourceRow(row_number, raw))
    except csv.Error as exc:
        raise TradingViewCSVError(
            f"Malformed CSV: {_short_repr(str(exc))}", "invalid_csv"
        )

    if not source_rows:
        raise TradingViewCSVError("CSV has no data rows", "empty_file")

    grouped: dict[int, list[_SourceRow]] = {}
    rejected: list[RejectedTrade] = []
    for row in source_rows:
        try:
            number = _trade_number(_row_value(row, mapping, "trade_number"))
        except _ValueErrorWithCode as exc:
            issue = ImportIssue("error", exc.code, str(exc), None, row.row_number)
            rejected.append(RejectedTrade(None, [issue], [row.raw]))
            continue
        grouped.setdefault(number, []).append(row)

    trades: list[ParsedTrade] = []
    warnings: list[ImportIssue] = []
    for number, rows in grouped.items():
        trade, issues = _parse_group(number, rows, mapping, source_zone)
        warnings.extend(issue for issue in issues if issue.level == "warning")
        if trade is not None:
            trades.append(trade)
        else:
            rejected.append(RejectedTrade(number, issues, [row.raw for row in rows]))

    return TradingViewParseResult(
        source_sha256=hashlib.sha256(data).hexdigest(),
        encoding=encoding,
        headers=headers,
        mapping=mapping,
        row_count=len(source_rows),
        trades=trades,
        rejected_trades=rejected,
        warnings=warnings,
    )


__all__ = [
    "MAX_CSV_BYTES",
    "ImportIssue",
    "ParsedTrade",
    "RejectedTrade",
    "TradingViewCSVError",
    "TradingViewParseResult",
    "parse_tradingview_csv",
]
