"""The owner's record for a new option plan's setup: opening option trades by gap and 20-day trend at entry, and size.
Read-only, from the journal; today's context from daily bars. No network."""

from datetime import date, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.engine import setup_record
from app.engine.chart_math import ET
from app.models import Account, Fill, FillMarketContext, Trade, TradeFill

ROTH, WEBULL = UUID(int=1), UUID(int=2)
TODAY = date(2026, 10, 29)


@pytest.fixture
def engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Account(id=ROTH, name="Roth", type="roth_ira", last4="1111", broker="robinhood"))
        db.add(Account(id=WEBULL, name="Webull", type="individual", last4="0001", broker="webull"))
        db.commit()
    yield engine
    engine.dispose()


def closed(db, side, pnl, *, opened="2026-09-01T09:45", gap=None, price=None, sma=None, premium=500.0, account=ROTH,
           status="closed", context=True):
    """One closed option trade with its entry fill and, by default, the fill's market context."""
    trade = Trade(account_id=account, ticker="NBIS", instrument_type="option", option_type=side, contracts=1,
                  avg_entry_premium=premium, total_premium_paid=premium, realized_pnl=pnl,
                  opened_at=datetime.fromisoformat(opened), status=status)
    db.add(trade)
    fill = Fill(id=uuid4(), account_id=account, ticker="NBIS", instrument_type="option", side="buy_to_open", contracts=1,
                price=premium, executed_at=datetime.fromisoformat(opened), raw_email_id=f"gmail:{uuid4().hex}",
                option_type=side, strike=100, expiration=date(2026, 9, 4))
    db.add(fill)
    db.flush()
    db.add(TradeFill(trade_id=trade.id, fill_id=fill.id, role="entry"))
    if context:
        db.add(FillMarketContext(fill_id=fill.id, data_source="alpaca_sip", fetched_at=datetime(2026, 9, 1),
                                 entry_gap_pct=gap, entry_underlying_price=price, entry_sma_20=sma))


def test_cohorts_follow_todays_gap_and_trend_for_each_side(engine):
    with Session(engine) as db:
        for i in range(5):  # calls against a gap down, below the 20-day: 4 of 5 won
            closed(db, "call", 200.0 if i else -100.0, gap=-2.0, price=95.0, sma=100.0)
        for i in range(5):  # calls with a gap up, above the 20-day: 1 of 5 won
            closed(db, "call", -50.0 if i else 80.0, gap=1.5, price=105.0, sma=100.0)
        for _ in range(5):  # puts after a gap down: with the gap for a put, below the 20-day: with the trend
            closed(db, "put", -300.0, gap=-1.2, price=90.0, sma=100.0)
        closed(db, "call", 9999.0, opened="2026-09-01T10:30", gap=-2.0, price=95.0, sma=100.0)  # after the first hour
        closed(db, "call", 9999.0, gap=-2.0, price=95.0, sma=100.0, account=WEBULL)              # Webull: dormant
        closed(db, "call", 9999.0, gap=-2.0, price=95.0, sma=100.0, status="open")               # still open
        closed(db, "call", 9999.0, context=False)                                                 # no context: no cohort
        db.commit()
        trades = setup_record.opening_trades(db)
    assert len(trades) == 16
    found = setup_record.record(trades, gap_pct=-3.1, vs_sma_pct=-4.0)
    assert found["calls"]["gap"] == {"relation": "against", "record": {"trades": 5, "won": 4, "pnl": 700.0}}
    assert found["calls"]["trend"] == {"relation": "against", "record": {"trades": 5, "won": 4, "pnl": 700.0}}
    assert found["puts"]["gap"] == {"relation": "with", "record": {"trades": 5, "won": 0, "pnl": -1500.0}}
    assert found["puts"]["trend"] == {"relation": "with", "record": {"trades": 5, "won": 0, "pnl": -1500.0}}
    small = setup_record.record(trades, gap_pct=0.4, vs_sma_pct=None)
    assert small["calls"]["gap"] == {"relation": "small", "record": None}  # no small-gap calls: too thin to show
    assert small["calls"]["trend"] is None and small["puts"]["trend"] is None  # today's trend unknown: no line


def test_the_size_record_needs_twenty_trades_and_counts_the_top_quarter(engine):
    with Session(engine) as db:
        for i in range(19):
            closed(db, "call", 100.0 if i < 10 else -100.0, premium=100.0 * (i + 1))
        db.commit()
        assert setup_record.record(setup_record.opening_trades(db), None, None)["size"] is None
        closed(db, "put", -700.0, premium=2000.0)
        db.commit()
        size = setup_record.record(setup_record.opening_trades(db), None, None)["size"]
    # premiums 100..1900 and 2000: median 1050, the top quarter from the 16th smallest (1600)
    assert size == {"usual": 1050.0, "top_quarter_from": 1600.0, "top_quarter": {"trades": 5, "won": 0, "pnl": -1100.0}}


def bar(day, open_, close):
    return {"time": int(datetime(day.year, day.month, day.day, 9, 30, tzinfo=ET).timestamp()), "open": open_, "close": close}


def test_todays_context_from_daily_bars():
    prior = [bar(date(2026, 9, 1 + i), 100.0, 100.0 + i) for i in range(20)]  # closes 100..119: average 109.5
    today = setup_record.today_context(prior + [bar(TODAY, 116.62, 115.0)], TODAY)
    assert today == {"gap_pct": -2.0, "vs_sma_pct": round((115.0 / 109.5 - 1) * 100, 2)}
    before_open = setup_record.today_context(prior, TODAY)
    assert before_open == {"gap_pct": None, "vs_sma_pct": round((119.0 / 109.5 - 1) * 100, 2)}
    assert setup_record.today_context(prior[-5:], TODAY) == {"gap_pct": None, "vs_sma_pct": None}  # under 20 days
    assert setup_record.today_context([], TODAY) == {"gap_pct": None, "vs_sma_pct": None}


def test_a_failed_daily_read_leaves_only_the_size_record(engine):
    def broken(symbol):
        raise RuntimeError("feed down")
    with Session(engine) as db:
        found = setup_record.for_symbol(db, "NBIS", datetime(2026, 10, 29, 10, tzinfo=ET).timestamp(), daily=broken)
    assert found == {"gap_pct": None, "vs_sma_pct": None, "calls": {"gap": None, "trend": None},
                     "puts": {"gap": None, "trend": None}, "size": None}
