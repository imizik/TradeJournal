"""Reports, TradingView-shaped CSVs and export parity for the Market Map port,
plus the backtest script end to end with a stub bar loader (no network)."""

from __future__ import annotations

import importlib.util
import math
import re
import sys
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from app.engine.market_map import ET, MarketMapConfig, run_market_map
from app.engine.market_map_report import (
    ExportedTrade,
    compare_to_export,
    cohort_report,
    entry_comment,
    exit_comment,
    group_stats,
    load_tradingview_export,
    pine_number,
    tradingview_csv,
)
from app.engine.strategy_csv import parse_tradingview_csv
from tests.market_map_bars import DAY, NEXT_DAY, PRIOR_DAY, daily_history, flat_benchmark, quiet_day, session

BACKEND = Path(__file__).resolve().parents[1]
PINE = (BACKEND.parent / "docs" / "pine" / "isaac_market_map.pine").read_text()


def _pine_function(name: str) -> str:
    lines = PINE.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(f"{name}("))
    body = [lines[start]]
    for line in lines[start + 1 :]:
        if line and not line.startswith(" "):
            break
        body.append(line)
    return "\n".join(body)


def _three_trade_run():
    """Two days of the power-window factory: stop, time and eod exits."""
    bars = quiet_day()
    for day in (DAY, NEXT_DAY):
        closes = [100.0] * 54 + [101.7 + 0.1 * k for k in range(24)]
        bars += session(day, closes, first_open=100.0, overrides={55: {"low": 95.0}})
    config = replace(MarketMapConfig(), enable_orb=False, enable_level_breaks=False, enable_vwap=False)
    return run_market_map("MU", bars, daily_history(), flat_benchmark(bars), config)


# --- sl1 comments -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "text"),
    [(1.8234567, "1.823457"), (-0.3125, "-0.3125"), (0.0000004, "0"), (-0.0000004, "0"), (3, "3"),
     (12345.678901234, "12345.678901"), (0.08, "0.08"), (math.nan, "null"), (None, "null")],
)
def test_numbers_render_as_pine_f_num(value, text) -> None:
    assert pine_number(value) == text


def test_comments_carry_the_pine_keys_in_the_pine_order() -> None:
    trade = _three_trade_run().closed_trades[0]
    pine_entry = re.findall(r'f_sl1\("([^"]+)"', _pine_function("f_entryComment"))
    pine_exit = re.findall(r'f_sl1\("([^"]+)"', _pine_function("f_exitComment"))

    assert [token.split("=")[0] for token in entry_comment(trade).split("|")[1:]] == pine_entry
    assert [token.split("=")[0] for token in exit_comment(trade).split("|")[1:]] == pine_exit


# --- TradingView-shaped CSV --------------------------------------------------------


def test_the_csv_imports_into_strategy_lab_with_every_trade_and_no_warnings() -> None:
    result = _three_trade_run()
    closed = result.closed_trades
    assert {t.exit_reason for t in closed} >= {"stop", "time"}

    parsed = parse_tradingview_csv(("﻿" + tradingview_csv(result.trades, result.config)).encode(), "America/New_York")

    assert parsed.accepted_count == len(closed)
    assert parsed.rejected_count == 0
    assert not parsed.warnings, [w.message for w in parsed.warnings]
    first = parsed.trades[0]
    assert first.feature_snapshot["setup"] == closed[0].setup
    assert first.feature_snapshot["exit_reason"] == closed[0].exit_reason
    assert first.entry_at.replace(tzinfo=timezone.utc) == closed[0].entry_time
    assert (first.net_pnl, first.duration_bars) == (Decimal(f"{closed[0].pnl:.2f}"), closed[0].bars_held)


def test_the_csv_reads_back_as_the_same_trades() -> None:
    result = _three_trade_run()
    exported = load_tradingview_export(tradingview_csv(result.trades, result.config))

    assert [(e.entry_stamp, e.side, e.setup) for e in exported] == [
        (t.entry_time.astimezone(ET).strftime("%Y-%m-%d %H:%M"), t.side_text, t.setup) for t in result.closed_trades
    ]


