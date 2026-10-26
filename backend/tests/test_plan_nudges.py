"""Unplanned-entry nudge: one phone ping when a new position has no plan linked or suggested. Phone only."""

import asyncio
from datetime import UTC, date, datetime, timedelta
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.database import get_session
from app.engine import capture_links, ntfy, plan_nudges, reconstructor
from app.engine.chart_math import ET
from app.engine.level_alert_monitor import LevelAlertMonitor
from app.engine.plan_nudges import PlanNudges
from app.models import Account, Fill, PlanNudge, Trade, TradeCapture
from app.routers import position_alerts as position_alerts_router
from app.routers.fills import _rebuild_trades

ROTH, WEBULL = UUID(int=1), UUID(int=2)
WED = date(2026, 10, 21)
FRI = date(2026, 10, 23)
n = iter(range(100, 10_000))


def at(hhmm: str, day: date = WED) -> float:
    h, m = map(int, hhmm.split(":"))
    return datetime(day.year, day.month, day.day, h, m, tzinfo=ET).timestamp()


def utc(hhmm: str) -> datetime:
    return datetime.fromtimestamp(at(hhmm), UTC).replace(tzinfo=None)


class Clock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


class Calendar:
    def hours(self, day):
        return {"status": "open", "open": 570, "close": 960}


class _Wednesday(date):
    @classmethod
    def today(cls):
        return WED


@pytest.fixture(autouse=True)
def on_wednesday(monkeypatch):
    monkeypatch.setattr(reconstructor, "date", _Wednesday)
    for name in ("PLAN_NUDGE_GRACE_MINUTES", "PLAN_NUDGE_DAILY_CAP", "PLAN_NUDGE_ENABLED"):
        monkeypatch.delenv(name, raising=False)


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
def world(engine):
    clock = Clock(at("09:50"))
    return clock, PlanNudges(engine, Calendar(), clock=clock)


def buy(engine, when="10:00", ticker="NBIS", qty=2, price=310, account=ROTH, side="buy_to_open", day=WED):
    i = next(n)
    option = {} if side == "buy" else {"option_type": "call", "strike": 100, "expiration": FRI}
    with Session(engine) as db:
        db.add(Fill(id=UUID(int=i), account_id=account, ticker=ticker, instrument_type="stock" if side == "buy" else "option",
                    side=side, contracts=qty, price=price, executed_at=datetime.combine(day, datetime.strptime(when, "%H:%M").time()),
                    raw_email_id=f"gmail:{i}", **option))
        db.commit()
        _rebuild_trades(db, "test")
        db.commit()


def tick(clock, nudger, hhmm):
    clock.now = at(hhmm)
    nudger.run()


def nudges(engine):
    with Session(engine) as db:
        return db.exec(select(PlanNudge).order_by(PlanNudge.detected_at)).all()


def plan(engine, received: datetime, **fields):
    with Session(engine) as db:
        capture = TradeCapture(client_id=f"client-{next(n)}", received_at=received, account_id=ROTH, account_label="Roth", underlying="NBIS",
                               side="buy_calls", instrument="option", mode="discretionary", wording="Out below 92.50.",
                               context_state="unavailable", image_state="unavailable", **fields)
        db.add(capture)
        db.commit()
        db.refresh(capture)
        return capture


def test_off_by_default(monkeypatch):
    assert plan_nudges.enabled() is False
    monkeypatch.setenv("PLAN_NUDGE_ENABLED", "true")
    assert plan_nudges.enabled() is True


def test_fires_once_after_the_grace_period_for_an_unplanned_entry(engine, world):
    clock, nudger = world
    buy(engine, "10:00")
    tick(clock, nudger, "10:02")
    assert nudges(engine) == []  # inside the 3-minute grace
    tick(clock, nudger, "10:03")
    [row] = nudges(engine)
    assert (row.contract, row.contracts, row.price, row.delivery) == ("NBIS 10/23/26 100C", 2, 310, "pending")
    # Once per position, even across a rebuild of the trades.
    with Session(engine) as db:
        _rebuild_trades(db, "test")
        db.commit()
    tick(clock, nudger, "10:10")
    buy(engine, "10:12", qty=1, price=290)  # adding to it is the same position
    tick(clock, nudger, "10:20")
    assert len(nudges(engine)) == 1


