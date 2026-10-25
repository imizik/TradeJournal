"""Blind-segment boundary and durable retry behavior for personal fixture replay."""
import json
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.database import get_session
from app.main import app as main_app
from app.engine import personal_replay as replay_engine
from app.models import PracticeReplayAttempt
from app.routers import personal_replay
from tests.test_browser_access import boundary as boundary, signin


@pytest.fixture
def client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    app = FastAPI()
    app.state.replay_test_engine = engine

    def session():
        with Session(engine) as db:
            yield db

    app.include_router(personal_replay.router, prefix="/practice")
    app.dependency_overrides[get_session] = session
    with TestClient(app) as http:
        yield http
    engine.dispose()


def begin(client):
    response = client.post("/practice/replay/attempts", json={"operation_id": str(uuid.uuid4())})
    assert response.status_code == 201, response.text
    return response.json()


def test_catalog_and_initial_attempt_never_include_sealed_information(client):
    catalog = client.get("/practice/replay/scenarios").json()["scenarios"]
    assert catalog[0]["id"] == "synthetic-option-position-v1"
    state = begin(client)
    assert state["phase"] == "decision"
    assert state["checkpoint"]["id"] == "first-look"
    assert state["checkpoint"]["decision_received_at"] is None
    assert state["checkpoint"]["chart_context"]["provider"] == "sample_fixture"
    assert len(state["checkpoint"]["bars"]) == 59
    serialized = str(state).lower()
    for forbidden in ("final_outcome", "actual_action", "260.0", "later-look"):
        assert forbidden not in serialized
    cutoff = state["checkpoint"]["input_cutoff"]
    for bar in state["checkpoint"]["bars"]:
        assert bar["interval_end"] <= cutoff
        assert bar["published_at"] <= cutoff
    for key in ("mark_time", "mark_observed_at", "mark_published_at", "mark_retrieved_at"):
        assert state["checkpoint"]["position"][key] <= cutoff


def test_decision_then_sequential_reveals_and_idempotent_retries(client):
    state = begin(client)
    attempt_id = state["attempt_id"]
    first_choice = {"checkpoint_id": "first-look", "decision": "reduce", "rationale": "Protect some gain."}
    assert client.post(f"/practice/replay/attempts/{attempt_id}/reveal", json={"checkpoint_id": "first-look"}).status_code == 409
    saved = client.post(f"/practice/replay/attempts/{attempt_id}/choice", json=first_choice)
    assert saved.status_code == 200, saved.text
    assert saved.json()["checkpoint"]["decision_received_at"]
    retry = client.post(f"/practice/replay/attempts/{attempt_id}/choice", json=first_choice)
    assert retry.status_code == 200
    assert retry.json()["choice"]["decision"] == "reduce"
    assert client.post(f"/practice/replay/attempts/{attempt_id}/choice", json={**first_choice, "decision": "exit"}).status_code == 409

    first_reveal = client.post(f"/practice/replay/attempts/{attempt_id}/reveal", json={"checkpoint_id": "first-look"})
    assert first_reveal.status_code == 200, first_reveal.text
    revealed = first_reveal.json()
    assert revealed["revealed"][0]["actual_action"]["decision"] == "held"
    assert revealed["revealed"][0]["choice"]["decision"] == "reduce"
    assert revealed["checkpoint"]["id"] == "later-look"
    assert "final_outcome" not in str(revealed)
    assert client.post(f"/practice/replay/attempts/{attempt_id}/reveal", json={"checkpoint_id": "first-look"}).json() == revealed
    assert client.post(f"/practice/replay/attempts/{attempt_id}/reveal", json={"checkpoint_id": "later-look"}).status_code == 409

    second_choice = {"checkpoint_id": "later-look", "decision": "hold"}
    assert client.post(f"/practice/replay/attempts/{attempt_id}/choice", json=second_choice).status_code == 200
    final = client.post(f"/practice/replay/attempts/{attempt_id}/reveal", json={"checkpoint_id": "later-look"})
    assert final.status_code == 200
    result = final.json()
    assert result["phase"] == "complete" and result["checkpoint"] is None
    assert result["revealed"][1]["choice"]["decision"] == "hold"
    assert result["revealed"][1]["final_outcome"]["pnl"]["value"] == 100.0
    assert result["revealed"][1]["final_outcome"]["later_retrospective_rationale"]["status"] == "unavailable"
    assert client.get(f"/practice/replay/attempts/{attempt_id}").json() == result


