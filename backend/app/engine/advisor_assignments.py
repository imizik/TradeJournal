"""Bounded owner-managed questions inside one existing invented fixture ledger."""
from copy import deepcopy
from datetime import timedelta
import uuid

from app.engine import advisor_shadow as service, decisions, practice
from app.models import PracticeAgentCall

KEY = "advisor_assignments_v1"
MAX_QUESTIONS = 20
IDENTITY = ("version", "assignment_id", "run_id", "packet_sha256", "request_sha256")
REQUEST_KEYS = (*IDENTITY[:-1], "expires_at", "requested_at", "comparison", "question", "user_plan")


def anchor(db, profile):
    # The original immutable handoff bounds every later question to this fixture.
    call = db.get(PracticeAgentCall, uuid.UUID(profile.assignment_id))
    if call is None or str(call.run_id) != profile.run_id:
        raise decisions.DecisionError("Invented advisor anchor unavailable")
    _, config, packet = service.assignment(db, call)
    original = config.get("advisor", {}).get("export", {})
    if (original.get("version") != service.HANDOFF_VERSION or original.get("demo_only") is not True
            or any(original.get(k) != getattr(profile, k) for k in IDENTITY[1:])
            or original.get("packet") != packet
            or service.digest({k: original[k] for k in REQUEST_KEYS}) != profile.request_sha256):
        raise decisions.DecisionError("Invented advisor anchor changed")
    ledger = config.get(KEY, {"selected": None, "entries": []})
    if len(ledger["entries"]) > MAX_QUESTIONS:
        raise decisions.DecisionError("Advisor assignment limit exceeded")
    return call, config, original, ledger


def validate(entry, original):
    request = entry["request"]
    if (request["packet"] != original["packet"] or request["run_id"] != original["run_id"]
            or request["packet_sha256"] != original["packet_sha256"]
            or request["version"] != service.HANDOFF_VERSION or request["demo_only"] is not True
            or service.digest({k: request[k] for k in REQUEST_KEYS}) != request["request_sha256"]):
        raise decisions.DecisionError("Managed advisor request changed")
    saved = entry["receipt"]
    if saved is not None:
        envelope = saved["submitted_output"]
        if (set(envelope) != {*IDENTITY, "answer"}
                or any(saved[k] != request[k] or envelope[k] != request[k] for k in IDENTITY)
                or saved["receipt_sha256"] != service.digest({k: v for k, v in saved.items() if k != "receipt_sha256"})
                or saved["transport"] != "oauth-mcp" or saved["demo_only"] is not True):
            raise decisions.DecisionError("Managed advisor receipt changed")
        service.validate_handoff_answer(envelope["answer"], request["packet"])
    return entry


def status(entry):
    if not entry["enabled"]:
        return "revoked"
    if entry["receipt"] is not None:
        return "answered"
    if practice.now_utc() >= decisions._utc(entry["request"]["expires_at"], "expiry"):
        return "expired"
    return "pending"


def active(entry):
    service.active_assignment({"enabled": entry["enabled"], "expires_at": entry["request"]["expires_at"]})


def selected(db, profile):
    _, _, original, ledger = anchor(db, profile)
    entry = next((e for e in ledger["entries"] if e["request"]["assignment_id"] == ledger["selected"]), None)
    if entry is None:
        raise decisions.DecisionError("No advisor question assigned")
    validate(entry, original)
    active(entry)
    return entry


def owner_view(db, profile, assignment_id=None):
    _, _, original, ledger = anchor(db, profile)
    entries = [validate(e, original) for e in ledger["entries"]]
    result = {"schema_version": KEY, "demo_only": True, "selected": ledger["selected"],
        "assignments": [{"assignment_id": e["request"]["assignment_id"], "question": e["request"]["question"][:120],
            "requested_at": e["request"]["requested_at"], "status": status(e)} for e in reversed(entries)]}
    if assignment_id is not None:
        entry = next((e for e in entries if e["request"]["assignment_id"] == assignment_id), None)
        if entry is None:
            raise decisions.DecisionError("Advisor assignment unavailable")
        result["record"] = {"request": entry["request"], "receipt": entry["receipt"], "status": status(entry)}
    return service.bounded(result)


