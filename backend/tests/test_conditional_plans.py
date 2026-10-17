"""Real plan receipts, future-only evaluation, restart, cancellation and MCP denial."""

from datetime import timedelta
import sqlite3
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

from app.engine.conditional_plans import PlanMonitor
from app.engine.market_watch_wakes import MarketWatchWakeStore
from cloud_mcp_check_ledger import Ledger, Conflict, NotFound
from conditional_plan_common import publish, status
from conditional_plan_ledger import PlanLedger, export
from market_watch_common import seal
from stock_watch_common import stamp, write_once
from stock_watch_ledger import StockWatchLedger
from tests.test_stock_watch import alert, NOW, ACTOR, SCOPE
from tests.test_cloud_mcp_check import (
    harness as harness,
    signing_key as signing_key,
    call,
    rpc,
    IDEA,
)
from tests.test_setup_scanner import engine as engine


def ready(directory, now=NOW, **changes):
    return publish(
        directory,
        "conditional-plan-readiness.json",
        seal(
            {
                "format": "conditional-plan-readiness-v1",
                "enabled": True,
                "session_date": now.date().isoformat(),
                "symbols": ["NBIS", "SPY"],
                "selection_revision": 1,
                "session_open_at": stamp(now.replace(hour=13, minute=30, second=0)),
                "session_close_at": stamp(now.replace(hour=20, minute=0, second=0)),
                "created_at": stamp(now),
                **changes,
            }
        ),
    )


def args(source):
    return {
        "operation_id": "plan-one",
        "source_kind": "stock_alert",
        "source_id": source["alert_id"],
        "direction": "long",
        "trigger_price": 105.0,
        "invalidation_price": 100.0,
        "confirm_bars": 2,
        "expires_at": stamp(NOW + timedelta(hours=1)),
        "rationale": "Watch two closes above 105; a close below 100 invalidates.",
    }


@pytest.fixture
def setup(tmp_path):
    public, outbox = tmp_path / "public", tmp_path / "outbox"
    public.mkdir()
    outbox.mkdir()
    ledger = Ledger(tmp_path / "check.db")
    stock = StockWatchLedger(ledger)
    p = alert()
    stock.serve(ACTOR, p, NOW)
    write_once(public, f"stock-{p['alert_id']}.json", p)
    ready(public)
    plans = PlanLedger(ledger)
    return SimpleNamespace(
        public=public,
        outbox=outbox,
        ledger=ledger,
        plans=plans,
        source=p,
        request=args(p),
        store=MarketWatchWakeStore(tmp_path / "wakes.db"),
        now=NOW,
    )


def create(s, **changes):
    p = s.plans.create(ACTOR, {**s.request, **changes}, s.public, lambda: s.now)
    export(s.outbox, p)
    return p


def bar(at, close):
    return {
        "time": at.timestamp(),
        "end_time": at.timestamp() + 60,
        "open": close,
        "high": close + 1,
        "low": close - 1,
        "close": close,
        "volume": 1000,
    }


def monitor(s, sent=None):
    return PlanMonitor(
        s.store,
        s.public,
        s.outbox,
        clock=lambda: s.now,
        push=lambda title, body: (
            sent.append((title, body)) or "fixture-push"
            if sent is not None
            else "fixture-push"
        ),
    )


def observe(s, m, p, bars, *, selected=("NBIS",), active=True, observed=None):
    scanner = SimpleNamespace(
        _pass_minutes={
            "NBIS": (bars, observed if observed is not None else s.now.timestamp())
        }
    )
    session = SimpleNamespace(
        open_at=NOW.replace(hour=13, minute=30).timestamp(),
        close_at=NOW.replace(hour=20, minute=0).timestamp(),
    )
    m.observe(p, scanner, selected, session, active)
    m.deliver(p, active)
    m.project(p, active)
    return status(s.public, p, s.now)


