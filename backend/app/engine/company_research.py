"""Stored company research. Reads never fetch providers or invoke a model."""
import hashlib
import json
import re
import uuid

from fastapi import HTTPException
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.company_research_models import ResearchCompany, ResearchSnapshot, utc_now_naive


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def company(db, identifier):
    row = db.get(ResearchCompany, identifier)
    if row is None:
        raise HTTPException(404, "Company not found")
    return row


def add(db, symbol):
    symbol = symbol.strip().upper()
    if not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,14}", symbol):
        raise HTTPException(422, "Enter a US company ticker")
    # Serialize limit checking on Postgres, including an initially empty list.
    if db.bind.dialect.name == "postgresql":
        from sqlalchemy import text
        db.execute(text("SELECT pg_advisory_xact_lock(741963852)"))
    if db.bind.dialect.name == "sqlite":
        db.execute(update(ResearchCompany).where(ResearchCompany.symbol == symbol).values(updated_at=ResearchCompany.updated_at))
    existing = db.exec(select(ResearchCompany).where(ResearchCompany.symbol == symbol).with_for_update().execution_options(populate_existing=True)).first()
    if existing and existing.followed:
        return existing
    rows = db.exec(select(ResearchCompany).where(ResearchCompany.followed.is_(True))).all()
    if len(rows) >= 10:
        raise HTTPException(409, "Follow at most 10 companies")
    if existing:
        existing.followed = True
        existing.revision += 1
        row = existing
    else:
        row = ResearchCompany(symbol=symbol)
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        row = db.exec(select(ResearchCompany).where(ResearchCompany.symbol == symbol)).first()
        if row is None:
            raise
    db.refresh(row)
    return row


def snapshot(db, row, component, provider, payload, operation_id):
    previous = db.exec(select(ResearchSnapshot).where(
        ResearchSnapshot.company_id == row.id, ResearchSnapshot.component == component,
        ResearchSnapshot.operation_id == operation_id)).first()
    hashed = digest(payload)
    if previous:
        if previous.digest != hashed:
            raise HTTPException(409, "Operation already saved with different content")
        return previous
    saved = ResearchSnapshot(company_id=row.id, component=component, provider=provider,
                             operation_id=operation_id, state=payload.get("state", "ready"), payload_json=canonical(payload), digest=hashed)
    db.add(saved)
    db.commit()
    db.refresh(saved)
    return saved


def patch(db, identifier, revision, thesis, assumptions, followed):
    row = company(db, identifier)
    if row.revision != revision:
        raise HTTPException(409, "Company changed in another tab. Reload before saving; keep your draft.")
    if followed and not row.followed:
        raise HTTPException(422, "Restore using Add company so the coverage limit is checked")
    prior = {"thesis": row.thesis, "assumptions": json.loads(row.assumptions_json)}
    result = db.execute(update(ResearchCompany).where(
        ResearchCompany.id == identifier, ResearchCompany.revision == revision).values(
            thesis=thesis, assumptions_json=canonical(assumptions), followed=followed,
            revision=revision + 1, updated_at=utc_now_naive()))
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(409, "Company changed in another tab. Reload before saving; keep your draft.")
    # Thesis revision is committed atomically with its historical record.
    payload = {"previous": prior, "thesis": thesis, "assumptions": assumptions, "revision": revision + 1}
    db.add(ResearchSnapshot(company_id=identifier, component="thesis", provider="owner",
                           operation_id=f"revision-{revision + 1}", payload_json=canonical(payload), digest=digest(payload)))
    db.commit()
    db.expire_all()
    return company(db, identifier)


def history(db, identifier, limit=100, offset=0):
    company(db, identifier)
    rows = db.exec(select(ResearchSnapshot).where(ResearchSnapshot.company_id == identifier).order_by(
        ResearchSnapshot.observed_at.desc(), ResearchSnapshot.id.desc()).offset(offset).limit(limit)).all()
    return [{"id": str(r.id), "component": r.component, "provider": r.provider,
             "observed_at": r.observed_at.isoformat() + "Z", "data": json.loads(r.payload_json)} for r in rows]


