"""Short & borrow block (T3.1): FINRA short interest, daily short volume and Tradier's borrow list.

Pure: the normalizers and the view compute on responses they are handed. Fetching
and caching live in ``symbol_info_short_feed``.

* Polygon ``/stocks/v1/short-interest`` is FINRA's twice-monthly settlement data:
  ``short_interest`` (shares), ``avg_daily_volume``, ``days_to_cover`` (observed) and
  ``settlement_date``, which lags the calendar by about two weeks.
* Polygon ``/stocks/v1/short-volume`` is the daily FINRA short-sale volume report. It
  covers only the volume FINRA's facilities report, not all trading, so its ratio is
  a share of *that* volume. Polygon's ``short_volume_ratio`` is a percent; the ratio
  here is recomputed from the two volumes.
* Polygon ``/v3/reference/tickers/{t}`` supplies shares outstanding. Neither Polygon
  nor Tradier gives a usable float, so the percentage is of shares outstanding and
  is never called a float percentage.
* Tradier ``/v1/markets/etb`` is the easy-to-borrow list. A symbol missing from it
  is flagged hard to borrow.
"""

import re

SHORT_VOLUME_SESSIONS = 10
SETTLEMENT_NOTE = "FINRA publishes short interest twice a month and the figure lags its settlement date by about two weeks."
VOLUME_NOTE = "Share of the volume FINRA's facilities report, not of all trading, so the share of the full day is lower."
PCT_NOTE = "Shown against shares outstanding. A float figure is not available, so this is not a percent of float."


def _number(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if value == value and abs(value) != float("inf") else None


def _day(value) -> str | None:
    return value if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) else None


def normalize_short_interest(body: dict) -> list[dict]:
    """Settlement rows, newest first: settlement_date, short_interest, avg_daily_volume, days_to_cover."""
    rows = []
    for item in (body or {}).get("results") or []:
        if not isinstance(item, dict):
            continue
        day, shares = _day(item.get("settlement_date")), _number(item.get("short_interest"))
        if not day or shares is None or shares < 0:
            continue
        average, cover = _number(item.get("avg_daily_volume")), _number(item.get("days_to_cover"))
        rows.append({"settlement_date": day, "short_interest": int(shares),
                     "avg_daily_volume": int(average) if average is not None else None, "days_to_cover": cover})
    return sorted(rows, key=lambda row: row["settlement_date"], reverse=True)


def normalize_short_volume(body: dict) -> list[dict]:
    """Daily rows, newest first: date, short_volume, total_volume and ``ratio_pct`` (short over total, in percent)."""
    rows = []
    for item in (body or {}).get("results") or []:
        if not isinstance(item, dict):
            continue
        day, short, total = _day(item.get("date")), _number(item.get("short_volume")), _number(item.get("total_volume"))
        if not day or short is None or total is None or short < 0 or total <= 0:
            continue
        rows.append({"date": day, "short_volume": int(round(short)), "total_volume": int(round(total)),
                     "ratio_pct": round(short / total * 100, 1)})
    return sorted(rows, key=lambda row: row["date"], reverse=True)[:SHORT_VOLUME_SESSIONS]


def normalize_details(body: dict) -> list[dict]:
    """One row of shares outstanding from ticker details, or none: the share class count first, the weighted one as fallback."""
    result = (body or {}).get("results")
    if not isinstance(result, dict):
        return []
    for field in ("share_class_shares_outstanding", "weighted_shares_outstanding"):
        shares = _number(result.get(field))
        if shares and shares > 0:
            return [{"shares_outstanding": int(shares), "basis": field}]
    return []


def normalize_etb(body: dict) -> list[str]:
    """The easy-to-borrow symbols, uppercase and sorted. Tradier returns one object, not a list, for a single row."""
    securities = (body or {}).get("securities")
    rows = securities.get("security") if isinstance(securities, dict) else None
    if isinstance(rows, dict):
        rows = [rows]
    return sorted({str(row["symbol"]).upper() for row in rows or [] if isinstance(row, dict) and row.get("symbol")})


def symbol_key(symbol: str) -> str:
    """Class-share spellings (BRK.B, BRK-B, BRK/B) compare equal."""
    return re.sub(r"[./-]", "", symbol.upper())


def hard_to_borrow(symbol: str, easy: list[str]) -> bool:
    return symbol_key(symbol) not in {symbol_key(item) for item in easy}


def interest_view(rows: list[dict], shares: list[dict]) -> dict:
    """The newest settlement, the change from the one before, and the percent of shares outstanding (calculated)."""
    if not rows:
        return {}
    latest = rows[0]
    out = {**latest, "settlement_note": SETTLEMENT_NOTE, "pct_note": PCT_NOTE, "shares_outstanding": None,
           "shares_basis": None, "pct_of_shares_outstanding": None, "pct_message": None, "previous": None}
    if len(rows) > 1 and rows[1]["short_interest"]:
        before = rows[1]
        out["previous"] = {"settlement_date": before["settlement_date"], "short_interest": before["short_interest"],
                           "change_pct": round((latest["short_interest"] - before["short_interest"]) / before["short_interest"] * 100, 1)}
    if shares:
        out["shares_outstanding"], out["shares_basis"] = shares[0]["shares_outstanding"], shares[0]["basis"]
        out["pct_of_shares_outstanding"] = round(latest["short_interest"] / shares[0]["shares_outstanding"] * 100, 2)
    return out


def volume_view(rows: list[dict]) -> dict:
    if not rows:
        return {}
    # Volume-weighted over the listed sessions: total short volume over total reported volume.
    return {"rows": rows, "average_pct": round(sum(r["short_volume"] for r in rows) / sum(r["total_volume"] for r in rows) * 100, 1),
            "note": VOLUME_NOTE}
