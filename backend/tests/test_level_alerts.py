"""Level alerts (Charts C5.1): when they fire, that each firing is recorded once
through reconnects and restarts, that delivery retries without losing one, and
the private routes. Trades come through the real stream parser; minutes through
a stand-in for the chart feed's budgeted read."""

import asyncio
from datetime import UTC, date, datetime
import json
from types import SimpleNamespace
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.database import get_session
from app.engine import chart_stream, level_alerts, ntfy
from app.engine import level_alert_monitor as monitor_module
from app.engine.chart_math import ET
from app.engine.level_alert_monitor import LevelAlertMonitor, alert_rows, create_alert
from app.models import LevelAlert, LevelAlertEvent
from app.routers import level_alerts as routes

TEN = datetime(2026, 10, 5, 10, 0, tzinfo=ET).timestamp()  # a Monday, in the regular session


def at(clock: str) -> float:
    hour, minute = clock.split(":")[:2]
    second = clock.split(":")[2] if clock.count(":") == 2 else "0"
    return datetime(2026, 10, 5, int(hour), int(minute), int(second), tzinfo=ET).timestamp()


# ------------------------------------------------------------------ pure rules

def test_touches_reach_the_level_and_crosses_go_through_it():
    assert level_alerts.direction(99.5, 100) == "up" and level_alerts.direction(100.5, 100) == "down"
    assert level_alerts.direction(100, 100) is None
    assert level_alerts.trade_fires("touches", "up", 100, 100.0) and not level_alerts.trade_fires("crosses", "up", 100, 100.0)
    assert level_alerts.trade_fires("crosses", "up", 100, 100.01) and not level_alerts.trade_fires("touches", "up", 100, 99.99)
    assert level_alerts.trade_fires("crosses", "down", 100, 99.99) and not level_alerts.trade_fires("crosses", "down", 100, 100.5)
    bar = {"high": 100.4, "low": 99.2, "close": 99.9}
    assert level_alerts.minute_fires("crosses", "up", 100, bar) and level_alerts.minute_fires("touches", "down", 99.2, bar)
    assert not level_alerts.close_fires("up", 100, bar) and level_alerts.close_fires("down", 100, bar)


def test_a_candle_is_final_thirty_seconds_after_it_closes():
    bars = [{"time": at("10:00"), "end_time": at("10:05")}, {"time": at("10:05"), "end_time": at("10:10")}]
    assert level_alerts.final(bars, at("10:05:29"), 0) == []
    assert level_alerts.final(bars, at("10:05:30"), 0) == bars[:1]
    assert level_alerts.final(bars, at("10:11"), at("10:05")) == bars[1:]  # already judged through 10:05


def test_an_alert_moves_with_a_later_split_as_a_saved_level_does():
    splits = [{"ex_date": "2026-10-02", "ratio": 5.0}]
    assert level_alerts.on_today_basis(500, date(2026, 10, 1), splits) == 100
    assert level_alerts.on_today_basis(100, date(2026, 10, 2), splits) == 100


def test_the_phone_message_names_symbol_level_price_and_time():
    alert = {"symbol": "SPY", "condition": "crosses", "interval": None, "direction": "up", "label": "PDH"}
    event = {"level": 581.2, "price": 581.24, "event_at": at("10:42:13"), "source": "stream", "bar_time": None, "detected_at": at("10:42:13")}
    assert level_alerts.message(alert, event) == ("SPY crossed above 581.20", "Crossed at 581.24 (trade), 10:42:13 AM ET. Alert on PDH.")
    late = {**event, "source": "minute_bars", "event_at": at("10:42"), "bar_time": at("10:42"), "detected_at": at("10:50")}
    assert level_alerts.message({**alert, "condition": "touches", "label": ""}, late) == (
        "SPY touched 581.20", "Touched at 581.24 (1-minute bar high), the 10:42 AM ET minute. Noticed 8 min after it happened.")
    close = {"level": 581.2, "price": 580.9, "event_at": at("10:45"), "source": "closed_bar", "bar_time": at("10:40"), "detected_at": at("10:45:40")}
    assert level_alerts.message({**alert, "condition": "closes_beyond", "interval": "5m", "direction": "down", "label": ""}, close) == (
        "SPY 5m closed below 581.20", "Close 580.90, the 10:40 AM–10:45 AM ET candle.")


# ------------------------------------------------------------------ monitor

class Feed:
    """The chart feed's read: today's minutes, counted."""

    def __init__(self, minutes=()):
        self.minutes = list(minutes)
        self.calls = []

    def read(self, path, params, ttl):
        self.calls.append(params["symbol"])
        rows = [{"timestamp": int(start), "open": o, "high": h, "low": low, "close": c, "volume": 100} for start, o, h, low, c in self.minutes]
        return {"series": {"data": rows}}, time.time(), None


