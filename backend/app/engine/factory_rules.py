"""The strategy factory's rules: entry families, one execution model, and specs.

A candidate strategy is a spec (`research/specs/*.json`): a family of entry
rules with its settings, the exits, the costs, an entry window, session loss
limits, and optional filters. New ideas are mostly new settings; a new family
is a small class here and a synthetic-bar test.

Every candidate, and the every-bar baseline it is judged against, goes
through the same execution model, the one the Market Map, VWAP reclaim and
NBIS swing backtests use:

- A signal is decided at a bar's close; the entry is a market order at the
  next bar's open, slipped by the larger of a tick count and basis points.
  An order still unfilled at a session's end expires unless the exits allow
  holding overnight.
- The stop is frozen at the signal. If the open (or the slipped fill) is
  already through it, there is no trade. R is the price risk from the fill
  to the stop, and the target is `target_r` R from the fill.
- The stop and the target rest from the fill. A bar that opens through
  either fills at that open (overnight gaps included); when one bar reaches
  both, the stop fills first. Stops and closing exits slip; targets do not.
- At a bar's close the trade leaves if it has held `max_minutes`, or at the
  last bar of its `max_sessions`-th session (the entry session is the first).
- Candidates hold one position at a time per ticker, and the session loss
  limits stop new entries for the rest of a session. The baseline takes every
  signal as its own trade.

Pure: no network, no database. The caller supplies the bars.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field, fields, replace
from datetime import datetime, timedelta
from typing import Any, Protocol

from app.engine.factory_data import FEATURES, NA, FeatureContext, Series, atr, ema, prior, daily_ema, session_vwap

# --- signals, trades, and the settings every family shares ----------------------


@dataclass(frozen=True)
class Signal:
    """Enter `side` (1 long, -1 short) at the open after bar `index`, stop at `stop`."""

    index: int
    side: int
    stop: float


@dataclass(frozen=True)
class Context:
    """What the runner tells a family at each bar's close.

    `flat`: no position (a pending order has always filled or failed by now).
    `halted`: the session loss limits allow no new entry this session.
    `accept`: whether a proposed signal may become an order (not halted, in
    the entry window, through the filters and the model); a family that gets
    False treats the signal as rejected and consumes the setup.
    """

    flat: bool
    halted: bool
    accept: Callable[[Signal], bool]


@dataclass(frozen=True)
class Exits:
    target_r: float | None = 2.0
    max_sessions: int = 1
    max_minutes: int | None = None


@dataclass(frozen=True)
class Costs:
    slippage_ticks: float = 1.0
    slippage_bps: float = 1.0
    tick_size: float = 0.01

    def slip(self, price: float) -> float:
        return max(self.slippage_ticks * self.tick_size, price * self.slippage_bps / 10_000)

    def times(self, factor: float) -> Costs:
        return replace(self, slippage_ticks=self.slippage_ticks * factor, slippage_bps=self.slippage_bps * factor)


@dataclass(frozen=True)
class Limits:
    """Per ticker and session: no new entry after `max_entries` fills, after
    `max_losses` losing trades, or once the session's closed trades reach
    -`max_loss_r`."""

    max_entries: int | None = None
    max_losses: int | None = None
    max_loss_r: float | None = None

    def halted(self, entries: int, losses: int, session_r: float) -> bool:
        return (
            (self.max_entries is not None and entries >= self.max_entries)
            or (self.max_losses is not None and losses >= self.max_losses)
            or (self.max_loss_r is not None and session_r <= -self.max_loss_r)
        )


@dataclass
class Trade:
    ticker: str
    side: int
    signal_index: int
    signal_time: datetime
    entry_index: int
    entry_time: datetime
    entry_price: float
    stop: float
    target: float | None
    exit_index: int | None = None
    exit_time: datetime | None = None
    exit_price: float | None = None
    exit_reason: str = ""
    sessions_held: int = 1
    both_hit: bool = False
    features: dict[str, float] = field(default_factory=dict)

    @property
    def closed(self) -> bool:
        return self.exit_price is not None

    @property
    def risk(self) -> float:
        return self.side * (self.entry_price - self.stop)

    @property
    def r(self) -> float:
        if self.exit_price is None:
            return NA
        return self.side * (self.exit_price - self.entry_price) / self.risk


# --- the execution model ---------------------------------------------------------


def _enter(series: Series, signal: Signal, i: int, exits: Exits, costs: Costs) -> Trade | None:
    """The order from `signal` at bar `i`'s open, or None when that open or its fill is through the stop."""
    side, stop = signal.side, signal.stop
    price = series.open[i]
    if side * (price - stop) <= 0:
        return None
    fill = price + side * costs.slip(price)
    if side * (fill - stop) <= 0:
        return None
    risk = side * (fill - stop)
    target = None if exits.target_r is None else round(fill + side * exits.target_r * risk, 10)
    return Trade(
        ticker=series.ticker,
        side=side,
        signal_index=signal.index,
        signal_time=series.time[signal.index],
        entry_index=i,
        entry_time=series.time[i],
        entry_price=round(fill, 10),
        stop=stop,
        target=target,
    )


