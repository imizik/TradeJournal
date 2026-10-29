"""Append-only owner day journal storage and validation."""
from __future__ import annotations

from datetime import date, datetime, timezone
import json
import re

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.models import DailyReviewRecord, DayJournalEntry

# ``decision``: what the owner chose after an alert, logged from the Copilot desk's decision bar. ``horizon``: how often
# the desk checks in on a symbol's plan or position (``HORIZONS``' words), from a plan card's Confirm or the thread
# header. ``plan_ask``: the answer to the desk's one "Want a plan for this?" about a position with no plan.
KINDS = {"outlook", "update", "idea", "reflection", "decision", "horizon", "plan_ask"}
HORIZONS = {"Day trade": "day", "Swing": "swing", "Long hold": "long"}
SYMBOL = re.compile(r"^[A-Z][A-Z0-9./-]{0,14}$")
MAX_TEXT = 10_000


class EntryError(ValueError):
    pass


class EntryConflict(EntryError):
    pass


def entries(session: Session, day: date) -> list[DayJournalEntry]:
    return list(session.exec(select(DayJournalEntry).where(DayJournalEntry.day == day)
                              .order_by(DayJournalEntry.created_at, DayJournalEntry.id)).all())


def check_ins(session: Session) -> tuple[dict[str, str], dict[str, DayJournalEntry]]:
    """Each symbol's horizon (``day``, ``swing`` or ``long``: its newest ``horizon`` entry) and its newest
    ``plan_ask`` entry, across every day."""
    horizons, asked = {}, {}
    for row in session.exec(select(DayJournalEntry).where(DayJournalEntry.kind.in_(("horizon", "plan_ask")),
                                                          DayJournalEntry.symbol.is_not(None))
                            .order_by(DayJournalEntry.created_at, DayJournalEntry.id)).all():
        if row.kind == "plan_ask":
            asked[row.symbol] = row
        elif row.text in HORIZONS:
            horizons[row.symbol] = HORIZONS[row.text]
    return horizons, asked


def append(session: Session, *, day: date, operation_id: str, kind: str, text: str,
           symbol: str | None = None, not_traded: bool = False) -> DayJournalEntry:
    if not operation_id.strip() or len(operation_id) > 100:
        raise EntryError("operation_id must contain 1 to 100 characters")
    if kind not in KINDS:
        raise EntryError("kind must be outlook, update, idea, reflection, decision, horizon, or plan_ask")
    if kind == "horizon" and text not in HORIZONS:
        raise EntryError(f"a horizon is one of {', '.join(HORIZONS)}")
    if not text.strip() or len(text) > MAX_TEXT:
        raise EntryError(f"text must contain 1 to {MAX_TEXT} characters")
    symbol = symbol.strip().upper() if symbol is not None else None
    if symbol == "":
        symbol = None
    if symbol is not None and not SYMBOL.fullmatch(symbol):
        raise EntryError("Use a valid US stock or ETF ticker")
    if not isinstance(not_traded, bool):
        raise EntryError("not_traded must be a boolean")

    existing = session.exec(select(DayJournalEntry).where(DayJournalEntry.operation_id == operation_id)).first()
    if existing:
        _ensure_same(existing, day, kind, text, symbol, not_traded)
        return existing

    row = DayJournalEntry(operation_id=operation_id, day=day, kind=kind, text=text, symbol=symbol,
                          not_traded=not_traded, created_at=datetime.now(timezone.utc).replace(tzinfo=None), actor="owner")
    try:
        session.add(row)
        # This SELECT can trigger ORM autoflush, so it belongs inside the
        # IntegrityError recovery boundary just like commit itself.
        review = session.exec(select(DailyReviewRecord).where(DailyReviewRecord.day == day)).first()
        if review:
            try:
                saved = json.loads(review.review_json)
            except (TypeError, json.JSONDecodeError):
                saved = {}
            if not isinstance(saved, dict):
                saved = {}
            saved["source_data_stale"] = True
            saved["source_data_stale_reason"] = "Owner thoughts changed after this review was generated."
            review.review_json = json.dumps(saved)
            session.add(review)
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = session.exec(select(DayJournalEntry).where(DayJournalEntry.operation_id == operation_id)).first()
        if not existing:
            raise
        _ensure_same(existing, day, kind, text, symbol, not_traded)
        return existing
    session.refresh(row)
    return row


def _ensure_same(row: DayJournalEntry, day: date, kind: str, text: str, symbol: str | None, not_traded: bool) -> None:
    if (row.day, row.kind, row.text, row.symbol, row.not_traded) != (day, kind, text, symbol, not_traded):
        raise EntryConflict("operation_id was already used with a different entry")
