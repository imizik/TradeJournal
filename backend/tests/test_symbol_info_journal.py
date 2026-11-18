"""Tests for the read-only symbol journal adapter (app/engine/symbol_info_journal.py)."""

from datetime import date, datetime
import uuid

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.engine.symbol_info_journal import read_journal
from app.models import Account, Fill, Trade

ROTH = uuid.UUID("00000000-0000-4000-8000-000000000001")
INDIVIDUAL = uuid.UUID("00000000-0000-4000-8000-000000000002")


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Account(id=ROTH, name="Roth", type="roth_ira", last4="8267", broker="robinhood"))
        session.commit()
        yield session
    engine.dispose()


def _trade(
    account_id: uuid.UUID,
    ticker: str,
    *,
    status: str = "closed",
    instrument_type: str = "option",
    option_type: str | None = "call",
    strike: float | None = 100.0,
    expiration: date | None = date(2026, 11, 21),
    realized_pnl: float | None = None,
    hold_duration_mins: int | None = None,
    opened_at: datetime = datetime(2026, 10, 27, 9, 30),
    closed_at: datetime | None = datetime(2026, 10, 27, 10, 30),
) -> Trade:
    return Trade(
        account_id=account_id,
        ticker=ticker,
        instrument_type=instrument_type,
        contracts=1,
        option_type=option_type,
        strike=strike,
        expiration=expiration,
        avg_entry_premium=200.0,
        total_premium_paid=200.0,
        realized_pnl=realized_pnl,
        hold_duration_mins=hold_duration_mins,
        opened_at=opened_at,
        closed_at=closed_at,
        status=status,
    )


def _fill(account_id: uuid.UUID, ticker: str, executed_at: datetime, raw_email_id: str) -> Fill:
    return Fill(
        account_id=account_id,
        ticker=ticker,
        instrument_type="option",
        side="buy_to_open",
        contracts=1,
        price=200.0,
        executed_at=executed_at,
        raw_email_id=raw_email_id,
        option_type="call",
        strike=100.0,
        expiration=date(2026, 11, 21),
    )


def test_empty_symbol_returns_zero_summary_and_metadata(db):
    result = read_journal(db, "IWM")

    assert result["symbol"] == "IWM"
    assert result["total_trades"] == 0
    assert result["closed_trades"] == 0
    assert result["missing_pnl"] == 0
    assert result["realized_pnl"] is None
    assert result["win_rate"] is None
    assert result["average_hold_mins"] is None
    assert result["hold_samples"] == 0
    assert result["best_trade"] is None
    assert result["worst_trade"] is None
    assert result["last_traded_at"] is None
    assert result["open_positions"] == []
    assert result["recent_trades"] == []
    assert result["source"] == "Journal · all accounts"
    assert result["time_zone"] == "America/New_York"
    parsed_as_of = datetime.fromisoformat(result["as_of"])
    assert parsed_as_of.tzinfo is not None


def test_includes_trades_across_accounts_and_excludes_other_symbols(db):
    db.add(Account(id=INDIVIDUAL, name="Individual", type="individual", last4="1234", broker="robinhood"))
    roth_nvda = _trade(ROTH, "NVDA", status="closed", realized_pnl=150.0, hold_duration_mins=45)
    ind_nvda = _trade(
        INDIVIDUAL,
        "NVDA",
        status="open",
        realized_pnl=None,
        hold_duration_mins=None,
        opened_at=datetime(2026, 10, 28, 10, 0),
        closed_at=None,
    )
    other_spy = _trade(ROTH, "SPY", status="closed", realized_pnl=999.0, hold_duration_mins=120)
    db.add_all([roth_nvda, ind_nvda, other_spy])
    db.commit()

    result = read_journal(db, "NVDA")

    assert result["symbol"] == "NVDA"
    assert result["total_trades"] == 2
    assert result["closed_trades"] == 1
    assert result["realized_pnl"] == 150.0
    assert result["win_rate"] == 1.0
    assert result["average_hold_mins"] == 45.0
    assert result["hold_samples"] == 1
    assert {t["id"] for t in result["recent_trades"]} == {str(roth_nvda.id), str(ind_nvda.id)}
    assert {t["account_name"] for t in result["recent_trades"]} == {"Roth", "Individual"}
    assert [t["id"] for t in result["open_positions"]] == [str(ind_nvda.id)]
    assert str(other_spy.id) not in {t["id"] for t in result["recent_trades"]}


def test_last_traded_at_uses_latest_fill_for_symbol_and_ignores_closed_at_and_other_symbols(db):
    nvda_trade = _trade(
        ROTH,
        "NVDA",
        status="expired",
        realized_pnl=-200.0,
        opened_at=datetime(2026, 10, 20, 9, 30),
        closed_at=datetime(2026, 10, 24, 16, 0),
    )
    db.add(nvda_trade)
    db.add_all([
        _fill(ROTH, "NVDA", datetime(2026, 10, 20, 9, 30), "nvda-fill-1"),
        _fill(ROTH, "NVDA", datetime(2026, 10, 21, 14, 15), "nvda-fill-2"),
        _fill(ROTH, "QQQ", datetime(2026, 10, 28, 15, 45), "qqq-fill-1"),
    ])
    db.commit()

    result = read_journal(db, "NVDA")

    assert result["last_traded_at"] == "2026-10-21T14:15:00"


def test_serializes_uuid_and_date_fields_to_iso_strings_and_preserves_none(db):
    open_option = _trade(
        ROTH,
        "AAPL",
        status="open",
        instrument_type="option",
        option_type="call",
        strike=220.0,
        expiration=date(2026, 11, 21),
        realized_pnl=None,
        hold_duration_mins=None,
        opened_at=datetime(2026, 10, 27, 9, 45),
        closed_at=None,
    )
    closed_stock = _trade(
        ROTH,
        "AAPL",
        status="closed",
        instrument_type="stock",
        option_type=None,
        strike=None,
        expiration=None,
        realized_pnl=75.0,
        hold_duration_mins=60,
        opened_at=datetime(2026, 10, 26, 10, 30),
        closed_at=datetime(2026, 10, 26, 11, 30),
    )
    db.add_all([open_option, closed_stock])
    db.commit()

    result = read_journal(db, "AAPL")

    assert result["last_traded_at"] is None
    assert len(result["open_positions"]) == 1
    open_row = result["open_positions"][0]
    assert isinstance(open_row["id"], str) and open_row["id"] == str(open_option.id)
    assert isinstance(open_row["account_id"], str) and open_row["account_id"] == str(ROTH)
    assert open_row["expiration"] == "2026-11-21"
    assert open_row["opened_at"] == "2026-10-27T09:45:00"
    assert open_row["closed_at"] is None

    closed_row = result["best_trade"]
    assert closed_row is not None
    assert isinstance(closed_row["id"], str) and closed_row["id"] == str(closed_stock.id)
    assert isinstance(closed_row["account_id"], str) and closed_row["account_id"] == str(ROTH)
    assert closed_row["expiration"] is None
    assert closed_row["option_type"] is None
    assert closed_row["strike"] is None
    assert closed_row["opened_at"] == "2026-10-26T10:30:00"
    assert closed_row["closed_at"] == "2026-10-26T11:30:00"
