"""The alert scorecard (app/engine/alert_scorecard.py): each sent position alert, the decision logged after it, and
what its contracts fetched against selling at the alert's bid."""
from datetime import UTC, date, datetime
import uuid

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.engine import alert_scorecard
from app.models import Account, DayJournalEntry, Fill, PositionAlert, Trade, TradeFill

ROTH = uuid.UUID("00000000-0000-4000-8000-000000000001")
NOW = datetime(2026, 10, 28, 20, 0, tzinfo=UTC).timestamp()  # 16:00 New York


def utc(day: int, hour: int, minute: int = 0) -> datetime:
    """A naive UTC time for a New York (EDT) wall clock on Oct ``day``, as alerts and journal entries store it."""
    return datetime(2026, 10, day, hour + 4, minute)


def ny(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute)


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Account(id=ROTH, name="Roth", type="roth_ira", last4="8267", broker="robinhood"))
        session.commit()
        yield session
    engine.dispose()


def position(db, ticker, buys, sells=(), status="open", closed_at=None, side="buy_to_open"):
    """A traded option: entry fills (contracts, premium per contract, NY time) and exit fills after them."""
    trade = Trade(account_id=ROTH, ticker=ticker, instrument_type="option", contracts=sum(b[0] for b in buys), option_type="call",
                  strike=100, expiration=date(2026, 11, 21), avg_entry_premium=buys[0][1], total_premium_paid=sum(b[0] * b[1] for b in buys),
                  opened_at=buys[0][2], closed_at=closed_at, status=status)
    db.add(trade)
    db.flush()
    for i, (qty, price, at) in enumerate(buys):
        fill = Fill(account_id=ROTH, ticker=ticker, instrument_type="option", side=side, contracts=qty, price=price, executed_at=at,
                    raw_email_id=f"{ticker}-in-{i}-{uuid.uuid4().hex[:6]}", option_type="call", strike=100, expiration=date(2026, 11, 21))
        db.add(fill)
        db.flush()
        db.add(TradeFill(trade_id=trade.id, fill_id=fill.id, role="entry"))
    for i, (qty, price, at) in enumerate(sells):
        fill = Fill(account_id=ROTH, ticker=ticker, instrument_type="option", side="sell_to_close", contracts=qty, price=price, executed_at=at,
                    raw_email_id=f"{ticker}-out-{i}-{uuid.uuid4().hex[:6]}", option_type="call", strike=100, expiration=date(2026, 11, 21))
        db.add(fill)
        db.flush()
        db.add(TradeFill(trade_id=trade.id, fill_id=fill.id, role="exit"))
    db.commit()
    from app.engine.position_alerts import anchor
    from sqlmodel import select
    entries = db.exec(select(Fill).join(TradeFill, TradeFill.fill_id == Fill.id).where(TradeFill.trade_id == trade.id, TradeFill.role == "entry")).all()
    return trade, anchor(entries)


def alert(db, trade, key, at, contracts, bid, kind="giveback", delivery="sent", mark=None, gain_pct=-0.25):
    row = PositionAlert(account_id=ROTH, source_key=key, kind=kind, generation=1, trade_id=trade.id, contract=f"{trade.ticker} 11/21/26 100C",
                        contracts=contracts, avg_cost=400, mark=mark if mark is not None else bid, bid=bid, gain_pct=gain_pct,
                        detected_at=at, delivery=delivery)
    db.add(row)
    db.commit()
    return row


def decide(db, symbol, text, at):
    db.add(DayJournalEntry(operation_id=f"decision-{uuid.uuid4().hex}", day=date(2026, 10, at.day), kind="decision", text=text,
                           symbol=symbol, created_at=at))
    db.commit()


def test_held_past_the_alert_and_sold_higher_counts_as_better(db):
    trade, key = position(db, "NBIS", [(2, 400, ny(27, 9, 41))], [(2, 520, ny(28, 11, 5))], status="closed", closed_at=ny(28, 11, 5))
    alert(db, trade, key, utc(27, 10, 31), contracts=2, bid=300)
    decide(db, "NBIS", "Holding. Give-back fired at 10:31; plan says hold above 85.00 (3.1% above).", utc(27, 10, 44))
    card = alert_scorecard.scorecard(db, NOW)
    [row] = card["rows"]
    assert row["decision"] == "holding" and row["pnl_pct_at_alert"] == -25.0
    assert row["outcome"] == {"state": "closed", "how": "sold", "sell_at_alert_usd": 600.0, "basis": "bid", "actual_usd": 1040.0,
                              "vs_alert_usd": 440.0, "ended_at": int(ny(28, 11, 5).replace(tzinfo=alert_scorecard.ET).timestamp())}
    assert card["summary"]["holding"] == {"alerts": 1, "closed": 1, "better": 1, "worse": 0, "even": 0, "open": 0, "not_measured": 0, "vs_alert_usd": 440.0}


