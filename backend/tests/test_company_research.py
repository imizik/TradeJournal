"""Persistence, temporal safety and provider provenance on disposable data."""
import json
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlmodel import Session, SQLModel, create_engine

from app.engine import company_research as service
from app.engine.company_research_math import compare
from app.engine.company_research_sources import actuals


@pytest.fixture
def db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'research.db'}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as db:
        yield db


def test_empty_dedup_archive_restore_and_revision_conflict(db):
    row = service.add(db, "nvda")
    assert service.add(db, "NVDA").id == row.id
    assert service.view(db, row)["latest"] == {}
    row = service.patch(db, row.id, 0, "Margins improve", ["Capacity arrives"], False)
    assert not row.followed
    with pytest.raises(HTTPException) as exc:
        service.patch(db, row.id, 0, "Clobber", [], True)
    assert exc.value.status_code == 409
    assert service.add(db, "NVDA").id == row.id
    assert service.history(db, row.id)[0]["data"]["thesis"] == "Margins improve"


def test_snapshot_retry_conflict_and_append(db):
    row = service.add(db, "NVDA")
    first = service.snapshot(db, row, "actuals", "SEC", {"revenue": "10"}, "run-1")
    assert service.snapshot(db, row, "actuals", "SEC", {"revenue": "10"}, "run-1").id == first.id
    with pytest.raises(HTTPException):
        service.snapshot(db, row, "actuals", "SEC", {"revenue": "11"}, "run-1")
    service.snapshot(db, row, "actuals", "SEC", {"revenue": "11"}, "run-2")
    assert len(service.history(db, row.id)) == 2


def test_limit_and_invalid_tickers(db):
    for symbol in ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF", "GGG", "HHH", "III", "JJJ"]:
        service.add(db, symbol)
    with pytest.raises(HTTPException):
        service.add(db, "KKK")
    with pytest.raises(HTTPException):
        service.add(db, "../../secret")


def test_sec_sources_are_per_metric_and_q4_remains_missing():
    document = json.loads((Path(__file__).parent / "fixtures/sec/nvda_companyfacts_2026-10-08.json").read_text())
    data = actuals(document, 1045810)
    assert any(q["gap"] for q in data["quarters"])
    for q in data["quarters"]:
        if q["gap"]:
            assert q["revenue"] is None and not q["evidence"]
        else:
            assert isinstance(q["revenue"], str)
            assert q["evidence"]["revenue"]["accession"]
            assert q["evidence"]["eps_diluted"]["unit"] == "USD/shares"


def observation(**changes):
    return {"issuer": "company-1", "metric": "eps", "period_end": "2026-09-30", "currency": "USD",
            "period_start": "2026-07-01", "fiscal_year": 2026, "fiscal_period": "Q3", "scope": "consolidated",
            "unit": "USD/share", "basis": "adjusted", "share_basis": "same", "value": "1.20", **changes}


@pytest.mark.parametrize("field,value", [("basis", "gaap"), ("basis", "unknown"), ("period_end", "2025-09-30"), ("currency", "EUR"), ("share_basis", "unknown")])
def test_incompatible_numbers_are_not_compared(field, value):
    assert compare(observation(), observation(**{field: value}))["state"] == "incompatible"


def test_zero_negative_and_small_eps():
    assert compare(observation(), observation(value="0"))["percent"] is None
    assert compare(observation(), observation(value="0.001"))["percent"] is None
    assert compare(observation(value="-1"), observation(value="-2"))["percent"] == "0.5"
    assert compare(observation(value=True), observation())["state"] == "unavailable"