def mutate(db, profile, body, authorize):
    service.lock(db)
    try:
        authorize()
        call, config, original, ledger = anchor(db, profile)
        if set(body) == {"operation_id", "question", "user_plan", "invented_only"}:
            operation = str(uuid.UUID(body["operation_id"]))
            if body["operation_id"] != operation or body["invented_only"] is not True or any(
                    not isinstance(body[k], str) or not body[k].strip() or len(body[k]) > 2000 for k in ("question", "user_plan")):
                raise decisions.DecisionError("Confirm invented text and supply a bounded question and plan")
            existing = next((e for e in ledger["entries"] if e["operation_id"] == operation), None)
            if existing:
                if any(existing["request"][k] != body[k] for k in ("question", "user_plan")):
                    raise decisions.DecisionError("Create operation already has different content")
                result = owner_view(db, profile, existing["request"]["assignment_id"])
                authorize()
                db.rollback()
                return result
            if len(ledger["entries"]) >= MAX_QUESTIONS:
                raise decisions.DecisionError("This invented fixture has reached its 20 question limit")
            if any(e["request"]["assignment_id"] == ledger["selected"] and status(e) == "pending" for e in ledger["entries"]):
                raise decisions.DecisionError("Answer or revoke the pending assignment first")
            request = deepcopy(original)
            request.update(assignment_id=str(uuid.uuid4()), requested_at=practice.iso(practice.now_utc()),
                expires_at=practice.iso(practice.now_utc() + timedelta(minutes=30)), comparison="assisted",
                question=body["question"], user_plan=body["user_plan"])
            request["request_sha256"] = service.digest({k: request[k] for k in REQUEST_KEYS})
            request["answer_contract"].update({k: request[k] for k in IDENTITY})
            service.bounded(request)
            entry = {"operation_id": operation, "request": request, "receipt": None, "enabled": True}
            ledger["entries"].append(entry)
            ledger["selected"] = request["assignment_id"]
            assignment_id = request["assignment_id"]
        elif set(body) == {"revoke"}:
            assignment_id = str(uuid.UUID(body["revoke"]))
            entry = next((e for e in ledger["entries"] if e["request"]["assignment_id"] == assignment_id), None)
            if entry is None:
                raise decisions.DecisionError("Advisor assignment unavailable")
            validate(entry, original)
            entry["enabled"] = False
        else:
            raise decisions.DecisionError("Unsupported advisor management action")
        config[KEY] = ledger
        call.config_json = service.canonical(config)
        db.add(call)
        db.flush()
        result = owner_view(db, profile, assignment_id)
        authorize()
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise


def save(db, profile, body, authorize):
    service.lock(db)
    try:
        authorize()
        call, config, _, ledger = anchor(db, profile)
        entry = selected(db, profile)
        request = entry["request"]
        if set(body) != {"packet_sha256", "request_sha256", "answer"} or any(body[k] != request[k] for k in ("packet_sha256", "request_sha256")):
            raise decisions.DecisionError("Answer does not match the currently assigned immutable request")
        service.validate_handoff_answer(body["answer"], request["packet"])
        envelope = {**{k: request[k] for k in IDENTITY}, "answer": body["answer"]}
        if entry["receipt"] is not None:
            if entry["receipt"]["submitted_output"] != envelope:
                raise decisions.DecisionError("Immutable answer conflict")
            authorize()
            active(entry)
            db.rollback()
            return entry["receipt"]
        receipt = service.answer_receipt(request, envelope, "oauth-mcp")
        # selected() reloaded JSON; update the entry in this transaction's ledger.
        target = next(e for e in ledger["entries"] if e["request"]["assignment_id"] == request["assignment_id"])
        target["receipt"] = receipt
        config[KEY] = ledger
        call.config_json = service.canonical(config)
        db.add(call)
        authorize()
        active(entry)
        db.commit()
        return receipt
    except Exception:
        db.rollback()
        raise
