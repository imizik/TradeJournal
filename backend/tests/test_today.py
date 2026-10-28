"""The owner's Today screen (GET /today): Act now, plans near a trigger, new since you looked, held-back pings and the
week, composed in-process from the existing readers with one batched quote read. Owner-only. No network."""

from datetime import UTC, date, datetime, timedelta
import json
from pathlib import Path
import re
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlmodel import Session, select

from app.database import get_session
from app.engine import copilot_plans, plan_positions, plan_streak, quotes as quote_engine
from app.engine.chart_feed import chart_feed
from app.engine.quotes import OptionQuoteResult
from app.engine.radar_store import RadarStore
from app.models import (CopilotInvestigation, Fill, PhonePing, PositionAlert, PositionWatch, PremarketPrep, ThesisWatchTrigger, Trade)
from app.routers import radar, today as today_routes
from app.routers.fills import _rebuild_trades
from tests.test_browser_access import boundary, signin  # noqa: F401  (the shared access fixture)
from tests.test_copilot_plans import (  # noqa: F401  (fixtures)
    APLD, CRWV, NBIS, ROTH, T0, WED, alert, capture, engine, quotes, time_stop,
)
from tests.test_plan_positions import link

UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
RADAR_EVENT = json.loads((Path(__file__).parent / "fixtures" / "radar" / "sample_event.json").read_text())["event"]


def epoch(moment: datetime) -> float:
    return moment.replace(tzinfo=UTC).timestamp()


@pytest.fixture
def clock(monkeypatch):
    """New York 14:49 on Wednesday Oct 21 unless a test moves it."""
    now = {"t": epoch(T0 + timedelta(minutes=289))}
    monkeypatch.setattr(today_routes, "_now", lambda: now["t"])
    monkeypatch.setattr(plan_positions, "_now", lambda: now["t"])
    return now


@pytest.fixture
def marks(monkeypatch):
    monkeypatch.setattr(quote_engine, "get_stock_quotes", lambda symbols: {s: 131.2 for s in symbols})
    monkeypatch.setattr(quote_engine, "get_option_quotes", lambda requests: [OptionQuoteResult(mid=4.0)] * len(requests))
    monkeypatch.setattr(quote_engine, "option_mark", lambda req: (OptionQuoteResult(mid=4.0), 1792000000.0))


@pytest.fixture
def client(engine, quotes, marks, clock, monkeypatch):  # noqa: F811
    monkeypatch.delenv("RADAR_ENABLED", raising=False)
    app = FastAPI()
    app.include_router(today_routes.router, prefix="/today")

    def session():
        with Session(engine) as db:
            yield db
    app.dependency_overrides[get_session] = session
    with TestClient(app) as c:
        yield c


def buy(db_engine, n, symbol="NBIS", *, expiration=date(2026, 10, 23), minute=5):
    with Session(db_engine) as db:
        db.add(Fill(id=UUID(int=n), account_id=ROTH, ticker=symbol, instrument_type="option", side="buy_to_open", contracts=2,
                    price=310, executed_at=datetime(2026, 10, 21, 10, minute), raw_email_id=f"gmail:{n}", option_type="call",
                    strike=100, expiration=expiration))
        db.commit()
        _rebuild_trades(db, "test")
        db.commit()
        return str(db.get(Trade, UUID(int=n)).id)


def planned_nbis(db_engine):
    """NBIS 100C entered under a plan card: invalidation 92.30 (NBIS last 94.00, 1.81% away), time stop 15:30."""
    plan = capture(db_engine, "NBIS")
    time_stop(db_engine, NBIS, "NBIS")
    alert(db_engine, NBIS, "NBIS", "invalidation", 92.3)
    trade = buy(db_engine, 500)
    link(db_engine, plan, 500)
    return trade


def reasons(body, trade_id):
    return [r["kind"] for row in body["act_now"]["rows"] if row["trade_id"] == trade_id for r in row["reasons"]]