def _close(trade: Trade, series: Series, i: int, price: float, reason: str) -> None:
    trade.exit_index = i
    trade.exit_time = series.time[i]
    trade.exit_price = round(price, 10)
    trade.exit_reason = reason
    trade.sessions_held = series.session[i] - series.session[trade.entry_index] + 1


def _step(series: Series, trade: Trade, i: int, exits: Exits, costs: Costs) -> bool:
    """Bar `i` for an open trade: the resting stop and target, then the
    closing exits. True when the trade closed."""
    side, stop, target = trade.side, trade.stop, trade.target
    o, h, lo, c = series.open[i], series.high[i], series.low[i], series.close[i]
    if side * (o - stop) <= 0:
        _close(trade, series, i, o - side * costs.slip(o), "stop")
        return True
    if target is not None and side * (o - target) >= 0:
        _close(trade, series, i, o, "target")
        return True
    stop_hit = lo <= stop if side == 1 else h >= stop
    target_hit = target is not None and (h >= target if side == 1 else lo <= target)
    if stop_hit:
        trade.both_hit = target_hit
        _close(trade, series, i, stop - side * costs.slip(stop), "stop")
        return True
    if target_hit:
        _close(trade, series, i, target, "target")
        return True
    held = series.session[i] - series.session[trade.entry_index] + 1
    if series.last[i] and held >= exits.max_sessions:
        _close(trade, series, i, c - side * costs.slip(c), "session")
        return True
    if exits.max_minutes is not None:
        closes_at = series.time[i] + timedelta(minutes=series.timeframe)
        if closes_at - trade.entry_time >= timedelta(minutes=exits.max_minutes):
            _close(trade, series, i, c - side * costs.slip(c), "time")
            return True
    return False


class Family(Protocol):
    def on_bar(self, i: int, ctx: Context) -> Signal | None: ...


def run_candidate(
    series: Series,
    family: Family,
    exits: Exits,
    costs: Costs,
    window: tuple[int, int] | None = None,
    limits: Limits = Limits(),
    accept: Callable[[Signal], bool] | None = None,
    features: FeatureContext | None = None,
) -> list[Trade]:
    """Run a family over the series, one position at a time. Trades still open
    at the end of the bars are returned open (`closed` is False)."""
    trades: list[Trade] = []
    pending: Signal | None = None
    position: Trade | None = None
    entries = losses = 0
    session_r = 0.0
    overnight = exits.max_sessions > 1

    def allowed(signal: Signal, halted: bool) -> bool:
        if halted:
            return False
        if window is not None and not window[0] <= series.close_minute(signal.index) <= window[1]:
            return False
        return accept is None or accept(signal)

    for i in range(len(series)):
        if i and series.session[i] != series.session[i - 1]:
            entries = losses = 0
            session_r = 0.0
            if pending is not None and not overnight:
                pending = None
        if pending is not None:
            position = _enter(series, pending, i, exits, costs)
            if position is not None:
                if features is not None:
                    position.features = features.at(pending.index, pending.side, pending.stop)
                trades.append(position)
                entries += 1
            pending = None
        if position is not None and _step(series, position, i, exits, costs):
            losses += position.r < 0
            session_r += position.r
            position = None
        halted = limits.halted(entries, losses, session_r)
        ctx = Context(position is None, halted, lambda proposed: allowed(proposed, halted))
        signal = family.on_bar(i, ctx)
        if signal is not None:
            if position is not None:
                raise RuntimeError(f"{type(family).__name__} signalled while a position was open")
            pending = signal
    return trades


