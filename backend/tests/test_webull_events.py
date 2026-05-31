"""
Tests for the Webull gRPC event subscriber.

Strategy: the gRPC channel itself is impractical to unit-test (would need a
live or fake server). Instead we test:
  - The envelope builder: protobuf-shaped responses convert correctly.
  - The host resolver: env/region mapping is right.
  - The metadata signer: produces the headers Webull expects.
  - The streaming listener loop: cooperative stop + reconnect logic against
    a fake subscriber.
"""

from __future__ import annotations

import json
import uuid
from typing import Callable, List

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.engine.webull_events import (
    ET_PING,
    ET_SUBSCRIBE_SUCCESS,
    _build_subscribe_metadata,
    _envelope_from_response,
    resolve_event_host,
)
from app.engine.webull_proto import events_pb2


# ---------------------------------------------------------------------------
# Host resolution
# ---------------------------------------------------------------------------

def test_resolve_event_host_prod_us() -> None:
    assert resolve_event_host(env="prod", region="us") == "events-api.webull.com"


def test_resolve_event_host_uat_us() -> None:
    assert resolve_event_host(env="uat", region="us") == "us-openapi-events.uat.webullbroker.com"


def test_resolve_event_host_unknown_combo_raises() -> None:
    from app.engine.webull_client import WebullClientError
    with pytest.raises(WebullClientError):
        resolve_event_host(env="prod", region="jp")


def test_resolve_event_host_respects_events_host_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WEBULL_EVENTS_HOST", "events.custom.example")
    assert resolve_event_host(env="uat", region="us") == "events.custom.example"


# ---------------------------------------------------------------------------
# Envelope builder
# ---------------------------------------------------------------------------

def _make_response(
    *,
    event_type: int,
    payload: str = "",
    content_type: str = "application/json",
    request_id: str = "req-1",
    subscribe_type: int = 1,
    timestamp: int = 0,
) -> events_pb2.SubscribeResponse:
    r = events_pb2.SubscribeResponse()
    r.eventType = event_type
    r.contentType = content_type
    r.payload = payload
    r.requestId = request_id
    r.subscribeType = subscribe_type
    r.timestamp = timestamp
    return r


def test_envelope_returns_none_for_subscribe_success() -> None:
    r = _make_response(event_type=ET_SUBSCRIBE_SUCCESS, payload="ok")
    assert _envelope_from_response(r) is None


def test_envelope_returns_none_for_ping() -> None:
    r = _make_response(event_type=ET_PING, payload="ping")
    assert _envelope_from_response(r) is None


def test_envelope_wraps_json_data_event() -> None:
    inner = {
        "account_id": "ACCT_X",
        "client_order_id": "co_1",
        "symbol": "AAPL",
        "filled_qty": "1",
        "filled_price": "180",
        "filled_time": "2025-11-21T14:27:43Z",
        "side": "BUY",
        "category": "US_STOCK",
        "scene_type": "FILLED",
        "order_status": "FILLED",
        "request_id": "rid_inner",
    }
    r = _make_response(
        event_type=1024,
        payload=json.dumps(inner),
        request_id="rid_outer",
        subscribe_type=1,
        timestamp=1700000000000,
    )
    env = _envelope_from_response(r)
    assert env is not None
    assert env["id"] == "grpc:rid_outer"
    assert env["event_type"] == "TRADE"
    assert env["payload"] == inner
    assert env["_meta"]["grpc_event_type_raw"] == 1024
    assert env["_meta"]["grpc_subscribe_type"] == 1
    assert env["_meta"]["grpc_timestamp_ms"] == 1700000000000


def test_envelope_falls_back_to_composite_id_when_request_id_missing() -> None:
    inner = {"client_order_id": "co_99", "filled_time": "2025-01-01T00:00:00Z", "filled_qty": "5"}
    r = _make_response(event_type=1024, payload=json.dumps(inner), request_id="")
    env = _envelope_from_response(r)
    assert env is not None
    assert env["id"] == "grpc:co_99:2025-01-01T00:00:00Z:5"


def test_envelope_uses_uuid_when_nothing_identifies_event() -> None:
    r = _make_response(event_type=1024, payload="{}", request_id="")
    env = _envelope_from_response(r)
    assert env is not None
    assert env["id"].startswith("grpc:missing-")


def test_envelope_preserves_non_json_payload() -> None:
    r = _make_response(event_type=1024, payload="not json", content_type="text/plain")
    env = _envelope_from_response(r)
    assert env is not None
    assert env["payload"] == {"raw_payload": "not json", "content_type": "text/plain"}


