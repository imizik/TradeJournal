"""A3 daily routine; orchestration only, A1/A2 remain the decision authorities."""
from datetime import datetime, time, timezone
import json
import os
import uuid

from fastapi.encoders import jsonable_encoder
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.engine import decisions, paper, practice_agent
from app.engine.chart_math import ET
from app.models import DecisionContext, DecisionEvent, DecisionRecord, JobRun, PracticeAgentCall, PracticeOpportunity, PracticeRun

UTC = timezone.utc
BENCHMARK = {"version": "underlying-open-close-v1", "source": paper.SOURCE,
             "measure": "100 * (regular close / regular open - 1)",
             "coverage": "every regular-session minute, positive OHLC, verified no split",
             "costs": "none; descriptive underlying return, never actor P&L or R"}


def now_utc():
    return datetime.now(UTC).replace(tzinfo=None)


def iso(value):
    return value.replace(tzinfo=UTC).isoformat() if value else None


def opportunities(db, run_id):
    return list(db.exec(select(PracticeOpportunity).where(PracticeOpportunity.run_id == run_id).order_by(PracticeOpportunity.symbol)).all())


def records(db, opp):
    return {r.actor: r for r in db.exec(select(DecisionRecord).where(DecisionRecord.opportunity_id == f"a3:{opp.id}")).all()}


def start(db: Session, *, mode="manual", comparison="independent", day=None, revision=0, now=None):
    now = now or now_utc()
    day = day or now.replace(tzinfo=UTC).astimezone(ET).date()
    if mode not in {"manual", "scheduled"} or comparison not in {"independent", "assisted"}:
        raise decisions.DecisionError("Invalid preparation mode")
    key = f"{day}:{paper.POLICY_HASH}:{revision}"
    existing = db.exec(select(PracticeRun).where(PracticeRun.session_key == key)).first()
    if existing:
        return existing
    parent = None
    if revision:
        parent = db.exec(select(PracticeRun).where(PracticeRun.session_key == f"{day}:{paper.POLICY_HASH}:0")).first()
        if parent is None or revision < 1 or revision > 10:
            raise decisions.DecisionError("Revision requires the original run and revision 1–10")
        if parent.status in {"queued", "preparing"}:
            raise decisions.DecisionError("Original preparation is still active")
        comparison = "assisted"  # re-preparing cannot silently rejoin the blind cohort
    deadline = datetime.combine(day, time(9), ET).astimezone(UTC).replace(tzinfo=None)
    job = JobRun(job_type="practice_prepare", params_json="{}", total=5)
    run = PracticeRun(session_key=key, day=day, revision=revision, parent_id=parent.id if parent else None,
        job_id=job.id, mode=mode, comparison=comparison, deadline=deadline, created_at=now,
        late=now > deadline, policy_version=paper.POLICY_VERSION, policy_hash=paper.POLICY_HASH)
    job.params_json = json.dumps({"run_id": str(run.id)})
    db.add(job)
    db.add(run)
    try:
        db.flush()
        for symbol in paper.UNIVERSE:
            db.add(PracticeOpportunity(run_id=run.id, symbol=symbol,
                benchmark_json=json.dumps({**BENCHMARK, "status": "unavailable", "reason": "Session coverage not collected"})))
        db.commit()
    except IntegrityError:
        db.rollback()
        return db.exec(select(PracticeRun).where(PracticeRun.session_key == key)).one()
    db.refresh(run)
    return run


def recover_view(db, run):
    job = db.get(JobRun, run.job_id)
    if job and job.status == "failed" and run.status in {"queued", "preparing", "prepared"}:
        run.status = run.result = "failed"
        run.error = "Preparation interrupted; original evidence retained. Explicit revision required."
        run.finished_at = now_utc()
        db.add(run)
        call = db.exec(select(PracticeAgentCall).where(PracticeAgentCall.run_id == run.id)).first()
        if call and call.status == "reserved":
            call.status = "uncertain"
            call.error = "Worker interrupted; no paid retry permitted for this day"
            db.add(call)
        db.commit()