# --- cohort report -----------------------------------------------------------------


def test_group_stats_are_in_r_with_drawdown_from_the_running_peak() -> None:
    trades = _three_trade_run().closed_trades[:1] * 4
    budgets = [1, -1, -1, 2]
    fake = []
    for trade, r in zip(trades, budgets):
        clone = replace(trade, quantity=1, risk_budget=1.0)
        clone.exit_price = clone.entry_price + r
        fake.append(clone)
    for index, trade in enumerate(fake):
        trade.entry_time = trade.entry_time + timedelta(minutes=index)

    stats = group_stats(fake)
    assert (stats.n, stats.total_r, stats.win_pct, stats.profit_factor, stats.max_drawdown_r) == (
        4, pytest.approx(1.0), 50.0, pytest.approx(1.5), pytest.approx(2.0)
    )


def test_the_report_groups_by_every_requested_dimension() -> None:
    text = cohort_report(_three_trade_run().trades)
    for heading in ("ticker", "setup", "side", "grade", "window", "exit_reason", "tier"):
        assert f"== {heading}" in text
    assert text.startswith("  ALL")


# --- parity ------------------------------------------------------------------------


def test_parity_with_its_own_export_is_complete() -> None:
    result = _three_trade_run()
    exported = load_tradingview_export(tradingview_csv(result.trades, result.config))
    report = compare_to_export(result.trades, result.signals, exported)

    assert report.matched == report.tradingview_entries == len(result.closed_trades)
    assert report.match_rate == 1.0 and report.mismatches == []
    assert report.agreement == {"grade": 1.0, "size": 1.0, "exit_reason": 1.0, "exit_time": 1.0}


def test_parity_names_a_cause_for_every_mismatch() -> None:
    result = _three_trade_run()
    exported = load_tradingview_export(tradingview_csv(result.trades, result.config))
    first, second = exported[0], exported[1]
    cooled_down = next(s for s in result.signals if s.outcome == "cooldown")
    stamp = cooled_down.time.astimezone(ET).strftime("%Y-%m-%d %H:%M")
    altered = [
        # TradingView held the first trade longer, so the port's second entry is a knock-on.
        ExportedTrade(first.entry_stamp, second.exit_stamp, first.side, first.setup, first.fields),
        # A TradingView entry on a bar where the port had the same signal but was cooling down.
        ExportedTrade(stamp, stamp, "long", cooled_down.setup, {"grade": "B"}),
        # A TradingView entry where the port saw no setup at all.
        ExportedTrade(f"{DAY.isoformat()} 10:00", f"{DAY.isoformat()} 10:05", "long", "orb_break", {}),
        *exported[2:],
    ]
    report = compare_to_export(result.trades, result.signals, sorted(altered, key=lambda e: e.entry_stamp))

    causes = {(m.source, m.stamp): m.cause for m in report.mismatches}
    assert causes[("python", second.entry_stamp)] == "knock-on"
    assert causes[("tradingview", stamp)] == "knock-on"
    assert causes[("tradingview", f"{DAY.isoformat()} 10:00")] == "no signal (prices)"
    assert report.matched == len(exported) - 1


# --- the script, end to end with a stub loader ---------------------------------------


