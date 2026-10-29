"""The Copilot desk's thread list (GET /copilot/desk/threads): one grouped list composed from the Today screen's readers,
the Plans board and the open investigations, with one batched quote read. Owner-only, refused while the lab is off,
read-only. No network."""

from datetime import UTC, datetime, timedelta
import json
from types import SimpleNamespace
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlmodel import Session, select

from app.database import get_session
from app.engine import plan_streak
from app.engine.chart_feed import chart_feed
from app.engine.radar_store import RadarStore
from app.models import CopilotInvestigation, DayJournalEntry, PhonePing, PremarketPrep, ThesisWatchTrigger
from app.routers import copilot_desk, radar
from tests.test_browser_access import boundary, signin  # noqa: F401  (the shared access fixture)
from tests.test_copilot_plans import APLD, CRWV, NBIS, T0, WED, alert, engine, quotes  # noqa: F401  (fixtures)
from tests.test_today import RADAR_EVENT, UUID_RE, buy, clock, marks, planned_nbis  # noqa: F401  (fixtures)
from app.engine import quotes as quote_engine


@pytest.fixture
def desk(engine, quotes, marks, clock, monkeypatch):  # noqa: F811
    monkeypatch.delenv("RADAR_ENABLED", raising=False)
    monkeypatch.setattr(copilot_desk.copilot, "settings", lambda: SimpleNamespace(enabled=True))
    monkeypatch.setattr(copilot_desk, "_hours", lambda day: {"status": "open", "open": 570, "close": 960})
    app = FastAPI()
    app.include_router(copilot_desk.router, prefix="/copilot")

    def session():
        with Session(engine) as db:
            yield db
    app.dependency_overrides[get_session] = session
    with TestClient(app) as client:
        yield client


def read(desk):
    response = desk.get("/copilot/desk/threads")
    assert response.status_code == 200, response.text
    return response.json()


def groups(body):
    return {g: [r["key"] for r in body["threads"] if r["group"] == g] for g in ("pinned", "act", "near", "draft", "new", "watch")}


def investigation(engine, inv, symbol, title, *, source="copilot", conclusion=None, status="open"):  # noqa: F811
    with Session(engine) as db:
        db.add(CopilotInvestigation(id=UUID(inv), title=title, symbol=symbol, source=source, conclusion=conclusion, status=status,
                                    transcript_json="[]", evidence_json="[]"))
        db.commit()


def test_a_quiet_day_is_the_two_pinned_rows_and_one_day_line(desk):
    body = read(desk)
    assert groups(body) == {"pinned": ["briefing", "week"], "act": [], "near": [], "draft": [], "new": [], "watch": []}
    assert body["day"] == {"phase": "regular", "need_you": 0, "streak": None}  # 14:49 New York, a trading day
    assert set(body["sections"].values()) <= {"ok", "off"} and body["sections"]["radar"] == "off"
    briefing = body["threads"][0]
    assert (briefing["title"], briefing["status"]["text"]) == ("Briefing", "What matters right now? One turn across everything")


def test_a_position_near_its_invalidation_is_act_now_with_its_pnl_and_the_underlyings_meter(desk, engine, quotes):  # noqa: F811
    trade = planned_nbis(engine)
    alert(engine, NBIS, "NBIS", "entry", 95.9, state="fired", fired=T0 + timedelta(minutes=10))
    body = read(desk)
    [row] = [r for r in body["threads"] if r["group"] == "watch"]  # 1.81% away: watching, no meter
    assert row["key"] == f"trade:{trade}" and row["meter"] is None
    assert row["status"]["text"] == "Invalidation 92.30 (NBIS) · 1.8% away"  # the option's level is on the underlying
    quotes["rows"][0]["last"] = 93.2  # 0.97% from 92.30
    body = read(desk)
    [row] = [r for r in body["threads"] if r["group"] == "act"]
    assert (row["symbol"], row["title"], row["instrument"]) == ("NBIS", "NBIS 10/23/26 100C", "10/23/26 100C")
    assert row["status"] == {"text": "1.0% from invalidation 92.30", "tone": "attention"}
    assert row["value"] == {"text": "+$180.00", "tone": "gain"}  # 2 contracts, 3.10 → 4.00: the option's P&L, not NBIS
    assert (row["investigation_id"], row["trade_id"], row["path"]) == (NBIS, trade, None)
    # 0 at 92.30, the entry 95.90 at 80, NBIS 93.20 a quarter of the way: 0.9 / 3.6 = 0.25 of the risk
    assert row["meter"] == {"last": 20.0, "entry": 80.0, "tone": "attention"}
    assert body["day"]["need_you"] == 1
    assert groups(body)["near"] == [] and groups(body)["watch"] == []  # the plan shows once, on its position
    assert quotes["asked"][-1] == ["NBIS"] and len(quotes["asked"]) == 2  # one batched read per request


