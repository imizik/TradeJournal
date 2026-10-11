"""Research-only persistence/lifecycle/protected-file refusal evidence."""
from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys
import uuid

import pytest

from app.engine.research_studio_analysis import analyze
from app.engine.research_studio_store import ResearchStore, decode_snapshot, encode_snapshot
from tests.test_research_studio_analysis import definition as definition, snapshot as snapshot


def operation():
    return str(uuid.uuid4())


@pytest.fixture
def store(tmp_path):
    source = tmp_path / "sip"
    source.mkdir()
    root = tmp_path / "research"
    root.mkdir()
    return ResearchStore(root, source_root=source)


def test_roundtrip_and_completed_inputs_result_are_immutable(store, snapshot, definition):
    assert decode_snapshot(encode_snapshot(snapshot)).identity == snapshot.identity
    op = operation()
    queued = store.enqueue(snapshot, definition, op)
    assert queued == store.enqueue(snapshot, definition, op)
    assert store.work_once()["status"] == "completed"
    assert store.work_once() == {"status": "idle"}
    before = (store.root / queued["run_id"] / "result.json").read_bytes()
    view = operation()
    result = store.result(queued["run_id"], view)
    assert result == store.result(queued["run_id"], view)
    assert store.status(queued["run_id"])["exposures"] == 1
    assert result == store.result(queued["run_id"], operation())
    assert store.status(queued["run_id"])["exposures"] == 2
    store.enqueue(snapshot, definition, operation())
    assert store.status(queued["run_id"])["attempt"] == 1
    assert before == (store.root / queued["run_id"] / "result.json").read_bytes()


def test_failure_explicit_retry_and_global_operation_conflict(store, snapshot, definition):
    op = operation()
    run = store.enqueue(snapshot, definition, op)["run_id"]
    def fail(*args, **kwargs):
        raise ValueError("invented failure")
    assert store.work_once(compute=fail)["status"] == "failed"
    assert store.work_once() == {"status": "idle"}
    with pytest.raises(ValueError, match="not complete"):
        store.result(run, operation())
    retry = operation()
    assert store.control(run, "retry", retry)["attempt"] == 2
    assert store.control(run, "retry", retry)["attempt"] == 2
    assert store.work_once()["status"] == "completed"
    with pytest.raises(ValueError, match="different research action"):
        store.result(run, retry)
    other = replace(definition, window_end=605)
    with pytest.raises(ValueError, match="different research action"):
        store.enqueue(snapshot, other, op)


def test_cancel_queued_and_running_without_result_exposure(store, snapshot, definition):
    run = store.enqueue(snapshot, definition, operation())["run_id"]
    assert store.control(run, "cancel", operation())["status"] == "cancelled"
    assert store.work_once() == {"status": "idle"}
    store.control(run, "retry", operation())
    def cancel(obs, definition, code, *, cancel):
        store.control(run, "cancel", operation())
        return analyze(obs, definition, code, cancel=cancel)
    assert store.work_once(compute=cancel)["status"] == "cancelled"
    assert not (store.root / run / "result.json").exists()
    assert store.status(run)["exposures"] == 0


def test_dead_worker_is_failed_and_never_automatically_replayed(store, snapshot, definition):
    run = store.enqueue(snapshot, definition, operation())["run_id"]
    # Real subprocess death after claim. No cleanup/finally status is possible.
    program = "from app.engine.research_studio_store import ResearchStore; from pathlib import Path; import os; "
    program += f"s=ResearchStore(Path({str(store.root)!r}),source_root=Path({str(store.root.parent / 'sip')!r})); "
    program += "s.work_once(compute=lambda *a,**k: os._exit(17))"
    result = subprocess.run([sys.executable, "-c", program], cwd=Path(__file__).parents[1], timeout=20)
    assert result.returncode == 17
    assert store.status(run)["status"] == "running"
    assert store.work_once() == {"status": "idle"}
    state = store.status(run)
    assert state["status"] == "failed" and "interrupted" in state["reason"]
    assert state["attempt"] == 1
    store.control(run, "retry", operation())
    assert store.work_once()["status"] == "completed"


