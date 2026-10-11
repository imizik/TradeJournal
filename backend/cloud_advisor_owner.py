"""Dormant owner-only Unix reader. No OAuth, journal mounts or ledger writes."""
import os
import sys

if __name__ == "__main__" and os.environ.get("TJ_ADVISOR_OWNER_CLEAN") != "1":
    os.execve(sys.executable, [sys.executable, "-B", *sys.argv], {
        "PATH": "/usr/bin:/bin", "PYTHON_DOTENV_DISABLED": "1", "TJ_ADVISOR_OWNER_CLEAN": "1",
        **{k: os.environ[k] for k in ("LISTEN_PID", "LISTEN_FDS") if k in os.environ}})

import asyncio
from datetime import datetime, timezone
from pathlib import Path
import socket
import sqlite3
import struct
import time
from urllib.parse import quote
import uuid

from fastapi import FastAPI
from pydantic import Field, field_validator
from sqlalchemy.pool import NullPool
from sqlmodel import Session, create_engine
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse
from uvicorn.protocols.http.h11_impl import H11Protocol

from app.engine import advisor_shadow as service, decisions, practice
from app.models import PracticeAgentCall
from app.schema import ensure_current
from cloud_mcp_advisor_common import AdvisorProfile, REQUEST_KEYS, private_fixture, reject_credentials
from cloud_mcp_d0 import MAX_BYTES, Strict

READ_PATH = "/owner/advisor"


def private_path(value, *, file=False, reader_uid=None):
    path = Path(value)
    if not path.is_absolute() or str(path) != value or ".." in path.parts or any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("Require an exact operator-owned path without symlinks")
    if file:
        private_fixture(path, owner_reader_uid=reader_uid)
    return path


class OwnerConfig(Strict):
    enabled: bool = False
    peer_uid: int = Field(ge=1)
    socket_path: str
    socket_uid: int = Field(ge=0)
    reader_uid: int | None = Field(default=None, ge=1)
    database_path: str
    binding: AdvisorProfile

    @field_validator("socket_path", "database_path")
    @classmethod
    def exact_path(cls, value):
        private_path(value)
        return value


def read_config(path):
    path = private_path(str(path))
    if not path.is_file() or path.stat().st_mode & 0o022:
        raise ValueError("Owner configuration must not be group/world writable")
    with Path(path).open("rb") as handle:
        body = handle.read(MAX_BYTES + 1)
    if len(body) > MAX_BYTES:
        raise ValueError("Owner configuration exceeds its bound")
    return OwnerConfig.model_validate_json(body)


def socket_identity(config):
    path = private_path(config.socket_path)
    info = path.stat()
    import stat
    if not stat.S_ISSOCK(info.st_mode) or info.st_uid != config.socket_uid or info.st_mode & 0o007:
        raise ValueError("Owner socket permissions changed")
    return (info.st_dev, info.st_ino, info.st_uid, info.st_gid, info.st_mode)


def readonly_engine(path, *, reader_uid=None):
    def connect():
        private_path(str(path), file=True, reader_uid=reader_uid)
        connection = sqlite3.connect(f"file:{quote(str(path))}?mode=ro", uri=True, timeout=2,
            check_same_thread=False)
        connection.execute("PRAGMA query_only=ON")
        deadline = time.monotonic() + 2
        connection.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
        return connection
    return create_engine("sqlite://", creator=connect, poolclass=NullPool)


def project(engine, binding):
    # A single SQLite read transaction keeps all frozen-context/receipt reads
    # consistent, including when an advisor save completes during this GET.
    with Session(engine) as db:
        db.connection().exec_driver_sql("BEGIN")
        call = db.get(PracticeAgentCall, uuid.UUID(binding.assignment_id))
        if call is None or str(call.run_id) != binding.run_id:
            raise ValueError("Assigned owner fixture unavailable")
        _, config, packet = service.assignment(db, call)
        owner = service.owner_view(db, call.run_id)
        advisor = owner["advisor"]
        if not advisor or advisor.get("version") != service.HANDOFF_VERSION:
            raise ValueError("Versioned owner handoff unavailable")
        exported = advisor["export"]
        identity_keys = ("assignment_id", "run_id", "packet_sha256", "request_sha256")
        if (any(exported[k] != getattr(binding, k) for k in identity_keys)
                or exported["packet"] != packet or owner["packet_sha256"] != binding.packet_sha256
                or exported["version"] != service.HANDOFF_VERSION
                or exported["expires_at"] != config["expires_at"]
                or service.digest({k: exported[k] for k in REQUEST_KEYS}) != binding.request_sha256
                or exported["demo_only"] is not True):
            raise ValueError("Owner request identity changed")
        receipt = advisor["receipt"]
        if receipt is not None:
            envelope = receipt["submitted_output"]
            keys = ("version", *identity_keys)
            if (set(envelope) != {*keys, "answer"}
                    or any(receipt[k] != exported[k] or envelope[k] != exported[k] for k in keys)
                    or receipt["receipt_sha256"] != service.digest({k: v for k, v in receipt.items() if k != "receipt_sha256"})
                    or envelope["answer"] != advisor["response"]
                    or receipt["received_at"] != advisor["received_at"]
                    or receipt["transport"] not in {"manual-paste", "oauth-mcp"}
                    or receipt["demo_only"] is not True):
                raise ValueError("Owner receipt integrity changed")
            service.validate_handoff_answer(envelope["answer"], packet)
        elif advisor["response"] is not None or advisor["received_at"] is not None:
            raise ValueError("Owner receipt missing")
        # Expiry/revocation is intentionally not an owner recovery barrier.
        # No capabilities, choices, broader session state or database path leave.
        return service.bounded({"schema_version": "advisor-owner-review-v1", "demo_only": True,
            "request": exported, "receipt": receipt,
            "assignment": {"enabled": config["enabled"],
                "expired": practice.now_utc() >= decisions._utc(config["expires_at"], "expiry")},
            "read_at": datetime.now(timezone.utc).isoformat(),
            "recovery": "Owner read only. After an uncertain save, compare the complete saved receipt before any explicit advisor retry."})


