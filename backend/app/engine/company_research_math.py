"""Conservative arithmetic over explicitly identified financial observations."""
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone


def number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        out = Decimal(str(value))
        return out if out.is_finite() else None
    except InvalidOperation:
        return None


def compare(actual, reference):
    keys = ("issuer", "metric", "period_start", "period_end", "fiscal_year", "fiscal_period", "scope", "currency", "unit", "basis", "share_basis")
    for key in keys:
        if key not in actual or key not in reference or actual[key] in (None, "unknown", "unresolved") or actual[key] != reference[key]:
            return {"state": "incompatible", "reason": f"Incompatible or unknown {key}"}
    if actual["scope"] == "segment" and (not actual.get("segment") or actual.get("segment") != reference.get("segment")):
        return {"state": "incompatible", "reason": "Incompatible segment"}
    a, b = number(actual.get("value")), number(reference.get("value"))
    midpoint = False
    if b is None:
        low, high = number(reference.get("low")), number(reference.get("high"))
        if low is not None and high is not None and low <= high:
            b, midpoint = (low + high) / 2, True
    if a is None or b is None:
        return {"state": "unavailable", "reason": "Missing or invalid number"}
    delta = a - b
    if actual["metric"] in {"gross_margin", "operating_margin"}:
        return {"state": "ready", "difference": str(delta * 100), "percent": None,
                "difference_unit": "percentage points", "reference": "calculated range midpoint" if midpoint else "point value",
                "result": "above" if delta > 0 else "below" if delta < 0 else "equal"}
    minimum = Decimal("0.01") if actual["metric"] == "eps" else Decimal(0)
    pct = delta / abs(b) if b != 0 and abs(b) >= minimum else None
    return {"state": "ready", "difference": str(delta), "percent": str(pct) if pct is not None else None,
            "result": "above" if delta > 0 else "below" if delta < 0 else "equal",
            "reference": "calculated range midpoint" if midpoint else "point value", "difference_unit": actual["unit"]}


def earnings_comparison(actual, reference):
    result = compare(actual, reference)
    if result["state"] != "ready":
        return result
    try:
        published = actual["published_at"]
        # A date-only release requires a snapshot from before that entire UTC day;
        # this is conservative for a US issuer's New York reporting date.
        released = datetime.fromisoformat(published.replace("Z", "+00:00"))
        released = released.replace(tzinfo=timezone.utc) if released.tzinfo is None else released
        observed = datetime.fromisoformat(reference["observed_at"].replace("Z", "+00:00"))
        if observed >= released:
            raise ValueError()
    except (KeyError, TypeError, ValueError, AttributeError):
        return {"state": "incompatible", "reason": "No compatible estimate observed before the release"}
    return result
