"""The desk's live prices (``GET /copilot/desk/ticks``, docs/copilot-lab.md § Live prices): each named underlying's last
price and change today, and a held option contract's mark, every few seconds in the regular session.

- **Regular session only.** Outside it the read makes no provider call and answers ``closed`` with the next open
  today (``opens_at``), so the desk waits instead of polling.
- **One batched call.** Every symbol any open desk asked for in the last ``WANTED_SECONDS`` goes into one Tradier quote
  read through the chart feed (its single-flight, its four places, low priority so a screen's read goes first), so
  several tabs and the phone share it. A read is kept ``TICK_SECONDS``; one already in flight is waited on, not repeated.
- **Within the feed's budget.** When the chart feed has made ``BUDGET_HEADROOM`` of its 60 calls in the last minute the
  ticks stop asking until it drops, so a chart or the copilot never runs out because of them.
- **Marks remembered for the contract chart.** Each held contract's mark is kept once a minute for today, in memory
  (``marks``), so the desk's Contract view can draw where its trades are sparse. No extra call: it is the read above.
- **Never a made-up price.** A failed read answers ``unavailable``; a symbol with no positive price is left out, never a
  zero. Each row carries the time it was read (``at``), so the desk can grey a price that is no longer live.

Display only: nothing is written, and Robinhood is never read here.
"""

from __future__ import annotations

import logging
import re
import threading
from datetime import UTC, datetime

log = logging.getLogger(__name__)

TICK_SECONDS = 4  # one read serves every desk for this long; the desk asks every POLL_SECONDS
POLL_SECONDS = 5
WANTED_SECONDS = 30  # a symbol a desk asked for this recently rides every read
MAX_NAMES = 60  # one request: the book, the Watching list, the chart's symbol and the held contracts
MAX_BATCH = 100  # one provider call
BUDGET_HEADROOM = 45  # of the chart feed's 60 calls a minute
FLIGHT_WAIT = 3.0  # a request joining a read in flight waits at most this, then answers from what is kept
MARK_CONTRACTS = 64  # contracts whose marks are remembered for today

_TICKER = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")
_OCC = re.compile(r"^[A-Z]{1,6}\d{6}[CP]\d{8}$")

_lock = threading.Lock()
_kept: dict[str, tuple[float, dict | None]] = {}  # symbol -> (read at, row; None: the read had no price for it)
_wanted: dict[str, float] = {}  # symbol -> last asked at
_flight: threading.Event | None = None
_issue: tuple[float, str] | None = None  # the newest failed read: (when, what)
_marks: dict[str, tuple[str, dict[int, float]]] = {}  # OCC symbol -> (New York date, minute start -> mark)


def clear() -> None:
    global _flight, _issue
    with _lock:
        _kept.clear()
        _wanted.clear()
        _marks.clear()
        _flight = None
        _issue = None


def health() -> dict:
    """For the desk's data health, no I/O: ``good`` (when the newest quote read came back), ``failed`` (when the newest
    read failed), ``asked`` (when a desk last asked for a price) and ``reading`` (a read is in flight)."""
    with _lock:
        return {"good": max((at for at, _row in _kept.values()), default=None), "failed": _issue[0] if _issue else None,
                "asked": max(_wanted.values(), default=None), "reading": _flight is not None}


def names(symbols: str) -> list[str]:
    """The asked symbols, upper-cased, de-duplicated in order: stock tickers and OCC option symbols only."""
    out: list[str] = []
    for raw in symbols.split(","):
        name = raw.strip().upper()
        if name and name not in out and (_TICKER.match(name) or _OCC.match(name)):
            out.append(name)
    return out[:MAX_NAMES]


def _row(quote: dict, at: float) -> dict | None:
    """A quote as a tick: an option's mark is its bid/ask midpoint, else its last trade (as the book's marks are)."""
    last = quote.get("last")
    option = bool(_OCC.match(str(quote.get("symbol") or "")))
    if option:
        from app.engine.quotes import _calc_mid
        bid, ask = quote.get("bid"), quote.get("ask")
        mid = _calc_mid(bid, ask) if bid is not None and ask is not None and ask >= bid >= 0 else None
        price = mid if mid is not None else last
    else:
        price = last
    if price is None or price <= 0:
        return None  # never a zero for "no price"
    change = quote.get("change_percentage")
    return {"last": round(float(price), 4), "change_pct": None if option or change is None else round(float(change), 2),
            "prev_close": None if option else quote.get("previous_close"), "at": int(at)}


