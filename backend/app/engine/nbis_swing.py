"""NBIS recovery swing, version 0.1, as a pure backtest engine.

A follow-on module of the Pine research framework written from the 2026
journal. Its rules, all of them the framework's proposed defaults:

- 15-minute regular-session candles, long only.
- Arm after price has traded below the prior completed day's daily EMA 20.
- Trigger on a completed 15-minute reclaim of EMA 20 on that timeframe (the
  previous bar closed at or below it, this one closes above it) that also
  closes above the preceding three completed bars' highs. The arming bar never
  triggers.
- Enter at the next bar's open. Invalidation is below the last four completed
  bars' lows, 0.1 ATR(14) beyond them, frozen.
- A fixed 2R target and at most two trading sessions: the position is closed
  at the end of the second session (the entry session counts as the first).
  Overnight holding is allowed for this module only.
- For comparison, every trade also carries the intraday-only exit with the
  same entry: the same stop and target, but flat at the entry session's close.

Two choices the framework leaves open, made here and not tuned:

- An arm lasts for its own session and the next (`arm_sessions`), and each
  arm triggers once; trading below the daily EMA again re-arms.
- "EMA 20 on that timeframe" is read as the 15-minute EMA 20
  (`reclaim_level="ema"`). `reclaim_level="daily_ema"` is the other reading, a
  15-minute close back above the daily EMA 20.

Execution matches `app.engine.vwap_reclaim`: signals on bar close, entries at
the next bar's open, the stop and target rest from the fill, a bar that opens
through either fills at the open (overnight gaps included), the stop is
assumed first when one bar reaches both, and market and stop fills slip by the
larger of a tick count and basis points of price.

Pure: no network, no database. The caller supplies the bars.
"""

from __future__ import annotations

import bisect
import math
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import date, datetime

from app.engine.market_map import ET, Bar, DailyBar
from app.engine.market_map_report import pine_number
from app.engine.vwap_reclaim import NYSE_EARLY_CLOSES, RTH_CLOSE, RTH_OPEN, _Atr, _Ema

NA = math.nan
SETUP = "nbis_recovery"


@dataclass(frozen=True)
class SwingConfig:
    """The framework's inputs for the NBIS module, with its proposed defaults."""

    version: str = "0.1"
    timeframe_minutes: int = 15
    daily_ema_length: int = 20
    ema_length: int = 20
    reclaim_level: str = "ema"  # "ema": the 15-minute EMA; "daily_ema": the daily EMA 20
    breakout_bars: int = 3
    stop_bars: int = 4
    atr_length: int = 14
    atr_buffer: float = 0.1
    target_r: float = 2.0
    max_sessions: int = 2
    arm_sessions: int = 2
    both_hit: str = "stop"
    slippage_ticks: int = 1
    slippage_bps: float = 1.0
    tick_size: float = 0.01
    risk_per_trade: float = 100.0
    initial_capital: float = 25000.0

    def slip(self, price: float) -> float:
        return max(self.slippage_ticks * self.tick_size, price * self.slippage_bps / 10_000)


@dataclass
class SwingTrade:
    ticker: str
    version: str
    armed_time: datetime
    signal_time: datetime
    signal_close: float
    daily_ema: float
    atr_at_signal: float
    entry_bar: int
    entry_time: datetime
    entry_price: float
    stop: float
    target: float
    quantity: int
    side: int = 1
    exit_bar: int | None = None
    exit_time: datetime | None = None
    exit_price: float | None = None
    exit_reason: str | None = None
    sessions_held: int = 1
    both_hit: bool = False
    best_price: float = NA
    worst_price: float = NA
    # The intraday-only exit with the same entry: set when the trade leaves
    # on its entry day, or at that session's close when it is carried.
    intraday_time: datetime | None = None
    intraday_price: float | None = None
    intraday_reason: str | None = None

    @property
    def setup(self) -> str:
        return SETUP

    @property
    def side_text(self) -> str:
        return "long"

    @property
    def closed(self) -> bool:
        return self.exit_price is not None

    @property
    def risk(self) -> float:
        return self.entry_price - self.stop

    @property
    def r(self) -> float:
        return NA if self.exit_price is None else (self.exit_price - self.entry_price) / self.risk

    @property
    def pnl(self) -> float:
        return NA if self.exit_price is None else round((self.exit_price - self.entry_price) * self.quantity, 6)

    @property
    def bars_held(self) -> int | None:
        return None if self.exit_bar is None else self.exit_bar - self.entry_bar

    @property
    def hold_minutes(self) -> float:
        return NA if self.exit_time is None else (self.exit_time - self.entry_time).total_seconds() / 60

    @property
    def run_up(self) -> float:
        return 0.0 if math.isnan(self.best_price) else max(0.0, (self.best_price - self.entry_price) * self.quantity)

    @property
    def drawdown(self) -> float:
        return 0.0 if math.isnan(self.worst_price) else min(0.0, (self.worst_price - self.entry_price) * self.quantity)

    @property
    def overnight(self) -> bool:
        return self.sessions_held > 1


