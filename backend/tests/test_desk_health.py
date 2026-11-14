"""The desk's data health (GET /copilot/desk/health): one row per source behind the desk, read from what each source
already keeps. Closed hours say closed, not stale; unknown is never green; a hidden ticker's TradingView alert stays
silent; no Robinhood read is started. Owner-only, refused while the lab is off, served inside the minute request."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlmodel import Session

from app.engine import chatter, desk_health, desk_minute, desk_sparks, desk_ticks, robinhood_book, robinhood_fills
from app.models import DayJournalEntry
from app.routers import copilot_desk
from tests.test_copilot_desk import desk  # noqa: F401  (the desk app over the shared fixtures)
from tests.test_copilot_desk_feed import tv_alert
from tests.test_copilot_plans import T0, engine, quotes  # noqa: F401  (fixtures)
from tests.test_today import clock, marks  # noqa: F401  (fixtures)

NOW = (T0 + timedelta(minutes=289)).replace(tzinfo=UTC).timestamp()  # 14:49 New York, Wednesday Oct 21 (the clock fixture's)
OPEN = (T0 - timedelta(minutes=30)).replace(tzinfo=UTC).timestamp()  # 9:30


@pytest.fixture
def regular(monkeypatch):
    """The regular session (9:30–16:00), whatever the calendar would say; ``phase["now"]`` moves it."""
    phase = {"now": "regular"}
    monkeypatch.setattr(desk_sparks, "_session", lambda now: (None, phase["now"], None,
                                                               (int(OPEN), int(OPEN + 390 * 60)) if phase["now"] != "weekend" else None))
    desk_ticks.clear()
    yield phase
    desk_ticks.clear()


def read(client):
    response = client.get("/copilot/desk/health")
    assert response.status_code == 200, response.text
    return response.json()


def by_id(body):
    return {row["id"]: row for row in body["sources"]}


def test_refused_while_the_lab_is_off(desk, monkeypatch):  # noqa: F811
    monkeypatch.setattr(copilot_desk.copilot, "settings", lambda: SimpleNamespace(enabled=False))
    assert desk.get("/copilot/desk/health").status_code == 503


def test_every_source_has_a_row_and_nothing_switched_on_is_never_green(desk, regular, monkeypatch):  # noqa: F811
    monkeypatch.setattr(desk_health, "gmail", lambda db, now: desk_health._row("gmail", "Fill emails", "off", "Real-time off", None, ""))
    body = read(desk)
    rows = by_id(body)
    assert list(rows) == ["robinhood", "prices", "chatter", "tradingview", "gmail", "radar", "budget"]
    assert rows["robinhood"]["state"] == "off"
    assert rows["prices"]["state"] == "unknown"  # in the session with no price read yet: unknown, not live
    assert rows["prices"]["line"] == "No price read yet"
    assert rows["radar"]["state"] == "off" and rows["budget"]["state"] == "off"
    assert all(r["state"] != "live" for r in body["sources"])
    assert body["overall"] == "unknown"


def test_closed_hours_say_closed_not_stale(desk, regular, monkeypatch):  # noqa: F811
    regular["now"] = "weekend"
    monkeypatch.setenv("CHATTER_WSB_SOURCE", "apewisdom")
    monkeypatch.setattr(chatter, "load", lambda name, root=None: {"ok_at": NOW - 3 * 86400, "error_at": None})
    monkeypatch.setattr(desk_ticks, "health", lambda: (NOW - 3 * 86400, None))
    rows = by_id(read(desk))
    assert rows["prices"]["state"] == "closed"
    assert rows["chatter"]["state"] == "closed"
    assert rows["chatter"]["line"].startswith("Reads on market days")


def test_prices_live_then_stale_then_failing(desk, regular, monkeypatch):  # noqa: F811
    good = {"at": NOW - 4, "failed": None}
    monkeypatch.setattr(desk_ticks, "health", lambda: (good["at"], good["failed"]))
    assert by_id(read(desk))["prices"]["state"] == "live"
    good["at"] = NOW - 5 * 60
    row = by_id(read(desk))["prices"]
    assert row["state"] == "stale" and row["line"] == "Last price 14:44"
    good["failed"] = NOW - 2
    row = by_id(read(desk))["prices"]
    assert row["state"] == "down" and row["line"] == "Quotes failing · last price 14:44"


def test_desk_ticks_health_reports_the_newest_read_and_failure():
    desk_ticks.clear()
    try:
        assert desk_ticks.health() == (None, None)
        with desk_ticks._lock:
            desk_ticks._kept.update({"NVDA": (100.0, {"last": 1}), "MU": (130.0, None)})
            desk_ticks._issue = (120.0, "timeout")
        assert desk_ticks.health() == (130.0, 120.0)
    finally:
        desk_ticks.clear()


def test_the_router_reads_the_feed_without_starting_a_read(monkeypatch):
    calls = []

    class Feed:
        def snapshot(self, kick=True):
            calls.append(kick)
            return {"state": "signed_out"}, None

        def last_read_at(self):
            return NOW - 9 * 60

        def refresh(self, force=False):
            pytest.fail("the health read started a Robinhood read")

    monkeypatch.setattr(robinhood_book, "feed", Feed())
    monkeypatch.setattr(robinhood_fills, "mode", lambda: "shadow")
    monkeypatch.setattr(robinhood_fills.poller, "status", lambda: {"at": None, "state": "not run"})
    facts = copilot_desk._robinhood_health(NOW)
    assert calls == [False]
    assert facts["state"] == "signed_out" and facts["last_at"] == NOW - 9 * 60
    assert facts["refresh_window"] == robinhood_book.STALE_REFRESHES * robinhood_book.ttl(NOW)
    assert facts["orders"] == {"mode": "shadow", "status": {"at": None, "state": "not run"}}


def rh(state="ok", last=NOW - 30, orders=None):
    return {"state": state, "last_at": last, "refresh_window": 180, "orders": orders or {"mode": "off", "status": {}}}


def test_robinhood_signed_out_says_its_last_read_and_the_sign_in_steps():
    row = desk_health.robinhood(NOW, rh("signed_out", NOW - 9 * 60))
    assert row["state"] == "down"
    assert row["line"] == "Last read 14:40, signed out"
    assert row["fix"]["kind"] == "text" and "sign-in" in row["fix"]["text"]
    assert "Positions" in row["affects"]
    assert desk_health.robinhood(NOW, rh("expired", None))["line"] == "No read yet, sign-in expired"
    assert desk_health.robinhood(NOW, rh("off", None))["state"] == "off"
    assert desk_health.robinhood(NOW, rh("loading", None))["state"] == "unknown"


def test_robinhood_live_stale_and_orders_behind():
    assert desk_health.robinhood(NOW, rh())["state"] == "live"
    assert desk_health.robinhood(NOW, rh(last=NOW - 10 * 60))["state"] == "stale"  # past three market-hours refreshes
    failed = {"mode": "shadow", "status": {"at": int(NOW - 60), "state": "read failed (timeout)"}}
    row = desk_health.robinhood(NOW, rh(orders=failed))
    assert row["state"] == "down" and row["line"] == "Positions live · orders: last read failed 14:48"
    behind = {"mode": "shadow", "status": {"at": int(NOW - 20 * 60), "state": "ok"}}
    row = desk_health.robinhood(NOW, rh(orders=behind))
    assert row["state"] == "stale" and row["line"] == "Positions live · orders last read 14:29"


def test_robinhood_feed_last_read_at_is_the_kept_snapshot():
    feed = robinhood_book.Feed(settings_fn=lambda: SimpleNamespace(enabled=False))
    assert feed.last_read_at() is None
    feed._snapshot = {"at": 123.0}
    assert feed.last_read_at() == 123.0


def test_chatter_live_stale_and_the_first_read_of_the_day(regular, monkeypatch):
    monkeypatch.setenv("CHATTER_WSB_SOURCE", "apewisdom")
    state = {"ok_at": NOW - 10 * 60, "error_at": None}
    monkeypatch.setattr(chatter, "load", lambda name, root=None: dict(state))
    regular_window = (int(OPEN), int(OPEN + 390 * 60))
    assert desk_health.chatter_row(NOW, regular_window)["state"] == "live"
    state["ok_at"] = NOW - 2 * 3600
    assert desk_health.chatter_row(NOW, regular_window)["state"] == "stale"
    state["error_at"] = NOW - 60
    assert desk_health.chatter_row(NOW, regular_window)["state"] == "down"
    # 6:05 on a market day, last read last night: its first read is due, not stale.
    early = datetime(2026, 10, 21, 10, 5, tzinfo=UTC).timestamp()
    state.update(ok_at=early - 10 * 3600, error_at=None)
    assert desk_health.chatter_row(early, regular_window)["state"] == "unknown"


def test_tradingview_today_is_live_none_today_is_quiet_and_a_hidden_ticker_stays_silent(desk, engine, regular):  # noqa: F811
    with Session(engine) as db:
        tv_alert(db, "NBIS", -60 * 24)  # yesterday
        db.commit()
    row = by_id(read(desk))["tradingview"]
    assert row["state"] == "quiet" and row["line"] == "No alerts today · last Tue 10:00"
    with Session(engine) as db:
        tv_alert(db, "APLD", 30)  # today 10:30, on a ticker he then stops following
        db.add(DayJournalEntry(operation_id="unfollow-apld", day=T0.date(), kind="follow", symbol="APLD", text="Not following"))
        db.commit()
    row = by_id(read(desk))["tradingview"]
    assert row["state"] == "quiet" and "APLD" not in row["line"] and "10:30" not in row["line"]
    with Session(engine) as db:
        tv_alert(db, "NBIS", 40)
        db.commit()
    row = by_id(read(desk))["tradingview"]
    assert row["state"] == "live" and row["line"] == "Last alert 10:40"


def test_gmail_disconnected_offers_the_existing_reconnect(monkeypatch):
    from app.engine import gmail_health
    monkeypatch.setattr(gmail_health, "gmail_health", lambda db: {"status": "down", "action": "reconnect_gmail", "message": "x",
                                                                  "last_notification_at": "2026-10-21T18:40:00+00:00"})
    row = desk_health.gmail(None, NOW)
    assert row["state"] == "down" and row["fix"] == {"kind": "gmail_reconnect"}
    assert row["line"] == "Gmail disconnected · last email 14:40"


def test_budget_left_low_and_spent(monkeypatch):
    from app.ai import copilot, copilot_spend
    monkeypatch.setattr(copilot, "settings", lambda: SimpleNamespace(enabled=True, backend="anthropic", daily_budget_usd=4.0))
    spent = {"usd": 1.6}
    monkeypatch.setattr(copilot_spend, "spent_today", lambda db=None: spent["usd"])
    row = desk_health.budget(None)
    assert row["state"] == "live" and row["line"] == "$2.40 left of $4.00 today"
    spent["usd"] = 3.7
    assert desk_health.budget(None)["state"] == "low"
    spent["usd"] = 4.2
    row = desk_health.budget(None)
    assert row["state"] == "down" and row["line"] == "Spent for today ($4.00)"


def test_radar_stale_in_the_session_and_closed_after(tmp_path, monkeypatch):
    from app.engine.radar_store import RadarStore
    path = tmp_path / "radar.sqlite"
    store = RadarStore(path)
    def add(minute, status="ok"):
        at = (T0 + timedelta(minutes=minute)).replace(tzinfo=UTC).isoformat()
        store.append_pass({"session_date": "2026-10-21", "started_at": at, "finished_at": at, "universe_version": "v",
                           "status": status, "symbols_requested": 1, "symbols_returned": 1, "unmatched": [],
                           "requests_used": 1, "error": None, "skip_reason": None})
    add(280)  # 14:40
    monkeypatch.setenv("RADAR_ENABLED", "true")
    monkeypatch.setenv("RADAR_STORE", str(path))
    window = (int(OPEN), int(OPEN + 390 * 60))
    row = desk_health.radar(NOW, "regular", window)
    assert row["state"] == "stale" and row["line"] == "Last pass 14:40"
    add(288)
    assert desk_health.radar(NOW, "regular", window)["state"] == "live"
    assert desk_health.radar(NOW, "post", window)["state"] == "closed"
    monkeypatch.setenv("RADAR_ENABLED", "false")
    assert desk_health.radar(NOW, "regular", window)["state"] == "off"


def test_a_failing_source_is_unknown_and_the_rest_stand(desk, regular, monkeypatch):  # noqa: F811
    def boom(db, now):
        raise RuntimeError("no")
    monkeypatch.setattr(desk_health, "tradingview", boom)
    rows = by_id(read(desk))
    assert rows["tradingview"]["state"] == "unknown"
    assert rows["robinhood"]["state"] == "off"


def test_overall_is_the_worst_state():
    def r(state):
        return {"state": state}
    assert desk_health.overall([r("live"), r("closed"), r("off"), r("quiet")]) == "ok"
    assert desk_health.overall([r("live"), r("unknown")]) == "unknown"
    assert desk_health.overall([r("unknown"), r("stale")]) == "bad"
    assert desk_health.overall([r("low")]) == "bad"


def test_fixture_mode_is_invented_and_reads_nothing(desk, monkeypatch):  # noqa: F811
    monkeypatch.setattr(copilot_desk.copilot, "settings", lambda: SimpleNamespace(enabled=True, evidence="fixture"))
    monkeypatch.setattr(desk_health, "robinhood", lambda now, facts: pytest.fail("fixture mode read a source"))
    monkeypatch.setattr(copilot_desk, "_robinhood_health", lambda now: pytest.fail("fixture mode read the feed"))
    body = read(desk)
    assert body["overall"] == "bad"
    assert by_id(body)["robinhood"]["state"] == "down"


def test_the_minute_request_serves_it():
    assert desk_minute.allowed("/copilot/desk/health")
