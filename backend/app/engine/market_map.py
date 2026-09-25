"""Isaac Market Map, ported bar for bar from `docs/pine/isaac_market_map.pine`.

The Pine is the specification. Every input is a `MarketMapConfig` field with
the Pine default, named as the Pine input in snake_case, and the per-bar
logic keeps the Pine's order of evaluation, because several rules depend on
it (a retest level set on this bar cannot fire until the next one; an exit
is counted and its cooldown started on the bar the script notices it, which
for a market close is the next bar and can be the next session).

Pine's `na` is represented as `math.nan`. Comparisons with NaN are false in
Python exactly as comparisons with `na` are false in Pine, so the conditions
read the same as the source.

Execution follows the Pine `strategy()` settings:

- `process_orders_on_close = true`: signals are evaluated on bar close, and
  market entries and `strategy.close` fill at that close.
- `strategy.exit` stop (and optional limit) orders placed on a bar's close
  are checked intrabar from the next bar. A bar that opens through the stop
  fills at the open. A stop moved on a bar takes effect on the bar after.
- `slippage = 2`: two ticks against the trade on market and stop fills.

Pure: no network, no database. The caller supplies bars.
"""

from __future__ import annotations

import bisect
import math
import re
from collections import deque
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
NA = math.nan

PREMARKET_OPEN = 240
RTH_OPEN = 570
RTH_CLOSE = 960
MAX_SESSION_BARS = 400
MIDDAY_OFF = "Off"
MIDDAY_A_HALF = "A only, half size"
MIDDAY_ALLOW = "Allow"

# How a signal is graded. "rs_gate" is v1.1.0: relative strength on the
# trade's side of at least `min_rs_pct` or the signal is C. "rvol_or_rs" is
# v1.0.0, kept so the port can be checked against the v1.0.0 exports.
GRADE_RS_GATE = "rs_gate"
GRADE_RVOL_OR_RS = "rvol_or_rs"

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


@dataclass(frozen=True, slots=True)
class Bar:
    """One chart bar. `time` is the bar's open, timezone-aware."""

    time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True, slots=True)
class DailyBar:
    day: date
    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True)
class MarketMapConfig:
    """Every Pine input that affects signals or fills, with the Pine default."""

    # Core
    indicator_version: str = "1.1.0"
    benchmark_symbol: str = "AMEX:SPY"
    or_minutes: int = 5
    atr_length: int = 14
    rvol_days: int = 10
    rvol_min: float = 1.5
    min_rs_pct: float = 1.5
    allow_shorts: bool = False
    risk_per_trade: float = 100.0
    # Windows (ET, HHMM)
    open_window_end: int = 1015
    power_window_start: int = 1400
    last_entry_time: int = 1545
    flat_time: int = 1555
    midday_mode: str = MIDDAY_OFF
    # Risk
    max_heat_atr: float = 0.4
    min_risk_atr: float = 0.08
    level_buffer_atr: float = 0.05
    breakeven_at_r: float = 0.75
    trail_start_r: float = 1.5
    trail_offset_r: float = 1.0
    target_r: float = 0.0
    time_stop_min: int = 30
    time_stop_min_r: float = 0.5
    cooldown_min: int = 15
    max_entries_per_day: int = 3
    max_losses_per_day: int = 2
    hold_power_overnight: bool = False
    overnight_exit_time: int = 1000
    # Tickers
    core_tickers: str = "LLY,MU,AMD,META,SPY,TSLA,GS,CAT,AMZN,NFLX,COIN"
    avoid_tickers: str = "SNDK,NVDA,SLV,CVNA,MSFT,MSTR,CRWV,JPM"
    allow_avoid: bool = False
    # Setups
    enable_orb: bool = True
    enable_level_breaks: bool = True
    enable_retest: bool = True
    enable_orb_retest: bool = False
    enable_hod: bool = True
    enable_vwap: bool = True
    enable_orb_fail: bool = True
    retest_bars: int = 12
    retest_tol_atr: float = 0.1
    fail_bars: int = 3
    # strategy() properties and chart facts, not inputs
    initial_capital: float = 25000.0
    slippage: int = 2
    tick_size: float = 0.01
    timeframe_minutes: int = 5
    grade_rule: str = GRADE_RS_GATE

    @classmethod
    def v1_0_0(cls, **overrides) -> MarketMapConfig:
        """The inputs and grading of v1.0.0, which produced the committed exports."""
        base = cls(
            indicator_version="1.0.0",
            allow_shorts=True,
            midday_mode=MIDDAY_A_HALF,
            enable_orb_retest=True,
            grade_rule=GRADE_RVOL_OR_RS,
        )
        return replace(base, **overrides)

    @property
    def benchmark_ticker(self) -> str:
        return self.benchmark_symbol.split(":")[-1].upper()


