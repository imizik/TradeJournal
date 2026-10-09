"""Retrospective fixtures: separate clocks, sealed ownership and deterministic paper outcomes."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time, timedelta, timezone
import json
from types import SimpleNamespace
import uuid
import importlib.util
from pathlib import Path

import pytest
from sqlmodel import Session, select

from app.engine import access, decisions, historical_replay as history, paper
from app.main import app
from app.models import AccessPrincipal, DecisionContext, DecisionEvent, DecisionRecord, JobRun, PracticeOpportunity, PracticeRun
from scripts.historical_trial_fixture import bundle
from tests.test_browser_access import boundary as boundary, signin


def plan(context):
    packet = json.loads(context.data_json)["packet"]
    base = 110 if context.symbol == "MU" else 60
    return {"instrument": "stock", "direction": "long", "trigger": decisions.POLICY_SPEC["trigger"],
        "trigger_level": base, "trigger_fact": "minute:0:c", "stop": base-1, "stop_fact": "minute:0:l",
        "target": base+4, "target_fact": "minute:0:h", "entry_guard": {"min": base, "max": base+.5},
        "expiry": packet["plan_expiry_max"], "max_holding_sessions": 2,
        "freshness_limit_seconds": 7200, "cost_model": paper.COST}


@pytest.fixture
def historical(boundary):
    for name in ("TJ_ACCESS_SAMPLE_DATA", "TJ_DOT_TRIAL_ENABLED", "TJ_MARKET_DECISION_WRITES", "TJ_HISTORICAL_REPLAY_ENABLED"):
        boundary.patch.setenv(name, "true")
    for name in ("market_decisions_isolated", "historical_replay_isolated"):
        boundary.patch.setattr(app.state, name, True, raising=False)
    original = bundle()
    with Session(boundary.engine) as db:
        run = history.prepare(db, original, identifier="history-test", proof=True)
        run_id = run.id
        opps = db.exec(select(PracticeOpportunity).where(PracticeOpportunity.run_id == run.id)).all()
        ids = {o.symbol: o.id for o in opps}
        mu = next(o for o in opps if o.symbol == "MU")
        context = db.get(DecisionContext, mu.context_id)
        terms = plan(context)
    grants = {"symbols": ["MU", "NBIS"], "run_ids": [str(run_id)], "journal_read": False,
        "market_decision_write": True, "historical_replay": True}
    made = boundary.owner.post("/access/assistants", json={"identifier": "history-test", "grants": grants})
    assert made.status_code == 201, made.text
    assert signin(boundary, identifier="history-test", key=made.json()["key"]).status_code == 200
    return SimpleNamespace(b=boundary, original=original, run_id=run_id, ids=ids, plan=terms, grants=grants)


def choose(h, symbol="MU", decision="take"):
    body = {"decision": decision, "rationale": "Historical fixture choice; no live performance claim"}
    if decision == "take":
        body["plan"] = h.plan
    if decision == "wait":
        body.update(wait_condition="Historical test condition", wait_expiry=h.plan["expiry"])
    return h.b.public.post(f"/practice/opportunities/{h.ids[symbol]}/agent-choice", json=body)


def start(h, symbol="MU"):
    return h.b.public.post(f"/practice/opportunities/{h.ids[symbol]}/historical-replay", json={})


def test_separate_original_clocks_choices_sealed_replay_and_exact_costs(historical):
    h = historical
    before = h.b.public.get(f"/practice/runs/{h.run_id}").json()
    assert before["historical_replay"] and not before["sample_data"]
    assert "nonce" not in json.dumps(before) and "continuation" not in json.dumps(before)
    mu = next(o for o in before["opportunities"] if o["symbol"] == "MU")
    assert mu["take_unavailable"] is None and mu["replay"] is None
    assert mu["context"]["captured_at"] == h.original["captured_at"]
    assert len(mu["context"]["packet"]["recent_minute_bars"]) == 60
    assert all(f["observed_at"] == h.original["captured_at"] for f in mu["context"]["price_facts"])
    assert choose(h).status_code == 201
    saved = next(o for o in h.b.public.get(f"/practice/runs/{h.run_id}").json()["opportunities"] if o["symbol"] == "MU")
    assert saved["choice"]["policy_version"] == decisions.HISTORICAL_POLICY_VERSION
    assert decisions._utc(saved["choice"]["input_cutoff"], "cutoff") == decisions._utc(h.original["simulated_as_of"], "cutoff")
    assert decisions._utc(saved["choice"]["received_at"], "receipt") > decisions._utc(h.original["captured_at"], "retrieval")
    assert saved["replay"] is None
    assert choose(h).status_code == 200
    replay = start(h)
    assert replay.status_code == 201, replay.text
    done = next(o for o in replay.json()["opportunities"] if o["symbol"] == "MU")
    value = done["replay"]
    assert done["choice"] == saved["choice"]
    assert value["status"] == "closed" and value["commitment_verified"]
    assert [e["type"] for e in value["events"]] == ["armed", "trigger", "order_intent", "entry", "exit"]
    assert value["outcome"]["entry_fill"] == pytest.approx(110.22102)
    assert value["outcome"]["exit_fill"] == pytest.approx(113.9786)
    assert value["outcome"]["net_per_share"] == pytest.approx(3.75758)
    assert value["outcome"]["planned_r"] == pytest.approx(3.75758)
    assert value["outcome_x3"]["net_per_share"] == pytest.approx(3.67274)
    assert start(h).status_code == 200
    assert next(o for o in start(h).json()["opportunities"] if o["symbol"] == "MU")["replay"] == value
    assert h.b.owner.get(f"/practice/runs/{h.run_id}").json() == replay.json()
    with Session(h.b.engine) as db:
        record = db.get(DecisionRecord, uuid.UUID(done["choice"]["id"]))
        assert record.policy_hash == decisions.HISTORICAL_POLICY_HASH
        with pytest.raises(paper.PaperError):
            paper.arm(db, record.id, "forbidden", now=access.now(), calendar=None)
        db.rollback()
        with pytest.raises(LookupError):
            paper.paper_row(db, record.id)
        events = db.exec(select(DecisionEvent).where(DecisionEvent.record_id == record.id)).all()
        assert len(events) == 6 and all(e.delivery == "none" and e.source == history.SOURCE for e in events)
        assert all(e.effective_at < e.recorded_at for e in events)


@pytest.mark.parametrize("decision", ["wait", "skip"])
def test_wait_skip_never_reveal_or_replay(historical, decision):
    h = historical
    assert choose(h, "NBIS", decision).status_code == 201
    assert start(h, "NBIS").status_code == 422
    view = h.b.public.get(f"/practice/runs/{h.run_id}").json()
    assert "nonce" not in json.dumps(view) and all(o["replay"] is None for o in view["opportunities"])
    with Session(h.b.engine) as db:
        assert not db.exec(select(DecisionEvent)).all()


def test_flags_factory_csrf_foreign_grants_live_routes_and_revocation(historical):
    h = historical
    for field in ("historical_replay", "market_decision_write"):
        grants = {**h.grants, field: False}
        r = h.b.owner.post("/access/assistants", json={"identifier": "other-history", "grants": grants})
        assert r.status_code == 403
    assert choose(h).status_code == 201
    endpoint = f"/practice/opportunities/{h.ids['MU']}/historical-replay"
    assert h.b.public.post(endpoint, headers={"x-tj-csrf": "wrong"}, json={}).status_code == 403
    assert h.b.public.post(endpoint, json={"clock": "forged"}).status_code == 422
    for path in ("/fills", "/trades", "/packets/analyze?symbol=MU", "/cloud-mcp/d1/runs"):
        assert h.b.public.get(path).status_code in {403, 404}
    assert h.b.public.post(f"/practice/opportunities/{h.ids['MU']}/sample-replay", json={}).status_code == 403
    h.b.patch.setenv("TJ_HISTORICAL_REPLAY_ENABLED", "false")
    assert start(h).status_code == 403
    assert choose(h, "NBIS", "skip").status_code == 403
    h.b.patch.setenv("TJ_HISTORICAL_REPLAY_ENABLED", "true")
    h.b.patch.setattr(app.state, "historical_replay_isolated", False)
    assert start(h).status_code == 403
    h.b.patch.setattr(app.state, "historical_replay_isolated", True)
    assert h.b.owner.post("/access/assistants/history-test/revoke", json={}).status_code == 200
    assert start(h).status_code == 401


def test_expiry_exact_retry_integrity_and_atomic_failed_import(historical):
    h = historical
    assert choose(h).status_code == 201
    with Session(h.b.engine) as db:
        run = db.get(PracticeRun, h.run_id)
        run.deadline = access.now()-timedelta(seconds=1)
        db.add(run)
        db.commit()
    assert choose(h).status_code == 200
    assert choose(h, "NBIS", "skip").status_code == 422
    assert start(h).status_code == 422
    with Session(h.b.engine) as db:
        run = db.get(PracticeRun, h.run_id)
        run.deadline = access.now()+timedelta(hours=1)
        opp = db.get(PracticeOpportunity, h.ids["MU"])
        sealed = json.loads(opp.benchmark_json)
        sealed["minutes"][0]["c"] += .1
        opp.benchmark_json = decisions._canonical(sealed)
        db.add(run)
        db.add(opp)
        db.commit()
    assert start(h).status_code == 422
    with Session(h.b.engine) as db:
        assert not db.exec(select(DecisionEvent)).all()
        original = deepcopy(h.original)
        original["packets"]["NBIS"]["recent_minute_bars"][0]["c"] = -1
        before = len(db.exec(select(PracticeRun)).all())
        with pytest.raises(decisions.DecisionError):
            history.prepare(db, original, identifier="failed-history", proof=True)
        assert len(db.exec(select(PracticeRun)).all()) == before
        freeze = decisions.freeze_context
        def failed_freeze(*args, **kwargs):
            if args[2] == "NBIS":
                raise RuntimeError("interrupted second context")
            return freeze(*args, **kwargs)
        h.b.patch.setattr(decisions, "freeze_context", failed_freeze)
        with pytest.raises(RuntimeError):
            history.prepare(db, h.original, identifier="failed-history", proof=True)
        assert len(db.exec(select(PracticeRun)).all()) == before
        assert len(db.exec(select(JobRun)).all()) == 1


def test_import_retries_original_observation_freshness_and_no_live_bypass(historical):
    h = historical
    with Session(h.b.engine) as db:
        run = history.prepare(db, h.original, identifier="history-test", proof=True)
        assert run.id == h.run_id
        altered = deepcopy(h.original)
        altered["packets"]["MU"]["recent_minute_bars"][0]["v"] += 1
        with pytest.raises(decisions.DecisionError):
            history.prepare(db, altered, identifier="history-test", proof=True)
        opp = db.get(PracticeOpportunity, h.ids["MU"])
        ctx = db.get(DecisionContext, opp.context_id)
        evidence = json.loads(ctx.data_json)
        cutoff = decisions._utc(evidence["packet"]["simulated_as_of"], "cutoff")
        # Generic live validation still rejects retrospectively stale bars.
        with pytest.raises(decisions.DecisionError, match="expiry|stale"):
            decisions._validate_take("MU", ctx.captured_at, evidence, h.plan, access.now())
        stale = deepcopy(evidence)
        stale["price_facts"][0]["formed_at"] = (cutoff-timedelta(hours=3)).replace(tzinfo=timezone.utc).isoformat()
        source_name = stale["price_facts"][0]["name"]
        stale_plan = {**h.plan, "trigger_fact": source_name, "trigger_level": stale["price_facts"][0]["value"]}
        with pytest.raises(decisions.DecisionError):
            decisions._validate_take("MU", cutoff, stale, stale_plan, cutoff, historical=True)


def test_pure_replay_missing_confirmation_entry_hold_and_bounded_end(historical):
    h = historical
    with Session(h.b.engine) as db:
        opp = db.get(PracticeOpportunity, h.ids["MU"])
        ctx = db.get(DecisionContext, opp.context_id)
        evidence = json.loads(ctx.data_json)
        cutoff = decisions._utc(evidence["packet"]["simulated_as_of"], "cutoff")
        valid = decisions._validate_take("MU", cutoff, evidence, h.plan, cutoff, historical=True)
        sealed = json.loads(opp.benchmark_json)
    for index, stage in ((0, "trigger"), (16, "entry"), (17, "hold")):
        tape = deepcopy(sealed)
        del tape["minutes"][index]
        events, state, normal, stressed = history.simulate(valid, tape)
        assert state.status == "unresolved" and events[-1]["stage"] == stage
        assert normal is None and stressed is None
    tape = deepcopy(sealed)
    tape["minutes"] = tape["minutes"][:17]
    assert history.simulate(valid, tape)[1].status == "unresolved"
    tape = deepcopy(sealed)
    for bar in tape["minutes"]:
        bar.update(o=110, c=110, h=110.2, l=109.9)
    events, state, normal, stressed = history.simulate(valid, tape)
    assert state.status == "expired" and normal is None


def test_simultaneous_replay_start_is_one_atomic_receipt(historical):
    h = historical
    assert choose(h).status_code == 201
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(lambda _: start(h), range(2)))
    assert sorted(r.status_code for r in responses) == [200, 201]
    values = [next(o for o in r.json()["opportunities"] if o["symbol"] == "MU")["replay"] for r in responses]
    assert values[0] == values[1]
    with Session(h.b.engine) as db:
        assert len(db.exec(select(DecisionEvent)).all()) == 6


def test_unassigned_readonly_projection_and_assignment_reset_refuse(historical):
    h = historical
    assert choose(h).status_code == 201
    with Session(h.b.engine) as db:
        principal = db.get(AccessPrincipal, "dot")
        principal.grants_json = json.dumps({"symbols": ["MU", "NBIS"], "run_ids": [str(h.run_id)], "journal_read": False})
        db.add(principal)
        db.commit()
        record = db.exec(select(DecisionRecord)).first()
        record_id = record.id
        run = db.get(PracticeRun, h.run_id)
        with pytest.raises(decisions.DecisionError):
            history.view(db, run, "dot", {"MU"})
    assert signin(h.b).status_code == 200
    assert h.b.public.get(f"/practice/runs/{h.run_id}").status_code == 404
    assert h.b.public.get("/practice/runs").json()["runs"] == []
    assert h.b.public.get("/decisions").json()["decisions"] == []
    assert h.b.public.get(f"/decisions/{record_id}").status_code == 404
    assert h.b.owner.post("/access/assistants/dot/reset", json={"grants": h.grants}).status_code == 403


def test_replay_commit_interruption_leaves_no_partial_events(historical):
    h = historical
    assert choose(h).status_code == 201
    original = Session.commit
    def interrupt(db):
        if any(isinstance(row, DecisionEvent) for row in db.new):
            raise RuntimeError("precommit interruption")
        return original(db)
    h.b.patch.setattr(Session, "commit", interrupt)
    with pytest.raises(RuntimeError, match="precommit"):
        start(h)
    h.b.patch.setattr(Session, "commit", original)
    with Session(h.b.engine) as db:
        assert not db.exec(select(DecisionEvent)).all()
    assert start(h).status_code == 201


def test_capture_has_six_bounded_reads_and_preserves_actual_time(monkeypatch):
    deploy = Path(__file__).resolve().parents[2] / "deploy"
    monkeypatch.syspath_prepend(str(deploy))
    spec = importlib.util.spec_from_file_location("historical_capture_test", deploy / "dot_historical_capture.py")
    capture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(capture)
    calls = []
    actual = datetime(2026, 10, 10, 17, tzinfo=timezone.utc)
    def reader(url, params, credentials):
        calls.append((url, dict(params)))
        if url.endswith("calendar"):
            return [{"date": "2026-10-07", "open": "09:30", "close": "16:00"},
                {"date": "2026-10-08", "open": "09:30", "close": "16:00"}]
        begin = datetime.fromisoformat(params["start"])
        return {"bars": {params["symbols"]: [{"t": begin.isoformat(), "o": 110, "h": 111,
            "l": 109, "c": 110.5, "v": 1, "vw": 110.2}]}, "next_page_token": None}
    credentials = {"ALPACA_API_KEY": "never-export-key", "ALPACA_API_SECRET": "never-export-secret", "ALPACA_DATA_FEED": "iex"}
    result = capture.capture(credentials, date(2026, 10, 7), time(13, 45), reader=reader, now=actual)
    assert len(calls) == 5  # one successful calendar plus four symbol/session reads
    assert result["captured_at"] == actual.isoformat()
    assert result["simulated_as_of"] == "2026-10-07T17:45:00+00:00"
    assert "never-export" not in json.dumps(result)
    for url, params in calls[1:]:
        assert url == "https://data.alpaca.markets/v2/stocks/bars"
        assert params["feed"] == "iex" and params["adjustment"] == "raw" and params["currency"] == "USD"
        assert params["limit"] == 1000 and params["timeframe"] == "1Min"
    def incomplete(url, params, credentials):
        result = reader(url, params, credentials)
        if "bars" in result:
            result["next_page_token"] = "unbounded-pagination-refused"
        return result
    with pytest.raises(ValueError, match="incomplete"):
        capture.capture(credentials, date(2026, 10, 7), time(13, 45), reader=incomplete, now=actual)
    with pytest.raises(ValueError):
        capture.capture(credentials, date(2026, 10, 10), time(13, 45), reader=reader, now=actual)


@pytest.mark.parametrize("change", ["future", "extra", "duplicate", "off-session", "bad-ohlc", "unknown-source", "unaligned-cutoff"])
def test_strict_historical_handoff_refusals(change):
    original = bundle()
    bars = original["packets"]["MU"]["recent_minute_bars"]
    if change == "future":
        original["captured_at"] = (access.now()+timedelta(days=1)).replace(tzinfo=timezone.utc).isoformat()
    elif change == "extra":
        original["credentials"] = "must-never-be-imported"
    elif change == "duplicate":
        bars.insert(0, deepcopy(bars[0]))
    elif change == "off-session":
        bars[0]["t"] = bars[0]["t"].replace("15:59", "20:00")
    elif change == "bad-ohlc":
        bars[0]["l"] = bars[0]["h"]+1
    elif change == "unknown-source":
        original["packets"]["MU"]["data_source"] = "sample_fixture"
    else:
        original["simulated_as_of"] = original["simulated_as_of"].replace(":45:", ":46:")
    with pytest.raises(decisions.DecisionError):
        history.validate_bundle(original)