def view(db: Session, run: PracticeRun, *, details=True):
    recover_view(db, run)
    call = db.exec(select(PracticeAgentCall).where(PracticeAgentCall.run_id == run.id)).first()
    opps = opportunities(db, run.id) if details else []
    contexts = {c.id: c for c in db.exec(select(DecisionContext).where(DecisionContext.id.in_([o.context_id for o in opps if o.context_id]))).all()} if opps else {}
    saved_records = list(db.exec(select(DecisionRecord).where(DecisionRecord.opportunity_id.in_([f"a3:{o.id}" for o in opps]))).all()) if opps else []
    events = list(db.exec(select(DecisionEvent).where(DecisionEvent.record_id.in_([r.id for r in saved_records])).order_by(DecisionEvent.seq)).all()) if saved_records else []
    items = []
    for opp in opps:
        actors = {r.actor: r for r in saved_records if r.opportunity_id == f"a3:{opp.id}"}
        human, agent = actors.get("human"), actors.get("agent:a3")
        visible = run.comparison == "assisted" or opp.revealed_at is not None
        ctx = contexts.get(opp.context_id)
        late = any(r.received_at > run.deadline for r in actors.values())
        items.append({"id": str(opp.id), "symbol": opp.symbol,
            "context": decisions.context_row(ctx, json.loads(ctx.data_json)) if ctx else None,
            "human": decisions.row(human) if human else None,
            "agent": decisions.row(agent) if visible and agent else None,
            "revealed": opp.revealed_at is not None, "revealed_at": iso(opp.revealed_at),
            "reveal_timing": ("before_deadline" if opp.revealed_at <= run.deadline else "after_deadline") if opp.revealed_at else "unrevealed",
            "choice_timeliness": "late" if late or run.late else "on_time",
            "comparison_status": "assisted" if run.comparison == "assisted" else
                "late" if late or run.late else "revealed" if opp.revealed_at else "committed" if human and agent else
                "human_nonresponse" if not human else "agent_unavailable",
            "benchmark": json.loads(opp.benchmark_json),
            "paper": paper.paper_row(db, human.id, record=human, event_rows=[e for e in events if e.record_id == human.id]) if human and human.decision == "take" else None,
            "agent_paper": paper.paper_row(db, agent.id, record=agent, event_rows=[e for e in events if e.record_id == agent.id]) if visible and agent and agent.decision == "take" else None,
            "feedback": json.loads(opp.feedback_json)})
    # Validation errors/raw output can contain hidden verdicts. Never expose them before all reveals.
    all_visible = run.comparison == "assisted" or (details and bool(opps) and all(o.revealed_at for o in opps))
    return {"id": str(run.id), "day": run.day.isoformat(), "revision": run.revision,
        "parent_id": str(run.parent_id) if run.parent_id else None, "status": ("late" if run.late else "completed") if run.result == "no_setup" and not all_visible else run.status, "result": "completed" if run.result == "no_setup" and not all_visible else run.result,
        "error": run.error, "mode": run.mode, "comparison": run.comparison, "late": run.late,
        "created_at": iso(run.created_at), "finished_at": iso(run.finished_at), "deadline": iso(run.deadline),
        "calendar": json.loads(run.calendar_json), "policy_version": run.policy_version, "policy_hash": run.policy_hash,
        "brief": json.loads(run.brief_json), "timings": json.loads(run.timings_json),
        "agent": {"status": call.status if call else "disabled", "model": call.model if call else None,
            "prompt_version": call.prompt_version if call else practice_agent.PROMPT_VERSION,
            "started_at": iso(call.started_at) if call else None, "finished_at": iso(call.finished_at) if call else None,
            "runtime_seconds": (call.finished_at - call.started_at).total_seconds() if call and call.finished_at else None,
            "limits": json.loads(call.config_json) if call else None,
            "error": (call.error if all_visible or call.status in {"budget_exhausted", "uncertain"} else "Output validation failed; verdict details withheld") if call and call.error else None,
            "usage": json.loads(call.usage_json) if call and call.usage_json else None,
            "cost": call.cost_usd if call else None, "cost_provenance": "configured token rates" if call and call.cost_usd is not None else "unavailable"},
        "opportunities": items,
        "counts": {choice: sum(1 for o in items if o["human"] and o["human"]["decision"] == choice) for choice in ("take", "wait", "skip")},
        "scheduling_configured": os.environ.get("PRACTICE_SCHEDULE_ENABLED") == "true"}


