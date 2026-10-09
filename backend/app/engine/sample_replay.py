"""One atomic, sealed, sample-only paper replay; never a live watcher or outbox."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
import secrets

from sqlmodel import select

from app.engine import access, decisions, paper_execution as px, sample_practice
from app.engine.chart_math import ET
from app.models import (
    AccessPrincipal,
    AccessSession,
    DecisionContext,
    DecisionEvent,
    DecisionRecord,
    JobRun,
    PracticeOpportunity,
    PracticeRun,
)

VERSION = "sample-paper-replay-v1"
SOURCE = "sample_replay_fixture"
PREFIX = sample_practice.PREFIX + "paper-replay-v1:"
SCENARIO_VERSION = "sample-scenarios-v2"
POLICY = {
    "version": VERSION,
    "decision_schema": decisions.REPLAY_POLICY_HASH,
    "reducer": px.EXEC_VERSION,
    "clock": "seconds_from_simulated_session_open",
    "session_seconds": 23400,
    "armed_second": 900,
    "expiry_second": 3600,
    "detected_delay_seconds": 2,
    "entry": "next_full_minute_after_detection",
    "stop_first": True,
    "max_holding_sessions": 2,
    "cost_version": "sample-cost-v1",
    "slippage_bps": 1,
    "slippage_per_share": 0.01,
    "stress_factor": 3,
    "source": SOURCE,
    "universe": ["MU", "NBIS"],
    "replays_per_actor_opportunity": 1,
    "live_execution": False,
    "notifications": False,
}
POLICY_HASH = decisions._hash(decisions._canonical(POLICY))


def eligible(run):
    return (
        run.session_key.startswith(PREFIX)
        and run.status == "prepared"
        and (run.policy_version, run.policy_hash)
        == (decisions.REPLAY_POLICY_VERSION, decisions.REPLAY_POLICY_HASH)
    )


def seal(base):
    """Operator-only continuation; the nonce prevents guessing its two outcomes from its hash."""
    ending = secrets.choice(("stop", "target"))
    bars = [
        {
            "start": minute * 60,
            "o": base + 0.2,
            "h": base + 0.35,
            "l": base + 0.1,
            "c": base + 0.25,
        }
        for minute in range(15, 31)
    ]
    bars.extend(
        [
            {
                "start": 1860,
                "o": base + 0.2,
                "h": base + 0.4,
                "l": base + 0.1,
                "c": base + 0.3,
            },
            {
                "start": 1920,
                "o": base + 0.3,
                "h": base + 0.5,
                "l": base + 0.2,
                "c": base + 0.4,
            },
            {
                "start": 1980,
                "o": base + 0.4,
                "h": base + 4.1 if ending == "target" else base + 0.5,
                "l": base + 0.3 if ending == "target" else base - 2.1,
                "c": base + 3.9 if ending == "target" else base - 1.9,
            },
        ]
    )
    payload = {"version": VERSION, "nonce": secrets.token_hex(32), "minutes": bars}
    return payload, decisions._hash(decisions._canonical(payload))


def _interpolate(points, minute):
    for (left, begin), (right, end) in zip(points, points[1:]):
        if left <= minute <= right:
            return begin + (end - begin) * (minute - left) / (right - left)
    raise ValueError("Minute outside sample scenario")


def scenario_packet(symbol, base, now, run):
    """Invented completed history; no continuation or recommended choice is published."""
    packet = sample_practice.packet(symbol, base, now, run)
    if symbol == "MU":
        closes = [
            (0, base + 2.8),
            (5, base + 0.6),
            (19, base - 0.9),
            (29, base - 0.7),
            (44, base - 0.4),
            (59, base),
        ]
        volumes = [(0, 300), (5, 500), (19, 1600), (29, 400), (44, 1200), (59, 2600)]
        stop_minute, stop, target, guard_max = 19, base - 1, base + 3, base + 0.2
        description = "Invented 60-minute history: a pullback followed by recovery toward the fixed trigger. Evaluate the completed bars and volume yourself; TAKE still requires confirmation in the hidden replay."
    elif symbol == "NBIS":
        closes = [
            (0, base + 3.5),
            (14, base - 1.6),
            (29, base + 0.1),
            (44, base - 0.2),
            (59, base),
        ]
        volumes = [(0, 2200), (59, 850)]
        stop_minute, stop, target, guard_max = 14, base - 2, base + 4, base + 0.5
        description = "Invented 60-minute history: a rebound followed by alternating closes around the fixed trigger. Evaluate the completed bars and volume yourself; TAKE still requires confirmation in the hidden replay."
    else:
        raise ValueError("Scenario symbol outside MU/NBIS")
    end = now.replace(second=0, microsecond=0) - timedelta(minutes=1)
    bars = []
    total_volume, weighted_price = 0, 0.0
    previous = closes[0][1] + 0.1
    for minute in range(60):
        wiggle = (
            0.015 * (minute % 4 - 1.5)
            if symbol == "MU"
            else 0.15 * ((minute % 6) - 2.5)
        )
        close = round(_interpolate(closes, minute) + wiggle, 4)
        if minute in (0, stop_minute, 59):
            close = _interpolate(closes, minute)
        opening = round(previous, 4)
        high = round(max(opening, close) + 0.06 + 0.01 * (minute % 3), 4)
        low = round(min(opening, close) - 0.05 - 0.01 * (minute % 2), 4)
        if minute == 0:
            high = target
        if minute == stop_minute:
            low = stop
        volume = round(_interpolate(volumes, minute))
        total_volume += volume
        weighted_price += ((opening + high + low + close) / 4) * volume
        bars.append(
            {
                "t": (end - timedelta(minutes=59 - minute)).isoformat(),
                "o": opening,
                "h": high,
                "l": low,
                "c": close,
                "vw": round(weighted_price / total_volume, 4),
                "v": volume,
            }
        )
        previous = close
    # The established price-fact index is newest first; source references name
    # the actual completed pivot/earlier high, not a made-up latest-bar extreme.
    packet["recent_minute_bars"] = list(reversed(bars))
    packet["sample_plan"].update(
        stop=stop,
        target=target,
        stop_fact=f"minute:{59 - stop_minute}:l",
        target_fact="minute:59:h",
        entry_guard={"min": base, "max": guard_max},
    )
    packet.update(
        scenario_version=SCENARIO_VERSION,
        scenario_id=f"{symbol.lower()}-history-v2",
        scenario=description,
        vwap_basis="Cumulative volume-weighted OHLC typical price within this invented 60-minute window; not exchange VWAP.",
    )
    return packet


def prepare(db, *, scenarios=False):
    if not access.sample_replays_enabled():
        raise decisions.DecisionError("Sample replay preparation is disabled")
    now = datetime.now(timezone.utc)
    day = now.astimezone(ET).date()
    key = PREFIX + (SCENARIO_VERSION + ":" if scenarios else "") + day.isoformat()
    run = db.exec(select(PracticeRun).where(PracticeRun.session_key == key)).first()
    if run and eligible(run):
        return run
    if run is None:
        job = JobRun(
            job_type="sample_replay_fixture", status="running", total=2, done=0
        )
        db.add(job)
        db.flush()
        run = PracticeRun(
            session_key=key,
            day=day,
            job_id=job.id,
            mode="manual",
            comparison="assisted",
            status="preparing",
            result="sample_paper_replay",
            deadline=(now + timedelta(hours=20)).replace(tzinfo=None),
            policy_version=decisions.REPLAY_POLICY_VERSION,
            policy_hash=decisions.REPLAY_POLICY_HASH,
            calendar_json=json.dumps(
                {
                    "status": "simulated",
                    "description": "Relative sample session; no real calendar",
                }
            ),
            brief_json="[]",
        )
        db.add(run)
        db.commit()
    else:
        job = db.get(JobRun, run.job_id)
    for symbol, base in (("MU", 110.0), ("NBIS", 60.0)):
        opp = db.exec(
            select(PracticeOpportunity).where(
                PracticeOpportunity.run_id == run.id,
                PracticeOpportunity.symbol == symbol,
            )
        ).first()
        if opp and opp.context_id:
            # Published contexts and their sealed continuations are never refreshed.
            continue
        if opp is None:
            payload, _ = seal(base)
            opp = PracticeOpportunity(
                run_id=run.id,
                symbol=symbol,
                benchmark_json=decisions._canonical(payload),
            )
            db.add(opp)
            db.commit()  # persist the continuation before freezing its public commitment
        payload = json.loads(opp.benchmark_json)
        digest = decisions._hash(decisions._canonical(payload))
        packet = (scenario_packet if scenarios else sample_practice.packet)(
            symbol, base, now, run
        )
        packet.update(
            replay_exercise=True,
            replay_commitment=digest,
            replay_rules={**POLICY, "hash": POLICY_HASH},
            rules={
                **decisions.REPLAY_POLICY_SPEC,
                "policy_hash": decisions.REPLAY_POLICY_HASH,
                "decision_deadline": run.deadline.isoformat() + "Z",
                "exercise_ends": run.deadline.isoformat() + "Z",
            },
            notice="Invented bars and prices. This sample replay is separate from live trading.",
            scenario=packet["scenario"]
            + " TAKE saves a conditional plan before the replay trigger. WAIT/SKIP stay valid and create no entry. The continuation is hidden until you start your own TAKE replay.",
            replay_notice="Invented session clock: minute 0 is session open. Capture/save timestamps are real; replay seconds are simulated. Plan start must precede the real exercise deadline; replay expiry is minute 60.",
        )
        context, _ = decisions.freeze_context(
            db, f"sample:{run.id}:{symbol}", symbol, packet
        )
        opp.context_id, opp.benchmark_json = context.id, decisions._canonical(payload)
        db.add(opp)
        db.commit()
    run.status, run.finished_at = "prepared", now.replace(tzinfo=None)
    job.status, job.done, job.finished_at = "succeeded", 2, now.replace(tzinfo=None)
    db.add(run)
    db.add(job)
    db.commit()
    return run


def _rows(db, record):
    return list(
        db.exec(
            select(DecisionEvent)
            .where(DecisionEvent.record_id == record.id)
            .order_by(DecisionEvent.seq)
        ).all()
    )


def view(db, record):
    rows = _rows(db, record)
    if not rows:
        return None
    if any(
        row.source != SOURCE or not row.event_type.startswith("sample_replay_")
        for row in rows
    ):
        raise decisions.DecisionError("Sample replay ledger is incompatible")
    data = [json.loads(row.data_json) for row in rows]
    if (
        data[-1].get("type") != "replay_result"
        or data[0].get("record_sha256") != record.record_sha256
    ):
        raise decisions.DecisionError(
            "Sample replay receipt is incomplete or has a different decision"
        )
    # Read the committed outcome; do not recompute history through a new reducer.
    result = data[-1]
    if (
        decisions._hash(decisions._canonical(result["continuation"]))
        != data[0].get("tape_sha256")
        or data[0].get("evidence_sha256") != record.evidence_sha256
    ):
        raise decisions.DecisionError("Stored replay commitment mismatch")
    return {
        "record_id": str(record.id),
        "simulated": True,
        "status": result["status"],
        "policy_version": data[0]["policy_version"],
        "policy_hash": data[0]["policy_hash"],
        "tape_sha256": data[0]["tape_sha256"],
        "clock": POLICY["clock"],
        "receipt_sha256": decisions._hash(
            decisions._canonical([row.data_json for row in rows])
        ),
        "events": [
            {
                **event,
                "seq": row.seq,
                "recorded_at": row.recorded_at.isoformat() + "Z",
                "source": row.source,
            }
            for row, event in zip(rows, data)
            if event["type"] != "replay_result"
        ],
        "outcome": result["outcome"],
        "outcome_x3": result["outcome_x3"],
        "continuation": result["continuation"],
        "commitment_verified": True,
    }


def _writer(db, who, run, opp):
    principal = db.get(AccessPrincipal, who.identifier)
    session = db.get(AccessSession, who.session_digest) if who.session_digest else None
    now = access.now()
    if (
        who.owner
        or who.service
        or not principal
        or not principal.enabled
        or not session
        or session.principal_id != who.identifier
        or session.audience != "assistant"
        or session.version != principal.version
        or session.expires_at <= now
        or not principal.credential_expires_at
        or principal.credential_expires_at <= now
    ):
        raise PermissionError("Sample replay login is no longer authorized")
    grants = json.loads(principal.grants_json)
    if (
        grants != who.grants
        or grants.get("sample_replay") is not True
        or grants.get("decision_write") is not True
        or grants.get("journal_read") is not False
        or grants.get("run_ids") != [str(run.id)]
        or opp.symbol not in grants.get("symbols", [])
        or opp.symbol not in POLICY["universe"]
        or len(grants.get("symbols", [])) > 2
    ):
        raise PermissionError("Sample replay is outside this login's grant")


def start(db, opp_id, who):
    if not access.sample_replays_enabled():
        raise PermissionError("Sample replay is disabled")
    access._serialized(
        db
    )  # shares the grant/revocation lock; all events commit together
    db.expire_all()
    opp = db.get(PracticeOpportunity, opp_id)
    run = db.get(PracticeRun, opp.run_id) if opp else None
    if run is None:
        raise LookupError("Sample opportunity not found")
    _writer(db, who, run, opp)
    if not eligible(run):
        raise decisions.DecisionError("Only a fresh replay exercise can start")
    record = db.exec(
        select(DecisionRecord).where(
            DecisionRecord.opportunity_id == f"a3:{opp.id}",
            DecisionRecord.actor == sample_practice.actor(who.identifier),
        )
    ).first()
    if not record or record.decision != "take":
        raise decisions.DecisionError("Only your saved TAKE can start a sample replay")
    if (record.policy_version, record.policy_hash) != (
        decisions.REPLAY_POLICY_VERSION,
        decisions.REPLAY_POLICY_HASH,
    ):
        raise decisions.DecisionError("Decision is not a sample replay plan")
    existing = view(db, record)
    if existing:
        db.commit()
        return run, False
    now = access.now()
    if run.deadline <= now:
        raise decisions.DecisionError("Sample replay start deadline has passed")
    context = db.get(DecisionContext, record.context_id)
    if (
        not context
        or context.id != opp.context_id
        or context.data_json != record.evidence_json
    ):
        raise decisions.DecisionError(
            "Replay context does not match the saved decision"
        )
    digest = decisions._hash(context.data_json)
    if digest != context.context_sha256 or digest != record.evidence_sha256:
        raise decisions.DecisionError("Frozen evidence hash mismatch")
    packet = json.loads(context.data_json)["packet"]
    sealed = json.loads(opp.benchmark_json)
    tape_hash = decisions._hash(decisions._canonical(sealed))
    if (
        packet.get("replay_exercise") is not True
        or packet.get("replay_rules") != {**POLICY, "hash": POLICY_HASH}
        or packet.get("replay_commitment") != tape_hash
        or sealed.get("version") != VERSION
    ):
        raise decisions.DecisionError("Sealed continuation or replay policy mismatch")
    detail = json.loads(record.decision_json)
    example = packet["sample_plan"]
    plan = detail["plan"]
    extra = {"trigger_source", "stop_source", "target_source", "initial_risk_per_share"}
    if set(plan) != set(example) | extra or any(
        plan[key] != value for key, value in example.items()
    ):
        raise decisions.DecisionError(
            "Replay requires the frozen sample plan without amendments"
        )
    request = {
        "operation_id": record.operation_id,
        "opportunity_id": record.opportunity_id,
        "actor": record.actor,
        "symbol": record.symbol,
        "context_id": str(record.context_id),
        "decision": record.decision,
        # Preserve the actual submitted JSON number types: browser JSON writes
        # 110, whereas the frozen Python fixture may have published 110.0.
        "plan": {key: plan[key] for key in example},
        **{key: detail[key] for key in ("rationale", "wait_condition", "wait_expiry")},
    }
    expected = decisions._hash(
        decisions._canonical({"request": request, "context_sha256": digest})
    )
    if expected != record.record_sha256:
        raise decisions.DecisionError("Frozen decision hash mismatch")
    # Freshness/start expiry are real time; the sealed paper clock is explicitly relative.
    validated_plan = decisions._validate_take(
        record.symbol,
        context.captured_at,
        json.loads(context.data_json),
        request["plan"],
        now,
        sample=True,
    )
    if plan != validated_plan:
        raise decisions.DecisionError("Frozen plan risk or provenance mismatch")
    terms = replace(px.terms_from_plan(validated_plan), expiry=POLICY["expiry_second"])
    sessions = [
        px.Session("sample-session-1", 0, POLICY["session_seconds"]),
        px.Session("sample-session-2", 86400, 86400 + POLICY["session_seconds"]),
    ]
    bars = sealed["minutes"]
    if len(bars) != 19 or [bar["start"] for bar in bars] != list(range(900, 2040, 60)):
        raise decisions.DecisionError("Sealed sample minute coverage is incomplete")
    px._regular(bars, sessions)
    armed = {
        **px.arm_event(POLICY["armed_second"]),
        "operation_id": f"sample-replay:{record.id}",
        "policy_version": VERSION,
        "policy_hash": POLICY_HASH,
        "record_sha256": record.record_sha256,
        "evidence_sha256": digest,
        "tape_sha256": tape_hash,
        "clock_origin": context.captured_at.replace(tzinfo=timezone.utc).timestamp()
        - POLICY["armed_second"],
    }
    events = [armed]
    detected = 1800 + POLICY["detected_delay_seconds"]
    events.extend(
        px.watch(
            px.fold(events),
            terms,
            [{"start": 900, "end": 1800, "close": bars[14]["c"]}],
            detected,
        )
    )
    state = px.fold(events)
    if state.status == "triggered":
        events.append(
            {
                "type": "order_intent",
                "key": "order_intent",
                "at": detected,
                "eligible_bar_start": 1860,
                "clock": POLICY["clock"],
            }
        )
        events.extend(
            px.advance(px.fold(events), terms, bars, sessions, durable_at=detected)
        )
    else:
        events.extend(
            px.check_expiry(state, terms, terms.expiry + px.MAX_DETECTION_DELAY + 1)
        )
    state = px.fold(events)
    events.append(
        {
            "type": "replay_result",
            "key": "result",
            "at": events[-1]["at"],
            "status": state.status,
            "outcome": px.outcome(state, terms),
            "outcome_x3": px.outcome(state, terms, 3),
            "continuation": sealed,
        }
    )
    for seq, event in enumerate(events, 1):
        db.add(
            DecisionEvent(
                record_id=record.id,
                seq=seq,
                key="sample-replay:" + event["key"],
                event_type="sample_replay_" + event["type"],
                effective_at=datetime.fromtimestamp(
                    armed["clock_origin"] + event["at"], timezone.utc
                ).replace(tzinfo=None),
                recorded_at=now,
                exec_version=VERSION,
                source=SOURCE,
                data_json=decisions._canonical(event),
                delivery="none",
            )
        )
    db.commit()
    return run, True