@pytest.fixture
def engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    yield engine
    engine.dispose()


def make(engine, *, symbol="SPY", price=100.0, reference=99.0, condition="crosses", interval=None, session="regular", now=TEN, label="My level"):
    with Session(engine) as db:
        return create_alert(db, symbol=symbol, price=price, reference=reference, condition=condition, interval=interval,
                            session=session, source_kind="level", source_id="lvl-1", label=label, now=now).id


def events(engine):
    with Session(engine) as db:
        return db.exec(select(LevelAlertEvent)).all()


@pytest.fixture
def stream(monkeypatch):
    """The real stream parser on a fixed clock: trades are validated as Tradier sends them."""
    clock = [TEN + 60]
    monkeypatch.setattr(chart_stream, "time", SimpleNamespace(time=lambda: clock[0], monotonic=time.monotonic))
    market = chart_stream.ChartMarketStream(clock=lambda: clock[0])
    return market, clock


def trades(*rows):
    return "\n".join(json.dumps({"type": "timesale", "symbol": symbol, "last": str(price), "date": str(int(stamp * 1000)), "size": "100",
                                 "cancel": "false", "correction": "false"}) for symbol, price, stamp in rows)


def test_a_fixture_stream_records_one_event_per_crossing_before_coalescing(engine, stream):
    market, clock = stream
    alert = make(engine)
    monitor = LevelAlertMonitor(engine, market, clock=lambda: clock[0])
    market.attach(monitor)
    monitor.reload()
    assert market._wanted() == {"SPY"}  # carried with no chart open
    # A touch is not a cross; the crossing trade is followed by more trades in the same second,
    # which the browser's coalescing would have merged into one price.
    market._receive(trades(("SPY", 99.8, TEN + 50), ("SPY", 100.0, TEN + 51), ("SPY", 100.3, TEN + 52), ("SPY", 99.9, TEN + 52.5)))
    assert len(monitor._found) == 1 and monitor._found[0]["price"] == 100.3 and monitor._found[0]["source"] == "stream"
    market._receive(trades(("SPY", 100.6, TEN + 55)))
    assert len(monitor._found) == 1
    monitor.record(monitor._found)
    saved = events(engine)
    assert len(saved) == 1 and saved[0].price == 100.3 and saved[0].delivery == "pending"
    with Session(engine) as db:
        assert db.get(LevelAlert, alert).state == "fired"
    # A restart: a new monitor with nothing in memory reloads only active alerts, and a second
    # detector finding the same firing records nothing more.
    again = LevelAlertMonitor(engine, market, clock=lambda: clock[0])
    again.reload()
    assert again._watched == {}
    again.record([{**monitor._found[0], "detected_at": clock[0] + 5}])
    assert len(events(engine)) == 1
    with Session(engine) as db, pytest.raises(IntegrityError):
        db.add(LevelAlertEvent(alert_id=alert, generation=1, level=100, price=101, source="stream", event_at=datetime.now(UTC).replace(tzinfo=None)))
        db.commit()


def test_a_reconnect_gap_is_judged_on_minute_bars_and_covered_minutes_are_not(engine, stream):
    market, clock = stream
    make(engine)
    # The 10:01 minute's high crossed, but the stream carried SPY then (and saw no valid crossing trade);
    # it dropped from 10:02 to 10:04, when the 10:03 minute crossed.
    feed = Feed([(at("10:01"), 99.5, 100.4, 99.4, 99.6), (at("10:02"), 99.6, 99.9, 99.5, 99.7), (at("10:03"), 99.7, 100.2, 99.6, 99.8)])
    market._coverage = {"SPY": [[TEN, at("10:02")], [at("10:04"), None]]}
    clock[0] = at("10:04:31")
    monitor = LevelAlertMonitor(engine, market, feed=feed, clock=lambda: clock[0])
    monitor.reload()
    fired = monitor.sweep()
    assert [(e["source"], e["price"], e["event_at"]) for e in fired] == [("minute_bars", 100.2, at("10:03"))]
    monitor.record(fired)
    assert len(events(engine)) == 1


def test_a_covered_stream_costs_no_rest_read_and_saves_progress_for_a_restart(engine, stream):
    market, clock = stream
    alert = make(engine)
    feed = Feed()
    market._coverage = {"SPY": [[TEN - 1, None]]}
    clock[0] = at("10:06:40")
    monitor = LevelAlertMonitor(engine, market, feed=feed, clock=lambda: clock[0])
    monitor.reload()
    assert monitor.sweep() == [] and feed.calls == []
    with Session(engine) as db:
        assert db.get(LevelAlert, alert).checked_through == at("10:06")


