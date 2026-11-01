"""The Radar outcomes review: the question it builds, and that it runs one unsaved research job on API credits."""
import json

import pytest

from app.ai import research_job
from scripts import radar_outcomes_review as rv


def _row(event_id, session, value, symbol, movers=0.0):
    return {"event_id": event_id, "session_date": session, "rule_version": "radar-rules-v1", "kind": "relative_to_spy",
            "direction": "up", "symbols": [symbol], "first_seen_at": f"{session}T14:00:00.000Z",
            "horizons": {"60m": {"event": value, "movers": movers}},
            "evidence_verified": True, "config_digest": "frozen"}


ROWS = [_row("a", "2026-10-27", 3.0, "AAA"), _row("b", "2026-10-27", -2.0, "BBB"), _row("c", "2026-10-28", 1.0, "CCC"),
        _row("d", "2026-10-28", -0.5, "AAA"), _row("old", "2026-10-20", 9.0, "OLD"),
        {**_row("nohorizon", "2026-10-28", 0.0, "NNN"), "horizons": {}}]

ROWS += [{"record_type": "session", "session_date": d, "rule_version": "radar-rules-v1",
          "verified": True, "config_digest": "frozen"} for d in ("2026-10-20", "2026-10-27", "2026-10-28")]


def test_the_question_ranks_each_side_within_the_range_and_dedupes_symbols():
    text, symbols = rv.question_for(ROWS, "2026-10-27", None)
    kept, reversed_ = text.split("Kept going most at +60 min:")[1].split("Reversed most at +60 min:")
    assert kept.index("AAA") < kept.index("CCC") and "OLD" not in text  # outside the range
    assert reversed_.index("BBB") < reversed_.index("AAA")              # furthest reversal first
    assert symbols == ["AAA", "CCC", "BBB"]
    assert "(4 scored)" in text and "hindsight" in text and "No trade ideas" in text


def test_a_range_with_no_scored_event_builds_nothing():
    assert rv.question_for(ROWS, "2026-11-01", None) is None


def _outcomes(tmp_path):
    path = tmp_path / "outcomes.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in ROWS))
    return path


@pytest.fixture
def no_env_files(monkeypatch):
    monkeypatch.setattr(rv, "load_env_files", lambda: None)


def test_the_job_runs_unsaved_and_writes_the_review(tmp_path, monkeypatch, no_env_files):
    calls = {}

    def fake_run(question, symbols, evidence, now, **kwargs):
        calls.update(question=question, symbols=symbols, **kwargs)
        return {"auth": "api_key", "status": "ok", "assessment": {"summary": "s"}}

    monkeypatch.setattr(research_job, "run", fake_run)
    out = tmp_path / "review.json"
    assert rv.main([str(_outcomes(tmp_path)), "--since", "2026-10-27", "--out", str(out)]) == 0
    assert "mode" not in calls and calls["save"] is False and calls["symbols"] == ["AAA", "CCC", "BBB"]
    assert json.loads(out.read_text())["status"] == "ok"


def test_a_missing_key_stops_the_review_with_the_reason_and_writes_nothing(tmp_path, monkeypatch, no_env_files, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    out = tmp_path / "review.json"
    assert rv.main([str(_outcomes(tmp_path)), "--since", "2026-10-27", "--out", str(out)]) == 2
    assert "api_not_configured" in capsys.readouterr().err and not out.exists()


def test_a_dry_run_prints_the_question_and_runs_nothing(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(research_job, "run", lambda *a, **k: pytest.fail("dry run"))
    assert rv.main([str(_outcomes(tmp_path)), "--since", "2026-10-27", "--dry-run"]) == 0
    assert json.loads(capsys.readouterr().out)["symbols"] == ["AAA", "CCC", "BBB"]


def test_legacy_only_file_and_unverified_events_never_build_a_review():
    event = _row("legacy", "2026-10-27", 3.0, "AAA")
    assert rv.question_for([event], "2026-10-27", None) is None
    session = {"record_type": "session", "session_date": "2026-10-27", "rule_version": "radar-rules-v1",
               "verified": True, "config_digest": "frozen"}
    event.pop("evidence_verified")
    assert rv.question_for([event, session], "2026-10-27", None) is None
    event["evidence_verified"] = True
    session["verified"] = False
    assert rv.question_for([event, session], "2026-10-27", None) is None