def test_a_decision_logged_today_moves_the_row_to_watching(desk, engine, quotes):  # noqa: F811
    trade = planned_nbis(engine)
    quotes["rows"][0]["last"] = 93.2
    with Session(engine) as db:
        db.add(DayJournalEntry(operation_id="d1", day=WED, kind="decision", symbol="NBIS", text="Holding: group confirms",
                               created_at=T0 + timedelta(minutes=280)))
        db.add(DayJournalEntry(operation_id="d2", day=WED, kind="update", symbol="CRWV", text="not a decision", created_at=T0))
        db.commit()
    body = read(desk)
    assert groups(body)["act"] == [] and body["day"]["need_you"] == 0
    [row] = [r for r in body["threads"] if r["key"] == f"trade:{trade}"]
    assert row["group"] == "watch" and row["meter"] is None
    assert row["status"] == {"text": "Decided 14:40 · 1.0% from invalidation 92.30", "tone": "muted"}


def test_an_invalidation_hit_after_the_decision_needs_a_new_one(desk, engine):  # noqa: F811
    from tests.test_copilot_plans import capture, time_stop
    from tests.test_plan_positions import link
    plan = capture(engine, "NBIS")
    time_stop(engine, NBIS, "NBIS", due_minute=420)
    alert(engine, NBIS, "NBIS", "invalidation", 92.3, state="fired", fired=T0 + timedelta(minutes=200))  # hit 13:20
    trade = buy(engine, 500)
    link(engine, plan, 500)
    with Session(engine) as db:
        db.add(DayJournalEntry(operation_id="d1", day=WED, kind="decision", symbol="NBIS", text="Holding",
                               created_at=T0 + timedelta(minutes=100)))  # 11:40, before the hit
        db.commit()
    [row] = [r for r in read(desk)["threads"] if r["key"] == f"trade:{trade}"]
    assert row["group"] == "act" and row["status"] == {"text": "Invalidation 92.30 hit", "tone": "loss"}
    with Session(engine) as db:
        db.add(DayJournalEntry(operation_id="d2", day=WED, kind="decision", symbol="NBIS", text="Exiting",
                               created_at=T0 + timedelta(minutes=210)))  # 13:30, after it
        db.commit()
    [row] = [r for r in read(desk)["threads"] if r["key"] == f"trade:{trade}"]
    assert row["group"] == "watch" and row["status"]["text"] == "Decided 13:30 · Invalidation 92.30 hit"


def test_a_failing_plan_link_still_lists_the_positions(desk, engine, quotes, monkeypatch):  # noqa: F811
    planned_nbis(engine)
    quotes["rows"][0]["last"] = 93.2

    def broken(*_args, **_kwargs):
        raise RuntimeError("boom")
    monkeypatch.setattr(copilot_desk, "_position_investigations", broken)
    body = read(desk)
    [row] = [r for r in body["threads"] if r["group"] == "act"]
    assert row["investigation_id"] is None and row["path"].startswith("/trades/")  # opens the trade instead
    assert body["sections"]["positions"] == "ok"


def test_plans_near_a_trigger_and_the_rest_watching(desk, engine):  # noqa: F811
    alert(engine, CRWV, "CRWV", "entry", 100.6)  # CRWV last 100: 0.6% to entry
    alert(engine, CRWV, "CRWV", "invalidation", 95.0)
    alert(engine, APLD, "APLD", "entry", 31.0)  # APLD last 30: 3.3%
    investigation(engine, CRWV, "CRWV", "CRWV breakout")
    body = read(desk)
    [near] = [r for r in body["threads"] if r["group"] == "near"]
    assert (near["key"], near["title"], near["investigation_id"]) == (f"plan:{CRWV}", "CRWV breakout", CRWV)
    assert near["status"] == {"text": "0.6% to entry 100.60", "tone": "attention"}
    assert near["value"] == {"text": "Armed", "tone": "muted"} and near["instrument"] == "long"
    assert near["meter"] == {"last": 71.4, "entry": 80.0, "tone": "attention"}  # 5.0 of the 5.6 risk: just short of the entry
    [watch] = [r for r in body["threads"] if r["group"] == "watch"]
    assert watch["key"] == f"plan:{APLD}" and watch["status"]["text"] == "Entry 31.00 · 3.3% away" and watch["meter"] is None
    assert groups(body)["watch"] == [f"plan:{APLD}"]  # the CRWV investigation shows once, as its plan


