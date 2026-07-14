from __future__ import annotations

import uuid
from collections.abc import Generator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.database import get_session
from app.models import StrategyRun
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


def _create_strategy(client: TestClient, name: str, **overrides: Any) -> dict[str, Any]:
    payload = {
        "name": name,
        "description": f"Research plan for {name}",
        "setup_type": "trend",
        **overrides,
    }
    response = client.post("/strategy-lab/strategies", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _version_payload(label: str, **overrides: Any) -> dict[str, Any]:
    return {
        "version_label": label,
        "pine_source": "//@version=6\nstrategy('Research strategy')",
        "source_reference": "tradingview://research-strategy",
        "change_summary": "Initial controlled baseline",
        "hypothesis": "The baseline establishes a comparison point.",
        "parameters": {"ema_length": 9, "filters": {"rvol": 1.5}},
        "entry_rule_summary": "Enter on the confirmed EMA reclaim.",
        "exit_rule_summary": "Exit on a close below the EMA.",
        "execution_timing": "bar_close",
        "session_mode": "regular",
        "commission_type": "cash_per_order",
        "commission_value": "1.25",
        "slippage_type": "ticks",
        "slippage_value": "2",
        "pyramiding": 1,
        "known_limitations": "Not yet tested outside liquid index ETFs.",
        "repainting_risk_notes": "Signals use confirmed bars only.",
        "lookahead_risk_notes": "No lookahead calls are used.",
        "status": "draft",
        **overrides,
    }


def _create_version(
    client: TestClient,
    strategy_id: str,
    label: str,
    **overrides: Any,
) -> dict[str, Any]:
    response = client.post(
        f"/strategy-lab/strategies/{strategy_id}/versions",
        json=_version_payload(label, **overrides),
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_strategy_create_list_get_and_patch(client: TestClient) -> None:
    later = _create_strategy(client, "VWAP Reclaim")
    earlier = _create_strategy(
        client,
        "Opening Range Breakout",
        description="First 15-minute range.",
        setup_type="breakout",
    )

    response = client.get("/strategy-lab/strategies")
    assert response.status_code == 200
    assert [row["name"] for row in response.json()] == [
        "Opening Range Breakout",
        "VWAP Reclaim",
    ]
    assert all("versions" not in row for row in response.json())

    response = client.get(f"/strategy-lab/strategies/{earlier['id']}")
    assert response.status_code == 200
    assert response.json() == {**earlier, "versions": []}

    response = client.patch(
        f"/strategy-lab/strategies/{later['id']}",
        json={
            "name": "  VWAP Reclaim Long  ",
            "description": "  Confirmed reclaim entries.  ",
            "setup_type": "reversal",
        },
    )
    assert response.status_code == 200
    updated = response.json()
    assert updated["name"] == "VWAP Reclaim Long"
    assert updated["description"] == "Confirmed reclaim entries."
    assert updated["setup_type"] == "reversal"

    response = client.get(f"/strategy-lab/strategies/{later['id']}")
    assert response.status_code == 200
    assert response.json()["name"] == "VWAP Reclaim Long"


def test_version_labels_are_unique_per_strategy_and_conflict_rolls_back(
    client: TestClient,
) -> None:
    first_strategy = _create_strategy(client, "First strategy")
    second_strategy = _create_strategy(client, "Second strategy")

    _create_version(client, first_strategy["id"], "v1")
    same_label_elsewhere = _create_version(client, second_strategy["id"], "v1")
    assert same_label_elsewhere["version_label"] == "v1"

    duplicate = client.post(
        f"/strategy-lab/strategies/{first_strategy['id']}/versions",
        json=_version_payload("v1", pine_source="//@version=6\nstrategy('Duplicate')"),
    )
    assert duplicate.status_code == 409
    assert "already has a version with that label" in duplicate.json()["detail"]

    # The IntegrityError path must roll the session back so later writes work.
    after_conflict = _create_version(client, first_strategy["id"], "v2")
    assert after_conflict["version_label"] == "v2"

    detail = client.get(
        f"/strategy-lab/strategies/{first_strategy['id']}"
    ).json()
    assert {version["version_label"] for version in detail["versions"]} == {
        "v1",
        "v2",
    }
    assert all("pine_source" not in version for version in detail["versions"])


def test_fork_copies_source_parameters_and_assumptions(client: TestClient) -> None:
    strategy = _create_strategy(client, "Forkable strategy")
    source = _create_version(client, strategy["id"], "1.0.0")

    response = client.post(
        f"/strategy-lab/versions/{source['id']}/fork",
        json={
            "version_label": "1.1.0",
            "change_summary": "Require stronger relative volume.",
            "hypothesis": "A stricter filter will improve expectancy.",
        },
    )
    assert response.status_code == 201, response.text
    forked = response.json()

    assert forked["id"] != source["id"]
    assert forked["strategy_definition_id"] == strategy["id"]
    assert forked["parent_version_id"] == source["id"]
    assert forked["version_label"] == "1.1.0"
    assert forked["change_summary"] == "Require stronger relative volume."
    assert forked["hypothesis"] == "A stricter filter will improve expectancy."
    assert forked["status"] == "challenger"

    copied_fields = (
        "pine_source",
        "source_reference",
        "source_fingerprint",
        "parameters",
        "entry_rule_summary",
        "exit_rule_summary",
        "execution_timing",
        "session_mode",
        "commission_type",
        "commission_value",
        "slippage_type",
        "slippage_value",
        "pyramiding",
        "known_limitations",
        "repainting_risk_notes",
        "lookahead_risk_notes",
    )
    for field in copied_fields:
        assert forked[field] == source[field], field

    source_after_fork = client.get(
        f"/strategy-lab/versions/{source['id']}"
    ).json()
    assert source_after_fork == source


def test_parent_version_must_belong_to_same_strategy(client: TestClient) -> None:
    first_strategy = _create_strategy(client, "Parent strategy")
    second_strategy = _create_strategy(client, "Unrelated strategy")
    parent = _create_version(client, first_strategy["id"], "v1")

    response = client.post(
        f"/strategy-lab/strategies/{second_strategy['id']}/versions",
        json=_version_payload("v2", parent_version_id=parent["id"]),
    )
    assert response.status_code == 422
    assert response.json() == {
        "detail": "Parent version must belong to the same strategy"
    }

    second_detail = client.get(
        f"/strategy-lab/strategies/{second_strategy['id']}"
    ).json()
    assert second_detail["versions"] == []


def test_version_validation_rejects_invalid_status_costs_and_unknown_fields(
    client: TestClient,
) -> None:
    strategy = _create_strategy(client, "Validated strategy")

    invalid_status = client.post(
        f"/strategy-lab/strategies/{strategy['id']}/versions",
        json=_version_payload("bad-status", status="live"),
    )
    assert invalid_status.status_code == 422

    missing_cost = client.post(
        f"/strategy-lab/strategies/{strategy['id']}/versions",
        json=_version_payload(
            "missing-cost",
            commission_type="percent",
            commission_value=None,
        ),
    )
    assert missing_cost.status_code == 422
    assert missing_cost.json()["detail"] == (
        "commission_value is required when type is percent"
    )

    excessive_cost_precision = client.post(
        f"/strategy-lab/strategies/{strategy['id']}/versions",
        json=_version_payload(
            "cost-precision",
            commission_value="1.0000001",
        ),
    )
    assert excessive_cost_precision.status_code == 422

    oversized_pyramiding = client.post(
        f"/strategy-lab/strategies/{strategy['id']}/versions",
        json=_version_payload("pyramiding-overflow", pyramiding=2_147_483_648),
    )
    assert oversized_pyramiding.status_code == 422

    unknown_field = client.post(
        f"/strategy-lab/strategies/{strategy['id']}/versions",
        json={**_version_payload("unknown-field"), "magic_score": 99},
    )
    assert unknown_field.status_code == 422

    detail = client.get(f"/strategy-lab/strategies/{strategy['id']}").json()
    assert detail["versions"] == []


def test_champion_transition_is_scoped_and_demotes_previous_champion(
    client: TestClient,
) -> None:
    first_strategy = _create_strategy(client, "Champion strategy")
    former = _create_version(
        client,
        first_strategy["id"],
        "baseline",
        status="champion",
    )
    replacement = _create_version(
        client,
        first_strategy["id"],
        "challenger",
        status="challenger",
    )

    response = client.patch(
        f"/strategy-lab/versions/{replacement['id']}",
        json={"status": "champion"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "champion"

    first_detail = client.get(
        f"/strategy-lab/strategies/{first_strategy['id']}"
    ).json()
    statuses = {
        version["id"]: version["status"] for version in first_detail["versions"]
    }
    assert statuses[former["id"]] == "challenger"
    assert statuses[replacement["id"]] == "champion"
    assert list(statuses.values()).count("champion") == 1

    second_strategy = _create_strategy(client, "Independent champion strategy")
    independent = _create_version(
        client,
        second_strategy["id"],
        "baseline",
        status="champion",
    )
    assert independent["status"] == "champion"
    assert client.get(f"/strategy-lab/versions/{replacement['id']}").json()[
        "status"
    ] == "champion"


def test_unlocked_result_changes_recalculate_fingerprint(client: TestClient) -> None:
    strategy = _create_strategy(client, "Editable strategy")
    version = _create_version(client, strategy["id"], "draft")

    response = client.patch(
        f"/strategy-lab/versions/{version['id']}",
        json={
            "pine_source": "//@version=6\nstrategy('Changed research strategy')",
            "parameters": {"ema_length": 21, "filters": {"rvol": 2.0}},
        },
    )
    assert response.status_code == 200, response.text
    updated = response.json()
    assert updated["locked"] is False
    assert updated["pine_source"] != version["pine_source"]
    assert updated["parameters"] == {
        "ema_length": 21,
        "filters": {"rvol": 2.0},
    }
    assert updated["source_fingerprint"] != version["source_fingerprint"]

    persisted = client.get(f"/strategy-lab/versions/{version['id']}").json()
    assert persisted["source_fingerprint"] == updated["source_fingerprint"]


def test_run_locks_result_fields_but_allows_metadata_and_status_updates(
    client: TestClient,
    test_engine,
) -> None:
    strategy = _create_strategy(client, "Locked strategy")
    version = _create_version(client, strategy["id"], "tested")

    with Session(test_engine) as session:
        session.add(
            StrategyRun(
                strategy_version_id=uuid.UUID(version["id"]),
                version_fingerprint=version["source_fingerprint"],
                symbol="SPY",
                timeframe="5m",
                source_timezone="America/New_York",
            )
        )
        session.commit()

    detail = client.get(f"/strategy-lab/versions/{version['id']}")
    assert detail.status_code == 200
    assert detail.json()["locked"] is True

    locked_update = client.patch(
        f"/strategy-lab/versions/{version['id']}",
        json={"commission_value": "2.50", "pine_source": "strategy('mutated')"},
    )
    assert locked_update.status_code == 409
    assert locked_update.json()["detail"].startswith(
        "Version is locked because it has runs; fork it to change:"
    )
    assert "commission_value" in locked_update.json()["detail"]
    assert "pine_source" in locked_update.json()["detail"]

    allowed_update = client.patch(
        f"/strategy-lab/versions/{version['id']}",
        json={
            "status": "retired",
            "source_reference": "tradingview://archived-tested-version",
            "change_summary": "Retired after the initial evaluation.",
            "hypothesis": "Historical hypothesis retained for the audit trail.",
            "known_limitations": "The imported run only covered SPY.",
            "repainting_risk_notes": "Confirmed bars; reviewed after testing.",
            "lookahead_risk_notes": "No known lookahead after review.",
        },
    )
    assert allowed_update.status_code == 200, allowed_update.text
    updated = allowed_update.json()
    assert updated["locked"] is True
    assert updated["status"] == "retired"
    assert updated["source_reference"] == "tradingview://archived-tested-version"
    assert updated["known_limitations"] == "The imported run only covered SPY."
    assert updated["pine_source"] == version["pine_source"]
    assert updated["commission_value"] == version["commission_value"]
    assert updated["source_fingerprint"] == version["source_fingerprint"]

    persisted = client.get(f"/strategy-lab/versions/{version['id']}").json()
    assert persisted["status"] == "retired"
    assert persisted["source_fingerprint"] == version["source_fingerprint"]
