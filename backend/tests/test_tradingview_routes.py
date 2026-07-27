from __future__ import annotations

from decimal import Decimal
import json
import logging

from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import event
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.database import get_session
from app.engine.tradingview import MAX_ALERT_BODY_BYTES, parse_alert_bytes
from app.engine.tradingview_alerts import (
    TradingViewPersistenceBusyError,
    TradingViewPersistenceError,
    persist_alert,
    serialize_snapshot,
)
from app.models import TradingViewAlert
from app.routers import tradingview_alerts, tradingview_webhook
from app.tradingview_database import get_tradingview_session_factory
from app.tradingview_ingress import create_tradingview_ingress_app


TOKEN = "test_" + ("x" * 40)
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


def _build_ingress(engine, session_count: dict[str, int]) -> FastAPI:
    ingress = create_tradingview_ingress_app()

    def override_session_factory():
        def open_session():
            session_count["opened"] += 1
            return Session(engine)

        return open_session

    ingress.dependency_overrides[
        get_tradingview_session_factory
    ] = override_session_factory
    return ingress


def _post(
    client: TestClient,
    body: bytes,
    *,
    token: str | None = TOKEN,
    headers: dict[str, str] | None = None,
):
    params = {"token": token} if token is not None else None
    return client.post(
        "/tradingview/webhook",
        params=params,
        content=body,
        headers=headers,
    )


def test_webhook_persists_once_and_classifies_semantic_duplicate(
    alert_engine,
    monkeypatch,
):
    monkeypatch.setenv("TRADINGVIEW_WEBHOOK_TOKEN", TOKEN)
    session_count = {"opened": 0}
    app = _build_ingress(alert_engine, session_count)
    first_raw = _raw_body()
    second_raw = json.dumps(
        _payload(),
        indent=2,
        sort_keys=False,
    ).encode("utf-8")

    with TestClient(app) as client:
        first = _post(client, first_raw)
        duplicate = _post(client, second_raw)

    assert first.status_code == 200
    assert first.json() == {
        "accepted": True,
        "dup": False,
        "alert_id": _payload()["alert_id"],
        "analysis_status": "pending",
    }
    assert duplicate.status_code == 200
    assert duplicate.json()["dup"] is True
    assert session_count["opened"] == 2

    with Session(alert_engine) as session:
        rows = session.exec(select(TradingViewAlert)).all()
        assert len(rows) == 1
        assert rows[0].payload_json == first_raw.decode("utf-8")


@pytest.mark.parametrize(
    ("server_token", "request_token", "authorization", "status_code"),
    [
        (None, TOKEN, None, 503),
        ("   ", TOKEN, None, 503),
        ("too-short", "too-short", None, 503),
        (TOKEN, None, None, 401),
        (TOKEN, "wrong", None, 401),
        (TOKEN, None, "Basic abc", 401),
        (TOKEN, None, "Bearer wrong", 401),
        (TOKEN, "é", None, 401),
    ],
)
def test_webhook_auth_fails_closed_before_body_or_database(
    alert_engine,
    monkeypatch,
    server_token,
    request_token,
    authorization,
    status_code,
):
    if server_token is None:
        monkeypatch.delenv("TRADINGVIEW_WEBHOOK_TOKEN", raising=False)
    else:
        monkeypatch.setenv("TRADINGVIEW_WEBHOOK_TOKEN", server_token)
    session_count = {"opened": 0}
    parse_count = {"called": 0}
    app = _build_ingress(alert_engine, session_count)

    def fail_if_parsed(_body):
        parse_count["called"] += 1
        raise AssertionError("unauthorized body must not be parsed")

    monkeypatch.setattr(
        tradingview_webhook,
        "parse_alert_bytes",
        fail_if_parsed,
    )
    headers = (
        {"Authorization": authorization}
        if authorization is not None
        else None
    )

    with TestClient(app) as client:
        response = _post(
            client,
            b"x" * (MAX_ALERT_BODY_BYTES + 1),
            token=request_token,
            headers=headers,
        )

    assert response.status_code == status_code
    assert session_count["opened"] == 0
    assert parse_count["called"] == 0


