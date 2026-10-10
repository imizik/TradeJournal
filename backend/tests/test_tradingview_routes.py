from __future__ import annotations

from decimal import Decimal
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import event
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.database import get_session
from app.engine.tradingview import parse_alert_bytes
from app.engine.tradingview_alerts import persist_alert, serialize_snapshot
from app.routers import tradingview_alerts


BAR_TIME_MS = 1_737_561_600_000


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


def _payload(**overrides) -> dict:
    payload = {
        "v": 1,
        "indicator_version": "1.0.0",
        "alert_id": (
            "v1:1.0.0:AAPL:5:1737561600000:orb_break:long"
        ),
        "symbol": "AAPL",
        "timeframe": "5",
        "setup": "orb_break",
        "side": "long",
        "price": 214.32,
        "bar_time_ms": BAR_TIME_MS,
        "levels": {"or_high": 213.9, "vwap": 211.1},
        "context": {"above_vwap": True, "label": "ready"},
    }
    payload.update(overrides)
    return payload


def _raw_body(**overrides) -> bytes:
    return json.dumps(
        _payload(**overrides),
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def test_private_app_exposes_only_read_routes_for_stored_alerts():
    from app.main import app as private_app

    methods_by_path: dict[str, set[str]] = {}
    for route in private_app.routes:
        candidates = [(getattr(route, "path", None), route)]
        if hasattr(route, "original_router"):
            prefix = route.include_context.prefix
            candidates = [
                (prefix + child.path, child)
                for child in route.original_router.routes
            ]
        for path, candidate in candidates:
            if path is None:
                continue
            methods_by_path.setdefault(path, set()).update(
                getattr(candidate, "methods", set()) or set()
            )

    assert methods_by_path["/tradingview/alerts"] == {"GET"}
    assert methods_by_path["/tradingview/alerts/{alert_id}"] == {"GET"}
    assert "/tradingview/webhook" not in methods_by_path


def test_private_list_is_light_and_detail_is_explicit(
    alert_engine,
):
    raw_body = _raw_body()
    parsed = parse_alert_bytes(raw_body)
    marker = "deferred-secret-marker"
    with Session(alert_engine) as session:
        row = persist_alert(session, parsed, raw_body).alert
        row.analysis_status = "done"
        row.verdict = "wait"
        row.confidence = "medium"
        row.scorer_revision = "scalper-v1"
        row.assessment_json = json.dumps(
            {
                "request": {
                    "symbol": "AAPL",
                    "direction": "long",
                },
                "assessment": {
                    "verdict": "wait",
                    "confidence": "medium",
                    "reasons_against": [marker],
                },
            }
        )
        row.analysis_error = marker
        row.levels_json = serialize_snapshot(
            {
                "marker": marker,
                "maximum": Decimal("999999999999.123456789012"),
                "minimum": Decimal("0.000000000001"),
                "number": Decimal("1"),
                "string": "1",
            }
        )
        row.context_json = json.dumps({"flag": True, "marker": marker})
        session.add(row)
        session.commit()

    app = FastAPI()
    app.include_router(tradingview_alerts.router, prefix="/tradingview")

    def override_session():
        with Session(alert_engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    statements: list[str] = []

    def capture(_conn, _cursor, statement, _params, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(alert_engine, "before_cursor_execute", capture)
    try:
        with TestClient(app) as client:
            listing = client.get("/tradingview/alerts")
            detail = client.get(
                f"/tradingview/alerts/{parsed.alert_id}"
            )
            missing = client.get("/tradingview/alerts/missing")
            invalid = client.get("/tradingview/alerts?limit=0")
    finally:
        event.remove(alert_engine, "before_cursor_execute", capture)

    assert listing.status_code == 200
    assert len(listing.json()) == 1
    item = listing.json()[0]
    assert item["price"] == "214.32"
    for omitted in (
        "payload_json",
        "levels_json",
        "context_json",
        "assessment_json",
        "analysis_error",
        "levels",
        "context",
        "assessment",
    ):
        assert omitted not in item
    assert marker not in listing.text
    # One SELECT for the list. Detail and missing each make their own explicit
    # full query; response serialization must not lazy-load deferred fields.
    assert len(statements) == 3

    assert detail.status_code == 200
    detail_body = detail.json()
    assert detail_body["payload_json"] == raw_body.decode("utf-8")
    assert detail_body["levels"]["marker"] == {
        "type": "string",
        "value": marker,
    }
    assert detail_body["levels"]["maximum"] == {
        "type": "number",
        "value": "999999999999.123456789012",
    }
    assert detail_body["levels"]["minimum"] == {
        "type": "number",
        "value": "0.000000000001",
    }
    assert detail_body["levels"]["number"] == {
        "type": "number",
        "value": "1",
    }
    assert detail_body["levels"]["string"] == {
        "type": "string",
        "value": "1",
    }
    assert detail_body["context"]["flag"] == {
        "type": "boolean",
        "value": True,
    }
    assert (
        detail_body["assessment"]["assessment"]["verdict"]
        == "wait"
    )
    assert detail_body["analysis_error"] == marker
    assert missing.status_code == 404
    assert invalid.status_code == 422


@pytest.mark.parametrize(
    "query",
    [
        "symbol=%20",
        "setup=%20",
        "analysis_status=unknown",
    ],
)
def test_private_list_rejects_invalid_filters(alert_engine, query):
    app = FastAPI()
    app.include_router(tradingview_alerts.router, prefix="/tradingview")

    def override_session():
        with Session(alert_engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    with TestClient(app) as client:
        response = client.get(f"/tradingview/alerts?{query}")

    assert response.status_code == 422
