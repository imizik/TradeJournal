"""Main chat's Rate yesterday card (GET /copilot/desk/to-rate): the position alerts, alerted Radar events and copilot
answers since the previous trading session that still wait on the owner's rating, newest first, each with the ids its
rating route takes. Owner-only, refused while the lab is off, read-only. No network."""

from datetime import UTC, datetime, timedelta
import json
from types import SimpleNamespace

from sqlmodel import Session

from app.engine.radar_store import RadarStore
from app.models import CopilotInvestigation, CopilotTurn, RadarAlert
from app.routers import copilot as copilot_routes, copilot_desk, position_alerts, radar
from tests.test_browser_access import boundary, signin  # noqa: F401  (the shared access fixture)
from tests.test_copilot_desk import desk  # noqa: F401  (the desk app over the shared fixtures)
from tests.test_copilot_desk_session import sent
from tests.test_copilot_plans import T0, engine, quotes  # noqa: F401  (fixtures)
from tests.test_today import RADAR_EVENT, buy, clock, marks  # noqa: F401  (fixtures)

at = lambda minutes: int((T0 + timedelta(minutes=minutes)).replace(tzinfo=UTC).timestamp())  # noqa: E731  (T0 is Wed 10:00 New York)
# The clock reads Wed Oct 21 14:49 New York; the previous session is Tue Oct 20, from 04:00 UTC (T0 - 34 hours).
TUESDAY_START = -34 * 60


def read(desk):  # noqa: F811
    response = desk.get("/copilot/desk/to-rate")
    assert response.status_code == 200, response.text
    return response.json()


def radar_on(tmp_path, monkeypatch) -> RadarStore:
    path = tmp_path / "radar.sqlite"
    monkeypatch.setenv("RADAR_ENABLED", "true")
    monkeypatch.setenv("RADAR_STORE", str(path))
    return RadarStore(path)


def hit(store, event_id, session, seen, *, delivery="sent", kind="relative_to_sector", version="radar-rules-v0", db=None):
    store.append_event({**RADAR_EVENT, "event_id": event_id, "session_date": session, "first_seen_at": seen, "kind": kind,
                        "rule_version": version})
    if delivery:
        db.add(RadarAlert(event_id=event_id, session_date=session, rule_version=version, kind=kind, subject="MU", title="Radar: MU",
                          body="b", first_seen_at=datetime.fromisoformat(seen.replace("Z", "")), delivery=delivery))


def conversation(db, title, exchanges, *, created=T0):
    """A saved conversation: each exchange is (question, minutes after T0 its turn started or None, rating, backend)."""
    transcript = []
    for question, minute, rating, backend in exchanges:
        answer = {"role": "assistant", "content": f"About {question}"}
        if minute is not None:
            turn = CopilotTurn(started_at=T0 + timedelta(minutes=minute), backend=backend, billing="api")
            db.add(turn)
            answer["metrics"] = {"turn_id": str(turn.id)}
        if rating:
            answer["rating"] = rating
        transcript += [{"role": "user", "content": question}, answer]
    row = CopilotInvestigation(title=title, transcript_json=json.dumps(transcript), evidence_json="[]", created_at=created, updated_at=T0)
    db.add(row)
    return str(row.id)


