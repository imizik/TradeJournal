"""Generated tokens and disposable files/SQLite only; no real data publication."""
from datetime import timedelta
import json
import re
from pathlib import Path
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from app.engine import jo_briefing as store
from app.models import JoMemoryRevision, MorningBriefingRecord
from cloud_mcp_check_common import read_config
from jo_briefing_common import MemorySave, PacketSave, BriefingSave, Text
import jo_briefing_exchange as exchange
import jo_briefing_owner as owner
from tests.test_cloud_mcp_check import harness, signing_key, call, rpc, RECEIPT  # noqa: F401

SCOPES = "check:read jo:read jo:submit"


@pytest.mark.parametrize("text", ["", " ", "\t\r\n", "\u00a0"])
def test_nonblank_validation_still_refuses_blank_text(text):
    from pydantic import TypeAdapter, ValidationError
    with pytest.raises(ValidationError):
        TypeAdapter(Text).validate_python(text)
    for field in ("author", "prompt_version", "summary"):
        with pytest.raises(ValidationError):
            BriefingSave.model_validate({**brief({"id": str(uuid4())}), field: text})


def test_exported_nonblank_patterns_accept_whole_strings(personal):
    """Connector validators may full-match JSON Schema patterns instead of searching."""
    h, _, _, _, _ = personal
    with TestClient(h.server().streamable_http_app()) as client:
        tools = rpc(client, "", {}, h.token(scope=SCOPES), "tools/list").json()["result"]["tools"]
    patterns = []

    def collect(schema):
        if isinstance(schema, dict):
            if schema.get("type") == "string" and schema.get("maxLength") in (120, 4000) and "pattern" in schema:
                # Operation IDs have a separate restricted alphabet, not free text.
                if schema["pattern"] != r"^[A-Za-z0-9_.:-]+$":
                    patterns.append(schema["pattern"])
            for value in schema.values():
                collect(value)
        elif isinstance(schema, list):
            for value in schema:
                collect(value)

    for tool in tools:
        if tool["name"] in ("jo_briefing_submit", "jo_memory_propose"):
            collect(tool["inputSchema"])
    assert len(patterns) >= 3
    for pattern in patterns:
        for text in ("Jo", "jo-morning-v2", "Review APLD’s calls.", " first\nsecond \n", "\nJo\n"):
            assert re.fullmatch(pattern, text), (pattern, text)
        for text in ("", " ", "\t\r\n", "\u00a0"):
            assert not re.search(pattern, text), (pattern, text)


@pytest.fixture
def personal(harness, tmp_path):  # noqa: F811
    snapshots, outbox = tmp_path / "snapshots", tmp_path / "outbox"
    snapshots.mkdir()
    outbox.mkdir()
    harness.configure(jo_briefing_enabled=True, market_watch_snapshots_dir=str(snapshots), market_watch_outbox_dir=str(outbox))
    config = read_config(harness.config_path)
    engine = create_engine("sqlite:///" + str(tmp_path / "personal.sqlite"))
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        memory = store.save_memory(session, MemorySave(operation_id="owner-memory", kind="preference",
            original_text="Wait for my confirmation.", source="owner_statement", status="active", owner_confirmed=True))
        packet = store.save_packet(session, PacketSave(operation_id="owner-packet", day=RECEIPT.date(), as_of=RECEIPT,
            scope="invented fixture", evidence=[dict(id="fact1", kind="fact", text="Fixture quote", source="invented",
                retrieved_at=RECEIPT)], gaps=["No positions"], memory_revision_ids=[UUID(memory["id"])]))
        owner.publish(session, config, UUID(packet["id"]), RECEIPT)
    yield harness, config, engine, packet, memory
    engine.dispose()


def proposed(operation_id="proposal"):
    return MemorySave(operation_id=operation_id, kind="thesis", original_text="I might prefer SPY.",
        interpretation="Tentative preference", source="jo_proposal").model_dump(mode="json")


def brief(packet, operation_id="brief"):
    return BriefingSave(operation_id=operation_id, packet_id=packet["id"], author="Jo", prompt_version="test-v1",
        summary="Fixture only", summary_evidence_ids=["fact1"], items=[], limitations=["Invented"]).model_dump(mode="json")


def result(client, name, args, token):
    value = call(client, name, args, token)
    assert not value.get("isError"), value
    return value["structuredContent"]


