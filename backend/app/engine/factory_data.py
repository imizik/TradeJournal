"""The strategy factory's bars: sessions, splits, indicators and entry features.

The factory (`docs/strategy-factory.md`) tests every candidate strategy on
the same data the same way. This module turns one ticker's intraday bars into
a `Series`: regular-session bars only (13:00 closes included), stock splits
taken out, one daily bar per session built from the same bars, and the
session bookkeeping every rule needs. It also computes the indicators the
rules share and the features a filter or a model may read at a signal.

Everything is causal: a value at bar `i` reads bars up to `i` and completed
sessions before it, never later ones. Daily values used intraday are the prior
completed session's, the `request.security(..., "D", x[1], lookahead_on)`
pattern.

Pure: no network, no database. The caller supplies the bars.
"""

from __future__ import annotations

import bisect
import math
from collections import deque
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime

from app.engine.market_map import ET, Bar, DailyBar, daily_from_bars

NA = math.nan
RTH_OPEN = 570
RTH_CLOSE = 960

# NYSE sessions that close at 13:00, confirmed in SIP minute volume through
# 2026-09-24 (the closing cross prints at 12:59-13:00 and 15:59 is nearly
# empty); the 2026 ones are the published schedule.
NYSE_EARLY_CLOSES: dict[date, int] = {
    date(2023, 7, 3): 780,
    date(2023, 11, 24): 780,
    date(2024, 7, 3): 780,
    date(2024, 11, 29): 780,
    date(2024, 12, 24): 780,
    date(2025, 7, 3): 780,
    date(2025, 11, 28): 780,
    date(2025, 12, 24): 780,
    date(2026, 11, 27): 780,
    date(2026, 12, 24): 780,
}


def _minute_of_day(moment: datetime) -> int:
    local = moment.astimezone(ET)
    return local.hour * 60 + local.minute


def session_bars(bars: Iterable[Bar], early_closes: Mapping[date, int] = NYSE_EARLY_CLOSES) -> list[Bar]:
    """Regular-session bars only: 09:30 to the close, 13:00 on early-close days."""
    kept = []
    for bar in bars:
        local = bar.time.astimezone(ET)
        minute = local.hour * 60 + local.minute
        if RTH_OPEN <= minute < early_closes.get(local.date(), RTH_CLOSE):
            kept.append(bar)
    return kept


# --- splits -------------------------------------------------------------------


@dataclass(frozen=True)
class Split:
    """A share split: `day` is the first session at the new price, and older
    prices are divided by `ratio` (10 for a 10-for-1 split, 0.1 for a 1-for-10
    reverse split)."""

    day: date
    ratio: float


def find_splits(daily: Sequence[DailyBar], tolerance: float = 0.04) -> list[Split]:
    """Overnight jumps that are a clean split: the open over the prior close
    within `tolerance` of 1/k or k for a whole k from 2 to 50.

    Minute bars are unadjusted, so a split shows as a jump of exactly that
    size. Ordinary gaps are never that large for these names; a jump that is
    large but not a whole ratio is left alone, as real price action.
    """
    splits = []
    for prior, current in zip(daily, daily[1:]):
        if prior.close <= 0 or current.open <= 0:
            continue
        move = current.open / prior.close
        if 1 / 1.8 < move < 1.8:
            continue
        whole = round(1 / move) if move < 1 else round(move)
        size = 1 / move if move < 1 else move
        if 2 <= whole <= 50 and abs(size / whole - 1) <= tolerance:
            splits.append(Split(current.day, float(whole) if move < 1 else 1 / whole))
    return splits


def adjust_for_splits(bars: Sequence[Bar], splits: Sequence[Split]) -> list[Bar]:
    """Bars before each split on the post-split scale: prices divided by the
    ratio, volume multiplied by it."""
    if not splits:
        return list(bars)
    ordered = sorted(splits, key=lambda split: split.day)
    days = [split.day for split in ordered]
    # factor[k]: the product of the ratios of every split after position k.
    factors = [1.0] * (len(ordered) + 1)
    for k in range(len(ordered) - 1, -1, -1):
        factors[k] = factors[k + 1] * ordered[k].ratio
    adjusted = []
    for bar in bars:
        factor = factors[bisect.bisect_right(days, bar.time.astimezone(ET).date())]
        if factor == 1.0:
            adjusted.append(bar)
        else:
            adjusted.append(
                Bar(bar.time, bar.open / factor, bar.high / factor, bar.low / factor, bar.close / factor, bar.volume * factor)
            )
    return adjusted


# --- the series ----------------------------------------------------------------