def test_webhook_accepts_bearer_or_either_valid_credential(
    alert_engine,
    monkeypatch,
):
    monkeypatch.setenv("TRADINGVIEW_WEBHOOK_TOKEN", TOKEN)
    session_count = {"opened": 0}
    app = _build_ingress(alert_engine, session_count)

    with TestClient(app) as client:
        bearer = _post(
            client,
            _raw_body(),
            token=None,
            headers={"Authorization": f"bEaReR {TOKEN}"},
        )
        either = _post(
            client,
            _raw_body(),
            token=TOKEN,
            headers={"Authorization": "Bearer wrong"},
        )

    assert bearer.status_code == 200
    assert either.status_code == 200
    assert either.json()["dup"] is True


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"{",
        b"[]",
        b'{"v":1,"v":1}',
        b"\xff",
    ],
)
def test_webhook_rejects_invalid_contract_bodies(
    alert_engine,
    monkeypatch,
    body,
):
    monkeypatch.setenv("TRADINGVIEW_WEBHOOK_TOKEN", TOKEN)
    session_count = {"opened": 0}
    app = _build_ingress(alert_engine, session_count)

    with TestClient(app) as client:
        response = _post(client, body)

    assert response.status_code == 400
    assert session_count["opened"] == 0
    with Session(alert_engine) as session:
        assert session.exec(select(TradingViewAlert)).all() == []


def test_webhook_stream_enforces_hard_body_limit(
    alert_engine,
    monkeypatch,
):
    monkeypatch.setenv("TRADINGVIEW_WEBHOOK_TOKEN", TOKEN)
    session_count = {"opened": 0}
    app = _build_ingress(alert_engine, session_count)
    oversized = b"x" * (MAX_ALERT_BODY_BYTES + 1)

    with TestClient(app) as client:
        declared_large = _post(client, oversized)
        declared_small = _post(
            client,
            oversized,
            headers={"Content-Length": "1"},
        )

    assert declared_large.status_code == 413
    assert declared_small.status_code == 413
    assert session_count["opened"] == 0


def test_webhook_accepts_valid_body_at_exact_stream_limit(
    alert_engine,
    monkeypatch,
):
    monkeypatch.setenv("TRADINGVIEW_WEBHOOK_TOKEN", TOKEN)
    app = _build_ingress(alert_engine, {"opened": 0})
    raw = _raw_body()
    exact_limit = raw + (b" " * (MAX_ALERT_BODY_BYTES - len(raw)))

    with TestClient(app) as client:
        response = _post(client, exact_limit)

    assert len(exact_limit) == MAX_ALERT_BODY_BYTES
    assert response.status_code == 200


def test_webhook_collision_returns_409_and_preserves_first_evidence(
    alert_engine,
    monkeypatch,
):
    monkeypatch.setenv("TRADINGVIEW_WEBHOOK_TOKEN", TOKEN)
    app = _build_ingress(alert_engine, {"opened": 0})
    first_raw = _raw_body()
    changed_raw = _raw_body(price=215.01)

    with TestClient(app) as client:
        assert _post(client, first_raw).status_code == 200
        collision = _post(client, changed_raw)

    assert collision.status_code == 409
    assert collision.json() == {
        "detail": "TradingView alert identity collision"
    }
    with Session(alert_engine) as session:
        stored = session.get(TradingViewAlert, _payload()["alert_id"])
        assert stored is not None
        assert stored.payload_json == first_raw.decode("utf-8")


def test_webhook_maps_busy_and_unexpected_persistence_without_leaks(
    alert_engine,
    monkeypatch,
    caplog,
):
    monkeypatch.setenv("TRADINGVIEW_WEBHOOK_TOKEN", TOKEN)
    app = _build_ingress(alert_engine, {"opened": 0})
    caplog.set_level(
        logging.ERROR,
        logger="app.routers.tradingview_webhook",
    )

    def busy(*_args, **_kwargs):
        raise TradingViewPersistenceBusyError("sensitive driver detail")

    monkeypatch.setattr(tradingview_webhook, "persist_alert", busy)
    with TestClient(app) as client:
        response = _post(client, _raw_body())

    assert response.status_code == 503
    assert response.headers["retry-after"] == "2"
    assert "sensitive" not in response.text

    def rejected(*_args, **_kwargs):
        raise TradingViewPersistenceError("raw-payload-secret-marker")

    monkeypatch.setattr(tradingview_webhook, "persist_alert", rejected)
    with TestClient(app) as client:
        response = _post(client, _raw_body())

    assert response.status_code == 500
    assert response.json() == {
        "detail": "Unable to persist TradingView alert"
    }

    def unexpected(*_args, **_kwargs):
        raise RuntimeError("raw-payload-secret-marker")

    monkeypatch.setattr(tradingview_webhook, "persist_alert", unexpected)
    with TestClient(app) as client:
        response = _post(client, _raw_body())

    assert response.status_code == 500
    assert response.json() == {
        "detail": "Unable to persist TradingView alert"
    }
    assert "raw-payload-secret-marker" not in response.text
    application_logs = "\n".join(
        record.getMessage()
        for record in caplog.records
        if record.name == "app.routers.tradingview_webhook"
    )
    assert TOKEN not in application_logs
    assert "raw-payload-secret-marker" not in application_logs