def test_receipts_exact_retry_conflict_owner_and_export_recovery(setup):
    s = setup
    p = create(s)
    assert status(s.public, p, NOW)["state"] == "pending_activation"
    assert not status(s.public, p, NOW)["monitoring"]
    # A lost response/export can be recovered after expiry without creating a new plan.
    (s.outbox / f"conditional-plan-{p['plan_id']}.json").unlink()
    s.now += timedelta(days=1)
    assert create(s) == p
    with pytest.raises(Conflict):
        create(s, trigger_price=106)
    with pytest.raises(NotFound):
        s.plans.get("other", p["plan_id"])
    with pytest.raises(NotFound):
        s.plans.cancel("other", p["plan_id"], lambda: s.now)
    c = s.plans.cancel(ACTOR, p["plan_id"], lambda: s.now)
    assert s.plans.cancel(ACTOR, p["plan_id"], lambda: s.now + timedelta(days=1)) == c
    export(s.outbox, c)
    with sqlite3.connect(s.ledger.path) as db:
        assert db.execute("SELECT COUNT(*) FROM shadow_decision").fetchone()[0] == 0
        for table in ("conditional_plan", "conditional_plan_cancel"):
            for sql in (
                f"DELETE FROM {table}",
                f"UPDATE {table} SET actor='other'",
                f"INSERT OR REPLACE INTO {table} SELECT * FROM {table}",
            ):
                with pytest.raises(sqlite3.IntegrityError):
                    db.execute(sql)


@pytest.mark.parametrize(
    "change",
    [
        {"trigger_price": float("nan")},
        {"invalidation_price": -1},
        {"trigger_price": 99},
        {"direction": "short"},
        {"confirm_bars": True},
        {"confirm_bars": 4},
        {"expires_at": stamp(NOW)},
        {"expires_at": stamp(NOW + timedelta(hours=5))},
        {"expires_at": "2026-10-09T16:00:00"},
        {"rationale": " "},
    ],
)
def test_invalid_plan_refused(setup, change):
    with pytest.raises((ValueError, TypeError)):
        create(setup, **change)


def test_monitor_readiness_selection_early_close_and_stale_source(setup):
    s = setup
    ready(s.public, enabled=False)
    with pytest.raises(ValueError, match="not enabled"):
        create(s)
    ready(s.public, symbols=["SPY"])
    with pytest.raises(ValueError, match="selected"):
        create(s)
    ready(s.public, session_close_at=stamp(NOW + timedelta(minutes=20)))
    with pytest.raises(ValueError, match="regular session"):
        create(s)
    s.now += timedelta(minutes=5)
    with pytest.raises(ValueError, match="heartbeat"):
        create(s)
    ready(s.public, s.now)
    with pytest.raises(ValueError, match="source is stale"):
        create(s)


def test_future_closes_trigger_once_then_invalidate_and_restart(setup):
    s = setup
    p = create(s)
    sent = []
    m = monitor(s, sent)
    old = [bar(NOW - timedelta(minutes=2), 108), bar(NOW - timedelta(minutes=1), 109)]
    assert observe(s, m, p, old)["state"] == "watching"  # historical trigger ignored
    rows = old + [bar(NOW, 106)]
    s.now = NOW + timedelta(minutes=1)
    assert observe(s, m, p, rows)["state"] == "watching"
    # New process: confirmation state survives from the immutable observations.
    m = monitor(s, sent)
    rows.append(bar(NOW + timedelta(minutes=1), 107))
    s.now += timedelta(minutes=1)
    result = observe(s, m, p, rows)
    assert result["state"] == "triggered" and result["monitoring"]
    assert len(sent) == 1 and "2 completed" in sent[0][1]
    observe(s, monitor(s, sent), p, rows)
    assert len(sent) == 1
    rows.append(bar(NOW + timedelta(minutes=2), 99))
    s.now += timedelta(minutes=1)
    result = observe(s, monitor(s, sent), p, rows)
    assert result["state"] == "invalidated" and not result["monitoring"]
    assert len(sent) == 2 and "no entry, exit, or order assumed" in sent[-1][1]
    assert len(s.store.records("plan_observation")) == 3