@dataclass
class Trade:
    ticker: str
    side: int
    setup: str
    grade: str
    size: str
    score: int
    window: str
    tier: str
    rvol: float
    rs_vs_spy: float
    gap_atr: float
    ext_atr: float
    risk_atr: float
    dte_hint: str
    entry_bar: int
    entry_time: datetime
    entry_ref: float
    entry_price: float
    stop: float
    risk: float
    quantity: int
    risk_budget: float
    exit_bar: int | None = None
    exit_time: datetime | None = None
    exit_price: float | None = None
    exit_reason: str | None = None
    exit_mfe_r: float = NA
    best_price: float = NA
    worst_price: float = NA

    @property
    def side_text(self) -> str:
        return "long" if self.side == 1 else "short"

    @property
    def closed(self) -> bool:
        return self.exit_price is not None

    @property
    def pnl(self) -> float:
        if self.exit_price is None:
            return NA
        return round(self.side * (self.exit_price - self.entry_price) * self.quantity, 6)

    @property
    def r(self) -> float:
        """Net PnL over the risk budget for the trade's size, as imm_export_cohorts.py computes it."""
        return self.pnl / self.risk_budget

    @property
    def bars_held(self) -> int | None:
        return None if self.exit_bar is None else self.exit_bar - self.entry_bar

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
class Signal:
    """A bar where a long or short setup fired, and what became of it."""

    time: datetime
    bar_index: int
    side: int
    setup: str
    outcome: str
    grade: str = ""
    rvol: float = NA
    rs_vs_spy: float = NA


@dataclass
class BacktestResult:
    ticker: str
    config: MarketMapConfig
    trades: list[Trade] = field(default_factory=list)
    signals: list[Signal] = field(default_factory=list)

    @property
    def closed_trades(self) -> list[Trade]:
        return [trade for trade in self.trades if trade.closed]


# --- data shaping -----------------------------------------------------------


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def bars_from_alpaca(raw: list[dict]) -> list[Bar]:
    """Alpaca bar dicts (t, o, h, l, c, v) to `Bar`s, sorted and de-duplicated."""
    bars = {
        _parse_time(item["t"]): Bar(
            _parse_time(item["t"]),
            float(item["o"]),
            float(item["h"]),
            float(item["l"]),
            float(item["c"]),
            float(item.get("v") or 0.0),
        )
        for item in raw
    }
    return [bars[key] for key in sorted(bars)]


def daily_from_alpaca(raw: list[dict]) -> list[DailyBar]:
    days = {}
    for item in raw:
        day = _parse_time(item["t"]).astimezone(ET).date()
        days[day] = DailyBar(day, float(item["o"]), float(item["h"]), float(item["l"]), float(item["c"]))
    return [days[key] for key in sorted(days)]


def _minute_of_day(moment: datetime) -> int:
    local = moment.astimezone(ET)
    return local.hour * 60 + local.minute


