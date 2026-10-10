"""Private chart data, journal execution markers and the saved chart workspace."""

from bisect import bisect_right
import asyncio
from datetime import UTC, datetime
import json
import re
import time
from typing import Any
import uuid

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
from app.engine import symbol_info_tradier
from app.engine import chart_journal, access
from app.engine.quotes import OptionQuoteRequest, option_mark
from app.engine.options_feed import Layer, options_feed
from app.engine.options_history import attach_open_interest_changes
from app.engine.options_positioning import SCOPES
from app.routers.level_alerts import listing as alert_listing
from app.models import FILL_LIGHT, ChartSettingsRecord, Fill, Trade

router = APIRouter()
SYMBOL = re.compile(r"^[A-Z][A-Z0-9./-]{0,14}$")
SETTINGS = "default"
# The main symbol plus two held by panels: each costs its own chart-feed reads.
MAX_SYMBOLS = 3
# The chart symbols plus the saved watchlist share the same market stream.
MAX_STREAM_SYMBOLS = 33
# Thirty levels on each of hundreds of symbols fit; a runaway client does not.
SETTINGS_BYTES = 512_000
STREAM_AUTH_INTERVAL = 15


def stream_clock():
    return time.monotonic()


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
    request: Request,
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
    if interval in ("1D", "1W"):
        # Daily and weekly bars are Tradier's regular session; `session` and `continuation` do not apply.
        try:
            data = chart_feed.daily.page(symbol, interval, before, limit)
        except ChartFeedError as exc:
            retry = int(time.time() + (60 if exc.code == "rate_limited" else 15))
            raise HTTPException(503, {"code": exc.code, "message": str(exc), "retry_at": retry}) from None
        data["session"] = session
        data["markers"] = []
        data["fills_truncated"] = _markers(db, symbol, [data])[1] if access.is_journal(request) else False
        return data
    try:
        data = chart_history.page(symbol, interval, session, before, limit, continuation)
    except HistoryError as exc:
        status = 422 if exc.code == "invalid_request" else 503
        raise HTTPException(status, {"code": exc.code, "message": str(exc), "retry_at": exc.retry_at}) from None
    data["markers"] = []
    fills, truncated = _markers(db, symbol, [data]) if access.is_journal(request) else ([], False)
    data["fills_truncated"] = truncated
    return data


