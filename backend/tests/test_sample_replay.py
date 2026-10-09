"""Real scoped requests and durable sample events, including refusal and recovery."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace
import uuid

import pytest
from sqlmodel import Session, select
from starlette.middleware import Middleware

from app.engine import access, decisions, paper, sample_practice, sample_replay
from app.main import app
from app.models import (
    AccessPrincipal,
    DecisionContext,
    DecisionEvent,
    DecisionRecord,
    PracticeOpportunity,
    PracticeRun,
    Fill,
)
from tests.test_browser_access import boundary as boundary, signin
from tests.test_dot_trial import trial


@pytest.fixture
def replay(boundary, request):
    for name in (
        "TJ_ACCESS_SAMPLE_DATA",
        "TJ_DOT_TRIAL_ENABLED",
        "TJ_SAMPLE_DECISION_WRITES",
        "TJ_SAMPLE_REPLAY_ENABLED",
    ):
        boundary.patch.setenv(name, "true")
    boundary.patch.setattr(
        app,
        "user_middleware",
        [
            app.user_middleware[0],
            Middleware(trial.FixtureMarket),
            *app.user_middleware[1:],
        ],
    )
    boundary.patch.setattr(app, "middleware_stack", None)
    boundary.patch.setattr(app.state, "sample_replay_isolated", True, raising=False)
    if hasattr(request, "param"):
        boundary.patch.setattr(sample_replay.secrets, "choice", lambda _: request.param)
    with Session(boundary.engine) as db:
        run = sample_replay.prepare(db)
        opps = db.exec(
            select(PracticeOpportunity).where(PracticeOpportunity.run_id == run.id)
        ).all()
    grants = {
        "symbols": ["MU", "NBIS"],
        "run_ids": [str(run.id)],
        "journal_read": False,
        "decision_write": True,
        "sample_replay": True,
    }
    created = boundary.owner.post(
        "/access/assistants", json={"identifier": "replay-writer", "grants": grants}
    )
    assert created.status_code == 201, created.text
    boundary.key = created.json()["key"]
    assert signin(boundary, identifier="replay-writer").status_code == 200
    return SimpleNamespace(
        **vars(boundary), run=run, opps={o.symbol: o for o in opps}, grants=grants
    )


def saved(r, symbol="MU", kind="take", **extra):
    data = r.public.get(f"/practice/runs/{r.run.id}").json()
    opp = next(o for o in data["opportunities"] if o["symbol"] == symbol)
    body = {
        "decision": kind,
        "rationale": "Conditional sample plan, awaiting the unseen replay trigger.",
        **extra,
    }
    if kind == "take":
        body["plan"] = extra.get("plan", opp["context"]["packet"]["sample_plan"])
    response = r.public.post(
        f"/practice/opportunities/{opp['id']}/agent-choice", json=body
    )
    assert response.status_code == 201, response.text
    return next(
        o["choice"] for o in response.json()["opportunities"] if o["symbol"] == symbol
    )


def start(r, selected="MU", **body):
    return r.public.post(
        f"/practice/opportunities/{r.opps[selected].id}/sample-replay", json=body
    )


def result(response, symbol="MU"):
    assert response.status_code in (200, 201), response.text
    return next(
        o["replay"] for o in response.json()["opportunities"] if o["symbol"] == symbol
    )


@pytest.mark.parametrize("replay", ["stop", "target"], indirect=True)
def test_sealed_continuation_hidden_then_one_complete_durable_replay(replay):
    before = replay.public.get(f"/practice/runs/{replay.run.id}")
    assert (
        '"nonce"' not in before.text
        and '"continuation"' not in before.text
        and '"benchmark"' not in before.text
    )
    record = saved(replay)
    assert record["policy_version"] == decisions.REPLAY_POLICY_VERSION
    assert '"nonce"' not in json.dumps(record)
    first = start(replay)
    assert first.status_code == 201
    receipt = result(first)
    assert receipt["status"] == "closed" and receipt["simulated"] is True
    assert [e["type"] for e in receipt["events"]] == [
        "armed",
        "trigger",
        "order_intent",
        "entry",
        "exit",
    ]
    assert (
        receipt["events"][3]["at"] == 1860
    )  # next full minute after detection at 1802
    assert receipt["outcome"]["entry_fill"] == pytest.approx(110.22102)
    expected = 3.75758 if receipt["outcome"]["exit_kind"] == "target" else -2.24182
    assert receipt["outcome"]["net_per_share"] == pytest.approx(expected)
    assert receipt["outcome"]["planned_r"] == pytest.approx(expected / 2)
    stress = 3.67274 if receipt["outcome"]["exit_kind"] == "target" else -2.32546
    assert receipt["outcome_x3"]["net_per_share"] == pytest.approx(stress)
    assert receipt["tape_sha256"] == record["evidence"]["packet"]["replay_commitment"]
    assert receipt["commitment_verified"] is True
    assert result(start(replay)) == receipt
    reopened = replay.public.get(f"/practice/runs/{replay.run.id}").json()
    assert (
        next(o["replay"] for o in reopened["opportunities"] if o["symbol"] == "MU")
        == receipt
    )
    assert replay.public.get("/decisions/" + record["id"]).json() == record
    with Session(replay.engine) as db:
        rows = db.exec(select(DecisionEvent)).all()
        assert len(rows) == 6 and len({row.key for row in rows}) == 6
        assert all(
            row.event_type.startswith("sample_replay_")
            and row.source == sample_replay.SOURCE
            and row.delivery == "none"
            for row in rows
        )
        assert paper._armed_rows(db) == []
        assert db.exec(select(Fill)).all() == []
        # P0 arm must refuse even the sample replay's matching retry operation.
        with pytest.raises(paper.PaperError, match="different plan schema"):
            paper.arm(
                db,
                uuid.UUID(record["id"]),
                f"sample-replay:{record['id']}",
                now=datetime.now(timezone.utc),
                calendar=None,
            )
        with pytest.raises(LookupError):
            paper.paper_row(db, uuid.UUID(record["id"]))


@pytest.mark.parametrize("decision", ["wait", "skip"])
def test_wait_and_skip_never_create_replay_events(replay, decision):
    args = (
        {
            "wait_condition": "Confirm later",
            "wait_expiry": (
                datetime.now(timezone.utc) + timedelta(hours=1)
            ).isoformat(),
        }
        if decision == "wait"
        else {}
    )
    saved(replay, kind=decision, **args)
    assert start(replay).status_code == 422
    with Session(replay.engine) as db:
        assert db.exec(select(DecisionEvent)).all() == []


@pytest.mark.parametrize(
    "forged",
    [
        {"actor": "human"},
        {"operation_id": "change"},
        {"plan": {}},
        {"symbol": "SPY"},
        {"continuation": {}},
    ],
)
def test_no_client_override_fields(replay, forged):
    saved(replay)
    assert start(replay, **forged).status_code == 422
    with Session(replay.engine) as db:
        assert db.exec(select(DecisionEvent)).all() == []


def test_capability_flags_csrf_expiry_and_revocation_refuse(replay):
    saved(replay)
    path = f"/practice/opportunities/{replay.opps['MU'].id}/sample-replay"
    assert (
        replay.public.post(path, json={}, headers={"x-tj-csrf": "forged"}).status_code
        == 403
    )
    replay.patch.setenv("TJ_SAMPLE_REPLAY_ENABLED", "false")
    assert start(replay).status_code == 403
    replay.patch.setenv("TJ_SAMPLE_REPLAY_ENABLED", "true")
    with Session(replay.engine) as db:
        run = db.get(PracticeRun, replay.run.id)
        run.deadline = access.now() - timedelta(seconds=1)
        db.add(run)
        db.commit()
    assert start(replay).status_code == 422
    assert (
        replay.owner.post(
            "/access/assistants/replay-writer/revoke", json={}
        ).status_code
        == 200
    )
    assert start(replay).status_code == 401
    with Session(replay.engine) as db:
        assert db.exec(select(DecisionEvent)).all() == []


def test_old_sample_decisions_remain_unarmed_and_cannot_replay(replay):
    with Session(replay.engine) as db:
        old = sample_practice.prepare(db)
        opp = db.exec(
            select(PracticeOpportunity).where(PracticeOpportunity.run_id == old.id)
        ).first()
    assert replay.public.post(
        f"/practice/opportunities/{opp.id}/sample-replay", json={}
    ).status_code in (403, 404)
    assert (
        replay.public.post(
            f"/decisions/{uuid.uuid4()}/arm", json={"operation_id": "forged"}
        ).status_code
        == 403
    )
    assert replay.public.get("/fills").status_code == 403
    assert replay.public.post("/practice/prepare", json={}).status_code == 403


def test_other_actor_and_read_only_inspector_cannot_see_continuation(replay):
    saved(replay)
    receipt = result(start(replay))
    created = replay.owner.post(
        "/access/assistants", json={"identifier": "other", "grants": replay.grants}
    )
    replay.key = created.json()["key"]
    assert signin(replay, identifier="other").status_code == 200
    body = replay.public.get(f"/practice/runs/{replay.run.id}")
    assert receipt["receipt_sha256"] not in body.text and '"nonce"' not in body.text
    assert all(
        o["replay"] is None and o["choice"] is None
        for o in body.json()["opportunities"]
    )
    assert start(replay).status_code == 422
    inspector = {**replay.grants, "decision_write": False, "sample_replay": False}
    created = replay.owner.post(
        "/access/assistants", json={"identifier": "inspector", "grants": inspector}
    )
    replay.key = created.json()["key"]
    assert signin(replay, identifier="inspector").status_code == 200
    body = replay.public.get(f"/practice/runs/{replay.run.id}")
    assert '"nonce"' not in body.text and '"benchmark"' not in body.text
    assert start(replay).status_code == 403


@pytest.mark.parametrize(
    "change",
    [{"decision_write": False}, {"sample_replay": "true"}, {"journal_read": True}],
)
def test_replay_permission_is_explicit_and_bounded(replay, change):
    response = replay.owner.post(
        "/access/assistants",
        json={"identifier": "bad-replay", "grants": {**replay.grants, **change}},
    )
    assert response.status_code in (403, 422)


def test_tampered_continuation_and_plan_refused(replay):
    saved(replay)
    with Session(replay.engine) as db:
        opp = db.get(PracticeOpportunity, replay.opps["MU"].id)
        payload = json.loads(opp.benchmark_json)
        payload["minutes"][-1]["h"] += 1
        opp.benchmark_json = json.dumps(payload)
        db.add(opp)
        db.commit()
    assert start(replay).status_code == 422
    with Session(replay.engine) as db:
        assert db.exec(select(DecisionEvent)).all() == []


def test_concurrent_starts_have_exactly_one_immutable_receipt(replay):
    saved(replay)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: start(replay), range(2)))
    assert sorted(r.status_code for r in responses) == [200, 201]
    assert result(responses[0]) == result(responses[1])
    with Session(replay.engine) as db:
        assert len(db.exec(select(DecisionEvent)).all()) == 6


def test_failure_before_commit_rolls_back_whole_replay_and_retry_recovers(
    replay, monkeypatch
):
    saved(replay)
    commit = Session.commit
    failed = []

    def interrupt(db):
        if not failed and any(isinstance(row, DecisionEvent) for row in db.new):
            failed.append(True)
            db.flush()
            raise RuntimeError("simulated process interruption")
        return commit(db)

    monkeypatch.setattr(Session, "commit", interrupt)
    with pytest.raises(RuntimeError, match="process interruption"):
        start(replay)
    with Session(replay.engine) as db:
        assert db.exec(select(DecisionEvent)).all() == []
    assert start(replay).status_code == 201
    assert start(replay).status_code == 200


def test_preparation_resumes_with_original_sealed_nonce(boundary, monkeypatch):
    for name in (
        "TJ_ACCESS_SAMPLE_DATA",
        "TJ_DOT_TRIAL_ENABLED",
        "TJ_SAMPLE_DECISION_WRITES",
        "TJ_SAMPLE_REPLAY_ENABLED",
    ):
        boundary.patch.setenv(name, "true")
    freeze = decisions.freeze_context
    failed = []

    def interrupt(*args):
        value = freeze(*args)
        if not failed:
            failed.append(True)
            raise RuntimeError("after frozen context commit")
        return value

    monkeypatch.setattr(decisions, "freeze_context", interrupt)
    with Session(boundary.engine) as db:
        with pytest.raises(RuntimeError):
            sample_replay.prepare(db)
    with Session(boundary.engine) as db:
        original = db.exec(select(PracticeOpportunity)).first().benchmark_json
        run = sample_replay.prepare(db)
        opp = db.exec(
            select(PracticeOpportunity).where(
                PracticeOpportunity.run_id == run.id, PracticeOpportunity.symbol == "MU"
            )
        ).one()
        assert opp.benchmark_json == original
        context = db.get(DecisionContext, opp.context_id)
        assert json.loads(context.data_json)["packet"][
            "replay_commitment"
        ] == decisions._hash(decisions._canonical(json.loads(original)))


@pytest.mark.parametrize(
    "flag",
    [
        "TJ_ACCESS_ENABLED",
        "TJ_ACCESS_SAMPLE_DATA",
        "TJ_DOT_TRIAL_ENABLED",
        "TJ_SAMPLE_DECISION_WRITES",
        "TJ_SAMPLE_REPLAY_ENABLED",
    ],
)
def test_every_required_flag_fails_closed(replay, flag):
    saved(replay)
    replay.patch.setenv(flag, "false")
    assert start(replay).status_code >= 400
    with Session(replay.engine) as db:
        assert db.exec(select(DecisionEvent)).all() == []


def test_replay_grant_removed_after_save_and_historical_retry_after_deadline(replay):
    saved(replay)
    with Session(replay.engine) as db:
        principal = db.get(AccessPrincipal, "replay-writer")
        principal.grants_json = json.dumps({**replay.grants, "sample_replay": False})
        db.add(principal)
        db.commit()
    assert start(replay).status_code == 403
    with Session(replay.engine) as db:
        principal = db.get(AccessPrincipal, "replay-writer")
        principal.grants_json = json.dumps(replay.grants)
        db.add(principal)
        db.commit()
    receipt = result(start(replay))
    with Session(replay.engine) as db:
        run = db.get(PracticeRun, replay.run.id)
        run.deadline = access.now() - timedelta(seconds=1)
        db.add(run)
        db.commit()
    assert result(start(replay)) == receipt  # replay receipt, never a fresh run
    assert start(replay, "NBIS").status_code == 422
    replay.patch.setenv("TJ_SAMPLE_REPLAY_ENABLED", "false")
    assert start(replay).status_code == 403
    assert replay.public.get(f"/practice/runs/{replay.run.id}").status_code == 200


def test_partial_replay_run_never_exposes_tape_to_inspector(replay):
    created = replay.owner.post(
        "/access/assistants",
        json={
            "identifier": "read-partial",
            "grants": {
                **replay.grants,
                "decision_write": False,
                "sample_replay": False,
            },
        },
    )
    replay.key = created.json()["key"]
    assert signin(replay, identifier="read-partial").status_code == 200
    with Session(replay.engine) as db:
        run = db.get(PracticeRun, replay.run.id)
        run.status = "preparing"
        db.add(run)
        db.commit()
    response = replay.public.get(f"/practice/runs/{replay.run.id}")
    assert response.status_code == 404 and "nonce" not in response.text


def test_changed_plan_refuses_replay(replay):
    response = replay.public.get(f"/practice/runs/{replay.run.id}").json()
    plan = response["opportunities"][0]["context"]["packet"]["sample_plan"]
    plan["entry_guard"]["max"] -= 0.1
    saved(replay, plan=plan)
    assert start(replay).status_code == 422
    with Session(replay.engine) as db:
        assert db.exec(select(DecisionEvent)).all() == []


def test_five_flags_alone_do_not_enable_replay_on_normal_app(replay):
    saved(replay)
    replay.patch.setattr(app.state, "sample_replay_isolated", False)
    assert replay.public.get("/access/me").json()["sample_replay_enabled"] is False
    assert start(replay).status_code == 403
    with Session(replay.engine) as db:
        assert db.exec(select(DecisionEvent)).all() == []


def test_browser_integer_json_preserves_original_decision_hash(replay):
    data = replay.public.get(f"/practice/runs/{replay.run.id}").json()
    plan = data["opportunities"][0]["context"]["packet"]["sample_plan"]
    plan.update(
        trigger_level=110, stop=108, target=114, entry_guard={"min": 110, "max": 110.5}
    )
    record = saved(replay, plan=plan)
    assert start(replay).status_code == 201
    assert (
        replay.public.get("/decisions/" + record["id"]).json()["record_sha256"]
        == record["record_sha256"]
    )


def check_concurrent_replay_store(engine, monkeypatch):
    """Shared SQLite/Postgres transaction check; does not substitute for HTTP auth tests."""
    from app.models import AccessSession
    from app.engine import paper_execution as px
    from threading import Barrier

    for flag in (
        "TJ_ACCESS_ENABLED",
        "TJ_ACCESS_SAMPLE_DATA",
        "TJ_DOT_TRIAL_ENABLED",
        "TJ_SAMPLE_DECISION_WRITES",
        "TJ_SAMPLE_REPLAY_ENABLED",
    ):
        monkeypatch.setenv(flag, "true")
    identity = "parity-replay-" + uuid.uuid4().hex[:12]
    token = access.digest(identity)
    with Session(engine) as db:
        run = sample_replay.prepare(db)
        opp = db.exec(
            select(PracticeOpportunity).where(
                PracticeOpportunity.run_id == run.id, PracticeOpportunity.symbol == "MU"
            )
        ).one()
        grants = {
            "symbols": ["MU", "NBIS"],
            "run_ids": [str(run.id)],
            "journal_read": False,
            "decision_write": True,
            "sample_replay": True,
        }
        db.add(
            AccessPrincipal(
                id=identity,
                grants_json=json.dumps(grants),
                credential_expires_at=access.now() + timedelta(hours=1),
            )
        )
        db.commit()
        db.add(
            AccessSession(
                digest=token,
                principal_id=identity,
                audience="assistant",
                version=1,
                csrf="test",
                expires_at=access.now() + timedelta(hours=1),
            )
        )
        db.commit()
        context = db.get(DecisionContext, opp.context_id)
        record, _ = sample_practice.choose(
            db,
            run,
            opp,
            identity,
            {
                "decision": "take",
                "rationale": "Store parity only",
                "plan": json.loads(context.data_json)["packet"]["sample_plan"],
            },
        )
        opp_id, record_id = opp.id, record.id
    who = access.Identity(
        identity, "assistant", grants=grants, session_digest=token, csrf="test"
    )
    gate = Barrier(2)

    def execute(_):
        with Session(engine) as db:
            gate.wait(timeout=10)
            _, created = sample_replay.start(db, opp_id, who)
            return created, sample_replay.view(db, db.get(DecisionRecord, record_id))

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(execute, range(2)))
    assert sorted(r[0] for r in results) == [False, True]
    assert results[0][1] == results[1][1]
    with Session(engine) as db:
        rows = db.exec(
            select(DecisionEvent).where(DecisionEvent.record_id == record_id)
        ).all()
        assert len(rows) == 6
        assert sum(r.event_type == "sample_replay_entry" for r in rows) == 1
        assert sum(r.event_type == "sample_replay_exit" for r in rows) == 1
        record = db.get(DecisionRecord, record_id)
        assert (
            px.terms_from_plan(json.loads(record.decision_json)["plan"]).risk_per_share
            == 2
        )


def test_shared_replay_transaction_check_on_sqlite(replay, monkeypatch):
    check_concurrent_replay_store(replay.engine, monkeypatch)
