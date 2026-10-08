"""Overview (T1.3): Tradier fundamentals normalization, cache and route."""

import httpx

from app.engine import symbol_info_tradier as module
from app.engine.symbol_info_overview import normalize_ratios, normalize_statistics
from app.engine.symbol_info_tradier import SymbolEvents
from app.routers import symbol_info


def test_multiple_share_classes_choose_one_and_never_merge():
    payload = [{"request": "NVDA", "results": [
        {"id": "secondary", "tables": {"ratios": {"pe_ratio": 999, "price_to_book": 88}}},
        {"id": "primary", "tables": {"ratios": {"primary": True, "pe_ratio": 52.5, "dividend_yield": 0.0003}}},
    ]}]
    assert normalize_ratios(payload)["NVDA"] == [{"pe": 52.5, "price_to_sales": None, "price_to_book": None,
                                                   "ev_to_ebitda": None, "dividend_yield": 0.0003,
                                                   "beta_60_month": None}]


def test_empty_statistics_response_is_missing_not_zero():
    assert normalize_statistics([{"request": "SPY", "results": []}]) == {"SPY": []}


def test_overview_route_reads_three_datasets_once_and_serves_cached_values(tmp_path, monkeypatch):
    calls = []
    payloads = {
        "company": [{"request": "NVDA", "results": [{"tables": {"company": {
            "company_name": "NVIDIA Corporation", "sector": "Technology", "employees": 36000,
            "ipo_date": "1999-01-22", "description": "GPU designer"}}}]}],
        "ratios": [{"request": "NVDA", "results": [{"tables": {"ratios": {
            "pe_ratio": 52, "price_to_sales": 25, "price_to_book": 40, "ev_to_ebitda": 48,
            "dividend_yield": 0.0003, "beta_60_month": 1.8}}}]}],
        "statistics": [{"request": "NVDA", "results": [{"tables": {"price_statistics": {
            "market_cap": 4_500_000_000_000, "enterprise_value": 4_490_000_000_000,
            "shares_outstanding": 24_500_000_000, "institutional_ownership": 0.68,
            "average_volume_30_day": 112_700_000}}}]}],
    }

    def get(url, params=None, **_):
        dataset = url.rsplit("/", 1)[-1]
        calls.append((dataset, params["symbols"]))
        return httpx.Response(200, json=payloads[dataset], request=httpx.Request("GET", url))

    monkeypatch.setattr(module.tradier, "TRADIER_API_KEY", "test-secret")
    monkeypatch.setattr(module.httpx, "get", get)
    monkeypatch.setattr(module, "symbol_events", SymbolEvents(root=tmp_path, clock=lambda: 1_000_000))
    first = symbol_info.overview("NVDA")
    second = symbol_info.overview("NVDA")
    assert first["state"] == "ready"
    assert first["datasets"]["company"]["sector"] == "Technology"
    assert first["datasets"]["ratios"]["pe"] == 52
    assert first["datasets"]["statistics"]["market_cap"] == 4_500_000_000_000
    assert first == second
    assert calls == [("company", "NVDA"), ("ratios", "NVDA"), ("statistics", "NVDA")]


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
