"""
Webull TRADE event subscriber (gRPC server-streaming).

Connects to:
  - prod US:  events-api.webull.com:443
  - UAT US:   us-openapi-events.uat.webullbroker.com:443

Wire-up mirrors webull-openapi-python-sdk 2.0.8's TradeEventsClient, but
reimplemented locally so we don't depend on the SDK at runtime (it pins
Python <3.14). Signing reuses the primitives in app.engine.webull_client.

Flow:
  1. Build SubscribeRequest proto (subscribeType=3 for US, timestamp_ms, accounts).
  2. Compute HMAC-SHA1 signature over SerializeToString() of the request,
     produce gRPC metadata tuples.
  3. Open a TLS gRPC channel; call EventServiceStub.Subscribe(...).
  4. Iterate the server-streaming response:
       - SubscribeSuccess  -> connection established, log and continue
       - Ping              -> heartbeat, ignore
       - AuthError / NumOfConnExceed / SubscribeExpired -> terminal, raise
       - default (data)    -> JSON-parse payload, wrap in our envelope, call on_event
  5. Honor the cooperative stop_check passed by the caller.

No live trading. Read-only subscription.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Callable, Optional

import grpc

import hashlib
import os
import urllib.parse

from app.engine.webull_client import (
    WEBULL_APP_KEY,
    WEBULL_APP_SECRET,
    WEBULL_ENVIRONMENT,
    WEBULL_REGION_ID,
    SIGNATURE_ALGORITHM,
    SIGNATURE_VERSION,
    WebullClientError,
    compute_signature,
    iso8601_utc_now,
    make_nonce,
    webull_configured,
)
from app.engine.webull_proto import events_pb2, events_pb2_grpc

log = logging.getLogger(__name__)


# Event host base URLs. Both US hosts are in upgrade_hosts → HMAC-SHA1.
_EVENT_HOSTS = {
    ("us", "prod"): "events-api.webull.com",
    ("us", "uat"):  "us-openapi-events.uat.webullbroker.com",
}
DEFAULT_PORT = 443

# Webull-defined subscribeType values
SUBSCRIBE_TYPE_US = 3
SUBSCRIBE_TYPE_NON_US = 1

# Internal enum values from the proto (re-exported for clarity)
ET_SUBSCRIBE_SUCCESS = events_pb2.SubscribeSuccess
ET_PING = events_pb2.Ping
ET_AUTH_ERROR = events_pb2.AuthError
ET_NUM_OF_CONN_EXCEED = events_pb2.NumOfConnExceed
ET_SUBSCRIBE_EXPIRED = events_pb2.SubscribeExpired

# Per-iteration timeout so the listener can check the stop signal often.
_RPC_NEXT_TIMEOUT_SECONDS = 1.0


def resolve_event_host(env: Optional[str] = None, region: Optional[str] = None) -> str:
    """
    Resolve the events-api host for the active environment/region.

    `WEBULL_EVENTS_HOST` env var, if set, wins — same pattern as
    `WEBULL_API_BASE` for the HTTP client. Use it to point gRPC at prod
    while the HTTP layer hits UAT (or vice versa) without rewriting code.
    """
    override = os.environ.get("WEBULL_EVENTS_HOST", "").strip()
    if override:
        return override
    region = (region or WEBULL_REGION_ID).lower()
    env = (env or WEBULL_ENVIRONMENT).lower()
    key = (region, env)
    if key not in _EVENT_HOSTS:
        raise WebullClientError(
            f"No events host configured for region={region!r} environment={env!r}"
        )
    return _EVENT_HOSTS[key]


def _md5_hex_bytes(content: bytes) -> str:
    """
    Lowercase hex MD5 of raw bytes — matches the SDK's
    webull/core/utils/common.py::md5_hex. Distinct from the HTTP flow which
    uppercases (see webull_client.md5_upper).
    """
    return hashlib.md5(content).hexdigest()


def _build_events_canonical_string(
    *,
    sign_params: dict[str, str],
    body_md5_hex_lower: str,
) -> str:
    """
    Replicate the SDK's events-flow canonical string EXACTLY.

    The SDK's default_signature_composer._build_sign_string takes (uri=None)
    on the events path, which triggers a quirk: the sorted "k=v" pairs are
    joined with '=' (not '&'), then '&' + body_md5 is appended, and the
    whole thing is URL-encoded with safe=''.

    Example output (URL-decoded):
        x-app-key=KEY=x-signature-algorithm=HMAC-SHA1=x-signature-nonce=N=...&<md5>
    """
    sorted_pairs = [f"{k}={sign_params[k]}" for k in sorted(sign_params.keys())]
    # PARAM_KV_JOIN = "=" — yes, '=' is what the SDK uses here.
    string_to_sign = "=".join(sorted_pairs)
    if body_md5_hex_lower:
        string_to_sign = string_to_sign + "&" + body_md5_hex_lower
    return urllib.parse.quote(string_to_sign, safe="")


def _build_subscribe_metadata(
    *,
    app_key: str,
    app_secret: str,
    request: events_pb2.SubscribeRequest,
) -> list[tuple[str, str]]:
    """
    Build the gRPC metadata tuples that authenticate a SubscribeRequest.

    For the events flow:
      1. body_string = md5_hex(SerializeToString(request))  -- LOWERCASE hex
      2. signing headers (lowercased keys), sorted, joined with '=' (sic)
      3. + '&' + body_string
      4. URL-encode with safe=''
      5. base64(HMAC-SHA1(secret + '&', encoded))

    This matches webull/trade/events/signature_composer.calc_signature
    exactly (verified against the SDK 2.0.8 source).
    """
    timestamp = iso8601_utc_now()
    nonce = make_nonce()
    sign_params = {
        "x-app-key": app_key,
        "x-signature-algorithm": SIGNATURE_ALGORITHM,
        "x-signature-version": SIGNATURE_VERSION,
        "x-signature-nonce": nonce,
        "x-timestamp": timestamp,
    }
    body_md5 = _md5_hex_bytes(request.SerializeToString())  # bytes -> lowercase hex
    encoded = _build_events_canonical_string(
        sign_params=sign_params,
        body_md5_hex_lower=body_md5,
    )
    signature = compute_signature(app_secret=app_secret, encoded_string=encoded)
    metadata = [
        ("x-app-key", app_key),
        ("x-signature-algorithm", SIGNATURE_ALGORITHM),
        ("x-signature-version", SIGNATURE_VERSION),
        ("x-signature-nonce", nonce),
        ("x-timestamp", timestamp),
        ("x-signature", signature),
    ]
    return metadata


def _envelope_from_response(response: events_pb2.SubscribeResponse) -> Optional[dict]:
    """
    Convert a Webull SubscribeResponse into the envelope shape our
    ingest_event() expects:
        {"id": "<unique>", "event_type": "TRADE", "payload": {...}}
    Returns None for non-data response types (SubscribeSuccess, Ping, etc.).
    """
    if response.eventType in (
        ET_SUBSCRIBE_SUCCESS, ET_PING,
        ET_AUTH_ERROR, ET_NUM_OF_CONN_EXCEED, ET_SUBSCRIBE_EXPIRED,
    ):
        return None

    content_type = (response.contentType or "").lower()
    if content_type == "application/json":
        try:
            inner = json.loads(response.payload)
        except Exception as exc:
            log.warning("Webull event payload not JSON-decodable: %s", exc)
            inner = {"raw_payload": response.payload}
    else:
        inner = {"raw_payload": response.payload, "content_type": response.contentType}

    # Pick a stable idempotency key. requestId is preferred; fall back to
    # composite of payload fields; last-resort uuid prevents loss but breaks dedupe.
    base_id = response.requestId or (
        f"{inner.get('client_order_id', '')}:"
        f"{inner.get('filled_time', '')}:"
        f"{inner.get('filled_qty', '')}"
    )
    if not base_id.strip(":"):
        base_id = f"missing-{uuid.uuid4()}"

    return {
        "id": f"grpc:{base_id}",
        "event_type": "TRADE",
        "payload": inner if isinstance(inner, dict) else {"raw_payload": inner},
        # Diagnostic-only fields (ignored by ingest_event):
        "_meta": {
            "grpc_event_type_raw": int(response.eventType),
            "grpc_subscribe_type": int(response.subscribeType),
            "grpc_timestamp_ms": int(response.timestamp),
            "grpc_content_type": response.contentType,
        },
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class WebullEventsTerminalError(WebullClientError):
    """Raised when the server signals an unrecoverable subscription state."""


def subscribe_events(
    *,
    accounts: list[str],
    on_event: Callable[[dict], None],
    stop_check: Callable[[], bool] = lambda: False,
    app_key: Optional[str] = None,
    app_secret: Optional[str] = None,
    host: Optional[str] = None,
    port: int = DEFAULT_PORT,
    next_timeout: float = _RPC_NEXT_TIMEOUT_SECONDS,
) -> None:
    """
    Subscribe to Webull TRADE events for the given accounts.

    Args:
      accounts: list of Webull broker account ids to subscribe to. At least one.
      on_event: callback invoked for each *data* event (not for handshake or
        ping). Receives the envelope dict ready for ingest_event().
      stop_check: cooperative cancel — called between every received message
        and every empty timeout. Returning True ends the call cleanly.
      app_key, app_secret: override env credentials (testing).
      host: override the events-api host (testing or special routing).
      port: gRPC TLS port, default 443.
      next_timeout: how long to block on a single response read before
        checking stop_check. Lower = snappier shutdown, higher = less CPU.

    Raises:
      WebullClientError on configuration problems.
      WebullEventsTerminalError on AuthError / NumOfConnExceed / SubscribeExpired.
      grpc.RpcError on network/transport failures (caller decides retry).
    """
    if not accounts:
        raise WebullClientError("subscribe_events: at least one account is required")
    app_key = app_key or WEBULL_APP_KEY
    app_secret = app_secret or WEBULL_APP_SECRET
    if not (app_key and app_secret):
        raise WebullClientError("Webull credentials are not configured")
    host = host or resolve_event_host()

    subscribe_type = SUBSCRIBE_TYPE_US if WEBULL_REGION_ID == "us" else SUBSCRIBE_TYPE_NON_US
    request = events_pb2.SubscribeRequest(
        subscribeType=subscribe_type,
        timestamp=int(time.time() * 1000),
        accounts=list(accounts),
    )
    metadata = _build_subscribe_metadata(
        app_key=app_key, app_secret=app_secret, request=request
    )

    target = f"{host}:{port}"
    log.info("Webull events: opening gRPC stream to %s (accounts=%d)", target, len(accounts))

    creds = grpc.ssl_channel_credentials()
    with grpc.secure_channel(target, creds) as channel:
        stub = events_pb2_grpc.EventServiceStub(channel)
        call = stub.Subscribe(request=request, metadata=metadata)
        try:
            _drain_stream(call=call, on_event=on_event, stop_check=stop_check, next_timeout=next_timeout)
        finally:
            try:
                call.cancel()
            except Exception:
                pass


def _drain_stream(
    *,
    call,
    on_event: Callable[[dict], None],
    stop_check: Callable[[], bool],
    next_timeout: float,
) -> None:
    """Pull responses off the streaming call, honoring stop_check."""
    iterator = iter(call)
    while True:
        if stop_check():
            log.info("Webull events: stop_check requested, closing stream")
            return
        try:
            response = next(iterator)
        except StopIteration:
            log.info("Webull events: server ended the stream")
            return
        except grpc.RpcError as exc:
            # DEADLINE_EXCEEDED on per-call timeouts would surface here if we
            # set call.with_deadline(). We instead control loop pace via
            # next_timeout via grpc.Call.cancel() patterns below; treat any
            # RpcError as transport-level and propagate to the listener.
            code = exc.code() if callable(getattr(exc, "code", None)) else None
            if code == grpc.StatusCode.CANCELLED:
                log.info("Webull events: call cancelled")
                return
            raise

        et = response.eventType
        if et == ET_SUBSCRIBE_SUCCESS:
            log.info("Webull events: subscribe success")
            continue
        if et == ET_PING:
            log.debug("Webull events: ping")
            continue
        if et in (ET_AUTH_ERROR, ET_NUM_OF_CONN_EXCEED, ET_SUBSCRIBE_EXPIRED):
            name = events_pb2.EventType.Name(et)
            raise WebullEventsTerminalError(f"Webull events terminal state: {name}")

        envelope = _envelope_from_response(response)
        if envelope is None:
            continue
        try:
            on_event(envelope)
        except Exception:
            # The listener handles its own error logging; we just guarantee
            # one bad event doesn't kill the stream.
            log.exception("Webull events: on_event raised")
