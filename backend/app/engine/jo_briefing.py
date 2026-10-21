"""Private owner persistence only: no providers, model calls, schedules or Shadow imports."""
from datetime import datetime, timezone
import hashlib
import json
from uuid import UUID, uuid4

from sqlalchemy import func, update
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.models import JoMemoryRevision, MorningBriefingPacket, MorningBriefingRecord, MorningBriefingSubmission, utc_now_naive

from jo_briefing_common import (  # noqa: F401 — retained owner API imports
    BriefingSave, MemoryRedact, MemorySave, PacketSave, validate_opportunity_evidence,
)


class Conflict(ValueError):
    pass


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def fingerprint(body):
    encoded = canonical(body.model_dump(mode="json")).encode()
    if len(encoded) > 128 * 1024:
        raise ValueError("Request exceeds 128 KiB")
    return hashlib.sha256(encoded).hexdigest()


def timestamp(value):
    return value.replace(tzinfo=timezone.utc).isoformat()


def receipt(row):
    result = {"id": str(row.id), "operation_id": row.operation_id,
              "received_at": timestamp(row.created_at), "body": json.loads(row.body_json)}
    if isinstance(row, JoMemoryRevision):
        result.update(memory_id=str(row.memory_id), revision=row.revision, status=row.status, symbol=row.symbol)
    if isinstance(row, MorningBriefingPacket):
        result.update(day=row.day.isoformat(), provenance="owner_supplied")
    if isinstance(row, MorningBriefingRecord):
        result.update(packet_id=str(row.packet_id), provenance="owner_supplied",
                      labels=["personal_advice", "independence-unverified"])
    if hasattr(row, "redacted_at"):
        result["redacted_at"] = timestamp(row.redacted_at) if row.redacted_at else None
    return result


def replay(session, table, operation_id, sha):
    row = session.exec(select(table).where(table.operation_id == operation_id)).first()
    if row is not None and row.request_sha256 != sha:
        raise Conflict("Operation ID already used for different content")
    return row


def persist(session, row):
    session.add(row)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = replay(session, type(row), row.operation_id, row.request_sha256)
        if existing is None:
            raise Conflict("Revision changed; reload before saving") from None
        return receipt(existing)
    session.refresh(row)
    return receipt(row)


def latest_memory(session, memory_id):
    return session.exec(select(JoMemoryRevision).where(JoMemoryRevision.memory_id == memory_id)
                        .order_by(JoMemoryRevision.revision.desc()).limit(1)).first()


def save_memory(session: Session, body: MemorySave):
    sha = fingerprint(body)
    existing = replay(session, JoMemoryRevision, body.operation_id, sha)
    if existing is not None:
        return receipt(existing)
    if body.memory_id:
        latest = latest_memory(session, body.memory_id)
        if latest is None:
            raise LookupError("Memory not found")
        if latest.redacted_at or latest.revision != body.base_revision:
            raise Conflict("Memory changed or was redacted; reload before saving")
    return persist(session, JoMemoryRevision(memory_id=body.memory_id or uuid4(),
        revision=body.base_revision + 1, operation_id=body.operation_id, request_sha256=sha,
        status=body.status, symbol=body.symbol, body_json=canonical(body.model_dump(mode="json"))))


def memories(session, status="active", symbol=None, limit=50):
    latest = select(JoMemoryRevision.memory_id, func.max(JoMemoryRevision.revision).label("revision")) \
        .group_by(JoMemoryRevision.memory_id).subquery()
    query = select(JoMemoryRevision).join(latest,
        (JoMemoryRevision.memory_id == latest.c.memory_id) & (JoMemoryRevision.revision == latest.c.revision))
    if status:
        query = query.where(JoMemoryRevision.status == status)
    if symbol:
        query = query.where(JoMemoryRevision.symbol == symbol)
    return [receipt(row) for row in session.exec(query.order_by(JoMemoryRevision.created_at.desc(),
        JoMemoryRevision.id).limit(limit)).all()]


