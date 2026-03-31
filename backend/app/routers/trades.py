import uuid

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


@router.post("/{trade_id}/review")
async def review_trade(trade_id: uuid.UUID, session: Session = Depends(get_session)):
    # AI review wired in a later step (ai/reviewer.py)
    trade = session.get(Trade, trade_id)
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")
    return {"status": "not_implemented"}
