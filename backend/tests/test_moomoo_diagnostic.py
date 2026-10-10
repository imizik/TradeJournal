"""Offline only: public RFC 8032 test key, invented quotes, mock HTTP."""

import base64
import asyncio
import copy
import getpass
import hashlib
import io
import json
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import httpx
import pytest
from websockets.datastructures import Headers
from websockets.exceptions import InvalidStatus
from websockets.http11 import Response

from scripts import moomoo_diagnostic as probe

FIXTURES = Path(__file__).parent / "fixtures/moomoo"
NOW = 1791637200100
# RFC 8032 test vector 1, a publicly documented test key, NEVER a credential.
RFC_SEED = bytes.fromhex("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60")


@pytest.fixture
def key():
    return Ed25519PrivateKey.from_private_bytes(RFC_SEED)


@pytest.fixture
def depth():
    return json.loads((FIXTURES / "depth.json").read_text())


@pytest.fixture
def quote():
    return json.loads((FIXTURES / "quote.json").read_text())


def test_documented_get_signing_string_retains_final_newline():
    assert probe.signing_payload(1782357937000, "get", "/api/v1.0/quote/trading-days", "market=HK&start=2025-12-22&end=2025-12-26", b"") == (
        b"1782357937000\nGET\n/api/v1.0/quote/trading-days\nmarket=HK&start=2025-12-22&end=2025-12-26\n")


def test_empty_query_and_body_are_distinct_empty_fields():
    assert probe.signing_payload(1, "GET", "/x", "", b"") == b"1\nGET\n/x\n\n"


def test_ed25519_uses_direct_signing_rfc8032_vector(key):
    assert key.sign(b"").hex() == (
        "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555f"
        "b8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b")


def test_signs_exact_wire_body_and_query(key):
    body = b'{ "code" : "US.NVDA" }\n'
    request = httpx.Request("POST", probe.HOST + probe.BOOK_PATH + "?z=a%20b&a=%2F", content=body)
    probe.sign_request(request, "offline-test-id", key, 123, "offline_nonce")
    assert request.url.query == b"z=a%20b&a=%2F"
    payload = b"123\nPOST\n/api/v1.0/quote/order-book\nz=a%20b&a=%2F\n" + hashlib.sha256(body).hexdigest().encode()
    key.public_key().verify(base64.b64decode(request.headers["Authorization"], validate=True), payload)
    assert request.content == body
    assert request.headers["X-Timestamp"] == "123"
    assert request.headers["X-Nonce"] == "offline_nonce"
    assert not request.headers["Authorization"].startswith("Bearer")
    assert probe.signing_payload(123, "POST", probe.BOOK_PATH, "", body) != probe.signing_payload(123, "POST", probe.BOOK_PATH, "", b'{"code":"US.NVDA"}')


@pytest.mark.parametrize("url,method", [
    ("https://example.com" + probe.BOOK_PATH, "POST"),
    ("http://webapi.moomoo.com" + probe.BOOK_PATH, "POST"),
    (probe.HOST + "/api/v1.0/trading/accounts", "POST"),
    (probe.HOST + probe.BOOK_PATH, "GET"),
    ("https://webapi.moomoo.com:8443" + probe.BOOK_PATH, "POST"),
])
def test_no_account_trade_or_other_destination_can_be_signed(key, url, method):
    with pytest.raises(probe.DiagnosticError):
        probe.sign_request(httpx.Request(method, url), "offline-test-id", key, 123, "nonce")


def test_depth_fields_flags_precision_and_freshness(depth):
    before = copy.deepcopy(depth)
    result = probe.parse_book(depth, NOW, 10)
    first, second = result["books"]
    assert first["bid_verified_levels"] == first["ask_verified_levels"] == 2
    assert first["exchange"] == "NASDAQ"
    assert "entitlement unconfirmed" in first["classification"]
    assert first["freshness"]["estimated_age_ms"] == 110
    assert first["provider_dispatch_delay_ms"] == 20
    assert first["estimated_dispatch_to_receive_ms"] == 90
    assert first["bid_sample"][1]["order_count"] == 0
    assert second["exchange"] == "ARCA"
    assert second["ask_verified_levels"] == 0
    assert second["bid_sample"][0]["volume"] == 12345
    assert second["order_volume_precision"] == 2
    assert depth == before


