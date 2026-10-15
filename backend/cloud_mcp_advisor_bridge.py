"""Dormant advisor-only Unix backend app. Never mounted in the owner API."""
import os
import sys

# Clean before importing engines that may load .env. Re-exec preserves the
# inherited socket FD and PID; no token/database credentials enter the process.
if __name__ == "__main__" and os.environ.get("TJ_ADVISOR_MCP_CLEAN_PROCESS") != "1":
    os.execve(sys.executable, [sys.executable, "-B", *sys.argv], {
        "PATH": os.environ.get("PATH", ""), "PYTHON_DOTENV_DISABLED": "1",
        "TJ_ADVISOR_MCP_CLEAN_PROCESS": "1", **{k: os.environ[k] for k in ("LISTEN_PID", "LISTEN_FDS") if k in os.environ}})

import asyncio
import json
from pathlib import Path
import uuid

from fastapi import FastAPI, HTTPException, Request
from sqlmodel import Session, create_engine
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse

from app.engine import advisor_shadow as service, advisor_assignments as managed, decisions
from app.models import PracticeAgentCall
from app.schema import ensure_current
from cloud_mcp_advisor_common import (AdvisorVerifier, PROFILE_SCOPE, READ_SCOPE,
    WRITE_SCOPE, READ_PATH, WRITE_PATH, REQUEST_KEYS, SCHEMA, private_fixture, read_config, reject_credentials)
from cloud_mcp_d0 import RequestLimits, activated_socket

MANAGE_PATH = "/owner/advisor/assignments"
PATHS = frozenset({("GET", READ_PATH), ("POST", WRITE_PATH), ("GET", MANAGE_PATH), ("POST", MANAGE_PATH)})
UNAVAILABLE = "Advisor request or permission unavailable"


class AdvisorBounds(RequestLimits):
    def __init__(self, app):
        super().__init__(app)
        self.slots = asyncio.Semaphore(4)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await super().__call__(scope, receive, send)
        if (scope["method"], scope["path"]) not in PATHS:
            return await JSONResponse({"detail": "Not found"}, status_code=404)(scope, receive, send)
        if self.slots.locked():
            return await JSONResponse({"detail": "Advisor busy; read receipt before retry"}, status_code=429)(scope, receive, send)
        async with self.slots:
            await super().__call__(scope, receive, send)


def validate_binding(profile, call, config, packet, advisor):
    service.active_assignment(config)
    if not advisor or advisor.get("version") != service.HANDOFF_VERSION:
        raise decisions.DecisionError(UNAVAILABLE)
    exported = advisor["export"]
    if (exported["version"] != service.HANDOFF_VERSION or str(call.id) != profile.assignment_id or str(call.run_id) != profile.run_id
            or config["packet_sha256"] != profile.packet_sha256
            or exported["packet_sha256"] != profile.packet_sha256
            or exported["request_sha256"] != profile.request_sha256
            or exported["assignment_id"] != profile.assignment_id or exported["run_id"] != profile.run_id
            or exported["packet"] != packet
            or exported["expires_at"] != config["expires_at"]
            or service.digest({key: exported[key] for key in REQUEST_KEYS}) != profile.request_sha256):
        raise decisions.DecisionError(UNAVAILABLE)
    saved = advisor["receipt"]
    if saved is not None:
        if (saved["receipt_sha256"] != service.digest({k: v for k, v in saved.items() if k != "receipt_sha256"})
                or any(saved[key] != exported[key] for key in ("version", "assignment_id", "run_id", "packet_sha256", "request_sha256"))
                or any(saved["submitted_output"][key] != exported[key] for key in ("version", "assignment_id", "run_id", "packet_sha256", "request_sha256"))
                or saved["submitted_output"]["answer"] != advisor["response"]):
            raise decisions.DecisionError(UNAVAILABLE)
    return exported


