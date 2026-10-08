"""Analyst consensus (T2.3): provider normalization, fallback, caching."""

from datetime import datetime

import pandas as pd

import pytest

from app.engine import symbol_info_analysts as module
from app.engine.symbol_info_analysts import (PartialRead, ProviderError, SymbolAnalysts, normalize_webull_eps, normalize_webull_ratings,
                                             normalize_webull_targets,
                                             normalize_yahoo)

YAHOO = {
    "targets": {"mean": 328.7, "median": 315.0, "high": 515.0, "low": 180.0},
    "ratings": {"strong_buy": 10, "buy": 48, "hold": 2, "sell": 1, "strong_sell": 0},
    "estimates": [{"period": "current quarter", "eps": {"avg": 2.47, "low": 2.3, "high": 2.7, "analysts": 44, "growth": 0.9}}],
}


def test_webull_live_responses_from_2026_10_08():
    """Recorded from the VPS: values are strings, ratings use under_perform, EPS is a bare list."""
    assert normalize_webull_targets({"symbol": "NVDA", "category": "US_STOCK", "mean": "328.71695", "low": "180", "high": "515", "median": "315", "currency": "USD"}) \
        == {"mean": 328.71695, "median": 315.0, "high": 515.0, "low": 180.0}
    assert normalize_webull_ratings({"number": "61", "under_perform": "0", "buy": "10", "sell": "1", "strong_buy": "48", "hold": "2"}) \
        == {"strong_buy": 48, "buy": 10, "hold": 2, "sell": 1, "strong_sell": 0}
    eps = normalize_webull_eps([
        {"fiscal_year": 2027, "fiscal_period": 1, "actual": "2.391087", "est": "1.74134", "reported": True},
        {"fiscal_year": 2027, "fiscal_period": 2, "actual": "2.457813", "est": "2.06024", "reported": True},
        {"fiscal_year": 2027, "fiscal_period": 3, "est": "2.49676", "reported": False}])
    assert [row["quarter"] for row in eps] == ["FY2027 Q2", "FY2027 Q1"] and eps[0]["result"] == "beat"
    assert round(eps[0]["surprise"], 3) == 0.193  # (actual - est) / est, not Yahoo's rounded figure


def test_webull_empty_or_garbage_is_missing_not_zero():
    assert normalize_webull_targets({}) is None
    assert normalize_webull_ratings({"buy": "n/a"}) is None


def test_yahoo_frames_normalize():
    out = normalize_yahoo(
        {"current": 237, "high": 515.0, "low": 180.0, "mean": 328.7, "median": 315.0},
        pd.DataFrame([{"period": "0m", "strongBuy": 10, "buy": 48, "hold": 2, "sell": 1, "strongSell": 0}]),
        pd.DataFrame([{"Firm": "Piper", "ToGrade": "Buy", "FromGrade": "Buy", "Action": "main", "priceTargetAction": "Raises",
                       "currentPriceTarget": 400.0, "priorPriceTarget": 0.0}], index=pd.DatetimeIndex([datetime(2026, 9, 10, 14)], name="GradeDate")),
        pd.DataFrame([{"avg": 2.47, "low": 2.3, "high": 2.7, "numberOfAnalysts": 44, "growth": 0.9}], index=pd.Index(["0q"], name="period")),
        pd.DataFrame([{"avg": 1.0e11, "low": 9e10, "high": 1.1e11, "numberOfAnalysts": 40, "growth": 0.9}], index=pd.Index(["0q"], name="period")),
        pd.DataFrame([{"epsActual": 1.87, "epsEstimate": 1.77, "surprisePercent": 0.055}], index=pd.DatetimeIndex([datetime(2026, 4, 30)], name="quarter")),
    )
    assert out["targets"]["median"] == 315.0 and out["ratings"]["buy"] == 48
    assert out["actions"] == [{"date": "2026-09-10", "firm": "Piper", "to_grade": "Buy", "from_grade": "Buy", "action": "Raises",
                               "target": 400.0, "prior_target": None}]  # a zero prior target is "none", not $0
    assert out["estimates"][0]["eps"]["analysts"] == 44 and out["estimates"][0]["revenue"]["avg"] == 1.0e11
    assert out["history"][0]["result"] == "beat"


