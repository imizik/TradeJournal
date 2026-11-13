"""The desk's Grid (``GET /copilot/desk/grid``): small intraday charts of up to nine names, read in one request.

Each tile is the session's 1-minute or 5-minute candles (pre-market to now, extended candles flagged) after the last
``TAIL_MINUTES`` of the previous regular session, with today's RTH VWAP per candle and the symbol's armed plan and alert
levels. The desk's shared ticker moves each tile's last candle between reads; this read runs at most once a minute.

Today's minutes come from the cheapest source that has them, in this order:

1. **This module's own minute cache** (``KEEP_SECONDS``): a second tab, a timeframe switch (both timeframes are built
   from the same minutes) or a quick re-read costs nothing.
2. **The chart feed's cache**: minutes a chart (the desk's Chart tab, Charts, a ping picture, the sparklines' fallback)
   read in the last ``CHART_CACHE_SECONDS``.
3. **One batched Alpaca read** for every name left (SIP, like the charts and the sparklines). A refusal or failure turns
   it off for ten minutes.
4. **The chart feed's own low-priority read** for each name still missing (at most two at once, behind any screen's
   read), and only while the feed has made fewer than ``TRADIER_HEADROOM`` of its 60 calls in the last minute; the same
   cached request the Chart tab makes, so it serves both.

The previous session's tail is read from disk (stored sessions), else rides the batched Alpaca read; it never gets a
Tradier read of its own. A completed session's minutes never change, so they are kept for the process.

A tile still unread when the budget ends is ``pending`` and its read carries on in the background. A ticker set to Not
following is never read (the route drops it). Display only: nothing is written, and Robinhood is never read here.
"""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor, wait
from datetime import UTC, date, datetime, time as wall_time, timedelta
import logging
import re
import threading
import time

from app.engine.chart_math import ET, chart_bars, normalize_bars, session_windows

log = logging.getLogger(__name__)

SLOTS = 9
TIMEFRAMES = {"1m": 60, "5m": 300}
TAIL_MINUTES = 30  # the previous regular session's last minutes, before today's first candle
KEEP_SECONDS = 55  # a symbol's minutes, kept for the grid's once-a-minute read
CHART_CACHE_SECONDS = 60  # the oldest chart-feed minutes the grid takes as now
BUDGET_SECONDS = 6.0
TRADIER_HEADROOM = 30  # of the chart feed's 60 calls a minute: above this the grid asks Tradier for nothing
ALPACA_BACKOFF_SECONDS = 600
ALPACA_PAGES = 3
TAIL_RETRY_SECONDS = 600  # a previous session's tail no source had is asked again after this long
STALE_SECONDS = 150  # a live tile's minutes older than this (its re-read failed or waited) are marked stale

_TICKER = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")

_lock = threading.Lock()
_minutes: dict[str, tuple[float, date, list[dict], str]] = {}  # symbol -> (read at, its day, raw minutes, source)
_tails: dict[tuple[str, date], list[dict]] = {}  # (symbol, the session's date) -> its raw minutes; a completed session
_alpaca_off_until = 0.0
_tail_tried: dict[tuple[str, date], float] = {}  # (symbol, the session's date) -> when a read last looked for its tail
_filling: set[str] = set()  # symbols a background read is filling now: a second request does not start another


def clear() -> None:
    global _alpaca_off_until
    with _lock:
        _minutes.clear()
        _tails.clear()
        _tail_tried.clear()
        _filling.clear()
        _alpaca_off_until = 0.0


def names(symbols: str, hidden: set[str] = frozenset()) -> list[str]:
    """The asked tickers, upper-cased, in order, de-duplicated, never a hidden one, at most ``SLOTS``."""
    out: list[str] = []
    for raw in symbols.split(","):
        name = raw.strip().upper()
        if name and name not in out and name not in hidden and _TICKER.match(name):
            out.append(name)
    return out[:SLOTS]


