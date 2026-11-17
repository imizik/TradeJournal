"""Compare recent QQQ paper receipts with elapsed windows on the cached calendar."""

from datetime import date, datetime, timedelta

from app.engine.chart_calendar import chart_calendar
from app.engine.chart_math import ET

LOOKBACK_DAYS = 14


def report(now: float, receipts: set[tuple[str, int]], windows: tuple[tuple[int, int], ...]) -> dict | None:
    """Start at the first receipt. A missing row cannot tell us when the worker was enabled or why it missed a window."""
    if not receipts:
        return None
    first = min(receipts)
    local = datetime.fromtimestamp(now, ET)
    today = local.date()
    minute = local.hour * 60 + local.minute
    day = max(date.fromisoformat(first[0]), today - timedelta(days=LOOKBACK_DAYS - 1))
    missing = 0
    latest_missing_day = None
    unknown_days = 0
    while day <= today:
        iso = day.isoformat()
        absent = sum(
            (iso, slot) >= first and (day < today or minute >= deadline) and (iso, slot) not in receipts
            for slot, deadline in windows
        )
        if absent and day.weekday() < 5:
            hours = chart_calendar.cached(day)
            if hours is None:
                unknown_days += 1
            elif hours["status"] == "open" and hours["close"] == 16 * 60:
                missing += absent
                latest_missing_day = iso
        day += timedelta(days=1)
    return {"missing": missing, "latest_missing_day": latest_missing_day, "unknown_days": unknown_days}
