"""
Cross-reference CSV (source of truth) with DB fills for Roth IRA.
Run from backend/ directory.
"""

import csv
import re
import sqlite3
from collections import defaultdict
from datetime import date, datetime

# ── Parse CSV ─────────────────────────────────────────────────────────────────
# Description format: "SPY 4/17/2026 Put $709.00"
DESC_RE = re.compile(
    r"^(\S+)\s+(\d{1,2}/\d{1,2}/\d{4})\s+(Call|Put)\s+\$([\d,]+\.?\d*)$",
    re.IGNORECASE,
)
AMOUNT_NUM_RE = re.compile(r"[\d,]+\.?\d*")

SIDE_MAP = {
    "BTO": "buy_to_open",
    "STC": "sell_to_close",
    "BTC": "buy_to_close",
    "STO": "sell_to_open",
}

csv_fills = []
unparseable = []
with open("Robinhood/ROTH jul2023 to april 2026.csv", newline="", encoding="utf-8") as f:
    for r in csv.DictReader(f):
        tc = (r.get("Trans Code") or "").strip()
        if tc not in SIDE_MAP:
            continue
        desc = (r.get("Description") or "").replace("\n", " ").strip()
        m = DESC_RE.match(desc)
        if not m:
            unparseable.append((tc, desc))
            continue
        ticker, exp_str, opt_type, strike_str = m.group(1), m.group(2), m.group(3), m.group(4)
        exp = datetime.strptime(exp_str, "%m/%d/%Y").date()
        strike = float(strike_str.replace(",", ""))
        act_date = datetime.strptime(r["Activity Date"].strip(), "%m/%d/%Y").date()
        qty = int(r["Quantity"].strip())
        price_str = r["Price"].strip().lstrip("$").replace(",", "")
        price_per_share = float(price_str)
        price_per_contract = round(price_per_share * 100, 2)
        amount_str = r["Amount"].strip()
        neg = amount_str.startswith("(")
        amount_num_m = AMOUNT_NUM_RE.search(amount_str.replace(",", ""))
        amount = -float(amount_num_m.group()) if neg else float(amount_num_m.group())
        csv_fills.append({
            "date": act_date,
            "ticker": ticker.upper(),
            "option_type": opt_type.lower(),
            "strike": strike,
            "expiration": exp,
            "contracts": qty,
            "side": SIDE_MAP[tc],
            "price_per_contract": price_per_contract,
            "amount": amount,
            "tc": tc,
        })

print(f"Parsed {len(csv_fills)} option CSV rows")
if unparseable:
    print(f"  Could not parse {len(unparseable)} option rows:")
    for tc, desc in unparseable[:10]:
        print(f"    [{tc}] {repr(desc)}")

# ── Load DB fills (Roth IRA only) ─────────────────────────────────────────────
conn = sqlite3.connect("data/trade_journal.db")
cur = conn.cursor()
cur.execute("""
    SELECT f.id, f.ticker, f.option_type, f.strike, f.expiration,
           f.contracts, f.side, f.price, f.executed_at
    FROM fill f
    JOIN account a ON f.account_id = a.id
    WHERE a.type = 'roth_ira' AND f.instrument_type = 'option'
    ORDER BY f.executed_at
""")
db_fills = []
for row in cur.fetchall():
    fid, ticker, opt_type, strike, exp_str, contracts, side, price, executed_at = row
    exp = date.fromisoformat(exp_str) if exp_str else None
    exec_date = datetime.fromisoformat(executed_at).date() if executed_at else None
    db_fills.append({
        "id": fid,
        "date": exec_date,
        "ticker": ticker,
        "option_type": opt_type,
        "strike": float(strike) if strike else None,
        "expiration": exp,
        "contracts": int(contracts),
        "side": side,
        "price": float(price),
    })
conn.close()

print(f"\nDB option fills (Roth):  {len(db_fills)}")
print(f"CSV option fills:        {len(csv_fills)}")
print(f"Difference:              {len(csv_fills) - len(db_fills)}")


# ── Match fills: group by (date, ticker, opt_type, strike, expiration, contracts, side) ──
def make_key(d):
    return (d["date"], d["ticker"], d["option_type"], d["strike"], d["expiration"], d["contracts"], d["side"])


