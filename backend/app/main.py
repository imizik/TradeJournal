from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import Session, select

from app.database import create_db_and_tables, engine
from app.models import Account
from app.routers import health, accounts, fills, trades, stats, rebuild


def _seed_account() -> None:
    """Ensure the Roth IRA account row exists. Safe to call on every startup."""
    with Session(engine) as session:
        existing = session.exec(select(Account).where(Account.last4 == "8267")).first()
        if not existing:
            session.add(Account(name="Roth IRA", type="roth_ira", last4="8267"))
            session.commit()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    create_db_and_tables()
    _seed_account()
    yield


app = FastAPI(title="Trade Journal API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, tags=["health"])
app.include_router(accounts.router, prefix="/accounts", tags=["accounts"])
app.include_router(fills.router, prefix="/fills", tags=["fills"])
app.include_router(trades.router, prefix="/trades", tags=["trades"])
app.include_router(stats.router, prefix="/stats", tags=["stats"])
app.include_router(rebuild.router, prefix="/rebuild", tags=["rebuild"])
