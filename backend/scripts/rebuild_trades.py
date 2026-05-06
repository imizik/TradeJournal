"""Rebuild trades directly (bypasses the HTTP API)."""
import sqlite3
import sys
import uuid
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.engine.reconstructor import FillInput, reconstruct  # noqa: E402

DB_PATH = BACKEND_ROOT / "data" / "trade_journal.db"


def main():
    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row

    # 1. Load all fills
    fills_raw = con.execute(
        "SELECT * FROM fill ORDER BY executed_at"
    ).fetchall()
    print(f"Fills loaded: {len(fills_raw)}")

    fill_inputs = []
    for row in fills_raw:
        fill_inputs.append(FillInput(
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

    # 2. Run FIFO reconstructor
    result = reconstruct(fill_inputs)
    print(f"Trades reconstructed: {len(result.trades)}")
    print(f"Trade-fill links: {len(result.trade_fills)}")
    print(f"Anomalies: {len(result.anomalies)}")

    # 3. Wipe derived tables
    con.execute("DELETE FROM tradetag")
    con.execute("DELETE FROM tradefill")
    con.execute("DELETE FROM trade")
    con.commit()

    # 4. Insert trades
    for t in result.trades:
        con.execute(
            """INSERT INTO trade (
                id, account_id, ticker, instrument_type, option_type,
                strike, expiration, contracts,
                avg_entry_premium, avg_exit_premium, total_premium_paid,
                realized_pnl, pnl_pct,
                hold_duration_mins, entry_time_bucket,
                expired_worthless, opened_at, closed_at, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                t.id.hex, t.account_id.hex, t.ticker, t.instrument_type, t.option_type,
                float(t.strike) if t.strike is not None else None,
                t.expiration.isoformat() if t.expiration else None,
                float(t.contracts),
                float(t.avg_entry_premium),
                float(t.avg_exit_premium) if t.avg_exit_premium is not None else None,
                float(t.total_premium_paid),
                float(t.realized_pnl) if t.realized_pnl is not None else None,
                float(t.pnl_pct) if t.pnl_pct is not None else None,
                t.hold_duration_mins,
                t.entry_time_bucket,
                t.expired_worthless,
                t.opened_at.isoformat(),
                t.closed_at.isoformat() if t.closed_at else None,
                t.status,
            ),
        )

    # 5. Insert trade-fill junctions
    for tf in result.trade_fills:
        con.execute(
            "INSERT INTO tradefill (trade_id, fill_id, role) VALUES (?, ?, ?)",
            (tf.trade_id.hex, tf.fill_id.hex, tf.role),
        )

    con.commit()

    # 6. Report results
    row = con.execute("""
        SELECT
            COALESCE(SUM(CASE WHEN status IN ('closed', 'expired') THEN realized_pnl END), 0) as dashboard_pnl,
            COUNT(*) as total,
            COUNT(CASE WHEN status = 'closed' THEN 1 END) as closed,
            COUNT(CASE WHEN status = 'expired' THEN 1 END) as expired,
            COUNT(CASE WHEN status = 'open' THEN 1 END) as open_count
        FROM trade
    """).fetchone()

    print(f"\n=== REBUILD COMPLETE ===")
    print(f"  Total trades: {row['total']}")
    print(f"  Closed: {row['closed']}, Expired: {row['expired']}, Open: {row['open_count']}")
    print(f"  Dashboard PnL: ${row['dashboard_pnl']:+,.2f}")

    # Per-account breakdown
    for acct_row in con.execute("""
        SELECT a.name, a.last4,
               COALESCE(SUM(CASE WHEN t.status IN ('closed','expired') THEN t.realized_pnl END), 0) as pnl,
               COUNT(*) as cnt
        FROM trade t JOIN account a ON t.account_id = a.id
        GROUP BY a.id
    """).fetchall():
        print(f"  {acct_row['name']} ({acct_row['last4']}): ${acct_row['pnl']:+,.2f} ({acct_row['cnt']} trades)")

    if result.anomalies:
        print(f"\n  Anomalies ({len(result.anomalies)}):")
        for a in result.anomalies:
            print(f"    - {a[:120]}")

    con.close()


if __name__ == "__main__":
    main()
