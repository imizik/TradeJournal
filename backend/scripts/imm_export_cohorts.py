"""
Cohort report, in R, for Isaac Market Map Strategy Tester exports.

Reads TradingView "List of trades" CSVs exported from
`docs/pine/isaac_market_map.pine`, pairs entry and exit rows, reads the `sl1`
metadata on both, and prints results grouped by ticker, setup, side, grade,
window, exit reason, entry time, relative strength and quarter. R is net PnL
divided by the backtest risk for the trade's size (full = the risk input,
half = half of it), so it assumes the script's default $100 risk input.

Usage:
    python scripts/imm_export_cohorts.py
    python scripts/imm_export_cohorts.py "TradingView/IMM_v1.1.0_*.csv" --risk 100
"""

from __future__ import annotations

import argparse
import csv
import glob
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PATTERN = str(BACKEND_ROOT / "TradingView" / "IMM_v*.csv")


def sl1_fields(signal: str) -> dict[str, str]:
    if not signal.startswith("sl1|"):
        return {}
    return dict(token.split("=", 1) for token in signal.split("|")[1:] if "=" in token)


def load_trades(paths: list[str], risk: float) -> list[dict]:
    trades = []
    for path in paths:
        ticker = Path(path).stem.split("_")[-2]
        groups: dict[str, dict[str, dict]] = defaultdict(dict)
        with open(path, encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                kind = "entry" if row["Type"].startswith("Entry") else "exit"
                groups[row["Trade number"]][kind] = row
        for pair in groups.values():
            if "entry" not in pair or "exit" not in pair:
                continue
            entry, exit_row = pair["entry"], pair["exit"]
            fields = {**sl1_fields(exit_row["Signal"]), **sl1_fields(entry["Signal"])}
            trade_risk = risk if fields.get("size") == "full" else risk / 2
            pnl = float(entry["Net PnL USD"])
            stamp = entry["Date and time"]
            trades.append(
                {
                    **fields,
                    "ticker": ticker,
                    "pnl": pnl,
                    "r": pnl / trade_risk,
                    "stamp": stamp,
                    "hhmm": int(stamp[11:13]) * 100 + int(stamp[14:16]),
                }
            )
    return trades


def summarize(trades: list[dict]) -> str:
    rs = [t["r"] for t in trades]
    wins = [r for r in rs if r > 0]
    loss_total = abs(sum(r for r in rs if r <= 0))
    profit_factor = sum(wins) / loss_total if loss_total else float("inf")
    return (
        f"n={len(rs):4d}  R={sum(rs):7.1f}  avgR={sum(rs) / len(rs):6.3f}  "
        f"win%={100 * len(wins) / len(rs):5.1f}  pf={profit_factor:5.2f}"
    )


def print_groups(title: str, trades: list[dict], key: Callable[[dict], str]) -> None:
    groups: dict[str, list[dict]] = defaultdict(list)
    for trade in trades:
        groups[key(trade)].append(trade)
    print(f"\n== {title}")
    for label, members in sorted(groups.items(), key=lambda item: -sum(t["r"] for t in item[1])):
        print(f"  {label:24s} {summarize(members)}")


def entry_time(trade: dict) -> str:
    for cutoff, label in ((945, "09:35-09:45"), (1015, "09:45-10:15"), (1400, "10:15-14:00")):
        if trade["hhmm"] < cutoff:
            return label
    return "14:00+"


def relative_strength(trade: dict) -> str:
    value = trade.get("rs_vs_spy")
    if value in (None, "null"):
        return "n/a"
    aligned = float(value) * (1 if trade.get("side") == "long" else -1)
    for cutoff in (0.0, 1.5, 3.0):
        if aligned < cutoff:
            return f"< {cutoff}%"
    return ">= 3.0%"


def quarter(trade: dict) -> str:
    return f"{trade['stamp'][:4]}Q{(int(trade['stamp'][5:7]) - 1) // 3 + 1}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("pattern", nargs="?", default=DEFAULT_PATTERN)
    parser.add_argument("--risk", type=float, default=100.0)
    args = parser.parse_args()

    paths = sorted(glob.glob(args.pattern))
    trades = load_trades(paths, args.risk)
    if not trades:
        raise SystemExit(f"No paired trades found in {args.pattern}")
    print(f"{len(paths)} exports, ALL {summarize(trades)}")
    print_groups("Ticker", trades, lambda t: t["ticker"])
    print_groups("Setup and side", trades, lambda t: f"{t.get('setup')} {t.get('side')}")
    print_groups("Grade and size", trades, lambda t: f"{t.get('grade')} {t.get('size')}")
    print_groups("Window", trades, lambda t: t.get("window", "?"))
    print_groups("Exit reason", trades, lambda t: t.get("exit_reason", "?"))
    print_groups("Entry time", trades, entry_time)
    print_groups("Relative strength on the trade's side", trades, relative_strength)
    print_groups("Quarter", trades, quarter)


if __name__ == "__main__":
    main()
