from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
import json
from pathlib import Path
import threading

import pytest

from market_watch_schedule import (
    ENV_ALLOWLIST,
    ScheduleRefused,
    _parse_dotenv,
    _snapshot_quality,
    _runtime_env,
    run_slot,
    scheduled_slot,
)


ROOT = Path(__file__).resolve().parents[2]
ET = __import__("zoneinfo").ZoneInfo("America/New_York")


def at(clock: str, day: str = "2026-10-14") -> datetime:
    hour, minute = (int(part) for part in clock.split(":"))
    return datetime.fromisoformat(day).replace(hour=hour, minute=minute, tzinfo=ET)


def snapshot(now: datetime, *, stale=False):
    from tests.test_market_watch_snapshot import fixture_snapshot
    return fixture_snapshot(now=now.astimezone(UTC), stale=stale)


OPEN = {"date": "2026-10-14", "status": "open", "open": 570, "close": 960}


def invoke(now, root, *, builder=None, publisher=None, calendar=None, retry=False):
    return run_slot(
        now,
        root / "public",
        root / "receipts",
        calendar_reader=calendar or (lambda _day: OPEN),
        snapshot_builder=builder or (lambda: snapshot(now)),
        publisher=publisher or (lambda _directory, _snapshot: Path("snapshot.json")),
        retry_failed=retry,
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("09:49", "09-49"),
        ("11:02", "10-59"),
        ("12:29", "12-29"),
        ("14:02", "13-59"),
    ],
)
def test_fixed_et_slots_and_grace_window(value, expected):
    assert scheduled_slot(at(value)) == (date(2026, 10, 14), expected)
    assert scheduled_slot(at(value) + timedelta(minutes=3, seconds=1)) is None


def test_slots_follow_dst_and_never_catch_up_outside_grace():
    assert scheduled_slot(datetime(2026, 3, 9, 13, 49, tzinfo=UTC)) == (date(2026, 3, 9), "09-49")
    assert scheduled_slot(datetime(2026, 11, 2, 14, 49, tzinfo=UTC)) == (date(2026, 11, 2), "09-49")
    assert scheduled_slot(datetime(2026, 10, 14, 15, 10, tzinfo=UTC)) is None
    assert scheduled_slot(datetime(2026, 10, 17, 13, 49, tzinfo=UTC)) is None


def test_exchange_calendar_gates_holidays_unknown_and_half_days(tmp_path):
    closed = invoke(at("09:49"), tmp_path, calendar=lambda _day: {"status": "closed"})
    assert closed["status"] == "skipped_exchange_closed"
    assert not (tmp_path / "public").exists()

    with pytest.raises(ScheduleRefused, match="exchange_calendar_unavailable"):
        invoke(at("09:49"), tmp_path / "unknown", calendar=lambda _day: None)
    # On a half-day the 12:30 read fits; the 14:00 read is explicitly skipped.
    half = {"status": "open", "open": 570, "close": 780}
    assert invoke(at("12:29"), tmp_path / "half", calendar=lambda _day: half)["status"] == "published_partial"
    assert invoke(at("13:59"), tmp_path / "half-late", calendar=lambda _day: half)["status"] == "skipped_outside_regular_session"


def test_missed_slot_refused_without_creating_receipt(tmp_path):
    with pytest.raises(ScheduleRefused, match="outside_scheduled_slot"):
        invoke(at("10:04"), tmp_path)
    assert not (tmp_path / "receipts").exists()


def test_same_slot_publishes_once_and_exact_repeat_recovers_receipt(tmp_path):
    count = 0

    def publish(_directory, _snapshot):
        nonlocal count
        count += 1
        return Path("fixture.json")

    first = invoke(at("09:49"), tmp_path, publisher=publish)
    second = invoke(at("09:50"), tmp_path, publisher=publish)
    assert first["status"] in {"published", "published_partial"}
    assert second["status"] == "already_recorded"
    assert count == 1
    rows = list((tmp_path / "receipts").rglob("*.json"))
    assert len(rows) == 2  # started plus terminal publication receipt
    for row in rows:
        data = json.loads(row.read_text())
        assert data["receipt_sha256"]


def test_stale_partial_snapshot_is_published_with_its_exact_provenance(tmp_path):
    now = at("09:49")
    packet = snapshot(now, stale=True)
    served = []
    result = invoke(now, tmp_path, builder=lambda: packet,
                    publisher=lambda _directory, passed: served.append(passed) or Path("partial.json"))
    assert result["status"] == "published_partial"
    assert result["error_reason"] == "snapshot_has_explicit_gaps"
    assert any("SPY" in flag or "spy" in flag for flag in result["quality_flags"])
    assert served == [packet]
    assert served[0]["indices"]["SPY"]["price"]["at"] == packet["indices"]["SPY"]["price"]["at"]
    terminal = next((tmp_path / "receipts").rglob("*-published.json"))
    assert json.loads(terminal.read_text())["content_sha256"] == packet["content_sha256"]


def test_failed_source_receipt_requires_explicit_retry(tmp_path):
    now = at("09:49")
    with pytest.raises(ScheduleRefused, match="snapshot_unavailable"):
        invoke(now, tmp_path, builder=lambda: (_ for _ in ()).throw(ScheduleRefused("snapshot_unavailable")))
    with pytest.raises(ScheduleRefused, match="failed_attempt_requires_explicit_retry"):
        invoke(now, tmp_path)
    recovered = invoke(now, tmp_path, retry=True)
    assert recovered["status"] in {"published", "published_partial"}
    assert len(list((tmp_path / "receipts").rglob("*-failed.json"))) == 1
    assert len(list((tmp_path / "receipts").rglob("*-published.json"))) == 1


