"""Isolated sequential scanner benchmark; immutable choices, batch-gated exams.

Reuses existing run/context/decision storage without arming the paper engine.
All private continuation lives in calendar_json; generic practice projections
must refuse this schema. No provider or model is called by these functions.
"""
from datetime import date, timedelta, timezone
import json
import random
import re
import uuid

from sqlmodel import select

from app.engine import access, decisions
from app.engine import scanner_replay_market as market
from app.models import AccessPrincipal, DecisionContext, DecisionRecord, JobRun, PracticeRun

SCHEMA = "practice-scanner-replay-v1"
PREFIX = "scanner-replay:"
MAX_SESSIONS = 30
MAX_SETUPS = 200
DEFAULT_PROMPT = (
    "Act as Shadow Isaac in a historical selection benchmark. Start the next assigned replay run; "
    "read its next_setup, then commit TAKE, SKIP or INSUFFICIENT_DATA with a reason of at most 1000 characters. "
    "The scanner's direction, stop, target and exits are fixed; decide only whether to take the setup. "
    "Use only the supplied frozen setup, historical market packet, candles and prior closed-trade aggregates. "
    "Do not call other trading, journal, email or co-pilot tools. Missing historical option fields are unavailable, "
    "not a failed liquidity check. After each commit read the same run for its next setup. "
    "Resume interruptions at the next uncommitted setup. Do not request outcomes during a run. "
    "For an interrupted run call get_practice_run with resume=true so the next uncommitted setup is marked in its receipt. "
    "This is underlying-scored paper research, with no explicit outcome feedback, not live options execution."
)


def canonical(value):
    return decisions._canonical(value)


def digest(value):
    return decisions._hash(canonical(value))


def recognized(run):
    return bool(run and run.session_key.startswith(PREFIX))


def metadata(run):
    meta = json.loads(run.brief_json)
    if not recognized(run) or meta.get("schema") != SCHEMA or digest(meta["manifest"]) != run.policy_hash:
        raise decisions.DecisionError("Scanner replay manifest integrity failed")
    return meta


def eligible(run):
    return recognized(run) and run.policy_version == SCHEMA and run.status in {"prepared", "committed", "abandoned"}


def split_dates(days, seed, exam_count=0, *, allow_holdout=False):
    if type(seed) is not int or type(exam_count) is not int or not 0 <= exam_count <= len(days):
        raise decisions.DecisionError("Invalid recorded split seed or exam count")
    ordered = sorted(days)
    if not 1 <= len(ordered) <= MAX_SESSIONS or len(set(ordered)) != len(ordered):
        raise decisions.DecisionError("Choose one to thirty distinct sessions")
    for day in ordered:
        parsed = date.fromisoformat(day)
        if parsed.isoformat() != day or (parsed >= date(2026, 9, 14) and not allow_holdout):
            raise decisions.DecisionError("SC-3 holdout requires explicit --allow-holdout")
    shuffled = ordered[:]
    random.Random(seed).shuffle(shuffled)
    exams = set(shuffled[:exam_count])
    return {day: "exam" if day in exams else "practice" for day in ordered}