def owned_record(db, record):
    if not record.opportunity_id.startswith("a3:"):
        return None
    try:
        return db.get(PracticeOpportunity, uuid.UUID(record.opportunity_id[3:]))
    except ValueError:
        return None


def visible_record(db, record):
    opp = owned_record(db, record)
    if not opp or record.actor == "human":
        return True
    run = db.get(PracticeRun, opp.run_id)
    return run.comparison == "assisted" or opp.revealed_at is not None


def choose(db, opp, request, *, actor="human"):
    run = db.get(PracticeRun, opp.run_id)
    if (actor == "human" and run.status in {"queued", "preparing"}) or opp.context_id is None:
        raise decisions.DecisionError("Preparation has not frozen this opportunity")
    if actor not in {"human", "agent:a3"}:
        raise decisions.DecisionError("Unapproved actor")
    if request.get("decision") == "take" and json.loads(run.calendar_json).get("status") != "open":
        raise decisions.DecisionError("TAKE requires a verified open session calendar")
    allowed = {"decision", "rationale", "wait_condition", "wait_expiry", "plan"}
    if set(request) - allowed:
        raise decisions.DecisionError("Actor, context and ownership are server assigned")
    payload = {"operation_id": f"a3:{opp.id}:{actor}", "opportunity_id": f"a3:{opp.id}",
        "actor": actor, "context_id": str(opp.context_id), "symbol": opp.symbol,
        "plan": None, "rationale": "", "wait_condition": None, "wait_expiry": None, **request}
    record, _ = decisions.create(db, payload, routine=True)
    return record


def reveal(db, opp):
    actors = records(db, opp)
    if set(actors) != {"human", "agent:a3"}:
        raise decisions.DecisionError("Reveal requires both durably committed choices; nonresponse is unobserved")
    if not opp.revealed_at:
        opp.revealed_at = now_utc()
        db.add(opp)
        db.commit()


def runner_payload(db, run):
    # This whitelist is the only model ingress. No raw packet, personal notes,
    # journal rows, decisions, feedback, or application credentials cross it.
    return {"prompt_version": practice_agent.PROMPT_VERSION, "policy": paper.POLICY_SPEC,
        "deadline": iso(run.deadline), "benchmark": BENCHMARK,
        "session_calendar": json.loads(run.calendar_json),
        "plan_contract": {"instrument": "stock", "direction": "long", "trigger": decisions.POLICY_SPEC["trigger"],
            "max_holding_sessions": 2, "freshness_limit_seconds": paper.FRESHNESS_SECONDS, "cost_model": paper.COST,
            "required_price_fields": ["trigger_level", "stop", "target"],
            "required_fact_fields": ["trigger_fact", "stop_fact", "target_fact"],
            "entry_guard": {"min": "at or above trigger", "max": "at or above min and strictly below target"},
            "price_order": "stop < trigger_level < target; every level equals its selected fact value",
            "expiry": "ISO timestamp after receipt and before 15:15 ET or 45 minutes before early close, whichever earlier"},
        "opportunities": [{"opportunity_id": str(o.id), "symbol": o.symbol,
            "context_sha256": db.get(DecisionContext, o.context_id).context_sha256,
            "price_facts": json.loads(db.get(DecisionContext, o.context_id).data_json)["price_facts"][-10:]}
            for o in opportunities(db, run.id) if o.context_id]}


