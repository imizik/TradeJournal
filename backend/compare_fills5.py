"""
Find fills not linked to any trade (orphaned) and understand the reconstructor gap.
"""
import sqlite3
from collections import defaultdict
from datetime import date, datetime

conn = sqlite3.connect("data/trade_journal.db")
cur = conn.cursor()

# ── 1. Orphaned fills (in fills table but not in tradefill) ───────────────────
cur.execute("""
    SELECT f.id, f.ticker, f.option_type, f.strike, f.expiration,
           f.contracts, f.side, f.price, f.executed_at, a.last4
    FROM fill f
    JOIN account a ON f.account_id = a.id
    WHERE a.type = 'roth_ira'
      AND f.instrument_type = 'option'
      AND f.id NOT IN (SELECT fill_id FROM tradefill)
    ORDER BY f.executed_at
""")
orphans = cur.fetchall()
print(f"=== ORPHANED FILLS (not linked to any trade): {len(orphans)} ===")
orphan_bto_val = 0.0
orphan_stc_val = 0.0
for row in orphans:
    fid, tkr, ot, strike, exp, qty, side, price, exec_at, last4 = row
    val = qty * price
    if "buy" in side:
        orphan_bto_val += val
    else:
        orphan_stc_val += val
    print(f"  {exec_at[:10]} {tkr:6s} {ot:4s} {side:14s} ${float(strike):8.2f} exp={exp} "
          f"qty={qty:3d} price=${price:.2f}  total=${val:,.2f}  acct=•{last4}")

print(f"\nOrphaned BTO value: ${orphan_bto_val:,.2f}")
print(f"Orphaned STC value: ${orphan_stc_val:,.2f}")
print(f"Orphaned net:       ${orphan_stc_val - orphan_bto_val:+,.2f}")

# ── 2. Verify fill-to-trade PnL accounting ────────────────────────────────────
# For each closed trade, compute expected PnL from linked fills
cur.execute("""
    SELECT t.id, t.realized_pnl, t.avg_entry_premium, t.avg_exit_premium,
           t.contracts, t.status, t.ticker, t.expiration
    FROM trade t
    JOIN account a ON t.account_id = a.id
    WHERE a.type = 'roth_ira' AND t.instrument_type = 'option'
    AND t.status != 'open'
""")
trades = cur.fetchall()

# Get fills for each trade
cur.execute("""
    SELECT tf.trade_id, tf.role, f.contracts, f.price, f.side
    FROM tradefill tf
    JOIN fill f ON tf.fill_id = f.id
    JOIN trade t ON tf.trade_id = t.id
    JOIN account a ON t.account_id = a.id
    WHERE a.type = 'roth_ira' AND t.instrument_type = 'option'
""")
trade_fills = defaultdict(list)
for row in cur.fetchall():
    trade_fills[row[0]].append(row[1:])

pnl_errors = []
total_fill_net = 0.0
total_db_pnl = 0.0
for tid, db_pnl, avg_entry, avg_exit, contracts, status, tkr, exp in trades:
    fills = trade_fills[tid]
    entry_val = sum(f[1] * f[2] for f in fills if f[0] == "entry")
    exit_val = sum(f[1] * f[2] for f in fills if f[0] == "exit")
    if status == "expired":
        fill_implied_pnl = -entry_val
    else:
        fill_implied_pnl = exit_val - entry_val
    total_fill_net += fill_implied_pnl
    total_db_pnl += db_pnl if db_pnl else 0
    if db_pnl is not None and abs(fill_implied_pnl - db_pnl) > 0.50:
        pnl_errors.append({
            "id": tid, "ticker": tkr, "exp": exp, "status": status,
            "contracts": contracts, "avg_entry": avg_entry, "avg_exit": avg_exit,
            "fill_entry": entry_val, "fill_exit": exit_val,
            "fill_pnl": fill_implied_pnl, "db_pnl": db_pnl,
            "diff": db_pnl - fill_implied_pnl
        })

print(f"\n=== TRADE PnL CONSISTENCY CHECK ===")
print(f"Total trades checked: {len(trades)}")
print(f"Trades where db_pnl != fill_implied_pnl by >$0.50: {len(pnl_errors)}")
print(f"Sum of fill-implied PnL: ${total_fill_net:+,.2f}")
print(f"Sum of db realized PnL:  ${total_db_pnl:+,.2f}")
print(f"Diff: ${total_db_pnl - total_fill_net:+,.2f}")

if pnl_errors:
    print(f"\n--- Inconsistent trades (largest diff first) ---")
    for e in sorted(pnl_errors, key=lambda x: abs(x["diff"]), reverse=True)[:20]:
        print(f"  {e['ticker']:6s} {e['exp']} {e['status']:8s} qty={e['contracts']:3d} "
              f"entry=${e['fill_entry']:.2f} exit=${e['fill_exit']:.2f} "
              f"fill_pnl=${e['fill_pnl']:+.2f} db_pnl=${e['db_pnl']:+.2f} diff=${e['diff']:+.2f}")

# ── 3. Big picture reconciliation ─────────────────────────────────────────────
cur.execute("""
    SELECT COALESCE(SUM(f.contracts * f.price), 0)
    FROM fill f
    JOIN account a ON f.account_id = a.id
    WHERE a.type = 'roth_ira' AND f.instrument_type = 'option'
    AND f.side IN ('buy_to_open', 'buy_to_close')
    AND f.id IN (SELECT fill_id FROM tradefill)
""")
linked_bto = cur.fetchone()[0]

cur.execute("""
    SELECT COALESCE(SUM(f.contracts * f.price), 0)
    FROM fill f
    JOIN account a ON f.account_id = a.id
    WHERE a.type = 'roth_ira' AND f.instrument_type = 'option'
    AND f.side IN ('sell_to_close', 'sell_to_open')
    AND f.id IN (SELECT fill_id FROM tradefill)
""")
linked_stc = cur.fetchone()[0]

print(f"\n=== FILL ACCOUNTING ===")
print(f"Total BTO fills value:            ${698014.04:>12,.2f}")
print(f"  linked to trades:               ${linked_bto:>12,.2f}")
print(f"  orphaned:                       ${orphan_bto_val:>12,.2f}")
print(f"  unaccounted:                    ${698014.04 - linked_bto - orphan_bto_val:>12,.2f}")
print()
print(f"Total STC fills value:            ${701455.02:>12,.2f}")
print(f"  linked to trades:               ${linked_stc:>12,.2f}")
print(f"  orphaned:                       ${orphan_stc_val:>12,.2f}")
print(f"  unaccounted:                    ${701455.02 - linked_stc - orphan_stc_val:>12,.2f}")

conn.close()
