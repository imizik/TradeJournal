"""Saved-advice links (Dots step 5): explicit owner links and clearly labelled
possible later activity. A match never claims the advice was followed."""

from datetime import UTC, date, datetime
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.database import get_session
from app.engine import check_links
from app.engine.check_links import CheckFacts, LinkError
from app.models import Account, CheckLink, Fill, Trade, TradeFill
from app.routers import check_links as check_links_router
from app.routers.fills import _rebuild_trades

ROTH = UUID(int=1)
INDIVIDUAL = UUID(int=2)
WEBULL = UUID(int=3)
CHECK = "chk_00000000-0000-4000-8000-000000000001"
OCT23 = date(2026, 10, 23)
CALL_180 = {"option_type": "call", "strike": 180, "expiration": OCT23}
# The NBIS check: Monday October 19, 2026, 09:30 New York (13:30 UTC, EDT).
FACTS = {"ticker": "NBIS", "received_at": "2026-10-19T13:30:00Z", "instrument": "option", **{k: str(v) for k, v in CALL_180.items()}}
n = iter(range(100, 10_000))


def fill(db, side, qty, price, at, ticker="NBIS", account=ROTH, **option):
    i = next(n)
    option = option or CALL_180
    db.add(Fill(id=UUID(int=i), account_id=account, ticker=ticker, instrument_type="option", side=side, contracts=qty, price=price,
                executed_at=datetime.fromisoformat(at), raw_email_id=f"advice:{i}", **option))
    db.commit()
    return UUID(int=i)


def nbis_lifecycle(db):
    """Two buys and three sells of NBIS Oct 23 $180 calls after the check: +$141 by the engine."""
    first = fill(db, "buy_to_open", 2, 500, "2026-10-19T09:43")
    second = fill(db, "buy_to_open", 2, 520, "2026-10-19T10:05")
    fill(db, "sell_to_close", 1, 560, "2026-10-19T10:40")
    fill(db, "sell_to_close", 1, 540, "2026-10-19T11:10")
    fill(db, "sell_to_close", 2, 540.5, "2026-10-19T13:02")
    _rebuild_trades(db, "test")
    return first, second


def facts(**change):
    value = {**FACTS, **change}
    return CheckFacts.build(CHECK, value.get("ticker"), datetime.fromisoformat(value["received_at"].replace("Z", "+00:00"))
                            if value.get("received_at") else None, value.get("instrument"), value.get("option_type"),
                            float(value["strike"]) if value.get("strike") else None,
                            date.fromisoformat(value["expiration"]) if value.get("expiration") else None)


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Account(id=ROTH, name="Roth", type="roth_ira", last4="8267", broker="robinhood"))
        session.add(Account(id=INDIVIDUAL, name="Individual", type="individual", last4="1111", broker="robinhood"))
        session.add(Account(id=WEBULL, name="Webull", type="individual", last4="2222", broker="webull"))
        session.commit()
        yield session
    engine.dispose()


@pytest.fixture
def client(db):
    app = FastAPI()
    app.include_router(check_links_router.router, prefix="/jo/check-links")
    app.dependency_overrides[get_session] = lambda: db
    with TestClient(app) as test_client:
        yield test_client


def test_nbis_lifecycle_is_possible_later_activity_with_engine_pnl(client, db):
    first, _ = nbis_lifecycle(db)
    body = client.get(f"/jo/check-links/{CHECK}/activity", params=FACTS).json()
    assert body["linked"] == [] and len(body["possible"]) == 1
    trade = body["possible"][0]
    engine_trade = db.get(Trade, first)
    assert trade["trade_id"] == str(first) and trade["contract"] == "NBIS 10/23/26 180C" and trade["timing"] == "after"
    assert trade["realized_pnl"] == float(engine_trade.realized_pnl) == 141.0  # The engine's number, not recomputed.
    assert [f["side"] for f in trade["fills"]] == ["buy_to_open"] * 2 + ["sell_to_close"] * 3
    assert "followed" not in str(body) and "overrode" not in str(body) and "outdated" not in str(body)