@dataclass
class Series:
    """One ticker's regular-session bars on one timeframe, oldest first, in columns.

    `session[i]` numbers the sessions from 0 and `days[s]` is session `s`'s
    date; `last[i]` marks the last bar of its session in the data; `daily[s]`
    is session `s` as one bar. Build it with `Series.build`.
    """

    ticker: str
    timeframe: int
    time: list[datetime]
    open: list[float]
    high: list[float]
    low: list[float]
    close: list[float]
    volume: list[float]
    minute: list[int]
    session: list[int]
    last: list[bool]
    days: list[date]
    daily: list[DailyBar]
    splits: list[Split] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.time)

    @classmethod
    def build(cls, ticker: str, bars: Sequence[Bar], timeframe: int) -> Series:
        """From session bars already on `timeframe` (see `session_bars` and
        `market_map.resample`). Splits are found in the bars' own daily closes
        and taken out."""
        ordered = sorted(bars, key=lambda bar: bar.time)
        splits = find_splits(daily_from_bars(ordered))
        ordered = adjust_for_splits(ordered, splits)
        daily = daily_from_bars(ordered)
        index_of_day = {bar.day: index for index, bar in enumerate(daily)}
        local_days = [bar.time.astimezone(ET).date() for bar in ordered]
        session = [index_of_day[day] for day in local_days]
        last = [k == len(ordered) - 1 or session[k + 1] != session[k] for k in range(len(ordered))]
        return cls(
            ticker=ticker.upper(),
            timeframe=timeframe,
            time=[bar.time for bar in ordered],
            open=[bar.open for bar in ordered],
            high=[bar.high for bar in ordered],
            low=[bar.low for bar in ordered],
            close=[bar.close for bar in ordered],
            volume=[bar.volume for bar in ordered],
            minute=[_minute_of_day(bar.time) for bar in ordered],
            session=session,
            last=last,
            days=[bar.day for bar in daily],
            daily=daily,
            splits=splits,
        )

    def bars(self) -> list[Bar]:
        return [
            Bar(self.time[k], self.open[k], self.high[k], self.low[k], self.close[k], self.volume[k])
            for k in range(len(self))
        ]

    def close_minute(self, i: int) -> int:
        """The minute of day when bar `i` closes, which is when a signal on it can be acted on."""
        return self.minute[i] + self.timeframe

    def index_at(self, moment: datetime) -> int:
        """The last bar that opened at or before `moment`, or -1."""
        return bisect.bisect_right(self.time, moment) - 1


# --- indicators ----------------------------------------------------------------


def ema(values: Sequence[float], length: int) -> list[float]:
    """`ta.ema`: NaN until `length` values, seeded with their simple average."""
    alpha = 2 / (length + 1)
    out: list[float] = []
    value = NA
    for k, source in enumerate(values):
        if math.isnan(value):
            if k + 1 >= length:
                value = sum(values[k + 1 - length : k + 1]) / length
        else:
            value = alpha * source + (1 - alpha) * value
        out.append(value)
    return out


def atr(high: Sequence[float], low: Sequence[float], close: Sequence[float], length: int) -> list[float]:
    """`ta.atr`: Wilder's average of true range, seeded with the simple average;
    the first bar's true range is its high minus its low."""
    out: list[float] = []
    ranges: list[float] = []
    value = NA
    for k in range(len(high)):
        if k == 0:
            true_range = high[k] - low[k]
        else:
            true_range = max(high[k] - low[k], abs(high[k] - close[k - 1]), abs(low[k] - close[k - 1]))
        if math.isnan(value):
            ranges.append(true_range)
            if len(ranges) >= length:
                value = sum(ranges[-length:]) / length
        else:
            value = (value * (length - 1) + true_range) / length
        out.append(value)
    return out


def session_vwap(series: Series) -> list[float]:
    """VWAP of the typical price, reset at each session's first bar."""
    out: list[float] = []
    price_volume = volume = 0.0
    for k in range(len(series)):
        if k == 0 or series.session[k] != series.session[k - 1]:
            price_volume = volume = 0.0
        price_volume += (series.high[k] + series.low[k] + series.close[k]) / 3 * series.volume[k]
        volume += series.volume[k]
        out.append(price_volume / volume if volume > 0 else NA)
    return out


def daily_ema(series: Series, length: int) -> list[float]:
    """The EMA of daily closes, one value per session (through that session's close)."""
    return ema([bar.close for bar in series.daily], length)


def daily_atr(series: Series, length: int) -> list[float]:
    """ATR of the daily bars, one value per session (through that session's close)."""
    return atr([bar.high for bar in series.daily], [bar.low for bar in series.daily],
               [bar.close for bar in series.daily], length)


def prior(values: Sequence[float], session: int, lag: int = 1) -> float:
    """A per-session value `lag` completed sessions before `session`, or NaN."""
    index = session - lag
    return values[index] if 0 <= index < len(values) else NA


# --- features --------------------------------------------------------------------

