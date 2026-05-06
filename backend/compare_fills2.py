"""
Deeper analysis of CSV vs DB discrepancy.
"""
import csv
import re
import sqlite3
from collections import defaultdict
from datetime import date, datetime

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

# ── Load all CSV rows ─────────────────────────────────────────────────────────
csv_option_rows = []
csv_oexp_rows = []
with open("Robinhood/ROTH jul2023 to april 2026.csv", newline="", encoding="utf-8") as f:
    for r in csv.DictReader(f):
        tc = (r.get("Trans Code") or "").strip()
        desc = (r.get("Description") or "").replace("\n", " ").strip()
        act_date = None
        try:
            act_date = datetime.strptime(r["Activity Date"].strip(), "%m/%d/%Y").date()
        except Exception:
            continue

        if tc == "OEXP":
            csv_oexp_rows.append({"date": act_date, "desc": desc, "raw": r})
            continue

        if tc not in SIDE_MAP:
            continue
        m = DESC_RE.match(desc)
        if not m:
            continue
        ticker, exp_str, opt_type, strike_str = m.group(1), m.group(2), m.group(3), m.group(4)
        exp = datetime.strptime(exp_str, "%m/%d/%Y").date()
        strike = float(strike_str.replace(",", ""))
        qty = int(r["Quantity"].strip())
        price_str = r["Price"].strip().lstrip("$").replace(",", "")
        price_per_contract = round(float(price_str) * 100, 2)
        amount_str = r["Amount"].strip()
        neg = amount_str.startswith("(")
        amount_num_m = AMOUNT_NUM_RE.search(amount_str.replace(",", ""))
        amount = -float(amount_num_m.group()) if neg else float(amount_num_m.group())
        csv_option_rows.append({
            "date": act_date, "ticker": ticker.upper(), "option_type": opt_type.lower(),
            "strike": strike, "expiration": exp, "contracts": qty,
            "side": SIDE_MAP[tc], "price_per_contract": price_per_contract,
            "amount": amount, "tc": tc,
        })

# ── Consolidate CSV fills to match email-level granularity ────────────────────
# Group CSV rows by (date, ticker, opt_type, strike, expiration, side) and sum qty
# This mimics how an email would report the order: total qty at avg price
csv_consolidated = defaultdict(lambda: {"contracts": 0, "total_value": 0.0, "rows": []})
for r in csv_option_rows:
    key = (r["date"], r["ticker"], r["option_type"], r["strike"], r["expiration"], r["side"])
    g = csv_consolidated[key]
    g["contracts"] += r["contracts"]
    g["total_value"] += r["price_per_contract"] * r["contracts"]
    g["rows"].append(r)

print(f"CSV option rows (raw):       {len(csv_option_rows)}")
print(f"CSV after consolidation:     {len(csv_consolidated)}")
print(f"OEXP (expired worthless):    {len(csv_oexp_rows)}")

# ── Load DB fills ─────────────────────────────────────────────────────────────
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
        "id": fid, "date": exec_date, "ticker": ticker,
        "option_type": opt_type, "strike": float(strike) if strike else None,
        "expiration": exp, "contracts": int(contracts),
        "side": side, "price": float(price),
    })

# DB also as consolidated
db_consolidated = defaultdict(lambda: {"contracts": 0, "total_value": 0.0, "rows": []})
for r in db_fills:
    key = (r["date"], r["ticker"], r["option_type"], r["strike"], r["expiration"], r["side"])
    g = db_consolidated[key]
    g["contracts"] += r["contracts"]
    g["total_value"] += r["price"] * r["contracts"]
    g["rows"].append(r)

print(f"\nDB option fills (raw):       {len(db_fills)}")
print(f"DB after consolidation:      {len(db_consolidated)}")

# ── Compare consolidated ──────────────────────────────────────────────────────
all_keys = set(csv_consolidated) | set(db_consolidated)
missing_from_db = []   # consolidated key in CSV but not DB
phantom_in_db = []     # consolidated key in DB but not CSV
contract_mismatch = []
price_mismatch = []

for key in sorted(all_keys):
    in_csv = key in csv_consolidated
    in_db = key in db_consolidated
    if in_csv and not in_db:
        missing_from_db.append((key, csv_consolidated[key]))
    elif in_db and not in_csv:
        phantom_in_db.append((key, db_consolidated[key]))
    else:
        cg = csv_consolidated[key]
        dg = db_consolidated[key]
        csv_qty = cg["contracts"]
        db_qty = dg["contracts"]
        csv_avg = cg["total_value"] / csv_qty if csv_qty else 0
        db_avg = dg["total_value"] / db_qty if db_qty else 0
        if csv_qty != db_qty:
            contract_mismatch.append((key, csv_qty, db_qty, csv_avg, db_avg))
        elif abs(csv_avg - db_avg) > 1.0:  # >$1/contract tolerance
            price_mismatch.append((key, csv_qty, csv_avg, db_avg))

print(f"\n=== AFTER CONSOLIDATION ===")
print(f"Keys only in CSV (truly missing from DB):     {len(missing_from_db)}")
print(f"Keys only in DB  (phantom fills, not in CSV): {len(phantom_in_db)}")
print(f"Keys in both but contract qty mismatch:       {len(contract_mismatch)}")
print(f"Keys in both but avg price mismatch >$1:      {len(price_mismatch)}")