# ---------------------------------------------------------------------------
# Metadata signer
# ---------------------------------------------------------------------------

def test_subscribe_metadata_has_expected_keys() -> None:
    request = events_pb2.SubscribeRequest(subscribeType=3, timestamp=1, accounts=["A"])
    metadata = _build_subscribe_metadata(
        app_key="K", app_secret="S", request=request,
    )
    keys = {k for (k, _v) in metadata}
    assert keys == {
        "x-app-key",
        "x-signature-algorithm",
        "x-signature-version",
        "x-signature-nonce",
        "x-timestamp",
        "x-signature",
    }
    # Signature is non-empty
    by_key = dict(metadata)
    assert by_key["x-signature"]
    assert by_key["x-app-key"] == "K"
    assert by_key["x-signature-algorithm"] == "HMAC-SHA1"
    assert by_key["x-signature-version"] == "1.0"


def test_events_canonical_string_matches_sdk_quirks() -> None:
    """
    Lock down the three SDK-events quirks that aren't shared with HTTP:
      1. body MD5 is computed over raw protobuf BYTES, not a decoded string.
      2. body MD5 is LOWERCASE hex.
      3. sorted (k=v) pairs join with '=' (not '&') when there is no path.
    """
    import hashlib
    import urllib.parse
    from app.engine.webull_events import _build_events_canonical_string, _md5_hex_bytes

    raw_bytes = b"\x01\x02\x03\xff\xfe"  # includes bytes > 0x7F
    assert _md5_hex_bytes(raw_bytes) == hashlib.md5(raw_bytes).hexdigest()
    assert _md5_hex_bytes(raw_bytes) == _md5_hex_bytes(raw_bytes).lower()  # lowercase

    encoded = _build_events_canonical_string(
        sign_params={
            "x-app-key": "K",
            "x-signature-algorithm": "HMAC-SHA1",
            "x-signature-version": "1.0",
            "x-signature-nonce": "N",
            "x-timestamp": "2025-01-01T00:00:00Z",
        },
        body_md5_hex_lower="deadbeef",
    )
    decoded = urllib.parse.unquote(encoded)
    # The "=" join produces this exact shape:
    expected = (
        "x-app-key=K=x-signature-algorithm=HMAC-SHA1=x-signature-nonce=N"
        "=x-signature-version=1.0=x-timestamp=2025-01-01T00:00:00Z"
        "&deadbeef"
    )
    assert decoded == expected


# ---------------------------------------------------------------------------
# Streaming listener loop with a fake subscriber
# ---------------------------------------------------------------------------

@pytest.fixture
def isolated_db(monkeypatch: pytest.MonkeyPatch):
    """An in-memory DB shared between the listener's read/write threads."""
    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(test_engine)
    monkeypatch.setattr("app.engine.webull_listener.engine", test_engine)
    # Also redirect ingest_event's engine if it uses one — it does not, it
    # takes a session, so we're fine.
    return test_engine


def _make_listener_job(test_engine, *, accounts: list[str]) -> uuid.UUID:
    """Create a JobRun row directly (avoid the engine.jobs.create_* indirection
    so the test stays focused on the listener loop)."""
    from datetime import datetime
    from app.models import JobRun
    job_id = uuid.uuid4()
    with Session(test_engine) as s:
        job = JobRun(
            id=job_id,
            job_type="webull_listener",
            status="queued",
            params_json=json.dumps({"accounts": accounts}),
            total=0,
            updated_at=datetime.utcnow(),
        )
        s.add(job)
        s.commit()
    return job_id


