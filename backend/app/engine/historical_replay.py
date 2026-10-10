"""Own-actor retrospective market replay; original source times, separate paper clock."""
from datetime import datetime, timedelta, timezone
import json
import re
import secrets
from types import SimpleNamespace

from sqlmodel import select

from app.engine import access, decisions, market_practice, paper, paper_execution as px
from app.engine.chart_math import ET
from app.models import AccessPrincipal, DecisionContext, DecisionEvent, DecisionRecord, JobRun, PracticeOpportunity, PracticeRun

PREFIX = "dot-historical-replay:"
LEGACY_VERSION = "historical-paper-replay-v1"
VERSION = "historical-paper-replay-v2"
SOURCE = "historical_alpaca_replay"
UTC = timezone.utc
POLICY = {"version": VERSION, "decision_schema": decisions.HISTORICAL_POLICY_HASH,
    "reducer": px.EXEC_VERSION, "clock": "historical_epoch_seconds", "detection_delay_seconds": 2,
    "trigger": "complete_clock_aligned_15m_close", "entry": "next_full_minute_after_detection",
    "stop_first": True, "max_holding_sessions": 2, "cost_model": paper.COST,
    "stress_factor": 3, "source": SOURCE, "universe": ["MU", "NBIS"],
    "missing_minutes": "unresolved", "live_execution": False, "notifications": False}
LEGACY_POLICY = {**POLICY, "version": LEGACY_VERSION}
LEGACY_POLICY_HASH = decisions._hash(decisions._canonical(LEGACY_POLICY))
POLICY = {**POLICY, "split_coverage": "unavailable", "session_transition": "unresolved_without_frozen_split_evidence"}
POLICY_HASH = decisions._hash(decisions._canonical(POLICY))
PLAN_FIELDS = frozenset({"instrument", "direction", "trigger", "trigger_level", "trigger_fact", "stop", "stop_fact",
    "target", "target_fact", "entry_guard", "expiry", "max_holding_sessions", "freshness_limit_seconds", "cost_model"})


def eligible(run):
    return (run is not None and run.session_key.startswith(PREFIX) and run.status == "prepared"
        and (run.policy_version, run.policy_hash) == (decisions.HISTORICAL_POLICY_VERSION, decisions.HISTORICAL_POLICY_HASH))


def sessions_from(rows):
    if not isinstance(rows, list) or len(rows) != 2:
        raise decisions.DecisionError("Two verified historical sessions are required")
    sessions = []
    for row in rows:
        if (not isinstance(row, dict) or set(row) != {"day", "open", "close", "source"}
                or row["source"] != "alpaca_calendar" or any(type(row[k]) is not int for k in ("open", "close"))
                or not 0 <= row["open"] < row["close"] < 1440):
            raise decisions.DecisionError("Invalid historical calendar")
        try:
            day = datetime.strptime(row["day"], "%Y-%m-%d").date()
            if day.isoformat() != row["day"]:
                raise ValueError()
        except (TypeError, ValueError) as exc:
            raise decisions.DecisionError("Invalid historical day") from exc
        midnight = datetime.combine(day, datetime.min.time(), ET)
        sessions.append(px.Session(row["day"], int((midnight + timedelta(minutes=row["open"])).timestamp()),
            int((midnight + timedelta(minutes=row["close"])).timestamp())))
    if not 0 < sessions[1].open_at - sessions[0].close_at <= 7 * 86400:
        raise decisions.DecisionError("Historical sessions must be ordered and bounded")
    return sessions


