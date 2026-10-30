"""The Charts dock's Copilot tab for one symbol (GET /copilot/symbol/{symbol}): its open positions with their plans,
its armed plans, and what is new on it, composed in-process from the existing readers. Owner-only. No network."""

from datetime import timedelta
from types import SimpleNamespace
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlmodel import Session

from app.database import get_session
from app.engine import copilot_plans, plan_positions, setup_record
from app.engine.chart_feed import chart_feed
from app.engine.radar_store import RadarStore
from app.models import Account, ThesisWatchTrigger
from app.routers import copilot_plans as plan_routes, radar
from tests.test_browser_access import boundary, signin  # noqa: F401  (the shared access fixture)
from tests.test_copilot_plans import (  # noqa: F401  (fixtures)
    CRWV, NBIS, T0, alert, capture, engine, quotes, time_stop,
)
from tests.test_plan_positions import WEBULL, buy, link
from tests.test_today import RADAR_EVENT, clock, marks  # noqa: F401  (fixtures)


@pytest.fixture
def lab(engine, quotes, marks, clock, monkeypatch):  # noqa: F811
    monkeypatch.delenv("RADAR_ENABLED", raising=False)
    monkeypatch.setattr(plan_routes.copilot, "settings", lambda: SimpleNamespace(enabled=True))
    monkeypatch.setattr(setup_record, "_daily_bars", lambda symbol: [])  # no network: no gap or trend today
    app = FastAPI()
    app.include_router(plan_routes.router, prefix="/copilot")

    def session():
        with Session(engine) as db:
            yield db
    app.dependency_overrides[get_session] = session
    with TestClient(app) as client:
        yield client


def planned_nbis(db_engine):
    """NBIS 100C entered under a plan card: invalidation 92.30 (NBIS last 94.00), time stop 15:30."""
    plan = capture(db_engine, "NBIS")
    time_stop(db_engine, NBIS, "NBIS")
    alert(db_engine, NBIS, "NBIS", "invalidation", 92.3)
    trade = buy(db_engine, 500)
    link(db_engine, plan, 500)
    return trade


def test_only_the_symbol_with_its_position_plan_and_one_quote_read(lab, engine, quotes):  # noqa: F811
    trade = planned_nbis(engine)
    alert(engine, CRWV, "CRWV", "entry", 100.6)
    body = lab.get("/copilot/symbol/nbis").json()
    assert body["symbol"] == "NBIS"
    [row] = body["positions"]["rows"]
    assert row["trade_id"] == trade and row["contract"] == "NBIS 10/23/26 100C"
    assert row["plan"]["invalidation"]["price"] == 92.3 and row["plan"]["invalidation"]["distance_pct"] == -1.81
    assert row["plan"]["time_stop"]["clock"] == "15:30"
    assert body["plans"]["rows"] == []  # the plan it was entered under shows with the position only
    assert quotes["asked"] == [["NBIS"]]  # one read, this symbol only
    crwv = lab.get("/copilot/symbol/CRWV").json()
    assert crwv["positions"]["rows"] == []
    [plan] = crwv["plans"]["rows"]
    assert (plan["investigation_id"], plan["entry"]["price"], plan["entry"]["distance_pct"]) == (CRWV, 100.6, 0.6)


def test_webull_is_left_out(lab, engine):  # noqa: F811
    with Session(engine) as db:
        db.add(Account(id=WEBULL, name="Webull 4242", type="individual", last4="4242", broker="webull"))
        db.commit()
    buy(engine, 600, "CRWV", account=WEBULL)
    assert lab.get("/copilot/symbol/CRWV").json()["positions"]["rows"] == []


def test_new_on_the_symbol_only(lab, engine, tmp_path, monkeypatch):  # noqa: F811
    path = tmp_path / "radar.sqlite"
    monkeypatch.setenv("RADAR_ENABLED", "true")
    monkeypatch.setenv("RADAR_STORE", str(path))
    monkeypatch.setattr(radar, "_regular_window", lambda day: (570, 960))
    RadarStore(path).append_event(RADAR_EVENT)  # an MU event
    with Session(engine) as db:
        db.add(ThesisWatchTrigger(symbol="NBIS", kind="news", dedupe_key="news:a", investigation_id=UUID(NBIS), day="2026-10-21",
                                  fired_at=T0 + timedelta(minutes=30), text="NBIS wins a contract", path="/copilot-lab?symbol=NBIS",
                                  delivery="sent"))
        db.add(ThesisWatchTrigger(symbol="MU", kind="move", dedupe_key="move:b", day="2026-10-21", fired_at=T0,
                                  text="MU up 5%", path="/copilot-lab?symbol=MU", delivery="sent"))
        db.commit()
    mu = lab.get("/copilot/symbol/MU").json()["new"]
    assert [e["event_id"] for e in mu["radar"]["rows"]] == [RADAR_EVENT["event_id"]] and mu["radar"]["count"] == 1
    assert [t["text"] for t in mu["thesis"]["rows"]] == ["MU up 5%"]
    nbis = lab.get("/copilot/symbol/NBIS").json()["new"]
    assert nbis["radar"]["rows"] == [] and nbis["radar"]["count"] == 0
    assert [t["text"] for t in nbis["thesis"]["rows"]] == ["NBIS wins a contract"]


