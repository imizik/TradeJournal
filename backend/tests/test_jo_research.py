"""Jo's research role: the Check context and submit tools, the app importer, the red-team request route and the
publication pass. Generated tokens, disposable directories and the pinned test database only; no network."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlmodel import Session, delete, select

from app.ai import copilot_tools
from app.database import engine, get_session
from app.engine import copilot_investigations as inv
from app.engine import jo_research
from app.models import CopilotInvestigation, JoRedTeamRequest, JoResearchImport
from app.routers import copilot_plans as plan_routes
from cloud_mcp_check_common import read_config
import jo_briefing_exchange as briefing_exchange
import jo_research_exchange as exchange
from tests.test_cloud_mcp_check import harness, signing_key, call, rpc, RECEIPT  # noqa: F401

SCOPES = "check:read jo:read jo:submit"
SECRET = "COPILOT-REASONING-SENTINEL"
SOURCE = {"url": "https://www.reuters.com/markets/nbis-capacity", "publisher": "Reuters", "published_at": "2026-10-09"}


@pytest.fixture(autouse=True)
def clean():
    with Session(engine) as db:
        for table in (JoResearchImport, JoRedTeamRequest, CopilotInvestigation):
            db.exec(delete(table))
        db.commit()
    yield


@pytest.fixture
def check(harness, tmp_path):  # noqa: F811
    snapshots, outbox = tmp_path / "snapshots", tmp_path / "outbox"
    snapshots.mkdir()
    outbox.mkdir()
    harness.configure(jo_briefing_enabled=True, market_watch_snapshots_dir=str(snapshots), market_watch_outbox_dir=str(outbox))
    config = read_config(harness.config_path)
    return harness, config, config.profiles[0].id


def plan_thread(confirmed=True) -> tuple[str, str]:
    """A saved copilot answer with one trade plan card; its text carries the copilot's reasoning (``SECRET``)."""
    card = {"id": "plan-1", "kind": "trade_plan", "symbol": "NBIS", "direction": "long", "instrument": "calls",
            "thesis": "Capacity deal re-rates the stock", "entry_trigger": {"condition": "crosses", "price": 95.5},
            "invalidation": {"condition": "closes_beyond", "price": 90.0, "interval": "5m"}, "contract": "Nov 100C"}
    if confirmed:
        card["outcome"] = {"state": "confirmed", "fields": {"thesis": "Capacity deal re-rates NBIS", "entry": "95.50",
                                                            "invalidation": "90", "contract": "Nov 100C", "time_stop": "Friday close"}}
    saved = inv.create(inv.InvestigationFields(title="NBIS plan", symbol="NBIS", transcript=[
        {"role": "user", "content": "Plan NBIS?"},
        {"role": "assistant", "content": f"Verdict: Draft — Plan the breakout.\nRead: Thesis holds · Timing early · Contract fits\n{SECRET}",
         "proposals": [card]}]))
    return saved["id"], "plan-1"


def research(operation_id="nbis-dossier-2026-10-09", **changes):
    return {"operation_id": operation_id, "kind": "dossier", "symbols": ["NBIS"], "title": "NBIS: capacity story intact",
            "body": "Capacity deal confirmed by two outlets.\n\nRisk: dilution.", "sources": [SOURCE],
            "as_of": "2026-10-09T14:00:00Z", **changes}


def result(client, name, args, token):
    value = call(client, name, args, token)
    assert not value.get("isError"), value
    return value["structuredContent"]


def keyed(actor, operation_id):
    return briefing_exchange.operation_key(actor, operation_id)


# --------------------------------------------------------------------------- Check tools

