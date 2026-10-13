"""Isolated SQLite ledger of immutable pre-trade check rows.

Each check is inserted once and never updated or deleted (SQLite triggers
refuse both). A retry with the same operation ID and the same request returns
the original row; the same operation ID with a different request conflicts.
A model verdict is attached once per check under the same rule. A check's final
result (trade link and price move) is saved once and kept; later reads use it.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import uuid
from zoneinfo import ZoneInfo

FORMAT = "pretrade-check-record-v1"
VERDICTS = ("go", "wait", "pass", "insufficient_data")
MAX_SUMMARY = 2000

SHADOW_LABELS = ["informed-by-history", "independence-unverified"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS tool_call (
    id INTEGER PRIMARY KEY, actor TEXT NOT NULL, tool TEXT NOT NULL, called_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS shadow_decision (
    decision_id TEXT PRIMARY KEY, actor TEXT NOT NULL, candidate_id TEXT NOT NULL,
    decision TEXT NOT NULL, reason TEXT NOT NULL, committed_at TEXT NOT NULL,
    timing TEXT NOT NULL, clean_order INTEGER NOT NULL, setup_sha256 TEXT NOT NULL,
    content_sha256 TEXT NOT NULL, UNIQUE(actor, candidate_id)
);
CREATE TRIGGER IF NOT EXISTS tool_call_no_update BEFORE UPDATE ON tool_call
BEGIN SELECT RAISE(ABORT, 'tool calls are immutable'); END;
CREATE TRIGGER IF NOT EXISTS tool_call_no_delete BEFORE DELETE ON tool_call
BEGIN SELECT RAISE(ABORT, 'tool calls are immutable'); END;
CREATE TRIGGER IF NOT EXISTS shadow_decision_no_update BEFORE UPDATE ON shadow_decision
BEGIN SELECT RAISE(ABORT, 'shadow decisions are immutable'); END;
CREATE TRIGGER IF NOT EXISTS shadow_decision_no_delete BEFORE DELETE ON shadow_decision
BEGIN SELECT RAISE(ABORT, 'shadow decisions are immutable'); END;
CREATE TABLE IF NOT EXISTS check_record (
    check_id TEXT PRIMARY KEY,
    actor TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    received_at TEXT NOT NULL,
    request_sha256 TEXT NOT NULL,
    record_json TEXT NOT NULL,
    record_sha256 TEXT NOT NULL,
    UNIQUE (actor, operation_id)
);
CREATE TABLE IF NOT EXISTS model_verdict (
    check_id TEXT PRIMARY KEY REFERENCES check_record(check_id),
    actor TEXT NOT NULL,
    received_at TEXT NOT NULL,
    verdict TEXT NOT NULL,
    summary TEXT NOT NULL,
    content_sha256 TEXT NOT NULL
);
-- What happened after a check, saved once when final (closed-trade link and price move).
CREATE TABLE IF NOT EXISTS check_result (
    check_id TEXT PRIMARY KEY REFERENCES check_record(check_id),
    saved_at TEXT NOT NULL,
    result_json TEXT NOT NULL,
    result_sha256 TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS check_result_no_update BEFORE UPDATE ON check_result
BEGIN SELECT RAISE(ABORT, 'check results are immutable'); END;
CREATE TRIGGER IF NOT EXISTS check_result_no_delete BEFORE DELETE ON check_result
BEGIN SELECT RAISE(ABORT, 'check results are immutable'); END;
CREATE TRIGGER IF NOT EXISTS check_record_no_update BEFORE UPDATE ON check_record
BEGIN SELECT RAISE(ABORT, 'check records are immutable'); END;
CREATE TRIGGER IF NOT EXISTS check_record_no_delete BEFORE DELETE ON check_record
BEGIN SELECT RAISE(ABORT, 'check records are immutable'); END;
CREATE TRIGGER IF NOT EXISTS model_verdict_no_update BEFORE UPDATE ON model_verdict
BEGIN SELECT RAISE(ABORT, 'model verdicts are immutable'); END;
CREATE TRIGGER IF NOT EXISTS model_verdict_no_delete BEFORE DELETE ON model_verdict
BEGIN SELECT RAISE(ABORT, 'model verdicts are immutable'); END;
"""


class Conflict(Exception):
    """The operation or check already holds different content."""


class NotFound(Exception):
    """No check with this ID for this actor."""


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
        allow_nan=False, default=str).encode()).hexdigest()


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


