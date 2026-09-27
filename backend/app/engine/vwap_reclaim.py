"""VWAP reclaim/rejection, version 0.1, as a pure backtest engine.

This is the "first build" of the Pine research framework written from the 2026
journal (MU intraday reclaim/rejection). Every number is the framework's
proposed research default; none was fitted to bars:

- Regular-session one-minute bars. VWAP resets at 09:30 America/New_York.
- Arm a long when the previous bar closed at or below its session VWAP and
  this bar closes above VWAP and above EMA 9. A short is the mirror. The
  arming bar never enters.
- Within the next three bars, a close above the arming bar's high (long) or
  below its low (short) confirms. A close back through VWAP cancels the
  setup, and a setup triggers at most once.
- A confirmation more than 1.0 ATR(14) from VWAP is rejected (no chasing),
  and so is one whose fill would fall outside 09:35-15:00.
- Entry at the next bar's open. The stop is the setup's extreme from arming
  through confirmation, 0.1 ATR beyond it, frozen. R is the price risk from
  the fill to the stop; the target is 1.5R; a trade still open 20 minutes
  after the fill exits; anything open at the session close is flattened,
  early closes included.
- At most two entries a session, and none after two losing trades or a
  realized -2R.

Execution: signals on bar close, market entries at the next bar's open, the
stop and target rest from the fill. A bar that opens through either fills at
the open; when one bar reaches both, the stop is assumed to fill first (the
framework's conservative assumption, `both_hit`). Market and stop fills slip
by the larger of `slippage_ticks` ticks and `slippage_bps` of price.

Pure: no network, no database. The caller supplies the bars.
"""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from app.engine.market_map import ET, Bar
from app.engine.market_map_report import pine_number

NA = math.nan
RTH_OPEN = 570
RTH_CLOSE = 960

# NYSE sessions that close at 13:00. The 2024-2025 ones are confirmed in SIP
# minute volume (the closing cross prints at 13:00 and 15:59 is nearly empty).
NYSE_EARLY_CLOSES: dict[date, int] = {
    date(2024, 7, 3): 780,
    date(2024, 11, 29): 780,
    date(2024, 12, 24): 780,
    date(2025, 7, 3): 780,
    date(2025, 11, 28): 780,
    date(2025, 12, 24): 780,
    date(2026, 11, 27): 780,
    date(2026, 12, 24): 780,
}

SETUP_NAMES = {1: "vwap_reclaim", -1: "vwap_rejection"}


@dataclass(frozen=True)
class ReclaimConfig:
    """The framework's inputs, with its proposed defaults."""

    version: str = "0.1"
    ema_length: int = 9
    atr_length: int = 14
    atr_buffer: float = 0.1
    confirm_bars: int = 3
    chase_atr: float = 1.0
    target_r: float = 1.5
    max_hold_min: int = 20
    entry_start: int = 935  # HHMM: the earliest fill
    entry_end: int = 1500  # HHMM: the latest fill
    max_entries: int = 2
    max_losses: int = 2
    max_session_loss_r: float = 2.0
    allow_longs: bool = True
    allow_shorts: bool = True
    both_hit: str = "stop"  # which fills when one bar reaches the stop and the target
    slippage_ticks: int = 1
    slippage_bps: float = 1.0
    tick_size: float = 0.01
    risk_per_trade: float = 100.0
    initial_capital: float = 25000.0  # caps the position: no leverage
    timeframe_minutes: int = 1

    def slip(self, price: float) -> float:
        return max(self.slippage_ticks * self.tick_size, price * self.slippage_bps / 10_000)