def test_live_worker_lock_prevents_recovery_or_duplicate_execution(store, snapshot, definition):
    store.enqueue(snapshot, definition, operation())
    with store._lock("worker.lock", nonblocking=True):
        with pytest.raises(ValueError, match="already active"):
            store.work_once()


def test_same_date_source_or_preparation_correction_invalidates_logical_run(store, snapshot, definition):
    first = store.enqueue(snapshot, definition, operation())["run_id"]
    source = snapshot.symbols[0]
    bar = source.bars[-1]
    corrected = replace(snapshot, symbols=(replace(source, bars=source.bars[:-1] + (replace(bar, close=bar.close + .1),)), snapshot.symbols[1]))
    second = store.enqueue(corrected, definition, operation())["run_id"]
    assert first != second
    assert store.work_once()["status"] == "completed"
    assert store.work_once()["status"] == "completed"


def test_prepared_file_tampering_refuses_before_analysis_and_is_failed(store, snapshot, definition):
    run = store.enqueue(snapshot, definition, operation())["run_id"]
    (store.root / run / "snapshot.json.gz").write_bytes(b"forbidden")
    def forbidden(*args, **kwargs):
        pytest.fail("tampered prepared data reached analysis")
    assert store.work_once(compute=forbidden)["status"] == "failed"


def test_source_and_store_overlap_and_symlink_payloads_refuse(tmp_path, store, snapshot, definition):
    with pytest.raises(ValueError, match="not overlap"):
        ResearchStore(store.root.parent, source_root=store.root.parent / "sip")
    run = store.enqueue(snapshot, definition, operation())["run_id"]
    assert store.work_once()["status"] == "completed"
    protected = store.root.parent / "sip" / "2024-10-01.json"
    protected.write_text('{"forbidden":true}')
    result_path = store.root / run / "result.json"
    result_path.unlink()
    result_path.symlink_to(protected)
    with pytest.raises(OSError):
        store.result(run, operation())
    assert store.status(run)["exposures"] == 0


def test_prepared_snapshot_dates_guard_before_continuation():
    payload = {"through": "2024-10-01", "symbols": [], "manifest": [], "engine_fingerprint": "x", "provenance": "invented"}
    import gzip
    with pytest.raises(ValueError):
        decode_snapshot(gzip.compress(json.dumps(payload).encode()))


def test_request_corruption_rejected_before_prepared_payload_open(store, snapshot, definition, monkeypatch):
    run = store.enqueue(snapshot, definition, operation())["run_id"]
    with store._db(write=True) as db:
        request = json.loads(db.execute("SELECT request FROM run WHERE id=?", (run,)).fetchone()[0])
        request["definition"]["end"] = "2024-10-01"
        db.execute("UPDATE run SET request=? WHERE id=?", (json.dumps(request), run))
    opened = []
    original = store._read
    def read(fd, name):
        opened.append(name)
        return original(fd, name)
    monkeypatch.setattr(store, "_read", read)
    with pytest.raises(ValueError, match="request changed"):
        store.work_once()
    assert "snapshot.json.gz" not in opened
    with store._db() as db:
        assert db.execute("SELECT state FROM attempt WHERE run_id=?", (run,)).fetchone()[0] == "failed"


def test_research_root_replacement_and_lock_symlink_refuse_before_payload(tmp_path, snapshot, definition):
    source = tmp_path / "sip"
    source.mkdir()
    parent = tmp_path / "parent"
    root = parent / "research"
    root.mkdir(parents=True)
    store = ResearchStore(root, source_root=source)
    foreign = tmp_path / "foreign"
    (foreign / "research").mkdir(parents=True)
    parent.rename(tmp_path / "old-parent")
    parent.symlink_to(foreign, target_is_directory=True)
    with pytest.raises(ValueError, match="directory changed"):
        store.enqueue(snapshot, definition, operation())
    assert list((foreign / "research").iterdir()) == []
    parent.unlink()
    (tmp_path / "old-parent").rename(parent)
    protected = source / "2024-10-01.json"
    protected.write_text("forbidden")
    (root / "ledger.lock").symlink_to(protected)
    with pytest.raises(OSError):
        store.enqueue(snapshot, definition, operation())
    assert protected.read_text() == "forbidden"


