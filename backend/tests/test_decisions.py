from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.database import get_session
from app.routers import decisions as routes


@pytest.fixture
def client(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    app = FastAPI()

    def session():
        with Session(engine) as db:
            yield db

    app.include_router(routes.router, prefix="/decisions")
    app.dependency_overrides[get_session] = session
    monkeypatch.setattr(routes, "build_ticker_analysis", lambda symbol: packet(symbol, close=100))
    with TestClient(app) as http:
        yield http
    engine.dispose()


def iso_ago(seconds=30):
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()


def packet(symbol="SPY", close=100):
    stamp = (datetime.now(timezone.utc) - timedelta(minutes=2)).replace(second=0, microsecond=0)
    return {"symbol": symbol, "generated_at": iso_ago(), "data_source": "alpaca_sip",
            "recent_minute_bars": [{"t": stamp.isoformat(), "o": close - 0.2, "h": close + 1,
                                     "l": close - 1, "c": close, "vw": close}]}


def freeze(client, operation_id="ctx-1"):
    response = client.post("/decisions/context/SPY", json={"operation_id": operation_id})
    assert response.status_code == 200, response.text
    return response.json()


def base(context, **overrides):
    result = {
        "operation_id": "op-1", "opportunity_id": "opp-1", "actor": "human",
        "decision": "skip", "symbol": "SPY", "context_id": context["context_id"],
        "rationale": "No clear setup",
    }
    result.update(overrides)
    return result


def take_payload(context, **plan_overrides):
    facts = {fact["name"]: fact for fact in context["price_facts"]}
    trigger_fact, stop_fact, target_fact = "minute:0:c", "minute:0:l", "minute:0:h"
    trigger = facts[trigger_fact]["value"]
    stop = facts[stop_fact]["value"]
    plan = {
        "instrument": "stock", "direction": "long",
        "trigger": {"kind": "close_beyond_level", "interval": "15m", "session": "regular"},
        "trigger_level": trigger, "trigger_fact": trigger_fact,
        "stop": stop, "stop_fact": stop_fact,
        "target": facts[target_fact]["value"], "target_fact": target_fact,
        "entry_guard": {"min": trigger, "max": trigger + 0.25},
        "expiry": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
        "max_holding_sessions": 2, "freshness_limit_seconds": 3600,
        "cost_model": {"version": "cost-v1", "slippage_bps": 1, "slippage_per_share": 0.01},
    }
    plan.update(plan_overrides)
    return base(context, decision="take", rationale="Valid structure", plan=plan)


def test_skip_records_are_immutable_and_idempotent_after_expiry(client):
    context = freeze(client)
    payload = base(context)
    first = client.post("/decisions", json=payload)
    assert first.status_code == 201
    saved = first.json()
    assert saved["status"] == "practice_draft_unarmed"
    # Idempotency is resolved before checking any time-dependent decision policy.
    assert client.post("/decisions", json=payload).json()["id"] == saved["id"]
    conflict = client.post("/decisions", json={**payload, "rationale": "changed"})
    assert conflict.status_code == 409
    assert client.patch(f"/decisions/{saved['id']}", json={"decision": "take"}).status_code == 405
    assert client.get(f"/decisions/{saved['id']}").json()["record_sha256"] == saved["record_sha256"]
    assert client.get("/decisions").json()["decisions"][0]["id"] == saved["id"]


def test_context_is_durable_and_later_packet_does_not_rewrite_decision(client, monkeypatch):
    first_context = freeze(client)
    monkeypatch.setattr(routes, "build_ticker_analysis", lambda symbol: packet(symbol, close=150))
    retry = freeze(client)
    assert retry["context_id"] == first_context["context_id"]
    assert retry["context_sha256"] == first_context["context_sha256"]
    payload = base(first_context)
    saved = client.post("/decisions", json=payload).json()
    second_context = freeze(client, "ctx-2")
    assert first_context["context_sha256"] != second_context["context_sha256"]
    reopened = client.get(f"/decisions/{saved['id']}").json()
    assert reopened["evidence"]["packet"]["recent_minute_bars"][0]["c"] == 100
    assert reopened["context_id"] == first_context["context_id"]


def test_context_serializes_live_analysis_datetime_and_retries_same_evidence(client, monkeypatch):
    live_packet = packet()
    as_of = datetime(2026, 10, 8, 10, 15)
    live_packet["short_term"] = {"entry_context_as_of": as_of}
    monkeypatch.setattr(routes, "build_ticker_analysis", lambda symbol: live_packet)
    context = freeze(client, "ctx-live-datetime")
    assert context["packet"]["short_term"]["entry_context_as_of"] == as_of.isoformat()
    retry = freeze(client, "ctx-live-datetime")
    assert retry == context
    saved = client.post("/decisions", json=base(context)).json()
    reopened = client.get(f"/decisions/{saved['id']}").json()
    assert reopened["evidence"]["packet"]["short_term"] == context["packet"]["short_term"]


def test_unavailable_context_still_records_wait_or_skip_but_cannot_support_take(client, monkeypatch):
    def unavailable(_symbol):
        raise RuntimeError("provider offline")

    monkeypatch.setattr(routes, "build_ticker_analysis", unavailable)
    context = freeze(client, "ctx-unavailable")
    assert context["price_facts"] == []
    saved = client.post("/decisions", json=base(context, operation_id="op-unavailable")).json()
    assert saved["evidence"]["context_state"] == "unavailable"
    monkeypatch.setattr(routes, "build_ticker_analysis", lambda symbol: packet(symbol, close=100))
    valid_plan = take_payload(freeze(client, "ctx-with-facts"), operation_id="op-take-unavailable")
    valid_plan["context_id"] = context["context_id"]
    rejected = client.post("/decisions", json=valid_plan)
    assert rejected.status_code == 422


@pytest.mark.parametrize("session", [
    {"date": "2026-11-26", "status": "closed", "open": None, "close": None,
     "description": "Thanksgiving Day", "source": "tradier"},
    {"date": "2026-11-27", "status": "open", "open": 240, "close": 780,
     "description": "Early close", "source": "tradier"},
])
def test_context_freezes_holiday_and_early_close_calendar_metadata(client, monkeypatch, session):
    monkeypatch.setattr(routes.chart_calendar, "hours", lambda _day: session)
    context = freeze(client, f"ctx-calendar-{session['date']}")
    assert context["packet"]["session_calendar"] == session
    # Context retries retrieve the original session facts as well as prices.
    monkeypatch.setattr(routes.chart_calendar, "hours", lambda _day: None)
    retry = freeze(client, f"ctx-calendar-{session['date']}")
    assert retry["context_sha256"] == context["context_sha256"]
    assert retry["packet"]["session_calendar"] == session


def test_context_operation_key_for_another_symbol_returns_conflict(client):
    freeze(client, "ctx-symbol-conflict")
    response = client.post("/decisions/context/QQQ", json={"operation_id": "ctx-symbol-conflict"})
    assert response.status_code == 409
    assert "different symbol" in response.json()["detail"]


def test_wait_requires_condition_and_expiry(client, monkeypatch):
    context = freeze(client)
    payload = base(context, decision="wait", rationale="Wait for a close",
                   wait_condition="15m close above 100", wait_expiry=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat())
    response = client.post("/decisions", json=payload)
    assert response.status_code == 201
    original_datetime = routes.decisions.datetime

    class AfterExpiry(original_datetime):
        @classmethod
        def now(cls, tz=None):
            return original_datetime.now(tz) + timedelta(days=2)

    # The same operation remains idempotent after its WAIT deadline passes.
    import app.engine.decisions as decision_engine
    monkeypatch.setattr(decision_engine, "datetime", AfterExpiry)
    assert client.post("/decisions", json=payload).json()["id"] == response.json()["id"]
    assert client.post("/decisions", json=base(context, operation_id="op-wait-invalid", decision="wait")).status_code == 422


def test_take_requires_context_provenance_and_finite_values(client):
    context = freeze(client)
    payload = take_payload(context)
    response = client.post("/decisions", json=payload)
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "practice_draft_unarmed"

    # Caller cannot replace evidence on a saved context; unknown context is rejected.
    invalid = {**payload, "context_id": "00000000-0000-0000-0000-000000000000", "operation_id": "op-stale"}
    assert client.post("/decisions", json=invalid).status_code == 422

    nonfinite = take_payload(context, trigger_level="NaN")
    assert client.post("/decisions", json={**nonfinite, "operation_id": "op-nan"}).status_code == 422
    unknown_fact = {**payload, "operation_id": "op-unknown", "plan": {**payload["plan"], "target_fact": "caller:invented"}}
    assert client.post("/decisions", json=unknown_fact).status_code == 422


def test_take_rejects_old_source_bar_against_declared_freshness(client, monkeypatch):
    old = (datetime.now(timezone.utc) - timedelta(hours=2)).replace(second=0, microsecond=0)
    old_packet = {"symbol": "SPY", "generated_at": iso_ago(), "data_source": "alpaca_sip",
                  "recent_minute_bars": [{"t": old.isoformat(), "o": 99.8, "h": 101,
                                           "l": 99, "c": 100, "vw": 100}]}
    monkeypatch.setattr(routes, "build_ticker_analysis", lambda symbol: old_packet)
    context = freeze(client, "ctx-old")
    payload = take_payload(context)
    payload["plan"]["freshness_limit_seconds"] = 3600
    assert client.post("/decisions", json=payload).status_code == 422