def test_held_into_a_worthless_expiry_loses_what_the_bid_would_have_fetched(db):
    trade, key = position(db, "APLD", [(3, 200, ny(20, 10))], status="expired", closed_at=ny(24, 16))
    alert(db, trade, key, utc(23, 14), contracts=3, bid=35)
    decide(db, "APLD", "Holding. Give-back fired at 14:00.", utc(23, 14, 5))
    [row] = alert_scorecard.scorecard(db, NOW)["rows"]
    assert row["outcome"]["state"] == "closed" and row["outcome"]["how"] == "expired"
    assert row["outcome"]["actual_usd"] == 0 and row["outcome"]["vs_alert_usd"] == -105.0


def test_only_sells_after_the_alert_count_and_fifo_takes_the_alert_s_contracts_first(db):
    # One contract sold before the alert, two seen open at it; then three sold after (one more bought after the alert).
    trade, key = position(db, "CRWV", [(3, 300, ny(21, 10)), (1, 350, ny(22, 15))],
                          [(1, 330, ny(22, 10)), (2, 360, ny(23, 10)), (1, 380, ny(23, 11))], status="closed", closed_at=ny(23, 11))
    alert(db, trade, key, utc(22, 12), contracts=2, bid=310)
    decide(db, "CRWV", "Exiting. Give-back fired at 12:00.", utc(22, 12, 2))
    [row] = alert_scorecard.scorecard(db, NOW)["rows"]
    assert row["decision"] == "exiting"
    assert row["outcome"]["sell_at_alert_usd"] == 620.0 and row["outcome"]["actual_usd"] == 720.0 and row["outcome"]["vs_alert_usd"] == 100.0


def test_a_position_still_open_is_open_and_unsent_alerts_do_not_count(db):
    trade, key = position(db, "IREN", [(4, 150, ny(27, 9, 35))], [(1, 170, ny(27, 13))])
    alert(db, trade, key, utc(27, 11), contracts=4, bid=120)
    alert(db, trade, key, utc(27, 12), contracts=4, bid=110, kind="hold_hour", delivery="held")
    card = alert_scorecard.scorecard(db, NOW)
    [row] = card["rows"]
    assert row["decision"] is None
    assert row["outcome"] == {"state": "open", "sell_at_alert_usd": 480.0, "basis": "bid", "sold_so_far_usd": 170.0, "contracts_left": 3.0}
    assert card["summary"]["none"]["open"] == 1 and card["summary"]["none"]["closed"] == 0


def test_a_decision_belongs_to_the_alert_before_it_not_an_earlier_one(db):
    trade, key = position(db, "NBIS", [(1, 400, ny(27, 9, 41))], [(1, 450, ny(28, 10))], status="closed", closed_at=ny(28, 10))
    alert(db, trade, key, utc(27, 10, 31), contracts=1, bid=300, kind="giveback")
    alert(db, trade, key, utc(27, 14, 30), contracts=1, bid=280, kind="expiry_first")
    decide(db, "NBIS", "Exiting. Expires today.", utc(27, 14, 35))
    rows = alert_scorecard.scorecard(db, NOW)["rows"]
    assert [(r["kind"], r["decision"]) for r in rows] == [("expiry_first", "exiting"), ("giveback", None)]


