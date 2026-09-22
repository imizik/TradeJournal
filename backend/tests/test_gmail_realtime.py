"""Real-time Gmail import: history cursor, targeted fetch, coalescing, health.

Every Gmail call is a fake. State files are redirected by conftest.
"""

import json
import time
from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, delete, select

from app.database import engine
from app.engine import gmail_health, gmail_listener, gmail_poller
from app.engine.email_parser import ParsedFill
from app.models import JobRun
from app.routers import sync

ET = ZoneInfo("America/New_York")


# ---------------------------------------------------------------------------
# Fake Gmail API
# ---------------------------------------------------------------------------


class _Request:
    def __init__(self, fn):
        self._fn = fn

    def execute(self):
        return self._fn()


class _NotFound(Exception):
    resp = SimpleNamespace(status=404)


class FakeGmail:
    def __init__(self, *, history_pages=None, history_error=None, messages=None, labels=None, profile="900", watch=None):
        self.history_pages = history_pages or {None: {"historyId": "0"}}
        self.history_error = history_error
        self.messages_by_id = messages or {}
        self.labels_list = labels or []
        self.profile = profile
        self.watch_result = watch or {"historyId": "777", "expiration": str(int((time.time() + 7 * 86400) * 1000))}
        self.calls = []

    def users(self):
        return self

    # users().history()
    def history(self):
        gmail = self

        class History:
            def list(self, **kwargs):
                gmail.calls.append(("history", kwargs))
                if gmail.history_error:
                    raise gmail.history_error
                return _Request(lambda: gmail.history_pages[kwargs.get("pageToken")])

        return History()

    # users().messages()
    def messages(self):
        gmail = self

        class Messages:
            def get(self, userId, id, format, metadataHeaders=None):
                gmail.calls.append((format, id))
                return _Request(lambda: gmail.messages_by_id[id])

        return Messages()

    def labels(self):
        gmail = self

        class Labels:
            def list(self, userId):
                return _Request(lambda: {"labels": gmail.labels_list})

        return Labels()

    def getProfile(self, userId):
        return _Request(lambda: {"historyId": self.profile})

    def watch(self, userId, body):
        self.calls.append(("watch", body))
        return _Request(lambda: self.watch_result)


def _metadata(sender, subject):
    return {"payload": {"headers": [{"name": "From", "value": sender}, {"name": "Subject", "value": subject}]}}


def _fill(raw_id):
    return ParsedFill(
        ticker="SPY", side="buy_to_open", contracts=Decimal("1"), price=Decimal("1.25"),
        executed_at=datetime(2026, 9, 22, 10, 31, tzinfo=ET), instrument_type="option",
        raw_email_id=raw_id, account_last4="8267", account_type="individual",
        option_type="call", strike=Decimal("660"), expiration=datetime(2026, 9, 22).date(),
    )


# ---------------------------------------------------------------------------
# History and targeted fetch
# ---------------------------------------------------------------------------


def test_history_ids_follow_pages_and_only_the_watched_label():
    gmail = FakeGmail(history_pages={
        None: {
            "history": [
                {"messagesAdded": [{"message": {"id": "a"}}]},
                {"labelsAdded": [
                    {"message": {"id": "b"}, "labelIds": ["Label_1"]},
                    {"message": {"id": "c"}, "labelIds": ["STARRED"]},
                ]},
            ],
            "nextPageToken": "p2",
            "historyId": "100",
        },
        "p2": {"history": [{"messagesAdded": [{"message": {"id": "a"}}, {"message": {"id": "d"}}]}], "historyId": "105"},
    })
    ids, latest = gmail_poller.history_message_ids(gmail, "50", "Label_1")
    assert (ids, latest) == (["a", "b", "d"], "105")
    first = gmail.calls[0][1]
    assert first["startHistoryId"] == "50" and first["labelId"] == "Label_1"
    assert first["historyTypes"] == ["messageAdded", "labelAdded"]


