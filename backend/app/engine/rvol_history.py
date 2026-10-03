"""Store the sessions the charts' relative volume needs, before the open (Charts C2.4).

A candle's RVol compares today's volume with the 20 sessions before today, read
from the completed SIP sessions the chart history keeps on disk (C0.0). Charting
a symbol stores its sessions as its older candles load; this job stores them
ahead of time for every name on the shared chart watchlist, so RVol is ready
at the open. It is the ``rvol_history`` job in the sync lane, queued at 06:00
and 08:40 New York on weekdays.

A stored session is never fetched again, so a run after a complete one costs
no request and every morning after the first fetches one session per name.
Sessions are fetched newest first. A day Alpaca has no minutes for (an index
such as SPX, or a stock before it listed) is not stored, so the name has no
baseline yet: the run notes it, moves to the next name, and does not fail.
Reads go through the chart history's own Alpaca budget (30 requests a minute
in this process); the job sleeps when it is spent instead of exceeding it, and
stops after ten minutes so a first run (20 sessions for each of 30 names) does
not hold the sync lane long. The next run continues where it stopped.
"""

from __future__ import annotations

from datetime import date, datetime
import json
import time
from typing import Callable, Protocol

from sqlmodel import Session

from app.engine import chart_rvol
from app.engine.chart_history import SYMBOL, HistoryError
from app.engine.chart_math import ET
from app.models import ChartSettingsRecord

RUN_SECONDS = 600
FATAL = {"not_configured", "access_denied"}
WAIT = {"rate_limited", "pending"}
LATE = "late"
NO_DATA = "no_data"


class RvolHistoryError(RuntimeError):
    """The run could not store what it needed. Whatever it stored is kept."""


class Calendar(Protocol):
    def hours(self, day: date) -> dict | None: ...


class History(Protocol):
    def stored(self, symbol: str, day: date) -> list[dict] | None: ...
    def session(self, symbol: str, day: date) -> list[dict]: ...


def scope(db: Session) -> list[str]:
    """The shared chart watchlist's names, each once, in its order."""
    settings = db.get(ChartSettingsRecord, "default")  # the row every browser shares
    try:
        watchlist = json.loads(settings.data_json).get("watchlist") if settings else None
    except (ValueError, AttributeError):
        watchlist = None
    chosen: list[str] = []
    for name in watchlist if isinstance(watchlist, list) else []:
        symbol = name.strip().upper() if isinstance(name, str) else ""
        if SYMBOL.fullmatch(symbol) and symbol not in chosen:
            chosen.append(symbol)
    return chosen


def store(
    db: Session,
    *,
    history: History | None = None,
    calendar: Calendar | None = None,
    clock: Callable[[], datetime] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    progress: Callable[[int, int, str], None] | None = None,
) -> tuple[int, str]:
    """Store the 20 sessions before today for each watchlist name. Returns (sessions
    fetched, message); raises RvolHistoryError when a session could not be stored."""
    if history is None:
        from app.engine.chart_history import chart_history as history
    if calendar is None:
        from app.engine.chart_calendar import chart_calendar as calendar
    clock = clock or (lambda: datetime.now(ET))
    today = clock().astimezone(ET).date()
    # Today's window. On a weekend or holiday it is also the next session's: nothing trades in between.
    days = chart_rvol.window(today, calendar.hours)
    if days is None:
        raise RvolHistoryError(f"The market calendar is unavailable, so the sessions before {today} cannot be chosen; the next run retries.")
    symbols = scope(db)
    if not symbols:
        return 0, "The chart watchlist is empty; nothing to store."
    deadline = time.monotonic() + RUN_SECONDS
    fetched, complete, failures, left, absent = 0, 0, [], 0, []
    for index, symbol in enumerate(symbols):
        if progress:
            progress(index, len(symbols), f"{symbol}: {index + 1} of {len(symbols)} watchlist names")
        missing = [day for day in reversed(days) if history.stored(symbol, day) is None]
        problems, remaining, empty = [], 0, False
        for position, day in enumerate(missing):
            outcome = _fetch(history, symbol, day, deadline, sleep)
            if outcome is LATE:
                remaining = len(missing) - position
                break
            if outcome is NO_DATA:
                absent.append(f"{symbol} on {day} and earlier")
                empty = True
                break  # older sessions have none either
            if outcome is None:
                fetched += 1
            else:
                problems.append(f"{day} ({outcome})")
        left += remaining
        if problems:
            failures.append(f"{symbol} {', '.join(problems[:2])}" + (f" and {len(problems) - 2} more" if len(problems) > 2 else ""))
        elif not remaining and not empty:
            complete += 1
    message = f"{today}: stored {fetched} session(s); {complete} of {len(symbols)} watchlist names have the 20 sessions before today."
    if absent:
        message += f" Alpaca has no minutes for {', '.join(absent)} (an index, or not listed yet), so RVol waits."
    if left:
        message += f" {left} session(s) left for the next run."
    if failures:
        shown = "; ".join(failures[:2]) + (f"; and {len(failures) - 2} more" if len(failures) > 2 else "")
        raise RvolHistoryError(f"Relative volume history incomplete: {shown}. {message} The next run retries.")
    return fetched, message


def _fetch(history: History, symbol: str, day: date, deadline: float, sleep: Callable[[float], None]) -> str | None:
    """None once the session is stored, LATE when the run's time is up first, NO_DATA when Alpaca
    has no minutes that day, else what went wrong."""
    while time.monotonic() < deadline:
        try:
            history.session(symbol, day)
            return None
        except HistoryError as exc:
            if exc.code in FATAL:
                raise RvolHistoryError(f"{exc} Sessions already stored are kept; the next run retries.") from exc
            if exc.code == NO_DATA:
                return NO_DATA
            if exc.code not in WAIT:
                return str(exc)
            # Wait out the budget (or a batch still loading), never past the run's end.
            sleep(max(0.5, min((exc.retry_at or 0) - time.time(), deadline - time.monotonic())))
    return LATE