def test_positions_opened_before_the_feature_started_are_left_alone(engine, world):
    clock, nudger = world
    buy(engine, "09:40")
    tick(clock, nudger, "10:00")
    assert nudges(engine) == []


def test_a_linked_plan_means_no_nudge(engine, world):
    clock, nudger = world
    buy(engine, "10:00")
    capture = plan(engine, utc("09:20"))  # outside the suggestion window, linked by hand
    with Session(engine) as db:
        trade = db.exec(select(Trade)).one()
        capture_links.link(db, db.get(TradeCapture, capture.id), trade.id)
    tick(clock, nudger, "10:05")
    assert nudges(engine) == []


def test_a_suggested_plan_sends_a_link_ping_not_a_nudge(engine, world, monkeypatch):
    sent = []
    monkeypatch.setenv("NTFY_URL", "https://ntfy.example/topic")
    monkeypatch.setattr(ntfy, "publish", lambda title, body, **kw: sent.append((title, body, kw)))
    clock, nudger = world
    plan(engine, utc("09:58"), setup_label="Group recovery")  # captured two minutes before the entry, not linked yet
    buy(engine, "10:00")
    tick(clock, nudger, "10:05")
    [row] = nudges(engine)
    assert (row.kind, row.delivery) == ("link", "pending")
    nudger.deliver()
    with Session(engine) as db:
        trade_id = db.exec(select(Trade.id)).one()
        assert capture_links.for_trade(db, trade_id) == []  # the ping links nothing: the owner's tap does
    [(title, body, kw)] = sent
    assert title == "NBIS 10/23 100C filled"
    assert body == 'Link it to your plan "Group recovery" (captured 9:58)? Tap to confirm.'
    assert kw["path"] == f"/plans/link?trade={trade_id}" and kw["direct_click"] is True
    # Once per position: the next pass sends nothing more of either kind.
    tick(clock, nudger, "10:10")
    nudger.deliver()
    assert len(nudges(engine)) == 1 and len(sent) == 1


def test_several_suggested_plans_say_how_many(engine, world, monkeypatch):
    sent = []
    monkeypatch.setenv("NTFY_URL", "https://ntfy.example/topic")
    monkeypatch.setattr(ntfy, "publish", lambda title, body, **kw: sent.append((title, body, kw)))
    clock, nudger = world
    plan(engine, utc("09:57"), setup_label="Group recovery")
    plan(engine, utc("09:59"), setup_label="Copilot plan")
    plan(engine, utc("09:30"), setup_label="Too early")  # outside the window: not a candidate
    buy(engine, "10:00")
    tick(clock, nudger, "10:05")
    nudger.deliver()
    [(_, body, _)] = sent
    assert body == "2 of your saved plans match it. Tap to choose the one to link."


def test_a_link_ping_whose_plan_was_linked_meanwhile_is_skipped(engine, world, monkeypatch):
    monkeypatch.setenv("NTFY_URL", "https://ntfy.example/topic")
    monkeypatch.setattr(ntfy, "publish", lambda *a, **kw: pytest.fail("sent after the owner linked it"))
    clock, nudger = world
    capture = plan(engine, utc("09:58"))
    buy(engine, "10:00")
    tick(clock, nudger, "10:05")
    with Session(engine) as db:
        capture_links.link(db, db.get(TradeCapture, capture.id), db.exec(select(Trade.id)).one())
    nudger.deliver()
    [row] = nudges(engine)
    assert row.delivery == "skipped" and "linked or set aside" in row.last_error


