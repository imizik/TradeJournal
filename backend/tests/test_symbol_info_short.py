"""Short & borrow block (T3.1): the normalizers on recorded, trimmed real Polygon and Tradier
responses (backend/tests/fixtures/symbol_info_short/, recorded 2026-10-08), the view, the
one-day caches, the Polygon 429 fallback with the cached copy's age, and the route. No live calls."""

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
import pytest

from app.engine import symbol_info_short_feed as module
from app.engine.symbol_info_short import (hard_to_borrow, interest_view, normalize_details, normalize_etb,
                                          normalize_short_interest, normalize_short_volume, symbol_key, volume_view)
from app.engine.symbol_info_short_feed import ShortFeed
from app.routers import symbol_info

FIXTURES = Path(__file__).parent / "fixtures" / "symbol_info_short"


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text())


# ----------------------------------------------------------------- normalizers

def test_short_interest_keeps_the_provider_fields_newest_first():
    rows = normalize_short_interest(fixture("polygon_short_interest_NVDA"))
    assert [r["settlement_date"] for r in rows] == ["2026-09-15", "2026-08-31", "2026-08-14"]
    assert rows[0] == {"settlement_date": "2026-09-15", "short_interest": 294225803, "avg_daily_volume": 115324892, "days_to_cover": 2.55}
    assert normalize_short_interest(fixture("polygon_short_interest_empty")) == []
    assert normalize_short_interest({"results": [{"settlement_date": "bad", "short_interest": 1}, {"settlement_date": "2026-09-15"},
                                                 "junk", {"settlement_date": "2026-09-15", "short_interest": 5}]})[0]["days_to_cover"] is None


def test_short_volume_recomputes_the_ratio_and_keeps_ten_sessions():
    rows = normalize_short_volume(fixture("polygon_short_volume_NVDA"))
    assert len(rows) == 10 and rows[0]["date"] == "2026-10-07" and rows[-1]["date"] == "2026-09-24"
    assert rows[0] == {"date": "2026-10-07", "short_volume": 17901999, "total_volume": 34776416, "ratio_pct": 51.5}
    # Polygon's own short_volume_ratio is 51.48; ours is short over total, to one decimal.
    one_oct = next(r for r in rows if r["date"] == "2026-10-01")
    assert one_oct["total_volume"] == 41606403  # the doc's 41.6M row, well under the ~100M-share day
    assert all(0 < r["ratio_pct"] < 100 for r in rows)
    assert normalize_short_volume({"results": [{"date": "2026-10-01", "short_volume": 5, "total_volume": 0}]}) == []


def test_details_prefers_the_share_class_count_and_falls_back_to_weighted():
    assert normalize_details(fixture("polygon_ticker_details_NVDA")) == [{"shares_outstanding": 24100000000, "basis": "share_class_shares_outstanding"}]
    assert normalize_details(fixture("polygon_ticker_details_SPY"))[0]["shares_outstanding"] == 1070432116
    assert normalize_details({"results": {"weighted_shares_outstanding": 10}})[0]["basis"] == "weighted_shares_outstanding"
    assert normalize_details({"results": {"ticker": "X"}}) == [] and normalize_details({}) == []


def test_etb_list_and_the_hard_to_borrow_flag():
    easy = normalize_etb(fixture("etb_trimmed"))
    assert easy == ["AAPL", "KIM", "NVDA", "SPY", "USHY"]
    assert hard_to_borrow("NVDA", easy) is False and hard_to_borrow("zzzq", easy) is True
    assert normalize_etb({"securities": {"security": {"symbol": "brk.b"}}}) == ["BRK.B"]  # one row comes back as an object
    assert hard_to_borrow("BRK-B", ["BRK.B"]) is False and symbol_key("BRK/B") == "BRKB"
    assert normalize_etb({"securities": "null"}) == [] and normalize_etb({}) == []


def test_interest_view_divides_by_shares_outstanding_and_never_says_float():
    shares = normalize_details(fixture("polygon_ticker_details_NVDA"))
    view = interest_view(normalize_short_interest(fixture("polygon_short_interest_NVDA")), shares)
    assert view["pct_of_shares_outstanding"] == 1.22 and view["shares_basis"] == "share_class_shares_outstanding"
    assert view["previous"] == {"settlement_date": "2026-08-31", "short_interest": 298301619, "change_pct": -1.4}
    assert "not a percent of float" in view["pct_note"]
    assert interest_view(normalize_short_interest(fixture("polygon_short_interest_NVDA")), [])["pct_of_shares_outstanding"] is None
    assert interest_view([], shares) == {}
    avg = volume_view(normalize_short_volume(fixture("polygon_short_volume_NVDA")))
    assert avg["average_pct"] == pytest.approx(46.4, abs=0.5) and "FINRA" in avg["note"]


