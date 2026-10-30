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
