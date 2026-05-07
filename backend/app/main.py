import warnings
warnings.filterwarnings("ignore", category=FutureWarning, module="google")

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import Session, delete, select

from app.database import create_db_and_tables, engine
from app.models import Account, Fill
from app.routers import health, accounts, fills, trades, stats, rebuild, quotes, daily_review, auth
from app.routers.fills import (
    _clear_derived_trade_data,
    _persist_rebuild,
    backup_manual_fills,
    restore_manual_fills_from_backup,
)


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


@asynccontextmanager
async def lifespan(_app: FastAPI):
    create_db_and_tables()
    _seed_and_normalize_roth_account()
    with Session(engine) as session:
        restored = restore_manual_fills_from_backup(session)
        if restored:
            session.commit()
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