def test_unlabeled_depth_is_not_claimed_to_be_consolidated(depth):
    depth["data"][0]["books"][0]["exchange"] = ""
    result = probe.parse_book(depth, NOW, None)["books"][0]
    assert "consolidation unconfirmed" in result["classification"]
    assert result["freshness"]["estimated_age_ms"] is None


def test_invalid_side_flag_does_not_prove_depth(depth):
    depth["data"][0]["books"][0]["bid_flag"] = 0
    book = probe.parse_book(depth, NOW, 0)["books"][0]
    assert book["bid_returned_levels"] == 2
    assert book["bid_verified_levels"] == 0


@pytest.mark.parametrize("change", [
    lambda d: d.update(data={}),
    lambda d: d["data"][0].update(code="US.AAPL"),
    lambda d: d["data"][0].update(books=[]),
    lambda d: d["data"][0]["books"][0].update(bid_list=None),
    lambda d: d["data"][0]["books"][0].update(ask_list=[12]),
    lambda d: d.update(ret_code=True),
])
def test_bad_shapes_are_refused(depth, change):
    change(depth)
    with pytest.raises(probe.DiagnosticError):
        probe.parse_book(depth, NOW, 0)


def test_quote_parser_uses_rest_millisecond_field(quote):
    result = probe.parse_quote(quote, NOW, 0)
    assert result["last_price"] == 180.02
    assert result["freshness"]["estimated_age_ms"] == 100


def test_reflected_secrets_and_nonfinite_data_are_not_printed(depth):
    depth["secret"] = "DO-NOT-ECHO"
    book = depth["data"][0]["books"][0]
    book["exchange"] = "DO-NOT-ECHO"
    book["bid_list"][0].update(price="DO-NOT-ECHO", volume=float("nan"))
    result = probe.parse_book(depth, NOW, 0)
    assert "DO-NOT-ECHO" not in json.dumps(result, allow_nan=False)
    assert result["books"][0]["bid_sample"][0]["price"] is None
    assert result["books"][0]["bid_verified_levels"] == 1
    assert probe.api_result({"ret_code": -3, "ret_msg": "DO-NOT-ECHO"}) == {"ret_code": -3, "status": "api_error"}
    assert probe.numeric_headers(httpx.Headers({"X-Ratelimit-Limit": "100", "Retry-After": "DO-NOT-ECHO"})) == {"x-ratelimit-limit": "100"}


def test_zero_and_missing_timestamps_are_preserved_without_age_estimate(depth):
    depth["data"][0]["books"][0]["exchange_data_time_ms"] = 0
    book = probe.parse_book(depth, NOW, 0)["books"][0]
    assert book["freshness"]["reported_source_time_ms"] == 0
    assert book["freshness"]["source_time_ms"] is None
    assert book["freshness"]["estimated_age_ms"] is None
    assert probe.number(10**1000) is None
    assert probe.number(True) is None


def test_bounded_three_request_flow_signing_redaction_and_close(key, quote, depth, monkeypatch):
    seen = []
    monkeypatch.setattr(probe.time, "sleep", lambda seconds: None)

    def serve(request):
        seen.append(request)
        if request.url.path == probe.TIME_PATH:
            assert "X-Api-Key" not in request.headers
            return httpx.Response(200, json={"server_time_ms": str(NOW)})
        assert request.headers["X-Api-Key"] == "offline-test-id"
        assert json.loads(request.content) in ({"code_list": ["US.NVDA"]}, {"code": "US.NVDA"})
        key.public_key().verify(base64.b64decode(request.headers["Authorization"]),
                                probe.signing_payload(int(request.headers["X-Timestamp"]), "POST", request.url.path, "", request.content))
        return httpx.Response(200, json=quote if request.url.path == probe.QUOTE_PATH else depth)

    with httpx.Client(transport=httpx.MockTransport(serve)) as client:
        result = probe.probe(client, "offline-test-id", key)
    assert client.is_closed
    assert len(seen) == 3
    assert result["quote"]["status"] == result["order_book"]["status"] == "success"
    assert result["websocket"]["status"] == "not_requested"
    assert "offline-test-id" not in json.dumps(result)