def validate_bundle(bundle):
    if (not isinstance(bundle, dict) or set(bundle) != {"version", "captured_at", "simulated_as_of", "sessions", "packets"}
            or type(bundle["version"]) is not int or bundle["version"] != 1):
        raise decisions.DecisionError("Invalid historical handoff")
    retrieved = decisions._utc(bundle["captured_at"], "actual retrieval")
    cutoff = decisions._utc(bundle["simulated_as_of"], "historical cutoff")
    sessions = sessions_from(bundle["sessions"])
    stamp = cutoff.replace(tzinfo=UTC).timestamp()
    if (retrieved > access.now() or retrieved.year < 2020 or cutoff >= retrieved or stamp % 900
            or not sessions[0].open_at + 3600 <= stamp < sessions[0].close_at
            or sessions[-1].close_at >= retrieved.replace(tzinfo=UTC).timestamp()):
        raise decisions.DecisionError("Use an aligned past-session cutoff and already completed continuation")
    packets = bundle["packets"]
    if not isinstance(packets, dict) or set(packets) != market_practice.SYMBOLS:
        raise decisions.DecisionError("Historical handoff requires MU and NBIS")
    for symbol, packet in packets.items():
        if (not isinstance(packet, dict) or set(packet) != {"symbol", "data_source", "recent_minute_bars", "missing"}
                or packet["symbol"] != symbol or packet["data_source"] not in {"alpaca_iex", "alpaca_sip"}
                or not isinstance(packet["recent_minute_bars"], list) or not 1 <= len(packet["recent_minute_bars"]) <= 840):
            raise decisions.DecisionError("Bounded actual provider history is required")
        bars = packet["recent_minute_bars"]
        parsed = [decisions._utc(b.get("t"), "minute time") if isinstance(b, dict) else None for b in bars]
        if any(t is None for t in parsed) or parsed != sorted(set(parsed), reverse=True):
            raise decisions.DecisionError("Historical minutes must be unique and newest first")
        if any(t < cutoff-timedelta(hours=1) for t in parsed):
            raise decisions.DecisionError("Public historical window starts one hour before its cutoff")
        assigned = 0
        # Reuse the existing strict raw-bar validator, in bounded per-session chunks.
        # These validation clocks are session closes; stored actual retrieval is unchanged.
        for session, row in zip(sessions, bundle["sessions"]):
            selected = [b for b, t in zip(bars, parsed) if session.open_at <= t.replace(tzinfo=UTC).timestamp() < session.close_at]
            assigned += len(selected)
            for index in range(0, max(1, len(selected)), 60):
                other = next(s for s in market_practice.SYMBOLS if s != symbol)
                market_practice.validate_bundle({"version": 1,
                    "captured_at": datetime.fromtimestamp(session.close_at, UTC).isoformat(), "day": session.day,
                    "calendar": {"status": "open", **{k: row[k] for k in ("open", "close", "source")}},
                    "packets": {symbol: {**packet, "recent_minute_bars": selected[index:index+60]},
                        other: {"symbol": other, "data_source": "unavailable", "recent_minute_bars": [], "missing": []}}})
        if assigned != len(bars) or not any(t + timedelta(minutes=1) <= cutoff for t in parsed):
            raise decisions.DecisionError("History includes non-session minutes or lacks pre-cutoff evidence")
    decisions._canonical(bundle)
    return retrieved, cutoff, sessions


