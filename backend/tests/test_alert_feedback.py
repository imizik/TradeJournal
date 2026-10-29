"""Real routes: owner feedback persists independently of fills and survives retries/rebuilds."""
from datetime import datetime
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlmodel import Session, select

from app.database import get_session
from app.engine import exit_habits
from app.models import Account, PositionAlert, PositionAlertFeedback, Trade
from app.routers import position_alerts
from app.routers.fills import _rebuild_trades
from tests.test_browser_access import boundary, signin  # noqa: F401
from tests.test_exit_habits import ROTH, add_alert, engine, fill  # noqa: F401


def seed(db):
    if db.get(Account, ROTH) is None:
        db.add(Account(id=ROTH, name="Fixture", type="roth_ira", last4="8267", broker="robinhood"))
    source = fill(db, "SNDK", "buy_to_open", 2, 200, "2026-10-21T09:45")
    fill(db, "SNDK", "sell_to_close", 2, 280, "2026-10-21T10:40")
    fill(db, "MU", "buy_to_open", 1, 100, "2026-10-21T09:45")
    db.commit()
    _rebuild_trades(db, "test")
    add_alert(db, source, "giveback", "2026-10-21T10:30", 2, 300)
    db.commit()
    trade = db.exec(select(Trade).where(Trade.ticker == "SNDK")).one()
    other = db.exec(select(Trade).where(Trade.ticker == "MU")).one()
    alert = db.exec(select(PositionAlert)).one()
    return trade.id, other.id, alert.id


@pytest.fixture
def case(engine):  # noqa: F811
    with Session(engine) as db:
        trade, other, alert = seed(db)
    app = FastAPI()
    app.include_router(position_alerts.router, prefix="/trades")
    def session():
        with Session(engine) as db:
            yield db
    app.dependency_overrides[get_session] = session
    with TestClient(app) as client:
        yield client, engine, trade, other, alert


def path(trade, alert):
    return f"/trades/{trade}/phone-alerts/{alert}/feedback"


def test_save_retry_edit_conflict_and_rebuild(case):
    client, db_engine, trade, other, alert = case
    url = path(trade, alert)
    body = {"rating": "prompted_review", "reason": "  Checked my thesis.  ", "base_version": 0}
    with Session(db_engine) as db:
        before = exit_habits.build(db)
        pnl = db.get(Trade, trade).realized_pnl
    saved = client.put(url, json=body)
    assert saved.status_code == 200
    first = saved.json()
    assert first["reason"] == "Checked my thesis." and first["version"] == 1
    assert first["created_at"] == first["updated_at"]
    # Lost successful response: the same retry preserves timestamp/version, one response only.
    assert client.put(url, json=body).json() == first
    read = client.get(f"/trades/{trade}/phone-alerts").json()
    assert read["alerts"][0]["feedback"] == first
    edit = {"rating": "already_aware", "reason": "", "base_version": 1}
    edited = client.put(url, json=edit).json()
    assert edited["rating"] == "already_aware" and edited["reason"] is None and edited["version"] == 2
    assert edited["created_at"] == first["created_at"]
    assert client.put(url, json=edit).json() == edited
    assert client.put(url, json=body).status_code == 409  # stale retry cannot overwrite a newer edit
    assert client.put(url, json={**edit, "rating": "not_useful"}).status_code == 409
    assert client.put(path(other, alert), json=body).status_code == 404
    with Session(db_engine) as db:
        assert len(db.exec(select(PositionAlertFeedback)).all()) == 1
        assert db.get(Trade, trade).realized_pnl == pnl
        # The stored alert's trade ID is deliberately obsolete; source identity still binds it.
        assert db.get(PositionAlert, alert).trade_id == UUID(int=0)
        _rebuild_trades(db, "test")
        db.commit()
        current = db.exec(select(Trade).where(Trade.ticker == "SNDK")).one().id
        after = exit_habits.build(db)
        assert after["feedback"] == {"total": 1, "responded": 1, "unanswered": 0, "counts": {"already_aware": 1}}
        assert after["verdict"] == before["verdict"] and after["responses"] == before["responses"]
    assert client.get(f"/trades/{current}/phone-alerts").json()["alerts"][0]["feedback"] == edited


