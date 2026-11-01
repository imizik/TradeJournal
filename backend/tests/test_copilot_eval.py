"""The offline copilot eval (scripts/copilot_eval.py) and its graders. No network: the scripted model on fixture evidence,
and an Anthropic client that would fail loudly if anything tried to build one."""
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import anthropic
import pytest
from sqlmodel import Session, delete

from app.ai import copilot_graders
from app.database import engine
from app.models import CopilotInvestigation
from scripts import copilot_eval

CASES = Path(__file__).parent / "fixtures" / "copilot_eval" / "starter.jsonl"
STARTER = copilot_eval.load_cases(CASES)


def _no_client(*args, **kwargs):
    raise AssertionError("an Anthropic client was built during a free run")


@pytest.fixture
def harness(tmp_path, monkeypatch):
    monkeypatch.setattr(anthropic, "AsyncAnthropic", _no_client)
    monkeypatch.setattr(copilot_eval, "DATA_DIR", tmp_path / "data")
    return tmp_path


def _records(run_dir: Path) -> list[dict]:
    return copilot_eval.read_jsonl(run_dir / "records.jsonl")


def test_a_free_run_writes_one_record_per_case_and_builds_no_client(harness):
    out = harness / "run1"
    assert copilot_eval.main(["run", "--cases", str(CASES), "--model", "fake", "--out", str(out)]) == 0
    records = _records(out)
    assert [r["id"] for r in records] == [c["id"] for c in STARTER]
    assert all(r["cost_usd"] == 0 and not r["cached"] and not r.get("skipped") for r in records)
    assert all(r["tools"] and r["tools"][0]["name"] == "owner_context" for r in records)  # every turn read the pack first
    assert all(r["text"].lstrip().startswith("Verdict:") or r["error"] for r in records)
    meta = json.loads((out / "run.json").read_text())
    assert meta["count"] == len(STARTER) and meta["backend"] == "fake" and meta["cached"] == 0
    follow = next(r for r in records if r["id"] == "followup-carry")
    assert follow["history"][0]["content"] == next(c for c in STARTER if c["id"] == "ask-nbis-group")["question"]
    assert follow["carry"] == "ok"


def test_a_second_run_is_all_cache_hits_with_the_same_text(harness):
    first, second = harness / "a", harness / "b"
    assert copilot_eval.main(["run", "--cases", str(CASES), "--model", "fake", "--out", str(first)]) == 0
    assert copilot_eval.main(["run", "--cases", str(CASES), "--model", "fake", "--out", str(second)]) == 0
    a, b = _records(first), _records(second)
    assert all(r["cached"] for r in b) and [r["text"] for r in a] == [r["text"] for r in b]
    assert next(r for r in b if r["id"] == "followup-carry")["carry"] == "unavailable"  # a cached parent carries nothing


def test_grade_emits_every_check_and_scripted_answers_pass_format_and_orders(harness):
    out = harness / "run"
    copilot_eval.main(["run", "--cases", str(CASES), "--model", "fake", "--out", str(out)])
    assert copilot_eval.main(["grade", "--run", str(out), "--cases", str(CASES)]) == 0
    grades = copilot_eval.read_jsonl(out / "grades.jsonl")
    names = {"completed", "format_verdict", "format_read", "format_against", "length", "traceable_figures", "verdict_in", "no_reread",
             "unsupported", "no_orders", "tools_any", "tools_none"}
    for g in grades:
        assert {c["name"] for c in g["checks"]} == names, g["id"]
        states = {c["name"]: c["state"] for c in g["checks"]}
        assert states["completed"] == "pass" and states["format_verdict"] == "pass" and states["no_orders"] == "pass", g["id"]
    assert copilot_eval.main(["report", "--run", str(out)]) == 0
    report = json.loads((out / "report.json").read_text())
    assert report["runs"][0]["checks"]["format_verdict"]["pass_rate"] == 1.0 and report["comparison"] is None


def _record(text: str, tools=None, question="Is NBIS lagging?", history=None, **extra) -> dict:
    tools = tools if tools is not None else [{"name": "owner_context", "args": ["NBIS"], "result": {"positions": {"count": 2}}},
                                            {"name": "get_group_comparison", "args": {"symbol": "NBIS"},
                                             "result": {"rows": [{"symbol": "NBIS", "change_pct": 0.84}, {"symbol": "CRWV", "change_pct": 1.92},
                                                                 {"symbol": "SPY", "change_pct": 0.09}], "coverage": {"peers_up": 5, "peers_total": 7}}}]
    return {"id": "x", "question": question, "history": history or [], "text": text, "tools": tools, "error": None, **extra}