def test_what_waits_since_the_previous_session_newest_first_with_its_route_ids(desk, engine, tmp_path, monkeypatch):  # noqa: F811
    nbis, apld = buy(engine, 500), buy(engine, 501, "APLD")
    store = radar_on(tmp_path, monkeypatch)
    with Session(engine) as db:
        giveback = sent(db, "gmail:500", "giveback", 31)
        sent(db, "gmail:500", "hold_hour", 60, answer="already_aware")  # answered: off the card
        expiry = sent(db, "gmail:501", "expiry_final", -1200, delivery="unknown")  # Tuesday, maybe reached the phone
        sent(db, "gmail:501", "expiry_first", TUESDAY_START - 60)  # Monday evening: before the previous session
        sent(db, "gmail:500", "giveback", 20, delivery="expired", generation=1)  # never sent
        sent(db, "gmail:999", "giveback", 40)  # its position left the journal: nothing to save it against
        hit(store, "today-1", "2026-10-21", "2026-10-21T15:12:04.000Z", db=db)
        hit(store, "tuesday-1", "2026-10-20", "2026-10-20T16:00:00.000Z", kind="group_move", db=db)
        hit(store, "tuesday-rated", "2026-10-20", "2026-10-20T17:00:00.000Z", db=db)
        hit(store, "feed-only", "2026-10-21", "2026-10-21T15:30:00.000Z", delivery=None, db=db)  # never pinged
        hit(store, "held", "2026-10-21", "2026-10-21T15:40:00.000Z", delivery="held", db=db)  # the policy kept it off the phone
        hit(store, "monday-1", "2026-10-19", "2026-10-19T16:00:00.000Z", db=db)  # before the previous session
        hit(store, "dip-1", "2026-10-21", "2026-10-21T15:50:00.000Z", version="radar-dip-v1", kind="dip_turn", db=db)
        store.append_feedback("tuesday-rated", "useful", "2026-10-20T20:00:00Z")
        main = conversation(db, "Main chat · 2026-10-21", [
            ("Should I trim APLD into this strength before the close or let it run?", 45, None, "anthropic"),
            ("And NBIS?", 50, "helped", "anthropic"),  # rated: off the card
            ("Simulated", 55, None, "fake"),  # a simulated turn is not an answer the scorecard counts
        ])
        older = conversation(db, "APLD calls", [("What changed on APLD?", -1000, None, "anthropic"),
                                                ("Last week?", TUESDAY_START - 600, None, "anthropic")], created=T0 - timedelta(days=8))
        conversation(db, "Morning brief 2026-10-21", [("Prep", -30, None, "anthropic")])  # automatic: not asked about
        db.commit()

    body = read(desk)
    assert (body["day"], body["since"], body["count"]) == ("2026-10-21", "2026-10-20", 6)
    assert body["sections"] == {"alerts": "ok", "radar": "ok", "answers": "ok"}
    assert [i["key"] for i in body["items"]] == [
        "radar:today-1", f"answer:{main}:1", f"alert:{giveback}", f"answer:{older}:1", f"alert:{expiry}", "radar:tuesday-1"]
    radar_hit, first, alert, older_answer, older_alert, group = body["items"]
    assert first == {"key": f"answer:{main}:1", "type": "answer", "investigation_id": main, "index": 1,
                     "label": "Should I trim APLD into this strength before the close or…", "detail": "Main chat",
                     "at": at(45), "answers": ["helped", "didnt"]}
    assert alert == {"key": f"alert:{giveback}", "type": "alert", "id": giveback, "trade_id": nbis, "label": "NBIS 10/23/26 100C",
                     "detail": "Give-back", "at": at(31), "answers": ["prompted_review", "already_aware", "too_late", "not_useful"]}
    assert (older_alert["trade_id"], older_alert["label"], older_alert["detail"]) == (apld, "APLD 10/23/26 100C", "30 minutes left")
    assert radar_hit == {"key": "radar:today-1", "type": "radar", "event_id": "today-1", "label": "MU", "detail": RADAR_EVENT["summary"],
                         "at": int(datetime(2026, 10, 21, 15, 12, 4, tzinfo=UTC).timestamp()),
                         "answers": ["useful", "already_knew", "too_late", "irrelevant"]}
    assert group["label"] == RADAR_EVENT["group"]
    assert (older_answer["label"], older_answer["detail"]) == ("What changed on APLD?", "APLD calls")


