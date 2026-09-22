"""The Gmail Pub/Sub listener with a fake subscriber: no network, real job rows."""

import json
import threading
import time
from datetime import datetime, timedelta

import pytest
from sqlmodel import Session, delete, select

from app.database import engine
from app.engine import gmail_listener, gmail_poller, job_runtime
from app.engine.job_runtime import shutdown_requested
from app.models import JobRun


@pytest.fixture(autouse=True)
def job_rows():
    def clear():
        with Session(engine) as session:
            session.exec(delete(JobRun))
            session.commit()

    clear()
    yield
    clear()


@pytest.fixture
def configured(tmp_path, monkeypatch):
    key = tmp_path / "pubsub-subscriber.json"
    key.write_text("{}")
    monkeypatch.setenv("GMAIL_LISTENER_ENABLED", "true")
    monkeypatch.setenv("GMAIL_PUBSUB_SUBSCRIPTION", "projects/p/subscriptions/s")
    monkeypatch.setenv("GMAIL_PUBSUB_CREDENTIALS_FILE", str(key))
    monkeypatch.delenv("GMAIL_PUBSUB_TOPIC", raising=False)
    monkeypatch.setattr(gmail_listener, "_wait", lambda seconds: shutdown_requested.wait(min(seconds, 0.01)))
    return key


class FakeMessage:
    def __init__(self, payload):
        self.data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.acked = self.nacked = False

    def ack(self):
        self.acked = True

    def nack(self):
        self.nacked = True


class FakeFuture:
    def __init__(self, error=None):
        self.error = error
        self.cancelled = False

    def done(self):
        return self.error is not None or self.cancelled

    def result(self, timeout=None):
        if self.error is not None:
            raise self.error

    def cancel(self):
        self.cancelled = True
        return True


class FakeClient:
    def __init__(self, futures=None):
        self.futures = list(futures or [])
        self.callbacks = []
        self.closed = 0

    def __call__(self, _credentials_path):
        return self

    def subscribe(self, subscription, callback):
        assert subscription == "projects/p/subscriptions/s"
        self.callbacks.append(callback)
        return self.futures.pop(0) if self.futures else FakeFuture()

    def close(self):
        self.closed += 1


def _listener_row(status="running"):
    with Session(engine) as session:
        row = JobRun(job_type="gmail_listener", status=status, total=0)
        session.add(row)
        session.commit()
        return row.id


def _row(job_id):
    with Session(engine) as session:
        return session.get(JobRun, job_id)


def _rows(job_type):
    with Session(engine) as session:
        return session.exec(select(JobRun).where(JobRun.job_type == job_type)).all()


