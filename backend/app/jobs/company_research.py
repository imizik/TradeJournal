"""Explicit company-research operations; no scheduler starts on import.

python -m app.jobs.company_research --daily
python -m app.jobs.company_research --exchange --check-config /approved/config.json
python -m app.jobs.company_research --publish ASSIGNMENT --actor check_UUID --check-config /approved/config.json
"""
import argparse
import json
import os
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from sqlmodel import Session, select

from app.database import engine
from app.company_research_models import ResearchAssignment, ResearchCompany, ResearchFinding
from app.engine import company_research as store
from app.engine import company_research_assignments as tasks


def daily(db, day):
    """Opt-in finite enqueue pass. A successful daily run is never repeated implicitly."""
    if os.getenv("COMPANY_RESEARCH_DAILY_ENABLED") != "true":
        return []
    from app.models import JobRun
    from app.engine.job_runtime import submit_job
    queued = []
    for row in db.exec(select(ResearchCompany).where(ResearchCompany.followed.is_(True)).limit(10)).all():
        previous = db.exec(select(JobRun).where(JobRun.job_type == "company_research_refresh",
            JobRun.created_at >= datetime.fromisoformat(day) - timedelta(days=1)).limit(1000)).all()
        if any(json.loads(j.params_json).get("company_id") == str(row.id) and json.loads(j.params_json).get("scheduled_day") == day for j in previous):
            continue
        job = store.queue_refresh(db, row, scheduled_day=day)
        submit_job(job.id)
        queued.append(str(job.id))
    return queued


def publish(db, identifier, actor, config):
    import jo_briefing_exchange as files
    import company_research_exchange as exchange
    if not config.company_research_enabled or not any(p.id == actor and p.enabled for p in config.profiles):
        raise ValueError("Research must be explicitly enabled for a configured actor")
    row = tasks.get(db, identifier)
    from sqlalchemy import update
    if db.bind.dialect.name == "sqlite":
        db.execute(update(ResearchCompany).where(ResearchCompany.id == row.company_id).values(updated_at=ResearchCompany.updated_at))
    company = db.exec(select(ResearchCompany).where(ResearchCompany.id == row.company_id).with_for_update().execution_options(populate_existing=True)).one()
    if row.actor not in {"manual", actor} or row.status != "queued" or row.expires_at <= store.utc_now_naive() or not company.followed:
        raise ValueError("Assignment unavailable for publication")
    row.actor = actor
    db.add(row)
    db.flush()
    packet = tasks.packet(row)
    name = exchange.context_name(actor, identifier)
    try:
        files.write(config.market_watch_snapshots_dir, name, packet)
        db.commit()
    except Exception:
        db.rollback()
        (Path(config.market_watch_snapshots_dir) / name).unlink(missing_ok=True)
        raise
    return packet


def exchange_pass(db, config):
    import jo_briefing_exchange as files
    from company_research_common import FindingBody
    if not config.company_research_enabled:
        return {"saved": 0, "rejected": 0}
    root, outbox = config.market_watch_snapshots_dir, config.market_watch_outbox_dir
    allowed = {p.id for p in config.profiles if p.enabled}
    # Revoke published snapshots whose source assignment is no longer readable.
    for path in list(Path(root).glob("company-context-*.json"))[:100]:
        packet = files.read(root, path.name)
        row = db.get(ResearchAssignment, uuid.UUID(packet["id"]))
        if row is None or row.status != "queued" or row.actor not in allowed or row.expires_at <= store.utc_now_naive() or not store.company(db, row.company_id).followed:
            path.unlink()
    saved = rejected = 0
    pending = (p for p in Path(outbox).glob("company-request-*.json")
               if not (Path(root) / p.name.replace("company-request-", "company-receipt-")).exists())
    for path in list(pending)[:100]:
        data = files.read(outbox, path.name)
        actor, body = data["actor"], FindingBody.model_validate(data["payload"])
        key = files.operation_key(actor, body.operation_id)
        if path.name != f"company-request-{key}.json" or data["digest"] != files.digest(body.model_dump(mode="json")):
            raise ValueError("Sealed submission identity mismatch")
        receipt_name = f"company-receipt-{key}.json"
        if (Path(root) / receipt_name).exists():
            continue
        status = "rejected"
        try:
            identifier = uuid.UUID(data["assignment_id"])
            row = tasks.get(db, identifier)
            if row.actor != actor:
                raise ValueError("Wrong assignment actor")
            payload = body.model_dump(mode="json")
            hashed = store.digest(payload)
            prior = db.exec(select(ResearchFinding).where(ResearchFinding.assignment_id == identifier,
                                                        ResearchFinding.operation_id == body.operation_id)).first()
            if prior and (prior.digest != hashed or prior.actor != actor):
                raise ValueError("Operation conflict")
            if not prior:
                if actor not in allowed:
                    raise ValueError("Actor is no longer enabled")
                _, payload, hashed = tasks.validate(db, identifier, body)
                db.add(ResearchFinding(company_id=row.company_id, assignment_id=identifier, operation_id=body.operation_id,
                    actor=actor, payload_json=store.canonical(payload), digest=hashed))
                row.status = "imported"
                db.add(row)
                db.commit()
            status = "saved"
            saved += 1
        except (ValueError, tasks.HTTPException):
            db.rollback()
            rejected += 1
        files.write(root, receipt_name, {"actor": actor, "operation_id": body.operation_id, "status": status,
                                      "app_saved": status == "saved", "digest": data["digest"]})
    return {"saved": saved, "rejected": rejected}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--daily", action="store_true")
    group.add_argument("--exchange", action="store_true")
    group.add_argument("--publish", type=uuid.UUID)
    parser.add_argument("--actor")
    parser.add_argument("--check-config", default=os.getenv("COMPANY_RESEARCH_CHECK_CONFIG"))
    args = parser.parse_args()
    if args.daily and os.getenv("COMPANY_RESEARCH_DAILY_ENABLED") != "true":
        print(json.dumps({"completed": True, "count": 0, "enabled": False}))
        return
    from app.engine.job_runtime import _lock, lock_directory
    # One host owns the database and exchange; serialize explicit operation passes.
    with _lock(lock_directory(), "company-research-operations") as acquired:
        if not acquired:
            print(json.dumps({"completed": False, "busy": True}))
            return
        execute(args, parser)


def execute(args, parser):
    with Session(engine) as db:
        if args.daily:
            from app.engine.chart_math import ET
            result = daily(db, datetime.now(ET).date().isoformat())
        else:
            if not args.check_config:
                parser.error("--check-config is required")
            from cloud_mcp_check_common import read_config
            config = read_config(args.check_config)
            result = publish(db, args.publish, args.actor, config) if args.publish else exchange_pass(db, config)
        # Print counts only; frozen company/thesis contexts belong in the protected exchange.
        print(json.dumps({"completed": True, "count": len(result)}))


if __name__ == "__main__":
    main()
