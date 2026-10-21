"""Personal Jo messages over the existing Check snapshot/outbox directories.

No database, private API or providers. Files are bounded, actor-bound and
immutable; a queued submission is not an application save receipt.
"""
from datetime import timedelta
import hashlib
import json
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field

from app.engine.market_watch_snapshot import _publish_immutable, _read_bounded, _fsync_directory
from jo_briefing_common import BriefingSave, MemorySave, Operation, PacketSave, Strict, validate_opportunity_evidence

READ_SCOPE = "jo:read"
SUBMIT_SCOPE = "jo:submit"
LIMIT = 512 * 1024


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def profile(value):
    if not value.startswith("check_") or str(UUID(value[6:])) != value[6:]:
        raise ValueError("Invalid Check profile")
    return value


def operation_key(actor, operation_id):
    # Validate with the same bounded identifier schema used by owner persistence.
    from pydantic import TypeAdapter
    TypeAdapter(Operation).validate_python(operation_id)
    return hashlib.sha256((profile(actor) + "\n" + operation_id).encode()).hexdigest()


def read(directory, name):
    return json.loads(_read_bounded(Path(directory) / name, LIMIT))


def write(directory, name, value):
    body = canonical(value).encode()
    if len(body) > LIMIT:
        raise ValueError("Jo exchange payload exceeds its bound")
    root = Path(directory)
    if not root.is_absolute() or any(p.is_symlink() for p in (root, *root.parents)):
        raise ValueError("Require an existing absolute exchange directory without symlinks")
    _publish_immutable(root / name, body)
    _fsync_directory(root)


class Context(Strict):
    schema_version: Literal["jo-context-v1"] = "jo-context-v1"
    profile_id: str
    published_at: AwareDatetime
    expires_at: AwareDatetime
    packet: dict


def context_name(actor, packet_id):
    return f"jo-context-{profile(actor)}-{UUID(str(packet_id))}.json"


def context(directory, actor, packet_id, now, *, allow_expired=False):
    value = Context.model_validate(read(directory, context_name(actor, packet_id)))
    if value.profile_id != actor or value.packet.get("id") != str(packet_id):
        raise ValueError("Context ownership mismatch")
    if not value.published_at <= now or not timedelta(0) < value.expires_at - value.published_at <= timedelta(hours=24):
        raise ValueError("Invalid publication time")
    if not allow_expired and now >= value.expires_at:
        raise ValueError("Personal context expired; request a fresh owner publication")
    PacketSave.model_validate(value.packet["body"])
    if value.packet.get("redacted_at"):
        raise ValueError("Packet redacted")
    return value.model_dump(mode="json")


def read_marker_name(actor, day):
    return f"jo-read-{profile(actor)}-{day}.json"


def record_read(outbox, actor, day, packet_id, now):
    """Keep the first morning read per profile and New York day; later reads leave it alone.

    No packet content: only who, which day/packet and when Check served it. A read shows
    the tool was called, not who started the run or how the packet was used.
    """
    name = read_marker_name(actor, day)
    if (Path(outbox) / name).exists():
        return
    try:
        write(outbox, name, {"schema_version": "jo-read-v1", "profile_id": actor, "day": day,
            "packet_id": str(UUID(str(packet_id))), "read_at": now.isoformat()})
    except ValueError:
        if not (Path(outbox) / name).exists():
            raise  # A concurrent first read already kept its own time; anything else is a real failure.


def read_marker(outbox, actor, day, packet_id):
    """The recorded first read of this packet, None when absent, or raise when it can't be trusted.

    Absence means "not read" only once this profile's trace is known to be live: an
    earlier day's marker exists. Before that (an old Check runtime, or days before the
    trace existed) the caller must report unknown, never "not read".
    """
    name = read_marker_name(actor, day)
    try:
        value = read(outbox, name)
    except FileNotFoundError:
        prefix = f"jo-read-{profile(actor)}-"
        if not any(p.name < name for p in Path(outbox).glob(prefix + "*.json")):
            raise LookupError("Read trace not yet live for this profile") from None
        return None
    if value.get("profile_id") != actor or value.get("day") != day or value.get("packet_id") != str(packet_id):
        raise ValueError("Read marker does not match this packet")
    return value["read_at"]


