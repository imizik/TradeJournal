"""
Tests for the FIFO reconstructor.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from app.engine.reconstructor import FillInput, reconstruct

ET = ZoneInfo("America/New_York")
ACCOUNT = uuid.uuid4()
SECOND_ACCOUNT = uuid.uuid4()


def D(value: str) -> Decimal:
    return Decimal(value)


def _fill(
    side: str,
    contracts: str,
    price: str,
    executed_at: datetime,
    instrument_type: str = "option",
    ticker: str = "NVDA",
    option_type: str = "call",
    strike: str = "500",
    expiration: date = date(2026, 3, 28),
) -> FillInput:
    return FillInput(
        id=uuid.uuid4(),
        account_id=ACCOUNT,
        ticker=ticker,
        instrument_type=instrument_type,
        side=side,
        contracts=D(contracts),
        price=D(price),
        executed_at=executed_at,
        option_type=option_type,
        strike=D(strike),
        expiration=expiration,
    )


def _dt(hour: int, minute: int = 0, day: int = 1) -> datetime:
    return datetime(2026, 3, day, hour, minute, tzinfo=ET)


def test_simple_round_trip():
    fills = [
        _fill("buy_to_open", "2", price="100.0", executed_at=_dt(10, 0)),
        _fill("sell_to_close", "2", price="150.0", executed_at=_dt(11, 0)),
    ]
    result = reconstruct(fills, today=date(2026, 3, 29))

    assert len(result.trades) == 1
    t = result.trades[0]
    assert t.status == "closed"
    assert t.contracts == D("2.000000")
    assert t.avg_entry_premium == D("100.000000")
    assert t.avg_exit_premium == D("150.000000")
    assert t.realized_pnl == D("100.000000")
    assert t.pnl_pct == D("0.5000")
    assert t.hold_duration_mins == 60

    tf_roles = {tf.fill_id: tf.role for tf in result.trade_fills}
    assert tf_roles[fills[0].id] == "entry"
    assert tf_roles[fills[1].id] == "exit"


def test_trade_id_is_stable_from_first_entry_fill():
    fills = [
        _fill("buy_to_open", "2", price="100.0", executed_at=_dt(10, 0)),
        _fill("sell_to_close", "2", price="150.0", executed_at=_dt(11, 0)),
    ]

    result_a = reconstruct(fills, today=date(2026, 3, 29))
    result_b = reconstruct(fills, today=date(2026, 3, 29))

    assert result_a.trades[0].id == fills[0].id
    assert result_b.trades[0].id == fills[0].id
    assert result_a.trade_fills[0].trade_id == fills[0].id
    assert result_b.trade_fills[0].trade_id == fills[0].id


def test_partial_exit():
    fills = [
        _fill("buy_to_open", "4", price="100.0", executed_at=_dt(10, 0)),
        _fill("sell_to_close", "2", price="120.0", executed_at=_dt(11, 0)),
        _fill("sell_to_close", "2", price="130.0", executed_at=_dt(12, 0)),
    ]
    result = reconstruct(fills, today=date(2026, 3, 29))

    assert len(result.trades) == 1
    t = result.trades[0]
    assert t.status == "closed"
    assert t.realized_pnl == D("100.000000")
    assert len(result.trade_fills) == 3


def test_scale_in():
    fills = [
        _fill("buy_to_open", "2", price="100.0", executed_at=_dt(10, 0)),
        _fill("buy_to_open", "2", price="200.0", executed_at=_dt(10, 30)),
        _fill("sell_to_close", "4", price="200.0", executed_at=_dt(11, 0)),
    ]
    result = reconstruct(fills, today=date(2026, 3, 29))

    t = result.trades[0]
    assert t.avg_entry_premium == D("150.000000")
    assert t.realized_pnl == D("200.000000")


def test_expired_worthless():
    exp = date(2026, 3, 25)
    fills = [
        _fill("buy_to_open", "1", price="500.0", executed_at=_dt(9, 45), expiration=exp),
    ]
    result = reconstruct(fills, today=date(2026, 3, 29))

    t = result.trades[0]
    assert t.status == "expired"
    assert t.expired_worthless is True
    assert t.realized_pnl == D("-500.000000")
    assert t.pnl_pct == D("-1.0000")
    assert t.closed_at is not None
    assert t.closed_at.hour == 16
    assert t.closed_at.date() == exp


def test_different_strikes_separate_trades():
    future_exp = date(2026, 12, 31)
    fills = [
        _fill("buy_to_open", "1", price="100.0", executed_at=_dt(10, 0), strike="500.0", expiration=future_exp),
        _fill("buy_to_open", "1", price="50.0", executed_at=_dt(10, 5), strike="510.0", expiration=future_exp),
    ]
    result = reconstruct(fills, today=date(2026, 3, 29))

    assert len(result.trades) == 2
    strikes = {t.strike for t in result.trades}
    assert strikes == {D("500.0"), D("510.0")}
    assert all(t.status == "open" for t in result.trades)


def test_open_trade_not_expired():
    future_exp = date(2026, 12, 31)
    fills = [
        _fill("buy_to_open", "2", price="100.0", executed_at=_dt(10, 0), expiration=future_exp),
    ]
    result = reconstruct(fills, today=date(2026, 3, 29))

    assert len(result.trades) == 1
    assert result.trades[0].status == "open"
    assert result.trades[0].realized_pnl is None


def test_time_buckets():
    exp = date(2026, 12, 31)
    cases = [
        (_dt(9, 35), "open"),
        (_dt(10, 0), "mid"),
        (_dt(14, 59), "mid"),
        (_dt(15, 0), "close"),
        (_dt(15, 59), "close"),
    ]
    for dt, expected_bucket in cases:
        fills = [_fill("buy_to_open", "1", price="100.0", executed_at=dt, expiration=exp, strike=str(dt.hour * 100))]
        result = reconstruct(fills, today=date(2026, 3, 29))
        assert result.trades[0].entry_time_bucket == expected_bucket


def test_orphaned_close_is_reported():
    fills = [
        _fill("sell_to_close", "1", price="100.0", executed_at=_dt(11, 0)),
    ]
    result = reconstruct(fills, today=date(2026, 3, 29))
    assert result.trades == []
    assert result.trade_fills == []
    assert len(result.anomalies) == 1


def test_fractional_stock_round_trip_keeps_share_precision():
    fills = [
        FillInput(
            id=uuid.uuid4(),
            account_id=ACCOUNT,
            ticker="RCAT",
            instrument_type="stock",
            side="buy",
            contracts=D("9.78593"),
            price=D("8.17"),
            executed_at=_dt(9, 47, 25),
        ),
        FillInput(
            id=uuid.uuid4(),
            account_id=ACCOUNT,
            ticker="RCAT",
            instrument_type="stock",
            side="sell",
            contracts=D("9.78593"),
            price=D("8.50"),
            executed_at=_dt(10, 15, 26),
        ),
    ]

    result = reconstruct(fills, today=date(2026, 3, 30))
    trade = result.trades[0]
    assert trade.instrument_type == "stock"
    assert trade.contracts == D("9.785930")
    assert trade.realized_pnl == D("3.229357")


def test_partial_stock_exit_stays_open_and_keeps_realized_pnl():
    fills = [
        FillInput(
            id=uuid.uuid4(),
            account_id=ACCOUNT,
            ticker="RNXT",
            instrument_type="stock",
            side="buy",
            contracts=D("450"),
            price=D("0.90"),
            executed_at=_dt(11, 4, 5),
        ),
        FillInput(
            id=uuid.uuid4(),
            account_id=ACCOUNT,
            ticker="RNXT",
            instrument_type="stock",
            side="buy",
            contracts=D("450"),
            price=D("0.89"),
            executed_at=_dt(11, 4, 5),
        ),
        FillInput(
            id=uuid.uuid4(),
            account_id=ACCOUNT,
            ticker="RNXT",
            instrument_type="stock",
            side="sell",
            contracts=D("450"),
            price=D("0.89"),
            executed_at=_dt(11, 4, 5),
        ),
        FillInput(
            id=uuid.uuid4(),
            account_id=ACCOUNT,
            ticker="RNXT",
            instrument_type="stock",
            side="sell",
            contracts=D("250"),
            price=D("0.96"),
            executed_at=_dt(14, 46, 16),
        ),
    ]

    result = reconstruct(fills, today=date(2026, 3, 30))
    trade = result.trades[0]
    assert trade.status == "open"
    assert trade.contracts == D("900.000000")
    assert trade.avg_exit_premium == D("0.915000")
    assert trade.realized_pnl == D("13.000000")


def test_same_contract_in_different_accounts_stays_separate():
    fills = [
        FillInput(
            id=uuid.uuid4(),
            account_id=ACCOUNT,
            ticker="GOOG",
            instrument_type="option",
            side="buy_to_open",
            contracts=D("1"),
            price=D("500"),
            executed_at=_dt(10, 42, 12),
            option_type="put",
            strike=D("290"),
            expiration=date(2026, 4, 2),
        ),
        FillInput(
            id=uuid.uuid4(),
            account_id=SECOND_ACCOUNT,
            ticker="GOOG",
            instrument_type="option",
            side="buy_to_open",
            contracts=D("1"),
            price=D("495"),
            executed_at=_dt(10, 43, 12),
            option_type="put",
            strike=D("290"),
            expiration=date(2026, 4, 2),
        ),
        FillInput(
            id=uuid.uuid4(),
            account_id=ACCOUNT,
            ticker="GOOG",
            instrument_type="option",
            side="sell_to_close",
            contracts=D("1"),
            price=D("495"),
            executed_at=_dt(11, 27, 12),
            option_type="put",
            strike=D("290"),
            expiration=date(2026, 4, 2),
        ),
        FillInput(
            id=uuid.uuid4(),
            account_id=SECOND_ACCOUNT,
            ticker="GOOG",
            instrument_type="option",
            side="sell_to_close",
            contracts=D("1"),
            price=D("475"),
            executed_at=_dt(11, 32, 12),
            option_type="put",
            strike=D("290"),
            expiration=date(2026, 4, 2),
        ),
    ]

    result = reconstruct(fills, today=date(2026, 4, 17))

    assert len(result.trades) == 2

    trades_by_account = {t.account_id: t for t in result.trades}
    first = trades_by_account[ACCOUNT]
    second = trades_by_account[SECOND_ACCOUNT]

    assert first.contracts == D("1.000000")
    assert first.avg_entry_premium == D("500.000000")
    assert first.avg_exit_premium == D("495.000000")
    assert first.realized_pnl == D("-5.000000")

    assert second.contracts == D("1.000000")
    assert second.avg_entry_premium == D("495.000000")
    assert second.avg_exit_premium == D("475.000000")
    assert second.realized_pnl == D("-20.000000")