def test_new_since_you_looked_and_open_investigations(desk, engine, tmp_path, monkeypatch):  # noqa: F811
    path = tmp_path / "radar.sqlite"
    monkeypatch.setenv("RADAR_ENABLED", "true")
    monkeypatch.setenv("RADAR_STORE", str(path))
    monkeypatch.setattr(radar, "_regular_window", lambda day: (570, 960))
    RadarStore(path).append_event(RADAR_EVENT)
    investigation(engine, NBIS, "NBIS", "Is the NBIS recovery real?", conclusion="Group confirms.")
    investigation(engine, CRWV, "CRWV", "CRWV capacity terms", source="research_job", conclusion="untrusted web text")
    investigation(engine, APLD, "APLD", "Closed one", status="closed")
    with Session(engine) as db:
        for n, minute in ((1, 30), (2, 60)):
            db.add(ThesisWatchTrigger(symbol="NBIS", kind="news", dedupe_key=f"news:{n}", investigation_id=UUID(NBIS), day="2026-10-21",
                                      fired_at=T0 + timedelta(minutes=minute), text=f"NBIS headline {n}",
                                      path=f"/copilot-lab?investigation={NBIS}&context=x", delivery="sent"))
        db.add(PremarketPrep(day=WED, investigation_id=APLD, body="NBIS 100C expires Friday.", delivery="sent"))
        db.commit()
    body = read(desk)
    assert groups(body)["new"] == [f"thesis:{NBIS}", f"radar:{RADAR_EVENT['event_id']}"]  # newest first, one per thread
    thesis, event = [r for r in body["threads"] if r["group"] == "new"]
    assert (thesis["title"], thesis["status"]["text"], thesis["investigation_id"]) == (
        "Is the NBIS recovery real?", "News · NBIS headline 2", NBIS)
    assert (event["symbol"], event["status"]["text"], event["path"]) == ("MU", "Radar · vs sector", f"/copilot-lab?symbol=MU&radar={RADAR_EVENT['event_id']}")
    assert event["title"].startswith("MU up 4.1%") and event["radar_event_id"] == RADAR_EVENT["event_id"]
    [research] = [r for r in body["threads"] if r["group"] == "watch"]  # NBIS is under New; the closed one is gone
    assert (research["key"], research["instrument"], research["status"]["text"]) == (f"investigation:{CRWV}", "research", "Research")
    assert "untrusted web text" not in json.dumps(body)  # a research job's conclusion never reaches the list
    assert body["threads"][0]["status"] == {"text": "Prep: NBIS 100C expires Friday.", "tone": "info"}
    with Session(engine) as db:
        assert db.exec(select(PhonePing)).all() == []


def test_an_unplanned_position_links_to_planning_it(desk, engine):  # noqa: F811
    trade = buy(engine, 700, "CRWV")
    [row] = [r for r in read(desk)["threads"] if r["group"] == "watch"]
    assert row["key"] == f"trade:{trade}" and row["status"] == {"text": "No plan yet", "tone": "muted"}
    assert row["investigation_id"] is None and row["path"].startswith("/copilot-lab?symbol=CRWV")


def test_the_week_and_the_streak(desk, engine):  # noqa: F811
    planned_nbis(engine)
    body = read(desk)
    assert body["day"]["streak"] == {"current": 1, "best": 1}
    assert body["threads"][1]["status"]["text"] == "1 of 1 entries planned this week"


def test_after_hours_and_a_closed_day(desk, clock, monkeypatch):  # noqa: F811
    clock["t"] = datetime(2026, 10, 21, 21, 0, tzinfo=UTC).timestamp()  # 17:00 New York
    assert read(desk)["day"]["phase"] == "post"
    monkeypatch.setattr(copilot_desk, "_hours", lambda day: {"status": "closed"})
    assert read(desk)["day"]["phase"] == "closed"