def view(db, row):
    latest, attempts = {}, {}
    for component in ("actuals", "analysts", "calendar", "thesis"):
        base = select(ResearchSnapshot).where(ResearchSnapshot.company_id == row.id, ResearchSnapshot.component == component)
        attempt = db.exec(base.order_by(ResearchSnapshot.observed_at.desc(), ResearchSnapshot.id.desc()).limit(1)).first()
        success = db.exec(base.where(ResearchSnapshot.state != "unavailable").order_by(ResearchSnapshot.observed_at.desc(), ResearchSnapshot.id.desc()).limit(1)).first()
        def entry(r):
            return {"id": str(r.id), "component": r.component, "provider": r.provider,
                    "observed_at": r.observed_at.isoformat() + "Z", "data": json.loads(r.payload_json)}
        if attempt:
            attempts[component] = entry(attempt)
            latest[component] = entry(success or attempt)
    actual_history = db.exec(select(ResearchSnapshot).where(ResearchSnapshot.company_id == row.id,
        ResearchSnapshot.component == "actuals", ResearchSnapshot.state == "ready").order_by(
            ResearchSnapshot.observed_at.desc()).limit(2)).all()
    changes = []
    if len(actual_history) == 2:
        before = {q["end"]: q for q in json.loads(actual_history[1].payload_json).get("quarters", [])}
        for q in json.loads(actual_history[0].payload_json).get("quarters", []):
            if q.get("gap"):
                continue
            if q["end"] not in before:
                changes.append({"period_end": q["end"], "metric": "new_quarter", "before": None, "after": None})
                continue
            for metric in ("revenue", "eps_diluted", "gross_margin", "operating_margin"):
                if q.get(metric) != before[q["end"]].get(metric):
                    changes.append({"period_end": q["end"], "metric": metric, "before": before[q["end"]].get(metric), "after": q.get(metric)})
    return {"id": str(row.id), "symbol": row.symbol, "name": row.name, "cik": row.cik,
            "followed": row.followed, "revision": row.revision, "thesis": row.thesis,
            "assumptions": json.loads(row.assumptions_json), "latest": latest, "attempts": attempts,
            "changes": changes, "baseline": len(actual_history) < 2}


def sourced_numbers(db, identifier):
    company(db, identifier)
    rows = db.exec(select(ResearchSnapshot).where(ResearchSnapshot.company_id == identifier,
        ResearchSnapshot.component == "sourced_numbers").order_by(ResearchSnapshot.observed_at.desc()).limit(100)).all()
    out = []
    for row in rows:
        payload = json.loads(row.payload_json)
        for i, number in enumerate(payload["numbers"]):
            source = payload["sources"][number["source_index"]]
            out.append({**number, "id": f"{row.id}:{i}", "issuer": str(identifier), "observed_at": row.observed_at.isoformat() + "Z",
                        "published_at": source.get("published_at"), "source": source, "origin": payload["origin"]})
    return out


def queue_refresh(db, row):
    from app.models import JobRun
    from app.engine.jobs import create_job
    if not row.followed:
        raise HTTPException(409, "Restore this company before refreshing")
    db.execute(update(ResearchCompany).where(ResearchCompany.id == row.id).values(updated_at=ResearchCompany.updated_at))
    pending = db.exec(select(JobRun).where(JobRun.job_type == "company_research_refresh",
                                         JobRun.status.in_(["queued", "running"]))).all()
    for job in pending:
        if json.loads(job.params_json).get("company_id") == str(row.id):
            return job
    return create_job(db, "company_research_refresh", {"company_id": str(row.id)}, total=1)


def run_refresh(job_id):
    from app.database import engine
    from app.models import JobRun
    from app.engine.company_research_sources import collect
    with Session(engine) as db:
        job = db.get(JobRun, job_id)
        row = company(db, uuid.UUID(json.loads(job.params_json)["company_id"]))
        identifier, symbol, followed = row.id, row.symbol, row.followed
    # Network requests run outside write transactions. Each component survives a partial failure.
    if followed:
        for component, provider, data in collect(symbol):
            with Session(engine) as db:
                row = company(db, identifier)
                if not row.followed:
                    break
                if component == "actuals" and data.get("cik"):
                    if row.cik and row.cik != data["cik"]:
                        raise ValueError("Issuer identity changed; owner investigation required")
                    row.cik, row.name = data["cik"], data.get("entity") or row.name
                    db.add(row)
                snapshot(db, row, component, provider, data, str(job_id))
    with Session(engine) as db:
        job = db.get(JobRun, job_id)
        job.status, job.phase, job.done = "succeeded", "complete", 1
        job.current = "Checked available sources" if followed else "Company no longer followed"
        job.finished_at = job.updated_at = utc_now_naive()
        db.add(job)
        db.commit()
    return 0
