"""Where a desk read's server time goes (docs/copilot-lab.md § Where the wait goes).

Every request under ``PREFIXES`` (the desk's reads, the copilot's symbol header and a position's since-entry context)
is timed: each named section (``today._section`` records its own; ``timed`` marks any other block) and the whole
request up to its response. The response carries a standard ``Server-Timing`` header (section names and milliseconds,
nothing else); a request slower than ``SLOW_MS`` logs one line naming its slowest sections; the last ``KEEP`` timings
of each route stay in memory for ``GET /copilot/desk/timings`` (p50 and p90 per route and per section). Names and
numbers only: no symbol, id, price or query string is kept or sent.
"""

from __future__ import annotations

import contextvars
import logging
import re
import threading
import time
from collections import deque
from contextlib import contextmanager

log = logging.getLogger(__name__)

PREFIXES = ("/copilot/desk/", "/copilot/symbol/", "/charts/journal/positions/")
SKIP = {"/copilot/desk/timings"}
SLOW_MS = 1500
KEEP = 50
SHOWN = 10  # timings listed per route in the diagnostics read; the percentiles use all ``KEEP``

_current: contextvars.ContextVar[Timer | None] = contextvars.ContextVar("request_timing", default=None)
_started = time.time()
_recent: dict[str, deque] = {}
_seen: set[str] = set()  # routes timed since the start: the first of each is the cold one
_lock = threading.Lock()


class Timer:
    """One request's sections, in the order they finished. Sections may finish on worker threads."""

    def __init__(self):
        self.sections: list[tuple[str, float]] = []
        self._lock = threading.Lock()

    def add(self, name: str, ms: float) -> None:
        with self._lock:
            self.sections.append((name, ms))


def current() -> Timer | None:
    return _current.get()


def record(name: str, ms: float) -> None:
    timer = _current.get()
    if timer is not None:
        timer.add(name, ms)


@contextmanager
def timed(name: str):
    start = time.perf_counter()
    try:
        yield
    finally:
        record(name, (time.perf_counter() - start) * 1000)


def bind(timer: Timer | None, fn):
    """``fn`` run on another thread still records into this request's timer."""
    def run(*args, **kwargs):
        token = _current.set(timer)
        try:
            return fn(*args, **kwargs)
        finally:
            _current.reset(token)
    return run


_TOKEN = re.compile(r"[^A-Za-z0-9_.-]+")


def _token(name: str) -> str:
    return _TOKEN.sub("-", name.strip()).strip("-")[:60] or "section"


def header(timer: Timer, total_ms: float) -> str:
    parts = [f"{_token(name)};dur={ms:.1f}" for name, ms in timer.sections]
    parts.append(f"total;dur={total_ms:.1f}")
    return ", ".join(parts)


def _percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(q * (len(ordered) - 1))))
    return round(ordered[index], 1)


def finish(route: str, timer: Timer, total_ms: float, status: int) -> None:
    sections: dict[str, float] = {}
    for name, ms in timer.sections:  # a name used twice in one request adds up
        sections[name] = round(sections.get(name, 0.0) + ms, 1)
    with _lock:
        kept = _recent.setdefault(route, deque(maxlen=KEEP))
        entry = {"at": int(time.time()), "ms": round(total_ms, 1), "status": status, "first": route not in _seen,
                 "sections": sections}
        _seen.add(route)
        kept.append(entry)
    if total_ms >= SLOW_MS:
        slowest = sorted(sections.items(), key=lambda kv: -kv[1])[:4]
        log.warning("slow desk read %s %.0f ms: %s", route, total_ms,
                    ", ".join(f"{name} {ms:.0f} ms" for name, ms in slowest) or "no sections recorded")



def summary(limit: int = SHOWN) -> dict:
    """Per route: how many timings are kept, p50/p90/max of the whole request, p50/p90 of each section (slowest p90
    first), and the newest ``limit`` timings."""
    with _lock:
        copied = {route: list(kept) for route, kept in _recent.items()}
    routes = {}
    for route, kept in sorted(copied.items()):
        totals = [e["ms"] for e in kept]
        names = {name for e in kept for name in e["sections"]}
        sections = {name: {"p50": _percentile(vals, 0.5), "p90": _percentile(vals, 0.9), "n": len(vals)}
                    for name in names if (vals := [e["sections"][name] for e in kept if name in e["sections"]])}
        routes[route] = {
            "count": len(kept), "p50_ms": _percentile(totals, 0.5), "p90_ms": _percentile(totals, 0.9),
            "max_ms": max(totals) if totals else None,
            "sections": dict(sorted(sections.items(), key=lambda kv: -(kv[1]["p90"] or 0))),
            "recent": list(reversed(kept[-limit:])) if limit > 0 else [],
        }
    return {"since": int(_started), "slow_ms": SLOW_MS, "keep": KEEP, "routes": routes}


def reset() -> None:
    with _lock:
        _recent.clear()
        _seen.clear()


def template(scope) -> str:
    """The route as the app declares it (``/charts/journal/positions/{symbol}/context``): the path with each path
    parameter's segment named, so no symbol or id is kept. ``unmatched`` when no route took the request."""
    if scope.get("route") is None:
        return "unmatched"
    params = {str(v): k for k, v in (scope.get("path_params") or {}).items()}
    return "/".join(f"{{{params.pop(part)}}}" if part in params else part for part in scope.get("path", "").split("/"))


class TimingMiddleware:
    """Pure ASGI, so a streamed or refused response is never buffered. Sits inside the access check: a refused request
    is not timed."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "") if scope["type"] == "http" else ""
        if not path.startswith(PREFIXES) or path in SKIP:
            return await self.app(scope, receive, send)
        timer = Timer()
        token = _current.set(timer)
        start = time.perf_counter()

        async def timed_send(message):
            if message["type"] == "http.response.start":
                total = (time.perf_counter() - start) * 1000
                message = {**message, "headers": [*message.get("headers", []), (b"server-timing", header(timer, total).encode())]}
                try:
                    route = template(scope)
                    finish(f"{scope.get('method', 'GET')} {route}", timer, total, message.get("status", 0))
                except Exception:  # noqa: BLE001 - timing must never break a response
                    log.debug("request timing not recorded", exc_info=True)
            await send(message)

        try:
            await self.app(scope, receive, timed_send)
        finally:
            _current.reset(token)
