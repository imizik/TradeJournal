"""Owner view of Jo's scheduled market reads: packet, read seen, measured delay. Read-only.

Joins #315's publisher receipts with the MW-2 wake store's read notices
(``reliability_report``). No store, scheduler or tolerance of its own.
"""

from datetime import UTC, date, datetime, timedelta
import logging
import os
from pathlib import Path

from fastapi import APIRouter

from stock_watch_common import ET

router = APIRouter()
log = logging.getLogger(__name__)
SESSIONS = 10  # weekdays shown, newest first


def _now():
    return datetime.now(UTC)


def _hours(day: date):
    from app.engine.chart_calendar import chart_calendar
    return chart_calendar.hours(day)


def _receipts() -> Path:
    from market_watch_schedule import RECEIPT_DIRECTORY
    return RECEIPT_DIRECTORY


def _days(today: date, first: date | None) -> list[date]:
    """Weekdays back from today, never before the earliest recorded evidence."""
    days, day = [], today
    while len(days) < SESSIONS and day >= (first or today):
        if day.weekday() < 5:
            days.append(day)
        day -= timedelta(days=1)
    return days


@router.get("")
def market_reads():
    from app.engine.market_watch_wakes import MarketWatchWakeStore, enabled, reliability_report

    now = _now()
    store_path = os.environ.get("MARKET_WATCH_STORE", "")
    store = None
    if store_path and Path(store_path).is_absolute() and Path(store_path).exists():
        try:
            store = MarketWatchWakeStore(store_path)
        except Exception:
            log.exception("Market-watch store unreadable")
    receipts = _receipts()
    evidence = set()
    try:
        for child in receipts.iterdir() if receipts.is_dir() else ():
            try:
                evidence.add(date.fromisoformat(child.name))
            except ValueError:
                pass
    except OSError:
        log.exception("Publisher receipts unreadable")
    try:
        if store is not None:
            evidence |= {date.fromisoformat(r["session_date"]) for r in store.records("read_notice")}
        days = _days(now.astimezone(ET).date(), min(evidence, default=None))
        view = reliability_report(store, receipts, days, hours=_hours, now=now)
    except Exception:
        # A corrupt or locked store makes reads unknown; it never fails the page.
        log.exception("Market-watch store unreadable")
        days = _days(now.astimezone(ET).date(), min(evidence, default=None))
        view = reliability_report(None, receipts, days, hours=_hours, now=now)
    return {**view, "market_watch_enabled": enabled()}
