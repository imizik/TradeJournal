"""R3 browser-facing data identity, observation/reveal and owner boundaries."""
import json
import threading
from types import SimpleNamespace
import uuid

from fastapi.testclient import TestClient
import pytest

from app.engine.research_studio_session import Busy, ResearchSession
from app.engine.research_studio_store import ResearchStore
from scripts.research_studio_server import create_app
from tests.test_research_studio_analysis import snapshot as snapshot, definition as definition, clock
from tests.test_browser_access import boundary as boundary, signin


def op():
    return str(uuid.uuid4())


@pytest.fixture
def session(tmp_path, snapshot):
    source = tmp_path / "sip"
    source.mkdir()
    root = tmp_path / "research"
    root.mkdir()
    return ResearchSession(SimpleNamespace(snapshot=lambda *a, **kw: snapshot), ResearchStore(root, source_root=source))


def test_preview_charts_same_identity_and_durable_reveal_before_bytes(session, definition):
    p = session.preview(definition.canonical())
    assert p["event_count"] == 1 and "outcomes" not in json.dumps(p)
    args = {"symbol": "MU", "decision_time": clock().isoformat(), "data_id": p["data_id"]}
    view = op()
    before = session.chart(**args, operation_id=view)
    assert max(b["time"] + 300 for b in before["bars"]) <= clock().timestamp()
    assert before["occurrence_id"] == p["events"][0]["occurrence_id"]
    assert session.chart(**args, operation_id=view) == before
    reveal = op()
    after = session.chart(**args, reveal=True, operation_id=reveal)
    assert after["revealed"] and max(b["time"] for b in after["bars"]) > clock().timestamp()
    artifact = session.store.root / f"inspection.{reveal}.json"
    assert json.loads(artifact.read_text())["future_revealed"] is True
    with pytest.raises(ValueError, match="conflicts"):
        session.chart(**args, reveal=True, operation_id=view)


@pytest.mark.parametrize("changed", [{"decision_time": "2024-10-01T10:00:00-04:00"},
    {"decision_time": "2023-07-10T10:00:00"}, {"symbol": "../SPY"}, {"data_id": "a"*64},
    {"decision_time": "2023-06-30T10:00:00-04:00"}])
def test_invalid_chart_never_writes_exposure(session, definition, changed):
    p = session.preview(definition.canonical())
    with pytest.raises(ValueError):
        session.chart(**({"symbol": "MU", "decision_time": clock().isoformat(), "data_id": p["data_id"],
                          "operation_id": op(), "reveal": True} | changed))
    assert not list(session.store.root.glob("inspection.*"))


def test_saved_chart_reopens_original_snapshot_without_source_access(session, definition):
    run = session.enqueue(definition.canonical(), op())
    session.source.snapshot = lambda *a, **k: (_ for _ in ()).throw(AssertionError("source reopened"))
    session.observations = None
    chart = session.chart(symbol="MU", decision_time=clock().isoformat(), data_id=run["data_id"],
                          run_id=run["run_id"], reveal=True, operation_id=op())
    assert chart["data_id"] == run["data_id"]
    assert session.runs()["runs"][0]["status"] == "queued"
    assert session.store.status(run["run_id"])["exposures"] == 0


def test_finite_dispatch_no_startup_replay_and_busy_refusal(session, definition, monkeypatch):
    session.enqueue(definition.canonical(), op())
    assert session.worker is None
    entered, finish = threading.Event(), threading.Event()
    monkeypatch.setattr(session.store, "work_once", lambda: (entered.set(), finish.wait(3)))
    session.execute()
    assert entered.wait(1)
    with pytest.raises(Busy):
        session.execute()
    finish.set()
    session.worker.join(2)
    assert not session.worker.is_alive()
    with session._prepare():
        with pytest.raises(Busy):
            session.preview(definition.canonical())


def test_sidecar_requires_secret_before_loading_and_refuses_paths(session, definition):
    client = TestClient(create_app(session, "r"*32))
    assert client.get("/config").status_code == 403
    assert client.post("/command", json={"action": "preview", "arguments": {"raw": definition.canonical()}}).status_code == 403
    assert session.observations is None
    client.headers["authorization"] = "Bearer " + "r"*32
    assert client.get("/config").status_code == 200
    assert client.post("/command", json={"action": "preview", "arguments": {"raw": definition.canonical(), "cache_root": "/tmp"}}).status_code == 400
    assert client.post("/command", json={"action": "preview", "arguments": {"raw": definition.canonical()}}).json()["event_count"] == 1


def test_assistant_cannot_forward_or_access_research(boundary, monkeypatch):
    from app.routers import research_studio
    calls = []
    monkeypatch.setattr(research_studio, "forward", lambda *a, **k: calls.append(a) or {})
    assert signin(boundary).status_code == 200
    assert boundary.public.get("/research-studio/config").status_code == 403
    assert boundary.public.post("/research-studio/command", json={"action": "runs", "arguments": {}}).status_code == 403
    assert not calls
    assert boundary.owner.get("/research-studio/config").status_code == 200
    assert boundary.owner.post("/research-studio/command", json={"action": "runs", "arguments": {}}).status_code == 200
    assert len(calls) == 2


def test_informed_submission_is_durable_and_reveal_requires_boolean(session, definition):
    operation = op()
    result = session.enqueue(definition.canonical(), operation, outcome_informed=True)
    saved = json.loads((session.store.root / f"submission.{operation}.json").read_text())
    assert saved == {"run_id": result["run_id"], "outcome_informed": True}
    with pytest.raises(ValueError, match="conflicts"):
        session.enqueue(definition.canonical(), operation, outcome_informed=False)
    with pytest.raises(ValueError, match="boolean"):
        session.chart(symbol="MU", decision_time=clock().isoformat(), data_id=result["data_id"], reveal="false", operation_id=op())


def test_engine_upgrade_does_not_recalculate_saved_chart_as_original(session, definition, monkeypatch):
    run = session.enqueue(definition.canonical(), op())
    monkeypatch.setattr("app.engine.research_studio_session.engine_fingerprint", lambda: "f"*64)
    with pytest.raises(ValueError, match="engine changed"):
        session.chart(symbol="MU", decision_time=clock().isoformat(), data_id=run["data_id"],
                      run_id=run["run_id"], operation_id=op())
    assert not list(session.store.root.glob("inspection.*"))
