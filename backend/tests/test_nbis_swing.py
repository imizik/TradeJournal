"""The NBIS recovery swing (v0.1) on synthetic 15-minute bars.

Each default bar opens at the previous close and spans 0.5 either side of its
close, so with moves of at most 0.5 every true range is 1.0 and ATR(14) stays
exactly 1.0. Two prior sessions at 101 seed the 15-minute EMA 20 at 101, and
the daily EMA 20 is 100 unless a test says otherwise.

The core scenario: 09:45 trades down to 99.5, under the daily EMA (armed);
10:00-10:30 hold 100 under the falling 15-minute EMA; the 10:45 bar closes
at 101.0, back above that EMA (100.67) and above the prior three highs
(100.5), so it triggers. The 11:00 fill is 101.01 (one tick of slippage),
the stop 99.5 - 0.1 = 99.4, so 1R is 1.61 and the 2R target 104.23.
"""

from __future__ import annotations

import csv
import importlib.util
import io
import sys
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.engine.market_map import ET, Bar, DailyBar
from app.engine.market_map_report import tradingview_csv
from app.engine.nbis_swing import SwingConfig, entry_comment, exit_comment, intraday_only, run_nbis_swing
from app.engine.strategy_csv import parse_tradingview_csv
from app.engine.vwap_reclaim import summarize

PRIOR2, PRIOR, DAY, NEXT, THIRD = (date(2026, 2, 27), date(2026, 3, 2), date(2026, 3, 3), date(2026, 3, 4),
                                   date(2026, 3, 5))
BACKEND = Path(__file__).resolve().parents[1]
BASE = SwingConfig(slippage_bps=0.0)
DIP = [100.5, 100.0, 100.0, 100.0, 100.0]  # 09:30-10:30, armed at 09:45
TRIGGER = {"open": 100.0, "high": 101.0, "low": 100.0}  # the 10:45 bar, close 101.0
STOP, FILL, TARGET, RISK = 99.4, 101.01, 104.23, 1.61


