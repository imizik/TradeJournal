"""News tab (T1.2): the normalizers, merge, dedupe and Focused flag on a mixed-tagging
fixture; the caches and the Polygon 429 fallback; the route. No live Alpaca or Polygon."""

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
import pytest

from app.engine import symbol_info_news_feed as module
from app.engine.symbol_info_news import (ALPACA, POLYGON, canonical_url, headline_key, listed, merge, normalize_alpaca,
                                         normalize_polygon)
from app.engine.symbol_info_news_feed import SymbolNews
from app.routers import symbol_info

ALPACA_ROWS = [
    {"id": 1, "headline": "Nvidia Unveils New Chip", "summary": "A chip.", "symbols": ["NVDA"], "source": "benzinga",
     "created_at": "2026-10-06T14:30:00Z", "url": "https://www.benzinga.com/news/nvda-chip?utm_source=x"},
    {"id": 2, "headline": "Mega-Cap Roundup: 5 Stocks Moving", "summary": "", "symbols": ["NVDA", "AAPL", "MSFT", "AMZN", "GOOGL"],
     "source": "benzinga", "created_at": "2026-10-06T13:00:00Z", "url": "https://benzinga.com/roundup"},
    {"id": 3, "headline": "Three Tickers Is Still Focused", "summary": None, "symbols": ["nvda", "amd", "avgo"], "source": "benzinga",
     "created_at": "2026-10-05T10:00:00Z", "url": "https://benzinga.com/three"},
    {"id": 4, "headline": "No link", "summary": "", "symbols": ["NVDA"], "source": "benzinga", "created_at": "2026-10-05T09:00:00Z", "url": None},
]
POLYGON_BODY = {"results": [
    {"id": "p1", "title": "NVIDIA unveils new chip!", "article_url": "https://example.com/other-url", "published_utc": "2026-10-06T14:31:00Z",
     "publisher": {"name": "The Motley Fool"}, "tickers": ["NVDA"], "description": "Polygon summary.",
     "insights": [{"ticker": "NVDA", "sentiment": "positive", "sentiment_reasoning": "Strong demand."},
                  {"ticker": "AMD", "sentiment": "bogus", "sentiment_reasoning": "dropped"}]},
    {"id": "p2", "title": "Fresh Polygon Only", "article_url": "https://example.com/fresh", "published_utc": "2026-10-06T15:00:00+00:00",
     "publisher": {"name": "Reuters"}, "tickers": ["NVDA", "TSM"], "description": None},
    {"id": "p3", "title": "Same Link Different Headline", "article_url": "http://WWW.benzinga.com/roundup/", "published_utc": "2026-10-06T13:01:00Z",
     "publisher": {"name": "Benzinga"}, "tickers": ["NVDA"]},
    {"id": "p4", "title": "", "article_url": "https://example.com/x", "published_utc": "2026-10-06T13:01:00Z"},
]}


def test_normalizers_make_one_shape_and_drop_unusable_rows():
    alpaca = normalize_alpaca(ALPACA_ROWS)
    assert [r["id"] for r in alpaca] == ["alpaca_benzinga:1", "alpaca_benzinga:2", "alpaca_benzinga:3"]  # no url -> dropped
    assert alpaca[0]["provider"] == ALPACA and alpaca[0]["published_at"] == "2026-10-06T14:30:00Z" and alpaca[0]["summary"] == "A chip."
    assert alpaca[1]["summary"] is None and alpaca[1]["roundup"] is True
    assert alpaca[2]["tickers"] == ["NVDA", "AMD", "AVGO"] and alpaca[2]["roundup"] is False  # exactly three is not a roundup
    polygon = normalize_polygon(POLYGON_BODY)
    assert [r["id"] for r in polygon] == ["polygon:p1", "polygon:p2", "polygon:p3"]  # empty title -> dropped
    assert polygon[0]["provider"] == POLYGON and polygon[0]["publisher"] == "The Motley Fool"
    assert polygon[0]["sentiment"] == [{"ticker": "NVDA", "sentiment": "positive", "reasoning": "Strong demand."}]
    assert polygon[1]["published_at"] == "2026-10-06T15:00:00Z" and polygon[1]["sentiment"] == []
    assert set(alpaca[0]) == set(polygon[0])  # one shape


