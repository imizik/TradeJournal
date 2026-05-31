import threading
import time
import uuid
from datetime import date, datetime
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, not_
from sqlmodel import Session, delete, select

from app.database import engine, get_session
from app.engine.jobs import (
    JOB_ALPACA_ENRICH,
    JOB_POLYGON_ENRICH,
    JOB_TRADE_PATH,
    JOB_WEBULL_LISTENER,
    create_alpaca_enrichment_job,
    create_job,
    create_polygon_enrichment_job,
    create_trade_path_job,
    job_status,
    latest_job,
    run_job,
    running_job,
)
from app.models import Fill, JobRun, Trade
from app.routers.fills import _clear_derived_trade_data, _import_fills_from_gmail, _persist_rebuild

router = APIRouter()

JOB_GMAIL_SYNC = "gmail_sync"
JOB_FILL_CHECK = "fill_import_check"
JOB_TRADE_REBUILD = "trade_rebuild"
JOB_DAILY_REVIEW = "daily_review"
JOB_FULL_PIPELINE = "full_pipeline"
JOB_RESYNC_ALL = "resync_all"

JOB_CONFIG: list[dict[str, Any]] = [
    {"job_type": JOB_GMAIL_SYNC, "label": "Gmail email sync", "description": "Poll Robinhood execution emails and save new fills.", "advanced": False},
    {"job_type": JOB_FILL_CHECK, "label": "Import/manual fills check", "description": "Verify imported and manual fills are present before rebuilding.", "advanced": False},
    {"job_type": JOB_TRADE_REBUILD, "label": "Rebuild trades / FIFO matching", "description": "Recreate derived trades and trade-fill links from fill rows.", "advanced": False},
    {"job_type": JOB_POLYGON_ENRICH, "label": "Enrich missing market data", "description": "Fill missing Polygon-derived prices, IV, Greeks, and indicators.", "advanced": False},
    {"job_type": JOB_ALPACA_ENRICH, "label": "Alpaca context enrichment", "description": "Fetch fill-level market context and cached bars.", "advanced": False},
    {"job_type": JOB_TRADE_PATH, "label": "Path metrics calculation", "description": "Compute closed-trade MFE, MAE, and exit efficiency.", "advanced": False},
    {"job_type": JOB_DAILY_REVIEW, "label": "Daily review generation", "description": "Generate the latest daily review from current trades and enrichment.", "advanced": False},
]

_sync_lock = threading.Lock()


def _now() -> datetime:
    return datetime.utcnow()


def _set_job(job_id: uuid.UUID, **values: Any) -> None:
    with Session(engine) as session:
        job = session.get(JobRun, job_id)
        if not job:
            return
        for key, value in values.items():
            setattr(job, key, value)
        job.updated_at = _now()
        session.add(job)
        session.commit()


def _run_thread(target: Callable[[], None]) -> None:
    thread = threading.Thread(target=target, daemon=True)
    thread.start()


# Job types that the Sync Center treats as "blocking syncs". Excludes
# long-running listeners (e.g. webull_listener) which are persistent
# background workers, not finite sync jobs — they should NOT block the
# user from running sync/enrichment work, and they should NOT be shown
# in the "Sync running: ..." banner.
_LISTENER_JOB_TYPES = {JOB_WEBULL_LISTENER}


def _active_job(session: Session) -> JobRun | None:
    return session.exec(
        select(JobRun)
        .where(JobRun.status.in_(["queued", "running"]))
        .where(JobRun.job_type.notin_(_LISTENER_JOB_TYPES))
        .order_by(JobRun.updated_at.desc())
    ).first()


def _run_simple_job(job_id: uuid.UUID, fn: Callable[[Session, uuid.UUID], tuple[int, str]]) -> None:
    _set_job(job_id, status="running", started_at=_now(), error=None)
    try:
        with Session(engine) as session:
            processed, message = fn(session, job_id)
        _set_job(
            job_id,
            status="succeeded",
            done=1,
            total=1,
            enriched=processed,
            current=message,
            finished_at=_now(),
        )
    except Exception as exc:
        _set_job(job_id, status="failed", error=str(exc), current=str(exc), finished_at=_now())


