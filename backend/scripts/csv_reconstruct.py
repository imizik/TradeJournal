"""
CSV Ground-Truth FIFO Reconstruction.

Parses the Robinhood CSV, converts rows to FillInput objects,
runs the same FIFO reconstructor used by the app, and produces
"gold standard" PnL to compare against the DB.

Usage:
    python scripts/csv_reconstruct.py                  # options only
    python scripts/csv_reconstruct.py --include-stocks  # options + stocks
    python scripts/csv_reconstruct.py --compare         # compare with DB
"""

from __future__ import annotations

import argparse
import csv
import re
import sqlite3
import sys
import uuid
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.engine.reconstructor import FillInput, ReconstructResult, reconstruct  # noqa: E402

DB_PATH = BACKEND_ROOT / "data" / "trade_journal.db"
CSV_PATH = BACKEND_ROOT / "Robinhood" / "ROTH jul2023 to april 2026.csv"

SYNTHETIC_ACCOUNT_ID = uuid.uuid5(uuid.NAMESPACE_URL, "roth-ira-8267")

SIDE_MAP = {
    "BTO": "buy_to_open",
    "STC": "sell_to_close",
    "Buy": "buy",
    "Sell": "sell",
}

OPT_DESC_RE = re.compile(
    r"^(\S+)\s+(\d{1,2}/\d{1,2}/\d{4})\s+(Call|Put)\s+\$([\d,]+\.?\d*)$",
    re.IGNORECASE,
)

AMOUNT_RE = re.compile(r"[\d,]+\.?\d*")


def parse_csv_fills(
    csv_path: Path,
    include_stocks: bool = False,
    min_date: date | None = None,
) -> list[FillInput]:
    fills: list[FillInput] = []

    with csv_path.open(newline="", encoding="utf-8-sig") as f:
        for idx, row in enumerate(csv.DictReader(f)):
            tc = (row.get("Trans Code") or "").strip()
            if tc not in SIDE_MAP:
                continue

            activity_date_str = (row.get("Activity Date") or "").strip()
            if not activity_date_str:
                continue

            activity_date = datetime.strptime(activity_date_str, "%m/%d/%Y").date()
            if min_date and activity_date < min_date:
                continue

            side = SIDE_MAP[tc]
            qty_str = (row.get("Quantity") or "0").strip()
            qty = Decimal(qty_str.replace(",", ""))
            price_str = (row.get("Price") or "0").strip().lstrip("$").replace(",", "")
            price_per_share = Decimal(price_str)

            if tc in ("BTO", "STC"):
                desc = (row.get("Description") or "").replace("\n", " ").strip()
                m = OPT_DESC_RE.match(desc)
                if not m:
                    continue
                ticker = m.group(1).upper()
                exp = datetime.strptime(m.group(2), "%m/%d/%Y").date()
                option_type = m.group(3).lower()
                strike = Decimal(m.group(4).replace(",", ""))
                price = price_per_share * 100  # per-share -> per-contract

                fills.append(FillInput(
                    id=uuid.uuid5(uuid.NAMESPACE_URL, f"csv-opt-{idx}"),
                    account_id=SYNTHETIC_ACCOUNT_ID,
                    ticker=ticker,
                    instrument_type="option",
                    side=side,
                    contracts=qty,
                    price=price,
                    executed_at=datetime(activity_date.year, activity_date.month, activity_date.day, 12, 0),
                    option_type=option_type,
                    strike=strike,
                    expiration=exp,
                ))
            elif include_stocks and tc in ("Buy", "Sell"):
                ticker = (row.get("Instrument") or "").strip().upper()
                if not ticker:
                    continue
                fills.append(FillInput(
                    id=uuid.uuid5(uuid.NAMESPACE_URL, f"csv-stk-{idx}"),
                    account_id=SYNTHETIC_ACCOUNT_ID,
                    ticker=ticker,
                    instrument_type="stock",
                    side=side,
                    contracts=qty,
                    price=price_per_share,
                    executed_at=datetime(activity_date.year, activity_date.month, activity_date.day, 12, 0),
                ))

    return fills


