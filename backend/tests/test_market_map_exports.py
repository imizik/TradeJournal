"""The port's execution model against real TradingView output.

The committed Strategy Tester exports (`backend/TradingView/IMM_v1.0.0_*.csv`)
cannot be replayed here without the bars behind them, but every trade in them
still carries the fingerprints of how TradingView filled and sequenced it.
Each test below states one rule the port implements and checks it against
every trade in every export, using the port's own functions and inputs:

- slippage and the breakeven stop: a breakeven exit fills exactly 2 ticks
  under the entry bar's close, which is 4 ticks under the entry fill, or
  worse when the stop is already through the price it fills at (a gap open,
  or the close of the bar that moved it there), never better;
- the time stop and the 15:55 flatten, measured in bars;
- the v1.0.0 grade, size and window rules, from each entry's own sl1 fields;
- the cooldown: from the exit bar for stop-type exits, one bar later for
  market closes, because the script notices those on the next bar. A stop
  filled at a bar's close is noticed on the next bar too, but the export
  cannot tell it from an intrabar fill, so stop-type exits keep the earlier
  bound;
- the daily entry and loss limits.

Entry-by-entry parity on real bars is `scripts/backtest_market_map.py --parity`.
"""

from __future__ import annotations

import csv
import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app.engine.market_map import MarketMapConfig, grade_for, session_window, size_for, ticker_tier
from app.engine.market_map_report import sl1_fields

EXPORTS = sorted((Path(__file__).resolve().parents[1] / "TradingView").glob("IMM_v1.0.0_*.csv"))
CONFIG = MarketMapConfig.v1_0_0()
TICK = CONFIG.tick_size
STEP = timedelta(minutes=CONFIG.timeframe_minutes)


@dataclass(frozen=True)
class ExportTrade:
    ticker: str
    side: int
    entry: datetime
    exit: datetime
    entry_price: float
    exit_price: float
    quantity: int
    pnl: float
    fields: dict[str, str]

    @property
    def reason(self) -> str:
        return self.fields["exit_reason"]

    def number(self, key: str) -> float:
        value = self.fields.get(key, "null")
        return math.nan if value == "null" else float(value)


def _load() -> list[ExportTrade]:
    trades = []
    for path in EXPORTS:
        pairs: dict[str, dict[str, dict[str, str]]] = defaultdict(dict)
        with path.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                pairs[row["Trade number"]][row["Type"].split()[0]] = row
        for pair in pairs.values():
            if "Exit" not in pair:
                continue
            entry, exit_row = pair["Entry"], pair["Exit"]
            trades.append(
                ExportTrade(
                    ticker=path.stem.split("_")[-2],
                    side=1 if entry["Type"].endswith("long") else -1,
                    entry=datetime.fromisoformat(entry["Date and time"]),
                    exit=datetime.fromisoformat(exit_row["Date and time"]),
                    entry_price=float(entry["Price USD"]),
                    exit_price=float(exit_row["Price USD"]),
                    quantity=int(entry["Size (qty)"]),
                    pnl=float(entry["Net PnL USD"]),
                    fields={**sl1_fields(exit_row["Signal"]), **sl1_fields(entry["Signal"])},
                )
            )
    return trades


TRADES = _load()


def test_the_exports_are_here() -> None:
    assert len(EXPORTS) == 5 and len(TRADES) > 1400


def test_breakeven_exits_fill_two_ticks_through_the_entry_close_or_worse() -> None:
    slip = CONFIG.slippage * TICK
    exact = worse = 0
    for t in (t for t in TRADES if t.reason == "be"):
        expected = t.entry_price - t.side * 2 * slip
        shortfall = t.side * (t.exit_price - expected)
        assert shortfall <= 1e-9, f"{t.ticker} {t.entry} filled better than the stop: {t.exit_price} vs {expected}"
        exact += abs(shortfall) < 1e-9
        worse += shortfall < -1e-9
    assert exact > worse > 0


def test_mfe_at_exit_agrees_with_the_exit_stage() -> None:
    for t in TRADES:
        mfe = t.number("mfe_r")
        if t.reason == "stop":
            assert mfe < CONFIG.breakeven_at_r
        elif t.reason == "be":
            assert mfe >= CONFIG.breakeven_at_r
        elif t.reason == "trail":
            assert mfe >= CONFIG.trail_start_r
        elif t.reason == "time":
            assert mfe < CONFIG.time_stop_min_r


def test_time_stops_and_the_flatten_happen_on_the_modelled_bar() -> None:
    flat = datetime.strptime(str(CONFIG.flat_time), "%H%M")
    for t in TRADES:
        if t.reason == "time":
            assert t.exit - t.entry == timedelta(minutes=CONFIG.time_stop_min)
        if t.reason == "eod":
            # The bar whose close is 15:55 opens one bar earlier.
            assert (t.exit.hour, t.exit.minute) == ((flat - STEP).hour, (flat - STEP).minute)


def test_grade_size_and_window_follow_the_v1_0_0_rules() -> None:
    for t in TRADES:
        minute = t.entry.hour * 60 + t.entry.minute
        tier = ticker_tier(CONFIG, t.ticker)
        window = session_window(CONFIG, minute)
        grade = grade_for(CONFIG, tier, t.fields["setup"], t.side, t.number("rvol"), t.number("rs_vs_spy"))
        assert (t.fields["window"], t.fields["grade"], t.fields["size"], t.fields["tier"]) == (
            window,
            grade,
            size_for(grade, window, tier),
            tier,
        ), f"{t.ticker} {t.entry}"


def test_pnl_is_price_difference_times_quantity() -> None:
    for t in TRADES:
        assert t.pnl == pytest.approx(t.side * (t.exit_price - t.entry_price) * t.quantity, abs=0.011)


def test_the_cooldown_runs_from_the_bar_the_exit_is_noticed() -> None:
    cooldown = timedelta(minutes=CONFIG.cooldown_min)
    at_minimum = defaultdict(int)
    by_ticker = defaultdict(list)
    for t in TRADES:
        by_ticker[t.ticker].append(t)
    for trades in by_ticker.values():
        trades.sort(key=lambda t: t.entry)
        for current, following in zip(trades, trades[1:]):
            if following.entry.date() != current.exit.date():
                continue
            market_close = current.reason in ("time", "eod")
            # Intrabar stop fills are seen on their own bar; market closes (and
            # stops filled at a close, indistinguishable here) on the next one.
            earliest = current.exit + cooldown + (STEP if market_close else timedelta(0))
            assert following.entry >= earliest, f"{current.ticker} {current.exit} -> {following.entry}"
            at_minimum[market_close] += following.entry == earliest
    # Both edges are exercised: entries land exactly on each boundary.
    assert at_minimum[False] > 0 and at_minimum[True] > 0


def test_daily_entry_and_loss_limits_hold() -> None:
    days = defaultdict(list)
    for t in TRADES:
        days[(t.ticker, t.entry.date())].append(t)
    for trades in days.values():
        trades.sort(key=lambda t: t.entry)
        assert len(trades) <= CONFIG.max_entries_per_day
        losses = 0
        for t in trades:
            assert losses < CONFIG.max_losses_per_day
            losses += t.pnl < 0 and t.reason == "stop"
    assert max(len(v) for v in days.values()) == CONFIG.max_entries_per_day
