"""Opt-in request-local chart diagnostics. No logs, identifiers or provider metadata."""
from contextlib import contextmanager
from contextvars import ContextVar
import time

_current: ContextVar[dict[str, float] | None] = ContextVar("chart_timing", default=None)


@contextmanager
def measured(name: str):
    metrics = _current.get()
    start = time.perf_counter() if metrics is not None else 0
    try:
        yield
    finally:
        if metrics is not None:
            metrics[name] = metrics.get(name, 0) + (time.perf_counter() - start) * 1000


@contextmanager
def measured_lock(lock, name: str):
    # Preserve exactly the existing lock lifetime and reentrancy.
    with measured(name):
        lock.acquire()
    try:
        yield
    finally:
        lock.release()


@contextmanager
def request_timing(enabled: bool, response):
    metrics = {} if enabled else None
    token = _current.set(metrics)
    try:
        with measured("total"):
            yield
    finally:
        _current.reset(token)
        if metrics is not None:
            response.headers["Server-Timing"] = ", ".join(f"{key};dur={value:.3f}" for key, value in metrics.items())
