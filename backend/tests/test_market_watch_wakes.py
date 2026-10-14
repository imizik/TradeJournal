"""MW-2 wake-ups, detector, read notices, message delivery and the session report (fixtures only)."""
from datetime import UTC, datetime, timedelta
import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.engine import market_watch_wakes as mw
from app.engine.market_watch_snapshot import build_snapshot, publish_snapshot
from app.engine.market_watch_evaluation import MarketWatchOutcomeStore
from cloud_mcp_check_ledger import Ledger
from market_watch_common import digest, seal
from market_watch_ledger import MarketWatchLedger, read_notice, write_read_notice
from tests.test_market_watch_ledger import ACTOR, request
from tests.test_cloud_mcp_check import harness as harness, signing_key as signing_key, call

OPEN = datetime(2026, 10, 14, 13, 30, tzinfo=UTC)
CLOSE = datetime(2026, 10, 14, 20, 0, tzinfo=UTC)
BOUNDS = (OPEN, CLOSE)


def _rows(closes):
    rows, previous = [], closes[0]
    for i, close in enumerate(closes):
        start = OPEN + timedelta(minutes=i)
        rows.append({"t": start.isoformat().replace("+00:00", "Z"), "o": previous, "h": max(previous, close) + .02,
                     "l": min(previous, close) - .02, "c": close, "v": 1000})
        previous = close
    return rows