def test_confirmation_resets_and_equality_is_not_a_cross(setup):
    s = setup
    p = create(s)
    m = monitor(s)
    rows = []
    for i, close in enumerate([106, 105, 106, 107]):
        rows.append(bar(NOW + timedelta(minutes=i), close))
        s.now = NOW + timedelta(minutes=i + 1)
        result = observe(s, m, p, rows)
        assert result["state"] == ("triggered" if i == 3 else "watching")


def test_short_and_invalidation_before_trigger(setup):
    s = setup
    p = create(
        s, direction="short", trigger_price=100, invalidation_price=105, confirm_bars=1
    )
    s.now += timedelta(minutes=1)
    r = observe(s, monitor(s), p, [bar(NOW, 106)])
    assert r["state"] == "invalidated"
    assert not any(e["state"] == "triggered" for e in r["events"])


@pytest.mark.parametrize(
    "case", ["missing", "stale", "future", "duplicate", "malformed"]
)
def test_missing_or_bad_evidence_never_fakes_trigger(setup, case):
    s = setup
    p = create(s, confirm_bars=1)
    s.now += timedelta(minutes=2)
    rows = [bar(NOW, 106), bar(NOW + timedelta(minutes=1), 107)]
    observed = s.now.timestamp()
    if case == "missing":
        rows = rows[1:]
    if case == "stale":
        observed -= 181
    if case == "future":
        rows = [bar(s.now, 106)]
    if case == "duplicate":
        rows.append(rows[-1])
    if case == "malformed":
        rows[-1]["low"] = 1000
    result = observe(s, monitor(s), p, rows, observed=observed)
    assert result["state"] == "unavailable"
    assert not any(e["state"] == "triggered" for e in result["events"])


def test_cancel_removal_disable_and_expiry(setup):
    s = setup
    p = create(s)
    m = monitor(s)
    c = s.plans.cancel(ACTOR, p["plan_id"], lambda: s.now)
    export(s.outbox, c)
    assert (
        observe(s, m, p, [bar(NOW - timedelta(minutes=1), 101)])["state"] == "cancelled"
    )
    for i, change in enumerate(({"selected": []}, {"active": False}, {})):
        p = create(
            s, operation_id=f"next-{i}", expires_at=stamp(NOW + timedelta(minutes=1))
        )
        if not change:
            s.now = NOW + timedelta(minutes=1)
        r = observe(s, m, p, [bar(NOW, 110)], **change)
        assert r["state"] == ("cancelled" if change else "expired")
        assert not r["monitoring"]


def test_uncertain_send_not_retried_and_stale_trigger_not_sent(setup):
    s = setup
    p = create(s, confirm_bars=1)
    m = monitor(s, [])
    s.now += timedelta(minutes=1)
    scanner = SimpleNamespace(
        _pass_minutes={"NBIS": ([bar(NOW, 106)], s.now.timestamp())}
    )
    session = SimpleNamespace(
        open_at=NOW.timestamp() - 3600, close_at=NOW.timestamp() + 3600
    )
    m.observe(p, scanner, ["NBIS"], session, True)
    event = m.events(p)[-1]
    m.runner._attempt(
        "plan_push_attempt",
        s.now,
        p["session_date"],
        "event_id",
        event["event_id"],
        1,
        "sending",
        "push",
    )
    m.deliver(p, True)
    m.deliver(p, True)
    assert [a["result"] for a in s.store.records("plan_push_attempt")] == [
        "sending",
        "unknown",
    ]
    # A different plan's old event must be marked expired, never delivered as current.
    s.now = NOW
    p2 = create(s, operation_id="second", confirm_bars=1)
    s.now += timedelta(minutes=1)
    m.observe(p2, scanner, ["NBIS"], session, True)
    s.now += timedelta(minutes=4)
    m.deliver(p2, True)
    assert s.store.records("plan_push_attempt")[-1]["result"] == "expired"