def _job_to_row(session: Session, config: dict[str, Any]) -> dict[str, Any]:
    job = latest_job(session, config["job_type"])
    status = job_status(job)
    return {
        **config,
        "status": status["status"] or "idle",
        "running": status["running"],
        "done": status["done"],
        "total": status["total"],
        "items_processed": status["enriched"],
        "errors_count": 1 if status["error"] else 0,
        "message": status["current"] or status["error"] or None,
        "error_summary": status["error"],
        "job_id": status["job_id"],
        "created_at": job.created_at if job else None,
        "started_at": status.get("started_at"),
        "finished_at": status.get("finished_at"),
        "last_run_at": status.get("finished_at") or status.get("started_at") or (job.created_at if job else None),
    }


def _create_run(session: Session, job_type: str, message: str) -> JobRun:
    job = create_job(session, job_type, {"source": "sync_center", "message": message}, total=1)
    job.current = message
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def _run_gmail_sync(session: Session, _job_id: uuid.UUID) -> tuple[int, str]:
    result = _import_fills_from_gmail(session, start_enrichment=False)
    processed = int(result["saved"]) + int(result["skipped"])
    return processed, f"Imported {result['saved']} new fill(s), skipped {result['skipped']}."


def _run_fill_check(session: Session, _job_id: uuid.UUID) -> tuple[int, str]:
    total = session.exec(select(func.count(Fill.id))).one()
    manual = session.exec(select(func.count(Fill.id)).where(Fill.raw_email_id.like("manual:%"))).one()
    imported = max(0, total - manual)
    return total, f"{total} fill(s): {imported} imported, {manual} manual."


def _run_trade_rebuild(session: Session, _job_id: uuid.UUID) -> tuple[int, str]:
    _clear_derived_trade_data(session)
    rebuilt, anomalies = _persist_rebuild(session, anomalies_label="/sync/rebuild")
    session.commit()
    suffix = f" {len(anomalies)} anomaly/anomalies logged." if anomalies else ""
    return rebuilt, f"Rebuilt {rebuilt} trade(s).{suffix}"


def _latest_review_day(session: Session) -> tuple[date, list[uuid.UUID]] | None:
    trades = session.exec(select(Trade).order_by(Trade.opened_at.desc())).all()
    by_day: dict[date, set[uuid.UUID]] = {}
    for trade in trades:
        for value in (trade.opened_at, trade.closed_at):
            if value:
                by_day.setdefault(value.date(), set()).add(trade.id)
    if not by_day:
        return None
    day = max(by_day)
    return day, list(by_day[day])


def _run_daily_review(session: Session, _job_id: uuid.UUID) -> tuple[int, str]:
    latest = _latest_review_day(session)
    if not latest:
        return 0, "No trades available for daily review."
    review_day, trade_ids = latest

    from app.routers.daily_review import DailyReviewRequest, create_daily_review

    # Call the existing implementation directly so behavior stays consistent.
    result = create_daily_review(DailyReviewRequest(day=review_day.isoformat(), trade_ids=trade_ids), session)
    if hasattr(result, "__await__"):
        import asyncio

        result = asyncio.run(result)  # type: ignore[assignment]
    return len(trade_ids), f"Generated daily review for {review_day.isoformat()}."


def _run_existing_enrichment(job_type: str, range_value: str, force: bool) -> JobRun:
    with Session(engine) as session:
        if running_job(session, job_type):
            raise HTTPException(status_code=409, detail="That job is already running")
        if job_type == JOB_POLYGON_ENRICH:
            job = create_polygon_enrichment_job(session, range_value=range_value, force=force)
        elif job_type == JOB_ALPACA_ENRICH:
            job = create_alpaca_enrichment_job(session, range_value=range_value, force=force)
        elif job_type == JOB_TRADE_PATH:
            job = create_trade_path_job(session, range_value=range_value, force=force)
        else:
            raise HTTPException(status_code=400, detail="Unsupported enrichment job")
    if job.total:
        _run_thread(lambda: run_job(job.id))
    return job


