"""The Copilot Lab's Plans board (GET /copilot/plans): armed copilot plans, nearest to a trigger first, with distances,
hits, time stops and the linked fill; fired, deleted and finished plans drop off. Owner-only. No network."""

from datetime import UTC, date, datetime, timedelta
import json
import re
from types import SimpleNamespace
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.database import get_session
from app.engine import reconstructor
from app.engine.chart_feed import ChartFeedError, chart_feed
from app.models import Account, CaptureLink, CopilotInvestigation, Fill, LevelAlert, PlanTimeStop, TradeCapture
from app.routers import copilot_plans as plan_routes
from app.routers.fills import _rebuild_trades
from tests.test_browser_access import boundary, signin  # noqa: F401  (the shared access fixture)

ROTH = UUID(int=1)
NBIS, CRWV, APLD = "11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222", "33333333-3333-4333-8333-333333333333"
WED = date(2026, 10, 21)
T0 = datetime(2026, 10, 21, 14, 0)  # 10:00 ET, naive UTC as stored
UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)


class _Wednesday(date):
    @classmethod
    def today(cls):
        return WED


@pytest.fixture
def engine(monkeypatch):
    monkeypatch.setattr(reconstructor, "date", _Wednesday)
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Account(id=ROTH, name="Roth", type="roth_ira", last4="8267", broker="robinhood"))
        db.commit()
    yield engine
    engine.dispose()


@pytest.fixture
def quotes(monkeypatch):
    read = {"rows": [{"symbol": "NBIS", "last": 94.0}, {"symbol": "CRWV", "last": 100.0}, {"symbol": "APLD", "last": 30.0}],
            "at": 1792000000.0, "issue": None, "fail": False}

    def quote_rows(symbols):
        read.setdefault("asked", []).append(list(symbols))
        if read["fail"]:
            raise ChartFeedError("Tradier unavailable")
        return [r for r in read["rows"] if r["symbol"] in symbols], read["at"], read["issue"]
    monkeypatch.setattr(chart_feed, "quote_rows", quote_rows)
    return read


@pytest.fixture
def lab(engine, quotes, monkeypatch):
    monkeypatch.setattr(plan_routes.copilot, "settings", lambda: SimpleNamespace(enabled=True))
    app = FastAPI()
    app.include_router(plan_routes.router, prefix="/copilot")

    def session():
        with Session(engine) as db:
            yield db
    app.dependency_overrides[get_session] = session
    with TestClient(app) as client:
        yield client


def alert(engine, inv, symbol, role, price, *, minute=0, state="active", fired=None, source_kind="copilot"):
    with Session(engine) as db:
        db.add(LevelAlert(symbol=symbol, price=price, created_on=WED, condition="crosses", session="regular", direction="up",
                          source_kind=source_kind, source_id=inv, label=f"{symbol} {role}", plan_role=role, state=state,
                          created_at=T0 + timedelta(minutes=minute), fired_at=fired))
        db.commit()


def time_stop(engine, inv, symbol, *, client_id="card-1", minute=1, delivery="scheduled", due_minute=330):
    with Session(engine) as db:
        db.add(PlanTimeStop(client_id=client_id, investigation_id=inv, symbol=symbol, text="out by 15:30", delivery=delivery,
                            due_at=T0 + timedelta(minutes=due_minute), created_at=T0 + timedelta(minutes=minute)))
        db.commit()


def capture(engine, symbol, *, client_id="card-1", side="buy_calls", thesis="Reclaims VWAP with the group", minute=0):
    with Session(engine) as db:
        row = TradeCapture(client_id=client_id, received_at=T0 + timedelta(minutes=minute) - timedelta(seconds=5), account_id=ROTH,
                           account_label="Roth", underlying=symbol, side=side, instrument="option", mode="discretionary",
                           setup_label="Copilot plan", wording="Entry: crosses 95.9.",
                           note=f"Thesis: {thesis} Contract: 100C Oct 24. From a Copilot Lab plan card.",
                           context_state="unavailable", image_state="unavailable")
        db.add(row)
        db.commit()
        return row.id


