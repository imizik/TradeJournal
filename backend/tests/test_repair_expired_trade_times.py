import json
import uuid
from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.engine.reconstructor import reconstruct
from app.models import Account, DailyReviewRecord, Fill, Trade, TradePathMetrics
from scripts import repair_expired_trade_times as repair


def test_expiration_repair_preserves_saved_reviews_and_rejects_unrelated_times(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    account_id = uuid.uuid4()
    expirations = (date(2025, 7, 18), date(2025, 12, 19), date(2025, 8, 15))
    with Session(engine) as session:
        session.add(Account(id=account_id, name="Test", type="roth_ira", last4="8267"))
        fills = []
        for index, expiry in enumerate(expirations):
            fill = Fill(
                id=uuid.uuid4(), account_id=account_id, ticker="AAPL",
                instrument_type="option", side="buy_to_open", contracts=1,
                price=Decimal("100"), option_type="call", strike=Decimal(200 + index),
                expiration=expiry, executed_at=datetime(2025, 7, 14, 10),
                raw_email_id=f"manual:{index}",
            )
            session.add(fill)
            fills.append(fill)
        session.flush()
        rebuilt = reconstruct([repair._fill_input(fill) for fill in fills], today=date(2026, 1, 1))
        for item in rebuilt.trades:
            trade = Trade(**vars(item), ai_review='{"note":"keep"}')
            if item.expiration == expirations[0]:
                trade.closed_at = datetime(2025, 7, 18, 20)
            elif item.expiration == expirations[1]:
                trade.closed_at = datetime(2025, 12, 19, 21)
            else:
                trade.closed_at = datetime(2025, 8, 15, 18)
            session.add(trade)
            session.add(TradePathMetrics(
                trade_id=trade.id, data_source="alpaca_iex",
                fetched_at=datetime.now(), inputs_fingerprint="saved",
            ))
        session.add(DailyReviewRecord(
            day=expirations[0], review_json='{"summary":"keep"}', trade_count=1,
        ))
        session.commit()

    monkeypatch.setattr(repair, "engine", engine)
    assert repair.repair() == {"candidate_trades": 2, "already_correct": 0, "unresolved": 1}
    assert repair.repair(apply=True) == {"candidate_trades": 2, "already_correct": 0, "unresolved": 1}
    assert repair.repair() == {"candidate_trades": 0, "already_correct": 2, "unresolved": 1}

    with Session(engine) as session:
        trades = {trade.expiration: trade for trade in session.exec(select(Trade)).all()}
        assert trades[expirations[0]].closed_at == datetime(2025, 7, 18, 16)
        assert trades[expirations[1]].closed_at == datetime(2025, 12, 19, 16)
        assert trades[expirations[2]].closed_at == datetime(2025, 8, 15, 18)
        assert json.loads(trades[expirations[0]].ai_review) == {
            "note": "keep", "source_data_stale": True,
        }
        assert json.loads(trades[expirations[2]].ai_review) == {"note": "keep"}
        assert {path.trade_id for path in session.exec(select(TradePathMetrics)).all()} == {
            trades[expirations[2]].id,
        }
        assert json.loads(session.exec(select(DailyReviewRecord)).one().review_json) == {
            "summary": "keep", "source_data_stale": True,
        }

    with Session(engine) as session:
        trade = session.get(Trade, trades[expirations[0]].id)
        trade.closed_at = datetime(2025, 7, 18, 20)
        trade.realized_pnl = Decimal("-999")
        session.commit()
    with pytest.raises(ValueError, match="no longer matches"):
        repair.repair(apply=True)
    with Session(engine) as session:
        assert session.get(Trade, trades[expirations[0]].id).closed_at == datetime(2025, 7, 18, 20)
