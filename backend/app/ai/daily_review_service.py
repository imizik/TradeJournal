"""Load a day's trades, review them and save the review: shared by the Daily
Review button (``POST /daily-review``) and the nightly plan run
(``app.jobs.plan_reviews``)."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
import json
import uuid
from zoneinfo import ZoneInfo

from sqlmodel import Session, or_, select

from app.models import (FILL_LIGHT, CaptureLink, DailyReviewRecord, DayJournalEntry, Fill, Trade, TradeCapture,
                        TradeFill)

ET = ZoneInfo("America/New_York")


def day_trade_ids(session: Session, day: date) -> list[uuid.UUID]:
    """Trades that opened or closed on the day: the same rule as the Daily Review calendar."""
    start, end = datetime.combine(day, time.min), datetime.combine(day + timedelta(days=1), time.min)
    rows = session.exec(select(Trade.id).where(or_(
        (Trade.opened_at >= start) & (Trade.opened_at < end),
        (Trade.closed_at >= start) & (Trade.closed_at < end),
    ))).all()
    return list(rows)


def has_day_inputs(session: Session, day: date) -> bool:
    if session.exec(select(DayJournalEntry.id).where(DayJournalEntry.day == day).limit(1)).first():
        return True
    start, end = datetime.combine(day, time.min, ET).astimezone(timezone.utc).replace(tzinfo=None), datetime.combine(day + timedelta(days=1), time.min, ET).astimezone(timezone.utc).replace(tzinfo=None)
    return session.exec(select(TradeCapture.id).where(TradeCapture.received_at >= start,
                                                      TradeCapture.received_at < end).limit(1)).first() is not None


def review_days_without_trades(session: Session) -> set[date]:
    """Days with owner thoughts or captures that are not linked to a trade."""
    days = set(session.exec(select(DayJournalEntry.day).distinct()).all())
    captures = session.exec(select(TradeCapture.id, TradeCapture.received_at, TradeCapture.not_taken_at)).all()
    if captures:
        ids = [capture_id for capture_id, _, _ in captures]
        linked = set(session.exec(select(CaptureLink.capture_id).where(CaptureLink.unlinked_at.is_(None),
                                                                       CaptureLink.capture_id.in_(ids))).all())
        for capture_id, received_at, not_taken_at in captures:
            if capture_id in linked and not not_taken_at:
                continue
            stamp = received_at.replace(tzinfo=timezone.utc) if received_at.tzinfo is None else received_at
            days.add(stamp.astimezone(ET).date())
    return days


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


def generate(session: Session, day: date, trade_ids: list[uuid.UUID] | None = None, backend: str | None = None) -> tuple[DailyReviewRecord, dict]:
    """Review the day (its own trades unless ids are given) and save it."""
    from app.ai.daily_reviewer import review_trading_day

    wanted = day_trade_ids(session, day) if trade_ids is None else trade_ids
    trades, fills_by_trade_id = load_trades(session, wanted)
    allowed = set(day_trade_ids(session, day))
    if len(trades) != len(set(wanted)) or any(trade_id not in allowed for trade_id in wanted):
        raise LookupError("Selected trades must belong to the review day")
    if not trades and not has_day_inputs(session, day):
        raise LookupError(f"No trades or saved thoughts/captures on {day.isoformat()}")
    owner_thought_count = len(session.exec(select(DayJournalEntry.id).where(DayJournalEntry.day == day)).all())
    review = review_trading_day(day.isoformat(), trades, fills_by_trade_id, session, backend=backend)
    review["owner_input_count"] = owner_thought_count
    # Thoughts are append-only, so a count change means generation used a
    # snapshot that did not include all owner inputs available at save time.
    current_thought_count = len(session.exec(select(DayJournalEntry.id).where(DayJournalEntry.day == day)).all())
    if current_thought_count:
        review["owner_thoughts_included"] = True
    if current_thought_count != owner_thought_count:
        review["source_data_stale"] = True
        review["source_data_stale_reason"] = "Owner thoughts changed while this review was being generated."
    return save_review(session, day, review, len(trades)), review
