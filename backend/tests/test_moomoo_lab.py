"""Offline bridge boundaries; never load real credentials or contact providers."""
import asyncio
import copy
import json

from fastapi.testclient import TestClient
import pytest

from scripts import moomoo_diagnostic as d
from scripts import moomoo_lab_server as lab
from tests.test_moomoo_diagnostic import FakeSocket
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

TOKEN = "invented-loopback-token-00000000000000"
HEADERS = {"Authorization": "Bearer " + TOKEN, "Content-Type": "application/x-level2-start"}
BOOK = {"type": "ORDER_BOOK", "symbol": "US.NVDA", "data": {
    "exchange_data_time_ms": 0, "exchange": "ARCA", "order_volume_precision": 2,
    "bid_list": [{"price": 230.1234, "volume": 101.5, "mpid": "ARCA"}],
    "ask_list": [{"price": 230.1235, "volume": 210, "order_count": 0}]}}


def test_book_precision_missing_time_and_allowlist():
    wire = copy.deepcopy(BOOK)
    wire["data"]["secret"] = "DO-NOT-ECHO"
    wire["data"]["ask_list"][0]["mpid"] = "DO-NOT-ECHO"
    result = d.display_book(wire, 1710000000000, 0)
    book = result["books"][0]
    assert book["source_time_ms"] is None and book["estimated_age_ms"] is None
    assert book["bids"][0]["price"] == 230.1234
    assert book["bids"][0]["volume"] == 101.5
    assert book["bids"][0]["order_count"] is None
    assert book["asks"][0]["order_count"] == 0
    assert "DO-NOT-ECHO" not in json.dumps(result)
    wire["data"].pop("exchange")
    assert d.display_book(wire, 1710000000000, 0)["books"][0]["exchange"] == "UNKNOWN"
    wire["data"]["bid_flag"] = 0
    assert d.display_book(wire, 1710000000000, 0)["books"][0]["bids"] == []


@pytest.mark.parametrize("value", [True, "230", float("nan"), -1, None])
def test_book_invalid_price_refused(value):
    wire = copy.deepcopy(BOOK)
    wire["data"]["bid_list"][0]["price"] = value
    with pytest.raises(d.DiagnosticError):
        d.display_book(wire, 1710000000000, None)


def test_book_bounds_and_no_previous_side_merging():
    wire = copy.deepcopy(BOOK)
    wire["data"].pop("bid_list")
    assert d.display_book(wire, 1710000000000, 0)["books"][0]["bids"] == []
    wire["data"]["ask_list"] *= 61
    with pytest.raises(d.DiagnosticError):
        d.display_book(wire, 1710000000000, 0)
    wire["symbol"] = "US.AAPL"
    with pytest.raises(d.DiagnosticError):
        d.display_book(wire, 1710000000000, 0)


def test_status_auth_body_boundary_no_credential_reads():
    def forbidden():
        pytest.fail("Credentials must not be read")
    with TestClient(lab.create_app(token=TOKEN, loader=forbidden), client=("127.0.0.1", 50000)) as client:
        assert client.get("/status").status_code == 403
        assert client.get("/status", headers=HEADERS).json() == {"enabled": True}
        assert client.post("/session").status_code == 403
        assert client.post("/session?seconds=300", headers=HEADERS).status_code == 400
        assert client.post("/session", headers=HEADERS, content=b"{}" ).status_code == 400
        assert client.get("/docs", headers=HEADERS).status_code == 404
    with TestClient(lab.create_app(token=TOKEN, loader=forbidden), client=("203.0.113.1", 50000)) as client:
        assert client.post("/session", headers=HEADERS).status_code == 403


def test_sanitized_credential_failure():
    def invalid():
        raise ValueError("DO-NOT-ECHO")
    with TestClient(lab.create_app(token=TOKEN, loader=invalid), client=("127.0.0.1", 50000)) as client:
        result = client.post("/session", headers=HEADERS)
        assert result.status_code == 503 and "DO-NOT-ECHO" not in result.text


