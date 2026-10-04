"""Stream prices cannot invent bars or open a session per browser tab."""

import asyncio
from datetime import date, datetime
import json

import httpx

from app.engine import chart_stream
from app.engine.chart_math import ET


MARKET_TIME = datetime(2026, 9, 29, 10, 2, tzinfo=ET).timestamp()


def event(price=264.9, *, symbol="MRVL", at=MARKET_TIME, **overrides):
    return {"type": "timesale", "symbol": symbol, "date": int(at * 1000), "last": price,
            "size": 100, "cancel": False, "correction": False, **overrides}


def test_stream_event_uses_new_york_session_buckets_and_rejects_bad_ticks():
    tick = chart_stream.trade_event(event(), now=MARKET_TIME)
    assert tick is not None
    assert tick["buckets"]["1m"]["time"] == int(MARKET_TIME)
    assert tick["buckets"]["5m"]["time"] == int(datetime(2026, 9, 29, 10, 0, tzinfo=ET).timestamp())
    assert tick["buckets"]["5m"]["extended"] is False
    assert chart_stream.trade_event(event(correction=True), now=MARKET_TIME) is None
    assert chart_stream.trade_event(event(cancel="true"), now=MARKET_TIME) is None
    assert chart_stream.trade_event(event(price=-1), now=MARKET_TIME) is None
    assert chart_stream.trade_event(event(at=MARKET_TIME - 180), now=MARKET_TIME) is None
    closed = datetime(2026, 9, 29, 20, 1, tzinfo=ET).timestamp()
    assert chart_stream.trade_event(event(at=closed), now=closed) is None


def test_stream_buckets_follow_the_calendar_on_early_close_and_holiday():
    half = {"status": "open", "open": 570, "close": 780}
    calendar = {date(2026, 11, 27): half, date(2026, 11, 26): {"status": "closed", "open": None, "close": None}}.get
    before_close = datetime(2026, 11, 27, 12, 58, tzinfo=ET).timestamp()
    tick = chart_stream.trade_event(event(at=before_close), now=before_close, calendar=calendar)
    assert tick["session"] == "regular"
    assert datetime.fromtimestamp(tick["buckets"]["1h"]["time"], ET).strftime("%H:%M") == "12:30"
    assert datetime.fromtimestamp(tick["buckets"]["1h"]["end_time"], ET).strftime("%H:%M") == "13:00"
    after_close = datetime(2026, 11, 27, 13, 7, tzinfo=ET).timestamp()
    post = chart_stream.trade_event(event(at=after_close), now=after_close, calendar=calendar)
    assert post["session"] == "post" and post["buckets"]["5m"]["extended"] is True
    assert datetime.fromtimestamp(post["buckets"]["5m"]["time"], ET).strftime("%H:%M") == "13:05"
    assert chart_stream.trade_event(event(at=after_close), now=after_close)["session"] == "regular"  # clock rule
    late = datetime(2026, 11, 27, 17, 1, tzinfo=ET).timestamp()
    assert chart_stream.trade_event(event(at=late), now=late, calendar=calendar) is None
    holiday = datetime(2026, 11, 26, 10, 0, tzinfo=ET).timestamp()
    assert chart_stream.trade_event(event(at=holiday), now=holiday, calendar=calendar) is None


def test_session_uses_websocket_endpoint_when_provider_returns_http_stream_url(monkeypatch):
    def response(request):
        assert request.url.path == "/v1/markets/events/session"
        return httpx.Response(200, json={"stream": {"url": "https://stream.tradier.com/v1/markets/events",
                                                    "sessionid": "temporary-session"}})

    real_client = httpx.AsyncClient
    transport = httpx.MockTransport(response)
    monkeypatch.setattr(chart_stream.httpx, "AsyncClient", lambda **kwargs: real_client(transport=transport, **kwargs))
    monkeypatch.setattr(chart_stream.tradier, "TRADIER_API_KEY", "test-token")
    url, session_id = asyncio.run(chart_stream.ChartMarketStream()._session())
    assert url == "wss://ws.tradier.com/v1/markets/events"
    assert session_id == "temporary-session"