def run_agent(db, run, *, adapter=practice_agent.invoke):
    limits = practice_agent.config()
    if limits is None:
        return "disabled"
    payload = runner_payload(db, run)
    serialized = json.dumps(payload)
    # UTF-8 bytes bound token count conservatively without a tokenizer call.
    input_bound = len(serialized.encode()) + len(practice_agent.PROMPT.encode()) + 1024  # protocol framing reserve
    maximum_cost = (input_bound * limits["input_usd_per_million"] + limits["output_tokens"] * limits["output_usd_per_million"]) / 1e6
    call = PracticeAgentCall(day=run.day, run_id=run.id, model=limits["model"],
        prompt_version=practice_agent.PROMPT_VERSION, payload_json=serialized, config_json=json.dumps(limits))
    db.add(call)
    try:
        db.commit()  # reservation survives death before/after the actual paid call
    except IntegrityError:
        db.rollback()
        raise decisions.DecisionError("Daily paid attempt already reserved; no silent retry")
    if input_bound > limits["input_tokens"] or maximum_cost > limits["daily_usd"]:
        call.status = "budget_exhausted"
        call.error = "Agent hard input/spending limit exhausted before call"
        call.finished_at = now_utc()
        db.add(call)
        db.commit()
        return call.status
    try:
        result = adapter(payload, limits)
        call.output_json = json.dumps(result)
        usage = result.get("usage")
        call.usage_json = json.dumps(usage) if usage else None
        if usage and all(type(usage.get(k)) is int and usage[k] >= 0 for k in ("input_tokens", "output_tokens")):
            call.cost_usd = (usage["input_tokens"] * limits["input_usd_per_million"] + usage["output_tokens"] * limits["output_usd_per_million"]) / 1e6
        db.add(call)
        db.commit()  # preserve exact output before validation
        output = json.loads(result["raw"])
        choices = output["choices"]
        opps = {str(o.id): o for o in opportunities(db, run.id)}
        if set(output) != {"choices"} or not isinstance(choices, list) or len(choices) != len(opps):
            raise ValueError("Expected exactly one choice for each shared opportunity")
        if any(not isinstance(c, dict) or not isinstance(c.get("opportunity_id"), str) for c in choices):
            raise ValueError("Choices must have typed opportunity IDs")
        ids = [c.get("opportunity_id") for c in choices]
        if set(ids) != set(opps) or len(set(ids)) != len(ids):
            raise ValueError("Forged or duplicated opportunity ownership")
        if sum(c.get("decision") == "take" for c in choices) > 3:
            raise ValueError("At most three agent TAKEs")
        if result.get("stop_reason") != "end_turn":
            raise ValueError("Incomplete model output")
        # Validate every choice before writing any decision; writes then have stable IDs.
        for c in choices:
            opp = opps[c["opportunity_id"]]
            request = {k: v for k, v in c.items() if k != "opportunity_id"}
            if set(request) - {"decision", "rationale", "wait_condition", "wait_expiry", "plan"}:
                raise ValueError("Unapproved model operation or actor")
            if not isinstance(request.get("rationale", ""), str) or len(request.get("rationale", "")) > 2000:
                raise ValueError("Rationale must be bounded text")
            if request.get("wait_condition") is not None and (not isinstance(request["wait_condition"], str) or len(request["wait_condition"]) > 500):
                raise ValueError("WAIT condition must be bounded text")
            check = {"operation_id": "validate", "opportunity_id": "validate", "actor": "agent:a3",
                "context_id": str(opp.context_id), "symbol": opp.symbol, **request}
            _, _, _, decision, _, detail = decisions._validate_request(check)
            ctx = db.get(DecisionContext, opp.context_id)
            if decision == "take":
                session = paper.regular_session(run.day, json.loads(run.calendar_json))
                plan = detail["plan"]
                expiry = decisions._utc(plan.get("expiry"), "expiry")
                if not session or expiry.replace(tzinfo=UTC).timestamp() > paper.watch_cutoff(session):
                    raise ValueError("Agent TAKE expiry exceeds the P0 watch cutoff")
                if plan.get("cost_model") != paper.COST or plan.get("freshness_limit_seconds") != paper.FRESHNESS_SECONDS:
                    raise ValueError("Agent TAKE must retain P0 costs and freshness")
                decisions._validate_take(opp.symbol, ctx.captured_at, json.loads(ctx.data_json), detail["plan"], now_utc())
            elif decision == "wait" and decisions._utc(detail["wait_expiry"], "wait_expiry") <= now_utc():
                raise ValueError("WAIT expiry must be future")
        for c in choices:
            choose(db, opps[c["opportunity_id"]], {k: v for k, v in c.items() if k != "opportunity_id"}, actor="agent:a3")
        call.status = "completed"
    except (ValueError, KeyError, TypeError) as exc:
        call.status = "invalid"
        call.error = str(exc)[:500]
    except Exception:
        call.status = "uncertain"
        call.error = "Model call failed or timed out; completion/cost may be unknown. No retry."
    call.finished_at = now_utc()
    db.add(call)
    db.commit()
    return call.status


