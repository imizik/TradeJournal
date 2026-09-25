"""
Acceptance report, in R, for the Pine research strategies.

Reads TradingView Strategy Tester "List of trades" CSVs exported from the
research scripts in docs/pine/ (first: intraday_reclaim.pine). Every file goes
through Strategy Lab's own importer, so the report sees exactly what an import
would store. It prints the measures from the "Iteration and acceptance
framework" in docs/pine/research-framework.md:
- trades and independent sessions
- expectancy, profit factor and max drawdown
- average win and loss, tail loss and holding time
- totals without the best trade and without the best day
- the same, split by side, ticker, month and exit reason
- cost stress, mechanics checks and a replay checklist

R is net PnL divided by the actual risk, quantity x |fill - frozen stop|, so
every trade counts equally whatever size the capital cap allowed. Runs with a
different strategy, version, variant, timeframe, settings or data feed
(BATS vs NASDAQ) are reported separately and never pooled.

Usage (from backend/):
    python scripts/pine_research_report.py "TradingView/IR_*.csv"
    python scripts/pine_research_report.py "TradingView/IR_*.csv" --replay 10
"""

from __future__ import annotations

import argparse
import glob
import re
import statistics
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.engine.strategy_csv import parse_tradingview_csv  # noqa: E402

REQUIRED_KEYS = ("setup_id", "stop", "risk_ps", "signal_close", "exit_reason")
NEW_YORK = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class Trade:
    config: str
    ticker: str
    side: str
    setup_id: str
    armed_at: str
    entry_raw: str
    exit_raw: str
    fill: float
    exit_price: float
    stop: float
    target: float | None
    risk: float
    r: float
    entry_slip_r: float
    overshoot_r: float | None
    exit_reason: str
    hold_min: int
    tick: float

    @property
    def day(self) -> str:
        return self.entry_raw[:10]

    @property
    def month(self) -> str:
        return self.entry_raw[:7]

    def stressed_r(self, ticks_per_side: int) -> float:
        return self.r - 2 * ticks_per_side * self.tick / self.risk


def parse_setup_id(setup_id: str) -> dict[str, str] | None:
    """`prefix:version:exchange:ticker:timeframe:arm_close_ms:side`, as the
    strategy's f_setupId writes it."""

    parts = setup_id.split(":")
    if len(parts) != 7 or not parts[5].isdigit():
        return None
    keys = ("prefix", "version", "exchange", "ticker", "timeframe", "arm_ms", "side")
    return dict(zip(keys, parts))


def load_trades(paths: list[str], source_timezone: str) -> tuple[list[Trade], list[str]]:
    trades: list[Trade] = []
    problems: list[str] = []
    seen: dict[tuple[str, str], str] = {}
    for path in paths:
        name = Path(path).name
        duplicates: dict[str, int] = defaultdict(int)
        result = parse_tradingview_csv(Path(path).read_bytes(), source_timezone)
        for rejected in result.rejected_trades:
            reasons = "; ".join(issue.message for issue in rejected.issues)
            problems.append(f"{name}: trade {rejected.trade_number} rejected: {reasons}")
        for parsed in result.trades:
            features = parsed.feature_snapshot
            missing = [key for key in REQUIRED_KEYS if features.get(key) is None]
            ids = parse_setup_id(str(features.get("setup_id", "")))
            if missing or ids is None or parsed.net_pnl is None:
                what = ", ".join(missing) if missing else "a valid setup_id" if ids is None else "net PnL"
                problems.append(f"{name}: trade {parsed.trade_number} has no {what}; skipped")
                continue
            # The same trade in two files (a re-export, or one run saved under
            # two names) would be counted twice.
            identity = (str(features["setup_id"]), parsed.entry_at_raw)
            if identity in seen:
                duplicates[seen[identity]] += 1
                continue
            seen[identity] = name
            direction = 1 if parsed.direction == "long" else -1
            fill = float(parsed.entry_price)
            exit_price = float(parsed.exit_price)
            stop = float(features["stop"])
            planned_risk = float(features["risk_ps"])
            actual_risk = direction * (fill - stop)
            risk = actual_risk if actual_risk > 0 else planned_risk
            target_r = features.get("target_r")
            reason = str(features["exit_reason"])
            armed = datetime.fromtimestamp(int(ids["arm_ms"]) / 1000, NEW_YORK)
            trades.append(
                Trade(
                    config=(
                        f"{ids['prefix']} v{features.get('ver')} {features.get('variant')} "
                        f"tf={ids['timeframe']} {features.get('cfg')} feed={ids['exchange']}"
                    ),
                    ticker=ids["ticker"],
                    side=parsed.direction,
                    setup_id=str(features["setup_id"]),
                    armed_at=armed.strftime("%Y-%m-%d %H:%M"),
                    entry_raw=parsed.entry_at_raw,
                    exit_raw=parsed.exit_at_raw,
                    fill=fill,
                    exit_price=exit_price,
                    stop=stop,
                    target=fill + direction * float(target_r) * actual_risk
                    if target_r is not None and actual_risk > 0
                    else None,
                    risk=risk,
                    r=float(parsed.net_pnl) / (float(parsed.quantity) * risk),
                    entry_slip_r=direction * (fill - float(features["signal_close"])) / planned_risk,
                    overshoot_r=direction * (stop - exit_price) / risk if reason == "stop" else None,
                    exit_reason=reason,
                    hold_min=parsed.duration_minutes,
                    tick=float(features.get("tick") or 0.01),
                )
            )
        for original, count in duplicates.items():
            problems.append(f"{name}: {count} trades duplicate {original}; skipped")
    return trades, problems


