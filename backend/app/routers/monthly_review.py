import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.database import get_session
from app.models import MonthlyReviewRecord, Trade

router = APIRouter()


class MonthlyReviewRequest(BaseModel):
    month: str


def _month(value: str) -> str:
    try:
        return datetime.strptime(value, "%Y-%m").strftime("%Y-%m")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="month must be YYYY-MM") from exc


@router.get("")
def list_monthly_reviews(session: Session = Depends(get_session)):
    """Months with closed trades (newest first), whether each has a saved review, and its grade."""
    counts: dict[str, int] = {}
    for closed_at in session.exec(select(Trade.closed_at).where(Trade.status.in_(("closed", "expired")), Trade.closed_at.is_not(None))).all():
        key = closed_at.strftime("%Y-%m")
        counts[key] = counts.get(key, 0) + 1
    records = {record.month: record for record in session.exec(select(MonthlyReviewRecord)).all()}
    out = []
    for month in sorted(counts, reverse=True):
        record = records.get(month)
        grade = None
        if record:
            try:
                grade = json.loads(record.review_json).get("month_grade")
            except ValueError:
                grade = None
        out.append({"month": month, "closed_trades": counts[month], "saved": record is not None,
                    "grade": grade, "generated_at": record.updated_at if record else None})
    return out


@router.get("/{month}")
def get_monthly_review(month: str, session: Session = Depends(get_session)):
    record = session.exec(select(MonthlyReviewRecord).where(MonthlyReviewRecord.month == _month(month))).first()
    if not record:
        return None
    return {"month": record.month, "review": json.loads(record.review_json), "generated_at": record.updated_at, "trade_count": record.trade_count}


@router.post("")
def create_monthly_review(body: MonthlyReviewRequest, session: Session = Depends(get_session)):
    month = _month(body.month)
    from app.ai import monthly_reviewer, plan_runner

    try:
        record, review = monthly_reviewer.generate(session, month)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=f"No closed trades in {month}") from exc
    except plan_runner.PlanUnavailable as exc:
        raise HTTPException(status_code=503, detail=f"Monthly review is not set up on the Claude plan: {exc}") from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Monthly review generation failed: {exc}") from exc
    return {"month": record.month, "review": review, "generated_at": record.updated_at, "trade_count": record.trade_count}
