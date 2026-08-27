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


# A table this module creates in its own scratch database, so a later run can
# tell "my own residue" from "someone else's data". It lives in the schema
# that gets dropped, and is recreated immediately afterwards.
SCRATCH_MARKER_TABLE = "parity_scratch_marker"


def _is_marked_scratch(engine) -> bool:
    return SCRATCH_MARKER_TABLE in inspect(engine).get_table_names()


def _mark_as_scratch(engine) -> None:
    with engine.begin() as connection:
        connection.execute(text(
            f"CREATE TABLE IF NOT EXISTS {SCRATCH_MARKER_TABLE} ("
            "note TEXT NOT NULL)"
        ))
        connection.execute(
            text(f"INSERT INTO {SCRATCH_MARKER_TABLE} (note) VALUES (:note)"),
            {"note": "disposable database for tests/test_postgres_parity.py"},
        )


def _populated_application_tables(engine) -> list[str]:
    """Every application table currently holding rows."""
    inspector = inspect(engine)
    present = set(inspector.get_table_names())
    populated: list[str] = []
    with engine.connect() as connection:
        for table in sorted(set(SQLModel.metadata.tables) - {"alembic_version"}):
            if table not in present:
                continue
            count = connection.execute(
                text(f'SELECT COUNT(*) FROM "{table}"')
            ).scalar_one()
            if count:
                populated.append(f"{table} ({count} row(s))")
    return populated


def _refuse_if_not_disposable(engine) -> None:
    """
    These tests run DROP SCHEMA public CASCADE. Refuse anything that might not
    be disposable.

    Checking one table is not enough: a database whose `fill` table is empty
    can still hold irreplaceable TradingView alerts, Strategy Lab runs, Webull
    raw events or accounts, and dropping the schema would take all of it. So
    the rule is: any application data at all means refuse, unless this module
    has previously claimed the database as scratch by leaving its marker.

    That keeps re-runs working (the marker is recreated after each drop)
    without ever green-lighting a database it has not seen before.
    """
    if _is_marked_scratch(engine):
        return

    populated = _populated_application_tables(engine)
    if populated:
        raise AssertionError(
            "TEST_DATABASE_URL points at a database holding application data:\n"
            + "\n".join(f"  - {entry}" for entry in populated)
            + "\n\nThese tests run DROP SCHEMA public CASCADE. Point them at a "
            "disposable database. A database this module has already claimed "
            f"carries a {SCRATCH_MARKER_TABLE} table and is accepted on later "
            "runs."
        )


@pytest.fixture(scope="module")
def pg_engine():
    engine = create_engine(TEST_DATABASE_URL)
    _refuse_if_not_disposable(engine)
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    # The drop took the marker with it; re-claim the database so the next run
    # recognises its own residue.
    _mark_as_scratch(engine)
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


def test_guard_refuses_a_database_whose_data_is_outside_the_fill_table(migrated):
    """
    The blind spot this guard was originally missing: a database with an empty
    `fill` table can still hold irreplaceable TradingView alerts, Strategy Lab
    runs, Webull events or accounts. Checking fills alone let DROP SCHEMA
    CASCADE run over all of it.
    """
    from app.models import WebullRawEvent

    with Session(migrated) as session:
        session.add(WebullRawEvent(
            event_id="guard-probe",
            event_type="TRADE",
            payload_json="{}",
        ))
        session.commit()

    populated = _populated_application_tables(migrated)
    assert any(entry.startswith("webull_raw_event") for entry in populated), (
        "data outside the fill table must be visible to the guard"
    )

    # With the scratch marker removed, that data must block the drop.
    with migrated.begin() as connection:
        connection.execute(text(f"DROP TABLE {SCRATCH_MARKER_TABLE}"))
    try:
        assert not _is_marked_scratch(migrated)
        with pytest.raises(AssertionError, match="holding application data"):
            _refuse_if_not_disposable(migrated)
    finally:
        _mark_as_scratch(migrated)

    # And with the marker back, the same database is accepted again, so
    # re-running against a scratch database keeps working.
    _refuse_if_not_disposable(migrated)


def test_guard_accepts_an_empty_unclaimed_database(migrated):
    """A database with no application data is safe to drop whether or not it
    has been claimed before."""
    inspector = inspect(migrated)
    assert "fill" in inspector.get_table_names()  # schema exists
    # Nothing asserted about markers here: an empty schema has nothing to lose.
    empty = create_engine(TEST_DATABASE_URL)
    try:
        with empty.begin() as connection:
            connection.execute(text("DROP SCHEMA public CASCADE"))
            connection.execute(text("CREATE SCHEMA public"))
        _refuse_if_not_disposable(empty)  # must not raise
    finally:
        empty.dispose()
