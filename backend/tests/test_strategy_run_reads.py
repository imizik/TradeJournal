from __future__ import annotations

import json
import uuid
from collections.abc import Generator
from datetime import date, datetime
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.database import get_session
from app.engine.strategy_metrics import CALCULATION_VERSION
from app.models import (
    StrategyDefinition,
    StrategyRun,
    StrategyRunMetrics,
    StrategyRunTrade,
    StrategyVersion,
)
from app.routers import strategy_lab


@pytest.fixture
def test_engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    yield engine
    SQLModel.metadata.drop_all(engine)


@pytest.fixture
def client(test_engine) -> Generator[TestClient, None, None]:
    def override_session() -> Generator[Session, None, None]:
        with Session(test_engine) as session:
            yield session

    test_app = FastAPI()
    test_app.include_router(strategy_lab.router, prefix="/strategy-lab")
    test_app.dependency_overrides[get_session] = override_session

    with TestClient(test_app) as test_client:
        yield test_client


@pytest.fixture
def sql_statements(test_engine) -> Generator[list[str], None, None]:
    statements: list[str] = []

    def record_statement(_conn, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)

    event.listen(test_engine, "before_cursor_execute", record_statement)
    yield statements
    event.remove(test_engine, "before_cursor_execute", record_statement)


