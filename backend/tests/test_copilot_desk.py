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
from app.models import CopilotInvestigation, DayJournalEntry, PhonePing, PlanTimeStop, PremarketPrep, ThesisWatchTrigger
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


def investigation(engine, inv, symbol, title, *, source="copilot", conclusion=None, status="open", transcript=(),  # noqa: F811
                  updated_at=None):
    with Session(engine) as db:
        db.add(CopilotInvestigation(id=UUID(inv), title=title, symbol=symbol, source=source, conclusion=conclusion, status=status,
                                    transcript_json=json.dumps(list(transcript)), evidence_json="[]",
                                    **({"updated_at": updated_at} if updated_at else {})))
        db.commit()


def watch_card(pid, symbol, price, outcome=None, condition="crosses"):
    card = {"id": pid, "kind": "watch", "symbol": symbol, "condition": condition, "price": price,
            "interval": "5m" if condition == "closes_beyond" else None, "label": f"{symbol} level", "why": "the level",
            "client_id": f"client-{pid}"}
    return {**card, "outcome": outcome} if outcome else card


def plan_card(pid, symbol, outcome=None):
    card = {"id": pid, "kind": "trade_plan", "symbol": symbol, "direction": "long", "instrument": "calls", "contract": None,
            "thesis": "Holds the base", "entry_trigger": {"condition": "crosses", "price": 31.2, "interval": None},
            "invalidation": {"condition": "touches", "price": 29.5, "interval": None}, "time_stop": "15:30", "size_note": None}
    return {**card, "outcome": outcome} if outcome else card


def db_rows(engine):  # noqa: F811
    with Session(engine) as db:
        return db.exec(select(CopilotInvestigation)).all()


def answer(*cards):
    return [{"role": "user", "content": "plan it"}, {"role": "assistant", "content": "Here are the cards.", "proposals": list(cards)}]


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


def test_conversations_with_cards_still_waiting_are_waiting_for_you(desk, engine):  # noqa: F811
    from app.engine import copilot_investigations
    done = {"state": "confirmed", "note": "Alert set"}
    investigation(engine, APLD, "APLD", "APLD base", updated_at=T0 + timedelta(minutes=30),
                  transcript=answer(watch_card("w1", "APLD", 31.2), plan_card("p1", "APLD"), watch_card("w0", "APLD", 30, done)))
    investigation(engine, NBIS, "NBIS", "NBIS recovery", updated_at=T0 + timedelta(minutes=60),
                  transcript=answer(watch_card("w2", "NBIS", 92.3, condition="closes_beyond")))
    investigation(engine, CRWV, "CRWV", "All handled", transcript=answer(
        watch_card("w3", "CRWV", 100, done), watch_card("w4", "CRWV", 99, {"state": "dismissed"}),
        {"id": "m1", "kind": "memory", "memory_kind": "lesson", "symbol": "CRWV", "text": "a memory card is not a draft"}))
    for row in db_rows(engine):  # the saved transcripts are what the investigation store itself accepts
        copilot_investigations.SavedMessage.model_validate(json.loads(row.transcript_json)[1])
    body = read(desk)
    assert groups(body)["draft"] == [f"draft:{NBIS}", f"draft:{APLD}"]  # newest first
    nbis, apld = [r for r in body["threads"] if r["group"] == "draft"]
    assert (apld["symbol"], apld["title"], apld["investigation_id"], apld["path"]) == ("APLD", "APLD base", APLD, None)
    assert apld["value"] == {"text": "2 to confirm", "tone": "attention"}  # the confirmed card is done
    assert apld["status"] == {"text": "Alert · APLD crosses 31.20", "tone": "muted"}  # the first waiting card
    assert nbis["status"]["text"] == "Alert · NBIS 5m close beyond 92.30" and nbis["value"]["text"] == "1 to confirm"
    assert groups(body)["watch"] == [f"investigation:{CRWV}"]  # a waiting conversation shows once, under Waiting for you
    assert body["sections"]["drafts"] == "ok" and "client-w1" not in json.dumps(body)