def redact_memory(session, memory_id, body: MemoryRedact):
    # Keep ID/hash tombstones so retries cannot restore the removed text.
    sha = hashlib.sha256((str(memory_id) + fingerprint(body)).encode()).hexdigest()
    existing = replay(session, JoMemoryRevision, body.operation_id, sha)
    if existing is not None:
        return receipt(existing)
    latest = latest_memory(session, memory_id)
    if latest is None:
        raise LookupError("Memory not found")
    if latest.revision != body.base_revision or latest.redacted_at:
        raise Conflict("Memory changed or was redacted; reload before saving")
    now = utc_now_naive()
    row = JoMemoryRevision(memory_id=memory_id, revision=body.base_revision + 1,
        operation_id=body.operation_id, request_sha256=sha, status="redacted", body_json="{}", redacted_at=now)
    # Revision uniqueness serializes redaction against concurrent amendments.
    session.add(row)
    try:
        session.flush()
        session.exec(update(JoMemoryRevision).where(JoMemoryRevision.memory_id == memory_id)
                     .values(body_json="{}", symbol=None, status="redacted", redacted_at=now))
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = replay(session, JoMemoryRevision, body.operation_id, sha)
        if existing is None:
            raise Conflict("Memory changed; reload before redacting") from None
        return receipt(existing)
    session.refresh(row)
    return receipt(row)


def save_packet(session, body: PacketSave):
    sha = fingerprint(body)
    existing = replay(session, MorningBriefingPacket, body.operation_id, sha)
    if existing is not None:
        return receipt(existing)
    if body.as_of > datetime.now(timezone.utc):
        raise ValueError("Packet as_of cannot be in the future")
    for revision_id in body.memory_revision_ids:
        row = session.get(JoMemoryRevision, revision_id)
        if row is None or row.status != "active" or row.redacted_at:
            raise ValueError("Packet memory must name an active, unredacted revision")
        latest = latest_memory(session, row.memory_id)
        if latest.id != row.id:
            raise Conflict("Packet memory revision is no longer current")
    return persist(session, MorningBriefingPacket(operation_id=body.operation_id, request_sha256=sha,
        day=body.day, body_json=canonical(body.model_dump(mode="json"))))


def get_packet(session, packet_id):
    row = session.get(MorningBriefingPacket, packet_id)
    if row is None:
        raise LookupError("Packet not found")
    result = receipt(row)
    # References preserve the historical revision, not today's replacement.
    result["memories"] = [receipt(session.get(JoMemoryRevision, UUID(key)))
                          for key in result["body"].get("memory_revision_ids", [])]
    return result


def save_briefing(session, body: BriefingSave, submitted_at=None):
    """submitted_at: when Check received an imported submission (naive UTC); None when unknown."""
    sha = fingerprint(body)
    existing = replay(session, MorningBriefingRecord, body.operation_id, sha)
    if existing is not None:
        return receipt(existing)
    packet = get_packet(session, body.packet_id)
    if packet["redacted_at"]:
        raise Conflict("Cannot submit against a redacted packet")
    evidence_ids = {item["id"] for item in packet["body"]["evidence"]}
    references = body.summary_evidence_ids + [ref for item in [*body.items, *body.opportunities, *body.urgent_positions] for ref in item.evidence_ids]
    if any(ref not in evidence_ids for ref in references):
        raise ValueError("Every citation must resolve to the frozen packet")
    validate_opportunity_evidence(body, packet)
    if not body.summary_evidence_ids and (body.items or body.opportunities or body.urgent_positions or not body.limitations):
        raise ValueError("An uncited summary must be an unavailable briefing with explicit limitations")
    if body.supersedes_id:
        previous = session.get(MorningBriefingRecord, body.supersedes_id)
        if previous is None or session.get(MorningBriefingPacket, previous.packet_id).day.isoformat() != packet["day"]:
            raise ValueError("A correction must reference a briefing for the same day")
    row = MorningBriefingRecord(operation_id=body.operation_id, request_sha256=sha,
        packet_id=body.packet_id, body_json=canonical(body.model_dump(mode="json")))
    if submitted_at is not None:
        # Committed with the record, so a saved import never lacks its receipt time.
        session.add(MorningBriefingSubmission(briefing_id=row.id, submitted_at=submitted_at))
    return persist(session, row)