def test_streaming_listener_normalizes_events_from_fake_subscriber(
    monkeypatch: pytest.MonkeyPatch, isolated_db,
) -> None:
    monkeypatch.setattr("app.engine.webull.webull_configured", lambda: True)
    monkeypatch.setattr("app.engine.webull_listener.webull_configured", lambda: True)

    job_id = _make_listener_job(isolated_db, accounts=["ACCT_FAKE"])

    fake_events = [
        {
            "id": "grpc:evt_1",
            "event_type": "TRADE",
            "payload": {
                "account_id": "ACCT_FAKE",
                "client_order_id": "co_1",
                "symbol": "MSFT",
                "filled_price": "400.00",
                "filled_qty": "2.00",
                "filled_time": "2025-11-21T14:27:43Z",
                "side": "BUY",
                "category": "US_STOCK",
                "scene_type": "FILLED",
                "order_status": "FILLED",
            },
        },
        {
            "id": "grpc:evt_2",
            "event_type": "TRADE",
            "payload": {
                "account_id": "ACCT_FAKE",
                "client_order_id": "co_2",
                "symbol": "MSFT",
                "filled_price": "401.00",
                "filled_qty": "3.00",
                "filled_time": "2025-11-21T14:28:43Z",
                "side": "BUY",
                "category": "US_STOCK",
                "scene_type": "FINAL_FILLED",
                "order_status": "FILLED",
            },
        },
    ]

    def fake_subscriber(
        accounts: List[str],
        on_event: Callable[[dict], None],
        stop_check: Callable[[], bool],
    ) -> None:
        assert accounts == ["ACCT_FAKE"]
        for evt in fake_events:
            if stop_check():
                return
            on_event(evt)
        # Returns cleanly — listener should mark succeeded.

    from app.engine.webull_listener import run_listener
    from app.models import Fill, WebullRawEvent, JobRun

    enriched = run_listener(job_id, subscriber=fake_subscriber)
    assert enriched == 2

    with Session(isolated_db) as s:
        raws = s.exec(select(WebullRawEvent)).all()
        assert len(raws) == 2
        assert {r.event_id for r in raws} == {"grpc:evt_1", "grpc:evt_2"}

        fills = s.exec(select(Fill)).all()
        assert len(fills) == 2
        assert all(f.raw_email_id.startswith("webull:grpc:") for f in fills)

        job = s.get(JobRun, job_id)
        assert job.status == "succeeded"
        assert job.enriched == 2
        assert job.done == 2


def test_streaming_listener_fails_when_no_accounts_configured(
    monkeypatch: pytest.MonkeyPatch, isolated_db,
) -> None:
    monkeypatch.setattr("app.engine.webull.webull_configured", lambda: True)
    monkeypatch.setattr("app.engine.webull_listener.webull_configured", lambda: True)

    # accounts list empty => listener should mark failed without calling subscriber
    job_id = _make_listener_job(isolated_db, accounts=[])

    called = []

    def fake_subscriber(*args, **kwargs):
        called.append(True)

    from app.engine.webull_listener import run_listener
    from app.models import JobRun
    enriched = run_listener(job_id, subscriber=fake_subscriber)
    assert enriched == 0
    assert called == []
    with Session(isolated_db) as s:
        job = s.get(JobRun, job_id)
        assert job.status == "failed"
        assert "accounts" in (job.error or "").lower()


def test_streaming_listener_propagates_terminal_error(
    monkeypatch: pytest.MonkeyPatch, isolated_db,
) -> None:
    monkeypatch.setattr("app.engine.webull.webull_configured", lambda: True)
    monkeypatch.setattr("app.engine.webull_listener.webull_configured", lambda: True)

    job_id = _make_listener_job(isolated_db, accounts=["ACCT"])

    from app.engine.webull_events import WebullEventsTerminalError

    def terminal_subscriber(*args, **kwargs):
        raise WebullEventsTerminalError("AuthError")

    from app.engine.webull_listener import run_listener
    from app.models import JobRun
    run_listener(job_id, subscriber=terminal_subscriber)
    with Session(isolated_db) as s:
        job = s.get(JobRun, job_id)
        assert job.status == "failed"
        assert "AuthError" in (job.error or "")


def test_streaming_listener_reconnects_on_transient_error(
    monkeypatch: pytest.MonkeyPatch, isolated_db,
) -> None:
    monkeypatch.setattr("app.engine.webull.webull_configured", lambda: True)
    monkeypatch.setattr("app.engine.webull_listener.webull_configured", lambda: True)
    # Skip the real backoff sleeps so the test runs fast.
    monkeypatch.setattr("app.engine.webull_listener.time.sleep", lambda *_a, **_k: None)

    job_id = _make_listener_job(isolated_db, accounts=["ACCT"])

    call_count = {"n": 0}

    def flaky_subscriber(accounts, on_event, stop_check):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("transport blip")
        # Second time around: deliver one event then return cleanly.
        on_event({
            "id": "grpc:reconnect_evt",
            "event_type": "TRADE",
            "payload": {
                "account_id": "ACCT",
                "client_order_id": "co_x",
                "symbol": "NVDA",
                "filled_price": "100",
                "filled_qty": "1",
                "filled_time": "2025-11-21T14:27:43Z",
                "side": "BUY",
                "category": "US_STOCK",
                "scene_type": "FILLED",
                "order_status": "FILLED",
            },
        })

    from app.engine.webull_listener import run_listener
    from app.models import JobRun
    enriched = run_listener(job_id, subscriber=flaky_subscriber)
    assert enriched == 1
    assert call_count["n"] == 2
    with Session(isolated_db) as s:
        job = s.get(JobRun, job_id)
        assert job.status == "succeeded"