def test_link_pings_share_the_cap_and_leave_webull_out(engine, world, monkeypatch):
    monkeypatch.setenv("PLAN_NUDGE_DAILY_CAP", "1")
    clock, nudger = world
    plan(engine, utc("09:58"))
    buy(engine, "10:00")
    buy(engine, "10:01", ticker="CRWV", side="buy", qty=10, price=120)  # no plan: a nudge, but past the cap
    with Session(engine) as db:
        db.add(TradeCapture(client_id="wb", received_at=utc("09:58"), account_id=WEBULL, account_label="Webull", underlying="NBIS",
                            side="buy_calls", instrument="option", mode="discretionary", context_state="unavailable", image_state="unavailable"))
        db.commit()
    buy(engine, "10:00", account=WEBULL)
    tick(clock, nudger, "10:05")
    rows = nudges(engine)
    assert sorted((r.ticker, r.kind, r.delivery) for r in rows) == [("CRWV", "no_plan", "skipped"), ("NBIS", "link", "pending")]
    assert all(r.account_id == ROTH for r in rows)


def _link_client(engine):
    app = FastAPI()
    app.include_router(position_alerts_router.router, prefix="/trades")

    def session():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_session] = session
    return TestClient(app)


def test_the_link_page_lists_the_position_and_its_plans_with_only_the_ids_it_needs(engine, world):
    inv = "7d3f1b2a-0000-4000-8000-000000000abc"
    first = plan(engine, utc("09:58"), setup_label="Copilot plan", note="Thesis: holds the group.",
                 context_json=f'{{"state":"unavailable","investigation_id":"{inv}"}}')
    second = plan(engine, utc("10:00"), setup_label="Group recovery")
    buy(engine, "10:00")
    with Session(engine) as db:
        trade_id = db.exec(select(Trade.id)).one()
    client = _link_client(engine)
    body = client.get(f"/trades/{trade_id}/plan-link").json()
    assert body["trade"] == {"id": str(trade_id), "ticker": "NBIS", "contract": "NBIS 10/23/26 100C", "status": "open", "opened": "opened",
                             "fill": "2 at $3.10", "opened_at": int(at("10:00")), "opened_at_reliable": True}
    assert [(c["capture_id"], c["setup"], c["timing"], c["investigation_id"]) for c in body["candidates"]] == [
        (str(first.id), "Copilot plan", "pre_entry", inv), (str(second.id), "Group recovery", "unverified", None)]
    assert body["linked"] == [] and body["plan_path"].startswith("/copilot-lab?symbol=NBIS&context=Plan%20this%20position")
    # No account, fill or client ids: only the trade, plan and investigation ids the page links with.
    text = str(body)
    for stray in (str(ROTH), first.client_id, "gmail:"):
        assert stray not in text
    assert set(body["candidates"][0]) == {"capture_id", "setup", "mode", "wording", "note", "received_at", "timing", "investigation_id"}
    # Linked through the existing route: the page then shows it linked and offers nothing to link.
    with Session(engine) as db:
        capture_links.link(db, db.get(TradeCapture, first.id), trade_id)
    after = client.get(f"/trades/{trade_id}/plan-link").json()
    assert after["candidates"] == [] and [c["capture_id"] for c in after["linked"]] == [str(first.id)]
    assert client.get(f"/trades/{UUID(int=999)}/plan-link").status_code == 404


def test_the_link_page_route_is_owner_only():
    from app.access_manifest import DOMAIN_ROUTES
    from app.engine import access

    operation = "GET /trades/{trade_id}/plan-link"
    assert operation in DOMAIN_ROUTES
    for granted in (access.JOURNAL_PATHS, access.MARKET_PATHS, access.PRACTICE_PATHS, access.SAMPLE_WRITER_PATHS, *access.SERVICE_PATHS.values()):
        assert operation not in granted


def test_a_plan_marked_not_taken_does_not_cover_it(engine, world):
    clock, nudger = world
    plan(engine, utc("09:58"), not_taken_at=utc("09:59"))
    buy(engine, "10:00")
    tick(clock, nudger, "10:05")
    assert len(nudges(engine)) == 1