@pytest.mark.parametrize("status", [401, 403, 429])
def test_stops_after_refusal_without_retries(key, status):
    seen = []

    def serve(request):
        seen.append(request)
        return httpx.Response(200, json={"server_time_ms": str(NOW)}) if len(seen) == 1 else httpx.Response(status, text="DO-NOT-ECHO")

    with httpx.Client(transport=httpx.MockTransport(serve)) as client:
        result = probe.probe(client, "offline-test-id", key)
    assert len(seen) == 2
    assert result["quote"]["http_status"] == status
    assert "order_book" not in result
    assert "DO-NOT-ECHO" not in json.dumps(result)


@pytest.mark.parametrize("status", [401, 403, 429])
def test_server_time_refusal_stops_all_signed_requests(key, status):
    seen = []

    def serve(request):
        seen.append(request)
        return httpx.Response(status, text="DO-NOT-ECHO", headers={"Retry-After": "60"})

    with httpx.Client(transport=httpx.MockTransport(serve)) as client:
        result = probe.probe(client, "offline-test-id", key)
    assert client.is_closed
    assert len(seen) == 1
    assert result["clock"]["http_status"] == status
    assert "quote" not in result and "order_book" not in result
    assert "DO-NOT-ECHO" not in json.dumps(result)


def test_credentials_require_private_owned_regular_files(tmp_path):
    tmp_path.chmod(0o700)
    path = tmp_path / "credential"
    path.write_text("synthetic")
    path.chmod(0o600)
    assert probe.secure_read(path) == b"synthetic"
    path.chmod(0o644)
    with pytest.raises(probe.DiagnosticError):
        probe.secure_read(path)
    link = tmp_path / "link"
    link.symlink_to(path)
    with pytest.raises(OSError):
        probe.secure_read(link)


def test_configure_hidden_input_does_not_echo_or_overwrite(tmp_path, key, monkeypatch, capsys):
    tmp_path.chmod(0o700)
    private = tmp_path / "phase1-ed25519.pem"
    private.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    private.chmod(0o600)
    monkeypatch.setattr(probe, "KEY_DIR", tmp_path)
    monkeypatch.setattr(probe, "getpass", lambda prompt: "offline-test-id")
    probe.configure()
    assert probe.secure_read(tmp_path / "appkey") == b"offline-test-id"
    assert "offline-test-id" not in capsys.readouterr().out
    with pytest.raises(FileExistsError):
        probe.configure()


def test_configure_refuses_getpass_echo_fallback_before_reading(tmp_path, key, monkeypatch):
    tmp_path.chmod(0o700)
    private = tmp_path / "phase1-ed25519.pem"
    private.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    private.chmod(0o600)
    input_stream = io.StringIO("offline-test-id\n")
    monkeypatch.setattr(probe, "KEY_DIR", tmp_path)
    monkeypatch.setattr(probe, "getpass", getpass.fallback_getpass)
    monkeypatch.setattr("sys.stdin", input_stream)
    with pytest.raises(probe.DiagnosticError, match="Hidden terminal input is unavailable"):
        probe.configure()
    assert input_stream.tell() == 0
    assert not (tmp_path / "appkey").exists()


def test_websocket_signature_four_fields_no_trailing_newline(key):
    vector = json.loads((FIXTURES / "ws_signature.json").read_text())
    frame = probe.websocket_auth("offline-test-id", key, vector["timestamp_ms"], vector["nonce"])
    expected = vector["payload"].encode("utf-8")
    key.public_key().verify(base64.b64decode(frame["data"]["authorization"], validate=True), expected)
    assert frame["data"]["authorization"] == vector["signature_base64"]
    assert frame["data"]["auth_type"] == "appkey"
    assert probe.signing_payload(1782357937000, "POST", "ws/auth", "", b"") != expected


