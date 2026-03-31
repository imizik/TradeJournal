"""
Tests for the FIFO reconstructor.

All 5 cases from the spec + a few edge cases.
"""

import uuid
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from app.engine.reconstructor import FillInput, reconstruct

ET = ZoneInfo("America/New_York")
ACCOUNT = uuid.uuid4()


def _fill(
    side: str,
    contracts: int,
    price: float,
    executed_at: datetime,
    ticker: str = "NVDA",
    option_type: str = "call",
    strike: float = 500.0,
    expiration: date = date(2026, 3, 28),
) -> FillInput:
    return FillInput(
        id=uuid.uuid4(),
        account_id=ACCOUNT,
        ticker=ticker,
        side=side,
        contracts=contracts,
        price=price,
        executed_at=executed_at,
        option_type=option_type,
        strike=strike,
        expiration=expiration,
    )


def _dt(hour: int, minute: int = 0, day: int = 1) -> datetime:
    return datetime(2026, 3, day, hour, minute, tzinfo=ET)


# ---------------------------------------------------------------------------
# Case 1: simple round trip
# ---------------------------------------------------------------------------

def test_simple_round_trip():
    fills = [
        _fill("buy_to_open",   2, price=100.0, executed_at=_dt(10, 0)),
        _fill("sell_to_close", 2, price=150.0, executed_at=_dt(11, 0)),
    ]
    result = reconstruct(fills, today=date(2026, 3, 29))

    assert len(result.trades) == 1
    t = result.trades[0]
    assert t.status == "closed"
    assert t.contracts == 2
    assert t.avg_entry_premium == 100.0
    assert t.avg_exit_premium == 150.0
    assert t.realized_pnl == pytest.approx(100.0)   # (150 - 100) * 2
    assert t.pnl_pct == pytest.approx(0.5)           # 100 / 200
    assert t.hold_duration_mins == 60

    tf_roles = {tf.fill_id: tf.role for tf in result.trade_fills}
    assert tf_roles[fills[0].id] == "entry"
    assert tf_roles[fills[1].id] == "exit"


# ---------------------------------------------------------------------------
# Case 2: partial exits
# ---------------------------------------------------------------------------

def test_partial_exit():
    fills = [
        _fill("buy_to_open",   4, price=100.0, executed_at=_dt(10, 0)),
        _fill("sell_to_close", 2, price=120.0, executed_at=_dt(11, 0)),
        _fill("sell_to_close", 2, price=130.0, executed_at=_dt(12, 0)),
    ]
    result = reconstruct(fills, today=date(2026, 3, 29))

    assert len(result.trades) == 1
    t = result.trades[0]
    assert t.status == "closed"
    # pnl = (120-100)*2 + (130-100)*2 = 40 + 60 = 100
    assert t.realized_pnl == pytest.approx(100.0)
    assert len(result.trade_fills) == 3
    roles = [tf.role for tf in result.trade_fills]
    assert roles.count("entry") == 1
    assert roles.count("exit") == 2


# ---------------------------------------------------------------------------
# Case 3: scale in (weighted average entry)
# ---------------------------------------------------------------------------

def test_scale_in():
    fills = [
        _fill("buy_to_open",   2, price=100.0, executed_at=_dt(10, 0)),
        _fill("buy_to_open",   2, price=200.0, executed_at=_dt(10, 30)),
        _fill("sell_to_close", 4, price=200.0, executed_at=_dt(11, 0)),
    ]
    result = reconstruct(fills, today=date(2026, 3, 29))

    assert len(result.trades) == 1
    t = result.trades[0]
    assert t.status == "closed"
    assert t.avg_entry_premium == pytest.approx(150.0)   # (100*2 + 200*2) / 4
    # pnl: FIFO — first lot: (200-100)*2 = 200, second lot: (200-200)*2 = 0 → 200
    assert t.realized_pnl == pytest.approx(200.0)
    assert len([tf for tf in result.trade_fills if tf.role == "entry"]) == 2
    assert len([tf for tf in result.trade_fills if tf.role == "exit"]) == 1


# ---------------------------------------------------------------------------
# Case 4: expired worthless
# ---------------------------------------------------------------------------

def test_expired_worthless():
    exp = date(2026, 3, 25)
    fills = [
        _fill("buy_to_open", 1, price=500.0, executed_at=_dt(9, 45), expiration=exp),
    ]
    # today is after expiration
    result = reconstruct(fills, today=date(2026, 3, 29))

    assert len(result.trades) == 1
    t = result.trades[0]
    assert t.status == "expired"
    assert t.expired_worthless is True
    assert t.realized_pnl == pytest.approx(-500.0)
    assert t.pnl_pct == pytest.approx(-1.0)
    assert t.closed_at is not None
    assert t.closed_at.hour == 16
    assert t.closed_at.date() == exp


# ---------------------------------------------------------------------------
# Case 5: same ticker, different strikes = separate trades
# ---------------------------------------------------------------------------

def test_different_strikes_separate_trades():
    future_exp = date(2026, 12, 31)
    fills = [
        _fill("buy_to_open", 1, price=100.0, executed_at=_dt(10, 0), strike=500.0, expiration=future_exp),
        _fill("buy_to_open", 1, price=50.0,  executed_at=_dt(10, 5), strike=510.0, expiration=future_exp),
    ]
    result = reconstruct(fills, today=date(2026, 3, 29))

    assert len(result.trades) == 2
    strikes = {t.strike for t in result.trades}
    assert strikes == {500.0, 510.0}
    assert all(t.status == "open" for t in result.trades)


# ---------------------------------------------------------------------------
# Edge: open trade stays open when expiration is in the future
# ---------------------------------------------------------------------------

def test_open_trade_not_expired():
    future_exp = date(2026, 12, 31)
    fills = [
        _fill("buy_to_open", 2, price=100.0, executed_at=_dt(10, 0), expiration=future_exp),
    ]
    result = reconstruct(fills, today=date(2026, 3, 29))

    assert len(result.trades) == 1
    assert result.trades[0].status == "open"
    assert result.trades[0].realized_pnl is None


# ---------------------------------------------------------------------------
# Edge: entry time bucket classification
# ---------------------------------------------------------------------------

def test_time_buckets():
    exp = date(2026, 12, 31)
    cases = [
        (_dt(9, 35),  "open"),
        (_dt(10, 0),  "mid"),
        (_dt(14, 59), "mid"),
        (_dt(15, 0),  "close"),
        (_dt(15, 59), "close"),
    ]
    for dt, expected_bucket in cases:
        fills = [_fill("buy_to_open", 1, price=100.0, executed_at=dt,
                       expiration=exp, strike=float(dt.hour * 100))]
        result = reconstruct(fills, today=date(2026, 3, 29))
        assert result.trades[0].entry_time_bucket == expected_bucket, (
            f"Expected {expected_bucket!r} for {dt.hour}:{dt.minute:02d}"
        )


# ---------------------------------------------------------------------------
# Edge: orphaned close fill (no matching open) — should not crash
# ---------------------------------------------------------------------------

def test_orphaned_close_ignored():
    fills = [
        _fill("sell_to_close", 1, price=100.0, executed_at=_dt(11, 0)),
    ]
    result = reconstruct(fills, today=date(2026, 3, 29))
    assert result.trades == []
    assert result.trade_fills == []