def test_unknown_and_out_of_order_checkpoint_writes_refused(client):
    state = begin(client)
    attempt_id = state["attempt_id"]
    assert client.post(f"/practice/replay/attempts/{attempt_id}/choice", json={"checkpoint_id": "later-look", "decision": "hold"}).status_code == 409
    assert client.post(f"/practice/replay/attempts/{attempt_id}/choice", json={"checkpoint_id": "first-look", "decision": "sell-all"}).status_code == 409
    assert client.post(f"/practice/replay/attempts/{attempt_id}/choice", json={"checkpoint_id": "first-look", "decision": "hold", "rationale": "x" * 501}).status_code == 422
    assert client.post(f"/practice/replay/attempts/{attempt_id}/reveal", json={"checkpoint_id": "first-look"}).status_code == 409
    assert client.post(f"/practice/replay/attempts/{attempt_id}/choice", json={"checkpoint_id": "first-look", "decision": "hold", "rationale": "ok"}).status_code == 200
    assert client.post(f"/practice/replay/attempts/{attempt_id}/reveal", json={"checkpoint_id": "later-look"}).status_code == 409


def test_create_operation_retry_returns_original_and_new_attempt_is_marked_repeat(client):
    op = str(uuid.uuid4())
    first = client.post("/practice/replay/attempts", json={"operation_id": op}).json()
    retry = client.post("/practice/replay/attempts", json={"operation_id": op}).json()
    assert retry["attempt_id"] == first["attempt_id"]
    assert retry["repeated"] is False
    later = begin(client)
    assert later["repeated"] is True
    scenario = client.get("/practice/replay/scenarios").json()["scenarios"][0]
    assert scenario["repeat_status"] == "repeat"
    assert scenario["latest_attempt_id"] == later["attempt_id"]


def test_missing_attempt_and_invalid_request_are_bounded(client):
    missing = uuid.uuid4()
    assert client.get(f"/practice/replay/attempts/{missing}").status_code == 404
    assert client.post(f"/practice/replay/attempts/{missing}/choice", json={"checkpoint_id": "first-look", "decision": "hold"}).status_code == 404
    assert client.post("/practice/replay/attempts", json={"operation_id": "not-a-uuid", "extra": True}).status_code == 422


def test_future_copilot_projection_is_neutral_and_never_reads_seal(client):
    state = begin(client)
    attempt_id = uuid.UUID(state["attempt_id"])
    chosen = client.post(f"/practice/replay/attempts/{attempt_id}/choice",
        json={"checkpoint_id": "first-look", "decision": "exit", "rationale": "Committed privately."})
    assert chosen.status_code == 200
    with Session(client.app.state.replay_test_engine) as db:
        projection = replay_engine.copilot_context(db, attempt_id)
        assert projection["packet"] == state["checkpoint"]
        assert projection["evidence_sha256"]
        assert set(projection) == {"checkpoint_id", "input_cutoff", "evidence_sha256", "packet"}
        raw = json.loads(db.get(PracticeReplayAttempt, attempt_id).state_json)
        assert "final_outcome" in raw["sealed"]["later-look"]
        assert "final_outcome" not in str(projection)


