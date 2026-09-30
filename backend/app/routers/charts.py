"""Private, read-only chart data and journal execution markers."""

from bisect import bisect_right
import asyncio
from datetime import datetime
import json
import re

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlmodel import Session, select

from app.database import get_session
from app.engine.chart_feed import ChartFeedError, chart_feed
from app.engine.chart_history import HistoryError, chart_history
from app.engine import tradier
from app.engine.chart_math import ET, INTERVALS
from app.models import Fill

router = APIRouter()
SYMBOL = re.compile(r"^[A-Z][A-Z0-9./-]{0,14}$")


def _markers(db: Session, symbol: str, panels: list[dict]) -> tuple[list[dict], bool]:
    panel_bars = [p["bars"] for p in panels if p["bars"]]
    if not panel_bars:
        return [], False
    start = min(b[0]["time"] for b in panel_bars)
    end = max(b[-1]["end_time"] for b in panel_bars)
    query = select(Fill.id, Fill.executed_at, Fill.side, Fill.instrument_type, Fill.option_type, Fill.contracts).where(
        Fill.ticker == symbol,
        Fill.executed_at >= datetime.fromtimestamp(start, ET).replace(tzinfo=None),
        Fill.executed_at < datetime.fromtimestamp(end, ET).replace(tzinfo=None),
    ).order_by(Fill.executed_at.desc(), Fill.id.desc()).limit(1001)
    rows = db.exec(query).all()
    fills = []
    for row in reversed(rows[:1000]):
        stamp = int(row.executed_at.replace(tzinfo=ET).timestamp())
        option = f" {row.option_type or 'option'}" if row.instrument_type == "option" else " stock"
        label = f"{row.side.replace('_', ' ')} {float(row.contracts):g}{option}"
        fills.append({"id": str(row.id), "time": stamp, "label": label, "buy": row.side.startswith("buy")})
    for panel in panels:
        times = [b["time"] for b in panel["bars"]]
        for fill in fills:
            index = bisect_right(times, fill["time"]) - 1
            if index >= 0 and fill["time"] < panel["bars"][index]["end_time"]:
                panel["markers"].append({**fill, "time": times[index]})
    return fills, len(rows) > 1000


@router.get("/history")
def history(
    symbol: str = Query(..., max_length=15),
    interval: str = Query(...),
    session: str = Query(..., pattern="^(regular|extended)$"),
    before: int = Query(..., gt=0),
    limit: int = Query(1200, ge=1, le=1200),
    continuation: str | None = Query(None, max_length=64),
    db: Session = Depends(get_session),
):
    symbol = symbol.upper().strip()
    if not SYMBOL.fullmatch(symbol):
        raise HTTPException(422, "Use a US stock or ETF ticker.")
    try:
        data = chart_history.page(symbol, interval, session, before, limit, continuation)
    except HistoryError as exc:
        status = 422 if exc.code == "invalid_request" else 503
        raise HTTPException(status, {"code": exc.code, "message": str(exc), "retry_at": exc.retry_at}) from None
    data["markers"] = []
    fills, truncated = _markers(db, symbol, [data])
    data["fills_truncated"] = truncated
    return data


@router.get("/stream")
async def stream(symbol: str, request: Request):
    """Relay one private market stream to each visible chart tab as SSE."""
    symbol = symbol.upper().strip()
    if not SYMBOL.fullmatch(symbol):
        raise HTTPException(422, "Use a US stock or ETF ticker.")
    if not tradier.tradier_configured():
        raise HTTPException(503, "Tradier market streaming is not configured.")
    market = request.app.state.chart_market_stream

    async def events():
        client_id, queue = market.subscribe(symbol)
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                yield f"event: {event['type']}\ndata: {json.dumps(event, separators=(',', ':'))}\n\n"
        finally:
            market.unsubscribe(client_id)

    return StreamingResponse(events(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no",
    })


@router.get("/workspace")
def workspace(
    symbol: str = Query("SPY", max_length=15),
    intervals: str = Query("5m,15m,1h,1D,1m", max_length=80),
    watchlist: str = Query("SPY,QQQ,MRVL,NVDA,AMD,META", max_length=500),
    session: str = Query("extended", pattern="^(regular|extended)$"),
    db: Session = Depends(get_session),
):
    symbol = symbol.upper().strip()
    symbols = list(dict.fromkeys(s.strip().upper() for s in watchlist.split(",") if s.strip()))
    frames = list(dict.fromkeys(s.strip() for s in intervals.split(",") if s.strip()))
    if not SYMBOL.fullmatch(symbol) or any(not SYMBOL.fullmatch(s) for s in symbols):
        raise HTTPException(422, "Use a US stock or ETF ticker.")
    if len(symbols) > 30 or not frames or len(frames) > 5 or any(f not in INTERVALS for f in frames):
        raise HTTPException(422, "Choose up to 5 supported intervals and 30 watchlist symbols.")
    try:
        data = chart_feed.workspace(symbol, frames, symbols, session)
    except ChartFeedError as exc:
        raise HTTPException(503, {"code": exc.code, "message": str(exc)}) from None

    # Network calls above finish before opening any journal transaction. Select
    # only marker fields: no email bodies, lazy loads, derived P&L or mutations.
    data["fills"], data["fills_truncated"] = _markers(db, symbol, list(data["panels"].values()))
    return data
