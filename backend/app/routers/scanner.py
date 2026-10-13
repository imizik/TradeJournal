"""Owner view of the setup scanner: rules, Shadow and linked Isaac trades.

Read-only. The scanner itself runs in the level alert monitor's loop
(``engine/setup_scanner.py``); these routes never start, stop or change it.
"""

from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from sqlalchemy import func

from app.database import get_session
from app.engine.chart_math import ET
from app.engine.setup_scanner import day_view
from app.models import Account, ScannerCandidate, Trade

router = APIRouter()


@router.get("/day")
def scanner_day(day: str | None = None, db: Session = Depends(get_session)):
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
    return day_view(db, wanted, entries, active_trades)