def _load_script():
    path = BACKEND / "scripts" / "backtest_market_map.py"
    spec = importlib.util.spec_from_file_location("backtest_market_map_under_test", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _alpaca(bars) -> list[dict]:
    return [
        {"t": b.time.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"), "o": b.open, "h": b.high,
         "l": b.low, "c": b.close, "v": b.volume}
        for b in bars
    ]


class StubLoader:
    feed = "sip"

    def __init__(self) -> None:
        closes = [100.0] * 54 + [101.7 + 0.1 * k for k in range(24)]
        mu = quiet_day() + session(DAY, closes, first_open=100.0, overrides={55: {"low": 95.0}})
        self.minutes = {"MU": mu, "SPY": flat_benchmark(mu)}
        self.requested_days = []

    def minute_bars(self, symbols, day):
        self.requested_days.append(day)
        return {s: _alpaca([b for b in self.minutes[s] if b.time.astimezone(ET).date() == day]) for s in symbols}

    def daily_bars(self, symbols, start, end):
        rows = [
            {"t": datetime(d.day.year, d.day.month, d.day.day, tzinfo=ET).isoformat(), "o": d.open, "h": d.high,
             "l": d.low, "c": d.close}
            for d in daily_history()
        ]
        return {s: rows for s in symbols}


def test_the_script_backtests_writes_csvs_and_checks_parity(tmp_path, capsys) -> None:
    script = _load_script()
    loader = StubLoader()
    args = ["MU", "--start", DAY.isoformat(), "--end", DAY.isoformat(), "--warmup-days", "1", "--out", str(tmp_path)]

    assert script.main(args, loader_factory=lambda: loader) == 0
    assert set(loader.requested_days) == {PRIOR_DAY, DAY}
    (run_dir,) = tmp_path.iterdir()
    (csv_path,) = run_dir.glob("IMM_py_v1.1.0_MU_*.csv")
    exported = load_tradingview_export(csv_path.read_text(encoding="utf-8-sig"))
    assert exported and all(e.entry_stamp.startswith(DAY.isoformat()) for e in exported)
    report = (run_dir / "report.txt").read_text()
    assert "== setup" in report and "hod_break" in report
    assert "WARNING: IEX" not in capsys.readouterr().err

    # Feed the port's own export back as the "TradingView" export.
    export_copy = tmp_path / f"IMM_v1.1.0_NASDAQ_MU_{DAY.isoformat()}.csv"
    export_copy.write_text(csv_path.read_text(encoding="utf-8-sig"))
    out2 = tmp_path / "second"
    assert script.main([*args[1:-1], str(out2), "--parity", str(export_copy)], loader_factory=lambda: loader) == 0
    parity = next(out2.iterdir()) / "parity.txt"
    assert f"MU: {len(exported)}/{len(exported)} TradingView entries matched (100.0%)" in parity.read_text()


def test_the_script_warns_when_the_feed_is_iex(tmp_path, capsys) -> None:
    script = _load_script()
    loader = StubLoader()
    loader.feed = "iex"
    args = ["MU", "--start", DAY.isoformat(), "--end", DAY.isoformat(), "--warmup-days", "1", "--out", str(tmp_path)]
    script.main(args, loader_factory=lambda: loader)
    assert "WARNING: IEX feed" in capsys.readouterr().err


def test_set_overrides_are_typed_and_unknown_fields_fail() -> None:
    script = _load_script()
    config = script.build_config("v1.0.0", ["allow_shorts=false", "rvol_min=2", "max_entries_per_day=1"], 5)
    assert (config.allow_shorts, config.rvol_min, config.max_entries_per_day) == (False, 2.0, 1)
    assert config.indicator_version == "1.0.0"
    with pytest.raises(SystemExit):
        script.build_config("v1.1.0", ["not_a_field=1"], 5)


def test_split_adjusted_daily_closes_are_flagged_against_minute_closes() -> None:
    from app.engine.market_map import DailyBar

    script = _load_script()
    chart = quiet_day()
    assert script.adjustment_mismatches(chart, [DailyBar(PRIOR_DAY, 100, 101, 99, 100.1)]) == []
    assert script.adjustment_mismatches(chart, [DailyBar(PRIOR_DAY, 25, 26, 24, 25.0)]) == [PRIOR_DAY]


def test_export_names_give_ticker_and_version() -> None:
    script = _load_script()
    assert script.export_ticker("TradingView/IMM_v1.0.0_NASDAQ_MU_2026-09-24.csv") == "MU"
    assert script.export_version("TradingView/IMM_v1.0.0_NASDAQ_MU_2026-09-24.csv") == "1.0.0"
    assert script.find_exports("TradingView/IMM_v1.0.0_*.csv")