def test_superseded_trigger_and_cancellation_before_send(setup):
    s = setup
    p = create(s, confirm_bars=1)
    m = monitor(s, [])
    s.now += timedelta(minutes=2)
    scanner = SimpleNamespace(
        _pass_minutes={
            "NBIS": (
                [bar(NOW, 106), bar(NOW + timedelta(minutes=1), 99)],
                s.now.timestamp(),
            )
        }
    )
    m.observe(
        p,
        scanner,
        ["NBIS"],
        SimpleNamespace(open_at=0, close_at=s.now.timestamp() + 100),
        True,
    )
    m.deliver(p, True)
    assert [a["result"] for a in s.store.records("plan_push_attempt")] == [
        "expired",
        "sending",
        "accepted",
    ]
    assert s.store.records("plan_push_attempt")[0]["error_code"] == "superseded"


def test_partial_creation_minute_and_heartbeat_truth(setup):
    s = setup
    s.now += timedelta(seconds=30)
    p = create(s, confirm_bars=1)
    m = monitor(s)
    s.now = NOW + timedelta(minutes=1)
    r = observe(s, m, p, [bar(NOW, 106)])
    assert r["state"] == "watching" and r["last_bar_end"] is None
    assert not status(s.public, p, s.now + timedelta(seconds=91))["monitoring"]
    s.now += timedelta(minutes=1)
    assert (
        observe(s, m, p, [bar(NOW, 106), bar(NOW + timedelta(minutes=1), 107)])["state"]
        == "triggered"
    )


def test_mcp_opt_in_scopes_identity_source_and_no_extra_provider(harness, tmp_path):
    with TestClient(harness.server().streamable_http_app()) as client:
        names = {
            t["name"]
            for t in rpc(client, "", {}, harness.token(), "tools/list").json()[
                "result"
            ]["tools"]
        }
        assert not any(n.startswith("conditional_plan_") for n in names)
    public, outbox = tmp_path / "public", tmp_path / "outbox"
    public.mkdir()
    outbox.mkdir()
    ready(public)
    p = alert()
    write_once(public, f"stock-{p['alert_id']}.json", p)
    harness.configure(
        market_watch_snapshots_dir=str(public),
        market_watch_outbox_dir=str(outbox),
        conditional_plan_enabled=True,
    )
    with TestClient(harness.server().streamable_http_app()) as client:
        token = harness.token(scope=SCOPE)
        request = args(p)
        assert call(client, "conditional_plan_create", request, harness.token())[
            "isError"
        ]
        assert call(client, "conditional_plan_create", request, token)[
            "isError"
        ]  # not served
        assert not call(client, "stock_alert", {"alert_id": p["alert_id"]}, token).get(
            "isError"
        )
        result = call(client, "conditional_plan_create", request, token)
        assert not result.get("isError"), result
        saved = result["structuredContent"]
        assert saved["state"] == "pending_activation"
        plan_id = saved["plan"]["plan_id"]
        assert (
            call(client, "conditional_plan_status", {"plan_id": plan_id}, token)[
                "structuredContent"
            ]["plan"]
            == saved["plan"]
        )
        assert call(
            client, "conditional_plan_create", {**request, "actor": "spoof"}, token
        )["isError"]
        assert call(
            client,
            "conditional_plan_cancel",
            {"plan_id": plan_id},
            harness.token(scope="check:read market-watch:read"),
        )["isError"]
        assert call(client, "conditional_plan_cancel", {"plan_id": plan_id}, token)[
            "structuredContent"
        ]["cancel_requested"]
        assert harness.requests == []
        # Pre-trade checks are subject-owned, whereas plans are profile-owned.
        check = call(client, "pre_trade_check", IDEA, harness.token())[
            "structuredContent"
        ]
        count = len(harness.requests)
        result = call(
            client,
            "conditional_plan_create",
            {
                **request,
                "operation_id": "own-check",
                "source_kind": "check",
                "source_id": check["check_id"],
            },
            token,
        )
        assert not result.get("isError"), result
        assert len(harness.requests) == count
        harness.configure(conditional_plan_enabled=False)
        assert rpc(client, "conditional_plan_list", {}, token).status_code == 401


