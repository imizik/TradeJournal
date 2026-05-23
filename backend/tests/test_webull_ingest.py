"""
Tests for the Webull event ingestion pipeline.

Coverage:
  - Sample event normalization (stock)
  - Duplicate event handling (same event_id)
  - Partial fill then final fill -> two Fill rows, no overlap
  - Account auto-creation + reuse for broker_account_id mapping
  - Option events save safely with unresolved metadata
  - Non-execution scene_type events save raw but skip Fill creation
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.engine.webull import ingest_event
from app.models import Account, Fill, WebullRawEvent


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def session():
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(eng)
    with Session(eng) as s:
        yield s


def _stock_event(
    *,
    event_id: str = "event_test_stock_001",
    account_id: str = "4MHSOMIJ88O7E80VBG0O4G6E9A",
    client_order_id: str = "db74f199-stock",
    symbol: str = "AAPL",
    side: str = "BUY",
    filled_qty: str = "1.00",
    filled_price: str = "180.00",
    scene_type: str = "FILLED",
    order_status: str = "FILLED",
    filled_time: str = "2025-11-21T14:27:43.312Z",
) -> dict:
    return {
        "id": event_id,
        "event_type": "TRADE",
        "position": "abc",
        "timestamp": "2025-03-29T07:02:33.200962333Z",
        "payload": {
            "account_id": account_id,
            "request_id": "1045474398137483264",
            "client_order_id": client_order_id,
            "instrument_id": "913256135",
            "order_status": order_status,
            "symbol": symbol,
            "qty": "10.00",
            "filled_price": filled_price,
            "filled_qty": filled_qty,
            "filled_time": filled_time,
            "side": side,
            "category": "US_STOCK",
            "order_type": "LIMIT",
            "scene_type": scene_type,
            "biz_type": "TRADE",
        },
    }


def _option_event(**overrides) -> dict:
    evt = _stock_event(**overrides)
    evt["payload"]["category"] = "US_OPTION"
    evt.setdefault("payload", {})
    return evt


# ---------------------------------------------------------------------------
# 1. Normalization
# ---------------------------------------------------------------------------

def test_stock_event_normalizes_to_fill(session: Session) -> None:
    result = ingest_event(_stock_event(), session)

    assert result.result == "normalized"
    assert result.event_id == "event_test_stock_001"
    assert result.fill_id is not None

    raw = session.get(WebullRawEvent, "event_test_stock_001")
    assert raw is not None
    assert raw.normalized is True
    assert raw.normalize_reason == "fill"
    assert raw.fill_id == result.fill_id
    assert raw.scene_type == "FILLED"

    fill = session.get(Fill, result.fill_id)
    assert fill is not None
    assert fill.ticker == "AAPL"
    assert fill.instrument_type == "stock"
    assert fill.side == "buy"
    assert float(fill.contracts) == pytest.approx(1.0)
    assert float(fill.price) == pytest.approx(180.0)
    assert fill.raw_email_id == "webull:event_test_stock_001"
    # filled_time was 2025-11-21T14:27:43Z -> 09:27 ET (EST is UTC-5 in Nov).
    # SQLite strips tz on round-trip, but the wall-clock fields prove the
    # UTC->ET conversion ran at write time.
    assert fill.executed_at.hour == 9
    assert fill.executed_at.minute == 27
    assert fill.executed_at.day == 21


# ---------------------------------------------------------------------------
# 2. Dedupe
# ---------------------------------------------------------------------------

def test_duplicate_event_id_does_not_create_second_fill(session: Session) -> None:
    evt = _stock_event(event_id="event_dup_001")
    first = ingest_event(evt, session)
    second = ingest_event(evt, session)

    assert first.result == "normalized"
    assert second.result == "duplicate"
    assert second.fill_id == first.fill_id

    fills = session.exec(select(Fill).where(Fill.raw_email_id == "webull:event_dup_001")).all()
    assert len(fills) == 1


# ---------------------------------------------------------------------------
# 3. Partial then final fill
# ---------------------------------------------------------------------------

def test_partial_then_final_creates_two_fills(session: Session) -> None:
    partial = _stock_event(
        event_id="event_partial",
        client_order_id="order_xyz",
        filled_qty="3.00",
        filled_price="180.00",
        scene_type="FILLED",
        order_status="PARTIAL_FILLED",
    )
    final = _stock_event(
        event_id="event_final",
        client_order_id="order_xyz",
        filled_qty="7.00",
        filled_price="180.50",
        scene_type="FINAL_FILLED",
        order_status="FILLED",
    )

    r1 = ingest_event(partial, session)
    r2 = ingest_event(final, session)

    assert r1.result == "normalized"
    assert r2.result == "normalized"
    assert r1.fill_id != r2.fill_id

    fills = session.exec(select(Fill).where(Fill.ticker == "AAPL")).all()
    assert len(fills) == 2
    total_contracts = sum(float(f.contracts) for f in fills)
    assert total_contracts == pytest.approx(10.0)


# ---------------------------------------------------------------------------
# 4. Account mapping
# ---------------------------------------------------------------------------

def test_account_is_created_once_and_reused(session: Session) -> None:
    e1 = _stock_event(event_id="evt_acct_1", account_id="ACCT_A_LONG_ID_111")
    e2 = _stock_event(event_id="evt_acct_2", account_id="ACCT_A_LONG_ID_111")
    e3 = _stock_event(event_id="evt_acct_3", account_id="ACCT_B_LONG_ID_222")

    ingest_event(e1, session)
    ingest_event(e2, session)
    ingest_event(e3, session)

    accts = session.exec(select(Account).where(Account.broker == "webull")).all()
    assert len(accts) == 2
    bids = {a.broker_account_id for a in accts}
    assert bids == {"ACCT_A_LONG_ID_111", "ACCT_B_LONG_ID_222"}

    # All three fills are linked to a Webull account; the first two share one account.
    fills = session.exec(select(Fill)).all()
    assert len(fills) == 3
    account_ids = [f.account_id for f in fills]
    # Fills 1 and 2 share an account; fill 3 is on a different account.
    assert account_ids[0] == account_ids[1]
    assert account_ids[2] != account_ids[0]


# ---------------------------------------------------------------------------
# 5. Option event saves safely with unresolved metadata
# ---------------------------------------------------------------------------

def test_option_event_saves_with_unresolved_metadata(session: Session) -> None:
    evt = _option_event(event_id="event_opt_001", symbol="AAPL", filled_price="2.50")
    result = ingest_event(evt, session)

    assert result.result == "normalized"
    fill = session.get(Fill, result.fill_id)
    assert fill is not None
    assert fill.instrument_type == "option"
    assert fill.side == "buy_to_open"           # provisional mapping
    assert fill.option_type is None             # TODO: resolve later
    assert fill.strike is None
    assert fill.expiration is None
    # per-share price 2.50 -> per-contract premium 250.00
    assert float(fill.price) == pytest.approx(250.0)
    assert fill.ticker == "AAPL"


# ---------------------------------------------------------------------------
# 6. Non-execution events are stored raw but skip Fill creation
# ---------------------------------------------------------------------------

def test_non_execution_event_saves_raw_but_no_fill(session: Session) -> None:
    evt = _stock_event(
        event_id="event_new_only",
        scene_type="NEW",
        order_status="SUBMITTED",
    )
    result = ingest_event(evt, session)

    assert result.result == "non_execution"
    raw = session.get(WebullRawEvent, "event_new_only")
    assert raw is not None
    assert raw.normalized is True
    assert raw.normalize_reason == "non_execution"
    assert raw.fill_id is None

    fills = session.exec(select(Fill)).all()
    assert len(fills) == 0


def test_non_trade_event_saves_raw_but_no_fill(session: Session) -> None:
    evt = _stock_event(event_id="event_balance_update")
    evt["event_type"] = "BALANCE_UPDATE"
    result = ingest_event(evt, session)

    assert result.result == "non_trade"
    raw = session.get(WebullRawEvent, "event_balance_update")
    assert raw is not None
    assert raw.normalized is True
    assert raw.normalize_reason == "non_trade"


# ---------------------------------------------------------------------------
# 7. Reject events without event_id
# ---------------------------------------------------------------------------

def test_event_missing_id_is_rejected(session: Session) -> None:
    evt = _stock_event()
    evt.pop("id")
    result = ingest_event(evt, session)

    assert result.result == "rejected"
    assert result.reason == "missing_event_id"
    assert session.exec(select(WebullRawEvent)).all() == []
    assert session.exec(select(Fill)).all() == []