def _read(batch: list[str], now: float) -> None:
    """One batched read for ``batch``; stores each row it returns. Raises when the read fails."""
    from app.engine.chart_feed import chart_feed
    from app.engine.request_timing import timed
    if chart_feed.calls_last_minute() >= BUDGET_HEADROOM:
        raise RuntimeError("the chart feed's minute budget is nearly spent")
    with timed("ticks quotes"):
        rows, _stamp, issue = chart_feed.quote_rows(batch, ttl=TICK_SECONDS, keep=False, low=True)
    if issue:
        raise RuntimeError(issue)
    found = {}
    for quote in rows:
        row = _row(quote, now)
        if row is not None:
            found[str(quote.get("symbol"))] = row
    with _lock:
        for symbol in batch:
            # "No price" is kept as long as a price: an unpriced contract never makes each tab's poll its own call.
            _kept[symbol] = (now, found.get(symbol))
        for symbol, row in found.items():
            if _OCC.match(symbol):
                _remember(symbol, row["last"], now)


def _remember(occ: str, mark: float, now: float) -> None:
    """The minute's newest mark for ``occ`` (today only; the oldest contract is let go past ``MARK_CONTRACTS``). Under
    ``_lock``."""
    from app.engine.chart_math import ET
    day = datetime.fromtimestamp(now, ET).date().isoformat()
    kept = _marks.get(occ)
    if kept is None or kept[0] != day:
        _marks.pop(occ, None)
        while len(_marks) >= MARK_CONTRACTS:
            _marks.pop(next(iter(_marks)))
        kept = _marks[occ] = (day, {})
    kept[1][int(now) - int(now) % 60] = mark


def marks(occ: str, now: float) -> list[tuple[int, float]]:
    """Today's remembered marks for ``occ``, one per minute, oldest first (empty when no desk quoted it today)."""
    from app.engine.chart_math import ET
    day = datetime.fromtimestamp(now, ET).date().isoformat()
    with _lock:
        kept = _marks.get(occ)
        return sorted(kept[1].items()) if kept and kept[0] == day else []


def kept_rows(symbols: list[str]) -> dict[str, dict]:
    """The newest price kept for each of ``symbols`` (a row with its ``at``), from earlier reads only: no I/O and no
    provider call. A symbol no desk has asked for, or with no price, is left out."""
    with _lock:
        return {s: dict(_kept[s][1]) for s in symbols if s in _kept and _kept[s][1] is not None}


def _session(now: float):
    from app.engine import desk_sparks
    _day, phase, _hours, regular = desk_sparks._session(now)
    return phase, regular


def read(symbols: str, now: float) -> dict:
    global _flight, _issue
    asked = names(symbols)
    as_of = datetime.fromtimestamp(now, UTC).isoformat()
    phase, regular = _session(now)
    if phase != "regular" or regular is None:
        opens = regular[0] if regular and now < regular[0] else None
        return {"state": "closed", "as_of": as_of, "rows": {}, "opens_at": opens, "poll_seconds": None}
    mine: threading.Event | None = None
    with _lock:
        for symbol in asked:
            _wanted[symbol] = now
        for symbol in [s for s, at in _wanted.items() if now - at > WANTED_SECONDS]:
            del _wanted[symbol]
        stale = [s for s in asked if s not in _kept or now - _kept[s][0] >= TICK_SECONDS]
        waiting = _flight
        if stale and waiting is None:
            others = sorted(s for s in _wanted if s not in asked)
            batch = (asked + others)[:MAX_BATCH]
            _flight = mine = threading.Event()
    if mine is not None:
        try:
            _read(batch, now)
            with _lock:
                _issue = None
        except Exception as exc:  # noqa: BLE001 -- the desk shows the price it has, greyed with its time
            log.warning("desk ticks unavailable: %s", type(exc).__name__)
            with _lock:
                _issue = (now, str(exc)[:200])
        finally:
            with _lock:
                _flight = None
            mine.set()
    elif stale and waiting is not None:
        waiting.wait(FLIGHT_WAIT)
    with _lock:
        rows = {s: dict(_kept[s][1]) for s in asked if s in _kept and _kept[s][1] is not None}
        failed = _issue is not None and now - _issue[0] < TICK_SECONDS
        fresh = any(now - _kept[s][0] < TICK_SECONDS for s in asked if s in _kept and _kept[s][1] is not None)
        if len(_kept) > 512:
            for symbol in [s for s in _kept if s not in _wanted]:
                del _kept[symbol]
    state = "unavailable" if failed and not fresh else "ok"
    return {"state": state, "as_of": as_of, "rows": rows, "closes_at": regular[1], "poll_seconds": POLL_SECONDS}