def test_tools_scopes_validation_idempotency_and_sealed_output(check):
    h, config, actor = check
    token = h.token(scope=SCOPES)
    outbox = Path(config.market_watch_outbox_dir)
    with TestClient(h.server().streamable_http_app()) as client:
        tools = {t["name"]: t for t in rpc(client, "", {}, token, "tools/list").json()["result"]["tools"]}
        assert tools["jo_research_context"]["securitySchemes"][0]["scopes"] == ["check:read", "jo:read"]
        assert tools["jo_research_submit"]["securitySchemes"][0]["scopes"] == SCOPES.split()
        # Read scope alone cannot submit; no read scope at all cannot read.
        assert call(client, "jo_research_submit", research(), h.token(scope="check:read jo:read"))["isError"]
        assert call(client, "jo_research_context", {"kind": "dossier"}, h.token())["isError"]
        missing = call(client, "jo_research_context", {"kind": "dossier"}, token)
        assert missing["isError"] and "[dossier_not_published]" in missing["content"][0]["text"]
        # A dossier needs sources and symbols; request_id belongs to red_team only; bounded body.
        for bad in (research(sources=[]), research(symbols=[]), research(request_id=str(uuid4())),
                    research(kind="red_team"), research(body="x" * 12_001), research(as_of="2026-10-10T14:00:00Z"),
                    research(sources=[{**SOURCE, "url": "ftp://example.com/x"}]), research(symbols=["NBIS", "NBIS"])):
            assert call(client, "jo_research_submit", bad, token)["isError"], bad
        assert not list(outbox.iterdir())
        # An audit or narrative may cite nothing; a red team must name a pending request.
        assert result(client, "jo_research_submit", research("audit-1", kind="audit", symbols=[], sources=[]), token)["status"] == "pending_import"
        refused = call(client, "jo_research_submit", research("rt-1", kind="red_team", request_id=str(uuid4())), token)
        assert refused["isError"] and "no_pending_request" in refused["content"][0]["text"]
        first = result(client, "jo_research_submit", research(), token)
        assert first["status"] == "pending_import" and not first["app_saved"] and first["kind"] == "dossier"
        assert result(client, "jo_research_submit", research(), token) == first
        assert call(client, "jo_research_submit", research(title="Changed"), token)["isError"]
    sealed = json.loads((outbox / exchange.request_name(keyed(actor, "nbis-dossier-2026-10-09"))).read_text())
    assert sealed["schema_version"] == "jo-research-submission-v1" and sealed["profile_id"] == actor
    assert sealed["body_sha256"] == briefing_exchange.digest(sealed["body"])
    assert sealed["body"]["sources"] == [SOURCE] and sealed["body"]["request_id"] is None
    assert not h.requests


def test_disabled_catalog_hides_research_tools(check):
    h, _, _ = check
    h.configure(jo_briefing_enabled=False)
    with TestClient(h.server().streamable_http_app()) as client:
        tools = rpc(client, "", {}, h.token(), "tools/list").json()["result"]["tools"]
    assert not any(t["name"].startswith("jo_research") for t in tools)


def test_context_newest_unexpired_and_identity_checked(check):
    _, config, actor = check
    snapshots = config.market_watch_snapshots_dir
    jo_research.publish(config, actor, "audit", {"n": 1}, RECEIPT - timedelta(hours=2))
    jo_research.publish(config, actor, "audit", {"n": 2}, RECEIPT - timedelta(hours=1))
    jo_research.publish(config, actor, "audit", {"n": 3}, RECEIPT + timedelta(hours=1))  # not yet published at RECEIPT
    found = exchange.context(snapshots, actor, "audit", RECEIPT)
    assert found["data"] == {"n": 2} and found["kind"] == "audit" and found["labels"] == exchange.LABELS
    with pytest.raises(ValueError, match="expired"):
        exchange.context(snapshots, actor, "audit", RECEIPT + timedelta(hours=30))
    with pytest.raises(FileNotFoundError):
        exchange.context(snapshots, actor, "dossier", RECEIPT)
    other = "check_" + str(uuid4())
    with pytest.raises(FileNotFoundError):
        exchange.context(snapshots, other, "audit", RECEIPT)


# --------------------------------------------------------------------------- red team, end to end

