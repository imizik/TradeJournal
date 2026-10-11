"""R4 frozen lineage, exact event sets, paired uncertainty and append-only history."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace

import pytest

from app.engine.market_map import ET
from app.engine.research_studio_comparison import compare
from app.engine.research_studio_analysis import HORIZONS, UNITS, summarize
from tests.test_research_studio_session import session as session, op
from tests.test_research_studio_analysis import snapshot as snapshot, definition as definition


def completed(session, definition):
    state = session.enqueue(definition.canonical(), op())
    session.store.work_once()
    assert session.store.status(state["run_id"])["status"] == "completed"
    return state


def pair(session, definition):
    parent = completed(session, replace(definition, window_end=610))
    child_definition = replace(definition, window_end=610,
        predicates=(replace(definition.predicates[0], minimum=35),))
    child = session.variant(child_definition.canonical(), parent["run_id"], op())
    session.store.work_once()
    return parent, child


def test_variant_uses_frozen_parent_and_records_later_replacement(session, definition):
    parent = completed(session, replace(definition, window_end=610))
    session.source.snapshot = lambda *a, **kw: (_ for _ in ()).throw(AssertionError("source reopened"))
    raw = replace(definition, window_end=610, predicates=(replace(definition.predicates[0], minimum=35),)).canonical()
    preview = session.preview(raw, parent_run_id=parent["run_id"])
    assert preview["data_id"] == parent["data_id"]
    child = session.variant(raw, parent["run_id"], op())
    session.store.work_once()
    comparison = session.compare(parent["run_id"], child["run_id"], op())
    assert comparison["sets"] == {
        "retained": [], "removed": ["MU:2023-07-10T14:00:00+00:00"],
        "added": ["MU:2023-07-10T14:05:00+00:00"]}
    assert comparison["retained_outcomes_identical"]
    assert comparison["parent_result"]["run_id"] == parent["run_id"]
    assert session.runs()["runs"][0]["parent_run_id"] == parent["run_id"]


def test_identical_retained_outcomes_and_pair_exposure_idempotence(session, definition):
    parent = completed(session, replace(definition, window_end=610))
    child_def = replace(definition, window_end=610, predicates=(replace(definition.predicates[0], minimum=29),))
    child = session.variant(child_def.canonical(), parent["run_id"], op())
    session.store.work_once()
    operation = op()
    result = session.compare(parent["run_id"], child["run_id"], operation)
    assert result["sets"] == {"retained": ["MU:2023-07-10T14:00:00+00:00"], "removed": [], "added": []}
    assert session.compare(parent["run_id"], child["run_id"], operation) == result
    assert [session.store.status(r["run_id"])["exposures"] for r in (parent,child)] == [1,1]
    session.compare(parent["run_id"], child["run_id"], op())
    assert [session.store.status(r["run_id"])["exposures"] for r in (parent,child)] == [2,2]


def test_conclusions_append_reload_exact_refs_and_conflicting_uuid_refuses(session, definition):
    parent, child = pair(session, definition)
    comparison = session.compare(parent["run_id"], child["run_id"], op())
    args = dict(run_ids=[parent["run_id"],child["run_id"]], verdict="Unclear", reason="Only one session; too little evidence.",
                horizon="30m",unit="percent",operation_id=op())
    first = session.variants.conclude(**args)
    assert session.variants.conclude(**args) == first
    with pytest.raises(ValueError, match="conflict"):
        session.variants.conclude(**{**args,"reason":"Different conclusion"})
    second = session.variants.conclude(**{**args,"operation_id":op(),"verdict":"Rejected","reason":"No clear separation."})
    from app.engine.research_studio_variants import Variants
    history = Variants(session.store).notes(args["run_ids"])["notes"]
    assert history == [first,second]
    assert first["comparison_id"] == comparison["comparison_id"]
    assert first["outcome_informed"] and first["references"][1]["run_id"] == child["run_id"]
    assert second["sequence"] == first["sequence"] + 1
    assert [session.store.status(r["run_id"])["exposures"] for r in (parent,child)] == [1,1]


def test_variant_refuses_scope_changes_unfinished_parent_and_cycle(session, definition):
    parent = session.enqueue(definition.canonical(),op())
    with pytest.raises(ValueError,match="completed"):
        session.preview(definition.canonical(),parent["run_id"])
    session.store.work_once()
    with pytest.raises(ValueError,match="change a condition"):
        session.variant(definition.canonical(),parent["run_id"],op())
    with pytest.raises(ValueError,match="conditions only"):
        session.variant(replace(definition,window_end=610).canonical(),parent["run_id"],op())
    child_def = replace(definition,predicates=(replace(definition.predicates[0],minimum=29),))
    child = session.variant(child_def.canonical(),parent["run_id"],op())
    session.store.work_once()
    with pytest.raises(ValueError,match="cycle"):
        session.variant(definition.canonical(),child["run_id"],op())


def test_changed_comparison_or_note_is_refused_without_new_exposure(session, definition):
    parent, child = pair(session,definition)
    session.compare(parent["run_id"],child["run_id"],op())
    path = session.store.root / f'comparison.{parent["run_id"]}.{child["run_id"]}.json'
    raw = path.read_text()
    path.write_text(raw.replace('"retained_outcomes_identical":true','"retained_outcomes_identical":false'))
    with pytest.raises(ValueError,match="artifact changed"):
        session.compare(parent["run_id"],child["run_id"],op())
    assert session.store.status(child["run_id"])["exposures"] == 1
    path.write_text(raw)
    note = session.variants.conclude([child["run_id"]],"Unclear","Small sample.","30m","percent",op())
    note_path = session.store.root / f'conclusion.{note["operation_id"]}.json'
    note_path.write_text(note_path.read_text().replace("Small sample.","Altered note."))
    with pytest.raises(ValueError,match="artifact changed"):
        session.variants.notes([child["run_id"]])


def test_busy_worker_comparison_refuses_without_exposing_results(session, definition):
    parent, child = pair(session,definition)
    with session.store._lock("worker.lock",nonblocking=True):
        with pytest.raises(ValueError,match="already active"):
            session.compare(parent["run_id"],child["run_id"],op())
    assert [session.store.status(r["run_id"])["exposures"] for r in (parent,child)] == [0,0]


def test_joint_resampling_uses_same_week_shocks_for_both_populations(monkeypatch):
    # Forty independently constructed blocks. Parent event=shock+2, baseline=shock+1;
    # variant event=shock+3, baseline=shock+1.5. Every paired draw must cancel shock.
    populations, event_ids = [[],[]], [set(),set()]
    rows_by_time = {}
    for week in range(40):
        monday = datetime(2023,7,3,10,tzinfo=ET)+timedelta(weeks=week)
        shock = (week % 7 - 3) * 10
        for population, signal in enumerate((2,3)):
            for ordinary in range(2):
                stamp = (monday+timedelta(days=population*2+ordinary)).astimezone(timezone.utc)
                value = shock + (signal if ordinary==0 else 0)
                row = {"symbol":"MU","decision_time":stamp.isoformat(),"clock":600,
                       "week":monday.date().isoformat(),"outcomes": {
                           h:{u:value for u in UNITS} | {u+"_reason":None for u in UNITS} for h in HORIZONS}}
                populations[population].append(row)
                rows_by_time[stamp] = row
                if ordinary==0:
                    event_ids[population].add(("MU",stamp.isoformat()))
    results = [{"run_id":str(i),"population":{"data_id":"d","events":[{"symbol":s,"decision_time":t} for s,t in sorted(ids)]},
                "events":[r for r in rows if (r["symbol"],r["decision_time"]) in ids],
                "horizons":summarize(rows,ids)} for i,(rows,ids) in enumerate(zip(populations,event_ids))]
    obs = SimpleNamespace(snapshot=SimpleNamespace(identity="d"),
        preview=lambda i:results[i]["population"],
        eligible_moments=lambda i:[SimpleNamespace(symbol="MU",close=datetime.fromisoformat(r["decision_time"])) for r in populations[i]])
    monkeypatch.setattr("app.engine.research_studio_comparison.outcome",lambda obs,s,t:rows_by_time[t])
    result = compare(obs,[0,1],results)
    change = result["horizons"]["30m"]["percent"]["change"]
    assert change["event_mean"] == pytest.approx(1)
    assert change["baseline_mean"] == pytest.approx(.5)
    assert change["difference"] == pytest.approx(.5)
    assert change["uncertainty"]["valid_draws"] == 2000
    assert change["uncertainty"]["intervals"]["difference"] == pytest.approx([.5,.5])
    assert change["uncertainty"]["intervals"]["event_mean"] == pytest.approx([1,1])

def test_missing_parent_endpoint_remains_unavailable_in_comparison(session,definition,snapshot):
    from tests.test_research_studio_analysis import changed
    session.source.snapshot=lambda *a,**kw:changed(snapshot,remove_minute=625)
    parent,child=pair(session,definition)
    result=session.compare(parent["run_id"],child["run_id"],op())
    summary=result["horizons"]["30m"]["percent"]
    assert summary["parent"]["event_n"]==0
    assert summary["variant"]["event_n"]==1
    assert summary["change"]["event_mean"] is None
    assert summary["parent"]["event_exclusions"]=={"missing_endpoint":1}


def test_single_run_notes_and_invalid_inputs_never_fetch_source_or_results(session,definition):
    parent=completed(session,definition)
    session.source.snapshot=lambda *a,**kw:(_ for _ in ()).throw(AssertionError("source reopened"))
    note=session.variants.conclude([parent["run_id"]],"Unclear","Question saved before viewing outcomes.","30m","percent",op())
    assert not note["outcome_informed"]
    assert session.variants.notes([parent["run_id"]])["notes"]==[note]
    for verdict,reason,horizon,unit in [("Winner","reason","30m","percent"),("Unclear"," ","30m","percent"),
                                      ("Unclear","x"*2001,"30m","percent"),("Unclear","reason","next_day","percent"),
                                      ("Unclear","reason","30m","R")]:
        with pytest.raises(ValueError):
            session.variants.conclude([parent["run_id"]],verdict,reason,horizon,unit,op())
    assert session.store.status(parent["run_id"])["exposures"]==0
    with pytest.raises(ValueError,match="discovery"):
        session.preview({**definition.canonical(),"end":"2024-10-01"},parent["run_id"])


def test_new_sidecar_commands_reject_token_paths_and_cross_action_uuid(session,definition):
    from fastapi.testclient import TestClient
    from scripts.research_studio_server import create_app
    client=TestClient(create_app(session,"r"*32))
    assert client.post("/command",json={"action":"notes","arguments":{"run_ids":[]}}).status_code==403
    client.headers["authorization"]="Bearer "+"r"*32
    assert client.get("/config").json()["capabilities"]==["variants","conclusions"]
    assert client.post("/command",json={"action":"variant","arguments":{
        "raw":definition.canonical(),"parent_run_id":"../outside","operation_id":op(),"cache_root":"/tmp"}}).status_code==400
    parent=completed(session,definition)
    operation=op()
    session.variants.conclude([parent["run_id"]],"Unclear","A prior note.","30m","percent",operation)
    with pytest.raises(ValueError,match="conflicts"):
        session.variants.conclude([parent["run_id"]],"Rejected","Changed action.","30m","percent",operation)
    assert client.post("/command",json={"action":"notes","arguments":{"run_ids":[parent["run_id"]],"store_root":"/tmp"}}).status_code==400


def test_actual_comparison_timeout_releases_inherited_worker_lock(session,definition,monkeypatch):
    import subprocess
    parent,child=pair(session,definition)
    original=subprocess.run
    # Real child, refused by subprocess.run's own kill/communicate/wait path.
    def very_short_child(*args,**kwargs):
        return original(*args,**{**kwargs,"timeout":.001})
    monkeypatch.setattr("app.engine.research_studio_variants.subprocess.run",very_short_child)
    with pytest.raises(ValueError,match="60-second"):
        session.compare(parent["run_id"],child["run_id"],op())
    assert session.store.recover()=={"recovered":[]}
    assert not session.preparation.locked()
    assert [session.store.status(r["run_id"])["exposures"] for r in (parent,child)]==[0,0]

def test_r4_uuid_cannot_be_reused_by_r2_actions(session,definition):
    parent=completed(session,definition)
    operation=op()
    note=session.variants.conclude([parent["run_id"]],"Unclear","An immutable reason.","30m","percent",operation)
    with pytest.raises(ValueError,match="operation id reused"):
        session.store.result(parent["run_id"],operation)
    with pytest.raises(ValueError,match="operation id reused"):
        session.enqueue(definition.canonical(),operation)
    assert session.variants.conclude([parent["run_id"]],"Unclear","An immutable reason.","30m","percent",operation)==note
    assert session.store.status(parent["run_id"])["exposures"]==0

def test_variant_submission_drops_preview_grid_before_loading_snapshot(session,definition,monkeypatch):
    parent=completed(session,definition)
    raw=replace(definition,predicates=(replace(definition.predicates[0],minimum=29),)).canonical()
    session.preview(raw,parent["run_id"])
    monkeypatch.setattr(session,"_saved_snapshot",lambda *a:(_ for _ in ()).throw(AssertionError("snapshot re-decoded")))
    child=session.variant(raw,parent["run_id"],op())
    assert child["data_id"]==parent["data_id"]
    assert session.observations is None and session.chart_snapshot is None
    session.store.work_once()
    assert session.store.status(child["run_id"])["status"]=="completed"

def test_variant_retry_keeps_original_provenance_after_parent_is_exposed(session,definition):
    parent=completed(session,definition)
    raw=replace(definition,predicates=(replace(definition.predicates[0],minimum=29),)).canonical()
    operation=op()
    child=session.variant(raw,parent["run_id"],operation)
    session.store.result(parent["run_id"],op())
    retry=session.variant(raw,parent["run_id"],operation)
    assert retry["run_id"]==child["run_id"]
    provenance=json.loads((session.store.root/f"submission.{operation}.json").read_text())
    assert provenance["outcome_informed"] is False
    with pytest.raises(ValueError,match="conflicts"):
        session.variant(raw,parent["run_id"],operation,outcome_informed=True)