def test_expired_history_is_a_distinct_error():
    gmail = FakeGmail(history_error=_NotFound("gone"))
    with pytest.raises(gmail_poller.GmailHistoryExpired):
        gmail_poller.history_message_ids(gmail, "50", None)


def test_pending_ids_without_cursor_capture_mailbox_position_first(monkeypatch):
    gmail = FakeGmail(profile="900")
    monkeypatch.setattr(gmail_poller, "_get_service", lambda: gmail)
    assert gmail_poller.pending_history_message_ids() == (None, "900")


def test_pending_ids_fall_back_when_cursor_expired(monkeypatch):
    gmail_poller.save_history_cursor("50")
    gmail = FakeGmail(history_error=_NotFound("gone"), profile="901")
    monkeypatch.setattr(gmail_poller, "_get_service", lambda: gmail)
    assert gmail_poller.pending_history_message_ids() == (None, "901")


def test_targeted_fetch_reads_only_headers_of_unrelated_mail(monkeypatch):
    rh = "Robinhood <noreply@robinhood.com>"
    gmail = FakeGmail(messages={
        "rh-1": _metadata(rh, "Option order executed"),
        "personal": _metadata("friend@example.com", "Option order executed"),
        "rh-partial": _metadata(rh, "Option order partially executed"),
        "rh-marketing": _metadata(rh, "Your weekly recap"),
    })
    full = {
        "rh-1": {"payload": {"headers": [{"name": "Subject", "value": "Option order executed"}]}},
        "rh-partial": {"payload": {"headers": [{"name": "Subject", "value": "Option order partially executed"}]}},
    }
    original_get = gmail.messages

    def messages():
        api = original_get()
        base_get = api.get

        def get(userId, id, format, metadataHeaders=None):
            if format == "full":
                gmail.calls.append(("full", id))
                return _Request(lambda: full[id])
            return base_get(userId=userId, id=id, format=format, metadataHeaders=metadataHeaders)

        return SimpleNamespace(get=get)

    gmail.messages = messages
    monkeypatch.setattr(gmail_poller, "_get_service", lambda: gmail)
    monkeypatch.setattr(gmail_poller, "_message_body", lambda _msg: "body")
    monkeypatch.setattr(
        gmail_poller, "parse_option_email",
        lambda subject, body, imap_uid: _fill(imap_uid) if subject == "Option order executed" else None,
    )

    fills = gmail_poller.poll_fills_by_ids(["known", "rh-1", "personal", "rh-partial", "rh-marketing"], known_ids={"known"})

    assert [fill.raw_email_id for fill in fills] == ["rh-1"]
    assert [call for call in gmail.calls if call[0] == "full"] == [("full", "rh-1"), ("full", "rh-partial")]
    assert ("metadata", "known") not in gmail.calls
    assert gmail_poller._load_skipped_message_ids() == {"rh-partial"}


# ---------------------------------------------------------------------------
# Watch registration
# ---------------------------------------------------------------------------


def test_watch_resolves_label_names_and_seeds_only_a_missing_cursor(monkeypatch):
    gmail = FakeGmail(labels=[{"id": "INBOX", "name": "INBOX"}, {"id": "Label_7", "name": "TradeJournal/Fills"}])
    monkeypatch.setattr(gmail_poller, "_get_service", lambda: gmail)
    monkeypatch.setenv("GMAIL_PUBSUB_TOPIC", "projects/p/topics/t")
    monkeypatch.setenv("GMAIL_WATCH_LABELS", "tradejournal/fills")

    state = gmail_poller.register_gmail_watch()
    assert gmail.calls[-1] == ("watch", {"topicName": "projects/p/topics/t", "labelIds": ["Label_7"], "labelFilterBehavior": "INCLUDE"})
    assert state["label_ids"] == ["Label_7"]
    assert gmail_poller.watch_label_id() == "Label_7"
    assert gmail_poller.load_history_cursor() == "777"

    gmail_poller.save_history_cursor("800")
    gmail_poller.register_gmail_watch()
    assert gmail_poller.load_history_cursor() == "800"  # renewal never moves the cursor