def intraday_only(trade: SwingTrade) -> SwingTrade:
    """The same entry, flat at the entry session's close."""
    if trade.intraday_price is None:
        return replace(trade)
    return replace(
        trade,
        exit_time=trade.intraday_time,
        exit_price=trade.intraday_price,
        exit_reason=trade.intraday_reason,
        sessions_held=1,
    )


@dataclass(frozen=True)
class SwingEvent:
    time: datetime
    kind: str
    detail: str = ""


@dataclass
class SwingResult:
    ticker: str
    config: SwingConfig
    trades: list[SwingTrade] = field(default_factory=list)
    events: list[SwingEvent] = field(default_factory=list)

    @property
    def closed_trades(self) -> list[SwingTrade]:
        return [trade for trade in self.trades if trade.closed]


class _PriorDayEma:
    """`request.security(ticker, "D", ta.ema(close, n)[1], lookahead_on)`: through the last completed day."""

    def __init__(self, daily: list[DailyBar], length: int):
        ordered = sorted(daily, key=lambda bar: bar.day)
        ema = _Ema(length)
        self.days = [bar.day for bar in ordered]
        self.values = [ema.update(bar.close) for bar in ordered]

    def before(self, day: date) -> float:
        index = bisect.bisect_left(self.days, day) - 1
        return self.values[index] if index >= 0 else NA


@dataclass
class _Order:
    armed_time: datetime
    signal_time: datetime
    signal_close: float
    daily_ema: float
    atr: float
    stop: float
    quantity: int


