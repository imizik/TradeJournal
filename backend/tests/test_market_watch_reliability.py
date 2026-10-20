"""Scheduled market-read reliability: packets, reads seen and measured delays, with no tolerance."""
from datetime import UTC, date, datetime, timedelta
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.engine import market_watch_wakes as mw
from app.engine.market_watch_evaluation import MarketWatchOutcomeStore
from app.engine.market_watch_snapshot import publish_snapshot
from app.routers import market_reads as route
from cloud_mcp_check_ledger import Ledger
import market_watch_schedule as schedule
from market_watch_ledger import MarketWatchLedger
from tests.test_market_watch_ledger import ACTOR
from tests.test_market_watch_wakes import CLOSE, _submit_notice, env as env, snapshot_at

DAY = date(2026, 10, 14)
OPEN_DAY = {"status": "open", "open": 570, "close": 960}
EVENING = datetime(2026, 10, 14, 21, 0, tzinfo=UTC)


def et(hour, minute, second=0):
    return datetime(2026, 10, 14, hour + 4, minute, second, tzinfo=UTC)


def receipt(root, day, prep, attempt, phase, status, **extra):
    record = {"schema_version": 1, "session_date": day.isoformat(), "slot": prep, "purpose": "planned_jo_wake_packet",
              "scheduled_read_slot": None, "attempt": attempt, "recorded_at": f"{day.isoformat()}T13:49:05Z",
              "phase": phase, "status": status, **extra}
    schedule._write_immutable(root / day.isoformat() / prep / f"attempt-{attempt:02d}-{phase}.json", record)


class Jo:
    """Submits reads through the real ledger and outbox, chaining each to the last."""

    def __init__(self, runner, tmp_path):
        self.runner, self.ledger, self.last = runner, MarketWatchLedger(Ledger(tmp_path / "ledger.sqlite")), None

    def read(self, at, operation):
        snapshot = snapshot_at(at)
        publish_snapshot(self.runner.snapshots_dir, snapshot)
        got = _submit_notice(self.ledger, self.runner.outbox_dir, snapshot, operation, at, self.last, message_intent="none")
        self.last = got["read_id"]
        self.runner.ingest_notices(at)
        return got, snapshot


def report(runner, receipts, now=EVENING, hours=lambda day: OPEN_DAY, **kw):
    return mw.reliability_report(runner.store, receipts, [DAY], hours=hours, now=now, **kw)["sessions"][0]


def slots(session):
    return {s["slot"]: s for s in session["slots"]}


