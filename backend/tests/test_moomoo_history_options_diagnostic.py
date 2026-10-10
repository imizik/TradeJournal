"""Offline fixed fixtures and mocked HTTP; never read actual credentials."""

import base64
import copy
import json
import logging
from pathlib import Path
import threading

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import httpx
import pytest

from scripts import moomoo_history_options_diagnostic as probe

FIXTURE = json.loads((Path(__file__).parent / "fixtures/moomoo/history_comparison.json").read_text())
RFC_SEED = bytes.fromhex("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60")


def reader(handler):
    return probe.Reader(httpx.Client(transport=httpx.MockTransport(handler)), probe.DEFAULT_DAY,
                        "public-test-appkey", Ed25519PrivateKey.from_private_bytes(RFC_SEED))


@pytest.fixture(autouse=True)
def no_wait(monkeypatch):
    monkeypatch.setattr(probe.time, "sleep", lambda seconds: None)


def test_exact_get_signature_vector():
    query = "start=2026-10-09&end=2026-10-09&ktype=1&autype=0&num=370&extended_time=0"
    request = httpx.Request("GET", probe.HOST + "/api/v1.0/quote/US.NVDA/history-kline?" + query)
    key = Ed25519PrivateKey.from_private_bytes(RFC_SEED)
    probe.sign_history(request, "public-test-appkey", key, 1782357937000, probe.DEFAULT_DAY)
    payload = b"1782357937000\nGET\n/api/v1.0/quote/US.NVDA/history-kline\n" + query.encode() + b"\n"
    key.public_key().verify(base64.b64decode(request.headers["Authorization"]), payload)
    assert request.headers["Authorization"] == "soy4ITeeExnHIQxTMgwwsAhTWvlL+eFbw1a2bypBbygkc8hs3pdRMgWa9AJBJD0azl8WIT7CP0v8HM4K/YtCAg=="
    assert request.content == b""
    assert request.url.query == query.encode()
    assert not request.headers["Authorization"].startswith("Bearer")


@pytest.mark.parametrize("url,method", [
    ("https://other.example/api/v1.0/quote/US.NVDA/history-kline", "GET"),
    (probe.HOST + "/api/v1.0/trading/accounts", "GET"),
    (probe.HOST + "/api/v1.0/quote/US.NVDA/history-kline", "POST"),
    (probe.HOST + "/api/v1.0/quote/US.AAPL/history-kline", "GET"),
    ("http://webapi.moomoo.com/api/v1.0/quote/US.NVDA/history-kline", "GET"),
    ("https://webapi.moomoo.com:8443/api/v1.0/quote/US.NVDA/history-kline", "GET"),
    ("https://user:password@webapi.moomoo.com/api/v1.0/quote/US.NVDA/history-kline", "GET"),
    (probe.HOST + probe.TIME_PATH, "GET"),
])
def test_refuse_outside_signing_allowlist(url, method):
    request = httpx.Request(method, url)
    with pytest.raises(probe.DiagnosticError):
        probe.sign_history(request, "public-test-appkey", Ed25519PrivateKey.from_private_bytes(RFC_SEED), 1, probe.DEFAULT_DAY)
    assert "Authorization" not in request.headers


@pytest.mark.parametrize("status", [401, 403, 429])
def test_http_refusal_stops_remaining_provider_reads(status):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(status, json={"message": "secret-reflection"})
    r = reader(handler)
    assert r.read("first", "moomoo", "GET", probe.HOST + probe.TIME_PATH) is None
    assert r.read("second", "moomoo", "POST", probe.HOST + probe.BASIC_PATH, body={"code_list": [probe.UNDERLYING]}) is None
    assert len(calls) == 1
    assert r.records["second"]["status"] == "skipped_after_refusal"
    assert "secret-reflection" not in json.dumps(r.records)
    r.client.close()


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_redirects_are_not_followed(status):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(status, headers={"Location": "https://other.example/collect"})
    r = reader(handler)
    assert r.read("redirect", "moomoo", "POST", probe.HOST + probe.BASIC_PATH, body={"code_list": [probe.UNDERLYING]}) is None
    assert len(calls) == 1
    assert r.records["redirect"]["http_status"] == status
    r.client.close()


def test_signature_failure_does_not_retry_or_copy_message():
    r = reader(lambda request: httpx.Response(200, json={"ret_code": -12006, "ret_msg": "secret-reflection"}))
    assert r.read("bad", "moomoo", "POST", probe.HOST + probe.BASIC_PATH, body={"code_list": [probe.UNDERLYING]}) is None
    assert r.read("next", "moomoo", "POST", probe.HOST + probe.BASIC_PATH) is None
    assert r.count == 1
    assert "secret-reflection" not in json.dumps(r.records)
    r.client.close()