class FakeSocket:
    def __init__(self, auth_fail=False, subscribe_fail=None, uncorrelated=False, silence=False, envelope=False, unsubscribe_fail=False):
        self.queue = asyncio.Queue()
        self.sent = []
        self.close_code = None
        self.auth_fail = auth_fail
        self.subscribe_fail = subscribe_fail
        self.uncorrelated = uncorrelated
        self.silence = silence
        self.envelope = envelope
        self.unsubscribe_fail = unsubscribe_fail

    async def send(self, raw):
        frame = json.loads(raw)
        self.sent.append(frame)
        if frame["action"] == "auth":
            message = {"id": frame["id"], "code": -1, "message": "DO-NOT-ECHO"} if self.auth_fail else {
                "id": frame["id"], "session_id": "DO-NOT-ECHO", "server_time": NOW * 1000}
        else:
            failed = self.subscribe_fail == frame["id"] or (self.unsubscribe_fail and frame["action"] == "unsubscribe")
            message = {"id": frame["id"], "code": 4 if failed else 0, "message": "DO-NOT-ECHO"}
            if self.envelope:
                message = {"ret_code": 0, "data": message}
        if self.uncorrelated:
            message.pop("id")
        if not self.silence:
            await self.queue.put(json.dumps(message))

    async def recv(self):
        return await self.queue.get()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        self.close_code = 1000


@pytest.mark.parametrize("envelope", [False, True])
def test_websocket_auth_subscribe_no_messages_unsubscribe_close(key, envelope):
    socket = FakeSocket(envelope=envelope)

    def connector(url, **kwargs):
        assert url == "wss://webapi-quote.moomoo.com/ws"
        assert kwargs["proxy"] is None
        assert kwargs["max_size"] == 1024 * 1024
        assert kwargs["ping_interval"] == 20
        return socket

    result = asyncio.run(probe.stream_probe("offline-test-id", key, 1, connector))
    assert result["authentication"]["status"] == "success"
    assert all(result["subscriptions"][kind]["status"] == "success" for kind in probe.STREAM_TYPES)
    assert [frame["action"] for frame in socket.sent] == ["auth", "subscribe", "subscribe", "subscribe", "unsubscribe"]
    assert result["unsubscribe"]["status"] == "success"
    assert result["closed"]
    assert result["message_counts"] == {"QUOTE": 0, "ORDER_BOOK": 0, "TICKER": 0}
    assert "offline-test-id" not in json.dumps(result) and "DO-NOT-ECHO" not in json.dumps(result)


@pytest.mark.parametrize("uncorrelated", [False, True])
def test_websocket_auth_failure_never_subscribes_and_redacts(key, uncorrelated):
    socket = FakeSocket(auth_fail=True, uncorrelated=uncorrelated)
    result = asyncio.run(probe.stream_probe("offline-test-id", key, 1, lambda *a, **k: socket))
    assert [frame["action"] for frame in socket.sent] == ["auth"]
    assert result["closed"]
    assert result["authentication"]["status"] != "success"
    assert "DO-NOT-ECHO" not in json.dumps(result)


def test_websocket_auth_timeout_closes_without_subscribing(key):
    socket = FakeSocket(silence=True)
    result = asyncio.run(probe.stream_probe("offline-test-id", key, 1, lambda *a, **k: socket))
    assert len(socket.sent) == 1
    assert result["status"] == "failed_or_timed_out"
    assert result["closed"]


