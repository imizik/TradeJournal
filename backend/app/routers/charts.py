"""Private chart data, journal execution markers and the saved chart workspace."""

from bisect import bisect_right
import asyncio
from datetime import UTC, datetime
import json
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.database import get_session
from app.engine.chart_calendar import chart_calendar
from app.engine.chart_feed import ChartFeedError, chart_feed
from app.engine.chart_history import HistoryError, chart_history
from app.engine import tradier
from app.engine.chart_math import ET, INTERVALS
from app.models import ChartSettingsRecord, Fill

router = APIRouter()
SYMBOL = re.compile(r"^[A-Z][A-Z0-9./-]{0,14}$")
SETTINGS = "default"
# The main symbol plus two held by panels: each costs its own chart-feed reads.
MAX_SYMBOLS = 3
# Thirty levels on each of hundreds of symbols fit; a runaway client does not.
SETTINGS_BYTES = 512_000


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
async def stream(request: Request, symbol: str = Query("", max_length=15), symbols: str = Query("", max_length=60)):
    """Relay one private market stream to each visible chart tab as SSE, for
    the tab's main symbol plus any symbols its panels hold (three at most)."""
    wanted = list(dict.fromkeys(s.strip().upper() for s in f"{symbol},{symbols}".split(",") if s.strip()))
    if not wanted or len(wanted) > MAX_SYMBOLS or any(not SYMBOL.fullmatch(s) for s in wanted):
        raise HTTPException(422, f"Stream one to {MAX_SYMBOLS} US stock or ETF tickers.")
    if not tradier.tradier_configured():
        raise HTTPException(503, "Tradier market streaming is not configured.")
    market = request.app.state.chart_market_stream

    async def events():
        client_id, queue = market.subscribe(wanted)
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
    extras: str = Query("", max_length=120),
    db: Session = Depends(get_session),
):
    """The main symbol's panels and quotes, plus panels for up to two symbols
    that panels hold on their own (``extras=SPY:5m.1h,QQQ:15m``)."""
    symbol = symbol.upper().strip()
    symbols = list(dict.fromkeys(s.strip().upper() for s in watchlist.split(",") if s.strip()))
    frames = list(dict.fromkeys(s.strip() for s in intervals.split(",") if s.strip()))
    held: dict[str, list[str]] = {}
    for part in filter(None, (p.strip() for p in extras.split(","))):
        name, _, wanted = part.partition(":")
        held[name.strip().upper()] = list(dict.fromkeys(i for i in wanted.split(".") if i))
    if not SYMBOL.fullmatch(symbol) or any(not SYMBOL.fullmatch(s) for s in [*symbols, *held]):
        raise HTTPException(422, "Use a US stock or ETF ticker.")
    if len(symbols) > 30 or not frames or len(frames) > 5 or any(f not in INTERVALS for f in frames):
        raise HTTPException(422, "Choose up to 5 supported intervals and 30 watchlist symbols.")
    if symbol in held or len(held) > MAX_SYMBOLS - 1 or any(not f or len(f) > 5 or any(i not in INTERVALS for i in f) for f in held.values()):
        raise HTTPException(422, f"Panels can hold up to {MAX_SYMBOLS - 1} other symbols, each with up to 5 supported intervals.")
    try:
        data = chart_feed.workspace(symbol, frames, symbols, session, calendar=chart_calendar)
    except ChartFeedError as exc:
        raise HTTPException(503, {"code": exc.code, "message": str(exc)}) from None
    data["extras"] = {}
    for name, wanted in held.items():
        try:
            other = chart_feed.workspace(name, wanted, [], session, calendar=chart_calendar, quotes=False)
            data["extras"][name] = {key: other[key] for key in ("panels", "fetched_at", "intraday_as_of", "issues")}
        except ChartFeedError as exc:
            # A held symbol that cannot load leaves the main charts intact.
            data["extras"][name] = {"panels": {}, "fetched_at": {}, "intraday_as_of": None, "issues": [str(exc)]}

    # Network calls above finish before opening any journal transaction. Select
    # only marker fields: no email bodies, lazy loads, derived P&L or mutations.
    data["fills"], data["fills_truncated"] = _markers(db, symbol, list(data["panels"].values()))
    for name, other in data["extras"].items():
        _markers(db, name, list(other["panels"].values()))
    return data


class ChartSettingsSave(BaseModel):
    base_revision: int = Field(ge=0)
    data: dict[str, Any]


def _settings(row: ChartSettingsRecord | None) -> dict:
    if row is None:
        return {"revision": 0, "data": None, "updated_at": None}
    return {"revision": row.revision, "data": json.loads(row.data_json), "updated_at": row.updated_at.isoformat()}


@router.get("/settings")
def get_settings(db: Session = Depends(get_session)):
    """The shared chart workspace; revision 0 and no data until the first save."""
    return _settings(db.get(ChartSettingsRecord, SETTINGS))


@router.put("/settings")
def save_settings(body: ChartSettingsSave, db: Session = Depends(get_session)):
    """Save only on top of the revision the client last saw; anything else is a 409 carrying the current copy.

    The frontend owns the document's shape and validates it on every read; the
    server stores it whole and guarantees that no save silently replaces one it
    was not based on. The revision check is a single conditional statement, so
    it holds across processes as well.
    """
    text = json.dumps(body.data, separators=(",", ":"))
    if len(text.encode()) > SETTINGS_BYTES:
        raise HTTPException(413, {"code": "too_large", "message": "Chart settings are too large to save."})
    now = datetime.now(UTC).replace(tzinfo=None)
    try:
        if body.base_revision == 0:
            db.add(ChartSettingsRecord(name=SETTINGS, data_json=text, revision=1, updated_at=now))
            db.commit()
            saved = True
        else:
            result = db.execute(update(ChartSettingsRecord).where(
                ChartSettingsRecord.name == SETTINGS, ChartSettingsRecord.revision == body.base_revision,
            ).values(data_json=text, revision=ChartSettingsRecord.revision + 1, updated_at=now))
            db.commit()
            saved = result.rowcount == 1
    except IntegrityError:
        db.rollback()  # another save created the row first
        saved = False
    if saved:
        # Exactly what this request wrote. Rereading the row could return a save
        # another device made after this commit, and this client would then take
        # that revision as the base for its own copy.
        return {"revision": body.base_revision + 1, "data": body.data, "updated_at": now.isoformat()}
    db.expire_all()
    raise HTTPException(409, {"code": "revision_conflict", "message": "These chart settings changed on another device.",
                              "current": _settings(db.get(ChartSettingsRecord, SETTINGS))})