def prepare(db, bundle, *, identifier="trader-jo-history", proof=False):
    if not re.fullmatch(r"[a-z][a-z0-9_-]{2,63}", identifier) or identifier == "owner" or type(proof) is not bool:
        raise decisions.DecisionError("Choose a new historical assistant ID")
    retrieved, cutoff, sessions = validate_bundle(bundle)
    digest = decisions._hash(decisions._canonical(bundle))
    key = PREFIX + VERSION + ":" + ("proof:" if proof else "") + cutoff.strftime("%Y%m%dT%H%M") + ":" + identifier
    previous = db.exec(select(PracticeRun).where(PracticeRun.session_key == key)).first()
    if previous:
        if (eligible(previous) and market_practice.metadata(previous).get("handoff_sha256") == digest
                and market_practice.visible_to(previous, identifier)):
            return previous
        raise decisions.DecisionError("Historical session is frozen; cannot replace its evidence")
    if db.get(AccessPrincipal, identifier):
        raise decisions.DecisionError("Existing identity cannot be repointed")
    now = access.now()
    job = JobRun(job_type="historical_replay_import", status="running", total=2, done=0)
    db.add(job)
    db.flush()
    run = PracticeRun(session_key=key, day=cutoff.replace(tzinfo=UTC).astimezone(ET).date(), job_id=job.id,
        mode="manual", comparison="assisted", status="preparing", result="historical_paper_replay", late=True,
        deadline=now + timedelta(hours=20), policy_version=decisions.HISTORICAL_POLICY_VERSION,
        policy_hash=decisions.HISTORICAL_POLICY_HASH, calendar_json=decisions._canonical(bundle["sessions"]),
        brief_json=decisions._canonical([{"title": "Historical market replay", "text": "Retrospective practice",
            "sources": [], "assigned_agent": "agent:" + identifier, "handoff_sha256": digest, "operational_proof": proof}]))
    db.add(run)
    db.flush()
    try:
        for symbol in sorted(market_practice.SYMBOLS):
            original = bundle["packets"][symbol]
            before, later = [], []
            for bar in original["recent_minute_bars"]:
                at = decisions._utc(bar["t"], "minute time")
                (before if at + timedelta(minutes=1) <= cutoff else later).append(bar)
            before = before[:60]
            sealed = {"version": VERSION, "nonce": secrets.token_hex(32), "symbol": symbol,
                "source": original["data_source"], "simulated_as_of": bundle["simulated_as_of"],
                "sessions": bundle["sessions"], "minutes": list(reversed(later))}
            packet = {**original, "recent_minute_bars": before, "sample_data": False, "market_pilot": False,
                "historical_replay": True, "simulated_as_of": bundle["simulated_as_of"], "retrieved_at": bundle["captured_at"],
                "window_start": (cutoff-timedelta(hours=1)).replace(tzinfo=UTC).isoformat(),
                "window_end": cutoff.replace(tzinfo=UTC).isoformat(),
                "generated_at": bundle["captured_at"], "historical_sessions": bundle["sessions"],
                "session_calendar": {"status": "open", **{k: bundle["sessions"][0][k] for k in ("open", "close", "source")}},
                "plan_expiry_max": datetime.fromtimestamp(sessions[-1].close_at, UTC).isoformat(),
                "replay_commitment": decisions._hash(decisions._canonical(sealed)), "replay_rules": {**POLICY, "hash": POLICY_HASH},
                "rules": {**decisions.HISTORICAL_POLICY_SPEC, "policy_hash": decisions.HISTORICAL_POLICY_HASH},
                "notice": "Real retrospective provider bars; historical clock and simulated execution. No live watcher.",
                "vwap_basis": "Provider-supplied minute VWAP; IEX is not consolidated market coverage."}
            ctx, _ = decisions.freeze_context(db, f"history:{run.id}:{symbol}", symbol, packet,
                captured_at=retrieved.replace(tzinfo=UTC), commit=False)
            db.add(PracticeOpportunity(run_id=run.id, symbol=symbol, context_id=ctx.id,
                benchmark_json=decisions._canonical(sealed)))
        run.status, run.finished_at = "prepared", access.now()
        job.status, job.done, job.finished_at = "succeeded", 2, run.finished_at
        db.add(run)
        db.add(job)
        db.commit()
    except BaseException:
        db.rollback()
        raise
    return run


def checked_context(context):
    if not context or decisions._hash(context.data_json) != context.context_sha256:
        raise decisions.DecisionError("Historical evidence integrity check failed")
    evidence = json.loads(context.data_json)
    packet = evidence["packet"]
    if (packet.get("historical_replay") is not True or packet.get("sample_data") is not False
            or packet.get("market_pilot") is not False or context.symbol != evidence["symbol"]
            or packet["symbol"] != context.symbol or context.provider != evidence["provider"]
            or context.provider != packet["data_source"] or context.provider not in {"alpaca_iex", "alpaca_sip"}
            or decisions._utc(packet["retrieved_at"], "retrieval") != context.captured_at):
        raise decisions.DecisionError("Historical evidence identity check failed")
    return evidence


def take_unavailable(context, run):
    evidence = checked_context(context)
    if evidence["packet"].get("replay_rules") != {**POLICY, "hash": POLICY_HASH}:
        return "This historical exercise uses older replay rules; its saved receipts remain readable"
    cutoff = decisions._utc(evidence["packet"]["simulated_as_of"], "historical cutoff")
    if access.now() > run.deadline:
        return "Exercise deadline expired; saved records remain readable"
    return market_practice.take_unavailable(context,
        SimpleNamespace(day=run.day, deadline=decisions._utc(evidence["packet"]["plan_expiry_max"], "session end")), now=cutoff)


