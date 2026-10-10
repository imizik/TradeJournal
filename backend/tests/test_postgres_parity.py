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
import secrets
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlmodel import Session, SQLModel, select

from app.models import Account, Fill, Trade
from app.engine.email_parser import ParsedFill
from app.routers.fills import _import_fills_from_gmail

BACKEND_DIR = Path(__file__).resolve().parents[1]

from tests.postgres_support import (  # noqa: E402
    ALLOW_DESTRUCTIVE,  # noqa: F401  -- re-exported for tests that assert on it
    TEST_DATABASE_URL,
    populated_tables as _populated_tables,
    refuse_if_not_disposable as _refuse_if_not_disposable,
    requires_postgres,
    reset_schema,
    run_alembic,
)

pytestmark = requires_postgres


@pytest.fixture(scope="module")
def pg_engine():
    engine = create_engine(TEST_DATABASE_URL)
    _refuse_if_not_disposable(engine)
    reset_schema(engine)
    yield engine
    # Leave the scratch database empty so a later run passes the guard without
    # anyone having to set TEST_DATABASE_ALLOW_DESTRUCTIVE. Deliberate, rather
    # than relying on whichever test happened to run last.
    reset_schema(engine)
    engine.dispose()


@pytest.fixture(scope="module")
def migrated(pg_engine):
    """The full Alembic chain, run against Postgres exactly as a deploy does."""
    result = run_alembic("upgrade", "head", url=TEST_DATABASE_URL)
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


def test_concurrent_paper_arms_enforce_symbol_cap_on_postgres(migrated, monkeypatch):
    from tests.test_paper_plans import check_concurrent_symbol_cap

    check_concurrent_symbol_cap(migrated, monkeypatch)


def test_gmail_fill_keeps_new_york_clock_on_postgres(migrated, monkeypatch):
    inspector = inspect(migrated)
    for table, column in (("fill", "executed_at"), ("trade", "opened_at"), ("trade", "closed_at")):
        column_type = next(item["type"] for item in inspector.get_columns(table) if item["name"] == column)
        assert column_type.timezone is False, f"{table}.{column} must store a naive New York clock"

    source_time = datetime(2026, 7, 14, 9, 30, tzinfo=ZoneInfo("America/New_York"))
    parsed = ParsedFill(
        ticker="AAPL", side="buy", contracts=Decimal("1"), price=Decimal("100"),
        executed_at=source_time, instrument_type="stock", raw_email_id="parity:gmail:time",
        account_last4="7701", account_type="individual",
    )
    monkeypatch.setattr("app.engine.gmail_poller.poll_new_fills", lambda **_kwargs: [parsed])
    with Session(migrated) as session:
        assert _import_fills_from_gmail(session, start_enrichment=False)["saved"] == 1
    with migrated.connect() as connection:
        stored = connection.execute(
            text("SELECT executed_at FROM fill WHERE raw_email_id = 'parity:gmail:time'")
        ).scalar_one()
    assert stored == datetime(2026, 7, 14, 9, 30)


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


def test_guard_sees_data_outside_the_model_tables(migrated):
    """
    A legacy table from an older schema is not in SQLModel.metadata, but
    DROP SCHEMA public CASCADE destroys it just the same. A model-driven guard
    could not see it.
    """
    with migrated.begin() as connection:
        connection.execute(text(
            "CREATE TABLE IF NOT EXISTS legacy_probe (id INTEGER PRIMARY KEY)"
        ))
        connection.execute(text("INSERT INTO legacy_probe (id) VALUES (1)"))
    try:
        assert any(
            entry.startswith("legacy_probe") for entry in _populated_tables(migrated)
        ), "a table outside SQLModel.metadata must still be visible to the guard"
    finally:
        with migrated.begin() as connection:
            connection.execute(text("DROP TABLE legacy_probe"))


def test_guard_sees_data_outside_the_fill_table(migrated):
    """
    The original blind spot: a database with an empty `fill` table can still
    hold irreplaceable TradingView alerts, Strategy Lab runs or Webull events.
    """
    from app.models import WebullRawEvent

    with Session(migrated) as session:
        session.add(WebullRawEvent(
            event_id="guard-probe",
            event_type="TRADE",
            payload_json="{}",
        ))
        session.commit()

    assert any(
        entry.startswith("webull_raw_event") for entry in _populated_tables(migrated)
    )
    with pytest.raises(AssertionError, match="not empty"):
        _refuse_if_not_disposable(migrated)


def test_guard_accepts_an_empty_database():
    """
    Empty has nothing to lose, so it needs no confirmation.

    Checked against a throwaway in-memory engine rather than the shared
    Postgres schema: the guard only uses get_table_names() and COUNT(*), both
    dialect-agnostic, and dropping the shared schema mid-module would leave
    later tests depending on test ordering.
    """
    empty = create_engine("sqlite://")
    try:
        assert _populated_tables(empty) == []
        _refuse_if_not_disposable(empty)  # must not raise
    finally:
        empty.dispose()