def make(tmp_path, webull, yahoo):
    now = [1000.0]
    return SymbolAnalysts(tmp_path, clock=lambda: now[0], fetchers={"webull": webull, "yahoo": yahoo}), now


def test_webull_is_primary_and_yahoo_fills_the_rest(tmp_path):
    analysts, _ = make(tmp_path, lambda s: {"targets": {"mean": 1.0, "median": 1.0, "high": 2.0, "low": 0.5}}, lambda s: YAHOO)
    view = analysts.view("NVDA")
    assert view["blocks"]["targets"]["source"] == "Webull" and view["blocks"]["targets"]["value"]["high"] == 2.0
    assert view["blocks"]["ratings"]["source"] == "Yahoo, unofficial"  # Webull gave none, so Yahoo
    assert view["blocks"]["estimates"]["source"] == "Yahoo, unofficial"
    assert view["state"] == "ready"


def test_one_provider_failing_blanks_only_what_it_alone_supplies(tmp_path):
    def webull(symbol):
        raise ProviderError("Webull HTTP 401 IP_NOT_ALLOWED")
    analysts, _ = make(tmp_path, webull, lambda s: YAHOO)
    view = analysts.view("NVDA")
    assert view["blocks"]["targets"]["source"] == "Yahoo, unofficial"
    assert view["providers"]["webull"]["message"] == "Webull HTTP 401 IP_NOT_ALLOWED"
    assert view["blocks"]["actions"]["state"] == "none"  # Yahoo answered without that table


def test_both_failing_is_unavailable_with_reasons(tmp_path):
    def fail(symbol):
        raise ProviderError("down")
    view = make(tmp_path, fail, fail)[0].view("NVDA")
    assert view["state"] == "unavailable" and view["blocks"]["targets"]["message"] == "down"


def test_cache_serves_a_day_then_retries_and_keeps_old_copy_on_failure(tmp_path):
    calls = {"yahoo": 0}

    def yahoo(symbol):
        calls["yahoo"] += 1
        if calls["yahoo"] == 2:
            raise ProviderError("rate limited")
        return YAHOO
    analysts, now = make(tmp_path, lambda s: {}, yahoo)
    analysts.view("NVDA")
    analysts.view("NVDA")
    assert calls["yahoo"] == 1
    now[0] += 24 * 3600 + 1
    stale = analysts.view("NVDA")  # second call fails: old copy still shown, with why
    assert stale["blocks"]["targets"]["state"] == "ready" and stale["providers"]["yahoo"]["message"] == "rate limited"
    analysts.view("NVDA")
    assert calls["yahoo"] == 2  # not retried inside five minutes
    # A restart reads the disk copy instead of Yahoo.
    reborn = SymbolAnalysts(tmp_path, clock=lambda: now[0] - 100, fetchers={"webull": lambda s: {}, "yahoo": yahoo})
    reborn.view("NVDA")
    assert calls["yahoo"] == 2


def test_yahoo_ratings_carry_a_label_note_and_webull_ones_do_not(tmp_path):
    view = make(tmp_path, lambda s: {}, lambda s: YAHOO)[0].view("NVDA")
    assert "labels differ" in view["blocks"]["ratings"]["note"]
    view = make(tmp_path / "w", lambda s: {"ratings": YAHOO["ratings"]}, lambda s: YAHOO)[0].view("NVDA")
    assert "note" not in view["blocks"]["ratings"]


def test_partial_read_is_shown_with_why_kept_in_memory_only_and_retried_after_five_minutes(tmp_path):
    calls = []

    def yahoo(symbol):
        calls.append(symbol)
        if len(calls) == 1:
            raise PartialRead({"targets": YAHOO["targets"]}, "Yahoo answered only in part.")
        return YAHOO
    analysts, now = make(tmp_path, lambda s: {}, yahoo)
    view = analysts.view("NVDA")
    assert view["blocks"]["targets"]["message"] == "Yahoo answered only in part." and view["blocks"]["estimates"]["state"] == "unavailable"  # missing because the read was partial
    assert not list((tmp_path / "yahoo").rglob("*.json"))  # the partial read is not written to disk
    analysts.view("NVDA")
    assert len(calls) == 1
    now[0] += 301
    assert analysts.view("NVDA")["blocks"]["estimates"]["state"] == "ready" and len(calls) == 2
    assert len(list((tmp_path / "yahoo").rglob("*.json"))) == 1  # the complete read is cached a day


