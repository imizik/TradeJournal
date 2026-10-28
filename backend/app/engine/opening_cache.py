"""Cache-only projection for the bounded Tradier opening research handoff.

This module only projects records already held by ``ChartFeed`` and the
in-memory ``ChartCalendar``. It has no provider, disk, scheduler or stream path.
"""

from datetime import UTC, datetime, timedelta
import math
import re

from app.engine.chart_math import ET

SCHEMA = "TRADIER_OPENING_CACHE_V1"
OBSERVATION_SCHEMA = "TRADIER_OPENING_OBSERVATION_V1"
PRODUCTION_BASE = "https://api.tradier.com"
SYMBOLS = ("SPY", "QQQ")
QUOTE_FIELDS = ("symbol", "bid", "ask", "bidsize", "asksize", "bid_date", "ask_date", "lot_size")
BAR_FIELDS = ("time", "timestamp", "open", "high", "low", "close", "volume")
_CHECKPOINT = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def parse_checkpoint(value: str, now: datetime) -> datetime:
    """Validate a live opening checkpoint before touching either cache."""
    if not isinstance(value, str) or not _CHECKPOINT.fullmatch(value):
        raise ValueError("invalid_checkpoint")
    try:
        checkpoint = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError:
        raise ValueError("invalid_checkpoint") from None
    local = checkpoint.astimezone(ET)
    current = now.astimezone(ET)
    if local.date() != current.date() or local.second or local.microsecond:
        raise ValueError("invalid_checkpoint")
    minute = local.hour * 60 + local.minute
    if minute < 570 or minute > 600 or (minute - 570) % 5:
        raise ValueError("invalid_checkpoint")
    if checkpoint > now or now > checkpoint + timedelta(seconds=5):
        raise ValueError("invalid_checkpoint")
    return checkpoint

def parse_observation_checkpoint(value: str, now: datetime) -> datetime:
    """Validate each minute from the open through 10:16 ET, same day only."""
    if not isinstance(value, str) or not _CHECKPOINT.fullmatch(value):
        raise ValueError("invalid_checkpoint")
    try:
        checkpoint = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError:
        raise ValueError("invalid_checkpoint") from None
    local = checkpoint.astimezone(ET)
    current = now.astimezone(ET)
    minute = local.hour * 60 + local.minute
    if (
        local.date() != current.date()
        or local.second
        or local.microsecond
        or not 570 <= minute <= 616
        or checkpoint > now
        or now > checkpoint + timedelta(seconds=5)
    ):
        raise ValueError("invalid_checkpoint")
    return checkpoint

def _unavailable(checkpoint: str, observed: datetime, reason: str) -> dict:
    return {
        "schema": SCHEMA, "checkpoint": checkpoint, "observed_at": _iso(observed),
        "status": "unavailable", "reason": reason,
        "quotes": {}, "bars": {}, "calendar": None,
        "provider_requests": 0, "stream_sessions_created": 0,
    }


def _params(key) -> dict:
    try:
        return dict(key[2])
    except (TypeError, ValueError, IndexError):
        return {}


def _rows(data, container, key) -> list:
    section = data.get(container) if isinstance(data, dict) else None
    rows = section.get(key) if isinstance(section, dict) else None
    return [rows] if isinstance(rows, dict) else rows if isinstance(rows, list) else []


def _stamp(row) -> int | None:
    try:
        value = row.get("timestamp")
        if value is None:
            value = row.get("time")
        if isinstance(value, bool):
            return None
        stamp = int(value)
        return stamp if stamp > 0 else None
    except (TypeError, ValueError, OverflowError):
        return None