def _wait_for(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition not reached")


def _start(job_id, client):
    thread = threading.Thread(
        target=gmail_listener.run_listener,
        args=(job_id,),
        kwargs={"client_factory": client, "tick_seconds": 0.01, "heartbeat_seconds": 0.05},
        daemon=True,
    )
    thread.start()
    return thread


def test_notifications_queue_one_push_and_shutdown_is_clean(configured):
    job_id = _listener_row()
    client = FakeClient()
    thread = _start(job_id, client)
    _wait_for(lambda: client.callbacks)

    messages = [FakeMessage({"emailAddress": "me@example.com", "historyId": 100 + n}) for n in range(3)]
    malformed = FakeMessage(b"not json")
    for message in [*messages, malformed]:
        client.callbacks[0](message)

    shutdown_requested.set()
    thread.join(5)
    assert not thread.is_alive()

    assert all(message.acked for message in messages) and malformed.acked
    assert len(_rows("gmail_push")) == 1
    row = _row(job_id)
    assert (row.status, row.current, row.done) == ("succeeded", "Stopped for shutdown", 3)
    state = gmail_listener.listener_state()
    assert state["state"] == "stopped" and state["messages"] == 3
    assert client.closed == 1


def test_uncommitted_request_is_nacked_for_redelivery(configured, monkeypatch):
    def broken(*_args, **_kwargs):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr("app.routers.sync.queue_gmail_push_pipeline", broken)
    listener = gmail_listener._Listener(_listener_row(), heartbeat_seconds=60)
    message = FakeMessage({"historyId": 5})
    listener.on_message(message)
    assert message.nacked and not message.acked


def test_stream_error_resubscribes_without_failing(configured):
    job_id = _listener_row()
    client = FakeClient([FakeFuture(RuntimeError("stream reset")), FakeFuture()])
    thread = _start(job_id, client)
    _wait_for(lambda: len(client.callbacks) == 2)
    assert _row(job_id).status == "running"
    shutdown_requested.set()
    thread.join(5)
    assert _row(job_id).status == "succeeded"
    assert client.closed == 2


def test_credential_error_fails_with_a_readable_message(configured):
    PermissionDenied = type("PermissionDenied", (Exception,), {})

    def denied(_path):
        raise PermissionDenied("403 User not authorized to perform this action")

    job_id = _listener_row()
    gmail_listener.run_listener(job_id, client_factory=denied, tick_seconds=0.01)
    row = _row(job_id)
    assert row.status == "failed"
    assert "PermissionDenied" in row.error and "Pub/Sub Subscriber" in row.error


def test_stop_request_on_the_row_ends_the_listener(configured, monkeypatch):
    monkeypatch.setattr(gmail_listener, "_STOP_CHECK_SECONDS", 0)
    job_id = _listener_row()
    client = FakeClient()
    thread = _start(job_id, client)
    _wait_for(lambda: client.callbacks)
    with Session(engine) as session:
        row = session.get(JobRun, job_id)
        row.status = "queued_stop"
        session.add(row)
        session.commit()
    thread.join(5)
    row = _row(job_id)
    assert (row.status, row.current) == ("succeeded", "Listener stopped")


def test_missing_configuration_fails_immediately(configured, monkeypatch):
    monkeypatch.delenv("GMAIL_PUBSUB_SUBSCRIPTION")
    job_id = _listener_row()
    assert gmail_listener.run_listener(job_id, client_factory=FakeClient()) == 0
    assert _row(job_id).error == "GMAIL_PUBSUB_SUBSCRIPTION is not set"


# ---------------------------------------------------------------------------
# Keeping a listener request alive
# ---------------------------------------------------------------------------


def test_nothing_is_queued_while_disabled(configured, monkeypatch):
    monkeypatch.setenv("GMAIL_LISTENER_ENABLED", "false")
    assert gmail_listener.ensure_listener_request() is None
    assert _rows("gmail_listener") == []


def test_nothing_is_queued_without_a_key(configured):
    configured.unlink()
    assert gmail_listener.ensure_listener_request() is None


def test_one_request_is_kept_alive(configured):
    job_id = gmail_listener.ensure_listener_request()
    assert _row(job_id).status == "queued"
    assert gmail_listener.ensure_listener_request() is None


def _failed(age_seconds, count=1):
    with Session(engine) as session:
        for n in range(count):
            finished = datetime.utcnow() - timedelta(seconds=age_seconds)
            session.add(JobRun(
                job_type="gmail_listener", status="failed", total=0,
                created_at=finished - timedelta(seconds=count - n), finished_at=finished,
            ))
        session.commit()


@pytest.mark.parametrize(
    ("failures", "age", "restarts"),
    [(1, 5, False), (1, 60, True), (2, 60, True), (3, 60, False), (3, 180, True)],
)
def test_restart_backs_off_after_consecutive_failures(configured, failures, age, restarts):
    _failed(age, failures)
    assert (gmail_listener.ensure_listener_request() is not None) is restarts


def test_startup_can_skip_the_backoff(configured):
    _failed(1, 3)
    assert gmail_listener.ensure_listener_request(ignore_backoff=True) is not None


# ---------------------------------------------------------------------------
# Watch renewal scheduling
# ---------------------------------------------------------------------------


def _watch(*, topic="projects/p/topics/t", registered_ago=60, expires_in=7 * 86400):
    now = time.time()
    gmail_poller._save_gmail_watch_state({
        "topic_name": topic, "label_ids": ["Label_7"],
        "registered_at": int(now - registered_ago), "expiration": int((now + expires_in) * 1000),
    })


@pytest.mark.parametrize(
    ("watch", "due"),
    [
        (None, True),
        ({}, False),
        ({"expires_in": 86400}, True),
        ({"registered_ago": 25 * 3600}, True),
        ({"topic": "projects/p/topics/old"}, True),
    ],
)
def test_watch_renewal_due(monkeypatch, watch, due):
    monkeypatch.setenv("GMAIL_PUBSUB_TOPIC", "projects/p/topics/t")
    if watch is not None:
        _watch(**watch)
    assert gmail_listener.watch_renewal_due() is due


def test_watch_renewal_is_queued_once_and_retried_slowly(monkeypatch):
    assert gmail_listener._maybe_queue_watch_renewal() is None  # no topic configured
    monkeypatch.setenv("GMAIL_PUBSUB_TOPIC", "projects/p/topics/t")
    first = gmail_listener._maybe_queue_watch_renewal()
    assert first is not None
    assert gmail_listener._maybe_queue_watch_renewal() is None
    with Session(engine) as session:
        row = session.get(JobRun, first)
        row.status, row.finished_at = "failed", datetime.utcnow()
        session.add(row)
        session.commit()
    assert gmail_listener._maybe_queue_watch_renewal() is None


# ---------------------------------------------------------------------------
# Lanes
# ---------------------------------------------------------------------------


def test_listener_runs_only_in_its_own_lane():
    assert job_runtime.job_lane("gmail_listener") == "gmail"
    assert job_runtime.job_lane("gmail_watch_renew") == "sync"
    job_id = _listener_row(status="queued")
    assert job_runtime.worker_tick("sync") is False
    assert _row(job_id).status == "queued"
