"""Radar PR 3-4: the owner-only feed API over a seeded Radar file."""
from datetime import UTC, datetime
import json
from pathlib import Path
import sqlite3

from fastapi.testclient import TestClient
import pytest

from app.engine.chart_math import ET
from app.engine.radar_store import RadarStore, load_universe
from app.main import app
from app.routers import radar
from tests.test_browser_access import boundary, signin  # noqa: F401  (the shared access fixture)

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "radar" / "sample_event.json").read_text())
EVENT_ID = FIXTURE["event"]["event_id"]
SESSION = "2026-10-20"


def _at(hh_mm: str, day=SESSION) -> float:
    return datetime.fromisoformat(f"{day}T{hh_mm}:00").replace(tzinfo=ET).timestamp()


def _pass(minute: str, status="ok"):
    started = datetime.fromtimestamp(_at(minute), UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    return {"session_date": SESSION, "started_at": started, "finished_at": started, "universe_version": "radar-universe-v1",
            "status": status, "symbols_requested": 169, "symbols_returned": 168, "unmatched": ["ZZZ"],
            "requests_used": 4, "error": None, "skip_reason": None}


@pytest.fixture
def api(tmp_path, monkeypatch):
    path = tmp_path / "radar.sqlite"
    monkeypatch.setenv("RADAR_ENABLED", "true")
    monkeypatch.setenv("RADAR_STORE", str(path))
    monkeypatch.setattr(radar, "_regular_window", lambda day: (570, 960))
    clock = {"now": _at("10:42")}
    monkeypatch.setattr(radar, "_now", lambda: clock["now"])
    store = RadarStore(path)
    with TestClient(app) as client:
        yield type("Api", (), {"client": client, "store": store, "clock": clock, "path": path})


def _seed(api, passes=("10:40", "10:41", "10:42"), revision=True):
    for minute in passes:
        api.store.append_pass(_pass(minute))
    api.store.append_event(FIXTURE["event"])
    if revision:
        api.store.append_revision(FIXTURE["revisions"][0])


def test_off_when_unset_or_unreadable(tmp_path, monkeypatch):
    with TestClient(app) as client:
        monkeypatch.delenv("RADAR_ENABLED", raising=False)
        monkeypatch.delenv("RADAR_STORE", raising=False)
        body = client.get("/radar/feed").json()
        assert body["state"] == "off" and body["events"] == [] and body["reason"]
        monkeypatch.setenv("RADAR_ENABLED", "true")
        assert client.get("/radar/feed").json()["state"] == "off"  # no store path
        foreign = tmp_path / "foreign.sqlite"
        sqlite3.connect(foreign).execute("CREATE TABLE fills(id)").connection.commit()
        monkeypatch.setenv("RADAR_STORE", str(foreign))
        response = client.get("/radar/feed")
        assert response.status_code == 200 and response.json()["state"] == "off"
        assert client.post("/radar/visits").status_code == 503


def test_no_data_recording_and_stale(api):
    assert api.client.get("/radar/feed").json()["state"] == "no_data"
    _seed(api, revision=False)
    body = api.client.get(f"/radar/feed?session={SESSION}").json()
    assert body["state"] == "recording"
    assert body["coverage"]["passes_recorded"] == 3 and body["coverage"]["passes_expected"] == 72
    assert body["coverage"]["symbols_missing"] == ["ZZZ"] and body["coverage"]["symbols_tracked"] == len(load_universe()["symbols"])
    api.clock["now"] = _at("10:46")
    assert api.client.get("/radar/feed").json()["state"] == "stale"
    api.clock["now"] = _at("17:00")  # after the close nothing is stale
    assert api.client.get("/radar/feed").json()["state"] == "recording"


def test_feed_serves_event_with_latest_status_and_default_session(api):
    _seed(api)
    body = api.client.get("/radar/feed").json()
    assert body["session"] == SESSION
    [event] = body["events"]
    assert event["event_id"] == EVENT_ID and event["latest_status"] == "extended" and event["rating"] is None
    assert event["summary"] == FIXTURE["event"]["summary"]
    assert api.client.get("/radar/feed?session=2026-10-19").json()["events"] == []
    assert api.client.get("/radar/feed?session=not-a-date").status_code == 422


def test_since_last_visit(api):
    _seed(api)
    assert api.client.get("/radar/feed").json()["since_last_visit"] == [EVENT_ID]  # never visited
    api.clock["now"] = _at("17:00")
    first = api.client.post("/radar/visits").json()
    assert first["previous_visit_at"] is None
    assert api.client.get("/radar/feed").json()["since_last_visit"] == []
    assert api.client.get("/radar/feed", params={"since": "2026-10-20T00:00:00Z"}).json()["since_last_visit"] == [EVENT_ID]
    second = api.client.post("/radar/visits").json()
    assert second["previous_visit_at"] == first["visited_at"]


def test_bad_since_is_rejected_and_a_busy_file_is_not_a_500(api):
    _seed(api)
    assert api.client.get("/radar/feed?since=garbage").status_code == 422
    assert api.client.post("/radar/visits", json={"visited_at": "garbage"}).status_code == 422
    with sqlite3.connect(api.path) as db:
        db.execute("INSERT INTO pass VALUES(NULL,'2026-10-20','a','b','v','ok',1,1,'not json',1,NULL,NULL)")
    body = api.client.get("/radar/feed")
    assert body.status_code == 200 and body.json()["state"] == "off"


def test_visit_can_use_the_time_the_feed_was_read(api):
    _seed(api)
    feed = api.client.get("/radar/feed").json()
    api.clock["now"] += 60
    visit = api.client.post("/radar/visits", json={"visited_at": feed["generated_at"]}).json()
    assert visit["visited_at"] == feed["generated_at"]
    future = api.client.post("/radar/visits", json={"visited_at": "2099-01-01T00:00:00Z"}).json()
    assert future["visited_at"] <= radar._iso(api.clock["now"])


def test_detail_returns_the_saved_original_after_a_revision(api):
    _seed(api, revision=False)
    before = api.client.get(f"/radar/events/{EVENT_ID}").json()
    assert before["event"] == FIXTURE["event"] and before["revisions"] == []
    api.store.append_revision(FIXTURE["revisions"][0])
    after = api.client.get(f"/radar/events/{EVENT_ID}").json()
    assert after["event"] == FIXTURE["event"]  # not replaced by the revision's later numbers
    assert after["revisions"] == FIXTURE["revisions"]
    assert api.client.get("/radar/events/nope").status_code == 404


def test_feedback_validates_and_latest_wins(api):
    _seed(api)
    assert api.client.post(f"/radar/events/{EVENT_ID}/feedback", json={"rating": "great"}).status_code == 422
    assert api.client.post("/radar/events/nope/feedback", json={"rating": "useful"}).status_code == 404
    assert api.client.post(f"/radar/events/{EVENT_ID}/feedback", json={"rating": "useful"}).status_code == 200
    assert api.client.post(f"/radar/events/{EVENT_ID}/feedback", json={"rating": "too_late"}).status_code == 200
    assert api.client.get(f"/radar/events/{EVENT_ID}").json()["rating"] == "too_late"
    assert api.client.get("/radar/feed").json()["events"][0]["rating"] == "too_late"
    api.store.append_visit("2026-10-20T20:00:00.000Z")
    with sqlite3.connect(api.path) as db:
        assert db.execute("SELECT count(*) FROM feedback").fetchone()[0] == 2
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("DELETE FROM feedback")
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("DELETE FROM visit")


def test_existing_file_without_new_tables_still_opens(tmp_path):
    path = tmp_path / "old.sqlite"
    RadarStore(path)
    with sqlite3.connect(path) as db:
        for trigger in ("visit_no_update", "visit_no_delete", "feedback_no_update", "feedback_no_delete"):
            db.execute(f"DROP TRIGGER {trigger}")
        db.execute("DROP TABLE visit")
        db.execute("DROP TABLE feedback")
    store = RadarStore(path)
    store.append_visit("2026-10-21T14:00:00.000Z")
    assert store.last_visit() == "2026-10-21T14:00:00.000Z"


def test_owner_only(boundary, tmp_path):  # noqa: F811
    store = RadarStore(tmp_path / "radar.sqlite")
    store.append_event(FIXTURE["event"])
    boundary.patch.setenv("RADAR_ENABLED", "true")
    boundary.patch.setenv("RADAR_STORE", str(tmp_path / "radar.sqlite"))
    assert boundary.owner.get("/radar/feed").status_code == 200
    assert boundary.owner.get(f"/radar/events/{EVENT_ID}").status_code == 200
    assert boundary.owner.post("/radar/visits").status_code == 200
    assert boundary.owner.post(f"/radar/events/{EVENT_ID}/feedback", json={"rating": "useful"}, headers={"x-tj-csrf": "wrong"}).status_code == 403
    assert signin(boundary).status_code == 200
    for method, path in [("GET", "/radar/feed"), ("GET", f"/radar/events/{EVENT_ID}"), ("POST", "/radar/visits"),
                         ("POST", f"/radar/events/{EVENT_ID}/feedback")]:
        assert boundary.public.request(method, path, json={"rating": "useful"} if method == "POST" else None).status_code == 403