def test_nothing_going_on_reads_as_empty_sections(client):
    body = client.get("/today").json()
    assert body["day"] == "2026-10-21" and body["as_of"] == "2026-10-21T18:49:00Z"
    assert body["act_now"] == {"state": "ok", "rows": [], "open_positions": 0}
    assert body["plans"] == {"state": "ok", "rows": [], "armed": 0}
    assert body["new"]["radar"]["state"] == "off" and body["new"]["radar"]["rows"] == []
    assert body["new"]["thesis"] == {"state": "ok", "rows": [], "count": 0}
    assert body["new"]["prep"] == {"state": "ok", "prep": None}
    assert body["held"] == {"state": "ok", "rows": [], "count": 0}
    assert body["week"]["state"] == "ok" and (body["week"]["planned"], body["week"]["total"]) == (0, 0)


def test_the_one_percent_invalidation_rule(client, engine, quotes):  # noqa: F811
    trade = planned_nbis(engine)
    body = client.get("/today").json()
    assert body["act_now"]["rows"] == [] and body["act_now"]["open_positions"] == 1  # 1.81% away: not yet
    quotes["rows"][0]["last"] = 93.2  # (92.3 - 93.2) / 93.2 = -0.97%
    [row] = client.get("/today").json()["act_now"]["rows"]
    assert row["trade_id"] == trade and row["contract"] == "NBIS 10/23/26 100C"
    assert row["reasons"] == [{"kind": "invalidation_near", "text": "1.0% from invalidation 92.30"}]
    # the decision bar's detail: the plan's level beside the reason
    assert row["direction"] == "long" and row["invalidation"]["price"] == 92.3 and row["invalidation"]["distance_pct"] == -0.97
    assert row["time_stop"]["clock"] == "15:30" and row["latest_alert"] is None
    quotes["rows"][0]["last"] = 93.3  # -1.07%
    assert client.get("/today").json()["act_now"]["rows"] == []


def test_a_hit_invalidation_is_act_now(client, engine):  # noqa: F811
    plan = capture(engine, "NBIS")
    time_stop(engine, NBIS, "NBIS", due_minute=420)  # 17:00, not due
    alert(engine, NBIS, "NBIS", "invalidation", 92.3, state="fired", fired=T0 + timedelta(minutes=200))
    trade = buy(engine, 500)
    link(engine, plan, 500)
    assert reasons(client.get("/today").json(), trade) == ["invalidation_hit"]


def test_the_thirty_minute_time_stop_rule(client, engine, clock):  # noqa: F811
    trade = planned_nbis(engine)  # time stop due 15:30 New York
    clock["t"] = epoch(T0 + timedelta(minutes=299))  # 14:59, 31 minutes out
    assert reasons(client.get("/today").json(), trade) == []
    clock["t"] = epoch(T0 + timedelta(minutes=300))  # 15:00
    [row] = client.get("/today").json()["act_now"]["rows"]
    assert row["reasons"] == [{"kind": "time_stop", "text": "Time stop 15:30 · 30 min"}]
    clock["t"] = epoch(T0 + timedelta(minutes=331))  # past due, still pending
    assert client.get("/today").json()["act_now"]["rows"][0]["reasons"][0]["text"] == "Time stop 15:30 · due now"


def test_expiring_today_and_give_back_fired(client, engine):  # noqa: F811
    expiring = buy(engine, 700, "CRWV", expiration=WED)
    later = buy(engine, 701, "APLD")
    with Session(engine) as db:
        db.add(PositionWatch(account_id=ROTH, source_key="gmail:701", contracts=2, avg_cost=310, peak_mark=500,
                             armed_at=T0 + timedelta(minutes=30)))
        db.add(PositionAlert(account_id=ROTH, source_key="gmail:701", kind="giveback", generation=0, trade_id=UUID(later),
                             contract="APLD 10/23/26 100C", contracts=2, avg_cost=310, delivery="sent",
                             detected_at=T0 + timedelta(minutes=90)))
        db.commit()
    body = client.get("/today").json()
    assert reasons(body, expiring) == ["expires_today"]
    assert reasons(body, later) == ["giveback"]
    [row] = [r for r in body["act_now"]["rows"] if r["trade_id"] == later]
    assert row["latest_alert"] == {"kind": "giveback", "at": epoch(T0 + timedelta(minutes=90))} and row["invalidation"] is None
    assert body["act_now"]["open_positions"] == 2