def test_raw_manifest_correction_creates_new_run_without_overwriting_old_result(store, snapshot, definition):
    first = store.enqueue(snapshot, definition, operation())["run_id"]
    assert store.work_once()["status"] == "completed"
    old = (store.root / first / "result.json").read_bytes()
    original = snapshot.manifest[0]
    corrected = replace(snapshot, manifest=((original[0], original[1], "c" * 64, original[3]),) + snapshot.manifest[1:])
    second = store.enqueue(corrected, definition, operation())["run_id"]
    assert first != second
    assert (store.root / first / "result.json").read_bytes() == old


def test_cli_complete_run_reopen_and_source_bytes_unchanged(tmp_path):
    from datetime import date
    from tests.test_research_studio import rows, write_day
    cache = tmp_path / "sip"
    cache.mkdir()
    root = tmp_path / "research"
    root.mkdir()
    for symbol in ("MU", "SPY"):
        write_day(cache, symbol, date(2023, 7, 3), rows(date(2023, 7, 3)))
    protected = write_day(cache, "MU", date(2024, 10, 1), [{"forbidden": True}])
    before = {str(p): p.read_bytes() for p in cache.rglob("*.json")}
    definition = tmp_path / "question.json"
    definition.write_text(json.dumps({"version": 1, "universe": ["MU"], "start": "2023-07-03", "end": "2023-07-03",
                                      "window_start": 600, "window_end": 600,
                                      "predicates": [{"feature": "minutes", "minimum": 30}]}))
    script = Path(__file__).resolve().parents[1] / "scripts/research_studio_run.py"
    base = [sys.executable, str(script), "--cache-root", str(cache), "--store-root", str(root)]
    def cli(*args):
        completed = subprocess.run(base + list(args), cwd=tmp_path, capture_output=True, text=True, timeout=30)
        assert completed.returncode == 0, completed.stderr
        return json.loads(completed.stdout)
    queued = cli("enqueue", "--definition", str(definition), "--operation-id", operation())
    assert cli("work-once")["status"] == "completed"
    run = queued["run_id"]
    result = cli("result", "--run-id", run, "--operation-id", operation())
    assert result["horizons"]["30m"]["percent"]["event_n"] == 1
    assert result["horizons"]["30m"]["percent"]["event_mean"] == 0
    assert cli("result", "--run-id", run, "--operation-id", operation()) == result
    assert cli("status", "--run-id", run)["exposures"] == 2
    assert before == {str(p): p.read_bytes() for p in cache.rglob("*.json")}
    assert protected.read_text() == '[{"forbidden": true}]'


def test_queue_is_bounded_and_cancel_releases_capacity(store, snapshot, definition):
    runs = [store.enqueue(snapshot, replace(definition, window_end=600 + k * 5), operation())["run_id"] for k in range(4)]
    with pytest.raises(ValueError, match="queue is full"):
        store.enqueue(snapshot, replace(definition, window_end=620), operation())
    store.control(runs[0], "cancel", operation())
    assert store.enqueue(snapshot, replace(definition, window_end=620), operation())["status"] == "queued"


def test_parent_cancellation_acknowledges_uncooperative_child_within_one_second(store, snapshot, definition, tmp_path, monkeypatch):
    import signal
    import threading
    import time
    from app.engine import research_studio_store as module
    run = store.enqueue(snapshot, definition, operation())["run_id"]
    blocker = tmp_path / "blocking-child.py"
    blocker.write_text("import signal,sys,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); sys.stdin.buffer.read(); time.sleep(60)")
    original = module.subprocess.Popen
    started = threading.Event()
    children = []
    def launch(args, **kwargs):
        child = original([sys.executable, str(blocker)], **kwargs)
        children.append(child)
        started.set()
        return child
    monkeypatch.setattr(module.subprocess, "Popen", launch)
    replies = []
    thread = threading.Thread(target=lambda: replies.append(store.work_once()))
    thread.start()
    assert started.wait(5)
    with pytest.raises(ValueError, match="already active"):
        store.work_once()
    began = time.monotonic()
    store.control(run, "cancel", operation())
    thread.join(timeout=.95)
    assert not thread.is_alive()
    assert time.monotonic() - began <= 1
    assert replies[0]["status"] == "cancelled"
    assert children[0].poll() in (-signal.SIGKILL, -signal.SIGTERM)
    assert not (store.root / run / "result.json").exists()