def prepare_batch(db, bundles, *, identifier, seed, exam_count=0, prompt_text=DEFAULT_PROMPT,
                  prompt_version="tj-shadow-selection-v2", policy=None, history_rows=None, allow_holdout=False):
    """Operator-only import. Split/freeze BEFORE generating or observing results."""
    if not re.fullmatch(r"[a-z][a-z0-9_-]{2,63}", identifier) or identifier == "owner":
        raise decisions.DecisionError("Use a fresh isolated actor")
    if not prompt_text.strip() or len(prompt_text) > 16000 or not prompt_version.strip() or len(prompt_version) > 128:
        raise decisions.DecisionError("Freeze a bounded prompt text and version")
    phases = split_dates([b["session_date"] for b in bundles], seed, exam_count, allow_holdout=allow_holdout)
    policy = policy or market.scoring_policy()
    history_rows = history_rows or []
    inputs = {b["session_date"]: digest(b) for b in bundles}
    identity = digest({"actor": identifier, "inputs": inputs, "phases": phases, "seed": seed, "exam_count": exam_count,
                       "prompt_text": prompt_text, "prompt_version": prompt_version, "policy": policy,
                       "history_sha256": digest(history_rows), "allow_holdout": allow_holdout})
    ids = {day: str(uuid.uuid5(uuid.NAMESPACE_URL, PREFIX + identity + ":" + day)) for day in phases}
    manifest = {"schema": SCHEMA, "actor": identifier, "batch_id": identity, "run_ids": ids,
                "phases": phases, "seed": seed, "exam_count": exam_count, "prompt_text": prompt_text, "prompt_version": prompt_version,
                "scoring_policy": policy, "input_sha256": inputs, "history_sha256": digest(history_rows),
                "allow_holdout": allow_holdout, "scanner_version": market.rules.VERSION,
                "params_hash": market.rules.PARAMS_HASH}
    previous = [db.get(PracticeRun, uuid.UUID(value)) for value in ids.values()]
    if any(previous):
        if all(previous) and all(metadata(r)["manifest"] == manifest for r in previous):
            return previous
        raise decisions.DecisionError("Cannot replace a partial or different frozen batch")
    if db.get(AccessPrincipal, identifier):
        raise decisions.DecisionError("Existing actor cannot be repointed")
    # Actor names are single-batch identities, even before credentials are issued.
    for existing in db.exec(select(PracticeRun).where(PracticeRun.session_key.startswith(PREFIX))).all():
        if metadata(existing)["manifest"]["actor"] == identifier:
            raise decisions.DecisionError("Actor already has a frozen scanner batch")
    now = access.now()
    job = JobRun(job_type="scanner_replay_import", status="running", total=len(bundles), done=0)
    db.add(job)
    db.flush()
    runs = []
    try:
        for bundle in sorted(bundles, key=lambda b: b["session_date"]):
            generated = market.generate_session(bundle, scoring_policy=policy, history_rows=history_rows, allow_holdout=allow_holdout)
            if decisions._utc(generated["retrieved_at"], "retrieval") > now:
                raise decisions.DecisionError("Provider retrieval cannot be in the future")
            if len(generated["setups"]) > MAX_SETUPS:
                raise decisions.DecisionError("Scanner session exceeds bounded setup count")
            day = bundle["session_date"]
            run = PracticeRun(id=uuid.UUID(ids[day]), session_key=PREFIX + identity + ":" + day,
                day=date.fromisoformat(day), job_id=job.id, mode="manual", comparison="assisted",
                status="prepared", result="historical_selection_benchmark", deadline=now + timedelta(days=30),
                policy_version=SCHEMA, policy_hash=digest(manifest),
                brief_json=canonical({"schema": SCHEMA, "manifest": manifest, "phase": phases[day],
                    "differences": generated["differences"], "coverage_gaps": generated["gaps"],
                    "coverage": generated["coverage"], "daily_atr": generated["daily_atr"],
                    "retrieved_at": generated["retrieved_at"]}))
            db.add(run)
            db.flush()
            entries = []
            for index, setup in enumerate(generated["setups"]):
                packet = setup["packet"]
                opportunity_id = str(uuid.uuid5(run.id, packet["candidate"]["candidate_id"]))
                sealed = setup["continuation"]
                public = {**packet, "replay_commitment": digest(sealed), "opportunity_id": opportunity_id,
                          "schema_version": SCHEMA}
                context = DecisionContext(operation_id=f"scanner:{opportunity_id}",
                    symbol=packet["candidate"]["symbol"], provider="alpaca_sip",
                    captured_at=decisions._utc(generated["retrieved_at"], "retrieval"),
                    data_json=canonical(public), context_sha256=digest(public))
                db.add(context)
                db.flush()
                entries.append({"index": index, "opportunity_id": opportunity_id, "context_id": str(context.id),
                                "symbol": context.symbol, "sealed": sealed})
            run.calendar_json = canonical({"session": generated["session"], "entries": entries})
            meta = json.loads(run.brief_json)
            meta["calendar_sha256"] = decisions._hash(run.calendar_json)
            run.brief_json = canonical(meta)
            db.add(run)
            runs.append(run)
            if not entries:
                run.status, run.finished_at = "committed", now
                run.timings_json = canonical({"served": {}, "results": [], "results_sha256": digest([])})
        job.status, job.done, job.finished_at = "succeeded", len(runs), now
        db.add(job)
        db.commit()
    except BaseException:
        db.rollback()
        raise
    return runs


def entries(run):
    meta = metadata(run)
    if decisions._hash(run.calendar_json) != meta["calendar_sha256"]:
        raise decisions.DecisionError("Frozen scanner sequence integrity failed")
    return json.loads(run.calendar_json)["entries"]


