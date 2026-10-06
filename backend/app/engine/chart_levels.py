"""Automatic chart levels: session and structure levels (C2.1), merged into
confluence zones (C2.2), with how price has interacted with each today (C2.3).

Pure: no network, no database, no provider calls, held that way by
`tests/test_import_boundaries.py`. The caller hands in bars the chart already
loaded, on the chart's display price basis (C0.6); nothing here fetches,
adjusts or fills in a missing bar.

Where fill enrichment already defines a level, this module calls that code:
`indicators.analyze_minute_bars` for the premarket range and the 5- and
15-minute opening ranges, `indicators.get_previous_day_data` for the prior
day. On the same bars the chart and a fill's market context therefore agree.
Those definitions are clock hours (04:00 and 09:30 New York), so on a day the
calendar opens at any other time they are left out rather than misplaced.

Each level says what it is (`evidence`): *observed* is a provider field passed
through (a daily bar's high), *calculated* a formula over observed bars,
*inferred* a heuristic (a swing). A level the supplied bars cannot support is
absent, and `LevelSet.missing` says why; nothing is estimated.
"""

from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass, field
from datetime import date, datetime, time as wall_time, timedelta, timezone
from math import floor, log, log10
from typing import Mapping

from app.engine.chart_math import ET, EXTENDED_END, PRE_START, REGULAR_CLOSE, REGULAR_OPEN, session_windows
from app.engine.indicators import analyze_minute_bars, compute_daily_indicators, get_previous_day_data

SWING_LOOKBACK = 60  # completed sessions searched for swings, about three months
SWING_SIDE = 2  # sessions on each side a swing high must stand above (a low, below)
ROUND_TARGET = 0.01  # round-number spacing aims at about 1% of price
ROUND_EACH_SIDE = 3  # round numbers at or below the price, and as many above
DAILY_TAIL = SWING_LOOKBACK + SWING_SIDE + 10  # daily bars any level reads
# A tenth of the prior daily ATR caps a zone's TOTAL width and defines proximity.
# Actual contacts/crosses use the visible bounds, never this proximity buffer.
BAND_ATR = 0.1

Calendar = Mapping[date, dict | None] | None


@dataclass(frozen=True, slots=True)
class Level:
    kind: str  # prior_day_high, premarket_low, opening_range_15m_high, swing_high, round, ...
    label: str  # short chart label: "PDH", "OR15 high", "21,500"
    price: float
    evidence: str  # "observed", "calculated" or "inferred"
    timeframe: str | None = None  # interval of the bars it was read from, "1m" or "1D"; None for round numbers
    source: str | None = None  # provider of the bar that set it ("tradier", "alpaca_sip")
    # Start (UTC seconds) of the bar that set the price. One bar can set several
    # levels (the premarket and overnight high, the prior day and week high);
    # confluence (C2.2) counts them once.
    bar_time: int | None = None
    formed_at: int | None = None  # UTC seconds it became final; None while developing and for round numbers
    developing: bool = False  # its window is still open at as_of, so it can still move


@dataclass(frozen=True, slots=True)
class LevelSet:
    day: date
    as_of: int
    levels: tuple[Level, ...]
    missing: dict[str, str] = field(default_factory=dict)  # group -> why it is absent
    # Wilder ATR(14) of the completed daily bars, as fill context computes it; None without enough of them.
    atr: float | None = None


@dataclass(frozen=True, slots=True)
class Zone:
    """Levels within one band of each other (C2.2). A lone level is a zone of one."""
    id: str  # stable while its members keep their kinds and prices
    low: float  # the members' lowest and highest prices, as they are: never rounded or padded
    high: float
    label: str  # the members' labels, highest price first: "PDH + 21,500 + OR15 high"
    score: int  # distinct origins, not statistical independence or strength
    members: tuple[Level, ...]