def load_db_fills(
    instrument_type: str | None = None,
    min_date: date | None = None,
) -> list[FillInput]:
    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    query = """
        SELECT f.id, f.account_id, f.ticker, f.instrument_type, f.side,
               f.contracts, f.price, f.executed_at,
               f.option_type, f.strike, f.expiration
        FROM fill f
        JOIN account a ON f.account_id = a.id
        WHERE a.type = 'roth_ira'
    """
    params: list = []
    if instrument_type:
        query += " AND f.instrument_type = ?"
        params.append(instrument_type)
    if min_date:
        query += " AND date(f.executed_at) >= ?"
        params.append(min_date.isoformat())
    query += " ORDER BY f.executed_at"

    fills: list[FillInput] = []
    for row in con.execute(query, params).fetchall():
        fills.append(FillInput(
            id=uuid.UUID(row["id"]),
            account_id=uuid.UUID(row["account_id"]),
            ticker=row["ticker"],
            instrument_type=row["instrument_type"],
            side=row["side"],
            contracts=Decimal(str(row["contracts"])),
            price=Decimal(str(row["price"])),
            executed_at=datetime.fromisoformat(row["executed_at"]),
            option_type=row["option_type"],
            strike=Decimal(str(row["strike"])) if row["strike"] is not None else None,
            expiration=date.fromisoformat(row["expiration"]) if row["expiration"] else None,
        ))
    con.close()
    return fills


def print_result(label: str, result: ReconstructResult) -> dict:
    closed = [t for t in result.trades if t.status == "closed"]
    expired = [t for t in result.trades if t.status == "expired"]
    open_trades = [t for t in result.trades if t.status == "open"]

    closed_pnl = sum(float(t.realized_pnl) for t in closed if t.realized_pnl is not None)
    expired_pnl = sum(float(t.realized_pnl) for t in expired if t.realized_pnl is not None)
    total_pnl = closed_pnl + expired_pnl

    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    print(f"  Closed trades:  {len(closed):>6}   PnL: ${closed_pnl:>+12,.2f}")
    print(f"  Expired trades: {len(expired):>6}   PnL: ${expired_pnl:>+12,.2f}")
    print(f"  Open trades:    {len(open_trades):>6}")
    print(f"  {'':>24}  --------------------")
    print(f"  TOTAL PnL:              ${total_pnl:>+12,.2f}")
    print(f"  Anomalies:      {len(result.anomalies):>6}")

    if result.anomalies:
        print(f"\n  Anomalies:")
        for a in result.anomalies[:15]:
            print(f"    - {a[:100]}")
        if len(result.anomalies) > 15:
            print(f"    ... and {len(result.anomalies) - 15} more")

    # Monthly breakdown
    monthly: dict[str, float] = defaultdict(float)
    for t in closed + expired:
        if t.closed_at and t.realized_pnl is not None:
            ym = t.closed_at.strftime("%Y-%m")
            monthly[ym] += float(t.realized_pnl)

    if monthly:
        print(f"\n  Monthly PnL:")
        for ym in sorted(monthly):
            print(f"    {ym}: ${monthly[ym]:>+10,.2f}")

    return {"closed_pnl": closed_pnl, "expired_pnl": expired_pnl, "total_pnl": total_pnl,
            "closed": len(closed), "expired": len(expired), "open": len(open_trades),
            "anomalies": len(result.anomalies)}