def context_packet(db, entry):
    context = db.get(DecisionContext, uuid.UUID(entry["context_id"]))
    if not context or context.symbol != entry["symbol"] or decisions._hash(context.data_json) != context.context_sha256:
        raise decisions.DecisionError("Frozen scanner evidence integrity failed")
    packet = json.loads(context.data_json)
    if packet["opportunity_id"] != entry["opportunity_id"] or packet["replay_commitment"] != digest(entry["sealed"]):
        raise decisions.DecisionError("Scanner continuation commitment failed")
    return context, packet


def own_records(db, run, actor):
    return {r.operation_id: r for r in db.exec(select(DecisionRecord).where(
        DecisionRecord.actor == "agent:" + actor,
        DecisionRecord.operation_id.startswith(f"scanner:{run.id}:"))).all()}


def operation(run, entry):
    return f"scanner:{run.id}:{entry['opportunity_id']}"


def receipt(record):
    value = json.loads(record.decision_json)
    if digest(value) != record.record_sha256:
        raise decisions.DecisionError("Scanner receipt integrity failed")
    return value


def authorized(run, actor, symbols):
    manifest = metadata(run)["manifest"]
    if not eligible(run) or manifest["actor"] != actor or not set(e["symbol"] for e in entries(run)) <= set(symbols):
        raise decisions.DecisionError("Scanner run is outside the frozen assignment")


def reveal_allowed(db, run):
    meta = metadata(run)
    if meta["phase"] == "practice":
        return run.status in {"committed", "abandoned"}
    manifest = meta["manifest"]
    for day, phase in manifest["phases"].items():
        if phase != "exam":
            continue
        other = db.get(PracticeRun, uuid.UUID(manifest["run_ids"][day]))
        if not other or metadata(other)["manifest"] != manifest or other.status != "committed":
            return False
    return True


def view(db, run, actor, symbols, *, details=True, resume=False):
    authorized(run, actor, symbols)
    meta = metadata(run)
    values = entries(run)
    records = own_records(db, run, actor)
    read_only = meta["manifest"]["scoring_policy"]["version"] != market.VERSION
    next_entry = next((e for e in values if operation(run, e) not in records), None) if run.status == "prepared" and not read_only else None
    state = json.loads(run.timings_json)
    revealed = reveal_allowed(db, run)
    result = {"id": str(run.id), "day": run.day.isoformat(), "status": run.status, "phase": meta["phase"],
        "schema_version": SCHEMA, "setups": len(values) if revealed else None, "committed": len(records),
        "prompt_version": meta["manifest"]["prompt_version"], "prompt_text": meta["manifest"]["prompt_text"],
        "scoring_policy": meta["manifest"]["scoring_policy"], "policy_hash": run.policy_hash,
        "differences_from_live": meta["differences"], "labels": market.LABELS,
        "retrieved_at": meta["retrieved_at"], "coverage_gaps": meta["coverage_gaps"] if revealed else None,
        "coverage": meta.get("coverage") if revealed else None,
        "daily_atr": meta.get("daily_atr") if revealed else None,
        "next_setup": None, "choices": [], "report": None,
        "outcomes_sealed": not revealed, "expires_on_historical_clock": False,
        "read_only": read_only,
        "batch_runs": [{"day": day, "run_id": value, "phase": meta["manifest"]["phases"][day]}
                       for day, value in meta["manifest"]["run_ids"].items()]}
    if details:
        result["choices"] = [receipt(records[operation(run, e)]) for e in values if operation(run, e) in records]
        if next_entry:
            _, result["next_setup"] = context_packet(db, next_entry)
            served = state.setdefault("served", {})
            changed = False
            if resume:
                if not records and not served:
                    raise decisions.DecisionError("An unstarted run cannot be marked resumed")
                marks = state.setdefault("resume_marks", {})
                if next_entry["opportunity_id"] not in marks:
                    marks[next_entry["opportunity_id"]] = access.now().replace(tzinfo=timezone.utc).isoformat()
                    changed = True
            if next_entry["opportunity_id"] not in served:
                served[next_entry["opportunity_id"]] = access.now().replace(tzinfo=timezone.utc).isoformat()
                changed = True
            if changed:
                run.timings_json = canonical(state)
                db.add(run)
                db.commit()
        if revealed:
            result["report"] = report(db, run)
    return result


def locate(db, run_ids, opportunity_id):
    for value in run_ids:
        run = db.get(PracticeRun, uuid.UUID(value))
        if not eligible(run):
            continue
        entry = next((e for e in entries(run) if e["opportunity_id"] == opportunity_id), None)
        if entry:
            return run, entry
    raise decisions.DecisionError("Scanner opportunity not found")


