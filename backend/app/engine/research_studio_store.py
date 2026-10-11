"""Explicit research-owned files and a manual isolated worker; no app DB/jobs."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict
from datetime import date, datetime, timezone
import fcntl
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sqlite3
import base64
import subprocess
import sys
import threading
import stat
import uuid

from app.engine.market_map import Bar
from app.engine.research_studio import Coverage, Observations, Snapshot, SymbolSnapshot, parse_definition
from app.engine.research_studio_analysis import Cancelled, analysis_id, canonical_bytes
from app.engine.research_studio_data import engine_fingerprint

MAX_BYTES = 128 * 1024 * 1024
RUN_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
MAX_ACTIVE = 4


def code_identity() -> str:
    root = Path(__file__).resolve().parent
    digest = hashlib.sha256()
    digest.update(engine_fingerprint().encode())
    for name in ("research_studio_analysis.py", "research_studio_store.py"):
        digest.update(name.encode())
        digest.update((root / name).read_bytes())
    digest.update((root.parents[1] / "scripts/research_studio_worker.py").read_bytes())
    return digest.hexdigest()


def encode_snapshot(snapshot: Snapshot) -> bytes:
    raw = {"through": str(snapshot.through), "engine_fingerprint": snapshot.engine_fingerprint,
           "provenance": snapshot.provenance, "manifest": snapshot.manifest,
           "symbols": [{"symbol": s.symbol,
                        "coverage": [{**asdict(c), "day": str(c.day)} for c in s.coverage],
                        "bars": [[b.time.isoformat(), b.open, b.high, b.low, b.close, b.volume] for b in s.bars]}
                       for s in snapshot.symbols]}
    payload = canonical_bytes(raw)
    if len(payload) > MAX_BYTES:
        raise ValueError("prepared snapshot exceeded research byte bound")
    return gzip.compress(payload, mtime=0)


def decode_snapshot(payload: bytes) -> Snapshot:
    with gzip.GzipFile(fileobj=io.BytesIO(payload)) as handle:
        raw = handle.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("prepared snapshot exceeded research byte bound")
    raw = json.loads(raw)
    return Snapshot(date.fromisoformat(raw["through"]), tuple(
        SymbolSnapshot(s["symbol"], tuple(Bar(datetime.fromisoformat(b[0]), *b[1:]) for b in s["bars"]),
                       tuple(Coverage(**{**c, "day": date.fromisoformat(c["day"])}) for c in s["coverage"]))
        for s in raw["symbols"]), tuple(tuple(row) for row in raw["manifest"]),
        raw["engine_fingerprint"], raw["provenance"])


class ResearchStore:
    """Single-host operator-selected directory, never a source/cache directory.

    No directory handle or lock survives a method call. The worker lock covers
    the complete execution; ledger locks cover short atomic append operations.
    Do not delete lock files while any worker is running.
    """

    def __init__(self, root: Path, *, source_root: Path):
        self.root = Path(root).resolve(strict=True)
        source = Path(source_root).resolve(strict=True)
        if self.root.is_relative_to(source) or source.is_relative_to(self.root):
            raise ValueError("research store and source cache must not overlap")
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        fd = os.open(self.root.anchor, flags)
        try:
            for part in self.root.parts[1:]:
                child = os.open(part, flags, dir_fd=fd)
                os.close(fd)
                fd = child
            info = os.fstat(fd)
            if info.st_uid != os.geteuid() or info.st_mode & 0o022:
                raise ValueError("research root must be owner-controlled and not group/world writable")
            self._identity = (info.st_dev, info.st_ino)
        finally:
            os.close(fd)

    @contextmanager
    def _root(self):
        fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            info = os.fstat(fd)
            if (info.st_dev, info.st_ino) != self._identity:
                raise ValueError("research root directory changed")
            yield fd
        finally:
            os.close(fd)

    @contextmanager
    def _lock(self, name: str, *, nonblocking=False):
        with self._root() as root:
            fd = os.open(name, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=root)
            try:
                if not stat.S_ISREG(os.fstat(fd).st_mode):
                    raise ValueError("research lock must be a regular file")
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | (fcntl.LOCK_NB if nonblocking else 0))
                except BlockingIOError:
                    raise ValueError("research worker is already active") from None
                yield fd
            finally:
                os.close(fd)

    @contextmanager
    def _run(self, run_id: str, *, create=False):
        if not RUN_PATTERN.fullmatch(run_id):
            raise ValueError("invalid research run identity")
        with self._root() as root:
            if create:
                try:
                    os.mkdir(run_id, 0o700, dir_fd=root)
                    os.fsync(root)
                except FileExistsError:
                    pass
            fd = os.open(run_id, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root)
            try:
                yield fd
            finally:
                os.close(fd)

    @staticmethod
    def _read(fd: int, name: str) -> bytes:
        opened = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        with os.fdopen(opened, "rb") as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_BYTES:
                raise ValueError("research file must be bounded and regular")
            payload = handle.read(MAX_BYTES + 1)
            if len(payload) > MAX_BYTES:
                raise ValueError("research file exceeded byte bound")
            return payload

    @classmethod
    def _immutable(cls, fd: int, name: str, payload: bytes):
        if len(payload) > MAX_BYTES:
            raise ValueError("research file exceeded byte bound")
        temporary = ".pending-" + uuid.uuid4().hex
        opened = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
        try:
            with os.fdopen(opened, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(temporary, name, src_dir_fd=fd, dst_dir_fd=fd, follow_symlinks=False)
            except FileExistsError:
                if cls._read(fd, name) != payload:
                    raise ValueError("immutable research record conflicts") from None
            os.fsync(fd)
        finally:
            os.unlink(temporary, dir_fd=fd)


    @contextmanager
    def _db(self, *, write=False):
        # SQLite's serialized image keeps authoritative transactions in a small
        # owner-controlled file, opened/replaced through the pinned directory.
        # SQLite itself never resolves cache paths, a journal DB or a WAL file.
        with self._lock("ledger.lock") if write else self._root():
            db = sqlite3.connect(":memory:")
            try:
                if not hasattr(db, "deserialize"):
                    raise ValueError("research ledger requires Python3.11+ SQLite serialization")
                with self._root() as root:
                    try:
                        db.deserialize(self._read(root, "ledger.sqlite3"))
                    except FileNotFoundError:
                        pass
                db.execute("PRAGMA foreign_keys=ON")
                db.executescript("""
                    CREATE TABLE IF NOT EXISTS run (
                      id TEXT PRIMARY KEY, request TEXT NOT NULL, request_sha TEXT NOT NULL,
                      result_sha TEXT, created TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS attempt (
                      run_id TEXT NOT NULL REFERENCES run(id), number INTEGER NOT NULL,
                      state TEXT NOT NULL, cancel_requested INTEGER NOT NULL DEFAULT 0, reason TEXT,
                      PRIMARY KEY(run_id,number));
                    CREATE TABLE IF NOT EXISTS operation (
                      id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES run(id), action TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS event (
                      seq INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL REFERENCES run(id),
                      attempt INTEGER NOT NULL, kind TEXT NOT NULL, at TEXT NOT NULL, detail TEXT);
                    CREATE TABLE IF NOT EXISTS exposure (
                      seq INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL REFERENCES run(id),
                      operation_id TEXT NOT NULL UNIQUE REFERENCES operation(id), at TEXT NOT NULL);
                """)
                yield db
                if write:
                    db.commit()
                    payload = db.serialize()
                    if len(payload) > MAX_BYTES:
                        raise ValueError("research ledger exceeded byte bound")
                    with self._root() as root:
                        temporary = ".ledger-" + uuid.uuid4().hex
                        opened = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                         0o600, dir_fd=root)
                        try:
                            with os.fdopen(opened, "wb") as handle:
                                handle.write(payload)
                                handle.flush()
                                os.fsync(handle.fileno())
                            # The ledger is the one mutable index; immutable data
                            # artifacts are separately content-bound in its rows.
                            os.rename(temporary, "ledger.sqlite3", src_dir_fd=root, dst_dir_fd=root)
                            os.fsync(root)
                        finally:
                            try:
                                os.unlink(temporary, dir_fd=root)
                            except FileNotFoundError:
                                pass
            finally:
                db.close()

    @staticmethod
    def _event(db, run_id, attempt, kind, detail=None):
        db.execute("INSERT INTO event(run_id,attempt,kind,at,detail) VALUES(?,?,?,?,?)",
                   (run_id, attempt, kind, datetime.now(timezone.utc).isoformat(), detail))

    @staticmethod
    def _operation(db, operation_id, run_id, action):
        if str(uuid.UUID(operation_id)) != operation_id:
            raise ValueError("operation id must be canonical UUID")
        existing = db.execute("SELECT run_id,action FROM operation WHERE id=?", (operation_id,)).fetchone()
        if existing is not None:
            if existing != (run_id, action):
                raise ValueError("operation id reused for different research action")
            return True
        db.execute("INSERT INTO operation VALUES(?,?,?)", (operation_id, run_id, action))
        return False

    @staticmethod
    def _request(db, run_id):
        found = db.execute("SELECT request,request_sha FROM run WHERE id=?", (run_id,)).fetchone()
        if found is None:
            raise ValueError("unknown research run")
        raw, expected = found
        if hashlib.sha256(raw.encode()).hexdigest() != expected:
            raise ValueError("immutable research request changed")
        request = json.loads(raw)
        definition = parse_definition(request["definition"])
        if request["run_id"] != run_id or analysis_id(definition, request["data_id"], request["code_id"]) != run_id:
            raise ValueError("immutable research request identity mismatch")
        return request

    @classmethod
    def _status(cls, db, run_id):
        request = cls._request(db, run_id)
        row = db.execute("SELECT number,state,cancel_requested,reason FROM attempt WHERE run_id=? ORDER BY number DESC LIMIT 1",
                         (run_id,)).fetchone()
        completed = db.execute("SELECT detail FROM event WHERE run_id=? AND kind='completed' ORDER BY seq DESC LIMIT 1",
                               (run_id,)).fetchone()
        return {"run_id": run_id, "definition_id": parse_definition(request["definition"]).identity,
                "data_id": request["data_id"], "analysis_code_id": request["code_id"],
                "attempt": row[0], "status": row[1], "cancel_requested": bool(row[2]), "reason": row[3],
                "exposures": db.execute("SELECT COUNT(*) FROM exposure WHERE run_id=?", (run_id,)).fetchone()[0],
                "attempts": [{"number": a[0], "state": a[1], "reason": a[2]}
                             for a in db.execute("SELECT number,state,reason FROM attempt WHERE run_id=? ORDER BY number", (run_id,))],
                "worker_metrics": json.loads(completed[0]) if completed and completed[0] else None,
                "distinct_specifications": len({parse_definition(json.loads(r[0])["definition"]).identity
                                                for r in db.execute("SELECT request FROM run")})}

    def status(self, run_id):
        if not RUN_PATTERN.fullmatch(run_id):
            raise ValueError("invalid research run identity")
        with self._db() as db:
            return self._status(db, run_id)

    def enqueue(self, snapshot, definition, operation_id):
        code = code_identity()
        run_id = analysis_id(definition, snapshot.identity, code)
        payload = encode_snapshot(snapshot)
        request = {"run_id": run_id, "definition": definition.canonical(), "data_id": snapshot.identity,
                   "code_id": code, "snapshot_sha256": hashlib.sha256(payload).hexdigest()}
        raw = canonical_bytes(request).decode()
        with self._db(write=True) as db:
            if str(uuid.UUID(operation_id)) != operation_id:
                raise ValueError("operation id must be canonical UUID")
            prior_operation = db.execute("SELECT run_id,action FROM operation WHERE id=?", (operation_id,)).fetchone()
            if prior_operation is not None and prior_operation != (run_id, "enqueue"):
                raise ValueError("operation id reused for different research action")
            existing = db.execute("SELECT request FROM run WHERE id=?", (run_id,)).fetchone()
            if existing is None:
                active = db.execute("SELECT COUNT(*) FROM attempt WHERE state IN ('queued','running')").fetchone()[0]
                if active >= MAX_ACTIVE:
                    raise ValueError("research queue is full (maximum four active runs)")
                with self._run(run_id, create=True) as fd:
                    self._immutable(fd, "snapshot.json.gz", payload)
                db.execute("INSERT INTO run VALUES(?,?,?,?,?)", (run_id, raw, hashlib.sha256(raw.encode()).hexdigest(),
                                                                 None, datetime.now(timezone.utc).isoformat()))
                db.execute("INSERT INTO attempt(run_id,number,state) VALUES(?,1,'queued')", (run_id,))
                self._event(db, run_id, 1, "queued")
            elif existing[0] != raw:
                raise ValueError("immutable research request conflicts")
            if not self._operation(db, operation_id, run_id, "enqueue") and existing is not None:
                self._event(db, run_id, self._status(db, run_id)["attempt"], "request_reused")
            return self._status(db, run_id)

    def control(self, run_id, action, operation_id):
        if action not in ("retry", "cancel"):
            raise ValueError("invalid research control action")
        with self._db(write=True) as db:
            state = self._status(db, run_id)
            if self._operation(db, operation_id, run_id, action):
                return state
            if action == "retry":
                if state["status"] not in ("failed", "cancelled"):
                    raise ValueError("retry requires a failed or cancelled research run")
                if db.execute("SELECT COUNT(*) FROM attempt WHERE state IN ('queued','running')").fetchone()[0] >= MAX_ACTIVE:
                    raise ValueError("research queue is full (maximum four active runs)")
                db.execute("INSERT INTO attempt(run_id,number,state) VALUES(?,?,'queued')", (run_id, state["attempt"] + 1))
                self._event(db, run_id, state["attempt"] + 1, "queued")
            elif state["status"] == "queued":
                db.execute("UPDATE attempt SET state='cancelled' WHERE run_id=? AND number=?", (run_id, state["attempt"]))
                self._event(db, run_id, state["attempt"], "cancelled")
            elif state["status"] == "running":
                db.execute("UPDATE attempt SET cancel_requested=1 WHERE run_id=? AND number=?", (run_id, state["attempt"]))
                self._event(db, run_id, state["attempt"], "cancel_requested")
            else:
                raise ValueError("cancel requires an active research run")
            return self._status(db, run_id)

    def result(self, run_id, operation_id):
        with self._db(write=True) as db:
            state = self._status(db, run_id)
            if state["status"] != "completed":
                raise ValueError("research result is not complete")
            with self._run(run_id) as fd:
                raw = self._read(fd, "result.json")
            expected = db.execute("SELECT result_sha FROM run WHERE id=?", (run_id,)).fetchone()[0]
            if hashlib.sha256(raw).hexdigest() != expected:
                raise ValueError("immutable research result changed")
            if not self._operation(db, operation_id, run_id, "result"):
                db.execute("INSERT INTO exposure(run_id,operation_id,at) VALUES(?,?,?)",
                           (run_id, operation_id, datetime.now(timezone.utc).isoformat()))
                self._event(db, run_id, state["attempt"], "exposed")
            return json.loads(raw)

    def _child(self, request, payload, run_id, worker_fd):
        script = Path(__file__).resolve().parents[2] / "scripts/research_studio_worker.py"
        envelope = canonical_bytes({"request": request, "snapshot": base64.b64encode(payload).decode(), "parent": os.getpid()})
        process = subprocess.Popen([sys.executable, str(script)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, pass_fds=(worker_fd,))
        reply, errors = [], []
        def communicate():
            try:
                reply.append(process.communicate(envelope))
            except Exception as exc:
                errors.append(exc)
        thread = threading.Thread(target=communicate, daemon=True)
        thread.start()
        try:
            while thread.is_alive():
                if self.status(run_id)["cancel_requested"]:
                    process.terminate()
                    try:
                        process.wait(timeout=.4)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=.4)
                    raise Cancelled()
                thread.join(.025)
            if errors or process.returncode != 0 or not reply or len(reply[0][0]) > MAX_BYTES:
                raise ValueError("research calculation child failed")
            envelope = json.loads(reply[0][0])
            return envelope["result"], envelope["worker_metrics"]
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()
            thread.join(timeout=1)

    def work_once(self, *, compute=None):
        with self._lock("worker.lock", nonblocking=True) as worker_fd:
            with self._db(write=True) as db:
                dead = db.execute("SELECT run_id,number,cancel_requested FROM attempt WHERE state='running'").fetchall()
                for run_id, attempt, cancelled in dead:
                    state = "cancelled" if cancelled else "failed"
                    db.execute("UPDATE attempt SET state=?,reason=? WHERE run_id=? AND number=?",
                               (state, "interrupted worker; explicit retry required", run_id, attempt))
                    self._event(db, run_id, attempt, state, "interrupted worker; explicit retry required")
                chosen = db.execute("SELECT a.run_id,a.number FROM attempt a JOIN run r ON r.id=a.run_id WHERE a.state='queued' ORDER BY r.created,a.number LIMIT 1").fetchone()
                if chosen is None:
                    return {"status": "idle"}
                run_id, attempt = chosen
                db.execute("UPDATE attempt SET state='running' WHERE run_id=? AND number=?", chosen)
                self._event(db, run_id, attempt, "running")
            try:
                with self._db() as db:
                    request = self._request(db, run_id)  # Date/identity checks before prepared payload open.
                if request["code_id"] != code_identity():
                    raise ValueError("analysis code changed; submit a fresh snapshot")
                with self._run(run_id) as fd:
                    payload = self._read(fd, "snapshot.json.gz")
                if hashlib.sha256(payload).hexdigest() != request["snapshot_sha256"]:
                    raise ValueError("immutable prepared snapshot changed")
                if compute is None:
                    result, metrics = self._child(request, payload, run_id, worker_fd)
                else:  # Owner-injected fixture computations, never a CLI selector.
                    metrics = None
                    snapshot = decode_snapshot(payload)
                    if snapshot.engine_fingerprint != engine_fingerprint() or snapshot.identity != request["data_id"]:
                        raise ValueError("prepared snapshot identity mismatch")
                    result = compute(Observations(snapshot), parse_definition(request["definition"]), request["code_id"],
                                     cancel=lambda: self.status(run_id)["cancel_requested"])
                if result["run_id"] != run_id:
                    raise ValueError("analysis result identity mismatch")
                with self._db(write=True) as db:
                    if self._status(db, run_id)["cancel_requested"]:
                        raise Cancelled()
                    raw = canonical_bytes(result)
                    with self._run(run_id) as fd:
                        self._immutable(fd, "result.json", raw)
                    db.execute("UPDATE run SET result_sha=? WHERE id=?", (hashlib.sha256(raw).hexdigest(), run_id))
                    db.execute("UPDATE attempt SET state='completed' WHERE run_id=? AND number=?", (run_id, attempt))
                    self._event(db, run_id, attempt, "completed", json.dumps(metrics) if metrics else None)
            except (Exception, KeyboardInterrupt) as exc:
                state = "cancelled" if isinstance(exc, (Cancelled, KeyboardInterrupt)) else "failed"
                reason = ("explicit cancellation" if isinstance(exc, Cancelled) else "worker interrupted"
                          if isinstance(exc, KeyboardInterrupt) else f"analysis failed ({type(exc).__name__}): {str(exc)[:300]}")
                with self._db(write=True) as db:
                    db.execute("UPDATE attempt SET state=?,reason=? WHERE run_id=? AND number=?", (state, reason, run_id, attempt))
                    self._event(db, run_id, attempt, state, reason)
            return self.status(run_id)