def test_explicit_link_and_unlink_are_recorded_and_never_touch_the_check(client, db):
    first, second = nbis_lifecycle(db)
    body = client.post(f"/jo/check-links/{CHECK}/link", json={**FACTS, "trade_id": str(first)}).json()
    assert body["possible"] == [] and len(body["linked"]) == 1
    linked = body["linked"][0]
    assert linked["target"] == "trade" and linked["method"] == "possible_match" and linked["trade"]["trade_id"] == str(first)
    assert client.post(f"/jo/check-links/{CHECK}/link", json={**FACTS, "trade_id": str(first)}).status_code == 422  # Already linked.
    # One fill of the same trade can be linked on its own.
    body = client.post(f"/jo/check-links/{CHECK}/link", json={**FACTS, "fill_id": str(second)}).json()
    assert [(row["target"], row["fill_id"]) for row in body["linked"]] == [("trade", None), ("fill", str(second))]
    assert {row["check_id"] for row in client.get(f"/jo/check-links/for-trade/{first}").json()["links"]} == {CHECK}

    body = client.post(f"/jo/check-links/{CHECK}/links/{linked['link_id']}/unlink", json=FACTS).json()
    assert [row["target"] for row in body["linked"]] == ["fill"]
    assert body["possible"] == []  # Still linked through its fill.
    history = {row["link_id"]: row for row in body["history"]}
    assert history[linked["link_id"]]["unlinked_at"] is not None  # The unlink is recorded, the row kept.
    rows = db.exec(select(CheckLink)).all()
    assert len(rows) == 2 and all(row.check_id == CHECK for row in rows)


def test_link_survives_a_rebuild_through_its_anchor_fill(client, db):
    first, _ = nbis_lifecycle(db)
    client.post(f"/jo/check-links/{CHECK}/link", json={**FACTS, "trade_id": str(first)})
    _rebuild_trades(db, "test")
    body = client.get(f"/jo/check-links/{CHECK}/activity", params=FACTS).json()
    assert body["linked"][0]["trade"]["trade_id"] == str(first)


def test_other_accounts_contracts_and_times_are_not_possible_matches(db):
    nbis_lifecycle(db)
    fill(db, "buy_to_open", 1, 400, "2026-10-19T09:50", account=WEBULL)  # Outside the approved scope.
    fill(db, "buy_to_open", 1, 300, "2026-10-19T09:51", option_type="call", strike=185, expiration=OCT23)  # Different strike.
    fill(db, "buy_to_open", 1, 300, "2026-10-19T09:52", option_type="put", strike=180, expiration=OCT23)  # Different type.
    fill(db, "buy_to_open", 1, 300, "2026-10-19T09:53", option_type="call", strike=180, expiration=date(2026, 10, 30))
    fill(db, "buy_to_open", 1, 300, "2026-10-19T09:54", ticker="NVDA")  # Different underlying.
    fill(db, "buy_to_open", 1, 300, "2026-10-16T10:00")  # A whole trade before the check.
    fill(db, "sell_to_close", 1, 310, "2026-10-16T10:30")
    fill(db, "buy_to_open", 1, 300, "2026-10-26T10:00")  # After the five-day window.
    _rebuild_trades(db, "test")
    found = check_links.possible(db, facts())
    assert [trade.opened_at.isoformat() for trade, _ in found] == ["2026-10-19T09:43:00"]


def test_another_approved_account_is_shown_with_its_name_never_assumed(db):
    fill(db, "buy_to_open", 1, 500, "2026-10-19T09:45", account=INDIVIDUAL)
    fill(db, "buy_to_open", 1, 500, "2026-10-19T09:46")
    _rebuild_trades(db, "test")
    body = check_links.activity(db, facts())
    assert [row["account"] for row in body["possible"]] == ["Individual", "Roth"]  # Multiple candidates, oldest first.
    assert body["linked"] == []


