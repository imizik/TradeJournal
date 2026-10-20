"""Owner view of Jo's plans and the refusal reasons Jo receives."""

from datetime import timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.routers import conditional_plans as route
from conditional_plan_common import MAX_DAILY_PLANS
from stock_watch_common import stamp
from tests.test_conditional_plans import bar, create, monitor, observe, ready, setup as setup
from tests.test_cloud_mcp_check import call, harness as harness, signing_key as signing_key
from tests.test_stock_watch import NOW, SCOPE, alert
from stock_watch_common import write_once


@pytest.fixture
def view(setup, monkeypatch):
    s = setup
    for name, value in {"MARKET_WATCH_STORE": str(s.store.path), "MARKET_WATCH_SNAPSHOTS_DIR": str(s.public),
                        "MARKET_WATCH_OUTBOX_DIR": str(s.outbox), "CONDITIONAL_PLAN_ENABLED": "true",
                        "STOCK_WATCH_ENABLED": "true", "NTFY_URL": "https://ntfy.example/topic"}.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(route, "_now", lambda: s.now)
    app = FastAPI()
    app.include_router(route.router, prefix="/jo/conditional-plans")
    client = TestClient(app)
    return lambda: client.get("/jo/conditional-plans").json()


def only(v):
    assert len(v["plans"]) == 1
    return v["plans"][0]


def test_unconfigured_feature_reads_off(monkeypatch):
    for name in ("MARKET_WATCH_STORE", "CONDITIONAL_PLAN_ENABLED"):
        monkeypatch.delenv(name, raising=False)
    app = FastAPI()
    app.include_router(route.router, prefix="/jo/conditional-plans")
    v = TestClient(app).get("/jo/conditional-plans").json()
    assert v["enabled"] is False and v["configured"] is False and v["plans"] == []
    assert v["readiness"] == {"heartbeat": "missing"}


def test_saved_plan_is_pending_until_monitor_accepts_it(setup, view):
    s = setup
    p = create(s)
    v = view()
    assert v["readiness"]["heartbeat"] == "fresh" and v["readiness"]["symbols"] == ["NBIS", "SPY"]
    assert v["delivery"] == {"channel": "ntfy phone push", "configured": True}
    plan = only(v)
    assert plan["plan_id"] == p["plan_id"] and plan["state"] == "pending_activation"
    assert not plan["accepted_by_monitor"] and not plan["monitoring"]
    assert plan["source"] == p["source"] and plan["trigger_price"] == 105.0 and plan["confirm_bars"] == 2
    assert v["plans_today"] == 1 and v["max_daily_plans"] == MAX_DAILY_PLANS


def test_watching_triggered_delivery_and_stale_heartbeat(setup, view):
    s = setup
    p = create(s, confirm_bars=1)
    m = monitor(s, [])
    m.ingest()
    s.now = NOW + timedelta(minutes=2)
    ready(s.public, s.now)
    observe(s, m, p, [bar(NOW, 103)])
    plan = only(view())
    assert plan["state"] == "watching" and plan["accepted_by_monitor"] and plan["monitoring"]
    assert plan["last_bar"]["close"] == 103 and plan["last_evaluated_at"] == stamp(s.now)
    s.now += timedelta(minutes=1)
    ready(s.public, s.now)
    observe(s, m, p, [bar(NOW, 103), bar(NOW + timedelta(minutes=1), 106)])
    plan = only(view())
    assert plan["state"] == "triggered" and plan["monitoring"]
    assert [(d["event_state"], d["outcome"]) for d in plan["deliveries"]] == [("triggered", "sent")]
    # The monitor stops reporting: the saved state stays, but it is not called active.
    s.now += timedelta(seconds=91)
    v = view()
    assert v["readiness"]["heartbeat"] == "stale" and only(v)["state"] == "triggered"
    assert not only(v)["monitoring"]


def test_switched_off_flag_and_unavailable_never_read_as_monitoring(setup, view, monkeypatch):
    s = setup
    p = create(s)
    m = monitor(s, [])
    m.ingest()
    s.now = NOW + timedelta(minutes=2)
    ready(s.public, s.now)
    observe(s, m, p, [bar(NOW, 103)])
    monkeypatch.setenv("CONDITIONAL_PLAN_ENABLED", "false")
    v = view()
    assert v["enabled"] is False and not only(v)["monitoring"]
    monkeypatch.setenv("CONDITIONAL_PLAN_ENABLED", "true")
    s.now += timedelta(minutes=1)
    observe(s, m, p, [bar(NOW, 103)], observed=(s.now - timedelta(minutes=10)).timestamp())
    plan = only(view())
    assert plan["state"] == "unavailable" and plan["reason"] == "stale_source" and not plan["monitoring"]


def test_unknown_send_is_reported_unknown_not_sent():
    events = [{"event_id": "e1", "state": "triggered"}]
    attempts = [{"event_id": "e1", "attempt": 1, "result": r, "error_code": None, "transport_receipt_id": None,
                 "occurred_at": stamp(NOW)} for r in ("sending", "unknown")]
    assert [d["outcome"] for d in route._deliveries(attempts, events)] == ["unknown"]
    assert [d["outcome"] for d in route._deliveries(attempts[:1], events)] == ["unknown"]


def test_refusals_name_the_reason(setup, tmp_path):
    s = setup
    with pytest.raises(ValueError, match=r"NBIS is not one of the owner's selected scanner tickers \(SPY\)"):
        ready(s.public, symbols=["SPY"])
        create(s)
    ready(s.public)
    (s.public / "conditional-plan-readiness.json").unlink()
    with pytest.raises(ValueError, match="never reported"):
        create(s)
    ready(s.public, enabled=False)
    with pytest.raises(ValueError, match="not enabled"):
        create(s)
    ready(s.public, created_at=stamp(NOW - timedelta(minutes=5)))
    with pytest.raises(ValueError, match="heartbeat is stale"):
        create(s)
    ready(s.public)
    with pytest.raises(ValueError, match="Stock alert not found"):
        create(s, source_id="sta_" + "0" * 8 + "-0000-4000-8000-" + "0" * 12)
    for i in range(MAX_DAILY_PLANS):
        create(s, operation_id=f"cap-{i}")
    with pytest.raises(ValueError, match="24 new plans"):
        create(s, operation_id="one-too-many")


def test_jo_receives_the_refusal_reason(harness, tmp_path):
    public, outbox = tmp_path / "public", tmp_path / "outbox"
    public.mkdir()
    outbox.mkdir()
    ready(public, symbols=["SPY"])
    p = alert()
    write_once(public, f"stock-{p['alert_id']}.json", p)
    harness.configure(market_watch_snapshots_dir=str(public), market_watch_outbox_dir=str(outbox),
                      conditional_plan_enabled=True)
    with TestClient(harness.server().streamable_http_app()) as client:
        token = harness.token(scope=SCOPE)
        call(client, "stock_alert", {"alert_id": p["alert_id"]}, token)
        request = {"operation_id": "refused", "source_kind": "stock_alert", "source_id": p["alert_id"],
                   "direction": "long", "trigger_price": 105.0, "invalidation_price": 100.0, "confirm_bars": 2,
                   "expires_at": stamp(NOW + timedelta(hours=1)), "rationale": "Two closes above 105."}
        result = call(client, "conditional_plan_create", request, token)
        assert result["isError"]
        text = result["content"][0]["text"]
        assert "REFUSED, nothing saved: NBIS is not one of the owner's selected scanner tickers (SPY)" in text
        assert list(outbox.iterdir()) == []