def test_red_team_request_context_answer_and_card(check, monkeypatch):
    h, config, actor = check
    investigation_id, proposal_id = plan_thread()
    monkeypatch.setattr(plan_routes.copilot, "settings", lambda: SimpleNamespace(enabled=True))
    app = FastAPI()
    app.include_router(plan_routes.router, prefix="/copilot")

    def session():
        with Session(engine) as db:
            yield db
    app.dependency_overrides[get_session] = session
    with TestClient(app) as lab:
        asked = lab.post(f"/copilot/plans/{investigation_id}/red-team", json={"proposal_id": proposal_id})
        assert asked.status_code == 201 and asked.json()["status"] == "pending" and asked.json()["answer"] is None
        again = lab.post(f"/copilot/plans/{investigation_id}/red-team", json={"proposal_id": proposal_id})
        assert again.status_code == 200 and again.json()["request_id"] == asked.json()["request_id"]
        assert lab.post(f"/copilot/plans/{investigation_id}/red-team", json={"proposal_id": "nope"}).status_code == 404
        assert lab.post(f"/copilot/plans/{uuid4()}/red-team", json={"proposal_id": proposal_id}).status_code == 404
        unconfirmed, card = plan_thread(confirmed=False)
        assert lab.post(f"/copilot/plans/{unconfirmed}/red-team", json={"proposal_id": card}).status_code == 409
    request_id = asked.json()["request_id"]

    with Session(engine) as db:
        jo_research.publish(config, actor, "red_team", jo_research.red_team_context(db), RECEIPT - timedelta(minutes=5))
    token = h.token(scope=SCOPES)
    with TestClient(h.server().streamable_http_app()) as client:
        context = result(client, "jo_research_context", {"kind": "red_team"}, token)
        row = context["data"]["requests"][0]
        assert row["request_id"] == request_id and row["thesis"] == "Capacity deal re-rates NBIS"
        assert row["entry"] == "95.50 (crosses)" and row["invalidation"] == "90 (closes_beyond 5m)"
        assert SECRET not in json.dumps(context) and "Verdict" not in json.dumps(context)
        answer = research("rt-nbis", kind="red_team", request_id=request_id, symbols=[], title="Dilution risk is underpriced",
                          body="The case against: a secondary is likely.\n\nDetails.")
        assert result(client, "jo_research_submit", answer, token)["status"] == "pending_import"
        with Session(engine) as db:
            saved = jo_research.import_submission(db, config, actor, keyed(actor, "rt-nbis"), RECEIPT + timedelta(seconds=5))
        assert saved["status"] == "saved" and saved["app_saved"]
        assert result(client, "jo_research_submit", answer, token) == saved
    with Session(engine) as db:
        request = db.get(JoRedTeamRequest, UUID(request_id))
        assert request.status == "answered" and str(request.answer_investigation_id) == saved["record_id"]
        record = inv.get(saved["record_id"], session=db)
        assert record["source"] == "jo" and record["symbol"] == "NBIS" and record["title"] == "Jo red team · NBIS · Oct 9"
        # Answered: the red-team list no longer offers it.
        assert jo_research.red_team_context(db)["requests"] == []
    with TestClient(app) as lab:
        shown = lab.get(f"/copilot/plans/{investigation_id}/red-team").json()["requests"]
    assert shown[0]["status"] == "answered" and shown[0]["answer"]["title"] == "Dilution risk is underpriced"
    assert shown[0]["answer"]["body"].startswith("The case against")
    # A second answer to the same request is rejected on import, not saved twice.
    with Session(engine) as db:
        briefing_exchange.write(config.market_watch_outbox_dir, exchange.request_name(keyed(actor, "rt-again")),
            exchange.Submission(profile_id=actor, operation_id="rt-again", received_at=RECEIPT,
                                body=(body := exchange.validate_body({**answer, "operation_id": "rt-again"}, RECEIPT)),
                                body_sha256=briefing_exchange.digest(body)).model_dump(mode="json"))
        late = jo_research.import_submission(db, config, actor, keyed(actor, "rt-again"), RECEIPT + timedelta(seconds=9))
        assert late["status"] == "rejected" and not late["app_saved"]
        assert len(db.exec(select(CopilotInvestigation).where(CopilotInvestigation.source == "jo")).all()) == 1


# --------------------------------------------------------------------------- importer