def test_oversized_response_and_request_budget():
    r = reader(lambda request: httpx.Response(200, content=b"x" * (probe.MAX_BYTES + 1)))
    assert r.read("large", "moomoo", "GET", probe.HOST + probe.TIME_PATH) is None
    assert r.records["large"]["status"] == "response_budget_exceeded"
    r.count = probe.MAX_REQUESTS
    assert r.read("budget", "moomoo", "GET", probe.HOST + probe.TIME_PATH) is None
    assert r.records["budget"]["status"] == "diagnostic_budget_exhausted"
    r.client.close()


def test_slow_small_chunks_stop_without_buffering_and_close(monkeypatch):
    clock = [0.0]
    class Trickle(httpx.SyncByteStream):
        consumed = 0
        closed = False
        def __iter__(self):
            for _ in range(1000):
                clock[0] += 14
                self.consumed += 1
                yield b"x" * 1024
        def close(self):
            self.closed = True
    stream = Trickle()
    monkeypatch.setattr(probe.time, "monotonic", lambda: clock[0])
    r = reader(lambda request: httpx.Response(200, stream=stream))
    r.last_request = -10
    assert r.read("trickle", "moomoo", "GET", probe.HOST + probe.TIME_PATH) is None
    assert r.records["trickle"]["status"] == "response_deadline_exceeded"
    assert stream.consumed == 2  # formerly 64 chunks / 896 simulated seconds
    assert stream.closed
    r.client.close()


def test_hard_deadline_interrupts_header_trickle_and_restores_timer(monkeypatch):
    if not hasattr(probe.signal, "setitimer"):
        pytest.skip("Unix deadline CLI")
    previous = probe.signal.getsignal(probe.signal.SIGALRM)
    monkeypatch.setattr(probe, "REQUEST_SECONDS", 0.01)
    def handler(request):
        assert max(request.extensions["timeout"].values()) <= 0.01
        threading.Event().wait(0.2)  # in-memory header wait, no socket/service
        return httpx.Response(200, json={})
    r = reader(handler)
    started = probe.time.perf_counter()
    assert r.read("headers", "moomoo", "GET", probe.HOST + probe.TIME_PATH) is None
    assert probe.time.perf_counter() - started < 0.15
    assert r.records["headers"]["status"] == "response_deadline_exceeded"
    assert probe.signal.getitimer(probe.signal.ITIMER_REAL) == (0.0, 0.0)
    assert probe.signal.getsignal(probe.signal.SIGALRM) == previous
    r.client.close()


def test_existing_debug_child_logger_cannot_emit_reflected_header(caplog):
    caplog.set_level(logging.DEBUG)
    child = logging.getLogger("httpcore.http11")
    old_level = child.level
    child.setLevel(logging.DEBUG)
    old_disable = logging.root.manager.disable
    try:
        def handler(request):
            child.debug("receive_response_headers.complete %s", {"x-reflection": "fixture-secret"})
            logging.getLogger("httpcore.future_child").debug("fixture-secret")
            return httpx.Response(200, json={}, headers={"x-reflection": "fixture-secret"})
        r = reader(handler)
        assert r.read("quiet", "moomoo", "GET", probe.HOST + probe.TIME_PATH) == {}
        assert "fixture-secret" not in caplog.text
        assert "fixture-secret" not in json.dumps(r.records)
        assert logging.root.manager.disable == old_disable
        child.debug("control-after-probe")
        assert "control-after-probe" in caplog.text
        r.client.close()
    finally:
        child.setLevel(old_level)


def test_unexpected_compression_is_refused_before_decoding():
    r = reader(lambda request: httpx.Response(200, stream=httpx.ByteStream(b"not-gzip"), headers={"content-encoding": "gzip"}))
    assert r.read("encoding", "moomoo", "GET", probe.HOST + probe.TIME_PATH) is None
    assert r.records["encoding"]["status"] == "unexpected_content_encoding"
    r.client.close()


