"""Owner view of the setup scanner (S1): the day's candidates and rules-only results.

Read-only. The scanner itself runs in the level alert monitor's loop
(``engine/setup_scanner.py``); these routes never start, stop or change it.
"""

from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.database import get_session
from app.engine.chart_math import ET
from app.engine.setup_scanner import day_view
from app.models import Trade

router = APIRouter()


@router.get("/day")
def scanner_day(day: str | None = None, db: Session = Depends(get_session)):
    try:
        wanted = date.fromisoformat(day) if day else datetime.now(ET).date()
    except ValueError:
        raise HTTPException(422, "day must be YYYY-MM-DD") from None
    start = datetime(wanted.year, wanted.month, wanted.day)
    # One entry per trade opened, so partial fills and scale-ins do not count twice.
    entries = db.exec(select(Trade.opened_at).where(Trade.instrument_type == "option",
                                                    Trade.opened_at >= start, Trade.opened_at < start + timedelta(days=1))).all()
    return day_view(db, wanted, list(entries))
