"""Notification routing uses one fixed IPv4 connection, including on refusal."""

import importlib.util
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread
from urllib.error import HTTPError, URLError

import httpx
import pytest

from app.engine import ntfy


@pytest.fixture
def alerts():
    path = Path(__file__).resolve().parents[2] / "deploy/alerts.py"
    spec = importlib.util.spec_from_file_location("ntfy_deployment_alerts", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("sender", ["api", "health"])
@pytest.mark.parametrize("status", [200, 307, 429])
def test_fixed_ipv4_publishes_once_and_preserves_payload(sender, status, alerts, monkeypatch):
    requests = []
    bindings = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            requests.append((self.path, self.headers.get("Authorization"),
                             json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
            self.send_response(status)
            if status == 307:
                self.send_header("Location", "/unexpected-redirect")
            self.end_headers()
            self.wfile.write(b'{"id":"receipt-123"}')

        def log_message(self, *_):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    transport = httpx.HTTPTransport

    def bound_transport(**kwargs):
        bindings.append(kwargs)
        return transport(**kwargs)

    def no_default_route(*args, **kwargs):
        pytest.fail("An IPv4-only notification must not use the default route or fall back")

    monkeypatch.setattr(httpx, "HTTPTransport", bound_transport)
    monkeypatch.setattr(httpx, "post", no_default_route)
    monkeypatch.setattr(alerts, "urlopen", no_default_route)
    config = {"NTFY_URL": f"http://localhost:{server.server_port}/fixture-topic", "NTFY_TOKEN": "fixture-token",
              "NTFY_IPV4_ONLY": "true", "ALERT_APP_URL": "https://fixture.invalid"}
    try:
        if sender == "api":
            for key, value in config.items():
                monkeypatch.setenv(key, value)
            if status != 200:
                with pytest.raises(ntfy.NtfyError, match=str(status)):
                    ntfy.publish("Test → phone", "Test only")
            else:
                assert ntfy.publish("Test → phone", "Test only") == "receipt-123"
        elif status != 200:
            with pytest.raises(HTTPError) as error:
                alerts.publish(config, "Test → phone", "Test only")
            assert error.value.code == status
        else:
            alerts.publish(config, "Test → phone", "Test only")
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()
    assert bindings == [{"local_address": "0.0.0.0"}]
    assert len(requests) == 1
    path, authorization, payload = requests[0]
    assert (path, authorization) == ("/", "Bearer fixture-token")
    assert {key: payload[key] for key in ("topic", "title", "message", "click")} == {
        "topic": "fixture-topic", "title": "Test → phone", "message": "Test only", "click": "https://fixture.invalid"}


@pytest.mark.parametrize("sender", ["api", "health"])
def test_fixed_ipv4_network_failure_keeps_existing_error_contract(sender, alerts, monkeypatch):
    def fail(*args, **kwargs):
        raise httpx.ConnectError("fixture connection unavailable")

    monkeypatch.setattr(httpx.Client, "post", fail)
    config = {"NTFY_URL": "https://fixture.invalid/topic", "NTFY_IPV4_ONLY": "true"}
    if sender == "api":
        for key, value in config.items():
            monkeypatch.setenv(key, value)
        with pytest.raises(ntfy.NtfyError, match="ConnectError"):
            ntfy.publish("Test", "Test")
    else:
        with pytest.raises(URLError, match="ConnectError"):
            alerts.publish(config, "Test", "Test")
