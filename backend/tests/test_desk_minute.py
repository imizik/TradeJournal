"""The desk's minute re-reads in one request (``GET /copilot/desk/minute``, app/engine/desk_minute.py): each read is
answered exactly as its own route answers the same browser, in order; only the desk's minute reads are dispatched; the
route is owner-only and refused while the lab is off. Every value is invented."""

from __future__ import annotations

from types import SimpleNamespace

from fastapi import Request

from app.access_manifest import DOMAIN_ROUTES
from app.engine import desk_minute
from app.routers import copilot_desk
from tests.test_copilot_desk import desk  # noqa: F401  (the desk app over the shared fixtures)
from tests.test_copilot_plans import engine, quotes  # noqa: F401  (fixtures)
from tests.test_owner_lock import lock  # noqa: F401  (fixture)
from tests.test_today import clock, marks  # noqa: F401  (fixtures)


def minute(client, *reads, **kwargs):
    return client.get("/copilot/desk/minute", params=[("read", r) for r in reads], **kwargs)


def test_each_read_is_its_own_route_answer_in_order(desk):  # noqa: F811
    reads = ["/copilot/desk/threads", "/copilot/desk/session", "/copilot/desk/watching", "/copilot/desk/sparks?symbols=NBIS"]
    response = minute(desk, *reads)
    assert response.status_code == 200, response.text
    got = response.json()["reads"]
    assert [r["status"] for r in got] == [200, 200, 200, 200]
    for target, read in zip(reads, got):
        alone = desk.get(target).json()
        if "as_of" in alone:  # the same read a moment apart: only the time it was made may differ
            alone["as_of"] = read["body"]["as_of"]
        assert read["body"] == alone, target


def test_a_refusal_is_that_reads_own_answer_and_the_rest_stand(desk, monkeypatch):  # noqa: F811
    got = minute(desk, "/copilot/desk/threads", "/copilot/desk/nope-here/chart?timeframe=5m").json()["reads"]
    assert got[0]["status"] == 200
    assert got[1]["status"] == 404  # the chart route is not in this test app: its answer passes through as it is


def test_only_the_desks_minute_reads_are_dispatched(desk, monkeypatch):  # noqa: F811
    calls = []
    real = desk_minute._one

    async def spy(app, scope, target):
        calls.append(target)
        return await real(app, scope, target)
    monkeypatch.setattr(desk_minute, "_one", spy)
    outside = ["/copilot/desk/robinhood/refresh", "/copilot/desk/read", "/copilot/desk/timings", "/fills",
               "http://elsewhere.example/copilot/desk/threads", "/copilot/desk/a%2Fb/chart", "/copilot/desk/minute?read=/copilot/desk/threads",
               "/copilot/desk/../chart", "/copilot/desk/%3Cx%3E%20y/chart", "/copilot/desk/watching/robinhood"]
    got = minute(desk, *outside).json()["reads"]
    assert [r["status"] for r in got] == [400] * len(outside)
    assert all(r["body"] == {"detail": "Not a desk minute read."} for r in got)
    assert desk_minute.allowed("/copilot/desk/symbol:NVDA/chart") and desk_minute.allowed("/copilot/tickets")
    assert desk_minute.allowed("/copilot/desk/symbol:BRK.B/chart") and desk_minute.allowed("/copilot/desk/market/chart")
    assert minute(desk).status_code == 400  # nothing named
    assert minute(desk, *["/copilot/desk/threads"] * (desk_minute.MAX_READS + 1)).status_code == 400


def test_a_read_carries_the_browsers_own_headers_and_address(desk):  # noqa: F811
    # The access decision for each read is the one the browser would get: same cookies/headers, same client address.
    app = desk.app

    @app.get("/copilot/tickets")
    def echo(request: Request):
        return {"probe": request.headers.get("x-probe"), "client": request.client.host if request.client else None,
                "access": getattr(request.state, "access", "unset")}
    got = minute(desk, "/copilot/tickets", headers={"x-probe": "owner-cookie"}).json()["reads"][0]
    alone = desk.get("/copilot/tickets", headers={"x-probe": "owner-cookie"}).json()
    assert got == {"status": 200, "body": alone}
    assert got["body"]["probe"] == "owner-cookie" and got["body"]["access"] == "unset"


def test_refused_while_the_lab_is_off_and_owner_only(desk, monkeypatch):  # noqa: F811
    monkeypatch.setattr(copilot_desk.copilot, "settings", lambda: SimpleNamespace(enabled=False))
    assert minute(desk, "/copilot/desk/threads").status_code == 503
    assert "GET /copilot/desk/minute" in DOMAIN_ROUTES  # classified; no grant names it, so only the owner reaches it


def test_the_server_list_matches_the_desks():
    # frontend/lib/deskMinute.ts BATCHED names the same paths: a path only one side knows would never be batched, or refused.
    from pathlib import Path
    source = (Path(__file__).resolve().parents[2] / "frontend" / "lib" / "deskMinute.ts").read_text()
    for path in desk_minute.PATHS:
        assert f'"{path}"' in source, path


def test_a_read_past_its_time_answers_504_for_itself_and_the_rest_land(desk, monkeypatch):  # noqa: F811
    import asyncio
    real = desk_minute._one

    async def slow(app, scope, target):
        if target.startswith("/copilot/desk/session"):
            await asyncio.sleep(5)
        return await real(app, scope, target)
    monkeypatch.setattr(desk_minute, "_one", slow)
    monkeypatch.setattr(desk_minute, "READ_SECONDS", 0.5)
    got = minute(desk, "/copilot/desk/threads", "/copilot/desk/session").json()["reads"]
    assert [r["status"] for r in got] == [200, 504]


def test_through_the_owner_lock_a_signed_out_batch_dispatches_nothing_and_a_signed_in_one_reads(lock, monkeypatch):  # noqa: F811
    from fastapi.testclient import TestClient

    from app.main import app
    from tests.test_owner_lock import BROWSER, token
    monkeypatch.setattr(copilot_desk.copilot, "settings", lambda: SimpleNamespace(enabled=True))
    calls = []
    real = desk_minute._one

    async def spy(app_, scope, target):
        calls.append(target)
        return await real(app_, scope, target)
    monkeypatch.setattr(desk_minute, "_one", spy)
    remote = TestClient(app, client=("100.64.0.7", 50000))  # a browser on the tailnet, not a process on the server
    target = "/copilot/desk/sparks?symbols="
    refused = remote.get("/copilot/desk/minute", params={"read": target}, headers=BROWSER)
    assert (refused.status_code, calls) == (401, [])
    cookie = {"__Host-tj_owner_lock": token(lock)}
    alone = remote.get(target, headers=BROWSER, cookies=cookie)
    got = remote.get("/copilot/desk/minute", params={"read": target}, headers=BROWSER, cookies=cookie)
    assert got.status_code == 200 and calls == [target]
    assert got.json()["reads"][0]["status"] == alone.status_code == 200
