"""Plan follow-through: a confirmed copilot plan's entry and invalidation pings name the plan and open its investigation
with the question ready, and its time stop becomes one timed ping about a position opened after the plan. Phone only."""

import asyncio
from datetime import date, datetime
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.database import get_session
from app.engine import level_alerts, ntfy, plan_time_stops, reconstructor
from app.engine.chart_math import ET
from app.engine.level_alert_monitor import LevelAlertMonitor, create_alert
from app.engine.plan_time_stops import PlanTimeStops, parse
from app.models import Account, Fill, LevelAlertEvent, PlanTimeStop, Trade
from app.routers import level_alerts as alert_routes
from app.routers import plan_time_stops as time_stop_routes
from app.routers.fills import _rebuild_trades

ROTH, WEBULL = UUID(int=1), UUID(int=2)
INV = "44444444-4444-4444-8444-444444444444"
WED, FRI, MON = date(2026, 10, 21), date(2026, 10, 23), date(2026, 10, 26)
n = iter(range(100, 10_000))


def at(hhmm: str, day: date = WED) -> float:
    h, m = map(int, hhmm.split(":"))
    return datetime(day.year, day.month, day.day, h, m, tzinfo=ET).timestamp()


def et(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, ET).strftime("%a %H:%M")


class Clock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


class Calendar:
    """Every weekday open 9:30-16:00, except an early close on the Friday."""

    def hours(self, day):
        if day.weekday() >= 5:
            return {"status": "closed"}
        return {"status": "open", "open": 570, "close": 780 if day == FRI else 960}


class _Wednesday(date):
    @classmethod
    def today(cls):
        return WED


@pytest.fixture(autouse=True)
def on_wednesday(monkeypatch):
    monkeypatch.setattr(reconstructor, "date", _Wednesday)
    monkeypatch.delenv("PLAN_TIME_STOPS_ENABLED", raising=False)


@pytest.fixture
def engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Account(id=ROTH, name="Roth", type="roth_ira", last4="8267", broker="robinhood"))
        db.add(Account(id=WEBULL, name="Webull", type="individual", last4="4242", broker="webull"))
        db.commit()
    yield engine
    engine.dispose()


@pytest.fixture
def phone(monkeypatch):
    sent = []
    monkeypatch.setenv("NTFY_URL", "https://ntfy.example/topic")
    monkeypatch.setattr(ntfy, "publish", lambda title, body, **kw: sent.append((title, body, kw)))
    return sent


def buy(engine, when="10:05", ticker="NBIS", account=ROTH, day=WED):
    i = next(n)
    with Session(engine) as db:
        db.add(Fill(id=UUID(int=i), account_id=account, ticker=ticker, instrument_type="option", side="buy_to_open", contracts=2,
                    price=310, executed_at=datetime.combine(day, datetime.strptime(when, "%H:%M").time()), raw_email_id=f"gmail:{i}",
                    option_type="call", strike=100, expiration=FRI))
        db.commit()
        _rebuild_trades(db, "test")
        db.commit()


def sell(engine, when="11:00", ticker="NBIS"):
    i = next(n)
    with Session(engine) as db:
        db.add(Fill(id=UUID(int=i), account_id=ROTH, ticker=ticker, instrument_type="option", side="sell_to_close", contracts=2,
                    price=350, executed_at=datetime.combine(WED, datetime.strptime(when, "%H:%M").time()), raw_email_id=f"gmail:{i}",
                    option_type="call", strike=100, expiration=FRI))
        db.commit()
        _rebuild_trades(db, "test")
        db.commit()


def stop(engine, text="out by 15:30", planned="10:00", symbol="NBIS", client_id=None):
    with Session(engine) as db:
        return plan_time_stops.create(db, client_id=client_id or f"card-{next(n)}", investigation_id=INV, symbol=symbol,
                                      text=text, now=at(planned), calendar=Calendar()).id


def stops(engine):
    with Session(engine) as db:
        return db.exec(select(PlanTimeStop).order_by(PlanTimeStop.created_at)).all()


# ------------------------------------------------------------------ plan-aware level pings