def test_canonical_url_and_headline_keys():
    assert canonical_url("https://www.Benzinga.com/a/b/?utm_source=x&id=2#top") == canonical_url("http://benzinga.com/a/b?id=2")
    assert canonical_url("https://benzinga.com/a?id=1") != canonical_url("https://benzinga.com/a?id=2")
    assert headline_key("NVIDIA unveils new chip!") == headline_key("Nvidia  Unveils New Chip")


def test_merge_dedupes_by_link_and_headline_newest_first_and_keeps_provider_sentiment():
    merged = merge(normalize_alpaca(ALPACA_ROWS), normalize_polygon(POLYGON_BODY))
    assert [r["headline"] for r in merged] == ["Fresh Polygon Only", "Nvidia Unveils New Chip", "Mega-Cap Roundup: 5 Stocks Moving",
                                               "Three Tickers Is Still Focused"]
    chip = merged[1]
    assert chip["provider"] == ALPACA and chip["also_in"] == [POLYGON]  # same headline, different link
    assert chip["sentiment"][0]["sentiment"] == "positive" and chip["summary"] == "A chip."
    assert merged[2]["also_in"] == [POLYGON]  # same link, different headline


def test_focused_hides_roundups_and_still_fills_twenty():
    many = [{"id": i, "headline": f"Story {i}", "summary": "", "symbols": ["NVDA"] if i % 3 else ["A", "B", "C", "D"], "source": "b",
             "created_at": f"2026-10-06T{10 + i // 60:02d}:{i % 60:02d}:00Z", "url": f"https://b.com/{i}"} for i in range(50)]
    merged = merge(normalize_alpaca(many))
    everything, focused = listed(merged, False), listed(merged, True)
    assert len(everything) == 20 and len(focused) == 20
    assert any(r["roundup"] for r in everything) and not any(r["roundup"] for r in focused)
    assert [r["published_at"] for r in everything] == sorted((r["published_at"] for r in everything), reverse=True)
    assert len(merged) <= 40


# --------------------------------------------------------------------- fetch

@pytest.fixture
def polygon(monkeypatch):
    calls = []
    answer = {"status": 200, "body": POLYGON_BODY, "headers": {}}

    def get(url, params=None, **_):
        calls.append(params)
        return httpx.Response(answer["status"], json=answer["body"], headers=answer["headers"], request=httpx.Request("GET", url))

    monkeypatch.setattr(module.enricher, "POLYGON_API_KEY", "test-secret")
    monkeypatch.setattr(module.enricher, "_limiter", module.enricher._AdaptiveRateLimiter())
    monkeypatch.setattr(module.httpx, "get", get)
    return calls, answer


def feed(tmp_path, clock, alpaca_calls=None, fail=None):
    def alpaca(symbol, start):
        if alpaca_calls is not None:
            alpaca_calls.append((symbol, start))
        if fail and fail[0]:
            raise RuntimeError("Alpaca down")
        return ALPACA_ROWS
    return SymbolNews(root=tmp_path, clock=lambda: clock[0], alpaca=alpaca)


def test_alpaca_is_cached_60_seconds_and_polygon_15_minutes_on_disk(tmp_path, polygon):
    calls, _ = polygon
    clock, reads = [1_000_000.0], []
    store = feed(tmp_path, clock, reads)
    first = store.view("NVDA")
    assert [s["state"] for s in first["sources"]] == ["ok", "ok"] and len(calls) == 1 and len(reads) == 1
    assert calls[0]["ticker"] == "NVDA" and calls[0]["published_utc.gte"] == "1970-01-05"  # seven days before the fake clock
    clock[0] += 59
    store.view("NVDA")
    assert len(reads) == 1 and len(calls) == 1
    clock[0] += 2  # Alpaca stale at 61 s, Polygon still fresh
    store.view("NVDA")
    assert len(reads) == 2 and len(calls) == 1
    assert json.loads((tmp_path / "news-NVDA.json").read_text())["schema"] == 1
    # A restart reuses the disk copy for 15 minutes.
    again = feed(tmp_path, clock)
    clock[0] += 600
    again.view("NVDA")
    assert len(calls) == 1
    clock[0] += 400  # 1,061 s since the Polygon read
    again.view("NVDA")
    assert len(calls) == 2