def test_sqlite_never_opens_an_application_database_path(store, snapshot, definition, monkeypatch):
    from app.engine import research_studio_store as module
    opened = []
    original = module.sqlite3.connect
    def connect(path, *args, **kwargs):
        opened.append(path)
        assert path == ":memory:"
        return original(path, *args, **kwargs)
    monkeypatch.setattr(module.sqlite3, "connect", connect)
    run = store.enqueue(snapshot, definition, operation())["run_id"]
    store.work_once(compute=analyze)
    store.result(run, operation())
    assert opened and set(opened) == {":memory:"}


def test_protected_request_date_refused_even_with_updated_checksum(store, snapshot, definition, monkeypatch):
    import hashlib
    run = store.enqueue(snapshot, definition, operation())["run_id"]
    with store._db(write=True) as db:
        request = json.loads(db.execute("SELECT request FROM run WHERE id=?", (run,)).fetchone()[0])
        request["definition"]["end"] = "2024-10-01"
        raw = json.dumps(request)
        db.execute("UPDATE run SET request=?,request_sha=? WHERE id=?", (raw, hashlib.sha256(raw.encode()).hexdigest(), run))
    opened = []
    original = store._read
    def read(fd, name):
        opened.append(name)
        return original(fd, name)
    monkeypatch.setattr(store, "_read", read)
    with pytest.raises(ValueError):
        store.work_once()
    assert "snapshot.json.gz" not in opened


def test_cached_results_reopen_with_saved_versions_but_old_jobs_cannot_recompute_after_upgrade(store, snapshot, definition, monkeypatch):
    import numpy as np
    run = store.enqueue(snapshot, definition, operation())["run_id"]
    store.work_once(compute=analyze)
    original = store.result(run, operation())
    queued = store.enqueue(snapshot, replace(definition, window_end=605), operation())["run_id"]
    monkeypatch.setattr(np, "__version__", "invented-upgrade")
    assert store.result(run, operation()) == original
    assert store.status(run)["status"] == "completed"
    assert store.work_once()["status"] == "failed"
    assert "code changed" in store.status(queued)["reason"]


def test_unrelated_sqlite_image_is_not_adopted_or_modified(store, snapshot, definition):
    import sqlite3
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE journal_private (trade_id INTEGER PRIMARY KEY)")
    db.execute("INSERT INTO journal_private VALUES(41)")
    db.commit()
    original = db.serialize()
    db.close()
    (store.root / "ledger.sqlite3").write_bytes(original)
    with pytest.raises(ValueError, match="not a Research Studio"):
        store.enqueue(snapshot, definition, operation())
    assert (store.root / "ledger.sqlite3").read_bytes() == original
    assert not any(p.is_dir() for p in store.root.iterdir())


def test_known_unmarked_research_index_remains_readable_and_namespaced_on_next_write(store, snapshot, definition):
    run = store.enqueue(snapshot, definition, operation())["run_id"]
    store.work_once(compute=analyze)
    original = store.result(run, operation())
    import sqlite3
    db = sqlite3.connect(":memory:")
    db.deserialize((store.root / "ledger.sqlite3").read_bytes())
    db.execute("PRAGMA application_id=0")
    db.execute("PRAGMA user_version=0")
    (store.root / "ledger.sqlite3").write_bytes(db.serialize())
    db.close()
    assert store.status(run)["status"] == "completed"
    assert store.result(run, operation()) == original
    with store._db() as db:
        from app.engine.research_studio_store import APPLICATION_ID
        assert db.execute("PRAGMA application_id").fetchone()[0] == APPLICATION_ID