def test_entry_and_invalidation_pings_name_the_plan_and_prefill_the_question():
    event = {"level": 95.9, "price": 95.93, "event_at": at("10:41"), "source": "stream", "bar_time": None, "detected_at": at("10:41")}
    title, body, path = level_alerts.plan_message("NBIS", "entry", INV, event)
    assert (title, body) == ("NBIS entry trigger hit", "NBIS hit your 95.90 entry trigger. Still valid? Tap to check.")
    url = urlsplit(path)
    query = parse_qs(url.query)
    assert url.path == "/copilot-lab" and query["investigation"] == [INV] and " " not in path
    assert query["context"] == ["My entry trigger hit at 95.90 (10:41). Is the plan still valid? Check the chart and group now."]

    late = {**event, "level": 92.3, "event_at": at("11:02"), "detected_at": at("11:10")}
    title, body, path = level_alerts.plan_message("NBIS", "invalidation", INV, late)
    assert (title, body) == ("NBIS invalidation broke", "NBIS broke your 92.30 invalidation. Your plan says out. Noticed 8 min after it happened.")
    assert parse_qs(urlsplit(path).query)["context"] == ["My invalidation broke at 92.30 (11:02). My plan says out. Check the chart and group now."]


def plan_alert(engine, role, price=95.9, reference=94.0, source_kind="copilot"):
    with Session(engine) as db:
        return create_alert(db, symbol="NBIS", price=price, reference=reference, condition="crosses", interval=None, session="regular",
                            source_kind=source_kind, source_id=INV, label=f"NBIS {role}: crosses {price}", now=at("10:00"),
                            plan_role=role).id


def fire_all(engine, when):
    monitor = LevelAlertMonitor(engine, None, clock=lambda: when)
    monitor.reload()
    monitor.record([monitor._event(alert, alert["level"] + (0.03 if alert["direction"] == "up" else -0.03), when - 30, "stream", None)
                    for alert in monitor._watched.values()])
    monitor.deliver()


def test_a_plan_alert_fires_with_the_plan_message_and_a_plain_copilot_watch_does_not(engine, monkeypatch):
    calls = []
    monkeypatch.setenv("NTFY_URL", "https://ntfy.example/topic")
    monkeypatch.setattr(ntfy, "publish", lambda title, body, **kw: calls.append((title, body, kw)))
    plan_alert(engine, "entry")
    plan_alert(engine, None, price=97.0)  # a copilot watch: no role
    fire_all(engine, at("10:42"))
    by_title = {title: (body, kw) for title, body, kw in calls}
    body, kw = by_title["NBIS entry trigger hit"]
    assert body == "NBIS hit your 95.90 entry trigger. Still valid? Tap to check." and kw["direct_click"] is True
    assert parse_qs(urlsplit(kw["path"]).query)["investigation"] == [INV]
    body, kw = by_title["NBIS crossed above 97.00"]
    assert kw == {"path": f"/copilot-lab?investigation={INV}", "direct_click": True}  # unchanged
    with Session(engine) as db:
        assert all(e.delivery == "sent" for e in db.exec(select(LevelAlertEvent)).all())


@pytest.fixture
def alert_client(engine):
    app = FastAPI()
    app.include_router(alert_routes.router, prefix="/charts")

    def session():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_session] = session
    with TestClient(app) as client:
        yield client


def test_the_alert_route_records_a_plan_role_only_for_a_copilot_alert(alert_client):
    body = {"symbol": "NBIS", "price": 95.9, "reference": 94.0, "condition": "crosses", "session": "regular",
            "source_kind": "copilot", "source_id": INV, "label": "NBIS entry: crosses 95.9"}
    made = alert_client.post("/charts/alerts", json={**body, "plan_role": "entry"})
    assert made.status_code == 200 and [a["plan_role"] for a in made.json()["alerts"]] == ["entry"]
    watch = alert_client.post("/charts/alerts", json={**body, "price": 97.0})
    assert sorted(str(a["plan_role"]) for a in watch.json()["alerts"]) == ["None", "entry"]
    assert alert_client.post("/charts/alerts", json={**body, "price": 98.0, "plan_role": "target"}).status_code == 422
    assert alert_client.post("/charts/alerts", json={**body, "price": 98.0, "source_kind": "level", "source_id": "lvl-1",
                                                     "plan_role": "entry"}).status_code == 422


# ------------------------------------------------------------------ parsing a time stop

