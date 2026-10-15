"""Owner view of the setup scanner: rules, Shadow and linked Isaac trades.

The owner can edit the universe for future scans. Saving never enables the
scanner or changes existing candidates and paper trades.
"""

import json
import re
from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session, select
from sqlalchemy import func, update
from sqlalchemy.exc import IntegrityError

from app.database import get_session
from app.engine.chart_math import ET
from app.engine.setup_scanner import day_view
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
