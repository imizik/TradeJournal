import json
import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.database import get_session
from app.models import Fill, Tag, Trade, TradeFill, TradeTag

router = APIRouter()


@router.get("", response_model=list[Trade])
async def get_trades(
    status: str | None = None,
    ticker: str | None = None,
    session: Session = Depends(get_session),
):
    query = select(Trade)
    if status and status != "all":
        query = query.where(Trade.status == status)
    if ticker:
        query = query.where(Trade.ticker == ticker.upper())
    query = query.order_by(Trade.opened_at.desc())
    return session.exec(query).all()


@router.get("/{trade_id}", response_model=Trade)
async def get_trade(trade_id: uuid.UUID, session: Session = Depends(get_session)):
    trade = session.get(Trade, trade_id)
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")
    return trade


@router.get("/{trade_id}/fills", response_model=list[Fill])
async def get_trade_fills(trade_id: uuid.UUID, session: Session = Depends(get_session)):
    trade = session.get(Trade, trade_id)
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")

    trade_fills = session.exec(
        select(TradeFill).where(TradeFill.trade_id == trade_id)
    ).all()
    fill_ids = [tf.fill_id for tf in trade_fills]

    fills = session.exec(
        select(Fill).where(Fill.id.in_(fill_ids)).order_by(Fill.executed_at)
    ).all()
    return fills


class TagBody(BaseModel):
    name: str
    source: str = "manual"


@router.post("/{trade_id}/tags")
async def add_tag(
    trade_id: uuid.UUID, body: TagBody, session: Session = Depends(get_session)
):
    trade = session.get(Trade, trade_id)
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")

    # Reuse existing tag with same name, or create new
    tag = session.exec(select(Tag).where(Tag.name == body.name)).first()
    if not tag:
        tag = Tag(id=uuid.uuid4(), name=body.name, source=body.source)
        session.add(tag)
        session.flush()

    # Avoid duplicate junction rows
    existing = session.exec(
        select(TradeTag).where(TradeTag.trade_id == trade_id, TradeTag.tag_id == tag.id)
    ).first()
    if not existing:
        session.add(TradeTag(trade_id=trade_id, tag_id=tag.id))

    session.commit()
    return {"trade_id": trade_id, "tag": tag.name}


@router.post("/{trade_id}/review", response_model=Trade)
async def review_trade(trade_id: uuid.UUID, session: Session = Depends(get_session)):
    trade = session.get(Trade, trade_id)
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")

    # Load fills for this trade
    trade_fills = session.exec(
        select(TradeFill).where(TradeFill.trade_id == trade_id)
    ).all()
    fill_ids = [tf.fill_id for tf in trade_fills]
    fills = session.exec(
        select(Fill).where(Fill.id.in_(fill_ids)).order_by(Fill.executed_at)
    ).all()

    # Find companion trades (same ticker, opened within 5 min of this trade)
    five_min = timedelta(minutes=5)
    companion_trades = session.exec(
        select(Trade).where(
            Trade.ticker == trade.ticker,
            Trade.id != trade_id,
            Trade.account_id == trade.account_id,
            Trade.opened_at >= trade.opened_at - five_min,
            Trade.opened_at <= trade.opened_at + five_min,
        )
    ).all()

    # Load overall stats for trader context
    all_trades = session.exec(select(Trade)).all()
    stats = _compute_stats_for_context(all_trades, session)

    # Call AI reviewer. Keep this import lazy so the core API can still boot
    # in environments that have not installed the optional AI dependency yet.
    try:
        from app.ai.reviewer import review_trade as ai_review_trade

        review_result = ai_review_trade(trade, fills, companion_trades, stats, session)
        trade.ai_review = json.dumps(review_result)
        session.add(trade)
        session.commit()
        session.refresh(trade)
    except ModuleNotFoundError as e:
        if e.name == "anthropic":
            raise HTTPException(
                status_code=503,
                detail="AI review dependency is not installed. Run `pip install -e .` from backend.",
            ) from e
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Review generation failed: {str(e)}")

    return trade


def _compute_stats_for_context(all_trades: list[Trade], session: Session) -> dict:
    """Compute a minimal stats dict for AI context (ticker + overall win_rate only)."""
    from collections import defaultdict

    closed = [t for t in all_trades if t.status in ("closed", "expired")]
    winners = [t for t in closed if t.realized_pnl is not None and t.realized_pnl > 0]

    win_rate = len(winners) / len(closed) if closed else 0.0

    # Ticker breakdown
    by_ticker: dict[str, dict] = defaultdict(
        lambda: {"count": 0, "total_pnl": 0.0, "winners": 0}
    )
    for t in closed:
        ticker = t.ticker
        by_ticker[ticker]["count"] += 1
        by_ticker[ticker]["total_pnl"] += float(t.realized_pnl or 0)
        if t.realized_pnl is not None and t.realized_pnl > 0:
            by_ticker[ticker]["winners"] += 1

    by_ticker_result = {}
    for ticker, stats in by_ticker.items():
        ticker_win_rate = stats["winners"] / stats["count"] if stats["count"] > 0 else 0
        by_ticker_result[ticker] = {
            "count": stats["count"],
            "win_rate": round(ticker_win_rate, 4),
            "total_pnl": round(stats["total_pnl"], 2),
        }

    # Behavioral flags
    flag_counts = defaultdict(int)
    for t in closed:
        if t.ai_review:
            try:
                review = json.loads(t.ai_review)
                for flag in review.get("flags", []):
                    flag_counts[flag] += 1
            except (json.JSONDecodeError, AttributeError):
                pass

    return {
        "win_rate": round(win_rate, 4),
        "by_ticker": by_ticker_result,
        "behavioral_flags": dict(flag_counts),
    }
