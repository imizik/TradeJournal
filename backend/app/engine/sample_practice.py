"""Bounded simulated decision exercise using immutable A1 records, never A2."""
import json
from datetime import datetime, timedelta, timezone

from sqlmodel import select

from app.engine import decisions
from app.models import DecisionContext, DecisionRecord, PracticeOpportunity, PracticeRun, JobRun
from app.engine.chart_math import ET

PREFIX = "dot-sample-decision:"


def eligible(run):
    return (run.session_key.startswith(PREFIX)
        and (run.policy_version, run.policy_hash) in {
            (decisions.SAMPLE_POLICY_VERSION, decisions.SAMPLE_POLICY_HASH),
            (decisions.REPLAY_POLICY_VERSION, decisions.REPLAY_POLICY_HASH)} and run.status == "prepared")


def actor(identifier):
    return "agent:" + identifier


def view(db, run, identifier, symbols, *, details=True):
    from app.engine import sample_replay
    if not eligible(run):
        raise decisions.DecisionError("Sample run not found")
    result = {"id": str(run.id), "day": run.day.isoformat(), "sample_data": True,
              "policy_version": run.policy_version, "policy_hash": run.policy_hash,
              "deadline": run.deadline.isoformat() + "Z", "replay_exercise": sample_replay.eligible(run), "opportunities": []}
    if not details:
        return result
    for opp in db.exec(select(PracticeOpportunity).where(PracticeOpportunity.run_id == run.id)).all():
        if opp.symbol not in symbols or opp.context_id is None:
            continue
        context = db.get(DecisionContext, opp.context_id)
        if not context or context.provider != "sample_fixture":
            continue
        evidence = json.loads(context.data_json)
        if evidence.get("packet", {}).get("sample_data") is not True:
            continue
        choice = db.exec(select(DecisionRecord).where(
            DecisionRecord.opportunity_id == f"a3:{opp.id}", DecisionRecord.actor == actor(identifier))).first()
        result["opportunities"].append({"id": str(opp.id), "symbol": opp.symbol,
            "context": decisions.context_row(context, evidence), "choice": decisions.row(choice) if choice else None,
            "replay": sample_replay.view(db, choice) if choice and sample_replay.eligible(run) else None})
    return result


def choose(db, run, opp, identifier, body):
    from app.engine import sample_replay
    if not eligible(run):
        raise decisions.DecisionError("Sample run not found")
    if not str(body.get("rationale", "")).strip():
        raise decisions.DecisionError("Explain the simulated decision before saving")
    identity = actor(identifier)
    payload = {"operation_id": f"sample:{opp.id}:{identifier}", "opportunity_id": f"a3:{opp.id}",
        "actor": identity, "symbol": opp.symbol, "context_id": str(opp.context_id),
        **{key: body.get(key) for key in ("decision", "rationale", "wait_condition", "wait_expiry", "plan")}}
    return decisions.create(db, payload, routine=True, sample=True, receipt_deadline=run.deadline,
        sample_replay=sample_replay.eligible(run))


def prepare(db):
    """Operator-only: create today's immutable demonstration, with no choices."""
    now = datetime.now(timezone.utc)
    day = now.astimezone(ET).date()
    session_key = PREFIX + day.isoformat()
    existing = db.exec(select(PracticeRun).where(PracticeRun.session_key == session_key)).first()
    if existing:
        prepared = db.exec(select(PracticeOpportunity).where(PracticeOpportunity.run_id == existing.id)).all()
        if eligible(existing) and {opp.symbol for opp in prepared if opp.context_id} == {"MU", "NBIS"}:
            return existing
        run = existing
        job = db.get(JobRun, run.job_id)
    else:
        job = JobRun(job_type="sample_fixture", status="running", total=2, done=0)
        db.add(job)
        db.flush()
        run = PracticeRun(session_key=session_key, day=day, job_id=job.id, mode="manual", comparison="assisted",
            status="preparing", result="sample_decision_exercise", deadline=(now + timedelta(hours=20)).replace(tzinfo=None),
            policy_version=decisions.SAMPLE_POLICY_VERSION, policy_hash=decisions.SAMPLE_POLICY_HASH,
            calendar_json=json.dumps({"status": "simulated", "description": "UI exercise only"}),
            brief_json=json.dumps([{"title": "Simulated decision exercise", "text": "MU/NBIS sample facts; no live market or paper execution.", "sources": []}]))
        db.add(run)
        db.commit()
    for symbol, base in (("MU", 110.0), ("NBIS", 60.0)):
        previous = db.exec(select(PracticeOpportunity).where(PracticeOpportunity.run_id == run.id, PracticeOpportunity.symbol == symbol)).first()
        if previous and previous.context_id:
            continue
        context, _ = decisions.freeze_context(db, f"sample:{run.id}:{symbol}", symbol, packet(symbol, base, now, run))
        opp = previous or PracticeOpportunity(run_id=run.id, symbol=symbol)
        opp.context_id = context.id
        db.add(opp)
        db.commit()
    run.status, run.finished_at = "prepared", now.replace(tzinfo=None)
    job.status, job.done, job.finished_at = "succeeded", 2, now.replace(tzinfo=None)
    db.add(run)
    db.add(job)
    db.commit()
    return run


def packet(symbol, base, now, run):
    end = now.replace(second=0, microsecond=0) - timedelta(minutes=1)
    bars = [{"t": (end - timedelta(minutes=i)).isoformat(), "o": base - .2, "h": base + 4,
             "l": base - 2, "c": base, "vw": base - .1, "v": 1000 + i * 20} for i in range(60)]
    expiry = run.deadline.replace(tzinfo=timezone.utc).isoformat()
    plan = {"instrument": "stock", "direction": "long", "trigger": decisions.POLICY_SPEC["trigger"],
        "trigger_level": base, "trigger_fact": "minute:0:c", "stop": base - 2, "stop_fact": "minute:0:l",
        "target": base + 4, "target_fact": "minute:0:h", "entry_guard": {"min": base, "max": base + .5},
        "expiry": expiry, "max_holding_sessions": 2, "freshness_limit_seconds": 86400,
        "cost_model": {"version": "sample-cost-v1", "slippage_bps": 1, "slippage_per_share": .01}}
    return {"symbol": symbol, "data_source": "sample_fixture", "sample_data": True,
        "generated_at": now.isoformat(), "sample_session_day": run.day.isoformat(), "sample_run_id": str(run.id),
        "notice": "Invented bars and prices for a UI exercise. No live market inference or execution.",
        "recent_minute_bars": bars, "recent_daily_bars": [], "missing": ["Live news, options and daily history are outside this sample exercise"],
        "scenario": "Demonstration prices bracket a long trigger; choose TAKE, WAIT or SKIP and explain why.",
        "rules": {**decisions.SAMPLE_POLICY_SPEC, "policy_hash": decisions.SAMPLE_POLICY_HASH,
            "decision_deadline": expiry, "exercise_ends": expiry}, "sample_plan": plan}