def test_one_failing_source_leaves_the_rest(lab, engine, monkeypatch):  # noqa: F811
    trade = planned_nbis(engine)

    def broken(*_args, **_kwargs):
        raise RuntimeError("boom")
    monkeypatch.setattr(copilot_plans, "board", broken)
    body = lab.get("/copilot/symbol/NBIS").json()
    assert body["plans"] == {"state": "unavailable"}
    assert [r["trade_id"] for r in body["positions"]["rows"]] == [trade]
    assert body["new"]["thesis"]["state"] == "ok" and body["new"]["radar"]["state"] == "off"
    monkeypatch.setattr(plan_positions, "positions", broken)
    assert lab.get("/copilot/symbol/NBIS").json()["positions"] == {"state": "unavailable"}


def test_a_bad_symbol_and_the_lab_off_are_refused(lab, monkeypatch):
    assert lab.get("/copilot/symbol/..%2Fetc").status_code in (400, 404)
    assert lab.get("/copilot/symbol/TOO-LONG-SYMBOL").status_code == 400
    monkeypatch.setattr(plan_routes.copilot, "settings", lambda: SimpleNamespace(enabled=False))
    assert lab.get("/copilot/symbol/NBIS").status_code == 503


def test_assistant_sessions_cannot_reach_it(boundary, monkeypatch):  # noqa: F811
    boundary.patch.setenv("COPILOT_ENABLED", "true")
    monkeypatch.setattr(chart_feed, "quote_rows", lambda symbols: ([], None, None))
    assert boundary.owner.get("/copilot/symbol/NBIS").status_code == 200
    assert signin(boundary).status_code == 200
    assert boundary.public.get("/copilot/symbol/NBIS").status_code == 403


def test_the_symbols_last_answered_exit_lesson_for_a_draft_plan_card(lab, engine, monkeypatch):  # noqa: F811
    from tests.test_copilot_desk import entry, sell
    from tests.test_today import buy as buy_at
    assert lab.get("/copilot/symbol/CRWV").json()["last_exit"] == {"state": "ok", "lesson": None}  # none yet
    alert(engine, CRWV, "CRWV", "entry", 99.0)
    buy_at(engine, 800, "CRWV")
    sell(engine, 801, "CRWV")
    entry(engine, "reflection", "CRWV", "Partly. Took half at the target, gave the rest back.", minute=299)
    entry(engine, "plan_done", "CRWV", "Exit reviewed", minute=300)
    assert lab.get("/copilot/symbol/CRWV").json()["last_exit"] == {"state": "ok", "lesson": {
        "exited": "2026-10-21", "followed": "partly", "lesson": "Partly. Took half at the target, gave the rest back."}}
    assert lab.get("/copilot/symbol/NBIS").json()["last_exit"]["lesson"] is None  # another symbol's lesson stays its own

    def broken(*_args, **_kwargs):
        raise RuntimeError("boom")
    monkeypatch.setattr(copilot_plans, "last_exit_lessons", broken)
    body = lab.get("/copilot/symbol/CRWV").json()
    assert body["last_exit"] == {"state": "unavailable"} and body["plans"]["state"] == "ok"


def test_the_setup_record_rides_along_on_its_own_when_asked(lab, monkeypatch):  # noqa: F811
    assert "setup" not in lab.get("/copilot/symbol/NBIS").json()  # the Charts dock's polling never computes it
    body = lab.get("/copilot/symbol/NBIS?setup=true").json()
    assert body["setup"] == {"state": "ok", "gap_pct": None, "vs_sma_pct": None, "calls": {"gap": None, "trend": None},
                             "puts": {"gap": None, "trend": None}, "size": None}

    def broken(*_args, **_kwargs):
        raise RuntimeError("boom")
    monkeypatch.setattr(setup_record, "opening_trades", broken)
    body = lab.get("/copilot/symbol/NBIS?setup=true").json()
    assert body["setup"] == {"state": "unavailable"} and body["plans"]["state"] == "ok"
