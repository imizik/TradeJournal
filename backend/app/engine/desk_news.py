"""Headlines on the desk chart (``GET /copilot/desk/{id}/news``, docs/copilot-lab.md § The desk): the selected symbol's
news at the candle where each was published, so a jump and its headline sit together.

- Source: the headlines the desk Feed already shows (Alpaca's news API, Benzinga's wire), one batched read per symbol
  covering ``LOOKBACK_DAYS``, kept ``NEWS_TTL_S`` seconds and shared by both intraday timeframes. No other provider,
  no page is fetched, no chatter. A refused or failed read is ``unavailable``, never "no news".
- Candles: the ones the chart read just drew, from the chart feed's response cache and the stored sessions on disk only.
  This read never asks for a bar, so it adds nothing to the Tradier/Polygon budget (#711). Intraday only (2m, 15m).
- Placement: a headline sits on the candle whose time span holds it; one published between candles (the 15m chart's
  pre-market and after hours, a quiet minute with no trade) sits on the next candle, marked ``before``; one published
  after the previous regular close and before the first candle sits on the first. Anything older is not shown.
- Groups: headlines on candles less than ``GROUP_S`` apart share one marker (at the first candle), newest first.
- Big moves: per New York day, a candle whose range, or the stretch of about ``STRETCH_S`` ending at it, is at least
  ``BIG_MULTIPLE`` times the day's typical (median) one and at least ``MIN_MOVE_PCT`` of price. A group with a headline
  published within ``NEAR_S`` of such a move is ``emphasis`` and carries the move. A move with no headline gets
  nothing: no reason is ever invented.
- A ticker set to Not following gets no markers, and a headline naming one is left out (as in the Feed). If that
  setting cannot be read, none show.

Headline text is third-party data shown as data with its publisher and time. Read-only: no write, no model call.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
import logging
import re
import statistics
import threading
import time as _time

from app.engine.chart_math import ET

log = logging.getLogger(__name__)

TIMEFRAMES = ("2m", "15m")
STEP = {"2m": 120, "15m": 900}
NEWS_TTL_S = 180
LOOKBACK_DAYS = 7  # calendar days of headlines in the one read (the 15m chart shows three sessions)
READ_LIMIT = 50  # one page, newest first
GROUP_S = 360  # candles closer than this share a marker (2m: three candles; 15m: the same candle)
STRETCH_S = 300
BIG_MULTIPLE = 3.0
MIN_MOVE_PCT = 0.3
MIN_DAY_CANDLES = 10  # fewer candles in a day: no "typical" to compare against, so no move is called big
NEAR_S = 300
MAX_GROUPS = 40
MAX_PER_GROUP = 8
SYMBOL = re.compile(r"[A-Z]{1,6}(\.[A-Z])?")


# ------------------------------------------------------------------ pure parts (tested directly)


def session_word(at: int) -> str:
    """Where a New York clock time falls: ``regular``, ``pre-market``, ``after hours``, ``overnight`` or ``weekend``."""
    moment = datetime.fromtimestamp(at, ET)
    if moment.weekday() >= 5:
        return "weekend"
    minute = moment.hour * 60 + moment.minute
    if 570 <= minute < 960:
        return "regular"
    if 240 <= minute < 570:
        return "pre-market"
    if 960 <= minute < 1200:
        return "after hours"
    return "overnight"


def place(headlines: list[dict], bars: list[dict], step: int, since: int) -> list[dict]:
    """Each headline (``_at`` a datetime, from ``premarket_prep._headline``) on its candle: ``time`` the candle's,
    ``before`` when it was published before that candle opened. ``since`` (epoch): headlines older than this, before the
    first candle, are left out; so is one after the last candle's end (it has no candle yet)."""
    if not bars:
        return []
    times = [int(b["time"]) for b in bars]
    first, end = times[0], times[-1] + step
    out = []
    for row in headlines:
        at = int(row["_at"].timestamp())
        if at < since or at >= end:
            continue
        if at < first:
            i = 0
        else:
            i = _last_at_or_before(times, at)
            if at >= times[i] + step:  # in a gap: the next candle is the first it could move
                i += 1
        out.append({"time": times[i], "at": at, "before": at < times[i], "session": session_word(at),
                    "headline": row["headline"], "source": row["publisher"], "url": row["url"]})
    return out


def _last_at_or_before(times: list[int], at: int) -> int:
    lo, hi = 0, len(times) - 1
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if times[mid] <= at:
            lo = mid
        else:
            hi = mid - 1
    return lo


def group(placed: list[dict]) -> list[dict]:
    """Headlines on candles less than ``GROUP_S`` apart as one marker at the first candle, each newest first, a story
    repeated (same link or same words) once."""
    seen: set[str] = set()
    rows = []
    for row in sorted(placed, key=lambda r: r["at"], reverse=True):
        key_url, key_text = row["url"], " ".join(row["headline"].lower().split())
        if key_url in seen or key_text in seen:
            continue
        seen.update((key_url, key_text))
        rows.append(row)
    groups: list[dict] = []
    for row in sorted(rows, key=lambda r: (r["time"], r["at"])):
        if groups and row["time"] - groups[-1]["time"] < GROUP_S:
            groups[-1]["items"].append(row)
        else:
            groups.append({"time": row["time"], "items": [row]})
    for g in groups:
        g["items"].sort(key=lambda r: r["at"], reverse=True)
        g["count"] = len(g["items"])
        g["items"] = [{k: v for k, v in r.items() if k != "time"} for r in g["items"][:MAX_PER_GROUP]]
        g["emphasis"], g["move"] = False, None
    return groups[-MAX_GROUPS:]


