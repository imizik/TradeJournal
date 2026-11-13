"""Known events where the owner looks on the desk: earnings tags on the book and Watching rows, the chart's earnings
and macro markers, and the implied move into a report.

Earnings come from the app's one earnings source, Tradier's corporate calendar, through the symbol-info cache
(``symbol_events.chart_earnings``: kept 12 hours on disk, stale symbols refreshed in one batched background read, never
a read in the request). That calendar has dates only, so nothing here claims before the open or after the close. A
symbol with no upcoming row in it shows nothing: no date is projected from earlier quarters. Macro days (FOMC, CPI,
jobs) come from ``app/data/macro_calendar.json``, whose ``market_closed`` list also counts trading days.

A row's tag (``tags``): grey within the next ``WINDOW`` trading days; amber whenever a held option on the symbol expires
on or after the report date (the report is inside the contract's life), however far off. Nothing otherwise.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Iterable

from app.engine.market_context import NO_EARNINGS

log = logging.getLogger(__name__)

MACRO_FILE = Path(__file__).resolve().parents[1] / "data" / "macro_calendar.json"
WINDOW = 7  # trading days ahead for the grey tag
MAX_SYMBOLS = 60  # the book and the Watching list together
INDEX_ETFS = ("SPY", "QQQ", "IWM")  # macro days are marked on these charts only
MACRO_AHEAD_DAYS = 21  # calendar days of upcoming macro days on an index chart
TIME_NOTE = "Time of day not published (the calendar has dates only)."


def _macro() -> dict:
    try:
        return json.loads(MACRO_FILE.read_text())
    except (OSError, ValueError):
        log.warning("desk events: the macro calendar could not be read", exc_info=True)
        return {"market_closed": [], "events": []}


def trading_days_until(today: date, target: date, closed: Iterable[str]) -> int | None:
    """Trading days after ``today`` through ``target``: 0 on the day itself, None once past. Weekends and the macro
    calendar's NYSE closures are not trading days."""
    if target < today:
        return None
    shut = set(closed)
    count, day = 0, today
    while day < target:
        day += timedelta(days=1)
        if day.weekday() < 5 and day.isoformat() not in shut:
            count += 1
    return count


def tag(symbol: str, upcoming: dict | None, today: date, held: Iterable[date], closed: Iterable[str]) -> dict | None:
    """One symbol's earnings tag, or None. ``upcoming`` is the calendar's next report ({date, status}); ``held`` the
    expiries of his open options on the symbol."""
    if not upcoming or not upcoming.get("date"):
        return None
    when = date.fromisoformat(upcoming["date"])
    days = trading_days_until(today, when, closed)
    if days is None:
        return None
    through = sorted({e for e in held if e >= when})
    if not through and days > WINDOW:
        return None
    estimated = upcoming.get("status") == "estimated"
    return {"symbol": symbol, "date": when.isoformat(), "status": upcoming.get("status"), "trading_days": days,
            "label": label(when, today, estimated), "tone": "amber" if through else "grey",
            "through": [e.isoformat() for e in through]}


def label(when: date, today: date, estimated: bool = False) -> str:
    """"ER today", "ER Thu" within the coming week, else "ER 11/24"; an estimated date ends with "?"."""
    gap = (when - today).days
    said = "today" if gap == 0 else f"{when:%a}" if gap < 7 else f"{when.month}/{when.day}"
    return f"ER {said}{'?' if estimated else ''}"


def _earnings(symbols: list[str], today: date) -> dict[str, dict]:
    from app.engine.symbol_info_tradier import symbol_events
    return symbol_events.chart_earnings(symbols, [], today)


