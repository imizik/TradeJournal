"""Keep holding check-ins: the ping card's +15m / +30m pings again then, once, while the pinged position is open."""

from datetime import UTC, date, datetime
import json
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.engine import hold_check_ins, ntfy
from app.engine.chart_math import ET
from app.engine.hold_check_ins import HoldCheckIns
from app.models import Account, DayJournalEntry, Fill, PhonePing, PositionAlert, Trade, TradeFill

ROTH = uuid.UUID(int=1)
DAY = date(2026, 11, 24)


def at(hhmm: str) -> float:
    h, m = map(int, hhmm.split(":"))
    return datetime(DAY.year, DAY.month, DAY.day, h, m, tzinfo=ET).timestamp()


def utc(stamp: float) -> datetime:
    return datetime.fromtimestamp(stamp, UTC).replace(tzinfo=None)


class Calendar:
    def hours(self, day):
        return {"status": "open", "open": 570, "close": 960}


@pytest.fixture(autouse=True)
def quiet_env(monkeypatch):
    for name in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "ALERT_APP_URL", "HOLD_CHECK_IN_PINGS", "COPILOT_ENABLED"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Account(id=ROTH, name="Roth", type="roth_ira", last4="8267", broker="robinhood"))
        db.commit()
    yield engine
    engine.dispose()


@pytest.fixture
def sent(monkeypatch):
    out = []
    monkeypatch.setenv("NTFY_URL", "https://ntfy.example/topic")
    monkeypatch.setattr(ntfy, "publish", lambda title, body, **kw: out.append((title, body, kw)))
    return out


def position(engine, status="open") -> PositionAlert:
    """An open NBIS call with one entry fill, and a give-back alert on it at 10:31."""
    from app.engine.position_alerts import anchor
    with Session(engine) as db:
        trade = Trade(account_id=ROTH, ticker="NBIS", instrument_type="option", contracts=2, option_type="call", strike=100,
                      expiration=date(2026, 12, 18), avg_entry_premium=400, total_premium_paid=800,
                      opened_at=datetime(2026, 11, 24, 9, 41), status=status)
        db.add(trade)
        db.flush()
        fill = Fill(account_id=ROTH, ticker="NBIS", instrument_type="option", side="buy_to_open", contracts=2, price=400,
                    executed_at=datetime(2026, 11, 24, 9, 41), raw_email_id="nbis-in", option_type="call", strike=100,
                    expiration=date(2026, 12, 18))
        db.add(fill)
        db.flush()
        db.add(TradeFill(trade_id=trade.id, fill_id=fill.id, role="entry"))
        db.flush()
        alert = PositionAlert(account_id=ROTH, source_key=anchor([fill]), kind="giveback", generation=1, trade_id=trade.id,
                              contract="NBIS 12/18/26 100C", contracts=2, avg_cost=400, bid=300, mark=310,
                              detected_at=utc(at("10:31")), delivery="sent")
        db.add(alert)
        db.commit()
        db.refresh(alert)
        return alert


def hold(engine, alert, held: str, minutes=15, text="Holding. Give-back ping at 10:31 AM; check again."):
    with Session(engine) as db:
        row = DayJournalEntry(operation_id=f"decision-{uuid.uuid4().hex}", day=DAY, kind="decision", text=text, symbol="NBIS",
                              created_at=utc(at(held)),
                              context_json=json.dumps(hold_check_ins.context(minutes, alert.id, None, at(held))) if minutes else None)
        db.add(row)
        db.commit()
        return row.id


def run(engine, hhmm: str):
    HoldCheckIns(engine, Calendar(), clock=lambda: at(hhmm)).run()