def test_slots_show_packets_reads_and_measured_delays_without_a_tolerance(env, tmp_path):
    runner, *_ = env
    receipts = tmp_path / "receipts"
    jo = Jo(runner, tmp_path)
    first, snap = jo.read(et(9, 52, 10), "mw-scheduled-v1:2026-10-14:09:50")
    late, _ = jo.read(et(11, 17, 30), "mw-scheduled-v1:2026-10-14:11:00")
    beyond, _ = jo.read(et(14, 45), "mw-scheduled-v1:2026-10-14:14:00")  # past the 30-minute time window
    receipt(receipts, DAY, "09-49", 1, "started", "started")
    receipt(receipts, DAY, "09-49", 1, "published", "published", snapshot_id=snap["snapshot_id"], quality_flags=[])
    receipt(receipts, DAY, "10-59", 1, "started", "started")
    receipt(receipts, DAY, "10-59", 1, "failed", "failed", error_code="snapshot_collection_failed")
    receipt(receipts, DAY, "12-29", 1, "started", "started")  # crashed mid-publish: outcome unknown
    # 13-59 has no receipt at all: the publisher never ran for it.
    s = slots(report(runner, receipts))

    assert s["09:50"]["status"] == "read_seen" and s["09:50"]["read_id"] == first["read_id"]
    assert s["09:50"]["attribution"] == "time_window" and s["09:50"]["receipt_delay_seconds"] == 130
    assert s["09:50"]["packet"]["status"] == "published" and s["09:50"]["read_used_slot_packet"] is True
    assert s["11:00"]["receipt_delay_seconds"] == 17 * 60 + 30 and s["11:00"]["read_used_slot_packet"] is None
    assert s["11:00"]["packet"] == {"slot": "10-59", "status": "failed", "attempts": 1, "recorded_at": "2026-10-14T13:49:05Z",
                                     "snapshot_id": None, "error_code": "snapshot_collection_failed", "quality_flags": []}
    assert s["12:30"]["status"] == "no_read_seen" and s["12:30"]["receipt_delay_seconds"] is None
    assert s["12:30"]["packet"]["status"] == "started"
    assert s["14:00"]["packet"]["status"] == "no_receipt"
    # Without an exported operation ID, a read beyond the window is listed, never credited to the slot.
    assert s["14:00"]["status"] == "no_read_seen" and s["14:00"]["read_id"] is None
    session = report(runner, receipts)
    assert [r["read_id"] for r in session["reads_not_credited_to_a_slot"]] == [beyond["read_id"]]
    assert session["summary"] == {"read_seen": 2, "no_read_seen": 2, "upcoming": 0, "not_expected": 0, "unknown": 0}
    assert not any(k in json.dumps(session) for k in ("on_time", "late\"", "tolerance"))

    # The exported operation ID links the 14:00 read exactly, so its real delay shows.
    outcomes = MarketWatchOutcomeStore(tmp_path / "outcomes.sqlite")
    outcomes.evaluate_export(MarketWatchLedger.export(jo.ledger.ledger.path, ACTOR), bars_by_session={},
                             evaluated_at=CLOSE + timedelta(hours=1))
    exact = report(runner, receipts, outcome_store=outcomes)
    s = slots(exact)
    assert s["14:00"]["read_id"] == beyond["read_id"] and s["14:00"]["attribution"] == "operation_id"
    assert s["14:00"]["receipt_delay_seconds"] == 45 * 60
    assert s["09:50"]["attribution"] == "operation_id" and exact["reads_not_credited_to_a_slot"] == []


def test_read_from_another_workflow_is_never_credited_to_a_slot(env, tmp_path):
    runner, *_ = env
    jo = Jo(runner, tmp_path)
    setup, _ = jo.read(et(12, 33), "mw-setup-context-v1:2026-10-14:x")
    outcomes = MarketWatchOutcomeStore(tmp_path / "outcomes.sqlite")
    outcomes.evaluate_export(MarketWatchLedger.export(jo.ledger.ledger.path, ACTOR), bars_by_session={},
                             evaluated_at=CLOSE + timedelta(hours=1))
    session = report(runner, tmp_path / "receipts", outcome_store=outcomes)
    assert slots(session)["12:30"]["status"] == "no_read_seen"
    assert [r["read_id"] for r in session["reads_not_credited_to_a_slot"]] == [setup["read_id"]]


def test_duplicate_notices_and_restarts_count_one_read(env, tmp_path):
    runner, *_ = env
    jo = Jo(runner, tmp_path)
    got, _ = jo.read(et(9, 51), "mw-scheduled-v1:2026-10-14:09:50")  # the helper writes the notice twice
    runner.ingest_notices(et(9, 52))
    second, _ = jo.read(et(9, 55), "manual")  # a second read in the same window is not double-credited
    before = report(runner, tmp_path / "receipts")
    runner.store = mw.MarketWatchWakeStore(runner.store.path)  # API restart: everything is rebuilt from the file
    runner.ingest_notices(et(10, 0))
    after = report(runner, tmp_path / "receipts")
    assert after == before
    assert len(runner.store.records("read_notice")) == 2
    assert slots(after)["09:50"]["read_id"] == got["read_id"]
    assert [r["read_id"] for r in after["reads_not_credited_to_a_slot"]] == [second["read_id"]]


