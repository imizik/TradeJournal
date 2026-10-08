"""The chart side panel, separate from chart feed and canvas routes."""

from datetime import datetime
import re

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session

from app.database import get_session
from app.engine.chart_math import ET
from app.engine import symbol_info_analysts, symbol_info_news_feed, symbol_info_tradier
from app.engine.options_feed import options_feed
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


@router.get("/symbol/{symbol:path}/news")
def news(symbol: str):
    """Headlines from Alpaca (Benzinga) and Polygon, merged (T1.2): the newest 20, plus the newest 20 that
    tag at most three symbols so the browser's Focused filter can fill a list. Cached 60 s (Alpaca) and
    15 min (Polygon); each source degrades on its own and the response says how each one went."""
    return symbol_info_news_feed.symbol_news.view(_ticker(symbol))


@router.get("/symbol/{symbol:path}/events")
def events(symbol: str):
    """Next earnings, past report dates, dividends and splits (T1.4), from Tradier's cached fundamentals."""
    return symbol_info_tradier.symbol_events.events(_ticker(symbol), datetime.now(ET).date())


@router.get("/symbol/{symbol:path}/overview")
def overview(symbol: str):
    """Company profile and valuation/statistics (T1.3), from cached Tradier fundamentals."""
    return symbol_info_tradier.symbol_events.overview(_ticker(symbol))


@router.get("/symbol/{symbol:path}/forecast")
def forecast(symbol: str, spot: float | None = Query(None, gt=0)):
    """The implied move (T2.1): the at-the-money straddle at ``spot`` (the chart's latest price)
    for the nearest expiration, the nearest Friday and the first expiration after the next report."""
    symbol = _ticker(symbol)
    today = datetime.now(ET).date()
    # The next report from the Events cache only; a stale one refreshes in the background.
    earnings = symbol_info_tradier.symbol_events.chart_earnings([symbol], [], today)[symbol].get("next")
    return options_feed.forecast(symbol, spot, earnings)


@router.get("/symbol/{symbol:path}/analysts")
def analysts(symbol: str):
    """Analyst targets, ratings, estimates and recent actions (T2.3): Webull first, Yahoo for the rest.
    Cached a day per provider; each block says which source it came from."""
    return symbol_info_analysts.symbol_analysts.view(_ticker(symbol))
