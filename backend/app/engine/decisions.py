"""Immutable, non-executable Practice decision records (A1)."""
from __future__ import annotations

import hashlib
import json
import math
import re
import uuid
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.engine.chart_math import ET
from app.models import DecisionContext, DecisionRecord, PracticeOpportunity

MAX_FRESHNESS_SECONDS = 86_400  # one regular-session day; P0 may choose less
POLICY_VERSION = "practice-long-15m-v1"
POLICY_SPEC = {
    "version": POLICY_VERSION,
    "instrument": "stock", "direction": "long",
    "trigger": {"kind": "close_beyond_level", "interval": "15m", "session": "regular"},
    "max_holding_sessions": 2,
    "max_freshness_seconds": MAX_FRESHNESS_SECONDS,
    "status": "practice_draft_unarmed",
}
POLICY_HASH = hashlib.sha256(json.dumps(POLICY_SPEC, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
SAMPLE_POLICY_VERSION = "practice-sample-long-15m-v1"
SAMPLE_POLICY_SPEC = {**POLICY_SPEC, "version": SAMPLE_POLICY_VERSION,
                      "source": "sample_fixture", "execution": "disabled"}
SAMPLE_POLICY_HASH = hashlib.sha256(json.dumps(SAMPLE_POLICY_SPEC, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
REPLAY_POLICY_VERSION = "practice-sample-replay-long-15m-v1"
REPLAY_POLICY_SPEC = {**SAMPLE_POLICY_SPEC, "version": REPLAY_POLICY_VERSION, "execution": "separate_sample_replay_only"}
REPLAY_POLICY_HASH = hashlib.sha256(json.dumps(REPLAY_POLICY_SPEC, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
MARKET_POLICY_VERSION = "practice-market-decision-only-v1"
MARKET_POLICY_SPEC = {**POLICY_SPEC, "version": MARKET_POLICY_VERSION,
    "symbols": ["MU", "NBIS"], "source": "frozen_alpaca_raw", "execution": "disabled",
    "decision_window_seconds": 3600, "latest_bar_max_age_seconds": 300,
    "plan_fact_max_age_seconds": 7200}
MARKET_POLICY_HASH = hashlib.sha256(json.dumps(MARKET_POLICY_SPEC, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class DecisionError(ValueError):
    pass


def _utc(value: str | datetime, name: str) -> datetime:
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError) as exc:
        raise DecisionError(f"{name} must be an ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise DecisionError(f"{name} must include a timezone")
    return parsed.astimezone(timezone.utc).replace(tzinfo=None)


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def saved_context(db: Session, operation_id: str, symbol: str) -> tuple[DecisionContext, dict] | None:
    item = db.exec(select(DecisionContext).where(DecisionContext.operation_id == operation_id)).first()
    if item is None:
        return None
    if item.symbol != symbol.strip().upper():
        raise DecisionError("context operation_id already exists for a different symbol")
    return item, json.loads(item.data_json)


def freeze_context(db: Session, operation_id: str, symbol: str, packet: dict, *, captured_at: datetime | None = None,
                   commit: bool = True) -> tuple[DecisionContext, dict]:
    if not isinstance(operation_id, str) or not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", operation_id):
        raise DecisionError("context operation_id must be 1–128 safe characters")
    symbol = symbol.strip().upper()
    if packet.get("symbol", "").upper() != symbol:
        raise DecisionError("context packet symbol does not match request")
    captured = datetime.now(timezone.utc).replace(tzinfo=None)
    if captured_at is not None:
        captured = _utc(captured_at, "capture time")
        if captured > datetime.now(timezone.utc).replace(tzinfo=None):
            raise DecisionError("capture time cannot be in the future")
    source = str(packet.get("data_source") or "unknown")
    verified_source = source in {"alpaca_iex", "alpaca_sip"}
    facts = []
    for index, bar in enumerate(packet.get("recent_minute_bars") or []):
        try:
            formed = _utc(bar["t"], "bar timestamp") + timedelta(minutes=1)
        except (KeyError, DecisionError):
            continue
        # Only completed source bars can support a frozen price fact.
        if formed > captured:
            continue
        for field in ("o", "h", "l", "c", "vw"):
            value = bar.get(field)
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                continue
            if not math.isfinite(numeric) or numeric <= 0:
                continue
            facts.append({
                "name": f"minute:{index}:{field}", "source_path": f"recent_minute_bars.{index}.{field}",
                "value": numeric, "currency": "USD", "unit": "USD/share", "source": source,
                "formed_at": formed.replace(tzinfo=timezone.utc).isoformat(),
                "observed_at": captured.replace(tzinfo=timezone.utc).isoformat(),
                "symbol": symbol, "split_basis": "raw" if verified_source else (
                    "simulated_raw" if source == "sample_fixture" and packet.get("sample_data") is True else "unknown"),
            })
    state = "unavailable" if source == "unknown" or not packet.get("recent_minute_bars") else (
        "partial" if packet.get("missing") else "ready")
    evidence = {"context_version": 1, "context_state": state, "symbol": symbol, "provider": source,
                "captured_at": captured.replace(tzinfo=timezone.utc).isoformat(),
                "packet": packet, "price_facts": facts}
    data_json = _canonical(evidence)
    item = DecisionContext(operation_id=operation_id, symbol=symbol, captured_at=captured, provider=source,
                           data_json=data_json, context_sha256=_hash(data_json))
    db.add(item)
    try:
        if commit:
            db.commit()
        else:
            db.flush()
    except IntegrityError:
        db.rollback()
        previous = saved_context(db, operation_id, symbol)
        if previous:
            return previous
        raise DecisionError("context could not be saved")
    db.refresh(item)
    return item, evidence


def context_row(item: DecisionContext, evidence: dict) -> dict:
    return {"context_id": str(item.id), "symbol": item.symbol,
            "captured_at": item.captured_at.replace(tzinfo=timezone.utc).isoformat(),
            "provider": item.provider, "context_sha256": item.context_sha256,
            "price_facts": evidence["price_facts"], "packet": evidence["packet"]}


def _validate_request(request: dict) -> tuple[str, str, str, str, uuid.UUID, dict]:
    operation_id = request.get("operation_id")
    opportunity_id = request.get("opportunity_id")
    actor = request.get("actor")
    decision = request.get("decision")
    symbol = request.get("symbol")
    try:
        context_id = uuid.UUID(str(request.get("context_id")))
    except (ValueError, TypeError, AttributeError) as exc:
        raise DecisionError("context_id must identify a saved server context") from exc
    if not isinstance(operation_id, str) or not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", operation_id):
        raise DecisionError("operation_id must be 1–128 safe characters")
    if not isinstance(opportunity_id, str) or not opportunity_id.strip():
        raise DecisionError("opportunity_id is required")
    if actor != "human" and not (isinstance(actor, str) and actor.startswith("agent:") and len(actor) <= 128):
        raise DecisionError("actor must be human or agent:<identity>")
    if decision not in {"take", "wait", "skip"}:
        raise DecisionError("decision must be take, wait, or skip")
    if not isinstance(symbol, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9.-]{0,14}", symbol):
        raise DecisionError("symbol must be a valid underlying ticker")
    detail = {"plan": request.get("plan") or {}, "rationale": request.get("rationale", ""),
              "wait_condition": request.get("wait_condition"), "wait_expiry": request.get("wait_expiry")}
    if decision == "take" and not isinstance(request.get("plan"), dict):
        raise DecisionError("TAKE requires a typed plan")
    if decision != "take" and request.get("plan") is not None:
        raise DecisionError("WAIT and SKIP cannot include a TAKE plan")
    if decision == "wait":
        if not isinstance(detail["wait_condition"], str) or not detail["wait_condition"].strip():
            raise DecisionError("WAIT requires a condition that would change the decision")
        if not detail["wait_expiry"]:
            raise DecisionError("WAIT requires an expiry")
    if decision == "skip" and not str(detail["rationale"]).strip():
        raise DecisionError("SKIP requires a reason")
    return operation_id, opportunity_id, actor, decision, context_id, {"symbol": symbol.upper(), **detail}


def _finite_positive(value: object, label: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise DecisionError(f"{label} must be a finite positive price") from exc
    if not math.isfinite(parsed) or parsed <= 0:
        raise DecisionError(f"{label} must be a finite positive price")
    return parsed


def _validate_take(symbol: str, cutoff: datetime, evidence: dict, plan: dict, now: datetime, *, sample: bool = False) -> dict:
    if plan.get("instrument") != "stock" or plan.get("direction") != "long":
        raise DecisionError("A1 supports long underlying shares only")
    if plan.get("trigger") != POLICY_SPEC["trigger"]:
        raise DecisionError("A1 trigger must be a regular-session 15-minute close beyond a frozen level")
    try:
        level = _finite_positive(plan["trigger_level"], "trigger_level")
        stop = _finite_positive(plan["stop"], "stop")
        target = _finite_positive(plan["target"], "target")
        guard = plan["entry_guard"]
        guard_min = _finite_positive(guard["min"], "entry_guard.min")
        guard_max = _finite_positive(guard["max"], "entry_guard.max")
        freshness = int(plan["freshness_limit_seconds"])
        costs = plan["cost_model"]
        cost_version = costs["version"]
        slippage_bps = float(costs["slippage_bps"])
        slippage_per_share = float(costs["slippage_per_share"])
        expiry = _utc(plan["expiry"], "plan.expiry")
        refs = {key: str(plan[key]) for key in ("trigger_fact", "stop_fact", "target_fact")}
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise DecisionError("TAKE requires source fact references, levels, guard, expiry, freshness limit, and versioned costs") from exc
    if not all(math.isfinite(n) for n in (slippage_bps, slippage_per_share)) or slippage_bps < 0 or slippage_per_share < 0:
        raise DecisionError("cost_model needs a version and finite nonnegative slippage parameters")
    if not isinstance(cost_version, str) or not cost_version.strip():
        raise DecisionError("cost_model needs a version and finite nonnegative slippage parameters")
    if not stop < level < target:
        raise DecisionError("long plan prices must satisfy stop < trigger level < target")
    if guard_min < level or not 0 < guard_min <= guard_max or guard_max >= target:
        raise DecisionError("entry_guard must start at/above trigger, be ordered, and remain below target")
    if freshness < 1 or freshness > MAX_FRESHNESS_SECONDS:
        raise DecisionError("freshness_limit_seconds must be 1–86400")
    if plan.get("max_holding_sessions") != POLICY_SPEC["max_holding_sessions"]:
        raise DecisionError("A1 maximum holding period is two trading sessions")
    if expiry <= cutoff or expiry <= now:
        raise DecisionError("plan expiry must be after cutoff and server receipt")
    facts = {fact["name"]: fact for fact in evidence.get("price_facts", [])}
    selected = {}
    for role, name in refs.items():
        fact = facts.get(name)
        if not fact:
            raise DecisionError(f"{role} must reference a price fact from the saved server context")
        if fact.get("symbol") != symbol or fact.get("split_basis") != ("simulated_raw" if sample else "raw"):
            raise DecisionError(f"{role} has an unsupported symbol or price basis")
        if fact.get("source") not in ({"sample_fixture"} if sample else {"alpaca_iex", "alpaca_sip"}):
            raise DecisionError(f"{role} has no verified provider source")
        observed = _utc(fact["observed_at"], f"{role}.observed_at")
        formed = _utc(fact["formed_at"], f"{role}.formed_at")
        if observed > now or formed > now:
            raise DecisionError(f"{role} has a future timestamp")
        if observed > cutoff or formed > cutoff:
            raise DecisionError(f"{role} was not available at input_cutoff")
        if (cutoff - formed).total_seconds() > freshness or (now - formed).total_seconds() > freshness:
            raise DecisionError(f"{role} is stale for the declared freshness limit")
        selected[role] = _finite_positive(fact.get("value"), role)
    if not math.isclose(level, selected["trigger_fact"], rel_tol=0, abs_tol=1e-8):
        raise DecisionError("trigger_level must equal its frozen source fact")
    if not math.isclose(stop, selected["stop_fact"], rel_tol=0, abs_tol=1e-8):
        raise DecisionError("stop must equal its frozen source fact")
    if not math.isclose(target, selected["target_fact"], rel_tol=0, abs_tol=1e-8):
        raise DecisionError("target must equal its frozen source fact")
    frozen = dict(plan)
    for role, name in refs.items():
        fact = facts[name]
        provenance = {"source": fact["source"], "source_ref": name,
                      "source_path": fact["source_path"], "formed_at": fact["formed_at"],
                      "observed_at": fact["observed_at"], "unit": fact["unit"],
                      "currency": fact["currency"], "split_basis": fact["split_basis"],
                      "value": fact["value"]}
        frozen[role.removesuffix("_fact") + "_source"] = provenance
    frozen["initial_risk_per_share"] = round(level - stop, 8)
    return frozen


def row(record: DecisionRecord) -> dict:
    detail = json.loads(record.decision_json)
    return {
        "id": str(record.id), "operation_id": record.operation_id,
        "opportunity_id": record.opportunity_id, "actor": record.actor,
        "decision": record.decision, "symbol": record.symbol,
        "context_id": str(record.context_id),
        "received_at": record.received_at.replace(tzinfo=timezone.utc).isoformat(),
        "input_cutoff": record.input_cutoff.replace(tzinfo=timezone.utc).isoformat(),
        "policy_version": record.policy_version, "policy_hash": record.policy_hash,
        "evidence": json.loads(record.evidence_json), "evidence_sha256": record.evidence_sha256,
        "plan": detail["plan"], "rationale": detail["rationale"],
        "wait_condition": detail["wait_condition"], "wait_expiry": detail["wait_expiry"],
        "record_sha256": record.record_sha256,
        "status": "practice_draft_unarmed",
    }


def create(db: Session, request: dict, *, routine: bool = False, commit: bool = True, expected_day: date | None = None,
           sample: bool = False, receipt_deadline: datetime | None = None, sample_replay: bool = False,
           market_pilot: bool = False) -> tuple[DecisionRecord, bool]:
    if market_pilot and (sample or sample_replay or not routine):
        raise DecisionError("Market pilot requires its separate routine service")
    if sample_replay and not sample:
        raise DecisionError("Replay decisions require explicit sample validation")
    policy_version, policy_hash = ((MARKET_POLICY_VERSION, MARKET_POLICY_HASH) if market_pilot else
        (REPLAY_POLICY_VERSION, REPLAY_POLICY_HASH) if sample_replay else
        (SAMPLE_POLICY_VERSION, SAMPLE_POLICY_HASH) if sample else (POLICY_VERSION, POLICY_HASH))
    if not routine:
        if str(request.get("opportunity_id", "")).startswith("a3:") or request.get("actor") == "agent:a3":
            raise DecisionError("A3 ownership requires the routine choice service")
        try:
            context_id = uuid.UUID(str(request.get("context_id")))
        except ValueError:
            context_id = None
        if context_id and db.exec(select(PracticeOpportunity).where(PracticeOpportunity.context_id == context_id)).first():
            raise DecisionError("A3 contexts require the routine choice service")
    operation_id = request.get("operation_id")
    # Idempotency is evaluated before expiry/freshness checks. A retry returns
    # the saved record even if its opportunity has since expired.
    try:
        _canonical(request)
    except (TypeError, ValueError) as exc:
        raise DecisionError("decision request must contain finite JSON values") from exc
    if isinstance(operation_id, str):
        existing = db.exec(select(DecisionRecord).where(DecisionRecord.operation_id == operation_id)).first()
        if existing:
            if existing.policy_version != policy_version:
                raise DecisionError("operation_id already exists under a different policy")
            expected = _hash(_canonical({"request": request, "context_sha256": existing.evidence_sha256}))
            if existing.record_sha256 != expected:
                raise DecisionError("operation_id already exists with different content")
            return existing, False

    operation_id, opportunity_id, actor, decision, context_id, detail = _validate_request(request)
    context = db.get(DecisionContext, context_id)
    if context is None:
        raise DecisionError("context_id does not identify a saved server context")
    symbol = detail.pop("symbol")
    if context.symbol != symbol:
        raise DecisionError("saved context symbol does not match decision symbol")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if receipt_deadline is not None and now > receipt_deadline:
        raise DecisionError("Sample exercise deadline has passed; existing records remain readable")
    cutoff = context.captured_at
    evidence = json.loads(context.data_json)
    if market_pilot and (evidence.get("packet", {}).get("market_pilot") is not True
            or evidence.get("packet", {}).get("sample_data") is not False):
        raise DecisionError("Market pilot requires its frozen real-market packet")
    if sample and (context.provider != "sample_fixture" or evidence.get("packet", {}).get("sample_data") is not True):
        raise DecisionError("Sample decisions require explicitly simulated server evidence")
    if sample_replay and evidence.get("packet", {}).get("replay_exercise") is not True:
        raise DecisionError("Replay decisions require a fresh replay exercise")
    if decision == "take":
        if expected_day is not None and now.replace(tzinfo=timezone.utc).astimezone(ET).date() != expected_day:
            raise DecisionError("TAKE must be committed on its run's market session date")
        detail["plan"] = _validate_take(symbol, cutoff, evidence, detail["plan"], now, sample=sample)
    elif decision == "wait":
        expiry = _utc(detail["wait_expiry"], "wait_expiry")
        if expiry <= cutoff or expiry <= now:
            raise DecisionError("WAIT expiry must be after context cutoff and server receipt")
        if receipt_deadline is not None and expiry > receipt_deadline:
            raise DecisionError("Sample WAIT expiry must not exceed the exercise deadline")
    record_sha = _hash(_canonical({"request": request, "context_sha256": context.context_sha256}))
    item = DecisionRecord(operation_id=operation_id, opportunity_id=opportunity_id,
                          actor=actor, decision=decision, symbol=symbol, context_id=context.id,
                          received_at=now, input_cutoff=cutoff,
                          policy_version=policy_version, policy_hash=policy_hash,
                          evidence_json=context.data_json, evidence_sha256=context.context_sha256,
                          decision_json=_canonical(detail), record_sha256=record_sha)
    db.add(item)
    try:
        if commit:
            db.commit()
        else:
            db.flush()
    except IntegrityError:
        if not commit:
            # The batch owner rolls back every actor choice together.
            raise DecisionError("operation_id already exists with different content")
        db.rollback()
        existing = db.exec(select(DecisionRecord).where(DecisionRecord.operation_id == operation_id)).first()
        if existing and existing.record_sha256 == record_sha:
            return existing, False
        raise DecisionError("operation_id already exists with different content")
    db.refresh(item)
    return item, True


def get(db: Session, record_id: uuid.UUID) -> DecisionRecord | None:
    return db.get(DecisionRecord, record_id)


def recent(db: Session, limit: int = 30) -> list[DecisionRecord]:
    query = select(DecisionRecord).order_by(DecisionRecord.received_at.desc()).limit(max(1, min(limit, 100)))
    return list(db.exec(query).all())
