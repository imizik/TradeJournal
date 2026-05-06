"""
Investigate root causes of the 6 qty mismatches and $3,967 PnL gap.
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
SIDE_MAP = {
    "BTO": "buy_to_open", "STC": "sell_to_close",
    "BTC": "buy_to_close", "STO": "sell_to_open",
}

csv_option_rows = []
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
        csv_option_rows.append({
            "date": act_date, "ticker": ticker.upper(), "option_type": opt_type.lower(),
            "strike": strike, "expiration": exp, "contracts": qty,
            "side": SIDE_MAP[tc], "price_per_contract": price_per_contract, "tc": tc,
        })

conn = sqlite3.connect("data/trade_journal.db")
cur = conn.cursor()

# ── 1. Check quantity mismatches — are they from duplicate accounts? ──────────
print("=== QTY MISMATCH INVESTIGATION ===")
print("Checking fills per account for each mismatched key:\n")

mismatch_keys = [
    (date(2025, 7, 25),  "COIN", "put",  375.0, date(2025, 7, 25),  "sell_to_close"),
    (date(2025, 9, 17),  "WMT",  "put",  102.0, date(2025, 9, 19),  "buy_to_open"),
    (date(2025, 10, 15), "GOOG", "call", 255.0, date(2025, 10, 17), "buy_to_open"),
    (date(2025, 11, 7),  "LMND", "put",   68.0, date(2025, 11, 7),  "sell_to_close"),
    (date(2026, 2, 20),  "AMD",  "put",  200.0, date(2026, 2, 20),  "buy_to_open"),
    (date(2026, 4, 17),  "SPY",  "put",  710.0, date(2026, 4, 17),  "sell_to_close"),
]

csv_qtys = {
    (date(2025, 7, 25),  "COIN", "put",  375.0, date(2025, 7, 25),  "sell_to_close"): 3,
    (date(2025, 9, 17),  "WMT",  "put",  102.0, date(2025, 9, 19),  "buy_to_open"): 3,
    (date(2025, 10, 15), "GOOG", "call", 255.0, date(2025, 10, 17), "buy_to_open"): 2,
    (date(2025, 11, 7),  "LMND", "put",   68.0, date(2025, 11, 7),  "sell_to_close"): 5,
    (date(2026, 2, 20),  "AMD",  "put",  200.0, date(2026, 2, 20),  "buy_to_open"): 30,
    (date(2026, 4, 17),  "SPY",  "put",  710.0, date(2026, 4, 17),  "sell_to_close"): 5,
}

for key in mismatch_keys:
    dt, tkr, ot, strike, exp, side = key
    cur.execute("""
        SELECT a.name, a.last4, f.contracts, f.price, f.executed_at, f.id
        FROM fill f
        JOIN account a ON f.account_id = a.id
        WHERE a.type = 'roth_ira'
          AND f.instrument_type = 'option'
          AND f.ticker = ?
          AND f.option_type = ?
          AND f.strike = ?
          AND date(f.expiration) = ?
          AND f.side = ?
          AND date(f.executed_at) = ?
        ORDER BY f.executed_at
    """, (tkr, ot, strike, exp.isoformat(), side, dt.isoformat()))
    rows = cur.fetchall()
    csv_qty = csv_qtys[key]
    db_qty = sum(r[2] for r in rows)
    print(f"  {dt} {tkr} {ot} {side} strike=${strike} exp={exp}")
    print(f"  CSV qty={csv_qty}, DB qty={db_qty} (+{db_qty - csv_qty} extra)")
    for acct_name, last4, qty, price, executed_at, fid in rows:
        print(f"    [{acct_name} •{last4}] qty={qty} price=${price:.2f} at {executed_at}")
    print()

# ── 2. PnL gap root cause ─────────────────────────────────────────────────────
print("\n=== PnL GAP ROOT CAUSE ===")

# DB PnL by trade status
cur.execute("""
    SELECT t.status,
           COUNT(*) as cnt,
           COALESCE(SUM(t.realized_pnl), 0) as total_pnl,
           COALESCE(SUM(t.total_premium_paid), 0) as total_cost
    FROM trade t
    JOIN account a ON t.account_id = a.id
    WHERE a.type = 'roth_ira' AND t.instrument_type = 'option'
    GROUP BY t.status