@pytest.mark.parametrize("text, now, due", [
    ("out by 15:30", at("10:00"), "Wed 15:30"),
    ("15:30", at("10:00"), "Wed 15:30"),
    ("3:30pm", at("10:00"), "Wed 15:30"),
    ("3:30", at("10:00"), "Wed 15:30"),  # an afternoon hour without am/pm
    ("out by 15:30 if the entry has not worked", at("10:00"), "Wed 15:30"),
    ("out by 15:30", at("16:10"), "Thu 15:30"),  # today's has passed: the next session
    ("12:30", at("12:45", FRI), "Mon 12:30"),  # Friday's has passed: Monday, over the weekend
    ("45m", at("10:00"), "Wed 10:45"),
    ("2h", at("10:00"), "Wed 12:00"),
    ("90 minutes", at("10:00"), "Wed 11:30"),
    ("2h", at("15:00"), "Wed 16:00"),  # a length runs no later than the close
    ("45m", at("12:45", FRI), "Fri 13:00"),  # Friday's early close
    ("2 days", at("10:00"), "Fri 12:30"),  # Friday closes early: half an hour before its close
    ("3 trading days", at("10:00"), "Mon 15:30"),  # Thursday, Friday, Monday
    ("1 day", at("10:00", FRI), "Mon 15:30"),
])
def test_a_time_stop_parses_clock_times_durations_and_trading_days(text, now, due):
    parsed = parse(text, now, Calendar())
    assert et(parsed["due_at"]) == due


def test_the_preview_says_when_in_words():
    assert parse("out by 15:30", at("10:00"), Calendar())["when"] == "today 15:30 ET"
    assert parse("2 days", at("10:00"), Calendar())["when"] == "Fri Oct 23, 12:30 ET"


@pytest.mark.parametrize("text", ["when it feels wrong", "", "0 days", "out by 18:00", "45 days", "8h", "25:00",
                                  "trail 1.5 hours", "10 minutes before the close", "out if 5m closes under 92"])
def test_unparseable_time_stops_stay_a_note(text):
    parsed = parse(text, at("10:00"), Calendar())
    assert parsed["due_at"] is None and parsed["reason"]


def test_a_length_needs_an_open_session_today():
    assert parse("45m", at("16:10"), Calendar())["due_at"] is None
    assert parse("45m", at("10:00", date(2026, 10, 24)), Calendar())["due_at"] is None  # a Saturday


def test_a_note_schedules_nothing(engine):
    with pytest.raises(ValueError):
        stop(engine, "when it feels wrong")
    assert stops(engine) == []


# ------------------------------------------------------------------ the time stop

def test_off_by_default(monkeypatch):
    assert plan_time_stops.enabled() is False
    monkeypatch.setenv("PLAN_TIME_STOPS_ENABLED", "true")
    assert plan_time_stops.enabled() is True


def test_it_pings_once_when_a_position_opened_after_the_plan_is_still_open(engine, phone):
    stop(engine, "out by 15:30", planned="10:00")
    buy(engine, "10:05")
    clock = Clock(at("15:29"))
    runner = PlanTimeStops(engine, Calendar(), clock=clock)
    runner.run()
    runner.deliver()
    assert phone == [] and stops(engine)[0].delivery == "scheduled"
    clock.now = at("15:30")
    for _ in range(3):
        runner.run()
        runner.deliver()
    with Session(engine) as db:
        trade_id = db.exec(select(Trade.id)).one()
    [(title, body, kw)] = phone
    assert (title, body) == ("NBIS time stop", "NBIS time stop: you planned to be out by 15:30.")
    assert kw["path"] == f"/trades/{trade_id}" and kw["direct_click"] is True
    [row] = stops(engine)
    assert (row.delivery, row.trade_id) == ("sent", trade_id)


def test_no_entry_after_the_plan_means_nothing_is_sent(engine, phone):
    buy(engine, "09:45")  # opened before the plan
    buy(engine, "10:05", ticker="CRWV")  # another symbol
    buy(engine, "10:06", account=WEBULL)  # Webull is dormant
    stop(engine, "out by 15:30", planned="10:00")
    runner = PlanTimeStops(engine, Calendar(), clock=Clock(at("15:30")))
    runner.run()
    runner.deliver()
    assert phone == []
    [row] = stops(engine)
    assert row.delivery == "skipped" and "No open NBIS position opened after the plan" in row.last_error


