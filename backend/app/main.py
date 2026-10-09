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

from app.database import engine
from app.schema import ensure_current
from app.models import Account, FILL_LIGHT, Fill
from app.routers import health, accounts, fills, trades, stats, rebuild, quotes, daily_review, auth, market_context, sync, webull, gmail_push, packets, research, strategy_lab, tradingview_alerts, charts
from app.routers import level_alerts as level_alerts_router
from app.routers import captures as captures_router
from app.routers import symbol_info
from app.routers import decisions as decisions_router
from app.routers import practice as practice_router
from app.routers import access as access_router
from app.access_middleware import AccessMiddleware
from app.routers.fills import (
    _rebuild_trades,
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
            account_fills = session.exec(select(Fill).options(*FILL_LIGHT).where(Fill.account_id == blank_account.id)).all()
            for fill in account_fills:
                fill.account_id = target.id
                session.add(fill)
            moved_fill_count += len(account_fills)

        if blank_account_ids:
            session.exec(delete(Account).where(Account.id.in_(blank_account_ids)))

        if moved_fill_count:
            _rebuild_trades(session, anomalies_label="/startup roth merge")

        session.commit()
        backup_manual_fills(session)


def _maybe_autostart_webull_listener() -> None:
    """
    Optionally start the Webull TRADE event listener on uvicorn boot.

    Gated by WEBULL_LISTENER_AUTOSTART (default off). Silently skips when:
      - the flag is off
      - Webull credentials are not configured
      - no local Account rows exist with broker='webull' and a broker_account_id

    Each match logs an INFO line so operators can diagnose why it didn't fire.
    Uses the same durable queue and ownership rules as the HTTP route.
    """
    if os.environ.get("WEBULL_LISTENER_AUTOSTART", "false").lower() not in ("1", "true", "yes"):
        return

    # Import here to avoid pulling grpc/protobuf at module load when the
    # flag is off (keeps test imports light).
    from app.engine.jobs import JOB_WEBULL_LISTENER, create_webull_listener_job, running_job
    from app.engine.webull import resolve_local_webull_accounts, webull_configured
    from app.engine.job_runtime import submit_job

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

    submit_job(job.id)
    _log.info(
        "Webull autostart: listener queued (job_id=%s, accounts=%d, source=%s)",
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
    from app.engine.gmail_listener import listener_enabled

    if listener_enabled():
        # One owner: the listener queues renewals in the sync lane.
        _log.info("Gmail watch autostart skipped: renewal is owned by the Gmail listener")
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


def _maybe_autostart_gmail_listener() -> None:
    """Development only: run the Gmail listener inside the API process.

    Under JOB_EXECUTION_MODE=external the gmail lane worker keeps its own
    listener request alive, so the API does nothing here.
    """
    from app.engine.gmail_listener import ensure_listener_request
    from app.engine.job_runtime import execution_mode, submit_job

    if execution_mode() != "embedded":
        return
    job_id = ensure_listener_request(ignore_backoff=True)
    if job_id is not None:
        submit_job(job_id)


async def _maybe_start_level_alerts(app_: FastAPI, stream):
    """Level alerts (Charts C5.1) are judged here whether or not a chart is open."""
    app_.state.level_alerts = None
    if os.environ.get("LEVEL_ALERTS_AUTOSTART", "true").lower() == "false":
        return None
    from app.engine.chart_calendar import chart_calendar
    from app.engine.chart_feed import chart_feed
    from app.engine.chart_splits import chart_splits
    from app.engine.level_alert_monitor import LevelAlertMonitor
    from app.engine.paper import PaperWatcher

    paper = PaperWatcher(engine, chart_feed, chart_calendar, chart_splits, clock=time.time)
    monitor = LevelAlertMonitor(engine, stream, feed=chart_feed, calendar=chart_calendar, splits=chart_splits, paper=paper)
    stream.attach(monitor)
    await monitor.start()
    app_.state.level_alerts = monitor
    return monitor


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Alembic owns the schema. The app used to call create_all() here, which
    # meant a database could be built two different ways and end up in a state
    # neither one describes; see app/schema.py. Refusing to start is louder
    # than silently repairing, which is the point.
    ensure_current(engine)
    _seed_and_normalize_roth_account()
    with Session(engine) as session:
        restored = restore_manual_fills_from_backup(session)
        if restored:
            session.commit()
    from app.engine.job_runtime import resume_embedded_jobs
    resume_embedded_jobs()
    _maybe_autostart_webull_listener()
    _maybe_autostart_gmail_watch()
    _maybe_autostart_gmail_listener()
    from app.engine.chart_calendar import chart_calendar
    from app.engine.chart_stream import ChartMarketStream
    chart_market_stream = ChartMarketStream(calendar=chart_calendar.cached)
    _app.state.chart_market_stream = chart_market_stream
    level_alerts = await _maybe_start_level_alerts(_app, chart_market_stream)
    try:
        yield
    finally:
        if level_alerts is not None:
            await level_alerts.stop()
        await chart_market_stream.stop()
        from app.engine.job_runtime import execution_mode, shutdown_requested

        if execution_mode() == "embedded":
            shutdown_requested.set()  # let an embedded Gmail listener end cleanly


app = FastAPI(title="Trade Journal API", lifespan=lifespan)

def _cors_origins() -> list[str]:
    """
    Browser origins allowed to call this API.

    The default localhost:3000 pair covers ordinary local development.
    FRONTEND_PUBLIC_URL is honored on top of it because the frontend does not
    always run there: startdev uses other ports, browser tests use their own,
    and a deployed frontend has a real hostname. auth.py already redirects to
    FRONTEND_PUBLIC_URL, so leaving CORS hardcoded meant following the
    documented advice to change ports produced an app whose OAuth worked while
    every client-side fetch was blocked.
    """
    origins = ["http://localhost:3000", "http://127.0.0.1:3000"]
    configured = os.environ.get("FRONTEND_PUBLIC_URL", "").strip().rstrip("/")
    if configured and configured not in origins:
        origins.append(configured)
    return origins


app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(access_router.router, prefix="/access", tags=["app access"])
app.include_router(health.router, tags=["health"])
app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(accounts.router, prefix="/accounts", tags=["accounts"])
app.include_router(fills.router, prefix="/fills", tags=["fills"])
app.include_router(trades.router, prefix="/trades", tags=["trades"])
app.include_router(stats.router, prefix="/stats", tags=["stats"])
app.include_router(rebuild.router, prefix="/rebuild", tags=["rebuild"])
app.include_router(quotes.router, prefix="/quotes", tags=["quotes"])
app.include_router(charts.router, prefix="/charts", tags=["charts"])
app.include_router(symbol_info.router, prefix="/charts", tags=["charts"])
app.include_router(level_alerts_router.router, prefix="/charts", tags=["charts"])
app.include_router(captures_router.router, prefix="/charts", tags=["charts"])
app.include_router(daily_review.router, prefix="/daily-review", tags=["daily-review"])
app.include_router(market_context.router, prefix="/market-context", tags=["market-context"])
app.include_router(sync.router, prefix="/sync", tags=["sync"])
app.include_router(webull.router, prefix="/webull", tags=["webull"])
app.include_router(gmail_push.router, prefix="/gmail", tags=["gmail"])
app.include_router(packets.router, prefix="/packets", tags=["packets"])
app.include_router(practice_router.router, prefix="/practice", tags=["practice"])
app.include_router(decisions_router.router, prefix="/decisions", tags=["decisions"])
app.include_router(
    tradingview_alerts.router,
    prefix="/tradingview",
    tags=["tradingview"],
)
app.include_router(research.router, prefix="/research", tags=["research"])
app.include_router(strategy_lab.router, prefix="/strategy-lab", tags=["strategy-lab"])

# Inspect the finalized route catalog; permission checks precede all handlers.
app.add_middleware(AccessMiddleware, routes=app.router.routes)