def test_a_plan_card_names_its_entry_and_an_armed_plan_or_a_research_job_stays_out(desk, engine):  # noqa: F811
    investigation(engine, APLD, "APLD", "APLD base", transcript=answer(plan_card("p1", "APLD")))
    alert(engine, CRWV, "CRWV", "entry", 104)  # CRWV's plan is armed: its row stays the plan
    investigation(engine, CRWV, "CRWV", "CRWV breakout", transcript=answer(watch_card("w1", "CRWV", 98)))
    investigation(engine, NBIS, "NBIS", "NBIS job", source="research_job", transcript=answer(watch_card("w2", "NBIS", 92)))
    body = read(desk)
    [row] = [r for r in body["threads"] if r["group"] == "draft"]
    assert row["key"] == f"draft:{APLD}" and row["status"]["text"] == "Plan · APLD long calls · entry crosses 31.20"
    assert groups(body)["watch"] == [f"plan:{CRWV}", f"investigation:{NBIS}"]


def test_a_failing_draft_read_leaves_the_conversation_watching(desk, engine, monkeypatch):  # noqa: F811
    investigation(engine, APLD, "APLD", "APLD base", transcript=answer(watch_card("w1", "APLD", 31.2)))

    def broken(*_args, **_kwargs):
        raise RuntimeError("boom")
    monkeypatch.setattr(copilot_desk, "_drafts", broken)
    body = read(desk)
    assert body["sections"]["drafts"] == "unavailable" and groups(body)["draft"] == []
    assert groups(body)["watch"] == [f"investigation:{APLD}"]


def test_an_unplanned_position_links_to_planning_it(desk, engine):  # noqa: F811
    trade = buy(engine, 700, "CRWV")
    [row] = [r for r in read(desk)["threads"] if r["group"] == "watch"]
    assert row["key"] == f"trade:{trade}" and row["status"] == {"text": "No plan yet", "tone": "muted"}
    assert row["investigation_id"] is None and row["path"].startswith("/copilot-lab?symbol=CRWV")


def test_a_fill_waiting_for_its_plan_names_its_trade_on_the_position_and_the_plan(desk, engine):  # noqa: F811
    from tests.test_copilot_plans import capture, time_stop
    capture(engine, "NBIS", minute=5)  # 10:04:55, unlinked: the linker suggests it for the 10:05 fill
    time_stop(engine, NBIS, "NBIS")
    alert(engine, NBIS, "NBIS", "entry", 95.9)
    trade = buy(engine, 500)
    body = read(desk)
    [position] = [r for r in body["threads"] if r["key"] == f"trade:{trade}"]
    assert position["status"] == {"text": "Fill to link", "tone": "attention"} and position["fill_to_link"] == trade
    assert position["investigation_id"] is None and position["path"] == "/copilot-lab?symbol=NBIS"  # opens on the desk
    [plan] = [r for r in body["threads"] if r["key"] == f"plan:{NBIS}"]
    assert plan["value"]["text"] == "Fill to link" and plan["fill_to_link"] == trade
    assert all(r["fill_to_link"] is None for r in body["threads"] if r["key"] not in (f"trade:{trade}", f"plan:{NBIS}"))


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


def entry(engine, kind, symbol, text, *, day=WED, minute=0):  # noqa: F811
    with Session(engine) as db:
        db.add(DayJournalEntry(operation_id=f"{kind}-{symbol}-{day}-{minute}", day=day, kind=kind, symbol=symbol, text=text,
                               created_at=T0 + (day - WED) + timedelta(minutes=minute)))
        db.commit()


by_key = lambda body: {r["key"]: r for r in body["threads"]}  # noqa: E731
WED_CLOSE = datetime(2026, 10, 21, 20, 30, tzinfo=UTC).timestamp()  # 16:30 New York
THU_CLOSE = datetime(2026, 10, 22, 20, 30, tzinfo=UTC).timestamp()