def big_moves(bars: list[dict], step: int) -> list[dict]:
    """Stretches well beyond their day's typical candle: ``start``/``end`` (epoch), ``pct`` the signed change from the
    stretch's first open to its last close, ``range_pct`` its high-to-low span against that open."""
    days: dict[date, list[int]] = {}
    for i, b in enumerate(bars):
        days.setdefault(datetime.fromtimestamp(b["time"], ET).date(), []).append(i)
    moves: list[dict] = []
    for idx in days.values():
        regular = [i for i in idx if not bars[i].get("extended")]
        basis = regular if len(regular) >= MIN_DAY_CANDLES else idx
        if len(basis) < MIN_DAY_CANDLES:
            continue
        ranges = {i: float(bars[i]["high"]) - float(bars[i]["low"]) for i in idx}
        stretch = {}
        first = 0
        for i in idx:  # by the clock, not a count of candles: a thin tape's candles can be many minutes apart
            while bars[idx[first]]["time"] <= bars[i]["time"] - STRETCH_S:
                first += 1
            start = idx[first]
            stretch[i] = (start, float(bars[i]["close"]) - float(bars[start]["open"]))
        typical_range = statistics.median(ranges[i] for i in basis)
        typical_move = statistics.median(abs(stretch[i][1]) for i in basis)
        big, wide_at = [], set()
        for i in idx:
            start, move = stretch[i]
            base = float(bars[start]["open"]) or 1.0
            wide = typical_range > 0 and ranges[i] >= BIG_MULTIPLE * typical_range
            far = typical_move > 0 and abs(move) >= BIG_MULTIPLE * typical_move
            pct = max(ranges[i] / base, abs(move) / base) * 100
            if (wide or far) and pct >= MIN_MOVE_PCT:
                big.append(i)
                if wide:
                    wide_at.add(i)
        runs: list[list[int]] = []
        for i in big:  # neighbouring big candles are one move
            if runs and bars[i]["time"] - bars[runs[-1][-1]]["time"] < STRETCH_S + step:
                runs[-1].append(i)
            else:
                runs.append([i])
        for run in runs:
            # The stretches after one wide candle still hold it: the move ends at the last wide candle.
            while len(run) > 1 and run[-1] not in wide_at and any(i in wide_at for i in run):
                run.pop()
            start = stretch[run[0]][0]
            span = bars[start: run[-1] + 1]
            base = float(bars[start]["open"]) or 1.0
            high, low = max(float(b["high"]) for b in span), min(float(b["low"]) for b in span)
            moves.append({"start": int(bars[start]["time"]), "end": int(bars[run[-1]]["time"]) + step,
                          "pct": round((float(bars[run[-1]]["close"]) - base) / base * 100, 2),
                          "range_pct": round((high - low) / base * 100, 2)})
    return moves


def emphasise(groups: list[dict], moves: list[dict]) -> list[dict]:
    """A group with a headline published within ``NEAR_S`` of a big move: ``emphasis`` and the largest such ``move``."""
    for g in groups:
        near = [m for m in moves if any(m["start"] - NEAR_S <= r["at"] <= m["end"] + NEAR_S for r in g["items"])]
        if near:
            g["emphasis"] = True
            g["move"] = max(near, key=lambda m: (abs(m["pct"]), m["range_pct"]))
    return groups


def view(headlines: list[dict], bars: list[dict], step: int, since: int, hidden: set[str] = frozenset(),
         symbol: str = "") -> list[dict]:
    """The chart's markers from headlines and candles."""
    wanted = [h for h in headlines if symbol in h.get("symbols", [symbol]) and not hidden.intersection(h.get("symbols") or [])]
    return emphasise(group(place(wanted, bars, step, since)), big_moves(bars, step))


# ------------------------------------------------------------------ reads


FAILED_TTL_S = 60  # a failed or refused read is not tried again for this long (each try can wait ~2.5 s)
_cache: dict[tuple[str, str], tuple[float, list[dict] | None]] = {}
_cache_lock = threading.Lock()
_inflight: dict[tuple[str, str], threading.Lock] = {}


def _window_start(now: float) -> datetime:
    day = datetime.fromtimestamp(now, ET).date() - timedelta(days=LOOKBACK_DAYS)
    return datetime(day.year, day.month, day.day, tzinfo=ET)


def _provider(symbol: str, start: datetime, end: datetime) -> list[dict]:
    from app.engine import news
    return news.fetch_news(symbols=[symbol], start=start, end=end, limit=READ_LIMIT, fast=True, strict=True)


class Page(list):
    """Headline rows; ``full`` when the provider's one page came back full (older headlines may be missing)."""
    full = False


