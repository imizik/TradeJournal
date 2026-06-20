"""
Market context router — Alpaca enrichment endpoints.

POST /market-context/enrich          start background Alpaca enrichment
GET  /market-context/enrich/status   progress of current job
GET  /market-context/fill/{fill_id}  FillMarketContext for one fill
GET  /market-context/fills/bulk      FillMarketContext for multiple fills
GET  /market-context/trade/{trade_id} TradePathMetrics for one trade
"""

import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.database import get_session
from app.engine.jobs import (
    JOB_ALPACA_ENRICH,
    JOB_TRADE_PATH,
    create_alpaca_enrichment_job,
    create_trade_path_job,
    job_status,
    latest_job,
    run_job,
    running_job,
)
from app.models import Fill, FillMarketContext, Trade, TradeFill, TradePathMetrics

router = APIRouter()

def _start_job_thread(job_id: uuid.UUID) -> None:
    import threading

    t = threading.Thread(target=run_job, args=(job_id,), daemon=True)
    t.start()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/enrich/status")
async def enrich_status(session: Session = Depends(get_session)):
    return job_status(latest_job(session, JOB_ALPACA_ENRICH))


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
    if running_job(session, JOB_ALPACA_ENRICH):
        raise HTTPException(status_code=409, detail="Alpaca enrichment already running")

    job = create_alpaca_enrichment_job(session, range_value=range, force=force)
    if not job.total:
        return {"started": False, "total_missing": 0}

    _start_job_thread(job.id)
    return {"started": True, "total_missing": job.total, "job_id": str(job.id)}


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


@router.get("/trade-path/bulk", response_model=dict[str, TradePathMetrics])
async def get_bulk_trade_paths(ids: str, session: Session = Depends(get_session)):
    """
    Return TradePathMetrics for multiple trades in one query.
    ids: comma-separated trade UUIDs.
    Returns {trade_id_str: TradePathMetrics} — trades without metrics are omitted.
    """
    trade_ids = [uuid.UUID(i.strip()) for i in ids.split(",") if i.strip()]
    if not trade_ids:
        return {}
    rows = session.exec(
        select(TradePathMetrics).where(TradePathMetrics.trade_id.in_(trade_ids))
    ).all()
    return {str(row.trade_id): row for row in rows}


@router.get("/trade-path/status")
async def trade_path_status(session: Session = Depends(get_session)):
    return job_status(latest_job(session, JOB_TRADE_PATH))


@router.get("/coverage")
async def get_coverage(session: Session = Depends(get_session)):
    """
    Returns enrichment coverage counts for fills and closed trades.
    Cheap — three COUNT queries.
    """
    from sqlalchemy import func

    total_fills = session.exec(select(func.count(Fill.id))).one()
    poly_enriched = session.exec(
        select(func.count(Fill.id)).where(Fill.underlying_price_at_fill.isnot(None))
    ).one()
    alpaca_enriched = session.exec(
        select(func.count(FillMarketContext.fill_id))
    ).one()
    total_closed = session.exec(
        select(func.count(Trade.id)).where(Trade.status.in_(["closed", "expired"]))
    ).one()
    path_done = session.exec(
        select(func.count(TradePathMetrics.trade_id))
    ).one()

    return {
        "fills": {
            "total": total_fills,
            "polygon_enriched": poly_enriched,
            "polygon_missing": max(0, total_fills - poly_enriched),
            "alpaca_enriched": alpaca_enriched,
            "alpaca_missing": max(0, total_fills - alpaca_enriched),
        },
        "trades": {
            "total_closed": total_closed,
            "path_metrics_done": path_done,
            "path_metrics_missing": max(0, total_closed - path_done),
        },
    }


@router.get("/audit/{trade_id}")
async def get_trade_audit(trade_id: uuid.UUID, session: Session = Depends(get_session)):
    """
    Synchronously re-derives all computed values for a single trade from cached bar data.
    Returns a structured audit report for UI display.
    """
    from app.engine.auditor import compute_audit

    trade = session.get(Trade, trade_id)
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")

    tfs = session.exec(select(TradeFill).where(TradeFill.trade_id == trade.id)).all()
    fill_ids = [tf.fill_id for tf in tfs]
    fills = session.exec(select(Fill).where(Fill.id.in_(fill_ids))).all()

    ctx_rows = session.exec(
        select(FillMarketContext).where(FillMarketContext.fill_id.in_(fill_ids))
    ).all()
    ctx_by_fill = {str(r.fill_id): r for r in ctx_rows}

    path = session.get(TradePathMetrics, trade.id)

    return compute_audit(trade, list(fills), ctx_by_fill, path)


@router.post("/trade-path/compute")
async def compute_trade_paths(
    range: str = "week",
    force: bool = False,
    session: Session = Depends(get_session),
):
    if running_job(session, JOB_TRADE_PATH):
        raise HTTPException(status_code=409, detail="Trade path computation already running")

    job = create_trade_path_job(session, range_value=range, force=force)
    if not job.total:
        return {"started": False, "total_missing": 0}

    _start_job_thread(job.id)
    return {"started": True, "total_missing": job.total, "job_id": str(job.id)}