def test_after_the_close_each_position_and_plan_asks_its_review_until_a_reflection_is_saved(desk, engine, clock):  # noqa: F811
    trade = planned_nbis(engine)
    unplanned = buy(engine, 700, "CRWV")
    alert(engine, APLD, "APLD", "entry", 31.0)
    investigation(engine, CRWV, "CRWV", "CRWV capacity terms")
    rows = by_key(read(desk))
    assert all(r["close"] is None for r in rows.values())  # 14:49: the session is still on
    assert rows[f"trade:{trade}"]["horizon"] == "swing" and rows[f"plan:{APLD}"]["horizon"] == "swing"  # the default
    assert rows["briefing"]["horizon"] is None and rows[f"investigation:{CRWV}"]["horizon"] is None
    clock["t"] = WED_CLOSE
    rows = by_key(read(desk))
    # A swing asks on a day something happened to it: NBIS was bought today.
    assert rows[f"trade:{trade}"]["close"] == {"kind": "position", "question": "Review: did you follow the plan?", "reviewed": None}
    assert rows[f"trade:{trade}"]["status"] == {"text": "Review: did you follow the plan?", "tone": "attention"}
    assert rows[f"trade:{unplanned}"]["close"] == {"kind": "plan_ask", "question": "Want a plan for this?", "reviewed": None}
    assert rows[f"plan:{APLD}"]["close"] is None  # a swing plan nothing happened to stays quiet
    assert rows[f"investigation:{CRWV}"]["close"] is None and rows["briefing"]["close"] is None
    entry(engine, "reflection", "NBIS", "Followed it: held above 92.30 and took half at the target", minute=395)
    entry(engine, "reflection", "NBIS", "A later one", minute=396)
    row = by_key(read(desk))[f"trade:{trade}"]
    assert row["close"]["reviewed"] == "Followed it: held above 92.30 and…"  # the first reflection's first words
    assert row["status"] == {"text": "Reviewed · Followed it: held above 92.30 and…", "tone": "muted"}
    clock["t"] = datetime(2026, 10, 24, 20, 30, tzinfo=UTC).timestamp()  # a Saturday: no close
    assert all(r["close"] is None for r in read(desk)["threads"])


def test_the_horizon_sets_which_rows_ask_after_the_close(desk, engine, clock):  # noqa: F811
    trade = planned_nbis(engine)  # bought Wednesday
    alert(engine, APLD, "APLD", "entry", 31.0)
    with Session(engine) as db:  # its 15:30 time stop went out Wednesday
        for stop in db.exec(select(PlanTimeStop)).all():
            stop.delivery = "sent"
            db.add(stop)
        db.commit()
    clock["t"] = THU_CLOSE
    rows = by_key(read(desk))
    assert rows[f"trade:{trade}"]["close"] is None and rows[f"plan:{APLD}"]["close"] is None  # swings, a quiet Thursday
    with Session(engine) as db:  # a give-back ping on NBIS Thursday
        db.add(PhonePing(sender="position_alerts", source_id="g1", kind="giveback", rank=2, symbol="NBIS", decision="sent",
                         title="t", body="b", decided_at=T0 + timedelta(days=1, minutes=60)))
        db.commit()
    entry(engine, "horizon", "APLD", "Day trade", minute=30)  # the plan card's Confirm, Wednesday
    rows = by_key(read(desk))
    assert rows[f"trade:{trade}"]["close"]["kind"] == "position"
    assert rows[f"plan:{APLD}"]["horizon"] == "day"
    assert rows[f"plan:{APLD}"]["close"] == {"kind": "plan", "question": "Added or not, and why?", "reviewed": None}
    entry(engine, "horizon", "NBIS", "Long hold", day=WED + timedelta(days=1), minute=10)  # the thread header, Thursday
    rows = by_key(read(desk))
    assert rows[f"trade:{trade}"]["horizon"] == "long" and rows[f"trade:{trade}"]["close"] is None  # never asked daily
    assert rows[f"trade:{trade}"]["status"]["text"] != "Review: did you follow the plan?"


def test_a_position_with_no_plan_asks_for_one_once(desk, engine, clock):  # noqa: F811
    unplanned = buy(engine, 700, "CRWV")
    clock["t"] = WED_CLOSE
    entry(engine, "plan_ask", "CRWV", "No plan for now", minute=391)
    row = by_key(read(desk))[f"trade:{unplanned}"]
    assert row["close"] == {"kind": "plan_ask", "question": "Want a plan for this?", "reviewed": "No plan for now"}
    assert row["status"] == {"text": "Reviewed · No plan for now", "tone": "muted"}
    clock["t"] = THU_CLOSE
    assert by_key(read(desk))[f"trade:{unplanned}"]["close"] is None  # answered: quiet from then on


def test_an_answer_before_the_position_opened_does_not_count_and_a_long_hold_is_not_asked(desk, engine, clock):  # noqa: F811
    entry(engine, "plan_ask", "CRWV", "No plan for now", day=WED - timedelta(days=7))
    unplanned = buy(engine, 700, "CRWV")
    clock["t"] = WED_CLOSE
    assert by_key(read(desk))[f"trade:{unplanned}"]["close"]["reviewed"] is None
    entry(engine, "horizon", "CRWV", "Long hold", minute=300)
    assert by_key(read(desk))[f"trade:{unplanned}"]["close"] is None


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