def test_a_phone_answer_button_is_the_same_one_save(case):
    """The ping's answer buttons open the trade page, which saves the rating once with base_version 0: the same row
    the desk, Close the day and Proof read. A second open of that link repeats the identical save harmlessly, and the
    other button tapped later cannot overwrite it (the page then shows the saved answer)."""
    from app.engine import position_alerts as engine_alerts
    client, db_engine, trade, _, alert = case
    with Session(db_engine) as db:
        before = exit_habits.build(db)["feedback"]
    first, second = (rating for _, rating in engine_alerts.ANSWER_ACTIONS)
    saved = client.put(path(trade, alert), json={"rating": first, "reason": None, "base_version": 0})
    assert saved.status_code == 200 and saved.json()["version"] == 1
    assert client.put(path(trade, alert), json={"rating": first, "reason": None, "base_version": 0}).json() == saved.json()
    assert client.put(path(trade, alert), json={"rating": second, "reason": None, "base_version": 0}).status_code == 409
    with Session(db_engine) as db:
        assert exit_habits.build(db)["feedback"] == {**before, "responded": 1, "unanswered": 0, "counts": {first: 1}}


@pytest.mark.parametrize("delivery", ["pending", "sending", "held", "expired"])
def test_unsent_alert_is_not_rateable(case, delivery):
    client, db_engine, trade, _, alert = case
    with Session(db_engine) as db:
        row = db.get(PositionAlert, alert)
        row.delivery = delivery
        db.add(row)
        db.commit()
    assert client.put(path(trade, alert), json={"rating": "too_late", "base_version": 0}).status_code == 409


@pytest.mark.parametrize("body", [
    {"rating": "profitable", "base_version": 0}, {"rating": "too_late", "base_version": -1},
    {"rating": "too_late", "base_version": True}, {"rating": "too_late", "base_version": 0, "reason": "x" * 501},
    {"rating": "too_late", "base_version": 0, "created_at": 123},
])
def test_invalid_feedback_is_rejected(case, body):
    client, _, trade, _, alert = case
    assert client.put(path(trade, alert), json=body).status_code == 422


def test_coverage_counts_all_alerts_including_unmatched_and_unknown_not_just_recent_list(case):
    _, db_engine, _, _, alert = case
    with Session(db_engine) as db:
        for i in range(25):
            db.add(PositionAlert(account_id=ROTH, source_key=f"missing-{i}", kind="hold_hour", generation=0,
                trade_id=UUID(int=0), contract="Fixture", contracts=1, avg_cost=100,
                detected_at=datetime(2026, 10, 21, 15, i), delivery="unknown" if i % 2 else "sent"))
        db.add(PositionAlertFeedback(alert_id=alert, rating="too_late"))
        db.commit()
        out = exit_habits.build(db)
    assert out["feedback"] == {"total": 26, "responded": 1, "unanswered": 25, "counts": {"too_late": 1}}
    assert len(out["alerts"]) < out["feedback"]["total"]


def test_owner_csrf_and_reader_boundaries(boundary):  # noqa: F811
    with Session(boundary.engine) as db:
        trade, _, alert = seed(db)
    url = path(trade, alert)
    body = {"rating": "prompted_review", "base_version": 0}
    assert boundary.public.put(url, json=body).status_code == 401
    assert boundary.owner.put(url, json=body, headers={"x-tj-csrf": "wrong"}).status_code == 403
    assert boundary.owner.put(url, json=body, headers={"origin": "https://other.invalid"}).status_code == 403
    boundary.patch.setenv("TJ_ACCESS_SAMPLE_DATA", "true")
    created = boundary.owner.post("/access/assistants", json={"identifier": "reader",
        "grants": {"symbols": ["SPY"], "run_ids": [], "journal_read": True}})
    assert created.status_code == 201
    assert signin(boundary, identifier="reader", key=created.json()["key"]).status_code == 200
    assert boundary.public.get("/stats/analytics").status_code == 200
    assert boundary.public.put(url, json=body).status_code == 403
    assert boundary.public.get(f"/trades/{trade}/phone-alerts").status_code == 403
    with Session(boundary.engine) as db:
        assert db.exec(select(PositionAlertFeedback)).all() == []
    assert boundary.owner.put(url, json=body).status_code == 200
