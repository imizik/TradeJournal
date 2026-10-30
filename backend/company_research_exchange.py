"""Actor-bound frozen company assignments and sealed research responses."""
from datetime import datetime, timezone
from uuid import UUID

import jo_briefing_exchange as files
from company_research_common import FindingBody


def context_name(actor, identifier):
    return f"company-context-{files.profile(actor)}-{UUID(str(identifier))}.json"


def context(root, actor, identifier, now):
    data = files.read(root, context_name(actor, identifier))
    if data["actor"] != actor or data["id"] != str(identifier) or data["status"] != "queued":
        raise ValueError("Assignment identity or status mismatch")
    expires = datetime.fromisoformat(data["expires_at"].replace("Z", "+00:00"))
    now = now.replace(tzinfo=timezone.utc) if now.tzinfo is None else now
    if expires <= now or (expires - now).total_seconds() > 86400:
        raise ValueError("Assignment expired or invalid")
    # Context hash comes from the app, never from agent input.
    return data


def submit(root, outbox, actor, identifier, body, now):
    body = FindingBody.model_validate(body)
    payload = body.model_dump(mode="json")
    if len(files.canonical(payload).encode()) > 65536:
        raise ValueError("Research exceeds 64 KiB")
    key = files.operation_key(actor, body.operation_id)
    name = f"company-request-{key}.json"
    try:
        prior = files.read(outbox, name)
    except FileNotFoundError:
        prior = None
    if prior is not None:
        if prior["actor"] != actor or prior["assignment_id"] != str(identifier) or prior["payload"] != payload:
            raise ValueError("Operation ID already used")
        return receipt(root, actor, body.operation_id)
    packet = context(root, actor, identifier, now)
    if body.context_hash != packet["context_hash"] or (body.kind != "question" and not body.sources):
        raise ValueError("Context or source evidence missing")
    # One sealed result per finite assignment bounds repeated operations. A retry
    # can finish publication after a crash between this binding and the request.
    binding = {"actor": actor, "assignment_id": str(identifier), "operation_id": body.operation_id,
               "digest": files.digest(payload)}
    files.write(outbox, f"company-assignment-{files.profile(actor)}-{UUID(str(identifier))}.json", binding)
    name = f"company-request-{key}.json"
    value = {"actor": actor, "assignment_id": str(identifier), "payload": payload,
             "digest": files.digest(payload), "received_at": now.isoformat()}
    try:
        old = files.read(outbox, name)
    except FileNotFoundError:
        old = None
    if old is not None:
        if any(old[k] != value[k] for k in ("actor", "assignment_id", "payload", "digest")):
            raise ValueError("Operation ID already used")
    else:
        try:
            files.write(outbox, name, value)
        except ValueError:
            concurrent = files.read(outbox, name)
            if any(concurrent[k] != value[k] for k in ("actor", "assignment_id", "payload", "digest")):
                raise
    return receipt(root, actor, body.operation_id)


def receipt(root, actor, operation_id):
    key = files.operation_key(actor, operation_id)
    try:
        data = files.read(root, f"company-receipt-{key}.json")
    except FileNotFoundError:
        return {"status": "pending_import", "app_saved": False}
    if data["actor"] != actor or data["operation_id"] != operation_id:
        raise ValueError("Receipt identity mismatch")
    return data