def test_a_polygon_429_serves_the_cached_copy_with_its_age_and_does_not_retry(tmp_path, polygon):
    calls, answer = polygon
    clock = [1_000_000.0]
    store = feed(tmp_path, clock)
    store.view("NVDA")
    answer.update(status=429, body={}, headers={"Retry-After": "30"})
    clock[0] += 16 * 60
    body = store.view("NVDA")
    assert len(calls) == 2  # one refused attempt, no retry
    polygon_status = body["sources"][1]
    assert polygon_status["state"] == "stale" and polygon_status["age_seconds"] == 960 and "429" in polygon_status["message"]
    assert body["sources"][0]["state"] == "ok"
    assert any(a["provider"] == POLYGON for a in body["articles"]) and any(a["provider"] == ALPACA for a in body["articles"])
    clock[0] += 61  # Polygon is quiet for five minutes after a failure
    store.view("NVDA")
    assert len(calls) == 2


def test_polygon_failure_with_no_cache_leaves_alpaca_news(tmp_path, polygon):
    calls, answer = polygon
    answer.update(status=500, body={})
    body = feed(tmp_path, [1_000_000.0]).view("NVDA")
    assert [s["state"] for s in body["sources"]] == ["ok", "failed"]
    assert body["articles"] and all(a["provider"] == ALPACA for a in body["articles"])


def test_alpaca_failure_degrades_only_alpaca_and_serves_its_older_copy(tmp_path, polygon):
    clock, fail = [1_000_000.0], [False]
    store = feed(tmp_path, clock, fail=fail)
    store.view("NVDA")
    fail[0], clock[0] = True, clock[0] + 120
    body = store.view("NVDA")
    assert [s["state"] for s in body["sources"]] == ["stale", "ok"] and body["sources"][0]["age_seconds"] == 120
    other = feed(tmp_path / "other", [1.0], fail=[True]).view("AMD")
    assert other["sources"][0]["state"] == "failed" and other["sources"][1]["state"] == "ok"


def test_polygon_not_configured_or_busy_never_calls_out(tmp_path, polygon, monkeypatch):
    calls, _ = polygon
    monkeypatch.setattr(module.enricher, "POLYGON_API_KEY", "")
    assert feed(tmp_path, [1.0]).view("NVDA")["sources"][1]["state"] == "not_configured"
    monkeypatch.setattr(module.enricher, "POLYGON_API_KEY", "k")
    monkeypatch.setattr(module.enricher._limiter, "reserve_within", lambda _max: None)
    busy = feed(tmp_path, [1.0]).view("NVDA")
    assert busy["sources"][1]["state"] == "failed" and "busy" in busy["sources"][1]["message"] and not calls


def test_route_returns_the_view_and_rejects_bad_tickers(tmp_path, polygon, monkeypatch):
    monkeypatch.setattr(symbol_info.symbol_info_news_feed, "symbol_news", feed(tmp_path, [1_000_000.0]))
    app = FastAPI()
    app.include_router(symbol_info.router, prefix="/charts")
    client = TestClient(app)
    body = client.get("/charts/symbol/NVDA/news").json()
    assert body["symbol"] == "NVDA" and body["articles"] and "apiKey" not in json.dumps(body)
    assert client.get("/charts/symbol/bad%20one/news").status_code == 422


# ------------------------------------------------- alpaca never blocks the route

def _alpaca_http(monkeypatch, status_code=429, raises=None):
    from app.engine import alpaca as alp, news as news_mod
    calls, sleeps = [], []
    monkeypatch.setattr(alp, "ALPACA_API_KEY", "k")
    monkeypatch.setattr(alp, "ALPACA_API_SECRET", "s")
    monkeypatch.setattr(alp, "observed_sleep", lambda *a: sleeps.append(a))
    monkeypatch.setattr(alp.time, "sleep", lambda s: sleeps.append(("time.sleep", s)))

    def get(url, params=None, headers=None, timeout=None):
        calls.append(timeout)
        if raises:
            raise raises
        return httpx.Response(status_code, json={"news": []}, request=httpx.Request("GET", url))

    monkeypatch.setattr(alp.httpx, "get", get)
    return alp, news_mod, calls, sleeps


