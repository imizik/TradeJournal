"""Owner view of the setup scanner: rules, Shadow and linked Isaac trades.

The owner can edit the universe for future scans. Saving never enables the
scanner or changes existing candidates and paper trades.
"""

import json
import re
import time
from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlmodel import Session, select
from sqlalchemy import func, update
from sqlalchemy.exc import IntegrityError

from app.database import get_session
from app.engine import scanner_rules as rules
from app.engine.chart_calendar import chart_calendar
from app.engine.chart_math import ET
from app.engine.level_alerts import LATENESS
from app.engine.paper import regular_session
from app.engine.setup_scanner import day_view, enabled
from app.engine.scanner_settings import MAX_SYMBOLS, SETTINGS_KEY, read_settings
from app.models import Account, ChartSettingsRecord, ScannerCandidate, Trade

router = APIRouter()


class ScannerSettingsSave(BaseModel):
    symbols: list[str] = Field(max_length=MAX_SYMBOLS)
    base_revision: int = Field(ge=0)


@router.get("/settings")
def scanner_settings(db: Session = Depends(get_session)):
    return read_settings(db)


@router.put("/settings")
def save_scanner_settings(body: ScannerSettingsSave, db: Session = Depends(get_session)):
    symbols = list(dict.fromkeys(symbol.strip().upper() for symbol in body.symbols))
    if any(not re.fullmatch(r"[A-Z][A-Z0-9./-]{0,14}", symbol) for symbol in symbols):
        raise HTTPException(422, "Use US stock or ETF ticker symbols, such as AAPL or BRK.B.")
    values = {"data_json": json.dumps({"symbols": symbols}), "revision": body.base_revision + 1,
              "updated_at": datetime.now(UTC).replace(tzinfo=None)}
    try:
        if body.base_revision == 0:
            db.add(ChartSettingsRecord(name=SETTINGS_KEY, **values))
            db.commit()
            saved = True
        else:
            result = db.execute(update(ChartSettingsRecord).where(
                ChartSettingsRecord.name == SETTINGS_KEY,
                ChartSettingsRecord.revision == body.base_revision,
            ).values(**values))
            db.commit()
            saved = result.rowcount == 1
    except IntegrityError:
        db.rollback()
        saved = False
    if not saved:
        raise HTTPException(409, "Scanner tickers changed on another device. Reload saved tickers before saving again.")
    return {"symbols": symbols, "revision": values["revision"], "max_symbols": MAX_SYMBOLS}


def _session_status(day: date):
    """The calendar's answer for ``day``; weekends are closed even when the calendar is unavailable."""
    hours = chart_calendar.hours(day)
    if hours is None:
        return ("closed" if day.weekday() >= 5 else "unknown"), None
    session = regular_session(day, hours)
    return ("open" if session is not None else "closed"), session


def _monitoring(request: Request, db: Session, now: float) -> dict:
    """Read-only freshness of the running scanner, from the bars it has judged this process.

    Only a judged bar proves the scanner looked; an enabled flag or a recent page load does not."""
    today = datetime.fromtimestamp(now, ET).date()
    result = {"state": "off", "checked_at": datetime.fromtimestamp(now, UTC).isoformat().replace("+00:00", "Z"),
              "last_judged_bar_end": None, "symbols_judged": 0, "symbols_selected": len(read_settings(db)["symbols"])}
    scanner = getattr(getattr(request.app.state, "level_alerts", None), "scanner", None)
    if not enabled():
        return result
    if scanner is None or not scanner.paper_enabled:
        return {**result, "state": "not_running"}
    status, session = _session_status(today)
    start = datetime(today.year, today.month, today.day, tzinfo=ET).timestamp()
    judged = [end for end in dict(scanner._scanned).values() if end >= start]
    newest = max(judged, default=None)
    if newest is not None:
        result.update(last_judged_bar_end=datetime.fromtimestamp(newest, UTC).isoformat().replace("+00:00", "Z"),
                      symbols_judged=judged.count(newest))
    if session is None:
        return {**result, "state": "market_closed" if status == "closed" else "calendar_unknown"}
    first_end = session.open_at + rules.FIRST_BAR_AFTER + rules.BAR_SECONDS
    last_end = min(datetime(today.year, today.month, today.day, rules.LAST_BAR_END_MINUTE // 60,
                            rules.LAST_BAR_END_MINUTE % 60, tzinfo=ET).timestamp(), session.close_at - 3600)
    if not first_end + LATENESS <= now <= last_end + LATENESS + rules.MAX_DELAY_SECONDS:
        return {**result, "state": "outside_window"}
    reference = newest if newest is not None else first_end - rules.BAR_SECONDS
    late = now - reference > rules.BAR_SECONDS + LATENESS + rules.MAX_DELAY_SECONDS
    return {**result, "state": "stale" if late else "fresh"}


@router.get("/day")
def scanner_day(request: Request, day: str | None = None, db: Session = Depends(get_session)):
    try:
        wanted = date.fromisoformat(day) if day else datetime.now(ET).date()
    except ValueError:
        raise HTTPException(422, "day must be YYYY-MM-DD") from None
    start = datetime(wanted.year, wanted.month, wanted.day)
    # One entry per trade opened, so partial fills and scale-ins do not count twice.
    first_day = select(func.min(ScannerCandidate.session_date)).where(ScannerCandidate.session_date <= wanted).scalar_subquery()
    trades = db.exec(select(Trade, Account.broker).outerjoin(Account, Trade.account_id == Account.id)
                     .where(Trade.instrument_type == "option", Trade.opened_at >= func.coalesce(first_day, start),
                            Trade.opened_at < start + timedelta(days=1))).all()
    # Preserve the S1 entry flag's account scope; only S2 linking excludes dormant Webull.
    entries = [trade.opened_at for trade, _ in trades if trade.opened_at >= start]
    active_trades = [trade for trade, broker in trades if broker != "webull"]
    status, session = _session_status(wanted)
    return {**day_view(db, wanted, entries, active_trades, session), "session": status,
            "monitoring": _monitoring(request, db, time.time())}