def run_each(series: Series, signals: Sequence[Signal], exits: Exits, costs: Costs) -> list[Trade]:
    """Every signal as its own trade, overlapping allowed: the every-bar baseline."""
    trades = []
    overnight = exits.max_sessions > 1
    for signal in signals:
        i = signal.index + 1
        if i >= len(series) or (not overnight and series.session[i] != series.session[signal.index]):
            continue
        trade = _enter(series, signal, i, exits, costs)
        if trade is None:
            continue
        for k in range(i, len(series)):
            if _step(series, trade, k, exits, costs):
                break
        trades.append(trade)
    return trades


# --- stops for the baseline -------------------------------------------------------


@dataclass(frozen=True)
class SwingStop:
    """Beyond the extreme of the last `bars` bars (the signal bar included), by `atr_buffer` ATR."""

    bars: int
    atr_buffer: float
    atr_length: int = 14

    def describe(self) -> str:
        return f"{self.atr_buffer:g} ATR beyond the last {self.bars} bars' extreme"


@dataclass(frozen=True)
class AtrStop:
    """`multiple` ATR from the signal close."""

    multiple: float
    atr_length: int = 14

    def describe(self) -> str:
        return f"{self.multiple:.2f} ATR from the signal close"


# The baseline stop of a family whose stop depends on its setup: an AtrStop
# at the candidate's own median risk in ATR, measured per period.
MATCHED = "matched"


def baseline_signals(
    series: Series,
    stop: SwingStop | AtrStop,
    sides: Sequence[int],
    first_day,
    last_day,
    window: tuple[int, int] | None = None,
    stride: int = 1,
) -> list[Signal]:
    """A signal at every bar from `first_day` to `last_day` (every `stride`-th
    bar, the offset turning with the session so every time of day is sampled)."""
    values = atr(series.high, series.low, series.close, stop.atr_length)
    signals = []
    position_in_session = 0
    for i in range(len(series)):
        if i and series.session[i] != series.session[i - 1]:
            position_in_session = 0
        else:
            position_in_session += i > 0
        day = series.days[series.session[i]]
        if day < first_day or day > last_day or math.isnan(values[i]):
            continue
        if (position_in_session + series.session[i]) % stride:
            continue
        if window is not None and not window[0] <= series.close_minute(i) <= window[1]:
            continue
        for side in sides:
            if isinstance(stop, SwingStop):
                if i + 1 < stop.bars:
                    continue
                if side == 1:
                    level = min(series.low[i + 1 - stop.bars : i + 1]) - stop.atr_buffer * values[i]
                else:
                    level = max(series.high[i + 1 - stop.bars : i + 1]) + stop.atr_buffer * values[i]
            else:
                level = series.close[i] - side * stop.multiple * values[i]
            signals.append(Signal(i, side, level))
    return signals


# --- families ---------------------------------------------------------------------


def _sides(value: str) -> tuple[int, ...]:
    return {"long": (1,), "short": (-1,), "both": (1, -1)}[value]


