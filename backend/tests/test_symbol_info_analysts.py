"""Analyst consensus (T2.3): provider normalization, fallback, caching."""

from datetime import datetime

import pandas as pd

from app.engine.symbol_info_analysts import (ProviderError, SymbolAnalysts, normalize_webull_eps, normalize_webull_ratings,
                                             normalize_webull_targets,
                                             normalize_yahoo)

YAHOO = {
    "targets": {"mean": 328.7, "median": 315.0, "high": 515.0, "low": 180.0},
    "ratings": {"strong_buy": 10, "buy": 48, "hold": 2, "sell": 1, "strong_sell": 0},
    "estimates": [{"period": "current quarter", "eps": {"avg": 2.47, "low": 2.3, "high": 2.7, "analysts": 44, "growth": 0.9}}],
}


def test_webull_shapes_with_different_spellings_and_wrapping():
    assert normalize_webull_targets({"data": {"highTargetPrice": "515", "lowTargetPrice": 180, "meanTargetPrice": 327.7, "medianTargetPrice": 315}}) \
        == {"mean": 327.7, "median": 315.0, "high": 515.0, "low": 180.0}
    assert normalize_webull_ratings([{"strong_buy": 10, "buy": 48, "hold": 2, "sell": 1, "strong_sell": 0}]) \
        == {"strong_buy": 10, "buy": 48, "hold": 2, "sell": 1, "strong_sell": 0}


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
    assert normalize_webull_ratings({"data": {"buy": "n/a"}}) is None


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


def make(tmp_path, webull, yahoo, now=[1000.0]):
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