def sell(engine, n, symbol="NBIS", *, hour=13):  # noqa: F811
    """Closes the 2 contracts ``buy(engine, n - 1, symbol)`` opened, Wednesday at ``hour`` New York."""
    from app.models import Fill
    from app.routers.fills import _rebuild_trades
    from tests.test_today import ROTH
    with Session(engine) as db:
        db.add(Fill(id=UUID(int=n), account_id=ROTH, ticker=symbol, instrument_type="option", side="sell_to_close", contracts=2,
                    price=400, executed_at=datetime(2026, 10, 21, hour, 0), raw_email_id=f"gmail:{n}", option_type="call",
                    strike=100, expiration=datetime(2026, 10, 23).date()))
        db.commit()
        _rebuild_trades(db, "test")
        db.commit()


def test_a_plan_whose_position_closed_is_exited_and_asks_its_review_once_until_done(desk, engine):  # noqa: F811
    trade = planned_nbis(engine)  # its invalidation alert is still armed
    sell(engine, 501)
    body = read(desk)
    rows = by_key(body)
    assert f"trade:{trade}" not in rows
    row = rows[f"plan:{NBIS}"]
    assert row["group"] == "watch" and groups(body)["watch"][0] == f"plan:{NBIS}"  # ahead of the "+N more" cut
    assert row["close"] == {"kind": "exit", "question": "Did you follow the plan? One lesson?", "reviewed": None}  # 14:49: any hour
    assert row["status"] == {"text": "Did you follow the plan? One lesson?", "tone": "attention"}
    assert row["value"]["text"] == "Exited Oct 21" and body["sections"]["exits"] == "ok"
    entry(engine, "plan_done", "NBIS", "Exit reviewed", minute=300)
    body = read(desk)
    assert not [r for r in body["threads"] if r["symbol"] == "NBIS"]  # done: out of every group, its conversation too


def test_a_plan_traded_without_a_link_exits_when_the_symbols_position_after_it_closes(desk, engine, clock):  # noqa: F811
    alert(engine, APLD, "APLD", "entry", 31.0)
    buy(engine, 800, "APLD")
    assert by_key(read(desk))[f"plan:{APLD}"]["close"] is None  # still held
    sell(engine, 801, "APLD")
    assert by_key(read(desk))[f"plan:{APLD}"]["close"]["kind"] == "exit"
    clock["t"] = datetime(2026, 10, 29, 18, 0, tzinfo=UTC).timestamp()  # eight days on: the review is not asked any more,
    assert by_key(read(desk))[f"plan:{APLD}"]["close"] is None  # its entry alert still armed keeps it a quiet plan row


def test_a_trade_long_after_an_unlinked_plan_is_not_its_exit(desk, engine, clock):  # noqa: F811
    with Session(engine) as db:
        from app.models import LevelAlert
        db.add(LevelAlert(symbol="APLD", price=31.0, created_on=WED - timedelta(days=30), condition="crosses", session="regular",
                          direction="up", source_kind="copilot", source_id=APLD, label="APLD entry", plan_role="entry", state="fired",
                          created_at=T0 - timedelta(days=30), fired_at=T0 - timedelta(days=29)))
        db.commit()
    buy(engine, 800, "APLD")
    sell(engine, 801, "APLD")
    assert f"plan:{APLD}" not in by_key(read(desk))


def test_mark_done_takes_a_plan_never_entered_off_the_list_and_a_new_plan_comes_back(desk, engine):  # noqa: F811
    alert(engine, APLD, "APLD", "entry", 31.0)
    investigation(engine, APLD, "APLD", "APLD breakout")
    entry(engine, "plan_done", "APLD", "Marked done", minute=30)
    assert not [r for r in read(desk)["threads"] if r["symbol"] == "APLD"]
    alert(engine, APLD, "APLD", "entry", 30.5, minute=60)  # planned again after it was done
    assert by_key(read(desk))[f"plan:{APLD}"]["group"] in ("watch", "near")


SOFI = "44444444-4444-4444-8444-444444444444"