@pytest.fixture
def seeded(test_engine) -> dict[str, uuid.UUID]:
    with Session(test_engine) as session:
        primary = StrategyDefinition(
            name="VWAP Reclaim",
            description="Primary research loop.",
            setup_type="vwap_reclaim",
        )
        secondary = StrategyDefinition(
            name="Opening Range",
            description="Separate strategy.",
            setup_type="opening_range",
        )
        session.add(primary)
        session.add(secondary)
        session.flush()

        baseline = StrategyVersion(
            strategy_definition_id=primary.id,
            version_label="v1",
            pine_source="PINE_PAYLOAD_MUST_NOT_LEAK",
            source_fingerprint="a" * 64,
            change_summary="Establish the baseline.",
            hypothesis="A confirmed reclaim should improve expectancy.",
            parameters_json=json.dumps({"rvol_min": 1.5}),
            status="champion",
        )
        challenger = StrategyVersion(
            strategy_definition_id=primary.id,
            parent_version_id=baseline.id,
            version_label="v2",
            pine_source="SECOND_PINE_PAYLOAD_MUST_NOT_LEAK",
            source_fingerprint="b" * 64,
            change_summary="Raise the RVOL floor.",
            hypothesis="Fewer low-volume entries should reduce drawdown.",
            parameters_json=json.dumps({"rvol_min": 1.8}),
            status="challenger",
        )
        unrelated = StrategyVersion(
            strategy_definition_id=secondary.id,
            version_label="v1",
            pine_source="THIRD_PINE_PAYLOAD_MUST_NOT_LEAK",
            source_fingerprint="c" * 64,
            parameters_json="{}",
            status="draft",
        )
        session.add(baseline)
        session.add(challenger)
        session.add(unrelated)
        session.flush()

        ready_run = StrategyRun(
            strategy_version_id=baseline.id,
            version_fingerprint=baseline.source_fingerprint,
            symbol="SPY",
            timeframe="5m",
            source_timezone="America/New_York",
            backtest_start=date(2026, 3, 1),
            backtest_end=date(2026, 3, 31),
            initial_capital=Decimal("25000"),
            currency="USD",
            commission_type="cash_per_order",
            commission_value=Decimal("1.25"),
            slippage_type="ticks",
            slippage_value=Decimal("2"),
            execution_timing="bar_close",
            session_mode="regular",
            extended_hours=False,
            pyramiding=0,
            parameters_json=json.dumps({"rvol_min": 1.5}),
            notes="March baseline.",
            source_file_name="spy-v1.csv",
            source_sha256="d" * 64,
            source_headers_json='["SOURCE_HEADERS_MUST_NOT_LEAK"]',
            source_mapping_json='{"SOURCE_MAPPING_MUST_NOT_LEAK":true}',
            source_warnings_json=json.dumps([{"code": "one"}, {"code": "two"}]),
            source_csv_text="SOURCE_CSV_MUST_NOT_LEAK",
            imported_at=datetime(2026, 4, 3, 12, 0),
            created_at=datetime(2026, 4, 3, 12, 0),
        )
        pending_run = StrategyRun(
            strategy_version_id=challenger.id,
            version_fingerprint=challenger.source_fingerprint,
            symbol="QQQ",
            timeframe="15m",
            source_timezone="UTC",
            currency="USD",
            parameters_json=json.dumps({"rvol_min": 1.8}),
            source_file_name="qqq-v2.csv",
            source_sha256="e" * 64,
            source_csv_text="SECOND_SOURCE_CSV_MUST_NOT_LEAK",
            imported_at=datetime(2026, 4, 2, 12, 0),
            created_at=datetime(2026, 4, 2, 12, 0),
        )
        stale_run = StrategyRun(
            strategy_version_id=unrelated.id,
            version_fingerprint=unrelated.source_fingerprint,
            symbol="IWM",
            timeframe="30m",
            source_timezone="UTC",
            currency="USD",
            parameters_json="{}",
            source_file_name="iwm-v1.csv",
            source_sha256="f" * 64,
            source_csv_text="THIRD_SOURCE_CSV_MUST_NOT_LEAK",
            imported_at=datetime(2026, 4, 1, 12, 0),
            created_at=datetime(2026, 4, 1, 12, 0),
        )
        session.add(ready_run)
        session.add(pending_run)
        session.add(stale_run)
        session.flush()

        trades = [
            StrategyRunTrade(
                run_id=ready_run.id,
                trade_number=1,
                direction="long",
                entry_at=datetime(2026, 3, 9, 13, 30),
                exit_at=datetime(2026, 3, 9, 14, 0),
                entry_at_raw="2026-03-09 09:30",
                exit_at_raw="2026-03-09 10:00",
                entry_price=Decimal("100"),
                exit_price=Decimal("102"),
                quantity=Decimal("10"),
                net_pnl=Decimal("20"),
                return_pct=Decimal("2"),
                mfe=Decimal("25"),
                mfe_pct=Decimal("2.5"),
                mae=Decimal("-5"),
                mae_pct=Decimal("-0.5"),
                cumulative_pnl=Decimal("20"),
                cumulative_return_pct=Decimal("0.08"),
                duration_bars=6,
                duration_minutes=30,
                entry_signal="reclaim",
                exit_signal="target",
                entry_comment="ENTRY_COMMENT_MUST_NOT_LEAK",
                exit_comment="EXIT_COMMENT_MUST_NOT_LEAK",
                feature_snapshot_json='{"FEATURE_SNAPSHOT_MUST_NOT_LEAK":true}',
                raw_entry_row_json='{"RAW_ENTRY_MUST_NOT_LEAK":true}',
                raw_exit_row_json='{"RAW_EXIT_MUST_NOT_LEAK":true}',
            ),
            StrategyRunTrade(
                run_id=ready_run.id,
                trade_number=2,
                direction="short",
                entry_at=datetime(2026, 3, 9, 19, 55),
                exit_at=datetime(2026, 3, 9, 20, 5),
                entry_at_raw="2026-03-09 15:55",
                exit_at_raw="2026-03-09 16:05",
                entry_price=Decimal("105"),
                exit_price=Decimal("106"),
                quantity=Decimal("5"),
                net_pnl=Decimal("-5"),
                return_pct=Decimal("-0.952381"),
                duration_minutes=10,
                entry_signal="fade",
                exit_signal="stop",
            ),
            StrategyRunTrade(
                run_id=ready_run.id,
                trade_number=3,
                direction="long",
                entry_at=datetime(2026, 3, 10, 13, 31),
                exit_at=datetime(2026, 3, 10, 13, 45),
                net_pnl=Decimal("0"),
                duration_minutes=14,
            ),
            StrategyRunTrade(
                run_id=ready_run.id,
                trade_number=4,
                direction="short",
                entry_at=datetime(2026, 3, 11, 13, 31),
                exit_at=datetime(2026, 3, 11, 13, 50),
                net_pnl=None,
                duration_minutes=19,
            ),
            StrategyRunTrade(
                run_id=pending_run.id,
                trade_number=1,
                direction="long",
                entry_at=datetime(2026, 3, 12, 14, 0),
                exit_at=datetime(2026, 3, 12, 14, 15),
                net_pnl=Decimal("10"),
            ),
        ]
        session.add_all(trades)
        session.add(
            StrategyRunMetrics(
                run_id=ready_run.id,
                calculation_version=CALCULATION_VERSION,
                calculated_at=datetime(2026, 4, 3, 12, 5),
                trade_count=4,
                total_net_pnl=Decimal("15"),
                net_return_pct=Decimal("0.06"),
                expectancy=Decimal("5"),
                max_drawdown_pct=Decimal("0.02"),
                win_rate=Decimal("0.333333"),
                equity_curve_json='[{"METRIC_CURVE_MUST_NOT_LEAK":true}]',
            )
        )
        session.add(
            StrategyRunMetrics(
                run_id=stale_run.id,
                calculation_version="strategy_metrics_v0",
                calculated_at=datetime(2026, 4, 1, 12, 5),
                trade_count=0,
            )
        )
        session.commit()

        return {
            "primary_strategy": primary.id,
            "secondary_strategy": secondary.id,
            "baseline_version": baseline.id,
            "challenger_version": challenger.id,
            "unrelated_version": unrelated.id,
            "ready_run": ready_run.id,
            "pending_run": pending_run.id,
            "stale_run": stale_run.id,
        }


