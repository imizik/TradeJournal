"""
Cash flow reconciliation: compare DB fill prices×qty directly with CSV amounts.
This tells us whether the gap is in the fills or in how trades were reconstructed.
"""
import csv
import re
import sqlite3
from collections import defaultdict
from datetime import date, datetime

AMOUNT_NUM_RE = re.compile(r"[\d,]+\.?\d*")
DESC_RE = re.compile(
    r"^(\S+)\s+(\d{1,2}/\d{1,2}/\d{4})\s+(Call|Put)\s+\$([\d,]+\.?\d*)$",
    re.IGNORECASE,
)
SIDE_MAP = {
    "BTO": "buy_to_open", "STC": "sell_to_close",
    "BTC": "buy_to_close", "STO": "sell_to_open",
}

csv_rows = []
with open("Robinhood/ROTH jul2023 to april 2026.csv", newline="", encoding="utf-8") as f:
    for r in csv.DictReader(f):
        tc = (r.get("Trans Code") or "").strip()
        if tc not in SIDE_MAP:
            continue
        desc = (r.get("Description") or "").replace("\n", " ").strip()
        m = DESC_RE.match(desc)
        if not m:
            continue
        ticker, exp_str, opt_type, strike_str = m.group(1), m.group(2), m.group(3), m.group(4)
        exp = datetime.strptime(exp_str, "%m/%d/%Y").date()
        strike = float(strike_str.replace(",", ""))
        act_date = datetime.strptime(r["Activity Date"].strip(), "%m/%d/%Y").date()
        qty = int(r["Quantity"].strip())
        price_per_contract = round(float(r["Price"].strip().lstrip("$").replace(",", "")) * 100, 2)
        amount_str = r["Amount"].strip()
        neg = amount_str.startswith("(")
        amount = -float(AMOUNT_NUM_RE.search(amount_str.replace(",", "")).group()) if neg else \
                  float(AMOUNT_NUM_RE.search(amount_str.replace(",", "")).group())
        csv_rows.append({
            "date": act_date, "ticker": ticker.upper(), "option_type": opt_type.lower(),
            "strike": strike, "expiration": exp, "contracts": qty,
            "side": SIDE_MAP[tc], "price_per_contract": price_per_contract,
            "amount": amount, "tc": tc,
        })

conn = sqlite3.connect("data/trade_journal.db")
cur = conn.cursor()

# ── 1. Fill-level cash flow: DB vs CSV ────────────────────────────────────────
cur.execute("""
    SELECT f.side, f.contracts, f.price
    FROM fill f
    JOIN account a ON f.account_id = a.id
    WHERE a.type = 'roth_ira' AND f.instrument_type = 'option'
""")
db_fill_rows = cur.fetchall()

db_bto_value = sum(r[1] * r[2] for r in db_fill_rows if r[0] in ("buy_to_open", "buy_to_close"))
db_stc_value = sum(r[1] * r[2] for r in db_fill_rows if r[0] in ("sell_to_close", "sell_to_open"))

csv_bto_gross = sum(r["contracts"] * r["price_per_contract"] for r in csv_rows if r["tc"] == "BTO")
csv_stc_gross = sum(r["contracts"] * r["price_per_contract"] for r in csv_rows if r["tc"] == "STC")
csv_bto_net = sum(r["amount"] for r in csv_rows if r["tc"] == "BTO")
csv_stc_net = sum(r["amount"] for r in csv_rows if r["tc"] == "STC")
csv_fees = (csv_bto_gross + csv_bto_net) + (csv_stc_gross - csv_stc_net)  # fees = gross - net

print("=== FILL-LEVEL CASH FLOW ===")
print(f"DB  BTO value (price*qty): ${db_bto_value:,.2f}")
print(f"CSV BTO gross (price*qty): ${csv_bto_gross:,.2f}  (before fees: {csv_bto_net:,.2f})")
print(f"BTO gap (DB - CSV gross): ${db_bto_value - csv_bto_gross:+,.2f}")
print()
print(f"DB  STC value (price*qty): ${db_stc_value:,.2f}")
print(f"CSV STC gross (price*qty): ${csv_stc_gross:,.2f}  (after fees: {csv_stc_net:,.2f})")
print(f"STC gap (DB - CSV gross): ${db_stc_value - csv_stc_gross:+,.2f}")
print()
print(f"DB net (STC - BTO):  ${db_stc_value - db_bto_value:+,.2f}")
print(f"CSV net gross:       ${csv_stc_gross - csv_bto_gross:+,.2f}")
print(f"CSV net after fees:  ${csv_stc_net + csv_bto_net:+,.2f}")
print(f"Estimated fees:      ${csv_fees:.2f}")

