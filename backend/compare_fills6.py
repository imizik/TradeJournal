"""
Why does fill net (+$3,441) differ so much from realized PnL (-$908)?
Check STC fills linked to expired trades, and find the biggest individual trade errors.
"""
import sqlite3
from collections import defaultdict

conn = sqlite3.connect("data/trade_journal.db")
cur = conn.cursor()

# ── 1. STC fills linked to expired trades ─────────────────────────────────────
cur.execute("""
    SELECT t.id, t.ticker, t.option_type, t.strike, t.expiration,
           t.contracts, t.status, t.realized_pnl, t.total_premium_paid,
           COALESCE(SUM(CASE WHEN tf.role='entry' THEN f.contracts*f.price ELSE 0 END), 0) as entry_val,
           COALESCE(SUM(CASE WHEN tf.role='exit'  THEN f.contracts*f.price ELSE 0 END), 0) as exit_val
    FROM trade t
    JOIN account a ON t.account_id = a.id
    LEFT JOIN tradefill tf ON tf.trade_id = t.id
    LEFT JOIN fill f ON tf.fill_id = f.id
    WHERE a.type = 'roth_ira' AND t.instrument_type = 'option' AND t.status = 'expired'
    GROUP BY t.id
    ORDER BY exit_val DESC
""")
expired_with_exits = [(r for r in cur.fetchall() if r[10] > 0)]
# re-run
cur.execute("""
    SELECT t.id, t.ticker, t.option_type, t.strike, t.expiration,
           t.contracts, t.status, t.realized_pnl, t.total_premium_paid,
           COALESCE(SUM(CASE WHEN tf.role='entry' THEN f.contracts*f.price ELSE 0 END), 0) as entry_val,
           COALESCE(SUM(CASE WHEN tf.role='exit'  THEN f.contracts*f.price ELSE 0 END), 0) as exit_val
    FROM trade t
    JOIN account a ON t.account_id = a.id
    LEFT JOIN tradefill tf ON tf.trade_id = t.id
    LEFT JOIN fill f ON tf.fill_id = f.id
    WHERE a.type = 'roth_ira' AND t.instrument_type = 'option' AND t.status = 'expired'
    GROUP BY t.id
""")
rows = cur.fetchall()
expired_with_exit_fills = [r for r in rows if r[10] > 0]
print(f"Expired trades with exit fills linked: {len(expired_with_exit_fills)}")
total_exit_in_expired = sum(r[10] for r in rows)
total_entry_in_expired = sum(r[9] for r in rows)
print(f"Total exit_val in expired trades: ${total_exit_in_expired:,.2f}")
print(f"Total entry_val in expired trades: ${total_entry_in_expired:,.2f}")
for r in expired_with_exit_fills:
    tid, tkr, ot, strike, exp, qty, status, rpnl, tpp, entry_val, exit_val = r
    print(f"  {exp} {tkr:6s} {ot:4s} ${float(strike):8.2f} qty={qty} "
          f"rpnl=${rpnl:.2f} entry=${entry_val:.2f} exit=${exit_val:.2f}")

# ── 2. What does the full accounting look like? ───────────────────────────────
cur.execute("""
    SELECT t.status,
           COALESCE(SUM(CASE WHEN tf.role='entry' THEN f.contracts*f.price ELSE 0 END), 0) as entry_val,
           COALESCE(SUM(CASE WHEN tf.role='exit'  THEN f.contracts*f.price ELSE 0 END), 0) as exit_val,
           COALESCE(SUM(t.realized_pnl), 0) as db_pnl,
           COUNT(DISTINCT t.id) as trade_count
    FROM trade t
    JOIN account a ON t.account_id = a.id
    LEFT JOIN tradefill tf ON tf.trade_id = t.id
    LEFT JOIN fill f ON tf.fill_id = f.id
    WHERE a.type = 'roth_ira' AND t.instrument_type = 'option' AND t.status != 'open'
    GROUP BY t.status
""")
print("\n=== FILL ACCOUNTING BY TRADE STATUS ===")
print(f"{'Status':<10} {'Trades':>7} {'Entry Val':>13} {'Exit Val':>13} {'Fill Net':>12} {'DB PnL':>12}")
total_fill_net = 0.0
total_db_pnl = 0.0
for row in cur.fetchall():
    status, entry_val, exit_val, db_pnl, count = row
    fill_net = exit_val - entry_val
    total_fill_net += fill_net
    total_db_pnl += db_pnl
    print(f"{status:<10} {count:>7} {entry_val:>13,.2f} {exit_val:>13,.2f} {fill_net:>12,.2f} {db_pnl:>12,.2f}")
