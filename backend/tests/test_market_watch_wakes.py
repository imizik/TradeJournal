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


def snapshot_at(now, closes=None, calendar_events=(), highs=None, drop=()):
    minutes = max(0, int((min(now, CLOSE) - OPEN).total_seconds() // 60))
    closes = (closes or [100.0] * 400)[:minutes]
    spy = _rows(closes)
    for index, high in (highs or {}).items():
        spy[index]["h"] = high
    spy = [row for i, row in enumerate(spy) if i not in drop]
    bars = {"SPY": spy, "QQQ": _rows([c * 4 for c in closes])} if closes else {"SPY": [], "QQQ": []}
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
    clock = Clock(START)
    sent, pushed = [], []

    def mail(subject, body):
        sent.append((subject, body))

    def push(title, body):
        pushed.append((title, body))
        return f"ntfy-{len(pushed)}"

    runner = mw.MarketWatchRunner(mw.MarketWatchWakeStore(tmp_path / "wakes.sqlite"), snapshots, outbox_dir=outbox,
                                  clock=clock, bounds=lambda day: BOUNDS, mail=mail, push=push, daily=lambda day: [],
                                  setup_window=lambda now: False)
    return runner, clock, sent, pushed, tmp_path


START = datetime(2026, 10, 14, 14, 20, 20, tzinfo=UTC)  # 10:20 ET: clear of Jo's 09:50 and 11:00 scheduled reads


def publish_cross(runner, now=START):
    """Publish (as #315's timer would) a snapshot whose newest bar crosses VWAP and the opening range."""
    minutes = int((now - OPEN).total_seconds() // 60)
    snapshot = snapshot_at(now, [100.0] * 15 + [100.5] * (minutes - 16) + [99.0])
    publish_snapshot(runner.snapshots_dir, snapshot)
    return snapshot


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


def test_level_cooldown_is_real_and_failed_reclaims_are_detected(monkeypatch):
    # Cross down at bar 16, back up at bar 27 (inside 30 minutes), down again at bar 55 (after 30 minutes).
    closes = [100.0] * 15 + [100.5] + [99.0] * 11 + [100.5] * 28 + [99.0] * 5
    now = OPEN + timedelta(minutes=len(closes))
    snap = snapshot_at(now, closes)
    vwap = [e for e in mw.detect_events(snap, detected_at=now) if e["detail"].get("level") == "vwap"]
    assert [(e["kind"], e["detail"]["direction"]) for e in vwap] == [("level_cross", "down"), ("level_cross", "down")]
    assert parse(vwap[1]["occurred_at"]) - parse(vwap[0]["occurred_at"]) >= timedelta(minutes=30)
    monkeypatch.setitem(mw.DETECTOR, "level_cooldown_minutes", 0)
    assert len([e for e in mw.detect_events(snap, detected_at=now) if e["detail"].get("level") == "vwap"]) == 3
    # Below VWAP, a wick reaches it and the bar closes back below: a failed reclaim.
    closes = [100.0] * 15 + [100.5] + [99.0] * 40
    snap = snapshot_at(OPEN + timedelta(minutes=len(closes)), closes, highs={50: 100.2})
    fails = [e for e in mw.detect_events(snap, detected_at=now) if e["kind"] == "level_fail"]
    assert ("vwap", "down") in [(e["detail"]["level"], e["detail"]["direction"]) for e in fails]


def test_atr_move_since_last_read_fires_per_multiple():
    closes = [100.0] * 15 + [100.5, 99.0] + [99.2] * 5 + [98.4]
    now = OPEN + timedelta(minutes=len(closes))
    snap = snapshot_at(now, closes)
    read = {"read_id": "mwr_00000000-0000-4000-8000-000000000001", "received_at": (OPEN + timedelta(minutes=17)).isoformat(), "price": 100.6}
    atr_events = [e for e in mw.detect_events(snap, detected_at=now, atr={"atr14": 2.0, "bars_sha256": "x"}, last_read=read)
                  if e["kind"] == "atr_move_since_read"]
    assert [(e["detail"]["direction"], e["detail"]["multiple"]) for e in atr_events] == [("down", 1), ("down", 2)]
    assert not any(e["kind"] == "atr_move_since_read" for e in mw.detect_events(snap, detected_at=now, atr=None, last_read=read))


def test_missing_minute_is_recorded_and_only_vwap_stops(env):
    runner, clock, _, _, _ = env
    closes = [100.0] * 15 + [100.5] + [99.0] * 74 + [97.0]
    now = OPEN + timedelta(minutes=len(closes))
    snap = snapshot_at(now, closes, drop={5})
    events = mw.detect_events(snap, detected_at=now)
    gap = [e for e in events if e["kind"] == "minute_gap"]
    assert len(gap) == 1 and gap[0]["detail"]["missing_from"] == "2026-10-14T13:35:00.000000Z"
    assert any(e["kind"] == "new_session_low" for e in events)  # extremes still watch the real bars
    assert not any(e["detail"].get("level") in ("vwap", "or15_high", "or15_low") for e in events)  # no VWAP, no full OR
    for e in events:
        runner.store.append("event", e, ident=e["event_id"])
    runner.plan_wakes(now, now.date(), CLOSE, snap)
    assert all(w["event_id"] != gap[0]["event_id"] for w in runner.store.records("wake"))


def parse(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


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


def test_event_wake_sends_only_an_id_publishes_nothing_and_never_resends(env):
    runner, clock, sent, _, _ = env
    runner.run_once()
    assert sent == [] and runner.store.records("wake") == []  # no snapshot published yet: nothing to detect, no scheduled wakes
    publish_cross(runner)
    files = sorted(p.name for p in runner.snapshots_dir.rglob("*"))
    runner.run_once()
    assert sorted(p.name for p in runner.snapshots_dir.rglob("*")) == files  # MW-2 never publishes snapshots
    wakes = runner.store.records("wake", "2026-10-14")
    assert {w["trigger"] for w in wakes} == {"event"}
    sent_wakes = [w for w in wakes if w["decision"] == "send"]
    assert len(sent_wakes) == 1 and all(w["decision"] == "coalesced" for w in wakes if w not in sent_wakes)
    wake_id = sent_wakes[0]["wake_id"]
    assert sent == [(f"TJ Market Watch: {wake_id}", f"Wake ID: {wake_id}\n")]
    clock.now += timedelta(seconds=30)
    runner.run_once()
    assert len(sent) == 1
    attempts = runner.store.records("wake_attempt")
    assert [(a["wake_id"], a["result"], a["channel"]) for a in attempts] == [(wake_id, "sending", "email"), (wake_id, "accepted", "email")]


def test_event_wakes_coalesce_with_jos_scheduled_reads(env):
    runner, clock, sent, _, _ = env
    for local, expected in (("10:56", "coalesced"), ("11:02", "coalesced"), ("11:20", "send")):
        hour, minute = map(int, local.split(":"))
        now = datetime(2026, 10, 14, hour + 4, minute, 20, tzinfo=UTC)
        snapshot = snapshot_at(now)
        e = mw._event(snapshot, "new_session_low", [local], now.isoformat(), now, {})
        runner.store.append("event", e, ident=e["event_id"])
        runner.plan_wakes(now, now.date(), CLOSE, snapshot)
        wake = next(w for w in runner.store.records("wake") if w["event_id"] == e["event_id"])
        assert wake["decision"] == expected, local
        if expected == "coalesced":
            assert "scheduled 11:00" in wake["reason"]


def test_event_wakes_wait_while_an_s1_setup_awaits_its_shadow_commit(env, tmp_path, monkeypatch):
    runner, clock, sent, _, _ = env
    runner.setup_window = lambda now: True
    publish_cross(runner)
    runner.run_once()
    assert sent == [] and {w["decision"] for w in runner.store.records("wake")} <= {"setup_guard", "coalesced"}
    assert any(w["decision"] == "setup_guard" for w in runner.store.records("wake"))
    # The default reader only reads S1's events: a sent email without a shadow decision is busy; decided or old is not.
    import uuid as _uuid
    from sqlmodel import Session, SQLModel, create_engine
    from app import database
    from app.models import ScannerCandidate, ScannerEvent
    engine = create_engine(f"sqlite:///{tmp_path / 's1.sqlite'}")
    SQLModel.metadata.create_all(engine, tables=[ScannerCandidate.__table__, ScannerEvent.__table__])
    monkeypatch.setattr(database, "engine", engine)
    now = START

    def add(candidate, kind, minutes_ago, status=None):
        with Session(engine) as db:
            at = (now - timedelta(minutes=minutes_ago)).replace(tzinfo=None)
            db.add(ScannerEvent(candidate_id=candidate, key=kind, event_type=kind, effective_at=at, recorded_at=at,
                                data_json=json.dumps({"status": status} if status else {})))
            db.commit()
    assert mw._default_setup_window(now) is False
    old, fresh = _uuid.uuid4(), _uuid.uuid4()
    add(old, "email", 30, "sent")
    assert mw._default_setup_window(now) is False
    add(fresh, "email", 2, "sent")
    assert mw._default_setup_window(now) is True
    add(fresh, "shadow_decision", 1)
    assert mw._default_setup_window(now) is False
    monkeypatch.setattr(database, "engine", None)
    assert mw._default_setup_window(now) is True  # unknown state protects S1


def test_wake_failures_retry_within_freshness_then_expire(env):
    runner, clock, _, _, _ = env
    publish_cross(runner)
    calls = []

    def broken(subject, body):
        calls.append(subject)
        raise OSError("smtp down")
    runner.mail = broken
    for seconds in (0, 30, 61, 122, 183, 300):
        clock.now = START + timedelta(seconds=seconds)
        runner.run_once()
    results = [(a["attempt"], a["result"], a["error_code"]) for a in runner.store.records("wake_attempt") if a["result"] != "sending"]
    assert results == [(1, "failed", "OSError"), (2, "failed", "OSError"), (3, "failed", "OSError"), (3, "expired", "attempts_exhausted")]
    assert len(calls) == 3
    report = mw.session_report(runner.store)["sessions"]["2026-10-14"]
    assert next(w for w in report["wakes"] if w["decision"] == "send")["attempts"] == 3


def test_wake_past_freshness_expires_without_sending(env):
    runner, clock, sent, _, _ = env
    publish_cross(runner)
    runner.mail = lambda subject, body: (_ for _ in ()).throw(OSError("down"))
    runner.run_once()
    runner.mail = lambda subject, body: sent.append(subject)
    clock.now += timedelta(minutes=6)
    runner.run_once()
    assert sent == [] and [a["error_code"] for a in runner.store.records("wake_attempt") if a["result"] == "expired"] == ["past_freshness"]


def test_uncertain_and_interrupted_sends_are_unknown_and_never_resent(env):
    import httpx
    from app.engine import ntfy
    runner, clock, sent, _, _ = env
    publish_cross(runner)
    tries = []

    def timeout(subject, body):
        tries.append(subject)
        try:
            raise httpx.ReadTimeout("slow")
        except httpx.ReadTimeout as exc:
            raise ntfy.NtfyError("ntfy could not be reached (ReadTimeout).") from exc
    runner.mail = timeout
    runner.run_once()
    clock.now += timedelta(minutes=2)
    runner.run_once()
    assert len(tries) == 1
    assert [a["result"] for a in runner.store.records("wake_attempt")] == ["sending", "unknown"]
    # A crash after "sending" but before the result: the next pass records unknown and sends nothing.
    snapshot = snapshot_at(clock.now)
    e = mw._event(snapshot, "level_cross", ["vwap", "up", "x"], clock.now.isoformat(), clock.now, {"level": "vwap"})
    runner.store.append("event", e, ident=e["event_id"])
    clock.now += timedelta(minutes=20)
    runner.plan_wakes(clock.now, clock.now.date(), CLOSE, snapshot)
    wake = next(w for w in runner.store.records("wake") if w["event_id"] == e["event_id"])
    runner._attempt("wake_attempt", clock.now, "2026-10-14", "wake_id", wake["wake_id"], 1, "sending", "email")
    runner.mail = lambda subject, body: sent.append(subject)
    runner.send_wakes(clock.now, clock.now.date())
    assert sent == [] and [a["result"] for a in runner.store.records("wake_attempt") if a["wake_id"] == wake["wake_id"]] == ["sending", "unknown"]


def test_event_wakes_are_rate_limited_coalesced_and_late_events_never_wake(env):
    runner, clock, sent, _, _ = env
    snapshot = snapshot_at(clock.now)

    def event(minute, late=False):
        at = clock.now - timedelta(minutes=30 if late else 0)
        return mw._event(snapshot, "level_cross", ["vwap", "down", str(minute)], at.isoformat(), clock.now, {"level": "vwap"})
    for e in (event(0), event(1), event(2, late=True)):
        runner.store.append("event", e, ident=e["event_id"])
    runner.plan_wakes(clock.now, clock.now.date(), CLOSE, snapshot)
    assert sorted(w["decision"] for w in runner.store.records("wake")) == ["coalesced", "event_late", "send"]
    clock.now = datetime(2026, 10, 14, 15, 20, 20, tzinfo=UTC)  # 11:20 ET, past the 11:00 scheduled read
    for i in range(8):
        clock.now += timedelta(minutes=16)
        e = event(10 + i)
        runner.store.append("event", e, ident=e["event_id"])
        runner.plan_wakes(clock.now, clock.now.date(), CLOSE, snapshot)
        runner.send_wakes(clock.now, clock.now.date())
    event_wakes = runner.store.records("wake")
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
    from market_watch_ledger import MessageBudgetExceeded
    runner, clock, _, pushed, _ = env
    ledger = MarketWatchLedger(Ledger(tmp_path / "ledger.sqlite"))
    snapshot = snapshot_at(clock.now)
    publish_snapshot(runner.snapshots_dir, snapshot)
    real_push = runner.push
    runner.push = lambda title, body: real_push(title, body) if len(pushed) < 2 else (_ for _ in ()).throw(RuntimeError("ntfy_not_configured"))
    receipts, previous = [], None
    for i in range(3):
        r = _submit_notice(ledger, runner.outbox_dir, snapshot, f"op{i}", clock.now + timedelta(seconds=i), previous)
        receipts.append(r)
        previous = r["read_id"]
    # The check ledger (#315) refuses a fourth ordinary intent before anything is committed.
    served = ledger.serve(ACTOR, snapshot, lambda: clock.now + timedelta(seconds=4))
    with pytest.raises(MessageBudgetExceeded):
        ledger.submit(ACTOR, request(served["input_id"], operation_id="op3", previous_read_id=previous), lambda: clock.now + timedelta(seconds=4))
    clock.now += timedelta(seconds=5)  # a notice stamped after the app's clock is refused as future-dated
    for step in range(4):  # the third push keeps failing and expires after its retries
        runner.ingest_notices(clock.now)
        runner.deliver_messages(clock.now)
        clock.now += timedelta(seconds=61)
    decisions = {d["read_id"]: d for d in runner.store.records("message_decision")}
    assert [decisions[r["read_id"]]["decision"] for r in receipts] == ["send", "send", "send"]
    assert len(pushed) == 2
    title, body = pushed[0]
    assert title == "Jo market read: DOWN" and "Weak tape" in body and "Wrong if: Reclaim VWAP" in body
    assert "30m 0.60" in body and receipts[0]["read_id"] in body and "late-day holds" in body
    attempts = [a for a in runner.store.records("message_attempt") if a["result"] in ("accepted", "expired")]
    assert {(a["read_id"], a["result"]) for a in attempts} == {(receipts[0]["read_id"], "accepted"), (receipts[1]["read_id"], "accepted"),
                                                               (receipts[2]["read_id"], "expired")}
    assert all(a["transport_receipt_id"].startswith("ntfy-") for a in attempts if a["result"] == "accepted")
    runner.push = real_push

    def correct(operation, target):
        nonlocal previous
        clock.now += timedelta(seconds=10)
        r = _submit_notice(ledger, runner.outbox_dir, snapshot, operation, clock.now, previous,
                           message_intent="correction", correction_of_read_id=target["read_id"])
        previous = r["read_id"]
        runner.ingest_notices(clock.now)
        runner.deliver_messages(clock.now)
        return {d["read_id"]: d for d in runner.store.records("message_decision")}[r["read_id"]]
    # A correction of a message Isaac got is budget-free, once per corrected message.
    first = correct("fix", receipts[0])
    assert first["decision"] == "send" and first["budget_free"] and first["corrects_message_id"] == receipts[0]["message_id"]
    assert pushed[-1][0].startswith("Jo correction: DOWN")
    # Correcting the never-delivered third message is budgeted like an update (the expired send was refunded).
    unsent = correct("fix-unsent", receipts[2])
    assert unsent["decision"] == "send" and not unsent["budget_free"] and unsent["budget_used_before"] == 2
    # A second correction of the same delivered message is budgeted too; the budget is now spent.
    again = correct("fix-again", receipts[0])
    assert again["decision"] == "suppressed_budget" and not again["budget_free"]
    assert len(pushed) == 4
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
    results = [(a["result"], a["error_code"]) for a in runner.store.records("message_attempt") if a["result"] != "sending"]
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
    runner.ingest_notices(clock.now)
    assert runner.store.records("read_notice") == []
    refusals = runner.store.records("notice_refusal")
    assert len(refusals) == 2 and {r["read_id"] for r in refusals} == {receipt["read_id"]}  # unpublished, then tampered; once each
    # A malformed but correctly sealed notice beside a valid one never stalls ingestion.
    junk = seal({**{k: v for k, v in notice.items() if k not in ("content_sha256",)}, "read_id": "mwr_00000000-0000-4000-8000-0000000000ff", "forecasts": [1, 2, 3]})
    (runner.outbox_dir / f"read-{junk['read_id']}.json").write_text(json.dumps(junk))
    with pytest.raises(ValueError, match="disagree"):
        write_read_notice(runner.outbox_dir, notice)
    path.write_text(json.dumps(notice))
    runner.ingest_notices(clock.now)
    assert [n["read_id"] for n in runner.store.records("read_notice")] == [receipt["read_id"]]


def test_session_report_links_wakes_reads_messages_and_evaluator_outcomes(env, tmp_path):
    runner, clock, _, _, _ = env
    snapshot = publish_cross(runner)
    runner.run_once()  # one event wake accepted
    wake_id = next(w["wake_id"] for w in runner.store.records("wake") if w["decision"] == "send")
    ledger = MarketWatchLedger(Ledger(tmp_path / "ledger.sqlite"))
    clock.now += timedelta(minutes=2)
    receipt = _submit_notice(ledger, runner.outbox_dir, snapshot, f"mw-event-v1:{wake_id}", clock.now)
    runner.run_once()
    # Jo's own 11:00 scheduled read (#315), linked by its operation ID; a manual read stays unprompted.
    clock.now = datetime(2026, 10, 14, 15, 0, 40, tzinfo=UTC)
    later = snapshot_at(clock.now)
    publish_snapshot(runner.snapshots_dir, later)
    scheduled = _submit_notice(ledger, runner.outbox_dir, later, "mw-scheduled-v1:2026-10-14:11:00", clock.now,
                               receipt["read_id"], message_intent="none")
    clock.now += timedelta(minutes=40)
    manual = _submit_notice(ledger, runner.outbox_dir, later, "manual", clock.now, scheduled["read_id"], message_intent="none")
    runner.ingest_notices(clock.now)
    outcomes = MarketWatchOutcomeStore(tmp_path / "outcomes.sqlite")
    export = MarketWatchLedger.export(ledger.ledger.path, ACTOR)
    outcomes.evaluate_export(export, bars_by_session={}, evaluated_at=CLOSE + timedelta(hours=1))
    report = mw.session_report(runner.store, outcomes)
    day = report["sessions"]["2026-10-14"]
    sent = next(w for w in day["wakes"] if w["wake_id"] == wake_id)
    assert sent["delivery"] == "accepted" and sent["read_id"] == receipt["read_id"] and sent["attribution"] == "operation_id"
    slots = {r["slot"]: r for r in day["scheduled_reads"]}
    assert slots["11:00"]["read_id"] == scheduled["read_id"] and slots["11:00"]["attribution"] == "operation_id"
    assert slots["09:50"]["outcome"] == "no_read_seen" and slots["14:00"]["outcome"] == "no_read_seen"
    assert day["reads"]["attributed_to_wake"] == 2 and day["reads"]["unprompted"] == 1 and manual["read_id"] in day["reads"]["read_ids"]
    assert day["reads"]["notices_missing_from_export"] == [] and day["reads"]["notice_hash_mismatches"] == []
    assert day["message_summary"]["discretionary_accepted"] == 1 and day["messages"][0]["read_id"] == receipt["read_id"]
    assert day["outcomes"]["forecast_status_counts"] == {"unavailable": 9}
    assert report["scores"]["total_submitted_slots"] == 9
    assert report["policy_sha256"] == mw.POLICY_SHA256
    # A setup-context read just after a scheduled slot that saved nothing is never credited to that slot.
    clock.now = datetime(2026, 10, 14, 16, 32, 0, tzinfo=UTC)  # 12:32 ET
    setup_read = _submit_notice(ledger, runner.outbox_dir, later, "mw-setup-context-v1:2026-10-14:x", clock.now,
                                manual["read_id"], message_intent="none")
    runner.ingest_notices(clock.now)
    second = MarketWatchOutcomeStore(tmp_path / "outcomes2.sqlite")
    second.evaluate_export(MarketWatchLedger.export(ledger.ledger.path, ACTOR), bars_by_session={}, evaluated_at=CLOSE + timedelta(hours=1))
    slots = {r["slot"]: r for r in mw.session_report(runner.store, second)["sessions"]["2026-10-14"]["scheduled_reads"]}
    assert slots["12:30"]["outcome"] == "no_read_seen" and slots["12:30"]["read_id"] is None
    assert setup_read["read_id"]
    # Without the export, the event read is still linked by time.
    plain = mw.session_report(runner.store)["sessions"]["2026-10-14"]
    assert next(w for w in plain["wakes"] if w["wake_id"] == wake_id)["attribution"] == "time_window"


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
    publish_cross(runner)
    clock.now = datetime(2026, 10, 14, 13, 0, tzinfo=UTC)  # 09:00 ET, before the open
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


def test_bad_market_watch_settings_never_stop_the_api(monkeypatch, tmp_path):
    import asyncio
    from types import SimpleNamespace
    from app import main
    foreign = tmp_path / "foreign.sqlite"
    sqlite3.connect(foreign).execute("CREATE TABLE fills(id)").connection.commit()
    monkeypatch.setenv("MARKET_WATCH_ENABLED", "true")
    monkeypatch.setenv("MARKET_WATCH_SNAPSHOTS_DIR", str(tmp_path / "public"))
    monkeypatch.setenv("MARKET_WATCH_STORE", str(foreign))
    app_ = SimpleNamespace(state=SimpleNamespace())
    assert asyncio.run(main._maybe_start_market_watch(app_)) is None and app_.state.market_watch is None