@dataclass
class ReclaimTrade:
    ticker: str
    version: str
    side: int
    armed_bar: int
    signal_bar: int
    armed_time: datetime
    signal_time: datetime
    signal_close: float
    vwap_at_signal: float
    atr_at_signal: float
    entry_bar: int
    entry_time: datetime
    entry_price: float
    stop: float
    target: float
    quantity: int
    exit_bar: int | None = None
    exit_time: datetime | None = None
    exit_price: float | None = None
    exit_reason: str | None = None
    both_hit: bool = False
    best_price: float = NA
    worst_price: float = NA

    @property
    def setup(self) -> str:
        return SETUP_NAMES[self.side]

    @property
    def side_text(self) -> str:
        return "long" if self.side == 1 else "short"

    @property
    def closed(self) -> bool:
        return self.exit_price is not None

    @property
    def risk(self) -> float:
        """Price risk per share from the fill to the stop: 1R."""
        return self.side * (self.entry_price - self.stop)

    @property
    def r(self) -> float:
        if self.exit_price is None:
            return NA
        return self.side * (self.exit_price - self.entry_price) / self.risk

    @property
    def pnl(self) -> float:
        if self.exit_price is None:
            return NA
        return round(self.side * (self.exit_price - self.entry_price) * self.quantity, 6)

    @property
    def bars_held(self) -> int | None:
        return None if self.exit_bar is None else self.exit_bar - self.entry_bar

    @property
    def bars_to_confirm(self) -> int:
        return self.signal_bar - self.armed_bar

    @property
    def hold_minutes(self) -> float:
        if self.exit_time is None:
            return NA
        return (self.exit_time - self.entry_time).total_seconds() / 60

    @property
    def run_up(self) -> float:
        if math.isnan(self.best_price):
            return 0.0
        return max(0.0, self.side * (self.best_price - self.entry_price) * self.quantity)

    @property
    def drawdown(self) -> float:
        if math.isnan(self.worst_price):
            return 0.0
        return min(0.0, self.side * (self.worst_price - self.entry_price) * self.quantity)


@dataclass(frozen=True)
class ReclaimEvent:
    """A setup's state change: armed, entered, cancelled, expired, or rejected.

    `time` is when the setup armed, so one setup's events share it.
    """

    time: datetime
    side: int
    kind: str
    detail: str = ""


@dataclass
class ReclaimResult:
    ticker: str
    config: ReclaimConfig
    trades: list[ReclaimTrade] = field(default_factory=list)
    events: list[ReclaimEvent] = field(default_factory=list)

    @property
    def closed_trades(self) -> list[ReclaimTrade]:
        return [trade for trade in self.trades if trade.closed]


@dataclass
class _Setup:
    side: int
    bar: int
    time: datetime
    level: float  # the arming bar's high (long) or low (short)
    extreme: float  # lowest low (long) or highest high (short) since arming


@dataclass
class _Order:
    setup: _Setup
    signal_bar: int
    signal_time: datetime
    signal_close: float
    vwap: float
    atr: float
    stop: float
    quantity: int


class _Ema:
    """`ta.ema`, seeded with the simple average of the first `length` values."""

    def __init__(self, length: int):
        self.length = length
        self.alpha = 2 / (length + 1)
        self.value = NA
        self.seed: list[float] = []

    def update(self, source: float) -> float:
        if math.isnan(self.value):
            self.seed.append(source)
            if len(self.seed) >= self.length:
                self.value = sum(self.seed[-self.length :]) / self.length
        else:
            self.value = self.alpha * source + (1 - self.alpha) * self.value
        return self.value


class _Atr:
    """`ta.atr`: Wilder's average of true range, seeded with the simple average."""

    def __init__(self, length: int):
        self.length = length
        self.value = NA
        self.seed: list[float] = []
        self.prior_close = NA

    def update(self, high: float, low: float, close: float) -> float:
        if math.isnan(self.prior_close):
            true_range = high - low
        else:
            true_range = max(high - low, abs(high - self.prior_close), abs(low - self.prior_close))
        self.prior_close = close
        if math.isnan(self.value):
            self.seed.append(true_range)
            if len(self.seed) >= self.length:
                self.value = sum(self.seed[-self.length :]) / self.length
        else:
            self.value = (self.value * (self.length - 1) + true_range) / self.length
        return self.value


def _minutes(hhmm: int) -> int:
    return hhmm // 100 * 60 + hhmm % 100