def metrics(trades: list[Trade]) -> dict[str, float]:
    ordered = sorted(trades, key=lambda t: (t.exit_raw, t.entry_raw))
    rs = [t.r for t in ordered]
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    by_day: dict[str, float] = defaultdict(float)
    for trade in ordered:
        by_day[trade.day] += trade.r
    equity = peak = drawdown = 0.0
    for r in rs:
        equity += r
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    total = sum(rs)
    loss_total = -sum(losses)
    return {
        "n": len(rs),
        "days": len(by_day),
        "total": total,
        "expectancy": total / len(rs),
        "win_rate": 100 * len(wins) / len(rs),
        "pf": sum(wins) / loss_total if loss_total > 0 else float("inf"),
        "avg_win": statistics.fmean(wins) if wins else 0.0,
        "avg_loss": statistics.fmean(losses) if losses else 0.0,
        "max_dd": drawdown,
        "worst_trade": min(rs),
        "worst_day": min(by_day.values()),
        "without_best_trade": total - max(rs),
        "without_best_day": total - max(by_day.values()),
        "median_hold": statistics.median(t.hold_min for t in ordered),
        "max_hold": max(t.hold_min for t in ordered),
        "stress_1": sum(t.stressed_r(1) for t in ordered),
        "stress_2": sum(t.stressed_r(2) for t in ordered),
    }


def headline(trades: list[Trade]) -> str:
    m = metrics(trades)
    return "\n".join(
        (
            f"trades {m['n']} over {m['days']} sessions | expectancy {m['expectancy']:+.3f}R | "
            f"total {m['total']:+.1f}R | win {m['win_rate']:.1f}% | PF {m['pf']:.2f}",
            f"avg win {m['avg_win']:+.2f}R | avg loss {m['avg_loss']:+.2f}R | max DD {m['max_dd']:.1f}R | "
            f"worst trade {m['worst_trade']:+.2f}R | worst day {m['worst_day']:+.2f}R",
            f"without best trade {m['without_best_trade']:+.1f}R | "
            f"without best day {m['without_best_day']:+.1f}R",
            f"hold median {m['median_hold']:.0f} min, max {m['max_hold']} min",
            f"cost stress: +1 tick/side {m['stress_1']:+.1f}R, +2 ticks/side {m['stress_2']:+.1f}R",
        )
    )


def one_line(trades: list[Trade]) -> str:
    m = metrics(trades)
    return (
        f"n={m['n']:4d} days={m['days']:3d} total={m['total']:+7.1f}R "
        f"exp={m['expectancy']:+.3f}R win={m['win_rate']:5.1f}% pf={m['pf']:5.2f} "
        f"maxDD={m['max_dd']:5.1f}R"
    )


def print_groups(title: str, trades: list[Trade], key) -> None:
    groups: dict[str, list[Trade]] = defaultdict(list)
    for trade in trades:
        groups[key(trade)].append(trade)
    print(f"\n-- by {title}")
    for label in sorted(groups):
        print(f"  {label:10s} {one_line(groups[label])}")


