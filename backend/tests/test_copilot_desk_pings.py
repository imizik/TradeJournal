"""Now's "How the pings did" card (GET /copilot/desk/pings): each position alert and each alerted Radar hit or setup card
since the previous trading session, with what followed, and nothing to answer. Read-only, refused while the lab is off.
No network."""

from types import SimpleNamespace

from sqlmodel import Session

from app.models import RadarSetup
from app.routers import copilot_desk
from tests.test_browser_access import boundary, signin  # noqa: F401  (the shared access fixture)
from tests.test_copilot_desk import desk  # noqa: F401  (the desk app over the shared fixtures)
from tests.test_copilot_desk_session import sent
from tests.test_copilot_desk_to_rate import TUESDAY_START, hit, radar_on
from tests.test_copilot_plans import engine, quotes  # noqa: F401  (fixtures)
from tests.test_today import buy, clock, marks  # noqa: F401  (fixtures)


def read(desk):  # noqa: F811
    response = desk.get("/copilot/desk/pings")
    assert response.status_code == 200, response.text
    return response.json()


def test_each_ping_since_the_previous_session_with_what_followed(desk, engine, tmp_path, monkeypatch):  # noqa: F811
    buy(engine, 500)
    store = radar_on(tmp_path, monkeypatch)
    with Session(engine) as db:
        sent(db, "gmail:500", "giveback", 31)
        sent(db, "gmail:500", "hold_hour", 60, answer="already_aware")  # answered or not, it is shown
        sent(db, "gmail:500", "expiry_first", TUESDAY_START - 60)  # Monday evening: before the previous session
        sent(db, "gmail:500", "giveback", 20, delivery="expired", generation=1)  # never sent
        hit(store, "today-1", "2026-10-21", "2026-10-21T15:12:04.000Z", db=db)
        hit(store, "feed-only", "2026-10-21", "2026-10-21T15:30:00.000Z", delivery=None, db=db)  # never pinged
        hit(store, "monday-1", "2026-10-19", "2026-10-19T16:00:00.000Z", db=db)  # before the previous session
        hit(store, "dip-1", "2026-10-21", "2026-10-21T15:50:00.000Z", version="radar-dip-v1", kind="dip_turn", db=db)
        db.add(RadarSetup(event_id="dip-1", session_date="2026-10-21", rule_version="radar-dip-v1", kind="dip_turn", symbol="MU",
                          direction="up", entry=100, invalidation=98, paper_state="closed", paper_pnl=-42.5,
                          paper_exit_reason="invalidation"))
        db.commit()

    body = read(desk)
    assert (body["day"], body["since"]) == ("2026-10-21", "2026-10-20")
    assert body["alerts"]["state"] == "ok"
    assert [r["kind"] for r in body["alerts"]["rows"]] == ["hold_hour", "giveback"]  # newest first
    assert body["alerts"]["rows"][0]["outcome"] == {"state": "not_measured", "why": body["alerts"]["rows"][0]["outcome"]["why"]}
    assert body["radar"]["state"] == "ok"
    rows = {r["event_id"]: r for r in body["radar"]["rows"]}
    assert set(rows) == {"today-1", "dip-1"}
    assert rows["today-1"]["setup"] is False and rows["today-1"]["paper"] is None
    assert rows["today-1"]["after"]["close_pct"] is None and rows["today-1"]["after"]["why"]  # not measured, and says why
    assert rows["dip-1"]["kind_label"] == "Dip turning up"
    assert rows["dip-1"]["paper"] == {"state": "closed", "pnl": -42.5, "exit_reason": "invalidation", "note": None}
    # Nothing to answer: no rating, feedback or route ids beyond the Radar event's own.
    assert not any(key in row for row in body["alerts"]["rows"] for key in ("feedback", "trade_id", "id"))


def test_radar_off_leaves_the_alerts(desk, engine):  # noqa: F811
    buy(engine, 500)
    with Session(engine) as db:
        sent(db, "gmail:500", "giveback", 31)
        db.commit()
    body = read(desk)
    assert body["radar"]["state"] == "off" and body["radar"]["rows"] == []
    assert len(body["alerts"]["rows"]) == 1


def test_refused_while_the_lab_is_off(desk, monkeypatch):  # noqa: F811
    monkeypatch.setattr(copilot_desk.copilot, "settings", lambda: SimpleNamespace(enabled=False))
    assert desk.get("/copilot/desk/pings").status_code == 503