@router.get("/stream")
async def stream(request: Request, symbol: str = Query("", max_length=15), symbols: str = Query("", max_length=600)):
    """Relay one private market stream to each visible chart tab as SSE, for
    up to three chart symbols and its 30-symbol watchlist."""
    wanted = list(dict.fromkeys(s.strip().upper() for s in f"{symbol},{symbols}".split(",") if s.strip()))
    if not wanted or len(wanted) > MAX_STREAM_SYMBOLS or any(not SYMBOL.fullmatch(s) for s in wanted):
        raise HTTPException(422, f"Stream one to {MAX_STREAM_SYMBOLS} US stock or ETF tickers.")
    if not tradier.tradier_configured():
        raise HTTPException(503, "Tradier market streaming is not configured.")
    market = request.app.state.chart_market_stream

    async def events():
        client_id, queue = market.subscribe(wanted)
        try:
            next_check = stream_clock()
            while True:
                if access.enabled() and stream_clock() >= next_check:
                    from starlette.concurrency import run_in_threadpool
                    if not await run_in_threadpool(access.still_authorized, request):
                        break
                    next_check = stream_clock() + STREAM_AUTH_INTERVAL
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
    request: Request,
    symbol: str = Query("SPY", max_length=15),
    intervals: str = Query("5m,15m,1h,1D,1m", max_length=80),
    watchlist: str = Query("SPY,QQQ,MRVL,NVDA,AMD,META", max_length=500),
    session: str = Query("extended", pattern="^(regular|extended)$"),
    extras: str = Query("", max_length=120),
    options: str = Query("", max_length=20),
    ranges: bool = Query(False),
    auto: bool = Query(True),
    db: Session = Depends(get_session),
):
    """The main symbol's panels and quotes, plus panels for up to two symbols
    that panels hold on their own (``extras=SPY:5m.1h,QQQ:15m``).

    ``options=oi.week.0`` (measure, scope, signed) adds the options levels layer
    (C4.4) to the automatic levels, from the option chain cache only: the main
    symbol in that scope, a held symbol at its nearest expiration. ``ranges=1``
    adds the expected-move range bands (C2.7) for every symbol shown. With either,
    ``auto=0`` leaves the automatic levels out of the zones."""
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
        layer = Layer.parse(options) if options else None
    except ValueError:
        raise HTTPException(422, "Options levels take a measure (oi, volume or gamma), a scope (nearest, week or all) and 0 or 1.") from None

    def levels_for(scope: str | None):
        found = {}
        if layer is not None:
            held_layer = Layer(layer.measure, scope or layer.scope, layer.signed)
            found["extra_levels"] = lambda name, spot: options_feed.chart(name, held_layer, spot)
        if ranges:
            found["range_levels"] = options_feed.ranges
        return {**found, "auto": auto} if found else {}

    def add_open_interest_changes(levels: dict | None, name: str) -> None:
        options_data = levels.get("options") if isinstance(levels, dict) else None
        if isinstance(options_data, dict):
            attach_open_interest_changes(db, name, options_data.get("root", ""),
                                         options_data.get("strikes", []), options_data.get("expirations", []))

    try:
        data = chart_feed.workspace(symbol, frames, symbols, session, calendar=chart_calendar, stored_session=chart_history.stored,
                                    volume_profile=chart_history.volume_profile, **levels_for(None))
    except ChartFeedError as exc:
        raise HTTPException(503, {"code": exc.code, "message": str(exc)}) from None
    add_open_interest_changes(data.get("auto_levels"), symbol)
    data["extras"] = {}
    for name, wanted in held.items():
        try:
            other = chart_feed.workspace(name, wanted, [], session, calendar=chart_calendar, quotes=False, stored_session=chart_history.stored,
                                         volume_profile=chart_history.volume_profile, **levels_for("nearest"))
            data["extras"][name] = {**{key: other[key] for key in ("panels", "fetched_at", "intraday_as_of", "issues", "adjustment")},
                                     "auto_levels": other.get("auto_levels"), "rvol": other.get("rvol")}
            add_open_interest_changes(data["extras"][name].get("auto_levels"), name)
        except ChartFeedError as exc:
            # A held symbol that cannot load leaves the main charts intact.
            data["extras"][name] = {"panels": {}, "fetched_at": {}, "intraday_as_of": None, "issues": [str(exc)], "adjustment": None, "auto_levels": None, "rvol": None}

    # Earnings (C2.5) come from the cache only; stale symbols refresh in the background.
    earnings = symbol_info_tradier.symbol_events.chart_earnings([symbol, *held], symbols, datetime.now(ET).date())
    data["earnings"] = earnings[symbol]
    for name, other in data["extras"].items():
        other["earnings"] = earnings[name]

    if not access.is_journal(request):
        data["fills"], data["fills_truncated"], data["positions"], data["alerts"] = [], False, [], []
        data["journal_access"] = "restricted"
        for other in data["extras"].values():
            other["fills_truncated"], other["positions"] = False, []
        return data

    # Network calls above finish before opening any journal transaction. Select
    # only marker fields: no email bodies, lazy loads, derived P&L or mutations.
    data["fills"], data["fills_truncated"] = _markers(db, symbol, list(data["panels"].values()))
    for name, other in data["extras"].items():
        _, other["fills_truncated"] = _markers(db, name, list(other["panels"].values()))
    # Open positions on each symbol shown (C3.2): three queries a symbol, no provider.
    data["positions"] = chart_journal.positions(db, symbol)
    for name, other in data["extras"].items():
        other["positions"] = chart_journal.positions(db, name)
    # Every level alert (C5.1), whichever symbols are on screen: the chart draws its own, the list shows all.
    data["alerts"] = alert_listing(db)
    return data


@router.get("/journal/fills/{fill_id}")
def journal_fill(fill_id: uuid.UUID, db: Session = Depends(get_session)):
    """A fill arrow's card (C3.1): the fill, and the trade it belongs to."""
    fill = db.exec(select(Fill).options(*FILL_LIGHT).where(Fill.id == fill_id)).first()
    if fill is None:
        raise HTTPException(404, "That fill is no longer in the journal.")
    return chart_journal.fill_card(db, fill)