@dataclass(frozen=True)
class RecoverySwing:
    """The NBIS recovery swing (docs/pine/nbis-swing.md), long only.

    Arm once a bar trades below the prior completed day's daily EMA; the arm
    lasts `arm_sessions` sessions and triggers once, and trading below again
    re-arms. Trigger on a close back above the reclaim level (the chart EMA,
    or with `reclaim_level="daily_ema"` the daily EMA) after a close at or
    below it, that also clears the prior `breakout_bars` highs. The arming bar
    never triggers. Stop: `atr_buffer` ATR under the last `stop_bars` lows.
    """

    daily_ema_length: int = 20
    ema_length: int = 20
    reclaim_level: str = "ema"
    breakout_bars: int = 3
    stop_bars: int = 4
    atr_length: int = 14
    atr_buffer: float = 0.1
    arm_sessions: int = 2

    defaults = {"timeframe": 15, "exits": {"target_r": 2.0, "max_sessions": 2}}
    sides = (1,)

    def validate(self) -> None:
        if self.reclaim_level not in ("ema", "daily_ema"):
            raise ValueError("reclaim_level must be 'ema' or 'daily_ema'")

    def baseline_stop(self) -> SwingStop | str:
        return SwingStop(self.stop_bars, self.atr_buffer, self.atr_length)

    def start(self, series: Series) -> _RecoverySwingRun:
        return _RecoverySwingRun(self, series)


class _RecoverySwingRun:
    def __init__(self, rules: RecoverySwing, series: Series):
        self.p = rules
        self.s = series
        self.ema = ema(series.close, rules.ema_length)
        self.atr = atr(series.high, series.low, series.close, rules.atr_length)
        levels = daily_ema(series, rules.daily_ema_length)
        self.level = [prior(levels, session) for session in series.session]
        self.armed = False
        self.armed_until = -1

    def on_bar(self, i: int, ctx: Context) -> Signal | None:
        p, s = self.p, self.s
        session, close, level = s.session[i], s.close[i], self.level[i]
        signal = None
        if ctx.flat and self.armed and session <= self.armed_until:
            if p.reclaim_level == "ema":
                reclaim, before = self.ema[i], self.ema[i - 1] if i else NA
            else:
                reclaim = before = level
            breakout = i >= p.breakout_bars and close > max(s.high[i - p.breakout_bars : i])
            if (
                not math.isnan(before)
                and not math.isnan(self.atr[i])
                and s.close[i - 1] <= before
                and close > reclaim
                and breakout
            ):
                self.armed = False
                stop = min(s.low[max(0, i + 1 - p.stop_bars) : i + 1]) - p.atr_buffer * self.atr[i]
                proposed = Signal(i, 1, stop)
                if ctx.accept(proposed):
                    signal = proposed
        elif self.armed and session > self.armed_until:
            self.armed = False
        if signal is None and ctx.flat and not math.isnan(level) and s.low[i] < level:
            self.armed = True
            self.armed_until = session + p.arm_sessions - 1
        return signal


@dataclass
class _Setup:
    bar: int
    level: float  # what the confirmation must close beyond
    extreme: float  # where the stop goes, tracked from the arming bar


@dataclass(frozen=True)
class VwapReclaim:
    """The VWAP reclaim/rejection (docs/pine/vwap-reclaim.md), both sides.

    Arm a long when the previous bar of the session closed at or below VWAP
    and this one closes above VWAP and the EMA; a short is the mirror. Within
    `confirm_bars` bars a close beyond the arming bar's high (low) confirms,
    and a close back through VWAP cancels; a setup triggers once. A
    confirmation more than `chase_atr` ATR from VWAP is rejected. Stop:
    `atr_buffer` ATR beyond the setup's extreme from arming through
    confirmation.
    """

    ema_length: int = 9
    atr_length: int = 14
    atr_buffer: float = 0.1
    confirm_bars: int = 3
    chase_atr: float = 1.0
    sides: str = "both"

    defaults = {
        "timeframe": 1,
        "exits": {"target_r": 1.5, "max_sessions": 1, "max_minutes": 20},
        "window": [935, 1500],
        "limits": {"max_entries": 2, "max_losses": 2, "max_loss_r": 2.0},
    }

    def validate(self) -> None:
        _sides(self.sides)

    def baseline_stop(self) -> SwingStop | str:
        return MATCHED

    def start(self, series: Series) -> _VwapReclaimRun:
        return _VwapReclaimRun(self, series)


