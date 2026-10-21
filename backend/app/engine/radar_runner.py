"""Radar PR 1: one Tradier quote pass a minute over the tracked symbol list.

Off unless ``RADAR_ENABLED`` is true and ``RADAR_STORE`` is an absolute path,
and off when Tradier is not configured. A pass runs only inside the regular
session of ``ChartCalendar.hours`` (holidays and early closes included); when
the calendar is unavailable during clock hours the pass is recorded as skipped
rather than guessed. Symbols go out in requests of at most ``BATCH_SIZE``
through ``tradier.get_quotes_once``, at most ``MAX_REQUESTS`` per pass. A rate
limit or transport failure ends the pass at once (recorded failed or partial);
the next minute tries again. Nothing is retried within a pass, detected, sent
or traded here.
"""
from __future__ import annotations

from datetime import UTC, date, datetime
import logging
import os
import time
from typing import Callable

from app.engine import tradier
from app.engine.chart_math import ET, REGULAR_CLOSE, REGULAR_OPEN, session_windows
from app.engine.radar_store import RadarPass, RadarQuote, RadarStore, load_universe

log = logging.getLogger(__name__)

PASS_SECONDS = 60
BATCH_SIZE = 50
MAX_REQUESTS = 6


def enabled() -> bool:
    return os.environ.get("RADAR_ENABLED", "false").lower() in ("1", "true", "yes")


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _raw_float(raw: dict | None, key: str) -> float | None:
    return tradier._f((raw or {}).get(key))


class RadarRunner:
    def __init__(self, store: RadarStore, calendar, *, universe: dict | None = None,
                 quotes: Callable[[list[str]], dict] = tradier.get_quotes_once,
                 clock: Callable[[], float] = time.time):
        self.store = store
        self.calendar = calendar
        self.universe = universe or load_universe()
        self.symbols = [row["symbol"] for row in self.universe["symbols"]]
        self.quotes = quotes
        self.clock = clock
        self._pruned_for: date | None = None

    def _regular(self, today: date, minute: int) -> tuple[bool, str | None]:
        """(inside the regular session, skip reason to record or None)."""
        hours = self.calendar.hours(today)
        if hours is None:
            # Clock hours cannot see holidays or early closes, so record the gap instead of guessing.
            clock_hours = today.weekday() < 5 and REGULAR_OPEN <= minute < REGULAR_CLOSE
            return False, "calendar_unavailable" if clock_hours else None
        regular = next((w for w in session_windows(today, hours) if w[0] == "regular"), None)
        return regular is not None and regular[1] <= minute < regular[2], None

    def run_once(self) -> int | None:
        """Record one pass when the regular session is open; returns the pass id, or None outside hours."""
        started = datetime.fromtimestamp(self.clock(), ET)
        today, minute = started.date(), started.hour * 60 + started.minute
        inside, skip = self._regular(today, minute)
        if not inside and skip is None:
            return None
        record: RadarPass = {"session_date": today.isoformat(), "started_at": _iso(started), "finished_at": "",
                             "universe_version": self.universe["version"], "status": "skipped",
                             "symbols_requested": 0, "symbols_returned": 0, "unmatched": [], "requests_used": 0,
                             "error": None, "skip_reason": skip}
        rows: list[RadarQuote] = []
        if inside:
            if self._pruned_for != today:
                self.store.prune_quotes()
                self._pruned_for = today
            rows = self._collect(record)
        record["finished_at"] = _iso(datetime.fromtimestamp(self.clock(), ET))
        return self.store.append_pass(record, rows)

    def _collect(self, record: RadarPass) -> list[RadarQuote]:
        batches = [self.symbols[i:i + BATCH_SIZE] for i in range(0, len(self.symbols), BATCH_SIZE)]
        errors = []
        if len(batches) > MAX_REQUESTS:
            left = sum(len(b) for b in batches[MAX_REQUESTS:])
            errors.append(f"request cap {MAX_REQUESTS}: {left} symbols not requested")
            batches = batches[:MAX_REQUESTS]
        rows: list[RadarQuote] = []
        unmatched: list[str] = []
        failed = False
        for batch in batches:
            record["requests_used"] += 1
            record["symbols_requested"] += len(batch)
            try:
                found = self.quotes(batch)
            except Exception as exc:  # a 429 or transport error ends the pass; the next minute tries again
                errors.append(f"{type(exc).__name__}: {str(exc)[:200]}")
                failed = True
                break
            retrieved = _iso(datetime.fromtimestamp(self.clock(), ET))
            for symbol in batch:
                quote = found.get(symbol)
                if quote is None:
                    unmatched.append(symbol)
                    continue
                rows.append({"symbol": symbol, "last": quote.last, "prev_close": _raw_float(quote.raw, "prevclose"),
                             "open": _raw_float(quote.raw, "open"), "high": _raw_float(quote.raw, "high"),
                             "low": _raw_float(quote.raw, "low"), "volume": quote.volume, "bid": quote.bid,
                             "ask": quote.ask, "trade_time_ms": quote.trade_date, "retrieved_at": retrieved})
        record["symbols_returned"] = len(rows)
        record["unmatched"] = unmatched
        record["error"] = "; ".join(errors) or None
        if failed:
            record["status"] = "partial" if rows else "failed"
        else:
            record["status"] = "partial" if errors else "ok"
        return rows


def runner_from_env() -> RadarRunner | None:
    if not enabled():
        return None
    store = os.environ.get("RADAR_STORE", "").strip()
    if not store or not os.path.isabs(store):
        log.error("RADAR_ENABLED needs an absolute RADAR_STORE; Radar stays off")
        return None
    if not tradier.tradier_configured():
        log.error("RADAR_ENABLED needs TRADIER_API_KEY; Radar stays off")
        return None
    from app.engine.chart_calendar import chart_calendar
    return RadarRunner(RadarStore(store), chart_calendar)
