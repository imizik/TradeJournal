from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Generator
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.database import get_session
from app.engine.strategy_csv import MAX_CSV_BYTES
from app.models import StrategyRun, StrategyRunMetrics, StrategyRunTrade
from app.routers import strategy_lab


FIXTURES = Path(__file__).parent / "fixtures" / "tradingview"


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


def _fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _create_version(
    client: TestClient,
    *,
    strategy_name: str = "Import strategy",
    version_label: str = "v1",
) -> dict[str, Any]:
    strategy_response = client.post(
        "/strategy-lab/strategies",
        json={
            "name": f"{strategy_name}-{uuid.uuid4()}",
            "description": "A controlled TradingView import test.",
            "setup_type": "vwap_reclaim",
        },
    )
    assert strategy_response.status_code == 201, strategy_response.text
    strategy = strategy_response.json()
    version_response = client.post(
        f"/strategy-lab/strategies/{strategy['id']}/versions",
        json={
            "version_label": version_label,
            "pine_source": "//@version=6\nstrategy('Import test')",
            "change_summary": "Establish a baseline.",
            "hypothesis": "A confirmed reclaim improves expectancy.",
            "parameters": {"rvol_min": 1.5},
            "entry_rule_summary": "Confirmed reclaim.",
            "exit_rule_summary": "Target or stop.",
            "execution_timing": "bar_close",
            "session_mode": "regular",
            "commission_type": "cash_per_order",
            "commission_value": "1.25",
            "slippage_type": "ticks",
            "slippage_value": "2",
            "pyramiding": 0,
            "status": "draft",
        },
    )
    assert version_response.status_code == 201, version_response.text
    return version_response.json()


def _preview(
    client: TestClient,
    version: dict[str, Any],
    *,
    fixture: str = "paired_trades.csv",
    timezone: str = "America/New_York",
):
    return client.post(
        "/strategy-lab/imports/preview",
        data={
            "strategy_version_id": version["id"],
            "source_timezone": timezone,
        },
        files={"file": (fixture, _fixture_bytes(fixture), "text/csv")},
    )


def _metadata(
    version: dict[str, Any],
    source_sha256: str,
    preview_fingerprint: str,
    **overrides: Any,
) -> dict[str, Any]:
    return {
        "strategy_version_id": version["id"],
        "expected_version_fingerprint": version["source_fingerprint"],
        "expected_source_sha256": source_sha256,
        "expected_preview_fingerprint": preview_fingerprint,
        "symbol": "nbis",
        "timeframe": "5m",
        "source_timezone": "America/New_York",
        "backtest_start": "2026-01-01",
        "backtest_end": "2026-12-31",
        "initial_capital": "25000",
        "currency": "usd",
        "extended_hours": False,
        "notes": "  Baseline import.  ",
        **overrides,
    }


def _commit(
    client: TestClient,
    metadata: dict[str, Any],
    *,
    fixture: str = "paired_trades.csv",
    file_name: str | None = None,
):
    return client.post(
        "/strategy-lab/runs/import",
        data={"metadata": json.dumps(metadata)},
        files={
            "file": (
                file_name or fixture,
                _fixture_bytes(fixture),
                "text/csv",
            )
        },
    )


def test_preview_is_non_persistent_and_exposes_pairing_mapping_and_version(
    client: TestClient,
    test_engine,
) -> None:
    version = _create_version(client)

    response = _preview(client, version)

    assert response.status_code == 200, response.text
    body = response.json()
    source = _fixture_bytes("paired_trades.csv")
    assert body["source_sha256"] == hashlib.sha256(source).hexdigest()
    assert body["source_timezone"] == "America/New_York"
    assert len(body["preview_fingerprint"]) == 64
    assert body["mapping"]["trade_number"] == "Trade number"
    assert body["mapping"]["timestamp"] == "Date and time"
    assert body["source_row_count"] == 4
    assert body["accepted_row_count"] == 4
    assert body["rejected_row_count"] == 0
    assert body["accepted_trade_count"] == 2
    assert body["rejected_trade_count"] == 0
    assert body["can_commit"] is True
    assert body["duplicate_run_id"] is None
    assert body["preview_truncated"] is False
    assert body["observed_start_at"] == "2026-03-09T13:45:00"
    assert body["observed_end_at"] == "2026-11-06T16:00:00"
    assert body["version"]["id"] == version["id"]
    assert body["version"]["hypothesis"] == version["hypothesis"]
    assert body["version"]["parameters"] == {"rvol_min": 1.5}
    assert body["version"]["commission_value"] == "1.250000"
    assert {trade["trade_number"] for trade in body["trades"]} == {101, 102}

    with Session(test_engine) as session:
        assert session.exec(select(StrategyRun)).all() == []
        assert session.exec(select(StrategyRunTrade)).all() == []