def _selects(statements: list[str]) -> list[str]:
    return [
        statement
        for statement in statements
        if statement.lstrip().upper().startswith("SELECT")
    ]


def test_run_list_is_paginated_filterable_and_lightweight(
    client: TestClient,
    seeded: dict[str, uuid.UUID],
    sql_statements: list[str],
) -> None:
    sql_statements.clear()
    response = client.get("/strategy-lab/runs?limit=2&offset=0")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 3
    assert body["limit"] == 2
    assert body["offset"] == 0
    assert [row["id"] for row in body["items"]] == [
        str(seeded["ready_run"]),
        str(seeded["pending_run"]),
    ]
    assert body["items"][0]["metrics_status"] == "ready"
    assert body["items"][1]["metrics_status"] == "pending"
    assert body["items"][0]["trade_count"] == 4
    assert body["items"][0]["total_net_pnl"] == "15.000000"
    assert body["items"][0]["observed_start_at"] == "2026-03-09T13:30:00"
    assert body["items"][0]["observed_end_at"] == "2026-03-11T13:50:00"

    summary_fields = {
        "id",
        "strategy_definition_id",
        "strategy_name",
        "setup_type",
        "strategy_version_id",
        "version_label",
        "version_status",
        "symbol",
        "timeframe",
        "source_timezone",
        "backtest_start",
        "backtest_end",
        "observed_start_at",
        "observed_end_at",
        "currency",
        "source_file_name",
        "imported_at",
        "trade_count",
        "metrics_status",
        "metrics_calculated_at",
        "total_net_pnl",
        "net_return_pct",
        "expectancy",
        "max_drawdown_pct",
        "win_rate",
    }
    assert set(body["items"][0]) == summary_fields
    assert len(_selects(sql_statements)) == 2
    selected_sql = " ".join(_selects(sql_statements)).lower()
    for excluded in (
        "source_csv_text",
        "source_headers_json",
        "source_mapping_json",
        "source_warnings_json",
        "pine_source",
        "equity_curve_json",
    ):
        assert excluded not in selected_sql
    assert "MUST_NOT_LEAK" not in response.text

    second_page = client.get("/strategy-lab/runs?limit=2&offset=2").json()
    assert [row["id"] for row in second_page["items"]] == [
        str(seeded["stale_run"])
    ]
    assert second_page["items"][0]["metrics_status"] == "stale"

    by_strategy = client.get(
        f"/strategy-lab/runs?strategy_id={seeded['primary_strategy']}"
    ).json()
    assert by_strategy["total"] == 2
    assert {row["id"] for row in by_strategy["items"]} == {
        str(seeded["ready_run"]),
        str(seeded["pending_run"]),
    }
    by_version = client.get(
        f"/strategy-lab/runs?version_id={seeded['challenger_version']}"
    ).json()
    assert by_version["total"] == 1
    assert by_version["items"][0]["id"] == str(seeded["pending_run"])
    mismatched = client.get(
        "/strategy-lab/runs"
        f"?strategy_id={seeded['secondary_strategy']}"
        f"&version_id={seeded['baseline_version']}"
    ).json()
    assert mismatched["total"] == 0
    assert mismatched["items"] == []


def test_run_detail_returns_assumptions_without_large_artifacts(
    client: TestClient,
    seeded: dict[str, uuid.UUID],
    sql_statements: list[str],
) -> None:
    sql_statements.clear()
    response = client.get(f"/strategy-lab/runs/{seeded['ready_run']}")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["strategy_name"] == "VWAP Reclaim"
    assert body["version_label"] == "v1"
    assert body["version_hypothesis"].startswith("A confirmed reclaim")
    assert body["version_change_summary"] == "Establish the baseline."
    assert body["version_fingerprint"] == "a" * 64
    assert body["source"] == "tradingview"
    assert body["initial_capital"] == "25000.000000"
    assert body["parameters"] == {"rvol_min": 1.5}
    assert body["commission_value"] == "1.250000"
    assert body["slippage_value"] == "2.000000"
    assert body["notes"] == "March baseline."
    assert body["source_warning_count"] == 2
    assert "source_csv_text" not in body
    assert "source_warnings" not in body
    assert "pine_source" not in body
    assert "equity_curve" not in body
    assert "MUST_NOT_LEAK" not in response.text

    selects = _selects(sql_statements)
    assert len(selects) == 2
    selected_sql = selects[0].lower()
    warning_count_sql = selects[1].lower()
    assert "source_warnings_json" not in selected_sql
    assert "json_array_length" in warning_count_sql
    assert "source_warnings_json" in warning_count_sql
    for excluded in (
        "source_csv_text",
        "source_headers_json",
        "source_mapping_json",
        "source_warnings_json",
        "pine_source",
        "equity_curve_json",
    ):
        assert excluded not in selected_sql

    missing = client.get(f"/strategy-lab/runs/{uuid.uuid4()}")
    assert missing.status_code == 404
    assert missing.json()["detail"] == "Strategy run not found"