def resample(bars: list[Bar], minutes: int) -> list[Bar]:
    """Aggregate 1-minute bars into `minutes` bars aligned to the ET clock.

    Only divisors of 30 are accepted, because those align with both 9:30 and
    4:00 the way TradingView's session-anchored bars do.
    """
    if minutes <= 0 or 30 % minutes:
        raise ValueError("timeframe must divide 30 minutes (1, 2, 3, 5, 10, 15, 30)")
    if minutes == 1:
        return list(bars)
    out: list[Bar] = []
    key = None
    for bar in bars:
        local = bar.time.astimezone(ET)
        bucket_minute = (local.hour * 60 + local.minute) // minutes * minutes
        bucket = local.replace(hour=bucket_minute // 60, minute=bucket_minute % 60, second=0, microsecond=0)
        if bucket != key:
            out.append(Bar(bucket.astimezone(timezone.utc), bar.open, bar.high, bar.low, bar.close, bar.volume))
            key = bucket
        else:
            last = out[-1]
            out[-1] = Bar(
                last.time,
                last.open,
                max(last.high, bar.high),
                min(last.low, bar.low),
                bar.close,
                last.volume + bar.volume,
            )
    return out


def regular_session(bars: list[Bar]) -> list[Bar]:
    """Drop extended-hours bars, the way a chart with extended hours off shows them."""
    return [bar for bar in bars if RTH_OPEN <= _minute_of_day(bar.time) < RTH_CLOSE]


def daily_from_bars(bars: list[Bar]) -> list[DailyBar]:
    """Regular-session daily bars built from intraday bars."""
    days: dict[date, DailyBar] = {}
    for bar in regular_session(bars):
        day = bar.time.astimezone(ET).date()
        prior = days.get(day)
        if prior is None:
            days[day] = DailyBar(day, bar.open, bar.high, bar.low, bar.close)
        else:
            days[day] = DailyBar(day, prior.open, max(prior.high, bar.high), min(prior.low, bar.low), bar.close)
    return [days[key] for key in sorted(days)]


# --- indicators -------------------------------------------------------------


def _isna(value: float) -> bool:
    return value != value


class _Ema:
    """`ta.ema`: seeded with the SMA of the first `length` values."""

    def __init__(self, length: int):
        self.length = length
        self.alpha = 2 / (length + 1)
        self.value = NA
        self.seed: list[float] = []

    def update(self, source: float) -> float:
        if _isna(self.value):
            self.seed.append(source)
            if len(self.seed) >= self.length:
                self.value = sum(self.seed[-self.length :]) / self.length
        else:
            self.value = self.alpha * source + (1 - self.alpha) * self.value
        return self.value


def daily_atr(daily: list[DailyBar], length: int) -> list[float]:
    """`ta.atr(length)` on daily bars: Wilder's RMA of true range, SMA-seeded."""
    values: list[float] = []
    ranges: list[float] = []
    rma = NA
    for index, bar in enumerate(daily):
        if index == 0:
            true_range = bar.high - bar.low
        else:
            prior_close = daily[index - 1].close
            true_range = max(bar.high - bar.low, abs(bar.high - prior_close), abs(bar.low - prior_close))
        ranges.append(true_range)
        if _isna(rma):
            if len(ranges) >= length:
                rma = sum(ranges[-length:]) / length
        else:
            rma = (rma * (length - 1) + true_range) / length
        values.append(rma)
    return values


class _PriorDayAtr:
    """`request.security(ticker, "D", ta.atr(n)[1], lookahead_on)`: ATR through the last completed day."""

    def __init__(self, daily: list[DailyBar], length: int):
        ordered = sorted(daily, key=lambda bar: bar.day)
        self.days = [bar.day for bar in ordered]
        self.values = daily_atr(ordered, length)

    def before(self, day: date) -> float:
        index = bisect.bisect_left(self.days, day) - 1
        return self.values[index] if index >= 0 else NA


class _Benchmark:
    """Same-timeframe `request.security` of the benchmark: the latest bar at or before `time`."""

    def __init__(self, bars: list[Bar]):
        self.bars = sorted(bars, key=lambda bar: bar.time)
        self.times = [bar.time for bar in self.bars]

    def at(self, moment: datetime) -> tuple[float, float]:
        index = bisect.bisect_right(self.times, moment) - 1
        if index < 0:
            return NA, NA
        bar = self.bars[index]
        return bar.open, bar.close


def _minutes(hhmm: int) -> int:
    return hhmm // 100 * 60 + hhmm % 100


def _in_list(list_text: str, ticker: str) -> bool:
    return any(item.upper() == ticker for item in list_text.replace(" ", "").split(","))


def ticker_tier(config: MarketMapConfig, ticker: str) -> str:
    ticker = ticker.upper()
    if _in_list(config.avoid_tickers, ticker):
        return "avoid"
    return "core" if _in_list(config.core_tickers, ticker) else "neutral"


_SYMBOL_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9._-]*$")


# --- the strategy -----------------------------------------------------------