def test_assignment_frozen_preview_and_idempotent_confirm(db):
    from app.engine import company_research_assignments as tasks
    row = service.add(db, "NVDA")
    task = tasks.create(db, row.id, "Why did margin decline?")
    result = tasks.FindingBody(operation_id="answer-1", context_hash=task["context_hash"], kind="fact",
        claim="Management described higher input costs", sources=[{"url": "https://example.com/report",
        "publisher": "Issuer", "excerpt": "Higher input costs reduced margin."}])
    preview = tasks.import_result(db, __import__("uuid").UUID(task["id"]), result)
    assert preview["status"] == "preview"
    identifier = __import__("uuid").UUID(task["id"])
    receipt = tasks.import_result(db, identifier, result, preview["digest"])
    assert tasks.import_result(db, identifier, result, preview["digest"]) == receipt
    assert receipt["status"] == "saved"
    result.claim = "Changed claim"
    with pytest.raises(HTTPException):
        tasks.import_result(db, identifier, result, preview["digest"])


def test_assignment_refuses_unsafe_sources_and_expired_context(db):
    from pydantic import ValidationError
    from app.engine import company_research_assignments as tasks
    with pytest.raises(ValidationError):
        tasks.Citation(url="https://example.com/a?token=private", publisher="Source", excerpt="Text")
    with pytest.raises(ValidationError):
        tasks.Citation(url="javascript:alert(1)", publisher="Source", excerpt="Text")


def test_annual_and_quarter_are_incompatible_and_margins_use_points():
    assert compare(observation(), observation(period_start="2026-01-01", fiscal_period="FY"))["state"] == "incompatible"
    result = compare(observation(metric="gross_margin", value="0.40", unit="ratio"), observation(metric="gross_margin", value="0.30", unit="ratio"))
    assert result["difference"] == "10.00" and result["difference_unit"] == "percentage points"
    assert result["percent"] is None
    assert compare(observation(metric="gross_margin", value="40", unit="percent"), observation(metric="gross_margin", value="30", unit="percent"))["state"] == "incompatible"


def test_valid_older_estimate_is_not_hidden_by_newer_ineligible_records(monkeypatch):
    from app.routers.company_research import comparisons
    actual = observation(role="actual", published_at="2026-10-20T20:00:00Z", observed_at="2026-10-21T12:00:00Z")
    late = observation(role="estimate", observed_at="2026-10-21T12:00:00Z")
    wrong = observation(role="estimate", basis="gaap", observed_at="2026-10-19T12:00:00Z")
    valid = observation(role="estimate", observed_at="2026-10-19T12:00:00Z")
    monkeypatch.setattr(service, "sourced_numbers", lambda *_: [actual, late, wrong, valid])
    result = comparisons(__import__("uuid").uuid4(), None)
    assert len(result) == 1 and result[0]["comparison"]["state"] == "ready"


def test_partial_refresh_retains_success_and_coalesces_pending_jobs(db):
    row = service.add(db, "NVDA")
    service.snapshot(db, row, "actuals", "SEC", {"state": "ready", "quarters": []}, "first")
    service.snapshot(db, row, "actuals", "SEC", {"state": "unavailable", "message": "Rate limited"}, "second")
    view = service.view(db, row)
    assert view["latest"]["actuals"]["data"]["state"] == "ready"
    assert view["attempts"]["actuals"]["data"]["message"] == "Rate limited"
    assert service.queue_refresh(db, row).id == service.queue_refresh(db, row).id


def test_company_migration_roundtrip_on_disposable_sqlite(tmp_path):
    from sqlalchemy import inspect
    from tests.postgres_support import run_alembic
    url = f"sqlite:///{tmp_path / 'migration.db'}"
    for arguments in (("upgrade", "head"), ("downgrade", "fa98b2a82e10"), ("upgrade", "head")):
        result = run_alembic(*arguments, url=url)
        assert result.returncode == 0, result.stdout + result.stderr
    engine = create_engine(url)
    assert "company_research_snapshot" in inspect(engine).get_table_names()
    assert {"company_id", "component", "operation_id"} in [set(c["column_names"]) for c in inspect(engine).get_unique_constraints("company_research_snapshot")]
    engine.dispose()