def run_vwap_reclaim(
    ticker: str,
    bars: list[Bar],
    config: ReclaimConfig | None = None,
    early_closes: Mapping[date, int] = NYSE_EARLY_CLOSES,
) -> ReclaimResult:
    """Run the strategy over chart bars, oldest first, and return its trades and events.

    Bars outside a session's regular hours are ignored, so extended-hours bars
    and the after-hours part of an early-close day never reach VWAP, the EMA or
    ATR. Include a prior session so EMA 9 and ATR(14) are seeded; until they
    are, nothing arms.
    """
    cfg = config or ReclaimConfig()
    if cfg.both_hit not in ("stop", "target"):
        raise ValueError("both_hit must be 'stop' or 'target'")
    result = ReclaimResult(ticker.upper(), cfg)
    step = timedelta(minutes=cfg.timeframe_minutes)
    entry_start, entry_end = _minutes(cfg.entry_start), _minutes(cfg.entry_end)
    allowed = {1: cfg.allow_longs, -1: cfg.allow_shorts}

    ema = _Ema(cfg.ema_length)
    atr = _Atr(cfg.atr_length)
    day: date | None = None
    vwap_pv = vwap_v = 0.0
    prev_close = prev_vwap = NA  # the previous bar of this session
    pending: dict[int, _Setup | None] = {1: None, -1: None}
    order: _Order | None = None
    position: ReclaimTrade | None = None
    last_bar: tuple[int, Bar] | None = None
    entries = losses = 0
    session_r = 0.0

    def event(moment: datetime, side: int, kind: str, detail: str = "") -> None:
        result.events.append(ReclaimEvent(moment, side, kind, detail))

    def close_position(index: int, bar: Bar, price: float, reason: str) -> None:
        nonlocal position, losses, session_r
        assert position is not None
        position.exit_bar = index
        position.exit_time = bar.time
        position.exit_price = round(price, 10)
        position.exit_reason = reason
        if position.r < 0:
            losses += 1
        session_r += position.r
        position = None

    def halted() -> bool:
        return entries >= cfg.max_entries or losses >= cfg.max_losses or session_r <= -cfg.max_session_loss_r

    i = -1  # in-session bars seen, so skipped bars never count toward a window
    for bar in bars:
        o, h, lo, c, v = bar.open, bar.high, bar.low, bar.close, bar.volume
        local = bar.time.astimezone(ET)
        m = local.hour * 60 + local.minute
        session_close = early_closes.get(local.date(), RTH_CLOSE)
        if not RTH_OPEN <= m < session_close:
            continue
        i += 1
        close_time = bar.time + step
        close_m = m + cfg.timeframe_minutes

        if local.date() != day:
            if position is not None and last_bar is not None:
                # The prior session's last bars were missing: flatten at the last one seen.
                index, prior = last_bar
                close_position(index, prior, prior.close - position.side * cfg.slip(prior.close), "session")
            if order is not None:
                event(order.setup.time, order.setup.side, "expired", "session ended before the fill")
                order = None
            day = local.date()
            vwap_pv = vwap_v = 0.0
            prev_close = prev_vwap = NA
            pending = {1: None, -1: None}
            entries = losses = 0
            session_r = 0.0

        # --- broker: the entry fills at this bar's open.
        if order is not None:
            side, placed = order.setup.side, order
            order = None
            if side * (o - placed.stop) <= 0:
                event(placed.setup.time, side, "rejected", "opened through the stop")
            else:
                fill = o + side * cfg.slip(o)
                if side * (fill - placed.stop) <= 0:
                    event(placed.setup.time, side, "rejected", "slippage reached the stop")
                else:
                    risk = side * (fill - placed.stop)
                    position = ReclaimTrade(
                        ticker=result.ticker,
                        version=cfg.version,
                        side=side,
                        armed_bar=placed.setup.bar,
                        signal_bar=placed.signal_bar,
                        armed_time=placed.setup.time,
                        signal_time=placed.signal_time,
                        signal_close=placed.signal_close,
                        vwap_at_signal=placed.vwap,
                        atr_at_signal=placed.atr,
                        entry_bar=i,
                        entry_time=bar.time,
                        entry_price=round(fill, 10),
                        stop=placed.stop,
                        target=round(fill + side * cfg.target_r * risk, 10),
                        quantity=placed.quantity,
                    )
                    result.trades.append(position)
                    entries += 1
                    event(placed.setup.time, side, "entered")

        # --- broker: the stop and target rest from the fill.
        if position is not None:
            side = position.side
            best, worst = (h, lo) if side == 1 else (lo, h)
            if math.isnan(position.best_price):
                position.best_price, position.worst_price = best, worst
            else:
                position.best_price = max(position.best_price, best) if side == 1 else min(position.best_price, best)
                position.worst_price = min(position.worst_price, worst) if side == 1 else max(position.worst_price, worst)
            stop, target = position.stop, position.target
            if side * (o - stop) <= 0:
                close_position(i, bar, o - side * cfg.slip(o), "stop")
            elif side * (o - target) >= 0:
                close_position(i, bar, o, "target")
            else:
                stop_hit = (lo <= stop) if side == 1 else (h >= stop)
                target_hit = (h >= target) if side == 1 else (lo <= target)
                if stop_hit and target_hit:
                    position.both_hit = True
                    if cfg.both_hit == "stop":
                        close_position(i, bar, stop - side * cfg.slip(stop), "stop")
                    else:
                        close_position(i, bar, target, "target")
                elif stop_hit:
                    close_position(i, bar, stop - side * cfg.slip(stop), "stop")
                elif target_hit:
                    close_position(i, bar, target, "target")

        # --- indicators at the close.
        vwap_pv += (h + lo + c) / 3 * v
        vwap_v += v
        vwap = vwap_pv / vwap_v if vwap_v > 0 else NA
        ema_value = ema.update(c)
        atr_value = atr.update(h, lo, c)

        # --- an open trade: the session close, then the time stop.
        if position is not None:
            if close_m >= session_close:
                close_position(i, bar, c - position.side * cfg.slip(c), "session")
            elif (close_time - position.entry_time) >= timedelta(minutes=cfg.max_hold_min):
                close_position(i, bar, c - position.side * cfg.slip(c), "time")

        # --- setups: cancel, confirm or expire the armed ones, then arm new ones.
        if position is None and order is None:
            for side in (1, -1):
                setup = pending[side]
                if setup is None:
                    continue
                setup.extreme = min(setup.extreme, lo) if side == 1 else max(setup.extreme, h)
                if side * (c - vwap) < 0:
                    event(setup.time, side, "cancelled", "closed back through VWAP")
                    pending[side] = None
                elif side * (c - setup.level) > 0:
                    pending[side] = None
                    reason = _rejection(cfg, close_m, entry_start, entry_end, c, vwap, atr_value, halted())
                    if reason:
                        event(setup.time, side, "rejected", reason)
                        continue
                    stop = setup.extreme - side * cfg.atr_buffer * atr_value
                    expected_risk = side * (c - stop)
                    quantity = min(
                        max(1, math.floor(cfg.risk_per_trade / expected_risk)),
                        math.floor(cfg.initial_capital / c),
                    )
                    if quantity < 1:
                        event(setup.time, side, "rejected", "capital below one share")
                        continue
                    order = _Order(setup, i, bar.time, c, vwap, atr_value, stop, quantity)
                    pending = {1: None, -1: None}
                    break
                elif i - setup.bar >= cfg.confirm_bars:
                    event(setup.time, side, "expired", f"no confirmation in {cfg.confirm_bars} bars")
                    pending[side] = None

        if position is None and order is None and not halted():
            ready = not (math.isnan(vwap) or math.isnan(ema_value) or math.isnan(atr_value) or math.isnan(prev_vwap))
            for side in (1, -1):
                if not ready or not allowed[side] or pending[side] is not None:
                    continue
                came_from_other_side = side * (prev_close - prev_vwap) <= 0
                if came_from_other_side and side * (c - vwap) > 0 and side * (c - ema_value) > 0:
                    pending[side] = _Setup(side, i, bar.time, h if side == 1 else lo, lo if side == 1 else h)
                    event(bar.time, side, "armed")

        prev_close, prev_vwap = c, vwap
        last_bar = (i, bar)

    return result