def test_a_check_naming_no_contract_matches_any_nbis_option_and_a_same_minute_entry_is_flagged(db):
    fill(db, "buy_to_open", 1, 500, "2026-10-19T09:30")  # Inside the check's own minute.
    fill(db, "buy_to_open", 1, 300, "2026-10-19T10:00", option_type="put", strike=170, expiration=OCT23)
    _rebuild_trades(db, "test")
    found = check_links.possible(db, facts(instrument=None, option_type=None, strike=None, expiration=None))
    assert [after for _, after in found] == ["same_minute", "after"]


def test_date_only_entries_after_the_check_day_are_after_and_same_day_is_unclear(db):
    fill(db, "buy_to_open", 1, 500, "2026-10-19T00:00")
    fill(db, "buy_to_open", 1, 300, "2026-10-20T00:00", option_type="put", strike=170, expiration=OCT23)
    fill(db, "buy_to_open", 1, 300, "2026-10-18T00:00", option_type="put", strike=160, expiration=OCT23)
    _rebuild_trades(db, "test")
    found = check_links.possible(db, facts(instrument=None, option_type=None, strike=None, expiration=None))
    assert [(trade.opened_at.day, after) for trade, after in found] == [(19, "same_day"), (20, "after")]


def test_window_end_is_five_new_york_days_across_daylight_saving(db):
    # 09:30 EDT on Oct 30 → 09:30 EST on Nov 4 (14:30 UTC), not 08:30.
    body = check_links.activity(db, facts(received_at="2026-10-30T13:30:00Z"))
    assert body["window"]["to"] == int(datetime(2026, 11, 4, 14, 30, tzinfo=UTC).timestamp())


def test_no_fills_means_no_activity(db):
    body = check_links.activity(db, facts())
    assert body["linked"] == [] and body["possible"] == [] and body["history"] == []


@pytest.mark.parametrize("change", [{"ticker": None}, {"ticker": ""}, {"received_at": None}])
def test_a_redacted_or_incomplete_check_shows_nothing(client, db, change):
    nbis_lifecycle(db)
    params = {k: v for k, v in {**FACTS, **change}.items() if v is not None}
    response = client.get(f"/jo/check-links/{CHECK}/activity", params=params)
    assert response.status_code == 422 and "no ticker or time" in response.json()["detail"]
    with pytest.raises(LinkError):
        facts(**change)


def test_unknown_check_id_and_refused_links(client, db):
    first, _ = nbis_lifecycle(db)
    assert client.get("/jo/check-links/not-a-check/activity", params=FACTS).status_code == 422
    webull = fill(db, "buy_to_open", 1, 400, "2026-10-19T09:50", account=WEBULL)
    nvda = fill(db, "buy_to_open", 1, 300, "2026-10-19T09:54", ticker="NVDA")
    _rebuild_trades(db, "test")
    assert "approved scope" in client.post(f"/jo/check-links/{CHECK}/link", json={**FACTS, "trade_id": str(webull)}).json()["detail"]
    assert "different symbol" in client.post(f"/jo/check-links/{CHECK}/link", json={**FACTS, "trade_id": str(nvda)}).json()["detail"]
    assert client.post(f"/jo/check-links/{CHECK}/link", json={**FACTS, "trade_id": str(first), "fill_id": str(first)}).status_code == 422
    other = "chk_00000000-0000-4000-8000-000000000002"
    link = client.post(f"/jo/check-links/{CHECK}/link", json={**FACTS, "trade_id": str(first)}).json()["linked"][0]["link_id"]
    assert client.post(f"/jo/check-links/{other}/links/{link}/unlink", json=FACTS).status_code == 404
    assert db.exec(select(TradeFill)).first() is not None
