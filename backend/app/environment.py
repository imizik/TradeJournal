"""
Which database is this process actually talking to?

There is one DATABASE_URL and no environment concept, which was fine while
there was one database. With a Neon dev branch alongside production there are
two that look identical from the UI, and the only thing distinguishing them is
which .env was edited last. `/health` returning {"status": "ok"} gives an
operator -- or an agent -- no way to check before pressing a destructive
button.

This module derives a redacted identity for the connected database, and
decides whether destructive operations need confirmation.

Two rules it follows deliberately:

1. **Credentials never appear in the identity.** It is rendered in an API
   response and in logs.

2. **A label never unlocks destruction.** APP_ENV names the environment for
   display only. An ambient "this is safe to destroy" flag is exactly the
   failure this repository already hit twice: a marker set once keeps
   authorizing destruction long after the database it described has been
   repointed. Whether confirmation is required is derived from the live
   connection, and the confirmation itself is per-request.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlparse

# A local SQLite file is a scratch database on this machine. Anything else is
# reachable over a network, belongs to someone, and is treated as precious.
LOCAL_BACKENDS = {"sqlite"}


@dataclass(frozen=True)
class Environment:
    name: str          # display label: "local", or whatever APP_ENV says
    backend: str       # "sqlite" | "postgresql" | ...
    identity: str      # redacted, human-checkable: "host/database" or a filename
    is_local: bool     # a file on this machine, versus a hosted database

    @property
    def destructive_requires_confirmation(self) -> bool:
        return not self.is_local

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "backend": self.backend,
            "identity": self.identity,
            "is_local": self.is_local,
            "destructive_requires_confirmation": self.destructive_requires_confirmation,
        }


def _redacted_identity(url: str, backend: str) -> str:
    """
    Something specific enough to tell two databases apart, and safe to print.

    For hosted databases that is host/database -- each Neon branch gets its own
    endpoint hostname, so a dev branch and production are visibly different.
    Username, password and query string are dropped.
    """
    parsed = urlparse(url)

    if backend in LOCAL_BACKENDS:
        # sqlite:///abs/path.db -> the filename is the useful part
        path = (parsed.path or "").lstrip("/")
        return os.path.basename(path) or "in-memory"

    host = parsed.hostname or "unknown-host"
    database = (parsed.path or "").lstrip("/") or "unknown-database"
    port = f":{parsed.port}" if parsed.port else ""
    return f"{host}{port}/{database}"


def describe(url: str | None = None) -> Environment:
    """Describe the database this process is configured to use."""
    if url is None:
        # Imported lazily: app.database resolves .env files at import time, and
        # this module is also used by tooling that sets DATABASE_URL itself.
        from app.database import DATABASE_URL

        url = DATABASE_URL

    scheme = urlparse(url).scheme or ""
    # "postgresql+psycopg" -> "postgresql"
    backend = scheme.split("+", 1)[0] or "unknown"
    is_local = backend in LOCAL_BACKENDS

    configured_name = os.environ.get("APP_ENV", "").strip()
    name = configured_name or ("local" if is_local else "unnamed-hosted")

    return Environment(
        name=name,
        backend=backend,
        identity=_redacted_identity(url, backend),
        is_local=is_local,
    )


def require_destructive_confirmation(confirm: str | None, operation: str) -> Environment:
    """
    Gate an operation that deletes data the app cannot rebuild from itself.

    Local SQLite passes straight through -- it is a scratch file on this
    machine, and gating it would just add friction to the normal dev loop.

    A hosted database requires the caller to name it. Typing the target's
    identity is the standard confirmation for destructive infrastructure work,
    and unlike a stored flag it cannot go stale: repoint DATABASE_URL and the
    expected value changes with it.

    Raises HTTPException(400) with the expected identity, so an operator or an
    agent that gets it wrong is told exactly what to send.
    """
    from fastapi import HTTPException

    environment = describe()
    if not environment.destructive_requires_confirmation:
        return environment

    if confirm != environment.identity:
        raise HTTPException(
            status_code=400,
            detail=(
                f"{operation} deletes data on a hosted database "
                f"({environment.identity}, environment {environment.name!r}). "
                "Resend with the database identity to confirm: "
                f'{{"confirm": "{environment.identity}"}}. '
                "Check GET /health if you are unsure which database this is."
            ),
        )
    return environment