def _rejection(
    cfg: ReclaimConfig,
    close_minute: int,
    entry_start: int,
    entry_end: int,
    close: float,
    vwap: float,
    atr_value: float,
    halted: bool,
) -> str:
    """Why a confirmation cannot enter, or "" when it can."""
    if halted:
        return "session limit reached"
    if not entry_start <= close_minute <= entry_end:
        return "outside the entry window"
    if not atr_value > 0:
        return "no ATR"
    if abs(close - vwap) > cfg.chase_atr * atr_value:
        return "more than the chase limit from VWAP"
    return ""


# --- statistics -------------------------------------------------------------


@dataclass(frozen=True)
class ReclaimStats:
    """The framework's acceptance measures, in R."""

    n: int
    days: int
    total_r: float
    expectancy_r: float
    profit_factor: float
    win_pct: float
    avg_win_r: float
    avg_loss_r: float
    worst_r: float
    max_drawdown_r: float
    avg_hold_min: float
    r_without_best_trade: float
    r_without_best_day: float
    both_hit: int


def summarize(trades: Iterable[ReclaimTrade]) -> ReclaimStats:
    closed = sorted((t for t in trades if t.closed), key=lambda t: t.entry_time)
    rs = [t.r for t in closed]
    if not rs:
        return ReclaimStats(0, 0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0)
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    peak = cumulative = drawdown = 0.0
    for r in rs:
        cumulative += r
        peak = max(peak, cumulative)
        drawdown = max(drawdown, peak - cumulative)
    by_day: dict[date, float] = defaultdict(float)
    for trade in closed:
        by_day[trade.entry_time.astimezone(ET).date()] += trade.r
    loss_total = -sum(losses)
    return ReclaimStats(
        n=len(rs),
        days=len(by_day),
        total_r=sum(rs),
        expectancy_r=sum(rs) / len(rs),
        profit_factor=sum(wins) / loss_total if loss_total else math.inf,
        win_pct=100 * len(wins) / len(rs),
        avg_win_r=statistics.fmean(wins) if wins else 0.0,
        avg_loss_r=statistics.fmean(losses) if losses else 0.0,
        worst_r=min(rs),
        max_drawdown_r=drawdown,
        avg_hold_min=statistics.fmean(t.hold_minutes for t in closed),
        r_without_best_trade=sum(rs) - max(rs),
        r_without_best_day=sum(rs) - max(by_day.values()),
        both_hit=sum(t.both_hit for t in closed),
    )