def test_watch_refuses_a_label_that_does_not_exist(monkeypatch):
    monkeypatch.setattr(gmail_poller, "_get_service", lambda: FakeGmail(labels=[{"id": "INBOX", "name": "INBOX"}]))
    monkeypatch.setenv("GMAIL_PUBSUB_TOPIC", "projects/p/topics/t")
    monkeypatch.setenv("GMAIL_WATCH_LABELS", "TradeJournal/Fills")
    with pytest.raises(gmail_poller.GmailPollingError, match="does not exist"):
        gmail_poller.register_gmail_watch()


# ---------------------------------------------------------------------------
# Files and auth state
# ---------------------------------------------------------------------------


def test_private_write_through_symlink_replaces_the_target(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    (state / "token.json").write_text("old")
    release = tmp_path / "release"
    release.mkdir()
    link = release / "token.json"
    link.symlink_to(state / "token.json")

    gmail_poller.write_private_file(link, '{"token": "new"}')

    assert link.is_symlink()
    assert (state / "token.json").read_text() == '{"token": "new"}'
    assert (state / "token.json").stat().st_mode & 0o777 == 0o600
    assert sorted(path.name for path in state.iterdir()) == ["token.json"]


def test_auth_state_tracks_sign_out_and_recovery(monkeypatch):
    def signed_out():
        raise gmail_poller.GmailAuthRequired("Gmail authorization is required.")

    monkeypatch.setattr(gmail_poller, "_build_service", signed_out)
    with pytest.raises(gmail_poller.GmailAuthRequired):
        gmail_poller._get_service()
    assert gmail_poller.gmail_auth_state()["status"] == "needs_reconnect"

    monkeypatch.setattr(gmail_poller, "_build_service", lambda: object())
    gmail_poller._get_service()
    assert gmail_poller.gmail_auth_state()["status"] == "ok"


# ---------------------------------------------------------------------------
# Push import (sync lane)
# ---------------------------------------------------------------------------


@pytest.fixture
def import_calls(monkeypatch):
    calls = []

    def fake_import(_session, *, start_enrichment=True, message_ids=None):
        calls.append(message_ids)
        return {"saved": len(message_ids or ["searched"]), "skipped": 0}

    monkeypatch.setattr(sync, "_import_fills_from_gmail", fake_import)
    return calls


@pytest.mark.parametrize(
    ("pending", "expected_call", "cursor"),
    [
        ((None, "900"), [None], "900"),          # no cursor: ordinary search
        ((["a", "b"], "120"), [["a", "b"]], "120"),  # history: exactly those ids
        (([], "130"), [], "130"),                  # nothing new: no Gmail fetches
    ],
)
def test_push_import_uses_the_history_cursor(monkeypatch, import_calls, pending, expected_call, cursor):
    monkeypatch.setattr(gmail_poller, "pending_history_message_ids", lambda: pending)
    sync._import_gmail_changes(None)
    assert import_calls == expected_call
    assert gmail_poller.load_history_cursor() == cursor


def test_failed_push_import_keeps_the_cursor(monkeypatch):
    gmail_poller.save_history_cursor("50")
    monkeypatch.setattr(gmail_poller, "pending_history_message_ids", lambda: (["a"], "60"))

    def broken(*_args, **_kwargs):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(sync, "_import_fills_from_gmail", broken)
    with pytest.raises(RuntimeError):
        sync._import_gmail_changes(None)
    assert gmail_poller.load_history_cursor() == "50"


# ---------------------------------------------------------------------------
# Coalescing (real job_run rows in the session test database)
# ---------------------------------------------------------------------------


@pytest.fixture
def job_rows():
    def clear():
        with Session(engine) as session:
            session.exec(delete(JobRun))
            session.commit()

    clear()
    yield
    clear()


def _rows(job_type="gmail_push"):
    with Session(engine) as session:
        return session.exec(select(JobRun).where(JobRun.job_type == job_type).order_by(JobRun.created_at)).all()


def _set_status(job_id, status, **values):
    with Session(engine) as session:
        job = session.get(JobRun, job_id)
        job.status = status
        for key, value in values.items():
            setattr(job, key, value)
        session.add(job)
        session.commit()


def _queue(**kwargs):
    with Session(engine) as session:
        job, created = sync.queue_gmail_push_pipeline(session, history_id="1", trigger="pubsub", **kwargs)
        return job.id, created


def test_burst_of_notifications_queues_one_push(job_rows):
    results = [_queue() for _ in range(20)]
    assert results[0][1] is True
    assert all(created is False for _job, created in results[1:])
    assert len({job_id for job_id, _created in results}) == 1
    (row,) = _rows()
    assert json.loads(row.params_json)["trigger"] == "pubsub"


def test_running_push_gets_exactly_one_follow_up(job_rows):
    first, _ = _queue()
    _set_status(first, "running")
    follow_ups = {_queue()[0] for _ in range(3)}
    assert len(follow_ups) == 1 and first not in follow_ups
    assert [row.status for row in _rows()] == ["running", "queued"]


def test_push_claimed_between_check_and_touch_queues_a_new_one(job_rows, monkeypatch):
    first, _ = _queue()
    real_now = sync._now

    def claim_then_now():
        _set_status(first, "running")  # a worker wins the race here
        return real_now()

    monkeypatch.setattr(sync, "_now", claim_then_now)
    second, created = _queue()
    assert created is True and second != first


def test_push_defers_enrichment_when_another_push_waits(job_rows, monkeypatch):
    current, _ = _queue()
    _set_status(current, "running")
    _queue()  # the next execution email
    monkeypatch.setattr(sync, "_import_gmail_changes", lambda _session: {"saved": 2, "skipped": 0})
    monkeypatch.setattr(sync, "_rebuild_trades", lambda _session, anomalies_label: (5, []))

    def no_enrichment(*_args):
        raise AssertionError("enrichment must wait for the queued push")

    monkeypatch.setattr(sync, "_run_existing_enrichment", no_enrichment)
    sync._run_gmail_push_pipeline(current)
    with Session(engine) as session:
        row = session.get(JobRun, current)
    assert row.status == "succeeded" and "deferred" in row.current


def test_deferred_enrichment_runs_even_when_the_next_push_imports_nothing(job_rows, monkeypatch):
    current, _ = _queue()
    _set_status(current, "running")
    waiting, _ = _queue()
    monkeypatch.setattr(sync, "_import_gmail_changes", lambda _session: {"saved": 1, "skipped": 0})
    monkeypatch.setattr(sync, "_rebuild_trades", lambda _session, anomalies_label: (5, []))
    sync._run_gmail_push_pipeline(current)
    assert json.loads(_rows()[1].params_json)["enrich_pending"] is True

    _set_status(waiting, "running")
    monkeypatch.setattr(sync, "_import_gmail_changes", lambda _session: {"saved": 0, "skipped": 0})
    enriched = []
    monkeypatch.setattr(
        sync, "_run_existing_enrichment",
        lambda job_type, *_args: enriched.append(job_type) or SimpleNamespace(total=0),
    )
    sync._run_gmail_push_pipeline(waiting)
    assert enriched == ["polygon_enrich", "alpaca_enrich", "trade_path"]


def test_history_fetch_error_aborts_instead_of_skipping(monkeypatch):
    gmail = FakeGmail(messages={"rh-1": _metadata("noreply@robinhood.com", "Option order executed")})
    original = gmail.messages

    def messages():
        api = original()

        def get(userId, id, format, metadataHeaders=None):
            if format == "full":
                raise ConnectionError("reset by peer")
            return api.get(userId=userId, id=id, format=format, metadataHeaders=metadataHeaders)

        return SimpleNamespace(get=get)

    gmail.messages = messages
    monkeypatch.setattr(gmail_poller, "_get_service", lambda: gmail)
    with pytest.raises(gmail_poller.GmailPollingError, match="rh-1"):
        gmail_poller.poll_fills_by_ids(["rh-1"])


def test_watch_renewal_job_reports_expiry(monkeypatch):
    expires = str(int(datetime(2026, 9, 29, 12, 0).timestamp() * 1000))
    monkeypatch.setattr(gmail_poller, "register_gmail_watch", lambda: {"label_ids": ["Label_7"], "expiration": expires})
    processed, message = sync._run_gmail_watch_renew(None, None)
    assert processed == 1 and "Label_7" in message and "2026-09-29" in message


def test_listener_does_not_block_manual_sync(job_rows):
    with Session(engine) as session:
        session.add(JobRun(job_type="gmail_listener", status="running", total=0))
        session.commit()
        assert sync._active_job(session) is None


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@pytest.fixture
def live_setup(tmp_path, monkeypatch, job_rows):
    gmail_poller.TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    gmail_poller.TOKEN_FILE.write_text("{}")
    key = tmp_path / "key.json"
    key.write_text("{}")
    monkeypatch.setenv("GMAIL_LISTENER_ENABLED", "true")
    monkeypatch.setenv("GMAIL_PUBSUB_SUBSCRIPTION", "projects/p/subscriptions/s")
    monkeypatch.setenv("GMAIL_PUBSUB_CREDENTIALS_FILE", str(key))
    with Session(engine) as session:
        row = JobRun(job_type="gmail_listener", status="running", total=0)
        session.add(row)
        session.commit()
        row_id = row.id

    def set_listener(heartbeat_age=0, state="listening", watch_days=6):
        now = time.time()
        gmail_listener.LISTENER_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        gmail_listener.LISTENER_STATE_FILE.write_text(json.dumps(
            {"state": state, "heartbeat_at": now - heartbeat_age, "messages": 3, "last_message_at": now - 5}
        ))
        gmail_poller._save_gmail_watch_state({"label_ids": ["Label_7"], "expiration": int((now + watch_days * 86400) * 1000)})

    set_listener()
    return SimpleNamespace(row_id=row_id, set_listener=set_listener)


def _health():
    with Session(engine) as session:
        return gmail_health.gmail_health(session)


def test_health_is_live_when_listener_heartbeats(live_setup):
    health = _health()
    assert (health["status"], health["action"]) == ("live", None)
    assert health["notifications_received"] == 3 and health["watch_expires_at"]


@pytest.mark.parametrize(
    ("change", "status"),
    [
        ({"heartbeat_age": 5 * 60}, "degraded"),
        ({"heartbeat_age": 20 * 60}, "down"),
        ({"state": "reconnecting"}, "degraded"),
        ({"watch_days": 1}, "degraded"),
    ],
)
def test_health_degrades_with_listener_and_watch(live_setup, change, status):
    live_setup.set_listener(**change)
    assert _health()["status"] == status


def test_health_reports_failed_listener_error(live_setup):
    _set_status(live_setup.row_id, "failed", error="PermissionDenied: no access")
    health = _health()
    assert health["status"] == "down" and "PermissionDenied" in health["message"]


def test_health_asks_to_reconnect_when_signed_out(live_setup):
    gmail_poller._record_gmail_auth("needs_reconnect", "invalid_grant")
    health = _health()
    assert (health["status"], health["action"]) == ("down", "reconnect_gmail")


def test_health_without_token_asks_to_reconnect(job_rows):
    assert _health()["action"] == "reconnect_gmail"


def test_health_is_off_until_enabled(job_rows):
    gmail_poller.TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    gmail_poller.TOKEN_FILE.write_text("{}")
    assert _health()["status"] == "off"


def test_health_route(live_setup):
    from app.main import app

    with TestClient(app) as client:
        response = client.get("/gmail/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "live" and body["data_version"]


def test_data_version_changes_when_a_push_finishes(job_rows):
    before = _health()["data_version"]
    with Session(engine) as session:
        session.add(JobRun(job_type="gmail_push", status="succeeded", finished_at=datetime.utcnow() + timedelta(seconds=1)))
        session.commit()
    assert _health()["data_version"] != before