def test_daily_cap_records_the_rest_as_skipped(engine, world, monkeypatch):
    monkeypatch.setenv("PLAN_NUDGE_DAILY_CAP", "1")
    clock, nudger = world
    buy(engine, "10:00", ticker="NBIS")
    buy(engine, "10:01", ticker="CRWV", side="buy", qty=10, price=120)
    tick(clock, nudger, "10:05")
    rows = nudges(engine)
    assert sorted(r.delivery for r in rows) == ["pending", "skipped"]
    assert "limit of 1" in next(r for r in rows if r.delivery == "skipped").last_error


def test_market_hours_only_and_webull_left_out(engine, world):
    clock, nudger = world
    buy(engine, "10:00", account=WEBULL)
    tick(clock, nudger, "10:05")
    assert nudges(engine) == []
    buy(engine, "15:58", ticker="CRWV", side="buy", qty=10, price=120)
    tick(clock, nudger, "16:05")  # past the grace, but the session has closed
    assert nudges(engine) == []
    clock.now = at("10:00", WED + timedelta(days=1))  # next morning: an entry from yesterday is not nudged
    nudger.run()
    assert nudges(engine) == []


def test_delivery_opens_the_copilot_with_a_plan_prompt(engine, world, monkeypatch):
    sent = []
    monkeypatch.setenv("NTFY_URL", "https://ntfy.example/topic")
    monkeypatch.setattr(ntfy, "publish", lambda title, body, **kw: sent.append((title, body, kw)))
    clock, nudger = world
    buy(engine, "10:00")
    tick(clock, nudger, "10:03")
    nudger.deliver()
    nudger.deliver()
    [(title, body, kw)] = sent
    assert title == "NBIS 10/23 100C: no plan yet"
    assert body == "Opened 2 at $3.10. Tap for a 20-second plan."
    assert kw["direct_click"] is True
    url = urlsplit(kw["path"])
    query = parse_qs(url.query)
    assert url.path == "/copilot-lab" and query["symbol"] == ["NBIS"]
    assert query["context"] == ["Plan this position: I just opened NBIS 10/23/26 100C (2 at $3.10) without a plan. "
                                "Help me set an invalidation and a time stop."]
    assert len(query["context"][0]) <= 300 and " " not in kw["path"]
    assert nudges(engine)[0].delivery == "sent"


def test_a_late_nudge_is_dropped_not_sent(engine, world, monkeypatch):
    monkeypatch.setenv("NTFY_URL", "https://ntfy.example/topic")
    monkeypatch.setattr(ntfy, "publish", lambda *a, **kw: pytest.fail("sent late"))
    clock, nudger = world
    buy(engine, "10:00")
    tick(clock, nudger, "10:03")
    clock.now = at("10:30")
    nudger.deliver()
    assert nudges(engine)[0].delivery == "expired"


def test_the_trade_page_lists_the_nudge(engine, world):
    clock, nudger = world
    buy(engine, "10:01", ticker="CRWV", side="buy", qty=10, price=120)
    tick(clock, nudger, "10:05")
    app = FastAPI()
    app.include_router(position_alerts_router.router, prefix="/trades")

    def session():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_session] = session
    with Session(engine) as db:
        trade_id = db.exec(select(Trade.id)).one()
    [row] = TestClient(app).get(f"/trades/{trade_id}/phone-alerts").json()["alerts"]
    assert (row["kind"], row["entry"], row["delivery"]) == ("plan_nudge", "10 shares at $120.00", "pending")


def test_the_monitor_runs_nudges_beside_position_alerts(engine):
    class Fake:
        calls = []

        def run(self):
            self.calls.append("run")

        def deliver(self):
            self.calls.append("deliver")

    fake = Fake()
    asyncio.run(LevelAlertMonitor(engine, None, nudges=fake).run_once())
    assert fake.calls == ["run", "deliver"]
