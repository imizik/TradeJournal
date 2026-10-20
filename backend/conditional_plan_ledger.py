"""Actor-bound plan/cancellation receipts in the existing Check ledger."""

from datetime import timedelta
import json
from pathlib import Path
import uuid

from cloud_mcp_check_ledger import Conflict, NotFound
from conditional_plan_common import (
    FORMAT,
    MAX_DAILY_PLANS,
    FRESH_SECONDS,
    price,
    readiness,
    validate_plan,
    validate_cancel,
)
from market_watch_common import digest, parse_time, seal
from stock_watch_common import stamp, write_once, validate_alert


class PlanLedger:
    def __init__(self, ledger):
        self.ledger = ledger
        db = ledger._connect()
        try:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS conditional_plan (
                  plan_id TEXT PRIMARY KEY, actor TEXT NOT NULL, operation_id TEXT NOT NULL,
                  request_sha256 TEXT NOT NULL, record_json TEXT NOT NULL, UNIQUE(actor,operation_id));
                CREATE TABLE IF NOT EXISTS conditional_plan_cancel (
                  plan_id TEXT PRIMARY KEY, actor TEXT NOT NULL, record_json TEXT NOT NULL);
            """)
            for table in ("conditional_plan", "conditional_plan_cancel"):
                for action in ("UPDATE", "DELETE"):
                    db.execute(
                        f"CREATE TRIGGER IF NOT EXISTS {table}_no_{action.lower()} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT,'immutable conditional plan'); END"
                    )
                db.execute(
                    f"CREATE TRIGGER IF NOT EXISTS {table}_no_replace BEFORE INSERT ON {table} WHEN EXISTS(SELECT 1 FROM {table} WHERE plan_id=NEW.plan_id) BEGIN SELECT RAISE(ABORT,'immutable conditional plan'); END"
                )
        finally:
            db.close()

    def get(self, actor, plan_id):
        db = self.ledger._connect()
        try:
            row = db.execute(
                "SELECT record_json FROM conditional_plan WHERE actor=? AND plan_id=?",
                (actor, plan_id),
            ).fetchone()
            if row is None:
                raise NotFound("No conditional plan for this actor")
            return validate_plan(json.loads(row[0]))
        finally:
            db.close()

    def list(self, actor):
        db = self.ledger._connect()
        try:
            return [
                validate_plan(json.loads(r[0]))
                for r in db.execute(
                    "SELECT record_json FROM conditional_plan WHERE actor=? ORDER BY rowid DESC LIMIT 50",
                    (actor,),
                )
            ]
        finally:
            db.close()

    def source(self, actor, source_kind, source_id, directory, now, check_actor):
        if source_kind == "check":
            # Pre-trade checks use the authenticated subject; stock/shadow
            # receipts use profile_id. Both come from the verified grant.
            r = self.ledger.get(check_actor, source_id)
            if r["profile_id"] != actor:
                raise ValueError("Check belongs to a different profile")
            answer = r["answer"]
            live = answer["live"]
            received = parse_time(r["received_at"])
            age = live["staleness"]["last_bar_age_seconds"]
            if (
                type(age) not in (int, float)
                or not 0 <= age <= FRESH_SECONDS
                or live["staleness"].get("is_stale") is not False
            ):
                raise ValueError("Check lacks fresh completed bars")
            return answer["idea"]["ticker"].upper(), {
                "kind": "check",
                "id": source_id,
                "sha256": digest(r),
                "observed_at": stamp(received - timedelta(seconds=age)),
                "price": price(live["price"]),
            }
        if source_kind != "stock_alert":
            raise ValueError("Require check or stock_alert source")
        from conditional_plan_common import read_json
        from stock_watch_common import identifier

        identifier(source_id, "sta")
        try:
            r = validate_alert(read_json(Path(directory) / f"stock-{source_id}.json"))
        except FileNotFoundError:
            raise ValueError("Stock alert not found") from None
        if r["alert_id"] != source_id or r["kind"] == "diagnostic":
            raise ValueError("Require a real matching stock alert")
        db = self.ledger._connect()
        try:
            row = db.execute(
                "SELECT alert_sha256 FROM stock_watch_input WHERE actor=? AND alert_id=?",
                (actor, source_id),
            ).fetchone()
        finally:
            db.close()
        if not row or row[0] != r["content_sha256"]:
            raise ValueError("Read this stock alert before creating a plan")
        from datetime import UTC, datetime

        return r["symbol"], {
            "kind": "stock_alert",
            "id": source_id,
            "sha256": r["content_sha256"],
            "observed_at": stamp(
                datetime.fromtimestamp(r["evidence"]["bars"][-1]["end_time"], UTC)
            ),
            "price": r["evidence"]["price"],
        }

    def create(self, actor, request, directory, clock, *, check_actor=None):
        operation = request["operation_id"]
        if not isinstance(operation, str) or not 1 <= len(operation) <= 160:
            raise ValueError("Require bounded retry key")
        request_hash = digest(request)
        db = self.ledger._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute(
                "SELECT request_sha256,record_json FROM conditional_plan WHERE actor=? AND operation_id=?",
                (actor, operation),
            ).fetchone()
            if old:
                if old[0] != request_hash:
                    raise Conflict(
                        "A different conditional plan is already committed for this operation"
                    )
                return validate_plan(json.loads(old[1]))
            now = clock()
            try:
                ready = readiness(directory, now)
            except FileNotFoundError:
                raise ValueError(
                    "Conditional-plan monitor has never reported; it is off or not running"
                ) from None
            symbol, source = self.source(
                actor,
                request["source_kind"],
                request["source_id"],
                directory,
                now,
                check_actor or actor,
            )
            if symbol not in ready["symbols"]:
                raise ValueError(
                    f"{symbol} is not one of the owner's selected scanner tickers"
                    f" ({', '.join(ready['symbols']) or 'none selected'})"
                )
            if (
                db.execute(
                    "SELECT COUNT(*) FROM conditional_plan WHERE actor=? AND json_extract(record_json,'$.session_date')=?",
                    (actor, ready["session_date"]),
                ).fetchone()[0]
                >= MAX_DAILY_PLANS
            ):
                raise ValueError(
                    "24 new plans per session reached; existing plans continue"
                )
            record = seal(
                {
                    "format": FORMAT,
                    "plan_id": "cpl_" + str(uuid.uuid4()),
                    "actor": actor,
                    "session_date": ready["session_date"],
                    "symbol": symbol,
                    **{
                        k: request[k]
                        for k in (
                            "direction",
                            "trigger_price",
                            "invalidation_price",
                            "confirm_bars",
                            "rationale",
                        )
                    },
                    "expires_at": stamp(parse_time(request["expires_at"])),
                    "created_at": stamp(now),
                    "source": source,
                    "session_open_at": ready["session_open_at"],
                    "session_close_at": ready["session_close_at"],
                }
            )
            validate_plan(record)
            db.execute(
                "INSERT INTO conditional_plan VALUES(?,?,?,?,?)",
                (record["plan_id"], actor, operation, request_hash, json.dumps(record)),
            )
            db.commit()
            return record
        finally:
            db.close()

    def cancel(self, actor, plan_id, clock):
        plan = self.get(actor, plan_id)
        db = self.ledger._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT record_json FROM conditional_plan_cancel WHERE plan_id=? AND actor=?",
                (plan_id, actor),
            ).fetchone()
            if row:
                return validate_cancel(json.loads(row[0]), plan)
            r = seal(
                {
                    "format": "conditional-plan-cancel-v1",
                    "plan_id": plan_id,
                    "plan_sha256": plan["content_sha256"],
                    "actor": actor,
                    "session_date": plan["session_date"],
                    "created_at": stamp(clock()),
                }
            )
            validate_cancel(r, plan)
            db.execute(
                "INSERT INTO conditional_plan_cancel VALUES(?,?,?)",
                (plan_id, actor, json.dumps(r)),
            )
            db.commit()
            return r
        finally:
            db.close()


def export(directory, record):
    prefix = (
        "conditional-plan" if record["format"] == FORMAT else "conditional-plan-cancel"
    )
    write_once(directory, f"{prefix}-{record['plan_id']}.json", record)
