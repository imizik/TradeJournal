"""Per-job observability for intentional API pacing and retry backoff.

The market-data clients are synchronous and can run in multiple background
threads.  A ContextVar keeps the observer scoped to the job/thread that is
currently making a request, without coupling the clients to JobRun or the
database.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
import time


ApiWaitObserver = Callable[[str, str | None, float], None]

_observer: ContextVar[ApiWaitObserver | None] = ContextVar("api_wait_observer", default=None)


@contextmanager
def observe_api_waits(observer: ApiWaitObserver) -> Iterator[None]:
    token = _observer.set(observer)
    try:
        yield
    finally:
        _observer.reset(token)


def report_api_wait(provider: str, reason: str, seconds: float) -> None:
    observer = _observer.get()
    if observer is not None:
        observer(provider, reason, max(0.0, seconds))


def clear_api_wait(provider: str) -> None:
    observer = _observer.get()
    if observer is not None:
        observer(provider, None, 0.0)


def observed_sleep(
    provider: str,
    reason: str,
    seconds: float,
    *,
    visible_after: float = 2.0,
) -> None:
    """Sleep while exposing waits long enough to matter to a polling UI.

    Tiny pacing sleeps are intentionally left unreported: persisting a JobRun
    update can cost more than the wait itself on hosted Postgres.
    """
    visible = seconds >= visible_after
    if visible:
        report_api_wait(provider, reason, seconds)
    try:
        time.sleep(seconds)
    finally:
        if visible:
            clear_api_wait(provider)