def buy_and_link(engine, capture_id, symbol="NBIS"):
    with Session(engine) as db:
        db.add(Fill(id=UUID(int=500), account_id=ROTH, ticker=symbol, instrument_type="option", side="buy_to_open", contracts=2,
                    price=310, executed_at=datetime(2026, 10, 21, 10, 5), raw_email_id="gmail:500", option_type="call", strike=100,
                    expiration=date(2026, 10, 23)))
        db.commit()
        _rebuild_trades(db, "test")
        db.add(CaptureLink(capture_id=capture_id, account_id=ROTH, source_key="gmail:500", method="manual"))
        db.commit()


def test_armed_plans_sort_nearest_first_with_distances_in_percent_and_dollars(engine, lab, quotes):
    alert(engine, NBIS, "NBIS", "entry", 95.9)
    alert(engine, NBIS, "NBIS", "invalidation", 92.3)
    alert(engine, CRWV, "CRWV", "entry", 101.0)
    alert(engine, CRWV, "CRWV", "invalidation", 97.0)
    alert(engine, APLD, "APLD", "entry", 33.0)
    alert(engine, APLD, "APLD", "invalidation", 31.5)  # 5% away: farthest
    body = lab.get("/copilot/plans").json()
    assert [p["symbol"] for p in body["plans"]] == ["CRWV", "NBIS", "APLD"]
    assert quotes["asked"] == [["APLD", "CRWV", "NBIS"]]  # one batched read
    nbis = body["plans"][1]
    assert nbis["last"] == 94.0 and nbis["direction"] == "long"
    assert nbis["entry"] == {"price": 95.9, "condition": "crosses", "interval": None, "state": "armed",
                             "distance_usd": 1.9, "distance_pct": 2.02}
    assert nbis["invalidation"] == {"price": 92.3, "condition": "crosses", "interval": None, "state": "armed",
                                         "distance_usd": -1.7, "distance_pct": -1.81}
    assert nbis["time_stop"] is None and nbis["position"] == "waiting"
    assert body["quotes_at"] == 1792000000.0 and body["quote_issue"] is None


def test_a_fired_entry_says_when_and_a_plan_with_nothing_armed_drops_off(engine, lab):
    alert(engine, NBIS, "NBIS", "entry", 95.9, state="fired", fired=T0 + timedelta(minutes=41))
    alert(engine, NBIS, "NBIS", "invalidation", 92.3)
    alert(engine, CRWV, "CRWV", "entry", 101.0, state="fired", fired=T0)
    alert(engine, CRWV, "CRWV", "invalidation", 97.0, state="fired", fired=T0)  # both fired, no position
    alert(engine, APLD, "APLD", "invalidation", 31.5, state="fired", fired=T0)  # entry deleted, invalidation fired
    [plan] = lab.get("/copilot/plans").json()["plans"]
    assert plan["symbol"] == "NBIS"
    assert plan["entry"] == {"price": 95.9, "condition": "crosses", "interval": None, "state": "hit",
                             "hit_at": int(datetime(2026, 10, 21, 14, 41, tzinfo=UTC).timestamp())}
    assert plan["invalidation"]["state"] == "armed"


def test_a_pending_time_stop_keeps_a_plan_whose_alerts_were_deleted_and_a_sent_one_does_not(engine, lab):
    time_stop(engine, NBIS, "NBIS")
    time_stop(engine, CRWV, "CRWV", client_id="card-2", delivery="sent")
    alert(engine, CRWV, "CRWV", "entry", 101.0, state="fired", fired=T0)
    [plan] = lab.get("/copilot/plans").json()["plans"]
    assert plan["symbol"] == "NBIS" and plan["entry"] is None and plan["invalidation"] is None
    assert plan["time_stop"]["text"] == "out by 15:30" and plan["time_stop"]["state"] == "pending"


