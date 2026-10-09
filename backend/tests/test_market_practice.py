"""Fixture-only real-source schema, storage, and authenticated denial checks."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import uuid

import pytest
from sqlmodel import Session, select
from starlette.middleware import Middleware

from app.engine import decisions, market_practice, paper, sample_practice
from app.main import app
from app.models import (
    DecisionContext,
    DecisionEvent,
    Fill,
    PracticeRun,
    PracticeOpportunity,
    JobRun,
)
from tests.test_browser_access import boundary as boundary, signin
from tests.test_dot_trial import trial

spec = importlib.util.spec_from_file_location(
    "market_capture",
    Path(__file__).resolve().parents[2] / "deploy/dot_market_capture.py",
)
capture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(capture)
UTC = timezone.utc


def bundle(at):
    day = at.astimezone(market_practice.ET).date()
    return {
        "version": 1,
        "captured_at": at.isoformat(),
        "day": day.isoformat(),
        "calendar": {
            "status": "open",
            "open": 570,
            "close": 960,
            "source": "alpaca_calendar",
        },
        "packets": {
            s: {
                "symbol": s,
                "data_source": "alpaca_iex",
                "missing": [],
                "recent_minute_bars": [
                    {
                        "t": (
                            at.replace(second=0, microsecond=0)
                            - timedelta(minutes=i + 1)
                        ).isoformat(),
                        "o": p,
                        "h": p + 2,
                        "l": p - 1,
                        "c": p,
                        "v": 100 + i,
                        "vw": p - 0.1,
                    }
                    for i in range(60)
                ],
            }
            for s, p in (("MU", 110), ("NBIS", 60))
        },
    }


@pytest.fixture
def market(boundary):
    at = (
        datetime.now(UTC)
        .astimezone(market_practice.ET)
        .replace(hour=15, minute=0, second=20, microsecond=0)
        .astimezone(UTC)
    )

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return at.astimezone(tz) if tz else at.replace(tzinfo=None)

    boundary.patch.setattr(market_practice, "datetime", Clock)
    boundary.patch.setattr(decisions, "datetime", Clock)
    for flag in (
        "TJ_ACCESS_SAMPLE_DATA",
        "TJ_DOT_TRIAL_ENABLED",
        "TJ_MARKET_DECISION_WRITES",
    ):
        boundary.patch.setenv(flag, "true")
    boundary.patch.setattr(app.state, "market_decisions_isolated", True, raising=False)
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
    with Session(boundary.engine) as db:
        run = market_practice.prepare(db, bundle(at), identifier="market-writer")
        opps = {
            o.symbol: o
            for o in db.exec(
                select(PracticeOpportunity).where(PracticeOpportunity.run_id == run.id)
            ).all()
        }
    grants = {
        "symbols": ["MU", "NBIS"],
        "run_ids": [str(run.id)],
        "journal_read": False,
        "market_decision_write": True,
    }
    created = boundary.owner.post(
        "/access/assistants", json={"identifier": "market-writer", "grants": grants}
    )
    assert created.status_code == 201, created.text
    boundary.key = created.json()["key"]
    assert signin(boundary, identifier="market-writer").status_code == 200
    return SimpleNamespace(**vars(boundary), run=run, opps=opps, at=at, grants=grants)


def choose(w, symbol="MU", **body):
    return w.public.post(
        f"/practice/opportunities/{w.opps[symbol].id}/agent-choice",
        json={"decision": "skip", "rationale": "Fixture decision only", **body},
    )


def plan(w):
    return {
        "instrument": "stock",
        "direction": "long",
        "trigger": decisions.POLICY_SPEC["trigger"],
        "trigger_level": 110,
        "trigger_fact": "minute:0:c",
        "stop": 109,
        "stop_fact": "minute:0:l",
        "target": 112,
        "target_fact": "minute:0:h",
        "entry_guard": {"min": 110, "max": 110.2},
        "expiry": (w.at + timedelta(minutes=30)).isoformat(),
        "max_holding_sessions": 2,
        "freshness_limit_seconds": 7200,
        "cost_model": paper.COST,
    }


def test_real_source_choice_retry_and_private_owner_review(market):
    response = choose(market, decision="take", plan=plan(market))
    assert response.status_code == 201, response.text
    data = response.json()
    assert (
        data["market_data"] is True
        and data["sample_data"] is False
        and data["replay_exercise"] is False
    )
    record = next(o["choice"] for o in data["opportunities"] if o["symbol"] == "MU")
    assert (
        record["policy_version"]
        == decisions.MARKET_POLICY_VERSION
        != decisions.POLICY_VERSION
    )
    assert record["plan"]["trigger_source"]["source"] == "alpaca_iex"
    assert record["plan"]["trigger_source"]["split_basis"] == "raw"
    assert record["input_cutoff"] == market.at.isoformat()
    assert choose(market, decision="take", plan=plan(market)).status_code == 200
    assert choose(market, rationale="Changed choice").status_code == 409
    assert market.public.get("/decisions/" + record["id"]).json() == record
    assert (
        market.owner.get(f"/practice/runs/{market.run.id}").json()["opportunities"][0][
            "choice"
        ]
        is not None
    )
    with Session(market.engine) as db:
        assert (
            db.exec(select(DecisionEvent)).all() == []
            and db.exec(select(Fill)).all() == []
        )
        with pytest.raises(paper.PaperError, match="different plan schema"):
            paper.arm(
                db, uuid.UUID(record["id"]), "no-arm", now=market.at, calendar=None
            )


def test_actor_run_symbol_and_provider_operations_denied(market):
    with Session(market.engine) as db:
        opp = market.opps["MU"]
        private, _ = decisions.create(
            db,
            {
                "operation_id": "private",
                "opportunity_id": f"a3:{opp.id}",
                "actor": "human",
                "symbol": "MU",
                "context_id": str(opp.context_id),
                "decision": "skip",
                "rationale": "SECRET HUMAN",
            },
            routine=True,
        )
        sample = sample_practice.prepare(db)
        private_id = str(private.id)
        sample_id = str(sample.id)
    assert (
        "SECRET HUMAN" not in market.public.get(f"/practice/runs/{market.run.id}").text
    )
    assert market.public.get("/decisions").json() == {"decisions": []}
    assert market.public.get("/decisions/" + private_id).status_code == 404
    assert market.public.get(f"/practice/runs/{sample_id}").status_code == 404
    for path in (
        "/fills",
        "/trades",
        "/accounts",
        "/stats",
        "/charts/workspace?symbol=MU&watchlist=MU",
        "/packets/analyze?symbol=MU",
    ):
        assert market.public.get(path).status_code == 403
    for path in (
        "/practice/prepare",
        "/decisions/context/MU",
        "/decisions",
        f"/practice/opportunities/{opp.id}/sample-replay",
        f"/practice/opportunities/{opp.id}/choice",
        f"/practice/opportunities/{opp.id}/reveal",
    ):
        assert market.public.post(path, json={}).status_code == 403
    assert (
        market.public.post(
            f"/practice/opportunities/{uuid.uuid4()}/agent-choice",
            json={"decision": "skip", "rationale": "guess"},
        ).status_code
        == 404
    )
    assert choose(market, actor="human").status_code == 422
    assert choose(market, context_id=str(opp.context_id)).status_code == 422


def test_deadline_stale_and_unavailable_source_refuse_take_but_preserve_retry(market):
    assert choose(market).status_code == 201
    with Session(market.engine) as db:
        run = db.get(PracticeRun, market.run.id)
        run.deadline = market.at.replace(tzinfo=None) - timedelta(seconds=1)
        db.add(run)
        db.commit()
    assert choose(market).status_code == 200
    assert choose(market, symbol="NBIS").status_code == 422
    with Session(market.engine) as db:
        run = db.get(PracticeRun, market.run.id)
        run.deadline = market.at.replace(tzinfo=None) + timedelta(minutes=30)
        ctx = db.get(DecisionContext, market.opps["NBIS"].context_id)
        issue = market_practice.take_unavailable(
            ctx, run, now=market.at.replace(tzinfo=None) + timedelta(minutes=6)
        )
        assert "older than five minutes" in issue
        data = json.loads(ctx.data_json)
        data["packet"]["recent_minute_bars"] = []
        ctx.data_json = decisions._canonical(data)
        ctx.context_sha256 = decisions._hash(ctx.data_json)
        db.add(ctx)
        db.add(run)
        db.commit()
    assert (
        choose(market, symbol="NBIS", decision="take", plan=plan(market)).status_code
        == 422
    )
    assert (
        choose(
            market,
            symbol="NBIS",
            decision="wait",
            wait_condition="Fresh data needed",
            wait_expiry=(market.at + timedelta(minutes=10)).isoformat(),
        ).status_code
        == 201
    )


def test_flags_factory_revocation_csrf_and_grant_expansion_denied(market):
    assert (
        market.public.post(
            f"/practice/opportunities/{market.opps['MU'].id}/agent-choice",
            json={"decision": "skip", "rationale": "x"},
            headers={"x-tj-csrf": "wrong"},
        ).status_code
        == 403
    )
    market.patch.setattr(app.state, "market_decisions_isolated", False)
    assert choose(market).status_code == 403
    market.patch.setattr(app.state, "market_decisions_isolated", True)
    market.patch.setenv("TJ_MARKET_DECISION_WRITES", "false")
    assert choose(market).status_code == 403
    market.patch.setenv("TJ_MARKET_DECISION_WRITES", "true")
    for extra in (
        {"journal_read": True},
        {"decision_write": True},
        {"sample_replay": True},
        {"symbols": ["SPY"]},
        {"run_ids": []},
    ):
        assert market.owner.post(
            "/access/assistants",
            json={"identifier": "bad-market", "grants": {**market.grants, **extra}},
        ).status_code in {403, 422}
    assert (
        market.owner.post(
            "/access/assistants/market-writer/revoke", json={}
        ).status_code
        == 200
    )
    assert choose(market).status_code == 401


def test_import_is_atomic_idempotent_and_keeps_original_cutoff(market):
    with Session(market.engine) as db:
        assert (
            market_practice.prepare(
                db, bundle(market.at), identifier="market-writer"
            ).id
            == market.run.id
        )
        changed = bundle(market.at)
        changed["packets"]["MU"]["recent_minute_bars"][0]["v"] += 1
        with pytest.raises(decisions.DecisionError, match="already frozen"):
            market_practice.prepare(db, changed, identifier="market-writer")
        before = {
            m: len(db.exec(select(m)).all())
            for m in (DecisionContext, PracticeRun, PracticeOpportunity, JobRun)
        }
        other = bundle(market.at - timedelta(days=1))
        original = decisions.freeze_context

        def fail(db, operation_id, symbol, packet, **kwargs):
            if symbol == "NBIS":
                raise RuntimeError("fixture interruption")
            return original(db, operation_id, symbol, packet, **kwargs)

        market.patch.setattr(decisions, "freeze_context", fail)
        with pytest.raises(RuntimeError):
            market_practice.prepare(db, other)
        assert {m: len(db.exec(select(m)).all()) for m in before} == before


@pytest.mark.parametrize(
    "mutation",
    [
        "secret",
        "future",
        "unfinished",
        "wrong_day",
        "duplicate",
        "simulated",
        "bad_ohlc",
        "unknown_calendar",
    ],
)
def test_handoff_refuses_invalid_or_unapproved_fields(market, mutation):
    data = deepcopy(bundle(market.at))
    p = data["packets"]["MU"]
    if mutation == "secret":
        p["api_key"] = "not permitted"
    if mutation == "future":
        data["captured_at"] = (market.at + timedelta(days=1)).isoformat()
    if mutation == "unfinished":
        p["recent_minute_bars"][0]["t"] = market.at.isoformat()
    if mutation == "wrong_day":
        data["day"] = "2020-01-01"
    if mutation == "duplicate":
        p["recent_minute_bars"][1] = p["recent_minute_bars"][0]
    if mutation == "simulated":
        p["data_source"] = "sample_fixture"
    if mutation == "bad_ohlc":
        p["recent_minute_bars"][0]["h"] = 1
    if mutation == "unknown_calendar":
        data["calendar"]["status"] = "unknown"
    with pytest.raises(decisions.DecisionError):
        market_practice.validate_bundle(data)


def test_capture_contract_only_reads_fixed_calendar_and_raw_bars(market):
    calls = []
    at = market.at

    def reader(url, params, keys):
        calls.append((url, params))
        if url.endswith("/calendar"):
            return [
                {
                    "date": at.astimezone(market_practice.ET).date().isoformat(),
                    "open": "09:30",
                    "close": "16:00",
                }
            ]
        assert (
            params["symbols"] in {"MU", "NBIS"}
            and params["adjustment"] == "raw"
            and params["feed"] == "iex"
        )
        return {
            "bars": {
                params["symbols"]: bundle(at)["packets"][params["symbols"]][
                    "recent_minute_bars"
                ]
            },
            "next_page_token": None,
        }

    result = capture.capture(
        {"ALPACA_API_KEY": "fixture-key", "ALPACA_API_SECRET": "fixture-secret"},
        reader=reader,
        now=at,
    )
    market_practice.validate_bundle(result)
    assert (
        len(calls) == 3
        and "fixture-key" not in json.dumps(result)
        and "fixture-secret" not in json.dumps(result)
    )
    assert (
        result["packets"]["MU"]["recent_minute_bars"]
        == bundle(at)["packets"]["MU"]["recent_minute_bars"]
    )
    failed = capture.capture(
        {},
        reader=lambda *args: pytest.fail("must not call without credentials"),
        now=at,
    )
    market_practice.validate_bundle(failed)
    assert failed["packets"]["MU"]["recent_minute_bars"] == []


def test_concurrent_retry_corruption_and_unassigned_agent_refusal(market):
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=2) as workers:
        responses = list(workers.map(lambda _: choose(market), range(2)))
    assert sorted(r.status_code for r in responses) == [200, 201]
    ids = [
        next(
            o["choice"]["id"] for o in r.json()["opportunities"] if o["symbol"] == "MU"
        )
        for r in responses
    ]
    assert ids[0] == ids[1]
    with Session(market.engine) as db:
        with pytest.raises(decisions.DecisionError, match="different agent"):
            market_practice.choose(
                db,
                market.run,
                market.opps["NBIS"],
                "another-agent",
                {"decision": "skip", "rationale": "No grant"},
            )
        ctx = db.get(DecisionContext, market.opps["NBIS"].context_id)
        ctx.data_json += " "
        db.add(ctx)
        db.commit()
    assert choose(market, symbol="NBIS").status_code == 422
    assert market.public.get(f"/practice/runs/{market.run.id}").status_code == 409


def test_large_market_body_and_extra_plan_fields_are_refused(market):
    assert (
        market.public.post(
            f"/practice/opportunities/{market.opps['MU'].id}/agent-choice",
            content='{"rationale":"' + "x" * 17000 + '"}',
            headers={"content-type": "application/json"},
        ).status_code
        == 413
    )
    assert (
        choose(
            market, decision="take", plan={**plan(market), "arbitrary": "not allowed"}
        ).status_code
        == 422
    )


def test_capture_missing_partial_and_holiday_never_substitute_fixture_prices(market):
    at = market.at

    def failing(url, params, keys):
        raise OSError("fixture-secret must never appear in exported error")

    failed = capture.capture(
        {"ALPACA_API_KEY": "fixture-key", "ALPACA_API_SECRET": "fixture-secret"},
        reader=failing,
        now=at,
    )
    market_practice.validate_bundle(failed)
    assert "fixture-secret" not in json.dumps(failed)
    assert len(failed["packets"]["MU"]["recent_minute_bars"]) == 0
    holiday = capture.capture(
        {"ALPACA_API_KEY": "fixture-key", "ALPACA_API_SECRET": "fixture-secret"},
        reader=lambda *args: [],
        now=at,
    )
    market_practice.validate_bundle(holiday)
    assert holiday["calendar"]["status"] == "closed"
    assert holiday["packets"]["NBIS"]["data_source"] == "unavailable"


def test_reusing_old_identity_does_not_poison_a_future_session(market):
    with Session(market.engine) as db:
        before = len(db.exec(select(PracticeRun)).all())
        other = bundle(market.at - timedelta(days=1))
        with pytest.raises(decisions.DecisionError, match="Existing identity"):
            market_practice.prepare(db, other, identifier="market-writer")
        assert len(db.exec(select(PracticeRun)).all()) == before


def test_unassigned_readers_cannot_read_market_runs_or_any_decision_projection(market):
    own = choose(market).json()["opportunities"][0]["choice"]
    # New grants refuse before exposing either a real writer or a read-only alias.
    for extra in ({"market_decision_write": True}, {"market_decision_write": False}):
        body = {"identifier": "unassigned", "grants": {**market.grants, **extra}}
        assert market.owner.post("/access/assistants", json=body).status_code == 403
    # Simulate a stale pre-existing administrative grant to prove projections
    # enforce assignment independently of grant creation validation.
    from app.models import AccessPrincipal

    # Reset the fixture account normally, then plant a stale administrative grant.
    reset = market.owner.post(
        "/access/assistants/dot/reset",
        json={
            "grants": {"symbols": ["MU", "NBIS"], "run_ids": [], "journal_read": False}
        },
    )
    assert reset.status_code == 200
    market.key = reset.json()["key"]
    assert signin(market, identifier="dot").status_code == 200
    with Session(market.engine) as db:
        other = db.get(AccessPrincipal, "dot")
        other.grants_json = json.dumps(
            {
                "symbols": ["MU", "NBIS"],
                "run_ids": [str(market.run.id)],
                "journal_read": False,
            }
        )
        db.add(other)
        db.commit()
    assert market.public.get(f"/practice/runs/{market.run.id}").status_code == 404
    assert market.public.get("/practice/runs").json() == {"runs": []}
    assert market.public.get("/decisions").json() == {"decisions": []}
    assert market.public.get("/decisions/" + own["id"]).status_code == 404
    assert (
        market.owner.post(
            "/access/assistants/dot/reset", json={"grants": market.grants}
        ).status_code
        == 403
    )
    with Session(market.engine) as db:
        with pytest.raises(decisions.DecisionError, match="Market session not found"):
            market_practice.view(db, market.run, "dot", ["MU"])
