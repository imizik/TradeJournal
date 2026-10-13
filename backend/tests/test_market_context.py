"""Earnings and VIX snapshot for the pre-trade check: symbols, replacement and failures kept honest."""
from datetime import date, datetime, timezone
import json
import uuid

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.engine import market_context
from app.engine.tradier import TradierQuote
from app.models import Account, ChartSettingsRecord, MarketContextItem, Trade

NOW = datetime(2026, 10, 13, 13, 0, tzinfo=timezone.utc)  # 09:00 New York.


def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def trade(session, account, ticker, *, status="closed", opened=datetime(2026, 10, 1, 10, 0)):
    session.add(Trade(account_id=account.id, ticker=ticker, instrument_type="option", option_type="call", contracts=1, avg_entry_premium=1, total_premium_paid=100,
                      opened_at=opened, status=status))


def seeded():
    session = db()
    roth = Account(id=uuid.uuid4(), name="Roth IRA", type="roth_ira", last4="0000", broker="robinhood")
    webull = Account(id=uuid.uuid4(), name="Webull", type="individual", last4="1111", broker="webull")
    session.add_all([roth, webull])
    trade(session, roth, "APLD", status="open")
    trade(session, roth, "NBIS", opened=datetime(2026, 10, 10, 10, 0))
    trade(session, roth, "SPY", opened=datetime(2026, 10, 9, 10, 0))
    trade(session, roth, "OLD", opened=datetime(2026, 8, 1, 10, 0))
    trade(session, webull, "TSLA", status="open")
    session.add(ChartSettingsRecord(name="default", data_json=json.dumps({"watchlist": ["mu", "NBIS", 7]})))
    session.commit()
    return session


def facts(symbols, today):
    assert today == date(2026, 10, 13)
    table = {"APLD": {"state": "ready", "next": {"date": "2026-10-15", "status": "confirmed", "label": "Q1 2027"}},
             "NBIS": {"state": "none", "next": None},
             "MU": {"state": "ready", "next": {"date": "2026-12-17", "status": "estimated", "label": "Q1 2027"}}}
    return {symbol: {"earnings": table[symbol]} for symbol in symbols if symbol in table}


def vix(symbols):
    return {"VIX": TradierQuote(symbol="VIX", last=15.21, trade_date=1791836101318, raw={"prevclose": 14.5})}


def test_symbols_held_recent_then_watchlist_without_webull_or_stale():
    session = seeded()
    assert market_context.tracked_symbols(session, date(2026, 10, 13)) == ["APLD", "NBIS", "SPY", "MU"]


def test_refresh_replaces_the_snapshot_and_keeps_rows_a_failed_read_could_not_replace():
    session = seeded()
    written, summary = market_context.refresh(session, facts=facts, quotes=vix, clock=lambda: NOW)
    rows = {(r.kind, r.symbol): r for r in session.exec(select(MarketContextItem)).all()}
    assert written == 3 and summary.startswith("3 rows for 4 symbols")
    assert rows[("earnings", "APLD")].event_date == date(2026, 10, 15) and rows[("earnings", "APLD")].status == "confirmed"
    assert ("earnings", "NBIS") not in rows and ("earnings", "SPY") not in rows  # No upcoming date; a fund.
    assert rows[("vix", "VIX")].value == 15.21 and rows[("vix", "VIX")].change_pct == 4.9
    assert rows[("vix", "VIX")].fetched_at == datetime(2026, 10, 13, 13, 0)
    # Calendar down and VIX missing: nothing is replaced, and the summary says why.
    def down(symbols, today):
        return {s: {"earnings": {"state": "unavailable", "message": "rate limited"}} for s in symbols}
    written, summary = market_context.refresh(session, facts=down, quotes=lambda s: {}, clock=lambda: NOW)
    assert written == 0 and "earnings calendar unavailable (rate limited)" in summary and "VIX quote unavailable" in summary
    assert len(session.exec(select(MarketContextItem)).all()) == 3