def test_concurrent_same_slot_has_one_publication(tmp_path):
    calls = 0
    guard = threading.Lock()

    def publish(_directory, _snapshot):
        nonlocal calls
        with guard:
            calls += 1
        return Path("concurrent.json")

    def worker():
        return invoke(at("09:49"), tmp_path, publisher=publish)

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _n: worker(), range(8)))
    assert calls == 1
    assert sum(row["status"] in {"published", "published_partial"} for row in results) == 1
    assert sum(row["status"] == "already_recorded" for row in results) == 7


def test_uncertain_started_attempt_fails_closed_without_overwrite(tmp_path):
    now = at("09:49")
    slot = "09-49"
    day_dir = tmp_path / "receipts" / now.date().isoformat() / slot
    from market_watch_schedule import _write_immutable

    _write_immutable(day_dir / "attempt-01-started.json", {
        "schema_version": 1, "session_date": now.date().isoformat(), "slot": slot,
        "attempt": 1, "phase": "started", "status": "started",
    })
    with pytest.raises(ScheduleRefused, match="prior_attempt_incomplete_owner_recovery_required"):
        invoke(now, tmp_path)


def test_crash_after_publication_remains_unknown_without_exact_receipt_binding(tmp_path):
    now = at("09:49")
    slot = "09-49"
    day = now.date().isoformat()
    day_dir = tmp_path / "receipts" / day / slot
    public = tmp_path / "public"
    public.mkdir()
    from market_watch_schedule import _write_immutable

    _write_immutable(day_dir / "attempt-01-started.json", {
        "schema_version": 1, "session_date": day, "slot": slot, "attempt": 1,
        "recorded_at": now.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "phase": "started", "status": "started",
    })
    # An arbitrary matching-time public packet cannot be attributed to this
    # invocation. Keep the started receipt intact for owner reconciliation.
    published = snapshot(now)
    (public / f"{published['content_sha256']}.json").write_text(json.dumps(published))

    with pytest.raises(ScheduleRefused, match="prior_attempt_incomplete_owner_recovery_required"):
        run_slot(
            now, public, tmp_path / "receipts", calendar_reader=lambda _day: OPEN,
            snapshot_builder=lambda: pytest.fail("unknown attempt must not recollect"),
            publisher=lambda *_: pytest.fail("unknown attempt must not republish"),
        )
    assert (day_dir / "attempt-01-started.json").exists()
    assert not list(day_dir.glob("*-published.json"))


def test_child_environment_is_narrow_and_postgres_read_only(tmp_path):
    source = tmp_path / "backend.env"
    source.write_text(
        "DATABASE_URL=postgresql://${OPENAI_API_KEY}@db/tradejournal\n"
        "MIGRATION_DATABASE_URL=postgresql://owner:secret@db/tradejournal\n"
        "ALPACA_API_KEY=key\nALPACA_API_SECRET=secret\nTRADIER_API_KEY=tkey\n"
        "TRADIER_BASE_URL=https://api.tradier.com\nALPACA_DATA_FEED=iex\nOPENAI_API_KEY=paid\n"
    )
    parsed = _parse_dotenv(source)
    assert set(parsed) == ENV_ALLOWLIST
    assert "MIGRATION_DATABASE_URL" not in parsed and "OPENAI_API_KEY" not in parsed
    assert "${OPENAI_API_KEY}" in parsed["DATABASE_URL"]
    child_env = _runtime_env(source)
    assert child_env["PGOPTIONS"] == "-c default_transaction_read_only=on"
    assert "OPENAI_API_KEY" not in child_env and "MIGRATION_DATABASE_URL" not in child_env
    assert child_env["ALPACA_DATA_FEED"] == "iex"
    source.write_text(source.read_text().replace("ALPACA_DATA_FEED=iex", "ALPACA_DATA_FEED=sip"))
    assert _runtime_env(source)["ALPACA_DATA_FEED"] == "iex"

    unit = (ROOT / "deploy/market-watch/tradejournal-market-watch-publisher.service").read_text()
    timer = (ROOT / "deploy/market-watch/tradejournal-market-watch-publisher.timer").read_text()
    assert "LoadCredential=backend.env:/etc/tradejournal/backend.env" in unit
    assert "EnvironmentFile=" not in unit
    assert "ReadWritePaths=/var/lib/tradejournal-market-watch-public" in unit
    assert "ReadWritePaths=/var/lib/tradejournal/market-watch" in unit
    assert "MIGRATION_DATABASE_URL" not in unit
    assert "Environment=PYTHONDONTWRITEBYTECODE=1" in unit
    assert "SHOW transaction_read_only" in Path(__file__).parents[1].joinpath("market_watch_schedule.py").read_text()
    assert "WantedBy=" not in unit
    assert timer.count("OnCalendar=") == 4
    assert "Persistent=false" in timer


def test_price_freshness_refuses_missing_stale_and_future_sources():
    now = at("09:49")
    assert any("SPY" in flag or "spy" in flag for flag in _snapshot_quality(snapshot(now, stale=True), now, slot="09-49"))
    future = snapshot(now)
    future["indices"]["SPY"]["price"]["at"] = (now + timedelta(minutes=1)).astimezone(UTC).isoformat()
    from market_watch_common import digest, seal
    future.pop("content_sha256")
    future.pop("snapshot_id")
    future["snapshot_id"] = "mws_" + digest({k: v for k, v in future.items() if k not in {"snapshot_id", "content_sha256"}})[:32]
    future = seal(future)
    with pytest.raises(ValueError, match="timestamp is after collection"):
        _snapshot_quality(future, now, slot="09-49")
    late = snapshot(now + timedelta(minutes=4))
    with pytest.raises(ScheduleRefused, match="snapshot_collection_late"):
        _snapshot_quality(late, now, slot="09-49")