def compute_levels(day: date, minutes: list[dict], daily: list[dict], as_of: int,
                   calendar: Calendar = None, reference: float | None = None) -> LevelSet:
    """Levels for the New York session ``day`` as known at ``as_of`` (UTC seconds).

    ``minutes`` are 1-minute bars sorted by start time (``time``, UTC seconds),
    covering the previous session and ``day``. ``daily`` are daily bars sorted
    by time, as ``chart_math.normalize_bars(daily=True)`` makes them. Only bars
    complete by ``as_of`` count. ``calendar`` maps dates to normalized market
    days, as for ``chart_math.chart_bars``; a date it lacks uses clock hours,
    which cannot see holidays. ``reference`` centers the round numbers and
    defaults to the last completed close.
    """
    levels: list[Level] = []
    missing: dict[str, str] = {}
    cut = bisect_left(daily, _stamp(day, 0), key=lambda bar: bar["time"])
    completed = [b for b in daily[max(0, cut - DAILY_TAIL):cut] if _close(_date(b), calendar) <= as_of]
    stale = _daily_gap(completed, day, calendar)
    _prior_day(day, completed, stale, calendar, levels, missing)
    _prior_week(day, completed, calendar, levels, missing)
    _intraday(day, minutes, as_of, calendar, levels, missing)
    history_gap = stale or _history_gap(completed, calendar)
    _swings(completed, history_gap, calendar, levels, missing)
    if reference is None:
        reference = _last_close(minutes, as_of) or (completed[-1]["close"] if completed and not stale else None)
    _round_numbers(reference, levels, missing)
    atr = compute_daily_indicators([_alpaca(b) for b in completed]).get(_date(completed[-1]).isoformat(), {}).get("atr_14") if len(completed) > 14 and not history_gap else None
    if history_gap:
        missing["atr"] = history_gap
    return LevelSet(day, as_of, tuple(levels), missing, atr)


def session_day(today: date, calendar: Calendar = None) -> date:
    """The session levels are for: today when it trades, otherwise the next one."""
    return next((d for d in _days(today, today + timedelta(days=10)) if _regular(d, calendar)), today)


def previous_session(day: date, calendar: Calendar = None) -> date | None:
    """The last date before ``day`` with a regular session, within two weeks."""
    return next((d for d in _days(day - timedelta(days=14), day)[::-1] if _regular(d, calendar)), None)


def confluence(levels: tuple[Level, ...] | list[Level], band: float | None) -> list[Zone]:
    """Nearest-pair complete-link clusters: TOTAL span must be less than ``band``.

    Adjacent clusters merge by the smallest maximum pair distance (their span),
    ties to the lower cluster. Adding a bridge cannot create an unlimited chain.
    No ATR merges exact-price duplicates only. Member prices are never padded.
    """
    zones = [[level] for level in sorted(levels, key=lambda item: item.price)]
    while len(zones) > 1:
        candidates = [(zones[i + 1][-1].price - zones[i][0].price, i) for i in range(len(zones) - 1)]
        span, index = min(candidates)
        # An exact threshold stays separate, including floating-point decimal noise.
        if not (span + 1e-9 < band if band else span == 0):
            break
        zones[index:index + 2] = [zones[index] + zones[index + 1]]
    out = []
    for members in zones:
        shown = sorted(members, key=lambda item: -item.price)  # stable: same-price members keep their group order
        sources = {(m.timeframe, m.bar_time) if m.bar_time is not None else (m.kind, m.price) for m in members}
        labels = list(dict.fromkeys(m.label for m in shown))  # "Swing high ×2", not the same name twice
        counts = {name: sum(m.label == name for m in shown) for name in labels}
        out.append(Zone("|".join(sorted(f"{m.kind}@{m.price!r}" for m in members)), members[0].price, members[-1].price,
                        " + ".join(name if counts[name] == 1 else f"{name} ×{counts[name]}" for name in labels), len(sources), tuple(shown)))
    return out


def zone_start(zone: Zone) -> int | None:
    """Count only once the whole current combination is confirmed.

    Any moving member makes the combination developing. This is a scan of a
    fixed current combination, not a durable event log of earlier combinations.
    A newly confirmed member starts a new history instead of backdating bounds.
    """
    return None if any(m.developing for m in zone.members) else max((m.formed_at or 0 for m in zone.members), default=0)