def test_after_the_close_each_position_and_plan_asks_its_review_until_a_reflection_is_saved(desk, engine, clock):  # noqa: F811
    trade = planned_nbis(engine)
    unplanned = buy(engine, 700, "CRWV")
    alert(engine, APLD, "APLD", "entry", 31.0)
    investigation(engine, CRWV, "CRWV", "CRWV capacity terms")
    by_key = lambda body: {r["key"]: r for r in body["threads"]}  # noqa: E731
    rows = by_key(read(desk))
    assert all(r["close"] is None for r in rows.values())  # 14:49: the session is still on
    clock["t"] = datetime(2026, 10, 21, 20, 30, tzinfo=UTC).timestamp()  # 16:30 New York
    rows = by_key(read(desk))
    assert rows[f"trade:{trade}"]["close"] == {"kind": "position", "question": "Review: did you follow the plan?", "reviewed": None}
    assert rows[f"trade:{trade}"]["status"] == {"text": "Review: did you follow the plan?", "tone": "attention"}
    assert rows[f"trade:{unplanned}"]["close"]["kind"] == "position"  # a position with no plan is reviewed too
    assert rows[f"plan:{APLD}"]["status"] == {"text": "Added or not, and why?", "tone": "attention"}
    assert rows[f"investigation:{CRWV}"]["close"] is None and rows["briefing"]["close"] is None
    with Session(engine) as db:
        db.add(DayJournalEntry(operation_id="r1", day=WED, kind="reflection", symbol="NBIS",
                               text="Followed it: held above 92.30 and took half at the target", created_at=T0 + timedelta(minutes=395)))
        db.add(DayJournalEntry(operation_id="r2", day=WED, kind="reflection", symbol="NBIS", text="A later one", created_at=T0 + timedelta(minutes=396)))
        db.commit()
    row = by_key(read(desk))[f"trade:{trade}"]
    assert row["close"]["reviewed"] == "Followed it: held above 92.30 and…"  # the first reflection's first words
    assert row["status"] == {"text": "Reviewed · Followed it: held above 92.30 and…", "tone": "muted"}
    clock["t"] = datetime(2026, 10, 24, 20, 30, tzinfo=UTC).timestamp()  # a Saturday: no close
    assert all(r["close"] is None for r in read(desk)["threads"])


def test_one_failing_source_leaves_the_rest(desk, engine, monkeypatch):  # noqa: F811
    buy(engine, 700, "CRWV", expiration=WED)  # expires today: Act now

    def broken(*_args, **_kwargs):
        raise RuntimeError("boom")
    monkeypatch.setattr(plan_streak, "streak", broken)
    monkeypatch.setattr(copilot_desk, "_hours", broken)
    monkeypatch.setattr(copilot_desk, "_board", broken)
    body = read(desk)
    assert (body["sections"]["week"], body["sections"]["plans"], body["sections"]["phase"]) == ("unavailable",) * 3
    assert body["sections"]["positions"] == "ok" and len(groups(body)["act"]) == 1
    assert body["day"] == {"phase": None, "need_you": 1, "streak": None}


def test_no_ids_beyond_the_ones_rows_link_to(desk, engine, quotes):  # noqa: F811
    trade = planned_nbis(engine)
    quotes["rows"][0]["last"] = 93.0
    alert(engine, CRWV, "CRWV", "entry", 100.6)
    text = json.dumps(read(desk))
    assert set(UUID_RE.findall(text)) == {trade, CRWV, NBIS}
    assert "gmail:" not in text and "card-1" not in text and "Roth" not in text


def test_refused_while_the_lab_is_off(desk, monkeypatch):
    monkeypatch.setattr(copilot_desk.copilot, "settings", lambda: SimpleNamespace(enabled=False))
    assert desk.get("/copilot/desk/threads").status_code == 503


def test_assistant_sessions_cannot_reach_the_desk(boundary, monkeypatch):  # noqa: F811
    boundary.patch.setenv("COPILOT_ENABLED", "true")
    monkeypatch.setattr(chart_feed, "quote_rows", lambda symbols: ([], None, None))
    monkeypatch.setattr(quote_engine, "get_stock_quotes", lambda symbols: {})
    monkeypatch.setattr(copilot_desk, "_hours", lambda day: None)
    owner = boundary.owner.get("/copilot/desk/threads")
    assert owner.status_code == 200, owner.text
    assert signin(boundary).status_code == 200
    assert boundary.public.get("/copilot/desk/threads").status_code == 403
