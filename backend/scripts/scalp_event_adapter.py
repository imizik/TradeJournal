"""Offline SPY/QQQ event normalization; deliberately has NO runtime wiring.

Input is caller-supplied bytes and receipt clocks. This module never obtains data,
reads credentials/configuration, writes files, computes strategy performance, or
imports the application. There is no CLI, stream client, timer or activation flag.

The wire shape follows Tradier's quote/timesale examples, with epoch milliseconds
for stream timestamps. Parsing a field is NOT verification of its exchange/feed
meaning. In particular seq/flag/session, NBBO entitlement, clock synchronization,
quote-size units and health require separate evidence before any live use.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import json

MAX_FRAME_BYTES = 65536
MAX_FRAME_EVENTS = 128
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


@dataclass(frozen=True)
class QuoteObservation:
    symbol: str | None
    bid: Decimal | None
    ask: Decimal | None
    bid_size: int | None
    ask_size: int | None
    bid_at: datetime | None
    ask_at: datetime | None
    bid_exchange: str | None
    ask_exchange: str | None


@dataclass(frozen=True)
class TradeObservation:
    symbol: str | None
    price: Decimal | None
    size: Decimal | None
    source_at: datetime | None
    sequence: int | None
    condition: str | None
    session: str | None
    cancelled: bool | None
    correction: bool | None
    exchange: str | None


@dataclass(frozen=True)
class Event:
    # Ordinal is transport position, never a fabricated exchange sequence.
    ordinal: int
    raw: bytes
    kind: str
    observation: QuoteObservation | TradeObservation | None
    issues: tuple[str, ...]


@dataclass(frozen=True)
class Frame:
    raw: bytes
    received_at: datetime
    received_mono_ns: int
    events: tuple[Event, ...]
    issues: tuple[str, ...] = ()


def _reject_constant(value):
    raise ValueError("nonfinite_json")


def _unique_object(pairs):
    row = {}
    for key, value in pairs:
        if key in row:
            raise ValueError("duplicate_json_key")
        row[key] = value
    return row


class _Fields:
    def __init__(self, row):
        self.row = row
        self.issues = []

    def value(self, key):
        if key not in self.row or self.row[key] is None:
            self.issues.append(f"missing:{key}")
            return None
        return self.row[key]

    def invalid(self, key):
        self.issues.append(f"invalid:{key}")
        return None

    def text(self, key, *, allow_empty=False):
        value = self.value(key)
        if value is None:
            return None
        if not isinstance(value, str) or (not allow_empty and (not value or value != value.strip())):
            return self.invalid(key)
        return value

    def decimal(self, key):
        value = self.value(key)
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
            return self.invalid(key)
        try:
            result = Decimal(value)
        except InvalidOperation:
            return self.invalid(key)
        if not result.is_finite() or result < 0:
            return self.invalid(key)
        return result  # Zero is retained; it cannot become a fabricated positive bid.

    def integer(self, key):
        value = self.value(key)
        if value is None:
            return None
        if isinstance(value, str) and value and value.isascii() and value.isdigit():
            try:
                value = int(value)
            except ValueError:
                return self.invalid(key)
        if type(value) is not int or value < 0:
            return self.invalid(key)
        return value

    def boolean(self, key):
        value = self.value(key)
        if value is None:
            return None
        if type(value) is not bool:
            return self.invalid(key)
        return value

    def timestamp(self, key):
        value = self.integer(key)
        if value is None:
            return None
        try:
            return EPOCH + timedelta(milliseconds=value)
        except (OverflowError, ValueError):
            return self.invalid(key)


def _decode(line, ordinal):
    try:
        row = json.loads(line.decode("utf-8"), parse_float=Decimal,
                         parse_constant=_reject_constant, object_pairs_hook=_unique_object)
    except (UnicodeError, ValueError, RecursionError):
        return Event(ordinal, line, "invalid", None, ("invalid_json_object",))
    if not isinstance(row, dict):
        return Event(ordinal, line, "invalid", None, ("invalid_json_object",))
    kind = row.get("type")
    if kind not in ("quote", "timesale"):
        # Status/error/summary messages are not discarded or treated as health.
        return Event(ordinal, line, "unsupported", None, ("unsupported_event_type",))
    f = _Fields(row)
    if kind == "quote":
        observation = QuoteObservation(
            symbol=f.text("symbol"), bid=f.decimal("bid"), ask=f.decimal("ask"),
            bid_size=f.integer("bidsz"), ask_size=f.integer("asksz"),
            bid_at=f.timestamp("biddate"), ask_at=f.timestamp("askdate"),
            bid_exchange=f.text("bidexch"), ask_exchange=f.text("askexch"),
        )
    else:
        observation = TradeObservation(
            symbol=f.text("symbol"), price=f.decimal("last"), size=f.decimal("size"),
            source_at=f.timestamp("date"), sequence=f.integer("seq"),
            condition=f.text("flag", allow_empty=True), session=f.text("session"),
            cancelled=f.boolean("cancel"), correction=f.boolean("correction"), exchange=f.text("exch"),
        )
    return Event(ordinal, line, kind, observation, tuple(f.issues))


def decode_frame(raw: bytes, *, received_at: datetime, received_mono_ns: int) -> Frame:
    """Normalize one complete, caller-framed newline-JSON message, in memory.

    All events retain the same receipt time. No sorting, deduplication, price
    filtering, coalescing, timestamp repair or health inference takes place.
    Input framing and verified provider semantics belong to a future adapter.
    Any frame/event issue must remain visible to that future consumer; skipping
    a bad trade while exposed is not evidence of an uninterrupted observation.
    """
    if type(raw) is not bytes:
        raise TypeError("raw must be immutable bytes")
    if not isinstance(received_at, datetime) or received_at.tzinfo is None or received_at.utcoffset() is None:
        raise ValueError("aware receipt time required")
    if type(received_mono_ns) is not int or received_mono_ns < 0:
        raise ValueError("nonnegative integer monotonic receipt required")
    received_at = received_at.astimezone(timezone.utc)
    if len(raw) > MAX_FRAME_BYTES:
        return Frame(raw, received_at, received_mono_ns, (), ("frame_too_large",))
    lines = [line for line in raw.split(b"\n") if line.strip()]
    if not lines:
        return Frame(raw, received_at, received_mono_ns, (), ("empty_frame",))
    if len(lines) > MAX_FRAME_EVENTS:
        return Frame(raw, received_at, received_mono_ns, (), ("too_many_events",))
    events = tuple(_decode(line, i) for i, line in enumerate(lines))
    return Frame(raw, received_at, received_mono_ns, events)
