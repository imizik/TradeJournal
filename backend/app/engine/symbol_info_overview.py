"""Pure normalizers for the Symbol Info Overview tab (T1.3).

Tradier's fundamentals endpoints wrap each requested symbol in a list and can
return more than one share class. Keep only the best matching class for each
dataset; never fill missing fields from a second class.
"""

from __future__ import annotations

import math


FIELDS = {
    "company": ("name", "sector", "employees", "ipo_date", "description"),
    "ratios": ("pe", "price_to_sales", "price_to_book", "ev_to_ebitda", "dividend_yield", "beta_60_month"),
    "statistics": ("market_cap", "enterprise_value", "shares_outstanding", "institutional_ownership", "average_volume_30_day"),
}

ALIASES = {
    "name": ("company_name", "name"),
    "sector": ("sector",),
    "employees": ("employees", "number_of_employees"),
    "ipo_date": ("ipo_date", "initial_public_offering_date"),
    "description": ("description", "long_description"),
    "pe": ("pe_ratio", "price_to_earnings"),
    "price_to_sales": ("price_to_sales", "price_sales_ratio", "ps_ratio"),
    "price_to_book": ("price_to_book", "price_book_ratio", "pb_ratio"),
    "ev_to_ebitda": ("ev_to_ebitda", "enterprise_value_to_ebitda"),
    "dividend_yield": ("dividend_yield",),
    "beta_60_month": ("beta_60_month", "beta_60_months", "beta_5_year"),
    "market_cap": ("market_cap", "market_capitalization"),
    "enterprise_value": ("enterprise_value",),
    "shares_outstanding": ("shares_outstanding",),
    "institutional_ownership": ("institutional_ownership", "percent_held_by_institutions", "institutional_holdings_percent"),
    "average_volume_30_day": ("average_volume_30_day", "average_daily_volume_30_day", "avg_volume_30_day"),
}


def _rows(value) -> list[dict]:
    if isinstance(value, dict):
        return [row for row in value.values() if isinstance(row, dict)] if value and all(isinstance(row, dict) for row in value.values()) else [value]
    if isinstance(value, list):
        return [row for row in value if isinstance(row, dict)]
    return []


def _finite(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _value(row: dict, key: str):
    for alias in ALIASES[key]:
        value = row.get(alias)
        if value not in (None, ""):
            if key in ("name", "sector", "description", "ipo_date"):
                return str(value).strip() or None
            if key == "employees":
                number = _finite(value)
                return int(number) if number is not None and number >= 0 else None
            return _finite(value)
    return None


def _table_rows(result: dict, table: str) -> list[dict]:
    tables = result.get("tables") if isinstance(result.get("tables"), dict) else {}
    return _rows(tables.get(table))


def _candidate_key(row: dict, symbol: str, fields: tuple[str, ...]) -> tuple[int, int, int]:
    named = str(row.get("symbol") or row.get("ticker") or "").strip().upper() == symbol
    primary = row.get("is_primary") is True or str(row.get("primary") or "").lower() in ("true", "yes", "primary")
    populated = sum(_value(row, field) is not None for field in fields)
    return (int(primary), int(named), populated)


def parse(payload, dataset: str) -> dict[str, list[dict]]:
    """Return one normalized, unmerged row per requested symbol."""
    if dataset not in FIELDS:
        raise ValueError(f"Unsupported fundamentals dataset: {dataset}")
    if not isinstance(payload, list):
        raise ValueError("Tradier fundamentals responses are lists")
    fields = FIELDS[dataset]
    table = {"company": "company", "ratios": "ratios", "statistics": "price_statistics"}[dataset]
    found: dict[str, dict] = {}
    for item in payload:
        if not isinstance(item, dict) or not isinstance(item.get("request"), str):
            continue
        symbol = item["request"].strip().upper()
        results = item.get("results") or []
        results = [results] if isinstance(results, dict) else results
        candidates = [row for result in results if isinstance(result, dict) for row in _table_rows(result, table)]
        if not candidates:
            found[symbol] = []
            continue
        row = max(candidates, key=lambda candidate: _candidate_key(candidate, symbol, fields))
        normalized = {field: _value(row, field) for field in fields}
        found[symbol] = [normalized] if any(value is not None for value in normalized.values()) else []
    return found


def normalize_company(payload) -> dict[str, list[dict]]:
    return parse(payload, "company")


def normalize_ratios(payload) -> dict[str, list[dict]]:
    return parse(payload, "ratios")


def normalize_statistics(payload) -> dict[str, list[dict]]:
    return parse(payload, "statistics")
