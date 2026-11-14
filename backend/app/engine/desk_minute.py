"""The desk's once-a-minute refresh as one request (``GET /copilot/desk/minute``, docs/copilot-lab.md § What an open desk asks).

Every minute the open desk re-reads its book, session, Watching list, what's moving, sparklines, Feed, unusual options,
scanner picks, armed plans, exposure, saved conversations and the centre chart. Each of those stays its own route (the
first read of each on a cold page still goes out on its own, so the book never waits on the slowest); the minute's
re-reads go out together here. Each named read is dispatched through the whole app, middleware included, as if the
browser had sent it with the same headers: the same access decision, the same timings, the same body and status. Only
the reads below are accepted; anything else answers 400 for that read alone, without being dispatched. No read of its
own, no provider call, no cache: the routes behind it keep theirs.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from urllib.parse import unquote, urlsplit

from app.engine import request_timing

log = logging.getLogger(__name__)

MAX_READS = 16
READ_SECONDS = 8.0  # one read past this answers 504 for itself, so a stuck provider never holds the minute's other reads
# The desk's minute reads (frontend lib/deskMinute.ts ``BATCHED``): read-only GETs.
PATHS = frozenset({
    "/copilot/desk/threads", "/copilot/desk/session", "/copilot/desk/watching", "/copilot/desk/moving",
    "/copilot/desk/feed", "/copilot/desk/sparks", "/copilot/unusual", "/copilot/scanner", "/copilot/tickets",
    "/copilot/exposure", "/copilot/investigations", "/copilot/desk/health", "/copilot/paper",
})
# The centre chart's minute bars: a thread id or ``symbol:NVDA``, in the characters the frontend proxy lets through.
CHART = re.compile(r"/copilot/desk/(?!\.\.?/)[A-Za-z0-9_.:-]+/chart")
_COPIED = ("type", "asgi", "http_version", "scheme", "server", "client", "root_path")
_DROPPED = {b"content-length", b"content-type", b"transfer-encoding"}


def allowed(path: str) -> bool:
    return path in PATHS or CHART.fullmatch(path) is not None


async def read_all(app, scope: dict, targets: list[str]) -> list[dict]:
    """Each target (a path with its query) answered as ``{"status", "body"}``, in order, side by side."""
    return list(await asyncio.gather(*(_bounded(app, scope, target) for target in targets)))


async def _bounded(app, scope: dict, target: str) -> dict:
    # Each read times itself as its own route (its own Server-Timing and timings entry), never under this request.
    request_timing._current.set(None)
    try:
        return await asyncio.wait_for(_one(app, scope, target), READ_SECONDS)
    except TimeoutError:
        log.warning("desk minute: a read ran past %.0f s", READ_SECONDS)
        return {"status": 504, "body": {"detail": "This read took too long; the next minute asks again."}}


async def _one(app, scope: dict, target: str) -> dict:
    parts = urlsplit(target)
    path = unquote(parts.path)
    if parts.scheme or parts.netloc or not allowed(path):
        return {"status": 400, "body": {"detail": "Not a desk minute read."}}
    sub = {key: scope[key] for key in _COPIED if key in scope}
    sub.update(method="GET", path=path, raw_path=parts.path.encode(), query_string=parts.query.encode(),
               headers=[(k, v) for k, v in scope.get("headers", []) if k.lower() not in _DROPPED])
    if "state" in scope:
        sub["state"] = {key: value for key, value in scope["state"].items() if key != "access"}
    status, chunks, sent = 500, [], False

    async def receive():
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": b"", "more_body": False}
        await asyncio.Event().wait()  # a connected client: nothing more arrives until the answer is done

    async def send(message):
        nonlocal status
        if message["type"] == "http.response.start":
            status = message["status"]
        elif message["type"] == "http.response.body":
            chunks.append(message.get("body", b""))

    try:
        await app(sub, receive, send)
    except Exception:  # noqa: BLE001 - the app already answered 500 for it; the other reads stand
        log.exception("desk minute: %s failed", path)
    try:
        body = json.loads(b"".join(chunks)) if chunks else None
    except ValueError:
        body = None
    return {"status": status, "body": body}