class _VwapReclaimRun:
    def __init__(self, rules: VwapReclaim, series: Series):
        self.p = rules
        self.s = series
        self.vwap = session_vwap(series)
        self.ema = ema(series.close, rules.ema_length)
        self.atr = atr(series.high, series.low, series.close, rules.atr_length)
        self.allowed = _sides(rules.sides)
        self.pending: dict[int, _Setup | None] = {1: None, -1: None}
        self.session = -1

    def on_bar(self, i: int, ctx: Context) -> Signal | None:
        p, s = self.p, self.s
        if s.session[i] != self.session:
            self.session = s.session[i]
            self.pending = {1: None, -1: None}
        c, vwap, atr_value = s.close[i], self.vwap[i], self.atr[i]
        signal = None
        if ctx.flat:
            for side in (1, -1):
                setup = self.pending[side]
                if setup is None:
                    continue
                setup.extreme = min(setup.extreme, s.low[i]) if side == 1 else max(setup.extreme, s.high[i])
                if side * (c - vwap) < 0:
                    self.pending[side] = None
                elif side * (c - setup.level) > 0:
                    self.pending[side] = None
                    if ctx.halted or not atr_value > 0 or abs(c - vwap) > p.chase_atr * atr_value:
                        continue
                    proposed = Signal(i, side, setup.extreme - side * p.atr_buffer * atr_value)
                    if not ctx.accept(proposed):
                        continue
                    signal = proposed
                    self.pending = {1: None, -1: None}
                    break
                elif i - setup.bar >= p.confirm_bars:
                    self.pending[side] = None
        if signal is None and ctx.flat and not ctx.halted:
            ready = (
                i > 0
                and s.session[i - 1] == s.session[i]
                and not math.isnan(vwap)
                and not math.isnan(self.vwap[i - 1])
                and not math.isnan(self.ema[i])
                and not math.isnan(atr_value)
            )
            for side in self.allowed:
                if not ready or self.pending[side] is not None:
                    continue
                came_from_other_side = side * (s.close[i - 1] - self.vwap[i - 1]) <= 0
                if came_from_other_side and side * (c - vwap) > 0 and side * (c - self.ema[i]) > 0:
                    high, low = s.high[i], s.low[i]
                    self.pending[side] = _Setup(i, high if side == 1 else low, low if side == 1 else high)
        return signal


@dataclass(frozen=True)
class FailedBreakout:
    """The failed breakout (the research framework's META module): short by
    default, the long mirror at the prior day's low with `sides`.

    Arm on a rejection bar: it trades above the prior session's high and
    closes back below it. Within `confirm_bars` bars a close below the
    rejection bar's low confirms, and a close back above the prior high
    cancels; a setup triggers once. Stop: `atr_buffer` ATR beyond the
    rejection bar's high. The confirmation window and the cancel rule are
    this module's reading; the framework leaves both open.
    """

    atr_length: int = 14
    atr_buffer: float = 0.1
    confirm_bars: int = 3
    sides: str = "short"

    defaults = {
        "timeframe": 1,
        "exits": {"target_r": 1.5, "max_sessions": 1, "max_minutes": 20},
        "window": [935, 1500],
        "limits": {"max_entries": 2, "max_losses": 2, "max_loss_r": 2.0},
    }

    def validate(self) -> None:
        _sides(self.sides)

    def baseline_stop(self) -> SwingStop | str:
        return MATCHED

    def start(self, series: Series) -> _FailedBreakoutRun:
        return _FailedBreakoutRun(self, series)


