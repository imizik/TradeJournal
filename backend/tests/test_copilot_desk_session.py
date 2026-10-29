"""The Briefing's session timeline (GET /copilot/desk/session): today's regular session, its fills, phone pings, Radar
events and logged decisions, the time stops still ahead, the pings against the daily cap, the prep and SPY/QQQ/VIX, composed
from readers that already exist. Owner-only, refused while the lab is off, read-only. No network."""

from datetime import UTC, datetime, timedelta
import json
from types import SimpleNamespace
import uuid

from sqlmodel import Session, select

from app.engine import day_replay
from app.engine.chart_feed import chart_feed
from app.engine.radar_store import RadarStore
from app.models import DayJournalEntry, PhonePing, PositionAlert, PositionAlertFeedback, PremarketPrep
from app.routers import copilot_desk, position_alerts, radar
from tests.test_browser_access import boundary, signin  # noqa: F401  (the shared access fixture)
from tests.test_copilot_desk import desk  # noqa: F401  (the desk app over the shared fixtures)
from tests.test_copilot_plans import APLD, NBIS, T0, WED, engine, quotes, time_stop  # noqa: F401  (fixtures)
from tests.test_today import RADAR_EVENT, ROTH, UUID_RE, buy, clock, marks  # noqa: F401  (fixtures)

OPEN = int(datetime(2026, 10, 21, 13, 30, tzinfo=UTC).timestamp())  # 9:30 New York
CLOSE = int(datetime(2026, 10, 21, 20, 0, tzinfo=UTC).timestamp())  # 16:00
at = lambda minutes: int((T0 + timedelta(minutes=minutes)).replace(tzinfo=UTC).timestamp())  # noqa: E731  (T0 is 10:00 New York)


def read(desk):  # noqa: F811
    response = desk.get("/copilot/desk/session")
    assert response.status_code == 200, response.text
    return response.json()


def ping(db, kind, minute, decision="sent", symbol="NBIS"):
    db.add(PhonePing(sender="position_alerts", source_id=f"{kind}-{minute}", kind=kind, rank=2, symbol=symbol, decision=decision,
                     title="t", body="b", decided_at=T0 + timedelta(minutes=minute)))


def test_a_quiet_day_is_the_session_and_the_indices(desk, quotes):  # noqa: F811
    quotes["rows"] += [{"symbol": "SPY", "last": 580.1, "change_percentage": 0.42}, {"symbol": "QQQ", "last": 500.2, "change_percentage": -0.31},
                       {"symbol": "VIX", "last": 16.9, "change_percentage": 3.1}]
    body = read(desk)
    assert (body["phase"], body["open"], body["close"], body["day"]) == ("regular", OPEN, CLOSE, "2026-10-21")
    assert body["now"] == at(289)  # 14:49
    assert (body["events"], body["time_stops"], body["prep"]) == ([], [], None)
    assert body["pings"] == {"sent": 0, "held": 0, "cap": 12}
    assert body["indices"] == [{"symbol": "SPY", "last": 580.1, "change_pct": 0.42}, {"symbol": "QQQ", "last": 500.2, "change_pct": -0.31},
                               {"symbol": "VIX", "last": 16.9, "change_pct": 3.1}]
    assert body["sections"]["radar"] == "off" and set(body["sections"].values()) <= {"ok", "off"}