def build_app(engine, config_path):
    verifier = AdvisorVerifier(config_path)
    profile = verifier.config.profiles[0]
    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
    app.add_middleware(AdvisorBounds)

    def bearer(request):
        headers = request.headers.getlist("authorization")
        if (len(headers) != 1 or not headers[0].startswith("Bearer ") or request.query_params
                or any(name in request.headers for name in ("cookie", "x-tj-service", "x-tj-gateway", "x-tj-bootstrap"))):
            raise HTTPException(401, UNAVAILABLE)
        return headers[0][7:]

    def authorize(token, write=False):
        if verifier.config.owner_reader_uid is not None:
            try:
                private_fixture(engine.url.database, owner_reader_uid=verifier.config.owner_reader_uid)
            except (ValueError, OSError):
                raise HTTPException(503, UNAVAILABLE) from None
        checked = asyncio.run(verifier.verify_token(token))
        needed = {PROFILE_SCOPE, READ_SCOPE, *([WRITE_SCOPE] if write else [])}
        if checked is None or not needed <= set(checked.scopes):
            raise HTTPException(401, UNAVAILABLE)

    def project(db):
        if verifier.config.assignment_management:
            entry = managed.selected(db, profile)
            return service.bounded({"schema_version": SCHEMA, "demo_only": True,
                "delivery_transport": "oauth-mcp", "request_origin_transport": entry["request"]["transport"],
                "request": entry["request"], "receipt": entry["receipt"],
                "recovery": "Read the current request and compare its exact receipt before an explicit retry."})
        call = db.get(PracticeAgentCall, uuid.UUID(profile.assignment_id))
        if not call:
            raise decisions.DecisionError(UNAVAILABLE)
        _, config, packet = service.assignment(db, call)
        advisor = config.get("advisor")
        exported = validate_binding(profile, call, config, packet, advisor)
        # Never project owner_view: it contains broader shadow/session state.
        return service.bounded({"schema_version": SCHEMA, "demo_only": True,
            "delivery_transport": "oauth-mcp", "request_origin_transport": exported["transport"],
            "request": exported, "receipt": advisor["receipt"],
            "recovery": "After an uncertain save read get_advisor_request and compare the complete submitted_output before an explicit retry. No automatic retry or fallback."})

    @app.get(READ_PATH)
    def get_request(request: Request):
        token = bearer(request)
        authorize(token)
        try:
            with Session(engine) as db:
                service.lock(db)
                result = project(db)
                authorize(token)
                project(db)  # assignment expiry is checked again before exposure
                return result
        except (decisions.DecisionError, KeyError, TypeError, ValueError):
            raise HTTPException(403, UNAVAILABLE) from None

    @app.post(WRITE_PATH)
    async def save(request: Request):
        token = bearer(request)
        try:
            body = json.loads(await request.body())
            if (not isinstance(body, dict) or set(body) != {"packet_sha256", "request_sha256", "answer"}
                    or (not verifier.config.assignment_management and
                        (body["packet_sha256"] != profile.packet_sha256 or body["request_sha256"] != profile.request_sha256))):
                raise ValueError()
        except (ValueError, UnicodeError):
            raise HTTPException(422, "Use the assigned packet/request hashes and one bounded answer") from None

        def commit():
            authorize(token, write=True)
            with Session(engine) as db:
                def check(call, config, packet, advisor):
                    authorize(token, write=True)
                    validate_binding(profile, call, config, packet, advisor)
                # Server derives the envelope, assignment, run and version.
                envelope = {"version": service.HANDOFF_VERSION, "assignment_id": profile.assignment_id,
                    "run_id": profile.run_id, **body}
                try:
                    if verifier.config.assignment_management:
                        receipt = managed.save(db, profile, body, lambda: authorize(token, write=True))
                        return service.bounded({"schema_version": SCHEMA, "demo_only": True,
                            "delivery_transport": "oauth-mcp", "receipt": receipt})
                    result = service.advisor_import(db, uuid.UUID(profile.run_id), envelope,
                        transport="oauth-mcp", authorize=check)
                    return service.bounded({"schema_version": SCHEMA, "demo_only": True,
                        "delivery_transport": "oauth-mcp", "receipt": result["advisor"]["receipt"]})
                except (decisions.DecisionError, KeyError, TypeError, ValueError):
                    raise HTTPException(409, "Advisor save refused; retrieve its immutable receipt before retrying") from None
        return await run_in_threadpool(commit)

    def owner_authorize(request):
        if not verifier.config.assignment_management:
            raise HTTPException(404, "Not found")
        current = verifier.active_config()
        if (current is None or not current.assignment_management or current.owner_peer_uid is None
                or request.scope.get("advisor_owner_peer_uid") != current.owner_peer_uid):
            raise HTTPException(403, "Dedicated owner Unix peer required")
        if any(k in request.headers for k in ("authorization", "cookie", "x-tj-gateway", "x-tj-service", "x-tj-bootstrap")):
            raise HTTPException(403, "Owner management accepts no forwarded credentials")
        private_fixture(engine.url.database, owner_reader_uid=current.owner_reader_uid)

    @app.get(MANAGE_PATH)
    def owner_questions(request: Request):
        owner_authorize(request)
        if set(request.query_params) - {"assignment_id"} or len(request.query_params.getlist("assignment_id")) > 1:
            raise HTTPException(400, "Use one assignment selector")
        if request.headers.get("content-length", "0") != "0" or request.headers.get("transfer-encoding"):
            raise HTTPException(400, "Owner read accepts no body")
        try:
            with Session(engine) as db:
                service.lock(db)
                result = managed.owner_view(db, profile, request.query_params.get("assignment_id"))
                owner_authorize(request)
                return JSONResponse(result, headers={"Cache-Control": "no-store"})
        except (decisions.DecisionError, ValueError, KeyError, TypeError):
            raise HTTPException(409, "Advisor assignments unavailable") from None

    @app.post(MANAGE_PATH)
    async def owner_change(request: Request):
        owner_authorize(request)
        if request.query_params:
            raise HTTPException(400, "Owner write accepts no selector")
        try:
            body = json.loads(await request.body())
            if not isinstance(body, dict):
                raise ValueError()
        except (ValueError, UnicodeError):
            raise HTTPException(422, "Supply a bounded management action") from None
        def change():
            with Session(engine) as db:
                try:
                    result = managed.mutate(db, profile, body, lambda: owner_authorize(request))
                    return JSONResponse(result, headers={"Cache-Control": "no-store"})
                except (decisions.DecisionError, ValueError, KeyError, TypeError) as exc:
                    raise HTTPException(409, str(exc) if isinstance(exc, decisions.DecisionError) else "Invalid management action") from None
        return await run_in_threadpool(change)

    @app.exception_handler(Exception)
    async def unavailable(request, exc):
        return JSONResponse({"detail": "Advisor unavailable; retrieve receipt before retrying"}, status_code=503)

    return app