def _safe_scalar(value):
    """Keep the projection JSON primitive-only and cap attacker-sized strings."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        try:
            return value if math.isfinite(value) and abs(value) <= 1e15 else None
        except OverflowError:
            return None
    if isinstance(value, str) and len(value) <= 64:
        return value
    return None


def _fresh(candidate, observed: datetime, checkpoint: datetime) -> bool:
    if candidate is None:
        return False
    fetched, expires, _ = candidate
    return (math.isfinite(fetched) and fetched <= observed.timestamp() and fetched >= checkpoint.timestamp()
            and math.isfinite(expires) and expires > observed.timestamp())


def peek_opening_cache(feed, calendar, checkpoint: str, *, now: datetime | None = None) -> dict:
    """Build one detached, bounded snapshot without waiting on existing locks."""
    observed = now or datetime.now(UTC)
    if observed.tzinfo is None:
        raise ValueError("now_must_be_aware")
    parsed = parse_checkpoint(checkpoint, observed)
    snapshot = feed.nonblocking_cache_peek()
    if snapshot is None:
        return _unavailable(checkpoint, observed, "cache_busy")

    # Identify the newest production cache entry addressing each requested
    # symbol. A malformed newest entry remains the answer; older data is never
    # silently substituted.
    newest_quotes = {}
    newest_bars = {}
    for key, cached in snapshot:
        try:
            base, path, _ = key
            fetched = float(cached.fetched_at)
            expires = float(cached.expires_at)
        except (TypeError, ValueError, AttributeError):
            continue
        if base != PRODUCTION_BASE or not math.isfinite(fetched):
            continue
        params = _params(key)
        if path == "/v1/markets/quotes":
            addressed = {s.strip().upper() for s in str(params.get("symbols", "")).split(",")}
            for symbol in SYMBOLS:
                if symbol in addressed and (symbol not in newest_quotes or fetched > newest_quotes[symbol][0]):
                    newest_quotes[symbol] = (fetched, expires, cached.data)
        elif path == "/v1/markets/timesales" and params.get("interval") == "1min":
            symbol = str(params.get("symbol", "")).upper()
            if symbol in SYMBOLS and (symbol not in newest_bars or fetched > newest_bars[symbol][0]):
                newest_bars[symbol] = (fetched, expires, cached.data)

    quotes = {}
    bars = {}
    checkpoint_ts = parsed.timestamp()
    for symbol in SYMBOLS:
        chosen = newest_quotes.get(symbol)
        if _fresh(chosen, observed, parsed):
            fetched, _, payload = chosen
            matching = [r for r in _rows(payload, "quotes", "quote")[:64]
                        if isinstance(r, dict) and str(r.get("symbol", "")).upper() == symbol]
            row = matching[0] if len(matching) == 1 else None
            if row is not None:
                projected = {"symbol": symbol}
                for field in QUOTE_FIELDS[1:]:
                    if field in row:
                        value = _safe_scalar(row[field])
                        if value is not None:
                            projected[field] = value
                quotes[symbol] = {"received_at": _iso(datetime.fromtimestamp(fetched, UTC)), "data": projected}
        chosen = newest_bars.get(symbol)
        if _fresh(chosen, observed, parsed):
            fetched, _, payload = chosen
            selected = []
            for row in _rows(payload, "series", "data")[:512]:
                if not isinstance(row, dict):
                    continue
                stamp = _stamp(row)
                if stamp is None or stamp < int(datetime.fromtimestamp(checkpoint_ts, ET).replace(hour=9, minute=30).timestamp()) or stamp + 60 > checkpoint_ts:
                    continue
                projected = {field: _safe_scalar(row[field]) for field in BAR_FIELDS if field in row}
                if any(value is None for value in projected.values()):
                    continue
                selected.append(projected)
            selected.sort(key=lambda row: _stamp(row) or 0)
            bars[symbol] = {"received_at": _iso(datetime.fromtimestamp(fetched, UTC)), "data": selected[:31]}

    calendar_data = None
    local_day = parsed.astimezone(ET).date()
    calendar_entry = calendar.nonblocking_peek(local_day) if calendar is not None else None
    if calendar_entry:
        fetched_day, item = calendar_entry
        if fetched_day == local_day and item.get("date") == local_day.isoformat():
            calendar_data = {"received_date": fetched_day.isoformat(), "data": {
                field: item[field] for field in ("date", "status", "open", "close", "source") if field in item
            }}
    needs_bars = parsed.astimezone(ET).hour * 60 + parsed.astimezone(ET).minute > 570
    if set(quotes) != set(SYMBOLS) or (needs_bars and set(bars) != set(SYMBOLS)):
        reason = "cache_missing"
    elif calendar_data is None:
        reason = "calendar_unavailable"
    else:
        reason = None
    return {
        "schema": SCHEMA, "checkpoint": checkpoint, "observed_at": _iso(observed),
        "status": "ok" if reason is None else "unavailable", "reason": reason,
        "quotes": quotes, "bars": bars, "calendar": calendar_data,
        "provider_requests": 0, "stream_sessions_created": 0,
    }


def peek_opening_observation(
    feed, checkpoint: str, *, now: datetime | None = None
) -> dict:
    """Project only fresh cached quotes for one opening-minute observation.

    This shares the bounded, nonblocking chart-cache snapshot and newest-entry
    rules with the five-minute packet route. It never asks ChartFeed to read or
    refresh, touches no calendar, and returns provider timestamp values as seen;
    the downstream consumer decides whether each quote side is causally usable.
    """
    observed = now or datetime.now(UTC)
    if observed.tzinfo is None:
        raise ValueError("now_must_be_aware")
    parsed = parse_observation_checkpoint(checkpoint, observed)

    def unavailable(reason):
        return {
            "schema": OBSERVATION_SCHEMA,
            "checkpoint": checkpoint,
            "observed_at": _iso(observed),
            "status": "unavailable",
            "reason": reason,
            "quotes": {},
            "provider_requests": 0,
            "stream_sessions_created": 0,
        }

    snapshot = feed.nonblocking_cache_peek()
    if snapshot is None:
        return unavailable("cache_busy")

    newest_quotes = {}
    for key, cached in snapshot:
        try:
            base, path, _ = key
            fetched = float(cached.fetched_at)
            expires = float(cached.expires_at)
        except (TypeError, ValueError, AttributeError):
            continue
        if base != PRODUCTION_BASE or not math.isfinite(fetched):
            continue
        if path != "/v1/markets/quotes":
            continue
        addressed = {
            s.strip().upper() for s in str(_params(key).get("symbols", "")).split(",")
        }
        for symbol in SYMBOLS:
            if symbol in addressed and (
                symbol not in newest_quotes or fetched > newest_quotes[symbol][0]
            ):
                newest_quotes[symbol] = (fetched, expires, cached.data)

    quotes = {}
    for symbol in SYMBOLS:
        chosen = newest_quotes.get(symbol)
        if not _fresh(chosen, observed, parsed):
            continue
        fetched, _, payload = chosen
        matching = [
            row
            for row in _rows(payload, "quotes", "quote")[:64]
            if isinstance(row, dict) and str(row.get("symbol", "")).upper() == symbol
        ]
        if len(matching) != 1:
            continue
        row = matching[0]
        projected = {"symbol": symbol}
        for field in QUOTE_FIELDS[1:]:
            if field in row:
                value = _safe_scalar(row[field])
                if value is not None:
                    projected[field] = value
        quotes[symbol] = {
            "received_at": _iso(datetime.fromtimestamp(fetched, UTC)),
            "data": projected,
        }
    reason = None if set(quotes) == set(SYMBOLS) else "cache_missing"
    return {
        "schema": OBSERVATION_SCHEMA,
        "checkpoint": checkpoint,
        "observed_at": _iso(observed),
        "status": "ok" if reason is None else "unavailable",
        "reason": reason,
        "quotes": quotes,
        "provider_requests": 0,
        "stream_sessions_created": 0,
    }
