"""Time-of-day relative volume for the charts (C2.4). Pure: no network, no files.

A candle's RVol is today's cumulative regular-session volume through that
candle over the average cumulative volume through the same minute of day in
the 20 sessions before today. It is fill context's
``indicators.compute_rvol_time_adjusted`` evaluated at every minute instead of
at one fill: volume counts from 09:30 New York by the clock, a session counts
toward a minute only once it has traded at or after 09:30 by then, and a
minute that fewer than five sessions had reached has no RVol. A half day in
the window therefore counts its whole session for the minutes after its 13:00
close, exactly as fill context does.

The baseline is 390 numbers per symbol per day, one for each regular-session
minute from 09:30 through 15:59. The window is the market calendar's 20
sessions before today, read from the completed SIP sessions the chart history
keeps on disk. A session in the window that is not stored yet means there is
no baseline, never one over fewer sessions. A session stored empty (the
symbol did not trade, for example before it listed) stays in the window and
adds nothing, as a day without bars does in fill context.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Callable, Sequence
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
OPEN = 570  # 09:30 in minutes of the New York day
MINUTES = 390  # 09:30 through 15:59
SESSIONS = 20
MIN_SESSIONS = 5
LOOKBACK_DAYS = 45  # 20 sessions and their holidays fit well inside this

# Cumulative regular-session volume through each minute 09:30–15:59; None before the session has traded.
Profile = tuple[float | None, ...]


@dataclass(frozen=True)
class Baseline:
    sessions: tuple[date, ...]  # the window, oldest first
    traded: tuple[date, ...]  # the window's sessions with regular-session volume
    average: Profile  # per minute; None where fewer than MIN_SESSIONS sessions had traded by then


def _minute(stamp: int) -> int:
    moment = datetime.fromtimestamp(stamp, ET)
    return moment.hour * 60 + moment.minute


def session_profile(minutes: Sequence[dict]) -> Profile:
    """One session's cumulative volume from 09:30 through each minute (that minute's bar
    included); None until a bar at or after 09:30 has traded."""
    volume: dict[int, float] = {}
    for bar in minutes:
        index = _minute(bar["time"]) - OPEN
        if 0 <= index < MINUTES:
            volume[index] = volume.get(index, 0.0) + float(bar["volume"])
    out: list[float | None] = []
    total = None
    for index in range(MINUTES):
        if index in volume:
            total = (total or 0.0) + volume[index]
        out.append(total)
    return tuple(out)


def window(day: date, hours: Callable[[date], dict | None]) -> list[date] | None:
    """The 20 open sessions before ``day``, oldest first, from the market calendar
    (``hours`` is a normalized calendar day); None when the calendar cannot say."""
    found: list[date] = []
    current = day
    for _ in range(LOOKBACK_DAYS):
        current -= timedelta(days=1)
        if current.weekday() >= 5:
            continue
        known = hours(current)
        if known is None:
            return None
        if known.get("status") == "open":
            found.append(current)
            if len(found) == SESSIONS:
                return sorted(found)
    return None


def baseline(profiles: Sequence[tuple[date, Profile]]) -> Baseline:
    """Average the window's profiles minute by minute; each is already on the chart's price basis."""
    average: list[float | None] = []
    for index in range(MINUTES):
        values = [profile[index] for _, profile in profiles if profile[index] is not None]
        average.append(sum(values) / len(values) if len(values) >= MIN_SESSIONS else None)
    return Baseline(tuple(sorted(day for day, _ in profiles)),
                    tuple(sorted(day for day, profile in profiles if profile[-1] is not None)), tuple(average))


def candle_rvol(bars: Sequence[dict], average: Profile, day: date, last_minute: int | None) -> list[float | None]:
    """Each candle's RVol: today's volume through the candle's last minute over the baseline
    at that minute. Only ``day``'s regular-session candles have one.

    ``bars`` are one panel's candles in order, holding ``day``'s regular session
    from its first candle. A candle still forming ends at ``last_minute``, the
    newest minute bar's start in minutes of the New York day.
    """
    out: list[float | None] = []
    total = 0.0
    for bar in bars:
        if bar.get("extended") or datetime.fromtimestamp(bar["time"], ET).date() != day:
            out.append(None)
            continue
        total += bar["volume"]
        through = _minute(bar["end_time"]) - 1
        if last_minute is not None:
            through = min(through, last_minute)
        index = through - OPEN
        expected = average[index] if 0 <= index < MINUTES else None
        out.append(round(total / expected, 4) if expected else None)
    return out