def interactions(low: float, high: float, band: float, bars: list[dict], start: int) -> dict:
    """Contacts/crosses use visible bounds; the ATR halo is proximity only.

    A contact followed by a wholly outside candle is ``tested`` (left above or
    below, not evidence of support strength). An outer-buffer-only visit can
    produce ``approached``. Unknown side never implies contact. Event ``time``
    is when the confirming candle closes; ``bar_time`` is its start.
    """
    top, bottom = high + band, low - band
    earlier = [b for b in bars if b["time"] < start]
    counted = [b for b in bars if b["time"] >= start]
    def where(value):
        return "above" if value > high else "below" if value < low else None
    side = where(earlier[-1]["close"]) if earlier else where(counted[0]["open"]) if counted else None
    origin, touching, approaching, events, crossed = side, False, False, [], None

    def event(name, bar, direction):
        events.append({"event": name, "time": bar.get("end_time", bar["time"]), "bar_time": bar["time"], "direction": direction})

    for bar in counted:
        closed = where(bar["close"])
        contact = bar["low"] <= high and bar["high"] >= low
        near = bar["low"] <= top and bar["high"] >= bottom
        if side is None:
            touching = touching or contact
            approaching = approaching or near
            side = origin = closed
            continue
        if closed is not None and closed != side:
            crossed = "broken" if side == origin else "reclaimed"
            event(crossed, bar, closed)
            side, touching, approaching = closed, False, False
        elif contact:
            touching = True
            approaching = False
        elif touching:
            event("tested", bar, side)
            touching, approaching = False, False
        elif near:
            approaching = True
        elif approaching:
            event("approached", bar, side)
            approaching = False
    state = crossed or ("touched" if touching else "approached" if approaching else events[-1]["event"] if events else "untested")
    last = counted[-1] if counted else None
    return {"state": state, "events": events, "at_level": bool(last and last["low"] <= high and last["high"] >= low),
            "near_level": bool(last and last["low"] <= top and last["high"] >= bottom),
            "since": max(start, counted[0]["time"]) if counted else start,
            "last_close": last["close"] if last else None,
            "last_close_at": last.get("end_time", last["time"]) if last else None}


def round_step(price: float) -> float:
    """The spacing of round numbers: 1 or 5 × 10^k, whichever is nearest (by ratio) to 1% of price.

    SPY at 660 steps by 5, NVDA at 180 by 1, a $10 stock by 0.10.
    """
    target = price * ROUND_TARGET
    k = floor(log10(target))
    return min((m * 10.0 ** e for m, e in ((1, k), (5, k), (1, k + 1))), key=lambda s: abs(log(s / target)))


# ---------------------------------------------------------------------------
# Daily levels
# ---------------------------------------------------------------------------

def _prior_day(day, completed, stale, calendar, levels, missing):
    if stale:
        missing["prior_day"] = stale
        return
    bar = completed[-1]
    # The fill-context definition, so a fill's prior-day fields and the chart agree.
    values = get_previous_day_data([_alpaca(b) for b in completed], day)
    common = {"evidence": "observed", "timeframe": "1D", "source": bar.get("source"),
              "bar_time": bar["time"], "formed_at": _close(_date(bar), calendar)}
    for side, label in (("high", "PDH"), ("low", "PDL"), ("close", "PDC")):
        levels.append(Level(f"prior_day_{side}", label, values[side], **common))


def _prior_week(day, completed, calendar, levels, missing):
    monday = day - timedelta(days=day.weekday())
    start = monday - timedelta(days=7)
    week = [b for b in completed if start <= _date(b) < monday]
    dates = {_date(b) for b in week}
    absent = next((d for d in _days(start, monday) if _regular(d, calendar) and d not in dates), None)
    if absent or not week:
        missing["prior_week"] = f"No daily bar for {absent or start}."
        return
    formed = _close(_date(week[-1]), calendar)
    for side, label, pick in (("high", "PWH", max), ("low", "PWL", min)):
        bar = pick(week, key=lambda b: b[side])  # the first session to reach it
        levels.append(Level(f"prior_week_{side}", label, bar[side], "calculated", "1D",
                            bar.get("source"), bar["time"], formed))