def test_plans_near_a_trigger(client, engine, quotes):  # noqa: F811
    alert(engine, CRWV, "CRWV", "entry", 100.6)  # CRWV last 100: 0.6% to entry
    alert(engine, CRWV, "CRWV", "invalidation", 95.0)
    alert(engine, APLD, "APLD", "entry", 31.0)  # APLD last 30: 3.3%
    with Session(engine) as db:
        db.add(CopilotInvestigation(id=UUID(CRWV), title="CRWV breakout", symbol="CRWV", transcript_json="[]", evidence_json="[]"))
        db.commit()
    body = client.get("/today").json()
    assert body["plans"]["armed"] == 2
    [row] = body["plans"]["rows"]
    assert (row["symbol"], row["trigger"], row["price"], row["distance_pct"]) == ("CRWV", "entry", 100.6, 0.6)
    assert row["path"] == f"/copilot-lab?investigation={CRWV}" and row["thesis"] == "CRWV breakout"
    assert len(quotes["asked"]) == 1  # one batched quote read


def test_a_plan_already_in_a_position_shows_under_act_now_only(client, engine, quotes):  # noqa: F811
    trade = planned_nbis(engine)
    quotes["rows"][0]["last"] = 93.0
    body = client.get("/today").json()
    assert body["plans"]["rows"] == [] and body["plans"]["armed"] == 1
    assert reasons(body, trade) == ["invalidation_near"]
    assert quotes["asked"] == [["NBIS"]]  # the board's read serves the positions too


def test_new_since_you_looked(client, engine, tmp_path, monkeypatch):  # noqa: F811
    path = tmp_path / "radar.sqlite"
    monkeypatch.setenv("RADAR_ENABLED", "true")
    monkeypatch.setenv("RADAR_STORE", str(path))
    monkeypatch.setattr(radar, "_regular_window", lambda day: (570, 960))
    store = RadarStore(path)
    store.append_event(RADAR_EVENT)
    path_inv = f"/copilot-lab?investigation={NBIS}&context=New%20since%20my%20thesis"
    with Session(engine) as db:
        db.add(ThesisWatchTrigger(symbol="NBIS", kind="news", dedupe_key="news:a", investigation_id=UUID(NBIS), day="2026-10-21",
                                  fired_at=T0 + timedelta(minutes=30), text="NBIS wins a contract", path=path_inv, delivery="sent"))
        db.add(ThesisWatchTrigger(symbol="MU", kind="move", dedupe_key="move:b", day="2026-10-20",
                                  fired_at=T0 - timedelta(days=1), text="MU up 5%", path="/copilot-lab?symbol=MU", delivery="sent"))
        db.add(PremarketPrep(day=WED, investigation_id=APLD, body="NBIS 100C expires Friday.\nCRWV entry 100.60 is 0.6% away.",
                             delivery="sent"))
        db.commit()
    new = client.get("/today").json()["new"]
    [event] = new["radar"]["rows"]
    assert event["event_id"] == RADAR_EVENT["event_id"] and event["symbol"] == "MU"
    assert event["path"] == f"/radar?event={RADAR_EVENT['event_id']}" and event["summary"].startswith("MU up 4.1%")
    assert new["thesis"]["count"] == 1
    [trigger] = new["thesis"]["rows"]
    assert (trigger["symbol"], trigger["text"], trigger["path"]) == ("NBIS", "NBIS wins a contract", path_inv)
    assert new["prep"]["prep"]["lines"] == ["NBIS 100C expires Friday.", "CRWV entry 100.60 is 0.6% away."]
    assert new["prep"]["prep"]["path"] == f"/copilot-lab?investigation={APLD}"
    store.append_visit("2026-10-21T18:00:00.000Z")  # looked after the event: nothing new
    assert client.get("/today").json()["new"]["radar"]["rows"] == []
    with Session(engine) as db:
        assert db.exec(select(PhonePing)).all() == []  # no pings