def run_market_map(
    ticker: str,
    bars: list[Bar],
    daily: list[DailyBar],
    benchmark: list[Bar] | None = None,
    config: MarketMapConfig | None = None,
) -> BacktestResult:
    """Run the strategy over chart bars and return its trades and signals.

    `bars` are the chart's bars at the chart timeframe, oldest first; include
    extended-hours bars only if the chart being matched shows them. `daily`
    feeds the prior-day ATR. `benchmark` is the benchmark at the same
    timeframe; when omitted and the ticker is the benchmark, the chart's own
    bars are used.
    """
    cfg = config or MarketMapConfig()
    ticker = ticker.upper()
    if benchmark is None and ticker == cfg.benchmark_ticker:
        benchmark = bars
    result = BacktestResult(ticker, cfg)

    last_entry_min = _minutes(cfg.last_entry_time)
    flat_min = _minutes(cfg.flat_time)
    overnight_exit_min = _minutes(cfg.overnight_exit_time)
    timeframe = timedelta(minutes=cfg.timeframe_minutes)
    tick = cfg.tick_size
    slip = cfg.slippage * tick

    symbol_valid = len(ticker) <= 32 and bool(_SYMBOL_PATTERN.match(ticker))
    tier = ticker_tier(cfg, ticker)
    atr_source = _PriorDayAtr(daily, cfg.atr_length)
    bench = _Benchmark(benchmark or [])
    ema9 = _Ema(9)
    ema20 = _Ema(20)
    highs: deque[float] = deque(maxlen=cfg.fail_bars + 1)
    lows: deque[float] = deque(maxlen=cfg.fail_bars + 1)

    # Series history ([1], [2]).
    prev_day: date | None = None
    prev_is_rth = False
    prev_close = [NA, NA]
    prev_vwap = [NA, NA]
    vwap_pv = 0.0
    vwap_v = 0.0

    # `var` state.
    pm_high = pm_low = NA
    pdh = pdl = pdc = NA
    session_high = session_low = session_close = NA
    rth_open_price = bench_session_open = NA
    or_high = or_low = NA
    bar_of_session = -1
    cum_volume = 0.0
    today_cum_volume = [NA] * MAX_SESSION_BARS
    cum_volume_history: list[list[float]] = []
    entries_today = 0
    losses_today = 0
    or_broke_up = or_broke_down = False
    or_break_up_bar = or_break_down_bar = NA
    or_fail_short_done = or_fail_long_done = False
    pdh_broke = pdl_broke = False
    retest_long_level = NA
    retest_long_bar = NA
    retest_long_name = ""
    retest_short_level = NA
    retest_short_bar = NA
    retest_short_name = ""

    trade_side = 0
    trade_entry = trade_stop = trade_risk = trade_best = NA
    trade_entry_bar = NA
    trade_entry_time: datetime | None = None
    trade_entry_day: date | None = None
    trade_stage = "stop"
    trade_window = ""
    trade_grade = ""
    trade_overnight = False
    cooldown_until = _EPOCH

    # Broker emulator.
    position: Trade | None = None
    order_stop = NA
    order_limit = NA
    order_reason = ""
    order_mfe_r = NA

    def close_position(index: int, bar: Bar, price: float, reason: str, mfe_r: float) -> None:
        nonlocal position, order_stop, order_limit
        assert position is not None
        position.exit_bar = index
        position.exit_time = bar.time
        position.exit_price = round(price, 10)
        position.exit_reason = reason
        position.exit_mfe_r = mfe_r
        position = None
        order_stop = order_limit = NA

    for i, bar in enumerate(bars):
        o, h, lo, c, v = bar.open, bar.high, bar.low, bar.close, bar.volume
        local = bar.time.astimezone(ET)
        time_close = bar.time + timeframe
        close_local = time_close.astimezone(ET)
        m = local.hour * 60 + local.minute
        close_minute = close_local.hour * 60 + close_local.minute
        day_key = local.date()

        # --- broker: resting exit orders from the last bar's close fill intrabar.
        if position is not None:
            side = position.side
            # Run-up and drawdown cover the whole exit bar, as the export's do.
            best, worst = (h, lo) if side == 1 else (lo, h)
            if _isna(position.best_price):
                position.best_price, position.worst_price = best, worst
            elif side == 1:
                position.best_price = max(position.best_price, best)
                position.worst_price = min(position.worst_price, worst)
            else:
                position.best_price = min(position.best_price, best)
                position.worst_price = max(position.worst_price, worst)
            fill = _exit_fill(side, o, h, lo, order_stop, order_limit, tick)
            if fill is not None:
                kind, price = fill
                if kind == "stop":
                    close_position(i, bar, price - side * slip, order_reason, order_mfe_r)
                else:
                    close_position(i, bar, price, "target", order_mfe_r)

        is_rth = RTH_OPEN <= m < RTH_CLOSE
        is_premarket = PREMARKET_OPEN <= m < RTH_OPEN
        new_day = day_key != prev_day
        new_rth_session = is_rth and (not prev_is_rth or new_day)
        window = session_window(cfg, m)

        if new_rth_session:
            vwap_pv = vwap_v = 0.0
        vwap_pv += (h + lo + c) / 3 * v
        vwap_v += v
        session_vwap = vwap_pv / vwap_v if vwap_v > 0 else NA
        e9 = ema9.update(c)
        e20 = ema20.update(c)
        highs.append(h)
        lows.append(lo)
        full_window = len(highs) == highs.maxlen
        recent_high = max(highs) if full_window else NA
        recent_low = min(lows) if full_window else NA
        atr = atr_source.before(day_key)
        bench_open, bench_close = bench.at(bar.time)

        if new_day:
            pm_high = pm_low = NA
        if is_premarket:
            pm_high = h if _isna(pm_high) else max(pm_high, h)
            pm_low = lo if _isna(pm_low) else min(pm_low, lo)

        if new_rth_session:
            if not _isna(session_high):
                pdh, pdl, pdc = session_high, session_low, session_close
                cum_volume_history.insert(0, list(today_cum_volume))
                del cum_volume_history[cfg.rvol_days :]
            today_cum_volume = [NA] * MAX_SESSION_BARS
            rth_open_price = o
            bench_session_open = bench_open
            session_high = session_low = NA
            or_high = or_low = NA
            bar_of_session = -1
            cum_volume = 0.0
            entries_today = losses_today = 0
            or_broke_up = or_broke_down = False
            or_fail_short_done = or_fail_long_done = False
            pdh_broke = pdl_broke = False
            retest_long_level = retest_short_level = NA

        prior_session_high = session_high
        prior_session_low = session_low
        if is_rth:
            bar_of_session += 1
            session_high = h if _isna(session_high) else max(session_high, h)
            session_low = lo if _isna(session_low) else min(session_low, lo)
            session_close = c
            cum_volume += v
            if bar_of_session < MAX_SESSION_BARS:
                today_cum_volume[bar_of_session] = cum_volume
            if m < RTH_OPEN + cfg.or_minutes:
                or_high = h if _isna(or_high) else max(or_high, h)
                or_low = lo if _isna(or_low) else min(or_low, lo)

        or_complete = is_rth and m >= RTH_OPEN + cfg.or_minutes and not _isna(or_high)
        rvol = _rvol(cum_volume_history, bar_of_session, cum_volume) if is_rth else NA
        rs_vs_bench = (
            (c / rth_open_price - bench_close / bench_session_open) * 100
            if is_rth and rth_open_price > 0 and bench_session_open > 0 and bench_close > 0
            else NA
        )
        gap_atr = (rth_open_price - pdc) / atr if atr > 0 and not _isna(pdc) else NA
        long_trend = c > session_vwap and e9 > e20
        short_trend = c < session_vwap and e9 < e20

        retest_long_signal = False
        retest_long_setup = ""
        retest_long_ref = NA
        if not _isna(retest_long_level):
            if i - retest_long_bar > cfg.retest_bars or c < retest_long_level - cfg.level_buffer_atr * atr:
                retest_long_level = NA
            elif (
                i > retest_long_bar
                and lo <= retest_long_level + cfg.retest_tol_atr * atr
                and c > retest_long_level
                and c > session_vwap
            ):
                retest_long_signal = True
                retest_long_setup = retest_long_name
                retest_long_ref = retest_long_level
                retest_long_level = NA

        retest_short_signal = False
        retest_short_setup = ""
        retest_short_ref = NA
        if not _isna(retest_short_level):
            if i - retest_short_bar > cfg.retest_bars or c > retest_short_level + cfg.level_buffer_atr * atr:
                retest_short_level = NA
            elif (
                i > retest_short_bar
                and h >= retest_short_level - cfg.retest_tol_atr * atr
                and c < retest_short_level
                and c < session_vwap
            ):
                retest_short_signal = True
                retest_short_setup = retest_short_name
                retest_short_ref = retest_short_level
                retest_short_level = NA

        orb_fail_short = (
            or_broke_up
            and not or_fail_short_done
            and i > or_break_up_bar
            and i - or_break_up_bar <= cfg.fail_bars
            and c < or_high
            and c < session_vwap
        )
        orb_fail_long = (
            or_broke_down
            and not or_fail_long_done
            and i > or_break_down_bar
            and i - or_break_down_bar <= cfg.fail_bars
            and c > or_low
            and c > session_vwap
        )
        if orb_fail_short:
            or_fail_short_done = True
        if orb_fail_long:
            or_fail_long_done = True

        orb_up_cross = or_complete and not or_broke_up and c > or_high
        orb_down_cross = or_complete and not or_broke_down and c < or_low
        if orb_up_cross:
            or_broke_up = True
            or_break_up_bar = i
            retest_long_level, retest_long_bar, retest_long_name = or_high, i, "orb_retest"
        if orb_down_cross:
            or_broke_down = True
            or_break_down_bar = i
            retest_short_level, retest_short_bar, retest_short_name = or_low, i, "orb_retest"

        pdh_cross = (
            is_rth and bar_of_session > 0 and not pdh_broke and not _isna(pdh) and c > pdh and prev_close[0] <= pdh
        )
        pdl_cross = (
            is_rth and bar_of_session > 0 and not pdl_broke and not _isna(pdl) and c < pdl and prev_close[0] >= pdl
        )
        if pdh_cross:
            pdh_broke = True
            retest_long_level, retest_long_bar, retest_long_name = pdh, i, "pdh_retest"
        if pdl_cross:
            pdl_broke = True
            retest_short_level, retest_short_bar, retest_short_name = pdl, i, "pdl_retest"

        hod_break = is_rth and bar_of_session > 0 and not _isna(prior_session_high) and c > prior_session_high
        lod_break = is_rth and bar_of_session > 0 and not _isna(prior_session_low) and c < prior_session_low
        vwap_reclaim = (
            is_rth
            and bar_of_session >= 2
            and c > session_vwap
            and prev_close[0] <= prev_vwap[0]
            and prev_close[1] <= prev_vwap[1]
        )
        vwap_loss = (
            is_rth
            and bar_of_session >= 2
            and c < session_vwap
            and prev_close[0] >= prev_vwap[0]
            and prev_close[1] >= prev_vwap[1]
        )

        long_setup = ""
        long_level = NA
        if (
            retest_long_signal
            and (cfg.enable_orb_retest if retest_long_setup == "orb_retest" else cfg.enable_retest)
            and e9 > e20
        ):
            long_setup, long_level = retest_long_setup, retest_long_ref
        elif cfg.enable_orb and orb_up_cross and long_trend:
            long_setup, long_level = "orb_break", or_high
        elif cfg.enable_level_breaks and pdh_cross and long_trend:
            long_setup, long_level = "pdh_break", pdh
        elif cfg.enable_hod and hod_break and window == "power" and long_trend:
            long_setup, long_level = "hod_break", max(session_vwap, e20)
        elif cfg.enable_vwap and vwap_reclaim and e9 > e20:
            long_setup, long_level = "vwap_reclaim", session_vwap
        elif cfg.enable_orb_fail and orb_fail_long:
            long_setup, long_level = "orb_fail", recent_low

        short_setup = ""
        short_level = NA
        if (
            retest_short_signal
            and (cfg.enable_orb_retest if retest_short_setup == "orb_retest" else cfg.enable_retest)
            and e9 < e20
        ):
            short_setup, short_level = retest_short_setup, retest_short_ref
        elif cfg.enable_orb and orb_down_cross and short_trend:
            short_setup, short_level = "orb_break", or_low
        elif cfg.enable_level_breaks and pdl_cross and short_trend:
            short_setup, short_level = "pdl_break", pdl
        elif cfg.enable_hod and lod_break and window == "power" and short_trend:
            short_setup, short_level = "lod_break", min(session_vwap, e20)
        elif cfg.enable_vwap and vwap_loss and e9 < e20:
            short_setup, short_level = "vwap_loss", session_vwap
        elif cfg.enable_orb_fail and orb_fail_short:
            short_setup, short_level = "orb_fail", recent_high

        # --- an exit noticed: count the loss, start the cooldown.
        if trade_side != 0 and position is None and i > trade_entry_bar:
            last = result.trades[-1]
            if last.pnl < 0 and trade_stage == "stop":
                losses_today += 1
            cooldown_until = time_close + timedelta(minutes=cfg.cooldown_min)
            trade_side = 0
            trade_overnight = False

        blocked = _entry_block(
            trade_side != 0 or position is not None,
            or_complete,
            m < last_entry_min,
            time_close >= cooldown_until,
            entries_today < cfg.max_entries_per_day,
            losses_today < cfg.max_losses_per_day,
            atr > 0,
            symbol_valid,
            tier != "avoid" or cfg.allow_avoid,
        )
        can_enter = blocked == ""

        entry_side = 0
        entry_setup = ""
        entry_level = NA
        if can_enter and long_setup and (not short_setup or not cfg.allow_shorts):
            entry_side, entry_setup, entry_level = 1, long_setup, long_level
        elif can_enter and cfg.allow_shorts and short_setup and not long_setup:
            entry_side, entry_setup, entry_level = -1, short_setup, short_level

        if entry_side != 0:
            rvol_aligned = not _isna(rvol) and rvol >= cfg.rvol_min
            rs_aligned = not _isna(rs_vs_bench) and (rs_vs_bench > 0 if entry_side == 1 else rs_vs_bench < 0)
            rs_strong = not _isna(rs_vs_bench) and entry_side * rs_vs_bench >= cfg.min_rs_pct
            gap_aligned = _isna(gap_atr) or (gap_atr > -0.25 if entry_side == 1 else gap_atr < 0.25)
            vwap_aligned = c > session_vwap if entry_side == 1 else c < session_vwap
            ema_aligned = e9 > e20 if entry_side == 1 else e9 < e20
            score = sum((vwap_aligned, ema_aligned, rvol_aligned, rs_aligned, gap_aligned))
            grade = _grade(cfg, tier, entry_setup, rvol_aligned, rs_aligned, rs_strong)
            if _window_allows(cfg, window, grade):
                size_tag = size_for(grade, window, tier)
                risk = _risk(cfg, c, atr, entry_level, entry_side)
                stop_price = c - entry_side * risk
                budget = cfg.risk_per_trade if size_tag == "full" else cfg.risk_per_trade / 2
                overnight_candidate = cfg.hold_power_overnight and window == "power" and grade == "A"
                position = Trade(
                    ticker=ticker,
                    side=entry_side,
                    setup=entry_setup,
                    grade=grade,
                    size=size_tag,
                    score=score,
                    window=window,
                    tier=tier,
                    rvol=rvol,
                    rs_vs_spy=rs_vs_bench,
                    gap_atr=gap_atr,
                    ext_atr=entry_side * (c - session_vwap) / atr,
                    risk_atr=risk / atr,
                    dte_hint="4_7dte" if overnight_candidate else "0dte",
                    entry_bar=i,
                    entry_time=bar.time,
                    entry_ref=c,
                    entry_price=round(c + entry_side * slip, 10),
                    stop=stop_price,
                    risk=risk,
                    quantity=max(1, math.floor(budget / risk)),
                    risk_budget=budget,
                )
                result.trades.append(position)
                trade_side = entry_side
                trade_entry = c
                trade_stop = stop_price
                trade_risk = risk
                trade_best = c
                trade_entry_bar = i
                trade_entry_time = time_close
                trade_entry_day = day_key
                trade_stage = "stop"
                trade_window = window
                trade_grade = grade
                trade_overnight = False
                entries_today += 1
                _record(result, bar, i, entry_side, entry_setup, "entered", grade, rvol, rs_vs_bench)
            else:
                outcome = "grade_c" if grade == "C" else "window"
                _record(result, bar, i, entry_side, entry_setup, outcome, grade, rvol, rs_vs_bench)
        elif is_rth and (long_setup or short_setup):
            if not can_enter:
                outcome = blocked
            elif long_setup and short_setup:
                outcome = "both_sides"
            else:
                outcome = "shorts_off"
            for side, setup in ((1, long_setup), (-1, short_setup)):
                if setup:
                    _record(result, bar, i, side, setup, outcome, "", rvol, rs_vs_bench)

        # --- manage the open trade; orders placed here act from the next bar.
        if trade_side != 0:
            if i > trade_entry_bar:
                trade_best = max(trade_best, h) if trade_side == 1 else min(trade_best, lo)
            mfe_r = trade_side * (trade_best - trade_entry) / trade_risk
            if mfe_r >= cfg.breakeven_at_r and trade_stage == "stop":
                trade_stop = trade_entry
                trade_stage = "be"
            if mfe_r >= cfg.trail_start_r:
                trail_candidate = trade_best - trade_side * cfg.trail_offset_r * trade_risk
                if trade_side * (trail_candidate - trade_stop) > 0:
                    trade_stop = trail_candidate
                    trade_stage = "trail"
            assert trade_entry_time is not None
            minutes_in_trade = (time_close - trade_entry_time).total_seconds() / 60
            at_flat_time = is_rth and close_minute >= flat_min
            keep_overnight = (
                cfg.hold_power_overnight
                and trade_window == "power"
                and trade_grade == "A"
                and mfe_r >= cfg.time_stop_min_r
            )
            if at_flat_time and not trade_overnight and keep_overnight:
                trade_overnight = True
            close_reason = ""
            if trade_overnight and is_rth and not at_flat_time and day_key != trade_entry_day and m >= overnight_exit_min:
                close_reason = "overnight_exit"
            elif not trade_overnight and (at_flat_time or not is_rth):
                close_reason = "eod"
            elif not trade_overnight and minutes_in_trade >= cfg.time_stop_min and mfe_r < cfg.time_stop_min_r:
                close_reason = "time"
            if close_reason:
                if position is not None:
                    close_position(i, bar, c - position.side * slip, close_reason, mfe_r)
            else:
                order_stop = _round_tick(trade_stop, tick)
                order_limit = (
                    _round_tick(trade_entry + trade_side * cfg.target_r * trade_risk, tick) if cfg.target_r > 0 else NA
                )
                order_reason = trade_stage
                order_mfe_r = mfe_r

        prev_day = day_key
        prev_is_rth = is_rth
        prev_close = [c, prev_close[0]]
        prev_vwap = [session_vwap, prev_vwap[0]]

    return result