def test_end_to_end_pending_import_reopen_and_receipt_recovery(personal):
    h, config, engine, packet, memory = personal
    token = h.token(scope=SCOPES)
    with TestClient(h.server().streamable_http_app()) as client:
        tools = {t["name"]: t for t in rpc(client, "", {}, token, "tools/list").json()["result"]["tools"]}
        assert tools["jo_context"]["securitySchemes"][0]["scopes"] == ["check:read", "jo:read"]
        assert tools["jo_briefing_submit"]["securitySchemes"][0]["scopes"] == SCOPES.split()
        context = result(client, "jo_context", {"packet_id": packet["id"]}, token)
        assert context["packet"]["memories"][0]["id"] == memory["id"]
        body = brief(packet)
        pending = result(client, "jo_briefing_submit", {"briefing": body}, token)
        assert pending["status"] == "pending_import" and not pending["app_saved"]
        assert result(client, "jo_briefing_submit", {"briefing": body}, token) == pending
        with Session(engine) as session:
            receipt = owner.import_submission(session, config, "brief", RECEIPT + timedelta(seconds=5))
            saved = session.get(MorningBriefingRecord, UUID(receipt["record_id"]))
            assert json.loads(saved.body_json)["summary"] == body["summary"]
            assert store.get_packet(session, saved.packet_id) == context["packet"]
        assert result(client, "jo_receipt", {"operation_id": "brief"}, token) == receipt
        assert receipt["status"] == "saved" and receipt["app_saved"]
        assert result(client, "jo_briefing_submit", {"briefing": body}, token) == receipt
        assert call(client, "jo_briefing_submit", {"briefing": {**body, "summary": "Changed"}}, token)["isError"]
        result(client, "jo_memory_propose", {"packet_id": packet["id"], "memory": proposed()}, token)
        with Session(engine) as session:
            accepted = owner.import_submission(session, config, "proposal", RECEIPT)
            assert accepted["memory_status"] == "proposed"
            assert len(store.memories(session, "active", None, 50)) == 1
            assert session.get(JoMemoryRevision, UUID(accepted["record_id"])).status == "proposed"
    with TestClient(h.server().streamable_http_app()) as client:
        assert result(client, "jo_receipt", {"operation_id": "brief"}, token) == receipt
    with Session(engine) as session:
        assert len(session.exec(select(MorningBriefingRecord)).all()) == 1
    assert not h.requests


def test_scopes_actor_revocation_and_disabled_catalog(personal):
    h, config, _, packet, _ = personal
    with TestClient(h.server().streamable_http_app()) as client:
        assert call(client, "jo_context", {"packet_id": packet["id"]}, h.token())["isError"]
        assert call(client, "jo_briefing_submit", {"briefing": brief(packet)}, h.token(scope="check:read jo:read"))["isError"]
        assert rpc(client, "jo_context", {"packet_id": packet["id"]}, h.token(subject="other", scope=SCOPES)).status_code == 401
        assert call(client, "jo_context", {"packet_id": str(uuid4())}, h.token(scope=SCOPES))["isError"]
        h.configure(jo_briefing_enabled=False)
        assert rpc(client, "jo_context", {"packet_id": packet["id"]}, h.token(scope=SCOPES)).status_code == 401
    with TestClient(h.server().streamable_http_app()) as client:
        tools = rpc(client, "", {}, h.token(), "tools/list").json()["result"]["tools"]
        assert not any(t["name"].startswith("jo_") for t in tools)
    assert not list(Path(config.market_watch_outbox_dir).iterdir())


@pytest.mark.parametrize("change", [{"status": "active", "owner_confirmed": True},
    {"source": "owner_statement"}, {"memory_id": str(uuid4()), "base_revision": 1},
    {"status": "retired", "owner_confirmed": True}, {"original_text": "x" * 4001}, {"extra": "ignored?"}])
def test_proposals_cannot_self_approve_or_amend(personal, change):
    h, config, _, packet, _ = personal
    with TestClient(h.server().streamable_http_app()) as client:
        assert call(client, "jo_memory_propose", {"packet_id": packet["id"], "memory": {**proposed(), **change}}, h.token(scope=SCOPES))["isError"]
    assert not list(Path(config.market_watch_outbox_dir).iterdir())


