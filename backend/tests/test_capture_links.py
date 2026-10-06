"""Capture links and adherence (Charts C3.6): suggestions are never confirmations,
links survive rebuilds by source identity, and timing is judged on the server's
receipt against the first entry's execution minute."""

from datetime import date, datetime
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.database import get_session
from app.engine import capture_links
from app.engine.capture_links import timing
from app.models import Account, CaptureLink, Fill, Trade, TradeCapture
from app.routers import captures as captures_router
from app.routers.fills import _rebuild_trades

ROTH = UUID(int=1)
OTHER = UUID(int=2)
LATER = date(2099, 1, 15)
CALL = {"option_type": "call", "strike": 900, "expiration": LATER}
CALL_905 = {"option_type": "call", "strike": 905, "expiration": LATER}
PUT = {"option_type": "put", "strike": 880, "expiration": LATER}
n = iter(range(100, 10_000))


def ny(at: str) -> datetime:
    return datetime.fromisoformat(at)


def utc(at: str) -> datetime:
    return datetime.fromisoformat(at)


def fill(db, ticker, side, qty, price, at, account=ROTH, **option):
    i = next(n)
    db.add(Fill(id=UUID(int=i), account_id=account, ticker=ticker, instrument_type="option" if option else "stock", side=side,
                contracts=qty, price=price, executed_at=ny(at), raw_email_id=f"links:{i}", **option))
    db.commit()
    return UUID(int=i)


def capture(db, received_utc, side="buy_calls", underlying="NVDA", account=ROTH, mode="template", **extra) -> TradeCapture:
    row = TradeCapture(client_id=f"client-{next(n)}", received_at=utc(received_utc), account_id=account, account_label="Roth",
                       underlying=underlying, side=side, instrument="stock" if side.endswith("stock") else "option", mode=mode,
                       context_state="unavailable", image_state="unavailable", **extra)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def trade_of(db, fill_id) -> Trade:
    from app.models import TradeFill
    return db.get(Trade, db.exec(select(TradeFill).where(TradeFill.fill_id == fill_id)).one().trade_id)


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Account(id=ROTH, name="Roth", type="roth_ira", last4="8267"))
        session.add(Account(id=OTHER, name="Individual", type="individual", last4="1111"))
        session.commit()
        yield session
    engine.dispose()


@pytest.fixture
def client(db):
    app = FastAPI()
    app.include_router(captures_router.router, prefix="/charts")
    app.dependency_overrides[get_session] = lambda: db
    with TestClient(app) as test_client:
        yield test_client


def test_timing_uses_the_entry_minute_and_new_york_daylight_saving():
    # 09:42 New York is 13:42 UTC in September (EDT) and 14:42 UTC in November (EST).
    assert timing(utc("2026-09-15T13:41:59"), ny("2026-09-15T09:42")) == "pre_entry"
    assert timing(utc("2026-09-15T13:42:30"), ny("2026-09-15T09:42")) == "unverified"  # tied: inside the fill's minute
    assert timing(utc("2026-09-15T13:43:00"), ny("2026-09-15T09:42")) == "retrospective"
    assert timing(utc("2026-11-02T14:41:00"), ny("2026-11-02T09:42")) == "pre_entry"
    assert timing(utc("2026-11-02T13:50:00"), ny("2026-11-02T09:42")) == "pre_entry"
    assert timing(utc("2026-11-02T14:43:00"), ny("2026-11-02T09:42")) == "retrospective"
    # A time with seconds is exact; a date with no time is unknown.
    assert timing(utc("2026-09-15T13:42:10"), ny("2026-09-15T09:42:05")) == "retrospective"
    assert timing(utc("2026-09-14T13:00:00"), ny("2026-09-15T00:00")) == "unverified"


