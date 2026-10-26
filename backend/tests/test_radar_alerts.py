"""Radar phone alerts: one ping per new event in regular hours, capped, at-most-once, off by default."""
from datetime import timedelta

import httpx
import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.engine import ntfy, radar_alerts, radar_runner, tradier
from app.engine.radar_alerts import RadarAlerts, message
from app.engine.radar_runner import RadarRunner
from app.engine.tradier import TradierQuote
from app.models import PhonePing, RadarAlert
from tests.test_radar_rules import DAY, OPEN, PATHS, UNIVERSE, Calendar, _iso, _store_with, steps

EVENT = "rv0-2030-01-15-spy-aaa-up-1"


class Clock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


def at(minute: int) -> float:
    return (OPEN + timedelta(minutes=minute)).timestamp()


@pytest.fixture
def engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture(autouse=True)
def env(monkeypatch):
    for name in ("RADAR_ALERTS_ENABLED", "RADAR_ALERTS_DAILY_CAP", "ALERT_APP_URL", "COPILOT_ENABLED", "ALERT_POLICY_ENABLED",
                 "PING_DAILY_CAP", "PING_QUIET_MINUTES"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("NTFY_URL", "https://ntfy.example/topic")


def sent_to(monkeypatch, record):
    def publish(title, body, priority=4, tags=(), path="", direct_click=False, more=()):
        record.append({"title": title, "body": body, "priority": priority, "tags": tags, "path": path, "direct_click": direct_click, "more": more})
        return "ntfy-id"
    monkeypatch.setattr(ntfy, "publish", publish)


def _runner(store, minute: int, alerts: RadarAlerts | None, paths=PATHS):
    """A recorder at ``minute`` after the open whose clock the alerts share."""
    clock = Clock(at(minute) + 1)
    if alerts is not None:
        alerts.clock = clock

    def quotes(symbols):
        return {s: TradierQuote(symbol=s, last=paths.get(s, steps())(minute), bid=None, ask=None, volume=1000,
                                trade_date=int((clock() - 1) * 1000), raw={"prevclose": "100"}) for s in symbols}
    return RadarRunner(store, Calendar(), universe=UNIVERSE, quotes=quotes, clock=clock, news=lambda symbols, start, end: [], alerts=alerts)


def rows(engine) -> list[RadarAlert]:
    with Session(engine) as db:
        return db.exec(select(RadarAlert).order_by(RadarAlert.detected_at)).all()


def _event(event_id: str, symbol: str, minute: int, kind="relative_to_spy", group=None, direction="up") -> dict:
    """The fields a ping reads, in the shape the rules write."""
    stock = kind != "group_move"
    measures = ({"relative_pct": 4.9, "change_pct": 5.0, "benchmark_change_pct": 0.1, "day_change_pct": 5.0, "window_minutes": 30} if stock
                else {"median_relative_pct": 2.3, "members_same_direction": 4, "members_with_data": 5, "members_total": 5, "window_minutes": 30})
    summary = (f"{symbol} ahead of SPY by 4.9% over 30 min ({symbol} +5.0%, SPY +0.1%)" if stock
               else f"{group} ahead of SPY: 4 of 5 members up vs SPY over 30 min, median +2.3% (biggest {symbol} +3.1%; SPY +0.1%)")
    return {"event_id": event_id, "session_date": DAY, "rule_version": "radar-rules-v0", "universe_version": "radar-universe-test",
            "kind": kind, "direction": direction, "symbols": [symbol], "benchmark": "SPY", "group": group,
            "first_seen_at": _iso(OPEN + timedelta(minutes=minute, seconds=2)), "summary": summary, "measures": measures,
            "evidence": [], "coverage": {"passes_expected": minute, "passes_recorded": minute, "symbols_missing": []},
            "chart": {"symbol": symbol, "from": _iso(OPEN), "to": _iso(OPEN + timedelta(minutes=minute))}}


# ------------------------------------------------------------ the trigger, through the recorder

def test_a_new_event_pings_once_with_its_read_and_rating_actions(tmp_path, engine, monkeypatch):
    store = _store_with(tmp_path, 36)
    sent = []
    sent_to(monkeypatch, sent)
    alerts = RadarAlerts(engine)
    _runner(store, 37, alerts).run_once()  # the third qualifying pass: the event is written and pinged the same minute
    [event] = store.events(DAY)
    assert event["event_id"] == EVENT
    [push] = sent
    assert push["title"] == "Radar: AAA +6.0% vs SPY 0.0%"
    assert push["body"] == f"{event['summary']} · 10:07 AM ET"
    assert push["path"] == f"/radar?event={EVENT}" and push["direct_click"] is True and push["priority"] == 4
    assert push["more"] == (("Useful", f"/radar?event={EVENT}&rate=useful"), ("Not useful", f"/radar?event={EVENT}&rate=irrelevant"))
    [row] = rows(engine)
    assert (row.event_id, row.subject, row.kind, row.delivery, row.attempts, row.last_error) == (EVENT, "AAA", "relative_to_spy", "sent", 1, None)
    assert row.delivered_at is not None and row.title == push["title"]

    # The next pass keeps the event active (no new event); an extension writes a revision: neither pings again.
    _runner(store, 38, alerts).run_once()
    _runner(store, 50, alerts, paths={"AAA": steps((35, 106.0), (50, 108.5))}).run_once()
    assert [r["status"] for r in store.revisions(EVENT)] == ["extended"]
    assert len(sent) == 1 and len(rows(engine)) == 1

    # A restart re-detecting the same pass writes nothing and pings nothing.
    restarted = _runner(store, 38, RadarAlerts(engine))
    assert restarted.detect(DAY, 38) == ([], [])
    restarted.run_once()
    assert len(sent) == 1 and len(rows(engine)) == 1


def test_without_alerts_the_recorder_stays_silent(tmp_path, engine, monkeypatch):
    store = _store_with(tmp_path, 36)
    sent = []
    sent_to(monkeypatch, sent)
    _runner(store, 37, None).run_once()
    assert len(store.events(DAY)) == 1 and sent == [] and rows(engine) == []


def test_startup_wires_alerts_only_when_switched_on(monkeypatch, tmp_path):
    monkeypatch.delenv("TJ_DOT_TRIAL_ENABLED", raising=False)
    monkeypatch.setenv("RADAR_ENABLED", "true")
    monkeypatch.setenv("RADAR_STORE", str(tmp_path / "radar.sqlite"))
    monkeypatch.setattr(tradier, "TRADIER_API_KEY", "test")
    assert radar_runner.runner_from_env().alerts is None  # off by default
    monkeypatch.setenv("RADAR_ALERTS_ENABLED", "true")
    assert isinstance(radar_runner.runner_from_env().alerts, RadarAlerts)


def test_nothing_is_recorded_or_sent_outside_regular_hours(tmp_path, engine, monkeypatch):
    store = _store_with(tmp_path, 36)
    sent = []
    sent_to(monkeypatch, sent)
    alerts = RadarAlerts(engine, clock=Clock(at(36)))
    [row] = alerts.record([_event("e-pending", "BBB", 36)])
    assert row.delivery == "pending"
    assert _runner(store, 395, alerts).run_once() is None  # 16:05: no pass, no ping, the row waits
    assert sent == [] and rows(engine)[0].delivery == "pending"


def test_a_failing_ping_never_touches_the_recorded_pass(tmp_path, engine, monkeypatch, caplog):
    store = _store_with(tmp_path, 36)
    alerts = RadarAlerts(engine)
    monkeypatch.setattr(alerts, "record", lambda events: 1 / 0)
    pass_id = _runner(store, 37, alerts).run_once()
    assert pass_id == 37 and store.passes(DAY)[-1]["status"] == "ok" and len(store.events(DAY)) == 1
    assert "Radar alerts failed" in caplog.text


# ------------------------------------------------------------ caps and messages

def test_daily_cap_and_one_per_subject_an_hour(engine, monkeypatch):
    monkeypatch.setenv("RADAR_ALERTS_DAILY_CAP", "3")
    clock = Clock(at(30))
    alerts = RadarAlerts(engine, clock=clock)
    [first] = alerts.record([_event("e1", "AAA", 30)])
    assert first.delivery == "pending"
    assert alerts.record([_event("e1", "AAA", 30)]) == []  # already written: left alone
    clock.now = at(60)
    [again] = alerts.record([_event("e2", "AAA", 60, direction="down")])
    assert again.delivery == "skipped" and again.last_error == "AAA was already alerted at 10:00 AM ET; one an hour, so this one was not sent."
    clock.now = at(91)
    [later, other] = alerts.record([_event("e3", "AAA", 91), _event("e4", "Test group", 91, kind="group_move", group="Test group")])
    assert later.delivery == "pending" and other.delivery == "pending" and other.subject == "Test group"
    [capped] = alerts.record([_event("e5", "CCC", 91)])
    assert capped.delivery == "skipped" and capped.last_error == "Daily cap of 3 Radar alerts reached, so this one was not sent."
    assert [r.delivery for r in rows(engine)] == ["pending", "skipped", "pending", "pending", "skipped"]
    sent = []
    sent_to(monkeypatch, sent)
    alerts.deliver()  # the 10:00 ping is over 15 minutes old by now: dropped, not sent late
    assert [p["title"] for p in sent] == ["Radar: AAA +5.0% vs SPY +0.1%", "Radar: Test group +2.3% vs SPY (4 of 5 up)"]
    assert [r.delivery for r in rows(engine)] == ["expired", "skipped", "sent", "sent", "skipped"]


def test_group_and_down_messages():
    title, body = message(_event("g", "AAA", 40, kind="group_move", group="Test group"))
    assert title == "Radar: Test group +2.3% vs SPY (4 of 5 up)" and body.endswith("SPY +0.1%) · 10:10 AM ET")
    event = _event("d", "BBB", 200, direction="down")
    event["measures"].update(change_pct=-5.7, benchmark_change_pct=-0.2)
    assert message(event)[0] == "Radar: BBB −5.7% vs SPY −0.2%"
    assert radar_alerts.event_path("rv0-x", "useful") == "/radar?event=rv0-x&rate=useful"


# ------------------------------------------------------------ delivery states

def _pending(engine, clock) -> RadarAlerts:
    alerts = RadarAlerts(engine, clock=clock)
    [row] = alerts.record([_event("e1", "AAA", 30)])
    assert row.delivery == "pending"
    return alerts


@pytest.mark.parametrize("cause,outcome", [
    (None, "pending"), (httpx.ConnectError("refused"), "pending"),
    (httpx.ReadTimeout("no answer"), "unknown"), (httpx.RemoteProtocolError("dropped"), "unknown"),
])
def test_only_a_send_that_surely_never_left_is_retried(engine, monkeypatch, cause, outcome):
    clock = Clock(at(30))
    alerts = _pending(engine, clock)

    def publish(*args, **kwargs):
        if cause is None:
            raise ntfy.NtfyError("ntfy refused the notification (500).")
        raise ntfy.NtfyError("ntfy could not be reached.") from cause
    monkeypatch.setattr(ntfy, "publish", publish)
    alerts.deliver()
    [row] = rows(engine)
    assert row.delivery == outcome and row.attempts == 1
    if outcome == "pending":
        assert row.next_attempt_at is not None
        alerts.deliver()  # backing off: not retried yet
        assert rows(engine)[0].attempts == 1
    else:
        assert "may have reached the phone" in row.last_error


def test_an_alert_not_sent_within_fifteen_minutes_expires(engine, monkeypatch):
    clock = Clock(at(30))
    alerts = _pending(engine, clock)
    monkeypatch.delenv("NTFY_URL")
    alerts.deliver()
    [row] = rows(engine)
    assert row.delivery == "pending" and "NTFY_URL" in row.last_error and row.attempts == 0
    monkeypatch.setenv("NTFY_URL", "https://ntfy.example/topic")
    sent = []
    sent_to(monkeypatch, sent)
    clock.now = at(46)
    alerts.deliver()
    assert sent == [] and rows(engine)[0].delivery == "expired"


def test_a_stale_claim_is_unknown_and_never_resent(engine, monkeypatch):
    clock = Clock(at(30))
    alerts = _pending(engine, clock)
    with Session(engine) as db:
        row = db.exec(select(RadarAlert)).one()
        row.delivery, row.claimed_at = "sending", radar_alerts._utc(clock.now - 200)
        db.commit()
    sent = []
    sent_to(monkeypatch, sent)
    alerts.deliver()
    assert sent == [] and rows(engine)[0].delivery == "unknown"


# ------------------------------------------------------------ the notification policy

def pings(engine) -> list[PhonePing]:
    with Session(engine) as db:
        return db.exec(select(PhonePing).order_by(PhonePing.decided_at)).all()


def test_a_sent_alert_is_recorded_on_the_notification_policy(engine, monkeypatch):
    sent = []
    sent_to(monkeypatch, sent)
    alerts = _pending(engine, Clock(at(30)))
    alerts.deliver()
    assert len(sent) == 1 and rows(engine)[0].delivery == "sent"
    [ping] = pings(engine)
    assert (ping.sender, ping.kind, ping.decision, ping.anchor, ping.symbol) == ("radar_alerts", "radar_event", "sent", "symbol:AAA", "AAA")
    assert ping.source_id == str(rows(engine)[0].id) and ping.delivered_at is not None


def test_over_the_shared_cap_the_alert_is_held_and_never_sent_later(engine, monkeypatch):
    monkeypatch.setenv("PING_DAILY_CAP", "3")  # every slot is reserved for position and plan pings
    sent = []
    sent_to(monkeypatch, sent)
    clock = Clock(at(30))
    alerts = _pending(engine, clock)
    alerts.deliver()
    [row] = rows(engine)
    assert sent == [] and row.delivery == "held" and row.last_error.startswith("Not sent: 0 pings already went out today (cap 3).")
    assert [p.decision for p in pings(engine)] == ["over_cap"]
    clock.now = at(31)
    alerts.deliver()
    assert sent == [] and rows(engine)[0].delivery == "held"


def test_inside_the_quiet_window_it_is_held_and_a_held_alert_does_not_use_up_its_own_caps(engine, monkeypatch):
    sent = []
    sent_to(monkeypatch, sent)
    clock = Clock(at(30))
    with Session(engine) as db:  # an entry trigger for AAA two minutes earlier
        db.add(PhonePing(sender="level_alerts", source_id="entry-1", kind="entry", rank=4, symbol="AAA", anchor="symbol:AAA",
                         title="t", body="b", decided_at=radar_alerts._utc(at(28)), delivered_at=radar_alerts._utc(at(28)), decision="sent"))
        db.commit()
    alerts = _pending(engine, clock)
    alerts.deliver()
    assert sent == [] and rows(engine)[0].delivery == "held" and "quiet window 10 min" in rows(engine)[0].last_error
    # Twenty minutes later the hourly cap does not count the held one, and the window is over: sent.
    clock.now = at(50)
    [again] = alerts.record([_event("e2", "AAA", 50)])
    assert again.delivery == "pending"
    alerts.deliver()
    assert [p["title"] for p in sent] == ["Radar: AAA +5.0% vs SPY +0.1%"] and rows(engine)[1].delivery == "sent"
    # The alerts' own caps still hold: a third AAA event inside the hour is skipped and never reaches the gate.
    clock.now = at(60)
    [third] = alerts.record([_event("e3", "AAA", 60)])
    assert third.delivery == "skipped" and "one an hour" in third.last_error
    assert [p.decision for p in pings(engine) if p.sender == "radar_alerts"] == ["suppressed", "sent"]


def test_a_group_event_is_anchored_to_its_group(engine, monkeypatch):
    sent_to(monkeypatch, [])
    alerts = RadarAlerts(engine, clock=Clock(at(30)))
    alerts.record([_event("g1", "AAA", 30, kind="group_move", group="Test group")])
    alerts.deliver()
    [ping] = pings(engine)
    assert (ping.anchor, ping.symbol, ping.decision) == ("group:Test group", None, "sent")
