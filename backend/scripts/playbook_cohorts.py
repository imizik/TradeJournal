"""
Cohort evidence behind the Isaac Market Map playbook.

Rebuilds option trades from a Robinhood activity CSV with the app's FIFO
reconstructor and prints the cohorts `docs/pine/README.md` cites: DTE, hold
length, ticker, ticker and side, premium size, and how positions were added
to. The CSV has dates but no times, so time-of-day cohorts come from
`backend/reports/edge_audit_2026-07-07.md`, not from here.

Ticker cohorts are in-sample: a ticker list picked from this output and then
scored on the same output will always look good.

Usage:
    python scripts/playbook_cohorts.py
    python scripts/playbook_cohorts.py --csv path/to/export.csv --min-n 5
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from collections.abc import Callable, Iterable
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))
sys.path.insert(0, str(BACKEND_ROOT / "scripts"))

from app.engine.reconstructor import TradeOutput, reconstruct  # noqa: E402
from csv_reconstruct import parse_csv_fills  # noqa: E402

DEFAULT_CSV = BACKEND_ROOT / "reports" / "1f4613d0-7593-50f0-a265-8171ec59973d.csv"
AVERAGE_DOWN_THRESHOLD = 0.97


def summarize(trades: Iterable[TradeOutput]) -> str:
    pnls = [float(t.realized_pnl) for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    loss_total = abs(sum(losses))
    profit_factor = sum(wins) / loss_total if loss_total else float("inf")
    win_rate = 100 * len(wins) / len(pnls) if pnls else 0.0
    return (
        f"n={len(pnls):4d}  total={sum(pnls):9.0f}  win%={win_rate:5.1f}  "
        f"pf={profit_factor:5.2f}"
    )


def print_cohorts(
    title: str,
    trades: list[TradeOutput],
    key: Callable[[TradeOutput], str],
    min_n: int,
) -> None:
    groups: dict[str, list[TradeOutput]] = defaultdict(list)
    for trade in trades:
        groups[key(trade)].append(trade)
    ranked = sorted(
        groups.items(),
        key=lambda item: sum(float(t.realized_pnl) for t in item[1]),
        reverse=True,
    )
    print(f"\n== {title}")
    for label, members in ranked:
        if len(members) >= min_n:
            print(f"  {label:26s} {summarize(members)}")


def dte_bucket(trade: TradeOutput) -> str:
    if trade.expiration is None:
        return "unknown"
    days = (trade.expiration - trade.opened_at.date()).days
    if days == 0:
        return "0"
    if days <= 3:
        return "1-3"
    if days <= 7:
        return "4-7"
    if days <= 21:
        return "8-21"
    return "22+"


def hold_bucket(trade: TradeOutput) -> str:
    if trade.closed_at is None:
        return "open"
    days = (trade.closed_at.date() - trade.opened_at.date()).days
    if days == 0:
        return "same day"
    if days == 1:
        return "next day"
    if days <= 3:
        return "2-3 days"
    return "4+ days"


def premium_bucket(trade: TradeOutput) -> str:
    paid = float(trade.total_premium_paid)
    for ceiling, label in ((100, "<100"), (300, "100-300"), (700, "300-700"), (1500, "700-1500")):
        if paid < ceiling:
            return label
    return "1500+"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--min-n", type=int, default=10)
    args = parser.parse_args()

    fills = parse_csv_fills(args.csv)
    fills_by_id = {fill.id: fill for fill in fills}
    result = reconstruct(fills)
    trades = [t for t in result.trades if t.realized_pnl is not None]

    entry_fills: dict[object, list] = defaultdict(list)
    for link in result.trade_fills:
        if link.role == "entry":
            entry_fills[link.trade_id].append(fills_by_id[link.fill_id])

    def entry_pattern(trade: TradeOutput) -> str:
        entries = sorted(entry_fills[trade.id], key=lambda f: (f.executed_at, str(f.id)))
        if len(entries) <= 1:
            return "single entry"
        first_price = float(entries[0].price)
        if min(float(f.price) for f in entries[1:]) < first_price * AVERAGE_DOWN_THRESHOLD:
            return "added lower (avg down)"
        return "added higher or flat"

    print(f"{args.csv.name}: {len(fills)} option fills, {len(trades)} closed trades")
    print(f"ALL {summarize(trades)}")
    print_cohorts("DTE at entry", trades, dte_bucket, 1)
    print_cohorts("Hold length (calendar days)", trades, hold_bucket, 1)
    print_cohorts("Entry pattern", trades, entry_pattern, 1)
    print_cohorts("Premium paid", trades, premium_bucket, 1)
    print_cohorts("Option type", trades, lambda t: t.option_type or "unknown", 1)
    print_cohorts("Ticker (in-sample)", trades, lambda t: t.ticker, args.min_n)
    print_cohorts(
        "Ticker and side (in-sample)",
        trades,
        lambda t: f"{t.ticker} {t.option_type or ''}".strip(),
        args.min_n,
    )


if __name__ == "__main__":
    main()