# ------------------------------------------------------------------ which day, and the session before it


def _hours(day: date) -> dict | None:
    from app.engine.chart_calendar import chart_calendar
    try:
        return chart_calendar.hours(day)
    except Exception:  # noqa: BLE001 -- an unreachable calendar reads clock hours, as the sparklines do
        return None


def _trading(day: date, hours: dict | None) -> bool:
    return day.weekday() < 5 and (hours is None or hours.get("status") == "open")


def _session_before(day: date) -> tuple[date, dict | None]:
    back = day
    for _ in range(10):
        back -= timedelta(days=1)
        hours = _hours(back) if back.weekday() < 5 else None
        if _trading(back, hours):
            return back, hours
    return back, None


def shown_day(now: float) -> tuple[date, dict | None, bool]:
    """(the session the tiles show, its hours, whether its minutes can still change). Today from 04:00 on a trading day;
    before that, on a weekend or a holiday, the last session."""
    local = datetime.fromtimestamp(now, ET)
    today = local.date()
    hours = _hours(today) if today.weekday() < 5 else None
    if _trading(today, hours) and local >= datetime.combine(today, wall_time(4), ET):
        ends = [end for _n, _s, end in session_windows(today, hours)]
        live = bool(ends) and local.hour * 60 + local.minute < max(ends) + 2
        return today, hours, live
    day, hours = _session_before(today)
    return day, hours, False


