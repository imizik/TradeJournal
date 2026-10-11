"""Explicitly started loopback-only, memory-only 30-second moomoo lab bridge.

Never imported by app.main, never loads the journal or starts on deployment.
Run with python -m scripts.moomoo_lab_server after configuring an ephemeral
TJ_MOOMOO_LAB_TOKEN shared with the local frontend server. No provider work
happens before an authenticated POST /session. Use one process/worker only.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
import json
import os
from pathlib import Path
import re
import secrets
import stat
import struct

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
import uvicorn

from scripts import moomoo_diagnostic as diagnostic

SESSION_SECONDS = 30  # Below the documented five-minute refresh recommendation.
SYSTEMD_CREDENTIAL_DIR = Path("/run/credentials/tradejournal-moomoo.service")


def validate_systemd_mode(info, *, directory=False):
    """systemd uses root-owned copies and a read-only service-user ACL."""
    kind = stat.S_ISDIR if directory else stat.S_ISREG
    expected = 0o550 if directory else 0o440
    if not kind(info.st_mode) or info.st_uid != 0 or info.st_gid != 0 or stat.S_IMODE(info.st_mode) != expected:
        raise diagnostic.DiagnosticError("Invalid systemd credential permissions.")


def validate_systemd_acl(raw, *, directory=False):
    permission = 5 if directory else 4
    undefined = 0xffffffff
    expected = {(1, permission, undefined), (2, permission, os.getuid()),
                (4, 0, undefined), (16, permission, undefined), (32, 0, undefined)}
    if len(raw) != 44 or struct.unpack("<I", raw[:4])[0] != 2 or {
        struct.unpack("<HHI", raw[offset:offset + 8]) for offset in range(4, 44, 8)
    } != expected:
        raise diagnostic.DiagnosticError("Invalid systemd credential access list.")


def read_systemd_credential(path):
    if path.parent != SYSTEMD_CREDENTIAL_DIR:
        raise diagnostic.DiagnosticError("Unexpected systemd credential directory.")
    validate_systemd_mode(path.parent.lstat(), directory=True)
    validate_systemd_acl(os.getxattr(path.parent, "system.posix_acl_access", follow_symlinks=False), directory=True)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as file:
        validate_systemd_mode(os.fstat(file.fileno()))
        validate_systemd_acl(os.getxattr(file.fileno(), "system.posix_acl_access"))
        data = file.read(16385)
        if len(data) > 16384:
            raise diagnostic.DiagnosticError("Credential file exceeds the size limit.")
        return data


def credentials():
    managed = os.environ.get("CREDENTIALS_DIRECTORY")
    directory = Path(managed or os.environ.get("TJ_MOOMOO_CREDENTIAL_DIR", str(diagnostic.KEY_DIR)))
    if not directory.is_absolute():
        raise diagnostic.DiagnosticError("Absolute credential directory required.")
    reader = read_systemd_credential if managed else diagnostic.secure_read
    appkey = reader(directory / "appkey").decode("ascii").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", appkey):
        raise diagnostic.DiagnosticError("Invalid credential format.")
    key = serialization.load_pem_private_key(reader(directory / "phase1-ed25519.pem"), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise diagnostic.DiagnosticError("Ed25519 key required.")
    return appkey, key


def check_credentials():
    """systemd preflight: reject bad setup without logging key parser errors."""
    try:
        credentials()
    except Exception:
        raise SystemExit("Secured moomoo credentials unavailable; details withheld.") from None


def create_app(*, token: str, runner=diagnostic.stream_probe, loader=credentials) -> FastAPI:
    if not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", token):
        raise ValueError("Local lab token must contain 32..128 URL-safe characters.")
    active = None

    @asynccontextmanager
    async def lifespan(app):
        yield
        if active is not None:
            active.cancel()
            with suppress(asyncio.CancelledError):
                await active

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    def authorize(request):
        if request.client is None or request.client.host not in ("127.0.0.1", "::1"):
            raise HTTPException(403, "Local requests only")
        if not secrets.compare_digest(request.headers.get("authorization", ""), "Bearer " + token):
            raise HTTPException(403, "Local lab authorization required")

    @app.get("/status")
    async def status(request: Request):
        authorize(request)
        # Capability only: deliberately never open credential files here.
        return {"enabled": True}

    @app.post("/session")
    async def session(request: Request):
        nonlocal active
        authorize(request)
        if request.headers.get("content-type") != "application/x-level2-start" or request.query_params:
            raise HTTPException(400, "Fixed lab session required")
        # The frontend sends no body. Bound the read before credential access.
        async for chunk in request.stream():
            if chunk:
                raise HTTPException(400, "Session takes no arguments")
        if active is not None and not active.done():
            raise HTTPException(409, "One lab session is already active")
        try:
            appkey, key = loader()
        except (OSError, ValueError, UnicodeError, diagnostic.DiagnosticError):
            raise HTTPException(503, "Local secured moomoo credentials unavailable") from None

        control = asyncio.Queue(maxsize=16)
        latest = None

        def observe(event):
            nonlocal latest
            if event["event"] == "book":
                latest = event  # Replace, never append market-depth history.
            else:
                control.put_nowait(event)

        async def run():
            try:
                report = await runner(appkey, key, SESSION_SECONDS, observer=observe)
                control.put_nowait({"event": "summary", "report": report})
            except asyncio.CancelledError:
                raise
            except Exception:
                # Do not log or reflect provider/credential-bearing exceptions.
                control.put_nowait({"event": "status", "phase": "failed"})
            finally:
                control.put_nowait({"event": "status", "phase": "closed"})

        active = asyncio.create_task(run())
        task = active

        async def events():
            nonlocal latest
            try:
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        event = await diagnostic.bounded_await(control.get(), 0.25)
                    except asyncio.TimeoutError:
                        event = latest
                        latest = None
                        if event is None:
                            continue
                    if event.get("event") == "summary" and latest is not None:
                        yield json.dumps(latest, separators=(",", ":"), allow_nan=False) + "\n"
                        latest = None
                    yield json.dumps(event, separators=(",", ":"), allow_nan=False) + "\n"
                    if event.get("phase") == "closed":
                        break
            finally:
                if not task.done():
                    task.cancel()
                # The provider finally-block unsubscribes and closes. Retain
                # ownership until it finishes; a new session cannot overlap it.
                with suppress(asyncio.CancelledError):
                    await asyncio.shield(task)
                latest = None

        return StreamingResponse(events(), media_type="application/x-ndjson", headers={
            "Cache-Control": "no-store", "X-Accel-Buffering": "no", "X-Content-Type-Options": "nosniff"})

    return app


def main():
    try:
        app = create_app(token=os.environ.get("TJ_MOOMOO_LAB_TOKEN", ""))
    except ValueError:
        raise SystemExit("Set a private ephemeral TJ_MOOMOO_LAB_TOKEN before starting the local lab.") from None
    # Fixed local endpoint. No reload, extra workers, file logging or startup
    # provider connections. Ctrl+C shuts down the active bounded session.
    uvicorn.run(app, host="127.0.0.1", port=8196, access_log=False, log_level="critical")


if __name__ == "__main__":
    main()