def test_one_upstream_connection_serves_tabs_and_updates_symbols(monkeypatch):
    class Socket:
        def __init__(self):
            self.sent = []
            self.incoming = asyncio.Queue()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def send(self, payload):
            self.sent.append(json.loads(payload))

        async def recv(self):
            return await self.incoming.get()

    async def scenario():
        socket = Socket()
        market = chart_stream.ChartMarketStream()
        sessions = 0

        async def session():
            nonlocal sessions
            sessions += 1
            return "wss://ws.tradier.com/v1/markets/events", "test-session"

        monkeypatch.setattr(market, "_session", session)
        monkeypatch.setattr(chart_stream, "connect", lambda *_args, **_kwargs: socket)
        first, _ = market.subscribe("MRVL")
        second, _ = market.subscribe("MRVL")
        for _ in range(100):
            if socket.sent:
                break
            await asyncio.sleep(0.01)
        assert sessions == 1
        assert socket.sent[0]["symbols"] == ["MRVL"]
        third, _ = market.subscribe("SPY")
        for _ in range(150):
            if len(socket.sent) == 2:
                break
            await asyncio.sleep(0.01)
        assert sessions == 1
        assert socket.sent[-1]["symbols"] == ["MRVL", "SPY"]
        market.unsubscribe(first)
        market.unsubscribe(second)
        market.unsubscribe(third)
        await market.stop()

    asyncio.run(scenario())


def test_tabs_following_several_symbols_share_one_upstream_subscription(monkeypatch):
    market = chart_stream.ChartMarketStream()
    layout, other_tab = asyncio.Queue(), asyncio.Queue()
    # One tab: MRVL with panels holding SPY and QQQ. Another tab: QQQ alone.
    market._clients = {1: (frozenset({"MRVL", "SPY", "QQQ"}), layout), 2: (frozenset({"QQQ"}), other_tab)}
    assert market._wanted() == {"MRVL", "SPY", "QQQ"}
    original = chart_stream.trade_event
    monkeypatch.setattr(chart_stream, "trade_event", lambda row, **kw: original(row, now=MARKET_TIME, **kw))
    market._receive("\n".join(json.dumps(row) for row in (
        event(264.9), event(712.4, symbol="SPY"), event(611.2, symbol="QQQ"), event(99.0, symbol="IWM"))))
    market._flush()
    received = [layout.get_nowait()["symbol"] for _ in range(layout.qsize())]
    assert sorted(received) == ["MRVL", "QQQ", "SPY"]  # IWM was never subscribed
    assert [other_tab.get_nowait()["symbol"] for _ in range(other_tab.qsize())] == ["QQQ"]


def test_stream_route_accepts_up_to_three_symbols(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.routers import charts

    app = FastAPI()
    app.include_router(charts.router, prefix="/charts")
    monkeypatch.setattr(charts.tradier, "TRADIER_API_KEY", "")
    with TestClient(app) as client:
        for query in ("symbols=MRVL,SPY,QQQ,IWM", "symbols=", "symbol=MRVL&symbols=../x"):
            assert client.get(f"/charts/stream?{query}").status_code == 422
        # Valid symbol sets get as far as the provider check.
        assert client.get("/charts/stream?symbols=MRVL,SPY,QQQ").status_code == 503
        assert client.get("/charts/stream?symbol=MRVL").status_code == 503


def test_stream_aggregates_one_second_of_prices_without_crossing_symbols(monkeypatch):
    market = chart_stream.ChartMarketStream()
    mrvl, spy = asyncio.Queue(), asyncio.Queue()
    market._clients = {1: (frozenset({"MRVL"}), mrvl), 2: (frozenset({"SPY"}), spy)}
    original = chart_stream.trade_event
    monkeypatch.setattr(chart_stream, "trade_event", lambda row, **kw: chart_stream_trade_event(row, **kw))

    def chart_stream_trade_event(row, **kw):
        # Keep this sample at a fixed market time regardless of the test clock.
        return original(row, now=MARKET_TIME, **kw)

    market._receive("\n".join(json.dumps(row) for row in (
        event(264.9), event(265.1, at=MARKET_TIME + 0.2), event(264.8, at=MARKET_TIME + 0.4),
        event(764.2, symbol="SPY"),
    )))
    market._flush()
    result = mrvl.get_nowait()
    assert (result["open"], result["high"], result["low"], result["price"]) == (264.9, 265.1, 264.8, 264.8)
    assert spy.get_nowait()["price"] == 764.2
