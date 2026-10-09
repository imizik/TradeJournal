"""One operator-imported real-market session; own decisions, no execution."""
from datetime import datetime, timedelta, timezone
import json
import math
import re

from sqlmodel import select

from app.engine import decisions, paper
from app.engine.chart_math import ET
from app.models import AccessPrincipal, DecisionContext, DecisionRecord, JobRun, PracticeOpportunity, PracticeRun

PREFIX = "dot-market-decision:"
SYMBOLS = frozenset({"MU", "NBIS"})
UTC = timezone.utc


def eligible(run):
    return (run.session_key.startswith(PREFIX) and run.status == "prepared"
        and (run.policy_version, run.policy_hash) == (decisions.MARKET_POLICY_VERSION, decisions.MARKET_POLICY_HASH))


def recognized(run):
    return run.session_key.startswith(PREFIX) or run.policy_version == decisions.MARKET_POLICY_VERSION


def visible_to(run, identifier):
    if identifier is None:
        return True  # only the private owner/service projection passes None
    try:
        return metadata(run).get("assigned_agent") == "agent:" + identifier
    except (ValueError, KeyError, IndexError, TypeError):
        return False


def validate_bundle(bundle):
    """Whitelist a credential-free market handoff; never import arbitrary packet fields."""
    if (not isinstance(bundle, dict) or set(bundle) != {"version", "captured_at", "day", "calendar", "packets"}
            or bundle["version"] != 1):
        raise decisions.DecisionError("Invalid market handoff")
    captured = decisions._utc(bundle["captured_at"], "capture time")
    if captured > datetime.now(UTC).replace(tzinfo=None) or captured.year < 2020:
        raise decisions.DecisionError("Invalid market capture time")
    day = captured.replace(tzinfo=UTC).astimezone(ET).date()
    if bundle["day"] != day.isoformat():
        raise decisions.DecisionError("Handoff date must match the actual capture date")
    hours = bundle["calendar"]
    if not isinstance(hours, dict) or set(hours) != {"status", "open", "close", "source"}:
        raise decisions.DecisionError("Invalid market calendar")
    if hours["status"] not in {"open", "closed", "unavailable"} or hours["source"] != "alpaca_calendar":
        raise decisions.DecisionError("Unsupported market calendar")
    if hours["status"] == "open":
        if any(type(hours[k]) is not int for k in ("open", "close")) or not 0 <= hours["open"] < hours["close"] <= 1440:
            raise decisions.DecisionError("Invalid regular-session hours")
    elif hours["open"] is not None or hours["close"] is not None:
        raise decisions.DecisionError("Unavailable sessions cannot supply hours")
    packets = bundle["packets"]
    if not isinstance(packets, dict) or set(packets) != SYMBOLS:
        raise decisions.DecisionError("Handoff requires exactly MU and NBIS")
    for symbol, packet in packets.items():
        if (not isinstance(packet, dict) or set(packet) != {"symbol", "data_source", "recent_minute_bars", "missing"}
                or packet["symbol"] != symbol or packet["data_source"] not in {"alpaca_iex", "alpaca_sip", "unavailable"}):
            raise decisions.DecisionError("Invalid market packet")
        if (not isinstance(packet["missing"], list) or len(packet["missing"]) > 5
                or any(not isinstance(s, str) or len(s) > 200 for s in packet["missing"])):
            raise decisions.DecisionError("Invalid source coverage")
        bars = packet["recent_minute_bars"]
        if not isinstance(bars, list) or len(bars) > 60:
            raise decisions.DecisionError("At most sixty completed minutes per symbol")
        if bars and (hours["status"] != "open" or packet["data_source"] == "unavailable"):
            raise decisions.DecisionError("Unverified sessions/sources cannot supply market bars")
        seen = set()
        for bar in bars:
            if not isinstance(bar, dict) or set(bar) != {"t", "o", "h", "l", "c", "v", "vw"}:
                raise decisions.DecisionError("Unsupported minute fields")
            at = decisions._utc(bar["t"], "minute timestamp")
            local = at.replace(tzinfo=UTC).astimezone(ET)
            if (at.second or at.microsecond or at in seen or at + timedelta(minutes=1) > captured
                    or local.date() != day or not hours["open"] <= local.hour * 60 + local.minute < hours["close"]):
                raise decisions.DecisionError("Duplicate, unfinished or non-session minute")
            seen.add(at)
            if any(type(bar[k]) not in {int, float} or not math.isfinite(bar[k]) or bar[k] <= 0 for k in ("o", "h", "l", "c")):
                raise decisions.DecisionError("Invalid market prices")
            if not bar["l"] <= min(bar["o"], bar["c"]) <= max(bar["o"], bar["c"]) <= bar["h"]:
                raise decisions.DecisionError("Invalid minute OHLC")
            if type(bar["v"]) not in {int, float} or not math.isfinite(bar["v"]) or bar["v"] < 0:
                raise decisions.DecisionError("Invalid share volume")
            if bar["vw"] is not None and (type(bar["vw"]) not in {int, float} or not math.isfinite(bar["vw"]) or bar["vw"] <= 0):
                raise decisions.DecisionError("Invalid supplied VWAP")
        if bars != sorted(bars, key=lambda b: decisions._utc(b["t"], "minute timestamp"), reverse=True):
            raise decisions.DecisionError("Minutes must be newest first")
    decisions._canonical(bundle)
    return captured, day


