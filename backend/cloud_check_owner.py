"""Owner-only Unix reader for the pre-trade check ledger. No OAuth, writes or network.

Serves `/advisor-review` through the private owner frontend: a bounded list of
saved checks, one check reopened with its integrity verified, and a grade of
the last 30 days from the results the check service saved. Runs as the
check service UID against its own SQLite file, opened read-only with
`query_only`; the ledger's triggers also refuse updates and deletes. The peer
is identified by the kernel (SO_PEERCRED), never a header or claim.
See docs/agent/advisor-pretrade-check-contract.md.
"""
import os
import sys

if __name__ == "__main__" and os.environ.get("TJ_CHECK_OWNER_CLEAN") != "1":
    os.execve(sys.executable, [sys.executable, "-B", *sys.argv], {
        "PATH": "/usr/bin:/bin", "PYTHON_DOTENV_DISABLED": "1", "TJ_CHECK_OWNER_CLEAN": "1",
        **{k: os.environ[k] for k in ("LISTEN_PID", "LISTEN_FDS") if k in os.environ}})

import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import socket
import sqlite3
import stat
import struct
import time
from urllib.parse import quote

from fastapi import FastAPI
from pydantic import Field, field_validator
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse
from uvicorn.protocols.http.h11_impl import H11Protocol

from cloud_mcp_d0 import MAX_BYTES, Strict

LIST_PATH = "/owner/checks"
CHECK_PATH = re.compile(r"^/owner/checks/(chk_[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$")
LIST_LIMIT = 50
GRADES_PATH = "/owner/grades"
LIST_SCHEMA = "check-owner-list-v1"
DETAIL_SCHEMA = "check-owner-detail-v1"
GRADES_SCHEMA = "check-owner-grades-v1"
GRADE_DAYS = 30
GRADE_LIMIT = 1000


def exact_path(value):
    path = Path(value)
    if not path.is_absolute() or str(path) != value or ".." in path.parts or any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("Require an exact operator-owned path without symlinks")
    return path


class OwnerConfig(Strict):
    enabled: bool = False
    peer_uid: int = Field(ge=1)
    socket_path: str
    ledger_path: str

    @field_validator("socket_path", "ledger_path")
    @classmethod
    def exact(cls, value):
        exact_path(value)
        return value


def read_config(path):
    path = exact_path(str(path))
    if not path.is_file() or path.stat().st_mode & 0o022:
        raise ValueError("Owner configuration must not be group/world writable")
    with path.open("rb") as handle:
        body = handle.read(MAX_BYTES + 1)
    if len(body) > MAX_BYTES:
        raise ValueError("Owner configuration exceeds its bound")
    return OwnerConfig.model_validate_json(body)


def connect(path):
    path = exact_path(str(path))
    if not stat.S_ISREG(path.stat().st_mode):
        raise ValueError("Ledger must be a regular file")
    db = sqlite3.connect(f"file:{quote(str(path))}?mode=ro", uri=True, timeout=2)
    db.execute("PRAGMA query_only=ON")
    deadline = time.monotonic() + 2
    db.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
    return db


def list_checks(path):
    """Newest checks first: idea, rules verdict, Jo's verdict and timing only."""
    db = connect(path)
    try:
        rows = db.execute("SELECT c.record_json, v.verdict FROM check_record c LEFT JOIN model_verdict v"
            " ON v.check_id = c.check_id ORDER BY c.received_at DESC, c.check_id DESC LIMIT ?", (LIST_LIMIT,)).fetchall()
        total = db.execute("SELECT count(*) FROM check_record").fetchone()[0]
    finally:
        db.close()
    checks = []
    for body, model in rows:
        record = json.loads(body)
        idea = record["idea"]
        checks.append({"check_id": record["check_id"], "received_at": record["received_at"],
            "ticker": idea.get("ticker"), "side": idea.get("side"), "instrument": idea.get("instrument"),
            "option_type": idea.get("option_type"), "horizon": idea.get("horizon"),
            "verdict": record["answer"]["verdict"], "model_verdict": model,
            "total_ms": record["timings_ms"]["total"]})
    return {"schema_version": LIST_SCHEMA, "checks": checks, "total": total, "limit": LIST_LIMIT,
        "read_at": datetime.now(timezone.utc).isoformat()}