def test_a3_cohort_and_agent_reservation_uniqueness_on_postgres(migrated):
    from app.engine import practice
    from app.models import PracticeAgentCall, PracticeOpportunity
    with Session(migrated) as db:
        run = practice.start(db)
        assert practice.start(db, mode="scheduled").id == run.id
        db.add(PracticeAgentCall(day=run.day, run_id=run.id, model="fixture", prompt_version="fixture", payload_json="{}", config_json="{}"))
        db.commit()
        db.add(PracticeAgentCall(day=run.day, run_id=run.id, model="fixture", prompt_version="fixture", payload_json="{}", config_json="{}"))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        first = practice.opportunities(db, run.id)[0]
        db.add(PracticeOpportunity(run_id=run.id, symbol=first.symbol))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()


def test_app_access_session_and_revocation_on_postgres(migrated, monkeypatch):
    from datetime import timedelta
    from starlette.requests import Request
    from app.engine import access
    from app.models import AccessPrincipal
    monkeypatch.setattr(access, "engine", migrated)
    principal_id = "pg-auth-inspector"
    with Session(migrated) as db:
        principal = AccessPrincipal(id=principal_id, grants_json='{"symbols":["SPY"],"run_ids":[],"journal_read":false}', credential_expires_at=access.now() + timedelta(days=30))
        db.add(principal)
        db.flush()
        token, _ = access.issue_session(db, principal, "assistant")
        db.commit()
    monkeypatch.setenv("TJ_OWNER_GATEWAY_KEY", "o" * 43)
    monkeypatch.setenv("TJ_ASSISTANT_GATEWAY_KEY", "p" * 43)
    monkeypatch.setenv("TJ_ASSISTANT_ORIGIN", "https://assistant.example")
    monkeypatch.delenv("TJ_ACCESS_ALLOW_LOCAL_HTTP", raising=False)
    request = Request({"type": "http", "method": "GET", "path": "/access/me", "headers": [(b"x-tj-gateway", b"p" * 43), (b"cookie", f"{access.cookie_name()}={token}".encode())], "query_string": b"", "server": ("localhost", 8080), "scheme": "http"})
    assert access.identify(request).identifier == principal_id
    with Session(migrated) as db:
        principal = db.get(AccessPrincipal, principal_id)
        principal.enabled = False
        principal.version += 1
        db.add(principal)
        db.commit()
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as denied:
        access.identify(request)
    assert denied.value.status_code == 401


def test_concurrent_sample_replay_is_atomic_on_postgres(migrated, monkeypatch):
    from tests.test_sample_replay import check_concurrent_replay_store

    check_concurrent_replay_store(migrated, monkeypatch)


