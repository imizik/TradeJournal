"""The desk's book sparklines (``GET /copilot/desk/sparks``): each symbol's day so far, thinned, with its change today.

A line is built from the cheapest source that has today's minutes, in this order:

1. **Radar's recorder** (the regular session only): the last price it wrote for the symbol each minute, read from its
   file with no provider call, together with the previous close it recorded, which is the change's base.
2. **The chart feed's cache**: the minute bars of a chart drawn in the last two minutes (``chart_feed.peek_minutes``).
3. **One batched Alpaca read** for what is left (two or more symbols), on the SIP feed like the charts; a refusal or
   failure turns it off for ten minutes and the symbols fall to 4.
4. **One Tradier read per symbol, low priority** (``chart_feed.today_minutes``): at most two at once, so the reads the
   screen is waiting on keep two of the feed's four places.

The Watching list's symbols (``watch``) come in the same read: their last price and change from the same quote read (or
the recorder), and a line only from sources 1 to 3. They never get a read of their own (4), so watching a name costs no
provider call per symbol; a watched name none of those has today shows its price and change without a line.

A symbol that is still unread when the budget ends is left out and the read carries on in the background, so the next
refresh finds it. A line is kept for a minute (five after the close, while after-hours minutes still come in), and,
once the extended session is over or on a day with no session, until the next 04:00 New York or midnight, whichever is
first: a line never outlives its own New York date. A symbol whose changes are unknown has none: the lines stand
without them.
"""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor, wait
from datetime import UTC, date, datetime, time as wall_time, timedelta
import logging
import math
import os
import threading
import time

from app.engine.chart_math import ET, session_windows

log = logging.getLogger(__name__)

POINTS = 48  # a book row's sparkline: today's minutes, thinned to this many closes
SYMBOLS = 12
WATCH = 30  # the Watching list's limit (desk_watch.MAX)
BUDGET_SECONDS = 6.0
LINE_SECONDS = 60  # a line, in the session
AFTER_CLOSE_SECONDS = 300  # after the regular close, until the extended session ends
RADAR_STALE_SECONDS = 180  # the recorder's newest pass must be this recent: it writes one a minute
RADAR_OPEN_SECONDS = 300  # and the first must be within this of the open, or the line would start mid-day
RADAR_GAP_SECONDS = 900  # no gap between two passes longer than this
RADAR_READ_SECONDS = 1.5  # the Radar file is a rollback-journal file the recorder writes: never wait long on it
CHART_CACHE_SECONDS = 120  # the oldest cached chart minutes a line is drawn from
SIP_BACKOFF_SECONDS = 600
SIP_PAGES = 3

_lock = threading.Lock()
_lines: dict[str, tuple[float, date, list[float]]] = {}  # symbol -> (valid until, its New York date, thinned closes)
_changes: dict[str, tuple[float, date, float | None, float | None]] = {}  # (valid until, date, change %, last price)
_sip_off_until = 0.0
_sip_watch_off_until = 0.0  # the Watching names' own batched read: its failure never turns the book's off


def clear() -> None:
    global _sip_off_until, _sip_watch_off_until
    with _lock:
        _lines.clear()
        _changes.clear()
        _sip_off_until = 0.0
        _sip_watch_off_until = 0.0


# ------------------------------------------------------------------ the session and what a line may be kept for