def test_closes_beyond_waits_for_a_final_candle_with_no_browser_open(engine):
    # 10:00-10:05 closes above 100 once its last minute is in; a candle closing above before
    # the alert was armed does not count. No stream at all: no chart is open.
    make(engine, condition="closes_beyond", interval="5m", now=at("09:58"), reference=99.0)
    minutes = [(at("09:50") + 60 * i, 100.5, 100.6, 100.4, 100.5) for i in range(5)]  # closes above at 09:55, before arming
    minutes += [(at("09:55") + 60 * i, 99.6, 99.8, 99.4, 99.5) for i in range(5)]  # closes below at 10:00
    minutes += [(at("10:00") + 60 * i, 99.8, 100.4, 99.7, 99.9 if i < 4 else 100.2) for i in range(5)]
    feed = Feed(minutes)
    clock = [at("10:05:20")]
    monitor = LevelAlertMonitor(engine, None, feed=feed, clock=lambda: clock[0])
    monitor.reload()
    assert monitor.symbols() == set()  # a close alert never needs the stream
    assert monitor.sweep() == []  # not final yet
    clock[0] = at("10:05:31")
    fired = monitor.sweep()
    assert [(e["source"], e["price"], e["event_at"], e["bar_time"]) for e in fired] == [("closed_bar", 100.2, at("10:05"), at("10:00"))]
    # Two passes in one minute read the minutes once.
    reads = len(feed.calls)
    monitor.record(fired)
    monitor.reload()
    monitor.sweep()
    assert len(feed.calls) == reads


def test_no_minutes_are_read_after_the_session_or_on_a_closed_day(engine):
    # After the last candle is judged the session is done: no read every 20 seconds until midnight.
    make(engine, condition="closes_beyond", interval="5m", now=at("15:00"))
    make(engine, symbol="QQQ", condition="crosses", now=at("15:00"))
    feed = Feed([(at("15:55") + 60 * i, 99.0, 99.2, 98.9, 99.1) for i in range(5)])
    clock = [at("16:10")]
    monitor = LevelAlertMonitor(engine, None, feed=feed, clock=lambda: clock[0])
    monitor.reload()
    monitor.sweep()
    assert sorted(feed.calls) == ["QQQ", "SPY"]
    with Session(engine) as db:
        # A regular-hours alert is judged through 16:00, the quiet minutes included.
        assert {a.checked_through for a in db.exec(select(LevelAlert)).all()} == {int(at("16:00"))}
    for later in ("16:30", "19:59", "23:00"):
        clock[0] = at(later)
        monitor.sweep()
    assert len(feed.calls) == 2
    # A Saturday, and a holiday the calendar names, read nothing.
    saturday = datetime(2026, 10, 10, 11, 0, tzinfo=ET).timestamp()
    weekend = LevelAlertMonitor(engine, None, feed=feed, clock=lambda: saturday)
    weekend.reload()
    assert weekend.sweep() == [] and len(feed.calls) == 2
    closed = SimpleNamespace(hours=lambda day: {"status": "closed", "open": None, "close": None})
    holiday = LevelAlertMonitor(engine, None, feed=feed, calendar=closed, clock=lambda: at("11:00"))
    holiday.reload()
    assert holiday.sweep() == [] and len(feed.calls) == 2
    # Before 09:30 a regular-hours alert has nothing to judge, so nothing is read.
    clock[0] = at("08:00")
    morning = LevelAlertMonitor(engine, None, feed=feed, clock=lambda: clock[0])
    with Session(engine) as db:
        for alert in db.exec(select(LevelAlert)).all():
            alert.checked_through, alert.armed_at = None, datetime.fromtimestamp(at("07:00"), UTC).replace(tzinfo=None)
        db.commit()
    morning.reload()
    morning.sweep()
    assert len(feed.calls) == 2


def test_a_firing_the_database_could_not_save_is_saved_on_the_next_pass(engine, phone, monkeypatch):
    sent, _ = phone
    make(engine)
    clock = [TEN + 60]
    monitor = LevelAlertMonitor(engine, None, clock=lambda: clock[0])
    monitor.reload()
    alert = next(iter(monitor._watched.values()))
    record = monitor.record
    outage = [True]

    def flaky(found):
        if outage.pop() if outage else False:
            raise OSError("database unavailable")
        record(found)

    monkeypatch.setattr(monitor, "record", flaky)
    monitor.on_tick({"symbol": "SPY", "session": "regular", "at": TEN + 55, "price": 100.4})
    with pytest.raises(OSError):
        asyncio.run(monitor.run_once())
    assert len(monitor._found) == 1 and events(engine) == []
    monitor.on_tick({"symbol": "SPY", "session": "regular", "at": TEN + 56, "price": 100.6})  # held out until saved
    asyncio.run(monitor.run_once())
    saved = events(engine)
    assert len(saved) == 1 and saved[0].price == 100.4 and monitor._found == []
    assert len(sent) == 1 and alert["id"] not in monitor._watched