def saved_results(db, check_ids):
    """Final results the check service saved, verified; none before its first save creates the table."""
    if not check_ids or db.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'check_result'").fetchone() is None:
        return {}
    rows = db.execute("SELECT check_id, result_json, result_sha256 FROM check_result WHERE check_id IN ("
        + ",".join("?" * len(check_ids)) + ")", list(check_ids)).fetchall()
    results = {}
    for check_id, body, sha in rows:
        if hashlib.sha256(body.encode()).hexdigest() != sha:
            raise ValueError("Check result integrity failed")
        results[check_id] = json.loads(body)
    return results


def grade_checks(path, now=None):
    """Checks from the last 30 days graded from their saved final results only; the rest count as pending."""
    from app.engine.pretrade_check import grade_results

    now = now or datetime.now(timezone.utc)
    db = connect(path)
    try:
        rows = db.execute("SELECT c.check_id, c.record_json, c.record_sha256, v.verdict FROM check_record c LEFT JOIN"
            " model_verdict v ON v.check_id = c.check_id WHERE c.received_at >= ? ORDER BY c.received_at LIMIT ?",
            ((now - timedelta(days=GRADE_DAYS)).isoformat(), GRADE_LIMIT)).fetchall()
        results = saved_results(db, [row[0] for row in rows])
    finally:
        db.close()
    items = []
    for check_id, body, sha, model in rows:
        if hashlib.sha256(body.encode()).hexdigest() != sha:
            raise ValueError("Check record integrity failed")
        if check_id in results:
            items.append({"verdict": json.loads(body)["answer"]["verdict"], "model_verdict": model, **results[check_id]})
    return {"schema_version": GRADES_SCHEMA, "days": GRADE_DAYS, "checks": len(rows), "settled": len(items),
        "grade": grade_results(items), "read_at": now.isoformat()}


def read_check(path, check_id):
    """One saved check exactly as stored, after its integrity hash is verified."""
    db = connect(path)
    try:
        row = db.execute("SELECT record_json, record_sha256 FROM check_record WHERE check_id = ?", (check_id,)).fetchone()
        model = db.execute("SELECT received_at, verdict, summary FROM model_verdict WHERE check_id = ?",
            (check_id,)).fetchone()
        result = saved_results(db, [check_id]).get(check_id)
    finally:
        db.close()
    if row is None:
        return None
    if hashlib.sha256(row[0].encode()).hexdigest() != row[1]:
        raise ValueError("Check record integrity failed")
    record = json.loads(row[0])
    answer = record["answer"]
    # Hashed fill keys become a count; the raw provider packet stays behind its hash.
    history = {k: v for k, v in answer["history"].items() if k != "source_fill_keys"}
    history["trades_used"] = len(answer["history"].get("source_fill_keys") or [])
    return {"schema_version": DETAIL_SCHEMA, "check_id": record["check_id"], "received_at": record["received_at"],
        "record_sha256": row[1], "idea": record["idea"], "free_text": record.get("free_text"),
        "answer": {**answer, "history": history}, "features": record["features"],
        "live_context_sha256": record["live_context"]["sha256"], "timings_ms": record["timings_ms"],
        "errors": record["errors"],
        "model_verdict": None if model is None else {"received_at": model[0], "verdict": model[1], "summary": model[2]},
        "result": result, "read_at": datetime.now(timezone.utc).isoformat()}


def socket_identity(config):
    info = exact_path(config.socket_path).stat()
    if not stat.S_ISSOCK(info.st_mode) or info.st_mode & 0o007:
        raise ValueError("Owner socket permissions changed")
    return (info.st_dev, info.st_ino, info.st_uid, info.st_gid, info.st_mode)