def test_fast_news_read_429_returns_at_once_without_sleeping_or_retrying(monkeypatch):
    alp, news_mod, calls, sleeps = _alpaca_http(monkeypatch, 429)
    with pytest.raises(alp.AlpacaFastFailure):
        news_mod.fetch_news(symbols=["NVDA"], fast=True)
    assert len(calls) == 1 and sleeps == [] and calls[0] <= 3


@pytest.mark.parametrize("raises", [httpx.ReadTimeout("slow"), httpx.ConnectError("down")])
def test_fast_news_read_timeout_or_network_error_is_not_retried(monkeypatch, raises):
    alp, news_mod, calls, sleeps = _alpaca_http(monkeypatch, raises=raises)
    with pytest.raises(alp.AlpacaFastFailure):
        news_mod.fetch_news(symbols=["NVDA"], fast=True)
    assert len(calls) == 1 and sleeps == []


def test_other_callers_still_retry_on_429(monkeypatch):
    alp, news_mod, calls, sleeps = _alpaca_http(monkeypatch, 429)
    monkeypatch.setattr(alp._limiter, "wait", lambda: None)
    with pytest.raises(RuntimeError):
        news_mod.fetch_news(symbols=["NVDA"])
    assert len(calls) == 5 and [s[2] for s in sleeps] == [30, 60, 90, 120, 150]


def test_route_default_reader_uses_the_fast_path(monkeypatch):
    seen = {}
    monkeypatch.setattr(module.news, "fetch_news", lambda **kw: seen.update(kw) or [])
    SymbolNews._read_alpaca("NVDA", None)
    assert seen["fast"] is True


def test_alpaca_failure_serves_stale_with_age_then_stays_quiet_for_five_minutes(tmp_path, polygon):
    clock, fail, calls = [1_000_000.0], [False], []
    store = feed(tmp_path, clock, alpaca_calls=calls, fail=fail)
    store.view("NVDA")
    fail[0], clock[0] = True, clock[0] + 120
    first = store.view("NVDA")["sources"][0]
    assert first["state"] == "stale" and first["age_seconds"] == 120 and len(calls) == 2
    clock[0] += 200  # inside the quiet period: no new call, still stale with a growing age
    quiet = store.view("NVDA")["sources"][0]
    assert quiet["state"] == "stale" and quiet["age_seconds"] == 320 and len(calls) == 2
    fail[0], clock[0] = False, clock[0] + 101  # quiet period over: reads again and recovers
    assert store.view("NVDA")["sources"][0]["state"] == "ok" and len(calls) == 3


def test_alpaca_failure_without_cache_is_failed_and_quiet(tmp_path, polygon):
    clock, calls = [1_000_000.0], []
    store = feed(tmp_path, clock, alpaca_calls=calls, fail=[True])
    assert store.view("AMD")["sources"][0]["state"] == "failed"
    clock[0] += 60
    assert store.view("AMD")["sources"][0]["state"] == "failed" and len(calls) == 1


# ------------------------------------------- the news read honors the limiter's slot

class _Tick:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_reserve_within_over_budget_returns_none_and_does_not_push_enrichment_back():
    clock = _Tick()
    limiter = module.enricher._AdaptiveRateLimiter(ceiling=6.0, clock=clock)
    limiter.reserve()  # slot now, next slot 10 s out
    before = limiter._next_slot
    assert limiter.reserve_within(2.0) is None
    assert limiter._next_slot == before
    clock.now += 9
    assert limiter.reserve_within(2.0) == pytest.approx(1.0) and limiter._next_slot == before + 10


def test_reserve_within_unpaced_is_instant():
    limiter = module.enricher._AdaptiveRateLimiter(ceiling=None, clock=_Tick())
    assert limiter.reserve_within(2.0) == 0.0


def test_polygon_news_sleeps_the_granted_delay_then_calls(tmp_path, polygon, monkeypatch):
    calls, _ = polygon
    slept = []
    monkeypatch.setattr(module, "observed_sleep", lambda provider, reason, seconds: slept.append((provider, reason, seconds)))
    monkeypatch.setattr(module.enricher._limiter, "reserve_within", lambda _max: 1.5)
    assert feed(tmp_path, [1_000_000.0]).view("NVDA")["sources"][1]["state"] == "ok"
    assert slept == [("Polygon", "rate_limit", 1.5)] and len(calls) == 1