# What a filter or a model may read at a signal. Direction-sensitive features
# are signed by the trade's side, so a positive value is "with the trade" for
# longs and shorts alike. Daily values are the prior completed session's.
FEATURES: dict[str, str] = {
    "minutes": "minutes from 09:30 to the signal bar's close",
    "rvol": "session volume so far over its average at the same time of day across the prior 10 sessions",
    "gap": "the session's opening gap from the prior close, in daily ATR(14)",
    "day_move": "the signal close against the session open, in daily ATR",
    "trend": "the signal close against the prior day's daily EMA 20, in daily ATR",
    "trend_slope": "the daily EMA 20's change over the prior five sessions, in daily ATR",
    "rel_strength": "percent return since the close five sessions ago, minus SPY's over the same span",
    "spy_trend": "SPY against its prior daily EMA 20, in SPY's daily ATR",
    "spy_day": "SPY against its session open, in SPY's daily ATR",
    "risk": "the signal close to the stop, in ATR(14) of the chart bars",
    "vwap_distance": "the signal close against the session VWAP, in ATR(14) of the chart bars",
    "vol_ratio": "the daily ATR(5) over the daily ATR(20): above 1 when the last week moved more than the month",
    "spy_vol": "SPY's daily ATR(14) as a percent of its close: the market's volatility level",
    "open_trend": "the session's open against the prior day's daily EMA 20, in daily ATR: where the day started "
                  "against the level `trend` measures the signal from",
}

RVOL_SESSIONS = 10
RVOL_MIN_SESSIONS = 5
LOOKBACK_SESSIONS = 5


def _ratio(numerator: float, denominator: float) -> float:
    if math.isnan(numerator) or math.isnan(denominator) or denominator == 0:
        return NA
    return numerator / denominator


class _Daily:
    """The daily values the features read, for one series."""

    def __init__(self, series: Series):
        self.series = series
        self.ema = daily_ema(series, 20)
        self.atr = daily_atr(series, 14)
        self.atr_week = daily_atr(series, 5)
        self.atr_month = daily_atr(series, 20)
        self.closes = [bar.close for bar in series.daily]
        self.opens = [bar.open for bar in series.daily]


class FeatureContext:
    """The features of any bar of one series, with SPY as the market."""

    def __init__(self, series: Series, market: Series | None):
        self.series = series
        self.daily = _Daily(series)
        self.market = _Daily(market) if market is not None else None
        self.chart_atr = atr(series.high, series.low, series.close, 14)
        self.vwap = session_vwap(series)
        self.rvol = _time_of_day_rvol(series)

    def at(self, i: int, side: int, stop: float) -> dict[str, float]:
        s = self.series
        d = self.daily
        session = s.session[i]
        close = s.close[i]
        day_atr = prior(d.atr, session)
        day_ema = prior(d.ema, session)
        session_open = d.opens[session]
        base = prior(d.closes, session, LOOKBACK_SESSIONS)
        values = {
            "minutes": float(s.close_minute(i) - RTH_OPEN),
            "rvol": self.rvol[i],
            "gap": side * _ratio(session_open - prior(d.closes, session), day_atr),
            "day_move": side * _ratio(close - session_open, day_atr),
            "trend": side * _ratio(close - day_ema, day_atr),
            "trend_slope": side * _ratio(day_ema - prior(d.ema, session, 1 + LOOKBACK_SESSIONS), day_atr),
            "rel_strength": NA,
            "spy_trend": NA,
            "spy_day": NA,
            "risk": _ratio(abs(close - stop), self.chart_atr[i]),
            "vwap_distance": side * _ratio(close - self.vwap[i], self.chart_atr[i]),
            "vol_ratio": _ratio(prior(d.atr_week, session), prior(d.atr_month, session)),
            "spy_vol": NA,
            "open_trend": side * _ratio(session_open - day_ema, day_atr),
        }
        m = self.market
        if m is not None:
            j = m.series.index_at(s.time[i])
            if j >= 0 and m.series.days[m.series.session[j]] == s.days[session]:
                market_session = m.series.session[j]
                market_close = m.series.close[j]
                market_atr = prior(m.atr, market_session)
                market_base = prior(m.closes, market_session, LOOKBACK_SESSIONS)
                values["spy_trend"] = side * _ratio(market_close - prior(m.ema, market_session), market_atr)
                values["spy_day"] = side * _ratio(market_close - m.opens[market_session], market_atr)
                values["spy_vol"] = 100 * _ratio(market_atr, prior(m.closes, market_session))
                own = _ratio(close, base) - 1
                market = _ratio(market_close, market_base) - 1
                values["rel_strength"] = side * 100 * (own - market)
        return values


def _time_of_day_rvol(series: Series) -> list[float]:
    """Cumulative session volume through each bar over its average at the same
    minute across the prior `RVOL_SESSIONS` sessions (NaN with fewer than
    `RVOL_MIN_SESSIONS` of them)."""
    history: dict[int, deque[float]] = {}
    out: list[float] = []
    cumulative = 0.0
    for k in range(len(series)):
        if k == 0 or series.session[k] != series.session[k - 1]:
            cumulative = 0.0
        cumulative += series.volume[k]
        past = history.setdefault(series.minute[k], deque(maxlen=RVOL_SESSIONS))
        if len(past) >= RVOL_MIN_SESSIONS:
            out.append(_ratio(cumulative, sum(past) / len(past)))
        else:
            out.append(NA)
        past.append(cumulative)
    return out
