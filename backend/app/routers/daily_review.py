import uuid
import json
from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.database import get_session
from app.models import DailyReviewRecord, Trade

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
    # Realized P&L of the trades that closed (or expired) that day, by the same
    # rule as the dashboard's today_pnl; null when none closed with a recorded P&L.
    closed_pnl: float | None = None
    saved: bool
    generated_at: datetime | None = None
    source_data_stale: bool = False


@router.get("", response_model=list[DailyReviewIndexItem])
async def list_daily_reviews(session: Session = Depends(get_session)):
    trades = session.exec(select(Trade)).all()
    trade_ids_by_day: dict[date, set[uuid.UUID]] = {}
    closed_pnl_by_day: dict[date, Decimal] = {}
    for trade in trades:
        for value in (trade.opened_at, trade.closed_at):
            if not value:
                continue
            trade_day = value.date()
            trade_ids_by_day.setdefault(trade_day, set()).add(trade.id)
        if trade.status != "open" and trade.closed_at and trade.realized_pnl is not None:
            close_day = trade.closed_at.date()
            closed_pnl_by_day[close_day] = closed_pnl_by_day.get(close_day, Decimal(0)) + Decimal(str(trade.realized_pnl))

    records = session.exec(select(DailyReviewRecord)).all()
    records_by_day = {record.day: record for record in records}
    from app.ai import daily_review_service
    review_days = set(trade_ids_by_day) | daily_review_service.review_days_without_trades(session) | set(records_by_day)

    return [
        {
            "day": review_day.isoformat(),
            "trade_count": len(trade_ids_by_day.get(review_day, set())),
            "closed_pnl": float(round(closed_pnl_by_day[review_day], 2)) if review_day in closed_pnl_by_day else None,
            "saved": review_day in records_by_day,
            "generated_at": records_by_day[review_day].updated_at if review_day in records_by_day else None,
            "source_data_stale": bool(json.loads(records_by_day[review_day].review_json).get("source_data_stale")) if review_day in records_by_day else False,
        }
        for review_day in sorted(review_days, reverse=True)
    ]


@router.get("/runner")
def plan_runner_status():
    """The nightly plan review run (app.jobs.plan_reviews): its last status, or null before the first run."""
    from app.ai import plan_runner
    from app.jobs.plan_reviews import read_status

    return {"configured": plan_runner.plan_configured(), "status": read_status()}


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
def create_daily_review(body: DailyReviewRequest, session: Session = Depends(get_session)):
    review_day = _parse_day(body.day)

    from app.ai import daily_review_service, plan_runner

    try:
        record, review = daily_review_service.generate(session, review_day, body.trade_ids)
    except LookupError as exc:
        detail = str(exc)
        raise HTTPException(status_code=400 if "belong to the review day" in detail else 404,
                            detail=detail) from exc
    except plan_runner.PlanUnavailable as exc:
        raise HTTPException(status_code=503, detail=f"Daily review is not set up on the Claude plan: {exc}") from exc
    except ModuleNotFoundError as exc:
        if exc.name == "anthropic":
            raise HTTPException(
                status_code=503,
                detail="AI review dependency is not installed. Run `pip install -e .` from backend.",
            ) from exc
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Daily review generation failed: {exc}") from exc

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
