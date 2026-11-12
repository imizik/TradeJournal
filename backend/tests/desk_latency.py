"""A desk app whose outside calls take real time, for the desk timing tests and the latency bench
(``tests/test_desk_bench.py``): every Tradier HTTP call (quotes, option quotes, minute bars, the market calendar), every
news read and every Robinhood MCP post sleeps ``latency.seconds`` and is counted, through the real caches above them.
Every value is invented."""

from __future__ import annotations

from datetime import date
import json
import threading
import time
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
import pytest
from sqlmodel import Session

from app.database import get_session
from app.engine import market_http, news, request_timing, robinhood_book as rb, robinhood_read as rh
from app.engine import quotes as quote_engine, tradier
from app.engine.chart_feed import chart_feed
from app.routers import charts, copilot_desk
from tests.robinhood_fake import FakeRobinhood, instrument, option_position, option_quote, token_file
from tests.test_today import buy, planned_nbis

OPTIONS = ("NBIS", "CRWV", "APLD", "IREN", "CIFR")
STOCKS = ("NVDA", "AMD", "PLTR", "SOFI", "HOOD", "MU")
latency = SimpleNamespace(seconds=0.35)


def _tradier_reply(url: str, params, data) -> dict:
    if url.endswith("/v1/markets/quotes"):
        asked = (params or {}).get("symbols") or (data or {}).get("symbols") or ""
        rows = [{"symbol": s, "last": 100.0, "prevclose": 99.0, "change": 1.0, "change_percentage": 1.01, "bid": 3.9, "ask": 4.1,
                 "type": "option" if len(s) > 10 else "stock", "greeks": {"mid_iv": 0.6, "delta": 0.5}} for s in asked.split(",") if s]
        return {"quotes": {"quote": rows}}
    if url.endswith("/v1/markets/calendar"):
        from calendar import monthrange
        year, month = int(params["year"]), int(params["month"])
        days = [{"date": f"{year}-{month:02d}-{d:02d}", "description": "",
                 **({"status": "open", "open": {"start": "09:30", "end": "16:00"}} if date(year, month, d).weekday() < 5 else {"status": "closed"})}
                for d in range(1, monthrange(year, month)[1] + 1)]
        return {"calendar": {"month": month, "year": year, "days": {"day": days}}}
    return {"series": None}


class Providers:
    """Counts and slows every outside call."""

    def __init__(self):
        self.calls: list[str] = []
        self.spans: list[tuple[str, str, float, float, str]] = []  # (kind, path, start, end, thread)
        self.robinhood_gate: threading.Event | None = None  # set: a Robinhood post waits for it

    def _span(self, kind, path, start):
        self.spans.append((kind, path, start, time.perf_counter(), threading.current_thread().name))

    def send(self, method, url, **kwargs):
        self.calls.append("tradier")
        start = time.perf_counter()
        time.sleep(latency.seconds)
        self._span("tradier", httpx.URL(url).path, start)
        body = _tradier_reply(url, kwargs.get("params"), kwargs.get("data"))
        return httpx.Response(200, content=json.dumps(body).encode(), headers={"content-type": "application/json"},
                              request=httpx.Request(method, url))

    def news(self, *args, **kwargs):
        self.calls.append("news")
        start = time.perf_counter()
        time.sleep(latency.seconds)
        self._span("news", "news", start)
        return {"news": []}