def _session(now: float) -> tuple[date, str, dict | None, tuple[int, int] | None]:
    """(New York date, phase: pre, regular, post or closed, that day's calendar hours, the regular session in epoch seconds)."""
    from app.engine.chart_calendar import chart_calendar
    local = datetime.fromtimestamp(now, ET)
    day = local.date()
    try:
        hours = chart_calendar.hours(day)
    except Exception:  # noqa: BLE001 -- an unreachable calendar reads the clock hours, as the recorder does
        hours = None
    minute = local.hour * 60 + local.minute
    windows = session_windows(day, hours)
    phase = next((name for name, start, end in windows if start <= minute < end), "closed")
    regular = next((w for w in windows if w[0] == "regular"), None)
    def at(m: int) -> int:
        return int(datetime.combine(day, wall_time(m // 60, m % 60), ET).timestamp())
    return day, phase, hours, (at(regular[1]), at(regular[2])) if regular else None


def _valid_until(now: float, phase: str, hours: dict | None = None) -> float:
    if phase in ("pre", "regular"):
        return now + LINE_SECONDS
    if phase == "post":
        return now + AFTER_CLOSE_SECONDS
    local = datetime.fromtimestamp(now, ET)
    # Just after the last window ends, what was read may stop short of its final minutes (a cached read up to two minutes
    # old): keep it as after the close does, and read once more before keeping it for the night.
    ends = [datetime.combine(local.date(), wall_time(m // 60, m % 60), ET) for _n, _s, m in session_windows(local.date(), hours)]
    if ends and ends[-1] <= local < ends[-1] + timedelta(seconds=CHART_CACHE_SECONDS + 60):
        return now + AFTER_CLOSE_SECONDS
    four = datetime.combine(local.date(), wall_time(4), ET)
    midnight = datetime.combine(local.date() + timedelta(days=1), wall_time(0), ET)
    return (four if local < four else midnight).timestamp()


def _fresh(entry, now: float, day: date) -> bool:
    return entry is not None and now < entry[0] and entry[1] == day


# ------------------------------------------------------------------ the sources


def _thin(shown: list[dict]) -> list[float]:
    step = max(1, -(-len(shown) // POINTS))
    points = [b["close"] for b in shown[::step]]
    if shown and (len(shown) - 1) % step:
        points.append(shown[-1]["close"])
    return points


def _bars(minutes: list[dict], day: date, hours: dict | None) -> list[dict]:
    """A provider's raw minutes as the desk's bars: time, close and whether the minute is outside the regular session."""
    from app.engine.chart_math import chart_bars
    return chart_bars(minutes, [], "1m", "extended", {day: hours})


def _radar(symbols: list[str], day: date, now: float, regular: tuple[int, int] | None) -> dict[str, dict]:
    """{symbol: {"bars", "change_pct"}} for the symbols the recorder covers today: at least two passes, the first near the
    open, none missing for long, the newest within ``RADAR_STALE_SECONDS``. Nothing but in the regular session."""
    from app.engine.radar_comparison import epoch
    from app.engine.radar_store import RadarStore
    from app.routers import radar
    path = os.environ.get("RADAR_STORE", "").strip()
    if not symbols or regular is None or not radar.enabled() or not path or not os.path.isabs(path):
        return {}
    try:
        store = RadarStore(path, read_only=True, read_deadline=time.monotonic() + RADAR_READ_SECONDS)
        series = store.session_series(day.isoformat(), symbols)
    except Exception:  # noqa: BLE001 -- the file is extra: the other sources serve the line
        log.warning("desk sparks: the Radar file could not be read", exc_info=True)
        return {}
    found: dict[str, dict] = {}
    for symbol, rows in series.items():
        try:
            kept = [r for r in rows if r["last"] is not None and math.isfinite(float(r["last"])) and float(r["last"]) > 0]
            marks = [(epoch(r["retrieved_at"]), float(r["last"])) for r in kept]
        except (TypeError, ValueError):
            continue
        if len(marks) < 2 or marks[-1][0] > now + 60 or now - marks[-1][0] > RADAR_STALE_SECONDS:
            continue
        if marks[0][0] > regular[0] + RADAR_OPEN_SECONDS:  # the recorder started late: not the day so far
            continue
        if any(b[0] - a[0] > RADAR_GAP_SECONDS for a, b in zip(marks, marks[1:])):
            continue
        previous = kept[-1]["prev_close"]
        change = round((marks[-1][1] - previous) / previous * 100, 2) if previous and previous > 0 else None
        found[symbol] = {"bars": [{"time": int(t), "close": c, "extended": False} for t, c in marks], "change_pct": change,
                         "last": marks[-1][1]}
    return found


def _chart_cache(symbol: str, day: date, hours: dict | None) -> list[dict] | None:
    """Minute bars of a chart drawn in the last ``CHART_CACHE_SECONDS``, or None."""
    from app.engine.chart_feed import chart_feed
    held = chart_feed.peek_minutes(symbol, day)
    if held is None or time.time() - held[1] > CHART_CACHE_SECONDS:
        return None
    return _bars(held[0], day, hours)


def _sip(symbols: list[str], day: date, now: float, hours: dict | None, watch: bool = False) -> dict[str, list[dict]]:
    """Today's minutes (extended hours) for every symbol in one Alpaca read, SIP like the charts. {} when Alpaca is not
    set up, refuses (403: the account's plan may not allow recent SIP minutes), fails or needs more than ``SIP_PAGES`` pages
    (a cut-off day is not a line); any of those turns it off for ``SIP_BACKOFF_SECONDS``. ``watch``: the Watching names'
    own read, with its own back-off, so a long watchlist that overflows the pages never turns off the book's read."""
    global _sip_off_until, _sip_watch_off_until
    from app.engine import alpaca
    start = datetime.combine(day, wall_time(4), ET)
    if not alpaca.alpaca_configured() or time.time() < (_sip_watch_off_until if watch else _sip_off_until) or datetime.fromtimestamp(now, ET) <= start:
        return {}
    params = {"symbols": ",".join(symbols), "timeframe": "1Min", "start": start.isoformat(),
              "end": datetime.fromtimestamp(now, UTC).isoformat(), "adjustment": "split", "feed": "sip", "limit": 10000}
    rows: dict[str, list[dict]] = {}
    try:
        for _ in range(SIP_PAGES):
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
    except Exception as exc:  # noqa: BLE001 -- the symbols fall to the Tradier reads
        if watch:
            _sip_watch_off_until = time.time() + SIP_BACKOFF_SECONDS
        else:
            _sip_off_until = time.time() + SIP_BACKOFF_SECONDS
        log.warning("desk sparks: the %sbatched Alpaca read is off for %d s (%s)", "Watching names' " if watch else "",
                    SIP_BACKOFF_SECONDS, exc)
        return {}
    out: dict[str, list[dict]] = {}
    for symbol, found in rows.items():
        minutes = []
        for r in found:
            try:
                minutes.append({"time": int(datetime.fromisoformat(r["t"].replace("Z", "+00:00")).timestamp()),
                                "close": float(r["c"])})
            except (KeyError, TypeError, ValueError):
                continue
        if minutes:
            out[symbol] = _extended(minutes, day, hours)
    return out


def _extended(minutes: list[dict], day: date, hours: dict | None) -> list[dict]:
    window = next((w for w in session_windows(day, hours) if w[0] == "regular"), None)
    out = []
    for m in minutes:
        local = datetime.fromtimestamp(m["time"], ET)
        minute = local.hour * 60 + local.minute
        out.append({**m, "extended": window is None or not window[1] <= minute < window[2]})
    return sorted(out, key=lambda b: b["time"])


# ------------------------------------------------------------------ building


def _store_line(symbol: str, bars: list[dict], now: float, day: date, valid: float) -> None:
    from app.engine import desk_context
    shown = desk_context._today_shown(lambda _s: bars, symbol, now)
    with _lock:
        _lines[symbol] = (valid, day, _thin(shown))


def _store_change(symbol: str, change: float | None, day: date, valid: float, last: float | None = None) -> None:
    with _lock:
        _changes[symbol] = (valid, day, change, last)


def _fill(symbols: list[str], day: date, now: float, valid: float, hours: dict | None, abandon: threading.Event,
          batched_only: frozenset[str] = frozenset()) -> None:
    """The lines nothing in hand served: one batched read, then one low-priority read each (never for ``batched_only``,
    the Watching list's names). Stores each line as it lands."""
    from app.engine.chart_feed import LOW_SLOTS, chart_feed
    todo = [s for s in symbols if s not in batched_only]
    watched = [s for s in symbols if s in batched_only]
    # The book's names in their own batch first; the Watching names in a second one that cannot fail the book's.
    for names, watch in ((todo, False), (watched, True)):
        if len(names) >= 2 or (watch and names):
            got = _sip(names, day, now, hours, watch=watch)
            for symbol, bars in got.items():
                _store_line(symbol, bars, now, day, valid)
            if not watch:
                todo = [s for s in todo if s not in got]

    def one(symbol: str) -> None:
        if abandon.is_set():  # the request gave up: do not start a read nobody waits for
            return
        try:
            _store_line(symbol, _bars(chart_feed.today_minutes(symbol, now), day, hours), now, day, valid)
        except Exception:  # noqa: BLE001 -- one symbol's failed read leaves it out
            log.warning("desk spark failed for %s", symbol, exc_info=True)
    with ThreadPoolExecutor(max_workers=LOW_SLOTS) as pool:
        list(pool.map(one, todo))


def _fill_logged(*args) -> None:
    try:
        _fill(*args)
    except Exception:  # noqa: BLE001 -- nobody waits on this future's result
        log.warning("desk sparks: filling the lines failed", exc_info=True)


def _quotes(symbols: list[str]) -> dict:
    """One quote read for the changes. Old rows handed back by a failed read are no change: they would be kept a minute
    (or the night) as if they were now."""
    from app.engine.chart_feed import chart_feed
    rows, stamp, issue = chart_feed.quote_rows(symbols)
    if issue and (stamp is None or time.time() - stamp > CHART_CACHE_SECONDS):
        return {"state": "stale", "rows": []}
    return {"state": "ok", "rows": rows}


def _names(symbols: str) -> list[str]:
    return sorted({s.strip().upper() for s in symbols.split(",") if s.strip().replace(".", "").isalnum()})


def read(symbols: str, now: float, watch: str = "") -> dict:
    from app.engine.request_timing import timed
    from app.routers import today
    book = _names(symbols)[:SYMBOLS]
    watched = [n for n in _names(watch) if n not in book][:WATCH]
    names = book + watched
    day, phase, hours, regular = _session(now)
    valid = _valid_until(now, phase, hours)
    with _lock:
        need_lines = [n for n in names if not _fresh(_lines.get(n), now, day)]
        need_change = [n for n in sorted({*names, "SPY"}) if not _fresh(_changes.get(n), now, day)]
    if phase == "regular" and (need_lines or need_change):
        with timed("sparks radar"):
            for symbol, found in _radar(sorted({*need_lines, *need_change}), day, now, regular).items():
                if symbol in need_lines:
                    _store_line(symbol, found["bars"], now, day, valid)
                if found["change_pct"] is not None:  # none recorded: the quote read below gives it
                    _store_change(symbol, found["change_pct"], day, valid, found["last"])
        with _lock:
            need_lines = [n for n in need_lines if not _fresh(_lines.get(n), now, day)]
            need_change = [n for n in need_change if not _fresh(_changes.get(n), now, day)]
    # The changes' quote read starts beside the line reads (one call for every symbol the recorder did not cover).
    quoted_ahead = (today._ahead("sparks quotes", lambda: _quotes(need_change))
                    if need_change else None)
    for symbol in list(need_lines):
        held = _chart_cache(symbol, day, hours)
        if held is not None:
            _store_line(symbol, held, now, day, valid)
            need_lines.remove(symbol)
    if need_lines:
        abandon = threading.Event()
        job: Future = today._start(lambda: _fill_logged(need_lines, day, now, valid, hours, abandon, frozenset(watched)))
        with timed("sparks closes"):
            done, _late = wait([job], timeout=BUDGET_SECONDS)
        if not done:
            abandon.set()
    if quoted_ahead is not None:
        read_back = quoted_ahead.get()  # its failure is logged by the section; the lines stand without the changes
        if read_back["state"] == "ok":
            quoted = {r["symbol"]: r for r in read_back["rows"]}
            for symbol in need_change:
                row = quoted.get(symbol) or {}
                _store_change(symbol, row.get("change_percentage"), day, valid, row.get("last"))
    rows: dict[str, dict] = {}
    with _lock:
        for name in names:
            line, change = _lines.get(name), _changes.get(name)
            change = change if _fresh(change, now, day) else None
            # A book row needs its line; a watched row shows its price and change without one.
            drawn = _fresh(line, now, day)
            points = list(line[2]) if drawn else []
            if name in watched and phase == "pre":
                # Before the open the quote carries no pre-market trade and its previous close has rolled (#718): a
                # watched row shows the line's last minute and no change, never a +0.00%.
                rows[name] = {"points": points, "change_pct": None, "last": points[-1] if points else None}
            elif name in watched and (drawn or change is not None):
                rows[name] = {"points": points, "change_pct": change[2] if change else None,
                              "last": change[3] if change and change[3] is not None else (points[-1] if points else None)}
            elif drawn:
                rows[name] = {"points": points, "change_pct": change[2] if change else None}
        spy = _changes.get("SPY")
        spy_change = spy[2] if _fresh(spy, now, day) else None
        for table in (_lines, _changes):
            if len(table) > 256:
                table.clear()
    return {"as_of": today._iso(now), "rows": rows, "spy_change_pct": spy_change}