def at(day: date, minute_of_day: int) -> datetime:
    return datetime(day.year, day.month, day.day, minute_of_day // 60, minute_of_day % 60, tzinfo=ET)


def bars15(day: date, closes: list[float], overrides: dict | None = None, previous: float | None = None) -> list[Bar]:
    bars, prior = [], closes[0] if previous is None else previous
    for index, close in enumerate(closes):
        values = {"open": prior, "high": max(close + 0.5, prior), "low": min(close - 0.5, prior), "close": close}
        values.update((overrides or {}).get(index, {}))
        bars.append(Bar(at(day, 570 + 15 * index), values["open"], values["high"], values["low"], values["close"], 1000.0))
        prior = close
    return bars


def daily_history(close: float = 100.0, days: int = 40, extra: list[DailyBar] | None = None) -> list[DailyBar]:
    bars, current = [], PRIOR2 - timedelta(days=1)
    while len(bars) < days:
        if current.weekday() < 5:
            bars.append(DailyBar(current, close, close, close, close))
        current -= timedelta(days=1)
    return sorted(bars + (extra or []), key=lambda bar: bar.day)


def history() -> list[Bar]:
    return bars15(PRIOR2, [101.0] * 26) + bars15(PRIOR, [101.0] * 26)


def scenario(after_day: list[float], next_day: list[float] | None = None, day_overrides: dict | None = None,
             next_overrides: dict | None = None) -> list[Bar]:
    """The core trigger at 10:45 on DAY, then `after_day` from 11:00 and `next_day` on NEXT."""
    today = DIP + [101.0] + after_day
    bars = history() + bars15(DAY, today, {5: TRIGGER, **(day_overrides or {})}, previous=101.0)
    if next_day:
        bars += bars15(NEXT, next_day, next_overrides, previous=today[-1])
    return bars


def run(bars, config: SwingConfig = BASE, daily=None):
    return run_nbis_swing("NBIS", bars, daily or daily_history(), config)


def hhmm(moment: datetime) -> str:
    return moment.astimezone(ET).strftime("%H:%M")


def kinds(result) -> list[tuple[str, str]]:
    return [(e.time.astimezone(ET).strftime("%m-%d %H:%M"), e.kind) for e in result.events]


# --- the trigger --------------------------------------------------------------


def test_arms_below_the_daily_ema_and_triggers_on_the_15_minute_reclaim_and_breakout() -> None:
    (trade,) = run(scenario([101.5] * 5)).trades
    assert (hhmm(trade.armed_time), hhmm(trade.signal_time), hhmm(trade.entry_time)) == ("09:45", "10:45", "11:00")
    assert (trade.entry_price, trade.stop, trade.target) == pytest.approx((FILL, STOP, TARGET))
    assert trade.risk == pytest.approx(RISK)
    assert trade.quantity == 62  # $100 over the expected 1.6 risk from the signal close
    assert trade.daily_ema == pytest.approx(100.0)


def test_the_stop_covers_four_bars_and_the_breakout_three() -> None:
    # 10:00 is the fourth bar back from the 10:45 trigger. Its low of 99.2
    # sets the stop (a three-bar window would use 99.5).
    (trade,) = run(scenario([101.5] * 5, day_overrides={2: {"low": 99.2}})).trades
    assert trade.stop == pytest.approx(99.2 - 0.1 * trade.atr_at_signal)
    assert trade.stop < 99.2 - 0.1

    # Its high of 101.2 is the third bar back from the trigger bar: the 101.0
    # close does not clear it (a two-bar window would), so nothing triggers.
    assert run(scenario([101.5] * 5, day_overrides={2: {"high": 101.2}})).trades == []


def test_without_a_dip_below_the_daily_ema_nothing_arms() -> None:
    result = run(scenario([101.5] * 5), daily=daily_history(close=90.0))
    assert result.trades == [] and result.events == []


def test_the_daily_ema_is_the_prior_completed_days() -> None:
    # A daily bar for DAY itself, closing at 1, must not move DAY's level.
    daily = daily_history(extra=[DailyBar(DAY, 1.0, 1.0, 1.0, 1.0)])
    assert len(run(scenario([101.5] * 5), daily=daily).trades) == 1


def test_the_arming_bar_never_triggers() -> None:
    # Daily EMA 99.85: the 09:45-10:30 lows (99.9) stay above it, and the
    # 10:45 bar both dips to 99.8 and satisfies the trigger. It arms only.
    closes = [100.5, 100.4, 100.4, 100.4, 100.4, 101.0] + [101.0] * 5
    bars = history() + bars15(DAY, closes, {5: {"open": 100.4, "high": 101.0, "low": 99.8}}, previous=101.0)
    result = run(bars, daily=daily_history(close=99.85))
    assert result.trades == []
    assert kinds(result) == [("03-03 10:45", "armed")]


def test_an_arm_lasts_two_sessions() -> None:
    # Armed on DAY; NEXT holds above the daily EMA without a trigger; THIRD
    # has a reclaim and breakout that stays above the daily EMA.
    today = DIP + [100.6] * 21
    third = [100.55, 100.55, 100.55, 101.2] + [101.2] * 5
    bars = (
        history()
        + bars15(DAY, today, previous=101.0)
        + bars15(NEXT, [100.6] * 26, previous=100.6)
        + bars15(THIRD, third, {3: {"open": 100.55, "high": 101.2, "low": 100.55}}, previous=100.6)
    )
    expired = run(bars)
    assert expired.trades == []
    assert kinds(expired) == [("03-03 09:45", "armed"), ("03-03 09:45", "expired")]
    assert [hhmm(t.signal_time) for t in run(bars, replace(BASE, arm_sessions=3)).trades] == ["10:15"]


def test_each_arm_triggers_once() -> None:
    # After the first trade reaches its target, a second reclaim and
    # breakout comes without a new dip under the daily EMA: no second trade.
    after = [101.5, 102.0, 102.5, 103.0, 103.5, 104.0, 101.6, 101.6, 101.6, 101.6, 102.5, 102.5]
    overrides = {12: {"open": 104.0, "high": 104.0, "low": 101.5}, 16: {"open": 101.6, "high": 102.5, "low": 101.6}}
    result = run(scenario(after, day_overrides=overrides))
    assert len(result.trades) == 1
    assert result.trades[0].exit_reason == "target"


def test_the_daily_ema_reading_reclaims_the_daily_level_instead() -> None:
    # Under reclaim_level="daily_ema" the 10:45 close must cross 100, the
    # daily EMA, from at or below it: 10:30 closed at 100.0, so it does.
    (trade,) = run(scenario([101.5] * 5), replace(BASE, reclaim_level="daily_ema")).trades
    assert hhmm(trade.signal_time) == "10:45"


# --- exits ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("after_day", "next_day", "next_overrides", "exit_at", "exit_price", "reason", "sessions", "intraday_price"),
    [
        ([101.5, 102.0, 102.5, 103.0, 103.5, 104.0], None, None, "03-03 12:15", TARGET, "target", 1, TARGET),
        ([100.5, 100.0, 99.5], None, None, "03-03 11:30", STOP - 0.01, "stop", 1, STOP - 0.01),
        # Carried overnight: flat at the end of the second session. The
        # intraday-only exit with the same entry is the first session's close.
        ([101.5] * 20, [102.5] * 26, {0: {"open": 102.5}}, "03-04 15:45", 102.49, "time", 2, 101.49),
        # NEXT opens under the stop: it fills at the open.
        ([101.5] * 20, [99.0] * 3, {0: {"open": 99.0, "high": 99.5, "low": 98.5}}, "03-04 09:30", 98.99, "stop", 2,
         101.49),
    ],
    ids=["target", "stop", "two_sessions", "overnight_gap"],
)
def test_exit(after_day, next_day, next_overrides, exit_at, exit_price, reason, sessions, intraday_price) -> None:
    (trade,) = run(scenario(after_day, next_day, next_overrides=next_overrides)).trades
    assert (trade.exit_reason, trade.exit_time.astimezone(ET).strftime("%m-%d %H:%M")) == (reason, exit_at)
    assert trade.exit_price == pytest.approx(exit_price)
    assert trade.r == pytest.approx((exit_price - FILL) / RISK)
    assert trade.sessions_held == sessions
    assert intraday_only(trade).r == pytest.approx((intraday_price - FILL) / RISK)


