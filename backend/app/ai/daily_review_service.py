"""Load a day's trades, review them and save the review: shared by the Daily
Review button (``POST /daily-review``) and the nightly plan run
(``app.jobs.plan_reviews``)."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
import json
import uuid

from sqlmodel import Session, or_, select

from app.models import FILL_LIGHT, DailyReviewRecord, Fill, Trade, TradeFill


def day_trade_ids(session: Session, day: date) -> list[uuid.UUID]:
    """Trades that opened or closed on the day: the same rule as the Daily Review calendar."""
    start, end = datetime.combine(day, time.min), datetime.combine(day + timedelta(days=1), time.min)
    rows = session.exec(select(Trade.id).where(or_(
        (Trade.opened_at >= start) & (Trade.opened_at < end),
        (Trade.closed_at >= start) & (Trade.closed_at < end),
    ))).all()
    return list(rows)


def load_trades(session: Session, trade_ids: list[uuid.UUID]) -> tuple[list[Trade], dict[str, list[Fill]]]:
    trades = session.exec(select(Trade).where(Trade.id.in_(trade_ids)).order_by(Trade.opened_at)).all() if trade_ids else []
    if not trades:
        return [], {}
    trade_fills = session.exec(select(TradeFill).where(TradeFill.trade_id.in_([trade.id for trade in trades]))).all()
    fill_ids = [tf.fill_id for tf in trade_fills]
    fills = session.exec(select(Fill).options(*FILL_LIGHT).where(Fill.id.in_(fill_ids)).order_by(Fill.executed_at)).all() if fill_ids else []
    fills_by_id = {fill.id: fill for fill in fills}
    fills_by_trade_id: dict[str, list[Fill]] = {str(trade.id): [] for trade in trades}
    for tf in trade_fills:
        fill = fills_by_id.get(tf.fill_id)
        if fill:
            fills_by_trade_id[str(tf.trade_id)].append(fill)
    for day_fills in fills_by_trade_id.values():
        day_fills.sort(key=lambda fill: fill.executed_at)
    return list(trades), fills_by_trade_id


def save_review(session: Session, day: date, review: dict, trade_count: int) -> DailyReviewRecord:
    record = session.exec(select(DailyReviewRecord).where(DailyReviewRecord.day == day)).first()
    now = datetime.utcnow()
    if record:
        record.review_json = json.dumps(review)
        record.trade_count = trade_count
        record.updated_at = now
    else:
        record = DailyReviewRecord(day=day, review_json=json.dumps(review), trade_count=trade_count, created_at=now, updated_at=now)
    session.add(record)
    session.commit()
    session.refresh(record)
    return record


def generate(session: Session, day: date, trade_ids: list[uuid.UUID] | None = None) -> tuple[DailyReviewRecord, dict]:
    """Review the day (its own trades unless ids are given) and save it. Raises LookupError when there are no trades."""
    from app.ai.daily_reviewer import review_trading_day

    trades, fills_by_trade_id = load_trades(session, day_trade_ids(session, day) if trade_ids is None else trade_ids)
    if not trades:
        raise LookupError(f"No trades on {day.isoformat()}")
    review = review_trading_day(day.isoformat(), trades, fills_by_trade_id, session)
    return save_review(session, day, review, len(trades)), review
