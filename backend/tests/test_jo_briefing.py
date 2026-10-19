"""Owner-only persistence, provenance and recovery; no live data or inference."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from app.database import get_session
from app.engine import jo_briefing as store
from app.models import JoMemoryRevision
from app.routers.jo_briefing import router
from tests.test_browser_access import boundary, signin  # noqa: F401
from tests.test_schema_migrations import _alembic


@pytest.fixture
def engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'briefing.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def client(engine):
    app = FastAPI()
    app.include_router(router, prefix="/jo")
    def session():
        with Session(engine) as db:
            yield db
    app.dependency_overrides[get_session] = session
    with TestClient(app) as client:
        yield client


def memory(**changes):
    return {"operation_id": "memory-1", "kind": "thesis", "symbol": "MU",
            "original_text": "  I believe demand will improve.\n", "source": "owner_statement",
            "status": "active", "owner_confirmed": True, **changes}


def packet(**changes):
    return {"operation_id": "packet-1", "day": "2026-10-01", "as_of": "2026-10-01T12:00:00Z",
            "scope": "Invented evidence only; not a live publication", "evidence": [
                {"id": "price", "kind": "fact", "text": "Invented MU price 100 USD/share",
                 "source": "fixture", "observed_at": "2026-10-01T11:59:00Z", "retrieved_at": "2026-10-01T12:00:00Z"}],
            "gaps": ["No verified earnings date"], **changes}


def briefing(packet_id, **changes):
    return {"operation_id": "brief-1", "packet_id": packet_id, "author": "fixture",
            "prompt_version": "fixture-v1", "summary": "The supplied price is 100 USD/share.",
            "summary_evidence_ids": ["price"], "limitations": ["Invented data"], "items": [
                {"symbol": "MU", "what_matters": "The supplied price", "why_personal": "A selected name",
                 "what_changed": "No prior briefing supplied", "contrary_evidence": "No corroboration supplied",
                 "watch_out": "Missing earnings data", "evidence_ids": ["price"]}], **changes}


def test_memory_revisions_retirement_and_frozen_packet_reopen(client):
    first = client.post("/jo/memories", json=memory())
    assert first.status_code == 201, first.text
    first = first.json()
    assert first["body"]["original_text"] == memory()["original_text"]
    assert client.post("/jo/memories", json=memory()).json() == first
    assert client.post("/jo/memories", json=memory(original_text="Changed retry")).status_code == 409
    saved_packet = client.post("/jo/packets", json=packet(memory_revision_ids=[first["id"]])).json()
    revised = memory(operation_id="revise", memory_id=first["memory_id"], base_revision=1,
                     original_text="I no longer believe that.", status="retired")
    second = client.post("/jo/memories", json=revised)
    assert second.status_code == 201, second.text
    assert second.json()["revision"] == 2
    assert client.get("/jo/memories").json()["items"] == []
    assert len(client.get("/jo/memories?status=retired").json()["items"]) == 1
    old = client.get(f"/jo/packets/{saved_packet['id']}").json()
    assert old["memories"] == [first]  # retirement does not rewrite yesterday
    assert client.post("/jo/packets", json=packet(operation_id="new", memory_revision_ids=[first["id"]])).status_code == 409
    assert client.post("/jo/memories", json={**revised, "operation_id": "stale"}).status_code == 409
    history = client.get(f"/jo/memories/{first['memory_id']}?limit=1").json()
    assert history["next_before_revision"] == 2
    assert client.get(f"/jo/memories/{first['memory_id']}?before_revision=2").json()["items"] == [first]


def test_proposals_are_not_active_and_require_owner_confirmation(client):
    proposed = memory(source="jo_proposal", status="proposed", owner_confirmed=False)
    saved = client.post("/jo/memories", json=proposed).json()
    assert client.get("/jo/memories").json()["items"] == []
    assert client.get("/jo/memories?status=proposed").json()["items"] == [saved]
    assert client.post("/jo/packets", json=packet(memory_revision_ids=[saved["id"]])).status_code == 422
    assert client.post("/jo/memories", json={**proposed, "status": "active"}).status_code == 422
    accepted = {**proposed, "operation_id": "accept", "memory_id": saved["memory_id"], "base_revision": 1,
                "status": "active", "owner_confirmed": True}
    assert client.post("/jo/memories", json=accepted).status_code == 201


def test_cited_briefings_reopen_without_overwriting_and_redaction_cannot_be_replayed_away(client):
    source = packet()
    saved_packet = client.post("/jo/packets", json=source).json()
    assert client.post("/jo/packets", json=source).json() == saved_packet
    request = briefing(saved_packet["id"])
    response = client.post("/jo/briefings", json=request)
    assert response.status_code == 201, response.text
    first = response.json()
    assert first["provenance"] == "owner_supplied" and first["body"]["model_id"] is None
    assert client.post("/jo/briefings", json=request).json() == first
    assert client.post("/jo/briefings", json={**request, "summary": "Different"}).status_code == 409
    assert client.post("/jo/briefings", json={**request, "operation_id": "bad", "summary_evidence_ids": ["invented"]}).status_code == 422
    corrected = {**request, "operation_id": "correction", "supersedes_id": first["id"], "summary": "A corrected interpretation"}
    assert client.post("/jo/briefings", json=corrected).status_code == 201
    reopened = client.get(f"/jo/briefings/{first['id']}").json()
    assert reopened["body"] == first["body"] and reopened["packet"]["body"] == saved_packet["body"]
    assert len(client.get("/jo/briefings?day=2026-10-01").json()["items"]) == 2
    other = client.post("/jo/packets", json=packet(operation_id="other-day", day="2026-10-02")).json()
    assert client.post("/jo/briefings", json={**corrected, "operation_id": "wrong-day", "packet_id": other["id"]}).status_code == 422
    redacted = client.post(f"/jo/briefings/{first['id']}/redact").json()
    assert redacted["body"] == {} and redacted["redacted_at"]
    assert client.post("/jo/briefings", json=request).json()["body"] == {}
    assert client.post(f"/jo/packets/{saved_packet['id']}/redact").json()["body"] == {}
    assert client.post("/jo/packets", json=source).json()["body"] == {}
    assert client.post("/jo/briefings", json={**request, "operation_id": "after-redaction"}).status_code == 409


def test_memory_redaction_scrubs_every_revision_and_preserves_tombstones(client, engine):
    first = client.post("/jo/memories", json=memory()).json()
    saved_packet = client.post("/jo/packets", json=packet(memory_revision_ids=[first["id"]])).json()
    second = memory(operation_id="second", memory_id=first["memory_id"], base_revision=1,
                    original_text="A sensitive correction", source_reference="A private source")
    assert client.post("/jo/memories", json=second).status_code == 201
    request = {"operation_id": "redact", "base_revision": 2}
    path = f"/jo/memories/{first['memory_id']}/redact"
    redacted = client.post(path, json=request).json()
    assert client.post(path, json=request).json() == redacted
    assert client.post("/jo/memories", json=memory()).json()["body"] == {}
    assert client.post("/jo/memories", json={**second, "operation_id": "restore", "base_revision": 3}).status_code == 409
    assert client.get(f"/jo/packets/{saved_packet['id']}").json()["memories"][0]["body"] == {}
    with Session(engine) as session:
        rows = session.exec(select(JoMemoryRevision)).all()
        assert len(rows) == 3
        assert all(row.body_json == "{}" and row.symbol is None and row.redacted_at for row in rows)


@pytest.mark.parametrize("changes", [
    {"as_of": "2026-10-01T12:00:00"},
    {"as_of": (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()},
    {"evidence": [], "gaps": []},
    {"evidence": packet()["evidence"] * 2},
    {"unexpected": "field"},
])
def test_invalid_packets_are_rejected(client, changes):
    assert client.post("/jo/packets", json=packet(**changes)).status_code == 422


def test_missing_sources_can_be_saved_without_invented_claims(client):
    source = client.post("/jo/packets", json=packet(evidence=[], gaps=["Publication unavailable"])).json()
    request = briefing(source["id"], items=[], summary="Briefing unavailable", summary_evidence_ids=[])
    assert client.post("/jo/briefings", json=request).status_code == 201
    assert client.post("/jo/briefings", json={**request, "operation_id": "silent", "limitations": []}).status_code == 422


def exercise_concurrency(engine):
    def write(body):
        with Session(engine) as session:
            try:
                return store.save_memory(session, store.MemorySave(**body))
            except store.Conflict:
                return "conflict"
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(write, [memory()] * 4))
    assert all(result == results[0] for result in results)
    first = results[0]
    variants = [memory(operation_id=f"update-{i}", memory_id=first["memory_id"], base_revision=1,
                       original_text=f"Changed {i}") for i in range(4)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(write, variants))
    assert results.count("conflict") == 3
    with Session(engine) as session:
        assert len(session.exec(select(JoMemoryRevision)).all()) == 2


def test_concurrent_retry_and_revision_conflict(engine):
    exercise_concurrency(engine)


def test_jo_routes_are_owner_only_even_for_journal_readers(boundary):  # noqa: F811
    assert signin(boundary).status_code == 200
    # Full read grants are not access to personal Jo storage.
    from app.models import AccessPrincipal
    with Session(boundary.engine) as session:
        principal = session.get(AccessPrincipal, "dot")
        import json
        grants = json.loads(principal.grants_json)
        grants["journal_read"] = True
        principal.grants_json = json.dumps(grants)
        session.add(principal)
        session.commit()
    for route in router.routes:
        path = "/jo" + route.path
        for name in ("memory_id", "packet_id", "briefing_id"):
            path = path.replace("{" + name + "}", str(UUID(int=1)))
        for method in route.methods:
            assert boundary.public.request(method, path, json={} if method == "POST" else None).status_code == 403
    assert boundary.owner.post("/jo/memories", json=memory(), headers={"x-tj-csrf": "wrong"}).status_code == 403
    assert boundary.owner.post("/jo/memories", json=memory()).status_code == 201


def test_storage_migration_upgrade_downgrade(tmp_path):
    from sqlalchemy import inspect
    path = tmp_path / "migration.sqlite"
    _alembic(path, "upgrade", "head")
    engine = create_engine(f"sqlite:///{path}")
    with Session(engine) as session:
        saved = store.save_memory(session, store.MemorySave(**memory()))
    _alembic(path, "upgrade", "head")
    with Session(engine) as session:
        assert store.latest_memory(session, UUID(saved["memory_id"])).id == UUID(saved["id"])
    _alembic(path, "downgrade", "b8d4f0a2c3e5")
    assert "jo_memory_revision" not in inspect(engine).get_table_names()
    _alembic(path, "upgrade", "head")
    assert "morning_briefing_record" in inspect(engine).get_table_names()
    engine.dispose()
