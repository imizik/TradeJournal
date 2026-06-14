import logging
import os
import threading
import time
import warnings
warnings.filterwarnings("ignore", category=FutureWarning, module="google")

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import Session, delete, select

from app.database import create_db_and_tables, engine
from app.models import Account, Fill
from app.routers import health, accounts, fills, trades, stats, rebuild, quotes, daily_review, auth, market_context, sync, webull, gmail_push, packets
from app.routers.fills import (
    _clear_derived_trade_data,
    _persist_rebuild,
    backup_manual_fills,
    restore_manual_fills_from_backup,
)

_log = logging.getLogger(__name__)


def _seed_and_normalize_roth_account() -> None:
    """Ensure Roth fills live under the canonical 8267 account."""
    with Session(engine) as session:
        target = session.exec(select(Account).where(Account.last4 == "8267")).first()
        if not target:
            target = Account(name="Roth IRA", type="roth_ira", last4="8267")
            session.add(target)
            session.commit()
            session.refresh(target)

        blank_roth_accounts = session.exec(
            select(Account).where(Account.type == "roth_ira").where(Account.last4 == "")
        ).all()
        if not blank_roth_accounts:
            return

        moved_fill_count = 0
        blank_account_ids: list[object] = []
        for blank_account in blank_roth_accounts:
            blank_account_ids.append(blank_account.id)
            account_fills = session.exec(select(Fill).where(Fill.account_id == blank_account.id)).all()
            for fill in account_fills:
                fill.account_id = target.id
                session.add(fill)
            moved_fill_count += len(account_fills)

        if blank_account_ids:
            session.exec(delete(Account).where(Account.id.in_(blank_account_ids)))

        if moved_fill_count:
            _clear_derived_trade_data(session)
            _persist_rebuild(session, anomalies_label="/startup roth merge")

        session.commit()
        backup_manual_fills(session)


def _cleanup_orphaned_jobs() -> None:
    """Mark any running/queued jobs as failed — they were orphaned by a restart."""
    from datetime import datetime
    with Session(engine) as session:
        from app.models import JobRun
        from sqlmodel import select as sel
        stuck = session.exec(
            sel(JobRun).where(JobRun.status.in_(["running", "queued"]))
        ).all()
        for job in stuck:
            job.status = "failed"
            job.error = "Orphaned: server restarted while job was running"
            job.finished_at = datetime.utcnow()
            job.updated_at = datetime.utcnow()
            session.add(job)
        if stuck:
            session.commit()
            import logging
            logging.getLogger(__name__).warning(
                "Marked %d orphaned job(s) as failed on startup", len(stuck)
            )


def _maybe_autostart_webull_listener() -> None:
    """
    Optionally start the Webull TRADE event listener on uvicorn boot.

    Gated by WEBULL_LISTENER_AUTOSTART (default off). Silently skips when:
      - the flag is off
      - Webull credentials are not configured
      - no local Account rows exist with broker='webull' and a broker_account_id

    Each match logs an INFO line so operators can diagnose why it didn't fire.
    Runs AFTER the orphan-cleanup pass — any stale 'running' listener row
    from a prior uvicorn boot has already been marked failed, so spawning a
    fresh listener here is safe.
    """
    if os.environ.get("WEBULL_LISTENER_AUTOSTART", "false").lower() not in ("1", "true", "yes"):
        return

    # Import here to avoid pulling grpc/protobuf at module load when the
    # flag is off (keeps test imports light).
    from app.engine.jobs import JOB_WEBULL_LISTENER, create_webull_listener_job, running_job
    from app.engine.webull import resolve_local_webull_accounts, webull_configured
    from app.engine.webull_listener import run_listener

    if not webull_configured():
        _log.info("Webull autostart skipped: credentials not configured")
        return

    # Explicit account allowlist via env wins over DB scan. Lets you keep
    # stray test-ingest rows in the DB without the autostart accidentally
    # subscribing to them.
    explicit = os.environ.get("WEBULL_LISTENER_ACCOUNTS", "").strip()
    explicit_accounts = [a.strip() for a in explicit.split(",") if a.strip()] if explicit else []

    with Session(engine) as session:
        if running_job(session, JOB_WEBULL_LISTENER) is not None:
            _log.info("Webull autostart skipped: a listener is already queued/running")
            return
        if explicit_accounts:
            accounts = explicit_accounts
            source = "WEBULL_LISTENER_ACCOUNTS"
        else:
            accounts = resolve_local_webull_accounts(session)
            source = "local DB"
        if not accounts:
            _log.info(
                "Webull autostart skipped: no accounts found. Set WEBULL_LISTENER_ACCOUNTS=<id[,id,...]> "
                "in .env, or seed an Account row with broker='webull' and a broker_account_id."
            )
            return
        job = create_webull_listener_job(session, accounts=accounts)

    thread = threading.Thread(
        target=run_listener,
        args=(job.id,),
        daemon=True,
        name=f"webull-listener-{job.id}",
    )
    thread.start()
    _log.info(
        "Webull autostart: listener spawned (job_id=%s, accounts=%d, source=%s)",
        job.id, len(accounts), source,
    )


def _maybe_autostart_gmail_watch() -> None:
    """
    Optionally register and renew the Gmail Pub/Sub watch while the API runs.

    Gmail watches expire, so production-ish local setups can set
    GMAIL_WATCH_AUTOSTART=true instead of manually renewing /gmail/watch.
    """
    if os.environ.get("GMAIL_WATCH_AUTOSTART", "false").lower() not in ("1", "true", "yes"):
        return

    def runner() -> None:
        interval = int(os.environ.get("GMAIL_WATCH_RENEW_SECONDS", str(24 * 60 * 60)))
        while True:
            try:
                from app.engine.gmail_poller import register_gmail_watch

                state = register_gmail_watch()
                _log.info(
                    "Gmail watch registered/renewed (history_id=%s, expiration=%s)",
                    state.get("history_id"),
                    state.get("expiration"),
                )
            except Exception:
                _log.warning("Gmail watch registration/renewal failed", exc_info=True)
            time.sleep(max(60, interval))

    thread = threading.Thread(target=runner, daemon=True, name="gmail-watch-renewer")
    thread.start()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    create_db_and_tables()
    _cleanup_orphaned_jobs()
    _seed_and_normalize_roth_account()
    with Session(engine) as session:
        restored = restore_manual_fills_from_backup(session)
        if restored:
            session.commit()
    _maybe_autostart_webull_listener()
    _maybe_autostart_gmail_watch()
    yield


app = FastAPI(title="Trade Journal API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, tags=["health"])
app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(accounts.router, prefix="/accounts", tags=["accounts"])
app.include_router(fills.router, prefix="/fills", tags=["fills"])
app.include_router(trades.router, prefix="/trades", tags=["trades"])
app.include_router(stats.router, prefix="/stats", tags=["stats"])
app.include_router(rebuild.router, prefix="/rebuild", tags=["rebuild"])
app.include_router(quotes.router, prefix="/quotes", tags=["quotes"])
app.include_router(daily_review.router, prefix="/daily-review", tags=["daily-review"])
app.include_router(market_context.router, prefix="/market-context", tags=["market-context"])
app.include_router(sync.router, prefix="/sync", tags=["sync"])
app.include_router(webull.router, prefix="/webull", tags=["webull"])
app.include_router(gmail_push.router, prefix="/gmail", tags=["gmail"])
app.include_router(packets.router, prefix="/packets", tags=["packets"])