# ── 2. Phantom contract PnL impact ────────────────────────────────────────────
print("\n=== PHANTOM CONTRACT ANALYSIS ===")
phantom = [
    # (date, ticker, opt_type, strike, exp, side, real_qty, db_qty, price)
    (date(2025, 7, 25), "COIN", "put",  375.0, date(2025, 7, 25), "sell_to_close", 3, 5, 15.0),
    (date(2025, 9, 17), "WMT",  "put",  102.0, date(2025, 9, 19), "buy_to_open",   3, 6, 25.0),
    (date(2025,10,15), "GOOG", "call", 255.0, date(2025,10,17), "buy_to_open",   2, 3, 125.0),
    (date(2025,11, 7), "LMND", "put",   68.0, date(2025,11, 7), "sell_to_close", 5, 6, 22.5),  # avg
    (date(2026, 2,20), "AMD",  "put",  200.0, date(2026, 2,20), "buy_to_open",  30,37, 43.0),
    (date(2026, 4,17), "SPY",  "put",  710.0, date(2026, 4,17), "sell_to_close", 5, 9, 115.0),
]
print("Phantom fills and their direct PnL impact:")
total_phantom_entry_cost = 0.0
total_phantom_exit_value = 0.0
for dt, tkr, ot, strike, exp, side, real_qty, db_qty, price in phantom:
    extra = db_qty - real_qty
    value = extra * price
    if "buy" in side:
        total_phantom_entry_cost += value
        print(f"  {tkr} {ot} {side}: +{extra} phantom BTO @ ${price:.2f} = ${value:.2f} phantom entry cost")
    else:
        total_phantom_exit_value += value
        print(f"  {tkr} {ot} {side}: +{extra} phantom STC @ ${price:.2f} = ${value:.2f} phantom exit value")

print(f"\nTotal phantom entry cost:  ${total_phantom_entry_cost:.2f}")
print(f"Total phantom exit value:  ${total_phantom_exit_value:.2f}")
print(f"Net phantom PnL effect:    ${total_phantom_exit_value - total_phantom_entry_cost:+.2f}")

# WMT + GOOG + AMD phantom BTOs all expired worthless
phantom_expired_loss = (3 * 25.0) + (1 * 125.0) + (7 * 43.0)
print(f"\nOf the phantom BTOs: WMT(3@25), GOOG(1@125), AMD(7@43) all expired worthless")
print(f"  Phantom expired loss: ${phantom_expired_loss:.2f}")
print(f"  Phantom STC income:   ${total_phantom_exit_value:.2f}")
print(f"  Net effect:           ${total_phantom_exit_value - phantom_expired_loss:+.2f}")

# ── 3. Deeper: compare DB net vs CSV net per month ────────────────────────────
print("\n=== MONTH-BY-MONTH CSV vs DB NET CASH FLOW ===")
from collections import defaultdict

# Group CSV by year-month
csv_by_month = defaultdict(float)
for r in csv_rows:
    ym = r["date"].strftime("%Y-%m")
    csv_by_month[ym] += r["amount"]

# Get DB realized PnL by month (from closed/expired at)
cur.execute("""
    SELECT strftime('%Y-%m', t.closed_at) as ym,
           SUM(t.realized_pnl)
    FROM trade t
    JOIN account a ON t.account_id = a.id
    WHERE a.type = 'roth_ira' AND t.instrument_type = 'option'
      AND t.status != 'open'
    GROUP BY ym ORDER BY ym
""")
db_by_month = dict(cur.fetchall())

# Get DB fill cash flows by month
cur.execute("""
    SELECT strftime('%Y-%m', f.executed_at) as ym,
           f.side, SUM(f.contracts * f.price)
    FROM fill f
    JOIN account a ON f.account_id = a.id
    WHERE a.type = 'roth_ira' AND f.instrument_type = 'option'
    GROUP BY ym, f.side ORDER BY ym
""")
db_fill_by_month = defaultdict(float)
for ym, side, val in cur.fetchall():
    if side in ("sell_to_close", "sell_to_open"):
        db_fill_by_month[ym] += val
    else:
        db_fill_by_month[ym] -= val

all_months = sorted(set(csv_by_month) | set(db_fill_by_month))
print(f"{'Month':<8} {'CSV Net':>10} {'DB Fill Net':>12} {'Gap':>8}")
print("-" * 45)
total_csv = 0.0
total_db = 0.0
for ym in all_months:
    c = csv_by_month.get(ym, 0)
    d = db_fill_by_month.get(ym, 0)
    gap = d - c
    total_csv += c
    total_db += d
    flag = " <-- GAP" if abs(gap) > 100 else ""
    print(f"{ym}  {c:>10.2f}  {d:>12.2f}  {gap:>8.2f}{flag}")
print("-" * 45)
print(f"{'TOTAL':<8} {total_csv:>10.2f}  {total_db:>12.2f}  {total_db-total_csv:>8.2f}")

conn.close()
