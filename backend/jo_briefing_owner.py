"""Explicit owner publication/import using the existing Check file exchange.

No daemon, provider call, grant change or activation. Run only against an
approved database and existing exchange paths. MCP never imports this module.
"""
from datetime import datetime, timedelta, timezone
import json
from uuid import UUID

from sqlmodel import Session, select

from app.engine import jo_briefing as store
from app.models import MorningBriefingRecord
from cloud_mcp_check_common import read_config
from jo_briefing_common import BriefingSave, MemorySave
import jo_briefing_exchange as exchange


def binding(config):
    if not (config.enabled and config.jo_briefing_enabled and config.profiles[0].enabled):
        raise ValueError("Personal Jo exchange disabled")
    return config.profiles[0].id


def load_binding(path):
    """Owner-side adapter for the current validated Check exchange binding."""
    config = read_config(path)
    binding(config)
    return config


def publish(session, config, packet_id, now, *, lifetime_hours=4):
    actor = binding(config)
    if not 0 < lifetime_hours <= 24:
        raise ValueError("Publication lifetime must be at most 24 hours")
    packet = store.get_packet(session, packet_id)
    if packet["redacted_at"] or any(m["redacted_at"] for m in packet["memories"]):
        raise ValueError("Cannot publish redacted personal context")
    # Exactly one supplied packet and its referenced revisions; no implicit holdings/history export.
    value = exchange.Context(profile_id=actor, published_at=now, expires_at=now + timedelta(hours=lifetime_hours),
        packet=packet).model_dump(mode="json")
    exchange.write(config.market_watch_snapshots_dir, exchange.context_name(actor, packet_id), value)
    return {"packet_id": str(packet_id), "profile_id": actor, "expires_at": value["expires_at"],
            "context_sha256": exchange.digest(value)}


def import_submission(session, config, operation_id, now):
    actor = binding(config)
    key = exchange.operation_key(actor, operation_id)
    snapshots, outbox = config.market_watch_snapshots_dir, config.market_watch_outbox_dir
    request = exchange.Submission.model_validate(exchange.read(outbox, f"jo-request-{key}.json"))
    if request.profile_id != actor or request.operation_id != operation_id or request.body.get("operation_id") != operation_id:
        raise ValueError("Submission identity mismatch")
    # Recover a completed import without rewriting receipts, including after expiry/redaction.
    current = exchange.status(snapshots, outbox, actor, operation_id)
    if current["status"] != "pending_import":
        return current
    ack = {"profile_id": actor, "submission_sha256": exchange.digest(request.model_dump(mode="json")),
           "imported_at": now.isoformat()}
    try:
        if request.received_at > now:
            raise ValueError("Future submission")
        published = exchange.context(snapshots, actor, request.packet_id, request.received_at)
        if exchange.digest(published) != request.context_sha256:
            raise ValueError("Published context changed")
        data = exchange.validate_body(request.kind, request.body, published["packet"])
        # Namespace the tool key away from owner saves and other Check profiles.
        data["operation_id"] = "jo-" + key
        model = MemorySave if request.kind == "memory" else BriefingSave
        table = store.JoMemoryRevision if request.kind == "memory" else MorningBriefingRecord
        body = model.model_validate(data)
        existing = store.replay(session, table, body.operation_id, store.fingerprint(body))
        if existing is not None:
            saved = store.receipt(existing)
        else:
            # Refuse a context removed/changed since publication, including memory redaction.
            packet = store.get_packet(session, request.packet_id)
            if packet != published["packet"]:
                raise ValueError("Personal context changed; publish a fresh packet")
            if request.kind == "briefing" and body.supersedes_id:
                previous = session.exec(select(MorningBriefingRecord).where(
                    MorningBriefingRecord.id == body.supersedes_id)).first()
                # Only corrections to results imported from this profile, never owner/other-actor records.
                if previous is None:
                    raise ValueError("Unknown correction")
                prior_key = previous.operation_id.removeprefix("jo-")
                prior = exchange.read(snapshots, f"jo-receipt-{prior_key}.json") if len(prior_key) == 64 and all(c in '0123456789abcdef' for c in prior_key) else {}
                if prior.get("profile_id") != actor or prior.get("record_id") != str(previous.id):
                    raise ValueError("Correction ownership mismatch")
            saved = (store.save_memory if request.kind == "memory" else store.save_briefing)(session, body)
        ack.update(status="saved", record_id=saved["id"], saved_at=saved["received_at"],
                   memory_id=saved.get("memory_id"), memory_status=saved.get("status"))
    except (ValueError, LookupError):
        session.rollback()
        ack.update(status="rejected", reason="Invalid, conflicting, removed or no longer authorized personal context")
    # A DB commit followed by export failure is recovered via the namespaced operation key above.
    try:
        exchange.write(snapshots, f"jo-receipt-{key}.json", ack)
    except ValueError:
        # Concurrent importers can have distinct imported_at times, but must agree on the result.
        other = exchange.read(snapshots, f"jo-receipt-{key}.json")
        if {k: v for k, v in other.items() if k != "imported_at"} != {k: v for k, v in ack.items() if k != "imported_at"}:
            raise
    return exchange.status(snapshots, outbox, actor, operation_id)


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, help="existing approved Check configuration")
    commands = parser.add_subparsers(dest="command", required=True)
    publication = commands.add_parser("publish")
    publication.add_argument("--packet-id", required=True, type=UUID)
    publication.add_argument("--lifetime-hours", type=int, default=4)
    importing = commands.add_parser("import")
    importing.add_argument("--operation-id", required=True)
    args = parser.parse_args()
    config = read_config(args.config)
    binding(config)
    from app.database import engine
    with Session(engine) as session:
        now = datetime.now(timezone.utc)
        result = (publish(session, config, args.packet_id, now, lifetime_hours=args.lifetime_hours)
                  if args.command == "publish" else import_submission(session, config, args.operation_id, now))
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
