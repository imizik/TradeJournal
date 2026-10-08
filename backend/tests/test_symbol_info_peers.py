"""Peers strip (T3.4): normalizers on recorded Polygon and Tradier responses, the seven-day disk
cache, the 429 / busy fallbacks, one batched quote call, and the route."""

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
import pytest

from app.engine import symbol_info_peers_feed as module
from app.engine.chart_feed import ChartFeedError
from app.engine.symbol_info_peers import chips, normalize_related
from app.engine.symbol_info_peers_feed import SymbolPeers
from app.routers import symbol_info

FIXTURES = Path(__file__).parent / "fixtures"
NVDA = json.loads((FIXTURES / "polygon" / "related_nvda.json").read_text())
SPY = json.loads((FIXTURES / "polygon" / "related_spy.json").read_text())
QUOTES = json.loads((FIXTURES / "tradier" / "quotes_peers_2026-10-08.json").read_text())


def test_related_keeps_order_and_drops_self_duplicates_and_junk():
    assert normalize_related(NVDA, "NVDA") == ["GOOGL", "AMD", "MSFT", "GOOG", "META", "AMZN", "TSLA", "AAPL", "AVGO", "INTC"]
    assert "AMD" not in normalize_related(NVDA, "AMD")
    body = {"results": [{"ticker": "amd"}, {"ticker": "AMD"}, {"ticker": ""}, {"ticker": "bad one"}, {"x": 1}, "junk", {"ticker": "NVDA"}]}
    assert normalize_related(body, "NVDA") == ["AMD"]


def test_an_etf_response_has_no_results_key_and_means_no_peers():
    assert "results" not in SPY
    assert normalize_related(SPY, "SPY") == [] and normalize_related(None, "SPY") == [] and normalize_related({"results": None}, "SPY") == []


def test_chips_read_change_percentage_and_never_the_average_volume():
    out = chips(["GOOGL", "AMD", "ZZZZNOPE"], QUOTES)
    assert out[0] == {"symbol": "GOOGL", "name": "Alphabet Inc", "last": 347.95, "change_percentage": -0.73}
    assert out[1]["change_percentage"] == -4.38
    assert out[2] == {"symbol": "ZZZZNOPE", "name": None, "last": None, "change_percentage": None}  # unmatched keeps its chip
    assert "average_volume" not in json.dumps(out)


def test_one_symbol_quote_comes_back_as_an_object_not_a_list():
    single = {"quotes": {"quote": QUOTES["quotes"]["quote"][0]}}
    assert chips(["GOOGL"], single)[0]["last"] == 347.95
    assert chips(["GOOGL"], {"quotes": "null"})[0]["last"] is None


# --------------------------------------------------------------------- fetch

@pytest.fixture
def polygon(monkeypatch):
    calls = []
    answer = {"status": 200, "body": NVDA, "headers": {}}

    def get(url, params=None, **_):
        calls.append(url)
        return httpx.Response(answer["status"], json=answer["body"], headers=answer["headers"], request=httpx.Request("GET", url))

    monkeypatch.setattr(module.enricher, "POLYGON_API_KEY", "test-secret")
    monkeypatch.setattr(module.enricher, "_limiter", module.enricher._AdaptiveRateLimiter())
    monkeypatch.setattr(module.httpx, "get", get)
    return calls, answer


def feed(tmp_path, clock, quote_calls=None, fail=False):
    def quotes(tickers):
        if quote_calls is not None:
            quote_calls.append(tickers)
        if fail:
            raise ChartFeedError("Tradier is down.")
        return QUOTES, clock[0], None
    return SymbolPeers(root=tmp_path, clock=lambda: clock[0], quotes=quotes)


def test_one_batched_quote_call_serves_every_peer_and_polygon_is_cached_seven_days(tmp_path, polygon):
    calls, _ = polygon
    quote_calls, clock = [], [1_000_000.0]
    view = feed(tmp_path, clock, quote_calls).view("NVDA")
    assert view["state"] == "ready" and [p["symbol"] for p in view["peers"]][:3] == ["GOOGL", "AMD", "MSFT"]
    assert len(quote_calls) == 1 and sorted(quote_calls[0]) == sorted(p["symbol"] for p in view["peers"])
    assert view["source"]["state"] == "ok" and view["quotes"]["state"] == "ok" and "test-secret" not in json.dumps(view)
    clock[0] += 6 * 24 * 3600
    assert feed(tmp_path, clock).view("NVDA")["source"]["age_seconds"] == 6 * 24 * 3600  # a new process reads the disk copy
    assert len(calls) == 1
    clock[0] += 2 * 24 * 3600
    feed(tmp_path, clock).view("NVDA")
    assert len(calls) == 2