def test_commit_persists_run_and_trades_atomically_and_locks_version(
    client: TestClient,
    test_engine,
) -> None:
    version = _create_version(client)
    preview = _preview(client, version).json()

    response = _commit(
        client,
        _metadata(
            version,
            preview["source_sha256"],
            preview["preview_fingerprint"],
        ),
        file_name="../paired_trades.csv",
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["strategy_version_id"] == version["id"]
    assert body["version_fingerprint"] == version["source_fingerprint"]
    assert body["source_sha256"] == preview["source_sha256"]
    assert body["source_file_name"] == "paired_trades.csv"
    assert body["imported_trade_count"] == 2
    assert body["imported_row_count"] == 4
    assert body["skipped_row_count"] == 0
    assert body["rejected_row_count"] == 0
    assert body["metrics_status"] == "pending"

    with Session(test_engine) as session:
        runs = list(session.exec(select(StrategyRun)).all())
        assert len(runs) == 1
        run = runs[0]
        trades = list(
            session.exec(
                select(StrategyRunTrade)
                .where(StrategyRunTrade.run_id == run.id)
                .order_by(StrategyRunTrade.trade_number)
            ).all()
        )
        assert run.symbol == "NBIS"
        assert run.timeframe == "5m"
        assert run.source_timezone == "America/New_York"
        assert run.currency == "USD"
        assert run.notes == "Baseline import."
        assert run.commission_type == "cash_per_order"
        assert run.commission_value == 1.25
        assert run.slippage_type == "ticks"
        assert run.slippage_value == 2
        assert json.loads(run.parameters_json) == {"rvol_min": 1.5}
        assert json.loads(run.source_headers_json)[0] == "Trade number"
        assert json.loads(run.source_mapping_json)["type"] == "Type"
        stored_warnings = json.loads(run.source_warnings_json)
        assert len(stored_warnings) == body["warning_count"]
        assert {warning["code"] for warning in stored_warnings} == {
            "duplicate_value_mismatch"
        }
        assert run.source_csv_text is not None
        assert run.source_csv_text.startswith("Trade number,Type,")
        assert len(trades) == 2
        assert trades[0].net_pnl == 156.25
        assert json.loads(trades[0].raw_entry_row_json)["Type"] == "Entry long"
        assert session.get(StrategyRunMetrics, run.id) is None

    version_response = client.get(f"/strategy-lab/versions/{version['id']}")
    assert version_response.status_code == 200
    assert version_response.json()["locked"] is True


def test_duplicate_is_visible_in_preview_and_rejected_on_commit(
    client: TestClient,
    test_engine,
) -> None:
    version = _create_version(client)
    first_preview = _preview(client, version).json()
    first = _commit(
        client,
        _metadata(
            version,
            first_preview["source_sha256"],
            first_preview["preview_fingerprint"],
        ),
    )
    assert first.status_code == 201, first.text

    duplicate_preview = _preview(client, version)
    assert duplicate_preview.status_code == 200
    duplicate = duplicate_preview.json()
    assert duplicate["duplicate_run_id"] == first.json()["run_id"]
    assert duplicate["can_commit"] is False

    duplicate_commit = _commit(
        client,
        _metadata(
            version,
            first_preview["source_sha256"],
            first_preview["preview_fingerprint"],
        ),
    )
    assert duplicate_commit.status_code == 409
    assert "already imported" in duplicate_commit.json()["detail"]

    with Session(test_engine) as session:
        assert len(session.exec(select(StrategyRun)).all()) == 1
        assert len(session.exec(select(StrategyRunTrade)).all()) == 2


def test_commit_rejects_changed_file_and_changed_version(
    client: TestClient,
    test_engine,
) -> None:
    version = _create_version(client)
    preview = _preview(client, version).json()

    changed_timezone = _commit(
        client,
        _metadata(
            version,
            preview["source_sha256"],
            preview["preview_fingerprint"],
            source_timezone="UTC",
        ),
    )
    assert changed_timezone.status_code == 409
    assert "settings do not match" in changed_timezone.json()["detail"].lower()

    changed_file = _commit(
        client,
        _metadata(
            version,
            preview["source_sha256"],
            preview["preview_fingerprint"],
        ),
        fixture="feature_metadata.csv",
    )
    assert changed_file.status_code == 409
    assert "does not match" in changed_file.json()["detail"]

    changed_version = client.patch(
        f"/strategy-lab/versions/{version['id']}",
        json={"pine_source": "//@version=6\nstrategy('Changed after preview')"},
    )
    assert changed_version.status_code == 200, changed_version.text
    assert changed_version.json()["source_fingerprint"] != version["source_fingerprint"]

    stale_preview = _commit(
        client,
        _metadata(
            version,
            preview["source_sha256"],
            preview["preview_fingerprint"],
        ),
    )
    assert stale_preview.status_code == 409
    assert "version changed" in stale_preview.json()["detail"].lower()

    with Session(test_engine) as session:
        assert session.exec(select(StrategyRun)).all() == []
        assert session.exec(select(StrategyRunTrade)).all() == []


def test_preview_fingerprint_is_bound_to_version_identity(
    client: TestClient,
    test_engine,
) -> None:
    source_version = _create_version(client, strategy_name="Source")
    other_version = _create_version(client, strategy_name="Other")
    assert (
        source_version["source_fingerprint"]
        == other_version["source_fingerprint"]
    )
    preview = _preview(client, source_version).json()

    response = _commit(
        client,
        _metadata(
            other_version,
            preview["source_sha256"],
            preview["preview_fingerprint"],
        ),
    )
    assert response.status_code == 409
    assert "settings do not match" in response.json()["detail"].lower()

    with Session(test_engine) as session:
        assert session.exec(select(StrategyRun)).all() == []


def test_rejected_trade_groups_block_partial_commit(
    client: TestClient,
    test_engine,
) -> None:
    version = _create_version(client)
    preview_response = _preview(client, version, fixture="malformed.csv")
    assert preview_response.status_code == 200, preview_response.text
    preview = preview_response.json()
    assert preview["accepted_trade_count"] == 1
    assert preview["rejected_trade_count"] == 3
    assert preview["accepted_row_count"] == 2
    assert preview["rejected_row_count"] == 7
    assert preview["can_commit"] is False
    assert {row["trade_number"] for row in preview["rejected_trades"]} == {
        302,
        303,
        304,
    }

    response = _commit(
        client,
        _metadata(
            version,
            preview["source_sha256"],
            preview["preview_fingerprint"],
        ),
        fixture="malformed.csv",
    )
    assert response.status_code == 422
    assert "rejected trade group" in response.json()["detail"]

    with Session(test_engine) as session:
        assert session.exec(select(StrategyRun)).all() == []
        assert session.exec(select(StrategyRunTrade)).all() == []


def test_run_metadata_must_contain_trades_and_match_session_mode(
    client: TestClient,
    test_engine,
) -> None:
    version = _create_version(client)
    preview = _preview(client, version).json()

    excludes_trade = _commit(
        client,
        _metadata(
            version,
            preview["source_sha256"],
            preview["preview_fingerprint"],
            backtest_start="2026-04-01",
        ),
    )
    assert excludes_trade.status_code == 422
    assert "excludes an imported trade" in excludes_trade.json()["detail"]

    contradicts_session = _commit(
        client,
        _metadata(
            version,
            preview["source_sha256"],
            preview["preview_fingerprint"],
            extended_hours=True,
        ),
    )
    assert contradicts_session.status_code == 422
    assert "regular-session" in contradicts_session.json()["detail"]

    with Session(test_engine) as session:
        assert session.exec(select(StrategyRun)).all() == []


def test_preview_maps_oversize_to_413_and_invalid_timezone_to_422(
    client: TestClient,
) -> None:
    version = _create_version(client)

    invalid_timezone = _preview(client, version, timezone="Mars/Olympus")
    assert invalid_timezone.status_code == 422
    assert "timezone" in invalid_timezone.json()["detail"].lower()

    oversize = client.post(
        "/strategy-lab/imports/preview",
        data={
            "strategy_version_id": version["id"],
            "source_timezone": "UTC",
        },
        files={"file": ("too-large.csv", b"x" * (MAX_CSV_BYTES + 1), "text/csv")},
    )
    assert oversize.status_code == 413


def test_commit_metadata_must_be_valid_strict_json(
    client: TestClient,
    test_engine,
) -> None:
    version = _create_version(client)
    source = _fixture_bytes("paired_trades.csv")

    invalid_json = client.post(
        "/strategy-lab/runs/import",
        data={"metadata": "{"},
        files={"file": ("paired.csv", source, "text/csv")},
    )
    assert invalid_json.status_code == 422

    preview = _preview(client, version).json()
    unknown_field = _commit(
        client,
        _metadata(
            version,
            preview["source_sha256"],
            preview["preview_fingerprint"],
            unexpected=True,
        ),
    )
    assert unknown_field.status_code == 422

    excessive_precision = _commit(
        client,
        _metadata(
            version,
            preview["source_sha256"],
            preview["preview_fingerprint"],
            initial_capital="1.0000001",
        ),
    )
    assert excessive_precision.status_code == 422

    with Session(test_engine) as session:
        assert session.exec(select(StrategyRun)).all() == []


def test_run_metrics_recalculate_persists_reads_and_replaces_one_row(
    client: TestClient,
    test_engine,
) -> None:
    version = _create_version(client, strategy_name="Metrics lifecycle")
    preview = _preview(client, version).json()
    imported = _commit(
        client,
        _metadata(
            version,
            preview["source_sha256"],
            preview["preview_fingerprint"],
        ),
    )
    assert imported.status_code == 201, imported.text
    run_id = imported.json()["run_id"]

    missing = client.get(f"/strategy-lab/runs/{run_id}/metrics")
    assert missing.status_code == 404
    assert "not been calculated" in missing.json()["detail"]

    recalculated = client.post(
        f"/strategy-lab/runs/{run_id}/metrics/recalculate"
    )
    assert recalculated.status_code == 200, recalculated.text
    body = recalculated.json()
    assert body["run_id"] == run_id
    assert body["calculation_version"] == "strategy_metrics_v1"
    assert body["trade_count"] == 2
    assert body["winning_trades"] == 1
    assert body["losing_trades"] == 1
    assert body["win_rate"] == "0.500000"
    assert body["total_net_pnl"] == "81.250000"
    assert body["net_return_pct"] == "0.325000"
    assert body["top_1_profit_contribution_pct"] == "192.307692"
    assert body["coverage"]["accounting_complete"] is True
    assert body["coverage"]["chronology_complete"] is True
    assert body["equity_curve"][0]["sequence"] == 0
    assert body["drawdown_curve"][0]["sequence"] == 0
    assert body["findings"] == []

    stored = client.get(f"/strategy-lab/runs/{run_id}/metrics")
    assert stored.status_code == 200
    assert stored.json() == body

    with Session(test_engine) as session:
        trade = session.exec(
            select(StrategyRunTrade)
            .where(StrategyRunTrade.run_id == uuid.UUID(run_id))
            .order_by(StrategyRunTrade.trade_number)
        ).first()
        assert trade is not None
        trade.net_pnl = Decimal("200")
        session.add(trade)
        session.commit()

    replaced = client.post(
        f"/strategy-lab/runs/{run_id}/metrics/recalculate"
    )
    assert replaced.status_code == 200, replaced.text
    assert replaced.json()["total_net_pnl"] == "125.000000"
    assert replaced.json()["top_1_profit_contribution_pct"] == "160.000000"

    with Session(test_engine) as session:
        rows = list(
            session.exec(
                select(StrategyRunMetrics).where(
                    StrategyRunMetrics.run_id == uuid.UUID(run_id)
                )
            ).all()
        )
        assert len(rows) == 1


def test_run_metrics_missing_run_and_invalid_timezone_do_not_persist(
    client: TestClient,
    test_engine,
) -> None:
    missing_id = uuid.uuid4()
    assert client.get(
        f"/strategy-lab/runs/{missing_id}/metrics"
    ).status_code == 404
    assert client.post(
        f"/strategy-lab/runs/{missing_id}/metrics/recalculate"
    ).status_code == 404

    version = _create_version(client, strategy_name="Invalid metrics timezone")
    preview = _preview(client, version).json()
    imported = _commit(
        client,
        _metadata(
            version,
            preview["source_sha256"],
            preview["preview_fingerprint"],
        ),
    )
    assert imported.status_code == 201, imported.text
    run_id = uuid.UUID(imported.json()["run_id"])

    with Session(test_engine) as session:
        run = session.get(StrategyRun, run_id)
        assert run is not None
        run.source_timezone = "Mars/Olympus"
        session.add(run)
        session.commit()

    response = client.post(
        f"/strategy-lab/runs/{run_id}/metrics/recalculate"
    )
    assert response.status_code == 422
    assert "timezone" in response.json()["detail"].lower()

    with Session(test_engine) as session:
        assert session.get(StrategyRunMetrics, run_id) is None