def tags(symbols: Iterable[str], held: dict[str, list[date]], today: date, hidden: set[str],
         read: Callable[[list[str], date], dict[str, dict]] | None = None) -> dict:
    """Earnings tags for the book's and the Watching list's symbols: one cache read for all of them. A hidden (not
    followed) ticker and a fund have none. ``loading`` says some symbol's calendar is still on its way (read again)."""
    wanted = [s for s in dict.fromkeys(s.strip().upper() for s in symbols if s and s.strip())
              if s not in hidden and s not in NO_EARNINGS][:MAX_SYMBOLS]
    base = {"today": today.isoformat(), "window": WINDOW, "note": TIME_NOTE, "rows": {}, "loading": False}
    if not wanted:
        return {**base, "state": "ok"}
    try:
        blocks = (read or _earnings)(wanted, today)
    except Exception:  # noqa: BLE001 -- the tags are extra; never a guessed one
        log.warning("desk events: the earnings cache could not be read", exc_info=True)
        return {**base, "state": "unavailable"}
    closed = _macro().get("market_closed", [])
    rows = {}
    for symbol in wanted:
        found = tag(symbol, (blocks.get(symbol) or {}).get("next"), today, held.get(symbol, []), closed)
        if found:
            rows[symbol] = found
    loading = any((blocks.get(s) or {}).get("state") == "loading" for s in wanted)
    return {**base, "state": "ok", "rows": rows, "loading": loading}


def parse_held(text: str) -> dict[str, list[date]]:
    """``AAPL:2026-11-21,TSLA:2026-11-28`` → expiries by symbol; a malformed pair is skipped."""
    out: dict[str, list[date]] = {}
    for pair in (text or "").split(","):
        symbol, _, day = pair.partition(":")
        try:
            expiry = date.fromisoformat(day.strip())
        except ValueError:
            continue
        out.setdefault(symbol.strip().upper(), []).append(expiry)
    return out


# ------------------------------------------------------------------ the chart


def implied_move(symbol: str, report: date, spot: float | None, now: datetime) -> dict | None:
    """The at-the-money straddle of the first expiry after ``report`` (``options_implied``), from option chains already
    in memory for today only: never a provider read. None when it is not cached or not readable."""
    if spot is None:
        return None
    try:
        from app.engine.options_feed import options_feed
        from app.engine.options_implied import straddle, targets
        from app.engine.options_positioning import primary_root
        listed = options_feed._list(symbol)
        if not listed:
            return None
        root = primary_root(symbol)
        expiry = targets(listed, root, now, report)["earnings"]
        read = options_feed._chain(symbol, expiry, now.date()) if expiry else None
        if read is None:
            return None
        move = straddle(read.value, spot, root)
    except Exception:  # noqa: BLE001 -- the tooltip goes without it
        log.warning("desk events: no implied move for %s", symbol, exc_info=True)
        return None
    if move.get("state") != "ready":
        return None
    return {"expiration": expiry.isoformat(), "move": move.get("move"), "percent": move.get("percent")}


def chart(symbol: str | None, today: date, now: datetime, first_day: date | None, spot: float | None,
          read: Callable[[list[str], date], dict[str, dict]] | None = None) -> dict:
    """The chart's events for ``symbol``: its next and most recent earnings (with the implied move into the next one when
    cached), and on SPY, QQQ and IWM the macro days from ``first_day`` (the first candle's) to three weeks ahead."""
    out: dict = {"earnings": None, "macro": [], "note": TIME_NOTE}
    if not symbol:
        return out
    if symbol in INDEX_ETFS:
        end = today + timedelta(days=MACRO_AHEAD_DAYS)
        start = first_day or today
        out["macro"] = [{"date": e["date"], "time": e["time"], "kind": e["kind"], "name": e["name"]}
                        for e in _macro().get("events", []) if start.isoformat() <= e["date"] <= end.isoformat()]
    if symbol in NO_EARNINGS:
        return out
    try:
        block = (read or _earnings)([symbol], today).get(symbol) or {}
    except Exception:  # noqa: BLE001
        log.warning("desk events: the earnings cache could not be read for %s", symbol, exc_info=True)
        return out
    upcoming = block.get("next")
    last = (block.get("reports") or [None])[0]
    if not upcoming and not last:
        return out
    nxt = None
    if upcoming and upcoming.get("date"):
        when = date.fromisoformat(upcoming["date"])
        nxt = {"date": upcoming["date"], "status": upcoming.get("status"), "label": upcoming.get("label"),
               "implied": implied_move(symbol, when, spot, now)}
    out["earnings"] = {"next": nxt, "last": {"date": last["date"], "label": last.get("label")} if last else None}
    return out