def test_due_check_in_pings_once_with_the_card(engine, sent):
    alert = position(engine)
    hold(engine, alert, "10:33")
    run(engine, "10:47")
    assert sent == []  # not yet
    checker = HoldCheckIns(engine, Calendar(), clock=lambda: at("10:48"))
    checker.run()
    assert len(sent) == 1
    title, body, kw = sent[0]
    assert title == "Check-in: NBIS 12/18/26 100C still open"
    assert "10:33 AM" in body and "15 minutes" in body and "give-back ping" in body
    run(engine, "10:49")  # a fresh process: the policy's claim holds it
    assert len(sent) == 1
    with Session(engine) as db:
        assert db.exec(select(PhonePing).where(PhonePing.sender == "hold_check_in")).one().decision == "sent"


def test_opens_the_ping_card_while_the_desk_is_on(engine, sent, monkeypatch):
    monkeypatch.setenv("COPILOT_ENABLED", "true")
    alert = position(engine)
    hold(engine, alert, "10:33")
    run(engine, "10:48")
    kw = sent[0][2]
    assert f"card=alert%3A{alert.id}" in kw["path"]
    assert [label for label, _ in kw["more"]] == ["Close", "Trim"]


def test_closed_position_sends_nothing(engine, sent):
    alert = position(engine, status="closed")
    hold(engine, alert, "10:33")
    run(engine, "10:48")
    assert sent == []


def test_exiting_after_the_hold_cancels_it(engine, sent):
    alert = position(engine)
    hold(engine, alert, "10:33")
    hold(engine, alert, "10:40", minutes=None, text="Exiting. Give-back ping at 10:31 AM; copied close all 2 at bid 3.00.")
    run(engine, "10:48")
    assert sent == []


def test_a_newer_hold_on_the_same_ping_replaces_the_older(engine, sent):
    alert = position(engine)
    hold(engine, alert, "10:33", minutes=15)
    hold(engine, alert, "10:35", minutes=30)
    run(engine, "10:48")
    assert sent == []
    run(engine, "11:05")
    assert len(sent) == 1 and "30 minutes" in sent[0][1]


def test_too_late_or_after_the_close_sends_nothing(engine, sent):
    alert = position(engine)
    hold(engine, alert, "10:33")
    run(engine, "11:00")  # 12 minutes past: a restart does not send it late
    assert sent == []
    hold(engine, alert, "15:50")
    run(engine, "16:05")
    assert sent == []


def test_route_saves_the_check_in_and_the_card_says_whether_it_pings(engine, monkeypatch):
    from app.database import get_session
    from app.main import app

    def session():
        with Session(engine) as db:
            yield db
    alert = position(engine)
    app.dependency_overrides[get_session] = session
    try:
        client = TestClient(app)
        base = {"operation_id": "decision-x", "kind": "decision", "text": "Holding. Give-back; check again.", "symbol": "NBIS"}
        bad = client.post(f"/day-journal/{DAY}/entries", json={**base, "check_in": {"minutes": 20, "alert": str(alert.id)}})
        assert bad.status_code == 422
        neither = client.post(f"/day-journal/{DAY}/entries", json={**base, "check_in": {"minutes": 15}})
        assert neither.status_code == 422
        ok = client.post(f"/day-journal/{DAY}/entries", json={**base, "check_in": {"minutes": 30, "alert": str(alert.id)}})
        assert ok.status_code == 200
        with Session(engine) as db:
            row = db.exec(select(DayJournalEntry).where(DayJournalEntry.operation_id == "decision-x")).one()
            saved = json.loads(row.context_json)["check_in"]
        assert saved["minutes"] == 30 and saved["alert"] == str(alert.id) and saved["interrupt"] is None
        monkeypatch.setenv("COPILOT_ENABLED", "true")
        from app.ai import copilot
        monkeypatch.setattr(copilot, "settings", lambda: type("S", (), {"enabled": True})())
        assert client.get(f"/copilot/desk/ping-card?alert={alert.id}").json()["check_in_pings"] is False
        monkeypatch.setenv("HOLD_CHECK_IN_PINGS", "true")
        assert client.get(f"/copilot/desk/ping-card?alert={alert.id}").json()["check_in_pings"] is True
    finally:
        app.dependency_overrides.pop(get_session, None)