print(f"{'TOTAL':<10} {'':>7} {'':>13} {'':>13} {total_fill_net:>12,.2f} {total_db_pnl:>12,.2f}")
print(f"Fill net vs DB PnL gap: ${total_db_pnl - total_fill_net:+,.2f}")
print()
print("If fill net = DB PnL, they should match. Gap shows reconstructor error.")

# ── 3. The 3 known problem trades in detail ───────────────────────────────────
print("\n=== THE 3 PROBLEM TRADES ===")
problem_ids_query = """
    SELECT t.id FROM trade t
    JOIN account a ON t.account_id = a.id
    WHERE a.type = 'roth_ira' AND t.instrument_type = 'option'
    AND (
        (t.ticker='SPY' AND t.expiration='2026-04-17' AND t.strike=710.0 AND t.option_type='put')
        OR (t.ticker='COIN' AND t.expiration='2025-07-25' AND t.strike=375.0 AND t.option_type='put')
        OR (t.ticker='LMND' AND t.expiration='2025-11-07' AND t.strike=68.0 AND t.option_type='put')
    )
"""
cur.execute(problem_ids_query)
pids = [r[0] for r in cur.fetchall()]
for pid in pids:
    cur.execute("""
        SELECT t.ticker, t.option_type, t.strike, t.expiration, t.contracts,
               t.status, t.realized_pnl, t.avg_entry_premium, t.avg_exit_premium,
               t.total_premium_paid
        FROM trade t WHERE t.id = ?
    """, (pid,))
    t = cur.fetchone()
    print(f"\n{t[0]} {t[1]} ${t[2]} exp={t[3]} qty={t[4]} status={t[5]}")
    print(f"  avg_entry=${t[7]:.2f} avg_exit=${t[8]:.2f if t[8] else 0:.2f} "
          f"db_pnl=${t[6]:.2f} total_premium=${t[9]:.2f}")
    cur.execute("""
        SELECT tf.role, f.side, f.contracts, f.price, f.executed_at
        FROM tradefill tf JOIN fill f ON tf.fill_id = f.id
        WHERE tf.trade_id = ?
        ORDER BY f.executed_at
    """, (pid,))
    for role, side, qty, price, exec_at in cur.fetchall():
        print(f"  [{role:5s}] {side:14s} qty={qty:3d} price=${price:.2f} at {exec_at}")

# ── 4. Summary of expected vs actual PnL ─────────────────────────────────────
print("\n=== SUMMARY ===")
print("CSV net cash flow (actual money made, after fees): $+3,059.10")
print("DB fill net (before reconstructor):               $+3,441.00 approx")
print("DB realized PnL (after reconstructor):             $-908.02")
print()
print("Phantom contract effects (18 extra contracts):")
print("  Phantom expired losses (WMT+GOOG+AMD):          $-501.00")
print("  Phantom exit proceeds (COIN+LMND+SPY):          $+512.50")
print("  Net phantom effect:                              $+11.50")
print()
print("Fill net adjusted for phantom contracts:          ~$+3,430")
print("Reconstructor losses from STC fills in expired:   investigate above")

conn.close()