def test_expiry_citations_payload_and_cross_actor_receipts(personal):
    h, config, _, packet, _ = personal
    token = h.token(scope=SCOPES)
    with TestClient(h.server().streamable_http_app()) as client:
        assert call(client, "jo_briefing_submit", {"briefing": {**brief(packet), "summary_evidence_ids": ["unknown"]}}, token)["isError"]
        assert call(client, "jo_context", {"packet_id": packet["id"], "path": "/private"}, token)["isError"]
        result(client, "jo_briefing_submit", {"briefing": brief(packet)}, token)
    with TestClient(h.server(now=RECEIPT + timedelta(hours=4)).streamable_http_app()) as client:
        assert call(client, "jo_context", {"packet_id": packet["id"]}, token)["isError"]
        assert call(client, "jo_briefing_submit", {"briefing": brief(packet, "new")}, token)["isError"]
        assert result(client, "jo_briefing_submit", {"briefing": brief(packet)}, token)["status"] == "pending_import"
    with pytest.raises(FileNotFoundError):
        exchange.status(config.market_watch_snapshots_dir, config.market_watch_outbox_dir, "check_" + str(uuid4()), "brief")


def test_commit_then_export_failure_recovers(personal, monkeypatch):
    _, config, engine, packet, _ = personal
    exchange.submit(config.market_watch_snapshots_dir, config.market_watch_outbox_dir, config.profiles[0].id,
        packet["id"], "briefing", brief(packet), RECEIPT)
    write = exchange.write
    def fail(*args):
        raise OSError("simulated export failure")
    monkeypatch.setattr(exchange, "write", fail)
    with Session(engine) as session:
        with pytest.raises(OSError):
            owner.import_submission(session, config, "brief", RECEIPT)
        assert len(session.exec(select(MorningBriefingRecord)).all()) == 1
    monkeypatch.setattr(exchange, "write", write)
    with Session(engine) as session:
        receipt = owner.import_submission(session, config, "brief", RECEIPT + timedelta(hours=6))
        assert receipt["status"] == "saved"
        assert "summary" not in json.dumps(receipt)
        assert len(session.exec(select(MorningBriefingRecord)).all()) == 1


def test_redacted_context_rejected_on_import(personal):
    _, config, engine, packet, memory = personal
    exchange.submit(config.market_watch_snapshots_dir, config.market_watch_outbox_dir, config.profiles[0].id,
                    packet["id"], "memory", proposed(), RECEIPT)
    with Session(engine) as session:
        store.redact_memory(session, UUID(memory["memory_id"]), store.MemoryRedact(operation_id="erase", base_revision=1))
        receipt = owner.import_submission(session, config, "proposal", RECEIPT)
        assert receipt["status"] == "rejected" and not receipt["app_saved"]
        assert not store.memories(session, "proposed", None, 50)
        assert owner.import_submission(session, config, "proposal", RECEIPT) == receipt


def test_symlinks_and_oversize_exchange_refused(personal, tmp_path):
    _, config, _, packet, _ = personal
    actor = config.profiles[0].id
    path = Path(config.market_watch_snapshots_dir) / exchange.context_name(actor, packet["id"])
    original = path.read_text()
    path.unlink()
    target = tmp_path / "secret"
    target.write_text(original)
    path.symlink_to(target)
    with pytest.raises(OSError):
        exchange.context(config.market_watch_snapshots_dir, actor, packet["id"], RECEIPT)
    path.unlink()
    path.write_text("x" * (exchange.LIMIT + 1))
    with pytest.raises(ValueError):
        exchange.context(config.market_watch_snapshots_dir, actor, packet["id"], RECEIPT)


