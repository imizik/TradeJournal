"""Jo research over the existing Check snapshot/outbox directories (docs/agent/dots-integration.md § Jo research role).

The app publishes three read-only contexts (dossier, audit, red_team) as immutable, time-stamped files; Check serves
the newest unexpired one. Jo's research goes back as one sealed, write-once submission per operation ID; the app
importer saves it as research and writes the receipt. No database, private API or providers here.
"""
from datetime import timedelta
from pathlib import Path
from typing import Literal

from pydantic import AwareDatetime, Field

from jo_briefing_common import Operation, Strict
import jo_briefing_exchange as exchange
from jo_research_common import CONTEXT_KINDS, ResearchSave

LIFETIME = timedelta(hours=24)
SKEW = timedelta(minutes=5)
LABELS = ["research", "independence-unverified"]


class Context(Strict):
    schema_version: Literal["jo-research-context-v1"] = "jo-research-context-v1"
    profile_id: str
    kind: Literal["dossier", "audit", "red_team"]
    as_of: AwareDatetime
    published_at: AwareDatetime
    expires_at: AwareDatetime
    data: dict


def stamp(when):
    return when.strftime("%Y%m%dT%H%M%S%fZ")


def context_prefix(actor, kind):
    if kind not in CONTEXT_KINDS:
        raise ValueError("Unknown research context")
    return f"jo-research-{exchange.profile(actor)}-{kind}-"


def context_name(actor, kind, published_at):
    return context_prefix(actor, kind) + stamp(published_at) + ".json"


def context(snapshots, actor, kind, now):
    """The newest published context of ``kind`` at ``now``; FileNotFoundError when none, ValueError when expired."""
    prefix = context_prefix(actor, kind)
    names = sorted((p.name for p in Path(snapshots).glob(prefix + "*.json")), reverse=True)
    for name in names:
        value = Context.model_validate(exchange.read(snapshots, name))
        if value.published_at > now + SKEW:
            continue
        if value.profile_id != actor or value.kind != kind or name != context_name(actor, kind, value.published_at):
            raise ValueError("Research context identity mismatch")
        if not value.as_of <= value.published_at or not timedelta(0) < value.expires_at - value.published_at <= LIFETIME:
            raise ValueError("Invalid publication time")
        if now >= value.expires_at:
            raise ValueError("Research context expired")
        data = value.model_dump(mode="json")
        return {"context_id": exchange.digest(data)[:16], "kind": kind, "as_of": data["as_of"],
                "published_at": data["published_at"], "expires_at": data["expires_at"], "data": data["data"],
                "labels": LABELS}
    raise FileNotFoundError(kind)


def pending_requests(snapshots, actor, now):
    try:
        return {row["request_id"] for row in context(snapshots, actor, "red_team", now)["data"]["requests"]}
    except (FileNotFoundError, ValueError, KeyError, TypeError):
        return set()  # no current red-team context: nothing is pending


class Submission(Strict):
    schema_version: Literal["jo-research-submission-v1"] = "jo-research-submission-v1"
    profile_id: str
    operation_id: Operation
    body: dict
    received_at: AwareDatetime
    body_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def request_name(key):
    return f"jo-research-request-{key}.json"


def receipt_name(key):
    return f"jo-research-receipt-{key}.json"


def validate_body(body, received_at):
    value = ResearchSave.model_validate(body)
    if value.as_of > received_at + SKEW:
        raise ValueError("as_of cannot be after the submission")
    data = value.model_dump(mode="json")
    if len(exchange.canonical(data).encode()) > 64 * 1024:
        raise ValueError("Research exceeds 64 KiB")
    return data


def submit(snapshots, outbox, actor, body, now):
    """Seal one research submission; an identical retry returns its current status, different content is refused."""
    key = exchange.operation_key(actor, body["operation_id"])
    name = request_name(key)
    try:
        prior = Submission.model_validate(exchange.read(outbox, name)).model_dump(mode="json")
    except FileNotFoundError:
        prior = None
    if prior is not None:
        if prior["profile_id"] != actor or prior["body"] != ResearchSave.model_validate(body).model_dump(mode="json"):
            raise ValueError("Operation ID already used for different content")
        return status(snapshots, outbox, actor, body["operation_id"])
    data = validate_body(body, now)
    if data["kind"] == "red_team" and data["request_id"] not in pending_requests(snapshots, actor, now):
        raise LookupError("No pending red-team request has that ID")
    request = Submission(profile_id=actor, operation_id=data["operation_id"], body=data, received_at=now,
                         body_sha256=exchange.digest(data)).model_dump(mode="json")
    try:
        exchange.write(outbox, name, request)
    except ValueError:
        # A concurrent identical request can have a different receipt clock.
        other = Submission.model_validate(exchange.read(outbox, name)).model_dump(mode="json")
        if {k: v for k, v in other.items() if k != "received_at"} != {k: v for k, v in request.items() if k != "received_at"}:
            raise
    return status(snapshots, outbox, actor, data["operation_id"])


def status(snapshots, outbox, actor, operation_id):
    key = exchange.operation_key(actor, operation_id)
    request = Submission.model_validate(exchange.read(outbox, request_name(key))).model_dump(mode="json")
    if request["profile_id"] != actor or request["operation_id"] != operation_id:
        raise ValueError("Receipt ownership mismatch")
    base = {"operation_id": operation_id, "submission_sha256": exchange.digest(request), "kind": request["body"]["kind"],
            "received_at": request["received_at"], "labels": LABELS}
    try:
        ack = exchange.read(snapshots, receipt_name(key))
    except FileNotFoundError:
        return {**base, "status": "pending_import", "app_saved": False}
    if (ack.get("profile_id") != actor or ack.get("submission_sha256") != exchange.digest(request)
            or ack.get("status") not in ("saved", "rejected")):
        raise ValueError("Application receipt mismatch")
    return {**base, **{k: v for k, v in ack.items() if k != "profile_id"}, "app_saved": ack["status"] == "saved"}