def view(db, run, identifier, symbols, *, details=True, include_replay=True):
    if not eligible(run) or not market_practice.visible_to(run, identifier):
        raise decisions.DecisionError("Historical session is outside this frozen assignment")
    assigned = market_practice.metadata(run)["assigned_agent"]
    result = {"id": str(run.id), "day": run.day.isoformat(), "sample_data": False, "market_data": True,
        "historical_replay": True, "assigned_agent": assigned,
        "operational_proof": market_practice.metadata(run).get("operational_proof", False),
        "policy_version": run.policy_version, "policy_hash": run.policy_hash,
        "deadline": run.deadline.replace(tzinfo=UTC).isoformat(), "replay_exercise": False, "opportunities": []}
    if details:
        for opp in db.exec(select(PracticeOpportunity).where(PracticeOpportunity.run_id == run.id)).all():
            if opp.symbol not in symbols:
                continue
            ctx = db.get(DecisionContext, opp.context_id)
            evidence = checked_context(ctx)
            choice = db.exec(select(DecisionRecord).where(DecisionRecord.opportunity_id == f"a3:{opp.id}",
                DecisionRecord.actor == assigned)).first()
            result["opportunities"].append({"id": str(opp.id), "symbol": opp.symbol,
                "context": decisions.context_row(ctx, evidence), "choice": decisions.row(choice) if choice else None,
                "take_unavailable": take_unavailable(ctx, run), "replay": replay_view(db, choice) if choice and include_replay else None})
    return result


def choose(db, run, opp, identifier, body):
    if not eligible(run) or not market_practice.visible_to(run, identifier) or opp.run_id != run.id:
        raise decisions.DecisionError("Historical session is outside this frozen assignment")
    if not str(body.get("rationale", "")).strip():
        raise decisions.DecisionError("Explain the historical practice choice")
    context = db.get(DecisionContext, opp.context_id)
    checked_context(context)
    payload = {"operation_id": f"history:{opp.id}:{identifier}", "opportunity_id": f"a3:{opp.id}",
        "actor": "agent:" + identifier, "symbol": opp.symbol, "context_id": str(opp.context_id),
        **{key: body.get(key) for key in ("decision", "rationale", "wait_condition", "wait_expiry", "plan")}}
    existing = db.exec(select(DecisionRecord).where(DecisionRecord.operation_id == payload["operation_id"])).first()
    if not existing and body.get("decision") == "take":
        issue = take_unavailable(context, run)
        if issue:
            raise decisions.DecisionError(issue)
        plan = body.get("plan") or {}
        packet = json.loads(context.data_json)["packet"]
        if (set(plan) != PLAN_FIELDS or plan.get("cost_model") != paper.COST or plan.get("freshness_limit_seconds") != 7200
                or decisions._utc(plan.get("expiry"), "historical expiry") > decisions._utc(packet["plan_expiry_max"], "session end")):
            raise decisions.DecisionError("Retain source-linked fields, declared costs/freshness and historical session expiry")
    return decisions.create(db, payload, routine=True, historical_replay=True, receipt_deadline=run.deadline)


def _authorize(db, request, opp_id):
    from fastapi import HTTPException
    who = request.state.access
    _, principal = access._session(db, request.cookies.get(access.cookie_name()), who.audience, touch=False)
    if (principal.id != who.identifier or json.loads(principal.grants_json) != who.grants
            or not access.historical_writer(request)):
        raise HTTPException(403, "Historical writer is no longer authorized")
    opp = db.get(PracticeOpportunity, opp_id)
    if not opp or str(opp.run_id) not in who.grants["run_ids"] or opp.symbol not in who.grants["symbols"]:
        raise HTTPException(404, "Historical opportunity not found")
    run = db.get(PracticeRun, opp.run_id)
    if not eligible(run) or not market_practice.visible_to(run, who.identifier):
        raise HTTPException(404, "Historical opportunity not found")
    return who, opp, run


def submit(db, request, opp_id, body):
    with access._LOCK:
        access._serialized(db)
        db.expire_all()
        who, opp, run = _authorize(db, request, opp_id)
        _, created = choose(db, run, opp, who.identifier, body)
        return run, created