def test_journal_coach_export_requires_and_observes_database_read_only_role(migrated):
    """Exercise the real exporter, PostgreSQL grants and writer refusal."""
    sys.path.insert(0, str(BACKEND_DIR / "scripts"))
    from export_journal_coach import ExportError, export_snapshot  # noqa: E402
    from journal_coach_snapshot import summary  # noqa: E402

    suffix = secrets.token_hex(5)
    reader = f"jc_reader_{suffix}"
    writer = f"jc_writer_{suffix}"
    member = f"jc_member_{suffix}"
    group = f"jc_group_{suffix}"
    names = (reader, writer, member, group)
    password_by_role = {name: secrets.token_hex(24) for name in names if name != group}
    role_created: set[str] = set()
    et_close = datetime.now(ZoneInfo("America/New_York")).replace(
        tzinfo=None, minute=0, second=0, microsecond=0
    )
    et_open = et_close - timedelta(hours=1)
    with Session(migrated) as session:
        used_suffixes = set(session.exec(select(Account.last4)).all())
        available = [str(value) for value in range(1000, 10000) if str(value) not in used_suffixes]
        assert len(available) >= 2
        account_a = Account(name=f"Coach A {suffix}", type="individual", last4=available[0])
        account_b = Account(name=f"Coach B {suffix}", type="individual", last4=available[1])
        session.add_all([account_a, account_b])
        session.flush()
        session.add_all([
            Trade(account_id=account_a.id, ticker="COACH", instrument_type="stock", contracts=Decimal("2.500000"),
                  avg_entry_premium=Decimal("10.000000"), total_premium_paid=Decimal("25.000000"),
                  realized_pnl=Decimal("-25.250000"), opened_at=et_open, closed_at=et_close, status="closed"),
            Trade(account_id=account_b.id, ticker="OTHER", instrument_type="stock", contracts=Decimal("1.000000"),
                  avg_entry_premium=Decimal("10.000000"), total_premium_paid=Decimal("10.000000"),
                  realized_pnl=None, opened_at=et_open, closed_at=et_close, status="expired"),
        ])
        session.commit()
        selected_account_id = account_a.id

    # Identifiers and passwords are random lowercase hex with fixed prefixes;
    # keep utility SQL literal-safe while using the disposable test URL only.
    try:
        with migrated.begin() as connection:
            for role in (reader, writer, member):
                password = password_by_role[role]
                connection.exec_driver_sql(
                    f"CREATE ROLE {role} LOGIN PASSWORD '{password}' "
                    "NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS"
                )
            connection.exec_driver_sql(f"CREATE ROLE {group} NOLOGIN")
            for role in (reader, writer, member):
                connection.exec_driver_sql(f"GRANT USAGE ON SCHEMA public TO {role}")
                connection.exec_driver_sql(f"GRANT SELECT ON TABLE public.trade TO {role}")
            connection.exec_driver_sql(f"GRANT UPDATE (ticker) ON TABLE public.trade TO {writer}")
            connection.exec_driver_sql(f"GRANT UPDATE ON TABLE public.trade TO {group}")
            connection.exec_driver_sql(f"GRANT {group} TO {member}")
        role_created.update(names)

        base_url = make_url(TEST_DATABASE_URL)
        db_name = base_url.database
        assert db_name

        def url_for(role: str) -> str:
            return base_url.set(username=role, password=password_by_role[role]).render_as_string(hide_password=False)

        snapshot = export_snapshot(url_for(reader), [selected_account_id], et_close.date(), et_close.date())
        assert len(snapshot.trades) == 1
        assert snapshot.trades[0].ticker == "COACH"
        assert snapshot.trades[0].quantity == "2.500000"
        assert snapshot.trades[0].realized_pnl == "-25.250000"
        assert snapshot.trades[0].status == "closed"
        assert snapshot.sample_data is False
        assert snapshot.source == "approved_journal_export"
        assert summary(snapshot)["realized_pnl_total"] == "-25.250000"
        assert set(snapshot.trades[0].model_dump()) == {
            "id", "ticker", "instrument_type", "quantity", "realized_pnl", "status", "opened_at", "closed_at"
        }

        with migrated.begin() as connection:
            quoted_database = connection.dialect.identifier_preparer.quote(db_name)
            connection.exec_driver_sql(f"GRANT CREATE ON DATABASE {quoted_database} TO {reader}")
        try:
            with pytest.raises(ExportError, match="create schemas"):
                export_snapshot(url_for(reader), [selected_account_id], et_close.date(), et_close.date())
        finally:
            with migrated.begin() as connection:
                connection.exec_driver_sql(f"REVOKE CREATE ON DATABASE {quoted_database} FROM {reader}")

        for role in (writer, member):
            with pytest.raises(ExportError):
                export_snapshot(url_for(role), [selected_account_id], et_close.date(), et_close.date())

        # The migration login owns public.trade, so the exporter must refuse
        # this currently privileged connection before reading any rows.
        with pytest.raises(ExportError):
            export_snapshot(TEST_DATABASE_URL, [selected_account_id], et_close.date(), et_close.date())

        readonly_engine = create_engine(url_for(reader), connect_args={"connect_timeout": 10})
        try:
            with readonly_engine.connect() as connection:
                transaction = connection.begin()
                with pytest.raises(DBAPIError) as denied:
                    connection.execute(text("UPDATE public.trade SET status = status WHERE false"))
                assert getattr(denied.value.orig, "sqlstate", None) == "42501"
                transaction.rollback()
        finally:
            readonly_engine.dispose()
    finally:
        with migrated.begin() as connection:
            if member in role_created and group in role_created:
                connection.exec_driver_sql(f"REVOKE {group} FROM {member}")
            for role in (reader, writer, member):
                if role in role_created:
                    if role == writer:
                        connection.exec_driver_sql(f"REVOKE UPDATE (ticker) ON TABLE public.trade FROM {writer}")
                    connection.exec_driver_sql(f"REVOKE ALL PRIVILEGES ON TABLE public.trade FROM {role}")
                    connection.exec_driver_sql(f"REVOKE ALL PRIVILEGES ON SCHEMA public FROM {role}")
            if group in role_created:
                connection.exec_driver_sql(f"REVOKE UPDATE ON TABLE public.trade FROM {group}")
                connection.exec_driver_sql(f"REVOKE ALL PRIVILEGES ON TABLE public.trade FROM {group}")
                connection.exec_driver_sql(f"DROP ROLE {group}")
            for role in (reader, writer, member):
                if role in role_created:
                    connection.exec_driver_sql(f"DROP ROLE {role}")