@router.get("/journal/trades/{trade_id}")
def journal_trade(trade_id: uuid.UUID, db: Session = Depends(get_session)):
    """One trade's card, for a link that names the trade rather than a fill."""
    trade = db.get(Trade, trade_id)
    if trade is None:
        raise HTTPException(404, "That trade is no longer in the journal. Trades are rebuilt from fills; open it from its fill instead.")
    return {"fill": None, **chart_journal.trade_card(db, trade)}


@router.get("/journal/trades/{trade_id}/mark")
def journal_mark(trade_id: uuid.UUID, db: Session = Depends(get_session)):
    """An open option trade's current premium and open P&L, asked for from its
    card. One quote through the dashboard's 60-second cache; the answer says
    when it was quoted, so an old mark is shown as old."""
    trade = db.get(Trade, trade_id)
    if trade is None or trade.instrument_type != "option" or trade.status != "open" or trade.expiration is None:
        raise HTTPException(422, "Only an open option trade has a mark to read.")
    card = chart_journal.trade_card(db, trade)
    position = card["position"]
    db.close()  # the quote is a network call; no journal transaction stays open across it
    quote, quoted_at = option_mark(OptionQuoteRequest(trade.ticker, trade.expiration.isoformat(), float(trade.strike), trade.option_type or ""))
    # Quotes are per share; journal option prices are per contract (x100).
    mark, basis = (quote.mid, "mid") if quote.mid is not None else (quote.last_price, "last") if quote.last_price is not None else (None, None)
    open_pnl = None
    if mark is not None and position and position["avg_cost"] is not None:
        sign = -1 if card["trade"]["direction"] == "short" else 1
        open_pnl = round((mark * 100 - position["avg_cost"]) * position["open"] * sign, 2)
    return {"mark": mark, "mark_per_contract": None if mark is None else round(mark * 100, 2), "basis": basis,
            "bid": quote.bid, "ask": quote.ask, "last": quote.last_price,
            "provider": quote.provider, "quoted_at": int(quoted_at) if quoted_at else None, "open_pnl": open_pnl}


@router.get("/options/{symbol:path}/ladder")
def options_ladder(symbol: str, scope: str = Query("week", max_length=10), signed: bool = Query(False),
                   spot: float | None = Query(None, gt=0), db: Session = Depends(get_session)):
    """The strike ladder (C4.5): open interest, volume and gamma by strike around ``spot``
    (the chart's latest price), over the scope's expirations. Reads stale chains first."""
    symbol = symbol.upper().strip()
    if not SYMBOL.fullmatch(symbol) or scope not in SCOPES:
        raise HTTPException(422, "Use a US stock or ETF ticker and a scope of nearest, week or all.")
    result = options_feed.ladder(symbol, scope, signed, spot)
    attach_open_interest_changes(db, symbol, result.get("root", ""), result.get("rows", []), result.get("expirations", []))
    return result


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
    server stores it and guarantees that no save silently replaces one it was
    not based on. The revision check is a single conditional statement, so it
    holds across processes as well.

    A save never drops a top-level field it leaves out: the stored copy keeps
    it. A browser tab still running an older build does not know fields a newer
    build added (C1.2's drawings), and must not erase them when it saves its
    watchlist. Clearing a field means saving it empty.
    """
    data = body.data
    row = db.get(ChartSettingsRecord, SETTINGS) if body.base_revision else None
    # Only the copy this save replaces lends fields; on any other revision the update below is refused anyway.
    if row is not None and row.revision == body.base_revision:
        stored = json.loads(row.data_json)
        if isinstance(stored, dict):
            data = {**data, **{key: value for key, value in stored.items() if key not in data}}
    text = json.dumps(data, separators=(",", ":"))
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
        return {"revision": body.base_revision + 1, "data": data, "updated_at": now.isoformat()}
    db.expire_all()
    raise HTTPException(409, {"code": "revision_conflict", "message": "These chart settings changed on another device.",
                              "current": _settings(db.get(ChartSettingsRecord, SETTINGS))})
