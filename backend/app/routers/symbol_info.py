"""The chart side panel, separate from chart feed and canvas routes."""

from datetime import datetime
import re

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.database import get_session
from app.engine.chart_math import ET
from app.engine import symbol_info_tradier
from app.engine.symbol_info_journal import read_journal

router = APIRouter()


def _ticker(symbol: str) -> str:
    symbol = symbol.strip().upper()
    if not re.fullmatch(r"[A-Z][A-Z0-9./-]{0,14}", symbol):
        raise HTTPException(422, "Use a US stock or ETF ticker.")
    return symbol


@router.get("/symbol/{symbol:path}/you")
def you(symbol: str, db: Session = Depends(get_session)):
    return read_journal(db, _ticker(symbol))


@router.get("/symbol/{symbol:path}/events")
def events(symbol: str):
    """Next earnings, past report dates, dividends and splits (T1.4), from Tradier's cached fundamentals."""
    return symbol_info_tradier.symbol_events.events(_ticker(symbol), datetime.now(ET).date())