def _fresh(hit: tuple[float, list[dict] | None] | None, clock: float) -> bool:
    return bool(hit) and clock - hit[0] < (NEWS_TTL_S if hit[1] is not None else FAILED_TTL_S)


def read_headlines(symbol: str, now: float, provider=None) -> list[dict]:
    """The symbol's headlines over ``LOOKBACK_DAYS`` (``premarket_prep._headline`` rows, newest first): one provider
    read per symbol per ``NEWS_TTL_S`` seconds, a second request for the same symbol waiting on the first. Raises when
    the read fails, and again without asking for ``FAILED_TTL_S`` seconds."""
    from app.engine.premarket_prep import _headline
    start = _window_start(now)
    key = (symbol, start.date().isoformat())

    def kept() -> list[dict] | None:
        with _cache_lock:
            hit = _cache.get(key)
        if not _fresh(hit, _time.monotonic()):
            return None
        if hit[1] is None:
            raise RuntimeError("headline read failed recently")
        return hit[1]

    found = kept()
    if found is not None:
        return found
    with _cache_lock:
        gate = _inflight.setdefault(key, threading.Lock())
    with gate:
        found = kept()
        if found is not None:
            return found
        end = datetime.fromtimestamp(now, ET)
        try:
            raw = (provider or _provider)(symbol, start, end)
            found = Page(h for a in raw if (h := _headline(a, start, end)))
            found.full = len(raw) >= READ_LIMIT
        except Exception:
            found = None
            raise
        finally:
            with _cache_lock:
                clock = _time.monotonic()
                for stale in [k for k, hit in _cache.items() if not _fresh(hit, clock)]:
                    del _cache[stale]
                _cache[key] = (clock, found)
                _inflight.pop(key, None)
    return found


def cached_bars(symbol: str, timeframe: str, now: float) -> list[dict]:
    """The chart's candles without a bar request: today's minutes from the chart feed's cache (2m, and 15m's today),
    the completed sessions before it from disk (15m)."""
    from app.engine import desk_context
    from app.engine.chart_calendar import chart_calendar
    from app.engine.chart_feed import chart_feed
    from app.engine.chart_math import chart_bars
    today = datetime.fromtimestamp(now, ET).date()
    found = chart_feed.peek_minutes(symbol, today)
    raw = [m for m in (found[0] if found else []) if int(m["time"]) <= now]
    if timeframe == "2m":
        return desk_context._two_minute(chart_bars(raw, [], "1m", "extended", {today: chart_calendar.hours(today)}) if raw else [])
    out: list[dict] = []
    for day, hours, minutes in desk_context.stored_sessions(symbol, today, desk_context.SESSIONS_15M - 1):
        out += chart_bars(minutes, [], "15m", "regular", {day: hours})
    if raw:
        out += chart_bars(raw, [], "15m", "regular", {today: chart_calendar.hours(today)})
    return [b for b in out if b["time"] <= now]


def _previous_close(first: int) -> int:
    from app.engine import premarket_prep
    from app.engine.chart_calendar import chart_calendar
    return int(premarket_prep._previous_close(chart_calendar, datetime.fromtimestamp(first, ET).date()).timestamp())


def build(symbol: str | None, timeframe: str, now: float, hidden: set[str] | None, *, bars=None, headlines=None,
          since=None) -> dict:
    """The markers for ``symbol`` on ``timeframe``. ``hidden`` None: the Not-following setting could not be read."""
    from app.engine import request_timing
    base = {"symbol": symbol, "timeframe": timeframe, "as_of": int(now), "groups": [], "reason": None}
    if not symbol or not SYMBOL.fullmatch(symbol) or timeframe not in TIMEFRAMES:
        return {**base, "state": "none", "reason": "Headlines show on the 2m and 15m charts of a symbol."}
    if hidden is None:
        return {**base, "state": "unavailable", "reason": "The Not following setting could not be read."}
    if symbol in hidden:
        return {**base, "state": "hidden", "reason": f"{symbol} is set to Not following."}
    with request_timing.timed("desk news bars"):
        shown = (bars or cached_bars)(symbol, timeframe, now)
    if not shown:
        return {**base, "state": "none", "reason": "No candles to place headlines on yet."}
    try:
        with request_timing.timed("desk news read"):
            found = (headlines or read_headlines)(symbol, now)
    except Exception as exc:  # noqa: BLE001 - a refused key is unavailable, never "no news"
        log.warning("desk news for %s unavailable: %s", symbol, type(exc).__name__)
        return {**base, "state": "unavailable", "reason": "The headline source could not be read; no marker is not evidence of no news."}
    start = (since or _previous_close)(int(shown[0]["time"]))
    # One page, newest first: when it is full, older headlines may be missing; say from when the markers are complete.
    oldest = min((int(h["_at"].timestamp()) for h in found), default=None)
    complete_from = oldest if getattr(found, "full", False) and oldest is not None and oldest > start else None
    return {**base, "state": "ok", "source": "Benzinga via Alpaca", "complete_from": complete_from,
            "groups": view(found, shown, STEP[timeframe], start, hidden, symbol)}
