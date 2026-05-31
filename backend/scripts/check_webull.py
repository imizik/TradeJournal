"""Quick sanity check for Webull ingest. Run after a /webull/events/test-ingest call."""
import sqlite3
from pathlib import Path

db = Path(__file__).resolve().parent.parent / "data" / "trade_journal.db"
conn = sqlite3.connect(db)

print("--- webull_raw_event ---")
rows = list(conn.execute(
    "SELECT event_id, normalized, normalize_reason, fill_id FROM webull_raw_event"
))
if not rows:
    print("(empty)")
for r in rows:
    print(r)

print()
print("--- fill (webull only) ---")
rows = list(conn.execute(
    "SELECT ticker, side, contracts, price, raw_email_id FROM fill WHERE raw_email_id LIKE 'webull:%'"
))
if not rows:
    print("(empty)")
for r in rows:
    print(r)

print()
print("--- account (broker=webull) ---")
rows = list(conn.execute(
    "SELECT id, name, type, last4, broker, broker_account_id FROM account WHERE broker='webull'"
))
if not rows:
    print("(empty)")
for r in rows:
    print(r)