if missing_from_db:
    print(f"\n--- MISSING FROM DB (first 20) ---")
    for (dt, tkr, ot, strike, exp, side), g in missing_from_db[:20]:
        avg = g["total_value"] / g["contracts"] if g["contracts"] else 0
        print(f"  {dt} {tkr:6s} {ot:4s} {side:14s} ${strike:8.2f} exp={exp} qty={g['contracts']:3d} avg=${avg:.2f}/contract")

if phantom_in_db:
    print(f"\n--- PHANTOM IN DB (first 20) ---")
    for (dt, tkr, ot, strike, exp, side), g in phantom_in_db[:20]:
        avg = g["total_value"] / g["contracts"] if g["contracts"] else 0
        print(f"  {dt} {tkr:6s} {ot:4s} {side:14s} ${strike:8.2f} exp={exp} qty={g['contracts']:3d} avg=${avg:.2f}/contract")

if contract_mismatch:
    print(f"\n--- CONTRACT QTY MISMATCH (first 20) ---")
    for (dt, tkr, ot, strike, exp, side), csv_q, db_q, csv_avg, db_avg in contract_mismatch[:20]:
        print(f"  {dt} {tkr:6s} {ot:4s} {side:14s} ${strike:8.2f} exp={exp} "
              f"csv_qty={csv_q} db_qty={db_q} csv_avg=${csv_avg:.2f} db_avg=${db_avg:.2f}")

if price_mismatch:
    print(f"\n--- PRICE MISMATCH >$1/contract (first 20) ---")
    for (dt, tkr, ot, strike, exp, side), qty, csv_avg, db_avg in price_mismatch[:20]:
        print(f"  {dt} {tkr:6s} {ot:4s} {side:14s} ${strike:8.2f} exp={exp} qty={qty} "
              f"csv_avg=${csv_avg:.2f} db_avg=${db_avg:.2f} diff={db_avg - csv_avg:+.2f}")

# ── PnL reconciliation ────────────────────────────────────────────────────────
# Recompute CSV expected PnL from consolidated fills
# Expected PnL = for each "trade" (BTO + STC pair)
# Let's compute what DB should show based on CSV prices

# Sum all CSV cash flows
csv_bto_total = sum(r["amount"] for r in csv_option_rows if r["tc"] == "BTO")
csv_stc_total = sum(r["amount"] for r in csv_option_rows if r["tc"] == "STC")
csv_net = csv_bto_total + csv_stc_total

# DB realized PnL
cur.execute("""
    SELECT COALESCE(SUM(t.realized_pnl), 0)
    FROM trade t
    JOIN account a ON t.account_id = a.id
    WHERE a.type = 'roth_ira' AND t.instrument_type = 'option'
    AND t.status != 'open'
""")
db_pnl = cur.fetchone()[0]

cur.execute("""
    SELECT COUNT(*), COALESCE(SUM(t.realized_pnl), 0)
    FROM trade t
    JOIN account a ON t.account_id = a.id
    WHERE a.type = 'roth_ira' AND t.instrument_type = 'option'
    AND t.status = 'expired'
""")
exp_count, exp_pnl = cur.fetchone()

cur.execute("""
    SELECT COUNT(*), COALESCE(SUM(t.realized_pnl), 0)
    FROM trade t
    JOIN account a ON t.account_id = a.id
    WHERE a.type = 'roth_ira' AND t.instrument_type = 'option'
    AND t.status = 'closed'
""")
closed_count, closed_pnl = cur.fetchone()

cur.execute("""
    SELECT COUNT(*)
    FROM trade t
    JOIN account a ON t.account_id = a.id
    WHERE a.type = 'roth_ira' AND t.instrument_type = 'option'
    AND t.status = 'open'
""")
open_count = cur.fetchone()[0]

# Open position cost basis still deployed
cur.execute("""
    SELECT COALESCE(SUM(f.price * f.contracts), 0)
    FROM fill f
    JOIN account a ON f.account_id = a.id
    WHERE a.type = 'roth_ira' AND f.instrument_type = 'option'
    AND f.side IN ('buy_to_open', 'sell_to_open')
    AND f.id IN (
        SELECT tf.fill_id FROM tradefill tf
        JOIN trade t ON tf.trade_id = t.id
        WHERE t.status = 'open'
    )
""")
open_deployed = cur.fetchone()[0]

conn.close()

print(f"\n=== PnL RECONCILIATION ===")
print(f"CSV BTO total (cash out):  ${csv_bto_total:+,.2f}")
print(f"CSV STC total (cash in):   ${csv_stc_total:+,.2f}")
print(f"CSV net cash flow (P&L minus fees): ${csv_net:+,.2f}")
print()
print(f"DB closed trades:  {closed_count} trades, PnL = ${closed_pnl:+,.2f}")
print(f"DB expired trades: {exp_count} trades, PnL = ${exp_pnl:+,.2f}")
print(f"DB open trades:    {open_count} trades (cost still deployed = ${open_deployed:,.2f})")
print(f"DB total realized: ${db_pnl:+,.2f}")
print()
print(f"Gap (CSV net - DB realized): ${csv_net - db_pnl:+,.2f}")
print()
print(f"OEXP rows in CSV (expired worthless): {len(csv_oexp_rows)}")
# Sum up OEXP implied losses — these aren't in the CSV amounts, they're just markers
# The BTO fills for expired options should have been recorded; the loss = that BTO cost
print("  (expired worthless losses ARE in the BTO cash flows above)")

# Show OEXP samples
print(f"\n--- OEXP sample (first 10) ---")
for r in csv_oexp_rows[:10]:
    print(f"  {r['date']} {r['desc'][:60]}")
