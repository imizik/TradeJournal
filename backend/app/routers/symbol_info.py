"""The chart side panel, separate from chart feed and canvas routes."""

from datetime import datetime
import logging
import re

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session

from app.database import get_session
from app.engine.chart_math import ET
from app.engine.chart_calendar import chart_calendar
from app.engine.chart_feed import ChartFeedError, chart_feed
from app.engine import symbol_info_news_feed, symbol_info_tradier
from app.engine.options_feed import options_feed
from app.engine.symbol_info_journal import read_journal
from app.engine.symbol_info_reactions import SOURCE as REACTIONS_SOURCE, calculate as calculate_reactions, summary as reaction_summary

log = logging.getLogger(__name__)
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
    # Refresh the active symbol's earnings calendar independently of option and daily history reads.
    events = symbol_info_tradier.symbol_events.forecast_earnings(symbol, today)
    earnings = events.get("next")
    return options_feed.forecast(symbol, spot, earnings)


@router.get("/symbol/{symbol:path}/reactions")
def reactions(symbol: str):
    """T2.2 inferred earnings reactions. Separate from the forecast so a slow daily-history read
    never delays the implied move; the daily series and calendar are cached per day."""
    symbol = _ticker(symbol)
    today = datetime.now(ET).date()
    events = symbol_info_tradier.symbol_events.forecast_earnings(symbol, today)
    out = {"state": "unavailable", "message": None, "source": REACTIONS_SOURCE, "fetched_at": None,
           "stale": False, "price_basis": "split_adjusted", "adjustment": {}, "rows": [],
           "usable_count": 0, "average_abs_pct": None, "report_range": None,
           "earnings_fetched_at": events.get("fetched_at"), "earnings_stale": bool(events.get("message")),
           "earnings_message": events.get("message")}
    if events["state"] in ("loading", "unavailable"):
        out.update(state=events["state"], message=events.get("message") or "Earnings history is loading.")
    elif not events["reports"]:
        out.update(state="none", message="No confirmed past earnings reports are listed.", fetched_at=events.get("fetched_at"))
    else:
        info = chart_feed.splits.get(symbol) if chart_feed.splits else None
        if not info or info.get("status") == "unknown":
            out["message"] = (info or {}).get("issue") or "Split adjustment data is unavailable."
        else:
            try:
                entry = chart_feed.daily.entry(symbol, today, info)
                rows = calculate_reactions(events["reports"], entry.bars, chart_calendar, datetime.now(ET), entry.conflicts)
                summary = reaction_summary(rows)
                warnings = []
                if info.get("status") == "stale":
                    warnings.append("Split adjustment data is stale.")
                if events.get("message"):
                    warnings.append(f"Earnings calendar refresh failed: {events['message']}")
                if "unverified" in entry.states.values():
                    for row in rows:
                        row.update(state="unavailable", reason="A stock split could not be verified for this history.",
                                   reaction_date=None, gap_pct=None, reaction_pct=None)
                    summary = reaction_summary(rows)
                    warnings.append("A stock split could not be verified for this history.")
                out.update(state="ready", message=" ".join(warnings) or None, fetched_at=entry.fetched_at,
                           stale=info.get("status") == "stale", adjustment={"status": info.get("status"), "as_of": info.get("as_of"),
                           "issue": info.get("issue"), "daily": entry.states}, rows=rows, **summary)
            except ChartFeedError as exc:
                out["message"] = str(exc)
            except Exception:  # the section degrades on its own
                log.exception("Earnings reactions failed for %s", symbol)
                out["message"] = "Earnings reactions could not be calculated."
    return out