def test_the_days_events_in_time_order_and_the_time_stops_ahead(desk, engine, tmp_path, monkeypatch):  # noqa: F811
    path = tmp_path / "radar.sqlite"
    monkeypatch.setenv("RADAR_ENABLED", "true")
    monkeypatch.setenv("RADAR_STORE", str(path))
    store = RadarStore(path)
    store.append_event(RADAR_EVENT)  # yesterday's: not on today's strip
    store.append_event({**RADAR_EVENT, "event_id": "today-1", "session_date": "2026-10-21", "first_seen_at": "2026-10-21T14:12:04.000Z"})
    buy(engine, 500, minute=5)  # 10:05 New York, the journal's wall clock
    time_stop(engine, NBIS, "NBIS", due_minute=330)  # 15:30, still scheduled
    time_stop(engine, APLD, "APLD", client_id="card-2", due_minute=60, delivery="skipped")  # judged already
    with Session(engine) as db:
        ping(db, "giveback", 31)
        ping(db, "time_stop", 40, decision="over_cap")
        db.add(DayJournalEntry(operation_id="d1", day=WED, kind="decision", symbol="NBIS", text="Holding. Give-back fired at 10:31; plan says hold.",
                               created_at=T0 + timedelta(minutes=44)))
        db.add(DayJournalEntry(operation_id="d2", day=WED, kind="update", symbol="NBIS", text="not a decision", created_at=T0))
        db.add(PremarketPrep(day=WED, investigation_id=APLD, body="NBIS 100C expires Friday.", delivery="sent",
                             detected_at=T0 - timedelta(minutes=90)))
        db.commit()
    body = read(desk)
    events = [(e["kind"], e["text"]) for e in body["events"]]
    assert [e for e in events if e[0] != "radar"] == [
        ("fill", "Bought NBIS"), ("ping", "Give-back ping · NBIS"), ("decision", "NBIS · Holding")]
    assert body["events"][0]["at"] == day_replay._ny(datetime(2026, 10, 21, 10, 5))
    assert [e["at"] for e in body["events"]] == sorted(e["at"] for e in body["events"])
    [radar] = [e for e in body["events"] if e["kind"] == "radar"]
    assert (radar["symbol"], radar["at"]) == ("MU", at(12) + 4) and radar["text"] == "Radar · MU vs sector"
    assert body["time_stops"] == [{"symbol": "NBIS", "at": at(330), "clock": "15:30"}]
    assert body["pings"] == {"sent": 1, "held": 1, "cap": 12}
    assert body["prep"] == {"at": at(-90), "line": "NBIS 100C expires Friday."}
    with Session(engine) as db:
        assert len(db.exec(select(PhonePing)).all()) == 2  # read-only: no ping written


def test_before_the_open_and_a_closed_day(desk, clock, monkeypatch):  # noqa: F811
    clock["t"] = datetime(2026, 10, 21, 12, 30, tzinfo=UTC).timestamp()  # 8:30 New York
    body = read(desk)
    assert (body["phase"], body["open"], body["close"]) == ("pre", OPEN, CLOSE)
    monkeypatch.setattr(copilot_desk, "_hours", lambda day: {"status": "closed"})
    body = read(desk)
    assert (body["phase"], body["open"], body["close"]) == ("closed", None, None)


def test_one_failing_source_leaves_the_rest(desk, engine, monkeypatch):  # noqa: F811
    buy(engine, 500)

    def broken(*_args, **_kwargs):
        raise RuntimeError("boom")
    monkeypatch.setattr(copilot_desk, "_hours", broken)
    monkeypatch.setattr(chart_feed, "quote_rows", broken)
    body = read(desk)
    assert (body["sections"]["hours"], body["sections"]["indices"], body["sections"]["phase"]) == ("unavailable",) * 3
    assert (body["open"], body["phase"], body["indices"]) == (None, None, [])
    assert [e["kind"] for e in body["events"]] == ["fill"] and body["sections"]["fills"] == "ok"


def test_no_ids_out(desk, engine):  # noqa: F811
    buy(engine, 500)
    time_stop(engine, NBIS, "NBIS")
    text = json.dumps(read(desk))
    assert UUID_RE.findall(text) == [] and "gmail:" not in text and "card-1" not in text


def sent(db, key, kind, minute, delivery="sent", answer=None, generation=0):
    alert = PositionAlert(account_id=ROTH, source_key=key, kind=kind, generation=generation, trade_id=uuid.uuid4(),
                          contract=f"{'APLD' if key == 'gmail:501' else 'NBIS'} 10/23/26 100C", contracts=2, avg_cost=310,
                          delivery=delivery, detected_at=T0 + timedelta(minutes=minute))
    db.add(alert)
    if answer:
        db.flush()
        db.add(PositionAlertFeedback(alert_id=alert.id, rating=answer, version=1, created_at=T0, updated_at=T0))
    return str(alert.id)