# Build a multiset from CSV
csv_multiset = defaultdict(list)
for f in csv_fills:
    csv_multiset[make_key(f)].append(f)

# Build a multiset from DB
db_multiset = defaultdict(list)
for f in db_fills:
    db_multiset[make_key(f)].append(f)

all_keys = set(csv_multiset) | set(db_multiset)

in_csv_not_db = []   # fills in CSV but missing from DB
in_db_not_csv = []   # fills in DB but not in CSV (phantom)
price_mismatches = []

for key in sorted(all_keys):
    csv_count = len(csv_multiset[key])
    db_count = len(db_multiset[key])
    if csv_count > db_count:
        for _ in range(csv_count - db_count):
            in_csv_not_db.append(csv_multiset[key][0])
    elif db_count > csv_count:
        for _ in range(db_count - csv_count):
            in_db_not_csv.append(db_multiset[key][0])

# Price mismatches (where both exist)
for key in all_keys:
    if csv_multiset[key] and db_multiset[key]:
        for cf, df in zip(csv_multiset[key], db_multiset[key]):
            expected = cf["price_per_contract"]
            actual = df["price"]
            if abs(expected - actual) > 0.05:  # >5 cent tolerance
                price_mismatches.append({
                    "key": key,
                    "csv_price_per_contract": expected,
                    "db_price": actual,
                    "diff": actual - expected,
                })

print(f"\n=== MISSING FROM DB (in CSV but not found in DB): {len(in_csv_not_db)} ===")
for f in in_csv_not_db[:30]:
    print(f"  {f['date']} {f['ticker']:6s} {f['option_type']:4s} {f['tc']:3s} "
          f"${f['strike']:8.2f} exp={f['expiration']} qty={f['contracts']:3d} "
          f"price=${f['price_per_contract']:.2f}/contract")

print(f"\n=== PHANTOM IN DB (not in CSV): {len(in_db_not_csv)} ===")
for f in in_db_not_csv[:30]:
    print(f"  {f['date']} {f['ticker']:6s} {f['option_type']:4s} {f['side']:14s} "
          f"${f['strike']:8.2f} exp={f['expiration']} qty={f['contracts']:3d} "
          f"price=${f['price']:.2f}/contract")

print(f"\n=== PRICE MISMATCHES (>$0.05/contract): {len(price_mismatches)} ===")
for p in price_mismatches[:30]:
    d, tkr, ot, strike, exp, qty, side = p["key"]
    print(f"  {d} {tkr:6s} {ot:4s} {side:14s} ${strike:8.2f} exp={exp} qty={qty:3d} "
          f"csv=${p['csv_price_per_contract']:.2f} db=${p['db_price']:.2f} diff={p['diff']:+.2f}")

# ── PnL reconciliation ────────────────────────────────────────────────────────
csv_total_amount = sum(f["amount"] for f in csv_fills)
# DB PnL from trades
conn = sqlite3.connect("data/trade_journal.db")
cur = conn.cursor()
cur.execute("""
    SELECT COALESCE(SUM(t.realized_pnl), 0)
    FROM trade t
    JOIN account a ON t.account_id = a.id
    WHERE a.type = 'roth_ira' AND t.status != 'open' AND t.instrument_type = 'option'
""")
db_total_pnl = cur.fetchone()[0]

cur.execute("""
    SELECT COALESCE(SUM(t.total_premium_paid), 0)
    FROM trade t
    JOIN account a ON t.account_id = a.id
    WHERE a.type = 'roth_ira' AND t.status = 'open' AND t.instrument_type = 'option'
""")
db_open_cost = cur.fetchone()[0]
conn.close()

print(f"\n=== PnL RECONCILIATION ===")
print(f"CSV net cash flow (all closed fills): ${csv_total_amount:+.2f}")
print(f"  (negative = net cash out, positive = net cash in, excluding open positions)")
print(f"DB realized PnL (closed + expired options, Roth): ${db_total_pnl:+.2f}")
print(f"DB open position cost basis: ${db_open_cost:.2f}")
