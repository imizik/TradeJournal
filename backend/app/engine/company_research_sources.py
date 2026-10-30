"""Existing/free adapters; no paid dataset or model calls."""
from decimal import Decimal

from app.engine import symbol_info_financials as financials
from app.engine import symbol_info_financials_feed as sec


def actuals(document, cik):
    normalized = financials.normalize(document)
    # Keep the precise fact selected by the existing conservative span/tag rules.
    for quarter in normalized["quarters"]:
        quarter["evidence"] = {}
        if quarter["gap"]:
            continue
        for metric, (tags, unit) in financials.TAGS.items():
            facts = financials._facts(document, tags, unit)
            selected = facts.get((quarter["start"], quarter["end"]))
            if selected is None:
                continue
            (filed, accession), value = selected
            tag = next((t for t in tags if any(
                r.get("accn") == accession and r.get("start") == quarter["start"] and r.get("end") == quarter["end"]
                for r in document.get("facts", {}).get("us-gaap", {}).get(t, {}).get("units", {}).get(unit, []))), None)
            raw_rows = document.get("facts", {}).get("us-gaap", {}).get(tag, {}).get("units", {}).get(unit, [])
            raw_value = next((r["val"] for r in raw_rows if r.get("accn") == accession and r.get("start") == quarter["start"] and r.get("end") == quarter["end"] and str(r.get("form", "")).startswith("10-Q")), value)
            quarter[metric] = str(Decimal(str(raw_value)))
            quarter["evidence"][metric] = {"accession": accession, "filed": filed, "tag": tag,
                "unit": unit, "basis": "gaap", "currency": "USD",
                "url": f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}/"}
        # Recalculate ratios using decimal values, retaining nulls/gaps.
        revenue = quarter.get("revenue")
        for field, numerator in (("gross_margin", "gross_profit"), ("operating_margin", "operating_income")):
            quarter[field] = str(Decimal(quarter[numerator]) / Decimal(revenue)) if revenue and Decimal(revenue) and quarter.get(numerator) is not None else None
        for key in list(quarter):
            if key.endswith("_yoy"):
                quarter.pop(key)  # Existing float summaries aren't point-in-time research arithmetic.
    return {"state": "ready", "quarters": normalized["quarters"], "entity": document.get("entityName"),
            "cik": str(cik), "note": "Historical financials imported now; Q4 gaps remain explicit."}


def collect(symbol):
    try:
        cik = sec.symbol_financials._cik(symbol)
        if cik is None:
            raise ValueError("No supported SEC issuer found; automatic financials unavailable")
        document = sec.http_json(sec.FACTS_URL.format(cik=int(cik)))
        yield "actuals", "SEC EDGAR", actuals(document, cik)
    except (ValueError, sec.ProviderError, sec.NotFound):
        yield "actuals", "SEC EDGAR", {"state": "unavailable", "message": "SEC financials unavailable. Check issuer coverage and SEC_USER_AGENT."}
    try:
        from app.engine.symbol_info_analysts import symbol_analysts
        data = symbol_analysts.view(symbol)
        data["coverage_note"] = "Current/next-quarter estimates have unresolved fiscal periods and basis. Revision and beat/miss arithmetic is unavailable."
        yield "analysts", "Webull / Yahoo (unofficial)", data
    except Exception:
        yield "analysts", "Webull / Yahoo (unofficial)", {"state": "unavailable", "message": "Analyst providers unavailable"}
    try:
        from app.engine.symbol_info_tradier import symbol_events
        from app.engine.chart_math import ET
        from datetime import datetime
        yield "calendar", "Tradier", symbol_events.events(symbol, datetime.now(ET).date())
    except Exception:
        yield "calendar", "Tradier", {"state": "unavailable", "message": "Earnings calendar unavailable"}
