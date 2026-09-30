"""The strategy factory's engine on synthetic bars: data, execution, families, model, gates.

The recovery swing and VWAP reclaim families were also checked trade for
trade against the engines they came from (`nbis_swing`, `vwap_reclaim` on
branch claude/nbis-recovery-swing): 4,134 and 20,600 identical trades on 18
tickers of SIP bars, 2023-06 to 2026-09 (docs/strategy-factory.md). These
tests pin the same behaviour on bars small enough to reason about.

Flat warm-up bars have a true range of exactly 1.0, so ATR(14) is 1.0 and
stops land on round numbers; costs are one tick with no basis points unless a
test says otherwise.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

import pytest

from app.engine import factory_gates
from app.engine.factory_data import (
    FEATURES,
    FeatureContext,
    Series,
    Split,
    adjust_for_splits,
    atr,
    ema,
    find_splits,
    session_bars,
    session_vwap,
)
from app.engine.factory_gates import (
    PERIODS,
    Check,
    Gate,
    Stats,
    clustered_mean,
    confirm_gate,
    discovery_trades,
    evaluate,
    exam_gate,
    ledger_record,
    prior_candidates,
    report,
    required_t,
    screen_gate,
    summarize,
)
from app.engine.factory_model import LogisticModel, fit_logistic
from app.engine.factory_rules import (
    FAMILIES,
    MODEL_DEFAULT_FEATURES,
    AtrStop,
    Context,
    Costs,
    Exits,
    FailedBreakout,
    Limits,
    OpeningRangeBreakout,
    RecoverySwing,
    Signal,
    SwingStop,
    Trade,
    VwapReclaim,
    baseline_signals,
    canonical,
    from_canonical,
    parse_spec,
    run_candidate,
    run_each,
    spec_id,
)
from app.engine.market_map import ET, Bar, DailyBar

TICK = Costs(slippage_ticks=1, slippage_bps=0.0)


def at(day: date, minute: int) -> datetime:
    return datetime(day.year, day.month, day.day, minute // 60, minute % 60, tzinfo=ET)


def weekdays(first: date, count: int) -> list[date]:
    days, current = [], first
    while len(days) < count:
        if current.weekday() < 5:
            days.append(current)
        current += timedelta(days=1)
    return days


def bar(day: date, minute: int, o: float, h: float, lo: float, c: float, v: float = 1000.0) -> Bar:
    assert lo <= min(o, c) and h >= max(o, c), (minute, o, h, lo, c)
    return Bar(at(day, minute), o, h, lo, c, v)


def flat(day: date, count: int, tf: int, price: float = 100.0, up: float = 0.5, down: float = 0.5,
         start: int = 570) -> list[Bar]:
    """`count` bars at `price` from `start`, each spanning `down` below to `up` above it."""
    return [bar(day, start + tf * k, price, price + up, price - down, price) for k in range(count)]


# --- data ---------------------------------------------------------------------------


def test_session_bars_end_at_one_on_an_early_close_day():
    early, normal = date(2025, 11, 28), date(2025, 12, 1)
    raw = [bar(day, minute, 1, 1, 1, 1) for day in (early, normal) for minute in (540, 570, 779, 780, 959, 960)]
    kept = [(b.time.astimezone(ET).date(), b.time.astimezone(ET).hour * 60 + b.time.astimezone(ET).minute)
            for b in session_bars(raw)]
    assert kept == [(early, 570), (early, 779), (normal, 570), (normal, 779), (normal, 780), (normal, 959)]


def test_a_ten_for_one_split_is_found_and_taken_out():
    d1, d2, d3 = weekdays(date(2024, 6, 6), 3)
    bars = [bar(d1, 570, 1000, 1010, 990, 1005, 100), bar(d2, 570, 100.8, 101, 99, 100, 1000),
            bar(d3, 570, 100, 102, 99, 101, 1000)]
    assert find_splits(Series.build("X", bars, 15).daily) == []  # already adjusted: no jump left
    raw_daily = [DailyBar(d1, 1000, 1010, 990, 1005), DailyBar(d2, 100.8, 101, 99, 100), DailyBar(d3, 100, 102, 99, 101)]
    assert find_splits(raw_daily) == [Split(d2, 10.0)]
    series = Series.build("X", bars, 15)
    assert series.splits == [Split(d2, 10.0)]
    assert (series.open[0], series.high[0], series.close[0], series.volume[0]) == (100.0, 101.0, 100.5, 1000.0)
    assert series.close[1:] == [100, 101]


def test_a_reverse_split_and_an_ordinary_crash():
    d1, d2 = weekdays(date(2024, 6, 6), 2)
    assert find_splits([DailyBar(d1, 10, 10, 10, 10), DailyBar(d2, 99, 101, 98, 100)]) == [Split(d2, 0.1)]
    # A 45% overnight fall is not a whole ratio, so it stays as price action.
    assert find_splits([DailyBar(d1, 100, 100, 100, 100), DailyBar(d2, 55, 56, 54, 55)]) == []
    adjusted = adjust_for_splits([bar(d1, 570, 10, 10, 10, 10, 500)], [Split(d2, 0.1)])
    assert adjusted[0].close == 100 and adjusted[0].volume == 50


def test_series_numbers_sessions_and_marks_their_last_bars():
    d1, d2 = weekdays(date(2025, 3, 3), 2)
    series = Series.build("x", flat(d1, 3, 15) + flat(d2, 2, 15), 15)
    assert series.ticker == "X"
    assert series.session == [0, 0, 0, 1, 1]
    assert series.last == [False, False, True, False, True]
    assert series.days == [d1, d2]
    assert series.close_minute(0) == 585


def test_ema_and_atr_seed_with_the_simple_average():
    assert ema([1, 2, 3, 4], 3)[2:] == [2.0, 3.0]
    assert math.isnan(ema([1, 2, 3, 4], 3)[1])
    # The first true range is high minus low; later ones reach back to the prior close.
    values = atr([2, 3, 10], [1, 2, 9], [1.5, 2.5, 9.5], 2)
    assert math.isnan(values[0]) and values[1] == (1.0 + 1.5) / 2 and values[2] == (1.25 + 7.5) / 2


def test_vwap_resets_each_session():
    d1, d2 = weekdays(date(2025, 3, 3), 2)
    series = Series.build("X", [bar(d1, 570, 10, 11, 9, 10, 1), bar(d1, 571, 20, 21, 19, 20, 3),
                                bar(d2, 570, 50, 51, 49, 50, 2)], 1)
    assert session_vwap(series) == [10.0, 17.5, 50.0]


def warm_sessions(count: int, tf: int, first: date = date(2025, 1, 6)) -> tuple[list[Bar], list[date]]:
    days = weekdays(first, count + 5)
    bars = [b for day in days[:count] for b in flat(day, 390 // tf, tf, up=1.0, down=0.0)]
    return bars, days


def test_features_read_only_the_past():
    bars, days = warm_sessions(25, 15)
    day = days[25]
    today = [bar(day, 570, 102, 103, 101.5, 102.5, 3000), bar(day, 585, 102.5, 104, 102, 103.5, 1000),
             bar(day, 600, 103.5, 104, 103, 103, 1000)]
    spy_bars, _ = warm_sessions(25, 15)
    spy = Series.build("SPY", spy_bars + [bar(day, 570, 100, 101, 99.8, 100.5), bar(day, 585, 100.5, 101, 100, 101)], 15)
    series = Series.build("X", bars + today, 15)
    context = FeatureContext(series, spy)
    i = len(bars) + 1
    values = context.at(i, 1, stop=101.5)
    # Daily ATR of the flat sessions is 1.0 and their EMA 100; the gap is 102 - 100.
    assert values["gap"] == pytest.approx(2.0)
    assert values["day_move"] == pytest.approx(1.5)
    assert values["trend"] == pytest.approx(3.5)
    assert values["trend_slope"] == pytest.approx(0.0)
    assert values["minutes"] == 30
    assert values["rvol"] == pytest.approx(4000 / 2000)
    assert values["risk"] == pytest.approx(2.0 / context.chart_atr[i])
    assert values["spy_trend"] == pytest.approx(1.0)
    assert values["spy_day"] == pytest.approx(1.0)
    assert values["rel_strength"] == pytest.approx(100 * (0.035 - 0.01))
    assert context.at(i, -1, stop=105.5)["trend"] == pytest.approx(-3.5)
    # VWAP through the signal bar: typical prices 307/3 on 3,000 shares and 309.5/3 on 1,000.
    vwap = (307 / 3 * 3000 + 309.5 / 3 * 1000) / 4000
    assert values["vwap_distance"] == pytest.approx((103.5 - vwap) / context.chart_atr[i])
    assert context.at(i, -1, stop=105.5)["vwap_distance"] == pytest.approx(-values["vwap_distance"])
    assert values["vol_ratio"] == pytest.approx(1.0)  # every flat session ranges 1.0
    assert values["spy_vol"] == pytest.approx(1.0)  # SPY's daily ATR 1.0 on a 100 close
    assert values["open_trend"] == pytest.approx(2.0)  # opened at 102 over an EMA of 100
    assert context.at(i, -1, stop=105.5)["open_trend"] == pytest.approx(-2.0)
    later = Series.build("X", bars + today[:2] + [bar(day, 600, 103.5, 150, 50, 60, 99999)], 15)
    assert FeatureContext(later, spy).at(i, 1, stop=101.5) == values


def test_vol_ratio_compares_the_last_week_with_the_month_through_the_prior_session():
    days = weekdays(date(2025, 1, 6), 31)
    calm = [b for day in days[:25] for b in flat(day, 13, 30, up=1.0, down=0.0)]  # a daily range of 1
    wild = [b for day in days[25:30] for b in flat(day, 13, 30, up=2.0, down=1.0)]  # a daily range of 3
    series = Series.build("X", calm + wild + flat(days[30], 2, 30), 30)
    week = month = 1.0
    for _ in range(5):  # Wilder's averages over the five wild sessions
        week, month = (4 * week + 3) / 5, (19 * month + 3) / 20
    context = FeatureContext(series, None)
    assert context.at(len(series) - 1, 1, stop=99.0)["vol_ratio"] == pytest.approx(week / month)
    assert context.at(len(calm), 1, stop=99.0)["vol_ratio"] == pytest.approx(1.0)  # the first wild session reads the calm ones
    assert math.isnan(context.at(len(series) - 1, 1, stop=99.0)["spy_vol"])  # no market, no market features
    spy = Series.build("SPY", [b for day in days for b in flat(day, 13, 30, price=400.0, up=2.0, down=0.0)], 30)
    assert FeatureContext(series, spy).at(len(series) - 1, 1, stop=99.0)["spy_vol"] == pytest.approx(0.5)


# --- the execution model ----------------------------------------------------------


@dataclass
class Scripted:
    """Signals `plan[i] = (side, stop)` at bar i when flat; records what the runner told it."""

    plan: dict[int, tuple[int, float]]
    seen: list[tuple[int, bool, bool]] = field(default_factory=list)
    force: bool = False

    def on_bar(self, i: int, ctx: Context) -> Signal | None:
        self.seen.append((i, ctx.flat, ctx.halted))
        if i in self.plan and (ctx.flat or self.force):
            side, stop = self.plan[i]
            signal = Signal(i, side, stop)
            return signal if ctx.accept(signal) else None
        return None


DAY, NEXT = date(2025, 3, 4), date(2025, 3, 5)


def one_day(bars_after: list[tuple[float, float, float, float]], tf: int = 15, day: date = DAY) -> list[Bar]:
    """A bar at 100 at 09:30, then `bars_after` (open, high, low, close)."""
    return [bar(day, 570, 100, 100.5, 99.5, 100)] + [
        bar(day, 570 + tf * (k + 1), *values) for k, values in enumerate(bars_after)]


def test_the_entry_fills_at_the_next_open_with_slippage_and_sets_the_target():
    series = Series.build("X", one_day([(100.2, 100.4, 100.0, 100.3)]), 15)
    (trade,) = run_candidate(series, Scripted({0: (1, 99.2)}), Exits(2.0), TICK)
    assert (trade.entry_index, trade.entry_price, trade.stop) == (1, 100.21, 99.2)
    assert trade.target == pytest.approx(100.21 + 2 * 1.01)
    assert trade.features == {}
    assert Costs().slip(100.0) == pytest.approx(0.01) and Costs().slip(250.0) == pytest.approx(0.025)
    assert Costs().times(3).slip(250.0) == pytest.approx(0.075)


def test_no_trade_when_the_open_is_through_the_stop():
    series = Series.build("X", one_day([(99.0, 99.5, 98.5, 99.2)]), 15)
    assert run_candidate(series, Scripted({0: (1, 99.2)}), Exits(2.0), TICK) == []
    assert run_candidate(series, Scripted({0: (-1, 99.0)}), Exits(2.0), TICK) == []


# A long signalled at 09:30 with its stop at 99.2 fills at 100.01 (one tick), so 1R is 0.81 and the 1R target 100.82.
@pytest.mark.parametrize(
    "after, price, reason, both",
    [
        ([(100.0, 100.5, 99.0, 99.5)], 99.19, "stop", False),  # the resting stop, slipped
        ([(100.0, 102.5, 99.5, 102.0)], 100.82, "target", False),  # the target, not slipped
        ([(100.0, 102.5, 99.0, 100.0)], 99.19, "stop", True),  # one bar reaches both: the stop
        ([(100.0, 100.5, 99.5, 100.0), (98.0, 98.5, 97.5, 98.0)], 97.99, "stop", False),  # opens through the stop
        ([(100.0, 100.5, 99.5, 100.0), (103.0, 103.5, 102.5, 103.0)], 103.0, "target", False),  # opens through the target
        ([(100.0, 100.5, 99.5, 100.0), (100.0, 100.8, 99.6, 100.6)], 100.59, "session", False),  # the session's last close
    ],
)
def test_exits(after, price, reason, both):
    series = Series.build("X", one_day(after), 15)
    (trade,) = run_candidate(series, Scripted({0: (1, 99.2)}), Exits(1.0), TICK)
    assert (trade.exit_reason, trade.exit_price, trade.both_hit) == (reason, pytest.approx(price), both)


def test_a_short_mirrors_the_long():
    series = Series.build("X", one_day([(100.0, 100.5, 99.4, 99.5), (99.5, 99.9, 98.0, 98.2)]), 15)
    (trade,) = run_candidate(series, Scripted({0: (-1, 100.8)}), Exits(1.0), TICK)
    assert (trade.entry_price, trade.target, trade.exit_reason) == (99.99, 99.18, "target")
    assert trade.r == pytest.approx(1.0)


def test_a_swing_holds_to_the_last_bar_of_its_second_session():
    after = [(100.0, 100.5, 99.5, 100.0)]
    bars = one_day(after) + [bar(NEXT, 570, 100.2, 100.5, 99.8, 100.1), bar(NEXT, 585, 100.1, 100.6, 99.9, 100.4)]
    series = Series.build("X", bars, 15)
    (trade,) = run_candidate(series, Scripted({0: (1, 99.2)}), Exits(2.0, max_sessions=2), TICK)
    assert (trade.exit_index, trade.exit_price, trade.exit_reason, trade.sessions_held) == (3, 100.39, "session", 2)
    (intraday,) = run_candidate(series, Scripted({0: (1, 99.2)}), Exits(2.0, max_sessions=1), TICK)
    assert (intraday.exit_index, intraday.exit_reason, intraday.sessions_held) == (1, "session", 1)


def test_a_time_limit_exits_at_the_close_of_the_bar_that_reaches_it():
    bars = [bar(DAY, 570 + k, 100, 100.2, 99.8, 100) for k in range(10)]
    series = Series.build("X", bars, 1)
    (trade,) = run_candidate(series, Scripted({0: (1, 99.0)}), Exits(2.0, max_minutes=3), TICK)
    # Filled at 09:31's open, so 09:33's close is three minutes on.
    assert (trade.exit_index, trade.exit_reason, trade.exit_price) == (3, "time", 99.99)


def test_an_order_at_the_close_waits_for_the_next_session_only_when_holding_overnight():
    bars = [bar(DAY, 945, 100, 100.5, 99.5, 100)] + flat(NEXT, 3, 15, 100.5)
    series = Series.build("X", bars, 15)
    assert run_candidate(series, Scripted({0: (1, 99.0)}), Exits(2.0, max_sessions=1), TICK) == []
    (swing,) = run_candidate(series, Scripted({0: (1, 99.0)}), Exits(2.0, max_sessions=2), TICK)
    assert swing.entry_time == at(NEXT, 570)
    assert len(run_each(series, [Signal(0, 1, 99.0)], Exits(2.0, max_sessions=1), TICK)) == 0


def test_one_position_at_a_time():
    series = Series.build("X", flat(DAY, 6, 15), 15)
    family = Scripted({0: (1, 98.0), 2: (1, 98.0), 4: (1, 98.0)})
    trades = run_candidate(series, family, Exits(3.0), TICK)
    assert [t.entry_index for t in trades] == [1]
    assert [flat_ for _, flat_, _ in family.seen] == [True, False, False, False, False, True]
    with pytest.raises(RuntimeError):
        run_candidate(series, Scripted({0: (1, 98.0), 2: (1, 98.0)}, force=True), Exits(3.0), TICK)


def test_session_limits_stop_new_entries_until_the_next_session():
    losing = [(100.0, 100.2, 98.0, 98.5), (98.5, 100.2, 98.4, 100.0)] * 3
    bars = one_day(losing) + one_day(losing, day=NEXT)
    series = Series.build("X", bars, 15)
    plan = {start + k: (1, 99.0) for start in (0, 7) for k in (0, 2, 4)}  # 09:30, 10:00 and 10:30 each day
    assert len(run_candidate(series, Scripted(dict(plan)), Exits(2.0), TICK)) == 6  # three a day without limits
    for limits, per_day in ((Limits(max_entries=2), 2), (Limits(max_losses=1), 1), (Limits(max_loss_r=1.5), 2)):
        trades = run_candidate(series, Scripted(dict(plan)), Exits(2.0), TICK, limits=limits)
        days = [t.entry_time.astimezone(ET).date() for t in trades]
        assert days.count(DAY) == per_day and days.count(NEXT) == per_day, limits


def test_the_entry_window_is_on_the_fill_time():
    series = Series.build("X", flat(DAY, 6, 15), 15)
    trades = run_candidate(series, Scripted({0: (1, 98.0), 3: (1, 98.0)}), Exits(3.0, max_minutes=15), TICK,
                           window=(630, 900))
    assert [t.signal_index for t in trades] == [3]  # 09:30 closes 09:45, before 10:30; 10:15 closes at 10:30


def test_run_each_takes_overlapping_signals():
    series = Series.build("X", one_day([(100.0, 100.5, 99.5, 100.0)] * 4), 15)
    trades = run_each(series, [Signal(0, 1, 99.0), Signal(1, 1, 99.0), Signal(1, -1, 101.0)], Exits(2.0), TICK)
    assert [(t.entry_index, t.side, t.exit_reason) for t in trades] == [(1, 1, "session"), (2, 1, "session"),
                                                                        (2, -1, "session")]


# --- moving the stop ------------------------------------------------------------------
#
# The long signalled at 09:30 with its stop at 99.2 again: filled at 100.01,
# 1R is 0.81, so +0.5R is 100.415 and +1R is 100.82.

LONG = {0: (1, 99.2)}


def test_breakeven_moves_the_stop_to_the_entry_after_the_bar_that_reached_it():
    after = [(100.0, 100.9, 99.5, 100.5), (100.5, 100.6, 99.9, 100.0), (100.0, 100.2, 99.8, 100.1)]
    series = Series.build("X", one_day(after), 15)
    (moved,) = run_candidate(series, Scripted(dict(LONG)), Exits(None, breakeven_r=1.0), TICK)
    assert (moved.exit_index, moved.exit_reason, moved.exit_price) == (2, "breakeven", pytest.approx(100.0))
    assert moved.r == pytest.approx(-0.01 / 0.81)  # the entry, less a tick of slippage
    (held,) = run_candidate(series, Scripted(dict(LONG)), Exits(None), TICK)
    assert (held.exit_index, held.exit_reason, held.moved_stop) == (3, "session", None)
    short_of_it = [(100.0, 100.8, 99.5, 100.5)] + after[1:]  # a high 0.02 under +1R moves nothing
    (kept,) = run_candidate(Series.build("X", one_day(short_of_it), 15), Scripted(dict(LONG)),
                            Exits(None, breakeven_r=1.0), TICK)
    assert (kept.exit_reason, kept.moved_stop) == ("session", None)


def test_the_bar_that_reaches_the_trigger_still_rests_on_the_old_stop():
    # Its high reaches +1R and its low trades back under the entry, in an order the bar does not tell.
    after = [(100.0, 100.9, 99.9, 100.2), (100.2, 100.3, 100.1, 100.2)]
    (trade,) = run_candidate(Series.build("X", one_day(after), 15), Scripted(dict(LONG)),
                             Exits(None, breakeven_r=1.0), TICK)
    assert (trade.exit_index, trade.exit_reason, trade.moved_stop, trade.moved_by) == (2, "session", 100.01, "breakeven")


def test_a_gap_through_a_moved_stop_fills_at_the_open():
    after = [(100.0, 100.9, 99.5, 100.5), (99.8, 100.0, 99.6, 99.9)]
    (trade,) = run_candidate(Series.build("X", one_day(after), 15), Scripted(dict(LONG)),
                             Exits(None, breakeven_r=1.0), TICK)
    assert (trade.exit_index, trade.exit_reason, trade.exit_price) == (2, "breakeven", pytest.approx(99.79))


def test_a_trailing_stop_follows_the_best_price():
    # 0.81 under the highest high so far: 100.19 after 101.0, 100.69 after 101.5, and there it stays.
    after = [(100.0, 101.0, 99.8, 100.9), (100.9, 101.5, 100.6, 101.4), (101.4, 101.45, 101.0, 101.2),
             (101.2, 101.3, 100.5, 100.6)]
    series = Series.build("X", one_day(after), 15)
    (trade,) = run_candidate(series, Scripted(dict(LONG)), Exits(None, trail_r=1.0), TICK)
    assert (trade.exit_index, trade.exit_reason, trade.exit_price) == (4, "trail", pytest.approx(100.68))
    assert trade.best == 101.5 and trade.r == pytest.approx((100.68 - 100.01) / 0.81)
    # Random entries go through the same exits.
    (each,) = run_each(series, [Signal(0, 1, 99.2)], Exits(None, trail_r=1.0), TICK)
    assert (each.exit_index, each.exit_reason, each.exit_price) == (4, "trail", trade.exit_price)


def test_with_both_rules_the_tighter_stop_wins_and_never_moves_back():
    # +0.5R puts the stop at the entry; a 2R trail (1.62) passes the entry only once the high is over 101.63.
    after = [(100.0, 100.5, 99.8, 100.4), (100.4, 101.0, 100.3, 100.9), (100.9, 102.0, 100.8, 101.9),
             (101.9, 101.95, 100.2, 100.3)]
    exits = Exits(None, breakeven_r=0.5, trail_r=2.0)
    (early,) = run_candidate(Series.build("X", one_day(after[:2]), 15), Scripted(dict(LONG)), exits, TICK)
    assert (early.exit_reason, early.moved_stop, early.moved_by) == ("session", 100.01, "breakeven")
    (trade,) = run_candidate(Series.build("X", one_day(after), 15), Scripted(dict(LONG)), exits, TICK)
    assert (trade.exit_index, trade.exit_reason, trade.exit_price) == (4, "trail", pytest.approx(100.37))


def test_a_stall_check_exits_a_trade_that_is_not_working_once_and_only_once():
    # The long fills at 100.01 at 09:45 with 1R 0.81, so +0.5R is a close of 100.415. The 30-minute check
    # falls at the close of the 10:00 bar; the 10:15 bar's weak close comes after it and changes nothing.
    exits = Exits(None, stall_minutes=30, stall_r=0.5)
    stalled = [(100.0, 100.4, 99.8, 100.1), (100.1, 100.4, 100.0, 100.3), (100.3, 100.5, 99.9, 100.0)]
    (trade,) = run_candidate(Series.build("X", one_day(stalled), 15), Scripted(dict(LONG)), exits, TICK)
    assert (trade.exit_index, trade.exit_reason, trade.exit_price) == (2, "stall", pytest.approx(100.29))
    working = [(100.0, 100.4, 99.8, 100.1), (100.1, 100.6, 100.0, 100.5), (100.5, 100.6, 99.9, 100.0)]
    (kept,) = run_candidate(Series.build("X", one_day(working), 15), Scripted(dict(LONG)), exits, TICK)
    assert (kept.exit_index, kept.exit_reason, kept.stall_checked) == (3, "session", True)
    # Left out, stall_r is 0: in profit at all passes.
    (flat_bar,) = run_candidate(Series.build("X", one_day(stalled), 15), Scripted(dict(LONG)),
                                Exits(None, stall_minutes=30, stall_r=0.0), TICK)
    assert flat_bar.exit_reason == "session"
    (short,) = run_candidate(Series.build("X", one_day([(100.0, 100.2, 99.6, 99.9), (99.9, 100.1, 99.7, 99.8), (99.8, 100.0, 99.6, 99.7)]), 15),
                             Scripted({0: (-1, 100.8)}), exits, TICK)
    assert (short.exit_index, short.exit_reason) == (2, "stall")  # 0.19 in favour of a short is under +0.5R
    (each,) = run_each(Series.build("X", one_day(stalled), 15), [Signal(0, 1, 99.2)], exits, TICK)
    assert (each.exit_index, each.exit_reason) == (2, "stall")  # the random baseline gets the same exit


def test_a_short_moves_its_stop_down():
    # Short at 99.99 with the stop at 100.8: 1R is 0.81, so -1R is 99.18. The trail sits 0.81 over the
    # lowest low: 99.81 after 99.0, then 99.41 after 98.6.
    after = [(100.0, 100.2, 99.0, 99.1), (99.1, 99.5, 98.6, 98.7), (98.7, 99.45, 98.65, 99.4)]
    series = Series.build("X", one_day(after), 15)
    (trailed,) = run_candidate(series, Scripted({0: (-1, 100.8)}), Exits(None, trail_r=1.0), TICK)
    assert (trailed.exit_index, trailed.exit_reason, trailed.exit_price) == (3, "trail", pytest.approx(99.42))
    assert trailed.best == 98.6 and trailed.r == pytest.approx((99.99 - 99.42) / 0.81)
    (even,) = run_candidate(series, Scripted({0: (-1, 100.8)}), Exits(None, breakeven_r=1.0), TICK)
    assert (even.exit_reason, even.moved_stop, even.moved_by) == ("session", 99.99, "breakeven")


def test_moved_stops_only_tighten_and_a_rule_that_never_moves_them_changes_nothing():
    rng = random.Random(7)
    price, bars = 100.0, []
    for day in weekdays(DAY, 20):
        for k in range(26):
            o = price
            c = o + rng.gauss(0, 0.3)
            bars.append(bar(day, 570 + 15 * k, o, max(o, c) + abs(rng.gauss(0, 0.2)), min(o, c) - abs(rng.gauss(0, 0.2)), c))
            price = c
    series = Series.build("X", bars, 15)
    signals = [Signal(i, side, series.close[i] - side * 0.8) for i in range(0, len(series) - 1, 5)
               for side in (1, -1)]

    def outcomes(trades: list[Trade]) -> list[tuple]:
        return [(t.entry_index, t.side, t.exit_index, t.exit_price, t.exit_reason) for t in trades]

    plain = run_each(series, signals, Exits(1.5, max_sessions=2), TICK)
    assert outcomes(run_each(series, signals, Exits(1.5, max_sessions=2, trail_r=50.0), TICK)) == outcomes(plain)
    moved = run_each(series, signals, Exits(1.5, max_sessions=2, breakeven_r=0.5, trail_r=1.0), TICK)
    assert {"breakeven", "trail"} <= {t.exit_reason for t in moved}
    for t in moved:
        if t.moved_stop is not None:
            assert t.side * (t.moved_stop - t.stop) > 0 and t.side * (t.best - t.moved_stop) > 0
        if t.exit_reason in ("breakeven", "trail"):
            assert t.exit_reason == t.moved_by and t.side * (t.moved_stop - t.exit_price) >= 0.01 - 1e-9


def test_baseline_signals_use_the_stop_rule_the_window_and_the_stride():
    bars, days = warm_sessions(3, 15)
    series = Series.build("X", bars, 15)
    swing = baseline_signals(series, SwingStop(4, 0.1), (1,), days[0], days[2])
    first = swing[0]
    assert first.index == 13 and first.stop == pytest.approx(100.0 - 0.1)  # ATR(14) is ready at bar 13
    short = baseline_signals(series, AtrStop(1.5), (-1,), days[1], days[1])
    assert [round(s.stop, 9) for s in short] == [101.5] * 26
    windowed = baseline_signals(series, AtrStop(1.0), (1,), days[1], days[1], window=(600, 660))
    assert [series.close_minute(s.index) for s in windowed] == [600, 615, 630, 645, 660]
    strided = baseline_signals(series, AtrStop(1.0), (1,), days[1], days[2], stride=3)
    assert len(strided) == 17 and {series.session[s.index] for s in strided} == {1, 2}
    assert strided[0].index % 26 != strided[9].index % 26  # the offset turns with the session


# --- the recovery swing -------------------------------------------------------------
#
# 21 flat sessions at 100 with lows at 100 (no dip) seed the daily EMA 20 at
# 100, the 15-minute EMA 20 at 100 and ATR at 1.0. On day D the 09:30 bar
# dips to 99.3 (armed), three bars hold 99.8 under the falling EMA, and the
# 10:30 bar closes 100.5: back over the EMA (99.99) and the prior highs
# (100.3). Stop 99.3 - 0.1 = 99.2; the 10:45 fill is 100.51, so 1R is 1.31.

SWING_WARM, SWING_DAYS = warm_sessions(21, 15)
D, D1, D2 = SWING_DAYS[21], SWING_DAYS[22], SWING_DAYS[23]
DIP = [bar(D, 570, 100, 100.3, 99.3, 99.8)] + [bar(D, 570 + 15 * k, 99.8, 100.3, 99.3, 99.8) for k in (1, 2, 3)]
RECLAIM = bar(D, 630, 99.8, 100.5, 99.5, 100.5)


def swing(extra: list[Bar], rules: RecoverySwing = RecoverySwing(), exits: Exits = Exits(2.0, max_sessions=2)):
    series = Series.build("X", SWING_WARM + extra, 15)
    return run_candidate(series, rules.start(series), exits, TICK)


def test_recovery_swing_triggers_on_the_reclaim_and_reaches_the_target():
    (trade,) = swing(DIP + [RECLAIM, bar(D, 645, 100.5, 101, 100, 100.8), bar(D, 660, 100.8, 103.2, 100.8, 103)])
    assert trade.signal_time == at(D, 630) and trade.entry_time == at(D, 645)
    assert (trade.stop, trade.entry_price) == (pytest.approx(99.2), 100.51)
    assert trade.target == pytest.approx(103.13)
    assert (trade.exit_reason, trade.exit_price) == ("target", pytest.approx(103.13))
    assert trade.r == pytest.approx(2.0)


def test_recovery_swing_holds_overnight_and_gaps_through_its_stop():
    rest = [bar(D, 645 + 15 * k, 100.5, 100.9, 100.1, 100.6) for k in range(21)]
    (trade,) = swing(DIP + [RECLAIM] + rest + [bar(D1, 570, 98.0, 98.5, 97.5, 98.2)])
    assert (trade.exit_reason, trade.exit_price, trade.sessions_held) == ("stop", 97.99, 2)


def test_the_stop_covers_four_bars_and_the_breakout_three():
    # 09:45 (four bars back from the trigger) has the lowest low, 99.1: the stop is 99.0, not 99.2.
    low_first = [DIP[0], bar(D, 585, 99.8, 100.1, 99.1, 99.8), *DIP[2:]]
    (trade,) = swing(low_first + [RECLAIM, *flat(D, 3, 15, 100.5, start=645)])
    assert trade.stop == pytest.approx(99.0)
    # 09:45 reaching 100.6 (three bars back) leaves 10:30's close short of a breakout.
    high_first = [DIP[0], bar(D, 585, 99.8, 100.6, 99.6, 99.8), *DIP[2:]]
    assert swing(high_first + [RECLAIM, *flat(D, 3, 15, 100.5, up=0.2, down=0.2, start=645)]) == []


def test_the_arming_bar_never_triggers():
    # 09:30 dips under 100 and closes over the EMA and the prior highs (101) at once.
    assert swing([bar(D, 570, 100, 101.3, 99.3, 101.2)] + flat(D, 5, 15, 101.2, start=585)) == []


def test_an_arm_lasts_two_sessions_and_triggers_once():
    dip = [bar(D, 570, 100, 100.5, 99.5, 100)] + flat(D, 25, 15, up=0.5, down=0.0, start=585)
    quiet = flat(D1, 26, 15, up=0.5, down=0.0)

    def reclaim(day: date) -> list[Bar]:
        return flat(day, 4, 15, up=0.5, down=0.0) + [bar(day, 630, 100, 100.8, 100, 100.8)] + flat(
            day, 21, 15, 100.8, up=0.2, down=0.2, start=645)

    assert len(swing(dip + reclaim(D1))) == 1
    assert swing(dip + quiet + reclaim(D2)) == []


def test_an_arm_triggers_once():
    # After the target at 11:00, the price drifts back under the EMA without
    # trading under the daily EMA (100), then reclaims again at 14:15.
    hit = [bar(D, 645, 100.5, 101, 100, 100.8), bar(D, 660, 100.8, 103.2, 100.8, 103)]
    drift = [bar(D, 675 + 15 * k, 100.3, 100.4, 100.0, 100.2) for k in range(12)]
    again = [bar(D, 855, 100.2, 101.0, 100.1, 101.0)] + flat(D, 6, 15, 101, 0.2, 0.2, start=870)
    assert len(swing(DIP + [RECLAIM] + hit + drift + again)) == 1
    dipped = drift[:5] + [bar(D, 750, 100.3, 100.4, 99.9, 100.2)] + drift[6:]
    assert len(swing(DIP + [RECLAIM] + hit + dipped + again)) == 2


def test_the_daily_ema_reading_reclaims_the_prior_days_level():
    # D-1 closes at 101: the daily EMA for D is 100 + 1/10.5 = 100.095 and the 15-minute EMA near 101.
    warm = SWING_WARM + flat(SWING_DAYS[21], 26, 15, 101, up=0.5, down=0.0)
    day = SWING_DAYS[22]
    today = [bar(day, 570, 100.3, 100.4, 99.9, 100.05)] + [bar(day, 570 + 15 * k, 100.05, 100.4, 99.9, 100.05)
                                                          for k in (1, 2, 3)] + [
        bar(day, 630, 100.05, 100.6, 100.0, 100.6)] + flat(day, 21, 15, 100.6, up=0.2, down=0.2, start=645)
    series = Series.build("X", warm + today, 15)
    run = RecoverySwing(reclaim_level="daily_ema").start(series)
    assert run.level[len(warm)] == pytest.approx(100 + 2 / 21)
    assert run_candidate(series, RecoverySwing().start(series), Exits(2.0, max_sessions=2), TICK) == []
    (trade,) = run_candidate(series, run, Exits(2.0, max_sessions=2), TICK)
    assert trade.signal_time == at(day, 630)


# --- VWAP reclaim --------------------------------------------------------------------
#
# A prior session of flat one-minute bars seeds EMA 9 at 100 and ATR at 1.0.
# D opens with ten flat bars (VWAP 100). 09:40 closes 99.4 under VWAP; 09:41
# closes 100.3, over VWAP and the EMA, and arms (level 100.4, extreme 99.4);
# 09:42 closes 100.5 over the level and confirms. Stop 99.3, fill 100.51 at
# 09:43, target 1.5R = 102.325.

VWAP_WARM = flat(D1, 30, 1)
VWAP_DAY = D2
VWAP_OPEN = flat(VWAP_DAY, 10, 1)
UNDER = bar(VWAP_DAY, 580, 100, 100.2, 99.2, 99.4)
ARM = bar(VWAP_DAY, 581, 99.4, 100.4, 99.4, 100.3)
VWAP_EXITS = Exits(1.5, max_sessions=1, max_minutes=20)


def vwap(extra: list[Bar], rules: VwapReclaim = VwapReclaim()):
    series = Series.build("X", VWAP_WARM + VWAP_OPEN + extra, 1)
    return run_candidate(series, rules.start(series), VWAP_EXITS, TICK, window=(575, 900),
                         limits=Limits(2, 2, 2.0))


def test_vwap_reclaim_confirms_over_the_arming_bars_high():
    (trade,) = vwap([UNDER, ARM, bar(VWAP_DAY, 582, 100.3, 100.6, 99.6, 100.5), bar(VWAP_DAY, 583, 100.5, 100.9, 100.1, 100.6)])
    assert (trade.side, trade.signal_time, trade.stop, trade.entry_price) == (1, at(VWAP_DAY, 582), pytest.approx(99.3), 100.51)
    assert trade.target == pytest.approx(102.325)


def test_vwap_reclaim_rejects_a_chase_cancels_back_through_vwap_and_expires():
    assert vwap([UNDER, ARM, bar(VWAP_DAY, 582, 100.3, 101.2, 100.2, 101.2)] + flat(VWAP_DAY, 5, 1, 101.2, start=583)) == []
    # 09:42 closes back under VWAP: 09:43's close over 100.4 arms a new setup instead of confirming the old one.
    assert vwap([UNDER, ARM, bar(VWAP_DAY, 582, 100.3, 100.4, 99.4, 99.5), bar(VWAP_DAY, 583, 99.5, 100.6, 99.5, 100.6)]
                + flat(VWAP_DAY, 5, 1, 100.6, start=584)) == []
    # Three bars without a confirmation: the fourth is too late.
    hold = [bar(VWAP_DAY, 582 + k, 100.2, 100.35, 99.9, 100.2) for k in range(3)]
    assert vwap([UNDER, ARM, *hold, bar(VWAP_DAY, 585, 100.2, 100.6, 100.1, 100.6), *flat(VWAP_DAY, 5, 1, 100.6, start=586)]) == []
    (trade,) = vwap([UNDER, ARM, *hold[:2], bar(VWAP_DAY, 584, 100.2, 100.6, 100.1, 100.6), *flat(VWAP_DAY, 3, 1, 100.6, start=585)])
    assert trade.signal_time == at(VWAP_DAY, 584)


def test_vwap_reclaim_never_arms_on_a_sessions_first_bar():
    # The prior session ends under its VWAP and the new one opens over its own: no setup yet, so no trade.
    ends_under = VWAP_WARM[:-1] + [bar(D1, 599, 100, 100.1, 99.1, 99.6)]
    opens_over = [bar(VWAP_DAY, 570, 100, 100.6, 99.6, 100.5), bar(VWAP_DAY, 571, 100.5, 100.9, 100.4, 100.8),
                  *flat(VWAP_DAY, 3, 1, 100.8, start=572)]
    series = Series.build("X", ends_under + opens_over, 1)
    assert run_candidate(series, VwapReclaim().start(series), VWAP_EXITS, TICK) == []


def test_vwap_rejection_mirrors_the_reclaim():
    def mirror(b: Bar) -> Bar:
        return Bar(b.time, 200 - b.open, 200 - b.low, 200 - b.high, 200 - b.close, b.volume)

    extra = [UNDER, ARM, bar(VWAP_DAY, 582, 100.3, 100.6, 99.6, 100.5), bar(VWAP_DAY, 583, 100.5, 100.9, 100.1, 100.6)]
    series = Series.build("X", [mirror(b) for b in VWAP_WARM + VWAP_OPEN + extra], 1)
    (trade,) = run_candidate(series, VwapReclaim().start(series), VWAP_EXITS, TICK, window=(575, 900))
    assert (trade.side, trade.stop, trade.entry_price) == (-1, pytest.approx(100.7), 99.49)
    assert run_candidate(series, VwapReclaim(sides="long").start(series), VWAP_EXITS, TICK) == []


# --- failed breakout ------------------------------------------------------------------
#
# The prior session's high is 100.5. At 09:40 a bar trades to 101 and closes
# 100.3, back under it (armed: confirm under 100.0, stop over 101.0); 09:41
# closes 99.8 and confirms. Stop 101.1, fill 99.79 at 09:42, target 97.825.

BREAK_DAY = D2
BREAK_OPEN = flat(BREAK_DAY, 10, 1)
REJECT = bar(BREAK_DAY, 580, 100.4, 101.0, 100.0, 100.3)


def breakout(extra: list[Bar], rules: FailedBreakout = FailedBreakout()):
    series = Series.build("X", VWAP_WARM + BREAK_OPEN + extra, 1)
    return run_candidate(series, rules.start(series), VWAP_EXITS, TICK, window=(575, 900))


def test_failed_breakout_shorts_the_confirmation():
    (trade,) = breakout([REJECT, bar(BREAK_DAY, 581, 100.3, 100.4, 99.4, 99.8), *flat(BREAK_DAY, 3, 1, 99.8, start=582)])
    assert (trade.side, trade.signal_time, trade.stop, trade.entry_price) == (-1, at(BREAK_DAY, 581), pytest.approx(101.1), 99.79)
    assert trade.target == pytest.approx(97.825)


def test_failed_breakout_cancels_expires_and_needs_a_prior_day():
    reclaimed = bar(BREAK_DAY, 581, 100.3, 100.8, 100.2, 100.7)  # closes back over the prior high: cancelled
    below = bar(BREAK_DAY, 582, 100.3, 100.4, 99.4, 99.6)
    after = flat(BREAK_DAY, 3, 1, 99.6, up=0.4, down=0.4, start=585)
    # 09:42 would have confirmed the cancelled setup; it is a new rejection bar instead, never confirmed.
    assert breakout([REJECT, reclaimed, bar(BREAK_DAY, 582, 100.7, 100.7, 99.4, 99.6),
                     *flat(BREAK_DAY, 3, 1, 99.6, up=0.4, down=0.1, start=583)]) == []
    hold = [bar(BREAK_DAY, 581 + k, 100.3, 100.5, 100.0, 100.2) for k in range(3)]
    assert breakout([REJECT, *hold, bar(BREAK_DAY, 584, 100.2, 100.4, 99.4, 99.6), *after]) == []
    assert len(breakout([REJECT, *hold[:2], bar(BREAK_DAY, 583, 100.2, 100.4, 99.4, 99.6), *flat(BREAK_DAY, 2, 1, 99.6, start=584)])) == 1
    first_session = Series.build("X", BREAK_OPEN + [REJECT, below], 1)
    assert run_candidate(first_session, FailedBreakout().start(first_session), VWAP_EXITS, TICK) == []


def test_failed_breakdown_is_the_long_mirror_and_off_by_default():
    reject_low = bar(BREAK_DAY, 580, 99.6, 100.0, 99.0, 99.7)
    extra = [reject_low, bar(BREAK_DAY, 581, 99.7, 100.6, 99.6, 100.2), *flat(BREAK_DAY, 3, 1, 100.2, start=582)]
    assert breakout(extra) == []
    (trade,) = breakout(extra, FailedBreakout(sides="long"))
    assert (trade.side, trade.stop) == (1, pytest.approx(98.9))


# --- opening range breakout -------------------------------------------------------------
#
# 5-minute bars. The 09:30 bar is the range, 99.5 to 100.5. 09:35 stays inside;
# 09:40 closes 100.8, over the high: long, stop at the range low 99.5, filled
# at 09:45's open plus a tick.

ORB_DAY = D2
ORB_RANGE = bar(ORB_DAY, 570, 100.0, 100.5, 99.5, 100.2)
INSIDE = bar(ORB_DAY, 575, 100.2, 100.4, 99.8, 100.1)
UP = bar(ORB_DAY, 580, 100.1, 100.9, 100.0, 100.8)


def orb(bars: list[Bar], rules: OpeningRangeBreakout = OpeningRangeBreakout(), tf: int = 5,
        limits: Limits = Limits(2, 2)):
    series = Series.build("X", bars, tf)
    return run_candidate(series, rules.start(series), Exits(None), TICK, limits=limits)


def test_opening_range_breakout_goes_long_on_the_first_close_over_the_range():
    (trade,) = orb([ORB_RANGE, INSIDE, UP, *flat(ORB_DAY, 3, 5, 100.8, start=585)])
    assert (trade.side, trade.signal_time, trade.stop, trade.entry_price) == (1, at(ORB_DAY, 580), 99.5, 100.81)
    assert trade.exit_reason == "session"
    (mid,) = orb([ORB_RANGE, INSIDE, UP, *flat(ORB_DAY, 3, 5, 100.8, start=585)], OpeningRangeBreakout(stop_at="mid"))
    assert mid.stop == pytest.approx(100.0)


def test_opening_range_breakout_shorts_the_low_and_each_side_triggers_once():
    down = bar(ORB_DAY, 580, 100.1, 100.2, 99.2, 99.3)
    # Short at 09:45's open, stopped at the range high by 09:50; the second close under the low does not re-enter.
    bars = [ORB_RANGE, INSIDE, down, bar(ORB_DAY, 585, 99.3, 100.6, 99.2, 100.0), bar(ORB_DAY, 590, 99.9, 100.0, 99.0, 99.1),
            *flat(ORB_DAY, 2, 5, 99.1, start=595)]
    (trade,) = orb(bars, OpeningRangeBreakout(sides="short"))
    assert (trade.side, trade.stop, trade.exit_reason) == (-1, 100.5, "stop")
    # Both sides: after the short is stopped, the later close over the high is the long's first break.
    reversal = [ORB_RANGE, INSIDE, down, bar(ORB_DAY, 585, 99.3, 100.6, 99.2, 100.0),
                bar(ORB_DAY, 590, 100.0, 101.0, 99.9, 100.9), *flat(ORB_DAY, 2, 5, 100.9, start=595)]
    short, long_ = orb(reversal)
    assert (short.side, long_.side, long_.signal_time) == (-1, 1, at(ORB_DAY, 590))
    assert [t.side for t in orb(reversal, OpeningRangeBreakout(sides="long"))] == [1]


def test_opening_range_breakout_waits_for_the_whole_range_and_needs_the_open():
    # A 15-minute range is 09:30-09:45: UP's 100.9 high widens it, so nothing closes over it.
    assert orb([ORB_RANGE, INSIDE, UP, *flat(ORB_DAY, 3, 5, 100.8, start=585)], OpeningRangeBreakout(range_minutes=15)) == []
    later = bar(ORB_DAY, 585, 100.8, 101.2, 100.7, 101.1)
    (trade,) = orb([ORB_RANGE, INSIDE, UP, later, *flat(ORB_DAY, 2, 5, 101.1, start=590)],
                   OpeningRangeBreakout(range_minutes=15))
    assert (trade.signal_time, trade.stop) == (at(ORB_DAY, 585), 99.5)
    # No 09:30 bar, no range.
    assert orb([INSIDE, UP, *flat(ORB_DAY, 3, 5, 100.8, start=585)]) == []
    # A range that is not whole bars is refused.
    with pytest.raises(ValueError):
        orb([ORB_RANGE, INSIDE, UP], OpeningRangeBreakout(range_minutes=5), tf=15)


def test_opening_range_breakout_uses_up_a_break_it_cannot_take():
    # Halted by the session limits, or outside the entry window: the break is used up, no trade later.
    bars = [ORB_RANGE, INSIDE, UP, *flat(ORB_DAY, 3, 5, 100.8, start=585)]
    assert orb(bars, limits=Limits(max_entries=0)) == []
    series = Series.build("X", bars, 5)
    refused = run_candidate(series, OpeningRangeBreakout().start(series), Exits(None), TICK, window=(600, 900))
    assert refused == []
    assert parse_spec({"family": "opening_range_breakout"}).exits == Exits(None, max_sessions=1)


# --- specs ----------------------------------------------------------------------------


def test_a_spec_takes_its_familys_defaults_and_overrides():
    spec = parse_spec({"family": "vwap_reclaim", "params": {"confirm_bars": 2}, "exits": {"target_r": 2.0}})
    assert spec.timeframe == 1 and spec.window == (575, 900)
    assert spec.exits == Exits(2.0, max_sessions=1, max_minutes=20)
    assert spec.limits == Limits(2, 2, 2.0)
    assert dict(spec.params)["confirm_bars"] == 2
    assert len(spec.tickers) == 18
    swing_spec = parse_spec({"family": "recovery_swing", "window": None, "tickers": ["nbis"]})
    assert (swing_spec.timeframe, swing_spec.window, swing_spec.tickers) == (15, None, ("NBIS",))
    assert swing_spec.exits == Exits(2.0, max_sessions=2)


@pytest.mark.parametrize("bad", [
    {"family": "nope"},
    {"family": "recovery_swing", "params": {"ema": 9}},
    {"family": "recovery_swing", "params": {"reclaim_level": "vwap"}},
    {"family": "recovery_swing", "filters": [{"feature": "moon_phase", "min": 0}]},
    {"family": "recovery_swing", "timeframe": 7},
    {"family": "recovery_swing", "surprise": 1},
    {"family": "recovery_swing", "model": {"kind": "forest"}},
])
def test_a_bad_spec_is_refused(bad):
    with pytest.raises(ValueError):
        parse_spec(bad)


@pytest.mark.parametrize("bad", [
    {"filters": [None]},
    {"filters": {"feature": "rvol", "min": 1}},
    {"filters": 5},
    {"filters": [{"feature": "rvol", "low": 1.5}]},  # the ledger's stored form is not the spec format
    {"filters": [{"feature": "rvol"}]},
    {"filters": [{"feature": "rvol", "min": 2, "max": 1}]},
    {"filters": [{"feature": "rvol", "min": "1.5"}]},
    {"params": "fast"},
    {"params": {"ema_length": "20"}},
    {"params": {"ema_length": 0}},
    {"params": {"atr_buffer": -0.1}},
    {"params": {"reclaim_level": 1}},
    {"exits": {"target_r": "2"}},
    {"exits": {"max_sessions": 1.5}},
    {"exits": {"stop_r": 1}},
    {"exits": [2.0]},
    {"exits": {"breakeven_r": 0}},
    {"exits": {"trail_r": -1}},
    {"exits": {"trail_r": "1"}},
    {"exits": {"breakeven_r": 2.0}},  # at the family's 2R target, which would always fill first
    {"exits": {"breakeven_r": 3, "target_r": 2}},
    {"exits": {"stall_r": 0.5}},  # progress without a time to check it
    {"exits": {"stall_minutes": 0}},
    {"exits": {"stall_minutes": "60"}},
    {"exits": {"stall_minutes": 60, "stall_r": 2.0}},  # at the 2R target
    {"exits": {"stall_minutes": 60, "max_minutes": 60}},
    {"window": "0930"},
    {"window": [900, 1000]},
    {"window": [1060, 1100]},
    {"window": [1500, 1000]},
    {"limits": {"max_entries": 0}},
    {"costs": {"slippage_bps": -1}},
    {"model": {"features": "gap"}},
    {"model": {"features": ["gap", "gap"]}},
    {"model": {"kind": "logistic", "l2": 0}},
    {"model": [1]},
    {"tickers": []},
    {"tickers": 5},
    {"timeframe": "15"},
    {"timeframe": 7},
])
def test_a_malformed_spec_is_refused_with_a_reason(bad):
    with pytest.raises(ValueError):
        parse_spec({"family": "recovery_swing", **bad})


def test_numbers_are_normalized_so_the_same_rules_get_the_same_id():
    loose = parse_spec({"family": "recovery_swing", "exits": {"target_r": 2, "max_sessions": 2.0},
                        "params": {"atr_buffer": 0, "stop_bars": 4.0}, "filters": [{"feature": "trend", "min": 0}]})
    tidy = parse_spec({"family": "recovery_swing", "exits": {"target_r": 2.0, "max_sessions": 2},
                       "params": {"atr_buffer": 0.0, "stop_bars": 4}, "filters": [{"feature": "trend", "min": 0.0}]})
    assert spec_id(loose) == spec_id(tidy)
    assert loose.exits.max_sessions == 2 and isinstance(loose.exits.target_r, float)


def test_moving_stops_are_rules_and_leave_every_earlier_id_alone():
    base = parse_spec({"family": "recovery_swing"})
    assert set(canonical(base)["exits"]) == {"target_r", "max_sessions", "max_minutes"}
    moved = parse_spec({"family": "recovery_swing", "exits": {"target_r": None, "breakeven_r": 1, "trail_r": 1.5}})
    assert moved.exits == Exits(None, max_sessions=2, breakeven_r=1.0, trail_r=1.5)
    assert canonical(moved)["exits"] == {"target_r": None, "max_sessions": 2, "max_minutes": None,
                                         "breakeven_r": 1.0, "trail_r": 1.5}
    assert spec_id(moved) != spec_id(base)
    for spec in (base, moved):
        assert spec_id(from_canonical(canonical(spec))) == spec_id(spec)


def test_a_stall_check_is_a_rule_that_leaves_every_earlier_id_alone():
    base = parse_spec({"family": "recovery_swing"})
    stall = parse_spec({"family": "recovery_swing", "exits": {"stall_minutes": 60}})
    assert stall.exits == Exits(2.0, max_sessions=2, stall_minutes=60, stall_r=0.0)
    assert canonical(stall)["exits"] == {"target_r": 2.0, "max_sessions": 2, "max_minutes": None,
                                         "stall_minutes": 60, "stall_r": 0.0}
    assert spec_id(stall) == spec_id(parse_spec({"family": "recovery_swing", "exits": {"stall_minutes": 60, "stall_r": 0}}))
    assert len({spec_id(base), spec_id(stall),
                spec_id(parse_spec({"family": "recovery_swing", "exits": {"stall_minutes": 60, "stall_r": 0.5}}))}) == 3
    assert spec_id(from_canonical(canonical(stall))) == spec_id(stall)


def test_a_model_without_a_list_reads_the_first_ten_features():
    learned = parse_spec({"family": "recovery_swing", "model": {"kind": "logistic"}})
    assert learned.model.features == MODEL_DEFAULT_FEATURES == tuple(FEATURES)[:10]
    named = parse_spec({"family": "recovery_swing", "model": {"features": ["vwap_distance", "vol_ratio", "spy_vol"]}})
    assert named.model.features == ("vwap_distance", "vol_ratio", "spy_vol")


def test_the_id_is_the_rules_not_the_name():
    base = parse_spec({"family": "recovery_swing"})
    assert spec_id(parse_spec({"family": "recovery_swing", "name": "x", "notes": "y"})) == spec_id(base)
    assert spec_id(parse_spec({"family": "recovery_swing", "params": {"arm_sessions": 2}})) == spec_id(base)
    assert spec_id(parse_spec({"family": "recovery_swing", "params": {"arm_sessions": 3}})) != spec_id(base)
    assert spec_id(parse_spec({"family": "recovery_swing", "costs": {"slippage_bps": 2}})) != spec_id(base)
    learned = parse_spec({"family": "recovery_swing", "model": {"kind": "logistic"}})
    assert spec_id(learned) != spec_id(base) and spec_id(learned.parent()) == spec_id(base)
    assert learned.model.features[0] == "minutes" and base.parent() is None


# --- the model -------------------------------------------------------------------------


def test_logistic_regression_recovers_a_known_effect():
    rng = random.Random(3)
    rows, labels = [], []
    for _ in range(3000):
        x, noise = rng.uniform(-2, 2), rng.gauss(0, 1)
        rows.append({"x": x, "noise": noise})
        labels.append(int(rng.random() < 1 / (1 + math.exp(-(1.5 * x - 0.5)))))
    model = fit_logistic(rows, labels, ["x", "noise"], l2=1.0)
    per_unit = model.weights[0] / model.scales[0]
    assert per_unit == pytest.approx(1.5, abs=0.15)
    assert abs(model.weights[1]) < 0.1
    assert model.threshold == pytest.approx(sum(labels) / len(labels))
    assert model.takes({"x": 1.5, "noise": 0}) and not model.takes({"x": -1.5, "noise": 0})
    assert model.probability({"noise": 0.0}) == model.probability({"x": model.means[0], "noise": 0.0})
    assert LogisticModel.from_json(model.to_json()) == model
    assert fit_logistic(rows, labels, ["x", "noise"], l2=1.0) == model


def test_a_constant_feature_gets_no_weight():
    model = fit_logistic([{"c": 1.0, "x": float(k % 2)} for k in range(40)], [k % 2 for k in range(40)], ["c", "x"])
    assert model.weights[0] == pytest.approx(0.0, abs=1e-9) and model.weights[1] > 1


# --- statistics and gates --------------------------------------------------------------


def trade(ticker: str, day: date, r: float, side: int = 1, minute: int = 600) -> Trade:
    t = Trade(ticker, side, 0, at(day, minute), 1, at(day, minute + 15), 100.0, 100.0 - side, None)
    t.exit_price = 100.0 + side * r
    return t


def test_clustered_standard_error_groups_by_week():
    mean, se = clustered_mean([1, 2, 3, 4], ["a", "a", "b", "b"])
    assert (mean, se) == (2.5, pytest.approx(1.0))
    assert math.isnan(clustered_mean([1, 2], ["a", "a"])[1])


def test_summarize_measures_against_matched_random_entries():
    monday, tuesday, next_week = date(2024, 3, 4), date(2024, 3, 5), date(2024, 3, 11)
    trades = [trade("A", monday, 2.0), trade("A", tuesday, -1.0), trade("B", next_week, 1.0),
              trade("B", next_week, -1.0, side=-1)]
    random_r = {("A", "discovery", 1): -0.5, ("B", "discovery", 1): 0.0, ("B", "discovery", -1): -0.2}
    s = summarize(trades, random_r)
    assert (s.n, s.days, s.total_r, s.mean_r) == (4, 3, 1.0, 0.25)
    assert s.profit_factor == pytest.approx(1.5) and s.win_pct == 50.0
    assert s.max_drawdown_r == 1.0 and s.without_best_trade == -1.0 and s.without_best_day == -1.0
    assert s.random_r == pytest.approx((-0.5 - 0.5 + 0 - 0.2) / 4)
    assert s.edge == pytest.approx(0.25 + 0.3)
    assert s.edge_se == pytest.approx(0.45)  # clustered by week: two weeks, deviations +0.9 and -0.9
    assert (s.tickers, s.tickers_up) == (0, 0)  # none has five trades
    assert s.without_best_ticker == pytest.approx(0.0)  # A made +1, B 0: without A


def test_the_bar_rises_with_every_candidate():
    assert required_t(1) == pytest.approx(1.645, abs=1e-3)
    assert required_t(10) == pytest.approx(2.576, abs=1e-3)
    assert required_t(100) > required_t(10) > required_t(1)


def good(**changes) -> Stats:
    values = dict(n=500, mean_r=0.2, edge=0.25, edge_t=4.0, tickers=10, tickers_up=7, without_best_ticker=0.15)
    values.update(changes)
    return Stats(**values)


def test_the_screen():
    assert screen_gate(good(), trained=False).passed
    for change in ({"n": 99}, {"mean_r": -0.01}, {"edge_t": 1.99}, {"edge_t": math.nan}):
        gate = screen_gate(good(**change), trained=False)
        assert not gate.passed and sum(not c.passed for c in gate.checks) == 1
    assert screen_gate(Stats(), trained=True).passed


def test_the_confirmation():
    halves = {"confirm_a": good(), "confirm_b": good()}
    assert confirm_gate(halves, good(), good(), 2.5, 7).passed
    failures = [
        ({"confirm_a": good(n=29), "confirm_b": good()}, good(), good()),
        ({"confirm_a": good(), "confirm_b": good(edge=-0.01)}, good(), good()),
        (halves, good(edge_t=2.49), good()),
        (halves, good(), good(mean_r=-0.01)),
        (halves, good(tickers_up=4), good()),
        (halves, good(without_best_ticker=-0.01), good()),
    ]
    for halves_, both, stressed in failures:
        assert not confirm_gate(halves_, both, stressed, 2.5, 7).passed
    parent = {"confirm_a": good(mean_r=0.1), "confirm_b": good(mean_r=0.25)}
    assert not confirm_gate(halves, good(), good(), 2.5, 7, parent).passed
    assert "the bar with 7 candidates" in confirm_gate(halves, good(), good(), 2.5, 7).checks[2].text


def test_the_exam():
    assert exam_gate(good(n=30)).passed
    assert not exam_gate(good(n=29)).passed
    assert not exam_gate(good(edge=-0.1)).passed
    assert not exam_gate(good(), parent=good(mean_r=0.3)).passed


def test_prior_candidates_count_distinct_ideas_that_reached_confirmation():
    records = [{"id": "hand-a", "reached_confirmation": True}, {"id": "x", "reached_confirmation": True},
               {"id": "x", "reached_confirmation": True}, {"id": "y", "reached_confirmation": False}]
    assert prior_candidates(records) == 2
    assert prior_candidates(records, excluding="x") == 1


# --- the evaluation end to end ------------------------------------------------------------
#
# Thirty-minute bars from June 2023 to June 2026 in a pattern with a real
# edge: each session falls from the open into the 10:00 bar, then rises back
# at 10:30 and goes flat; every fifth session it keeps falling instead. The
# test family buys the 10:00 bar's close with the stop at its low, so four
# days in five it makes 2R. Random entries mostly buy the flat afternoon and
# lose their costs.


@dataclass(frozen=True)
class DipBuyer:
    defaults = {"timeframe": 30, "exits": {"target_r": 2.0, "max_sessions": 1}}
    sides = (1,)

    def validate(self) -> None:
        pass

    def baseline_stop(self) -> SwingStop:
        return SwingStop(1, 0.0)

    def start(self, series: Series) -> _DipBuyerRun:
        return _DipBuyerRun(series)


class _DipBuyerRun:
    def __init__(self, series: Series):
        self.s = series

    def on_bar(self, i: int, ctx: Context) -> Signal | None:
        if self.s.minute[i] == 600 and ctx.flat:
            signal = Signal(i, 1, self.s.low[i])
            return signal if ctx.accept(signal) else None
        return None


def pattern(first: date, last: date, bad: callable, gap_on_bad: float = 0.0) -> list[Bar]:
    bars, day, k = [], first, 0
    while day <= last:
        if day.weekday() < 5:
            is_bad = bad(k, day)
            o = 100.0 + (gap_on_bad if is_bad else 0.0)
            bars += [bar(day, 570, o, o + 0.02, 99.45, 99.5), bar(day, 600, 99.5, 99.52, 98.95, 99.0)]
            if is_bad:
                bars += [bar(day, 630, 99.0, 99.05, 98.5, 98.6)] + flat(day, 10, 30, 98.6, 0.02, 0.02, start=660)
            else:
                bars += [bar(day, 630, 99.0, 99.5, 98.98, 99.5)] + flat(day, 10, 30, 99.5, 0.02, 0.02, start=660)
            k += 1
        day += timedelta(days=1)
    return bars


class StubLoader:
    """Bars by ticker, cut at the day asked for; records every request."""

    def __init__(self, bars: dict[str, list[Bar]]):
        self.bars = bars
        self.requests: list[tuple[str, date | None]] = []

    def __call__(self, ticker: str, timeframe: int, through: date | None) -> Series | None:
        self.requests.append((ticker, through))
        kept = [b for b in self.bars.get(ticker, []) if through is None or b.time.astimezone(ET).date() <= through]
        return Series.build(ticker, kept, timeframe) if kept else None


START, END = date(2023, 6, 1), date(2026, 6, 30)


def every_fifth(k: int, day: date) -> bool:
    return k % 5 == 4


@pytest.fixture
def dip_family(monkeypatch):
    monkeypatch.setitem(FAMILIES, "dip_buyer", DipBuyer)
    return parse_spec({"name": "dip buyer", "family": "dip_buyer", "tickers": ["AAA", "BBB"]})


def test_a_real_edge_passes_every_gate(dip_family):
    loader = StubLoader({"AAA": pattern(START, END, every_fifth), "BBB": pattern(START, END, every_fifth)})
    ev = evaluate(dip_family, loader, prior_candidates=9)
    assert ev.verdict == "passed", report(ev)
    assert ev.stats["discovery"].mean_r > 1 and ev.stats["discovery"].edge > 1
    assert ev.needed_t == pytest.approx(required_t(10)) and ev.candidates == 10
    assert [through for _, through in loader.requests if through is None]  # the exam saw the holdout
    assert ev.random_stop["discovery"] == "0 ATR beyond the last 1 bars' extreme"
    record = ledger_record(ev, datetime(2026, 9, 28, tzinfo=ET), "abc123", date(2026, 6, 30))
    assert (record["verdict"], record["reached_confirmation"], record["bar_t"]) == ("passed", True, pytest.approx(required_t(10)))
    assert set(record["periods"]) == {"discovery", "confirm_a", "confirm_b", "confirm", "confirm_x3", "holdout"}
    assert "Verdict: passed every gate" in report(ev)
    assert "Its bar at confirmation: t >= 2.58, with 9 other candidates counted there before it." in report(ev)


def test_moving_stops_go_through_the_evaluation_and_the_ledger(dip_family):
    spec = parse_spec({"name": "dip buyer, trailed", "family": "dip_buyer", "tickers": ["AAA", "BBB"],
                       "exits": {"target_r": None, "trail_r": 1.0}})
    ev = evaluate(spec, StubLoader({"AAA": pattern(START, END, every_fifth), "BBB": pattern(START, END, every_fifth)}), 0)
    assert "no target, stop trailing 1R behind the best price, flat by the close" in report(ev)
    record = ledger_record(ev, datetime(2026, 9, 28, tzinfo=ET), "abc123", date(2026, 6, 30))
    assert record["spec"]["exits"]["trail_r"] == 1.0 and record["id"] == spec_id(spec) != spec_id(dip_family)
    stalled = parse_spec({"name": "dip buyer, stall-checked", "family": "dip_buyer", "tickers": ["AAA", "BBB"],
                          "exits": {"stall_minutes": 60, "stall_r": 0.5}})
    ev = evaluate(stalled, StubLoader({"AAA": pattern(START, END, every_fifth), "BBB": pattern(START, END, every_fifth)}), 0)
    assert "out after 60 minutes unless +0.5R or better" in report(ev)


def test_an_edge_that_stops_in_the_holdout_fails_the_exam(dip_family):
    def turns(k: int, day: date) -> bool:
        return k % 5 == 4 or day >= date(2026, 4, 1)

    ev = evaluate(dip_family, StubLoader({"AAA": pattern(START, END, turns), "BBB": pattern(START, END, turns)}), 0)
    assert ev.verdict == "failed_exam"
    assert ev.stats["holdout"].mean_r < 0


def test_a_failed_screen_never_loads_later_data(dip_family, monkeypatch):
    loader = StubLoader({"AAA": pattern(START, END, lambda k, day: True)})
    ev = evaluate(dip_family, loader, 0)
    assert ev.verdict == "failed_screen"
    assert {through for _, through in loader.requests} == {PERIODS["discovery"][1]}
    assert set(ev.stats) == {"discovery"} and not ev.reached_confirmation
    assert {t.signal_time.astimezone(ET).date() <= PERIODS["discovery"][1] for t in ev.trades} == {True}
    assert ev.missing == {"screen": ["BBB"]}


def test_a_failed_confirmation_leaves_the_holdout_locked(dip_family, monkeypatch):
    monkeypatch.setattr(factory_gates, "screen_gate", lambda s, trained: Gate("screen", (Check("forced", True),)))
    loader = StubLoader({"AAA": pattern(START, END, lambda k, day: True), "BBB": pattern(START, END, lambda k, day: True)})
    ev = evaluate(dip_family, loader, 0)
    assert ev.verdict == "failed_confirmation" and ev.reached_confirmation and ev.candidates == 1
    assert None not in {through for _, through in loader.requests}
    assert max(through for _, through in loader.requests) == PERIODS["confirm_b"][1]


def test_discovery_evidence_reads_only_discovery_data(dip_family):
    loader = StubLoader({"AAA": pattern(START, END, every_fifth), "BBB": pattern(START, END, every_fifth)})
    trades = discovery_trades(dip_family, loader)
    assert {through for _, through in loader.requests} == {PERIODS["discovery"][1]}
    days = {t.signal_time.astimezone(ET).date() for t in trades}
    assert min(days) >= PERIODS["discovery"][0] and max(days) <= PERIODS["discovery"][1]
    assert all(t.closed and set(t.features) == set(FEATURES) for t in trades)
    learned = parse_spec({"family": "dip_buyer", "tickers": ["AAA", "BBB"], "model": {"kind": "logistic"}})
    assert len(discovery_trades(learned, loader)) == len(trades)  # read through its rules without the model


def test_a_learned_filter_trains_on_discovery_only_and_must_beat_its_parent(dip_family):
    # Bad sessions open 1.5 higher, so the gap tells them apart; the model has to find that.
    spec = parse_spec({"name": "dip buyer, learned", "family": "dip_buyer", "tickers": ["AAA", "BBB"],
                       "model": {"kind": "logistic", "features": ["gap", "minutes"]}})
    data = {t: pattern(START, END, every_fifth, gap_on_bad=1.5) for t in ("AAA", "BBB")}
    ev = evaluate(spec, StubLoader(data), 0)
    discovery_days = sum(1 for b in data["AAA"] if b.time.astimezone(ET).date() <= PERIODS["discovery"][1]
                         and b.time.astimezone(ET).date() >= PERIODS["discovery"][0] and b.time.astimezone(ET).hour == 10
                         and b.time.astimezone(ET).minute == 0)
    assert ev.model is not None and ev.model.trained_on == 2 * discovery_days
    assert ev.model.weights[0] < 0  # a bigger gap, a worse day
    assert ev.screen.checks[0].text.startswith("the model was trained on this period")
    assert ev.stats["confirm"].mean_r == pytest.approx(2.0, abs=0.01)
    assert ev.parent_stats["confirm_a"].mean_r < 1.8
    assert ev.verdict == "passed", report(ev)
    assert ev.parent_id == spec_id(spec.parent())


def test_an_opening_range_breakout_spec_goes_through_the_evaluation():
    # The stub bars are 30-minute, so a 30-minute range is each session's first bar.
    spec = parse_spec({"family": "opening_range_breakout", "params": {"range_minutes": 30}, "timeframe": 30,
                       "tickers": ["AAA", "BBB"]})
    ev = evaluate(spec, StubLoader({"AAA": pattern(START, END, every_fifth), "BBB": pattern(START, END, every_fifth)}), 0)
    assert ev.verdict in {"failed_screen", "failed_confirmation", "failed_exam", "passed"}
    assert "opening_range_breakout, 30-minute bars, long/short" in report(ev)