def _swings(completed, stale, calendar, levels, missing):
    """Daily pivots: a high above the SWING_SIDE sessions before it and at least as
    high as the SWING_SIDE after it (so equal highs mark the first), lows mirrored.
    It forms when the last confirming session closes."""
    if stale:
        missing["swings"] = stale
        return
    tail = completed[-(SWING_LOOKBACK + SWING_SIDE):]
    if len(tail) < 2 * SWING_SIDE + 1:
        missing["swings"] = "Not enough daily history for swings."
        return
    for i in range(SWING_SIDE, len(tail) - SWING_SIDE):
        bar, before, after = tail[i], tail[i - SWING_SIDE:i], tail[i + 1:i + 1 + SWING_SIDE]
        formed = _close(_date(after[-1]), calendar)
        if bar["high"] > max(b["high"] for b in before) and bar["high"] >= max(b["high"] for b in after):
            levels.append(Level("swing_high", "Swing high", bar["high"], "inferred", "1D", bar.get("source"), bar["time"], formed))
        if bar["low"] < min(b["low"] for b in before) and bar["low"] <= min(b["low"] for b in after):
            levels.append(Level("swing_low", "Swing low", bar["low"], "inferred", "1D", bar.get("source"), bar["time"], formed))


def _daily_gap(completed, day, calendar) -> str | None:
    """Why the daily bars cannot give the previous session, or None when they can."""
    if not completed:
        return f"No completed daily bars before {day}."
    absent = next((d for d in _days(_date(completed[-1]) + timedelta(days=1), day) if _regular(d, calendar)), None)
    return f"No daily bar for {absent}." if absent else None


def _history_gap(completed, calendar) -> str | None:
    """Do not compress a missing trading session out of pivot confirmation/ATR."""
    if not completed:
        return None
    dates = {_date(bar) for bar in completed}
    absent = next((d for d in _days(_date(completed[0]), _date(completed[-1])) if _regular(d, calendar) and d not in dates), None)
    return f"No daily bar for {absent}." if absent else None


# ---------------------------------------------------------------------------
# Intraday levels
# ---------------------------------------------------------------------------

def _intraday(day, minutes, as_of, calendar, levels, missing):
    windows = {part: (start, end) for part, start, end in session_windows(day, _hours(day, calendar))}
    if "regular" not in windows:
        for group in ("premarket", "overnight", "opening_range_5m", "opening_range_15m"):
            missing[group] = f"The market is closed on {day}."
        return
    opening = windows["regular"][0]
    _overnight(day, minutes, as_of, calendar, windows, levels, missing)
    if opening != REGULAR_OPEN:
        note = f"The session opens at {_clock(opening)}; premarket and opening ranges are defined from 09:30."
        for group in ("premarket", "opening_range_5m", "opening_range_15m"):
            missing[group] = note
        return

    lo, hi = bisect_left(minutes, _stamp(day, 0), key=lambda b: b["time"]), bisect_left(minutes, _stamp(day, 1440), key=lambda b: b["time"])
    todays = minutes[lo:hi]
    at = min(as_of, _stamp(day, EXTENDED_END))
    # The fill-context definitions, so a fill's entry context and the chart agree.
    context = analyze_minute_bars([_alpaca(b) for b in todays], _naive(at)) if todays and at >= _stamp(day, 0) else {}
    ranges = (("premarket", ("PMH", "PML"), PRE_START, REGULAR_OPEN),
              ("opening_range_5m", ("OR5 high", "OR5 low"), REGULAR_OPEN, REGULAR_OPEN + 5),
              ("opening_range_15m", ("OR15 high", "OR15 low"), REGULAR_OPEN, REGULAR_OPEN + 15))
    for group, labels, start, end in ranges:
        high, low = context.get(f"{group}_high"), context.get(f"{group}_low")
        if high is None or low is None:
            if group == "premarket" and as_of < _stamp(day, PRE_START + 1):
                missing[group] = "Premarket trading starts at 04:00."
            elif group != "premarket" and as_of < _stamp(day, end):
                missing[group] = f"Forms at {_clock(end)}."
            else:
                missing[group] = f"No bars from {_clock(start)} to {_clock(end)} on {day}."
            continue
        # The premarket range is shown while it forms; an opening range only once complete.
        developing = as_of < _stamp(day, end)
        span = [b for b in todays if _stamp(day, start) <= b["time"] < _stamp(day, end) and b["time"] + 60 <= as_of]
        for side, label, price in (("high", labels[0], high), ("low", labels[1], low)):
            # The provenance the fill-context function does not return: the first bar at that price.
            bar = next((b for b in span if round(b[side], 6) == price), None)
            levels.append(Level(f"{group}_{side}", label, price, "calculated", "1m",
                                bar and bar.get("source"), bar and bar["time"],
                                None if developing else _stamp(day, end), developing))