class _FailedBreakoutRun:
    def __init__(self, rules: FailedBreakout, series: Series):
        self.p = rules
        self.s = series
        self.atr = atr(series.high, series.low, series.close, rules.atr_length)
        self.allowed = _sides(rules.sides)
        self.pending: dict[int, _Setup | None] = {1: None, -1: None}
        self.session = -1

    def on_bar(self, i: int, ctx: Context) -> Signal | None:
        p, s = self.p, self.s
        session = s.session[i]
        if session != self.session:
            self.session = session
            self.pending = {1: None, -1: None}
        if session == 0:
            return None
        levels = {-1: s.daily[session - 1].high, 1: s.daily[session - 1].low}
        c, atr_value = s.close[i], self.atr[i]
        signal = None
        if ctx.flat:
            for side in (1, -1):
                setup = self.pending[side]
                if setup is None:
                    continue
                if side * (c - levels[side]) < 0:
                    self.pending[side] = None
                elif side * (c - setup.level) > 0:
                    self.pending[side] = None
                    if ctx.halted or not atr_value > 0:
                        continue
                    proposed = Signal(i, side, setup.extreme - side * p.atr_buffer * atr_value)
                    if not ctx.accept(proposed):
                        continue
                    signal = proposed
                    self.pending = {1: None, -1: None}
                    break
                elif i - setup.bar >= p.confirm_bars:
                    self.pending[side] = None
        if signal is None and ctx.flat and not ctx.halted and not math.isnan(atr_value):
            for side in self.allowed:
                if self.pending[side] is not None:
                    continue
                level, high, low = levels[side], s.high[i], s.low[i]
                if side == -1 and high > level and c < level:
                    self.pending[side] = _Setup(i, low, high)
                elif side == 1 and low < level and c > level:
                    self.pending[side] = _Setup(i, high, low)
        return signal


FAMILIES: dict[str, type] = {
    "recovery_swing": RecoverySwing,
    "vwap_reclaim": VwapReclaim,
    "failed_breakout": FailedBreakout,
}


def family_sides(family: Any) -> tuple[int, ...]:
    sides = family.sides
    return sides if isinstance(sides, tuple) else _sides(sides)


# --- specs --------------------------------------------------------------------------

# The universe every candidate trades unless its spec names tickers: liquid
# names from the 2026 journal and its comparison list. SPY is the market.
CORE_UNIVERSE = (
    "NBIS", "MU", "META", "AAPL", "AMD", "LLY", "TSLA", "GOOG", "AMZN",
    "NFLX", "NVDA", "MSFT", "AVGO", "COIN", "GS", "CAT", "MRVL", "PLTR",
)
MARKET = "SPY"


@dataclass(frozen=True)
class RuleFilter:
    """Take a signal only when `feature` is within [low, high] (either may be open)."""

    feature: str
    low: float | None = None
    high: float | None = None

    def passes(self, values: Mapping[str, float]) -> bool:
        value = values.get(self.feature, NA)
        if math.isnan(value):
            return False
        return (self.low is None or value >= self.low) and (self.high is None or value <= self.high)

    def describe(self) -> str:
        bounds = [f">= {self.low:g}" if self.low is not None else "", f"<= {self.high:g}" if self.high is not None else ""]
        return f"{self.feature} " + " and ".join(b for b in bounds if b)


@dataclass(frozen=True)
class ModelSpec:
    """A learned filter on the family's own trades (meta-labeling): trained on
    the discovery period's trades of the same spec without the model, then
    frozen. `kind` is "logistic": the probability that a trade ends positive,
    taken when it is at least the training base rate."""

    kind: str = "logistic"
    features: tuple[str, ...] = tuple(FEATURES)
    l2: float = 1.0


@dataclass(frozen=True)
class Spec:
    name: str
    family: str
    params: tuple[tuple[str, Any], ...]
    timeframe: int
    exits: Exits
    costs: Costs
    window: tuple[int, int] | None
    limits: Limits
    filters: tuple[RuleFilter, ...]
    model: ModelSpec | None
    tickers: tuple[str, ...]
    notes: str = ""

    def rules(self) -> Any:
        return FAMILIES[self.family](**dict(self.params))

    def parent(self) -> Spec | None:
        """The same spec without its model, which the model learns from."""
        return None if self.model is None else replace(self, model=None, name=f"{self.name} (without the model)")


