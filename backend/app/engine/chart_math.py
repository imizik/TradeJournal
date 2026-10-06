"""Chart-only calculations on supplied bars. Never changes journal enrichment.

Times are UTC seconds. Intraday buckets are anchored to New York sessions;
regular, premarket and postmarket bars never collapse into the same candle.
Session windows come from a normalized market-calendar day when one is
supplied, so holidays and early closes resample, stream and count down alike.
"""

from bisect import bisect_left
from datetime import date, datetime, time as wall_time, timedelta
from math import isfinite, sqrt
from typing import Mapping
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
INTERVALS = {"1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240, "1D": 1440, "1W": 10080}
# New York minutes of day. Consolidated extended trading ends four hours after
# the regular close: 20:00 normally, 17:00 after a 13:00 early close.
PRE_START, REGULAR_OPEN, REGULAR_CLOSE, EXTENDED_END, POST_MINUTES = 240, 570, 960, 1200, 240
CLOCK_NOTE = "Market calendar unavailable: holidays and early closes use regular clock hours."


def normalize_bars(rows: list[dict], *, daily: bool = False, source: str = "tradier") -> list[dict]:
    """Reject malformed OHLCV, sort and deduplicate by the provider timestamp."""
    result = {}
    for row in rows:
        try:
            if daily:
                dt = datetime.fromisoformat(row["date"]).replace(hour=9, minute=30, tzinfo=ET)
                stamp = int(dt.timestamp())
                end = int(dt.replace(hour=16, minute=0).timestamp())
            else:
                stamp = int(row["timestamp"])
                end = stamp + 60
            prices = {k: float(row[k]) for k in ("open", "high", "low", "close", "volume")}
            if not all(isfinite(v) for v in prices.values()):
                continue
            if min(prices[k] for k in ("open", "high", "low", "close")) <= 0 or prices["volume"] < 0:
                continue
            if prices["high"] < max(prices["open"], prices["close"], prices["low"]):
                continue
            if prices["low"] > min(prices["open"], prices["close"]):
                continue
            if stamp <= 0:
                continue
            result[stamp] = {"time": stamp, "end_time": end, "source": source, **prices}
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
    return [result[k] for k in sorted(result)]


def session_windows(day: date, hours: dict | None = None) -> list[tuple[str, int, int]]:
    """Premarket, regular and postmarket minute windows for one New York date.

    `hours` is a normalized calendar day: {"status": "open"|"closed", "open",
    "close"} in minutes. None means the calendar is unavailable; every weekday
    then uses the clock hours, which cannot see holidays or early closes.
    """
    if hours is None:
        if day.weekday() >= 5:
            return []
        start, end = REGULAR_OPEN, REGULAR_CLOSE
    elif hours.get("status") != "open":
        return []
    else:
        start, end = hours["open"], hours["close"]
    windows = [("pre", PRE_START, start), ("regular", start, end), ("post", end, min(end + POST_MINUTES, EXTENDED_END))]
    return [w for w in windows if w[1] < w[2]]


def session_part(dt: datetime, hours: dict | None = None) -> tuple[str, int, int] | None:
    minute = dt.hour * 60 + dt.minute
    return next((w for w in session_windows(dt.date(), hours) if w[1] <= minute < w[2]), None)


def market_day(day: date, hours: dict | None) -> dict:
    """One date's session windows as UTC seconds, for the browser's countdown."""
    def stamp(minute: int) -> int:
        return int(datetime.combine(day, wall_time(minute // 60, minute % 60), ET).timestamp())
    return {"date": day.isoformat(), "status": "unknown" if hours is None else hours["status"],
            "source": "clock" if hours is None else hours.get("source", "calendar"),
            "description": None if hours is None else hours.get("description") or None,
            "sessions": [{"part": part, "start": stamp(start), "end": stamp(end)} for part, start, end in session_windows(day, hours)],
            "note": CLOCK_NOTE if hours is None else None}


def daily_page(series: list[dict], before: int, limit: int) -> tuple[list[dict], int | None, bool]:
    """One page of an already computed daily or weekly series: the ``limit`` bars starting before ``before``.

    Slicing the finished series (never resampling a slice) keeps indicators and
    weekly bars identical across page seams. Returns (bars, older cursor, exhausted):
    exhausted only when the page reaches the series' first bar, and then the cursor is None.
    """
    end = bisect_left(series, before, key=lambda bar: bar["time"])
    page = series[max(0, end - limit):end]
    exhausted = end <= limit
    return page, None if exhausted or not page else page[0]["time"], exhausted


def chart_bars(minutes: list[dict], daily: list[dict], interval: str, session: str,
               calendar: Mapping[date, dict | None] | None = None) -> list[dict]:
    if interval == "1D":
        return indicators([{**b, "source": b.get("source", "tradier"), "extended": False, "vwap": None, "vwap_sd": None} for b in daily])
    if interval == "1W":
        groups: dict[int, dict] = {}
        for b in daily:
            dt = datetime.fromtimestamp(b["time"], ET)
            monday = dt - timedelta(days=dt.weekday())
            stamp = int(monday.timestamp())
            end = int((monday + timedelta(days=4)).replace(hour=16, minute=0).timestamp())
            _merge(groups, stamp, end, b, False, None, None)
        return indicators(list(groups.values()))

    width = INTERVALS[interval]
    groups = {}
    current_day = None
    windows: list[tuple[str, int, int]] = []
    pv = pv2 = volume = 0.0
    for b in minutes:
        dt = datetime.fromtimestamp(b["time"], ET)
        if dt.date() != current_day:
            current_day, pv, pv2, volume = dt.date(), 0.0, 0.0, 0.0
            windows = session_windows(current_day, calendar.get(current_day) if calendar else None)
        minute = dt.hour * 60 + dt.minute
        part = next((w for w in windows if w[1] <= minute < w[2]), None)
        if part is None or (session == "regular" and part[0] != "regular"):
            continue
        # RTH VWAP is always based on minute HLC3, never on resampled candles.
        # It is absent outside RTH, so extended-hours volume cannot dilute it.
        # Its standard deviation (the range bands' VWAP bands, C2.7) is the
        # volume-weighted spread of the same minute prices around it.
        vwap = sd = None
        if part[0] == "regular":
            typical = (b["high"] + b["low"] + b["close"]) / 3
            pv += typical * b["volume"]
            pv2 += typical * typical * b["volume"]
            volume += b["volume"]
            vwap = pv / volume if volume else None
            sd = sqrt(max(pv2 / volume - vwap * vwap, 0.0)) if volume else None
        anchor = part[1] + ((minute - part[1]) // width) * width
        start = dt.replace(hour=anchor // 60, minute=anchor % 60, second=0, microsecond=0)
        finish = min(anchor + width, part[2])
        end = dt.replace(hour=finish // 60, minute=finish % 60, second=0, microsecond=0)
        _merge(groups, int(start.timestamp()), int(end.timestamp()), b, part[0] != "regular", vwap, sd)
    return indicators(list(groups.values()))


def _merge(groups: dict, stamp: int, end: int, bar: dict, extended: bool, vwap: float | None, sd: float | None):
    if stamp not in groups:
        groups[stamp] = {**bar, "source": bar.get("source", "tradier"), "time": stamp, "end_time": end, "extended": extended, "vwap": vwap,
                         "vwap_sd": sd}
    else:
        b = groups[stamp]
        b.update(high=max(b["high"], bar["high"]), low=min(b["low"], bar["low"]),
                 close=bar["close"], volume=b["volume"] + bar["volume"], vwap=vwap, vwap_sd=sd)


def indicators(bars: list[dict]) -> list[dict]:
    """First-close EMA, Wilder RSI(14); missing warmup remains missing."""
    emas: dict[int, float] = {}
    gains = losses = 0.0
    previous = None
    out = []
    for i, bar in enumerate(bars):
        close = bar["close"]
        row = dict(bar)
        for length in (9, 20, 50, 200):
            emas[length] = close if length not in emas else emas[length] + 2 / (length + 1) * (close - emas[length])
            row[f"ema{length}"] = emas[length] if i + 1 >= length else None
        rsi = None
        if previous is not None:
            gain, loss = max(close - previous, 0), max(previous - close, 0)
            if i <= 14:
                gains += gain / 14
                losses += loss / 14
            else:
                gains = (gains * 13 + gain) / 14
                losses = (losses * 13 + loss) / 14
            if i >= 14:
                rsi = 50.0 if gains == losses == 0 else 100.0 if losses == 0 else 100 - 100 / (1 + gains / losses)
        row["rsi"] = rsi
        previous = close
        out.append(row)
    return out
