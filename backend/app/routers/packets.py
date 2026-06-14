from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, Query

from app.engine.alpaca import ET
from app.engine.news import fetch_news
from app.engine.packets import build_market_report

router = APIRouter()


@router.get("/report")
async def market_report(type: str = Query(..., pattern="^(premarket|postmarket)$")):
    """Build the deterministic market report consumed by Claude via MCP.

    Takes a few seconds (Alpaca snapshots + minute bars + news, rate-limited).
    """
    try:
        return build_market_report(type)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@router.get("/news")
async def news(
    symbols: str | None = Query(None, description="Comma-separated tickers; omit for broad tape"),
    hours: int = Query(24, ge=1, le=168),
    limit: int = Query(30, ge=1, le=100),
    include_content: bool = Query(False, description="Include full article text (capped); keep limit small"),
):
    """Raw headlines (Alpaca/Benzinga) for ad-hoc drill-down from chat."""
    symbol_list = [s.strip().upper() for s in symbols.split(",") if s.strip()] if symbols else None
    if include_content:
        limit = min(limit, 10)  # full text is heavy; force a tight page
    start = datetime.now(ET) - timedelta(hours=hours)
    return {
        "window_start": start.isoformat(),
        "articles": fetch_news(symbols=symbol_list, start=start, limit=limit, include_content=include_content),
    }
