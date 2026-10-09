"""ASGI authorization covers routes before their handlers and provider reads."""
from fastapi import HTTPException, Request
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse
from starlette.routing import Match
from sqlmodel import Session

from app.database import engine
from app.engine import access
from app.access_manifest import DOMAIN_ROUTES


def registered_routes(routes):
    # Newer FastAPI keeps included routers nested and exposes their effective
    # contexts. Older releases already return flattened APIRoutes.
    try:
        from fastapi.routing import iter_route_contexts
    except ImportError:
        return iter(routes)
    return iter_route_contexts(routes)


class AccessMiddleware:
    def __init__(self, app, routes):
        self.app, self.routes = app, routes

    def resolve(self, request):
        for route in registered_routes(self.routes):
            match, child = route.matches(request.scope)
            if match == Match.FULL:
                operation = f"{request.method} {route.path}"
                if operation not in DOMAIN_ROUTES | access.AUTH_PATHS:
                    raise HTTPException(404, "Not found")
                if operation in {"GET /access/challenge", "POST /access/login", "POST /access/bootstrap"}:
                    access.gateway(request)
                    return operation
                if operation.startswith("GET /cloud-mcp/"):
                    from app.engine import cloud_practice_access
                    from cloud_mcp_d1_common import READ_PATHS
                    if operation not in READ_PATHS:
                        raise HTTPException(404, "Not found")
                    request.state.access = cloud_practice_access.identify(request)
                    return operation
                request.state.access = access.identify(request)
                access.authorize(request, operation, child.get("path_params", {}))
                return operation
        raise HTTPException(404, "Not found")

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        request = Request(scope)
        if not access.enabled():
            # Legacy access is confined to the existing private installation.
            # A configured assistant gateway must never operate against it.
            if request.headers.get("x-tj-gateway") or request.url.path.startswith("/access"):
                return await JSONResponse({"detail": "App authentication is disabled"}, 503)(scope, receive, send)
            return await self.app(scope, receive, send)
        if request.method == "GET" and request.url.path == "/health" and not any(request.headers.get(h) for h in ("x-tj-gateway", "x-tj-service")):
            return await JSONResponse({"status": "ok"}, headers={"Cache-Control": "no-store"})(scope, receive, send)
        try:
            if request.headers.get("content-length") and int(request.headers["content-length"]) > 16_000_000:
                raise HTTPException(413, "Request too large")
            operation = await run_in_threadpool(self.resolve, request)
        except (ValueError, HTTPException) as exc:
            code = exc.status_code if isinstance(exc, HTTPException) else 400
            def record_denial():
                with Session(engine) as db:
                    access.audit(db, getattr(getattr(request.state, "access", None), "identifier", None), "request", "denied")
                    db.commit()
            await run_in_threadpool(record_denial)
            return await JSONResponse({"detail": exc.detail if isinstance(exc, HTTPException) else "Invalid request"}, code,
                headers={"Cache-Control": "no-store"})(scope, receive, send)
        status = 500
        async def guarded_send(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message["headers"] = [(k, v) for k, v in message.get("headers", []) if k.lower() != b"cache-control"] + [(b"cache-control", b"no-store")]
            await send(message)
        received = 0
        who = getattr(request.state, "access", None)
        maximum = 16_384 if (request.url.path.startswith("/access/")
            or (who and who.grants.get("market_decision_write"))) else 16_000_000
        async def bounded_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > maximum:
                    raise HTTPException(413, "Request too large")
            return message
        await self.app(scope, bounded_receive, guarded_send)
        if request.method not in {"GET", "HEAD"} and operation not in {"POST /access/login", "POST /access/bootstrap"}:
            def record():
                with Session(engine) as db:
                    access.audit(db, getattr(getattr(request.state, "access", None), "identifier", None), operation, "accepted" if status < 400 else "rejected")
                    db.commit()
            await run_in_threadpool(record)