def test_suggestions_need_account_side_and_window_and_are_never_confirmed(db, client):
    capture(db, "2026-09-15T13:40:00")
    fill(db, "NVDA", "buy_to_open", 1, 310, "2026-09-15T09:44", **CALL)  # in the window
    fill(db, "NVDA", "buy_to_open", 1, 300, "2026-09-15T09:45", **CALL_905)  # a second contract: ambiguous
    fill(db, "NVDA", "buy_to_open", 1, 200, "2026-09-15T09:43", **PUT)  # puts: wrong side
    fill(db, "NVDA", "buy_to_open", 1, 310, "2026-09-15T09:44", account=OTHER, **CALL)  # other account
    fill(db, "NVDA", "buy_to_open", 1, 310, "2026-09-15T09:55", **CALL)  # 15 minutes later: outside
    _rebuild_trades(db, "test")
    review = client.get("/charts/captures/review").json()
    [item] = review["needs_linking"]
    # Same ticker, two contracts and no contract in the plan: both offered, neither chosen.
    assert sorted(s["contract"] for s in item["suggestions"]) == ["NVDA 1/15/99 900C", "NVDA 1/15/99 905C"]
    assert all(s["timing"] == "pre_entry" for s in item["suggestions"])
    assert review["count"] == 1
    assert not db.exec(select(CaptureLink)).all()  # nothing linked by itself
    # The later entry of the same 900C contract is part of the first trade (a scale-in), so it is no separate candidate.
    assert len(item["suggestions"]) == 2
    # With the exact contract given, only that one matches.
    exact = capture(db, "2026-09-15T13:40:30", strike=905.0, expiration=LATER)
    [s] = capture_links.suggestions(db, [exact])[exact.id]
    assert s["contract"] == "NVDA 1/15/99 905C"


def test_link_unlink_history_and_one_plan_per_trade(db, client):
    plan = capture(db, "2026-09-15T13:40:00")
    entry = fill(db, "NVDA", "buy_to_open", 1, 310, "2026-09-15T09:44", **CALL)
    fill(db, "NVDA", "buy_to_open", 1, 320, "2026-09-15T09:44", **CALL)  # a partial opening fill: same trade
    _rebuild_trades(db, "test")
    trade = trade_of(db, entry)
    row = client.post(f"/charts/captures/{plan.id}/link", json={"trade_id": str(trade.id)}).json()
    assert row["link"]["trade_id"] == str(trade.id) and row["link"]["timing"] == "pre_entry" and row["link"]["method"] == "suggested"
    # Another plan cannot take the same trade; a re-entry is a new trade.
    second = capture(db, "2026-09-15T13:41:00")
    refused = client.post(f"/charts/captures/{second.id}/link", json={"trade_id": str(trade.id)})
    assert refused.status_code == 422 and "re-entry" in refused.json()["detail"]
    # Wrong side is refused even by hand.
    puts = capture(db, "2026-09-15T13:41:30", side="buy_puts")
    assert client.post(f"/charts/captures/{puts.id}/link", json={"trade_id": str(trade.id)}).status_code == 422
    # Unlink keeps history; the plan's own time never changes.
    row = client.post(f"/charts/captures/{plan.id}/unlink").json()
    received = row["received_at"]
    assert row["link"] is None and row["link_history"][0]["unlinked_at"] is not None
    row = client.post(f"/charts/captures/{plan.id}/link", json={"trade_id": str(trade.id)}).json()
    assert len(row["link_history"]) == 2 and row["link"]["timing"] == "pre_entry" and row["received_at"] == received
    assert [c["id"] for c in client.get(f"/charts/captures/for-trade/{trade.id}").json()["captures"]] == [str(plan.id)]


def test_manual_late_and_reflection_links_stay_retrospective(db, client):
    entry = fill(db, "AMD", "buy", 10, 150, "2026-09-15T10:00")
    _rebuild_trades(db, "test")
    trade = trade_of(db, entry)
    # A plan written after the entry (a late upload or a reflection) links by hand and says so.
    late = capture(db, "2026-09-15T15:00:00", side="buy_stock", underlying="AMD", mode="voice", transcript_status="ready")
    assert capture_links.suggestions(db, [late])[late.id] == []
    assert [o["trade_id"] for o in capture_links.others(db, late)] == [str(trade.id)]
    row = client.post(f"/charts/captures/{late.id}/link", json={"trade_id": str(trade.id)}).json()
    assert row["link"]["method"] == "manual" and row["link"]["timing"] == "retrospective"
    # Adding a note later never makes it pre-entry.
    client.post(f"/charts/captures/{late.id}/notes", json={"kind": "note", "text": "I meant to buy the reclaim"})
    assert client.get(f"/charts/captures/for-trade/{trade.id}").json()["captures"][0]["link"]["timing"] == "retrospective"


