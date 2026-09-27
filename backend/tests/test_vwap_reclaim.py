"""VWAP reclaim/rejection v0.1 on synthetic one-minute bars.

Each default bar opens at the previous close and spans 1.0 either side of its
close. With moves of at most 1.0 a bar, every true range is 2.0, so ATR(14)
stays exactly 2.0 (stop buffer 0.2, chase limit 2.0), and each bar's typical
price is its close, so VWAP is the running mean of the closes. A prior session
at 100 seeds EMA 9 and ATR.

The core scenario (long): 100 from 09:30, a dip to 99.5 at 09:38, a reclaim
to 100.5 at 09:39 (above VWAP 100.0 and EMA 9 100.02: armed, high 101.5,
low 99.5), and a 09:40 close of 101.8 that confirms. The 09:41 fill is
101.81 (one tick of slippage), the stop 99.5 - 0.2 = 99.3, so 1R is 2.51 and
the target 105.575. Every scenario also runs reflected through 100 as a short.
"""

from __future__ import annotations

import csv
import importlib.util
import io
import sys
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from app.engine.market_map import ET, Bar
from app.engine.market_map_report import tradingview_csv
from app.engine.strategy_csv import parse_tradingview_csv
from app.engine.vwap_reclaim import (
    ReclaimConfig,
    entry_comment,
    exit_comment,
    run_vwap_reclaim,
    summarize,
)

PRIOR = date(2026, 3, 2)
DAY = date(2026, 3, 3)
NEXT = date(2026, 3, 4)
BACKEND = Path(__file__).resolve().parents[1]

# No basis-point slippage in the tests, so every market or stop fill slips one tick.
BASE = ReclaimConfig(slippage_bps=0.0)
SETUP = [100.0] * 8 + [99.5, 100.5]  # 09:30-09:39, armed at 09:39
CONFIRM = {"open": 100.5, "high": 102.0, "low": 100.0}  # the 09:40 bar, close 101.8
STOP, FILL, TARGET = 99.3, 101.81, 105.575