def test_the_plans_view_lists_every_plan_by_stage_with_its_distance_or_r(desk, engine):  # noqa: F811
    alert(engine, APLD, "APLD", "entry", 31.0)  # APLD 30.00: 3.33% below the entry
    alert(engine, APLD, "APLD", "invalidation", 29.0)
    entry(engine, "horizon", "APLD", "Day trade")
    planned_nbis(engine)  # NBIS 94.00 in position: entry 95.90, invalidation 92.30
    alert(engine, NBIS, "NBIS", "entry", 95.9, state="fired", fired=T0 + timedelta(minutes=10))
    alert(engine, CRWV, "CRWV", "entry", 99.0)
    buy(engine, 800, "CRWV")
    sell(engine, 801, "CRWV")  # exited, its review not answered
    alert(engine, SOFI, "SOFI", "entry", 20.0)
    entry(engine, "plan_done", "SOFI", "Marked done", minute=30)
    entry(engine, "plan_done", "PLTR", "Marked done", day=WED - timedelta(days=10))  # not this week
    plans = {p["symbol"]: p for p in read(desk)["plans"]}
    assert set(plans) == {"APLD", "NBIS", "CRWV", "SOFI"}
    armed, held, exited, done = plans["APLD"], plans["NBIS"], plans["CRWV"], plans["SOFI"]
    assert (armed["stage"], armed["investigation_id"], armed["instrument"], armed["horizon"]) == ("armed", APLD, "long", "day")
    assert (armed["entry"]["price"], armed["entry"]["distance_pct"], armed["r"]) == (31.0, 3.33, None)
    assert (held["stage"], held["instrument"], held["horizon"], held["r"]) == ("in_position", "calls", "swing", -0.53)  # -1.90 / 3.60
    assert held["invalidation"]["distance_pct"] == -1.81 and held["time_stop"]["state"] == "pending"
    assert (exited["stage"], exited["investigation_id"], exited["at"]) == ("exited", CRWV, int(datetime(2026, 10, 21, 17, 0, tzinfo=UTC).timestamp()))
    assert (done["stage"], done["investigation_id"], done["note"]) == ("done", SOFI, "Marked done")
    assert done["at"] == int((T0 + timedelta(minutes=30)).replace(tzinfo=UTC).timestamp())
    entry(engine, "plan_done", "CRWV", "Exit reviewed", minute=300)
    plans = {p["symbol"]: p for p in read(desk)["plans"]}
    assert (plans["CRWV"]["stage"], plans["CRWV"]["note"]) == ("done", "Exit reviewed")


def test_a_done_plan_whose_parts_were_all_deleted_stands_alone_without_its_thread(desk, engine):  # noqa: F811
    entry(engine, "plan_done", "SOFI", "Marked done", minute=30)
    [row] = read(desk)["plans"]
    assert (row["stage"], row["symbol"], row["investigation_id"], row["note"]) == ("done", "SOFI", None, "Marked done")


def test_a_new_armed_plan_carries_the_symbols_last_answered_exit_lesson(desk, engine):  # noqa: F811
    alert(engine, CRWV, "CRWV", "entry", 99.0)
    buy(engine, 800, "CRWV")
    sell(engine, 801, "CRWV")  # out 13:00 New York, reviewed at 15:00
    lesson = "No, sold the give-back too early; hold to the time stop next time."
    entry(engine, "reflection", "CRWV", lesson, minute=299)
    entry(engine, "plan_done", "CRWV", "Exit reviewed", minute=300)
    again = "55555555-5555-4555-8555-555555555555"
    alert(engine, again, "CRWV", "entry", 101.0, minute=320)  # planned again after the review
    alert(engine, APLD, "APLD", "entry", 31.0)  # never exited: no lesson
    alert(engine, SOFI, "SOFI", "entry", 20.0)
    buy(engine, 900, "SOFI")
    sell(engine, 901, "SOFI")
    entry(engine, "plan_done", "SOFI", "Exit review skipped", minute=300)  # skipped: nothing to show
    alert(engine, "66666666-6666-4666-8666-666666666666", "SOFI", "entry", 21.0, minute=320)
    plans = {(p["symbol"], p["investigation_id"]): p for p in read(desk)["plans"]}
    assert plans[("CRWV", again)]["stage"] == "armed"
    assert plans[("CRWV", again)]["last_exit"] == {"exited": "2026-10-21", "followed": "no", "lesson": lesson}
    assert plans[("CRWV", CRWV)]["stage"] == "done" and plans[("CRWV", CRWV)]["last_exit"] is None  # only an armed plan
    assert plans[("APLD", APLD)]["last_exit"] is None
    assert plans[("SOFI", "66666666-6666-4666-8666-666666666666")]["last_exit"] is None


def test_a_failing_lesson_read_leaves_the_plans_view(desk, engine, monkeypatch):  # noqa: F811
    from app.engine import copilot_plans
    alert(engine, APLD, "APLD", "entry", 31.0)
    monkeypatch.setattr(copilot_plans, "last_exit_lessons", lambda db, symbols: 1 / 0)
    [row] = read(desk)["plans"]
    assert (row["stage"], row["last_exit"]) == ("armed", None)