def test_dossier_import_record_shape_and_saved_research(check):
    _, config, actor = check
    exchange.submit(config.market_watch_snapshots_dir, config.market_watch_outbox_dir, actor,
                    research(symbols=["NBIS", "CRWV"]), RECEIPT)
    with Session(engine) as db:
        receipt = jo_research.import_submission(db, config, actor, keyed(actor, "nbis-dossier-2026-10-09"), RECEIPT)
        record = inv.get(receipt["record_id"], session=db)
    assert receipt["status"] == "saved" and "body" not in json.dumps(receipt)
    assert record["source"] == "jo" and record["title"] == "Jo dossier · NBIS CRWV · Oct 9"
    assert record["conclusion"] == "NBIS: capacity story intact" and record["symbol"] == "NBIS"
    assert record["findings"]["summary"] == "Capacity deal confirmed by two outlets."
    assert record["findings"]["citations"] == [SOURCE] and record["findings"]["evidence_at"].startswith("2026-10-09T14:00")
    # Jo's text is a finding (a tool result for the copilot), never an answer a follow-up would replay as the copilot's.
    assert record["findings"]["report"] == research()["body"]
    # Closed: the thesis watch, the research queue's reassessments and the desk's threads read open records only.
    assert record["status"] == "closed"
    from app.engine import thesis_watch
    with Session(engine) as db:
        assert not [w for w in thesis_watch.watched_set(db) if "investigation" in w.reasons]  # Jo never pings
    assert [m["role"] for m in record["transcript"]] == ["user"]
    seen = copilot_tools.saved_research("NBIS")["items"]
    assert seen[0]["source"] == "jo" and seen[0]["findings"]["citations"][0]["publisher"] == "Reuters"


def test_import_recovers_after_receipt_write_failure(check, monkeypatch):
    _, config, actor = check
    exchange.submit(config.market_watch_snapshots_dir, config.market_watch_outbox_dir, actor, research(), RECEIPT)
    key = keyed(actor, "nbis-dossier-2026-10-09")
    write = briefing_exchange.write

    def fail(*args):
        raise OSError("simulated export failure")
    monkeypatch.setattr(briefing_exchange, "write", fail)
    with Session(engine) as db, pytest.raises(OSError):
        jo_research.import_submission(db, config, actor, key, RECEIPT)
    monkeypatch.setattr(briefing_exchange, "write", write)
    with Session(engine) as db:
        receipt = jo_research.import_submission(db, config, actor, key, RECEIPT + timedelta(minutes=1))
        assert receipt["status"] == "saved"
        assert len(db.exec(select(CopilotInvestigation)).all()) == 1


def test_tampered_submission_rejected(check):
    _, config, actor = check
    exchange.submit(config.market_watch_snapshots_dir, config.market_watch_outbox_dir, actor, research(), RECEIPT)
    key = keyed(actor, "nbis-dossier-2026-10-09")
    path = Path(config.market_watch_outbox_dir) / exchange.request_name(key)
    sealed = json.loads(path.read_text())
    sealed["body"]["body"] = "Rewritten after sealing"
    path.write_text(json.dumps(sealed))
    with Session(engine) as db:
        assert jo_research.import_submission(db, config, actor, key, RECEIPT)["status"] == "rejected"
        assert not db.exec(select(CopilotInvestigation)).all()


# --------------------------------------------------------------------------- contexts and the pass

def test_audit_context_strips_ids_and_answer_text(check, monkeypatch):
    plan_thread()
    from app.ai import copilot_review
    monkeypatch.setattr(copilot_review, "week_review", lambda week, session=None: {
        "state": "ok", "totals": {"trades": 3, "pnl_usd": 12.5, "pnl_on_premium_pct": 4.1, "accounts": ["Roth IRA"]},
        "alerts": {"by_kind": {"give_back": 2}, "then": {"held": 2}, "rows": [{"trade_id": "t", "thread": "x", "kind": "give_back"}]}})
    with Session(engine) as db:
        audit = jo_research.audit_context(db, datetime.now(timezone.utc))
    plan = audit["plans"][0]
    assert plan["verdict"] == "Verdict: Draft — Plan the breakout." and plan["read"].startswith("Read: Thesis holds")
    assert plan["card"] == "confirmed" and UUID(plan["plan_id"])
    assert audit["verdict_counts"] == {"Draft": 1}
    assert audit["week_review"]["alerts"]["rows"] == [{"kind": "give_back"}]
    assert audit["week_review"]["totals"] == {"trades": 3, "pnl_on_premium_pct": 4.1}  # no dollars, no account names
    assert SECRET not in json.dumps(audit)