def _state(checks, name):
    return next(c for c in checks if c.name == name).state


def test_the_figure_grader_traces_values_percents_and_differences_and_catches_an_invented_one():
    ok = _record("Verdict: Wait — Not yet.\n\n- NBIS is up 0.84% against SPY's 0.09%.\n- It lags CRWV by 1.08 points, with 5 of 7 peers up.\n\nAgainst: 84 bp is thin.")
    assert _state(copilot_graders.grade(ok, {"expects": {}}), "traceable_figures") == "pass"
    planted = _record("Verdict: Wait — Not yet.\n\n- NBIS is up 0.84%, with support at 123.45.")
    check = next(c for c in copilot_graders.grade(planted, {"expects": {}}) if c.name == "traceable_figures")
    assert check.state == "fail" and "123.45" in check.detail
    from_question = _record("Verdict: Pass — Too far.\n\n- Your 95.9 trigger is 1.6% above the last 94.35.",
                            question="Enter at 95.9?", tools=[{"name": "get_quotes", "args": {"symbols": ["NBIS"]}, "result": {"prices": {"NBIS": 94.35}}}])
    assert _state(copilot_graders.grade(from_question, {"expects": {}}), "traceable_figures") == "pass"


def test_the_other_graders_each_fail_and_pass():
    text = "Verdict: Hold — Thesis intact.\n\n- Body.\n\nAgainst: thin volume."
    again = _record(text)
    assert _state(copilot_graders.grade(again, {"expects": {"carried_tools": ["get_group_comparison"]}}), "no_reread") == "fail"
    fresh = _record(text, tools=[{"name": "owner_context", "args": ["NBIS"], "result": {}}])
    assert _state(copilot_graders.grade(fresh, {"expects": {"carried_tools": ["get_group_comparison"]}}), "no_reread") == "pass"
    assert _state(copilot_graders.grade(again, {"expects": {"planted_rumour": True}}), "unsupported") == "fail"
    flagged = _record("Verdict: Pass — Not on evidence.\n\n- Unsupported: a 2pm contract announcement — nothing in the news read shows it.\n\nAgainst: the dip is real.")
    assert _state(copilot_graders.grade(flagged, {"expects": {"planted_rumour": True}}), "unsupported") == "pass"
    order = _record("Verdict: Broken — The plan's level went.\n\n- Sell your NBIS calls now.")
    assert _state(copilot_graders.grade(order, {"expects": {}}), "no_orders") == "fail"
    assert _state(copilot_graders.grade(again, {"expects": {}}), "no_orders") == "pass"
    assert _state(copilot_graders.grade(again, {"expects": {"read": True}}), "format_read") == "fail"
    assert _state(copilot_graders.grade(again, {"expects": {"against": True}}), "format_against") == "pass"
    assert _state(copilot_graders.grade(again, {"expects": {"verdict_in": ["Wait"]}}), "verdict_in") == "fail"
    assert _state(copilot_graders.grade(again, {"expects": {"tools_any": ["get_moment"]}}), "tools_any") == "fail"
    assert _state(copilot_graders.grade(again, {"expects": {"tools_none": ["get_group_comparison"]}}), "tools_none") == "fail"
    long = _record("Verdict: Hold — H.\n\n" + " ".join(["word"] * 130))
    assert _state(copilot_graders.grade(long, {"expects": {}}), "length") == "fail"
    assert _state(copilot_graders.grade(long, {"expects": {"long_ok": True}}), "length") == "pass"
    failed = _record("", error="api_rate_limit")
    assert [c.name for c in copilot_graders.grade(failed, {"expects": {}})] == ["completed"]
    assert _state(copilot_graders.grade(_record("Just prose."), {"expects": {}}), "format_verdict") == "fail"


