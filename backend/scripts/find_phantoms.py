"""Identify phantom fills by comparing DB quantities against CSV for known groups.

Phantom fills are cumulative partial-fill emails that duplicate the complete fill.
They share the same (or very close) timestamp and price as a larger fill.
"""
import csv
import re
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = BACKEND_ROOT / "data" / "trade_journal.db"
CSV_PATH = BACKEND_ROOT / "Robinhood" / "ROTH jul2023 to april 2026.csv"

DESC_RE = re.compile(
    r"^(\S+)\s+(\d{1,2}/\d{1,2}/\d{4})\s+(Call|Put)\s+\$([\d,]+\.?\d*)$",
    re.IGNORECASE,
)
SIDE_MAP = {"BTO": "buy_to_open", "STC": "sell_to_close"}

# Parse CSV
csv_groups = defaultdict(int)
with CSV_PATH.open(newline="", encoding="utf-8-sig") as f:
    for r in csv.DictReader(f):
        tc = (r.get("Trans Code") or "").strip()
        if tc not in SIDE_MAP:
            continue
        desc = (r.get("Description") or "").replace("\n", " ").strip()
        m = DESC_RE.match(desc)
        if not m:
            continue
        ticker = m.group(1).upper()
        exp = datetime.strptime(m.group(2), "%m/%d/%Y").date().isoformat()
        opt_type = m.group(3).lower()
        strike = float(m.group(4).replace(",", ""))
        side = SIDE_MAP[tc]
        qty = int(r["Quantity"].strip())
        csv_groups[(ticker, opt_type, strike, exp, side)] += qty

# Check phantom groups
conn = sqlite3.connect(str(DB_PATH))
cur = conn.cursor()

phantom_specs = [
    ("COIN", "put", 375.0, "2025-07-25", "sell_to_close"),
    ("WMT", "put", 102.0, "2025-09-19", "buy_to_open"),
    ("GOOG", "call", 255.0, "2025-10-17", "buy_to_open"),
    ("LMND", "put", 68.0, "2025-11-07", "sell_to_close"),
    ("AMD", "put", 200.0, "2026-02-20", "buy_to_open"),
    ("SPY", "put", 710.0, "2026-04-17", "sell_to_close"),
]

fills_to_delete = []
print("=== PHANTOM FILL ANALYSIS ===\n")

for ticker, opt_type, strike, exp, side in phantom_specs:
    key = (ticker, opt_type, strike, exp, side)
    csv_qty = csv_groups.get(key, 0)

    cur.execute(
        """
        SELECT id, contracts, price, executed_at
        FROM fill
        WHERE ticker=? AND option_type=? AND strike=? AND expiration=? AND side=?
        ORDER BY executed_at, contracts
        """,
        (ticker, opt_type, strike, exp, side),
    )
    db_fills = cur.fetchall()
    db_qty = sum(int(r[1]) for r in db_fills)
    extra = db_qty - csv_qty

    print(f"{ticker} {opt_type} {side} exp={exp} strike={strike}")
    print(f"  CSV qty={csv_qty}, DB qty={db_qty}, extra={extra:+d}")

    # Parse timestamps for proximity check
    fill_data = []
    for fid, qty, price, exec_at in db_fills:
        dt = datetime.fromisoformat(exec_at)
        fill_data.append({"id": fid, "qty": int(qty), "price": price, "dt": dt})
        print(f"    {fid}  qty={int(qty):>3} price={price:>6} at={exec_at[:19]}")

    if extra <= 0:
        print()
        continue

    # Identify phantoms: fills that share timestamp (within 2 min) and price
    # with a LARGER fill in the same group. The smaller one is the cumulative partial.
    remaining_to_remove = extra
    candidates_for_deletion = []

    for i, f in enumerate(fill_data):
        for j, other in enumerate(fill_data):
            if i == j:
                continue
            same_price = f["price"] == other["price"]
            close_time = abs((f["dt"] - other["dt"]).total_seconds()) <= 120
            if same_price and close_time and f["qty"] < other["qty"]:
                # f is a cumulative partial of other
                candidates_for_deletion.append(f)
                break

    # Sort candidates by qty ascending, delete enough to remove 'extra'
    candidates_for_deletion.sort(key=lambda x: x["qty"])
    for cand in candidates_for_deletion:
        if remaining_to_remove <= 0:
            break
        if cand["qty"] <= remaining_to_remove:
            fills_to_delete.append((cand["id"], ticker, cand["qty"], side))
            remaining_to_remove -= cand["qty"]
            print(f"    >>> DELETE {cand['id']} (qty={cand['qty']}) -- phantom partial")

    if remaining_to_remove > 0:
        print(f"    !!! WARNING: still {remaining_to_remove} extra after deleting identified phantoms")
    print()

print(f"\n=== SUMMARY ===")
print(f"Fills to delete: {len(fills_to_delete)}")
total_phantom_contracts = sum(qty for _, _, qty, _ in fills_to_delete)
print(f"Total phantom contracts to remove: {total_phantom_contracts}")
print(f"\nFill IDs for deletion:")
for fid, ticker, qty, side in fills_to_delete:
    print(f"  {fid}  ({ticker} {side} qty={qty})")

conn.close()