def test_run_trades_are_paged_filtered_by_source_day_and_lightweight(
    client: TestClient,
    seeded: dict[str, uuid.UUID],
    sql_statements: list[str],
) -> None:
    run_id = seeded["ready_run"]
    sql_statements.clear()
    response = client.get(
        f"/strategy-lab/runs/{run_id}/trades?limit=2&offset=1"
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 4
    assert body["limit"] == 2
    assert body["offset"] == 1
    assert [row["trade_number"] for row in body["items"]] == [2, 3]
    assert body["items"][0]["net_pnl"] == "-5.000000"
    assert set(body["items"][0]) == {
        "id",
        "run_id",
        "trade_number",
        "direction",
        "entry_at",
        "exit_at",
        "entry_at_raw",
        "exit_at_raw",
        "entry_price",
        "exit_price",
        "quantity",
        "net_pnl",
        "return_pct",
        "mfe",
        "mfe_pct",
        "mae",
        "mae_pct",
        "cumulative_pnl",
        "cumulative_return_pct",
        "duration_bars",
        "duration_minutes",
        "entry_signal",
        "exit_signal",
        "created_at",
    }
    assert "MUST_NOT_LEAK" not in response.text
    selects = _selects(sql_statements)
    assert len(selects) == 3
    selected_sql = " ".join(selects).lower()
    for excluded in (
        "entry_comment",
        "exit_comment",
        "feature_snapshot_json",
        "raw_entry_row_json",
        "raw_exit_row_json",
    ):
        assert excluded not in selected_sql

    assert client.get(
        f"/strategy-lab/runs/{run_id}/trades?direction=short"
    ).json()["total"] == 2
    assert client.get(
        f"/strategy-lab/runs/{run_id}/trades?outcome=winner"
    ).json()["items"][0]["trade_number"] == 1
    assert client.get(
        f"/strategy-lab/runs/{run_id}/trades?outcome=loser"
    ).json()["items"][0]["trade_number"] == 2
    assert client.get(
        f"/strategy-lab/runs/{run_id}/trades?outcome=breakeven"
    ).json()["items"][0]["trade_number"] == 3
    assert client.get(
        f"/strategy-lab/runs/{run_id}/trades?outcome=unknown"
    ).json()["items"][0]["trade_number"] == 4

    # March 9 is already EDT. The source-local day maps to 04:00 UTC through
    # the next 04:00 UTC and includes both the 09:30 and 15:55 ET entries.
    source_day = client.get(
        f"/strategy-lab/runs/{run_id}/trades"
        "?entry_date_from=2026-03-09&entry_date_to=2026-03-09"
    ).json()
    assert [row["trade_number"] for row in source_day["items"]] == [1, 2]
    combined = client.get(
        f"/strategy-lab/runs/{run_id}/trades"
        "?direction=short&outcome=loser"
        "&entry_date_from=2026-03-09&entry_date_to=2026-03-09"
    ).json()
    assert [row["trade_number"] for row in combined["items"]] == [2]

    invalid_range = client.get(
        f"/strategy-lab/runs/{run_id}/trades"
        "?entry_date_from=2026-03-10&entry_date_to=2026-03-09"
    )
    assert invalid_range.status_code == 422
    assert "on or before" in invalid_range.json()["detail"]
    assert client.get(
        f"/strategy-lab/runs/{run_id}/trades?direction=sideways"
    ).status_code == 422
    assert client.get(
        f"/strategy-lab/runs/{run_id}/trades?limit=501"
    ).status_code == 422
    assert client.get(
        f"/strategy-lab/runs/{uuid.uuid4()}/trades"
    ).status_code == 404


def test_run_trades_reject_an_invalid_stored_timezone(
    client: TestClient,
    test_engine,
    seeded: dict[str, uuid.UUID],
) -> None:
    with Session(test_engine) as session:
        run = session.get(StrategyRun, seeded["ready_run"])
        assert run is not None
        run.source_timezone = "Mars/Olympus"
        session.add(run)
        session.commit()

    response = client.get(
        f"/strategy-lab/runs/{seeded['ready_run']}/trades"
    )
    assert response.status_code == 422
    assert "invalid source timezone" in response.json()["detail"]