def choose(db, run, entry, actor, symbols, payload):
    authorized(run, actor, symbols)
    if payload["decision"] not in {"take", "skip", "insufficient_data"} or not 1 <= len(payload["rationale"].strip()) <= 1000:
        raise decisions.DecisionError("Scanner choices require TAKE, SKIP or INSUFFICIENT_DATA and a bounded reason")
    if any(payload.get(k) is not None for k in ("plan", "wait_condition", "wait_expiry")):
        raise decisions.DecisionError("Scanner choices cannot change contracts or exits")
    context, packet = context_packet(db, entry)
    records = own_records(db, run, actor)
    key = operation(run, entry)
    if key in records:
        saved = receipt(records[key])
        if saved["decision"] != payload["decision"] or saved["reason"] != payload["rationale"]:
            raise decisions.DecisionError("Opportunity already has different content")
        return records[key], False
    if metadata(run)["manifest"]["scoring_policy"]["version"] != market.VERSION:
        raise decisions.DecisionError("Legacy scanner run is read-only; its frozen policy cannot accept new choices")
    if run.status != "prepared" or next((e for e in entries(run) if operation(run, e) not in records), None) != entry:
        raise decisions.DecisionError("Commit only the next uncommitted setup")
    now = access.now()
    state = json.loads(run.timings_json)
    served = state.get("served", {}).get(entry["opportunity_id"])
    if served is None:
        raise decisions.DecisionError("Read the frozen setup before committing")
    choice = {"schema_version": SCHEMA, "run_id": str(run.id), "opportunity_id": entry["opportunity_id"],
        "candidate_id": packet["candidate"]["candidate_id"], "decision": payload["decision"],
        "reason": payload["rationale"], "committed_at": now.replace(tzinfo=timezone.utc).isoformat(),
        "served_at": served, "wall_seconds": max(0, (now - decisions._utc(served, "served time")).total_seconds()),
        "resumed": entry["opportunity_id"] in state.get("resume_marks", {}),
        "resumed_at": state.get("resume_marks", {}).get(entry["opportunity_id"]),
        "prompt_version": metadata(run)["manifest"]["prompt_version"], "policy_hash": run.policy_hash,
        "context_sha256": context.context_sha256, "status": "scanner_selection_unarmed"}
    record = DecisionRecord(operation_id=key, opportunity_id="scanner:" + entry["opportunity_id"],
        actor="agent:" + actor, decision=payload["decision"], symbol=context.symbol, context_id=context.id,
        received_at=now, input_cutoff=decisions._utc(packet["candidate"]["detected_at"], "detection"),
        policy_version=SCHEMA, policy_hash=run.policy_hash, evidence_json=context.data_json,
        evidence_sha256=context.context_sha256, decision_json=canonical(choice), record_sha256=digest(choice))
    db.add(record)
    db.flush()
    if len(records) + 1 == len(entries(run)):
        run.status, run.finished_at = "committed", now
        state["results"] = score_results(db, run)
        state["results_sha256"] = digest(state["results"])
        run.timings_json = canonical(state)
        db.add(run)
    db.commit()
    return record, True


def score_results(db, run):
    meta = metadata(run)
    policy = meta["manifest"]["scoring_policy"]
    session = json.loads(run.calendar_json)["session"]
    records = own_records(db, run, meta["manifest"]["actor"])
    randomizer = random.Random(str(meta["manifest"]["seed"]) + ":" + run.day.isoformat())
    rows = []
    for entry in entries(run):
        _, packet = context_packet(db, entry)
        candidate = packet["candidate"]
        record = records.get(operation(run, entry))
        rows.append({"opportunity_id": entry["opportunity_id"], "candidate": candidate,
            "choice": receipt(record) if record else None,
            "rules": market.score_setup(candidate, entry["sealed"], session, policy, delay_seconds=0),
            "delayed": market.score_setup(candidate, entry["sealed"], session, policy,
                                           delay_seconds=policy["decision_delay_seconds"]),
            "random_take": randomizer.random() < 0.5})
    return rows


