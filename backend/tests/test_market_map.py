"""The Python port of Isaac Market Map, on synthetic bars.

Every scenario is written once as a long and run again reflected through 100
as a short (`market_map_bars.mirror`), so both sides are checked by the same
numbers. Inputs are checked against the Pine source itself, not a copy.
"""

from __future__ import annotations

import math
import re
from datetime import date
from dataclasses import fields, replace
from pathlib import Path

import pytest

from app.engine.market_map import (
    ET,
    MIDDAY_A_HALF,
    Bar,
    DailyBar,
    MarketMapConfig,
    daily_atr,
    daily_from_bars,
    regular_session,
    resample,
    run_market_map,
)
from tests.market_map_bars import (
    DAY,
    NEXT_DAY,
    PRIOR_DAY,
    at,
    daily_history,
    flat_benchmark,
    mirror,
    mirror_daily,
    quiet_day,
    session,
)

THREE_BACK = date(2026, 2, 26)
TWO_BACK = date(2026, 2, 27)
PINE = (Path(__file__).resolve().parents[2] / "docs" / "pine" / "isaac_market_map.pine").read_text()

ONLY = {
    "enable_orb": False,
    "enable_level_breaks": False,
    "enable_retest": False,
    "enable_orb_retest": False,
    "enable_hod": False,
    "enable_vwap": False,
    "enable_orb_fail": False,
}
SHORT_NAME = {"pdh_break": "pdl_break", "pdh_retest": "pdl_retest", "hod_break": "lod_break", "vwap_reclaim": "vwap_loss"}


def only(setup_flag: str, **overrides) -> MarketMapConfig:
    return replace(MarketMapConfig(), **{**ONLY, setup_flag: True, **overrides})


def run(bars, config=None, ticker="MU", side=1, daily=None, benchmark=None):
    daily = daily or daily_history()
    if side == -1:
        bars, daily = mirror(bars), mirror_daily(daily)
        config = replace(config or MarketMapConfig(), allow_shorts=True)
    return run_market_map(ticker, bars, daily, benchmark or flat_benchmark(bars), config)


def hhmm(moment) -> str:
    return moment.astimezone(ET).strftime("%H:%M")


def price(value: float, side: int) -> float:
    """A long scenario's price, reflected for the short run."""
    return round(value if side == 1 else 200 - value, 6)


# --- the inputs are the Pine's ---------------------------------------------------


def _pine_constants() -> dict[str, str]:
    return dict(re.findall(r'^const string (\w+) = "([^"]*)"', PINE, re.M))


def _pine_inputs() -> dict[str, object]:
    constants = _pine_constants()
    found: dict[str, object] = {}
    for name, kind, default in re.findall(r'^(\w+) = input\.(\w+)\(("[^"]*"|[^,]+),', PINE, re.M):
        default = default.strip()
        if kind in ("string", "symbol"):
            found[name] = default.strip('"') if default.startswith('"') else constants[default]
        elif kind == "bool":
            found[name] = default == "true"
        elif kind == "int":
            found[name] = int(default)
        else:
            found[name] = float(default)
    return found