def _overnight(day, minutes, as_of, calendar, windows, levels, missing):
    """From the previous session's close to this session's open: its postmarket and this premarket."""
    previous = previous_session(day, calendar)
    if previous is None:
        missing["overnight"] = "No previous session in the last two weeks."
        return
    lo = bisect_left(minutes, _stamp(previous, 0), key=lambda b: b["time"])
    if lo == len(minutes) or minutes[lo]["time"] >= _stamp(previous, 1440):
        # Without the previous session its postmarket cannot be told from a quiet one.
        missing["overnight"] = f"No minute bars for {previous}."
        return
    spans = [(_stamp(previous, start), _stamp(previous, end)) for part, start, end in session_windows(previous, _hours(previous, calendar)) if part == "post"]
    spans += [(_stamp(day, start), _stamp(day, end)) for part, (start, end) in windows.items() if part == "pre"]
    hi = bisect_left(minutes, _stamp(day, windows["regular"][0]), key=lambda b: b["time"])
    bars = [b for b in minutes[lo:hi] if b["time"] + 60 <= as_of and any(s <= b["time"] < e for s, e in spans)]
    if not bars:
        missing["overnight"] = f"No bars between the {previous} close and the {day} open."
        return
    open_at = _stamp(day, windows["regular"][0])
    developing = as_of < open_at
    for side, label, pick in (("high", "ONH", max), ("low", "ONL", min)):
        bar = pick(bars, key=lambda b: b[side])  # the first minute to reach it
        levels.append(Level(f"overnight_{side}", label, bar[side], "calculated", "1m", bar.get("source"),
                            bar["time"], None if developing else open_at, developing))


# ---------------------------------------------------------------------------
# Round numbers
# ---------------------------------------------------------------------------

def _round_numbers(reference, levels, missing):
    if not reference or reference <= 0:
        missing["round"] = "No price to place round numbers around."
        return
    step = round_step(reference)
    base = floor(reference / step + 1e-9)
    for k in range(base - ROUND_EACH_SIDE + 1, base + ROUND_EACH_SIDE + 1):
        price = round(k * step, 6)
        if price > 0:
            levels.append(Level("round", f"{price:,.6f}".rstrip("0").rstrip("."), price, "calculated"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _stamp(day: date, minute: int) -> int:
    return int(datetime.combine(day + timedelta(days=minute // 1440), wall_time(minute % 1440 // 60, minute % 60), ET).timestamp())


def _clock(minute: int) -> str:
    return f"{minute // 60:02d}:{minute % 60:02d}"


def _date(bar: dict) -> date:
    return datetime.fromtimestamp(bar["time"], ET).date()


def _naive(stamp: int) -> datetime:
    """New York wall time without a zone, as fill times are stored and the fill-context code reads them."""
    return datetime.fromtimestamp(stamp, ET).replace(tzinfo=None)


def _hours(day: date, calendar: Calendar) -> dict | None:
    return calendar.get(day) if calendar else None


def _regular(day: date, calendar: Calendar) -> tuple[int, int] | None:
    return next(((start, end) for part, start, end in session_windows(day, _hours(day, calendar)) if part == "regular"), None)


def _close(day: date, calendar: Calendar) -> int:
    """When that date's regular session closed: 13:00 on a half day the calendar knows about."""
    regular = _regular(day, calendar)
    return _stamp(day, regular[1] if regular else REGULAR_CLOSE)


def _days(start: date, end: date) -> list[date]:
    return [start + timedelta(days=i) for i in range((end - start).days)]


def _last_close(minutes: list[dict], as_of: int) -> float | None:
    i = bisect_left(minutes, as_of - 59, key=lambda b: b["time"])
    return minutes[i - 1]["close"] if i else None


def _alpaca(bar: dict) -> dict:
    """A chart bar in the Alpaca shape the fill-context code reads."""
    return {"t": datetime.fromtimestamp(bar["time"], timezone.utc).isoformat(), "o": bar["open"],
            "h": bar["high"], "l": bar["low"], "c": bar["close"], "v": bar["volume"]}
