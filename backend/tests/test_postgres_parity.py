"""
Behavior that only Postgres can prove.

The suite runs on SQLite, but production runs on Neon. Several things differ
between the two, and the SQLite half is the only half currently exercised:

- ``ExactDecimal`` (app/models.py) returns ``String(48)`` on SQLite and
  ``Numeric(precision, scale)`` on Postgres. Decimal storage is literally
  different code per dialect.
- Several Alembic revisions use batch table recreation, a SQLite workaround
  that behaves differently on Postgres.
- Constraint and uniqueness enforcement, and transaction semantics under real
  concurrency, are Postgres's own.

These tests are skipped unless TEST_DATABASE_URL names a Postgres database:

    TEST_DATABASE_URL=postgresql+psycopg://user@host:5432/db pytest tests/test_postgres_parity.py

TEST_DATABASE_URL is deliberately a different variable from DATABASE_URL.
conftest.py pins DATABASE_URL to a throwaway SQLite file precisely so the
suite can never inherit a developer's hosted database, and that guard stays
intact -- this module builds its own engine instead, the same way most other
test modules already do.

The target is dropped and recreated, so it must be disposable. There is a
guard below that refuses a database holding fills.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel, select

from app.models import Account, Fill

BACKEND_DIR = Path(__file__).resolve().parents[1]

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "").strip()

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL.startswith("postgresql"),
    reason="set TEST_DATABASE_URL to a Postgres URL to run dialect parity tests",
)


# Every row these tests create is tagged, so the guard below can tell its own
# residue from real data. Same convention as scripts/seed_dev_data.py.
PARITY_PREFIX = "parity-"


def _refuse_if_not_disposable(engine) -> None:
    """
    These tests drop the schema. Refuse anything that looks like real data.

    Cheap, but it catches the realistic accident: pointing TEST_DATABASE_URL
    at a dev or staging database that has journal data in it. Rows left by a
    previous run of this module are recognised and ignored, so re-running
    against the same scratch database stays possible.
    """
    inspector = inspect(engine)
    if "fill" not in inspector.get_table_names():
        return
    with engine.connect() as connection:
        foreign = connection.execute(
            text(
                "SELECT COUNT(*) FROM fill "
                "WHERE raw_email_id IS NULL OR raw_email_id NOT LIKE :prefix"
            ),
            {"prefix": f"{PARITY_PREFIX}%"},
        ).scalar_one()
    if foreign:
        raise AssertionError(
            f"TEST_DATABASE_URL points at a database holding {foreign} fill(s) "
            "this module did not create. These tests drop the schema. Point it "
            "at a disposable database."
        )


@pytest.fixture(scope="module")
def pg_engine():
    engine = create_engine(TEST_DATABASE_URL)
    _refuse_if_not_disposable(engine)
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def migrated(pg_engine):
    """The full Alembic chain, run against Postgres exactly as a deploy does."""
    environment = os.environ.copy()
    environment["DATABASE_URL"] = TEST_DATABASE_URL
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", "head"],
        cwd=BACKEND_DIR,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        "alembic upgrade head failed on Postgres. Several revisions use batch "
        "table recreation, a SQLite workaround.\n\n"
        + result.stdout + result.stderr
    )
    return pg_engine


def test_full_migration_chain_applies_to_postgres(migrated):
    """The deploy path itself. SQLite passing proves nothing about Neon."""
    tables = set(inspect(migrated).get_table_names())
    expected = set(SQLModel.metadata.tables) - {"alembic_version"}
    assert expected <= tables, f"missing after migration: {sorted(expected - tables)}"


def test_migrated_postgres_schema_matches_the_models(migrated):
    """
    The drift check from test_schema_migrations.py, on the dialect that
    actually matters. Startup calls create_all(), so drift is invisible
    locally and only surfaces on a migrated database like Neon.
    """
    inspector = inspect(migrated)
    for table in sorted(set(SQLModel.metadata.tables) - {"alembic_version"}):
        migrated_columns = {c["name"] for c in inspector.get_columns(table)}
        model_columns = set(SQLModel.metadata.tables[table].columns.keys())
        assert model_columns == migrated_columns, (
            f"column drift on {table!r} under Postgres.\n"
            f"  only in migrations: {sorted(migrated_columns - model_columns)}\n"
            f"  only in models:     {sorted(model_columns - migrated_columns)}"
        )


def test_exact_decimals_survive_a_postgres_round_trip(migrated):
    """
    ExactDecimal stores String(48) on SQLite and NUMERIC on Postgres, so this
    path is untested by the rest of the suite. Money must not acquire float
    error: option premium is dollars per contract, and fractional share
    quantities carry six decimal places.
    """
    values = [
        Decimal("9.785930"),      # fractional shares, full scale
        Decimal("1050.000000"),   # a strike
        Decimal("0.010000"),      # a penny
        Decimal("123456.789012"), # wide, to exercise precision
    ]

    with Session(migrated) as session:
        account = Account(name="Parity", type="individual", last4="9999")
        session.add(account)
        session.commit()
        session.refresh(account)

        for index, value in enumerate(values):
            session.add(Fill(
                account_id=account.id,
                ticker="PARITY",
                instrument_type="stock",
                side="buy",
                contracts=value,
                price=value,
                executed_at=datetime.now(timezone.utc),
                raw_email_id=f"parity-decimal-{index}",
            ))
        session.commit()

    with Session(migrated) as session:
        stored = session.exec(
            select(Fill).where(Fill.ticker == "PARITY").order_by(Fill.raw_email_id)
        ).all()

    assert [Decimal(str(f.contracts)) for f in stored] == values
    assert [Decimal(str(f.price)) for f in stored] == values


def test_exact_decimal_columns_are_numeric_not_text_on_postgres(migrated):
    """
    ExactDecimal is the one type whose storage genuinely differs by dialect:
    tradingview_alert.price is NUMERIC(28, 12) on Postgres and VARCHAR(48) on
    SQLite. Everything else in the suite exercises only the SQLite half.
    """
    column = next(
        c for c in inspect(migrated).get_columns("tradingview_alert")
        if c["name"] == "price"
    )
    rendered = str(column["type"]).upper()
    assert "NUMERIC" in rendered, (
        f"expected NUMERIC on Postgres, got {rendered}. ExactDecimal's "
        "load_dialect_impl should only return String on SQLite."
    )


def test_exact_decimal_round_trips_through_postgres_numeric(migrated):
    """
    The values that must not acquire float error. Twelve decimal places is
    the declared scale, so a value using all of them is the real test: a
    float-backed column would round it.
    """
    from app.models import TradingViewAlert

    values = [
        Decimal("123.456789012345"[:16]),  # long, within scale
        Decimal("0.000000000001"),         # smallest representable at scale 12
        Decimal("99999999999999.5"),       # large, to exercise precision
    ]

    with Session(migrated) as session:
        for index, value in enumerate(values):
            session.add(TradingViewAlert(
                alert_id=f"parity-decimal-{index}",
                contract_version=1,
                parser_revision="parity",
                indicator_version="parity",
                # The table CHECKs length()=64, so these must be real digests.
                content_sha256=hashlib.sha256(f"content-{index}".encode()).hexdigest(),
                raw_payload_sha256=hashlib.sha256(f"raw-{index}".encode()).hexdigest(),
                symbol="PARITY",
                timeframe="5",
                setup="parity",
                side="long",
                price=value,
                bar_time_ms=1700000000000 + index,
                bar_time=datetime.now(timezone.utc),
                payload_json="{}",
            ))
        session.commit()

    with Session(migrated) as session:
        stored = session.exec(
            select(TradingViewAlert)
            .where(TradingViewAlert.symbol == "PARITY")
            .order_by(TradingViewAlert.alert_id)
        ).all()

    assert [Decimal(str(a.price)) for a in stored] == values, (
        "exact decimals did not survive the Postgres NUMERIC round trip"
    )


def test_raw_email_id_uniqueness_is_enforced_by_postgres(migrated):
    """
    The fill import dedupe key. Revision 003 creates it as a named UNIQUE
    constraint while the models declare a unique index; both must actually
    enforce on the dialect that ships.
    """
    with Session(migrated) as session:
        account = session.exec(select(Account)).first()
        assert account is not None

        session.add(Fill(
            account_id=account.id,
            ticker="DUPE",
            instrument_type="stock",
            side="buy",
            contracts=Decimal("1"),
            price=Decimal("1"),
            executed_at=datetime.now(timezone.utc),
            raw_email_id="parity-duplicate",
        ))
        session.commit()

    with Session(migrated) as session:
        account = session.exec(select(Account)).first()
        session.add(Fill(
            account_id=account.id,
            ticker="DUPE",
            instrument_type="stock",
            side="buy",
            contracts=Decimal("1"),
            price=Decimal("1"),
            executed_at=datetime.now(timezone.utc),
            raw_email_id="parity-duplicate",  # same key
        ))
        with pytest.raises(IntegrityError):
            session.commit()


def test_account_last4_uniqueness_is_enforced_by_postgres(migrated):
    """Account identity. Blank-last4 Roth merging is an active cleanup story;
    the constraint behind it has to hold on Postgres."""
    with Session(migrated) as session:
        session.add(Account(name="Dupe", type="individual", last4="9999"))
        with pytest.raises(IntegrityError):
            session.commit()


def test_tradingview_alert_identity_is_enforced_by_postgres(migrated):
    """
    alert_id is the sole idempotency key for the live-alert loop: equal
    semantic hashes are retries, and a second row with the same id must never
    overwrite first evidence. That guarantee is the database's to keep.
    """
    from app.models import TradingViewAlert

    inspector = inspect(migrated)
    columns = {c["name"] for c in inspector.get_columns("tradingview_alert")}
    assert "alert_id" in columns

    primary_key = inspector.get_pk_constraint("tradingview_alert")
    unique = {
        tuple(sorted(c["column_names"]))
        for c in inspector.get_unique_constraints("tradingview_alert")
    } | {
        tuple(sorted(i["column_names"]))
        for i in inspector.get_indexes("tradingview_alert")
        if i.get("unique")
    }
    assert ("alert_id",) in unique or primary_key["constrained_columns"] == ["alert_id"], (
        "alert_id must be unique on Postgres; it is the only idempotency key "
        "for the TradingView ingress."
    )