""")
print("DB trades by status (Roth IRA options):")
for row in cur.fetchall():
    print(f"  {row[0]:8s}: {row[1]:4d} trades, realized_pnl=${row[2]:+,.2f}, total_premium_paid=${row[3]:,.2f}")

# Check expired trades — verify they're actually in OEXP CSV list
print("\nAll expired trades in DB vs OEXP in CSV:")
cur.execute("""
    SELECT t.ticker, t.option_type, t.strike, t.expiration, t.contracts,
           t.realized_pnl, t.total_premium_paid, a.last4
    FROM trade t
    JOIN account a ON t.account_id = a.id
    WHERE a.type = 'roth_ira' AND t.instrument_type = 'option' AND t.status = 'expired'
    ORDER BY t.expiration
""")
expired_trades = cur.fetchall()

# Parse OEXP from CSV
oexp_set = set()
with open("Robinhood/ROTH jul2023 to april 2026.csv", newline="", encoding="utf-8") as f:
    for r in csv.DictReader(f):
        tc = (r.get("Trans Code") or "").strip()
        if tc != "OEXP":
            continue
        desc = (r.get("Description") or "").replace("\n", " ").strip()
        # Format: "Option Expiration for TICKER MM/DD/YYYY Call/Put $STRIKE"
        m = re.search(r"for\s+(\S+)\s+(\d{1,2}/\d{1,2}/\d{4})\s+(Call|Put)\s+\$([\d,]+\.?\d*)", desc, re.IGNORECASE)
        if m:
            t, d, ot, s = m.group(1), m.group(2), m.group(3), m.group(4)
            exp = datetime.strptime(d, "%m/%d/%Y").date()
            oexp_set.add((t.upper(), ot.lower(), float(s.replace(",", "")), exp))

print(f"\nCSV OEXP entries: {len(oexp_set)}")
print(f"DB expired trades: {len(expired_trades)}")
print()

not_in_oexp = []
for tkr, ot, strike, exp_str, contracts, rpnl, tpp, last4 in expired_trades:
    exp = date.fromisoformat(exp_str) if exp_str else None
    strike_f = float(strike)
    key = (tkr, ot, strike_f, exp)
    in_csv = key in oexp_set
    if not in_csv:
        not_in_oexp.append((tkr, ot, strike_f, exp, contracts, rpnl, tpp, last4))
    # print all
    marker = "  OK" if in_csv else "  !! NOT IN CSV OEXP"
    print(f"{marker} {exp} {tkr:6s} {ot:4s} ${strike_f:8.2f} qty={contracts} pnl=${rpnl:+,.2f} acct=last4-{last4}")

print(f"\n{len(not_in_oexp)} expired trades NOT found in CSV OEXP list:")
for item in not_in_oexp:
    tkr, ot, strike, exp, contracts, rpnl, tpp, last4 = item
    print(f"  {exp} {tkr:6s} {ot:4s} ${strike:8.2f} qty={contracts} pnl=${rpnl:+,.2f} tpp=${tpp:.2f} acct=•{last4}")

# ── 3. Compute expected PnL per trade from fill prices ────────────────────────
print("\n=== FILL-LEVEL PnL VERIFICATION (sample closed trades) ===")
cur.execute("""
    SELECT t.id, t.ticker, t.option_type, t.strike, t.expiration,
           t.contracts, t.avg_entry_premium, t.avg_exit_premium,
           t.realized_pnl, t.status
    FROM trade t
    JOIN account a ON t.account_id = a.id
    WHERE a.type = 'roth_ira' AND t.instrument_type = 'option' AND t.status = 'closed'
    ORDER BY ABS(t.realized_pnl) DESC
    LIMIT 20
""")
print("Largest closed trade PnL entries:")
for row in cur.fetchall():
    tid, tkr, ot, strike, exp, qty, avg_entry, avg_exit, rpnl, status = row
    expected = (avg_exit - avg_entry) * qty if avg_exit else None
    match = "OK" if expected is not None and abs(expected - rpnl) < 0.01 else "!!"
    print(f"  {match} {tkr:6s} {ot:4s} ${float(strike):8.2f} exp={exp} qty={qty:3d} "
          f"entry=${avg_entry:.2f} exit=${avg_exit:.2f if avg_exit else 0:.2f} "
          f"calc_pnl=${expected:+.2f if expected else '—'} db_pnl=${rpnl:+.2f}")

conn.close()