class Ledger:
    def __init__(self, path):
        path = Path(path)
        if not path.is_absolute():
            raise ValueError("Ledger path must be absolute")
        self.path = path
        db = self._connect()
        try:
            db.executescript(SCHEMA)
        finally:
            db.close()

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        db.execute("PRAGMA foreign_keys = ON")
        db.execute("PRAGMA journal_mode = WAL")
        db.execute("PRAGMA synchronous = FULL")
        return db

    def log_call(self, actor: str, tool: str, now=None):
        db = self._connect()
        try:
            db.execute("INSERT INTO tool_call(actor, tool, called_at) VALUES (?, ?, ?)",
                (actor, tool, now.isoformat() if now is not None else now_utc()))
        finally:
            db.close()

    def decide(self, actor, setup, decision, reason, now):
        if decision not in ("take", "skip") or not isinstance(reason, str) or not reason.strip() or len(reason) > 1000:
            raise ValueError("Use take|skip and a non-empty reason of at most 1000 characters")
        db = self._connect()
        db.row_factory = sqlite3.Row
        try:
            db.execute("BEGIN IMMEDIATE")
            # The service passes its clock, sampled only after obtaining the writer
            # lock. File I/O or a contended ledger must not backdate a commit.
            now = now() if callable(now) else now
            if now.tzinfo is None:
                raise ValueError("Decision time must have a timezone")
            if setup["session_date"] != now.astimezone(ZoneInfo("America/New_York")).date().isoformat():
                raise ValueError("Shadow setup is not from today's session")
            row = db.execute("SELECT * FROM shadow_decision WHERE actor=? AND candidate_id=?",
                (actor, setup["candidate_id"])).fetchone()
            if row is not None:
                result = {"format": "shadow-decision-v1", **dict(row), "clean_order": bool(row["clean_order"]),
                    "labels": list(SHADOW_LABELS)}
                if any(result[key] != value for key, value in
                        (("decision", decision), ("reason", reason), ("setup_sha256", setup["content_sha256"]))):
                    raise Conflict("A different shadow decision is already committed")
                if digest({k: v for k, v in result.items() if k != "content_sha256"}) != result["content_sha256"]:
                    raise ValueError("Shadow decision integrity failed")
            else:
                detected = datetime.fromisoformat(setup["detected_at"])
                expires = datetime.fromisoformat(setup["expires_at"])
                calls = db.execute("SELECT called_at FROM tool_call WHERE actor=? AND tool NOT IN (?, ?)",
                    (actor, "shadow_setup", "shadow_decide")).fetchall()
                clean = not any(detected <= datetime.fromisoformat(call[0]) <= now for call in calls)
                result = {"format": "shadow-decision-v1", "decision_id": "shd_" + str(uuid.uuid4()),
                    "actor": actor, "candidate_id": setup["candidate_id"], "decision": decision, "reason": reason,
                    "committed_at": now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                    "timing": "late" if now >= expires else "on_time", "clean_order": clean,
                    "setup_sha256": setup["content_sha256"], "labels": list(SHADOW_LABELS)}
                result["content_sha256"] = digest(result)
                keys = ("decision_id", "actor", "candidate_id", "decision", "reason", "committed_at", "timing",
                    "clean_order", "setup_sha256", "content_sha256")
                db.execute("INSERT INTO shadow_decision VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    tuple(result[key] for key in keys))
            db.execute("COMMIT")
            return result
        except BaseException:
            if db.in_transaction:
                db.execute("ROLLBACK")
            raise
        finally:
            db.close()

    def find(self, actor: str, operation_id: str, request_sha256: str):
        """Original record for an identical retry; Conflict for different content."""
        db = self._connect()
        try:
            return self.find_in(db, actor, operation_id, request_sha256)
        finally:
            db.close()

    def insert(self, record: dict) -> dict:
        """Insert once. A concurrent identical retry gets the first writer's row."""
        if record.get("format") != FORMAT:
            raise ValueError("Unknown check record format")
        body = json.dumps(record, sort_keys=True, separators=(",", ":"), allow_nan=False)
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            existing = self.find_in(db, record["actor"], record["operation_id"], record["request_sha256"])
            if existing is not None:
                db.execute("ROLLBACK")
                return existing
            db.execute("INSERT INTO check_record VALUES (?, ?, ?, ?, ?, ?, ?)", (record["check_id"], record["actor"],
                record["operation_id"], record["received_at"], record["request_sha256"], body,
                hashlib.sha256(body.encode()).hexdigest()))
            db.execute("COMMIT")
            return json.loads(body)
        except BaseException:
            if db.in_transaction:
                db.execute("ROLLBACK")
            raise
        finally:
            db.close()

    @staticmethod
    def find_in(db, actor, operation_id, request_sha256):
        row = db.execute("SELECT request_sha256, record_json FROM check_record WHERE actor = ? AND operation_id = ?",
            (actor, operation_id)).fetchone()
        if row is None:
            return None
        if row[0] != request_sha256:
            raise Conflict("This operation ID already holds a different check")
        return json.loads(row[1])

    def get(self, actor: str, check_id: str) -> dict:
        db = self._connect()
        try:
            row = db.execute("SELECT record_json, record_sha256 FROM check_record WHERE check_id = ? AND actor = ?",
                (check_id, actor)).fetchone()
        finally:
            db.close()
        if row is None:
            raise NotFound("Unknown check")
        if hashlib.sha256(row[0].encode()).hexdigest() != row[1]:
            raise ValueError("Check record integrity failed")
        return json.loads(row[0])

    def between(self, actor: str, start: str, end: str, limit: int = 50) -> list[tuple[dict, dict | None]]:
        """This actor's checks received in [start, end) (UTC ISO strings), oldest first, each with its model verdict."""
        db = self._connect()
        try:
            rows = db.execute("SELECT c.record_json, c.record_sha256, v.verdict, v.summary, v.received_at FROM check_record c"
                " LEFT JOIN model_verdict v ON v.check_id = c.check_id WHERE c.actor = ? AND c.received_at >= ?"
                " AND c.received_at < ? ORDER BY c.received_at, c.check_id LIMIT ?", (actor, start, end, limit)).fetchall()
        finally:
            db.close()
        result = []
        for body, sha, verdict, summary, received in rows:
            if hashlib.sha256(body.encode()).hexdigest() != sha:
                raise ValueError("Check record integrity failed")
            result.append((json.loads(body), None if verdict is None else
                {"verdict": verdict, "summary": summary, "received_at": received}))
        return result

    def attach(self, actor: str, check_id: str, verdict: str, summary: str) -> dict:
        """Save the model verdict once; identical retries return the original."""
        if verdict not in VERDICTS or not isinstance(summary, str) or not summary.strip() or len(summary) > MAX_SUMMARY:
            raise ValueError("Use go|wait|pass|insufficient_data and a bounded non-empty summary")
        content = digest({"check_id": check_id, "verdict": verdict, "summary": summary})
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM check_record WHERE check_id = ? AND actor = ?", (check_id, actor)).fetchone() is None:
                raise NotFound("Unknown check")
            row = db.execute("SELECT actor, received_at, verdict, summary, content_sha256 FROM model_verdict WHERE check_id = ?",
                (check_id,)).fetchone()
            if row is None:
                row = (actor, now_utc(), verdict, summary, content)
                db.execute("INSERT INTO model_verdict VALUES (?, ?, ?, ?, ?, ?)", (check_id, *row))
            elif row[4] != content:
                raise Conflict("A different model verdict is already attached to this check")
            db.execute("COMMIT")
        except BaseException:
            if db.in_transaction:
                db.execute("ROLLBACK")
            raise
        finally:
            db.close()
        return {"check_id": check_id, "actor": row[0], "received_at": row[1], "verdict": row[2],
            "summary": row[3], "content_sha256": row[4]}


    def save_result(self, actor: str, check_id: str, result: dict) -> dict:
        """Save a check's final result once; the first saved result is kept and returned."""
        body = json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False)
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM check_record WHERE check_id = ? AND actor = ?", (check_id, actor)).fetchone() is None:
                raise NotFound("Unknown check")
            db.execute("INSERT OR IGNORE INTO check_result VALUES (?, ?, ?, ?)",
                (check_id, now_utc(), body, hashlib.sha256(body.encode()).hexdigest()))
            row = db.execute("SELECT result_json FROM check_result WHERE check_id = ?", (check_id,)).fetchone()
            db.execute("COMMIT")
        except BaseException:
            if db.in_transaction:
                db.execute("ROLLBACK")
            raise
        finally:
            db.close()
        return json.loads(row[0])

    def results(self, check_ids) -> dict:
        """Saved final results by check ID, each verified against its hash."""
        ids = list(check_ids)
        if not ids:
            return {}
        db = self._connect()
        try:
            rows = db.execute("SELECT check_id, result_json, result_sha256 FROM check_result WHERE check_id IN ("
                + ",".join("?" * len(ids)) + ")", ids).fetchall()
        finally:
            db.close()
        saved = {}
        for check_id, body, sha in rows:
            if hashlib.sha256(body.encode()).hexdigest() != sha:
                raise ValueError("Check result integrity failed")
            saved[check_id] = json.loads(body)
        return saved


def new_check_id() -> str:
    return "chk_" + str(uuid.uuid4())