def snapshot_at(now, closes=None, calendar_events=()):
    minutes = max(0, int((min(now, CLOSE) - OPEN).total_seconds() // 60))
    closes = (closes or [100.0] * 400)[:minutes]
    bars = {"SPY": _rows(closes), "QQQ": _rows([c * 4 for c in closes])} if closes else {"SPY": [], "QQQ": []}
    stamp = now.isoformat().replace("+00:00", "Z")
    events = list(calendar_events)
    return build_snapshot(now, bars_reader=lambda *_: bars, daily_reader=lambda *_: {},
        vix_reader=lambda: {"observed_at": now - timedelta(minutes=5), "value": 17.0, "change_pct": 1.0},
        calendar_reader=lambda day, at: {"status": "fresh", "reason": None, "source": "official_calendar", "observed_at": stamp,
            "retrieved_at": stamp, "age_seconds": 0, "coverage_start": "2026-01-01", "coverage_end": "2027-01-01",
            "calendar_version": "fixture", "events": events, "source_sha256": digest({"coverage_start": "2026-01-01",
            "coverage_end": "2027-01-01", "calendar_version": "fixture", "events": events})},
        news_reader=lambda start, end: {"status": "missing", "reason": "no_published_headline_cache", "source": "Alpaca Benzinga",
            "observed_at": None, "retrieved_at": end.isoformat().replace("+00:00", "Z"), "age_seconds": None,
            "source_sha256": digest([]), "query_symbols": ["SPY", "QQQ"], "window_start": start.isoformat().replace("+00:00", "Z"),
            "window_end": end.isoformat().replace("+00:00", "Z"), "coverage": "unpublished", "errors": [], "items": []},
        bounds_reader=lambda day: BOUNDS)


CPI = {"event_id": "cpi-fixture", "kind": "cpi", "name": "CPI (Sep 2026)", "scheduled_at": "2026-10-14T12:30:00Z",
       "source": "BLS/Federal Reserve schedule", "calendar_version": "fixture", "coverage_start": "2026-01-01",
       "coverage_end": "2027-01-01", "actual": None, "consensus": None, "surprise": None, "release_values_status": "not_supported"}


class Clock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


@pytest.fixture
def env(tmp_path):
    snapshots, outbox = tmp_path / "public", tmp_path / "outbox"
    snapshots.mkdir()
    outbox.mkdir()
    clock = Clock(datetime(2026, 10, 14, 13, 50, 20, tzinfo=UTC))
    sent, pushed = [], []

    def mail(subject, body):
        sent.append((subject, body))

    def push(title, body):
        pushed.append((title, body))
        return f"ntfy-{len(pushed)}"

    runner = mw.MarketWatchRunner(mw.MarketWatchWakeStore(tmp_path / "wakes.sqlite"), snapshots, outbox_dir=outbox,
                                  clock=clock, bounds=lambda day: BOUNDS, build=lambda now: snapshot_at(now),
                                  mail=mail, push=push, daily=lambda day: [])
    return runner, clock, sent, pushed, tmp_path


def kinds(events):
    return [(e["kind"], e["detail"].get("level"), e["detail"].get("direction")) for e in events]


def test_detector_is_deterministic_versioned_and_flags_late_events():
    # OR around 100; above at 09:45, then a drop through VWAP and the OR low, and a new low after 11:00.
    closes = [100.0] * 15 + [100.5, 99.0, 98.9, 98.8] + [98.6] * 20 + [98.5] * 52 + [97.0]
    now = OPEN + timedelta(minutes=len(closes))
    snapshot = snapshot_at(now, closes, [CPI])
    events = mw.detect_events(snapshot, detected_at=now)
    assert events == mw.detect_events(snapshot, detected_at=now)
    found = kinds(events)
    assert ("release_time_passed", None, None) in found
    assert ("level_cross", "vwap", "down") in found and ("level_cross", "or15_low", "down") in found
    assert any(e["kind"] == "new_session_low" and e["occurred_at"] >= "2026-10-14T15:00:00" for e in events)
    assert not any(e["kind"] == "new_session_high" for e in events)  # highs before 11:00 never count
    assert all(e["detector_version"] == "mw-detect-v1" and e["policy_sha256"] == mw.POLICY_SHA256 for e in events)
    release = next(e for e in events if e["kind"] == "release_time_passed")
    assert release["late"] and release["detail"]["release_values_status"] == "not_supported"
    fresh = [e for e in events if not e["late"]]
    assert fresh and all(e["occurred_at"] >= (now - timedelta(minutes=10)).isoformat().replace("+00:00", "Z") for e in fresh)
    # Same bar, later detection: identical identity, so the store keeps the first record only.
    later = mw.detect_events(snapshot, detected_at=now + timedelta(minutes=1))
    assert [e["event_id"] for e in later] == [e["event_id"] for e in events]


def test_failed_reclaim_cooldown_and_atr_move_since_last_read():
    closes = [100.0] * 15 + [100.5, 99.0] + [99.2] * 5
    rows_now = OPEN + timedelta(minutes=len(closes) + 1)
    snap = snapshot_at(rows_now, closes + [99.3])
    events = mw.detect_events(snap, detected_at=rows_now)
    crosses = [e for e in events if e["detail"].get("level") == "vwap"]
    assert len(crosses) == 1  # 30-minute cooldown holds later VWAP touches on the same level
    read = {"read_id": "mwr_00000000-0000-4000-8000-000000000001", "received_at": (OPEN + timedelta(minutes=17)).isoformat(), "price": 100.6}
    atr_events = [e for e in mw.detect_events(snap, detected_at=rows_now, atr={"atr14": 2.0, "bars_sha256": "x"}, last_read=read)
                  if e["kind"] == "atr_move_since_read"]
    assert [(e["detail"]["direction"], e["detail"]["multiple"]) for e in atr_events] == [("down", 1)]
    assert mw.detect_events(snap, detected_at=rows_now, atr=None, last_read=read) == events


def test_prior_atr_uses_only_complete_prior_sessions():
    rows = [{"t": f"2026-09-{d:02d}T04:00:00Z", "h": 102, "l": 100, "c": 101} for d in range(10, 30)]
    rows.append({"t": "2026-10-14T04:00:00Z", "h": 500, "l": 1, "c": 2})
    assert mw.prior_atr14(rows, datetime(2026, 10, 14).date())["atr14"] == pytest.approx(2.0)
    assert mw.prior_atr14(rows[:5], datetime(2026, 10, 14).date()) is None


def test_store_is_append_only_and_refuses_foreign_databases(tmp_path):
    store = mw.MarketWatchWakeStore(tmp_path / "wakes.sqlite")
    record = seal({"session_date": "2026-10-14", "value": 1})
    assert store.append("event", record, ident="a") is True
    assert store.append("event", seal({"session_date": "2026-10-14", "value": 2}), ident="a") is False
    assert [r["value"] for r in store.records("event")] == [1]
    with sqlite3.connect(tmp_path / "wakes.sqlite") as db:
        for sql in ("UPDATE record SET kind='x'", "DELETE FROM record", "INSERT OR REPLACE INTO record SELECT * FROM record"):
            with pytest.raises(sqlite3.IntegrityError, match="immutable"):
                db.execute(sql)
    sqlite3.connect(tmp_path / "other.sqlite").execute("CREATE TABLE fills(id)").connection.commit()
    with pytest.raises(ValueError, match="non-MW-2"):
        mw.MarketWatchWakeStore(tmp_path / "other.sqlite")
    with pytest.raises(ValueError):
        mw.MarketWatchWakeStore("relative.sqlite")
    tampered = dict(record, value=3)
    with pytest.raises(ValueError):
        store.append("event", tampered, ident="b")


def test_scheduled_wakes_send_only_an_id_record_results_and_never_resend(env):
    runner, clock, sent, _, _ = env
    runner.run_once()
    wakes = {w["ref"]: w for w in runner.store.records("wake", "2026-10-14")}
    assert wakes["08:50"]["decision"] == "missed_late" and wakes["09:50"]["decision"] == "send"
    assert "11:00" not in wakes
    wake_id = wakes["09:50"]["wake_id"]
    assert sent == [(f"TJ Market Watch: {wake_id}", f"Wake ID: {wake_id}\n")]
    clock.now += timedelta(seconds=30)
    runner.run_once()
    assert len(sent) == 1
    attempts = runner.store.records("wake_attempt")
    assert [(a["wake_id"], a["result"], a["channel"]) for a in attempts] == [(wake_id, "accepted", "email")]
    assert wakes["09:50"]["snapshot_id"] and (runner.snapshots_dir / "latest.json").exists()


def test_wake_failures_retry_within_freshness_then_expire(env):
    runner, clock, _, _, _ = env
    calls = []

    def broken(subject, body):
        calls.append(subject)
        raise OSError("smtp down")
    runner.mail = broken
    for seconds in (0, 30, 61, 122, 183, 300):
        clock.now = datetime(2026, 10, 14, 13, 50, 20, tzinfo=UTC) + timedelta(seconds=seconds)
        runner.run_once()
    results = [(a["attempt"], a["result"], a["error_code"]) for a in runner.store.records("wake_attempt")]
    assert results == [(1, "failed", "OSError"), (2, "failed", "OSError"), (3, "failed", "OSError"), (3, "expired", "attempts_exhausted")]
    assert len(calls) == 3


def test_event_wakes_are_rate_limited_coalesced_and_late_events_never_wake(env):
    runner, clock, sent, _, _ = env
    runner.run_once()  # 09:50 scheduled wake sent at 13:50:20Z
    snapshot = snapshot_at(clock.now)
    def event(minute, late=False):
        at = clock.now - timedelta(minutes=30 if late else 0)
        return mw._event(snapshot, "level_cross", ["vwap", "down", str(minute)], at.isoformat(), clock.now, {"level": "vwap"})
    for e in (event(1), event(2, late=True)):
        runner.store.append("event", e, ident=e["event_id"])
    runner.plan_wakes(clock.now, clock.now.date(), CLOSE, snapshot)
    decisions = {w["event_id"]: w["decision"] for w in runner.store.records("wake") if w["trigger"] == "event"}
    assert sorted(decisions.values()) == ["coalesced", "event_late"]
    for i in range(8):
        clock.now += timedelta(minutes=16)
        e = event(10 + i)
        runner.store.append("event", e, ident=e["event_id"])
        runner.plan_wakes(clock.now, clock.now.date(), CLOSE, snapshot)
        runner.send_wakes(clock.now, clock.now.date())
    event_wakes = [w for w in runner.store.records("wake") if w["trigger"] == "event"]
    assert sum(w["decision"] == "send" for w in event_wakes) == mw.WAKE_POLICY["event_wakes_per_session"]
    assert any(w["decision"] == "rate_limited" for w in event_wakes)


def _submit_notice(ledger, outbox, snapshot, operation, now, previous=None, **changes):
    served = ledger.serve(ACTOR, snapshot, lambda: now)
    receipt = ledger.submit(ACTOR, request(served["input_id"], operation_id=operation, previous_read_id=previous, **changes), lambda: now)
    notice = ledger.read_notice(ACTOR, receipt["read_id"])
    write_read_notice(outbox, notice)
    write_read_notice(outbox, notice)  # an exact retry recovers
    return receipt


def test_messages_budget_corrections_links_and_freshness(env, tmp_path):
    runner, clock, _, pushed, _ = env
    ledger = MarketWatchLedger(Ledger(tmp_path / "ledger.sqlite"))
    snapshot = snapshot_at(clock.now)
    publish_snapshot(runner.snapshots_dir, snapshot)
    receipts, previous = [], None
    for i in range(4):
        r = _submit_notice(ledger, runner.outbox_dir, snapshot, f"op{i}", clock.now + timedelta(seconds=i), previous)
        receipts.append(r)
        previous = r["read_id"]
    clock.now += timedelta(seconds=5)  # a notice stamped after the app's clock is refused as future-dated
    runner.ingest_notices(clock.now)
    runner.deliver_messages(clock.now)
    decisions = {d["read_id"]: d for d in runner.store.records("message_decision")}
    assert [decisions[r["read_id"]]["decision"] for r in receipts] == ["send", "send", "send", "suppressed_budget"]
    clock.now += timedelta(seconds=10)
    correction = _submit_notice(ledger, runner.outbox_dir, snapshot, "fix", clock.now, previous,
                                message_intent="correction", correction_of_read_id=receipts[0]["read_id"])
    runner.ingest_notices(clock.now)
    runner.deliver_messages(clock.now)
    final = {d["read_id"]: d for d in runner.store.records("message_decision")}[correction["read_id"]]
    assert final["decision"] == "send" and final["is_correction"] and final["corrects_message_id"] == receipts[0]["message_id"]
    assert len(pushed) == 4 and pushed[-1][0].startswith("Jo correction: DOWN")
    title, body = pushed[0]
    assert title == "Jo market read: DOWN" and "Weak tape" in body and "Wrong if: Reclaim VWAP" in body
    assert "30m 0.60" in body and receipts[0]["read_id"] in body and "late-day holds" in body
    attempts = runner.store.records("message_attempt")
    assert all(a["result"] == "accepted" and a["transport_receipt_id"].startswith("ntfy-") for a in attempts)
    assert {a["read_id"] for a in attempts} == {r["read_id"] for r in receipts[:3]} | {correction["read_id"]}
    runner.deliver_messages(clock.now + timedelta(minutes=1))
    assert len(pushed) == 4


def test_failed_messages_are_recorded_and_never_retried_past_freshness(env, tmp_path):
    runner, clock, _, _, _ = env
    ledger = MarketWatchLedger(Ledger(tmp_path / "ledger.sqlite"))
    snapshot = snapshot_at(clock.now)
    publish_snapshot(runner.snapshots_dir, snapshot)
    _submit_notice(ledger, runner.outbox_dir, snapshot, "op", clock.now)
    tries = []

    def down(title, body):
        tries.append(title)
        raise RuntimeError("ntfy_not_configured")
    runner.push = down
    runner.ingest_notices(clock.now)
    start = clock.now
    for seconds in (0, 70, 140, 700):
        runner.deliver_messages(start + timedelta(seconds=seconds))
    results = [(a["result"], a["error_code"]) for a in runner.store.records("message_attempt")]
    assert results[:3] == [("failed", "ntfy_not_configured")] * 3 and results[3][0] == "expired" and len(tries) == 3
    # A refunded failure does not consume the budget; a notice arriving stale is never sent.
    first_read = runner.store.records("read_notice")[0]["read_id"]
    late = _submit_notice(ledger, runner.outbox_dir, snapshot, "op2", clock.now, previous=first_read)
    runner.ingest_notices(start + timedelta(minutes=11))
    runner.deliver_messages(start + timedelta(minutes=11))
    decision = [d for d in runner.store.records("message_decision") if d["read_id"] == late["read_id"]][0]
    assert decision["decision"] == "expired_before_send" and decision["budget_used_before"] == 0
    assert len(tries) == 3


def test_tampered_or_unpublished_notices_are_refused(env, tmp_path):
    runner, clock, _, _, _ = env
    ledger = MarketWatchLedger(Ledger(tmp_path / "ledger.sqlite"))
    snapshot = snapshot_at(clock.now)  # never published by this app
    receipt = _submit_notice(ledger, runner.outbox_dir, snapshot, "op", clock.now)
    runner.ingest_notices(clock.now)
    assert runner.store.records("read_notice") == []
    publish_snapshot(runner.snapshots_dir, snapshot)
    path = runner.outbox_dir / f"read-{receipt['read_id']}.json"
    notice = json.loads(path.read_text())
    path.write_text(json.dumps({**notice, "main_text": "Buy everything"}))
    runner.ingest_notices(clock.now)
    assert runner.store.records("read_notice") == []
    with pytest.raises(ValueError, match="disagree"):
        write_read_notice(runner.outbox_dir, notice)
    path.write_text(json.dumps(notice))
    runner.ingest_notices(clock.now)
    assert [n["read_id"] for n in runner.store.records("read_notice")] == [receipt["read_id"]]


def test_session_report_links_wakes_reads_messages_and_evaluator_outcomes(env, tmp_path):
    runner, clock, _, _, _ = env
    runner.run_once()  # 09:50 wake accepted
    ledger = MarketWatchLedger(Ledger(tmp_path / "ledger.sqlite"))
    from app.engine.market_watch_snapshot import read_latest_snapshot
    snapshot = read_latest_snapshot(runner.snapshots_dir, clock.now)
    clock.now += timedelta(minutes=2)
    receipt = _submit_notice(ledger, runner.outbox_dir, snapshot, "op", clock.now)
    runner.run_once()
    outcomes = MarketWatchOutcomeStore(tmp_path / "outcomes.sqlite")
    export = MarketWatchLedger.export(ledger.ledger.path, ACTOR)
    outcomes.evaluate_export(export, bars_by_session={}, evaluated_at=CLOSE + timedelta(hours=1))
    report = mw.session_report(runner.store, outcomes)
    day = report["sessions"]["2026-10-14"]
    sent = next(w for w in day["wakes"] if w["ref"] == "09:50")
    assert sent["delivery"] == "accepted" and sent["read_id"] == receipt["read_id"] and sent["attribution"] == "time_window"
    assert next(w for w in day["wakes"] if w["ref"] == "08:50")["outcome"] == "missed_late"
    assert day["reads"]["attributed_to_wake"] == 1 and day["reads"]["notices_missing_from_export"] == []
    assert day["reads"]["notice_hash_mismatches"] == []
    assert day["message_summary"]["discretionary_accepted"] == 1 and day["messages"][0]["read_id"] == receipt["read_id"]
    assert day["outcomes"]["forecast_status_counts"] == {"unavailable": 3}
    assert report["scores"]["total_submitted_slots"] == 3
    assert report["policy_sha256"] == mw.POLICY_SHA256


def test_runner_is_off_by_default_and_needs_absolute_paths(monkeypatch, tmp_path):
    for name in ("MARKET_WATCH_ENABLED", "MARKET_WATCH_SNAPSHOTS_DIR", "MARKET_WATCH_STORE", "MARKET_WATCH_OUTBOX_DIR"):
        monkeypatch.delenv(name, raising=False)
    assert mw.runner_from_env() is None
    monkeypatch.setenv("MARKET_WATCH_ENABLED", "true")
    assert mw.runner_from_env() is None
    monkeypatch.setenv("MARKET_WATCH_SNAPSHOTS_DIR", "relative")
    monkeypatch.setenv("MARKET_WATCH_STORE", str(tmp_path / "w.sqlite"))
    assert mw.runner_from_env() is None
    monkeypatch.setenv("MARKET_WATCH_SNAPSHOTS_DIR", str(tmp_path / "public"))
    assert isinstance(mw.runner_from_env(), mw.MarketWatchRunner)


def test_no_wakes_outside_window_or_on_closed_days(env):
    runner, clock, sent, _, _ = env
    clock.now = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)  # 08:00 ET, before the snapshot window
    runner.run_once()
    runner.bounds = lambda day: None
    clock.now = datetime(2026, 10, 14, 15, 0, tzinfo=UTC)
    runner.run_once()
    assert sent == [] and runner.store.records("wake") == []


def test_check_service_writes_notice_to_outbox_only_when_configured(harness, tmp_path):
    public, outbox = tmp_path / "market-public", tmp_path / "market-outbox"
    public.mkdir()
    outbox.mkdir()
    now = datetime(2026, 10, 14, 14, 0, tzinfo=UTC)
    publish_snapshot(public, snapshot_at(now))
    harness.configure(market_watch_snapshots_dir=str(public), market_watch_outbox_dir=str(outbox))
    scope = "check:read market-watch:read market-watch:submit"
    with TestClient(harness.server(now=now).streamable_http_app()) as client:
        served = call(client, "market_watch_snapshot", {}, harness.token(scope=scope))["structuredContent"]
        req = request(served["input_id"])
        receipt = call(client, "market_watch_submit", req, harness.token(scope=scope))["structuredContent"]
        files = sorted(p.name for p in outbox.iterdir())
        assert files == [f"read-{receipt['read_id']}.json"]
        (outbox / files[0]).unlink()  # a lost handoff is recovered by the identical retry
        again = call(client, "market_watch_submit", req, harness.token(scope=scope))["structuredContent"]
        assert again["replayed"] and (outbox / files[0]).exists()
    notice = json.loads((outbox / files[0]).read_text())
    assert notice["message_id"] == receipt["message_id"] and notice["read_sha256"] == receipt["content_sha256"]
    assert mw.validate_notice(notice, public, now + timedelta(seconds=1))["snapshot_id"] == served["snapshot_id"]


def test_check_config_requires_snapshots_dir_and_disjoint_outbox(harness, tmp_path):
    from cloud_mcp_check_common import CheckConfig
    body = json.loads(harness.config_path.read_text())
    with pytest.raises(ValueError):
        CheckConfig.model_validate({**body, "market_watch_outbox_dir": str(tmp_path / "out")})
    with pytest.raises(ValueError):
        CheckConfig.model_validate({**body, "market_watch_snapshots_dir": str(tmp_path / "pub"),
                                    "market_watch_outbox_dir": str(tmp_path / "pub" / "out")})
    CheckConfig.model_validate({**body, "market_watch_snapshots_dir": str(tmp_path / "pub"), "market_watch_outbox_dir": str(tmp_path / "out")})


def test_ntfy_publish_returns_accept_receipt(monkeypatch):
    from app.engine import ntfy

    class Response:
        status_code = 200

        def json(self):
            return {"id": "abc123", "event": "message"}
    monkeypatch.setenv("NTFY_URL", "https://ntfy.example/topic")
    monkeypatch.setattr(ntfy.httpx, "post", lambda *a, **k: Response())
    assert ntfy.publish("t", "m") == "abc123"


def test_notice_builder_is_deterministic(tmp_path):
    ledger = MarketWatchLedger(Ledger(tmp_path / "ledger.sqlite"))
    now = datetime(2026, 10, 14, 14, 0, tzinfo=UTC)
    served = ledger.serve(ACTOR, snapshot_at(now), lambda: now)
    receipt = ledger.submit(ACTOR, request(served["input_id"], message_intent="none"), lambda: now)
    first = ledger.read_notice(ACTOR, receipt["read_id"])
    assert first == ledger.read_notice(ACTOR, receipt["read_id"]) and first["message_id"] is None
    assert first == read_notice(*_read_and_intent(ledger, receipt["read_id"]))


def _read_and_intent(ledger, read_id):
    export = MarketWatchLedger.export(ledger.ledger.path, ACTOR)
    read = next(r for r in export["reads"] if r["read_id"] == read_id)
    return read, next((m for m in export["messages"] if m["read_id"] == read_id and m["kind"] == "intent"), None)