def test_corrections_and_concurrent_exact_submission(personal):
    from concurrent.futures import ThreadPoolExecutor
    _, config, engine, packet, _ = personal
    actor = config.profiles[0].id
    def send(i):
        return exchange.submit(config.market_watch_snapshots_dir, config.market_watch_outbox_dir, actor,
            packet["id"], "briefing", brief(packet), RECEIPT + timedelta(microseconds=i))
    with ThreadPoolExecutor(max_workers=4) as pool:
        receipts = list(pool.map(send, range(4)))
    assert all(r == receipts[0] for r in receipts)
    with Session(engine) as session:
        first = owner.import_submission(session, config, "brief", RECEIPT + timedelta(seconds=1))
        correction = {**brief(packet, "correction"), "supersedes_id": first["record_id"], "summary": "Corrected fixture"}
        exchange.submit(config.market_watch_snapshots_dir, config.market_watch_outbox_dir, actor,
            packet["id"], "briefing", correction, RECEIPT + timedelta(seconds=2))
        assert owner.import_submission(session, config, "correction", RECEIPT + timedelta(seconds=3))["status"] == "saved"
        assert len(session.exec(select(MorningBriefingRecord)).all()) == 2
        owner_record = store.save_briefing(session, BriefingSave.model_validate(brief(packet, "owner-only")))
        forbidden = {**brief(packet, "forbidden"), "supersedes_id": owner_record["id"]}
        exchange.submit(config.market_watch_snapshots_dir, config.market_watch_outbox_dir, actor,
            packet["id"], "briefing", forbidden, RECEIPT)
        assert owner.import_submission(session, config, "forbidden", RECEIPT)["status"] == "rejected"


def test_changed_submission_digest_and_context_rejected(personal):
    _, config, engine, packet, _ = personal
    actor = config.profiles[0].id
    exchange.submit(config.market_watch_snapshots_dir, config.market_watch_outbox_dir, actor,
                    packet["id"], "memory", proposed(), RECEIPT)
    key = exchange.operation_key(actor, "proposal")
    path = Path(config.market_watch_outbox_dir) / f"jo-request-{key}.json"
    request = json.loads(path.read_text())
    request["context_sha256"] = "0" * 64
    path.write_text(json.dumps(request))
    with Session(engine) as session:
        assert owner.import_submission(session, config, "proposal", RECEIPT)["status"] == "rejected"
        assert not store.memories(session, "proposed", None, 50)
    receipt = Path(config.market_watch_snapshots_dir) / f"jo-receipt-{key}.json"
    ack = json.loads(receipt.read_text())
    ack["profile_id"] = "check_" + str(uuid4())
    receipt.write_text(json.dumps(ack))
    with pytest.raises(ValueError, match="mismatch"):
        exchange.status(config.market_watch_snapshots_dir, config.market_watch_outbox_dir, actor, "proposal")


def test_opportunity_tool_roundtrip_checks_freshness_and_new_section_citations(personal):
    h, config, engine, _, _ = personal
    rows = [dict(id=key, kind="fact", text="Invented candidate and range", source="Tradier fixture",
                 observed_at=RECEIPT, retrieved_at=RECEIPT) for key in ["discovery-NEW", "market-NEW", "setup-NEW"]]
    with Session(engine) as session:
        packet = store.save_packet(session, PacketSave(operation_id="discovery", day=RECEIPT.date(), as_of=RECEIPT,
            scope="Invented discovery", evidence=rows, gaps=[]))
        owner.publish(session, config, UUID(packet["id"]), RECEIPT)
    item = dict(symbol="NEW", status="conditional", what_matters="Reported catalyst", why_personal="An intraday candidate",
        what_changed="A reported update", contrary_evidence="Unverified liquidity", watch_out="Recheck spread",
        entry_trigger="Wait for a range break", invalidation="Failed retest", timeframe="Intraday only",
        evidence_ids=[r["id"] for r in rows])
    body = {**brief(packet, "opportunity"), "prompt_version": "jo-morning-v4", "summary_evidence_ids": ["market-NEW"], "opportunities": [item]}
    with TestClient(h.server().streamable_http_app()) as client:
        token = h.token(scope=SCOPES)
        assert call(client, "jo_briefing_submit", {"briefing": {**body, "summary_evidence_ids": []}}, token)["isError"]
        bad = {**item, "evidence_ids": ["unknown"]}
        assert call(client, "jo_briefing_submit", {"briefing": {**body, "opportunities": [bad]}}, token)["isError"]
        assert result(client, "jo_briefing_submit", {"briefing": body}, token)["status"] == "pending_import"
        with Session(engine) as session:
            receipt = owner.import_submission(session, config, "opportunity", RECEIPT+timedelta(seconds=1))
            saved = session.get(MorningBriefingRecord, UUID(receipt["record_id"]))
            assert json.loads(saved.body_json)["opportunities"][0]["entry_trigger"] == item["entry_trigger"]
        assert result(client, "jo_receipt", {"operation_id": "opportunity"}, token)["app_saved"]
