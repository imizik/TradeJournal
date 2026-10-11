"""R3 browser-facing data identity, observation/reveal and owner boundaries."""
import json
import threading
from types import SimpleNamespace
import uuid

from fastapi.testclient import TestClient
import pytest

from app.engine.market_map import ET
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
    monkeypatch.setattr(session.store, "work_once", lambda **kwargs: (entered.set(), finish.wait(3)))
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


@pytest.mark.parametrize("reveal", [False, True])
@pytest.mark.parametrize("saved", [False, True])
def test_partial_buckets_never_become_chart_candles(session, definition, snapshot, reveal, saved):
    from tests.test_research_studio_analysis import changed
    partial = changed(snapshot, remove_minute=595, partial=True)
    session.source.snapshot = lambda *a, **k: partial
    run = session.enqueue(definition.canonical(), op()) if saved else session.preview(definition.canonical())
    chart = session.chart(symbol="MU", decision_time=clock().isoformat(), data_id=run["data_id"],
                          run_id=run["run_id"] if saved else None, reveal=reveal, operation_id=op())
    assert int(clock(minute=595).timestamp()) not in {b["time"] for b in chart["bars"]}
    assert int(clock(minute=590).timestamp()) in {b["time"] for b in chart["bars"]}


@pytest.mark.parametrize("saved", [False, True])
def test_chart_and_endpoint_use_same_frozen_split_basis(session, definition, snapshot, saved):
    from dataclasses import replace
    from datetime import date
    from app.engine.research_studio import Observations
    from app.engine.research_studio_analysis import outcome
    source = snapshot.symbols[0]
    bars = tuple(replace(b, open=b.open/10, high=b.high/10, low=b.low/10, close=b.close/10)
                 if b.time.astimezone(ET).date() == date(2023,7,10)
                 else b for b in source.bars)
    adjusted = replace(snapshot, symbols=(replace(source, bars=bars), snapshot.symbols[1]))
    session.source.snapshot = lambda *a, **k: adjusted
    # Pre-split July7 occurrence, endpoint differs tenfold from raw input prices.
    decision = clock(day=date(2023,7,7))
    run = session.enqueue(definition.canonical(), op()) if saved else session.preview(definition.canonical())
    chart = session.chart(symbol="MU", decision_time=decision.isoformat(), data_id=run["data_id"],
                          run_id=run["run_id"] if saved else None, reveal=True, operation_id=op())
    analysis = outcome(Observations(adjusted), "MU", decision)
    endpoint = analysis["outcomes"]["30m"]
    candle = next(b for b in chart["bars"] if b["time"] == int(decision.timestamp())+25*60)
    assert candle["close"] == endpoint["endpoint_price"] == 10
    assert candle["open"] == 10 and candle["high"] == 10.1 and candle["low"] == 9.9


def test_previous_snapshot_compression_reopens_same_content(snapshot):
    import gzip
    from app.engine.research_studio_store import encode_snapshot, decode_snapshot
    current = encode_snapshot(snapshot)
    previous = gzip.compress(gzip.decompress(current), compresslevel=9, mtime=0)
    assert decode_snapshot(current).identity == decode_snapshot(previous).identity == snapshot.identity


def test_recovery_bypasses_preparation_and_never_dispatches_queued_work(session, definition):
    run = session.enqueue(definition.canonical(), op())
    with session._prepare():
        assert session.store.recover() == {"recovered": []}
    assert session.store.status(run["run_id"])["status"] == "queued"
    with session.store._lock("worker.lock", nonblocking=True):
        with pytest.raises(ValueError, match="already active"):
            session.store.recover()


def test_fork_window_releases_data_then_chart_uses_frozen_submission(session, definition, monkeypatch):
    run = session.enqueue(definition.canonical(), op())
    session.source.snapshot = lambda *a, **k: (_ for _ in ()).throw(AssertionError("source reopened"))
    seen = []
    def child(*, on_child_started):
        assert session.observations is None and session.chart_snapshot is None
        assert session.preparation.locked()
        on_child_started()
        assert not session.preparation.locked()
        chart = session.chart(symbol="MU", decision_time=clock().isoformat(), data_id=run["data_id"], operation_id=op())
        seen.append(chart["data_id"])
    monkeypatch.setattr(session.store, "work_once", child)
    session.execute()
    session.worker.join(2)
    assert seen == [run["data_id"]]
    assert not session.preparation.locked() and not session.execution.locked()


def test_thread_start_failure_releases_admission_without_claiming_work(session, definition, monkeypatch):
    run = session.enqueue(definition.canonical(), op())
    monkeypatch.setattr("app.engine.research_studio_session.threading.Thread.start",
                        lambda self: (_ for _ in ()).throw(RuntimeError("fixture thread refused")))
    with pytest.raises(RuntimeError, match="refused"):
        session.execute()
    assert not session.preparation.locked() and not session.execution.locked()
    assert session.store.status(run["run_id"])["status"] == "queued"


def test_inner_thread_start_failure_reaps_real_child_and_allows_retry(session, definition, monkeypatch):
    import subprocess
    run = session.enqueue(definition.canonical(), op())
    processes = []
    original_popen, original_start = subprocess.Popen, threading.Thread.start

    def capture_child(*args, **kwargs):
        child = original_popen(*args, **kwargs)
        processes.append(child)
        return child

    def refuse_communication(thread):
        if thread._target.__name__ == "communicate":
            raise RuntimeError("fixture communication thread refused")
        return original_start(thread)

    with monkeypatch.context() as patch:
        patch.setattr("app.engine.research_studio_store.subprocess.Popen", capture_child)
        patch.setattr(threading.Thread, "start", refuse_communication)
        session.execute()
        session.worker.join(5)
        assert not session.worker.is_alive()

    assert len(processes) == 1 and processes[0].poll() is not None
    assert all(pipe.closed for pipe in (processes[0].stdin, processes[0].stdout, processes[0].stderr))
    assert not session.preparation.locked() and not session.execution.locked()
    state = session.store.status(run["run_id"])
    assert state["status"] == "failed" and state["exposures"] == 0
    assert session.store.recover() == {"recovered": []}
    session.store.control(run["run_id"], "retry", op())
    session.execute()
    session.worker.join(15)
    assert not session.worker.is_alive()
    state = session.store.status(run["run_id"])
    assert state["status"] == "completed" and state["attempt"] == 2 and state["exposures"] == 0