class Submission(Strict):
    schema_version: Literal["jo-submission-v1"] = "jo-submission-v1"
    profile_id: str
    operation_id: Operation
    packet_id: UUID
    context_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    kind: Literal["memory", "briefing"]
    body: dict
    received_at: AwareDatetime


def validate_body(kind, body, packet):
    if kind == "memory":
        value = MemorySave.model_validate(body)
        if value.memory_id or value.base_revision or value.status != "proposed" or value.owner_confirmed or value.source != "jo_proposal":
            raise ValueError("Jo may only propose a new memory; owner acceptance stays private")
    else:
        value = BriefingSave.model_validate(body)
        if str(value.packet_id) != packet["id"] or value.author != "Jo":
            raise ValueError("Briefing must name this packet and Jo as its supplied author")
        ids = {e["id"] for e in packet["body"]["evidence"]}
        refs = value.summary_evidence_ids + [ref for item in [*value.items, *value.opportunities, *value.urgent_positions] for ref in item.evidence_ids]
        if any(ref not in ids for ref in refs):
            raise ValueError("Citations must resolve to the frozen packet")
        validate_opportunity_evidence(value, packet)
        if not value.summary_evidence_ids and (value.items or value.opportunities or value.urgent_positions or not value.limitations):
            raise ValueError("Uncited output must be unavailable with limitations")
    data = value.model_dump(mode="json")
    if len(canonical(data).encode()) > 128 * 1024:
        raise ValueError("Request exceeds 128 KiB")
    return data


def submit(snapshots, outbox, actor, packet_id, kind, body, now):
    key = operation_key(actor, body["operation_id"])
    name = f"jo-request-{key}.json"
    try:
        prior = Submission.model_validate(read(outbox, name)).model_dump(mode="json")
    except FileNotFoundError:
        prior = None
    if prior is not None:
        if (prior["profile_id"] != actor or prior["kind"] != kind or prior["packet_id"] != str(packet_id)
                or prior["body"] != body):
            raise ValueError("Operation ID already used for different content")
        return status(snapshots, outbox, actor, body["operation_id"])
    published = context(snapshots, actor, packet_id, now)
    body = validate_body(kind, body, published["packet"])
    request = Submission(profile_id=actor, operation_id=body["operation_id"], packet_id=packet_id,
        context_sha256=digest(published), kind=kind, body=body, received_at=now).model_dump(mode="json")
    try:
        write(outbox, name, request)
    except ValueError:
        # A concurrent identical request can have a different receipt clock.
        other = Submission.model_validate(read(outbox, name)).model_dump(mode="json")
        if {k: v for k, v in other.items() if k != "received_at"} != {k: v for k, v in request.items() if k != "received_at"}:
            raise
    return status(snapshots, outbox, actor, body["operation_id"])


def status(snapshots, outbox, actor, operation_id):
    key = operation_key(actor, operation_id)
    request = Submission.model_validate(read(outbox, f"jo-request-{key}.json")).model_dump(mode="json")
    if request["profile_id"] != actor or request["operation_id"] != operation_id:
        raise ValueError("Receipt ownership mismatch")
    base = {"operation_id": operation_id, "submission_sha256": digest(request), "kind": request["kind"],
            "received_at": request["received_at"], "labels": ["personal_advice", "independence-unverified"]}
    try:
        ack = read(snapshots, f"jo-receipt-{key}.json")
    except FileNotFoundError:
        return {**base, "status": "pending_import", "app_saved": False}
    if (ack.get("profile_id") != actor or ack.get("submission_sha256") != digest(request)
            or ack.get("status") not in ("saved", "rejected")):
        raise ValueError("Application receipt mismatch")
    return {**base, **ack, "app_saved": ack["status"] == "saved"}
