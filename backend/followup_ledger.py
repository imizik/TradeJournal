"""Durable, actor-owned conversational responsibilities and frozen review inputs."""

from datetime import timedelta
import json
import uuid

from cloud_mcp_check_ledger import Conflict, NotFound
from followup_common import (
    FollowupSave,
    FollowupReview,
    project,
    ready,
    read_work,
    validate_record,
)
from market_watch_common import digest, parse_time, seal
from stock_watch_common import stamp


class FollowupLedger:
    def __init__(self, ledger):
        self.ledger = ledger
        db = ledger._connect()
        try:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS jo_followup_record (
                  record_id TEXT PRIMARY KEY, actor TEXT NOT NULL, followup_id TEXT NOT NULL,
                  operation_id TEXT NOT NULL, request_hash TEXT NOT NULL, record_json TEXT NOT NULL,
                  UNIQUE(actor,operation_id));
                CREATE TABLE IF NOT EXISTS jo_followup_input (
                  input_id TEXT PRIMARY KEY, actor TEXT NOT NULL, record_json TEXT NOT NULL);
            """)
            for table in ("jo_followup_record", "jo_followup_input"):
                for op in ("UPDATE", "DELETE"):
                    db.execute(
                        f"CREATE TRIGGER IF NOT EXISTS {table}_no_{op} BEFORE {op} ON {table} "
                        "BEGIN SELECT RAISE(ABORT,'follow-up records are immutable'); END"
                    )
                db.execute(
                    f"CREATE TRIGGER IF NOT EXISTS {table}_no_replace BEFORE INSERT ON {table} "
                    f"WHEN EXISTS(SELECT 1 FROM {table} WHERE "
                    + (
                        "record_id=NEW.record_id"
                        if table.endswith("record")
                        else "input_id=NEW.input_id"
                    )
                    + ") BEGIN SELECT RAISE(ABORT,'follow-up records are immutable'); END"
                )
        finally:
            db.close()

    def records(self, actor, followup_id=None, db=None):
        own = db is None
        db = db or self.ledger._connect()
        try:
            sql = "SELECT record_json FROM jo_followup_record WHERE actor=?"
            args = [actor]
            if followup_id:
                sql += " AND followup_id=?"
                args.append(followup_id)
            result = [
                validate_record(json.loads(r[0]))
                for r in db.execute(sql + " ORDER BY rowid", args)
            ]
            if followup_id and not result:
                raise NotFound("Follow-up not found for this owner")
            return result
        finally:
            if own:
                db.close()

    def list(self, actor, now, db=None):
        grouped = {}
        for r in self.records(actor, db=db):
            grouped.setdefault(r["followup_id"], []).append(r)
        values = [project(rows, now) for rows in grouped.values()]
        # Active responsibilities are never hidden behind the history limit.
        return sorted(
            values,
            key=lambda p: (p["state"] == "active", p["request"]["created_at"]),
            reverse=True,
        )[:50]

    def _retry(self, db, actor, operation, body):
        old = db.execute(
            "SELECT request_hash,record_json FROM jo_followup_record WHERE actor=? AND operation_id=?",
            (actor, operation),
        ).fetchone()
        if old:
            if old[0] != digest(body):
                raise Conflict("This follow-up operation already has different content")
            return validate_record(json.loads(old[1]))

    def _save(self, db, actor, followup_id, operation, kind, body, now, **extra):
        record = seal(
            {
                "format": "jo-followup-v1",
                "kind": kind,
                "record_id": "fur_" + str(uuid.uuid4()),
                "followup_id": followup_id,
                "actor": actor,
                "session_date": now.date().isoformat(),
                "created_at": stamp(now),
                "body": body,
                **extra,
            }
        )
        validate_record(record)
        db.execute(
            "INSERT INTO jo_followup_record VALUES(?,?,?,?,?,?)",
            (
                record["record_id"],
                actor,
                followup_id,
                operation,
                digest(body),
                json.dumps(record),
            ),
        )
        return record

    def create(self, actor, body, directory, now):
        body = FollowupSave.model_validate(body).model_dump()
        db = self.ledger._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            old = self._retry(db, actor, "create:" + body["operation_id"], body)
            if old:
                return old
            ready(directory, now)
            if sum(p["state"] == "active" for p in self.list(actor, now, db)) >= 5:
                raise ValueError(
                    "Five active follow-ups already saved; close one before adding another"
                )
            if (
                sum(
                    r["kind"] == "request"
                    and parse_time(r["created_at"]).date() == now.date()
                    for r in self.records(actor, db=db)
                )
                >= 25
            ):
                raise ValueError("25 new follow-ups per day reached")
            if body["linked_plan_id"]:
                # Ownership and existence, without constructing a plan ledger inside this transaction.
                row = db.execute(
                    "SELECT actor FROM conditional_plan WHERE plan_id=?",
                    (body["linked_plan_id"],),
                ).fetchone()
                if not row or row[0] != actor:
                    raise NotFound("Linked price plan not found for this owner")
            record = self._save(
                db,
                actor,
                "fup_" + str(uuid.uuid4()),
                "create:" + body["operation_id"],
                "request",
                body,
                now,
            )
            db.commit()
            return record
        finally:
            db.close()

    def cancel(self, actor, followup_id, now):
        db = self.ledger._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            self.records(actor, followup_id, db)
            body = {"reason": "owner_cancelled"}
            old = self._retry(db, actor, "cancel:" + followup_id, body)
            if old:
                return old
            result = self._save(
                db, actor, followup_id, "cancel:" + followup_id, "cancel", body, now
            )
            db.commit()
            return result
        finally:
            db.close()

    def due(self, actor, directory, now):
        readiness = ready(directory, now)
        result, gaps = [], []
        db = self.ledger._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            for p in self.list(actor, now, db):
                if p["state"] != "active":
                    continue
                try:
                    work = read_work(directory, p["request"]["followup_id"], now)
                except (OSError, ValueError, KeyError):
                    gaps.append(
                        {
                            "followup_id": p["request"]["followup_id"],
                            "title": p["request"]["body"]["title"],
                            "reason": "worker_projection_unavailable",
                        }
                    )
                    continue
                if (
                    work["actor"] != actor
                    or work["parent_id"] != p["parent_id"]
                    or work["request_sha256"] != p["request"]["content_sha256"]
                ):
                    gaps.append(
                        {
                            "followup_id": p["request"]["followup_id"],
                            "title": p["request"]["body"]["title"],
                            "reason": "worker_handoff_pending_or_mismatched",
                        }
                    )
                    continue
                if not work["due"]:
                    continue
                # One frozen input per responsibility/reason/ten-minute window. Lost responses recover it.
                input_id = (
                    "fui_"
                    + digest(
                        [
                            actor,
                            p["parent_id"],
                            work["event_key"],
                            int(now.timestamp()) // 600,
                        ]
                    )[:32]
                )
                old = db.execute(
                    "SELECT record_json FROM jo_followup_input WHERE input_id=? AND actor=?",
                    (input_id, actor),
                ).fetchone()
                if old:
                    value = json.loads(old[0])
                else:
                    value = seal(
                        {
                            "format": "jo-followup-input-v1",
                            "input_id": input_id,
                            "actor": actor,
                            "followup_id": p["request"]["followup_id"],
                            "parent_id": p["parent_id"],
                            "request": p["request"]["body"],
                            "latest_review": p["latest_review"],
                            "last_notification_intent": p["last_notification_intent"],
                            "work": work,
                            "created_at": stamp(now),
                            "expires_at": stamp(
                                min(
                                    now + timedelta(minutes=10),
                                    parse_time(p["request"]["body"]["expires_at"]),
                                )
                            ),
                        }
                    )
                    db.execute(
                        "INSERT INTO jo_followup_input VALUES(?,?,?)",
                        (input_id, actor, json.dumps(value)),
                    )
                if now < parse_time(value["expires_at"]):
                    result.append(value)
            db.commit()
            return {
                "inputs": result,
                "gaps": gaps,
                "worker": readiness,
                "limits": "Periodic research reviews, not continuous thesis/news monitoring. Missing evidence stays missing.",
            }
        finally:
            db.close()

    def review(self, actor, body, now):
        body = FollowupReview.model_validate(body).model_dump()
        db = self.ledger._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            old = self._retry(db, actor, "review:" + body["input_id"], body)
            if old:
                return old
            row = db.execute(
                "SELECT record_json FROM jo_followup_input WHERE input_id=? AND actor=?",
                (body["input_id"], actor),
            ).fetchone()
            if not row:
                raise NotFound("Read your own follow-up input before reviewing")
            inp = json.loads(row[0])
            p = project(self.records(actor, inp["followup_id"], db), now)
            if p["state"] != "active" or p["parent_id"] != inp["parent_id"]:
                raise Conflict("Follow-up changed or closed; do not send this review")
            if not parse_time(inp["created_at"]) <= now < parse_time(inp["expires_at"]):
                raise ValueError(
                    "Follow-up evidence expired; recover a fresh due input"
                )
            if body["outcome"] == "resolved":
                if body["next_review_at"] is not None:
                    raise ValueError("A resolved follow-up has no next review")
            else:
                if not body["next_review_at"] or not now + timedelta(
                    minutes=30
                ) <= parse_time(body["next_review_at"]) < parse_time(
                    p["request"]["body"]["expires_at"]
                ):
                    raise ValueError(
                        "Next review must be at least 30 minutes away and before expiry; otherwise close the follow-up"
                    )
            if body["notify"] and body["outcome"] == "unchanged":
                raise ValueError("Unchanged reviews are saved quietly")
            supported = False
            # Pointers must resolve within the exact frozen input, not arbitrary claims.
            for ref in body["evidence_refs"]:
                value = inp
                if not ref.startswith("/work/evidence/"):
                    raise ValueError(
                        "Evidence must point into the frozen work evidence"
                    )
                try:
                    for part in ref[1:].split("/"):
                        key = part.replace("~1", "/").replace("~0", "~")
                        value = (
                            value[int(key)] if isinstance(value, list) else value[key]
                        )
                except (KeyError, IndexError, ValueError, TypeError):
                    raise ValueError("Evidence reference does not resolve") from None
                if ref.startswith("/work/evidence/stocks/"):
                    symbol = ref.split("/")[4]
                    supported |= bool(
                        inp["work"]["evidence"]["stocks"][symbol].get("bars")
                    )
                elif ref.startswith("/work/evidence/stock_events/"):
                    supported |= bool(inp["work"]["evidence"]["stock_events"])
                elif ref.startswith("/work/evidence/price_plan/"):
                    supported |= bool(inp["work"]["evidence"]["price_plan"])
            for source in body["web_sources"]:
                if (
                    not parse_time(inp["created_at"])
                    <= parse_time(source["observed_at"])
                    <= now
                ):
                    raise ValueError(
                        "External sources must be checked during this review"
                    )
            if body["outcome"] == "update" and not (supported or body["web_sources"]):
                raise ValueError("A changed assessment requires cited evidence")
            record = self._save(
                db,
                actor,
                inp["followup_id"],
                "review:" + body["input_id"],
                "review",
                body,
                now,
                parent_id=inp["parent_id"],
                input_sha256=inp["content_sha256"],
                event_key=inp["work"]["event_key"],
            )
            db.commit()
            return record
        finally:
            db.close()
