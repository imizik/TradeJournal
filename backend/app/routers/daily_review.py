import uuid
import json
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.database import get_session
from app.models import DailyReviewRecord, Fill, Trade, TradeFill

router = APIRouter()


class DailyReviewRequest(BaseModel):
    day: str
    trade_ids: list[uuid.UUID]


class DailyReviewResponse(BaseModel):
    day: str
    review: dict
    generated_at: datetime | None = None
    trade_count: int


class DailyReviewIndexItem(BaseModel):
    day: str
    trade_count: int
    saved: bool
    generated_at: datetime | None = None


@router.get("", response_model=list[DailyReviewIndexItem])
async def list_daily_reviews(session: Session = Depends(get_session)):
    trades = session.exec(select(Trade)).all()
    trade_ids_by_day: dict[date, set[uuid.UUID]] = {}
    for trade in trades:
        for value in (trade.opened_at, trade.closed_at):
            if not value:
                continue
            trade_day = value.date()
            trade_ids_by_day.setdefault(trade_day, set()).add(trade.id)

    records = session.exec(select(DailyReviewRecord)).all()
    records_by_day = {record.day: record for record in records}

    return [
        {
            "day": review_day.isoformat(),
            "trade_count": len(trade_ids_by_day[review_day]),
            "saved": review_day in records_by_day,
            "generated_at": records_by_day[review_day].updated_at if review_day in records_by_day else None,
        }
        for review_day in sorted(trade_ids_by_day.keys(), reverse=True)
    ]


@router.get("/{review_day}", response_model=DailyReviewResponse | None)
async def get_daily_review(review_day: date, session: Session = Depends(get_session)):
    record = session.exec(select(DailyReviewRecord).where(DailyReviewRecord.day == review_day)).first()
    if not record:
        return None

    return {
        "day": record.day.isoformat(),
        "review": json.loads(record.review_json),
        "generated_at": record.updated_at,
        "trade_count": record.trade_count,
    }


@router.post("", response_model=DailyReviewResponse)
async def create_daily_review(body: DailyReviewRequest, session: Session = Depends(get_session)):
    if not body.trade_ids:
        raise HTTPException(status_code=400, detail="At least one trade is required for a daily review")

    trades = session.exec(
        select(Trade).where(Trade.id.in_(body.trade_ids)).order_by(Trade.opened_at)
    ).all()
    if not trades:
        raise HTTPException(status_code=404, detail="No matching trades found")

    trade_fills = session.exec(select(TradeFill).where(TradeFill.trade_id.in_([trade.id for trade in trades]))).all()
    fill_ids = [tf.fill_id for tf in trade_fills]
    fills = session.exec(select(Fill).where(Fill.id.in_(fill_ids)).order_by(Fill.executed_at)).all() if fill_ids else []

    fills_by_id = {fill.id: fill for fill in fills}
    fills_by_trade_id: dict[str, list[Fill]] = {str(trade.id): [] for trade in trades}
    for tf in trade_fills:
        fill = fills_by_id.get(tf.fill_id)
        if fill:
            fills_by_trade_id[str(tf.trade_id)].append(fill)

    for trade_fills_for_trade in fills_by_trade_id.values():
        trade_fills_for_trade.sort(key=lambda fill: fill.executed_at)

    review_day = _parse_day(body.day)

    try:
        from app.ai.daily_reviewer import review_trading_day

        review = review_trading_day(body.day, list(trades), fills_by_trade_id, session)
    except ModuleNotFoundError as exc:
        if exc.name == "anthropic":
            raise HTTPException(
                status_code=503,
                detail="AI review dependency is not installed. Run `pip install -e .` from backend.",
            ) from exc
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Daily review generation failed: {exc}") from exc

    record = session.exec(select(DailyReviewRecord).where(DailyReviewRecord.day == review_day)).first()
    now = datetime.utcnow()
    if record:
        record.review_json = json.dumps(review)
        record.trade_count = len(trades)
        record.updated_at = now
    else:
        record = DailyReviewRecord(
            day=review_day,
            review_json=json.dumps(review),
            trade_count=len(trades),
            created_at=now,
            updated_at=now,
        )
    session.add(record)
    session.commit()
    session.refresh(record)

    return {
        "day": record.day.isoformat(),
        "review": review,
        "generated_at": record.updated_at,
        "trade_count": record.trade_count,
    }


def _parse_day(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="day must be YYYY-MM-DD") from exc