def test_one_session_holds_are_the_intraday_exit() -> None:
    (trade,) = run(scenario([101.5] * 20, [102.5] * 26), replace(BASE, max_sessions=1)).trades
    assert (trade.exit_reason, hhmm(trade.exit_time), trade.exit_price) == ("time", "15:45", pytest.approx(101.49))


def test_summary_and_the_strategy_lab_csv() -> None:
    result = run(scenario([101.5, 102.0, 102.5, 103.0, 103.5, 104.0]))
    assert summarize(result.trades).total_r == pytest.approx(2.0)

    text = tradingview_csv(result.trades, result.config, entry_comment, exit_comment)
    parsed = parse_tradingview_csv(("﻿" + text).encode(), "America/New_York")
    assert (parsed.accepted_count, parsed.rejected_count) == (1, 0)
    assert not parsed.warnings, [w.message for w in parsed.warnings]
    features = parsed.trades[0].feature_snapshot
    assert (features["setup"], features["exit_reason"], features["r"], features["sessions"]) == (
        "nbis_recovery", "target", 2, 1,
    )


# --- the script, with a stub loader ---------------------------------------------


def _load_script():
    path = BACKEND / "scripts" / "backtest_nbis_swing.py"
    spec = importlib.util.spec_from_file_location("backtest_nbis_swing_under_test", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class StubLoader:
    feed = "sip"

    def __init__(self) -> None:
        self.bars = scenario([101.5, 102.0, 102.5, 103.0, 103.5, 104.0])

    def minute_bars(self, symbols, day):
        rows = [
            {"t": b.time.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"), "o": b.open,
             "h": b.high, "l": b.low, "c": b.close, "v": b.volume}
            for b in self.bars if b.time.astimezone(ET).date() == day
        ]
        return {symbol: rows for symbol in symbols}

    def daily_bars(self, symbols, start, end):
        rows = [{"t": at(d.day, 0).isoformat(), "o": d.open, "h": d.high, "l": d.low, "c": d.close}
                for d in daily_history()]
        return {symbol: rows for symbol in symbols}


def test_the_script_backtests_and_writes_a_report_and_csv(tmp_path) -> None:
    script = _load_script()
    args = ["NBIS", "--start", DAY.isoformat(), "--end", DAY.isoformat(), "--warmup-days", "5",
            "--set", "slippage_bps=0", "--out", str(tmp_path)]
    assert script.main(args, loader_factory=StubLoader) == 0

    (run_dir,) = tmp_path.iterdir()
    report = (run_dir / "report.txt").read_text()
    assert "intraday-only exits, same entries" in report and "n=   1" in report
    (csv_path,) = run_dir.glob("NBS_py_v0.1_NBIS_*.csv")
    rows = list(csv.DictReader(io.StringIO(csv_path.read_text(encoding="utf-8-sig"))))
    assert [row["Type"] for row in rows] == ["Exit long", "Entry long"]
