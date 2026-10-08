"""Overview (T1.3): Tradier fundamentals normalization, cache and route."""

import json
from pathlib import Path

import httpx
import pytest

from app.engine import symbol_info_tradier as module
from app.engine.symbol_info_overview import normalize_company, normalize_ratios, normalize_statistics
from app.engine.symbol_info_tradier import SymbolEvents
from app.routers import symbol_info


FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "tradier" / "overview_2026-10-08.json").read_text())


def test_recorded_company_payload_reads_the_listed_share_class_and_its_company():
    rows = normalize_company(FIXTURE["company"])
    nvda, nbis = rows["NVDA"][0], rows["NBIS"][0]
    assert nvda["sector"] == "Technology" and nvda["employees"] == 42000 and nvda["ipo_date"] == "1999-01-22"
    assert nvda["market_cap"] == 5_734_188_090_000 and nvda["shares_outstanding"] == 24_147_000_000
    assert nvda["description"].startswith("Nvidia")
    # A Dutch issuer with a second, empty share class: the listed class wins, the 1970 placeholder is ignored.
    assert nbis["sector"] == "Communication Services" and nbis["ipo_date"] == "2011-05-24"
    assert nbis["enterprise_value"] == 66_599_364_947 and nbis["institutional_ownership"] == pytest.approx(0.589, abs=1e-3)
    assert nbis["ownership"] == {"as_of": "2026-09-30", "holders": 1153, "percent_held": nbis["institutional_ownership"],
                                 "buyers": 300, "sellers": 278, "new_holders": 391, "sold_out_holders": 102,
                                 "shares_bought": 42_132_403, "shares_sold": 17_525_593}
    assert nvda["name"] is None  # Tradier's fundamentals carry no company name; the panel uses the quote's


def test_recorded_ratios_take_one_class_and_never_merge():
    rows = normalize_ratios(FIXTURE["ratios"])
    assert rows["NVDA"] == [{"pe": 30.021492, "price_to_sales": 19.122931, "price_to_book": 25.041872,
                             "ev_to_ebitda": 24.4131, "dividend_yield": 0.0042, "beta_60_month": 2.232201}]
    # NBIS loses money, so no P/E; its second class's own 60-month beta (1.48 vs the placeholder's) is not mixed in.
    assert rows["NBIS"][0]["pe"] is None and rows["NBIS"][0]["beta_60_month"] == 1.480309


def test_recorded_statistics_read_volume_averages_from_the_class_that_has_them():
    rows = normalize_statistics(FIXTURE["statistics"])
    assert rows["NVDA"] == [{"average_volume_30_day": 107_936_931, "average_volume_90_day": 121_363_650}]
    assert rows["NBIS"][0]["average_volume_30_day"] == 15_986_725


def test_etf_zero_market_cap_is_missing_not_zero():
    spy = normalize_company(FIXTURE["company"])["SPY"][0]
    assert spy["market_cap"] is None and spy["enterprise_value"] is None and spy["sector"] is None


def test_empty_statistics_response_is_missing_not_zero():
    assert normalize_statistics([{"request": "SPY", "results": []}]) == {"SPY": []}


def test_overview_route_reads_three_datasets_once_and_serves_cached_values(tmp_path, monkeypatch):
    calls = []

    def get(url, params=None, **_):
        dataset = url.rsplit("/", 1)[-1]
        calls.append((dataset, params["symbols"]))
        payload = [item for item in FIXTURE[dataset] if item["request"] == params["symbols"]]
        return httpx.Response(200, json=payload, request=httpx.Request("GET", url))

    monkeypatch.setattr(module.tradier, "TRADIER_API_KEY", "test-secret")
    monkeypatch.setattr(module.httpx, "get", get)
    monkeypatch.setattr(module, "symbol_events", SymbolEvents(root=tmp_path, clock=lambda: 1_000_000))
    first = symbol_info.overview("NBIS")
    second = symbol_info.overview("NBIS")
    assert first["state"] == "ready"
    assert first["datasets"]["company"]["sector"] == "Communication Services"
    assert "market_cap" not in first["datasets"]["company"]
    assert first["datasets"]["ratios"]["price_to_sales"] == 48.451218
    # Key statistics joins the company call's share-class figures with the statistics call's volume.
    statistics = first["datasets"]["statistics"]
    assert statistics["state"] == "ready" and statistics["market_cap"] == 64_470_464_947
    assert statistics["average_volume_30_day"] == 15_986_725 and statistics["fetched_at"] == 1_000_000
    assert first == second
    assert calls == [("company", "NBIS"), ("ratios", "NBIS"), ("statistics", "NBIS")]


def test_overview_cache_written_by_the_first_parser_is_read_again(tmp_path, monkeypatch):
    stale = tmp_path / "company" / "NBIS.json"
    stale.parent.mkdir(parents=True)
    stale.write_text(json.dumps({"schema": 1, "provider": "tradier", "dataset": "company", "symbol": "NBIS",
                                 "fetched_at": 999_999, "rows": []}))
    calls = []

    def get(url, params=None, **_):
        calls.append(url.rsplit("/", 1)[-1])
        return httpx.Response(200, json=[i for i in FIXTURE[calls[-1]] if i["request"] == "NBIS"], request=httpx.Request("GET", url))

    monkeypatch.setattr(module.tradier, "TRADIER_API_KEY", "test-secret")
    monkeypatch.setattr(module.httpx, "get", get)
    data = SymbolEvents(root=tmp_path, clock=lambda: 1_000_000).overview("NBIS")
    assert "company" in calls and data["datasets"]["company"]["employees"] == 1500


def test_overview_route_marks_empty_etf_fundamentals_none(tmp_path, monkeypatch):
    def get(url, params=None, **_):
        return httpx.Response(200, json=[{"request": "SPY", "results": []}], request=httpx.Request("GET", url))

    monkeypatch.setattr(module.tradier, "TRADIER_API_KEY", "test-secret")
    monkeypatch.setattr(module.httpx, "get", get)
    monkeypatch.setattr(module, "symbol_events", SymbolEvents(root=tmp_path, clock=lambda: 1_000_000))
    data = symbol_info.overview("SPY")
    assert data["state"] == "none"
    assert {block["state"] for block in data["datasets"].values()} == {"none"}


def test_each_failed_overview_dataset_keeps_its_own_unavailable_state(tmp_path, monkeypatch):
    def get(url, params=None, **_):
        return httpx.Response(503, json={"fault": "unavailable"}, request=httpx.Request("GET", url))

    monkeypatch.setattr(module.tradier, "TRADIER_API_KEY", "test-secret")
    monkeypatch.setattr(module.httpx, "get", get)
    data = SymbolEvents(root=tmp_path, clock=lambda: 1_000_000).overview("NVDA")
    assert data["state"] == "unavailable"
    assert {block["state"] for block in data["datasets"].values()} == {"unavailable"}
    assert all(block["message"] and "503" in block["message"] for block in data["datasets"].values())