def test_websocket_subscriptions_have_separate_acks_and_release_attempted_types(key):
    socket = FakeSocket(subscribe_fail="sub-order_book")
    result = asyncio.run(probe.stream_probe("offline-test-id", key, 1, lambda *a, **k: socket))
    assert result["subscriptions"]["quote"]["status"] == "success"
    assert result["subscriptions"]["order_book"]["code"] == 4
    assert result["subscriptions"]["ticker"]["status"] == "success"
    assert all(socket.sent[-1][kind] == ["US.NVDA"] for kind in probe.STREAM_TYPES)
    assert result["unsubscribe"]["status"] == "success" and result["closed"]


def test_websocket_failed_unsubscribe_still_closes(key):
    socket = FakeSocket(envelope=True, unsubscribe_fail=True)
    result = asyncio.run(probe.stream_probe("offline-test-id", key, 1, lambda *a, **k: socket))
    assert result["unsubscribe"]["status"] == "failed"
    assert result["closed"]


def test_streaming_push_fixture_summaries_and_missing_fields(depth):
    data = depth["data"][0]
    book = probe.push_summary({"type": "ORDER_BOOK", "symbol": "US.NVDA", "data": data}, NOW, 0)
    assert book["books"][0]["bid_levels"] == 2
    assert book["books"][0]["exchange"] == "NASDAQ"
    assert book["books"][0]["bid_valid_entries"] == 2
    assert book["books"][0]["bid_distinct_prices"] == 2
    quote = probe.push_summary({"type": "QUOTE", "symbol": "US.NVDA", "data": {"last_price": 1, "data_time_ms": NOW}}, NOW, 0)
    assert quote["freshness"]["estimated_age_ms"] == 0
    tick = probe.push_summary({"type": "TICKER", "symbol": "US.NVDA", "data": {"ticker_list": [{"time_ms": NOW, "price": 1, "mpid": "DO-NOT-ECHO"}]}}, NOW, 0)
    assert tick["tick_count"] == 1
    assert "DO-NOT-ECHO" not in json.dumps(tick)
    assert probe.push_summary({"type": "UNKNOWN", "symbol": "US.NVDA", "data": {}}, NOW, 0) is None


def test_streaming_optional_lists_zero_prices_and_duplicate_prices():
    message = {"type": "ORDER_BOOK", "symbol": "US.NVDA", "data": {
        "bid_list": [{"price": 1, "volume": 1, "mpid": "ARCA"}, {"price": 1, "volume": 2, "mpid": "NITE"}, {"price": 0, "volume": 0}],
        "ask_list": None}}
    book = probe.push_summary(message, NOW, 0)["books"][0]
    assert book["bid_levels"] == 3
    assert book["bid_valid_entries"] == 2
    assert book["bid_distinct_prices"] == 1
    assert book["bid_mpids"] == ["ARCA", "NITE"]
    assert book["ask_levels"] is None
    assert not book["ask_list_available"]


@pytest.mark.parametrize("seconds", [0, 61, 600])
def test_stream_core_cannot_outlive_refresh_requirement(key, seconds):
    with pytest.raises(probe.DiagnosticError):
        asyncio.run(probe.stream_probe("offline-test-id", key, seconds))


@pytest.mark.parametrize("status", [300, 301, 302, 303, 307, 308])
def test_websocket_handshake_redirect_refused_before_auth(key, status):
    exc = InvalidStatus(Response(status, "Redirect", Headers({"Location": "wss://outside-allowlist.example/ws"})))
    client = probe.NoRedirectConnect(probe.WS_URL, proxy=None)
    assert client.process_redirect(exc) is exc
    assert client.uri == probe.WS_URL

    class RefusedHandshake:
        async def __aenter__(self):
            raise client.process_redirect(exc)

        async def __aexit__(self, *args):
            pytest.fail("handshake did not establish a connection")

    result = asyncio.run(probe.stream_probe("offline-test-id", key, 1, lambda *a, **k: RefusedHandshake()))
    assert result["authentication"]["status"] == "unconfirmed"
    assert all(result["subscriptions"][kind]["status"] == "not_attempted" for kind in probe.STREAM_TYPES)
    assert "offline-test-id" not in json.dumps(result)
    assert "outside-allowlist" not in json.dumps(result)