def test_extended_hours_trades_count_only_for_an_extended_alert(engine, stream):
    market, clock = stream
    make(engine, symbol="SPY", session="regular", now=at("08:00"))
    make(engine, symbol="QQQ", session="extended", now=at("08:00"))
    clock[0] = at("08:05")
    monitor = LevelAlertMonitor(engine, market, clock=lambda: clock[0])
    market.attach(monitor)
    monitor.reload()
    market._receive(trades(("SPY", 100.5, at("08:04:58")), ("QQQ", 100.5, at("08:04:59"))))
    assert [event["source"] for event in monitor._found] == ["stream"] and len(monitor._found) == 1
    # Overnight the stream drops alert symbols.
    clock[0] = at("23:00")
    assert monitor.symbols() == set()


@pytest.fixture
def phone(monkeypatch):
    sent = []
    failures = [0]

    def publish(title, message, **_):
        if failures[0]:
            failures[0] -= 1
            raise ntfy.NtfyError("ntfy could not be reached (ConnectError).")
        sent.append((title, message))

    monkeypatch.setenv("NTFY_URL", "https://ntfy.example/topic")
    monkeypatch.setattr(monitor_module.ntfy, "publish", publish)
    return sent, failures


def fire(engine, clock):
    monitor = LevelAlertMonitor(engine, None, clock=lambda: clock[0])
    monitor.reload()
    alert = next(iter(monitor._watched.values()))
    monitor.record([monitor._event(alert, 100.3, TEN + 50, "stream", None)])
    return monitor


def test_a_failed_send_is_retried_after_a_backoff_and_never_lost(engine, phone):
    sent, failures = phone
    make(engine)
    clock = [TEN + 60]
    monitor = fire(engine, clock)
    failures[0] = 1
    monitor.deliver()
    event = events(engine)[0]
    assert (event.delivery, event.attempts, sent) == ("pending", 1, [])
    assert "ConnectError" in event.last_error
    clock[0] += 10
    monitor.deliver()
    assert sent == []  # still backing off
    clock[0] += 30
    monitor.deliver()
    event = events(engine)[0]
    assert (event.delivery, event.attempts, event.last_error) == ("sent", 2, None)
    assert sent == [("SPY crossed above 100.00", "Crossed at 100.30 (trade), 10:00:50 AM ET. Alert on My level.")]
    monitor.deliver()
    assert len(sent) == 1


def test_a_send_interrupted_mid_claim_is_put_back_and_only_one_process_claims(engine, phone):
    sent, _ = phone
    make(engine)
    clock = [TEN + 60]
    monitor = fire(engine, clock)
    with Session(engine) as db:
        event = db.exec(select(LevelAlertEvent)).one()
        event.delivery, event.claimed_at = "sending", datetime.fromtimestamp(clock[0], UTC).replace(tzinfo=None)
        db.commit()
    monitor.deliver()
    assert sent == []  # another process has it
    clock[0] += 121
    monitor.deliver()
    assert len(sent) == 1 and events(engine)[0].delivery == "sent"


def test_without_ntfy_the_event_waits_and_an_old_one_expires(engine, monkeypatch):
    monkeypatch.delenv("NTFY_URL", raising=False)
    make(engine)
    clock = [TEN + 60]
    monitor = fire(engine, clock)
    monitor.deliver()
    event = events(engine)[0]
    assert (event.delivery, event.attempts) == ("pending", 0) and "NTFY_URL" in event.last_error
    clock[0] += 6 * 3600 + 1
    monitor.deliver()
    assert events(engine)[0].delivery == "expired"