def test_links_survive_rebuild_and_go_unresolved_when_the_fill_is_gone(db, client):
    plan = capture(db, "2026-09-15T13:40:00")
    entry = fill(db, "NVDA", "buy_to_open", 1, 310, "2026-09-15T09:44", **CALL)
    _rebuild_trades(db, "test")
    capture_links.link(db, plan, trade_of(db, entry).id)
    # A delayed import of an earlier fill: the trade's first entry moves earlier and timing is judged again.
    fill(db, "NVDA", "buy_to_open", 1, 300, "2026-09-15T09:38", **CALL)
    _rebuild_trades(db, "rebuild")
    [row] = client.get("/charts/captures").json()["captures"]
    assert row["link"]["trade_id"] is not None and row["link"]["timing"] == "retrospective"
    # A resync that loses the anchored fill: unresolved, never moved to another trade.
    from sqlalchemy import delete
    from app.models import TradeFill
    db.exec(delete(TradeFill).where(TradeFill.fill_id == entry))
    db.exec(delete(Fill).where(Fill.id == entry))
    db.commit()
    _rebuild_trades(db, "resync")
    data = client.get("/charts/captures").json()
    assert data["captures"][0]["link"]["unresolved"] is True and data["captures"][0]["link"]["trade_id"] is None
    assert data["needs_linking"] == 1
    assert db.exec(select(CaptureLink)).one().unlinked_at is None  # nothing deleted


def test_delayed_ingestion_turns_a_waiting_plan_into_a_suggestion(db, client):
    plan = capture(db, "2026-09-15T13:40:00", side="buy_stock", underlying="AMD")
    assert client.get("/charts/captures/review").json()["needs_linking"][0]["suggestions"] == []
    fill(db, "AMD", "buy", 10, 150, "2026-09-15T09:41")
    _rebuild_trades(db, "import")
    assert [s["timing"] for s in client.get("/charts/captures/review").json()["needs_linking"][0]["suggestions"]] == ["pre_entry"]
    # A plan marked not taken is a valid record and is not waiting for a link.
    client.post(f"/charts/captures/{plan.id}/not-taken")
    assert client.get("/charts/captures/review").json()["needs_linking"] == []


def test_adherence_counts_from_activation_with_pending_and_excluded_trades(db, client, monkeypatch):
    before = fill(db, "NVDA", "buy", 1, 100, "2026-09-14T10:00")  # before activation
    monkeypatch.setattr(capture_links, "datetime", type("Clock", (datetime,), {"utcnow": staticmethod(lambda: utc("2026-09-15T12:00:00"))}))
    assert client.put("/charts/captures/tracking", json={"on": True, "accounts": [str(ROTH)]}).json()["since"] is not None
    confirmed = fill(db, "NVDA", "buy_to_open", 1, 310, "2026-09-15T09:44", **CALL)
    discretionary = fill(db, "AMD", "buy", 5, 150, "2026-09-15T10:30")
    tied = fill(db, "MRVL", "buy", 5, 80, "2026-09-15T11:00")
    late = fill(db, "AAPL", "buy", 5, 230, "2026-09-15T11:30")
    fill(db, "TSLA", "buy", 1, 400, "2026-09-15T12:00")  # its plan waits for a link
    fill(db, "META", "buy", 1, 700, "2026-09-15T13:00")  # no plan at all
    fill(db, "QQQ", "buy", 1, 500, "2026-09-16T00:00")  # a date with no time: excluded
    fill(db, "SPY", "buy", 1, 600, "2026-09-15T13:30", account=OTHER)  # an account not tracked
    _rebuild_trades(db, "test")
    links = [(capture(db, "2026-09-15T13:40:00"), confirmed),
             (capture(db, "2026-09-15T14:29:00", side="buy_stock", underlying="AMD", mode="discretionary"), discretionary),
             (capture(db, "2026-09-15T15:00:30", side="buy_stock", underlying="MRVL"), tied),
             (capture(db, "2026-09-15T16:00:00", side="buy_stock", underlying="AAPL"), late)]
    for plan, entry in links:
        capture_links.link(db, plan, trade_of(db, entry).id)
    capture(db, "2026-09-15T15:58:00", side="buy_stock", underlying="TSLA")  # suggested, not yet confirmed
    summary = client.get("/charts/captures/review").json()["summary"]
    assert summary["eligible"] == 6  # NVDA, AMD, MRVL, AAPL, TSLA, META; not the earlier trade, the date-only one or the other account
    assert {k: summary[k] for k in ("confirmed", "confirmed_discretionary", "unverified", "retrospective", "needs_linking", "no_capture", "excluded")} == {
        "confirmed": 2, "confirmed_discretionary": 1, "unverified": 1, "retrospective": 1, "needs_linking": 1, "no_capture": 1, "excluded": 1}
    assert before  # recorded before tracking began, so outside the count
    assert client.put("/charts/captures/tracking", json={"on": False}).json() == {"since": None, "accounts": []}
    assert client.get("/charts/captures/review").json()["summary"] is None
    assert client.put("/charts/captures/tracking", json={"on": True, "accounts": []}).status_code == 422