def test_session_coalesces_latest_no_archive_and_fixed_cap():
    async def runner(appkey, key, seconds, observer):
        assert seconds == 30 and appkey == "fixture"
        observer({"event": "status", "phase": "authenticated"})
        for i in range(100):
            observer({"event": "book", "symbol": "US.NVDA", "received_ms": i, "books": []})
        return {"closed": True, "message_counts": {"ORDER_BOOK": 100}}
    with TestClient(lab.create_app(token=TOKEN, loader=lambda: ("fixture", None), runner=runner), client=("127.0.0.1", 50000)) as client:
        response = client.post("/session", headers=HEADERS)
        result = [json.loads(line) for line in response.text.splitlines()]
    books = [event for event in result if event["event"] == "book"]
    assert len(books) == 1 and books[0]["received_ms"] == 99
    assert result[-1] == {"event": "status", "phase": "closed"}


def test_single_session_gate_and_stop_closes_provider():
    async def scenario():
        from starlette.requests import Request
        started, stopped = asyncio.Event(), asyncio.Event()
        async def runner(appkey, key, seconds, observer):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()
        app = lab.create_app(token=TOKEN, loader=lambda: ("fixture", None), runner=runner)
        endpoint = next(route.endpoint for route in app.routes if route.path == "/session")
        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}
        scope = {"type": "http", "method": "POST", "path": "/session", "query_string": b"",
                 "client": ("127.0.0.1", 1000), "headers": [(k.lower().encode(), v.encode()) for k, v in HEADERS.items()]}
        request = Request(scope, receive)
        response = await endpoint(request)
        await started.wait()
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            await endpoint(Request(scope, receive))
        assert exc.value.status_code == 409
        # Drive stream once, then close it like a disconnected downstream.
        consumer = asyncio.create_task(anext(response.body_iterator))
        await asyncio.sleep(0.01)
        consumer.cancel()
        with pytest.raises(asyncio.CancelledError):
            await consumer
        await asyncio.wait_for(stopped.wait(), 1)
    asyncio.run(scenario())


def test_observer_auth_failure_no_subscribe_and_cancel_cleanup():
    async def scenario():
        key = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
        socket = FakeSocket(auth_fail=True)
        await socket.queue.put(json.dumps(BOOK))
        events = []
        report = await d.stream_probe("fixture", key, 1, lambda *a, **k: socket, events.append)
        assert report["closed"] and [frame["action"] for frame in socket.sent] == ["auth"]
        assert {"event": "status", "phase": "failed", "code": -1} in events
        assert not any(event["event"] == "book" for event in events)
        socket = FakeSocket()
        task = asyncio.create_task(d.stream_probe("fixture", key, 30, lambda *a, **k: socket, events.append))
        while not any(frame["action"] == "subscribe" and "ticker" in frame for frame in socket.sent):
            await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert socket.close_code == 1000
        assert socket.sent[-1]["action"] == "unsubscribe"
    asyncio.run(scenario())


def test_actual_asgi_http_disconnect_unsubscribes_before_session_release():
    async def scenario():
        socket = FakeSocket()
        key = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
        async def runner(appkey, supplied_key, seconds, observer):
            return await d.stream_probe(appkey, supplied_key, seconds, lambda *a, **k: socket, observer)
        app = lab.create_app(token=TOKEN, loader=lambda: ("fixture", key), runner=runner)
        disconnect = asyncio.Event()
        first = True
        async def receive():
            nonlocal first
            if first:
                first = False
                return {"type": "http.request", "body": b"", "more_body": False}
            await disconnect.wait()
            return {"type": "http.disconnect"}
        async def send(message):
            if message["type"] == "http.response.body" and message.get("body"):
                # Wait until subscriptions actually exist, then disconnect the
                # downstream HTTP client through the real ASGI channel.
                while not any("ticker" in frame for frame in socket.sent):
                    await asyncio.sleep(0)
                disconnect.set()
        scope = {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"},
                 "method": "POST", "scheme": "http", "path": "/session", "raw_path": b"/session",
                 "query_string": b"", "root_path": "", "http_version": "1.1",
                 "client": ("127.0.0.1", 50000), "server": ("127.0.0.1", 8196),
                 "headers": [(k.lower().encode(), v.encode()) for k, v in HEADERS.items()]}
        await asyncio.wait_for(app(scope, receive, send), 2)
        # Cancellation scopes may finish the HTTP response before the shielded
        # provider cleanup finishes. The active-session gate holds meanwhile.
        for _ in range(100):
            if socket.close_code is not None:
                break
            await asyncio.sleep(0.01)
        assert socket.close_code == 1000
        assert socket.sent[-1]["action"] == "unsubscribe"
    asyncio.run(scenario())