def test_publisher_retry_reports_latest_attempt_and_unreadable_receipts(env, tmp_path):
    runner, *_ = env
    receipts = tmp_path / "receipts"
    receipt(receipts, DAY, "09-49", 1, "started", "started")
    receipt(receipts, DAY, "09-49", 1, "failed", "failed", error_code="snapshot_unavailable")
    receipt(receipts, DAY, "09-49", 2, "started", "started")
    receipt(receipts, DAY, "09-49", 2, "published", "published_partial", snapshot_id="mws_x", quality_flags=["vix_stale"])
    receipt(receipts, DAY, "10-59", 1, "started", "started")
    tampered = receipts / DAY.isoformat() / "10-59" / "attempt-01-started.json"
    tampered.chmod(0o600)
    tampered.write_text(tampered.read_text().replace("started", "published", 1))
    s = slots(report(runner, receipts))
    assert s["09:50"]["packet"]["status"] == "published_partial" and s["09:50"]["packet"]["attempts"] == 2
    assert s["09:50"]["packet"]["quality_flags"] == ["vix_stale"]
    assert s["11:00"]["packet"]["status"] == "unreadable"


def test_holiday_early_close_unknown_calendar_and_upcoming(env, tmp_path):
    runner, *_ = env
    receipts = tmp_path / "receipts"
    receipt(receipts, DAY, "09-49", 1, "started", "started")
    receipt(receipts, DAY, "09-49", 1, "skipped", "skipped_exchange_closed")
    holiday = report(runner, receipts, hours=lambda day: {"status": "closed", "open": None, "close": None})
    assert {s["status"] for s in holiday["slots"]} == {"not_expected"}
    assert {s["not_expected_reason"] for s in holiday["slots"]} == {"exchange_closed"}
    assert slots(holiday)["09:50"]["packet"]["status"] == "skipped_exchange_closed"

    half = slots(report(runner, receipts, hours=lambda day: {"status": "open", "open": 570, "close": 780}))
    assert half["12:30"]["expected"] is True and half["12:30"]["status"] == "no_read_seen"
    assert (half["14:00"]["expected"], half["14:00"]["not_expected_reason"], half["14:00"]["status"]) == (False, "after_close", "not_expected")

    unknown = slots(report(runner, receipts, hours=lambda day: None))
    assert unknown["09:50"]["expected"] is None and unknown["09:50"]["not_expected_reason"] == "exchange_calendar_unavailable"

    def broken(day):
        raise RuntimeError("tradier down")
    assert slots(report(runner, receipts, hours=broken))["11:00"]["expected"] is None

    midday = slots(report(runner, receipts, now=et(12, 0)))
    assert midday["09:50"]["status"] == "no_read_seen" and midday["12:30"]["status"] == "upcoming"


def test_missing_evidence_is_unknown_not_missing(tmp_path):
    session = mw.reliability_report(None, tmp_path / "absent", [DAY], hours=lambda day: OPEN_DAY, now=EVENING)
    assert session["reads_available"] is False and session["receipts_available"] is False
    s = slots(session["sessions"][0])
    assert s["09:50"]["status"] == "unknown" and s["09:50"]["packet"]["status"] == "unknown"


@pytest.fixture
def client(env, tmp_path, monkeypatch):
    runner, *_ = env
    receipts = tmp_path / "receipts"
    receipt(receipts, DAY, "09-49", 1, "started", "started")
    monkeypatch.setenv("MARKET_WATCH_STORE", str(runner.store.path))
    monkeypatch.setattr(route, "_receipts", lambda: receipts)
    monkeypatch.setattr(route, "_hours", lambda day: OPEN_DAY)
    monkeypatch.setattr(route, "_now", lambda: datetime(2026, 10, 16, 21, 0, tzinfo=UTC))
    app = FastAPI()
    app.include_router(route.router, prefix="/jo/market-reads")
    return TestClient(app)


def test_route_lists_weekdays_back_to_the_first_evidence(client):
    view = client.get("/jo/market-reads").json()
    assert [s["session_date"] for s in view["sessions"]] == ["2026-10-16", "2026-10-15", "2026-10-14"]
    assert view["reads_available"] and view["receipts_available"]
    assert {s["status"] for s in view["sessions"][0]["slots"]} == {"no_read_seen"}


def test_route_days_skip_weekends_and_cap():
    assert route._days(date(2026, 10, 19), date(2026, 10, 16)) == [date(2026, 10, 19), date(2026, 10, 16)]
    assert len(route._days(date(2026, 10, 19), date(2026, 1, 1))) == route.SESSIONS
    assert route._days(date(2026, 10, 18), None) == []