def test_the_running_loop_records_and_sends_a_streamed_firing_at_once(engine, phone):
    sent, _ = phone
    make(engine)
    clock = [TEN + 60]
    stream = SimpleNamespace(started=0, covered=lambda *_: True)
    stream.ensure_running = lambda: setattr(stream, "started", stream.started + 1)

    async def scenario():
        monitor = LevelAlertMonitor(engine, stream, clock=lambda: clock[0], sweep_seconds=60)
        await monitor.start()
        for _ in range(100):  # the first pass loads the alert and starts the stream for it
            await asyncio.sleep(0.01)
            if monitor._watched:
                break
        monitor.on_tick({"symbol": "SPY", "session": "regular", "at": TEN + 55, "price": 100.4})
        for _ in range(100):  # woken by the firing, not the 60-second sweep
            await asyncio.sleep(0.01)
            if sent:
                break
        await monitor.stop()

    asyncio.run(scenario())
    assert stream.started >= 1
    assert sent == [("SPY crossed above 100.00", "Crossed at 100.40 (trade), 10:00:55 AM ET. Alert on My level.")]
    assert events(engine)[0].delivery == "sent"


# ------------------------------------------------------------------ routes

@pytest.fixture
def client(engine):
    app = FastAPI()
    app.include_router(routes.router, prefix="/charts")

    def session():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_session] = session
    changes = []
    app.state.level_alerts = SimpleNamespace(changed=lambda: changes.append(1))
    with TestClient(app) as test_client:
        yield test_client, changes


def body(**overrides):
    return {"symbol": "spy", "price": 581.2, "reference": 579.0, "condition": "crosses", "session": "regular",
            "source_kind": "level", "source_id": "lvl-1", "label": "PDH", **overrides}


def test_routes_create_rearm_and_remove_alerts_and_tell_the_monitor(client, engine):
    http, changes = client
    data = http.post("/charts/alerts", json=body()).json()
    first = data["alerts"][0]
    assert (first["symbol"], first["direction"], first["state"], first["interval"]) == ("SPY", "up", "active", None)
    assert changes == [1] and "phone" in data
    assert http.post("/charts/alerts", json=body()).status_code == 409  # already set
    assert "no side" in http.post("/charts/alerts", json=body(reference=581.2)).json()["detail"]
    assert http.post("/charts/alerts", json=body(condition="closes_beyond", interval="1D")).status_code == 409
    closes = http.post("/charts/alerts", json=body(condition="closes_beyond", interval="5m")).json()["alerts"]
    assert {a["interval"] for a in closes} == {None, "5m"}
    for symbol in ("QQQ", "IWM", "NVDA", "AMD"):
        assert http.post("/charts/alerts", json=body(symbol=symbol)).status_code == 200
    assert "5 symbols" in http.post("/charts/alerts", json=body(symbol="TSLA")).json()["detail"]
    assert http.post("/charts/alerts", json=body(price=-1)).status_code == 422

    # Fired, then re-armed: the next firing is a new generation, recorded beside the first.
    clock = [time.time()]
    monitor = LevelAlertMonitor(engine, None, clock=lambda: clock[0])
    monitor.reload()
    alert = next(a for a in monitor._watched.values() if a["symbol"] == "SPY" and a["condition"] == "crosses")
    monitor.record([monitor._event(alert, 581.3, clock[0], "stream", None)])
    fired = next(a for a in http.get("/charts/alerts").json()["alerts"] if a["id"] == str(alert["id"]))
    assert fired["state"] == "fired" and fired["event"]["price"] == 581.3 and fired["event"]["delivery"] == "pending"
    rearmed = http.post(f"/charts/alerts/{alert['id']}/rearm", json={"price": 581.2, "reference": 582.0}).json()["alerts"]
    again = next(a for a in rearmed if a["id"] == str(alert["id"]))
    assert again["state"] == "active" and again["direction"] == "down" and again["event"] is None
    monitor.reload()
    alert = monitor._watched[alert["id"]]
    monitor.record([monitor._event(alert, 581.1, clock[0], "stream", None)])
    assert len(events(engine)) == 2
    remaining = http.delete(f"/charts/alerts/{alert['id']}").json()["alerts"]
    assert str(alert["id"]) not in {a["id"] for a in remaining} and events(engine) == []
    assert http.post(f"/charts/alerts/{alert['id']}/rearm", json={"price": 1, "reference": 2}).status_code == 404


def test_active_alerts_list_first_and_fired_ones_newest_first(engine):
    for price in (100.0, 101.0, 102.0):
        make(engine, price=price, now=TEN + price)
    clock = [TEN + 300]
    monitor = LevelAlertMonitor(engine, None, clock=lambda: clock[0])
    monitor.reload()
    by_price = {a["level"]: a for a in monitor._watched.values()}
    monitor.record([monitor._event(by_price[100.0], 100.1, TEN + 200, "stream", None),
                    monitor._event(by_price[101.0], 101.1, TEN + 250, "stream", None)])
    with Session(engine) as db:
        assert [row["price"] for row in alert_rows(db)] == [102.0, 101.0, 100.0]
