"""Private, read-only chart data and journal execution markers."""

from bisect import bisect_right
from datetime import datetime
import re

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from app.database import get_session
from app.engine.chart_feed import ChartFeedError, chart_feed
from app.engine.chart_math import ET, INTERVALS
from app.models import Fill

router = APIRouter()
SYMBOL = re.compile(r"^[A-Z][A-Z0-9./-]{0,14}$")


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
    panel_bars = [p["bars"] for p in data["panels"].values() if p["bars"]]
    data["fills"] = []
    data["fills_truncated"] = False
    if panel_bars:
        start = min(b[0]["time"] for b in panel_bars)
        end = max(b[-1]["end_time"] for b in panel_bars)
        query = select(Fill.id, Fill.executed_at, Fill.side, Fill.instrument_type, Fill.option_type, Fill.contracts).where(
            Fill.ticker == symbol,
            Fill.executed_at >= datetime.fromtimestamp(start, ET).replace(tzinfo=None),
            Fill.executed_at < datetime.fromtimestamp(end, ET).replace(tzinfo=None),
        ).order_by(Fill.executed_at.desc(), Fill.id.desc()).limit(1001)
        rows = db.exec(query).all()
        data["fills_truncated"] = len(rows) > 1000
        for row in reversed(rows[:1000]):
            stamp = int(row.executed_at.replace(tzinfo=ET).timestamp())
            option = f" {row.option_type or 'option'}" if row.instrument_type == "option" else " stock"
            label = f"{row.side.replace('_', ' ')} {float(row.contracts):g}{option}"
            data["fills"].append({"id": str(row.id), "time": stamp, "label": label, "buy": row.side.startswith("buy")})
        for panel in data["panels"].values():
            times = [b["time"] for b in panel["bars"]]
            for fill in data["fills"]:
                index = bisect_right(times, fill["time"]) - 1
                if index >= 0 and fill["time"] < panel["bars"][index]["end_time"]:
                    panel["markers"].append({**fill, "time": times[index]})
    return data