def abandon(db, run):
    """Operator-only, terminal practice abandonment; exams stay sealed."""
    # The operator acquires writer serialization before calling. Its earlier
    # lookup may predate Jo's final commit; never transition a cached status.
    db.refresh(run)
    metadata(run)
    if run.status == "prepared":
        state = json.loads(run.timings_json)
        state["results"] = score_results(db, run)
        state["results_sha256"] = digest(state["results"])
        run.status, run.finished_at = "abandoned", access.now()
        run.timings_json = canonical(state)
        db.add(run)
        db.commit()


def summary(rows, select_row=lambda row: True, result_key="rules"):
    chosen = [row for row in rows if select_row(row)]
    resolved = [row[result_key] for row in chosen if row[result_key]["resolved"]]
    rs = [row["r"] for row in resolved]
    sensitivity = [row for row in resolved if row.get("r_cost_sensitivity") is not None]
    return {"selected": len(chosen), "resolved": len(resolved), "unresolved_or_invalidated": len(chosen)-len(resolved),
        "unresolved": sum(row[result_key]["status"] == "unresolved" for row in chosen),
        "invalidated": sum(row[result_key]["status"] == "invalidated" for row in chosen),
        "total_r": round(sum(rs), 6) if rs else None,
        "mean_r": round(sum(rs)/len(rs), 6) if rs else None,
        "win_rate": sum(r > 0 for r in rs)/len(rs) if rs else None,
        "pnl_100": round(sum(row["pnl_100"] for row in resolved), 2) if resolved else None,
        "cost_sensitivity_resolved": len(sensitivity),
        "r_cost_sensitivity": round(sum(row["r_cost_sensitivity"] for row in sensitivity), 6) if sensitivity else None,
        "pnl_100_cost_sensitivity": round(sum(row["pnl_100_cost_sensitivity"] for row in sensitivity), 2) if sensitivity else None}


def scorecard(rows, session_count):
    def decision(row):
        return (row["choice"] or {}).get("decision")
    card = {"setups": len(rows), "sessions": session_count,
        "decisions": {key: sum(decision(r) == key for r in rows) for key in ("take", "skip", "insufficient_data")},
        "uncommitted": sum(r["choice"] is None for r in rows),
        "rules_take_all": summary(rows), "jo_baseline_entry": summary(rows, lambda r: decision(r) == "take"),
        "jo_delayed_entry": summary(rows, lambda r: decision(r) == "take", "delayed"),
        "skipped_setups": summary(rows, lambda r: decision(r) == "skip"),
        "seeded_random_50pct": summary(rows, lambda r: r["random_take"]),
        "skip_all": {"selected": 0, "resolved": 0, "total_r": 0, "pnl_100": 0, "win_rate": None,
                     "r_cost_sensitivity": 0, "pnl_100_cost_sensitivity": 0}}
    card["evidence_warning"] = "not enough evidence" if sum(card["decisions"].values()) < 30 else None
    card["threshold_notice"] = "30 decisions is a display warning threshold, not proof; setups within sessions are correlated"
    return card


def snapshot_results(run):
    state = json.loads(run.timings_json)
    rows = state.get("results", [])
    if state.get("results_sha256") != digest(rows):
        raise decisions.DecisionError("Scanner result snapshot integrity failed")
    return rows


def report(db, run):
    if not reveal_allowed(db, run):
        raise decisions.DecisionError("Results are sealed")
    rows = snapshot_results(run)
    return {"scorecard": scorecard(rows, 1), "setups": rows, "cumulative": cumulative_report(db, run),
        "by_setup": {kind: scorecard([r for r in rows if r["candidate"]["setup"] == kind], 1)
                     for kind in sorted({r["candidate"]["setup"] for r in rows})},
        "contract_eligibility": "all unknown; with/without-contract cohort omitted", "labels": market.LABELS}


def cumulative_report(db, run):
    manifest = metadata(run)["manifest"]
    grouped = {"practice": [], "exam": []}
    counts = {"practice": 0, "exam": 0}
    for value in manifest["run_ids"].values():
        other = db.get(PracticeRun, uuid.UUID(value))
        if other and metadata(other)["manifest"] == manifest and reveal_allowed(db, other):
            phase = metadata(other)["phase"]
            grouped[phase].extend(snapshot_results(other))
            counts[phase] += 1
    return {phase: {**scorecard(rows, counts[phase]),
                   "by_setup": {kind: scorecard([r for r in rows if r["candidate"]["setup"] == kind],
                                               len({r["candidate"]["session_date"] for r in rows if r["candidate"]["setup"] == kind}))
                                for kind in sorted({r["candidate"]["setup"] for r in rows})}}
            for phase, rows in grouped.items()}
