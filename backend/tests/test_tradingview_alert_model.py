from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.models import TradingViewAlert


@pytest.fixture
def alert_engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    yield engine
    SQLModel.metadata.drop_all(engine)


def _alert(**overrides) -> TradingViewAlert:
    values = {
        "alert_id": "v1:1.0.0:AAPL:5:1737561600000:orb_break:long",
        "contract_version": 1,
        "parser_revision": "tv-alert-v1-r1",
        "indicator_version": "1.0.0",
        "content_sha256": "a" * 64,
        "raw_payload_sha256": "b" * 64,
        "symbol": "AAPL",
        "timeframe": "5",
        "setup": "orb_break",
        "side": "long",
        "price": Decimal("999999999999.123456789012"),
        "bar_time_ms": 1_737_561_600_000,
        "bar_time": datetime(2025, 1, 22, 16, 0),
        "payload_json": '{"v":1,"price":999999999999.123456789012}',
        "levels_json": '{"vwap":{"number":"214.1"}}',
        "context_json": '{"above_vwap":{"bool":true}}',
    }
    values.update(overrides)
    return TradingViewAlert(**values)


def test_alert_round_trip_preserves_exact_contract_and_audit_fields(alert_engine):
    alert = _alert()

    with Session(alert_engine) as session:
        session.add(alert)
        session.commit()
        session.expire_all()
        stored = session.get(TradingViewAlert, alert.alert_id)

        assert stored is not None
        assert stored.contract_version == 1
        assert stored.parser_revision == "tv-alert-v1-r1"
        assert stored.indicator_version == "1.0.0"
        assert stored.content_sha256 == "a" * 64
        assert stored.raw_payload_sha256 == "b" * 64
        assert stored.price == Decimal("999999999999.123456789012")
        assert stored.bar_time_ms == 1_737_561_600_000
        assert stored.bar_time == datetime(2025, 1, 22, 16, 0)
        assert stored.payload_json == (
            '{"v":1,"price":999999999999.123456789012}'
        )
        assert stored.levels_json == '{"vwap":{"number":"214.1"}}'
        assert stored.context_json == '{"above_vwap":{"bool":true}}'
        assert stored.analysis_status == "pending"
        assert stored.analysis_attempts == 0
        assert stored.analysis_started_at is None
        assert stored.analysis_completed_at is None
        assert stored.scorer_revision is None
        assert stored.verdict is None
        assert stored.confidence is None
        assert stored.assessment_json is None
        assert stored.analysis_error_code is None
        assert stored.analysis_error is None


def test_alert_id_is_the_only_database_idempotency_key(alert_engine):
    first = _alert()
    alert_id = first.alert_id
    second = _alert(
        content_sha256="c" * 64,
        raw_payload_sha256="d" * 64,
    )

    with Session(alert_engine) as session:
        session.add(first)
        session.commit()

    with Session(alert_engine) as session:
        session.add(second)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

    with Session(alert_engine) as session:
        assert session.get(TradingViewAlert, alert_id) is not None


@pytest.mark.parametrize(
    "overrides",
    [
        {"contract_version": 0},
        {"side": "flat"},
        {"price": Decimal("0")},
        {"analysis_attempts": -1},
        {"analysis_status": "unknown"},
        {"verdict": "buy"},
        {"confidence": "certain"},
        {"content_sha256": "short"},
        {"raw_payload_sha256": "short"},
        {"bar_time_ms": 4_102_444_800_000},
        {"indicator_version": "x" * 33},
    ],
)
def test_database_constraints_reject_invalid_alert_rows(alert_engine, overrides):
    with Session(alert_engine) as session:
        session.add(_alert(**overrides))
        with pytest.raises(IntegrityError):
            session.commit()


def test_alert_table_is_isolated_and_has_worker_query_indexes(alert_engine):
    inspector = inspect(alert_engine)

    assert inspector.get_foreign_keys("tradingview_alert") == []
    assert inspector.get_pk_constraint("tradingview_alert")[
        "constrained_columns"
    ] == ["alert_id"]

    indexes = {
        index["name"]: tuple(index["column_names"])
        for index in inspector.get_indexes("tradingview_alert")
    }
    assert indexes == {
        "ix_tradingview_alert_analysis_status_updated_at": (
            "analysis_status",
            "updated_at",
        ),
        "ix_tradingview_alert_bar_time": ("bar_time",),
        "ix_tradingview_alert_received_at": ("received_at",),
        "ix_tradingview_alert_setup_received_at": (
            "setup",
            "received_at",
        ),
        "ix_tradingview_alert_symbol_received_at": (
            "symbol",
            "received_at",
        ),
    }