def session_window(cfg: MarketMapConfig, minute: int) -> str:
    """The Pine's `window` for a bar opening `minute` minutes after midnight ET."""
    if not RTH_OPEN <= minute < RTH_CLOSE:
        return "closed"
    if minute < _minutes(cfg.open_window_end):
        return "open"
    return "midday" if minute < _minutes(cfg.power_window_start) else "power"


def size_for(grade: str, window: str, tier: str) -> str:
    return "full" if grade == "A" and window != "midday" and tier != "avoid" else "half"


def grade_for(
    cfg: MarketMapConfig, tier: str, setup: str, side: int, rvol: float, rs_vs_bench: float
) -> str:
    """`f_grade` with the Pine's alignment flags computed from RVOL and relative strength."""
    rvol_aligned = not _isna(rvol) and rvol >= cfg.rvol_min
    rs_aligned = not _isna(rs_vs_bench) and (rs_vs_bench > 0 if side == 1 else rs_vs_bench < 0)
    rs_strong = not _isna(rs_vs_bench) and side * rs_vs_bench >= cfg.min_rs_pct
    return _grade(cfg, tier, setup, rvol_aligned, rs_aligned, rs_strong)


def _rvol(history: list[list[float]], index: int, current: float) -> float:
    total = 0.0
    count = 0
    if 0 <= index < MAX_SESSION_BARS:
        for row in history:
            past = row[index]
            if not _isna(past) and past > 0:
                total += past
                count += 1
    return current / (total / count) if count > 0 and current > 0 else NA