def print_mechanics(trades: list[Trade], config: str) -> None:
    print("\n-- mechanics")
    hold = re.search(r"_hold(\d+)", config)
    timeframe = re.search(r"tf=(\d+)", config)
    if hold and timeframe:
        limit = int(hold.group(1)) + int(timeframe.group(1))
        late = [t for t in trades if t.exit_reason != "session" and t.hold_min > limit]
        print(f"  held past {limit} min (max hold plus one bar): {len(late)}")
        for trade in late[:5]:
            print(f"    {trade.setup_id} held {trade.hold_min} min, exit {trade.exit_reason}")
    entries = re.search(r"_ent(\d+)", config)
    if entries:
        per_day: dict[tuple[str, str], int] = defaultdict(int)
        for trade in trades:
            per_day[(trade.ticker, trade.day)] += 1
        over = sorted(key for key, count in per_day.items() if count > int(entries.group(1)))
        print(f"  sessions over the entry limit: {len(over)} {over[:5] if over else ''}")
    slips = sorted(t.entry_slip_r for t in trades)
    print(f"  entry vs signal close: median {statistics.median(slips):+.3f}R, worst {slips[-1]:+.3f}R")
    overshoots = [t.overshoot_r for t in trades if t.overshoot_r is not None]
    if overshoots:
        big = sum(1 for value in overshoots if value > 0.1)
        print(f"  stop fills past the stop by >0.1R: {big} of {len(overshoots)}, worst {max(overshoots):+.2f}R")
    print(
        "  ambiguous bars (stop and target inside one exit bar) are not in the export: "
        "TradingView's excursions stop at the exit fill. Read the script's Fill check row."
    )


def spread(items: list[Trade], count: int) -> list[Trade]:
    if len(items) <= count:
        return items
    return [items[round(i * (len(items) - 1) / (count - 1))] for i in range(count)] if count > 1 else items[:1]


def print_replay(trades: list[Trade], count: int) -> None:
    ordered = sorted(trades, key=lambda t: t.entry_raw)
    winners = spread([t for t in ordered if t.r > 0], count)
    losers = spread([t for t in ordered if t.r <= 0], count)
    print(f"\n-- replay checklist: {len(winners)} winners, {len(losers)} losers, spread across the run")
    print("   Check each on the chart: armed bar, trigger close, fill at the next open, stop, target, exit.")
    for label, group in (("W", winners), ("L", losers)):
        for t in group:
            target = f"{t.target:.2f}" if t.target is not None else "n/a"
            print(
                f"  {label} {t.ticker:5s} {t.side:5s} armed {t.armed_at} | entry {t.entry_raw} @ {t.fill:.2f} "
                f"| stop {t.stop:.2f} target {target} | exit {t.exit_raw} @ {t.exit_price:.2f} "
                f"{t.exit_reason} | {t.r:+.2f}R"
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("pattern", help='CSV glob, e.g. "TradingView/IR_*.csv"')
    parser.add_argument("--tz", default="America/New_York", help="timezone of the export's timestamps")
    parser.add_argument("--replay", type=int, default=0, help="print N winners and N losers to check by hand")
    args = parser.parse_args()

    paths = sorted(glob.glob(args.pattern))
    trades, problems = load_trades(paths, args.tz)
    for problem in problems:
        print(f"! {problem}")
    if not trades:
        raise SystemExit(f"No usable trades in {args.pattern}")

    by_config: dict[str, list[Trade]] = defaultdict(list)
    for trade in trades:
        by_config[trade.config].append(trade)
    if len(by_config) > 1:
        print(f"{len(by_config)} different configurations: reported separately, never pooled.")
    for config, members in sorted(by_config.items()):
        print(f"\n== {config}  ({len(paths)} files)")
        print(headline(members))
        print_groups("side", members, lambda t: t.side)
        print_groups("ticker", members, lambda t: t.ticker)
        print_groups("month", members, lambda t: t.month)
        print_groups("exit reason", members, lambda t: t.exit_reason)
        print_mechanics(members, config)
        if args.replay:
            print_replay(members, args.replay)


if __name__ == "__main__":
    main()
