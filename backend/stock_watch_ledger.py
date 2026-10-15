"""Immutable stock advice, separate from shadow decisions and market forecasts."""

import json
import uuid

from cloud_mcp_check_ledger import Conflict
from market_watch_common import parse_time, seal
from stock_watch_common import REVIEW_FORMAT, stamp, validate_alert, validate_review


class StockWatchLedger:
    def __init__(self, ledger):
        self.ledger = ledger
        db = ledger._connect()
        try:
            db.executescript("""CREATE TABLE IF NOT EXISTS stock_watch_review (
              actor TEXT NOT NULL, alert_id TEXT NOT NULL, record_json TEXT NOT NULL,
              PRIMARY KEY(actor,alert_id));
              CREATE UNIQUE INDEX IF NOT EXISTS stock_review_one_alert ON stock_watch_review(alert_id);
              CREATE TRIGGER IF NOT EXISTS stock_review_no_update BEFORE UPDATE ON stock_watch_review
              BEGIN SELECT RAISE(ABORT,'immutable stock review'); END;
              CREATE TRIGGER IF NOT EXISTS stock_review_no_delete BEFORE DELETE ON stock_watch_review
              BEGIN SELECT RAISE(ABORT,'immutable stock review'); END;
              CREATE TRIGGER IF NOT EXISTS stock_review_no_replace BEFORE INSERT ON stock_watch_review
              WHEN EXISTS(SELECT 1 FROM stock_watch_review WHERE actor=NEW.actor AND alert_id=NEW.alert_id)
              BEGIN SELECT RAISE(ABORT,'immutable stock review'); END;""")
            db.executescript("""CREATE TABLE IF NOT EXISTS stock_watch_input (
              actor TEXT NOT NULL, alert_id TEXT NOT NULL, alert_sha256 TEXT NOT NULL,
              served_at TEXT NOT NULL, PRIMARY KEY(actor,alert_id));
              CREATE TRIGGER IF NOT EXISTS stock_input_no_update BEFORE UPDATE ON stock_watch_input
              BEGIN SELECT RAISE(ABORT,'immutable stock input'); END;
              CREATE TRIGGER IF NOT EXISTS stock_input_no_delete BEFORE DELETE ON stock_watch_input
              BEGIN SELECT RAISE(ABORT,'immutable stock input'); END;
              CREATE TRIGGER IF NOT EXISTS stock_input_no_replace BEFORE INSERT ON stock_watch_input
              WHEN EXISTS(SELECT 1 FROM stock_watch_input WHERE actor=NEW.actor AND alert_id=NEW.alert_id)
              BEGIN SELECT RAISE(ABORT,'immutable stock input'); END;""")
        finally:
            db.close()

    def serve(self, actor, alert, now):
        validate_alert(alert)
        if parse_time(alert["detected_at"]) > now:
            raise ValueError("Future stock alert")
        db = self.ledger._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT alert_sha256,served_at FROM stock_watch_input WHERE actor=? AND alert_id=?",
                (actor, alert["alert_id"]),
            ).fetchone()
            if row is None:
                row = (alert["content_sha256"], stamp(now))
                db.execute(
                    "INSERT INTO stock_watch_input VALUES(?,?,?,?)",
                    (actor, alert["alert_id"], *row),
                )
            if row[0] != alert["content_sha256"]:
                raise ValueError("Stock input changed")
            db.execute("COMMIT")
            return {
                "alert": alert,
                "served_at": row[1],
                "expired": now >= parse_time(alert["expires_at"]),
                "advisory_only": True,
            }
        finally:
            db.close()

    def submit(self, actor, alert, stance, summary, invalidation, notify, clock):
        validate_alert(alert)
        db = self.ledger._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT actor,record_json FROM stock_watch_review WHERE alert_id=?",
                (alert["alert_id"],),
            ).fetchone()
            if row:
                if row[0] != actor:
                    raise Conflict("This stock alert already has an assessment")
                record = json.loads(row[1])
                validate_review(record, alert)
                if any(
                    record[k] != v
                    for k, v in [
                        ("stance", stance),
                        ("summary", summary),
                        ("invalidation", invalidation),
                        ("notify", notify),
                    ]
                ):
                    raise Conflict("A different stock review is already committed")
            else:
                now = clock()
                inp = db.execute(
                    "SELECT alert_sha256 FROM stock_watch_input WHERE actor=? AND alert_id=?",
                    (actor, alert["alert_id"]),
                ).fetchone()
                if inp is None or inp[0] != alert["content_sha256"]:
                    raise ValueError("Read this frozen stock alert before reviewing it")
                if now >= parse_time(alert["expires_at"]):
                    raise ValueError("Stock alert expired; no new review")
                record = seal(
                    {
                        "format": REVIEW_FORMAT,
                        "review_id": "str_" + str(uuid.uuid4()),
                        "alert_id": alert["alert_id"],
                        "alert_sha256": alert["content_sha256"],
                        "session_date": alert["session_date"],
                        "symbol": alert["symbol"],
                        "stance": stance,
                        "summary": summary,
                        "invalidation": invalidation,
                        "notify": notify,
                        "received_at": stamp(now),
                        "created_at": stamp(now),
                    }
                )
                validate_review(record, alert)
                db.execute(
                    "INSERT INTO stock_watch_review VALUES(?,?,?)",
                    (actor, alert["alert_id"], json.dumps(record)),
                )
            db.execute("COMMIT")
            return record
        except BaseException:
            if db.in_transaction:
                db.execute("ROLLBACK")
            raise
        finally:
            db.close()


def write_review(directory, record):
    """Write once; exact retry recovers an interrupted export."""
    from stock_watch_common import identifier, write_once

    identifier(record["review_id"], "str")
    write_once(directory, f"stock-review-{record['review_id']}.json", record)
