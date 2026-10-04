"""Pure normalizers for the Events tab (T1.4) and the chart's earnings markers (C2.5).

Tradier field names stop here. Callers receive normalized rows:

- earnings: {"date", "status": "confirmed"|"estimated", "fiscal_year", "fiscal_quarter", "event"}
- dividends: {"ex_date", "amount", "currency", "pay_date", "record_date", "declared", "frequency", "type"}
- splits: {"ex_date", "from", "to"}

Traps the 2026-10-02 probe found (docs/symbol-info-roadmap.md, "Data traps"):
each symbol comes back as several share classes or companies, and only one
carries data; fields are never merged across them. A calendar can hold a
confirmed and an estimated row for the same fiscal quarter; the confirmed one
wins. The calendar has dates only: its `time_zone` holds a placeholder date,
so nothing here claims a time of day. ETFs and indices have no calendar.
"""

from datetime import date, timedelta

# Tradier's corporate-calendar event types for quarterly earnings *results*.
# Conference calls (12-15), meetings and conferences are other types.
RESULT_TYPES = {7: 1, 8: 2, 9: 3, 10: 4}
STATUSES = {"Confirmed": "confirmed", "Estimated": "estimated"}
REPORTS_SHOWN = 8
SPLIT_DAYS = 730  # "splits in the last two years"


def _rows(table) -> list[dict]:
    """A Tradier table as rows: it comes back as null, one row as an object,
    several as a list, or (splits) as an object keyed by date."""
    if table is None:
        return []
    if isinstance(table, list):
        return [row for row in table if isinstance(row, dict)]
    if isinstance(table, dict):
        if table and all(isinstance(value, dict) for value in table.values()):
            return list(table.values())
        return [table]
    return []


def _classes(payload, table: str) -> dict[str, list[dict]]:
    """Each requested symbol's rows from ONE share class (or company): the one
    with the most rows. The secondary classes come back empty or nearly so."""
    if not isinstance(payload, list):
        raise ValueError("Tradier fundamentals responses are lists")
    found = {}
    for item in payload:
        if not isinstance(item, dict) or not isinstance(item.get("request"), str):
            continue
        results = item.get("results") or []
        results = [results] if isinstance(results, dict) else results
        candidates = [_rows(result["tables"][table]) for result in results
                      if isinstance(result, dict) and isinstance(result.get("tables"), dict) and table in result["tables"]]
        found[item["request"].strip().upper()] = max(candidates, key=len, default=[])
    return found


def _day(value) -> date | None:
    try:
        day = date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None
    return day if day.year >= 1980 else None  # 1970-01-01 is Tradier's empty-date placeholder


def _number(value) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed == parsed and parsed not in (float("inf"), float("-inf")) else None


def _int(value) -> int | None:
    number = _number(value)
    return int(number) if number is not None and number == int(number) else None


def parse_earnings(payload) -> dict[str, list[dict]]:
    """Quarterly earnings-result rows per requested symbol, oldest first. Rows
    without a usable date, quarter or status are dropped, never guessed."""
    result = {}
    for symbol, rows in _classes(payload, "corporate_calendars").items():
        kept = []
        for row in rows:
            quarter = RESULT_TYPES.get(_int(row.get("event_type")))
            status = STATUSES.get(row.get("event_status"))
            day = _day(row.get("begin_date_time"))
            year = _int(row.get("event_fiscal_year"))
            if quarter and status and day and year:
                kept.append({"date": day.isoformat(), "status": status, "fiscal_year": year, "fiscal_quarter": quarter,
                             "event": str(row.get("event") or "")[:160]})
        result[symbol] = sorted(kept, key=lambda row: (row["date"], row["status"]))
    return result


def parse_dividends(payload) -> dict[str, list[dict]]:
    """Cash dividends per requested symbol, newest ex-date first. `type` is
    Tradier's own code (CD: regular cash), passed through, not interpreted."""
    result = {}
    for symbol, rows in _classes(payload, "cash_dividends").items():
        kept = []
        for row in rows:
            ex_date, amount = _day(row.get("ex_date")), _number(row.get("cash_amount"))
            if ex_date and amount is not None and amount > 0:
                dates = {key: (_day(row.get(field)) or None) for key, field in
                         (("pay_date", "pay_date"), ("record_date", "record_date"), ("declared", "declaration_date"))}
                kept.append({"ex_date": ex_date.isoformat(), "amount": amount, "currency": str(row.get("currency_i_d") or "USD")[:3],
                             **{key: value.isoformat() if value else None for key, value in dates.items()},
                             "frequency": _int(row.get("frequency")) or None, "type": str(row.get("dividend_type") or "")[:4]})
        result[symbol] = sorted(kept, key=lambda row: row["ex_date"], reverse=True)
    return result


def parse_splits(payload) -> dict[str, list[dict]]:
    """Stock splits per requested symbol, newest first: `to` new shares for every `from`."""
    result = {}
    for symbol, rows in _classes(payload, "stock_splits").items():
        kept = []
        for row in rows:
            ex_date, before, after = _day(row.get("ex_date")), _number(row.get("split_from")), _number(row.get("split_to"))
            if ex_date and before and after and before > 0 and after > 0:
                kept.append({"ex_date": ex_date.isoformat(), "from": before, "to": after})
        result[symbol] = sorted(kept, key=lambda row: row["ex_date"], reverse=True)
    return result


def quarter_label(row: dict) -> str:
    return f"Q{row['fiscal_quarter']} FY{row['fiscal_year']}"


def report_dates(rows: list[dict]) -> list[dict]:
    """One date per fiscal quarter, oldest first. A confirmed row wins over an
    estimate for the same quarter; otherwise the earliest date wins."""
    best: dict[tuple[int, int], dict] = {}
    for row in rows:
        key = (row["fiscal_year"], row["fiscal_quarter"])
        held = best.get(key)
        if held is None or (row["status"] != "confirmed", row["date"]) < (held["status"] != "confirmed", held["date"]):
            best[key] = row
    return sorted(({**row, "label": quarter_label(row)} for row in best.values()), key=lambda row: row["date"])


def earnings_view(rows: list[dict], today: date, reports: int | None = REPORTS_SHOWN) -> dict:
    """The next report on or after ``today`` (New York), and past reports, newest first.

    A past quarter counts only when its date was confirmed: an estimate whose
    day has passed was never a report. Without an upcoming row, ``next`` is
    None: nothing is projected from earlier quarters.
    """
    quarters = report_dates(rows)
    day = today.isoformat()
    upcoming = [row for row in quarters if row["date"] >= day]
    past = [row for row in reversed(quarters) if row["date"] < day and row["status"] == "confirmed"]
    shown = past if reports is None else past[:reports]
    return {
        "next": {key: upcoming[0][key] for key in ("date", "status", "label")} if upcoming else None,
        "reports": [{key: row[key] for key in ("date", "label")} for row in shown],
    }


def dividends_view(rows: list[dict], today: date) -> dict:
    """The next announced ex-dividend date, if any, and the most recent one before today."""
    day = today.isoformat()
    upcoming = [row for row in rows if row["ex_date"] >= day]
    past = [row for row in rows if row["ex_date"] < day]
    return {"next": upcoming[-1] if upcoming else None, "last": past[0] if past else None}


def splits_view(rows: list[dict], today: date) -> list[dict]:
    """Splits from two years before ``today`` onward, announced ones included, newest first."""
    since = (today - timedelta(days=SPLIT_DAYS)).isoformat()
    return [{**row, "label": f"{row['to']:g}-for-{row['from']:g}"} for row in rows if row["ex_date"] >= since]