def _hhmm(value: int) -> int:
    return value // 100 * 60 + value % 100


def parse_spec(data: Mapping[str, Any]) -> Spec:
    """A spec from its JSON form, with the family's defaults filled in."""
    known = {"name", "notes", "family", "params", "timeframe", "exits", "costs", "window", "limits",
             "filters", "model", "tickers"}
    unknown = set(data) - known
    if unknown:
        raise ValueError(f"unknown spec keys: {sorted(unknown)}")
    family = data.get("family")
    if family not in FAMILIES:
        raise ValueError(f"family must be one of {sorted(FAMILIES)}, got {family!r}")
    cls = FAMILIES[family]
    params = dict(data.get("params") or {})
    names = {f.name for f in fields(cls)}
    if set(params) - names:
        raise ValueError(f"{family} has no settings {sorted(set(params) - names)}; it has {sorted(names)}")
    rules = cls(**params)
    rules.validate()
    defaults = cls.defaults
    exits = Exits(**{**{"target_r": None, "max_sessions": 1, "max_minutes": None},
                     **defaults.get("exits", {}), **(data.get("exits") or {})})
    if exits.max_sessions < 1:
        raise ValueError("max_sessions must be at least 1")
    window = data["window"] if "window" in data else defaults.get("window")
    limits = Limits(**{**defaults.get("limits", {}), **(data.get("limits") or {})})
    filters = []
    for item in data.get("filters") or []:
        if item.get("feature") not in FEATURES:
            raise ValueError(f"filter feature must be one of {sorted(FEATURES)}, got {item.get('feature')!r}")
        filters.append(RuleFilter(item["feature"], item.get("min"), item.get("max")))
    model = None
    if data.get("model"):
        raw = dict(data["model"])
        if raw.get("kind", "logistic") != "logistic":
            raise ValueError("model kind must be 'logistic'")
        chosen = tuple(raw.get("features") or FEATURES)
        if set(chosen) - set(FEATURES):
            raise ValueError(f"model features must come from {sorted(FEATURES)}")
        model = ModelSpec("logistic", chosen, float(raw.get("l2", 1.0)))
    tickers = data.get("tickers") or "core"
    tickers = CORE_UNIVERSE if tickers == "core" else tuple(t.upper() for t in tickers)
    timeframe = int(data.get("timeframe") or defaults["timeframe"])
    if timeframe <= 0 or 30 % timeframe:
        raise ValueError("timeframe must divide 30 minutes (1, 2, 3, 5, 10, 15, 30)")
    return Spec(
        name=str(data.get("name") or family),
        family=family,
        params=tuple(sorted(asdict(rules).items())),
        timeframe=timeframe,
        exits=exits,
        costs=Costs(**(data.get("costs") or {})),
        window=None if window is None else (_hhmm(int(window[0])), _hhmm(int(window[1]))),
        limits=limits,
        filters=tuple(filters),
        model=model,
        tickers=tickers,
        notes=str(data.get("notes") or ""),
    )


def canonical(spec: Spec) -> dict[str, Any]:
    """Everything that decides the trades, in a stable form. The name and notes are left out."""
    return {
        "family": spec.family,
        "params": dict(spec.params),
        "timeframe": spec.timeframe,
        "exits": asdict(spec.exits),
        "costs": asdict(spec.costs),
        "window": list(spec.window) if spec.window else None,
        "limits": asdict(spec.limits),
        "filters": [asdict(f) for f in spec.filters],
        "model": None if spec.model is None else {**asdict(spec.model), "features": list(spec.model.features)},
        "tickers": list(spec.tickers),
    }


def spec_id(spec: Spec) -> str:
    """A short, stable id for the rules: the same rules get the same id whatever they are called."""
    text = json.dumps(canonical(spec), sort_keys=True, separators=(",", ":"))
    return spec.family[:2] + "-" + hashlib.sha256(text.encode()).hexdigest()[:10]