def at(day: date, minute_of_day: int) -> datetime:
    return datetime(day.year, day.month, day.day, minute_of_day // 60, minute_of_day % 60, tzinfo=ET)


def minute_bars(day: date, closes: list[float], start: int = 570, overrides: dict | None = None) -> list[Bar]:
    bars, previous = [], closes[0]
    for index, close in enumerate(closes):
        values = {
            "open": previous,
            "high": max(close + 1.0, previous),
            "low": min(close - 1.0, previous),
            "close": close,
            "volume": 1000.0,
        }
        values.update((overrides or {}).get(index, {}))
        bars.append(Bar(at(day, start + index), values["open"], values["high"], values["low"],
                        values["close"], values["volume"]))
        previous = close
    return bars


def prior_session() -> list[Bar]:
    return minute_bars(PRIOR, [100.0] * 390)


def scenario(after: list[float], overrides: dict | None = None, day: date = DAY) -> list[Bar]:
    """The core long setup, confirmed at 09:40, followed by `after` from 09:41."""
    today = SETUP + [101.8] + after
    return prior_session() + minute_bars(day, today, overrides={10: CONFIRM, **(overrides or {})})


def mirror(bars: list[Bar]) -> list[Bar]:
    return [Bar(b.time, 200 - b.open, 200 - b.low, 200 - b.high, 200 - b.close, b.volume) for b in bars]


def run(bars, side: int = 1, config: ReclaimConfig = BASE, early_closes=None):
    config = replace(config, allow_longs=side == 1, allow_shorts=side == -1)
    bars = bars if side == 1 else mirror(bars)
    if early_closes is None:
        return run_vwap_reclaim("MU", bars, config)
    return run_vwap_reclaim("MU", bars, config, early_closes)


def price(value: float, side: int) -> float:
    return value if side == 1 else 200 - value


def hhmm(moment: datetime) -> str:
    return moment.astimezone(ET).strftime("%H:%M")


def kinds(result) -> list[tuple[str, str, str]]:
    return [(hhmm(e.time), e.kind, e.detail) for e in result.events]


SIDES = pytest.mark.parametrize("side", [1, -1], ids=["long", "short"])


# --- entries -----------------------------------------------------------------


@SIDES
def test_arms_on_the_reclaim_confirms_above_its_high_and_fills_at_the_next_open(side: int) -> None:
    result = run(scenario([102.5, 103.5, 104.5, 105.5]), side)

    (trade,) = result.trades
    assert trade.setup == ("vwap_reclaim" if side == 1 else "vwap_rejection")
    assert (hhmm(trade.armed_time), hhmm(trade.signal_time), hhmm(trade.entry_time)) == ("09:39", "09:40", "09:41")
    assert trade.entry_price == pytest.approx(price(FILL, side))
    assert trade.stop == pytest.approx(price(STOP, side))
    assert trade.target == pytest.approx(price(TARGET, side))
    assert trade.risk == pytest.approx(2.51)
    assert trade.quantity == 40  # $100 over the expected 2.5 risk from the signal close
    assert trade.bars_to_confirm == 1


@SIDES
def test_the_fill_is_the_next_open_and_sets_r_and_the_target(side: int) -> None:
    # The 09:41 bar gaps up to 102.2: the fill is 102.21, not the 101.8 signal
    # close, so 1R is 2.91 and the target 102.21 + 1.5 x 2.91 = 106.575.
    result = run(scenario([102.5] * 5, {11: {"open": 102.2}}), side)
    (trade,) = result.trades
    assert trade.entry_price == pytest.approx(price(102.21, side))
    assert trade.risk == pytest.approx(2.91)
    assert trade.target == pytest.approx(price(106.575, side))
    assert trade.signal_close == pytest.approx(price(101.8, side))


@SIDES
def test_a_confirmation_too_far_from_vwap_is_not_chased(side: int) -> None:
    bars = scenario([102.5] * 5, {10: {"open": 100.5, "high": 103.0, "low": 101.0, "close": 102.5}})
    result = run(bars, side)
    assert result.trades == []
    assert ("09:39", "rejected", "more than the chase limit from VWAP") in kinds(result)


@SIDES
def test_a_close_back_through_vwap_cancels_the_setup(side: int) -> None:
    # 09:40 closes under VWAP (99.98). The 09:42 close of 101.6 clears the old
    # arming high (101.5) but not the new setup's (101.8), so nothing enters.
    today = SETUP + [99.8, 100.8, 101.6, 101.6, 101.6, 101.6]
    result = run(prior_session() + minute_bars(DAY, today), side)
    assert result.trades == []
    assert kinds(result)[:2] == [("09:39", "armed", ""), ("09:39", "cancelled", "closed back through VWAP")]


@SIDES
def test_a_setup_expires_after_three_bars_without_confirmation(side: int) -> None:
    today = SETUP + [101.0, 101.2, 101.4, 102.0, 102.0]
    result = run(prior_session() + minute_bars(DAY, today), side)
    assert result.trades == []
    assert ("09:39", "expired", "no confirmation in 3 bars") in kinds(result)


@SIDES
def test_fills_must_fall_inside_0935_to_1500(side: int) -> None:
    # Armed 09:31, confirmed on the 09:32 bar: the fill would be 09:33.
    early = prior_session() + minute_bars(DAY, [99.5, 100.5, 101.8, 101.8, 101.8], overrides={2: CONFIRM})
    assert run(early, side).trades == []
    assert ("09:31", "rejected", "outside the entry window") in kinds(run(early, side))

    def late(dip_minute: int) -> list[Bar]:
        closes = [100.0] * (dip_minute - 570) + [99.5, 100.5, 101.8] + [101.8] * 5
        return prior_session() + minute_bars(DAY, closes, overrides={dip_minute - 570 + 2: CONFIRM})

    # Confirmed on the 14:59 bar: the fill is 15:00, the last one allowed.
    assert [hhmm(t.entry_time) for t in run(late(897), side).trades] == ["15:00"]
    # Confirmed on the 15:00 bar: the fill would be 15:01.
    assert run(late(898), side).trades == []


@SIDES
def test_a_bar_that_opens_through_the_stop_cancels_the_entry(side: int) -> None:
    bars = scenario([99.5, 99.5], {11: {"open": 99.0, "high": 100.0, "low": 98.5}})
    result = run(bars, side)
    assert result.trades == []
    assert ("09:39", "rejected", "opened through the stop") in kinds(result)


# --- exits -------------------------------------------------------------------


@SIDES
@pytest.mark.parametrize(
    ("after", "overrides", "config", "exit_at", "exit_price", "reason"),
    [
        ([102.5, 103.5, 104.5, 105.5], {}, {}, "09:44", TARGET, "target"),
        ([101.0, 100.0], {}, {}, "09:42", STOP - 0.01, "stop"),
        # 20 minutes after the 09:41 fill: the bar that closes at 10:01.
        ([102.0] * 25, {}, {}, "10:00", 101.99, "time"),
        # One bar reaches both: the stop is assumed first, unless told otherwise.
        ([102.0], {11: {"high": 106.0, "low": 99.0}}, {}, "09:41", STOP - 0.01, "stop"),
        ([102.0], {11: {"high": 106.0, "low": 99.0}}, {"both_hit": "target"}, "09:41", TARGET, "target"),
        # A bar that opens through the stop fills at its open.
        ([101.0, 98.5], {12: {"open": 98.8}}, {}, "09:42", 98.79, "stop"),
    ],
    ids=["target", "stop", "time", "both_stop_first", "both_target_first", "gap_through_stop"],
)
def test_exit(after, overrides, config, exit_at, exit_price, reason, side: int) -> None:
    result = run(scenario(after, overrides), side, replace(BASE, **config))
    (trade,) = result.trades
    assert (trade.exit_reason, hhmm(trade.exit_time)) == (reason, exit_at)
    assert trade.exit_price == pytest.approx(price(exit_price, side))
    assert trade.r == pytest.approx((exit_price - FILL) / 2.51)
    assert trade.both_hit == (after == [102.0] and 11 in overrides)


@SIDES
def test_an_early_close_flattens_and_ignores_after_hours_bars(side: int) -> None:
    # Armed 12:42, confirmed 12:43, filled 12:44. The session ends at 13:00,
    # before the time stop, and the 13:00-13:05 crash is after hours.
    closes = [100.0] * 191 + [99.5, 100.5, 101.8] + [102.0] * 16 + [90.0] * 6
    bars = prior_session() + minute_bars(DAY, closes, overrides={193: CONFIRM})
    (trade,) = run(bars, side, early_closes={DAY: 780}).trades
    assert (trade.exit_reason, hhmm(trade.exit_time)) == ("session", "12:59")
    assert trade.exit_price == pytest.approx(price(101.99, side))


# --- daily limits --------------------------------------------------------------

# A long setup that confirms and then stops out: -1.004R each time.
LOSING_CYCLE = [100.0, 100.0, 100.0, 99.5, 100.5, 101.8, 101.0, 100.0, 100.0, 100.0]


def losing_day(cycles: int = 3) -> list[Bar]:
    closes = [100.0] * 5 + LOSING_CYCLE * cycles + [100.0] * 5
    overrides = {5 + 10 * k + 5: CONFIRM for k in range(cycles)}
    return prior_session() + minute_bars(DAY, closes, overrides=overrides)


@SIDES
@pytest.mark.parametrize(
    ("limits", "trades"),
    [
        ({"max_entries": 5, "max_losses": 5, "max_session_loss_r": 10.0}, 3),
        ({"max_entries": 5, "max_session_loss_r": 10.0}, 2),  # two losing trades
        ({"max_entries": 5, "max_losses": 5}, 2),  # -2R realized
        ({"max_losses": 5, "max_session_loss_r": 10.0}, 2),  # two entries
    ],
    ids=["no_limit_binds", "two_losses", "minus_two_r", "two_entries"],
)
def test_session_limits(limits, trades, side: int) -> None:
    result = run(losing_day(), side, replace(BASE, **limits))
    assert len(result.trades) == trades
    assert all(t.exit_reason == "stop" and t.r == pytest.approx(-0.01 / 2.51 - 1.0) for t in result.trades)


# --- statistics and export -------------------------------------------------------


def test_summary_measures_follow_the_framework() -> None:
    result = run(losing_day(), config=replace(BASE, max_entries=5, max_losses=5, max_session_loss_r=10.0))
    win = run(scenario([102.5, 103.5, 104.5, 105.5], day=NEXT)).trades
    stats = summarize(result.trades + win)

    loss = -1.0 - 0.01 / 2.51
    assert (stats.n, stats.days, stats.win_pct) == (4, 2, 25.0)
    assert stats.total_r == pytest.approx(3 * loss + 1.5)
    assert stats.profit_factor == pytest.approx(1.5 / (-3 * loss))
    assert (stats.avg_win_r, stats.avg_loss_r, stats.worst_r) == pytest.approx((1.5, loss, loss))
    assert stats.max_drawdown_r == pytest.approx(-3 * loss)  # three losses, then the win
    assert stats.r_without_best_trade == pytest.approx(3 * loss)
    assert stats.r_without_best_day == pytest.approx(3 * loss)


def test_the_csv_imports_into_strategy_lab() -> None:
    result = run(scenario([102.5, 103.5, 104.5, 105.5]))
    text = tradingview_csv(result.trades, result.config, entry_comment, exit_comment)
    parsed = parse_tradingview_csv(("﻿" + text).encode(), "America/New_York")

    assert (parsed.accepted_count, parsed.rejected_count) == (1, 0)
    assert not parsed.warnings, [w.message for w in parsed.warnings]
    features = parsed.trades[0].feature_snapshot
    assert (features["setup"], features["side"], features["exit_reason"], features["r"]) == (
        "vwap_reclaim", "long", "target", 1.5,
    )
    assert parsed.trades[0].entry_at.replace(tzinfo=timezone.utc) == result.trades[0].entry_time


# --- the script, with a stub loader -----------------------------------------------


def _load_script():
    path = BACKEND / "scripts" / "backtest_vwap_reclaim.py"
    spec = importlib.util.spec_from_file_location("backtest_vwap_reclaim_under_test", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class StubLoader:
    feed = "sip"

    def __init__(self) -> None:
        self.bars = scenario([102.5, 103.5, 104.5, 105.5])

    def minute_bars(self, symbols, day):
        rows = [
            {"t": b.time.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"), "o": b.open,
             "h": b.high, "l": b.low, "c": b.close, "v": b.volume}
            for b in self.bars if b.time.astimezone(ET).date() == day
        ]
        return {symbol: rows for symbol in symbols}

    def daily_bars(self, symbols, start, end):
        return {symbol: [] for symbol in symbols}


def test_the_script_backtests_and_writes_a_report_and_csv(tmp_path, capsys) -> None:
    script = _load_script()
    args = ["MU", "--start", DAY.isoformat(), "--end", DAY.isoformat(), "--warmup-days", "1",
            "--set", "slippage_bps=0", "--out", str(tmp_path)]
    assert script.main(args, loader_factory=StubLoader) == 0

    (run_dir,) = tmp_path.iterdir()
    report = (run_dir / "report.txt").read_text()
    assert "ALL" in report and "n=   1" in report and "slippage_bps" in report
    (csv_path,) = run_dir.glob("VWR_py_v0.1_MU_*.csv")
    rows = list(csv.DictReader(io.StringIO(csv_path.read_text(encoding="utf-8-sig"))))
    assert [row["Type"] for row in rows] == ["Exit long", "Entry long"]
    assert "WARNING: IEX" not in capsys.readouterr().err


def test_overrides_are_typed_and_unknown_fields_fail() -> None:
    script = _load_script()
    config = script.build_config(["target_r=2", "allow_shorts=false", "max_hold_min=30"], 3)
    assert (config.target_r, config.allow_shorts, config.max_hold_min, config.timeframe_minutes) == (2.0, False, 30, 3)
    with pytest.raises(SystemExit):
        script.build_config(["not_a_field=1"], 1)


def test_prior_session_seeds_the_indicators_so_nothing_arms_without_it() -> None:
    today = minute_bars(DAY, SETUP + [101.8] + [102.0] * 5, overrides={10: CONFIRM})
    # Ten bars of today alone cannot seed ATR(14) by 09:39: nothing arms.
    assert run(today).events == []