def create_app(config_path, database_path):
    reject_credentials()
    if os.environ.get("PYTHON_DOTENV_DISABLED") != "1":
        raise ValueError("Advisor backend requires disabled dotenv loading")
    path = Path(database_path)
    if not path.is_absolute() or str(path) != str(database_path) or ".." in path.parts or not path.is_file():
        raise ValueError("Require an existing private isolated fixture SQLite file")
    private_fixture(path, owner_reader_uid=read_config(config_path).owner_reader_uid)
    engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False, "timeout": 2})
    ensure_current(engine)
    verifier = AdvisorVerifier(config_path)
    with Session(engine) as db:
        call = db.get(PracticeAgentCall, uuid.UUID(verifier.config.profiles[0].assignment_id))
        if not call:
            raise ValueError("Assigned fixture unavailable")
        _, config, packet = service.assignment(db, call)
        if verifier.config.assignment_management:
            managed.anchor(db, verifier.config.profiles[0])
        else:
            validate_binding(verifier.config.profiles[0], call, config, packet, config.get("advisor"))
    return build_app(engine, config_path)


if __name__ == "__main__":
    import argparse
    import uvicorn
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--database", type=Path, required=True)
    args = parser.parse_args()
    verifier = AdvisorVerifier(args.config)
    fd = activated_socket(verifier.config)
    from cloud_advisor_owner import OwnerProtocol
    uvicorn.run(create_app(args.config, args.database), fd=fd, http=OwnerProtocol, access_log=False,
        proxy_headers=False, ws="none", loop="asyncio", log_level="warning", limit_concurrency=4, timeout_keep_alive=5)
