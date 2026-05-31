"""
One-off cleanup: remove the SMOKE_ACCT placeholder row and its dependents.

Created during initial Webull integration testing. The /events/test-ingest
call seeds a Fill + WebullRawEvent + Account row using a fake account_id
("SMOKE_ACCT"). When the autostart hook tries to subscribe to all local
Webull accounts, the bogus SMOKE_ACCT causes the entire SubscribeRequest
to fail with PERMISSION_DENIED.

Safe to run once. Idempotent (deletes by exact ids; missing rows = no-op).
"""
import sqlite3
from pathlib import Path

db = Path(__file__).resolve().parent.parent / "data" / "trade_journal.db"
conn = sqlite3.connect(db)
cur = conn.cursor()

cur.execute("SELECT event_id FROM webull_raw_event WHERE event_id = 'event_smoke_test_1'")
raw_before = cur.fetchall()

cur.execute("SELECT id, raw_email_id FROM fill WHERE raw_email_id LIKE 'webull:event_smoke_test_%'")
fill_before = cur.fetchall()

cur.execute("SELECT id, broker_account_id FROM account WHERE broker_account_id = 'SMOKE_ACCT'")
acct_before = cur.fetchall()

print(f"Before: webull_raw_event={len(raw_before)} fill={len(fill_before)} account={len(acct_before)}")

# Order matters: child rows (tradefill, trade_path_metrics) might reference
# the fill. Webull fills shouldn't have trades yet, but guard anyway.
fill_ids = [row[0] for row in fill_before]
if fill_ids:
    placeholders = ",".join("?" for _ in fill_ids)
    cur.execute(f"DELETE FROM tradefill WHERE fill_id IN ({placeholders})", fill_ids)
    cur.execute(f"DELETE FROM webull_raw_event WHERE fill_id IN ({placeholders})", fill_ids)

cur.execute("DELETE FROM webull_raw_event WHERE event_id = 'event_smoke_test_1'")
cur.execute("DELETE FROM fill WHERE raw_email_id LIKE 'webull:event_smoke_test_%'")
cur.execute("DELETE FROM account WHERE broker_account_id = 'SMOKE_ACCT'")

conn.commit()
print("Deleted SMOKE_ACCT rows and dependents.")
