import uuid

from fastapi import APIRouter, Depends
from sqlmodel import Session, delete, select

from app.database import get_session
from app.engine.reconstructor import FillInput, reconstruct
from app.models import Fill, Trade, TradeFill, TradeTag

router = APIRouter()


@router.post("")
async def post_rebuild(session: Session = Depends(get_session)):
    # 1. Wipe derived tables
    session.exec(delete(TradeTag))
    session.exec(delete(TradeFill))
    session.exec(delete(Trade))
    session.commit()

    # 2. Load all fills ordered by executed_at ASC
    fills = session.exec(select(Fill).order_by(Fill.executed_at)).all()
    if not fills:
        return {"status": "ok", "trades_rebuilt": 0}

    # 3. Run FIFO reconstructor
    fill_inputs = [
        FillInput(
            id=f.id,
            account_id=f.account_id,
            ticker=f.ticker,
            instrument_type=f.instrument_type,
            side=f.side,
            contracts=f.contracts,
            price=f.price,
            executed_at=f.executed_at,
            option_type=f.option_type,
            strike=f.strike,
            expiration=f.expiration,
        )
        for f in fills
    ]
    result = reconstruct(fill_inputs)

    # 4. Persist trades
    for t in result.trades:
        session.add(Trade(
            id=t.id,
            account_id=t.account_id,
            ticker=t.ticker,
            instrument_type=t.instrument_type,
            option_type=t.option_type,
            strike=t.strike,
            expiration=t.expiration,
            contracts=t.contracts,
            avg_entry_premium=t.avg_entry_premium,
            avg_exit_premium=t.avg_exit_premium,
            total_premium_paid=t.total_premium_paid,
            realized_pnl=t.realized_pnl,
            pnl_pct=t.pnl_pct,
            hold_duration_mins=t.hold_duration_mins,
            entry_time_bucket=t.entry_time_bucket,
            expired_worthless=t.expired_worthless,
            opened_at=t.opened_at,
            closed_at=t.closed_at,
            status=t.status,
        ))

    # 5. Persist trade-fill junctions
    for tf in result.trade_fills:
        session.add(TradeFill(
            trade_id=tf.trade_id,
            fill_id=tf.fill_id,
            role=tf.role,
        ))

    session.commit()
    return {
        "status": "ok",
        "trades_rebuilt": len(result.trades),
        "anomalies": result.anomalies,
    }