def test_public_ingress_exposes_only_webhook_and_health(
    alert_engine,
    monkeypatch,
):
    monkeypatch.setenv("TRADINGVIEW_WEBHOOK_TOKEN", TOKEN)
    app = _build_ingress(alert_engine, {"opened": 0})
    public_routes = {
        (method, path)
        for route in app.routes
        for path, candidate in (
            [
                (
                    route.include_context.prefix + child.path,
                    child,
                )
                for child in route.original_router.routes
            ]
            if hasattr(route, "original_router")
            else [(getattr(route, "path", ""), route)]
        )
        if isinstance(candidate, APIRoute)
        for method in candidate.methods
    }
    assert public_routes == {
        ("GET", "/health"),
        ("POST", "/tradingview/webhook"),
    }

    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/tradingview/webhook").status_code == 405
        for path in (
            "/tradingview/alerts",
            "/fills",
            "/trades",
            "/stats",
            "/strategy-lab/strategies",
            "/docs",
            "/redoc",
            "/openapi.json",
        ):
            assert client.get(path).status_code == 404


def test_public_health_fails_closed_without_token_or_schema(
    alert_engine,
    monkeypatch,
):
    monkeypatch.delenv("TRADINGVIEW_WEBHOOK_TOKEN", raising=False)
    token_session_count = {"opened": 0}
    token_app = _build_ingress(alert_engine, token_session_count)
    with TestClient(token_app) as client:
        disabled = client.get("/health")

    assert disabled.status_code == 503
    assert token_session_count["opened"] == 0

    monkeypatch.setenv("TRADINGVIEW_WEBHOOK_TOKEN", TOKEN)
    missing_schema_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    schema_session_count = {"opened": 0}
    schema_app = _build_ingress(
        missing_schema_engine,
        schema_session_count,
    )
    with TestClient(schema_app) as client:
        missing_schema = client.get("/health")

    assert missing_schema.status_code == 503
    assert missing_schema.json() == {
        "detail": "TradingView ingress is not ready"
    }
    assert schema_session_count["opened"] == 1


def test_public_ingress_does_not_redirect_or_reflect_query_token(
    alert_engine,
    monkeypatch,
):
    monkeypatch.setenv("TRADINGVIEW_WEBHOOK_TOKEN", TOKEN)
    app = _build_ingress(alert_engine, {"opened": 0})

    with TestClient(app, follow_redirects=False) as client:
        response = client.post(
            f"/tradingview/webhook/?token={TOKEN}",
            content=_raw_body(),
        )

    assert response.status_code == 404
    assert all(
        TOKEN not in value
        for value in response.headers.values()
    )


def test_private_app_exposes_reads_but_not_public_webhook():
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

    assert "GET" in methods_by_path["/tradingview/alerts"]
    assert "GET" in methods_by_path["/tradingview/alerts/{alert_id}"]
    assert "/tradingview/webhook" not in methods_by_path


def test_private_worker_autostart_requires_explicit_flag(monkeypatch):
    from app.main import _tradingview_analysis_autostart_enabled

    monkeypatch.delenv("TRADINGVIEW_ANALYSIS_AUTOSTART", raising=False)
    monkeypatch.setenv("TRADINGVIEW_WEBHOOK_TOKEN", TOKEN)
    assert _tradingview_analysis_autostart_enabled() is False

    monkeypatch.setenv("TRADINGVIEW_ANALYSIS_AUTOSTART", "true")
    assert _tradingview_analysis_autostart_enabled() is True

    monkeypatch.setenv("TRADINGVIEW_ANALYSIS_AUTOSTART", "auto")
    assert _tradingview_analysis_autostart_enabled() is False


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