def test_held_back_pings_today_with_their_text(client, engine):  # noqa: F811
    with Session(engine) as db:
        for n, (decision, minute) in enumerate((("merged", 60), ("suppressed", 120), ("over_cap", 150), ("sent", 130),
                                                ("merged", -1500))):
            db.add(PhonePing(sender="plan_nudges", source_id=f"s{n}", kind="nudge", rank=6, symbol="NBIS", decision=decision,
                             reason=f"reason {n}", title=f"Plan NBIS {n}", body=f"body {n}", decided_at=T0 + timedelta(minutes=minute)))
        db.commit()
    held = client.get("/today").json()["held"]
    assert held["count"] == 3
    assert [(r["decision"], r["title"], r["body"], r["kind"]) for r in held["rows"]] == [
        ("over_cap", "Plan NBIS 2", "body 2", "plan nudge"), ("suppressed", "Plan NBIS 1", "body 1", "plan nudge"),
        ("merged", "Plan NBIS 0", "body 0", "plan nudge")]


def test_your_week_so_far(client, engine):  # noqa: F811
    planned_nbis(engine)  # a plan saved before the 10:05 entry
    week = client.get("/today").json()["week"]
    assert (week["current"], week["planned"], week["total"]) == (1, 1, 1)


def test_one_failing_section_leaves_the_rest(client, engine, monkeypatch):  # noqa: F811
    trade = buy(engine, 700, "CRWV", expiration=WED)

    def broken(*_args, **_kwargs):
        raise RuntimeError("boom")
    monkeypatch.setattr(plan_streak, "streak", broken)
    monkeypatch.setattr(copilot_plans, "board", broken)
    body = client.get("/today").json()
    assert body["week"] == {"state": "unavailable"} and body["plans"] == {"state": "unavailable"}
    assert reasons(body, trade) == ["expires_today"]
    assert body["held"]["state"] == "ok" and body["new"]["thesis"]["state"] == "ok"


def test_no_ids_beyond_the_ones_rows_link_to(client, engine, quotes):  # noqa: F811
    trade = planned_nbis(engine)
    quotes["rows"][0]["last"] = 93.0
    alert(engine, CRWV, "CRWV", "entry", 100.6)
    with Session(engine) as db:
        db.add(ThesisWatchTrigger(symbol="NBIS", kind="news", dedupe_key="news:a", investigation_id=UUID(NBIS), day="2026-10-21",
                                  fired_at=T0, text="NBIS wins a contract", path=f"/copilot-lab?investigation={NBIS}", delivery="sent",
                                  memory_id=UUID(int=77)))
        db.add(PremarketPrep(day=WED, investigation_id=APLD, body="Prep.", delivery="sent"))
        db.add(PhonePing(sender="plan_nudges", source_id=str(UUID(int=88)), kind="nudge", rank=6, decision="merged", title="t",
                         body="b", trade_id=UUID(trade), merged_into=UUID(int=99), decided_at=T0))
        db.commit()
    text = json.dumps(client.get("/today").json())
    assert set(UUID_RE.findall(text)) == {trade, CRWV, NBIS, APLD}
    assert "gmail:" not in text and "card-1" not in text and "Roth" not in text


def test_assistant_sessions_cannot_reach_today(boundary, monkeypatch):  # noqa: F811
    monkeypatch.setattr(chart_feed, "quote_rows", lambda symbols: ([], None, None))
    monkeypatch.setattr(quote_engine, "get_stock_quotes", lambda symbols: {})
    monkeypatch.setattr(quote_engine, "get_option_quotes", lambda requests: [])
    owner = boundary.owner.get("/today")
    assert owner.status_code == 200, owner.text
    assert signin(boundary).status_code == 200
    assert boundary.public.get("/today").status_code == 403
