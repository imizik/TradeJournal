"""Company research isolation and a real tool-to-outbox-to-app receipt, with invented data."""
import uuid
from datetime import datetime, timezone

import pytest
from sqlmodel import Session, SQLModel, create_engine

from app.engine import company_research as store
from app.engine import company_research_assignments as tasks
from app.jobs.company_research import publish, exchange_pass, daily
from cloud_mcp_check_common import read_config
from tests.test_cloud_mcp_check import harness, signing_key, call, RECEIPT  # noqa: F401


def test_scoped_roundtrip_and_owner_acceptance(harness, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setattr(tasks, "utc_now_naive", lambda: RECEIPT.replace(tzinfo=None))
    monkeypatch.setattr(store, "utc_now_naive", lambda: RECEIPT.replace(tzinfo=None))
    root, outbox = tmp_path / "snapshots", tmp_path / "outbox"
    root.mkdir()
    outbox.mkdir()
    harness.configure(company_research_enabled=True, market_watch_snapshots_dir=str(root), market_watch_outbox_dir=str(outbox))
    config = read_config(harness.config_path)
    actor = config.profiles[0].id
    db_engine = create_engine(f"sqlite:///{tmp_path / 'companies.db'}")
    SQLModel.metadata.create_all(db_engine)
    with Session(db_engine) as db:
        company = store.add(db, "NVDA")
        assignment = tasks.create(db, company.id, "Did revenue meet expectations?")
        identifier = uuid.UUID(assignment["id"])
        publish(db, identifier, actor, config)
        token = harness.token(scope="check:read company-research:read company-research:submit")
        from starlette.testclient import TestClient
        with TestClient(harness.server().streamable_http_app()) as client:
            assert call(client, "company_research_context", {"assignment_id": assignment["id"]}, harness.token())["isError"]
            result = call(client, "company_research_context", {"assignment_id": assignment["id"]}, token)
            assert not result.get("isError"), result
            body = {"operation_id": "research-1", "context_hash": assignment["context_hash"], "kind": "fact",
                    "claim": "The company reported revenue of $12 million.", "sources": [{"url": "https://example.com/earnings",
                    "publisher": "Issuer", "excerpt": "Quarterly revenue was $12 million."}], "numbers": [{"role": "actual",
                    "metric": "revenue", "period_start": "2026-07-01", "period_end": "2026-09-30", "fiscal_year": 2026, "fiscal_period": "Q3", "scope": "consolidated", "basis": "gaap", "currency": "USD",
                    "unit": "USD", "value": "12000000", "source_index": 0, "share_basis": "not applicable"}]}
            submitted = call(client, "company_research_submit", {"assignment_id": assignment["id"], "result": body}, token)
            assert not submitted.get("isError"), submitted
            assert submitted["structuredContent"]["status"] == "pending_import"
            assert exchange_pass(db, config) == {"saved": 1, "rejected": 0}
            receipt = call(client, "company_research_receipt", {"operation_id": "research-1"}, token)
            assert receipt["structuredContent"]["app_saved"]
            assert exchange_pass(db, config) == {"saved": 0, "rejected": 0}
            retry = call(client, "company_research_submit", {"assignment_id": assignment["id"], "result": body}, token)
            assert retry["structuredContent"]["app_saved"]
        from app.company_research_models import ResearchFinding
        from sqlmodel import select
        finding = db.exec(select(ResearchFinding).where(ResearchFinding.company_id == company.id)).one()
        assert finding.actor == actor and finding.disposition == "proposed"
        tasks.disposition(db, finding.id, finding.digest, "accepted")
        assert any(r["component"] == "sourced_numbers" for r in store.history(db, company.id))


def test_context_wrong_actor_expiry_and_daily_off(tmp_path, monkeypatch):
    from company_research_exchange import context, context_name
    import jo_briefing_exchange as files
    actor = "check_" + str(uuid.uuid4())
    other = "check_" + str(uuid.uuid4())
    identifier = str(uuid.uuid4())
    root = tmp_path / "context"
    root.mkdir()
    files.write(root, context_name(actor, identifier), {"id": identifier, "actor": actor, "status": "queued", "expires_at": "2026-10-29T12:00:00Z"})
    with pytest.raises(ValueError):
        context(root, actor, identifier, datetime(2026, 10, 30, tzinfo=timezone.utc))
    with pytest.raises(FileNotFoundError):
        context(root, other, identifier, datetime(2026, 10, 30, tzinfo=timezone.utc))
    monkeypatch.delenv("COMPANY_RESEARCH_DAILY_ENABLED", raising=False)
    assert daily(None, "2026-10-30") == []


def test_receipt_recovers_committed_import_after_archive(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from app.company_research_models import ResearchAssignment
    import company_research_exchange as exchange
    import jo_briefing_exchange as files
    root, outbox = tmp_path / "snapshots", tmp_path / "outbox"
    root.mkdir()
    outbox.mkdir()
    actor = "check_" + str(uuid.uuid4())
    config = SimpleNamespace(company_research_enabled=True, profiles=[SimpleNamespace(id=actor, enabled=True)],
                             market_watch_snapshots_dir=str(root), market_watch_outbox_dir=str(outbox))
    engine = create_engine(f"sqlite:///{tmp_path / 'recovery.db'}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as db:
        company = store.add(db, "NVDA")
        assignment = tasks.create(db, company.id, "Inspect the report")
        identifier = uuid.UUID(assignment["id"])
        publish(db, identifier, actor, config)
        body = {"operation_id": "recovery-1", "context_hash": assignment["context_hash"], "kind": "fact",
                "claim": "Management reported a change", "sources": [{"url": "https://example.com/report",
                "publisher": "Issuer", "excerpt": "Reported change"}]}
        exchange.submit(str(root), str(outbox), actor, identifier, body, datetime.now(timezone.utc))
        original = files.write
        def interrupted(directory, name, value):
            if name.startswith("company-receipt-"):
                raise OSError("Interrupted after database commit")
            original(directory, name, value)
        monkeypatch.setattr(files, "write", interrupted)
        with pytest.raises(OSError):
            exchange_pass(db, config)
        row = db.get(ResearchAssignment, identifier)
        assert row.status == "imported"
        store.patch(db, company.id, company.revision, "", [], False)
        monkeypatch.setattr(files, "write", original)
        assert exchange_pass(db, config)["saved"] == 1
        assert exchange.receipt(str(root), actor, "recovery-1")["app_saved"]


def test_daily_schedule_identity_survives_interruption_before_dispatch(tmp_path, monkeypatch):
    import json
    from sqlmodel import select
    from app.models import JobRun
    from app.engine import job_runtime
    engine = create_engine(f"sqlite:///{tmp_path / 'daily.db'}")
    SQLModel.metadata.create_all(engine)
    monkeypatch.setenv("COMPANY_RESEARCH_DAILY_ENABLED", "true")
    def interrupted(_):
        raise RuntimeError("Stopped before dispatch")
    monkeypatch.setattr(job_runtime, "submit_job", interrupted)
    with Session(engine) as db:
        store.add(db, "NVDA")
        with pytest.raises(RuntimeError):
            daily(db, "2026-10-30")
        job = db.exec(select(JobRun)).one()
        assert json.loads(job.params_json)["scheduled_day"] == "2026-10-30"
        job.status = "succeeded"  # an external worker could have completed the committed job
        db.add(job)
        db.commit()
        assert daily(db, "2026-10-30") == []
        assert len(db.exec(select(JobRun)).all()) == 1