def _snake(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


# Inputs that only change what the chart draws or logs.
DISPLAY_INPUTS = {"showLevels", "showTable", "logPayloads"}


def test_every_pine_input_is_a_config_field_with_the_pine_default() -> None:
    inputs = _pine_inputs()
    assert len(inputs) > 40, "input parsing broke"
    config = MarketMapConfig()
    names = {field.name for field in fields(MarketMapConfig)}
    missing, wrong = [], []
    for pine_name, default in inputs.items():
        if pine_name in DISPLAY_INPUTS:
            continue
        name = _snake(pine_name)
        if name not in names:
            missing.append(pine_name)
        elif getattr(config, name) != default:
            wrong.append(f"{name}: python {getattr(config, name)!r}, pine {default!r}")
    assert not missing, f"Pine inputs with no MarketMapConfig field: {missing}"
    assert not wrong, wrong


def test_strategy_properties_match_the_pine_header() -> None:
    header = re.search(r"^strategy\((.+)\)$", PINE, re.M).group(1)
    assert "process_orders_on_close = true" in header
    assert "pyramiding = 0" in header
    config = MarketMapConfig()
    assert f"slippage = {config.slippage}," in header
    assert f"initial_capital = {config.initial_capital:g}," in header
    assert "commission_value = 0" in header


def test_the_port_knows_every_setup_the_pine_can_emit() -> None:
    pine_setups = set(re.findall(r'(?:longSetup|shortSetup|retestLongName|retestShortName) := "([^"]+)"', PINE))
    source = (Path(__file__).resolve().parents[1] / "app" / "engine" / "market_map.py").read_text()
    port_setups = set(re.findall(r'"(\w+_(?:break|retest|reclaim|loss|fail))"', source))
    assert pine_setups == port_setups


# --- setups -----------------------------------------------------------------------


def _pdh_prior_day() -> list[Bar]:
    prior = quiet_day()
    prior[40] = replace(prior[40], high=101.0)
    return prior


SETUPS = {
    # name: (config flag, today's bars, prior session, entry time)
    "orb_break": ("enable_orb", session(DAY, [100.2, 101.8], first_open=100.0), None, "09:35"),
    "orb_retest": (
        "enable_orb_retest",
        session(DAY, [100.2, 101.8, 101.7], first_open=100.0, overrides={2: {"low": 101.0}}),
        None,
        "09:40",
    ),
    "pdh_break": ("enable_level_breaks", session(DAY, [100.2, 100.5, 101.6], first_open=100.0), _pdh_prior_day(), "09:40"),
    "pdh_retest": ("enable_retest", session(DAY, [100.2, 100.5, 101.6, 101.7], first_open=100.0), _pdh_prior_day(), "09:45"),
    "hod_break": ("enable_hod", session(DAY, [100.0] * 54 + [101.7], first_open=100.0), None, "14:00"),
    "vwap_reclaim": (
        "enable_vwap",
        session(DAY, [100.5, 102, 103.5, 104.5, 104.8, 101.9, 101.8, 103.0], first_open=100.0),
        None,
        "10:05",
    ),
    "orb_fail": ("enable_orb_fail", session(DAY, [100.2, 99.5, 101.7], first_open=100.0), None, "09:40"),
}


@pytest.mark.parametrize("side", [1, -1], ids=["long", "short"])
@pytest.mark.parametrize("setup", sorted(SETUPS))
def test_each_setup_fires_on_its_bar(setup: str, side: int) -> None:
    flag, today, prior, entry_at = SETUPS[setup]
    result = run((prior or quiet_day()) + today, only(flag), side=side)

    assert len(result.trades) == 1, result.signals
    trade = result.trades[0]
    assert trade.setup == (setup if side == 1 else SHORT_NAME.get(setup, setup))
    assert trade.side == side
    assert hhmm(trade.entry_time) == entry_at
    assert trade.entry_price == price(today[-1].close + 0.02, side)


@pytest.mark.parametrize("setup", sorted(SETUPS))
def test_no_setup_fires_with_every_setup_disabled(setup: str) -> None:
    _, today, prior, _ = SETUPS[setup]
    config = replace(MarketMapConfig(), **ONLY)
    assert run((prior or quiet_day()) + today, config).signals == []


def test_priority_prefers_the_opening_range_break_over_a_prior_day_break() -> None:
    today = session(DAY, [100.2, 101.8], first_open=100.0)
    prior = quiet_day()
    prior[40] = replace(prior[40], high=100.22)  # pdh just under the OR high: both cross on 9:35
    result = run(prior + today, MarketMapConfig())
    assert [t.setup for t in result.trades] == ["orb_break"]


def test_shorts_off_records_the_short_and_takes_nothing() -> None:
    result = run(mirror(quiet_day() + SETUPS["orb_break"][1]), MarketMapConfig(), daily=mirror_daily(daily_history()))
    assert result.trades == []
    assert [(s.setup, s.side, s.outcome) for s in result.signals] == [("orb_break", -1, "shorts_off")]


# --- exits (entry: orb_break long at 9:35 close 101.8, stop 99.75, risk 2.05) ----------

OPEN = [100.2, 101.8]
EXITS = {
    # name: (closes after entry, overrides, config overrides, exit time, exit price, reason)
    "stop": ([101.0, 99.5], {}, {}, "09:45", 99.73, "stop"),
    "stop_gap": ([101.0, 99.0], {3: {"open": 99.0}}, {}, "09:45", 98.98, "stop"),
    # The 9:40 bar reaches +0.85R and trades below entry; the stop only moves
    # to breakeven after that bar, so the exit is 9:45, not 9:40.
    "be": ([103.5, 101.0], {}, {}, "09:45", 101.78, "be"),
    "trail": ([105.5, 102.0], {}, {}, "09:45", 103.48, "trail"),
    # The 9:40 bar moves the stop and then closes through it. The order gets
    # one attempt at that close (process_orders_on_close) and fills there,
    # not at the 9:45 open (overridden lower so the two cannot agree).
    "be_at_close": ([101.5, 101.0], {2: {"high": 103.5}, 3: {"open": 101.0}}, {}, "09:40", 101.48, "be"),
    "trail_at_close": ([103.0, 102.4], {2: {"high": 105.5}, 3: {"open": 102.5}}, {}, "09:40", 102.98, "trail"),
    "time": ([102.0] * 6, {}, {}, "10:05", 101.98, "time"),
    "eod": ([103.0] * 76, {}, {}, "15:50", 102.98, "eod"),
    "target": ([106.5], {}, {"target_r": 2.0}, "09:40", 105.9, "target"),
    # +0.66R is short of breakeven (0.75R) but past the time stop's 0.5R, so
    # the trade rides a dip below entry to the close.
    "below_breakeven": ([103.1] + [100.5] * 75, {}, {}, "15:50", 100.48, "eod"),
}


@pytest.mark.parametrize("side", [1, -1], ids=["long", "short"])
@pytest.mark.parametrize("name", sorted(EXITS))
def test_exit(name: str, side: int) -> None:
    closes, overrides, config_overrides, exit_at, exit_price, reason = EXITS[name]
    today = session(DAY, OPEN + closes, first_open=100.0, overrides=overrides)
    result = run(quiet_day() + today, replace(MarketMapConfig(), **config_overrides), side=side)

    trade = result.trades[0]
    assert (trade.entry_price, trade.stop, trade.quantity) == (price(101.82, side), price(99.75, side), 24)
    assert trade.exit_reason == reason
    assert hhmm(trade.exit_time) == exit_at
    assert trade.exit_price == pytest.approx(price(exit_price, side))
    assert trade.pnl == pytest.approx((exit_price - 101.82) * 24)
    assert trade.r == pytest.approx(trade.pnl / 50)


def _overnight_bars() -> list[Bar]:
    today = session(DAY, [100.0] * 54 + [101.7] + [103.0] * 23, first_open=100.0, volume=2000)
    tomorrow = session(NEXT_DAY, [103.0] * 12, volume=2000)
    return quiet_day() + today + tomorrow


@pytest.mark.parametrize("side", [1, -1], ids=["long", "short"])
def test_overnight_experiment_holds_an_a_grade_power_winner_to_ten(side: int) -> None:
    config = only("enable_hod", hold_power_overnight=True)
    trade = run(_overnight_bars(), config, side=side).trades[0]

    assert (trade.grade, trade.window, trade.dte_hint) == ("A", "power", "4_7dte")
    assert trade.exit_reason == "overnight_exit"
    assert trade.exit_time == at(NEXT_DAY, 1000)
    assert trade.exit_price == pytest.approx(price(102.98, side))


def test_without_the_experiment_the_same_trade_is_flat_at_the_close() -> None:
    trade = run(_overnight_bars(), only("enable_hod")).trades[0]
    assert (trade.exit_reason, trade.exit_time, trade.dte_hint) == ("eod", at(DAY, 1550), "0dte")


# --- cooldown and daily limits -----------------------------------------------------


def _power_factory(stop_bars: list[int], days: int = 1) -> list[Bar]:
    """From 14:00 every bar closes at a new high (a hod_break each bar); the
    bars in `stop_bars` (index from 14:00) wick down through any stop."""
    bars = quiet_day()
    for day in [DAY, NEXT_DAY][:days]:
        closes = [100.0] * 54 + [101.7 + 0.1 * k for k in range(21)]
        wicks = {54 + k: {"low": 95.0} for k in stop_bars}
        bars += session(day, closes, first_open=100.0, overrides=wicks)
    return bars


def _outcomes(result, day=DAY) -> list[tuple[str, str]]:
    return [(hhmm(s.time), s.outcome) for s in result.signals if s.time.astimezone(ET).date() == day]


@pytest.mark.parametrize("side", [1, -1], ids=["long", "short"])
def test_cooldown_is_fifteen_minutes_from_the_bar_the_exit_is_noticed(side: int) -> None:
    result = run(_power_factory(stop_bars=[1]), only("enable_hod"), side=side)
    outcomes = _outcomes(result)

    # Stopped intrabar at 14:05, so the cooldown runs to 14:10 + 15 = 14:25:
    # the 14:20 bar closes at 14:25 and is the first allowed.
    assert outcomes[:5] == [
        ("14:00", "entered"),
        ("14:05", "cooldown"),
        ("14:10", "cooldown"),
        ("14:15", "cooldown"),
        ("14:20", "entered"),
    ]
    assert result.trades[0].exit_reason == "stop"


@pytest.mark.parametrize("side", [1, -1], ids=["long", "short"])
def test_a_stop_filled_at_the_close_is_noticed_on_the_next_bar(side: int) -> None:
    # Entry at 14:00. The 14:05 bar reaches +1.1R, which moves the stop to
    # breakeven, and closes under it, so it fills at that close. Like a
    # market close, the script only sees it on the 14:10 bar: the cooldown
    # runs to 14:15 + 15 = 14:30, and the 14:25 bar is the first allowed.
    closes = [100.0] * 54 + [101.7, 101.5] + [104.1 + 0.1 * k for k in range(19)]
    bars = quiet_day() + session(DAY, closes, first_open=100.0, overrides={55: {"high": 104.0}})
    result = run(bars, only("enable_hod"), side=side)

    first = result.trades[0]
    assert (first.exit_reason, hhmm(first.exit_time)) == ("be", "14:05")
    assert first.exit_price == pytest.approx(price(101.48, side))
    assert _outcomes(result)[:5] == [
        ("14:00", "entered"),
        ("14:10", "cooldown"),
        ("14:15", "cooldown"),
        ("14:20", "cooldown"),
        ("14:25", "entered"),
    ]


def test_two_full_stop_losses_end_the_day() -> None:
    result = run(_power_factory(stop_bars=[1, 5]), only("enable_hod"))
    outcomes = _outcomes(result)

    assert [o for o in outcomes if o[1] == "entered"] == [("14:00", "entered"), ("14:20", "entered")]
    assert outcomes[-1] == ("15:40", "max_losses")
    assert {o for _, o in outcomes[6:]} == {"cooldown", "max_losses"}


def test_three_entries_end_the_day_and_the_next_session_resets() -> None:
    config = only("enable_hod", max_losses_per_day=10)
    result = run(_power_factory(stop_bars=[1, 5, 9], days=2), config)
    today = _outcomes(result)

    assert [t for t, o in today if o == "entered"] == ["14:00", "14:20", "14:40"]
    assert today[-1] == ("15:40", "max_entries")
    assert [t for t, o in _outcomes(result, NEXT_DAY) if o == "entered"][:1] == ["14:00"]


def test_a_breakeven_exit_is_not_a_loss() -> None:
    # Entry at 14:00; +1.1R on 14:05 moves the stop to breakeven; the 14:10
    # wick takes it out two ticks under entry. The PnL is negative but the
    # stage is "be", so with one loss allowed the next signal still trades.
    bars = quiet_day() + session(
        DAY,
        [100.0] * 54 + [101.7, 104.0, 104.1] + [104.2 + 0.1 * k for k in range(18)],
        first_open=100.0,
        overrides={56: {"low": 95.0}},
    )
    result = run(bars, only("enable_hod", max_losses_per_day=1))
    first, second, third = result.trades
    assert (first.exit_reason, hhmm(first.exit_time)) == ("be", "14:10") and first.pnl < 0
    assert hhmm(second.entry_time) == "14:25"
    # A market close (here the time stop at 14:55) is noticed on the next bar,
    # so its cooldown runs from 15:05, one bar later than after a stop.
    assert (second.exit_reason, hhmm(second.exit_time)) == ("time", "14:55")
    assert hhmm(third.entry_time) == "15:15"


# --- grading, sizing, windows, tiers -------------------------------------------------


def _orb_day(second_close: float = 101.8, volume: float = 1000.0, start_flat: int = 0) -> list[Bar]:
    closes = [100.2] + [100.2] * start_flat + [second_close]
    return quiet_day() + session(DAY, closes, first_open=100.0, volume=volume)


def test_rvol_decides_a_full_versus_b_half() -> None:
    full = run(_orb_day(volume=2000.0)).trades[0]
    half = run(_orb_day(volume=1000.0)).trades[0]

    assert (full.grade, full.size, full.quantity, full.rvol) == ("A", "full", math.floor(100 / 2.05), 2.0)
    assert (half.grade, half.size, half.quantity, half.rvol) == ("B", "half", math.floor(50 / 2.05), 1.0)


def test_relative_strength_under_the_gate_is_grade_c_and_never_trades() -> None:
    result = run(_orb_day(second_close=101.2, volume=2000.0))
    assert result.trades == []
    assert [(s.setup, s.outcome, s.grade) for s in result.signals] == [("orb_break", "grade_c", "C")]


def test_v1_0_0_grading_trades_what_the_gate_rejects() -> None:
    trade = run(_orb_day(second_close=101.2), MarketMapConfig.v1_0_0()).trades[0]
    assert (trade.grade, trade.size) == ("B", "half")


def test_rvol_averages_the_same_bar_index_over_the_lookback() -> None:
    bars = (
        quiet_day(THREE_BACK, volume=9000.0)
        + quiet_day(TWO_BACK, volume=1000.0)
        + quiet_day(PRIOR_DAY, volume=3000.0)
        + session(DAY, [100.2, 101.8], first_open=100.0, volume=4000.0)
    )
    daily = daily_history(THREE_BACK)
    default = run(bars, daily=daily).trades[0]
    two_days = run(bars, replace(MarketMapConfig(), rvol_days=2), daily=daily).trades[0]

    # Bar index 1: today 8000 cumulative vs (18000 + 2000 + 6000) / 3, or (2000 + 6000) / 2.
    assert default.rvol == pytest.approx(8000 / (26000 / 3))
    assert two_days.rvol == pytest.approx(2.0)


def test_midday_is_off_by_default_and_a_only_half_size_when_asked() -> None:
    late_break = _orb_day(volume=2000.0, start_flat=8)  # breaks at 10:15
    assert [(hhmm(s.time), s.outcome) for s in run(late_break).signals] == [("10:15", "window")]

    trade = run(late_break, replace(MarketMapConfig(), midday_mode=MIDDAY_A_HALF)).trades[0]
    assert (trade.window, trade.grade, trade.size) == ("midday", "A", "half")

    b_grade = _orb_day(volume=1000.0, start_flat=8)
    assert run(b_grade, replace(MarketMapConfig(), midday_mode=MIDDAY_A_HALF)).trades == []


def test_avoid_tier_is_blocked_unless_allowed_and_then_capped_at_b_half() -> None:
    bars = _orb_day(volume=2000.0)
    assert [s.outcome for s in run(bars, ticker="NVDA").signals] == ["avoid_tier"]

    trade = run(bars, replace(MarketMapConfig(), allow_avoid=True), ticker="NVDA").trades[0]
    assert (trade.tier, trade.grade, trade.size) == ("avoid", "B", "half")
    assert run(bars, ticker="XYZ").trades[0].tier == "neutral"


def test_stop_distance_is_capped_at_max_heat_and_floored_at_min_risk() -> None:
    capped = run(_orb_day(second_close=106.0, volume=2000.0)).trades[0]
    assert capped.risk == pytest.approx(4.0) and capped.stop == pytest.approx(102.0)

    tight = quiet_day() + session(DAY, [101.5, 101.6], first_open=100.0, volume=2000.0)
    floored = run(tight).trades[0]
    assert floored.risk == pytest.approx(0.8) and floored.quantity == 125


# --- data shaping and indicators -----------------------------------------------------


def test_resample_aligns_to_the_clock_and_sums_volume() -> None:
    minutes = [Bar(at(DAY, 930 + k), 10 + k, 11 + k, 9 + k, 10.5 + k, 100) for k in range(10)]
    five = resample(minutes, 5)
    assert [hhmm(b.time) for b in five] == ["09:30", "09:35"]
    assert (five[0].open, five[0].high, five[0].low, five[0].close, five[0].volume) == (10, 15, 9, 14.5, 500)
    with pytest.raises(ValueError):
        resample(minutes, 7)


def test_regular_session_and_daily_bars_from_minutes() -> None:
    bars = [
        Bar(at(DAY, 925), 1, 50, 1, 1, 1),
        Bar(at(DAY, 930), 10, 12, 9, 11, 1),
        Bar(at(DAY, 1555), 11, 13, 10, 12, 1),
        Bar(at(DAY, 1600), 12, 40, 12, 12, 1),
    ]
    assert [hhmm(b.time) for b in regular_session(bars)] == ["09:30", "15:55"]
    assert daily_from_bars(bars) == [DailyBar(DAY, 10, 13, 9, 12)]


def test_daily_atr_is_wilder_seeded_with_the_simple_average() -> None:
    days = [DailyBar(PRIOR_DAY, 0, hi, lo, c) for hi, lo, c in [(10, 8, 9), (12, 9, 11), (11, 10, 10.5), (14, 11, 13)]]
    atr = daily_atr(days, 3)
    assert math.isnan(atr[0]) and math.isnan(atr[1])
    assert atr[2] == pytest.approx((2 + 3 + 1) / 3)
    assert atr[3] == pytest.approx((2 * 2 + 3.5) / 3)


def test_atr_is_the_last_completed_day_so_no_daily_history_means_no_trades() -> None:
    bars = _orb_day()
    assert [s.outcome for s in run(bars, daily=[DailyBar(DAY, 100, 105, 95, 100)] * 1).signals] == ["no_atr"]