def create_app(config_path):
    reject_credentials()
    if os.environ.get("PYTHON_DOTENV_DISABLED") != "1":
        raise ValueError("Owner reader requires disabled dotenv loading")
    initial = read_config(config_path)
    initial_socket = socket_identity(initial)
    if initial.reader_uid is not None and initial.reader_uid != os.geteuid():
        raise ValueError("Owner reader requires its exact dedicated UID")
    path = private_path(initial.database_path, file=True, reader_uid=initial.reader_uid)
    engine = readonly_engine(path, reader_uid=initial.reader_uid)
    ensure_current(engine)
    project(engine, initial.binding)
    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
    slots = asyncio.Semaphore(4)

    def current():
        config = read_config(config_path)
        if not config.enabled or config.model_dump(exclude={"enabled"}) != initial.model_dump(exclude={"enabled"}):
            raise ValueError("Owner reader disabled or changed")
        if socket_identity(config) != initial_socket:
            raise ValueError("Owner socket changed")
        private_path(config.database_path, file=True, reader_uid=config.reader_uid)
        return config

    @app.middleware("http")
    async def guard(request, call_next):
        if request.method != "GET" or request.url.path != READ_PATH or request.url.query:
            return JSONResponse({"detail": "Not found"}, 404)
        try:
            config = current()
            if request.scope.get("advisor_owner_peer_uid") != config.peer_uid:
                return JSONResponse({"detail": "Owner peer required"}, 403)
            headers = request.scope["headers"]
            if (sum(len(k) + len(v) for k, v in headers) > 16384
                    or request.headers.get("content-length", "0") != "0"
                    or any(k in request.headers for k in ("transfer-encoding", "authorization", "cookie", "x-tj-gateway", "x-tj-service", "x-tj-bootstrap"))):
                return JSONResponse({"detail": "Owner reader accepts no credentials or body"}, 400)
            if slots.locked():
                return JSONResponse({"detail": "Owner reader busy"}, 429)
            async with slots:
                value = await asyncio.wait_for(run_in_threadpool(project, engine, config.binding), 5)
                current()  # Refuse revocation/config drift during a read.
            return JSONResponse(value, headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})
        except Exception:
            return JSONResponse({"detail": "Owner advisor review unavailable"}, 503,
                headers={"Cache-Control": "no-store"})

    return app


class OwnerProtocol(H11Protocol):
    def connection_made(self, transport):
        super().connection_made(transport)
        peer = transport.get_extra_info("socket")
        # Linux SO_PEERCRED is read from the real connected Unix socket, never
        # a header, query, claimed UID or forwarded browser/OAuth credential.
        uid = peer_uid(peer)
        original = self.app
        async def identified(scope, receive, send):
            scope["advisor_owner_peer_uid"] = uid
            return await original(scope, receive, send)
        self.app = identified


def peer_uid(peer):
    if not peer or peer.family != socket.AF_UNIX:
        return None
    if hasattr(socket, "SO_PEERCRED"):
        return struct.unpack("3i", peer.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))[1]
    if sys.platform == "darwin":
        # Local disposable proof on macOS; retained units target Linux. Darwin's
        # getpeereid reads the same kernel identity, without accepting claims.
        import ctypes
        uid, gid = ctypes.c_uint(), ctypes.c_uint()
        function = ctypes.CDLL(None, use_errno=True).getpeereid
        function.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_uint), ctypes.POINTER(ctypes.c_uint)]
        function.restype = ctypes.c_int
        if function(peer.fileno(), ctypes.byref(uid), ctypes.byref(gid)) == 0:
            return uid.value
    return None


def listening_fd(config):
    if os.environ.get("LISTEN_PID") != str(os.getpid()) or os.environ.get("LISTEN_FDS") != "1":
        raise ValueError("Require exactly one inherited Unix listener")
    with socket.socket(fileno=os.dup(3)) as listener:
        # Darwin's AF_UNIX implementation does not expose SO_ACCEPTCONN;
        # disposable local fixtures bind/listen explicitly. Retained Linux
        # activation must additionally prove the inherited listener is accepting.
        if (listener.family != socket.AF_UNIX or listener.type != socket.SOCK_STREAM
                or listener.getsockname() != config.socket_path
                or (sys.platform != "darwin" and not listener.getsockopt(socket.SOL_SOCKET, socket.SO_ACCEPTCONN))):
            raise ValueError("Owner reader requires its exact listening Unix socket")
    return 3


if __name__ == "__main__":
    import argparse
    import uvicorn
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    args = parser.parse_args()
    config = read_config(args.config)
    if not config.enabled:
        raise ValueError("Owner reader is disabled")
    if config.reader_uid is None:
        raise ValueError("Retained owner command requires an exact dedicated read-only UID grant")
    uvicorn.run(create_app(args.config), fd=listening_fd(config), http=OwnerProtocol,
        access_log=False, proxy_headers=False, limit_concurrency=8, timeout_keep_alive=2)
