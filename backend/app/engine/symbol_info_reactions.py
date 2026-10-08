"""T2.2 inferred earnings reactions from completed, split-adjusted daily bars."""

from datetime import date, datetime, time, timedelta
from math import isfinite

from app.engine.chart_math import ET

SOURCE = "Tradier daily history"
MAX_SEARCH_DAYS = 10


def _session(day: date, calendar, *, after: bool) -> date | None:
    """Find an exchange session using the provider calendar, refusing unknown coverage."""
    for offset in range(MAX_SEARCH_DAYS + 1):
        candidate = day + timedelta(days=offset if after else -offset)
        hours = calendar.hours(candidate)
        if hours is None:
            return None
        if hours["status"] == "open":
            return candidate
    return None


def _completed(day: date, calendar, now: datetime) -> bool:
    hours = calendar.hours(day)
    if not hours or hours["status"] != "open":
        return False
    return now >= datetime.combine(day, time(hours["close"] // 60, hours["close"] % 60), ET)


def calculate(reports: list[dict], bars: list[dict], calendar, now: datetime, conflicts=()) -> list[dict]:
    """Calculate the latest eight selected confirmed reports, newest first."""
    report_rows = [r for r in reports if r.get("date") and r["date"] < now.date().isoformat()]
    selected = sorted(report_rows, key=lambda r: r["date"], reverse=True)[:8]
    by_day: dict[date, dict | None] = {datetime.fromtimestamp(bar["time"], ET).date(): bar for bar in bars}
    for day in conflicts:
        by_day[day] = None

    out = []
    for report in selected:
        report_day = date.fromisoformat(report["date"])
        first = _session(report_day, calendar, after=True)
        second = _session(first + timedelta(days=1), calendar, after=True) if first else None
        row = {"report_date": report["date"], "label": report.get("label"), "state": "unavailable",
               "reason": None, "sessions": [], "reaction_date": None, "gap_pct": None, "reaction_pct": None}
        if not first or not second:
            row["reason"] = "Exchange calendar coverage is unavailable."
            out.append(row)
            continue
        candidates = []
        for session_day in (first, second):
            previous = _session(session_day - timedelta(days=1), calendar, after=False)
            dates = {"date": session_day.isoformat(), "previous_date": previous.isoformat() if previous else None}
            if not previous:
                candidates.append({**dates, "state": "unavailable", "reason": "Exchange calendar coverage is unavailable.", "gap_pct": None, "day_pct": None})
                continue
            prior_bar, bar = by_day.get(previous), by_day.get(session_day)
            if not _completed(session_day, calendar, now):
                reason = "The session is not complete yet."
            elif prior_bar is None or bar is None:
                reason = "A required daily bar is missing or conflicting."
            else:
                prior, opened, closed = prior_bar["close"], bar["open"], bar["close"]
                if not all(isinstance(v, (int, float)) and isfinite(v) and v > 0 for v in (prior, opened, closed)):
                    reason = "A required daily price is invalid."
                else:
                    gap = 100 * (opened / prior - 1)
                    move = 100 * (closed / prior - 1)
                    candidates.append({**dates, "state": "ready", "reason": None, "gap_pct": gap, "day_pct": move})
                    continue
            candidates.append({**dates, "state": "unavailable", "reason": reason, "gap_pct": None, "day_pct": None})
        row["sessions"] = candidates
        if all(s["state"] == "ready" for s in candidates):
            # Larger absolute close-to-prior-close move wins; ties select first session.
            chosen = max(enumerate(candidates), key=lambda pair: (abs(pair[1]["day_pct"]), -pair[0]))[1]
            row.update(state="ready", reaction_date=chosen["date"], gap_pct=chosen["gap_pct"], reaction_pct=chosen["day_pct"])
        else:
            row["reason"] = next(s["reason"] for s in candidates if s["state"] != "ready")
        out.append(row)
    return out


def summary(rows: list[dict]) -> dict:
    usable = [r for r in rows if r["state"] == "ready"]
    average = sum(abs(r["reaction_pct"]) for r in usable) / len(usable) if len(usable) >= 4 else None
    return {"usable_count": len(usable), "average_abs_pct": average,
            "report_range": {"from": usable[-1]["report_date"], "to": usable[0]["report_date"]} if average is not None else None}