def prepare(db, run, *, calendar, packet_loader, adapter=practice_agent.invoke):
    run.status = "preparing"
    db.add(run)
    db.commit()
    hours = calendar.hours(run.day)
    run.calendar_json = json.dumps(hours or {"status": "unavailable"})
    if run.mode == "scheduled" and now_utc() > run.deadline and hours and hours.get("status") == "open":
        run.result = "missed_deadline"
        run.error = "Scheduled preparation missed 09:00 ET; no provider/model call attempted. Explicit manual revision remains available."
    elif not hours or hours.get("status") != "open":
        run.result = "failed" if not hours else "no_session"
        run.error = "Calendar unavailable; no session assumed" if not hours else None
        if not hours:
            for opp in opportunities(db, run.id):
                packet = {"symbol": opp.symbol, "data_source": "unavailable", "recent_minute_bars": [],
                    "missing": ["Calendar unavailable; market session not verified"], "session_calendar": {"status": "unavailable"}}
                ctx, _ = decisions.freeze_context(db, f"a3:{opp.id}:context", opp.symbol, packet)
                opp.context_id = ctx.id
                db.add(opp)
            db.commit()
    else:
        for opp in opportunities(db, run.id):
            if opp.context_id:
                continue
            try:
                packet = packet_loader(opp.symbol)
            except Exception:
                packet = {"symbol": opp.symbol, "data_source": "unavailable", "recent_minute_bars": [], "missing": ["Provider unavailable"]}
            packet["session_calendar"] = hours
            ctx, _ = decisions.freeze_context(db, f"a3:{opp.id}:context", opp.symbol, jsonable_encoder(packet))
            opp.context_id = ctx.id
            db.add(opp)
            db.commit()
        run.status = "preparing"  # keep UI polling until adapter terminal
        db.add(run)
        db.commit()
        try:
            agent_status = run_agent(db, run, adapter=adapter)
            run.result = "completed" if agent_status in {"completed", "disabled"} else "failed"
            if agent_status == "completed":
                agent_records = [records(db, o).get("agent:a3") for o in opportunities(db, run.id)]
                if not any(r and r.decision == "take" for r in agent_records):
                    run.result = "no_setup"
        except ValueError as exc:
            run.result = "failed"
            run.error = str(exc)
        if not any(json.loads(db.get(DecisionContext, o.context_id).data_json)["price_facts"] for o in opportunities(db, run.id)):
            run.result = "failed"
            run.error = "Required market facts unavailable; WAIT/SKIP still available"
    sources = [{"url": f"/daily/{run.day}?practice_run={run.id}#practice-opportunity-{o.id}", "label": o.symbol + " frozen context", "formed_at": next((f["formed_at"] for f in reversed(json.loads(db.get(DecisionContext, o.context_id).data_json)["price_facts"])), None),
                "observed_at": iso(db.get(DecisionContext, o.context_id).captured_at)} for o in opportunities(db, run.id) if o.context_id]
    run.brief_json = json.dumps([
        {"title": "MARKET TAPE", "text": "Frozen price facts below; missing coverage is unavailable. Regular-session RVOL and ORB are unavailable before the open.", "sources": sources},
        {"title": "IMPORTANT NEWS", "text": "Unavailable: this adapter has no approved news/search source. No news conclusion inferred.", "sources": []},
        {"title": "SETUP BOARD", "text": "Five predeclared P0 opportunities. Commit your validated choice on each frozen context. Agent verdicts are withheld in independent mode.", "sources": sources}])
    run.finished_at = now_utc()
    run.late = run.late or run.finished_at > run.deadline
    run.status = "late" if run.late and run.result in {"completed", "no_setup", "missed_deadline"} else run.result
    db.add(run)
    db.commit()


