"""
Market context router — Alpaca enrichment endpoints.

POST /market-context/enrich          start background Alpaca enrichment
GET  /market-context/enrich/status   progress of current job
GET  /market-context/fill/{fill_id}  FillMarketContext for one fill
GET  /market-context/fills/bulk      FillMarketContext for multiple fills
GET  /market-context/trade/{trade_id} TradePathMetrics for one trade
"""

import threading
import uuid
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.database import get_session, engine
from app.models import Fill, FillMarketContext, Trade, TradePathMetrics

router = APIRouter()

# ---------------------------------------------------------------------------
# Background enrichment state (separate from Polygon enrichment in fills.py)
# ---------------------------------------------------------------------------

_state: dict = {
    "running": False,
    "done": 0,
    "total": 0,
    "current": "",
    "enriched": 0,
    "error": None,
}
_lock = threading.Lock()

_path_state: dict = {
    "running": False,
    "done": 0,
    "total": 0,
    "current": "",
    "enriched": 0,
    "error": None,
}
_path_lock = threading.Lock()


def _run_background(fill_ids: list, force: bool = False) -> None:
    from app.engine.alpaca_enricher import enrich_fills_alpaca

    with _lock:
        _state["running"] = True
        _state["done"] = 0
        _state["total"] = len(fill_ids)
        _state["current"] = ""
        _state["enriched"] = 0
        _state["error"] = None

    def on_progress(done: int, label: str) -> None:
        with _lock:
            _state["done"] = done
            _state["current"] = label

    try:
        with Session(engine) as session:
            fills = session.exec(select(Fill).where(Fill.id.in_(fill_ids))).all()
            enriched = enrich_fills_alpaca(list(fills), session, on_progress=on_progress, force=force)
            with _lock:
                _state["enriched"] = enriched
    except Exception as exc:
        import logging
        logging.getLogger(__name__).exception("Background Alpaca enrichment failed")
        with _lock:
            _state["error"] = str(exc)
    finally:
        with _lock:
            _state["running"] = False


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/enrich/status")
async def enrich_status():
    with _lock:
        return dict(_state)


@router.post("/enrich")
async def enrich_missing(
    range: str = "week",
    force: bool = False,
    session: Session = Depends(get_session),
):
    """
    Start Alpaca enrichment for fills missing market context.
    range: day | week | month | all
    force: re-enrich fills that already have a context row
    """
    with _lock:
        if _state["running"]:
            raise HTTPException(status_code=409, detail="Alpaca enrichment already running")

    cutoff: datetime | None = None
    if range == "day":
        cutoff = datetime.utcnow() - timedelta(days=1)
    elif range == "week":
        cutoff = datetime.utcnow() - timedelta(weeks=1)
    elif range == "month":
        cutoff = datetime.utcnow() - timedelta(days=30)

    # When not forcing, only queue fills without existing context
    if not force:
        existing_fill_ids = set(session.exec(select(FillMarketContext.fill_id)).all())
        query = select(Fill.id).where(Fill.id.notin_(existing_fill_ids))
    else:
        query = select(Fill.id)

    if cutoff is not None:
        query = query.where(Fill.executed_at >= cutoff)

    fill_ids = session.exec(query).all()
    if not fill_ids:
        return {"started": False, "total_missing": 0}

    t = threading.Thread(target=_run_background, args=(fill_ids, force), daemon=True)
    t.start()
    return {"started": True, "total_missing": len(fill_ids)}


@router.get("/fill/{fill_id}", response_model=FillMarketContext)
async def get_fill_context(fill_id: uuid.UUID, session: Session = Depends(get_session)):
    ctx = session.get(FillMarketContext, fill_id)
    if not ctx:
        raise HTTPException(status_code=404, detail="No Alpaca context for this fill")
    return ctx


@router.get("/fills/bulk", response_model=dict[str, FillMarketContext])
async def get_bulk_fill_contexts(ids: str, session: Session = Depends(get_session)):
    """
    Return FillMarketContext for multiple fills.
    ids: comma-separated fill UUIDs.
    Returns {fill_id_str: FillMarketContext} — missing fills are omitted.
    """
    fill_ids = [uuid.UUID(i.strip()) for i in ids.split(",") if i.strip()]
    if not fill_ids:
        return {}
    rows = session.exec(
        select(FillMarketContext).where(FillMarketContext.fill_id.in_(fill_ids))
    ).all()
    return {str(row.fill_id): row for row in rows}


@router.get("/trade/{trade_id}", response_model=TradePathMetrics)
async def get_trade_path(trade_id: uuid.UUID, session: Session = Depends(get_session)):
    metrics = session.get(TradePathMetrics, trade_id)
    if not metrics:
        raise HTTPException(status_code=404, detail="No path metrics for this trade")
    return metrics


# ---------------------------------------------------------------------------
# Trade path metrics background job
# ---------------------------------------------------------------------------

def _run_path_background(trade_ids: list, force: bool = False) -> None:
    from app.engine.trade_path import compute_path_metrics_for_trades

    with _path_lock:
        _path_state["running"] = True
        _path_state["done"] = 0
        _path_state["total"] = len(trade_ids)
        _path_state["current"] = ""
        _path_state["enriched"] = 0
        _path_state["error"] = None

    def on_progress(done: int, label: str) -> None:
        with _path_lock:
            _path_state["done"] = done
            _path_state["current"] = label

    try:
        with Session(engine) as session:
            trades = session.exec(select(Trade).where(Trade.id.in_(trade_ids))).all()
            enriched = compute_path_metrics_for_trades(list(trades), session, on_progress=on_progress, force=force)
            with _path_lock:
                _path_state["enriched"] = enriched
    except Exception as exc:
        import logging
        logging.getLogger(__name__).exception("Background trade path computation failed")
        with _path_lock:
            _path_state["error"] = str(exc)
    finally:
        with _path_lock:
            _path_state["running"] = False


@router.get("/trade-path/status")
async def trade_path_status():
    with _path_lock:
        return dict(_path_state)


@router.post("/trade-path/compute")
async def compute_trade_paths(
    range: str = "week",
    force: bool = False,
    session: Session = Depends(get_session),
):
    with _path_lock:
        if _path_state["running"]:
            raise HTTPException(status_code=409, detail="Trade path computation already running")

    cutoff: datetime | None = None
    if range == "day":
        cutoff = datetime.utcnow() - timedelta(days=1)
    elif range == "week":
        cutoff = datetime.utcnow() - timedelta(weeks=1)
    elif range == "month":
        cutoff = datetime.utcnow() - timedelta(days=30)

    query = select(Trade.id).where(Trade.status.in_(["closed", "expired"]))
    if cutoff:
        query = query.where(Trade.opened_at >= cutoff)
    if not force:
        existing = set(session.exec(select(TradePathMetrics.trade_id)).all())
        query = query.where(Trade.id.notin_(existing))

    trade_ids = session.exec(query).all()
    if not trade_ids:
        return {"started": False, "total_missing": 0}

    t = threading.Thread(target=_run_path_background, args=(trade_ids, force), daemon=True)
    t.start()
    return {"started": True, "total_missing": len(trade_ids)}
