"""Pooled chart transport preserves per-request auth/timeouts and no cookie reuse."""
import httpx
from app.engine import market_http


def test_pooled_transport_is_reused_without_credentials_or_cookies_leaking(monkeypatch):
    market_http.close()
    requests = []
    created = []
    client_type = httpx.Client

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"ok": True}, headers={"set-cookie": "provider_session=private"})

    def create(**kwargs):
        client = client_type(transport=httpx.MockTransport(respond), **kwargs)
        created.append(client)
        return client

    monkeypatch.setattr(market_http.httpx, "Client", create)
    try:
        market_http.get("https://provider-a.test/bars", headers={"Authorization": "Bearer invented-a"}, params={"symbol": "SPY"}, timeout=3)
        market_http.get("https://provider-a.test/bars", headers={"Authorization": "Bearer invented-b"}, timeout=5)
        market_http.get("https://provider-b.test/bars", timeout=2)
        assert len(created) == 1
        assert requests[0].url.params["symbol"] == "SPY"
        assert requests[0].extensions["timeout"]["read"] == 3
        assert requests[1].extensions["timeout"]["read"] == 5
        assert requests[1].headers["authorization"] == "Bearer invented-b"
        assert "authorization" not in requests[2].headers
        assert all("cookie" not in r.headers for r in requests)
    finally:
        market_http.close()
    assert created[0].is_closed
