"""Read-only journal adapter; two queries, no per-trade reads or providers."""

from datetime import UTC, datetime

from sqlalchemy import func
from sqlmodel import Session, select

from app.engine.symbol_info import journal_summary
from app.models import Account, Fill, Trade


def read_journal(db: Session, symbol: str) -> dict:
    rows = db.exec(select(
        Trade.id, Trade.account_id, Account.name.label("account_name"), Account.last4,
        Trade.instrument_type, Trade.option_type, Trade.strike, Trade.expiration,
        Trade.status, Trade.realized_pnl, Trade.hold_duration_mins, Trade.opened_at, Trade.closed_at,
    ).join(Account, Account.id == Trade.account_id).where(Trade.ticker == symbol)).all()
    trades = []
    for row in rows:
        trade = dict(row._mapping)
        for key in ("id", "account_id", "expiration", "opened_at", "closed_at"):
            value = trade[key]
            trade[key] = value.isoformat() if hasattr(value, "isoformat") else str(value) if value is not None else None
        trades.append(trade)
    # Fills, rather than synthetic expiration closes, say when we last traded.
    last = db.exec(select(func.max(Fill.executed_at)).where(Fill.ticker == symbol)).one()
    return {
        **journal_summary(symbol, trades, last.isoformat() if last else None),
        "source": "Journal · all accounts",
        "as_of": datetime.now(UTC).isoformat(),
        "time_zone": "America/New_York",
    }
