"""Frozen recorded context enriches existing firings, never their authority."""
from copy import deepcopy
from datetime import datetime
import json
import sqlite3
import time
from uuid import UUID

import httpx
import pytest
from sqlmodel import Session, select

from app.engine import ntfy, position_alert_context as context, position_alerts
from app.engine.radar_store import RadarStore
from app.models import Trade, Fill, TradeFill
from tests import test_position_alerts as fixtures
from tests.test_position_alerts import WED, at, fill, step, alerts, sent_to

from tests.test_radar_comparison import seed

engine, world, on_wednesday = fixtures.engine, fixtures.world, fixtures.on_wednesday

UNIVERSE = {"version": "test-v1", "groups": [
    {"name": "Chips", "members": ["SNDK", "AMD", "MU"]},
    {"name": "Other chips", "members": ["SNDK", "MU"]},
]}
REGULAR = ("regular", 570, 960)


@pytest.fixture
def market(tmp_path, monkeypatch):
    store = RadarStore(tmp_path / "radar.sqlite")
    monkeypatch.setenv("RADAR_ENABLED", "true")
    monkeypatch.setenv("RADAR_STORE", str(store.path))
    monkeypatch.setattr(context, "load_universe", lambda: deepcopy(UNIVERSE))
    return store


def sample(store, hhmm, prices=None):
    return seed(store, at(WED, hhmm), prices or dict.fromkeys(("SNDK", "AMD", "MU", "QQQ", "SPY"), 100), day=WED.isoformat())


def fire(engine, world):
    clock, quotes, watcher = world
    with Session(engine) as db:
        fill(db, "buy_to_open", 2, 400, "2026-10-21T09:45")  # journal timestamps are naive New York
    quotes.set(4.60)
    step(clock, watcher)
    quotes.set(4.00)
    step(clock, watcher)
    return alerts(engine)[0]


def test_real_context_is_cut_off_frozen_and_identical_on_retry(engine, world, market, monkeypatch):
    first = sample(market, "09:46")
    last = sample(market, "10:00", {"SNDK": 98, "AMD": 99, "MU": 101, "QQQ": 99.5, "SPY": 100})
    sample(market, "10:02", {"SNDK": 200})  # present but in detection's future
    before = market.path.read_bytes()
    clock, quotes, watcher = world
    calls, original = [], watcher.calendar.hours
    watcher.calendar.hours = lambda day: (calls.append(day), original(day))[1]
    alert = fire(engine, world)
    assert quotes.calls == len(calls) == 2
    snapshot = json.loads(alert.context_snapshot_json)["comparison"]
    assert snapshot["group"]["name"] == "Chips"
    assert snapshot["window"]["start_pass_id"] == first
    assert snapshot["window"]["end_pass_id"] == last
    assert snapshot["entry"]["baseline_delay_seconds"] == 60
    assert [r["change_pct"] for r in snapshot["rows"]] == pytest.approx([-2, -1, 1, -0.5, 0])
    assert market.path.read_bytes() == before and not market.events() and not market.last_visit()
    text = context.phone_text(alert.context_snapshot_json)
    assert "SNDK -2.00% · QQQ -0.50% · SPY +0.00%" in text
    assert "1/2 peers lower, 1 higher; 2 tracked" in text
    assert "Samples start +60s after entry; 2/15 min recorded · partial coverage" in text
    assert len(text.splitlines()) == 4 and len(text) < 450
    monkeypatch.setenv("NTFY_URL", "https://ntfy.example/topic")
    sent = []
    def publish(title, body, **kwargs):
        sent.append((title, body, kwargs))
        if len(sent) == 1:
            raise ntfy.NtfyError("not connected") from httpx.ConnectTimeout("fixture")
    monkeypatch.setattr(ntfy, "publish", publish)
    watcher.deliver()
    assert alerts(engine)[0].delivery == "pending"
    sample(market, "10:03", {"SNDK": 50})
    monkeypatch.setattr(context, "capture", lambda *a: pytest.fail("must not recapture on replay/retry"))
    step(clock, watcher, 61)
    watcher.deliver()
    assert sent[0] == sent[1]
    assert sent[1][2]["path"] == f"/trades/{alert.trade_id}"
    assert alerts(engine)[0].context_snapshot_json == alert.context_snapshot_json
    assert alerts(engine)[0].delivery == "sent" and len(alerts(engine)) == 1