def test_real_scanner_monitor_hook_reuses_cache_and_publishes_status(
    setup, engine, monkeypatch
):
    from app.engine import scanner_settings
    from app.engine.paper import regular_session

    s = setup
    p = create(s)
    monkeypatch.setattr(
        scanner_settings,
        "read_settings",
        lambda db: {"symbols": ["NBIS"], "revision": 1},
    )
    scanner = SimpleNamespace(
        engine=engine,
        calendar=SimpleNamespace(
            hours=lambda day: {"status": "open", "open": 570, "close": 960}
        ),
        _pass_minutes={
            "NBIS": ([bar(NOW - timedelta(minutes=1), 103)], NOW.timestamp())
        },
        _minutes=lambda *_: pytest.fail("cached candles must be reused"),
    )
    assert regular_session(NOW.date(), scanner.calendar.hours(NOW.date()))
    m = monitor(s)
    m.run(scanner)
    assert status(s.public, p, NOW)["monitoring"]
    assert len(s.store.records("plan")) == 1
    m.run(scanner, active=False)
    assert status(s.public, p, NOW)["state"] == "cancelled"


def test_crash_after_transition_before_cursor_does_not_lose_or_duplicate_trigger(
    setup, monkeypatch
):
    s = setup
    p = create(s, confirm_bars=1)
    m = monitor(s)
    s.now += timedelta(minutes=1)
    scanner = SimpleNamespace(
        _pass_minutes={"NBIS": ([bar(NOW, 106)], s.now.timestamp())}
    )
    session = SimpleNamespace(
        open_at=NOW.timestamp() - 3600, close_at=NOW.timestamp() + 3600
    )
    append = s.store.append

    def crash(kind, *args, **kwargs):
        if kind == "plan_observation":
            raise SystemExit("simulated process stop")
        return append(kind, *args, **kwargs)

    monkeypatch.setattr(s.store, "append", crash)
    with pytest.raises(SystemExit):
        m.observe(p, scanner, ["NBIS"], session, True)
    monkeypatch.setattr(s.store, "append", append)
    sent = []
    m = monitor(s, sent)
    m.observe(p, scanner, ["NBIS"], session, True)
    m.deliver(p, True)
    assert [e["state"] for e in m.events(p)] == ["watching", "triggered"]
    assert len(s.store.records("plan_observation")) == 1
    assert len(sent) == 1


def test_cancellation_queued_after_trigger_prevents_phone_send(setup):
    s = setup
    p = create(s, confirm_bars=1)
    sent = []
    m = monitor(s, sent)
    s.now += timedelta(minutes=1)
    scanner = SimpleNamespace(
        _pass_minutes={"NBIS": ([bar(NOW, 106)], s.now.timestamp())}
    )
    m.observe(
        p,
        scanner,
        ["NBIS"],
        SimpleNamespace(open_at=0, close_at=s.now.timestamp() + 100),
        True,
    )
    export(s.outbox, s.plans.cancel(ACTOR, p["plan_id"], lambda: s.now))
    m.deliver(p, True)
    assert sent == []
    assert not s.store.records("plan_push_attempt")


def test_new_plan_limit_is_explicit_and_does_not_stop_accepted_plan(setup):
    s = setup
    for i in range(24):
        create(s, operation_id=f"plan-{i}", confirm_bars=1)
    with pytest.raises(ValueError, match="existing plans continue"):
        create(s, operation_id="overflow")
    p = s.plans.list(ACTOR)[0]
    s.now += timedelta(minutes=1)
    assert observe(s, monitor(s), p, [bar(NOW, 106)])["state"] == "triggered"
