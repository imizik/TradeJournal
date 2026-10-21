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


def window(day: date, hours: Callable[[date], dict | None], count: int = SESSIONS) -> list[date] | None:
    """The ``count`` open sessions before ``day`` (20 unless said), oldest first, from the
    market calendar (``hours`` is a normalized calendar day); None when the calendar cannot say."""
    found: list[date] = []
    current = day
    for _ in range(LOOKBACK_DAYS * count // SESSIONS):
        current -= timedelta(days=1)
        if current.weekday() >= 5:
            continue
        known = hours(current)
        if known is None:
            return None
        if known.get("status") == "open":
            found.append(current)
            if len(found) == count:
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


def day_baseline(day: date, hours: dict | None, calendar_hours: Callable[[date], dict | None] | None,
                 profile: Callable[[date], Profile | None], factor: Callable[[date], float],
                 past: bool = False) -> tuple[dict | None, Profile | None]:
    """``day``'s baseline from the stored sessions before it, each scaled by ``factor`` (its
    split factor) onto the chart's price basis. None on a day with no session; otherwise what
    the chart says about it (``state`` and the window), with the baseline only when it is ready.

    ``hours`` is ``day``'s normalized calendar day, None when the calendar is unavailable.
    ``past`` words the messages for an older session (C2.6) instead of today (C2.4).
    """
    before = "it" if past else "today"
    named = day.strftime("%b %-d") if past else "Today"

    def state(name: str, message: str | None, days=(), traded=(), missing=()) -> dict:
        return {"state": name, "day": day.isoformat(), "sessions": [d.isoformat() for d in days],
                "traded": len(traded), "missing": [d.isoformat() for d in missing], "message": message}

    if hours is not None and hours["status"] != "open":
        return None, None
    days = window(day, calendar_hours) if hours is not None and calendar_hours is not None else None
    if days is None:
        return state("unavailable", f"The market calendar is unavailable, so the 20 sessions before {before} cannot be chosen."), None
    if hours["open"] != OPEN:
        return state("unavailable", f"{named}'s regular session does not open at 9:30, so its minutes cannot be compared.", days), None
    profiles, missing = [], []
    for session in days:
        found = profile(session)
        if found is None:
            missing.append(session)
            continue
        # Raw stored volume, multiplied by every split from that session up to the chart's basis.
        scale = factor(session)
        profiles.append((session, found if scale == 1.0 else tuple(None if v is None else v * scale for v in found)))
    if missing:
        where = ("Older candles store them as they load, and each morning stores the 40 sessions before today for watchlist names."
                 if past else "Watchlist names are stored each morning before the open, and any symbol's sessions as its older candles load.")
        return state("building", f"RVol needs the 20 sessions before {before}; {len(missing)} not stored yet. {where}", days, missing=missing), None
    found = baseline(profiles)
    if len(found.traded) < MIN_SESSIONS:
        return state("insufficient", f"Only {len(found.traded)} of the 20 sessions before {before} traded in regular hours; RVol needs "
                     f"{MIN_SESSIONS}.", days, found.traded), None
    return state("ready", None, days, found.traded), found.average


def session_rvol(bars: Sequence[dict], session: Profile, average: Profile, factor: float) -> list[float | None]:
    """A completed session's candles' RVol (C2.6), from that session's own stored profile (raw
    volume, scaled by ``factor`` onto the chart's basis): its volume through each candle's last
    minute over the baseline there. ``bars`` are that session's candles; extended-hours ones have none.
    The same numbers ``candle_rvol`` gives when the whole session's candles are at hand, so a page
    that starts mid-session still counts from 09:30."""
    out: list[float | None] = []
    for bar in bars:
        index = _minute(bar["end_time"]) - 1 - OPEN
        if bar.get("extended") or not 0 <= index < MINUTES:
            out.append(None)
            continue
        through, expected = session[index], average[index]
        out.append(round(through * factor / expected, 4) if expected and through is not None else None)
    return out


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