def replay_view(db, record):
    rows = db.exec(select(DecisionEvent).where(DecisionEvent.record_id == record.id).order_by(DecisionEvent.seq)).all()
    if not rows:
        return None
    if any(row.source != SOURCE or not row.event_type.startswith("historical_replay_") for row in rows):
        raise decisions.DecisionError("Historical replay ledger is incompatible")
    data = [json.loads(row.data_json) for row in rows]
    first, result = data[0], data[-1]
    evidence = json.loads(record.evidence_json)
    if (result.get("type") != "replay_result" or first.get("record_sha256") != record.record_sha256
            or first.get("evidence_sha256") != record.evidence_sha256
            or decisions._hash(record.evidence_json) != record.evidence_sha256
            or (first.get("policy_version"), first.get("policy_hash")) not in {
                (VERSION, POLICY_HASH), (LEGACY_VERSION, LEGACY_POLICY_HASH)}
            or decisions._hash(decisions._canonical(result["continuation"])) != first.get("tape_sha256")
            or first["tape_sha256"] != evidence["packet"].get("replay_commitment")):
        raise decisions.DecisionError("Historical replay receipt integrity check failed")
    return {"record_id": str(record.id), "simulated": True, "historical_replay": True, "status": result["status"],
        "policy_version": first["policy_version"], "policy_hash": first["policy_hash"], "clock": POLICY["clock"],
        "tape_sha256": first["tape_sha256"], "receipt_sha256": decisions._hash(decisions._canonical([r.data_json for r in rows])),
        "events": [{**e, "seq": r.seq, "source": r.source, "recorded_at": r.recorded_at.replace(tzinfo=UTC).isoformat()}
            for r, e in zip(rows, data) if e["type"] != "replay_result"],
        "outcome": result["outcome"], "outcome_x3": result["outcome_x3"],
        "continuation": result["continuation"], "commitment_verified": True}