def test_stale_sessions_cannot_overwrite_an_immutable_choice(client):
    engine = client.app.state.replay_test_engine
    with Session(engine) as creator:
        state = replay_engine.create_attempt(creator, uuid.uuid4())
    attempt_id = uuid.UUID(state["attempt_id"])
    # Keep the original row in each identity map to exercise the revision compare-and-set.
    with Session(engine) as first, Session(engine) as stale:
        original = first.get(PracticeReplayAttempt, attempt_id)
        old_copy = stale.get(PracticeReplayAttempt, attempt_id)
        selected = replay_engine.save_choice(first, attempt_id, "first-look", "hold", None)
        assert original.revision == 1 and old_copy.revision == 0
        retry = replay_engine.save_choice(stale, attempt_id, "first-look", "hold", None)
        assert retry["choice"]["decision"] == selected["choice"]["decision"]
    with Session(engine) as first, Session(engine) as stale:
        original = first.get(PracticeReplayAttempt, attempt_id)
        old_copy = stale.get(PracticeReplayAttempt, attempt_id)
        replay_engine.reveal(first, attempt_id, "first-look")
        assert original.revision == 2 and old_copy.revision == 1
        retry = replay_engine.reveal(stale, attempt_id, "first-look")
        assert retry["checkpoint"]["id"] == "later-look"

    with Session(engine) as creator:
        competing = replay_engine.create_attempt(creator, uuid.uuid4())
    competing_id = uuid.UUID(competing["attempt_id"])
    with Session(engine) as first, Session(engine) as stale:
        original = first.get(PracticeReplayAttempt, competing_id)
        old_copy = stale.get(PracticeReplayAttempt, competing_id)
        replay_engine.save_choice(first, competing_id, "first-look", "hold", None)
        assert original.revision == 1 and old_copy.revision == 0
        with pytest.raises(RuntimeError, match="changed concurrently"):
            replay_engine.save_choice(stale, competing_id, "first-look", "exit", None)
    with Session(engine) as db:
        persisted = replay_engine.get_attempt(db, competing_id)
    assert persisted["choice"]["decision"] == "hold"


def test_fixture_cutoff_allowlist_and_attempt_snapshot_are_immutable(client, monkeypatch):
    original_bar = replay_engine._minute_bar

    def changed_bar(minute):
        bar = original_bar(minute)
        bar["later_source_note"] = "must never appear"
        if minute == 58:
            # The interval ended before 14:30, but it was not published until after cutoff.
            bar["published_at"] = "2026-02-10T14:30:02-05:00"
            bar["retrieved_at"] = "2026-02-10T14:30:06-05:00"
        return bar

    monkeypatch.setattr(replay_engine, "_minute_bar", changed_bar)
    with Session(client.app.state.replay_test_engine) as db:
        state = replay_engine.create_attempt(db, uuid.uuid4())
    attempt_id = uuid.UUID(state["attempt_id"])
    packet = state["checkpoint"]
    assert len(packet["bars"]) == 58
    assert all("later_source_note" not in bar for bar in packet["bars"])
    assert all(bar["published_at"] <= packet["input_cutoff"] for bar in packet["bars"])
    monkeypatch.setattr(replay_engine, "_freeze_checkpoint", lambda *_: (_ for _ in ()).throw(AssertionError("recomputed")))
    with Session(client.app.state.replay_test_engine) as db:
        resumed = replay_engine.get_attempt(db, attempt_id)
    assert resumed["checkpoint"] == packet
    assert client.post(f"/practice/replay/attempts/{attempt_id}/choice",
        json={"checkpoint_id": "first-look", "decision": "hold"}).status_code == 200
    assert client.post(f"/practice/replay/attempts/{attempt_id}/reveal",
        json={"checkpoint_id": "first-look"}).status_code == 200
    after_reveal = client.get(f"/practice/replay/attempts/{attempt_id}").json()
    for bar in after_reveal["revealed"][0]["continuation"]:
        assert "later_source_note" not in bar
        assert bar["published_at"] <= after_reveal["checkpoint"]["input_cutoff"]


def test_existing_assistant_and_service_permissions_do_not_gain_replay_access(boundary):
    assert signin(boundary).status_code == 200
    assert boundary.public.get("/practice/replay/scenarios").status_code == 403
    assert boundary.public.post("/practice/replay/attempts",
        json={"operation_id": str(uuid.uuid4())}).status_code == 403
    boundary.patch.setenv("TJ_ACCESS_SERVICES", json.dumps({"manual_mcp": "m" * 43}))
    with TestClient(main_app) as service:
        service.headers["x-tj-service"] = "m" * 43
        assert service.get("/practice/replay/scenarios").status_code == 403
        assert service.post("/practice/replay/attempts",
            json={"operation_id": str(uuid.uuid4())}).status_code == 403
