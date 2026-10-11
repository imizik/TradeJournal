"""Local fixture service proof, never actual ChatGPT inference/independence."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import json
import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from advisor_shadow_demo import build_app, PATHS
import advisor_shadow_demo
from app.database import get_session
from app.engine import advisor_shadow as service, decisions, practice, practice_agent
from app.models import DecisionContext, DecisionEvent, DecisionRecord, JobRun, PracticeAgentCall, PracticeRun
from app.routers import advisor_shadow as owner_routes, decisions as decision_routes, practice as practice_routes


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("No paid adapter/provider/job may run in manual demo")
    monkeypatch.setattr(practice_agent, "invoke", forbidden)
    monkeypatch.setattr(practice, "run_agent", forbidden)
    monkeypatch.setattr(practice_routes, "submit_job", forbidden)
    engine = create_engine(f"sqlite:///{tmp_path / 'demo.db'}", connect_args={"check_same_thread": False, "timeout": 2})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as db:
        run_id, call_id, token = service.create_fixture(db)
    gateway = build_app(engine, call_id)
    owner = FastAPI()
    owner.include_router(owner_routes.router, prefix="/advisor-shadow")
    owner.include_router(practice_routes.router, prefix="/practice")
    owner.include_router(decision_routes.router, prefix="/decisions")

    def session():
        with Session(engine) as db:
            yield db
    owner.dependency_overrides[get_session] = session
    with TestClient(gateway) as client, TestClient(owner) as operator:
        client.headers["authorization"] = f"Bearer {token}"
        yield engine, run_id, call_id, token, client, operator
    engine.dispose()


def submission(client, decision="skip"):
    packet = client.get("/packet").json()
    return {"assignment_id": packet["assignment_id"], "packet_sha256": packet["packet_sha256"],
        "choices": [{"opportunity_id": o["opportunity_id"], "decision": decision, "rationale": "No verified setup in invented fixture"}
                    for o in packet["packet"]["opportunities"]]}


def counts(engine):
    with Session(engine) as db:
        return len(db.exec(select(DecisionRecord)).all()), len(db.exec(select(DecisionEvent)).all())


def test_complete_atomic_receipt_retries_conflicts_reload_and_hidden_routes(fixture):
    engine, run_id, call_id, token, client, owner = fixture
    packet = client.get("/packet").json()
    assert len(packet["packet"]["opportunities"]) == 5
    assert packet["packet"]["demo_only"] is True
    assert client.get("/receipt").json()["choices"] == []
    body = submission(client)
    saved = client.post("/choices", json=body)
    assert saved.status_code == 200
    receipt = saved.json()
    assert len(receipt["choices"]) == 5
    assert receipt["submitted_output"] == body and receipt["independence"] == "independence-unverified"
    assert receipt == client.get("/receipt").json() == client.post("/choices", json=body).json()
    changed = json.loads(json.dumps(body))
    changed["choices"][0]["rationale"] = "Changed content"
    assert client.post("/choices", json=changed).status_code == 409
    assert client.get("/receipt").json() == receipt
    assert counts(engine) == (5, 0)
    # A new gateway/session reads exactly the persisted receipt after lost response/restart.
    with TestClient(build_app(engine, call_id)) as restarted:
        assert restarted.get("/receipt", headers={"authorization": f"Bearer {token}"}).json() == receipt
    view = owner.get(f"/practice/runs/{run_id}").json()
    assert view["manual_shadow"] and view["independence"] == "independence-unverified"
    assert view["agent"]["limits"] is None
    assert token not in json.dumps(view) and "capability_sha256" not in json.dumps(view)
    assert all(o["agent"] is None and o["human"] is None for o in view["opportunities"])
    record = receipt["choices"][0]
    assert owner.get(f"/decisions/{record['id']}").status_code == 404
    assert owner.get(f"/decisions/{record['id']}/paper").status_code == 404
    assert owner.post(f"/decisions/{record['id']}/arm", json={"operation_id": "probe"}).status_code == 404
    assert owner.get("/decisions").json()["decisions"] == []
    opp = packet["packet"]["opportunities"][0]
    assert owner.post(f"/practice/opportunities/{opp['opportunity_id']}/reveal", json={}).status_code == 409
    assert owner.post(f"/practice/opportunities/{opp['opportunity_id']}/choice", json={"decision": "skip", "rationale": "Human frozen without advice"}).status_code == 200
    revealed = owner.post(f"/practice/opportunities/{opp['opportunity_id']}/reveal", json={}).json()
    assert revealed["opportunities"][0]["agent"]["id"] == record["id"]
    assert counts(engine) == (6, 0)
    with Session(engine) as db:
        assert db.exec(select(JobRun)).one().status == "completed"


@pytest.mark.parametrize("mutation", ["partial", "duplicate", "wrong_id", "actor", "context", "policy", "invalid", "expired_wait", "oversize", "assignment", "hash", "take"])
def test_forged_or_invalid_batches_leave_no_partial_records(fixture, mutation):
    engine, _, _, _, client, _ = fixture
    body = submission(client)
    if mutation == "partial":
        body["choices"].pop()
    if mutation == "duplicate":
        body["choices"][1] = body["choices"][0]
    if mutation == "wrong_id":
        body["choices"][0]["opportunity_id"] = str(uuid.uuid4())
    if mutation in {"actor", "context", "policy"}:
        body["choices"][-1][mutation] = "forged"
    if mutation == "invalid":
        body["choices"][-1]["decision"] = "buy"
    if mutation == "expired_wait":
        body["choices"][-1].update(decision="wait", wait_condition="Wait", wait_expiry="2020-01-01T13:00:00Z")
    if mutation == "oversize":
        body["choices"][-1]["rationale"] = "x" * 65536
    if mutation == "assignment":
        body["assignment_id"] = str(uuid.uuid4())
    if mutation == "hash":
        body["packet_sha256"] = "0" * 64
    if mutation == "take":
        body["choices"][-1].update(decision="take", plan={})
    assert client.post("/choices", json=body).status_code in {409, 413}
    assert client.get("/receipt").json()["choices"] == []
    assert counts(engine) == (0, 0)


def test_wait_retry_retains_original_after_wait_expiry(fixture, monkeypatch):
    engine, _, _, _, client, _ = fixture
    body = submission(client)
    expiry = practice.now_utc() + timedelta(seconds=30)
    body["choices"][0].update(decision="wait", wait_condition="Await verified market capture", wait_expiry=practice.iso(expiry))
    first = client.post("/choices", json=body).json()
    # The capability is still current; only the original WAIT has expired.
    monkeypatch.setattr(practice, "now_utc", lambda: expiry + timedelta(seconds=1))
    assert client.post("/choices", json=body).json() == first
    assert counts(engine) == (5, 0)


def test_neutral_projection_and_receipt_exclude_raw_notes_and_other_actors(fixture):
    engine, run_id, _, _, client, owner = fixture
    with Session(engine) as db:
        ctx = db.exec(select(DecisionContext)).first()
        evidence = json.loads(ctx.data_json)
        evidence["packet"].update(journal="SECRET_JOURNAL", human="SECRET_HUMAN", advisor="SECRET_ADVISOR", sealed="SECRET_CONTINUATION")
        ctx.data_json = service.canonical(evidence)
        ctx.context_sha256 = decisions._hash(ctx.data_json)
        db.add(ctx)
        db.flush()
        call = service.demo_call(db, run_id)
        call.payload_json = service.canonical(service.neutral_packet(db, db.get(PracticeRun, run_id)))
        config = json.loads(call.config_json)
        config["packet_sha256"] = service.digest(json.loads(call.payload_json))
        call.config_json = service.canonical(config)
        db.add(call)
        db.commit()
    packet = client.get("/packet").json()
    assert "SECRET_" not in json.dumps(packet)
    opp = packet["packet"]["opportunities"][0]
    owner.post(f"/practice/opportunities/{opp['opportunity_id']}/choice", json={"decision": "skip", "rationale": "SECRET_OTHER_ACTOR"})
    body = submission(client)
    assert client.post("/choices", json=body).status_code == 200
    receipt = client.get("/receipt").json()
    assert "SECRET_" not in json.dumps(receipt)
    assert all("evidence" not in r and r["actor"] == "agent:a3" for r in receipt["choices"])


@pytest.mark.parametrize("tamper", ["context", "capture", "policy", "assignment"])
def test_stored_evidence_and_binding_integrity_fail_closed(fixture, tamper):
    engine, run_id, _, _, client, _ = fixture
    body = submission(client)
    with Session(engine) as db:
        if tamper in {"context", "capture"}:
            ctx = db.exec(select(DecisionContext)).first()
            if tamper == "context":
                ctx.data_json = ctx.data_json.replace('"value":100.0', '"value":999.0')
            else:
                ctx.captured_at += timedelta(seconds=1)
            db.add(ctx)
        elif tamper == "policy":
            run = db.get(PracticeRun, run_id)
            run.policy_hash = "forged"
            db.add(run)
        else:
            call = service.demo_call(db, run_id)
            call.payload_json = call.payload_json.replace('"demo_only":true', '"demo_only":false')
            db.add(call)
        db.commit()
    assert client.get("/packet").status_code == 403
    assert client.post("/choices", json=body).status_code == 409
    assert counts(engine) == (0, 0)


def test_catalog_and_direct_routes_auth_expiry_revocation(fixture):
    engine, _, call_id, _, client, _ = fixture
    assert PATHS == {("GET", "/packet"), ("GET", "/receipt"), ("POST", "/choices")}
    for path in ("/trades", "/fills", "/accounts", "/practice/runs", "/advisor-shadow", "/paper", "/shell", "/http", "/jobs", "/docs", "/openapi.json"):
        assert client.get(path).status_code == 404
        assert client.post(path, json={}).status_code == 404
    assert client.get("/packet", headers={"authorization": "Bearer " + "x" * 43}).status_code == 403
    assert client.get("/packet?run=forged").status_code == 401
    assert client.get("/packet", headers={"cookie": "owner=forged"}).status_code == 401
    with Session(engine) as db:
        call = db.get(PracticeAgentCall, call_id)
        config = json.loads(call.config_json)
        config["expires_at"] = practice.iso(practice.now_utc() - timedelta(seconds=1))
        call.config_json = service.canonical(config)
        db.add(call)
        db.commit()
    assert client.get("/packet").status_code == 403
    with Session(engine) as db:
        service.set_enabled(db, call_id, False)
    assert client.get("/receipt").status_code == 403


def test_revocation_during_body_reception_denies_commit(fixture):
    engine, _, call_id, token, client, _ = fixture
    body = json.dumps(submission(client)).encode()

    async def exercise():
        async def chunks():
            yield body[:20]
            with Session(engine) as db:
                service.set_enabled(db, call_id, False)
            yield body[20:]
        transport = httpx.ASGITransport(app=build_app(engine, call_id))
        async with httpx.AsyncClient(transport=transport, base_url="http://demo") as caller:
            return await caller.post("/choices", content=chunks(), headers={"authorization": f"Bearer {token}"})
    assert asyncio.run(exercise()).status_code == 409
    assert counts(engine) == (0, 0)


def test_concurrent_exact_submissions_have_one_whole_batch(fixture):
    engine, _, call_id, token, client, _ = fixture
    body = submission(client)
    def submit():
        with Session(engine) as db:
            return service.submit(db, call_id, token, body)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: submit(), range(2)))
    assert results[0] == results[1]
    assert counts(engine) == (5, 0)


def test_body_deadline_and_four_request_concurrency_bound(fixture, monkeypatch):
    engine, _, call_id, token, client, _ = fixture
    body = json.dumps(submission(client)).encode()
    monkeypatch.setattr(advisor_shadow_demo, "BODY_TIMEOUT_SECONDS", 0.01)

    async def deadline():
        async def slow():
            yield body[:20]
            await asyncio.sleep(0.05)
            yield body[20:]
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=build_app(engine, call_id)), base_url="http://demo") as caller:
            return await caller.post("/choices", content=slow(), headers={"authorization": f"Bearer {token}"})
    assert asyncio.run(deadline()).status_code == 408
    assert counts(engine) == (0, 0)
    monkeypatch.setattr(advisor_shadow_demo, "BODY_TIMEOUT_SECONDS", 10)

    async def concurrency():
        waiting, release = asyncio.Event(), asyncio.Event()
        entered = 0
        async def held():
            nonlocal entered
            yield b"{"
            entered += 1
            if entered == 4:
                waiting.set()
            await release.wait()
            yield b"}"
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=build_app(engine, call_id)), base_url="http://demo") as caller:
            tasks = [asyncio.create_task(caller.post("/choices", content=held(), headers={"authorization": f"Bearer {token}"})) for _ in range(4)]
            await asyncio.wait_for(waiting.wait(), 2)
            fifth = await caller.get("/packet", headers={"authorization": f"Bearer {token}"})
            release.set()
            await asyncio.gather(*tasks)
            return fifth
    assert asyncio.run(concurrency()).status_code == 429
    assert counts(engine) == (0, 0)


def test_receipt_time_failure_rolls_back_whole_batch(fixture, monkeypatch):
    engine, _, _, _, client, _ = fixture
    body = submission(client)
    original = practice.choose
    calls = 0
    def fail_last(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 5:
            raise decisions.DecisionError("Receipt time failure")
        return original(*args, **kwargs)
    monkeypatch.setattr(practice, "choose", fail_last)
    assert client.post("/choices", json=body).status_code == 409
    assert counts(engine) == (0, 0)
    assert client.get("/receipt").json()["status"] == "awaiting_submission"


def test_capability_expiring_during_batch_rolls_back_every_choice(fixture, monkeypatch):
    engine, _, _, _, client, _ = fixture
    body = submission(client)
    original = practice.choose
    def expire_after_write(*args, **kwargs):
        result = original(*args, **kwargs)
        monkeypatch.setattr(practice, "now_utc", lambda: result.received_at + timedelta(hours=1))
        return result
    monkeypatch.setattr(practice, "choose", expire_after_write)
    assert client.post("/choices", json=body).status_code == 409
    assert counts(engine) == (0, 0)


@pytest.mark.parametrize("all_humans", [False, True])
def test_advisor_export_assistance_immutable_response_and_fact_citations(fixture, all_humans):
    engine, run_id, _, _, client, owner = fixture
    original = client.get("/packet").json()
    if all_humans:
        for opp in original["packet"]["opportunities"]:
            owner.post(f"/practice/opportunities/{opp['opportunity_id']}/choice", json={"decision": "skip", "rationale": "Frozen before advice"})
    request = {"question": "Is my SPY breakout plan supported?", "user_plan": "I would enter only after a 15m close above 100"}
    exported = owner.post(f"/advisor-shadow/runs/{run_id}/advisor-packet", json=request)
    assert exported.status_code == 200
    assert exported.json()["packet"] == original["packet"]
    assert exported.json()["comparison"] == ("independent" if all_humans else "assisted")
    assert owner.get(f"/practice/runs/{run_id}").json()["comparison"] == exported.json()["comparison"]
    assert client.get("/packet").json() == original
    assert owner.post(f"/advisor-shadow/runs/{run_id}/advisor-packet", json={**request, "user_plan": "changed"}).status_code == 409
    opp = original["packet"]["opportunities"][0]
    response = {"summary": "No verified TAKE is supported.", "interpretation": "The invented close is above 100; it does not establish a real breakout.",
        "risks": "Provider/calendar unknown; fixed stop and guard must be validated.",
        "conditions": "Obtain approved fresh raw facts/calendar, then validate the strict 15m trigger and frozen risk.",
        "gaps": "Real market evidence and news unavailable.",
        "references": [{"opportunity_id": opp["opportunity_id"], "fact_name": opp["price_facts"][0]["name"]}]}
    answer = owner.post(f"/advisor-shadow/runs/{run_id}/advisor-output", json=response)
    assert answer.status_code == 200
    assert answer.json()["advisor"]["response"] == response
    assert owner.post(f"/advisor-shadow/runs/{run_id}/advisor-output", json=response).json() == answer.json()
    bad = {**response, "references": [{"opportunity_id": str(uuid.uuid4()), "fact_name": "fake"}]}
    assert owner.post(f"/advisor-shadow/runs/{run_id}/advisor-output", json=bad).status_code == 409
    assert owner.get(f"/advisor-shadow/runs/{run_id}").json() == answer.json()
    assert "user_plan" not in json.dumps(client.get("/receipt").json())
    assert counts(engine) == (5 if all_humans else 0, 0)


def handoff(owner, run_id):
    result = owner.post(f"/advisor-shadow/runs/{run_id}/advisor-handoff", json={
        "question": "Is an invented close enough?", "user_plan": "Wait for verified prices and fixed risk"})
    assert result.status_code == 200
    exported = result.json()
    opp = exported["packet"]["opportunities"][0]
    envelope = {key: exported[key] for key in ("version", "assignment_id", "run_id", "packet_sha256", "request_sha256")}
    envelope["answer"] = {"summary": "Wait", "interpretation": "Invented evidence only", "risks": "Calendar unavailable",
        "conditions": "Verified prices and risk", "gaps": "Real prices unavailable",
        "references": [{"opportunity_id": opp["opportunity_id"], "fact_name": opp["price_facts"][0]["name"]}]}
    return exported, envelope


@pytest.mark.parametrize("all_humans", [False, True])
def test_handoff_durable_identity_receipt_and_phase1_isolation(fixture, all_humans):
    engine, run_id, call_id, token, client, owner = fixture
    shadow = client.get("/packet").json()
    if all_humans:
        for opp in shadow["packet"]["opportunities"]:
            assert owner.post(f"/practice/opportunities/{opp['opportunity_id']}/choice", json={"decision": "skip", "rationale": "Frozen blind"}).status_code == 200
    exported, envelope = handoff(owner, run_id)
    assert exported["assignment_id"] == str(call_id) and exported["run_id"] == str(run_id)
    assert exported["packet"] == shadow["packet"]
    assert exported["comparison"] == ("independent" if all_humans else "assisted")
    identity = {key: exported[key] for key in ("version", "assignment_id", "run_id", "packet_sha256", "expires_at", "requested_at", "comparison", "question", "user_plan")}
    assert service.digest(identity) == exported["request_sha256"]
    assert owner.get(f"/advisor-shadow/runs/{run_id}").json()["advisor"]["export"] == exported
    assert owner.post(f"/advisor-shadow/runs/{run_id}/advisor-handoff", json={"question": exported["question"], "user_plan": exported["user_plan"]}).json() == exported
    assert owner.post(f"/advisor-shadow/runs/{run_id}/advisor-handoff", json={"question": "changed", "user_plan": exported["user_plan"]}).status_code == 409
    saved = owner.post(f"/advisor-shadow/runs/{run_id}/advisor-import", json=envelope)
    assert saved.status_code == 200
    receipt = saved.json()["advisor"]["receipt"]
    assert receipt["submitted_output"] == envelope
    assert receipt["receipt_sha256"] == service.digest({k: v for k, v in receipt.items() if k != "receipt_sha256"})
    assert owner.post(f"/advisor-shadow/runs/{run_id}/advisor-import", json=envelope).json() == saved.json()
    changed = json.loads(json.dumps(envelope))
    changed["answer"]["summary"] = "Changed interpretation"
    assert owner.post(f"/advisor-shadow/runs/{run_id}/advisor-import", json=changed).status_code == 409
    assert owner.get(f"/advisor-shadow/runs/{run_id}").json() == saved.json()
    assert owner.post(f"/advisor-shadow/runs/{run_id}/advisor-output", json=envelope["answer"]).status_code == 409
    assert client.get("/packet").json() == shadow
    assert client.get("/receipt").json()["choices"] == []
    assert counts(engine) == (5 if all_humans else 0, 0)
    with Session(engine) as db:
        service.set_enabled(db, call_id, False)
    assert owner.post(f"/advisor-shadow/runs/{run_id}/advisor-import", json=envelope).status_code == 409
    assert owner.get(f"/advisor-shadow/runs/{run_id}").json() == saved.json()


@pytest.mark.parametrize("key", ["version", "assignment_id", "run_id", "packet_sha256", "request_sha256", "citation_id", "citation_name", "empty_citations"])
def test_handoff_tampered_identity_and_citations_refuse_without_receipt(fixture, key):
    _, run_id, _, _, _, owner = fixture
    _, envelope = handoff(owner, run_id)
    if key == "citation_id":
        envelope["answer"]["references"][0]["opportunity_id"] = str(uuid.uuid4())
    elif key == "citation_name":
        envelope["answer"]["references"][0]["fact_name"] = "invented_nonexistent"
    elif key == "empty_citations":
        envelope["answer"]["references"] = []
    else:
        envelope[key] = str(uuid.uuid4()) if key.endswith("_id") else "x" * len(envelope[key])
    result = owner.post(f"/advisor-shadow/runs/{run_id}/advisor-import", json=envelope)
    assert result.status_code in (409, 422)
    assert owner.get(f"/advisor-shadow/runs/{run_id}").json()["advisor"]["receipt"] is None


@pytest.mark.parametrize("revoked", [False, True])
def test_handoff_expiry_revocation_new_writes_refuse_saved_owner_record_recovers(fixture, monkeypatch, revoked):
    engine, run_id, call_id, _, _, owner = fixture
    exported, envelope = handoff(owner, run_id)
    if revoked:
        with Session(engine) as db:
            service.set_enabled(db, call_id, False)
    else:
        monkeypatch.setattr(practice, "now_utc", lambda: decisions._utc(exported["expires_at"], "expiry").replace(tzinfo=None))
    assert owner.post(f"/advisor-shadow/runs/{run_id}/advisor-import", json=envelope).status_code == 409
    assert owner.post(f"/advisor-shadow/runs/{run_id}/advisor-handoff", json={"question": exported["question"], "user_plan": exported["user_plan"]}).status_code == 409
    recovered = owner.get(f"/advisor-shadow/runs/{run_id}")
    assert recovered.status_code == 200 and recovered.json()["advisor"]["export"] == exported
    assert recovered.json()["advisor"]["receipt"] is None


@pytest.mark.parametrize("action", ["export", "import"])
def test_handoff_expiry_at_commit_rolls_back_disclosure_or_receipt(fixture, monkeypatch, action):
    engine, run_id, call_id, _, _, owner = fixture
    envelope = handoff(owner, run_id)[1] if action == "import" else None
    original = service.active_assignment
    calls = 0
    def expire_before_commit(config):
        nonlocal calls
        calls += 1
        if calls >= (3 if action == "import" else 2):
            monkeypatch.setattr(practice, "now_utc", lambda: decisions._utc(config["expires_at"], "expiry").replace(tzinfo=None))
        return original(config)
    monkeypatch.setattr(service, "active_assignment", expire_before_commit)
    if action == "export":
        result = owner.post(f"/advisor-shadow/runs/{run_id}/advisor-handoff", json={"question": "test", "user_plan": "wait"})
    else:
        result = owner.post(f"/advisor-shadow/runs/{run_id}/advisor-import", json=envelope)
    assert result.status_code == 409
    with Session(engine) as db:
        config = json.loads(db.get(PracticeAgentCall, call_id).config_json)
        if action == "export":
            assert "advisor" not in config and db.get(PracticeRun, run_id).comparison == "independent"
        else:
            assert config["advisor"]["receipt"] is None


def test_phase1_record_is_readable_without_new_identity_and_never_upgraded(fixture):
    engine, run_id, call_id, _, _, owner = fixture
    request = {"question": "legacy", "user_plan": "wait"}
    assert owner.post(f"/advisor-shadow/runs/{run_id}/advisor-packet", json=request).status_code == 200
    before = owner.get(f"/advisor-shadow/runs/{run_id}").json()
    assert "export" not in before["advisor"]
    assert owner.post(f"/advisor-shadow/runs/{run_id}/advisor-handoff", json=request).status_code == 409
    assert owner.get(f"/advisor-shadow/runs/{run_id}").json() == before
    with Session(engine) as db:
        assert json.loads(db.get(PracticeAgentCall, call_id).config_json)["advisor"] == before["advisor"]


def test_concurrent_handoff_import_exact_retry_and_conflict_share_one_receipt(fixture):
    engine, run_id, _, _, _, owner = fixture
    _, envelope = handoff(owner, run_id)
    changed = json.loads(json.dumps(envelope))
    changed["answer"]["summary"] = "Different answer"
    def save(body):
        with Session(engine) as db:
            try:
                return service.advisor_import(db, run_id, body)["advisor"]["receipt"]
            except decisions.DecisionError:
                return None
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(save, [envelope, envelope, changed]))
    saved = owner.get(f"/advisor-shadow/runs/{run_id}").json()["advisor"]["receipt"]
    assert saved is not None
    assert all(result is None or result == saved for result in results)
    assert any(result is None for result in results)
    assert save(saved["submitted_output"]) == saved


def test_revocation_committing_while_import_waits_for_writer_lock_refuses(fixture):
    from threading import Event
    engine, run_id, call_id, _, _, owner = fixture
    _, envelope = handoff(owner, run_id)
    started = Event()
    def waiting_import():
        started.set()
        with Session(engine) as db:
            with pytest.raises(decisions.DecisionError, match="expired or revoked"):
                service.advisor_import(db, run_id, envelope)
    with Session(engine) as revoker:
        service.lock(revoker)
        call = revoker.get(PracticeAgentCall, call_id)
        config = json.loads(call.config_json)
        config["enabled"] = False
        call.config_json = service.canonical(config)
        revoker.add(call)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(waiting_import)
            assert started.wait(1)
            revoker.commit()
            future.result(timeout=3)
    assert owner.get(f"/advisor-shadow/runs/{run_id}").json()["advisor"]["receipt"] is None
