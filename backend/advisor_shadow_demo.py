"""Loopback fixture gateway. Not mounted in the private API or cloud MCP."""
import asyncio
import json
import os
from pathlib import Path
import sys
import uuid

# The supported executable re-execs before importing engines that load .env.
# No database/provider/model credentials are inherited into this demo process.
if __name__ == "__main__" and os.environ.get("TJ_ADVISOR_SHADOW_CLEAN_PROCESS") != "1":
    os.execve(sys.executable, [sys.executable, *sys.argv], {
        "PATH": os.environ.get("PATH", ""), "PYTHON_DOTENV_DISABLED": "1",
        "TJ_ADVISOR_SHADOW_CLEAN_PROCESS": "1"})

from fastapi import FastAPI, HTTPException, Request
from sqlmodel import Session, create_engine
from starlette.responses import JSONResponse

from app.engine import advisor_shadow as service, decisions
from app.schema import ensure_current

PATHS = frozenset({("GET", "/packet"), ("GET", "/receipt"), ("POST", "/choices")})
BODY_TIMEOUT_SECONDS = 10


class Bounds:
    """Bound entrance/body wait; SQLite locks have a separate two-second timeout."""
    def __init__(self, app):
        self.app = app
        self.slots = asyncio.Semaphore(4)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        if (scope["method"], scope["path"]) not in PATHS:
            return await JSONResponse({"detail": "Not found"}, status_code=404)(scope, receive, send)
        if self.slots.locked():
            return await JSONResponse({"detail": "Demo busy; read receipt before retry"}, status_code=429)(scope, receive, send)
        async with self.slots:
            chunks, size = [], 0
            async def collect():
                nonlocal size
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        return False
                    size += len(message.get("body", b""))
                    if size > service.MAX_BYTES:
                        return False
                    chunks.append(message.get("body", b""))
                    if not message.get("more_body"):
                        return True

            try:
                complete = await asyncio.wait_for(collect(), timeout=BODY_TIMEOUT_SECONDS)
                if not complete:
                    return await JSONResponse({"detail": "Demo byte bound exceeded or disconnected"}, status_code=413)(scope, receive, send)
            except asyncio.TimeoutError:
                return await JSONResponse({"detail": "Body deadline exceeded; read receipt before retry"}, status_code=408)(scope, receive, send)
            delivered = False

            async def buffered_receive():
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {"type": "http.request", "body": b"".join(chunks), "more_body": False}
                return await receive()

            await self.app(scope, buffered_receive, send)


def build_app(engine, assignment_id):
    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
    app.add_middleware(Bounds)

    def token(request):
        # Browser cookies, arbitrary headers and query parameters are not capabilities.
        headers = request.headers.getlist("authorization")
        if len(headers) != 1 or not headers[0].startswith("Bearer ") or request.query_params or request.headers.get("cookie"):
            raise HTTPException(401, "Demo capability unavailable")
        value = headers[0][7:]
        if len(value) != 43:
            raise HTTPException(401, "Demo capability unavailable")
        return value

    def read(request, kind):
        capability = token(request)
        try:
            with Session(engine) as db:
                service.lock(db)  # serialize the read snapshot with local grant revocation
                call, run, config, packet = service.authenticate(db, assignment_id, capability)
                if kind == "packet":
                    result = {"assignment_id": str(call.id), "packet_sha256": config["packet_sha256"],
                            "expires_at": config["expires_at"], "packet": packet,
                            "output_contract": {"assignment_id": str(call.id), "packet_sha256": config["packet_sha256"],
                                "choices": [{"opportunity_id": o["opportunity_id"], "decision": "take/wait/skip",
                                             "rationale": "bounded text"} for o in packet["opportunities"]]},
                            "recovery": "Read /receipt after an uncertain save before retrying; no fallback."}
                else:
                    result = service.receipt(db, call)
                service.authenticate(db, assignment_id, capability)
                return result
        except decisions.DecisionError as exc:
            raise HTTPException(403, "Demo capability or evidence unavailable") from exc

    @app.get("/packet")
    def packet(request: Request):
        return read(request, "packet")

    @app.get("/receipt")
    def receipt(request: Request):
        return read(request, "receipt")

    @app.post("/choices")
    async def choices(request: Request):
        capability = token(request)
        try:
            body = json.loads(await request.body())
            if not isinstance(body, dict):
                raise ValueError("Expected object")
        except (ValueError, UnicodeError) as exc:
            raise HTTPException(422, "Expected bounded JSON object") from exc
        # Authentication is independently repeated under the writer lock after body reception.
        from starlette.concurrency import run_in_threadpool

        def save():
            with Session(engine) as db:
                try:
                    return service.submit(db, assignment_id, capability, body)
                except (ValueError, KeyError, TypeError) as exc:
                    raise HTTPException(409, "Demo submission refused; read receipt before retry") from exc
        return await run_in_threadpool(save)

    @app.exception_handler(Exception)
    async def unavailable(request, exc):
        return JSONResponse({"detail": "Demo unavailable; read receipt before retry"}, status_code=503)

    return app


def create_app():
    """Explicit operator-owned file binding, never ambient DATABASE_URL/.env."""
    if os.environ.get("PYTHON_DOTENV_DISABLED") != "1":
        raise RuntimeError("Start through the clean demo executable; .env loading must be disabled")
    if any(value and (name.startswith(("OPENAI_", "AZURE_OPENAI", "ANTHROPIC_", "GEMINI_", "OPENROUTER_"))
                      or name in {"GOOGLE_API_KEY", "DATABASE_URL", "MIGRATION_DATABASE_URL", "ALPACA_API_KEY", "ALPACA_API_SECRET", "TRADIER_API_KEY"})
           for name, value in os.environ.items()):
        raise RuntimeError("Demo gateway refuses inherited model/provider/database credentials")
    config_path = Path(os.environ["TJ_ADVISOR_SHADOW_DEMO_CONFIG"])
    if not config_path.is_absolute() or config_path.stat().st_mode & 0o077:
        raise RuntimeError("Require an absolute private demo capability file")
    config = json.loads(config_path.read_text())
    if set(config) != {"database", "assignment_id", "capability"}:
        raise RuntimeError("Invalid demo file binding")
    db_path = Path(config["database"])
    if not db_path.is_absolute() or not db_path.is_file() or db_path.suffix != ".db":
        raise RuntimeError("Require an existing isolated SQLite demo file")
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False, "timeout": 2})
    ensure_current(engine)
    assignment_id = uuid.UUID(config["assignment_id"])
    with Session(engine) as db:
        # Revoked/expired files cannot restart a serving assignment.
        service.authenticate(db, assignment_id, config["capability"])
    return build_app(engine, assignment_id)


if __name__ == "__main__":
    import argparse
    import uvicorn

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("--port", type=int, default=8138)
    args = parser.parse_args()
    os.environ["TJ_ADVISOR_SHADOW_DEMO_CONFIG"] = str(args.config.resolve())
    uvicorn.run(create_app(), host="127.0.0.1", port=args.port, access_log=False)