def test_dossier_context_held_without_sizes_in_approved_accounts_only(check):
    from app.models import Account, Trade
    with Session(engine) as db:
        account = Account(name="Roth", type="roth_ira", last4="0001", broker="robinhood")
        other = Account(name="Individual", type="individual", last4="0002", broker="robinhood")
        db.add_all([account, other])
        db.commit()
        db.add(Trade(account_id=account.id, ticker="NBIS", instrument_type="option", contracts=3, option_type="call",
                     strike=100, expiration=datetime(2026, 11, 20).date(), avg_entry_premium=2.5, total_premium_paid=750,
                     opened_at=datetime(2026, 10, 8, 14)))
        db.add(Trade(account_id=other.id, ticker="ZZZQ", instrument_type="stock", contracts=10, avg_entry_premium=5,
                     total_premium_paid=50, opened_at=datetime(2026, 10, 8, 14)))
        db.commit()
        try:
            dossier = jo_research.dossier_context(db, RECEIPT, [account.id])
        finally:
            for trade in db.exec(select(Trade).where(Trade.account_id.in_([account.id, other.id]))).all():
                db.delete(trade)
            db.delete(account)
            db.delete(other)
            db.commit()
    assert all(r["symbol"] != "ZZZQ" for r in dossier["held"])  # not an account approved for Jo
    held = [r for r in dossier["held"] if r["symbol"] == "NBIS"]
    assert held == [{"symbol": "NBIS", "held": True, "instruments": ["calls"], "option_expiry_weeks": ["2026-11-16"]}]
    assert "750" not in json.dumps(dossier["held"]) and str(account.id) not in json.dumps(dossier)
    assert dossier["radar"]["state"] in ("off", "unavailable", "ok", "no_data", "live", "closed", "stale")


def test_runner_publishes_on_schedule_and_imports(check, monkeypatch):
    _, config, actor = check
    morning = SimpleNamespace(enabled=True, check_config=str(check[0].config_path), account_ids=[uuid4()])
    monkeypatch.setitem(jo_research.BUILDERS, "dossier", lambda db, now, accounts: {"day": "fixture"})
    monkeypatch.setitem(jo_research.BUILDERS, "audit", lambda db, now, accounts: {"week": "fixture"})
    runner = jo_research.ResearchRunner(engine, config_loader=lambda: morning, calendar=lambda day: {"status": "open"})
    thursday_noon = datetime(2026, 10, 8, 16, 0, tzinfo=timezone.utc)
    assert runner.run_once(thursday_noon)["published"] == ["red_team"]
    assert runner.run_once(thursday_noon + timedelta(minutes=1))["published"] == []  # unchanged list
    thursday_evening = datetime(2026, 10, 8, 22, 35, tzinfo=timezone.utc)  # 18:35 New York
    assert runner.run_once(thursday_evening)["published"] == ["dossier"]
    assert runner.run_once(thursday_evening + timedelta(minutes=1))["published"] == []
    friday_evening = datetime(2026, 10, 9, 21, 5, tzinfo=timezone.utc)  # 17:05 New York, before the dossier time
    assert runner.run_once(friday_evening)["published"] == ["red_team", "audit"]  # red team republished after 12 hours
    exchange.submit(config.market_watch_snapshots_dir, config.market_watch_outbox_dir, actor, research(), friday_evening)
    out = runner.run_once(friday_evening + timedelta(minutes=1))
    assert out["imported"] == 1 and out["errors"] == 0
    assert runner.run_once(friday_evening + timedelta(minutes=2))["imported"] == 0
    assert jo_research.ResearchRunner(engine, config_loader=lambda: None).run_once() == {"status": "disabled"}


def test_daily_cap_rejects_beyond_the_bound(check, monkeypatch):
    _, config, actor = check
    monkeypatch.setattr(jo_research, "DAILY_IMPORTS", 1)
    for operation_id in ("first", "second"):
        exchange.submit(config.market_watch_snapshots_dir, config.market_watch_outbox_dir, actor, research(operation_id), RECEIPT)
    with Session(engine) as db:
        assert jo_research.import_submission(db, config, actor, keyed(actor, "first"), RECEIPT)["status"] == "saved"
        capped = jo_research.import_submission(db, config, actor, keyed(actor, "second"), RECEIPT)
        assert capped["status"] == "rejected" and "Daily cap" in capped["reason"]
        assert len(db.exec(select(CopilotInvestigation)).all()) == 1
