"""
Build a small, deterministic dataset for local development and browser tests.

Why this exists: an empty dashboard proves nothing. Browser tests need known
values to assert on, and a developer or agent poking at a page needs realistic
data to poke at. Neither should require a copy of real trading history.

The fills below are invented but cover the shapes that actually break: a
scale-in, a partial exit that leaves a position open, an option expiring
worthless, fractional stock shares, two fills sharing a timestamp, and a
second account that must stay isolated.

Trades are NOT written directly. Fills are inserted and then the production
rebuild path reconstructs them, so the seeded database exercises the real FIFO
reconstructor and the expected values below are its actual output.

Usage:
    python scripts/seed_dev_data.py                     # backend/data/dev_seed.db
    python scripts/seed_dev_data.py --database-url URL
    python scripts/seed_dev_data.py --print-expected    # values, no writes

Safety: every seeded fill carries a `seed:` raw_email_id, and the script
refuses to touch a database containing any fill without that prefix. You
cannot seed over real trading history.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

ET = ZoneInfo("America/New_York")
SEED_PREFIX = "seed:"
DEFAULT_DB_PATH = BACKEND_DIR / "data" / "dev_seed.db"

# Fixed ids keep runs byte-identical. They also pin FIFO ordering: the
# reconstructor's final sort tie-break is str(fill.id), so same-timestamp
# fills resolve in declaration order only because these ascend.
# See docs/agent/domain-rules.md.
ROTH_ACCOUNT_ID = uuid.UUID(int=0x5EED_0001)
INDIVIDUAL_ACCOUNT_ID = uuid.UUID(int=0x5EED_0002)


# Dates are anchored to the run date, not hard-coded. An option's status
# depends on whether its expiration has passed, so fixed calendar dates make a
# fixture that silently changes meaning as the calendar moves: a position
# seeded as "open" becomes "expired" once its expiry slips into the past, and
# every asserted P&L with it. Offsets keep the contract in EXPECTED true
# forever. Timestamps therefore differ between runs; tests assert on tickers,
# statuses and P&L, never on displayed dates.
TODAY = date.today()


def _days_ago(days: int, hour: int, minute: int) -> datetime:
    day = TODAY - timedelta(days=days)
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=ET)


def _expiry_in(days: int) -> date:
    """Future expiration: the position stays open."""
    return TODAY + timedelta(days=days)


def _expiry_ago(days: int) -> date:
    """Past expiration: unsold lots are written off as expired worthless."""
    return TODAY - timedelta(days=days)


def _fills() -> list[dict]:
    """
    The dataset. Each entry becomes one Fill row.

    Ordering here is meaningful: ids are assigned sequentially, which decides
    FIFO order for fills that share a timestamp.
    """
    return [
        # 1. NVDA calls, scale-in then a single full exit -> CLOSED.
        #    2 @ 500 and 3 @ 400 = 2200 cost, sold 5 @ 700 = 3500. PnL +1300.
        #    Already closed, so its expiry being past is irrelevant.
        _option(ROTH_ACCOUNT_ID, "NVDA", "buy_to_open", "2", "500",
                _days_ago(120, 10, 15), "call", "900", _expiry_ago(75)),
        _option(ROTH_ACCOUNT_ID, "NVDA", "buy_to_open", "3", "400",
                _days_ago(119, 11, 30), "call", "900", _expiry_ago(75)),
        _option(ROTH_ACCOUNT_ID, "NVDA", "sell_to_close", "5", "700",
                _days_ago(113, 14, 45), "call", "900", _expiry_ago(75)),

        # 2. AAPL calls, partial exit, expiry still ahead -> stays OPEN with
        #    realized PnL banked on the exited portion.
        #    Bought 10 @ 200, sold 4 @ 300. PnL +400, 6 contracts still open.
        _option(ROTH_ACCOUNT_ID, "AAPL", "buy_to_open", "10", "200",
                _days_ago(40, 9, 45), "call", "230", _expiry_in(90)),
        _option(ROTH_ACCOUNT_ID, "AAPL", "sell_to_close", "4", "300",
                _days_ago(39, 15, 10), "call", "230", _expiry_in(90)),

        # 3. TSLA calls held past expiration, never sold -> EXPIRED, full loss.
        #    2 @ 150 = 300 written off.
        _option(ROTH_ACCOUNT_ID, "TSLA", "buy_to_open", "2", "150",
                _days_ago(60, 13, 20), "call", "400", _expiry_ago(20)),

        # 4. Two buys sharing one timestamp, then a partial exit. Real orders
        #    fill in multiple prints within the same second. The fixed ids put
        #    the 0.90 lot first, so selling 450 @ 1.00 realizes +45 and leaves
        #    the 0.80 lot open. Price-ascending order would realize +90 instead,
        #    making this fixture genuinely sensitive to the final tie-break.
        _stock(ROTH_ACCOUNT_ID, "RNXT", "buy", "450", "0.90", _days_ago(30, 11, 4)),
        _stock(ROTH_ACCOUNT_ID, "RNXT", "buy", "450", "0.80", _days_ago(30, 11, 4)),
        _stock(ROTH_ACCOUNT_ID, "RNXT", "sell", "450", "1.00", _days_ago(29, 14, 46)),

        # 5. Fractional shares, closed. 9.5 @ 8.00 -> 9.5 @ 10.00. PnL +19.
        _stock(ROTH_ACCOUNT_ID, "RCAT", "buy", "9.5", "8.00", _days_ago(20, 9, 47)),
        _stock(ROTH_ACCOUNT_ID, "RCAT", "sell", "9.5", "10.00", _days_ago(19, 10, 5)),

        # 6. Second account, same contract as the Roth AAPL position above and
        #    still open. Proves account isolation: these must never merge.
        _option(INDIVIDUAL_ACCOUNT_ID, "AAPL", "buy_to_open", "1", "250",
                _days_ago(10, 10, 0), "call", "230", _expiry_in(90)),
    ]


def _option(account_id, ticker, side, contracts, price, executed_at,
            option_type, strike, expiration) -> dict:
    return {
        "account_id": account_id,
        "ticker": ticker,
        "instrument_type": "option",
        "side": side,
        "contracts": Decimal(contracts),
        "price": Decimal(price),
        "executed_at": executed_at,
        "option_type": option_type,
        "strike": Decimal(strike),
        "expiration": expiration,
    }


def _stock(account_id, ticker, side, contracts, price, executed_at) -> dict:
    return {
        "account_id": account_id,
        "ticker": ticker,
        "instrument_type": "stock",
        "side": side,
        "contracts": Decimal(contracts),
        "price": Decimal(price),
        "executed_at": executed_at,
        "option_type": None,
        "strike": None,
        "expiration": None,
    }


# What the reconstructor should produce from the fills above. Browser tests
# assert against these, so a change here is a deliberate change to the
# fixture's contract.
EXPECTED = {
    "accounts": ["8267", "1113"],
    "trades": [
        {"ticker": "NVDA", "account": "8267", "status": "closed", "realized_pnl": "1300.00"},
        {"ticker": "AAPL", "account": "8267", "status": "open", "realized_pnl": "400.00"},
        {"ticker": "TSLA", "account": "8267", "status": "expired", "realized_pnl": "-300.00"},
        {"ticker": "RNXT", "account": "8267", "status": "open", "realized_pnl": "45.00"},
        {"ticker": "RCAT", "account": "8267", "status": "closed", "realized_pnl": "19.00"},
        {"ticker": "AAPL", "account": "1113", "status": "open", "realized_pnl": None},
    ],
    "total_fills": 12,
    "total_trades": 6,
}


def _resolve_database_url(explicit: str | None) -> str:
    if explicit:
        return explicit
    DEFAULT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{DEFAULT_DB_PATH}"


def _assert_safe_target(engine) -> None:
    """
    Refuse to run against a database holding anything but seeded fills.

    Deliberately raw SQL over one column rather than the ORM. This runs before
    migrations -- it has to, because refusing to touch someone's real fills
    outranks bringing a database to head -- so the database may be at an older
    revision than the models describe. `select(Fill)` would name every column
    the current model has and fail on whichever one that revision predates,
    turning a safety check into a crash. `raw_email_id` has been part of `fill`
    since 001_initial, so this works on any revision.
    """
    from sqlalchemy import inspect, text

    if "fill" not in inspect(engine).get_table_names():
        return

    with engine.connect() as connection:
        foreign = connection.execute(
            text(
                "SELECT COUNT(*) FROM fill "
                "WHERE raw_email_id IS NULL OR raw_email_id NOT LIKE :prefix"
            ),
            {"prefix": f"{SEED_PREFIX}%"},
        ).scalar_one()

    if foreign:
        raise SystemExit(
            f"Refusing to seed: target database holds {foreign} fill(s) that "
            "were not created by this script. Point --database-url at a scratch "
            "database instead."
        )


def _prepare_schema(database_url: str, engine) -> None:
    """
    Bring the seed database to the migration head.

    Alembic owns the schema (app/schema.py) and the app refuses to start on a
    database migrations did not build -- which includes this one, because the
    e2e suite seeds a database and then runs the real app against it. Building
    it with create_all() would leave no alembic_version and the backend would
    not come up.

    Migrations run out of process: alembic/env.py reads the URL through
    `from app.database import DATABASE_URL`, which binds at import time, so an
    in-process run migrates whichever database that module already resolved
    rather than this one.
    """
    import subprocess

    from app.schema import alembic_head, has_any_tables, stamped_revision

    head = alembic_head()
    stamped = stamped_revision(engine)

    if head is not None and stamped == head:
        return  # re-seeding a database that is already current

    if stamped is None and has_any_tables(engine):
        # A database built by create_all, before Alembic owned the schema.
        # Migrating it would fail on tables that already exist.
        #
        # This is a fixture, and _assert_safe_target has already established it
        # holds nothing but seeded rows, so rebuilding it is both safe and what
        # the caller wants -- a stale e2e database should not need a human. Only
        # for a local SQLite file: deleting anything on a hosted database is a
        # different decision, and belongs to whoever owns that database.
        if database_url.startswith("sqlite:///"):
            path = Path(database_url.removeprefix("sqlite:///"))
            engine.dispose()
            path.unlink(missing_ok=True)
            print(f"    rebuilt {path.name} (was built by create_all, before migrations)")
        else:
            raise SystemExit(
                f"{database_url} has tables but no migration history, so "
                "migrating it would fail on tables that already exist.\n"
                "  .venv/bin/python scripts/check_database.py --url <url>\n"
                "names the right command for it."
            )

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
        env={**os.environ, "DATABASE_URL": database_url},
    )
    if result.returncode != 0:
        raise SystemExit(
            "Could not migrate the seed database:\n" + (result.stderr or result.stdout)
        )


def seed(database_url: str) -> dict:
    """
    Build the fixture in `database_url`. Returns a summary dict.

    The engine is created here from the argument rather than imported from
    app.database. app.database binds its engine at import time, so setting
    DATABASE_URL and importing it only works if nothing imported it earlier --
    which would make this function silently write to whichever database was
    loaded first. Being explicit means the target is always the one passed in.
    """
    from sqlmodel import Session, SQLModel, create_engine, delete, select

    from app.models import Account, Fill  # noqa: F401  (registers the tables)
    from app.routers.fills import _rebuild_trades

    connect_args = (
        {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    )
    engine = create_engine(database_url, connect_args=connect_args)

    # Safety before schema. If this database already has tables it may hold
    # real fills, and refusing to touch it outranks bringing it to head --
    # otherwise a migration failure is what the caller sees instead of
    # "Refusing to seed", and the guard never gets to fire.
    _assert_safe_target(engine)
    _prepare_schema(database_url, engine)

    with Session(engine) as session:
        # Idempotent: drop previously seeded fills so re-running converges.
        session.exec(delete(Fill).where(Fill.raw_email_id.like(f"{SEED_PREFIX}%")))
        session.commit()

        _upsert_account(session, ROTH_ACCOUNT_ID, "Roth IRA", "roth_ira", "8267")
        _upsert_account(session, INDIVIDUAL_ACCOUNT_ID, "Individual", "individual", "1113")
        session.commit()

        for index, values in enumerate(_fills(), start=1):
            session.add(Fill(
                id=uuid.UUID(int=0x5EEDF111_0000 + index),
                raw_email_id=f"{SEED_PREFIX}{index:03d}",
                **values,
            ))
        session.commit()

        rebuilt, anomalies = _rebuild_trades(session, anomalies_label="/seed")
        session.commit()

        fill_count = len(session.exec(select(Fill.id)).all())

    engine.dispose()
    return {"database_url": database_url, "fills": fill_count,
            "trades": rebuilt, "anomalies": anomalies}


def _upsert_account(session, account_id, name, type_, last4) -> None:
    from sqlmodel import select

    from app.models import Account

    # Startup normalization owns Roth 8267, so match on last4 rather than id
    # and reuse whatever row is already there.
    existing = session.exec(select(Account).where(Account.last4 == last4)).first()
    if existing:
        return
    session.add(Account(id=account_id, name=name, type=type_, last4=last4))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=None,
                        help="SQLAlchemy URL. Defaults to backend/data/dev_seed.db")
    parser.add_argument("--print-expected", action="store_true",
                        help="Print the expected reconstruction and exit without writing")
    args = parser.parse_args()

    if args.print_expected:
        print(json.dumps(EXPECTED, indent=2))
        return

    result = seed(_resolve_database_url(args.database_url))
    print(f"Seeded {result['fills']} fills -> {result['trades']} trades")
    print(f"  {result['database_url']}")
    for anomaly in result["anomalies"]:
        print(f"  anomaly: {anomaly}")


if __name__ == "__main__":
    main()