def test_stale_copy_after_failed_refresh_says_why_on_the_block(tmp_path):
    state = {"fail": False}

    def yahoo(symbol):
        if state["fail"]:
            raise ProviderError("rate limited")
        return YAHOO
    analysts, now = make(tmp_path, lambda s: {}, yahoo)
    analysts.view("NVDA")
    state["fail"] = True
    now[0] += 24 * 3600 + 1
    block = analysts.view("NVDA")["blocks"]["targets"]
    assert block["state"] == "ready" and block["message"] == "rate limited" and block["fetched_at"] == 1000


class FakeWebull:
    queries = []
    failing = ()

    def get(self, path, *, query=None):
        FakeWebull.queries.append((path, query))
        if path in FakeWebull.failing:
            raise module_error("boom")
        return {module.WEBULL_TARGET_PATH: {"mean": "1", "median": "1", "high": "2", "low": "0.5"},
                module.WEBULL_RATING_PATH: {"strong_buy": "3", "buy": "1", "hold": "0", "sell": "0", "under_perform": "0"},
                module.WEBULL_EPS_PATH: [{"fiscal_year": 2027, "fiscal_period": 2, "actual": "2", "est": "1", "reported": True}]}[path]


def module_error(message):
    from app.engine.webull_client import WebullClientError
    return WebullClientError(message)


@pytest.fixture
def webull(monkeypatch):
    from app.engine import webull_client
    FakeWebull.queries, FakeWebull.failing = [], ()
    monkeypatch.setattr(webull_client, "webull_configured", lambda: True)
    monkeypatch.setattr(webull_client, "WebullHttpClient", FakeWebull)
    return FakeWebull


def test_fetch_webull_asks_each_endpoint_for_the_us_stock(webull):
    out = module.fetch_webull("NVDA")
    assert set(out) == {"targets", "ratings", "history"}
    assert {query["symbol"] for _, query in webull.queries} == {"NVDA"} and all(query["category"] == "US_STOCK" for _, query in webull.queries)


def test_fetch_webull_partial_and_total_failure(webull):
    webull.failing = (module.WEBULL_RATING_PATH,)
    with pytest.raises(PartialRead) as partial:
        module.fetch_webull("NVDA")
    assert set(partial.value.data) == {"targets", "history"}
    webull.failing = (module.WEBULL_TARGET_PATH, module.WEBULL_RATING_PATH, module.WEBULL_EPS_PATH)
    with pytest.raises(ProviderError) as total:
        module.fetch_webull("NVDA")
    assert not isinstance(total.value, PartialRead)


class FakeTicker:
    seen = []
    broken = ()

    def __init__(self, symbol):
        FakeTicker.seen.append(symbol)

    def __getattr__(self, name):
        if name in FakeTicker.broken:
            raise RuntimeError("429")
        return None if name != "analyst_price_targets" else {"mean": 1.0, "median": 1.0, "high": 2.0, "low": 0.5}


@pytest.fixture
def yahoo_ticker(monkeypatch):
    import sys
    import types
    FakeTicker.seen, FakeTicker.broken = [], ()
    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(Ticker=FakeTicker))
    return FakeTicker


def test_fetch_yahoo_maps_share_classes_and_flags_partial_and_total_failure(yahoo_ticker):
    module.fetch_yahoo("BRK.B")
    assert yahoo_ticker.seen == ["BRK-B"]
    yahoo_ticker.broken = ("earnings_estimate",)
    with pytest.raises(PartialRead) as partial:
        module.fetch_yahoo("NVDA")
    assert "targets" in partial.value.data
    yahoo_ticker.broken = ("analyst_price_targets", "recommendations_summary", "upgrades_downgrades", "earnings_estimate", "revenue_estimate", "earnings_history")
    with pytest.raises(ProviderError) as total:
        module.fetch_yahoo("NVDA")
    assert not isinstance(total.value, PartialRead)
