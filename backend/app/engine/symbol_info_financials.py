"""Quarterly financials for the Financials tab (T3.2), normalized from SEC EDGAR companyfacts.

Pure: no network, no clock. ``normalize`` takes the parsed
``data.sec.gov/api/xbrl/companyfacts/CIK##########.json`` document and returns
the last eight quarters. Rules the real NVDA and NBIS payloads forced:

- A quarter is identified by its ``(start, end)`` span of 80-105 days, never by
  ``fp``: the same fiscal period also carries 6- and 9-month year-to-date facts.
- Later 10-Qs repeat the prior-year quarter as a comparative with a later
  ``fy``/``fp``. The value comes from the latest filing for that span (a split
  restates EPS); the fiscal label comes from the earliest filing.
- Q4 exists only inside the 10-K as an annual figure. It is never derived; the
  row is kept as an empty gap so the missing quarter is visible.
- Margins are calculated here (gross profit / revenue, operating income /
  revenue), never read. A missing input leaves the field null, never 0.
"""

from datetime import date, timedelta

QUARTER_DAYS = (80, 105)
SHOWN = 8
YOY_DAYS = (350, 380)  # the same fiscal quarter, a year earlier (52 or 53 weeks)
GAP_DAYS = 120  # consecutive quarter ends further apart than this hide a quarter
REVENUE_TAGS = ("Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet")
TAGS = {
    "revenue": (REVENUE_TAGS, "USD"),
    "gross_profit": (("GrossProfit",), "USD"),
    "operating_income": (("OperatingIncomeLoss",), "USD"),
    "net_income": (("NetIncomeLoss",), "USD"),
    "eps_diluted": (("EarningsPerShareDiluted",), "USD/shares"),
}
NO_QUARTERS = "No quarterly SEC financials for this issuer."


def _day(text) -> date | None:
    try:
        return date.fromisoformat(str(text)[:10])
    except ValueError:
        return None


def _number(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if value == value and abs(value) != float("inf") else None


def _ratio(numerator, denominator) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    return numerator / denominator


def _growth(current, earlier) -> float | None:
    if current is None or earlier in (None, 0):
        return None
    return (current - earlier) / abs(earlier)


def _facts(document: dict, tags: tuple[str, ...], unit: str) -> dict[tuple[str, str], tuple[tuple, float]]:
    """``(start, end) -> (filing key, value)`` for 10-Q quarterly facts: the first tag that has a span wins it."""
    out: dict[tuple[str, str], tuple[tuple, float]] = {}
    gaap = (document.get("facts") or {}).get("us-gaap") or {}
    for tag in tags:
        taken = set(out)
        for row in ((gaap.get(tag) or {}).get("units") or {}).get(unit) or []:
            if not isinstance(row, dict) or not str(row.get("form") or "").startswith("10-Q"):
                continue
            start, end, value = _day(row.get("start")), _day(row.get("end")), _number(row.get("val"))
            if not start or not end or value is None or not QUARTER_DAYS[0] <= (end - start).days <= QUARTER_DAYS[1]:
                continue
            key = (start.isoformat(), end.isoformat())
            if key in taken:
                continue
            filing = (str(row.get("filed") or ""), str(row.get("accn") or ""))
            if key not in out or filing > out[key][0]:
                out[key] = (filing, value)
    return out


def _labels(document: dict) -> dict[tuple[str, str], tuple[tuple, int, str, str]]:
    """``(start, end) -> (filing key, fiscal year, fiscal period, filed)`` from the earliest 10-Q that reported the span."""
    out: dict = {}
    for tags, unit in TAGS.values():
        for tag in tags:
            for row in (((document.get("facts") or {}).get("us-gaap") or {}).get(tag) or {}).get("units", {}).get(unit) or []:
                if not isinstance(row, dict) or not str(row.get("form") or "").startswith("10-Q"):
                    continue
                start, end = _day(row.get("start")), _day(row.get("end"))
                period, year = str(row.get("fp") or ""), row.get("fy")
                if not start or not end or not QUARTER_DAYS[0] <= (end - start).days <= QUARTER_DAYS[1] or not isinstance(year, int) or not period.startswith("Q"):
                    continue
                key = (start.isoformat(), end.isoformat())
                filing = (str(row.get("filed") or ""), str(row.get("accn") or ""))
                if key not in out or filing < out[key][0]:
                    out[key] = (filing, year, period, filing[0])
    return out


def has_quarterly_facts(document: dict) -> bool:
    return bool(_labels(document))


def normalize(document: dict) -> dict:
    """The last eight quarters, oldest first, with gap rows for Q4 and year-over-year growth."""
    labels = _labels(document)
    series = {name: _facts(document, tags, unit) for name, (tags, unit) in TAGS.items()}
    spans = sorted({key for facts in series.values() for key in facts if key in labels}, key=lambda key: key[1])
    rows = []
    for start, end in spans:
        _, year, period, filed = labels[(start, end)]
        row = {"start": start, "end": end, "gap": False, "fiscal_year": year, "fiscal_period": period, "filed": filed}
        for name, facts in series.items():
            row[name] = facts[(start, end)][1] if (start, end) in facts else None
        row["gross_margin"] = _ratio(row["gross_profit"], row["revenue"])
        row["operating_margin"] = _ratio(row["operating_income"], row["revenue"])
        rows.append(row)
    # A quarter that no 10-Q carries (Q4) shows as an empty row between the two neighbours around it.
    timeline = []
    for index, row in enumerate(rows):
        if index and (_day(row["end"]) - _day(rows[index - 1]["end"])).days > GAP_DAYS:
            before = rows[index - 1]
            label = (before["fiscal_year"], "Q4") if before["fiscal_period"] == "Q3" else (None, None)
            timeline.append({"start": None, "end": (_day(row["end"]) - timedelta(days=91)).isoformat(), "gap": True,
                             "fiscal_year": label[0], "fiscal_period": label[1], "filed": None, **dict.fromkeys(
                                 ("revenue", "gross_profit", "operating_income", "net_income", "eps_diluted", "gross_margin", "operating_margin"))})
        timeline.append(row)
    real = [row for row in timeline if not row["gap"]]
    for row in timeline:
        earlier = None
        if not row["gap"]:
            end = _day(row["end"])
            earlier = next((other for other in real if YOY_DAYS[0] <= (end - _day(other["end"])).days <= YOY_DAYS[1]), None)
        for name in ("revenue", "net_income", "eps_diluted"):
            row[f"{name}_yoy"] = _growth(row[name], earlier[name]) if earlier else None
    return {"quarters": timeline[-SHOWN:], "latest_end": rows[-1]["end"] if rows else None}
