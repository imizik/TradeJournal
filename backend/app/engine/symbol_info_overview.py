"""Pure normalizers for the Symbol Info Overview tab (T1.3).

Tradier's fundamentals endpoints (Morningstar) wrap each requested symbol in a
list of results: ``Company`` results keyed by company id and ``Stock`` results
keyed by share-class id, each with named tables. A symbol can come back with a
second, nearly empty share class (ids like ``0PDXF...``). Each dataset reads one
result, the best populated, and never fills a field from another class.

Where the fields actually live (recorded in
``tests/fixtures/tradier/overview_2026-10-08.json``):

- company: ``share_class`` (symbol, IPO date, listing), ``share_class_profile``
  (market cap, enterprise value, shares outstanding) and ``ownership_summary``
  (13F) on the Stock result; ``company_profile`` (employees),
  ``historical_asset_classification`` (Morningstar sector code) and
  ``long_descriptions`` on the Company result the share class names.
- ratios: ``valuation_ratios`` and ``alpha_beta`` on a Stock result.
- statistics: ``price_statistics`` on a Stock result.

There is no company name in any of them. Percentages are fractions.
"""

from __future__ import annotations

import math


# Morningstar sector codes (historical_asset_classification.morningstar_sector_code).
SECTORS = {
    101: "Basic Materials", 102: "Consumer Cyclical", 103: "Financial Services", 104: "Real Estate",
    205: "Consumer Defensive", 206: "Healthcare", 207: "Utilities",
    308: "Communication Services", 309: "Energy", 310: "Industrials", 311: "Technology",
}
PLACEHOLDER_IPO = "1970-01-01"  # what the empty share classes carry

FIELDS = {
    "company": ("name", "sector", "employees", "ipo_date", "description",
                "market_cap", "enterprise_value", "shares_outstanding", "institutional_ownership", "ownership"),
    "ratios": ("pe", "price_to_sales", "price_to_book", "ev_to_ebitda", "dividend_yield", "beta_60_month"),
    "statistics": ("average_volume_30_day", "average_volume_90_day"),
}
OWNERSHIP = {
    "as_of": "as_of_date", "holders": "13_f_holder_number", "percent_held": "13_f_percent_held",
    "buyers": "13_f_number_of_existing_owner_buying", "sellers": "13_f_number_of_existing_owner_selling",
    "new_holders": "13_f_number_of_new_owners", "sold_out_holders": "13_f_number_of_sold_out_owners",
    "shares_bought": "13_f_shares_bought", "shares_sold": "13_f_shares_sold",
}


def _finite(value) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _positive(value) -> float | None:
    """Morningstar writes 0 for unknown market cap and enterprise value (SPY)."""
    number = _finite(value)
    return number if number is not None and number > 0 else None


def _count(value) -> int | None:
    number = _finite(value)
    return int(number) if number is not None and number >= 0 else None


def _text(value) -> str | None:
    return value.strip() or None if isinstance(value, str) else None


def _table(result: dict, name: str) -> dict:
    tables = result.get("tables")
    value = tables.get(name) if isinstance(tables, dict) else None
    return value if isinstance(value, dict) else {}


def _results(item: dict, kind: str) -> list[dict]:
    results = item.get("results") or []
    results = [results] if isinstance(results, dict) else results
    return [row for row in results if isinstance(row, dict) and row.get("type") == kind]


def _populated(row: dict) -> int:
    return sum(value is not None for value in row.values())