def _entry_block(
    in_trade: bool,
    or_complete: bool,
    before_last_entry: bool,
    cooled_down: bool,
    entries_left: bool,
    losses_left: bool,
    has_atr: bool,
    symbol_valid: bool,
    tier_allowed: bool,
) -> str:
    """Pine's `canEnter`, returning the first condition that fails ("" when it passes)."""
    for ok, reason in (
        (not in_trade, "in_trade"),
        (or_complete, "or_incomplete"),
        (before_last_entry, "after_last_entry"),
        (cooled_down, "cooldown"),
        (entries_left, "max_entries"),
        (losses_left, "max_losses"),
        (has_atr, "no_atr"),
        (symbol_valid, "invalid_symbol"),
        (tier_allowed, "avoid_tier"),
    ):
        if not ok:
            return reason
    return ""


def _grade(
    cfg: MarketMapConfig, tier: str, setup: str, rvol_aligned: bool, rs_aligned: bool, rs_strong: bool
) -> str:
    if cfg.grade_rule == GRADE_RVOL_OR_RS:
        if setup == "orb_fail":
            base = "B" if rvol_aligned or rs_aligned else "C"
        else:
            base = "A" if rvol_aligned and rs_aligned else "B" if rvol_aligned or rs_aligned else "C"
    elif cfg.grade_rule == GRADE_RS_GATE:
        base = "C" if not rs_strong else "B" if setup == "orb_fail" else "A" if rvol_aligned else "B"
    else:
        raise ValueError(f"unknown grade_rule {cfg.grade_rule!r}")
    return "B" if tier == "avoid" and base == "A" else base


