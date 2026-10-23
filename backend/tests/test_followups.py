"""Conversation → durable work → fresh review → one phone message, including failures."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
import sqlite3

from fastapi.testclient import TestClient
import pytest

from app.engine.followups import FollowupRunner, publish_stock
from app.engine.market_watch_wakes import MarketWatchRunner, MarketWatchWakeStore
from cloud_mcp_check_ledger import Ledger, Conflict, NotFound
from followup_common import export, read_work
from followup_ledger import FollowupLedger
from stock_watch_common import stamp
from tests.test_cloud_mcp_check import harness, signing_key, call, rpc  # noqa: F401

NOW = datetime(2026, 10, 23, 14, 0, tzinfo=UTC)
ACTOR = "check_00000000-0000-0000-0000-000000000001"


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("JO_FOLLOWUPS_ENABLED", "true")
    s = SimpleNamespace(now=NOW, mails=[], pushes=[])
    s.public, s.outbox = tmp_path / "public", tmp_path / "outbox"
    s.public.mkdir()
    s.outbox.mkdir()
    s.ledger = Ledger(tmp_path / "check.db")
    s.followups = FollowupLedger(s.ledger)
    s.store = MarketWatchWakeStore(tmp_path / "wakes.db")
    s.runner = MarketWatchRunner(
        s.store,
        s.public,
        outbox_dir=s.outbox,
        clock=lambda: s.now,
        bounds=lambda d: (
            s.now.replace(hour=13, minute=30),
            s.now.replace(hour=20, minute=0),
        ),
        mail=lambda title, body: s.mails.append((title, body)) or "mail-ok",
        push=lambda title, body: s.pushes.append((title, body)) or "push-ok",
        setup_window=lambda n: False,
    )
    s.worker = FollowupRunner(s.runner)
    s.worker.run_once()
    return s


def request(s, **changes):
    return {
        "operation_id": "nbis-bounce",
        "title": "NBIS bounce",
        "original_request": "Keep following the bounce we discussed",
        "why_it_matters": "I am considering it if the recovery holds",
        "review_question": "Is the recovery holding or failing?",
        "symbols": ["NBIS"],
        "next_review_at": stamp(s.now),
        "expires_at": stamp(s.now + timedelta(hours=4)),
        **changes,
    }


def create(s, **changes):
    r = s.followups.create(ACTOR, request(s, **changes), s.public, s.now)
    export(s.outbox, r)
    return r


def due(s):
    s.worker.run_once()
    return s.followups.due(ACTOR, s.public, s.now)["inputs"]


def review(s, inp, **changes):
    return {
        "input_id": inp["input_id"],
        "outcome": "update",
        "summary": "Following up on NBIS: the bounce is holding; volume confirmation is still missing.",
        "what_changed": "The latest completed bars held the discussed recovery",
        "why_it_matters": "It remains worth investigating",
        "next_step": "Review volume and whether support holds",
        "evidence_refs": ["/work/evidence/stocks/NBIS"],
        "notify": True,
        "next_review_at": stamp(s.now + timedelta(minutes=30)),
        **changes,
    }


def stock(s):
    rows = [
        {
            "time": s.now.timestamp() - 60,
            "end_time": s.now.timestamp(),
            "open": 100,
            "high": 101,
            "low": 99,
            "close": 100.5,
            "volume": 1000,
        }
    ]
    publish_stock(s.public, "NBIS", rows, s.now.timestamp(), s.now)


def test_whole_followup_restarts_recovers_context_and_sends_once(env):
    s = env
    r = create(s)
    stock(s)
    (inp,) = due(s)
    assert inp["request"]["original_request"] == request(s)["original_request"]
    assert inp["latest_review"] is None
    assert len(s.mails) == 1 and "Follow-up wake ID:" in s.mails[0][1]
    assert s.followups.due(ACTOR, s.public, s.now)["inputs"] == [inp]
    result = s.followups.review(ACTOR, review(s, inp), s.now)
    assert s.followups.review(ACTOR, review(s, inp), s.now) == result
    export(s.outbox, result)
    s.worker = FollowupRunner(s.runner)
    s.worker.run_once()
    s.worker.run_once()
    assert len(s.pushes) == 1 and "NBIS" in s.pushes[0][1]
    work = read_work(s.public, r["followup_id"], s.now)
    assert work["delivery"][-1]["result"] == "accepted"
    assert not s.followups.due(ACTOR, s.public, s.now)["inputs"]
    s.now += timedelta(minutes=30)
    stock(s)
    (second,) = due(s)
    assert second["latest_review"] == result
    assert second["request"] == inp["request"]
    quiet = s.followups.review(
        ACTOR, review(s, second, outcome="unchanged", notify=False), s.now
    )
    export(s.outbox, quiet)
    s.worker.run_once()
    assert len(s.pushes) == 1


def test_cancel_and_expiry_never_resurrect_or_send_old_reviews(env):
    s = env
    r = create(s)
    stock(s)
    (inp,) = due(s)
    result = s.followups.review(ACTOR, review(s, inp), s.now)
    export(s.outbox, result)
    cancel = s.followups.cancel(ACTOR, r["followup_id"], s.now)
    assert s.followups.cancel(ACTOR, r["followup_id"], s.now) == cancel
    export(s.outbox, cancel)
    s.worker.run_once()
    assert not s.pushes
    assert not s.followups.due(ACTOR, s.public, s.now)["inputs"]
    assert s.followups.list(ACTOR, s.now)[0]["state"] == "cancelled"
    other = create(
        s, operation_id="other", expires_at=stamp(s.now + timedelta(minutes=40))
    )
    s.now += timedelta(minutes=40)
    s.worker.run_once()
    assert "No Jo review was saved" in s.pushes[-1][1]
    assert read_work(s.public, other["followup_id"], s.now)["state"] == "expired"
    s.worker.run_once()
    assert len(s.pushes) == 1


def test_ownership_retry_conflicts_and_stale_parent(env):
    s = env
    body = request(s)
    r = create(s)
    with pytest.raises(Conflict):
        create(s, title="Different")
    for action in (
        lambda: s.followups.records("peer", r["followup_id"]),
        lambda: s.followups.cancel("peer", r["followup_id"], s.now),
    ):
        with pytest.raises(NotFound):
            action()
    (inp,) = due(s)
    assert not s.followups.due("peer", s.public, s.now)["inputs"]
    with pytest.raises(NotFound):
        s.followups.review("peer", review(s, inp), s.now)
    s.now += timedelta(minutes=10)
    stock(s)
    (newer,) = due(s)
    with pytest.raises(ValueError, match="expired"):
        s.followups.review(ACTOR, review(s, inp), s.now)
    s.followups.review(ACTOR, review(s, newer), s.now)
    with pytest.raises(Conflict):
        s.followups.review(ACTOR, review(s, inp), s.now)
    s.now += timedelta(days=8)
    assert s.followups.create(ACTOR, body, s.public, s.now) == r


def test_missing_evidence_off_worker_and_failure_recovery_are_honest(env, monkeypatch):
    s = env
    r = create(s)
    (inp,) = due(s)
    assert inp["work"]["evidence"]["stocks"]["NBIS"]["status"] == "unavailable"
    s.now += timedelta(seconds=91)
    with pytest.raises(ValueError, match="heartbeat"):
        s.followups.due(ACTOR, s.public, s.now)
    monkeypatch.setenv("JO_FOLLOWUPS_ENABLED", "false")
    s.worker.run_once()
    with pytest.raises(ValueError, match="not enabled"):
        s.followups.due(ACTOR, s.public, s.now)
    monkeypatch.setenv("JO_FOLLOWUPS_ENABLED", "true")
    s.now = NOW + timedelta(minutes=16)
    s.worker.run_once()
    assert read_work(s.public, r["followup_id"], s.now)["overdue"]
    assert "no saved response" in s.pushes[0][1]
    (inp,) = s.followups.due(ACTOR, s.public, s.now)["inputs"]
    saved = s.followups.review(
        ACTOR, review(s, inp, outcome="blocked", notify=False), s.now
    )
    export(s.outbox, saved)
    s.worker.run_once()
    assert not read_work(s.public, r["followup_id"], s.now)["overdue"]


def test_caps_validation_and_immutable_records(env):
    s = env
    for i in range(5):
        create(s, operation_id=str(i))
    with pytest.raises(ValueError, match="Five active"):
        create(s, operation_id="six")
    inp = due(s)[0]
    for changes in (
        {"outcome": "unchanged"},
        {"next_review_at": stamp(s.now + timedelta(minutes=2))},
        {"evidence_refs": ["/request/original_request"]},
        {"evidence_refs": ["/work/evidence/made-up"]},
        {"evidence_refs": []},
        {"outcome": "resolved"},
    ):
        with pytest.raises(ValueError):
            s.followups.review(ACTOR, review(s, inp, **changes), s.now)
    db = s.ledger._connect()
    try:
        for table in ("jo_followup_record", "jo_followup_input"):
            with pytest.raises(sqlite3.IntegrityError):
                db.execute(f"DELETE FROM {table}")
    finally:
        db.close()


def test_uncertain_push_is_not_retried(env):
    s = env
    create(s)
    stock(s)
    (inp,) = due(s)
    result = s.followups.review(ACTOR, review(s, inp), s.now)
    export(s.outbox, result)
    attempts = []

    def uncertain(title, text):
        attempts.append(title)
        raise TimeoutError("unknown")

    s.runner.push = uncertain
    s.worker.run_once()
    s.now += timedelta(minutes=2)
    s.worker.run_once()
    assert len(attempts) == 1
    assert s.store.records("followup_push")[-1]["result"] == "unknown"


def test_source_events_wake_early_without_spy_budget(env):
    from market_watch_common import seal

    s = env
    create(s, next_review_at=stamp(s.now + timedelta(hours=1)))
    assert not due(s)
    alert = seal(
        {
            "alert_id": "sta_test",
            "symbol": "NBIS",
            "created_at": stamp(s.now + timedelta(seconds=1)),
            "expires_at": stamp(s.now + timedelta(minutes=10)),
            "session_date": s.now.date().isoformat(),
        }
    )
    s.store.append("stock_alert", alert, ident=alert["alert_id"])
    s.now += timedelta(minutes=1)
    (inp,) = due(s)
    assert inp["work"]["reason"] == "new_evidence"
    saved = s.followups.review(
        ACTOR, review(s, inp, outcome="unchanged", notify=False), s.now
    )
    export(s.outbox, saved)
    s.now += timedelta(minutes=11)
    assert not due(s)


def test_tool_scope_actor_schema_and_runtime_revocation(harness, tmp_path):  # noqa: F811
    public, outbox = tmp_path / "followup-public", tmp_path / "followup-outbox"
    public.mkdir()
    outbox.mkdir()
    harness.configure(
        followup_enabled=True,
        market_watch_snapshots_dir=str(public),
        market_watch_outbox_dir=str(outbox),
    )
    with TestClient(harness.server().streamable_http_app()) as client:
        token = harness.token(scope="check:read market-watch:read market-watch:submit")
        result = call(client, "followup_list", {}, token)
        assert "structuredContent" in result, result
        assert result["structuredContent"]["followups"] == []
        assert call(client, "followup_list", {}, harness.token())["isError"]
        assert call(client, "followup_list", {"actor": "spoof"}, token)["isError"]
        harness.configure(followup_enabled=False)
        assert rpc(client, "followup_list", {}, token).status_code == 401


def test_full_mcp_handoff_and_closure(env, harness):  # noqa: F811
    s = env
    harness.configure(
        followup_enabled=True,
        market_watch_snapshots_dir=str(s.public),
        market_watch_outbox_dir=str(s.outbox),
    )
    stock(s)
    with TestClient(harness.server(now=s.now).streamable_http_app()) as client:
        token = harness.token(scope="check:read market-watch:read market-watch:submit")
        created = call(client, "followup_create", {"followup": request(s)}, token)[
            "structuredContent"
        ]
        assert created["handoff"] == "queued"
        followup_id = created["receipt"]["followup_id"]
        s.worker.run_once()
        listing = call(client, "followup_list", {"followup_id": followup_id}, token)[
            "structuredContent"
        ]
        assert listing["followups"][0]["worker"]["due"]
        (inp,) = call(client, "followup_due", {}, token)["structuredContent"]["inputs"]
        body = review(
            s,
            inp,
            outcome="resolved",
            next_review_at=None,
            summary="The question is answered; closing this follow-up.",
        )
        saved = call(client, "followup_review", {"review": body}, token)[
            "structuredContent"
        ]
        assert saved["receipt"]["body"]["outcome"] == "resolved"
        s.worker.run_once()
        assert len(s.pushes) == 1
        assert (
            call(client, "followup_due", {}, token)["structuredContent"]["inputs"] == []
        )
        listing = call(client, "followup_list", {"followup_id": followup_id}, token)[
            "structuredContent"
        ]
        assert len(listing["history"]) == 2
        assert listing["followups"][0]["state"] == "resolved"
        assert not harness.requests  # No provider or paid-model work in these tools.


def test_web_research_and_missing_data_do_not_become_price_evidence(env):
    s = env
    create(s)
    (inp,) = due(s)
    with pytest.raises(ValueError, match="cited evidence"):
        s.followups.review(ACTOR, review(s, inp), s.now)
    web = [
        {
            "url": "https://example.com/company-release",
            "finding": "A newly published release addresses the original question",
            "observed_at": stamp(s.now),
        }
    ]
    result = s.followups.review(
        ACTOR, review(s, inp, evidence_refs=[], web_sources=web), s.now
    )
    assert result["body"]["web_sources"] == web


def test_closed_session_defers_until_open_and_never_backdates(env):
    s = env
    s.now = NOW.replace(hour=12)
    s.worker.run_once()
    r = create(s)
    assert not due(s)
    assert not s.mails
    s.now = NOW.replace(hour=13, minute=30)
    (inp,) = due(s)
    assert not inp["work"]["overdue"]
    assert inp["created_at"] == stamp(s.now)
    s.now += timedelta(minutes=16)
    s.worker.run_once()
    assert read_work(s.public, r["followup_id"], s.now)["overdue"]
    assert len(s.pushes) == 1


def test_linked_plan_trigger_reassesses_without_changing_price_plan(env):
    from conditional_plan_common import publish
    from market_watch_common import seal

    s = env
    plan_id = "cpl_00000000-0000-0000-0000-000000000001"
    db = s.ledger._connect()
    try:
        db.execute("CREATE TABLE conditional_plan(plan_id TEXT, actor TEXT)")
        db.execute("INSERT INTO conditional_plan VALUES(?,?)", (plan_id, ACTOR))
        db.commit()
    finally:
        db.close()
    r = create(
        s, linked_plan_id=plan_id, next_review_at=stamp(s.now + timedelta(hours=1))
    )
    assert not due(s)
    s.now += timedelta(minutes=1)
    value = seal(
        {
            "format": "conditional-plan-status-v1",
            "plan_id": plan_id,
            "state": "triggered",
            "enabled": True,
            "checked_at": stamp(s.now),
            "created_at": stamp(s.now),
            "events": [
                {"event_id": plan_id + ":triggered", "created_at": stamp(s.now)}
            ],
        }
    )
    publish(s.public, f"conditional-plan-status-{plan_id}.json", value)
    (inp,) = due(s)
    assert inp["work"]["evidence"]["price_plan"]["monitoring"]
    assert inp["work"]["reason"] == "new_evidence"
    cancel = s.followups.cancel(ACTOR, r["followup_id"], s.now)
    export(s.outbox, cancel)
    s.worker.run_once()
    from conditional_plan_common import read_json

    assert read_json(s.public / f"conditional-plan-status-{plan_id}.json") == value


def test_restart_reports_overdue_and_expiry_even_after_transport_freshness(env):
    s = env
    r = create(s)
    s.now += timedelta(minutes=40)
    s.worker = FollowupRunner(s.runner)
    s.worker.run_once()
    assert len(s.pushes) == 1 and "no saved response" in s.pushes[0][1]
    s.worker.run_once()
    assert len(s.pushes) == 1
    s.now = NOW + timedelta(hours=5)
    s.worker = FollowupRunner(s.runner)
    s.worker.run_once()
    assert len(s.pushes) == 2 and "follow-up period ended" in s.pushes[-1][1]
    s.now += timedelta(days=1)
    s.worker.run_once()
    assert len(s.pushes) == 2
    assert read_work(s.public, r["followup_id"], s.now)["state"] == "expired"


def test_stale_saved_update_reports_delivery_gap_without_replaying_advice(env):
    s = env
    create(s)
    stock(s)
    (inp,) = due(s)
    saved = s.followups.review(ACTOR, review(s, inp), s.now)
    export(s.outbox, saved)
    s.now += timedelta(minutes=11)
    s.worker = FollowupRunner(s.runner)
    s.worker.run_once()
    assert len(s.pushes) == 1
    assert "could not be delivered while fresh" in s.pushes[0][1]
    assert "bounce is holding" not in s.pushes[0][1]
    s.worker.run_once()
    assert len(s.pushes) == 1
    assert any(
        a["result"] == "expired" and a["notice_id"] == saved["record_id"]
        for a in s.store.records("followup_push")
    )


def test_due_distinguishes_missing_stale_and_pending_work_from_no_due(env):
    from conditional_plan_common import publish
    from market_watch_common import seal

    s = env
    r = create(s)
    result = s.followups.due(ACTOR, s.public, s.now)
    assert not result["inputs"] and result["gaps"][0]["followup_id"] == r["followup_id"]
    (inp,) = due(s)
    work = inp["work"]
    s.now += timedelta(minutes=2)
    publish(
        s.public,
        "followup-readiness.json",
        seal(
            {
                "format": "jo-followup-readiness-v1",
                "enabled": True,
                "created_at": stamp(s.now),
            }
        ),
    )
    result = s.followups.due(ACTOR, s.public, s.now)
    assert (
        not result["inputs"]
        and result["gaps"][0]["reason"] == "worker_projection_unavailable"
    )
    changed = {**work, "created_at": stamp(s.now), "parent_id": "old-parent"}
    changed.pop("content_sha256")
    publish(s.public, f"followup-work-{r['followup_id']}.json", seal(changed))
    result = s.followups.due(ACTOR, s.public, s.now)
    assert (
        not result["inputs"]
        and result["gaps"][0]["reason"] == "worker_handoff_pending_or_mismatched"
    )
    s.worker.run_once()
    result = s.followups.due(ACTOR, s.public, s.now)
    assert result["inputs"] and not result["gaps"]


def test_multiday_overdue_warning_is_deduplicated_across_sessions(env):
    s = env
    r = create(s, expires_at=stamp(s.now + timedelta(days=5)))
    s.now += timedelta(minutes=16)
    s.worker.run_once()
    assert len(s.pushes) == 1 and "no saved response" in s.pushes[0][1]
    # Friday's unanswered review is still active on Monday; session-adjusted
    # eligibility must not give the same operational notice another send key.
    s.now = NOW + timedelta(days=3)
    s.now = s.now.replace(hour=13, minute=46)
    s.worker.run_once()
    assert read_work(s.public, r["followup_id"], s.now)["overdue"]
    assert len(s.pushes) == 1