def test_a_paid_model_without_a_cap_or_key_is_refused_before_any_client(harness, monkeypatch, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert copilot_eval.main(["run", "--cases", str(CASES), "--model", "claude-sonnet-5-5", "--out", str(harness / "paid")]) == 2
    assert "--max-cost-usd" in capsys.readouterr().err
    assert copilot_eval.main(["run", "--cases", str(CASES), "--model", "claude-sonnet-5-5", "--max-cost-usd", "1", "--out", str(harness / "paid")]) == 2
    assert "ANTHROPIC_API_KEY" in capsys.readouterr().err
    assert not (harness / "paid").exists()


def test_grading_with_the_judge_needs_a_cap(harness, capsys):
    out = harness / "run"
    copilot_eval.main(["run", "--cases", str(CASES), "--model", "fake", "--out", str(out)])
    assert copilot_eval.main(["grade", "--run", str(out), "--judge"]) == 2
    assert "--max-cost-usd" in capsys.readouterr().err


def test_a_report_compares_two_runs_case_by_case(harness, capsys):
    a, b = harness / "a", harness / "b"
    for out in (a, b):
        copilot_eval.main(["run", "--cases", str(CASES), "--model", "fake", "--out", str(out)])
        copilot_eval.main(["grade", "--run", str(out), "--cases", str(CASES)])
    assert copilot_eval.main(["report", "--run", str(a), "--run", str(b)]) == 0
    text = capsys.readouterr().out
    assert "fake · effort medium · fake · fixture" in text and "$0" in text and "B minus A" in text
    report = json.loads((b / "report.json").read_text())
    assert report["comparison"]["shared_cases"] == len(STARTER)
    assert all(c["b_minus_a"] in (0.0, None) for c in report["comparison"]["checks"].values())


def test_the_case_bootstrap_matches_its_source():
    mean, lo, hi = copilot_eval.case_bootstrap({"a": (1, 1), "b": (0, 1), "c": (1, 1), "d": (1, 1)})
    assert mean == 0.75 and 0 <= lo <= mean <= hi <= 1
    assert copilot_eval.case_bootstrap({"a": (1, 1)}) == (1.0, None, None) and copilot_eval.case_bootstrap({}) == (None, None, None)


def test_export_strips_ids_skips_briefs_and_refuses_the_fixtures_folder(tmp_path):
    now = datetime.now(UTC).replace(tzinfo=None)
    with Session(engine) as db:
        db.exec(delete(CopilotInvestigation))
        kept = CopilotInvestigation(source="copilot", title="NBIS vs the group", symbol="NBIS", status="open", revision=1,
                                    created_at=now, updated_at=now, evidence_json="[]",
                                    transcript_json=json.dumps([{"role": "user", "content": "Review this position: 11111111-1111-4111-8111-111111111111"},
                                                                {"role": "assistant", "content": "Verdict: Hold — Fine.", "rating": "helped"},
                                                                {"role": "user", "content": "Push back on \"Fine.\": the group is red"}]))
        brief = CopilotInvestigation(source="copilot", title="Morning brief Oct 30", symbol=None, status="closed", revision=1,
                                     created_at=now, updated_at=now, evidence_json="[]",
                                     transcript_json=json.dumps([{"role": "user", "content": "Prep"}, {"role": "assistant", "content": "x"}]))
        old = CopilotInvestigation(source="copilot", title="Old", symbol="SPY", status="closed", revision=1, created_at=now - timedelta(days=90),
                                   updated_at=now - timedelta(days=90), evidence_json="[]",
                                   transcript_json=json.dumps([{"role": "user", "content": "old"}, {"role": "assistant", "content": "y"}]))
        research = CopilotInvestigation(source="research_job", title="Radar: CRWV", symbol="CRWV", status="open", revision=1, created_at=now,
                                        updated_at=now, evidence_json="[]", transcript_json=json.dumps([{"role": "user", "content": "job"}]))
        db.add_all([kept, brief, old, research])
        db.commit()
        out = tmp_path / "owner-cases.jsonl"
        assert copilot_eval.export_cases(now - timedelta(days=30), out, session=db) == 2
        db.exec(delete(CopilotInvestigation))
        db.commit()
    cases = copilot_eval.read_jsonl(out)
    assert [c["question"] for c in cases] == ["Review this position: <id>", 'Push back on "Fine.": the group is red']
    assert cases[0]["rating"] == "helped" and cases[0]["next_question"].startswith("Push back") and cases[0]["symbol"] == "NBIS"
    assert not any(copilot_eval.UUID.search(json.dumps(c)) for c in cases)
    with pytest.raises(ValueError):
        copilot_eval.export_cases(now, Path(__file__).parent / "fixtures" / "copilot_eval" / "owner.jsonl")