def _wait_for_job(job_id: uuid.UUID) -> JobRun:
    while True:
        with Session(engine) as session:
            job = session.get(JobRun, job_id)
            if not job:
                raise RuntimeError(f"Job disappeared: {job_id}")
            if job.status == "failed":
                raise RuntimeError(job.error or f"{job.job_type} failed")
            if job.status == "succeeded":
                return job
        time.sleep(1)


def _run_pipeline(pipeline_id: uuid.UUID) -> None:
    if not _sync_lock.acquire(blocking=False):
        _set_job(pipeline_id, status="failed", error="Another sync pipeline is already running", finished_at=_now())
        return
    try:
        _set_job(pipeline_id, status="running", started_at=_now(), current="Starting full sync pipeline")
        steps: list[tuple[str, Callable[[Session, uuid.UUID], tuple[int, str]]]] = [
            (JOB_GMAIL_SYNC, _run_gmail_sync),
            (JOB_FILL_CHECK, _run_fill_check),
            (JOB_TRADE_REBUILD, _run_trade_rebuild),
        ]
        processed = 0
        for index, (job_type, fn) in enumerate(steps, start=1):
            _set_job(pipeline_id, done=index - 1, total=7, current=f"Running {job_type}")
            with Session(engine) as session:
                child = _create_run(session, job_type, f"Pipeline step {index}")
            _run_simple_job(child.id, fn)
            with Session(engine) as session:
                child = session.get(JobRun, child.id)
                if child and child.status == "failed":
                    raise RuntimeError(child.error or f"{job_type} failed")
                processed += child.enriched if child else 0

        _set_job(pipeline_id, done=3, total=7, current="Running market enrichment")
        polygon = _run_existing_enrichment(JOB_POLYGON_ENRICH, "all", False)
        alpaca = _run_existing_enrichment(JOB_ALPACA_ENRICH, "all", False)
        if polygon.total:
            _wait_for_job(polygon.id)
        if alpaca.total:
            _wait_for_job(alpaca.id)

        _set_job(pipeline_id, done=5, total=7, current="Calculating path metrics")
        path = _run_existing_enrichment(JOB_TRADE_PATH, "all", False)
        if path.total:
            _wait_for_job(path.id)

        _set_job(pipeline_id, done=6, total=7, current="Generating daily review")
        with Session(engine) as session:
            review = _create_run(session, JOB_DAILY_REVIEW, "Pipeline final step")
        _run_simple_job(review.id, _run_daily_review)
        with Session(engine) as session:
            review = session.get(JobRun, review.id)
            if review and review.status == "failed":
                raise RuntimeError(review.error or "Daily review failed")
            processed += review.enriched if review else 0

        _set_job(
            pipeline_id,
            status="succeeded",
            done=7,
            total=7,
            enriched=processed,
            current="Full sync pipeline completed",
            finished_at=_now(),
        )
    except Exception as exc:
        _set_job(pipeline_id, status="failed", error=str(exc), current=str(exc), finished_at=_now())
    finally:
        _sync_lock.release()


@router.get("/summary")
async def sync_summary(session: Session = Depends(get_session)):
    active = _active_job(session)
    latest_failures = [
        latest
        for config in JOB_CONFIG
        if (latest := latest_job(session, config["job_type"])) is not None and latest.status == "failed"
    ]
    latest_success = session.exec(
        select(JobRun)
        .where(JobRun.status == "succeeded")
        .order_by(JobRun.finished_at.desc())
    ).first()
    return {
        "running": active is not None,
        "active_job": _job_to_row(session, {"job_type": active.job_type, "label": active.job_type, "description": "", "advanced": False}) if active else None,
        "last_success_at": latest_success.finished_at if latest_success else None,
        "errors_count": len(latest_failures),
    }


@router.get("/jobs")
async def list_sync_jobs(session: Session = Depends(get_session)):
    return [_job_to_row(session, config) for config in JOB_CONFIG]


