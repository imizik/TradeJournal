"""The desk's live prices (``GET /copilot/desk/ticks``, docs/copilot-lab.md § Live prices): each named underlying's last
price and change today, and a held option contract's mark, every few seconds in the regular session.

- **Regular session only.** Outside it the read makes no provider call and answers ``closed`` with the next open
  today (``opens_at``), so the desk waits instead of polling.
- **One batched call.** Every symbol any open desk asked for in the last ``WANTED_SECONDS`` goes into one Tradier quote
  read through the chart feed (its single-flight, its four places, low priority so a screen's read goes first), so
  several tabs and the phone share it. A read is kept ``TICK_SECONDS``; one already in flight is waited on, not repeated.
- **Within the feed's budget.** When the chart feed has made ``BUDGET_HEADROOM`` of its 60 calls in the last minute the
  ticks stop asking until it drops, so a chart or the copilot never runs out because of them.
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

_TICKER = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")
_OCC = re.compile(r"^[A-Z]{1,6}\d{6}[CP]\d{8}$")

_lock = threading.Lock()
_kept: dict[str, tuple[float, dict]] = {}  # symbol -> (read at, row)
_wanted: dict[str, float] = {}  # symbol -> last asked at
_flight: threading.Event | None = None
_issue: tuple[float, str] | None = None  # the newest failed read: (when, what)


def clear() -> None:
    global _flight, _issue
    with _lock:
        _kept.clear()
        _wanted.clear()
        _flight = None
        _issue = None


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
        for symbol, row in found.items():
            _kept[symbol] = (now, row)


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
        rows = {s: dict(_kept[s][1]) for s in asked if s in _kept}
        failed = _issue is not None and now - _issue[0] < TICK_SECONDS
        fresh = any(now - _kept[s][0] < TICK_SECONDS for s in asked if s in _kept)
        if len(_kept) > 512:
            for symbol in [s for s in _kept if s not in _wanted]:
                del _kept[symbol]
    state = "unavailable" if failed and not fresh else "ok"
    return {"state": state, "as_of": as_of, "rows": rows, "closes_at": regular[1], "poll_seconds": POLL_SECONDS}
