from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, Query

from app.engine.alpaca import ET
from app.engine.analyzer import build_ticker_analysis
from app.engine.news import fetch_news
from app.engine.packets import build_market_report
from app.engine.scalper import build_scalp_analysis

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


@router.get("/analyze")
async def analyze(symbol: str = Query(..., description="Any ticker, traded or not")):
    """Live single-ticker analysis packet for any symbol, as of the latest data.

    Returns a short-term (intraday: VWAP, opening range, premarket, day
    structure) and long-term (daily: SMA/EMA/RSI/MACD/ATR, 52-week range,
    trailing returns) block plus recent daily and minute bars. Pure data — the
    caller forms the view. Independent of the journal; works on untraded tickers.
    """
    try:
        return build_ticker_analysis(symbol)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@router.get("/scalp")
async def scalp(
    symbol: str = Query(..., description="Underlying ticker"),
    direction: str | None = Query(None, description="long | short | up | down"),
    instrument: str | None = Query(None, description="stock | option"),
    option_type: str | None = Query(None, description="call | put"),
    expiration: str | None = Query(None, description="Option expiration YYYY-MM-DD"),
    strike: float | None = Query(None, gt=0),
    style: str | None = Query(None, description="open | midday | power_hour"),
):
    """Read-only scalp setup assessment: live data packet + deterministic scoring.

    Never places trades and never gives blind advice — returns verdict /
    confidence / bias, setup/liquidity/risk scores, trigger, invalidation,
    targets, reasons for/against, and missing-data caveats alongside the raw
    data. Verdict is forced to wait/no_trade when the market is closed or the
    live data is stale. Live minute bars are fetched fresh and never written
    to the persistent enrichment cache.
    """
    try:
        return build_scalp_analysis(
            symbol,
            direction=direction,
            instrument=instrument,
            option_type=option_type,
            expiration=expiration,
            strike=strike,
            style=style,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
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
