"""Private owner API. No assistant grants or MCP exposure in this first slice."""
from datetime import date, datetime, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy import update, func
from sqlmodel import Session, select

from app.database import get_session
from app.engine import jo_briefing as store
from jo_briefing_common import Strict
from app.models import JoMemoryRevision, MorningBriefingPacket, MorningBriefingRecord, utc_now_naive

router = APIRouter()


def call(operation, *args):
    try:
        return operation(*args)
    except store.Conflict as exc:
        raise HTTPException(409, str(exc)) from None
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from None
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


@router.post("/memories", status_code=201)
def save_memory(body: store.MemorySave, session: Session = Depends(get_session)):
    return call(store.save_memory, session, body)


@router.get("/memories")
def list_memories(status: Literal["active", "proposed", "retired", "redacted"] = "active",
                  symbol: str | None = Query(None, pattern=r"^[A-Z]{1,6}(\.[A-Z])?$"),
                  limit: int = Query(50, ge=1, le=100), session: Session = Depends(get_session)):
    return {"items": store.memories(session, status, symbol, limit), "limit": limit}


@router.get("/memories/{memory_id}")
def memory_history(memory_id: UUID, before_revision: int | None = Query(None, ge=1),
                   limit: int = Query(50, ge=1, le=100), session: Session = Depends(get_session)):
    if store.latest_memory(session, memory_id) is None:
        raise HTTPException(404, "Memory not found")
    query = select(JoMemoryRevision).where(JoMemoryRevision.memory_id == memory_id)
    if before_revision is not None:
        query = query.where(JoMemoryRevision.revision < before_revision)
    rows = session.exec(query.order_by(JoMemoryRevision.revision.desc()).limit(limit)).all()
    return {"items": [store.receipt(row) for row in rows],
            "next_before_revision": rows[-1].revision if len(rows) == limit else None}


@router.post("/memories/{memory_id}/redact")
def redact_memory(memory_id: UUID, body: store.MemoryRedact, session: Session = Depends(get_session)):
    result = call(store.redact_memory, session, memory_id, body)
    return {**result, "notice": "Memory revision text is removed. Copies in supplied evidence, briefings, "
            "exports or conversations are not automatically erased."}


@router.post("/packets", status_code=201)
def save_packet(body: store.PacketSave, session: Session = Depends(get_session)):
    return call(store.save_packet, session, body)


@router.get("/packets/{packet_id}")
def get_packet(packet_id: UUID, session: Session = Depends(get_session)):
    return call(store.get_packet, session, packet_id)


@router.post("/briefings", status_code=201)
def save_briefing(body: store.BriefingSave, session: Session = Depends(get_session)):
    return call(store.save_briefing, session, body)


@router.post("/packets/{packet_id}/redact")
def redact_packet(packet_id: UUID, session: Session = Depends(get_session)):
    row = session.get(MorningBriefingPacket, packet_id)
    if row is None:
        raise HTTPException(404, "Packet not found")
    if not row.redacted_at:
        row.body_json, row.redacted_at = "{}", utc_now_naive()
        session.add(row)
        session.commit()
        session.refresh(row)
    return {**store.receipt(row), "notice": "Packet evidence is removed. Memory records, saved briefing text "
            "and external copies are not automatically erased."}


@router.get("/briefings")
def list_briefings(day: date, limit: int = Query(20, ge=1, le=100), session: Session = Depends(get_session)):
    rows = session.exec(select(MorningBriefingRecord).join(MorningBriefingPacket)
        .where(MorningBriefingPacket.day == day)
        .order_by(MorningBriefingRecord.created_at.desc(), MorningBriefingRecord.id).limit(limit)).all()
    return {"day": day.isoformat(), "items": [store.receipt(row) for row in rows], "limit": limit}


@router.get("/briefings/{briefing_id}")
def get_briefing(briefing_id: UUID, session: Session = Depends(get_session)):
    row = session.get(MorningBriefingRecord, briefing_id)
    if row is None:
        raise HTTPException(404, "Briefing not found")
    return {**store.receipt(row), "packet": call(store.get_packet, session, row.packet_id)}


@router.post("/briefings/{briefing_id}/redact")
def redact_briefing(briefing_id: UUID, session: Session = Depends(get_session)):
    row = session.get(MorningBriefingRecord, briefing_id)
    if row is None:
        raise HTTPException(404, "Briefing not found")
    if not row.redacted_at:
        row.body_json, row.redacted_at = "{}", utc_now_naive()
        session.add(row)
        session.commit()
        session.refresh(row)
    return {**store.receipt(row), "notice": "Briefing text is removed; its input packet and external copies remain."}


@router.get("/morning")
def morning(request: Request, day: date, briefing_id: UUID | None = None, session: Session = Depends(get_session)):
    from app.engine.jo_morning import load_config, morning_view, watchdog_status
    from jo_briefing_owner import binding, load_binding
    try:
        config = load_config()
        configuration_error = False
    except Exception:
        config, configuration_error = None, True
    actor = None
    if config is not None:
        try:
            actor = binding(load_binding(config.check_config))
        except Exception:
            configuration_error = True  # delivery stays "unknown" rather than guessing the packet
    result = call(morning_view, session, day, datetime.now(timezone.utc), briefing_id, config, None, actor)
    runner = getattr(request.app.state, "jo_morning", None)
    result["automation"] = {"enabled": config is not None, "last_pass": getattr(runner, "last_pass", None),
                            "unavailable": configuration_error or bool(getattr(runner, "last_error", None)),
                            "configuration_error": configuration_error,
                            "last_status": getattr(runner, "last_status", None),
                            "pending": getattr(runner, "pending", None)}
    result["delivery"]["notifications"]["watchdog"] = watchdog_status(day)
    return result


class FeedbackSave(Strict):
    opened: bool = False
    rating: Literal["useful", "meh", "missed"] | None = None


@router.post("/briefings/{briefing_id}/feedback")
def feedback(briefing_id: UUID, body: FeedbackSave, session: Session = Depends(get_session)):
    from app.models import MorningBriefingFeedback
    if session.get(MorningBriefingRecord, briefing_id) is None:
        raise HTTPException(404, "Briefing not found")
    row = session.get(MorningBriefingFeedback, briefing_id)
    if row is None:
        session.add(MorningBriefingFeedback(briefing_id=briefing_id))
        try:
            session.commit()
        except IntegrityError:
            session.rollback()  # Another request created the same feedback row.
    now = utc_now_naive()
    values = {"updated_at": now}
    if body.opened:
        values["first_opened_at"] = func.coalesce(MorningBriefingFeedback.first_opened_at, now)
    if body.rating is not None:
        values["rating"] = body.rating
    session.execute(update(MorningBriefingFeedback).where(MorningBriefingFeedback.briefing_id == briefing_id).values(**values))
    session.commit()
    row = session.get(MorningBriefingFeedback, briefing_id)
    session.refresh(row)
    return {"rating": row.rating, "first_opened_at": store.timestamp(row.first_opened_at) if row.first_opened_at else None}