def _company(item: dict, symbol: str) -> dict:
    stocks = _results(item, "Stock")

    def rank(stock: dict) -> tuple[int, int, int]:
        share = _table(stock, "share_class")
        named = str(share.get("symbol") or "").strip().upper() == symbol
        listed = bool(share.get("m_i_c")) and share.get("i_p_o_date") != PLACEHOLDER_IPO
        filled = len(_table(stock, "share_class_profile")) + len(_table(stock, "ownership_summary"))
        return (int(named), int(listed), filled)

    stock = max(stocks, key=rank) if stocks else {}
    share = _table(stock, "share_class")
    profile = _table(stock, "share_class_profile")
    owners = _table(stock, "ownership_summary")
    company_id = share.get("company_id")
    company = next((row for row in _results(item, "Company") if row.get("id") == company_id), {})
    tables = company.get("tables") if isinstance(company.get("tables"), dict) else {}
    sector = _count(_table(company, "historical_asset_classification").get("morningstar_sector_code"))
    ipo = _text(share.get("i_p_o_date"))
    ownership = {key: (_text(owners.get(source)) if key == "as_of" else _finite(owners.get(source)) if key == "percent_held"
                       else _count(owners.get(source))) for key, source in OWNERSHIP.items()}
    return {
        "name": None,
        "sector": SECTORS.get(sector) if sector is not None else None,
        "employees": _count(_table(company, "company_profile").get("total_employee_number")),
        "ipo_date": None if ipo == PLACEHOLDER_IPO else ipo,
        "description": _text(tables.get("long_descriptions")),
        "market_cap": _positive(profile.get("market_cap")),
        "enterprise_value": _positive(profile.get("enterprise_value")),
        "shares_outstanding": _positive(profile.get("shares_outstanding")),
        "institutional_ownership": ownership["percent_held"],
        "ownership": ownership if ownership["holders"] is not None else None,
    }


def _ratios(item: dict, _symbol: str) -> dict:
    def read(stock: dict) -> dict:
        values = _table(stock, "valuation_ratios")
        beta = _table(stock, "alpha_beta").get("period_60m")
        return {
            "pe": _finite(values.get("p_e_ratio")),
            "price_to_sales": _finite(values.get("p_s_ratio")),
            "price_to_book": _finite(values.get("p_b_ratio")),
            "ev_to_ebitda": _finite(values.get("e_v_to_e_b_i_t_d_a")),
            "dividend_yield": _finite(values.get("forward_dividend_yield")),
            "beta_60_month": _finite(beta.get("beta")) if isinstance(beta, dict) else None,
        }

    rows = [read(stock) for stock in _results(item, "Stock")]
    return max(rows, key=_populated) if rows else {}


def _statistics(item: dict, _symbol: str) -> dict:
    def read(stock: dict) -> dict:
        periods = _table(stock, "price_statistics")

        def volume(period: str):
            row = periods.get(period)
            return _positive(row.get("average_volume")) if isinstance(row, dict) else None

        return {"average_volume_30_day": volume("period_30d"), "average_volume_90_day": volume("period_90d")}

    rows = [read(stock) for stock in _results(item, "Stock")]
    return max(rows, key=_populated) if rows else {}


READERS = {"company": _company, "ratios": _ratios, "statistics": _statistics}


def parse(payload, dataset: str) -> dict[str, list[dict]]:
    """Return one normalized, unmerged row per requested symbol, or [] when Tradier has nothing."""
    if dataset not in FIELDS:
        raise ValueError(f"Unsupported fundamentals dataset: {dataset}")
    if not isinstance(payload, list):
        raise ValueError("Tradier fundamentals responses are lists")
    found: dict[str, list[dict]] = {}
    for item in payload:
        if not isinstance(item, dict) or not isinstance(item.get("request"), str):
            continue
        symbol = item["request"].strip().upper()
        row = READERS[dataset](item, symbol)
        normalized = {field: row.get(field) for field in FIELDS[dataset]}
        found[symbol] = [normalized] if any(value is not None for value in normalized.values()) else []
    return found


def normalize_company(payload) -> dict[str, list[dict]]:
    return parse(payload, "company")


def normalize_ratios(payload) -> dict[str, list[dict]]:
    return parse(payload, "ratios")


def normalize_statistics(payload) -> dict[str, list[dict]]:
    return parse(payload, "statistics")