def compare_trades(csv_result: ReconstructResult, db_result: ReconstructResult):
    """Compare CSV vs DB trades by contract key."""
    ContractKey = tuple

    def trade_key(t):
        return (t.ticker, t.instrument_type, t.option_type, t.strike, t.expiration)

    # Group trades by contract key, summing PnL
    def group_by_key(trades):
        grouped: dict[ContractKey, dict] = defaultdict(
            lambda: {"pnl": 0.0, "count": 0, "statuses": []}
        )
        for t in trades:
            k = trade_key(t)
            if t.realized_pnl is not None:
                grouped[k]["pnl"] += float(t.realized_pnl)
            grouped[k]["count"] += 1
            grouped[k]["statuses"].append(t.status)
        return grouped

    csv_grouped = group_by_key([t for t in csv_result.trades if t.status != "open"])
    db_grouped = group_by_key([t for t in db_result.trades if t.status != "open"])

    all_keys = sorted(set(csv_grouped) | set(db_grouped), key=str)

    diffs = []
    for k in all_keys:
        csv_data = csv_grouped.get(k, {"pnl": 0.0, "count": 0, "statuses": []})
        db_data = db_grouped.get(k, {"pnl": 0.0, "count": 0, "statuses": []})
        pnl_diff = db_data["pnl"] - csv_data["pnl"]
        if abs(pnl_diff) > 1.0 or csv_data["count"] != db_data["count"]:
            diffs.append({
                "key": k,
                "csv_pnl": csv_data["pnl"],
                "db_pnl": db_data["pnl"],
                "diff": pnl_diff,
                "csv_trades": csv_data["count"],
                "db_trades": db_data["count"],
                "csv_statuses": csv_data["statuses"],
                "db_statuses": db_data["statuses"],
            })

    diffs.sort(key=lambda d: abs(d["diff"]), reverse=True)

    print(f"\n{'='*60}")
    print(f"  CSV vs DB COMPARISON")
    print(f"{'='*60}")
    print(f"  Contract keys compared: {len(all_keys)}")
    print(f"  Keys with PnL diff > $1 or trade count mismatch: {len(diffs)}")

    if diffs:
        print(f"\n  {'Ticker':<6} {'Type':<5} {'Strike':>8} {'Exp':<12} {'CSV PnL':>10} {'DB PnL':>10} {'Diff':>10} {'CSV#':>4} {'DB#':>4}")
        print(f"  {'-'*75}")
        total_diff = 0.0
        for d in diffs[:30]:
            k = d["key"]
            ticker, inst, opt_type, strike, exp = k
            strike_s = f"{float(strike):.0f}" if strike else "-"
            exp_s = str(exp) if exp else "-"
            opt_s = opt_type or "-"
            print(f"  {ticker:<6} {opt_s:<5} {strike_s:>8} {exp_s:<12} "
                  f"${d['csv_pnl']:>+9,.2f} ${d['db_pnl']:>+9,.2f} ${d['diff']:>+9,.2f} "
                  f"{d['csv_trades']:>4} {d['db_trades']:>4}")
            total_diff += d["diff"]
        if len(diffs) > 30:
            remaining_diff = sum(d["diff"] for d in diffs[30:])
            print(f"  ... and {len(diffs) - 30} more (remaining diff: ${remaining_diff:>+,.2f})")
            total_diff += remaining_diff
        print(f"  {'-'*75}")
        print(f"  Total discrepancy: ${total_diff:>+,.2f}")


def main():
    parser = argparse.ArgumentParser(description="CSV ground-truth FIFO reconstruction")
    parser.add_argument("--include-stocks", action="store_true", help="Include stock trades")
    parser.add_argument("--compare", action="store_true", help="Compare with DB trades")
    parser.add_argument("--min-date", type=str, default="2025-07-01",
                        help="Min date filter (YYYY-MM-DD). Default: 2025-07-01")
    args = parser.parse_args()

    min_dt = date.fromisoformat(args.min_date)

    # Parse CSV and reconstruct
    csv_fills = parse_csv_fills(CSV_PATH, include_stocks=args.include_stocks, min_date=min_dt)
    print(f"CSV fills parsed: {len(csv_fills)} (min_date={min_dt})")

    opt_fills = [f for f in csv_fills if f.instrument_type == "option"]
    stk_fills = [f for f in csv_fills if f.instrument_type == "stock"]
    print(f"  Options: {len(opt_fills)}, Stocks: {len(stk_fills)}")

    csv_result = reconstruct(csv_fills)
    csv_stats = print_result("CSV GROUND TRUTH (Robinhood CSV -> FIFO)", csv_result)

    # Options-only view
    if args.include_stocks:
        csv_opt_result = reconstruct(opt_fills)
        print_result("CSV OPTIONS ONLY", csv_opt_result)

    if args.compare:
        # Load DB fills and reconstruct independently
        inst_type = None if args.include_stocks else "option"
        db_fills = load_db_fills(instrument_type=inst_type, min_date=min_dt)
        print(f"\nDB fills loaded: {len(db_fills)}")

        # Use a single account_id for DB fills too (to match CSV)
        for f in db_fills:
            f.account_id = SYNTHETIC_ACCOUNT_ID

        db_result = reconstruct(db_fills)
        db_stats = print_result("DB RECONSTRUCTION (DB fills -> FIFO)", db_result)

        compare_trades(csv_result, db_result)

        # Summary
        gap = db_stats["total_pnl"] - csv_stats["total_pnl"]
        print(f"\n{'='*60}")
        print(f"  SUMMARY")
        print(f"{'='*60}")
        print(f"  CSV ground truth PnL:  ${csv_stats['total_pnl']:>+12,.2f}")
        print(f"  DB reconstructed PnL:  ${db_stats['total_pnl']:>+12,.2f}")
        print(f"  Gap (DB - CSV):        ${gap:>+12,.2f}")
        print(f"  (Positive gap = DB overstates, negative = DB understates)")


if __name__ == "__main__":
    main()