def metadata(run):
    return json.loads(run.brief_json)[0]


def prepare(db, bundle, *, identifier="trader-jo-market", proof=False):
    if not re.fullmatch(r"[a-z][a-z0-9_-]{2,63}", identifier) or identifier == "owner" or type(proof) is not bool:
        raise decisions.DecisionError("Choose a separate market identity")
    captured, day = validate_bundle(bundle)
    digest = decisions._hash(decisions._canonical(bundle))
    key = PREFIX + ("proof:" if proof else "") + day.isoformat() + (":" + identifier if proof else "")
    previous = db.exec(select(PracticeRun).where(PracticeRun.session_key == key)).first()
    if previous:
        if (eligible(previous) and metadata(previous).get("handoff_sha256") == digest
                and metadata(previous).get("assigned_agent") == "agent:" + identifier):
            return previous
        raise decisions.DecisionError("This session is already frozen; cannot replace its evidence")
    if db.get(AccessPrincipal, identifier):
        raise decisions.DecisionError("Existing identity cannot be repointed to another session; choose a fresh identifier")
    deadline = captured + timedelta(seconds=3600)
    job = JobRun(job_type="market_decision_import", status="running", total=2, done=0)
    db.add(job)
    db.flush()
    run = PracticeRun(session_key=key, day=day, job_id=job.id, mode="manual", comparison="assisted",
        status="preparing", result="market_decision_only", deadline=deadline,
        policy_version=decisions.MARKET_POLICY_VERSION, policy_hash=decisions.MARKET_POLICY_HASH,
        calendar_json=json.dumps(bundle["calendar"]), late=True,
        brief_json=json.dumps([{"title": "Real frozen market evidence", "text": "Decision-only manual pilot",
            "sources": [], "handoff_sha256": digest, "assigned_agent": "agent:" + identifier, "operational_proof": proof}]))
    db.add(run)
    db.flush()
    # Both contexts/opportunities and the run commit atomically.
    try:
        for symbol in sorted(SYMBOLS):
            packet = {**bundle["packets"][symbol], "market_pilot": True, "sample_data": False,
                "generated_at": bundle["captured_at"], "session_calendar": bundle["calendar"],
                "rules": {**decisions.MARKET_POLICY_SPEC, "policy_hash": decisions.MARKET_POLICY_HASH},
                "notice": "Real frozen market evidence; decisions only. No monitoring or execution.",
                "vwap_basis": "Provider-supplied minute VWAP. " + ("IEX coverage is not consolidated market coverage."
                    if bundle["packets"][symbol]["data_source"] == "alpaca_iex" else "Coverage follows the named provider and supplied bars.")}
            ctx, _ = decisions.freeze_context(db, f"market:{run.id}:{symbol}", symbol, packet,
                captured_at=captured.replace(tzinfo=UTC), commit=False)
            db.add(PracticeOpportunity(run_id=run.id, symbol=symbol, context_id=ctx.id))
        run.status, run.finished_at = "prepared", datetime.now(UTC).replace(tzinfo=None)
        job.status, job.done, job.finished_at = "succeeded", 2, run.finished_at
        db.add(job)
        db.add(run)
        db.commit()
    except BaseException:
        db.rollback()
        raise
    return run


def take_unavailable(context, run, now=None):
    now = now or datetime.now(UTC).replace(tzinfo=None)
    evidence = json.loads(context.data_json)
    packet = evidence["packet"]
    hours = packet["session_calendar"]
    local = now.replace(tzinfo=UTC).astimezone(ET)
    if (hours["status"] != "open" or local.date() != run.day
            or not hours["open"] <= local.hour * 60 + local.minute < hours["close"]):
        return "TAKE unavailable outside the verified regular session"
    bars = packet["recent_minute_bars"]
    if context.provider not in {"alpaca_iex", "alpaca_sip"} or not bars:
        return "TAKE unavailable: provider minutes missing"
    latest = max(decisions._utc(b["t"], "minute timestamp") + timedelta(minutes=1) for b in bars)
    if (now - latest).total_seconds() > 300:
        return "TAKE unavailable: latest frozen minute is older than five minutes"
    if now > run.deadline:
        return "Decision window expired; saved records remain readable"
    return None