def simulate(plan, sealed):
    """Pure bounded replay. No clock, network, database, outbox or gap filling."""
    terms = px.terms_from_plan(plan)
    sessions = sessions_from(sealed["sessions"])
    # Raw prices can change share basis between sessions. This capture has no
    # frozen corporate-action coverage: never evaluate that transition or
    # silently interpret a split as a gap stop. Preserve all original bars
    # in the sealed receipt, but judge only the first session's stable window.
    sessions = sessions[:1]
    cutoff = decisions._utc(sealed["simulated_as_of"], "historical cutoff").replace(tzinfo=UTC).timestamp()
    bars = [{"start": int(decisions._utc(b["t"], "minute time").replace(tzinfo=UTC).timestamp()),
        **{key: b[key] for key in ("o", "h", "l", "c")}} for b in sealed["minutes"]]
    bars = px._regular(bars, sessions)
    if any(b["start"] < cutoff for b in bars):
        raise decisions.DecisionError("Continuation precedes the historical cutoff")
    events = [px.arm_event(cutoff)]
    groups = {}
    for bar in bars:
        groups.setdefault(bar["start"] // 900 * 900, []).append(bar)
    for at, group in sorted(groups.items()):
        if at + 900 > terms.expiry:
            break
        known = {b["start"] for b in bars}
        missing = next((minute for session in sessions for minute in range(max(session.open_at, int(cutoff)),
            min(session.close_at, at+900), 60) if minute not in known), None)
        if missing is not None:
            events.append({"type": "unresolved", "key": "unresolved", "at": missing,
                "stage": "trigger", "reason": "missing historical confirmation minutes"})
            break
        if len(group) != 15 or [b["start"] for b in group] != list(range(at, at+900, 60)):
            continue
        detected = at + 902
        events.extend(px.watch(px.fold(events), terms, [{"start": at, "end": at+900, "close": group[-1]["c"]}], detected))
        if px.fold(events).status == "triggered":
            events.append({"type": "order_intent", "key": "order_intent", "at": detected,
                "eligible_bar_start": (int(detected) // 60 + 1) * 60, "clock": POLICY["clock"]})
            events.extend(px.advance(px.fold(events), terms, bars, sessions, durable_at=detected))
            break
    state = px.fold(events)
    if state.status == "armed":
        # A gap that could conceal an eligible trigger cannot be called an expiry.
        end = min(terms.expiry, sessions[-1].close_at)
        known = {b["start"] for b in bars}
        expected = [at for session in sessions for at in range(max(session.open_at, int(cutoff)),
            min(session.close_at, int(end)), 60)]
        missing = next((at for at in expected if at not in known), None)
        if missing is not None:
            events.append({"type": "unresolved", "key": "unresolved", "at": missing,
                "stage": "trigger", "reason": "missing historical confirmation minutes"})
        elif terms.expiry <= sessions[0].close_at:
            events.extend(px.check_expiry(state, terms, end + px.MAX_DETECTION_DELAY + 1))
        else:
            events.append({"type": "unresolved", "key": "unresolved", "at": sessions[0].close_at,
                "stage": "trigger", "reason": "split coverage unavailable across session boundary"})
    elif state.status in {"open", "triggered"}:
        events.extend(px.end_unresolved(state, sessions[-1].close_at,
            "split coverage unavailable across session boundary"))
    state = px.fold(events)
    return events, state, px.outcome(state, terms), px.outcome(state, terms, 3)


def start(db, request, opp_id):
    with access._LOCK:
        access._serialized(db)
        db.expire_all()
        who, opp, run = _authorize(db, request, opp_id)
        record = db.exec(select(DecisionRecord).where(DecisionRecord.opportunity_id == f"a3:{opp.id}",
            DecisionRecord.actor == "agent:" + who.identifier)).first()
        if not record or record.decision != "take" or (record.policy_version, record.policy_hash) != (
                decisions.HISTORICAL_POLICY_VERSION, decisions.HISTORICAL_POLICY_HASH):
            raise decisions.DecisionError("Only your saved historical TAKE can start a replay")
        ctx = db.get(DecisionContext, record.context_id)
        evidence = checked_context(ctx)
        if ctx.id != opp.context_id or record.evidence_json != ctx.data_json or record.evidence_sha256 != ctx.context_sha256:
            raise decisions.DecisionError("Saved historical decision does not match its evidence")
        detail = json.loads(record.decision_json)
        plan = detail["plan"]
        request_body = {"operation_id": record.operation_id, "opportunity_id": record.opportunity_id,
            "actor": record.actor, "symbol": record.symbol, "context_id": str(record.context_id), "decision": record.decision,
            "plan": {key: plan[key] for key in PLAN_FIELDS},
            **{key: detail[key] for key in ("rationale", "wait_condition", "wait_expiry")}}
        if decisions._hash(decisions._canonical({"request": request_body, "context_sha256": ctx.context_sha256})) != record.record_sha256:
            raise decisions.DecisionError("Historical decision hash mismatch")
        packet = evidence["packet"]
        cutoff = decisions._utc(packet["simulated_as_of"], "historical cutoff")
        if decisions._validate_take(record.symbol, cutoff, evidence, request_body["plan"], cutoff, historical=True) != plan:
            raise decisions.DecisionError("Historical plan provenance mismatch")
        previous = replay_view(db, record)
        if previous:
            db.commit()
            return run, False
        if access.now() > run.deadline:
            raise decisions.DecisionError("Historical replay start deadline has passed")
        sealed = json.loads(opp.benchmark_json)
        tape_hash = decisions._hash(decisions._canonical(sealed))
        if (packet.get("replay_rules") != {**POLICY, "hash": POLICY_HASH} or packet.get("replay_commitment") != tape_hash
                or sealed.get("version") != VERSION or sealed.get("symbol") != record.symbol
                or sealed.get("source") != ctx.provider or sealed.get("simulated_as_of") != packet["simulated_as_of"]
                or sealed.get("sessions") != packet["historical_sessions"]):
            raise decisions.DecisionError("Historical continuation commitment mismatch")
        events, state, outcome, stressed = simulate(plan, sealed)
        events[0].update(policy_version=VERSION, policy_hash=POLICY_HASH, record_sha256=record.record_sha256,
            evidence_sha256=record.evidence_sha256, tape_sha256=tape_hash)
        events.append({"type": "replay_result", "key": "result", "at": events[-1]["at"],
            "status": state.status, "outcome": outcome, "outcome_x3": stressed, "continuation": sealed})
        recorded = access.now()
        for seq, event in enumerate(events, 1):
            db.add(DecisionEvent(record_id=record.id, seq=seq, key="historical-replay:" + event["key"],
                event_type="historical_replay_" + event["type"], effective_at=datetime.fromtimestamp(event["at"], UTC).replace(tzinfo=None),
                recorded_at=recorded, exec_version=VERSION, source=SOURCE, delivery="none", data_json=decisions._canonical(event)))
        db.commit()
        return run, True
