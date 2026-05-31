import json
import logging
import time
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.exc import OperationalError
from sqlmodel import Session, select

from app.database import engine
from app.models import Fill, FillMarketContext, JobRun, Trade, TradePathMetrics

log = logging.getLogger(__name__)

JOB_POLYGON_ENRICH = "polygon_enrich"
JOB_ALPACA_ENRICH = "alpaca_enrich"
JOB_TRADE_PATH = "trade_path"
JOB_WEBULL_LISTENER = "webull_listener"


def create_job(session: Session, job_type: str, params: dict[str, Any] | None = None, total: int = 0) -> JobRun:
    now = datetime.utcnow()
    job = JobRun(
        id=uuid.uuid4(),
        job_type=job_type,
        status="queued" if total else "succeeded",
        params_json=json.dumps(params or {}),
        total=total,
        finished_at=now if not total else None,
        updated_at=now,
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def latest_job(session: Session, job_type: str) -> JobRun | None:
    return session.exec(
        select(JobRun)
        .where(JobRun.job_type == job_type)
        .order_by(JobRun.created_at.desc())
    ).first()


def job_status(job: JobRun | None) -> dict[str, Any]:
    if job is None:
        return {
            "running": False,
            "done": 0,
            "total": 0,
            "current": "",
            "enriched": 0,
            "error": None,
            "job_id": None,
            "status": None,
        }
    return {
        "running": job.status in {"queued", "running"},
        "done": job.done,
        "total": job.total,
        "current": job.current or "",
        "enriched": job.enriched,
        "error": job.error,
        "job_id": str(job.id),
        "status": job.status,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
    }


def running_job(session: Session, job_type: str) -> JobRun | None:
    return session.exec(
        select(JobRun)
        .where(JobRun.job_type == job_type)
        .where(JobRun.status.in_(["queued", "running"]))
        .order_by(JobRun.created_at.desc())
    ).first()


def _params(job: JobRun) -> dict[str, Any]:
    try:
        return json.loads(job.params_json or "{}")
    except json.JSONDecodeError:
        return {}


def _cutoff(range_value: str | None) -> datetime | None:
    if range_value == "day":
        return datetime.utcnow() - timedelta(days=1)
    if range_value == "week":
        return datetime.utcnow() - timedelta(weeks=1)
    if range_value == "month":
        return datetime.utcnow() - timedelta(days=30)
    return None


def _is_sqlite_locked(exc: OperationalError) -> bool:
    return "database is locked" in str(exc).lower()


def _set_job(job_id: uuid.UUID, *, ignore_locked: bool = False, attempts: int = 5, **values: Any) -> None:
    for attempt in range(attempts):
        try:
            with Session(engine) as session:
                job = session.get(JobRun, job_id)
                if not job:
                    return
                for key, value in values.items():
                    setattr(job, key, value)
                job.updated_at = datetime.utcnow()
                session.add(job)
                session.commit()
            return
        except OperationalError as exc:
            if not _is_sqlite_locked(exc):
                raise
            if ignore_locked:
                log.debug("Skipped locked job progress update for %s", job_id)
                return
            if attempt == attempts - 1:
                raise
            time.sleep(0.25 * (attempt + 1))


def _start_job(job_id: uuid.UUID) -> JobRun:
    with Session(engine) as session:
        job = session.get(JobRun, job_id)
        if not job:
            raise ValueError(f"Job not found: {job_id}")
        job.status = "running"
        job.error = None
        job.started_at = datetime.utcnow()
        job.updated_at = datetime.utcnow()
        session.add(job)
        session.commit()
        session.refresh(job)
        return job


def _finish_job(job_id: uuid.UUID, enriched: int, total: int) -> None:
    _set_job(
        job_id,
        status="succeeded",
        done=total,
        current=None,
        enriched=enriched,
        finished_at=datetime.utcnow(),
    )


def _fail_job(job_id: uuid.UUID, exc: Exception) -> None:
    log.exception("Job %s failed", job_id)
    _set_job(
        job_id,
        status="failed",
        error=str(exc),
        finished_at=datetime.utcnow(),
    )


def _polygon_fill_ids(session: Session, range_value: str, force: bool) -> list[uuid.UUID]:
    query = select(Fill.id)
    if not force:
        query = query.where(Fill.underlying_price_at_fill == None)  # noqa: E711
    cutoff = _cutoff(range_value)
    if cutoff is not None:
        query = query.where(Fill.executed_at >= cutoff)
    return list(session.exec(query).all())


def _alpaca_fill_ids(session: Session, range_value: str, force: bool) -> list[uuid.UUID]:
    query = select(Fill.id)
    if not force:
        complete_context_fill_ids = set(
            session.exec(
                select(FillMarketContext.fill_id)
                .where(FillMarketContext.entry_rsi_14 != None)  # noqa: E711
                .where(FillMarketContext.entry_ema_9 != None)  # noqa: E711
                .where(FillMarketContext.entry_ema_20 != None)  # noqa: E711
            ).all()
        )
        query = query.where(Fill.id.notin_(complete_context_fill_ids))
    cutoff = _cutoff(range_value)
    if cutoff is not None:
        query = query.where(Fill.executed_at >= cutoff)
    return list(session.exec(query).all())


def _trade_path_ids(session: Session, range_value: str, force: bool) -> list[uuid.UUID]:
    query = select(Trade.id).where(Trade.status.in_(["closed", "expired"]))
    cutoff = _cutoff(range_value)
    if cutoff is not None:
        query = query.where(Trade.opened_at >= cutoff)
    if not force:
        existing_trade_ids = set(session.exec(select(TradePathMetrics.trade_id)).all())
        query = query.where(Trade.id.notin_(existing_trade_ids))
    return list(session.exec(query).all())


def create_polygon_enrichment_job(session: Session, range_value: str = "week", force: bool = False) -> JobRun:
    fill_ids = _polygon_fill_ids(session, range_value, force)
    return create_job(
        session,
        JOB_POLYGON_ENRICH,
        {"range": range_value, "force": force, "fill_ids": [str(fill_id) for fill_id in fill_ids]},
        total=len(fill_ids),
    )


def create_alpaca_enrichment_job(session: Session, range_value: str = "week", force: bool = False) -> JobRun:
    fill_ids = _alpaca_fill_ids(session, range_value, force)
    return create_job(
        session,
        JOB_ALPACA_ENRICH,
        {"range": range_value, "force": force, "fill_ids": [str(fill_id) for fill_id in fill_ids]},
        total=len(fill_ids),
    )


def create_trade_path_job(session: Session, range_value: str = "week", force: bool = False) -> JobRun:
    trade_ids = _trade_path_ids(session, range_value, force)
    return create_job(
        session,
        JOB_TRADE_PATH,
        {"range": range_value, "force": force, "trade_ids": [str(trade_id) for trade_id in trade_ids]},
        total=len(trade_ids),
    )


def run_job(job_id: uuid.UUID) -> int:
    job = _start_job(job_id)
    try:
        if job.job_type == JOB_POLYGON_ENRICH:
            enriched = run_polygon_enrichment_job(job)
        elif job.job_type == JOB_ALPACA_ENRICH:
            enriched = run_alpaca_enrichment_job(job)
        elif job.job_type == JOB_TRADE_PATH:
            enriched = run_trade_path_job(job)
        elif job.job_type == JOB_WEBULL_LISTENER:
            # The listener manages its own lifecycle (status, started_at,
            # finished_at) via engine.webull_listener. Skip the generic
            # _finish_job() call so we don't overwrite its terminal state.
            from app.engine.webull_listener import run_listener
            return run_listener(job.id)
        else:
            raise ValueError(f"Unsupported job type: {job.job_type}")
        _finish_job(job.id, enriched, job.total)
        return enriched
    except Exception as exc:
        _fail_job(job.id, exc)
        raise


def create_webull_listener_job(
    session: Session,
    *,
    accounts: list[str] | None = None,
) -> JobRun:
    """
    Create a JobRun row for the Webull listener. total=0 (open-ended).

    Args:
      accounts: Webull broker account ids to subscribe to. At least one is
        required for the live streaming subscriber; tests that inject a
        polling pull_fn can omit it.
    """
    params: dict[str, Any] = {}
    if accounts:
        params["accounts"] = list(accounts)
    job = JobRun(
        id=uuid.uuid4(),
        job_type=JOB_WEBULL_LISTENER,
        status="queued",
        params_json=json.dumps(params),
        total=0,
        updated_at=datetime.utcnow(),
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def run_polygon_enrichment_job(job: JobRun) -> int:
    from app.engine.enricher import enrich_fills

    params = _params(job)
    fill_ids = [uuid.UUID(value) for value in params.get("fill_ids", [])]
    if not fill_ids:
        return 0

    def on_progress(done: int, label: str) -> None:
        _set_job(job.id, ignore_locked=True, done=done, current=label)

    with Session(engine) as session:
        fills = session.exec(select(Fill).where(Fill.id.in_(fill_ids))).all()
        _set_job(job.id, total=len(fills))
        return enrich_fills(list(fills), session, on_progress=on_progress)


def run_alpaca_enrichment_job(job: JobRun) -> int:
    from app.engine.alpaca_enricher import enrich_fills_alpaca

    params = _params(job)
    fill_ids = [uuid.UUID(value) for value in params.get("fill_ids", [])]
    force = bool(params.get("force", False))
    if not fill_ids:
        return 0

    def on_progress(done: int, label: str) -> None:
        _set_job(job.id, ignore_locked=True, done=done, current=label)

    with Session(engine) as session:
        fills = session.exec(select(Fill).where(Fill.id.in_(fill_ids))).all()
        _set_job(job.id, total=len(fills))
        # The job's fill_ids are already filtered to missing/incomplete rows.
        # Process that explicit set even when the row has a partial context.
        return enrich_fills_alpaca(list(fills), session, on_progress=on_progress, force=True)


def run_trade_path_job(job: JobRun) -> int:
    from app.engine.trade_path import compute_path_metrics_for_trades

    params = _params(job)
    trade_ids = [uuid.UUID(value) for value in params.get("trade_ids", [])]
    force = bool(params.get("force", False))
    if not trade_ids:
        return 0

    def on_progress(done: int, label: str) -> None:
        _set_job(job.id, ignore_locked=True, done=done, current=label)

    with Session(engine) as session:
        trades = session.exec(select(Trade).where(Trade.id.in_(trade_ids))).all()
        _set_job(job.id, total=len(trades))
        return compute_path_metrics_for_trades(list(trades), session, on_progress=on_progress, force=force)