def create_app(config_path):
    if os.environ.get("PYTHON_DOTENV_DISABLED") != "1":
        raise ValueError("Check owner reader requires disabled dotenv loading")
    initial = read_config(config_path)
    initial_socket = socket_identity(initial)
    list_checks(initial.ledger_path)  # Refuse to serve a missing or foreign ledger.
    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
    slots = asyncio.Semaphore(4)

    def current():
        config = read_config(config_path)
        if not config.enabled or config.model_dump(exclude={"enabled"}) != initial.model_dump(exclude={"enabled"}):
            raise ValueError("Check owner reader disabled or changed")
        if socket_identity(config) != initial_socket:
            raise ValueError("Owner socket changed")
        return config

    @app.middleware("http")
    async def guard(request, call_next):
        path = request.url.path
        match = CHECK_PATH.fullmatch(path)
        if request.method != "GET" or (path not in (LIST_PATH, GRADES_PATH) and match is None) or request.url.query:
            return JSONResponse({"detail": "Not found"}, 404)
        headers = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}
        try:
            config = current()
            if request.scope.get("check_owner_peer_uid") != config.peer_uid:
                return JSONResponse({"detail": "Owner peer required"}, 403, headers=headers)
            if (sum(len(k) + len(v) for k, v in request.scope["headers"]) > 16384
                    or request.headers.get("content-length", "0") != "0"
                    or any(k in request.headers for k in ("transfer-encoding", "authorization", "cookie"))):
                return JSONResponse({"detail": "Check owner reader accepts no credentials or body"}, 400, headers=headers)
            if slots.locked():
                return JSONResponse({"detail": "Check owner reader busy"}, 429, headers=headers)
            async with slots:
                if path == GRADES_PATH:
                    value = await asyncio.wait_for(run_in_threadpool(grade_checks, config.ledger_path), 5)
                elif match is None:
                    value = await asyncio.wait_for(run_in_threadpool(list_checks, config.ledger_path), 5)
                else:
                    value = await asyncio.wait_for(run_in_threadpool(read_check, config.ledger_path, match[1]), 5)
                current()  # Refuse revocation/config drift during a read.
            if value is None:
                return JSONResponse({"detail": "Unknown check"}, 404, headers=headers)
            return JSONResponse(value, headers=headers)
        except Exception:
            return JSONResponse({"detail": "Pre-trade check review unavailable"}, 503, headers=headers)

    return app


def peer_uid(peer):
    if not peer or peer.family != socket.AF_UNIX:
        return None
    if hasattr(socket, "SO_PEERCRED"):
        return struct.unpack("3i", peer.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))[1]
    if sys.platform == "darwin":  # Local proof only; retained units target Linux.
        import ctypes
        uid, gid = ctypes.c_uint(), ctypes.c_uint()
        function = ctypes.CDLL(None, use_errno=True).getpeereid
        function.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_uint), ctypes.POINTER(ctypes.c_uint)]
        function.restype = ctypes.c_int
        if function(peer.fileno(), ctypes.byref(uid), ctypes.byref(gid)) == 0:
            return uid.value
    return None


class OwnerProtocol(H11Protocol):
    def connection_made(self, transport):
        super().connection_made(transport)
        uid = peer_uid(transport.get_extra_info("socket"))
        original = self.app

        async def identified(scope, receive, send):
            scope["check_owner_peer_uid"] = uid
            return await original(scope, receive, send)
        self.app = identified


def listening_fd(config):
    if os.environ.get("LISTEN_PID") != str(os.getpid()) or os.environ.get("LISTEN_FDS") != "1":
        raise ValueError("Require exactly one inherited Unix listener")
    with socket.socket(fileno=os.dup(3)) as listener:
        if (listener.family != socket.AF_UNIX or listener.type != socket.SOCK_STREAM
                or listener.getsockname() != config.socket_path
                or (sys.platform != "darwin" and not listener.getsockopt(socket.SOL_SOCKET, socket.SO_ACCEPTCONN))):
            raise ValueError("Check owner reader requires its exact listening Unix socket")
    return 3


if __name__ == "__main__":
    import argparse
    import uvicorn
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    args = parser.parse_args()
    config = read_config(args.config)
    if not config.enabled:
        raise ValueError("Check owner reader is disabled")
    uvicorn.run(create_app(args.config), fd=listening_fd(config), http=OwnerProtocol,
        access_log=False, proxy_headers=False, limit_concurrency=8, timeout_keep_alive=2)