def _regular(day: date, hours: dict | None) -> tuple[int, int] | None:
    window = next((w for w in session_windows(day, hours) if w[0] == "regular"), None)
    if window is None:
        return None
    at = lambda m: int(datetime.combine(day, wall_time(m // 60, m % 60), ET).timestamp())  # noqa: E731
    return at(window[1]), at(window[2])


# ------------------------------------------------------------------ the sources


def _kept(symbol: str, day: date, hours: dict | None, live: bool) -> list[dict] | None:
    with _lock:
        found = _minutes.get(symbol)
    if found is None or found[1] != day:
        return None
    if live:
        return found[2] if time.time() - found[0] <= KEEP_SECONDS else None
    # A finished day: only minutes read after it ended are the whole day (one read at 15:00 stops short).
    return found[2] if found[0] >= _day_end(day, hours) else None


def _day_end(day: date, hours: dict | None) -> float:
    """When the day's last window (after hours) ends: 20:00, or earlier after an early close."""
    ends = [end for _n, _s, end in session_windows(day, hours)]
    minute = max(ends) if ends else 20 * 60
    return datetime.combine(day, wall_time(minute // 60, minute % 60), ET).timestamp()


def _keep(symbol: str, day: date, minutes: list[dict], source: str) -> None:
    with _lock:
        _minutes[symbol] = (time.time(), day, minutes, source)
        while len(_minutes) > 64:
            _minutes.pop(next(iter(_minutes)))


def _chart_cache(symbol: str, day: date, hours: dict | None, live: bool) -> list[dict] | None:
    """Minutes a chart read: for a live day only when at most ``CHART_CACHE_SECONDS`` old; for a finished day only when
    read after it ended (an earlier read stops short)."""
    from app.engine.chart_feed import chart_feed
    held = chart_feed.peek_minutes(symbol, day)
    if held is None:
        return None
    minutes, read_at = held
    if live:
        return minutes if time.time() - read_at <= CHART_CACHE_SECONDS else None
    return minutes if read_at >= _day_end(day, hours) else None


def _alpaca(symbols: list[str], start: datetime, end: datetime) -> dict[str, list[dict]] | None:
    """Every symbol's minutes between ``start`` and ``end`` in one Alpaca read (SIP, split-adjusted), as raw minutes.
    None when Alpaca is not set up, is backing off, refuses or fails (which starts the back-off)."""
    global _alpaca_off_until
    from app.engine import alpaca
    if not symbols or not alpaca.alpaca_configured() or time.time() < _alpaca_off_until or end <= start:
        return None
    params = {"symbols": ",".join(symbols), "timeframe": "1Min", "start": start.isoformat(),
              "end": end.astimezone(UTC).isoformat(), "adjustment": "split", "feed": "sip", "limit": 10000}
    rows: dict[str, list[dict]] = {}
    try:
        for _ in range(ALPACA_PAGES):
            page = alpaca._alpaca_get_fast("/v2/stocks/bars", params)
            if not page:
                raise RuntimeError("Alpaca refused the read")
            for symbol, found in (page.get("bars") or {}).items():
                rows.setdefault(symbol, []).extend(found)
            if not page.get("next_page_token"):
                break
            params = {**params, "page_token": page["next_page_token"]}
        else:
            raise RuntimeError("more minutes than the pages read")
    except Exception as exc:  # noqa: BLE001 -- the symbols fall to the chart feed
        _alpaca_off_until = time.time() + ALPACA_BACKOFF_SECONDS
        log.warning("desk grid: the batched Alpaca read is off for %d s (%s)", ALPACA_BACKOFF_SECONDS, exc)
        return None
    out: dict[str, list[dict]] = {}
    for symbol in symbols:
        raw = []
        for r in rows.get(symbol, []):
            try:
                stamp = int(datetime.fromisoformat(str(r["t"]).replace("Z", "+00:00")).timestamp())
                raw.append({"timestamp": stamp, "open": r["o"], "high": r["h"], "low": r["l"], "close": r["c"], "volume": r["v"]})
            except (KeyError, TypeError, ValueError):
                continue
        out[symbol] = normalize_bars(raw, source="alpaca")
    return out


def _tradier(symbol: str, day: date, now: float, live: bool) -> list[dict] | None:
    """The chart feed's low-priority read of the day's minutes (the Chart tab's own request), or None: over the headroom,
    failed, or only stale minutes for a live day."""
    from app.engine.chart_feed import ChartFeedError, chart_feed
    if chart_feed.calls_last_minute() >= TRADIER_HEADROOM:
        return None
    try:
        if live:
            return chart_feed.today_minutes(symbol, now, max_age=CHART_CACHE_SECONDS)
        from app.engine.chart_feed import _rows
        data, _at, issue = chart_feed.read("/v1/markets/timesales", chart_feed._minutes_params(symbol, day), 3600, low=True)
        return None if issue else normalize_bars(_rows(data, "series", "data"))
    except ChartFeedError:
        return None
    except Exception:  # noqa: BLE001 -- one symbol's failed read leaves its tile pending
        log.warning("desk grid: %s minutes failed", symbol, exc_info=True)
        return None


def _stored_tail(symbol: str, before: date) -> list[dict] | None:
    from app.engine import desk_context
    try:
        sessions = desk_context.stored_sessions(symbol, before, 1)
    except Exception:  # noqa: BLE001 -- the tail is extra
        return None
    return sessions[0][2] if sessions else None


def _tail_window(prior: date, hours: dict | None) -> tuple[int, int] | None:
    regular = _regular(prior, hours)
    return (regular[1] - TAIL_MINUTES * 60, regular[1]) if regular else None


def _fill(todo: list[str], tails: list[str], day: date, prior: tuple[date, dict | None], now: float, live: bool,
          abandon: threading.Event) -> None:
    """Reads what nothing in hand served: one batched Alpaca read (today's minutes and the missing tails), then the
    chart feed for today's minutes still missing. Stores each as it lands."""
    prior_day, prior_hours = prior
    window = _tail_window(prior_day, prior_hours)
    want = sorted({*todo, *tails})
    try:
        if want:
            start = (datetime.fromtimestamp(window[0], ET) if tails and window
                     else datetime.combine(day, wall_time(4), ET))
            end = datetime.fromtimestamp(now, ET) if live else datetime.combine(day, wall_time(20), ET)
            got = _alpaca(want, start, end) or {}
            for symbol, minutes in got.items():
                if symbol in tails and window:
                    tail = [m for m in minutes if window[0] <= m["time"] < window[1]]
                    if tail:
                        with _lock:
                            _tails[(symbol, prior_day)] = tail
                if symbol in todo:
                    on_day = [m for m in minutes if datetime.fromtimestamp(m["time"], ET).date() == day]
                    if on_day:  # none: the chart feed may have them (and an empty answer is never kept as the day)
                        _keep(symbol, day, on_day, "alpaca")
                        todo = [s for s in todo if s != symbol]

        def one(symbol: str) -> None:
            if abandon.is_set():  # the request gave up: do not start a read nobody waits for
                return
            minutes = _tradier(symbol, day, now, live)
            if minutes is not None:
                _keep(symbol, day, [m for m in minutes if datetime.fromtimestamp(m["time"], ET).date() == day], "tradier")

        from app.engine.chart_feed import LOW_SLOTS
        if todo:
            with ThreadPoolExecutor(max_workers=LOW_SLOTS) as pool:
                list(pool.map(one, todo))
    except Exception:  # noqa: BLE001 -- nobody may be waiting on this
        log.warning("desk grid: filling the tiles failed", exc_info=True)
    finally:
        with _lock:
            _filling.difference_update(want)


# ------------------------------------------------------------------ building a tile


def tile(symbol: str, minutes: list[dict], tail: list[dict], timeframe: str, day: date, hours: dict | None,
         prior: tuple[date, dict | None], now: float) -> list[dict]:
    """The tile's candles: the previous session's tail, then the day's candles up to ``now`` (extended ones flagged),
    each with today's RTH VWAP (None outside the regular session and on the tail)."""
    calendar = {day: hours, prior[0]: prior[1]}
    shown = []
    for bar in chart_bars(tail, [], timeframe, "regular", calendar):
        shown.append({**_plain(bar), "vwap": None, "prior": True})
    for bar in chart_bars([m for m in minutes if m["time"] <= now], [], timeframe, "extended", calendar):
        if datetime.fromtimestamp(bar["time"], ET).date() != day:
            continue
        vwap = bar.get("vwap")
        shown.append({**_plain(bar), "vwap": None if vwap is None else round(float(vwap), 4), "prior": False})
    return shown


def _plain(bar: dict) -> dict:
    return {"time": int(bar["time"]), "open": round(float(bar["open"]), 4), "high": round(float(bar["high"]), 4),
            "low": round(float(bar["low"]), 4), "close": round(float(bar["close"]), 4),
            "volume": float(bar.get("volume") or 0), "extended": bool(bar.get("extended"))}


def _change(symbol: str, day: date, now: float) -> float | None:
    """The day's change the sparklines already hold for the symbol (no read of its own); None when they hold none."""
    from app.engine import desk_sparks
    with desk_sparks._lock:
        found = desk_sparks._changes.get(symbol)
    return found[2] if desk_sparks._fresh(found, now, day) else None


def read(symbols: list[str], timeframe: str, now: float, levels: dict[str, list[dict]] | None = None,
         budget: float = BUDGET_SECONDS) -> dict:
    """Up to nine tiles in one answer: {symbol: {state ok|pending|unavailable, bars, last, change_pct, levels}}, with the
    session shown, the timeframe's ``step`` and ``live`` (bars can still change: the desk reads again in a minute)."""
    from app.engine.request_timing import timed
    from app.routers import today as today_router
    step = TIMEFRAMES.get(timeframe)
    if step is None:
        timeframe, step = "1m", 60
    day, hours, live = shown_day(now)
    prior = _session_before(day)
    window = _tail_window(*prior)
    base = {"as_of": int(now), "day": day.isoformat(), "timeframe": timeframe, "step": step, "live": live, "rows": {}}
    if not symbols:
        return base
    with timed("grid cache"):
        todo: list[str] = []
        for symbol in symbols:
            if _kept(symbol, day, hours, live) is not None:
                continue
            found = _chart_cache(symbol, day, hours, live)
            if found is not None:
                _keep(symbol, day, [m for m in found if datetime.fromtimestamp(m["time"], ET).date() == day], "chart")
            else:
                todo.append(symbol)
        tails: list[str] = []
        for symbol in symbols:
            with _lock:
                held = (symbol, prior[0]) in _tails
                tried = _tail_tried.get((symbol, prior[0]), 0.0)
            if held or window is None or time.time() - tried < TAIL_RETRY_SECONDS:
                continue
            stored = _stored_tail(symbol, day)
            if stored and datetime.fromtimestamp(stored[0]["time"], ET).date() == prior[0]:
                with _lock:
                    _tails[(symbol, prior[0])] = [m for m in stored if window[0] <= m["time"] < window[1]]
            else:
                tails.append(symbol)
    with _lock:
        todo = [s for s in todo if s not in _filling]
        tails = [s for s in tails if s not in _filling]
        for symbol in tails:  # one look per ``TAIL_RETRY_SECONDS``, found or not
            _tail_tried[(symbol, prior[0])] = time.time()
        _filling.update({*todo, *tails})
    if todo or tails:
        abandon = threading.Event()
        job: Future = today_router._start(lambda: _fill(todo, tails, day, prior, now, live, abandon))
        with timed("grid bars"):
            done, _late = wait([job], timeout=budget)
        if not done:
            abandon.set()
    rows: dict[str, dict] = {}
    for symbol in symbols:
        with _lock:
            found = _minutes.get(symbol)
            tail = _tails.get((symbol, prior[0]), [])
        minutes = found[2] if found is not None and found[1] == day else None
        if minutes is None:
            with _lock:
                pending = symbol in _filling
            rows[symbol] = {"state": "pending" if pending else "unavailable", "bars": [], "last": None,
                            "change_pct": None, "levels": (levels or {}).get(symbol, []), "source": None, "read_at": None,
                            "stale": False}
            continue
        bars = tile(symbol, minutes, tail, timeframe, day, hours, prior, now)
        today_bars = [b for b in bars if not b["prior"]]
        # Shown, but marked with their time, never as now: minutes older than a refresh or two while the day is live,
        # and, on a finished day, minutes read before it ended (the read after it failed or waited).
        stale = (time.time() - found[0] > STALE_SECONDS) if live else found[0] < _day_end(day, hours)
        rows[symbol] = {"state": "ok" if today_bars else "unavailable", "bars": bars, "read_at": int(found[0]), "stale": stale,
                        "last": today_bars[-1]["close"] if today_bars else None,
                        "change_pct": _change(symbol, day, now) if day == datetime.fromtimestamp(now, ET).date() else None,
                        "levels": (levels or {}).get(symbol, []), "source": found[3]}
    with _lock:
        while len(_tails) > 256:
            _tails.pop(next(iter(_tails)))
        while len(_tail_tried) > 256:
            _tail_tried.pop(next(iter(_tail_tried)))
    return {**base, "rows": rows}


def plan_levels(db, symbols: list[str]) -> dict[str, list[dict]]:
    """Each symbol's armed level alerts as thin lines: a plan's entry and invalidation by their role, any other as an
    alert. One query."""
    from sqlmodel import col, select
    from app.models import LevelAlert
    if not symbols:
        return {}
    out: dict[str, list[dict]] = {}
    for alert in db.exec(select(LevelAlert).where(col(LevelAlert.symbol).in_(symbols), LevelAlert.state == "active")
                         .order_by(LevelAlert.price)).all():
        role = alert.plan_role if alert.plan_role in ("entry", "invalidation") else "alert"
        out.setdefault(alert.symbol, []).append({"price": float(alert.price), "role": role, "label": alert.label or None})
    return out