def _window_allows(cfg: MarketMapConfig, window: str, grade: str) -> bool:
    if grade == "C":
        return False
    if window != "midday":
        return True
    if cfg.midday_mode == MIDDAY_ALLOW:
        return True
    if cfg.midday_mode == MIDDAY_A_HALF:
        return grade == "A"
    return False


def _risk(cfg: MarketMapConfig, close: float, atr: float, level: float, side: int) -> float:
    structure_stop = level - cfg.level_buffer_atr * atr if side == 1 else level + cfg.level_buffer_atr * atr
    raw = close - structure_stop if side == 1 else structure_stop - close
    max_risk = cfg.max_heat_atr * atr
    if _isna(raw):
        return max_risk
    return min(max(raw, cfg.min_risk_atr * atr), max_risk)


def _round_tick(price: float, tick: float) -> float:
    return round(round(price / tick) * tick, 10)


def _exit_fill(
    side: int, bar_open: float, high: float, low: float, stop: float, limit: float, tick: float
) -> tuple[str, float] | None:
    """Which resting exit order a bar fills, and at what price before slippage.

    A bar that opens through an order fills it at the open. When a bar
    reaches both the stop and the limit, the broker emulator assumes the
    extreme nearer the open came first.
    """
    if side == 1:
        stop_hit = not _isna(stop) and low <= stop
        limit_hit = not _isna(limit) and high >= limit
        if stop_hit and bar_open <= stop:
            return "stop", bar_open
        if limit_hit and bar_open >= limit:
            return "limit", bar_open
    else:
        stop_hit = not _isna(stop) and high >= stop
        limit_hit = not _isna(limit) and low <= limit
        if stop_hit and bar_open >= stop:
            return "stop", bar_open
        if limit_hit and bar_open <= limit:
            return "limit", bar_open
    if stop_hit and limit_hit:
        high_first = high - bar_open <= bar_open - low
        stop_first = (not high_first) if side == 1 else high_first
        return ("stop", stop) if stop_first else ("limit", limit)
    if stop_hit:
        return "stop", stop
    if limit_hit:
        return "limit", limit
    return None


def _record(
    result: BacktestResult,
    bar: Bar,
    index: int,
    side: int,
    setup: str,
    outcome: str,
    grade: str,
    rvol: float,
    rs: float,
) -> None:
    result.signals.append(Signal(bar.time, index, side, setup, outcome, grade, rvol, rs))