@router.get("/runs")
async def list_sync_runs(limit: int = 50, session: Session = Depends(get_session)):
    runs = session.exec(select(JobRun).order_by(JobRun.created_at.desc()).limit(limit)).all()
    labels = {config["job_type"]: config["label"] for config in JOB_CONFIG}
    labels[JOB_FULL_PIPELINE] = "Full sync pipeline"
    labels[JOB_RESYNC_ALL] = "Resync all"
    return [
        {
            "id": str(run.id),
            "job_type": run.job_type,
            "label": labels.get(run.job_type, run.job_type),
            "status": run.status,
            "created_at": run.created_at,
            "started_at": run.started_at,
            "finished_at": run.finished_at,
            "duration_seconds": (
                (run.finished_at - run.started_at).total_seconds()
                if run.started_at and run.finished_at
                else None
            ),
            "items_processed": run.enriched,
            "errors_count": 1 if run.error else 0,
            "error_summary": run.error,
            "message": run.current,
        }
        for run in runs
    ]


@router.post("/pipeline/run")
async def run_sync_pipeline(session: Session = Depends(get_session)):
    if _active_job(session):
        raise HTTPException(status_code=409, detail="A sync or enrichment job is already running")
    job = _create_run(session, JOB_FULL_PIPELINE, "Queued full sync pipeline")
    job.total = 7
    session.add(job)
    session.commit()
    _run_thread(lambda: _run_pipeline(job.id))
    return {"pipeline_run_id": str(job.id)}


@router.post("/jobs/{job_type}/run")
async def run_sync_job(job_type: str, range: str = "week", force: bool = False, session: Session = Depends(get_session)):
    if job_type in {JOB_POLYGON_ENRICH, JOB_ALPACA_ENRICH, JOB_TRADE_PATH}:
        job = _run_existing_enrichment(job_type, range, force)
        return {"run_id": str(job.id), "started": bool(job.total), "total": job.total}

    if _active_job(session):
        raise HTTPException(status_code=409, detail="A sync or enrichment job is already running")

    runners: dict[str, Callable[[Session, uuid.UUID], tuple[int, str]]] = {
        JOB_GMAIL_SYNC: _run_gmail_sync,
        JOB_FILL_CHECK: _run_fill_check,
        JOB_TRADE_REBUILD: _run_trade_rebuild,
        JOB_DAILY_REVIEW: _run_daily_review,
    }
    runner = runners.get(job_type)
    if not runner:
        raise HTTPException(status_code=404, detail="Unknown sync job")

    job = _create_run(session, job_type, "Queued from Sync Center")
    _run_thread(lambda: _run_simple_job(job.id, runner))
    return {"run_id": str(job.id), "started": True, "total": job.total}


@router.post("/advanced/rebuild-all")
async def advanced_rebuild_all(session: Session = Depends(get_session)):
    if _active_job(session):
        raise HTTPException(status_code=409, detail="A sync or enrichment job is already running")
    job = _create_run(session, JOB_TRADE_REBUILD, "Queued advanced rebuild")
    _run_thread(lambda: _run_simple_job(job.id, _run_trade_rebuild))
    return {"run_id": str(job.id)}


@router.post("/advanced/resync-all")
async def advanced_resync_all(session: Session = Depends(get_session)):
    if _active_job(session):
        raise HTTPException(status_code=409, detail="A sync or enrichment job is already running")
    job = _create_run(session, JOB_RESYNC_ALL, "Queued destructive resync")

    def runner() -> None:
        _set_job(job.id, status="running", started_at=_now(), error=None)
        try:
            with Session(engine) as run_session:
                _clear_derived_trade_data(run_session)
                run_session.exec(delete(Fill).where(not_(Fill.raw_email_id.like("manual:%"))))
                run_session.commit()
                result = _import_fills_from_gmail(run_session, start_enrichment=False)
                rebuilt, anomalies = _persist_rebuild(run_session, anomalies_label="/sync/resync-all")
                run_session.commit()
            message = f"Resynced {result['saved']} fill(s), rebuilt {rebuilt} trade(s)."
            if anomalies:
                message += f" {len(anomalies)} anomaly/anomalies logged."
            _set_job(job.id, status="succeeded", done=1, total=1, enriched=result["saved"], current=message, finished_at=_now())
        except Exception as exc:
            _set_job(job.id, status="failed", error=str(exc), current=str(exc), finished_at=_now())

    _run_thread(runner)
    return {"run_id": str(job.id)}