@pytest.mark.parametrize("issue", ["off", "missing", "foreign", "locked", "read_failure", "ungrouped", "stale", "partial"])
def test_context_problems_never_suppress_notification(engine, world, market, monkeypatch, issue):
    sample(market, "09:46")
    sample(market, "09:50" if issue == "stale" else "10:00", {"SNDK": 98, "QQQ": 99} if issue == "partial" else None)
    lock = None
    if issue == "off":
        monkeypatch.setenv("RADAR_ENABLED", "false")
    elif issue == "missing":
        market.path.unlink()
    elif issue == "foreign":
        market.path.unlink()
        with sqlite3.connect(market.path) as db:
            db.execute("create table unrelated (x)")
    elif issue == "locked":
        lock = sqlite3.connect(market.path)
        lock.execute("BEGIN EXCLUSIVE")
    elif issue == "read_failure":
        monkeypatch.setattr(context, "load_universe", lambda: (_ for _ in ()).throw(ValueError("fixture")))
    elif issue == "ungrouped":
        monkeypatch.setattr(context, "load_universe", lambda: {"version": "test-v1", "groups": []})
    try:
        alert = fire(engine, world)
        sent = []
        sent_to(monkeypatch, sent)
        world[2].deliver()
        assert len(sent) == 1 and alerts(engine)[0].delivery == "sent"
        text = context.phone_text(alert.context_snapshot_json)
        if issue == "partial":
            assert "SNDK -2.00%" in text and "SPY unavailable" in text
            assert "0/2 peers covered" in text and "partial coverage" in text
        else:
            assert "unavailable" in text and "SNDK -" not in text
        if issue == "missing":
            assert not market.path.exists()
    finally:
        if lock:
            lock.close()


def test_read_budget_fails_fast_on_lock_and_expired_deadline(market):
    with sqlite3.connect(market.path) as db:
        db.execute("BEGIN EXCLUSIVE")
        started = time.monotonic()
        with pytest.raises(sqlite3.OperationalError):
            RadarStore(market.path, read_only=True, read_deadline=started + 0.02)
        assert time.monotonic() - started < 0.5
    with pytest.raises(sqlite3.OperationalError, match="deadline"):
        RadarStore(market.path, read_only=True, read_deadline=time.monotonic() - 1)


@pytest.mark.parametrize("mismatch", ["account", "source", "trade", "overnight", "closed"])
def test_unsupported_entry_has_no_numbers(engine, world, market, mismatch):
    sample(market, "09:46")
    sample(market, "10:00")
    alert = fire(engine, world)
    if mismatch == "account":
        alert.account_id = UUID(int=999)
    elif mismatch == "source":
        alert.source_key = "other-fill"
    elif mismatch == "trade":
        alert.trade_id = UUID(int=999)
    else:
        with Session(engine) as db:
            trade = db.get(Trade, alert.trade_id)
            if mismatch == "closed":
                trade.status = "closed"
            else:
                first = db.exec(select(Fill).join(TradeFill).where(TradeFill.trade_id == trade.id)).first()
                first.executed_at = trade.opened_at = datetime(2026, 10, 20, 13, 45)
            db.commit()
    snapshot = context.capture(engine, alert, world[0](), REGULAR)
    assert "unavailable" in context.phone_text(snapshot)
    assert json.loads(snapshot)["comparison"].get("rows", []) == []


@pytest.mark.parametrize("kind", position_alerts.KINDS)
def test_context_is_additive_to_every_existing_kind(engine, world, market, kind):
    sample(market, "09:46")
    sample(market, "10:00")
    alert = fire(engine, world)
    alert.kind = kind
    title, body, priority = position_alerts.message(alert, "4:00 PM", 20)
    alert.context_snapshot_json = None
    original = position_alerts.message(alert, "4:00 PM", 20)
    assert (title, priority) == (original[0], original[2])
    assert body.startswith(original[1] + "\n\nUnderlying since entry")


@pytest.mark.parametrize("raw", [None, "bad-json", "null", "{}", '{"version": 2}', '{"version": 1, "comparison": {"state": "ready"}}'])
def test_invalid_snapshot_cannot_break_formatter(raw):
    assert context.phone_text(raw) == ("" if raw is None else "Since-entry context unavailable.")


def test_ambiguous_send_retains_context_and_is_never_resent(engine, world, market, monkeypatch):
    sample(market, "09:46")
    sample(market, "10:00")
    alert = fire(engine, world)
    attempts = []
    monkeypatch.setenv("NTFY_URL", "https://ntfy.example/topic")
    def publish(*args, **kwargs):
        attempts.append(args)
        raise ntfy.NtfyError("uncertain") from httpx.ReadTimeout("fixture")
    monkeypatch.setattr(ntfy, "publish", publish)
    world[2].deliver()
    monkeypatch.setattr(context, "capture", lambda *a: pytest.fail("must not recapture an unknown send"))
    step(world[0], world[2], 61)
    world[2].deliver()
    assert len(attempts) == 1
    current = alerts(engine)[0]
    assert current.delivery == "unknown" and current.context_snapshot_json == alert.context_snapshot_json


def test_source_identity_and_original_entry_survive_add_partial_exit_and_rebuild(engine, world, market):
    sample(market, "09:46")
    sample(market, "10:00")
    alert = fire(engine, world)
    original = json.loads(alert.context_snapshot_json)["comparison"]["entry"]
    with Session(engine) as db:
        fill(db, "buy_to_open", 1, 500, "2026-10-21T09:50")
        fill(db, "sell_to_close", 1, 450, "2026-10-21T09:55")
        trade = db.exec(select(Trade).where(Trade.status == "open")).one()
        alert.trade_id = trade.id
    snapshot = json.loads(context.capture(engine, alert, world[0](), REGULAR))["comparison"]
    assert snapshot["entry"]["recorded_at"] == original["recorded_at"]
    assert snapshot["entry"]["baseline_at"] == original["baseline_at"]
    assert snapshot["rows"][0]["change_pct"] == 0