def test_an_etf_with_no_related_companies_is_none_and_makes_no_quote_call(tmp_path, polygon):
    calls, answer = polygon
    answer["body"] = SPY
    quote_calls = []
    view = feed(tmp_path, [1_000_000.0], quote_calls).view("SPY")
    assert view["state"] == "none" and view["peers"] == [] and quote_calls == []
    feed(tmp_path, [1_000_100.0]).view("SPY")
    assert len(calls) == 1  # the empty answer is cached too


def test_a_429_serves_the_cached_copy_with_its_age_and_stays_quiet_five_minutes(tmp_path, polygon):
    calls, answer = polygon
    clock = [1_000_000.0]
    peers = feed(tmp_path, clock)
    peers.view("NVDA")
    clock[0] += 8 * 24 * 3600
    answer.update(status=429, body={}, headers={"Retry-After": "30"})
    view = peers.view("NVDA")
    assert view["state"] == "ready" and view["peers"] and view["source"]["state"] == "stale"
    assert view["source"]["age_seconds"] == 8 * 24 * 3600 and "429" in view["source"]["message"]
    assert len(calls) == 2
    clock[0] += 299
    peers.view("NVDA")
    assert len(calls) == 2
    clock[0] += 2
    answer.update(status=200, body=NVDA)
    module.enricher._limiter = module.enricher._AdaptiveRateLimiter()  # the 429 slowed the shared limiter; start it fresh
    assert peers.view("NVDA")["source"]["state"] == "ok" and len(calls) == 3


def test_failure_without_a_cache_is_unavailable_and_not_configured_or_busy_never_calls_out(tmp_path, polygon, monkeypatch):
    calls, answer = polygon
    answer.update(status=500, body={})
    view = feed(tmp_path / "a", [1.0]).view("NVDA")
    assert view["state"] == "unavailable" and view["peers"] == [] and view["source"]["state"] == "failed"
    monkeypatch.setattr(module.enricher, "POLYGON_API_KEY", "")
    assert feed(tmp_path / "b", [1.0]).view("NVDA")["source"]["state"] == "not_configured"
    monkeypatch.setattr(module.enricher, "POLYGON_API_KEY", "k")
    monkeypatch.setattr(module.enricher._limiter, "reserve_within", lambda _max: None)
    assert "busy" in feed(tmp_path / "c", [1.0]).view("NVDA")["source"]["message"]
    assert len(calls) == 1


def test_a_failed_quote_call_keeps_the_chips_without_numbers(tmp_path, polygon):
    view = feed(tmp_path, [1_000_000.0], fail=True).view("NVDA")
    assert view["state"] == "ready" and view["quotes"]["state"] == "failed"
    assert all(p["change_percentage"] is None for p in view["peers"])


def test_route_returns_the_view_and_rejects_bad_tickers(tmp_path, polygon, monkeypatch):
    monkeypatch.setattr(symbol_info.symbol_info_peers_feed, "symbol_peers", feed(tmp_path, [1_000_000.0]))
    app = FastAPI()
    app.include_router(symbol_info.router, prefix="/charts")
    client = TestClient(app)
    body = client.get("/charts/symbol/NVDA/peers").json()
    assert body["symbol"] == "NVDA" and len(body["peers"]) == 10 and "apiKey" not in json.dumps(body)
    assert client.get("/charts/symbol/bad%20one/peers").status_code == 422


def test_the_default_quote_reader_makes_one_budgeted_tradier_call(monkeypatch):
    from app.engine import chart_feed as feed_module
    calls = []

    def get(url, params=None, **_):
        calls.append((url, params))
        return httpx.Response(200, json=QUOTES, request=httpx.Request("GET", url))

    monkeypatch.setattr(feed_module.tradier, "TRADIER_API_KEY", "test-secret")
    monkeypatch.setattr(feed_module.httpx, "get", get)
    data, _, issue = SymbolPeers._read_quotes(["AMD", "AVGO"])
    assert issue is None and "quotes" in data
    assert len(calls) == 1 and calls[0][0].endswith("/v1/markets/quotes") and calls[0][1] == {"symbols": "AMD,AVGO"}