def test_a_rebuilt_trade_is_found_by_its_position_and_bad_rows_are_not_measured(db):
    trade, key = position(db, "MU", [(1, 500, ny(26, 10))], [(1, 600, ny(27, 10))], status="closed", closed_at=ny(27, 10))
    row = alert(db, trade, key, utc(26, 12), contracts=1, bid=450)
    row.trade_id = uuid.uuid4()  # the trade was rebuilt under a new id
    db.commit()
    short, short_key = position(db, "AMD", [(1, 300, ny(26, 10))], side="sell_to_open")
    alert(db, short, short_key, utc(26, 13), contracts=1, bid=250)
    unpriced, unpriced_key = position(db, "SOUN", [(1, 100, ny(26, 10))])
    alert(db, unpriced, unpriced_key, utc(26, 14), contracts=1, bid=None, mark=None)
    by = {r["symbol"]: r["outcome"] for r in alert_scorecard.scorecard(db, NOW)["rows"]}
    assert by["MU"]["state"] == "closed" and by["MU"]["vs_alert_usd"] == 150.0
    assert by["AMD"] == {"state": "not_measured", "why": "a short position"}
    assert by["SOUN"] == {"state": "not_measured", "why": "no price at the alert"}


def test_alerts_older_than_the_window_are_left_out(db):
    trade, key = position(db, "NBIS", [(1, 400, ny(1, 10))])
    alert(db, trade, key, utc(1, 11), contracts=1, bid=300)  # 27 days before NOW
    assert alert_scorecard.scorecard(db, NOW)["alerts"] == 1
    assert alert_scorecard.scorecard(db, NOW, days=20)["alerts"] == 0


def test_the_route_refuses_while_the_lab_is_off_and_reads_the_card_while_it_is_on(db, monkeypatch):
    from types import SimpleNamespace
    from fastapi import HTTPException
    from app.routers import copilot_desk
    monkeypatch.setattr(copilot_desk.copilot, "settings", lambda: SimpleNamespace(enabled=False))
    with pytest.raises(HTTPException) as refused:
        copilot_desk.desk_scorecard(db)
    assert refused.value.status_code == 503
    monkeypatch.setattr(copilot_desk.copilot, "settings", lambda: SimpleNamespace(enabled=True))
    monkeypatch.setattr(copilot_desk.today, "_now", lambda: NOW)
    monkeypatch.delenv("RADAR_ENABLED", raising=False)
    card = copilot_desk.desk_scorecard(db)
    assert card.pop("radar") == {"state": "off", "reason": "Radar recording is not switched on."}
    assert card == {"window_days": 30, "alerts": 0, "summary": {
        k: {"alerts": 0, "closed": 0, "better": 0, "worse": 0, "even": 0, "open": 0, "not_measured": 0, "vs_alert_usd": 0}
        for k in ("holding", "exiting", "none")}, "rows": [], "truncated": False}


def test_a_decision_only_answers_an_alert_on_its_own_new_york_day(db):
    trade, key = position(db, "NBIS", [(1, 400, ny(27, 9, 41))], [(1, 450, ny(29, 10))], status="closed", closed_at=ny(29, 10))
    alert(db, trade, key, utc(27, 10, 31), contracts=1, bid=300)
    decide(db, "NBIS", "Holding. A later thought about another position.", utc(28, 10, 0))
    [row] = alert_scorecard.scorecard(db, NOW)["rows"]
    assert row["decision"] is None


def test_a_sell_in_the_alert_s_own_minute_counts(db):
    trade, key = position(db, "NBIS", [(1, 400, ny(27, 9, 41))], [(1, 320, ny(27, 10, 31))], status="closed", closed_at=ny(27, 10, 31))
    alert(db, trade, key, datetime(2026, 10, 27, 14, 31, 30), contracts=1, bid=300)  # 10:31:30 New York
    [row] = alert_scorecard.scorecard(db, NOW)["rows"]
    assert row["outcome"]["state"] == "closed" and row["outcome"]["vs_alert_usd"] == 20.0


def test_a_failed_desk_link_read_still_sends_the_alert_to_the_trade_page(db, monkeypatch):
    from types import SimpleNamespace
    from app.engine import position_alerts
    monkeypatch.setenv("COPILOT_ENABLED", "true")
    monkeypatch.setattr(position_alerts, "desk_path", lambda own, alert: (_ for _ in ()).throw(RuntimeError("db went away")))
    row = SimpleNamespace(trade_id=uuid.uuid4(), id=uuid.uuid4(), contract="NBIS 11/21/26 100C", kind="giveback",
                          peak_gain=None, gain=None, mark=None, detected_at=datetime(2026, 10, 27, 14, 31))
    path, more = position_alerts._links(db, row)
    assert path == f"/trades/{row.trade_id}?alert={row.id}"
    assert db.exec(__import__("sqlmodel").select(Account)).first() is not None  # the caller's session still works
