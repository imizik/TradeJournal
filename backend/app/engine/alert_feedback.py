"""Owner feedback only: never infer attention, change fills, or score financial benefit."""
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.models import PositionAlertFeedback

RATINGS = ("prompted_review", "already_aware", "too_late", "not_useful")
ELIGIBLE_DELIVERIES = ("sent", "unknown")


def view(row: PositionAlertFeedback) -> dict:
    return {"rating": row.rating, "reason": row.reason, "version": row.version,
            "created_at": row.created_at.replace(tzinfo=UTC).timestamp(),
            "updated_at": row.updated_at.replace(tzinfo=UTC).timestamp()}


def for_alerts(db: Session, ids: list) -> dict:
    if not ids:
        return {}
    return {row.alert_id: view(row) for row in db.exec(
        select(PositionAlertFeedback).where(PositionAlertFeedback.alert_id.in_(ids))).all()}


def save(db: Session, alert_id, rating: str, reason: str | None, base_version: int) -> dict:
    reason = reason.strip() or None if reason is not None else None
    now = datetime.now(UTC).replace(tzinfo=None)
    if base_version == 0:
        db.add(PositionAlertFeedback(alert_id=alert_id, rating=rating, reason=reason, version=1,
                                     created_at=now, updated_at=now))
        try:
            db.commit()
            return view(db.get(PositionAlertFeedback, alert_id))
        except IntegrityError:
            db.rollback()  # a simultaneous save or a retry of an acknowledged-lost save
    else:
        changed = db.exec(update(PositionAlertFeedback).where(
            PositionAlertFeedback.alert_id == alert_id, PositionAlertFeedback.version == base_version)
            .values(rating=rating, reason=reason, version=base_version + 1, updated_at=now))
        db.commit()
        if changed.rowcount:
            return view(db.get(PositionAlertFeedback, alert_id))
    current = db.get(PositionAlertFeedback, alert_id)
    if current and current.version == base_version + 1 and (current.rating, current.reason) == (rating, reason):
        return view(current)
    raise HTTPException(409, "Feedback changed in another session. Reload to see the saved response before editing.")