def run_nbis_swing(
    ticker: str,
    bars: list[Bar],
    daily: list[DailyBar],
    config: SwingConfig | None = None,
    early_closes: Mapping[date, int] = NYSE_EARLY_CLOSES,
) -> SwingResult:
    """Run the module over 15-minute bars, oldest first, with daily bars for the daily EMA."""
    cfg = config or SwingConfig()
    if cfg.reclaim_level not in ("ema", "daily_ema"):
        raise ValueError("reclaim_level must be 'ema' or 'daily_ema'")
    if cfg.both_hit not in ("stop", "target"):
        raise ValueError("both_hit must be 'stop' or 'target'")
    result = SwingResult(ticker.upper(), cfg)
    daily_ema = _PriorDayEma(daily, cfg.daily_ema_length)
    ema = _Ema(cfg.ema_length)
    atr = _Atr(cfg.atr_length)
    highs: list[float] = []
    lows: list[float] = []

    day: date | None = None
    session = 0
    prev_close = prev_ema = NA
    armed_time: datetime | None = None
    armed_until = -1  # the last session the current arm may trigger in
    order: _Order | None = None
    position: SwingTrade | None = None
    entry_session = 0

    def event(moment: datetime, kind: str, detail: str = "") -> None:
        result.events.append(SwingEvent(moment, kind, detail))

    def close_position(index: int, bar: Bar, price: float, reason: str) -> None:
        nonlocal position
        assert position is not None
        position.exit_bar = index
        position.exit_time = bar.time
        position.exit_price = round(price, 10)
        position.exit_reason = reason
        position.sessions_held = session - entry_session + 1
        if position.intraday_price is None:
            position.intraday_time, position.intraday_price, position.intraday_reason = bar.time, position.exit_price, reason
        position = None

    i = -1
    for bar in bars:
        o, h, lo, c = bar.open, bar.high, bar.low, bar.close
        local = bar.time.astimezone(ET)
        m = local.hour * 60 + local.minute
        session_close = early_closes.get(local.date(), RTH_CLOSE)
        if not RTH_OPEN <= m < session_close:
            continue
        i += 1
        if local.date() != day:
            day = local.date()
            session += 1
        level = daily_ema.before(day)

        # --- broker: the entry fills at this bar's open.
        if order is not None:
            placed, order = order, None
            fill = o + cfg.slip(o)
            if o <= placed.stop or fill <= placed.stop:
                event(placed.armed_time, "rejected", "opened through the stop")
            else:
                risk = fill - placed.stop
                position = SwingTrade(
                    ticker=result.ticker,
                    version=cfg.version,
                    armed_time=placed.armed_time,
                    signal_time=placed.signal_time,
                    signal_close=placed.signal_close,
                    daily_ema=placed.daily_ema,
                    atr_at_signal=placed.atr,
                    entry_bar=i,
                    entry_time=bar.time,
                    entry_price=round(fill, 10),
                    stop=placed.stop,
                    target=round(fill + cfg.target_r * risk, 10),
                    quantity=placed.quantity,
                )
                entry_session = session
                result.trades.append(position)
                event(placed.armed_time, "entered")

        # --- broker: the stop and target rest from the fill.
        if position is not None:
            if math.isnan(position.best_price):
                position.best_price, position.worst_price = h, lo
            else:
                position.best_price = max(position.best_price, h)
                position.worst_price = min(position.worst_price, lo)
            stop, target = position.stop, position.target
            if o <= stop:
                close_position(i, bar, o - cfg.slip(o), "stop")
            elif o >= target:
                close_position(i, bar, o, "target")
            elif lo <= stop and h >= target:
                position.both_hit = True
                if cfg.both_hit == "stop":
                    close_position(i, bar, stop - cfg.slip(stop), "stop")
                else:
                    close_position(i, bar, target, "target")
            elif lo <= stop:
                close_position(i, bar, stop - cfg.slip(stop), "stop")
            elif h >= target:
                close_position(i, bar, target, "target")

        # --- indicators at the close.
        ema_value = ema.update(c)
        atr_value = atr.update(h, lo, c)
        highs.append(h)
        lows.append(lo)
        last_bar_of_session = m + cfg.timeframe_minutes >= session_close

        # --- an open trade: the intraday-only mark, then the session limit.
        if position is not None and last_bar_of_session:
            if session == entry_session and position.intraday_price is None:
                position.intraday_time = bar.time
                position.intraday_price = round(c - cfg.slip(c), 10)
                position.intraday_reason = "eod"
            if session - entry_session + 1 >= cfg.max_sessions:
                close_position(i, bar, c - cfg.slip(c), "time")

        # --- trigger on an earlier arm, then arm.
        if position is None and order is None and armed_time is not None and session <= armed_until:
            reclaim = ema_value if cfg.reclaim_level == "ema" else level
            prior_reclaim = prev_ema if cfg.reclaim_level == "ema" else level
            breakout = len(highs) > cfg.breakout_bars and c > max(highs[-cfg.breakout_bars - 1 : -1])
            if (
                not math.isnan(prior_reclaim)
                and not math.isnan(atr_value)
                and prev_close <= prior_reclaim
                and c > reclaim
                and breakout
            ):
                stop = min(lows[-cfg.stop_bars :]) - cfg.atr_buffer * atr_value
                expected_risk = c - stop
                quantity = min(
                    max(1, math.floor(cfg.risk_per_trade / expected_risk)),
                    math.floor(cfg.initial_capital / c),
                )
                if quantity >= 1:
                    order = _Order(armed_time, bar.time, c, level, atr_value, stop, quantity)
                else:
                    event(armed_time, "rejected", "capital below one share")
                armed_time, armed_until = None, -1
        elif armed_time is not None and session > armed_until:
            event(armed_time, "expired", f"no trigger in {cfg.arm_sessions} sessions")
            armed_time, armed_until = None, -1

        if not math.isnan(level) and lo < level and order is None and position is None:
            if armed_time is None:
                event(bar.time, "armed")
            armed_time = armed_time or bar.time
            armed_until = session + cfg.arm_sessions - 1

        prev_close, prev_ema = c, ema_value
        del highs[: -cfg.breakout_bars - cfg.stop_bars], lows[: -cfg.breakout_bars - cfg.stop_bars]

    return result


# --- sl1 comments for the Strategy Lab CSV -----------------------------------


def entry_comment(trade: SwingTrade) -> str:
    fields = [
        ("setup", trade.setup),
        ("side", trade.side_text),
        ("version", trade.version),
        ("risk_atr", pine_number(trade.risk / trade.atr_at_signal)),
        ("above_daily_ema_pct", pine_number(100 * (trade.signal_close / trade.daily_ema - 1))),
    ]
    return "sl1" + "".join(f"|{key}={value}" for key, value in fields)


def exit_comment(trade: SwingTrade) -> str:
    return (
        f"sl1|exit_reason={trade.exit_reason}|r={pine_number(trade.r)}|sessions={trade.sessions_held}"
        f"|intraday_r={pine_number(intraday_only(trade).r)}"
    )