def test_the_plan_capture_gives_thesis_direction_and_a_linked_open_position_keeps_it_on(engine, lab):
    with Session(engine) as db:
        db.add(CopilotInvestigation(id=UUID(CRWV), title="CRWV short idea", symbol="CRWV", transcript_json="[]", evidence_json="[]"))
        db.commit()
    nbis = capture(engine, "NBIS")
    time_stop(engine, NBIS, "NBIS", delivery="skipped")
    alert(engine, NBIS, "NBIS", "entry", 95.9, state="fired", fired=T0)
    alert(engine, NBIS, "NBIS", "invalidation", 92.3, state="fired", fired=T0)
    alert(engine, CRWV, "CRWV", "entry", 99.0)
    alert(engine, CRWV, "CRWV", "invalidation", 103.0)
    assert [p["symbol"] for p in lab.get("/copilot/plans").json()["plans"]] == ["CRWV"]  # NBIS: nothing armed, no fill yet
    buy_and_link(engine, nbis)
    plans = {p["symbol"]: p for p in lab.get("/copilot/plans").json()["plans"]}
    assert plans["NBIS"]["position"] == "in_position" and plans["NBIS"]["thesis"] == "Reclaims VWAP with the group"
    assert plans["NBIS"]["direction"] == "long" and plans["NBIS"]["time_stop"]["state"] == "skipped"
    # No capture: direction from the levels, the investigation's title stands in for the thesis.
    assert (plans["CRWV"]["direction"], plans["CRWV"]["thesis"], plans["CRWV"]["position"]) == ("short", "CRWV short idea", "waiting")


def test_an_unlinked_suggested_fill_is_flagged_and_an_older_plan_in_the_same_investigation_is_superseded(engine, lab):
    capture(engine, "NBIS", side="buy_calls", minute=60)
    alert(engine, NBIS, "NBIS", "entry", 90.0)  # an earlier plan, an hour before
    alert(engine, NBIS, "NBIS", "entry", 95.9, minute=60)
    alert(engine, NBIS, "NBIS", "invalidation", 92.3, minute=60)
    with Session(engine) as db:
        db.add(Fill(id=UUID(int=501), account_id=ROTH, ticker="NBIS", instrument_type="option", side="buy_to_open", contracts=1,
                    price=300, executed_at=datetime(2026, 10, 21, 11, 2), raw_email_id="gmail:501", option_type="call", strike=100,
                    expiration=date(2026, 10, 23)))
        db.commit()
        _rebuild_trades(db, "test")
        db.commit()
    [plan] = lab.get("/copilot/plans").json()["plans"]
    assert plan["entry"]["price"] == 95.9 and plan["position"] == "fill_to_link"


def test_plain_watches_are_not_plans_and_a_quote_outage_still_lists_without_distances(engine, lab, quotes):
    alert(engine, NBIS, "NBIS", None, 97.0)  # a copilot watch: no role
    alert(engine, None, "CRWV", "entry", 99.0, source_kind="level")
    assert lab.get("/copilot/plans").json()["plans"] == []
    alert(engine, NBIS, "NBIS", "entry", 95.9)
    quotes["fail"] = True
    body = lab.get("/copilot/plans").json()
    [plan] = body["plans"]
    assert plan["last"] is None and set(plan["entry"]) == {"price", "condition", "interval", "state"}
    assert body["quote_issue"] == "Tradier unavailable"


def test_the_only_id_out_is_the_investigation(engine, lab):
    nbis = capture(engine, "NBIS")
    time_stop(engine, NBIS, "NBIS")
    alert(engine, NBIS, "NBIS", "entry", 95.9)
    buy_and_link(engine, nbis)
    text = json.dumps(lab.get("/copilot/plans").json())
    assert set(UUID_RE.findall(text)) == {NBIS}
    assert "gmail:" not in text and "card-1" not in text and "Roth" not in text


def test_refused_while_the_lab_is_off(lab, monkeypatch):
    monkeypatch.setattr(plan_routes.copilot, "settings", lambda: SimpleNamespace(enabled=False))
    assert lab.get("/copilot/plans").status_code == 503


def test_assistant_sessions_cannot_reach_the_board(boundary, monkeypatch):  # noqa: F811
    boundary.patch.setenv("COPILOT_ENABLED", "true")
    monkeypatch.setattr(chart_feed, "quote_rows", lambda symbols: ([], None, None))
    assert boundary.owner.get("/copilot/plans").status_code == 200
    assert signin(boundary).status_code == 200
    assert boundary.public.get("/copilot/plans").status_code == 403
