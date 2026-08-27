"""
CORS origin resolution.

The frontend does not always run on localhost:3000 -- startdev uses other
ports, browser tests use their own, and a deployed frontend has a real
hostname. auth.py already redirects to FRONTEND_PUBLIC_URL, so CORS has to
honor it too; otherwise following the documented advice to change ports gives
you an app whose OAuth works while every client-side fetch is blocked by the
browser. That failure is invisible server-side: requests never arrive.
"""

from __future__ import annotations

import importlib

import pytest


def _origins(monkeypatch, configured: str | None) -> list[str]:
    if configured is None:
        monkeypatch.delenv("FRONTEND_PUBLIC_URL", raising=False)
    else:
        monkeypatch.setenv("FRONTEND_PUBLIC_URL", configured)

    from app import main

    importlib.reload(main)
    return main._cors_origins()


def test_local_development_origins_are_always_allowed(monkeypatch):
    assert _origins(monkeypatch, None) == [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]


def test_configured_frontend_origin_is_added(monkeypatch):
    origins = _origins(monkeypatch, "http://127.0.0.1:3099")
    assert "http://127.0.0.1:3099" in origins
    # The defaults survive, so setting this never breaks ordinary local work.
    assert "http://localhost:3000" in origins


def test_trailing_slash_is_normalized(monkeypatch):
    """An Origin header never carries a trailing slash, so a configured
    'https://app.example.com/' would otherwise never match."""
    assert "https://app.example.com" in _origins(monkeypatch, "https://app.example.com/")


@pytest.mark.parametrize("configured", ["", "   ", "http://localhost:3000"])
def test_blank_or_duplicate_values_do_not_pollute_the_list(monkeypatch, configured):
    origins = _origins(monkeypatch, configured)
    assert origins == ["http://localhost:3000", "http://127.0.0.1:3000"]


def test_preflight_from_a_configured_origin_is_accepted(monkeypatch):
    """End to end through the middleware, not just the helper."""
    from fastapi.testclient import TestClient

    monkeypatch.setenv("FRONTEND_PUBLIC_URL", "http://127.0.0.1:3099")
    from app import main

    importlib.reload(main)

    with TestClient(main.app) as client:
        response = client.options(
            "/stats",
            headers={
                "Origin": "http://127.0.0.1:3099",
                "Access-Control-Request-Method": "GET",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:3099"


def test_unknown_origin_is_not_granted_access(monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.delenv("FRONTEND_PUBLIC_URL", raising=False)
    from app import main

    importlib.reload(main)

    with TestClient(main.app) as client:
        response = client.get("/stats", headers={"Origin": "https://evil.example.com"})

    assert "access-control-allow-origin" not in response.headers