def test_a_position_already_closed_is_not_pinged(engine, phone):
    stop(engine, "out by 15:30", planned="10:00")
    buy(engine, "10:05")
    sell(engine, "11:00")
    runner = PlanTimeStops(engine, Calendar(), clock=Clock(at("15:30")))
    runner.run()
    runner.deliver()
    assert phone == [] and stops(engine)[0].delivery == "skipped"


def test_a_time_stop_judged_late_expires_instead_of_sending(engine, phone):
    stop(engine, "out by 15:30", planned="10:00")
    buy(engine, "10:05")
    runner = PlanTimeStops(engine, Calendar(), clock=Clock(at("15:46")))  # the server was down at 15:30
    runner.run()
    runner.deliver()
    assert phone == [] and stops(engine)[0].delivery == "expired"


def test_an_interrupted_send_is_never_resent(engine, monkeypatch):
    monkeypatch.setenv("NTFY_URL", "https://ntfy.example/topic")
    calls = []

    def timeout(title, body, **kw):
        calls.append(title)
        raise ntfy.NtfyError("timed out") from httpx.ReadTimeout("slow")

    monkeypatch.setattr(ntfy, "publish", timeout)
    stop(engine, "out by 15:30", planned="10:00")
    buy(engine, "10:05")
    clock = Clock(at("15:30"))
    runner = PlanTimeStops(engine, Calendar(), clock=clock)
    runner.run()
    runner.deliver()
    clock.now = at("15:32")
    runner.deliver()
    assert calls == ["NBIS time stop"] and stops(engine)[0].delivery == "unknown"


def test_the_monitor_runs_time_stops_on_its_loop(engine):
    class Fake:
        calls = []

        def run(self):
            self.calls.append("run")

        def deliver(self):
            self.calls.append("deliver")

    fake = Fake()
    asyncio.run(LevelAlertMonitor(engine, None, time_stops=fake).run_once())
    assert fake.calls == ["run", "deliver"]


# ------------------------------------------------------------------ routes

@pytest.fixture
def lab(engine, monkeypatch):
    monkeypatch.setattr(time_stop_routes.copilot, "settings", lambda: SimpleNamespace(enabled=True))
    monkeypatch.setattr(time_stop_routes, "_calendar", Calendar)
    monkeypatch.setattr(time_stop_routes.time, "time", lambda: at("10:00"))
    app = FastAPI()
    app.include_router(time_stop_routes.router, prefix="/copilot")

    def session():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_session] = session
    with TestClient(app) as client:
        yield client


def test_routes_preview_save_once_and_list_an_investigations_time_stops(lab):
    assert lab.get("/copilot/time-stops/preview", params={"text": "out by 15:30"}).json() == {
        "due_at": int(at("15:30")), "when": "today 15:30 ET", "enabled": False}
    note = lab.get("/copilot/time-stops/preview", params={"text": "when it feels wrong"}).json()
    assert note["due_at"] is None and note["reason"]
    body = {"client_id": "card-123456", "investigation_id": INV, "symbol": "NBIS", "text": "out by 15:30"}
    first = lab.post("/copilot/time-stops", json=body)
    again = lab.post("/copilot/time-stops", json=body)  # a retried Confirm
    assert first.status_code == again.status_code == 201
    assert again.json()["time_stops"] == first.json()["time_stops"] and len(first.json()["time_stops"]) == 1
    [row] = lab.get("/copilot/time-stops", params={"investigation": INV}).json()["time_stops"]
    assert (row["symbol"], row["text"], row["delivery"], row["due_at"]) == ("NBIS", "out by 15:30", "scheduled", int(at("15:30")))
    assert lab.post("/copilot/time-stops", json={**body, "client_id": "card-999999", "text": "soon"}).status_code == 422
    assert lab.post("/copilot/time-stops", json={**body, "client_id": "card-999999", "investigation_id": "../x"}).status_code == 422


def test_routes_refuse_while_the_lab_is_off(lab, monkeypatch):
    monkeypatch.setattr(time_stop_routes.copilot, "settings", lambda: SimpleNamespace(enabled=False))
    assert lab.get("/copilot/time-stops", params={"investigation": INV}).status_code == 503
