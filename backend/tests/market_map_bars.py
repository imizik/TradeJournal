"""Synthetic bars for the Market Map tests: fixed days, fixed times, no network.

Prices sit near 100 with a daily ATR of exactly 10, so the ATR-scaled inputs
are round numbers: stop buffer 0.5, retest tolerance 1.0, minimum risk 0.8,
maximum risk 4.0. The benchmark is flat at 100, so relative strength is the
ticker's own percent move since the 9:30 open.

`mirror()` reflects a scenario through 100 (highs become lows), which turns
every long scenario into the matching short one: VWAP, the EMAs and ATR are
all linear in price, so the reflected bars produce the reflected signals.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from app.engine.market_map import ET, Bar, DailyBar

PRIOR_DAY = date(2026, 3, 2)  # Monday
DAY = date(2026, 3, 3)  # Tuesday, the scenario day
NEXT_DAY = date(2026, 3, 4)
ATR = 10.0


def at(day: date, hhmm: int) -> datetime:
    return datetime(day.year, day.month, day.day, hhmm // 100, hhmm % 100, tzinfo=ET)


def hhmm_after(start: int, bars: int, minutes: int = 5) -> int:
    total = start // 100 * 60 + start % 100 + bars * minutes
    return total // 60 * 100 + total % 60


def session(
    day: date,
    closes: list[float],
    *,
    first_open: float | None = None,
    start: int = 930,
    volume: float = 1000.0,
    overrides: dict[int, dict[str, float]] | None = None,
) -> list[Bar]:
    """5-minute bars from `start`. Each bar opens at the previous close and
    spans 0.05 beyond its body unless `overrides[index]` says otherwise."""
    bars = []
    previous = closes[0] if first_open is None else first_open
    for index, close in enumerate(closes):
        values = {
            "open": previous,
            "high": max(previous, close) + 0.05,
            "low": min(previous, close) - 0.05,
            "close": close,
            "volume": volume,
        }
        values.update((overrides or {}).get(index, {}))
        bars.append(
            Bar(
                at(day, hhmm_after(start, index)),
                values["open"],
                values["high"],
                values["low"],
                values["close"],
                values["volume"],
            )
        )
        previous = close
    return bars


def quiet_day(day: date = PRIOR_DAY, price: float = 100.0, volume: float = 1000.0) -> list[Bar]:
    """A full flat session: prior-day high 100.05, low 99.95, 78 bars of history."""
    return session(day, [price] * 78, volume=volume)


def daily_history(before: date = PRIOR_DAY, days: int = 30) -> list[DailyBar]:
    """Weekday daily bars ending the day before `before`, every true range = ATR."""
    bars = []
    current = before - timedelta(days=1)
    while len(bars) < days:
        if current.weekday() < 5:
            bars.append(DailyBar(current, 100.0, 100.0 + ATR / 2, 100.0 - ATR / 2, 100.0))
        current -= timedelta(days=1)
    return sorted(bars, key=lambda bar: bar.day)


def flat_benchmark(bars: list[Bar]) -> list[Bar]:
    return [Bar(bar.time, 100.0, 100.0, 100.0, 100.0, 1000.0) for bar in bars]


def mirror(bars: list[Bar]) -> list[Bar]:
    return [Bar(b.time, 200 - b.open, 200 - b.low, 200 - b.high, 200 - b.close, b.volume) for b in bars]


def mirror_daily(daily: list[DailyBar]) -> list[DailyBar]:
    return [DailyBar(d.day, 200 - d.open, 200 - d.low, 200 - d.high, 200 - d.close) for d in daily]
