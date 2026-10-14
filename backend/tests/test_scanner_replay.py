"""Signed MCP integration for sequential historical selection and exam sealing."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
import json
import time
from types import SimpleNamespace
import uuid

from fastapi.testclient import TestClient
import httpx
import pytest
from sqlmodel import Session, select

from app.engine import access, cloud_practice_access, decisions, scanner_replay as replay
from app.main import app
from app.models import AccessPrincipal, DecisionContext, DecisionEvent, DecisionRecord, Fill
from cloud_mcp_d1 import create_server
from tests.test_browser_access import boundary as boundary  # noqa: F401
from tests.test_cloud_mcp_d0 import signing_key as signing_key, _token, _jwks, _write_config, _request, PROFILE_ID, ISSUER, JWKS_URL  # noqa: F401
from tests.test_scanner_replay_market import bundle


def two_setup_bundle(day_shift=0):
    value = bundle()
    value["symbols"]["QQQ"] = deepcopy(value["symbols"]["SPY"])
    if day_shift:
        delta = day_shift * 86400
        value["session_date"] = (replay.date.fromisoformat(value["session_date"]) + timedelta(days=day_shift)).isoformat()
        value["open_at"] += delta
        value["close_at"] += delta
        value["retrieved_at"] = (decisions._utc(value["retrieved_at"], "retrieval") + timedelta(days=day_shift)).isoformat()+"Z"
        for source in value["symbols"].values():
            for bar in source["minutes"]:
                bar["time"] += delta
                bar["end_time"] += delta
    return value


@pytest.fixture
def linked(boundary, signing_key, tmp_path):
    b = boundary
    for flag in ("TJ_ACCESS_SAMPLE_DATA", "TJ_DOT_TRIAL_ENABLED", "TJ_MARKET_DECISION_WRITES", "TJ_HISTORICAL_REPLAY_ENABLED",
                 "TJ_CLOUD_MCP_ENABLED", "TJ_CLOUD_MCP_HISTORICAL_ENABLED", "TJ_CLOUD_MCP_DECISION_WRITES"):
        b.patch.setenv(flag, "true")
    for flag in ("market_decisions_isolated", "historical_replay_isolated", "cloud_mcp_sample_only"):
        b.patch.setattr(app.state, flag, True, raising=False)
    with Session(b.engine) as db:
        runs = replay.prepare_batch(db, [two_setup_bundle(), two_setup_bundle(1)], identifier="scanner-test", seed=47,
                                   exam_count=1)
        ids = [str(r.id) for r in runs]
    grants = {"symbols": list(replay.market.rules.UNIVERSE), "run_ids": ids, "journal_read": False,
              "market_decision_write": True, "historical_replay": True, "scanner_replay": True}
    made = b.owner.post("/access/assistants", json={"identifier": "scanner-test", "grants": grants})
    assert made.status_code == 201, made.text
    config, keys = tmp_path / "scanner.json", tmp_path / "keys.json"
    _write_config(config, sample_only=True, exercise_kind="scanner_replay", decision_writes=True,
        jwks_file=str(keys), backend_socket=str(tmp_path / "reads.sock"),
        profiles=[{"subject": "owner-subject", "id": PROFILE_ID, "enabled": True,
                   "principal_id": "scanner-test", "principal_version": 1}])
    now = int(time.time())
    keys.write_text(json.dumps({"issuer_url": ISSUER, "jwks_url": JWKS_URL, "fetched_at": now,
        "expires_at": now + 3600, "keys": _jwks(signing_key.public_key())["keys"]}))
    b.patch.setenv("TJ_CLOUD_MCP_CONFIG", str(config))
    cloud_practice_access.verifier.cache_clear()
    token = _token(signing_key, scope="d0:profile practice:read practice:write")
    with TestClient(app) as client:
        client.headers["authorization"] = "Bearer " + token
        yield SimpleNamespace(b=b, ids=ids, grants=grants, config=config, token=token, backend=client, signer=signing_key)
    cloud_practice_access.verifier.cache_clear()


def read(h, run_id=None):
    response = h.backend.get("/cloud-mcp/practice/runs/" + (run_id or h.ids[0]))
    assert response.status_code == 200, response.text
    return response.json()["run"]


def path(opportunity):
    return "/cloud-mcp/practice/opportunities/" + opportunity + "/choice"


def complete(h, run_id):
    value = read(h, run_id)
    while value["next_setup"]:
        opportunity = value["next_setup"]["opportunity_id"]
        response = h.backend.post(path(opportunity), json={"decision": "take", "rationale": "Frozen price-path selection"})
        assert response.status_code == 201, response.text
        value = read(h, run_id)
    return value


def test_actual_tool_protocol_resume_immutable_retry_and_practice_reveal(linked):
    h = linked
    server = create_server(h.config, backend_transport=httpx.ASGITransport(app=app))
    with TestClient(server.streamable_http_app()) as client:
        result = _request(client, "tools/call", {"name": "list_practice_runs", "arguments": {}}, h.token)["result"]
        assert not result.get("isError"), result
        run_id = result["structuredContent"]["runs"][0]["id"]
        assert result["structuredContent"]["runs"][0]["phase"] == "practice"
        value = read(h, run_id)
        assert value["report"] is None and value["outcomes_sealed"]
        assert "nonce" not in json.dumps(value) and "continuation" not in json.dumps(value)
        first_id = value["next_setup"]["opportunity_id"]
        args = {"opportunity_id": first_id, "decision": "insufficient_data", "rationale": "Historical option inputs unavailable"}
        saved = _request(client, "tools/call", {"name": "record_practice_choice", "arguments": args}, h.token)["result"]
        assert not saved.get("isError"), saved
        receipt = saved["structuredContent"]["choice"]
        assert receipt["wall_seconds"] >= 0 and receipt["status"] == "scanner_selection_unarmed"
        retry = _request(client, "tools/call", {"name": "record_practice_choice", "arguments": args}, h.token)["result"]
        assert retry["structuredContent"]["created"] is False
        assert retry["structuredContent"]["choice"] == receipt
        assert h.backend.post(path(first_id), json={"decision": "skip", "rationale": args["rationale"]}).status_code == 409
        assert read(h, run_id)["report"] is None
    # Recreate both verifiers/adapter, simulating an interrupted agent session.
    cloud_practice_access.verifier.cache_clear()
    resumed = create_server(h.config, backend_transport=httpx.ASGITransport(app=app))
    with TestClient(resumed.streamable_http_app()) as client:
        result = _request(client, "tools/call", {"name": "get_practice_run", "arguments": {"run_id": run_id, "resume": True}}, h.token)["result"]
        assert not result.get("isError"), result
        value = result["structuredContent"]["run"]
        assert value["next_setup"]["opportunity_id"] != first_id
        args = {"opportunity_id": value["next_setup"]["opportunity_id"], "decision": "skip", "rationale": "Skip next setup"}
        assert not _request(client, "tools/call", {"name": "record_practice_choice", "arguments": args}, h.token)["result"].get("isError")
    done = read(h, run_id)
    assert done["status"] == "committed" and done["report"] and not done["outcomes_sealed"]
    assert done["report"]["scorecard"]["decisions"] == {"take": 0, "skip": 1, "insufficient_data": 1}
    assert done["report"]["scorecard"]["sessions"] == 1
    assert done["choices"][0]["resumed"] is False
    assert done["choices"][1]["resumed"] is True
    assert done["choices"][1]["resumed_at"] is not None
    with Session(h.b.engine) as db:
        assert len(db.exec(select(DecisionRecord)).all()) == 2
        assert not db.exec(select(DecisionEvent)).all()


def test_normal_rereads_are_not_resume_and_terminal_receipts_stay_frozen(linked):
    first = read(linked)
    repeated = read(linked)
    assert first["next_setup"]["opportunity_id"] == repeated["next_setup"]["opportunity_id"]
    done = complete(linked, linked.ids[0])
    assert all(not choice["resumed"] for choice in done["choices"])
    response = linked.backend.get("/cloud-mcp/practice/runs/" + linked.ids[0], params={"resume": "true"})
    assert response.status_code == 200
    assert response.json()["run"]["choices"] == done["choices"]


def test_unstarted_resume_is_refused_and_future_coverage_stays_sealed(linked):
    response = linked.backend.get("/cloud-mcp/practice/runs/" + linked.ids[0], params={"resume": "true"})
    assert response.status_code == 404
    value = read(linked)
    assert value["coverage"] is None and value["daily_atr"] is None
    assert linked.backend.get("/cloud-mcp/practice/runs/" + linked.ids[0], params={"resume": "false"}).status_code == 422


def test_superseded_policy_rejects_new_choices_before_any_partial_commit(boundary):
    with Session(boundary.engine) as db:
        run = replay.prepare_batch(db, [two_setup_bundle()], identifier="legacy-test", seed=19)[0]
        # Compatibility fixture: a prepared session retained from the original
        # policy. No real v0 session was activated; these rows are disposable.
        meta = replay.metadata(run)
        meta["manifest"]["scoring_policy"] = replay.market._scoring_policy(replay.market.LEGACY_VERSION, 60, 0, 0)
        run.brief_json = replay.canonical(meta)
        run.policy_hash = replay.digest(meta["manifest"])
        db.add(run)
        db.commit()
        value = replay.view(db, run, "legacy-test", replay.market.rules.UNIVERSE, resume=True)
        assert value["read_only"] and value["next_setup"] is None
        with pytest.raises(decisions.DecisionError, match="read-only"):
            replay.choose(db, run, replay.entries(run)[0], "legacy-test", replay.market.rules.UNIVERSE,
                          {"decision": "skip", "rationale": "Must not partly change a superseded run"})
        assert not db.exec(select(DecisionRecord)).all()


def test_future_setup_denied_and_concurrent_receipt_recovery(linked):
    h = linked
    with Session(h.b.engine) as db:
        run = db.get(replay.PracticeRun, uuid.UUID(h.ids[0]))
        future_id = replay.entries(run)[1]["opportunity_id"]
    assert h.backend.get(path(future_id)).status_code == 404
    assert h.backend.post(path(future_id), json={"decision": "take", "rationale": "Guess future setup"}).status_code == 404
    first_id = read(h)["next_setup"]["opportunity_id"]
    with ThreadPoolExecutor(max_workers=4) as pool:
        statuses = list(pool.map(lambda _: h.backend.post(path(first_id), json={"decision": "take", "rationale": "Same immutable choice"}).status_code, range(4)))
    assert set(statuses) <= {200, 201} and statuses.count(201) == 1
    assert h.backend.get(path(first_id)).json()["choice"]["reason"] == "Same immutable choice"


def test_exam_batch_reveal_waits_for_every_commit(boundary):
    with Session(boundary.engine) as db:
        runs = replay.prepare_batch(db, [two_setup_bundle(), two_setup_bundle(1)], identifier="exam-test", seed=8, exam_count=2)
        symbols = replay.market.rules.UNIVERSE
        first, second = runs
        for entry in replay.entries(first):
            replay.view(db, first, "exam-test", symbols)
            replay.choose(db, first, entry, "exam-test", symbols, {"decision": "skip", "rationale": "Frozen exam choice"})
        assert replay.view(db, first, "exam-test", symbols)["report"] is None
        assert not replay.reveal_allowed(db, first)
        with pytest.raises(decisions.DecisionError, match="sealed"):
            replay.report(db, first)
        for entry in replay.entries(second):
            replay.view(db, second, "exam-test", symbols)
            replay.choose(db, second, entry, "exam-test", symbols, {"decision": "take", "rationale": "Frozen exam choice"})
        assert replay.reveal_allowed(db, first)
        value = replay.view(db, first, "exam-test", symbols)
        assert value["report"]["cumulative"]["exam"]["sessions"] == 2
        # Snapshot remains tied to the prompt/scoring policy after restart.
        again = replay.prepare_batch(db, [two_setup_bundle(), two_setup_bundle(1)], identifier="exam-test", seed=8, exam_count=2)
        assert {r.id for r in again} == {r.id for r in runs}
        with pytest.raises(decisions.DecisionError):
            replay.prepare_batch(db, [two_setup_bundle(), two_setup_bundle(1)], identifier="exam-test", seed=8, exam_count=2,
                                 prompt_text="Retune after an exam")


def test_practice_abandon_reveals_but_abandoned_exam_never_opens_batch(boundary):
    with Session(boundary.engine) as db:
        practice = replay.prepare_batch(db, [two_setup_bundle()], identifier="abandon-practice", seed=1)[0]
        replay.abandon(db, practice)
        assert replay.report(db, practice)["scorecard"]["uncommitted"] == 2
        exam = replay.prepare_batch(db, [two_setup_bundle()], identifier="abandon-exam", seed=1, exam_count=1)[0]
        replay.abandon(db, exam)
        assert not replay.reveal_allowed(db, exam)


def test_stable_split_and_frozen_holdout_guard():
    days = ["2026-08-25", "2026-08-26", "2026-08-27"]
    assert replay.split_dates(days, 33, 1) == replay.split_dates(list(reversed(days)), 33, 1)
    with pytest.raises(decisions.DecisionError, match="holdout"):
        replay.split_dates(["2026-09-14"], 1)
    assert replay.split_dates(["2026-09-14"], 1, allow_holdout=True) == {"2026-09-14": "practice"}


@pytest.mark.parametrize("flag", ["TJ_ACCESS_SAMPLE_DATA", "TJ_DOT_TRIAL_ENABLED", "TJ_HISTORICAL_REPLAY_ENABLED", "TJ_MARKET_DECISION_WRITES", "TJ_CLOUD_MCP_HISTORICAL_ENABLED"])
def test_disabled_flags_cannot_activate_scanner(linked, flag):
    first_id = read(linked)["next_setup"]["opportunity_id"]
    linked.b.patch.setenv(flag, "false")
    assert linked.backend.get("/cloud-mcp/practice/runs/" + linked.ids[0]).status_code in {403, 503}
    assert linked.backend.post(path(first_id), json={"decision": "skip", "rationale": "Denied"}).status_code in {403, 503}


def test_wrong_mode_scope_generic_projection_and_integrity(linked):
    h = linked
    first_id = read(h)["next_setup"]["opportunity_id"]
    readonly = _token(h.signer, scope="d0:profile practice:read")
    assert h.backend.post(path(first_id), headers={"authorization": "Bearer " + readonly}, json={"decision": "skip", "rationale": "Denied"}).status_code == 401
    assert h.b.owner.get("/practice/runs/" + h.ids[0]).status_code == 404
    assert h.backend.get("/fills").status_code in {401, 403}
    with Session(h.b.engine) as db:
        run = db.get(replay.PracticeRun, uuid.UUID(h.ids[0]))
        entry = replay.entries(run)[0]
        context = db.get(DecisionContext, uuid.UUID(entry["context_id"]))
        context.data_json += " "
        db.add(context)
        db.commit()
    assert h.backend.get("/cloud-mcp/practice/runs/" + h.ids[0]).status_code == 404
    config = json.loads(h.config.read_text())
    config["exercise_kind"] = "historical"
    h.config.write_text(json.dumps(config))
    assert h.backend.get("/cloud-mcp/practice/runs/" + h.ids[0]).status_code == 401


def test_revoke_during_body_reception_refuses_commit(linked):
    h = linked
    first_id = read(h)["next_setup"]["opportunity_id"]
    with Session(h.b.engine) as db:
        fills_before = [f.model_dump(mode="json") for f in db.exec(select(Fill)).all()]
    def body():
        yield b'{"decision":"skip",'
        with Session(h.b.engine) as db:
            principal = db.get(AccessPrincipal, "scanner-test")
            principal.enabled = False
            db.add(principal)
            db.commit()
        yield b'"rationale":"Must not survive revocation"}'
    assert h.backend.post(path(first_id), content=body(), headers={"content-type": "application/json"}).status_code == 403
    with Session(h.b.engine) as db:
        assert not db.exec(select(DecisionRecord)).all()
        assert fills_before == [f.model_dump(mode="json") for f in db.exec(select(Fill)).all()]


def test_no_historical_expiry_and_strict_choice_schema(linked):
    h = linked
    first_id = read(h)["next_setup"]["opportunity_id"]
    with Session(h.b.engine) as db:
        run = db.get(replay.PracticeRun, uuid.UUID(h.ids[0]))
        run.deadline = access.now() - timedelta(days=1)
        db.add(run)
        db.commit()
    assert h.backend.post(path(first_id), json={"decision": "wait", "rationale": "Wait not supported"}).status_code == 422
    assert h.backend.post(path(first_id), json={"decision": "take", "rationale": "Cannot change exits", "plan": {}}).status_code == 422
    assert h.backend.post(path(first_id), json={"decision": "take", "rationale": "Historical clocks do not expire the run"}).status_code == 201


def test_completed_batch_can_be_listed_without_nested_transactions(linked):
    for run_id in linked.ids:
        complete(linked, run_id)
    response = linked.backend.get("/cloud-mcp/practice/runs")
    assert response.status_code == 200, response.text
    assert len(response.json()["runs"]) == 2
    assert all(r["status"] == "committed" for r in response.json()["runs"])


def test_abandon_stale_operator_read_cannot_overwrite_final_commit(boundary):
    with Session(boundary.engine) as db:
        run = replay.prepare_batch(db, [two_setup_bundle()], identifier="race-test", seed=1, exam_count=1)[0]
        run_id = run.id
    with Session(boundary.engine) as operator_db:
        cached = operator_db.get(replay.PracticeRun, run_id)
        assert cached.status == "prepared"
        with Session(boundary.engine) as actor_db:
            current = actor_db.get(replay.PracticeRun, run_id)
            for entry in replay.entries(current):
                replay.view(actor_db, current, "race-test", replay.market.rules.UNIVERSE)
                replay.choose(actor_db, current, entry, "race-test", replay.market.rules.UNIVERSE,
                              {"decision": "skip", "rationale": "Commit before operator obtains lock"})
            assert current.status == "committed"
        with access._LOCK:
            access._serialized(operator_db)
            replay.abandon(operator_db, cached)
    with Session(boundary.engine) as db:
        final = db.get(replay.PracticeRun, run_id)
        assert final.status == "committed"
        assert replay.reveal_allowed(db, final)