# ----------------------------------------------------------------------- feed

class Net:
    """A fake network keyed by URL path, serving the recorded bodies."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self.status = 200
        self.headers: dict = {}
        self.bodies = {
            "/stocks/v1/short-interest": fixture("polygon_short_interest_NVDA"),
            "/stocks/v1/short-volume": fixture("polygon_short_volume_NVDA"),
            "/v3/reference/tickers/NVDA": fixture("polygon_ticker_details_NVDA"),
            "/v1/markets/etb": fixture("etb_trimmed"),
        }

    def get(self, url, params=None, **_):
        path = httpx.URL(url).path
        self.calls.append((path, dict(params or {})))
        body = self.bodies.get(path, {"results": []}) if self.status == 200 else {}
        return httpx.Response(self.status, json=body, headers=self.headers, request=httpx.Request("GET", url))

    def polygon_calls(self):
        return [c for c in self.calls if c[0] != "/v1/markets/etb"]


@pytest.fixture
def net(monkeypatch):
    fake = Net()
    monkeypatch.setattr(module.enricher, "POLYGON_API_KEY", "test-secret")
    monkeypatch.setattr(module.enricher, "_limiter", module.enricher._AdaptiveRateLimiter())
    monkeypatch.setattr(module.tradier, "TRADIER_API_KEY", "test-token")
    monkeypatch.setattr(module.httpx, "get", fake.get)
    return fake


def feed(tmp_path, clock):
    return ShortFeed(root=tmp_path, clock=lambda: clock[0])


def test_a_cold_symbol_reads_each_source_once_and_assembles_the_block(tmp_path, net):
    body = feed(tmp_path, [1_000_000.0]).view("NVDA")
    assert [p for p, _ in net.calls] == ["/stocks/v1/short-interest", "/stocks/v1/short-volume", "/v3/reference/tickers/NVDA", "/v1/markets/etb"]
    assert net.calls[0][1]["ticker"] == "NVDA" and net.calls[1][1]["limit"] == 10
    assert body["state"] == "ready"
    assert body["interest"]["state"] == "ready" and body["interest"]["settlement_date"] == "2026-09-15"
    assert body["interest"]["short_interest"] == 294225803 and body["interest"]["days_to_cover"] == 2.55
    assert body["interest"]["pct_of_shares_outstanding"] == 1.22 and body["interest"]["pct_message"] is None
    assert len(body["volume"]["rows"]) == 10 and body["volume"]["rows"][0]["date"] == "2026-10-07"
    assert body["borrow"]["state"] == "ready" and body["borrow"]["hard_to_borrow"] is False
    assert "test-secret" not in json.dumps(body)


def test_a_symbol_missing_from_the_etb_list_is_flagged_hard_to_borrow(tmp_path, net):
    net.bodies["/stocks/v1/short-interest"] = fixture("polygon_short_interest_empty")
    net.bodies["/stocks/v1/short-volume"] = fixture("polygon_short_interest_empty")  # same empty envelope
    body = feed(tmp_path, [1.0]).view("ZZZQ")
    assert body["borrow"]["hard_to_borrow"] is True and "easy-to-borrow" in body["borrow"]["note"]
    assert body["state"] == "none" and body["interest"]["state"] == "none" and "ZZZQ" in body["interest"]["none_message"]
    assert not any(p == "/v3/reference/tickers/ZZZQ" for p, _ in net.calls)  # no interest row, so no shares call


def test_caches_last_a_day_on_disk_and_survive_a_restart(tmp_path, net):
    clock = [1_000_000.0]
    feed(tmp_path, clock).view("NVDA")
    assert json.loads((tmp_path / "polygon" / "short_interest-NVDA.json").read_text())["schema"] == 1
    assert (tmp_path / "tradier" / "etb.json").exists()
    net.calls.clear()
    clock[0] += 23 * 3600
    again = feed(tmp_path, clock)  # a restart
    assert again.view("NVDA")["interest"]["stale"] is False and not net.calls
    clock[0] += 2 * 3600  # 25 h
    again.view("NVDA")
    assert len(net.polygon_calls()) == 3 and len([c for c in net.calls if c[0] == "/v1/markets/etb"]) == 1
    # Another symbol shares the one borrow-list read.
    net.calls.clear()
    again.view("SPY")
    assert not any(p == "/v1/markets/etb" for p, _ in net.calls)


def test_a_polygon_429_serves_the_cached_copy_with_its_age_and_does_not_retry(tmp_path, net, monkeypatch):
    clock = [1_000_000.0]
    store = feed(tmp_path, clock)
    store.view("NVDA")
    net.calls.clear()
    net.status, net.headers = 429, {"Retry-After": "30"}
    clock[0] += 26 * 3600
    body = store.view("NVDA")
    assert len(net.polygon_calls()) == 1  # one refused attempt; the 429 quiets the other Polygon datasets, no retry
    interest = body["interest"]
    assert interest["state"] == "ready" and interest["stale"] is True and interest["age_seconds"] == 26 * 3600
    assert "429" in interest["message"] and interest["short_interest"] == 294225803
    assert body["volume"]["stale"] is True and body["volume"]["age_seconds"] == 26 * 3600 and len(body["volume"]["rows"]) == 10
    assert interest["pct_of_shares_outstanding"] == 1.22 and body["interest"]["fetched_at"] == 1_000_000.0
    clock[0] += 61  # quiet for five minutes after a failure
    store.view("NVDA")
    assert len(net.polygon_calls()) == 1
    clock[0] += 5 * 60  # then it asks again (a fresh limiter: its own refusal pacing runs on the wall clock)
    monkeypatch.setattr(module.enricher, "_limiter", module.enricher._AdaptiveRateLimiter())
    store.view("NVDA")
    assert len(net.polygon_calls()) == 2


def test_a_polygon_failure_with_no_cache_degrades_only_polygon_blocks(tmp_path, net):
    net.status = 500
    body = feed(tmp_path, [1.0]).view("NVDA")
    assert body["state"] == "unavailable"
    assert body["interest"]["state"] == "unavailable" and body["volume"]["state"] == "unavailable" and body["interest"]["message"]
    assert body["borrow"]["state"] == "unavailable"  # the same fake serves Tradier a 500 as well
    assert body["interest"]["fetched_at"] is None


def test_polygon_down_but_tradier_up_still_shows_the_borrow_flag(tmp_path, net, monkeypatch):
    monkeypatch.setattr(module.enricher, "POLYGON_API_KEY", "")
    body = feed(tmp_path, [1.0]).view("NVDA")
    assert body["interest"]["state"] == "unavailable" and "POLYGON_API_KEY" in body["interest"]["message"]
    assert body["borrow"]["state"] == "ready" and body["borrow"]["hard_to_borrow"] is False
    assert not net.polygon_calls()


def test_busy_limiter_never_calls_out_and_the_missing_shares_omit_only_the_percentage(tmp_path, net, monkeypatch):
    store = feed(tmp_path, [1.0])
    seen = {"n": 0}

    def reserve(_max):
        seen["n"] += 1
        return None if seen["n"] > 2 else 0.0  # interest and volume get slots; details do not
    monkeypatch.setattr(module.enricher._limiter, "reserve_within", reserve)
    body = store.view("NVDA")
    assert body["interest"]["state"] == "ready" and body["interest"]["pct_of_shares_outstanding"] is None
    assert "percentage is omitted" in body["interest"]["pct_message"]
    monkeypatch.setattr(module.enricher._limiter, "reserve_within", lambda _max: None)
    busy = feed(tmp_path / "other", [1.0]).view("NVDA")
    assert busy["interest"]["state"] == "unavailable" and "busy" in busy["interest"]["message"]


def test_the_granted_limiter_delay_is_slept_before_the_call(tmp_path, net, monkeypatch):
    slept = []
    monkeypatch.setattr(module, "observed_sleep", lambda provider, reason, seconds: slept.append((provider, reason, seconds)))
    monkeypatch.setattr(module.enricher._limiter, "reserve_within", lambda _max: 1.5)
    feed(tmp_path, [1.0]).view("NVDA")
    assert slept[0] == ("Polygon", "rate_limit", 1.5) and len(slept) == 3


def test_route_returns_the_view_and_rejects_bad_tickers(tmp_path, net, monkeypatch):
    monkeypatch.setattr(symbol_info.symbol_info_short_feed, "short_feed", feed(tmp_path, [1_000_000.0]))
    app = FastAPI()
    app.include_router(symbol_info.router, prefix="/charts")
    client = TestClient(app)
    ok = client.get("/charts/symbol/nvda/short")
    assert ok.status_code == 200 and ok.json()["symbol"] == "NVDA" and ok.json()["interest"]["settlement_date"] == "2026-09-15"
    assert client.get("/charts/symbol/%24bad/short").status_code == 422


def test_class_share_tickers_use_polygons_dot_spelling(tmp_path, net):
    feed(tmp_path, [1_000_000.0]).view("BRK/B")
    tickers = {params.get("ticker") for path, params in net.polygon_calls() if "ticker" in params}
    details = [path for path, _ in net.polygon_calls() if path.startswith("/v3/reference/tickers/")]
    assert tickers == {"BRK.B"} and all(path == "/v3/reference/tickers/BRK.B" for path in details)