@pytest.fixture
def slow_desk(engine, clock, tmp_path, monkeypatch):
    providers = Providers()
    monkeypatch.delenv("RADAR_ENABLED", raising=False)
    monkeypatch.setenv("QUOTES_PROVIDER", "tradier")
    monkeypatch.setattr(tradier, "TRADIER_API_KEY", "bench-key")
    monkeypatch.setattr(market_http, "_send", providers.send)
    monkeypatch.setattr(news, "_alpaca_get_fast", providers.news)
    monkeypatch.setattr(news, "_alpaca_get", providers.news)
    monkeypatch.setattr(copilot_desk.copilot, "settings", lambda: SimpleNamespace(enabled=True))
    from app.engine.chart_calendar import chart_calendar
    monkeypatch.setattr(chart_calendar, "root", tmp_path / "calendar")  # the calendar's month files stay out of backend/data
    monkeypatch.setattr(chart_calendar, "_months", {})
    monkeypatch.setattr(chart_calendar, "_retry", {})

    # The book: five option positions (one planned), and on Robinhood the same five plus six stocks across accounts.
    planned_nbis(engine)
    for n, symbol in enumerate(OPTIONS[1:], start=600):
        buy(engine, n, symbol, expiration=date(2026, 11, 20), minute=10 + n % 40)
    server = FakeRobinhood()
    server.options = {"333338267": [option_position(f"opt-{s.lower()}", s, expiry="2026-11-20") for s in OPTIONS]}
    server.instruments = {f"opt-{s.lower()}": instrument(f"opt-{s.lower()}", s, expiry="2026-11-20") for s in OPTIONS}
    server.quotes = {f"opt-{s.lower()}": option_quote(f"opt-{s.lower()}") for s in OPTIONS}
    server.stocks = {"333338267": [{"symbol": s, "quantity": "10", "average_buy_price": "50", "type": "long"} for s in STOCKS[:3]],
                     "444447884": [{"symbol": s, "quantity": "5", "average_buy_price": "20", "type": "long"} for s in STOCKS[3:]]}
    server.stock_quotes = {s: {"quote": {"symbol": s, "last_trade_price": "55", "previous_close": "54"}} for s in STOCKS}

    def slow_transport(url, body, headers):
        providers.calls.append("robinhood")
        start = time.perf_counter()
        if providers.robinhood_gate is not None:
            providers.robinhood_gate.wait(10)
        time.sleep(latency.seconds)
        providers._span("robinhood", "mcp", start)
        return server.transport(url, body, headers)
    monkeypatch.setattr(rh, "_transport", slow_transport)
    signin = token_file(tmp_path / "robinhood-token.json")
    feed = rb.Feed(settings_fn=lambda: rb.Settings(enabled=True, token_file=str(signin), accounts=("roth ira", "mcp")),
                   now=lambda: clock["t"])
    monkeypatch.setattr(rb, "feed", feed)

    app = FastAPI()
    app.include_router(copilot_desk.router, prefix="/copilot")
    app.include_router(charts.router, prefix="/charts")
    app.add_middleware(request_timing.TimingMiddleware)

    def session():
        with Session(engine) as db:
            yield db
    app.dependency_overrides[get_session] = session

    def expire():
        """The minute boundary: every provider cache past its time, the Robinhood snapshot due."""
        chart_feed._cache.clear()
        chart_feed._calls.clear()  # the feed's per-minute call budget: these tests are not its traffic
        chart_feed._failed.clear()
        chart_feed._retry_at = 0.0
        for cache in (quote_engine._stock_cache, quote_engine._option_chain_cache, quote_engine._option_contract_cache,
                      copilot_desk._spark_cache):
            cache.clear()
        from app.engine import desk_feed, trader_context
        desk_feed._news_cache.clear()
        trader_context._news.clear()
        feed._attempt = 0.0
        if hasattr(feed, "_due"):
            feed._due = 0.0

    expire()
    request_timing.reset()
    if hasattr(copilot_desk, "warm_at_start"):
        # What the startup warm-up leaves before the first desk read (on the bench's clock, which is not today).
        from app.engine import premarket_prep
        from app.engine.chart_math import ET
        from datetime import datetime
        day = datetime.fromtimestamp(clock["t"], ET).date()
        chart_calendar.hours(day)
        premarket_prep._previous_close(chart_calendar, day)
        providers.calls.clear()
    with TestClient(app) as client:
        yield SimpleNamespace(client=client, providers=providers, feed=feed, expire=expire, clock=clock, engine=engine)
    expire()