def test_each_rating_route_takes_its_item_off_the_card(desk, engine, tmp_path, monkeypatch):  # noqa: F811
    nbis = buy(engine, 500)
    store = radar_on(tmp_path, monkeypatch)
    with Session(engine) as db:
        alert = sent(db, "gmail:500", "giveback", 31)
        hit(store, "today-1", "2026-10-21", "2026-10-21T15:12:04.000Z", db=db)
        main = conversation(db, "Main chat · 2026-10-21", [("Trim APLD?", 45, None, "anthropic")])
        db.commit()
    assert read(desk)["count"] == 3
    desk.app.include_router(position_alerts.router, prefix="/trades")
    desk.app.include_router(radar.router, prefix="/radar")
    desk.app.include_router(copilot_routes.router, prefix="/copilot")
    assert desk.put(f"/trades/{nbis}/phone-alerts/{alert}/feedback",
                    json={"rating": "prompted_review", "reason": None, "base_version": 0}).status_code == 200
    assert desk.post("/radar/events/today-1/feedback", json={"rating": "too_late"}).status_code == 200
    assert desk.put(f"/copilot/investigations/{main}/messages/1/rating", json={"rating": "didnt"}).status_code == 200
    assert read(desk) == {"day": "2026-10-21", "since": "2026-10-20", "count": 0, "items": [],
                          "sections": {"alerts": "ok", "radar": "ok", "answers": "ok"}}


def test_after_a_weekend_the_previous_session_is_friday_and_a_holiday_is_skipped(desk, clock, monkeypatch):  # noqa: F811
    clock["t"] = datetime(2026, 10, 26, 13, 0, tzinfo=UTC).timestamp()  # Monday 09:00 New York
    monkeypatch.setattr(copilot_desk, "_hours", lambda day: {"status": "open", "open": 570, "close": 960} if day.weekday() < 5 else {"status": "closed"})
    assert read(desk)["since"] == "2026-10-23"
    monkeypatch.setattr(copilot_desk, "_hours", lambda day: {"status": "closed"} if day.weekday() >= 4 else {"status": "open", "open": 570, "close": 960})
    assert read(desk)["since"] == "2026-10-22"  # Friday closed: Thursday was the last session
    monkeypatch.setattr(copilot_desk, "_hours", lambda day: None)  # no calendar: the clock's weekdays
    assert read(desk)["since"] == "2026-10-23"


def test_the_list_is_capped_and_one_failing_source_leaves_the_rest(desk, engine, monkeypatch):  # noqa: F811
    buy(engine, 500)
    with Session(engine) as db:
        for minute in (10, 20, 30):
            sent(db, "gmail:500", "giveback", minute, generation=minute)
        db.commit()
    monkeypatch.setattr(copilot_desk, "TO_RATE_ROWS", 2)
    monkeypatch.setattr(copilot_desk, "_answers_to_rate", lambda db, start: 1 / 0)
    body = read(desk)
    assert (body["count"], [i["at"] for i in body["items"]]) == (3, [at(30), at(20)])
    assert body["sections"] == {"alerts": "ok", "radar": "off", "answers": "unavailable"}


def test_refused_while_the_lab_is_off(desk, monkeypatch):  # noqa: F811
    monkeypatch.setattr(copilot_desk.copilot, "settings", lambda: SimpleNamespace(enabled=False))
    assert desk.get("/copilot/desk/to-rate").status_code == 503


def test_assistant_sessions_cannot_reach_it(boundary, monkeypatch):  # noqa: F811
    boundary.patch.setenv("COPILOT_ENABLED", "true")
    monkeypatch.setattr(copilot_desk, "_hours", lambda day: None)
    owner = boundary.owner.get("/copilot/desk/to-rate")
    assert owner.status_code == 200, owner.text
    assert signin(boundary).status_code == 200
    assert boundary.public.get("/copilot/desk/to-rate").status_code == 403


def test_nothing_waiting_reads_empty(desk):  # noqa: F811
    body = read(desk)
    assert (body["count"], body["items"], body["sections"]["radar"]) == (0, [], "off")