def test_fixture_precision_and_matched_minute_comparison():
    r = reader(lambda request: httpx.Response(200, json=FIXTURE["moomoo"]))
    left, stats, shifted = probe.history(r, probe.UNDERLYING)
    right, baseline = probe.parse_bars(FIXTURE["alpaca"]["bars"]["NVDA"], "alpaca", probe.DEFAULT_DAY)
    result = probe.compare_bars(left, right)
    assert stats["pagination_has_more"] is True
    assert stats["page_limit"] == 1
    assert baseline["valid_regular_minutes"] == result["matched_minutes"] == 2
    assert result["fields"]["h"]["max_abs_difference"] == 0.5
    assert result["fields"]["v"]["max_abs_difference"] == 50
    assert result["fields"]["c"]["equal_minutes"] == 2
    assert result["shared_window_extremes"]["moomoo"]["high"] == 103
    r.client.close()


def test_missing_precision_stays_unknown_not_zero():
    payload = copy.deepcopy(FIXTURE["moomoo"])
    del payload["data"]["volume_precision"]
    r = reader(lambda request: httpx.Response(200, json=payload))
    bars, stats, shifted = probe.history(r, probe.UNDERLYING)
    assert stats["volume_comparison"] == "unavailable_precision"
    assert all(bar["v"] is None for bar in bars.values())
    assert probe.compare_bars(bars, bars)["fields"]["v"] == {"status": "unavailable_units"}
    r.client.close()


def test_duplicate_malformed_and_offsession_bars_are_excluded():
    rows = copy.deepcopy(FIXTURE["alpaca"]["bars"]["NVDA"])
    rows += [rows[0], {**rows[1], "c": float("nan")}, {**rows[1], "t": "2026-10-09T20:00:00Z"},
             {**rows[1], "t": "2026-10-09T13:32:00Z", "h": 1}, {**rows[1], "t": "2026-10-09T13:31:01Z"},
             {**rows[1], "t": "2026-10-09T13:31:00"}]
    bars, stats = probe.parse_bars(rows, "alpaca", probe.DEFAULT_DAY)
    assert len(bars) == 1
    assert stats["duplicates"] == 1
    assert stats["invalid"] == 4
    assert stats["outside_regular_session"] == 1


def test_no_overlap_does_not_claim_agreement():
    result = probe.compare_bars({}, {})
    assert result["status"] == "no_overlap"
    assert result["fields"]["c"]["max_abs_difference"] is None


def test_end_label_hypothesis_is_separate_and_preserves_close_bar():
    raw = copy.deepcopy(FIXTURE["moomoo"]["data"]["kline_list"])
    for row in raw:
        row["time_key"] += 60000
    labelled, raw_stats = probe.parse_bars(raw, "moomoo", probe.DEFAULT_DAY)
    shifted, stats = probe.parse_bars(raw, "moomoo", probe.DEFAULT_DAY, -60000)
    baseline, _ = probe.parse_bars(FIXTURE["moomoo"]["data"]["kline_list"], "moomoo", probe.DEFAULT_DAY)
    result = probe.compare_interpretations(labelled, shifted, baseline, True)
    assert raw_stats["first_ms"] == stats["first_ms"] + 60000
    assert result["as_reported_labels"]["matched_minutes"] == 1
    assert result["moomoo_end_label_hypothesis"]["matched_minutes"] == 2
    assert result["moomoo_end_label_hypothesis"]["fields"]["c"]["max_abs_difference"] == 0
    last = {**raw[0], "time_key": int(probe.datetime.fromisoformat("2026-10-09T20:00:00+00:00").timestamp() * 1000)}
    assert probe.parse_bars([last], "moomoo", probe.DEFAULT_DAY)[1]["outside_regular_session"] == 1
    assert probe.parse_bars([last], "moomoo", probe.DEFAULT_DAY, -60000)[1]["valid_regular_minutes"] == 1


def test_response_summaries_never_echo_arbitrary_strings():
    row = {k: "secret-reflection" for k in ("bid", "ask", "last", "greeks", "latestQuote", "latestTrade", "implied_volatility", "timestamp")}
    for provider in ("moomoo", "alpaca", "tradier"):
        assert "secret-reflection" not in json.dumps(probe.quote_fields(row, provider))
    assert probe.volatility({"data": {"item_list": [row]}})["timestamped_points"] == 0


@pytest.mark.parametrize("code,expected", [
    ("US.NVDA261016C230000", "NVDA261016C00230000"),
    ("US.NVDA270219P120000", "NVDA270219P00120000"),
    ("US.NVDA261016C00230000", "NVDA261016C00230000"),
    ("US.NVDA261099C230000", None), ("US.AAPL261016C230000", None),
    ("US.NVDA1261016C230000", None), ("US.NVDA261016C0", None),
    ("US.NVDA261016C230000/../accounts", None), (None, None),
])
def test_screen_contract_mapping_is_bounded(code, expected):
    assert probe.screen_occ(code) == expected


