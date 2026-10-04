"""The chart side panel, separate from chart feed and canvas routes."""

import re

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.database import get_session
from app.engine.symbol_info_journal import read_journal

router = APIRouter()


@router.get("/symbol/{symbol:path}/you")
def you(symbol: str, db: Session = Depends(get_session)):
    symbol = symbol.strip().upper()
    if not re.fullmatch(r"[A-Z][A-Z0-9./-]{0,14}", symbol):
        raise HTTPException(422, "Use a US stock or ETF ticker.")
    return read_journal(db, symbol)