def test_what_waits_on_an_answer_counts_as_proof_does(desk, engine, tmp_path, monkeypatch):  # noqa: F811
    nbis, apld = buy(engine, 500), buy(engine, 501, "APLD")
    with Session(engine) as db:
        waiting = sent(db, "gmail:500", "giveback", 31)
        answered = sent(db, "gmail:500", "hold_hour", 60, answer="already_aware")
        older = sent(db, "gmail:501", "expiry_final", -1200, delivery="unknown")
        sent(db, "gmail:501", "expiry_first", -1300, answer="prompted_review")  # answered before today: counted, not listed
        sent(db, "gmail:500", "giveback", 20, delivery="expired", generation=1)  # never sent: outside the proof's scope
        sent(db, "gmail:999", "giveback", -1400)  # its position left the journal: counted, not answerable here
        db.commit()
    path = tmp_path / "radar.sqlite"
    monkeypatch.setenv("RADAR_ENABLED", "true")
    monkeypatch.setenv("RADAR_STORE", str(path))
    store = RadarStore(path)
    version = {"rule_version": "radar-rules-v0"}
    store.append_event({**RADAR_EVENT, "event_id": "old-rules"})  # an earlier rule version: outside the proof's scope
    store.append_event({**RADAR_EVENT, **version, "event_id": "yesterday-rated"})
    store.append_event({**RADAR_EVENT, **version, "event_id": "yesterday-unrated", "first_seen_at": "2026-10-20T16:00:00.000Z"})
    store.append_event({**RADAR_EVENT, **version, "event_id": "today-1", "session_date": "2026-10-21", "first_seen_at": "2026-10-21T14:12:04.000Z"})
    store.append_feedback("yesterday-rated", "useful", "2026-10-20T20:00:00Z")

    body = read(desk)["to_answer"]
    assert body["alerts"]["count"] == 3
    assert [(r["id"], r["trade_id"], r["symbol"], r["kind"], r["today"]) for r in body["alerts"]["rows"]] == [
        (answered, nbis, "NBIS", "hold_hour", True), (waiting, nbis, "NBIS", "giveback", True), (older, apld, "APLD", "expiry_final", False)]
    assert body["alerts"]["rows"][0]["feedback"]["rating"] == "already_aware" and body["alerts"]["rows"][1]["feedback"] is None
    assert body["radar"]["count"] == 2
    assert [(r["event_id"], r["symbol"], r["kind"], r["today"], r["rating"]) for r in body["radar"]["rows"]] == [
        ("today-1", "MU", "vs sector", True, None), ("yesterday-unrated", "MU", "vs sector", False, None)]

    # The same answers move the counts, through the routes the trade page and the Radar feed save with.
    desk.app.include_router(position_alerts.router, prefix="/trades")
    desk.app.include_router(radar.router, prefix="/radar")
    assert desk.put(f"/trades/{nbis}/phone-alerts/{waiting}/feedback", json={"rating": "too_late", "base_version": 0}).status_code == 200
    assert desk.post("/radar/events/today-1/feedback", json={"rating": "too_late"}).status_code == 200
    body = read(desk)["to_answer"]
    assert (body["alerts"]["count"], body["radar"]["count"]) == (2, 1)
    assert body["radar"]["rows"][0]["rating"] == "too_late"


def test_nothing_to_answer_while_radar_is_off(desk):  # noqa: F811
    body = read(desk)
    assert body["to_answer"] == {"alerts": {"count": 0, "rows": []}, "radar": None}
    assert (body["sections"]["alerts_to_answer"], body["sections"]["radar_to_rate"]) == ("ok", "off")


def test_refused_while_the_lab_is_off(desk, monkeypatch):  # noqa: F811
    monkeypatch.setattr(copilot_desk.copilot, "settings", lambda: SimpleNamespace(enabled=False))
    assert desk.get("/copilot/desk/session").status_code == 503


def test_assistant_sessions_cannot_reach_it(boundary, monkeypatch):  # noqa: F811
    boundary.patch.setenv("COPILOT_ENABLED", "true")
    monkeypatch.setattr(chart_feed, "quote_rows", lambda symbols: ([], None, None))
    monkeypatch.setattr(copilot_desk, "_hours", lambda day: None)
    owner = boundary.owner.get("/copilot/desk/session")
    assert owner.status_code == 200, owner.text
    assert signin(boundary).status_code == 200
    assert boundary.public.get("/copilot/desk/session").status_code == 403