def run_preparation_job(job_id):
    from app.database import engine
    from app.engine.analyzer import build_ticker_analysis
    from app.engine.chart_calendar import chart_calendar
    from app.engine.jobs import _finish_job
    with Session(engine) as db:
        run = db.exec(select(PracticeRun).where(PracticeRun.job_id == job_id)).one()
        if run.mode == "scheduled" and os.environ.get("PRACTICE_SCHEDULE_ENABLED") != "true":
            run.status = run.result = "failed"
            run.error = "Scheduled preparation disabled before execution"
            run.finished_at = now_utc()
            db.add(run)
            db.commit()
        else:
            prepare(db, run, calendar=chart_calendar, packet_loader=build_ticker_analysis)
    if run.result == "failed":
        from app.engine.jobs import _fail_job
        _fail_job(job_id, RuntimeError(run.error or "Practice preparation failed; inspect durable run"))
    else:
        _finish_job(job_id, 5, 5)
    return 5


def benchmark(day, hours, bars, split_info, *, now=None):
    """Shared outcome uses full coverage, never an actor's plan or fill."""
    now = now or now_utc()
    session = paper.regular_session(day, hours)
    result = {**BENCHMARK, "status": "unavailable", "return_pct": None,
              "observed_at": iso(now), "reason": "Calendar/session unavailable"}
    if session is None:
        return result
    if now.replace(tzinfo=UTC).timestamp() < session.close_at:
        result["reason"] = "Session not complete"
        return result
    if split_info.get("status") != "ok" or any(s["ex_date"] == day.isoformat() for s in split_info.get("splits", [])):
        result["reason"] = "Split coverage unavailable or session has a split"
        return result
    selected = {b["time"]: b for b in bars if session.open_at <= b["time"] < session.close_at}
    expected = set(range(session.open_at, session.close_at, 60))
    if set(selected) != expected:
        result["reason"] = "Missing regular-session minutes"
        result["covered_minutes"] = len(selected)
        result["expected_minutes"] = len(expected)
        return result
    import math
    if any(b.get("source") != "tradier" or not all(isinstance(b.get(k), (int, float)) and math.isfinite(b[k]) and b[k] > 0 for k in ("open", "high", "low", "close")) for b in selected.values()):
        result["reason"] = "Invalid source or price coverage"
        return result
    opening, closing = selected[session.open_at]["open"], selected[session.close_at - 60]["close"]
    return {**result, "status": "complete", "reason": None, "return_pct": 100 * (closing / opening - 1),
            "open": opening, "close": closing, "formed_at": iso(datetime.fromtimestamp(session.close_at, UTC).replace(tzinfo=None)),
            "covered_minutes": len(expected), "expected_minutes": len(expected)}


def collect_benchmarks(db, run, *, feed, splits):
    from app.engine.chart_math import normalize_bars
    hours = json.loads(run.calendar_json)
    if not paper.regular_session(run.day, hours):
        return
    if now_utc().replace(tzinfo=UTC).timestamp() < paper.regular_session(run.day, hours).close_at:
        return
    for opp in opportunities(db, run.id):
        if json.loads(opp.benchmark_json).get("status") == "complete":
            continue
        try:
            data, _, issue = feed.read("/v1/markets/timesales", {"symbol": opp.symbol, "interval": "1min", "session_filter": "all",
                "start": f"{run.day} 04:00", "end": f"{run.day} 20:00"}, 60)
            rows = (data.get("series") or {}).get("data") or []
            if issue:
                raise ValueError("Provider coverage unavailable")
            value = benchmark(run.day, hours, normalize_bars(rows if isinstance(rows, list) else [rows]), splits.get(opp.symbol))
        except Exception:
            value = {**BENCHMARK, "status": "unavailable", "reason": "Provider coverage unavailable", "return_pct": None}
        opp.benchmark_json = json.dumps(value)
        db.add(opp)
    db.commit()