GROUP_KEYS: dict[str, Callable[[ReclaimTrade], str]] = {
    "ticker": lambda t: t.ticker,
    "side": lambda t: t.side_text,
    "month": lambda t: t.entry_time.astimezone(ET).strftime("%Y-%m"),
    "exit_reason": lambda t: t.exit_reason or "open",
}


def stats_line(label: str, stats: ReclaimStats) -> str:
    pf = "inf" if math.isinf(stats.profit_factor) else f"{stats.profit_factor:4.2f}"
    return (
        f"  {label:14s} n={stats.n:4d} days={stats.days:3d}  R={stats.total_r:7.1f}  "
        f"exp={stats.expectancy_r:6.3f}  pf={pf:>4s}  win%={stats.win_pct:5.1f}  "
        f"avgW={stats.avg_win_r:5.2f} avgL={stats.avg_loss_r:5.2f} worst={stats.worst_r:5.2f}  "
        f"maxDD={stats.max_drawdown_r:5.1f}R  hold={stats.avg_hold_min:4.1f}m  "
        f"-best trade={stats.r_without_best_trade:6.1f}  -best day={stats.r_without_best_day:6.1f}"
    )


def report(trades: Iterable[ReclaimTrade], keys: Iterable[str] = GROUP_KEYS) -> str:
    closed = [t for t in trades if t.closed]
    if not closed:
        return "No closed trades."
    overall = summarize(closed)
    lines = [
        stats_line("ALL", overall),
        f"  one bar reached both the stop and the target on {overall.both_hit} trades",
    ]
    for key in keys:
        groups: dict[str, list[ReclaimTrade]] = defaultdict(list)
        for trade in closed:
            groups[GROUP_KEYS[key](trade)].append(trade)
        lines.append(f"\n== {key}")
        lines += [stats_line(label, summarize(members)) for label, members in sorted(groups.items())]
    return "\n".join(lines)


# --- sl1 comments for the Strategy Lab CSV -----------------------------------


def entry_comment(trade: ReclaimTrade) -> str:
    fields = [
        ("setup", trade.setup),
        ("side", trade.side_text),
        ("version", trade.version),
        ("risk_atr", pine_number(trade.risk / trade.atr_at_signal)),
        ("ext_atr", pine_number(trade.side * (trade.signal_close - trade.vwap_at_signal) / trade.atr_at_signal)),
        ("bars_to_confirm", pine_number(trade.bars_to_confirm)),
    ]
    return "sl1" + "".join(f"|{key}={value}" for key, value in fields)


def exit_comment(trade: ReclaimTrade) -> str:
    both = "true" if trade.both_hit else "false"
    return f"sl1|exit_reason={trade.exit_reason}|r={pine_number(trade.r)}|both_hit={both}"