def test_settings_do_not_mutate_environment_or_interpolate(tmp_path, monkeypatch):
    path = tmp_path / "fixture.env"
    path.write_text("ALPACA_API_KEY=fixture-key\nPOLYGON_API_KEY=${DO_NOT_RESOLVE}\nUNRELATED=private\n")
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    values = probe.settings(path)
    assert values["POLYGON_API_KEY"] == "${DO_NOT_RESOLVE}"
    assert "UNRELATED" not in values
    assert "ALPACA_API_KEY" not in probe.os.environ


def test_empty_mock_run_is_bounded_and_returns_unavailability():
    r = reader(lambda request: httpx.Response(200, json={"ret_code": 0, "data": {}}))
    report = probe.run(r, {})
    assert report["request_count"] == 9
    assert report["history"][probe.ACTIVE]["schema"] == "missing_kline_list"
    assert report["history"][probe.ACTIVE]["valid_regular_minutes"] == 0
    assert report["alpaca"] == "credentials_unavailable"
    r.client.close()


def test_full_mock_comparison_uses_only_market_data_and_bounded_screen_symbols():
    seen = []
    sample = "US.NVDA270219P120000"
    def handler(request):
        seen.append(request)
        path = request.url.path
        if path == probe.TIME_PATH:
            return httpx.Response(200, json={"server_time_ms": str(int(probe.time.time() * 1000))})
        if path == probe.BASIC_PATH:
            return httpx.Response(200, json={"ret_code": 0, "data": {"basic_list": [{"code": probe.UNDERLYING, "stock_id": 99}]}})
        if path == probe.SCREEN_PATH:
            body = json.loads(request.content)
            assert body["limit"] == 5
            assert all(body["field_filter"][field] == 1 for field in ("bid_price", "ask_price", "open_interest", "multiplier"))
            assert body["strategy"]["filter_group_list"][0]["underlying_list"][0]["indicator_value"]["value_list"] == [99]
            return httpx.Response(200, json={"ret_code": 0, "data": {"option_list": [{"code": sample, "delta": -0.01}, {"code": "unsafe-reflection"}]}})
        if path.endswith("history-kline"):
            assert request.url.params["end"] == "2026-10-10"
            return httpx.Response(200, json=FIXTURE["moomoo"])
        if path == "/v2/stocks/bars":
            assert request.url.params["feed"] == "iex"
            return httpx.Response(200, json=FIXTURE["alpaca"])
        if path == "/v1beta1/options/snapshots":
            assert request.url.params["symbols"] == ",".join([probe.OCC[probe.ACTIVE], probe.OCC[probe.EXPIRED], "NVDA270219P00120000"])
            return httpx.Response(200, json={"snapshots": {"NVDA270219P00120000": {"greeks": {"delta": -0.01}}}})
        return httpx.Response(200, json={"ret_code": 0, "data": {}})
    r = reader(handler)
    report = probe.run(r, {"ALPACA_API_KEY": "fixture-key", "ALPACA_API_SECRET": "fixture-secret",
                           "TRADIER_API_KEY": "fixture-token", "POLYGON_API_KEY": "fixture-polygon"})
    assert report["request_count"] == len(seen) == 15 < probe.MAX_REQUESTS
    assert all("account" not in request.url.path and "order" not in request.url.path for request in seen)
    assert all("apiKey" not in request.url.params for request in seen)
    assert report["screen_current_comparison"]["NVDA270219P00120000"]["alpaca"]["greeks"]["delta"] == -0.01
    for text in ("fixture-key", "fixture-secret", "fixture-token", "fixture-polygon", "unsafe-reflection"):
        assert text not in json.dumps(report)
    r.client.close()


@pytest.mark.parametrize("status,exit_code", [("completed", 0), ("completed_with_request_failures", 1)])
def test_cli_exit_code_reports_request_failures(monkeypatch, capsys, status, exit_code):
    import sys
    key = Ed25519PrivateKey.from_private_bytes(RFC_SEED)
    pem = key.private_bytes(probe.serialization.Encoding.PEM, probe.serialization.PrivateFormat.PKCS8, probe.serialization.NoEncryption())
    monkeypatch.setattr(probe, "secure_read", lambda path: b"fixture-key" if path.name == "appkey" else pem)
    monkeypatch.setattr(probe, "settings", lambda path: {})
    monkeypatch.setattr(probe, "run", lambda *args: {"status": status})
    monkeypatch.setattr(sys, "argv", ["diagnostic"])
    assert probe.main() == exit_code
    assert json.loads(capsys.readouterr().out)["status"] == status