def checked_context(context):
    if not context or decisions._hash(context.data_json) != context.context_sha256:
        raise decisions.DecisionError("Frozen market evidence integrity check failed")
    evidence = json.loads(context.data_json)
    packet = evidence["packet"]
    if (packet.get("market_pilot") is not True or packet.get("sample_data") is not False
            or evidence["symbol"] != context.symbol or packet["symbol"] != context.symbol
            or evidence["provider"] != context.provider or packet["data_source"] != context.provider):
        raise decisions.DecisionError("Frozen market evidence identity check failed")
    return evidence


def view(db, run, identifier, symbols, *, details=True):
    if not eligible(run) or not visible_to(run, identifier):
        raise decisions.DecisionError("Market session not found")
    result = {"id": str(run.id), "day": run.day.isoformat(), "sample_data": False, "market_data": True,
        "policy_version": run.policy_version, "policy_hash": run.policy_hash,
        "deadline": run.deadline.replace(tzinfo=UTC).isoformat(), "replay_exercise": False,
        "assigned_agent": metadata(run)["assigned_agent"],
        "operational_proof": metadata(run)["operational_proof"], "opportunities": []}
    if not details:
        return result
    for opp in db.exec(select(PracticeOpportunity).where(PracticeOpportunity.run_id == run.id)).all():
        if opp.symbol not in symbols or opp.context_id is None:
            continue
        ctx = db.get(DecisionContext, opp.context_id)
        evidence = checked_context(ctx)
        query = select(DecisionRecord).where(DecisionRecord.opportunity_id == f"a3:{opp.id}",
            DecisionRecord.actor == metadata(run)["assigned_agent"], DecisionRecord.policy_version == decisions.MARKET_POLICY_VERSION)
        if identifier is not None:
            query = query.where(DecisionRecord.actor == "agent:" + identifier)
        choice = db.exec(query.order_by(DecisionRecord.received_at)).first()
        result["opportunities"].append({"id": str(opp.id), "symbol": opp.symbol,
            "context": decisions.context_row(ctx, evidence),
            "choice": decisions.row(choice) if choice else None, "take_unavailable": take_unavailable(ctx, run), "replay": None})
    return result


def choose(db, run, opp, identifier, body):
    if not eligible(run):
        raise decisions.DecisionError("Market session not found")
    if metadata(run).get("assigned_agent") != "agent:" + identifier:
        raise decisions.DecisionError("This market session is assigned to a different agent")
    if opp.run_id != run.id or opp.symbol not in SYMBOLS:
        raise decisions.DecisionError("Opportunity is outside this market session")
    ctx = db.get(DecisionContext, opp.context_id)
    checked_context(ctx)
    if not str(body.get("rationale", "")).strip():
        raise decisions.DecisionError("Explain the decision before saving")
    payload = {"operation_id": f"market:{opp.id}:{identifier}", "opportunity_id": f"a3:{opp.id}",
        "actor": "agent:" + identifier, "symbol": opp.symbol, "context_id": str(opp.context_id),
        **{k: body.get(k) for k in ("decision", "rationale", "wait_condition", "wait_expiry", "plan")}}
    # Exact immutable retries remain available after the decision window closes.
    existing = db.exec(select(DecisionRecord).where(DecisionRecord.operation_id == payload["operation_id"])).first()
    if not existing and body.get("decision") == "take":
        issue = take_unavailable(ctx, run)
        if issue:
            raise decisions.DecisionError(issue)
        plan = body.get("plan") or {}
        if set(plan) != {"instrument", "direction", "trigger", "trigger_level", "trigger_fact", "stop", "stop_fact",
                "target", "target_fact", "entry_guard", "expiry", "max_holding_sessions", "freshness_limit_seconds", "cost_model"}:
            raise decisions.DecisionError("TAKE requires only the declared source-linked plan fields")
        if (plan.get("cost_model") != paper.COST or plan.get("freshness_limit_seconds") != 7200
                or decisions._utc(plan.get("expiry"), "plan expiry") > run.deadline):
            raise decisions.DecisionError("Retain declared costs, two-hour fact freshness and the session deadline")
    return decisions.create(db, payload, routine=True, market_pilot=True, receipt_deadline=run.deadline,
        expected_day=run.day)


def submit(db, request, opp_id, body):
    """Serialize choices/retries with key resets, grant changes and revocation."""
    from fastapi import HTTPException
    from app.engine import access
    with access._LOCK:
        access._serialized(db)
        who = request.state.access
        _, principal = access._session(db, request.cookies.get(access.cookie_name()), who.audience, touch=False)
        if principal.id != who.identifier or json.loads(principal.grants_json) != who.grants or not access.market_writer(request):
            raise HTTPException(403, "Market writer is no longer authorized")
        opp = db.get(PracticeOpportunity, opp_id)
        if not opp or str(opp.run_id) not in who.grants["run_ids"] or opp.symbol not in who.grants["symbols"]:
            raise HTTPException(404, "Opportunity not found")
        run = db.get(PracticeRun, opp.run_id)
        _, created = choose(db, run, opp, who.identifier, body)
        return run, created
