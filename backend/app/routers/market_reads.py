"""Owner view of Jo's scheduled market reads: packet, read seen, delay and delivery. Read-only.

Joins #315's publisher receipts with the MW-2 wake store's read notices
(``reliability_report``) and the phone watchdog's notices. No store or scheduler of its own.
"""

from datetime import UTC, date, datetime, timedelta
import logging
import os
from pathlib import Path

from fastapi import APIRouter, Query, Request

from stock_watch_common import ET

router = APIRouter()
log = logging.getLogger(__name__)
SESSIONS = 10  # weekdays shown, newest first
IMPORT_STALE = timedelta(minutes=3)  # the MW-2 runner checks the read outbox every 30 s; six missed passes


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


def _one(day: date, now: datetime) -> list[date]:
    """One requested weekday for the Daily Review; a future date or weekend has no slots."""
    return [day] if day.weekday() < 5 and day <= now.astimezone(ET).date() else []


def _importer(app, now: datetime) -> dict:
    """Is the API's MW-2 runner bringing in Jo's read notices? Missing reads are only judged while it is."""
    runner = getattr(app.state, "market_watch", None)
    last = getattr(runner, "last_ingest", None)
    configured = runner is not None and runner.outbox_dir is not None
    current = configured and last is not None and now - _parse(last) <= IMPORT_STALE
    return {"running": runner is not None, "outbox_configured": configured, "last_ingest": last, "current": current}


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


@router.get("")
def market_reads(request: Request, day: date | None = None, month: str | None = Query(None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$")):
    from app.engine.jo_morning import watchdog_status, weekdays_in_month
    from app.engine.market_watch_wakes import MarketWatchWakeStore, enabled, reliability_report

    now = _now()
    importer = _importer(request.app, now)
    # Missing reads are judged only up to the last finished import; with none, they stay unknown.
    through = _parse(importer["last_ingest"]) if importer["outbox_configured"] and importer["last_ingest"] else datetime.min.replace(tzinfo=UTC)
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
    def pick(first):
        if day is not None:
            return _one(day, now)
        if month is not None:  # the calendar's month, never before the earliest recorded evidence
            return [d for d in weekdays_in_month(month, now.astimezone(ET).date()) if d >= (first or now.astimezone(ET).date())]
        return _days(now.astimezone(ET).date(), first)
    try:
        if store is not None:
            evidence |= {date.fromisoformat(r["session_date"]) for r in store.records("read_notice")}
        days = pick(min(evidence, default=None))
        view = reliability_report(store, receipts, days, hours=_hours, now=now, reads_through=through)
    except Exception:
        # A corrupt or locked store makes reads unknown; it never fails the page.
        log.exception("Market-watch store unreadable")
        days = pick(min(evidence, default=None))
        view = reliability_report(None, receipts, days, hours=_hours, now=now, reads_through=through)
    for session in view["sessions"]:
        session["watchdog"] = watchdog_status(date.fromisoformat(session["session_date"]), section="jo_market_reads")
    return {**view, "market_watch_enabled": enabled(), "importer": importer}
