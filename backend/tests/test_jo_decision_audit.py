"""Evidence integrity, numerical claim boundaries and sealed-study separation."""

import copy
from datetime import datetime, timedelta, timezone
import json
import sqlite3
import uuid

import pytest

import jo_decision_audit as audit
from jo_decision_audit_report import render
from scripts.jo_decision_audit import export_saved, main


def snapshot():
    rid = str(uuid.UUID(int=1))
    manifest = {"kind": "opportunity_feed", "exam_count": 0, "phases": {"day": "practice"},
                "run_ids": {"day": rid}, "actor": "fixture", "prompt_text": "Frozen assessment",
                "prompt_version": "fixture-v1", "source_manifest_sha256": "a" * 64}
    card = {"id": "card1", "candidate": {"ticker": "NVDA", "side": 1}, "family": "orb",
            "simulated_as_of": "2024-02-05T10:00:00-05:00", "entry_reference": 100, "stop": 99,
            "target_reference": 102, "features": {"day_move": 1.25, "trend": -0.25, "rvol": 1.33, "vol_ratio": .8},
            "estimated_round_trip_cost_r": .02, "candles": []}
    cutoff = datetime.fromisoformat(card["simulated_as_of"])
    for i in range(6):
        card["candles"].append({"start": (cutoff - timedelta(minutes=(6-i)*5)).isoformat(),
                                "end": (cutoff - timedelta(minutes=(5-i)*5)).isoformat(),
                                "open": 100, "high": 101, "low": 99.5, "close": 100, "volume": 100 if i < 5 else 200})
    evidence = {"opportunity_id": rid + ":card1", "candidate": {"candidate_id": "candidate1"}, "opportunity": card}
    receipt = {"run_id": rid, "opportunity_id": evidence["opportunity_id"], "candidate_id": "candidate1",
               "decision": "take", "reason": "C=[1.25,-0.25; mixed] entry 100, stop 99; risk 1.00; cost 0.02R; rvol 1.33; vol_ratio 0.8; V=[2.0x]",
               "served_at": "2026-10-17T12:00:00Z", "committed_at": "2026-10-17T12:00:10Z", "wall_seconds": 10,
               "policy_hash": audit.digest(manifest), "prompt_version": "fixture-v1", "context_sha256": audit.digest(evidence)}
    row = {"actor": "agent:fixture", "receipt": receipt, "evidence": evidence,
           "receipt_sha256": audit.digest(receipt), "evidence_sha256": audit.digest(evidence)}
    return {"format": "jo-decision-evidence-v1", "exported_at": "2026-10-17T13:00:00Z",
            "runs": [{"run_id": rid, "status": "prepared", "manifest": manifest, "policy_hash": audit.digest(manifest), "rows": [row]}]}


def checks(text):
    facts = audit.card_facts(snapshot()["runs"][0]["rows"][0]["evidence"]["opportunity"])
    return {x["field"]: x for x in audit.claims(text, facts)}


def test_literal_claims_rounding_and_unknowns():
    result = audit.audit_export(snapshot())
    assert result["claims"] == {"match": 10}
    assert result["runs"][0]["status"] == "prepared"  # partial runs allowed for facts only
    assert checks("risk 1.006")["risk"]["status"] == "mismatch"
    assert checks("risk 1e0")["risk"]["status"] == "match"
    assert checks("risk 1.0; risk 2.0")["risk"]["status"] == "ambiguous"
    assert checks("Seems stronger with participation")["risk"]["status"] == "unparsed"
    assert checks("C=[1.25,-0.25; aligned]")["context"]["status"] == "mismatch"
    assert audit.rounded_equal("1.3", 1.25)
    assert not audit.rounded_equal("1.30", 1.25)


@pytest.mark.parametrize("text", ["risk 1R", "risk 1 R", "risk 1%", "risk 1 %", "risk 1 ATR", "risk 1.25R", "risk 1.25percent", "risk 1,000"])
def test_incompatible_units_and_thousands_not_falsely_parsed(text):
    assert checks(text)["risk"]["status"] == "unparsed"


@pytest.mark.parametrize("mutation", ["hash", "actor", "run", "context", "policy", "future", "duplicate", "timing"])
def test_tampering_and_bad_evidence_refused(mutation):
    data = snapshot()
    run, row = data["runs"][0], data["runs"][0]["rows"][0]
    if mutation == "hash":
        row["receipt"]["reason"] = "changed"
    elif mutation == "actor":
        row["actor"] = "agent:elsewhere"
    elif mutation in {"run", "context", "policy", "timing"}:
        field = {"run": "run_id", "context": "context_sha256", "policy": "policy_hash", "timing": "wall_seconds"}[mutation]
        row["receipt"][field] = 11 if mutation == "timing" else "bad"
        row["receipt_sha256"] = audit.digest(row["receipt"])
    elif mutation == "duplicate":
        run["rows"].append(copy.deepcopy(row))
    else:
        row["evidence"]["opportunity"]["candles"][-1]["end"] = "2024-02-05T10:01:00-05:00"
        row["evidence_sha256"] = audit.digest(row["evidence"])
        row["receipt"]["context_sha256"] = row["evidence_sha256"]
        row["receipt_sha256"] = audit.digest(row["receipt"])
    with pytest.raises(ValueError):
        audit.audit_export(data)


def test_missing_and_nonfinite_evidence():
    card = snapshot()["runs"][0]["rows"][0]["evidence"]["opportunity"]
    card["features"]["rvol"] = None
    assert next(c for c in audit.claims("rvol 2", audit.card_facts(card)) if c["field"] == "rvol")["status"] == "missing_evidence"
    for value in (True, float("nan"), float("inf")):
        card["features"]["trend"] = value
        with pytest.raises(ValueError):
            audit.card_facts(card)


def comparison():
    arms = []
    for n, name in enumerate(("control", "structured")):
        rid = str(uuid.UUID(int=n + 1))
        assignment = {"arm": name, "run_id": rid, "cards": 3, "source_manifest_sha256": "a" * 64,
                      "policy_sha256": "b" * 64, "prompt_sha256": str(n) * 64, "prompt_version": name}
        rows = []
        for i, outcome in enumerate((-1, 2, None)):
            decision = ("take" if i == 0 else "skip") if name == "control" else ("take" if i == 1 else "skip")
            r = copy.deepcopy(snapshot()["runs"][0]["rows"][0]["receipt"])
            r.update(run_id=rid, opportunity_id=f"{rid}:{i}", decision=decision, prompt_version=name, reason="Saved reason")
            rows.append({"source_card_id": f"c{i}", "receipt": r, "decision": decision, "reason": r["reason"],
                         "outcome": {"resolved": outcome is not None, "r": outcome}, "candidate": {"ticker": "NVDA", "side": 1},
                         "features": {"day_move": 1, "trend": 1}, "simulated_as_of": f"2024-02-05T1{i}:00:00-05:00",
                         "entry_reference": 100, "stop": 99, "target_reference": 102, "target_r": 2, "max_minutes": 60,
                         "estimated_round_trip_cost_r": .02, "family": "orb", "setup": "orb", "session": "2024-02-05"})
        arms.append({"assignment": assignment, "rows": rows})
    return {"revealed_at": "2026-10-17T13:00:00Z", "arms": arms}


def test_changed_selection_accounting_and_unknown_totals():
    data = comparison()
    result = audit.compare_revealed(data, ["control", "structured"])
    assert result["arms"]["structured"]["delta_r"] == 3
    assert result["arms"]["control"]["total_r"] == -1
    assert result["take_all"]["total_r"] is None
    assert result["take_all"]["resolved_only_total_r"] == 1
    assert {r["change"] for r in result["changes"]} == {"added", "removed"}
    for arm in data["arms"]:
        row = arm["rows"][2]
        row["decision"] = row["receipt"]["decision"] = "take"
    result = audit.compare_revealed(data, ["control", "structured"])
    assert result["arms"]["structured"]["delta_r"] == 3  # common unresolved cancels
    assert result["arms"]["structured"]["total_r"] is None
    data["arms"][0]["rows"][2]["decision"] = data["arms"][0]["rows"][2]["receipt"]["decision"] = "skip"
    assert audit.compare_revealed(data, ["control", "structured"])["arms"]["structured"]["delta_r"] is None
    assert audit.stats([]) == {"selected": 0, "resolved": 0, "unresolved": 0, "total_r": 0, "resolved_only_total_r": 0, "mean_resolved_r": None}


@pytest.mark.parametrize("mutation", ["partial", "arms", "facts", "outcome", "policy", "duplicate", "late", "timing"])
def test_comparison_refuses_partial_or_inconsistent_inputs(mutation):
    data = comparison()
    row = data["arms"][1]["rows"][0]
    if mutation == "partial":
        data["arms"][1]["rows"].pop()
    elif mutation == "arms":
        data["arms"].pop()
    elif mutation == "facts":
        row["features"]["trend"] = 99
    elif mutation == "outcome":
        row["outcome"]["r"] = 100
    elif mutation == "policy":
        row["receipt"]["policy_hash"] = "e" * 64
    elif mutation == "duplicate":
        row["source_card_id"] = "c1"
    elif mutation == "late":
        row["receipt"]["committed_at"] = "2026-10-18T00:00:00Z"
    else:
        row["receipt"]["wall_seconds"] = -1
    with pytest.raises(ValueError):
        audit.compare_revealed(data, ["control", "structured"])


def fixture_database(tmp_path):
    root = tmp_path.resolve() / "sample"
    (root / "data").mkdir(parents=True)
    (root / ".sample-installation").touch()
    path = root / "data/trial.db"
    data = snapshot()
    run = data["runs"][0]
    row = run["rows"][0]
    with sqlite3.connect(path) as db:
        db.executescript("CREATE TABLE fill(raw_email_id TEXT); INSERT INTO fill VALUES ('seed:fixture'); CREATE TABLE practice_run(id TEXT, status TEXT, brief_json TEXT, policy_hash TEXT, calendar_json TEXT); CREATE TABLE decision_record(actor TEXT,operation_id TEXT,decision_json TEXT,evidence_json TEXT,record_sha256 TEXT,evidence_sha256 TEXT);")
        db.execute("INSERT INTO practice_run VALUES (?,?,?,?,?)", (uuid.UUID(run["run_id"]).hex, "prepared", json.dumps({"manifest": run["manifest"]}), run["policy_hash"], "SEALED_CANARY"))
        db.execute("INSERT INTO decision_record VALUES (?,?,?,?,?,?)", (row["actor"], "scanner:" + run["run_id"] + ":card1", json.dumps(row["receipt"]), json.dumps(row["evidence"]), row["receipt_sha256"], row["evidence_sha256"]))
    return root, data


def test_export_is_readonly_partial_and_no_seal_query(tmp_path, monkeypatch):
    root, data = fixture_database(tmp_path)
    path = root / "data/trial.db"
    before = path.read_bytes()
    connect, sql = sqlite3.connect, []
    def tracked(*args, **kwargs):
        db = connect(*args, **kwargs)
        db.set_trace_callback(sql.append)
        return db
    monkeypatch.setattr(sqlite3, "connect", tracked)
    result = export_saved(root, [data["runs"][0]["run_id"]])
    assert result["runs"] == data["runs"]
    assert before == path.read_bytes()
    assert "SEALED_CANARY" not in json.dumps(result)
    assert not any("calendar" in s.lower() for s in sql)
    assert any("query_only=ON" in s for s in sql)
    with pytest.raises(ValueError):
        export_saved(root, [data["runs"][0]["run_id"]] * 2)
    with connect(path) as db:
        db.execute("INSERT INTO fill VALUES ('real')")
    with pytest.raises(ValueError):
        export_saved(root, [data["runs"][0]["run_id"]])


def test_cli_private_files_no_overwrite_and_escape(tmp_path):
    source, html, output = (tmp_path.resolve() / name for name in ("input.json", "audit.html", "audit.json"))
    data = snapshot()
    row = data["runs"][0]["rows"][0]
    row["receipt"]["reason"] = '</script><img src="https://bad.example" onerror="alert(1)">'
    row["receipt_sha256"] = audit.digest(row["receipt"])
    source.write_text(json.dumps(data))
    source.chmod(0o600)
    args = ["audit", "--input", str(source), "--output", str(html), "--json-output", str(output)]
    main(args)
    text = html.read_text()
    assert '<img src=' not in text and '&lt;img' in text
    assert "default-src 'none'" in text and '<script' not in text
    assert html.stat().st_mode & 0o777 == 0o600
    assert output.stat().st_mode & 0o777 == 0o600
    with pytest.raises(SystemExit) as error:
        main(args)
    assert error.value.code == 2
    assert html.read_text() == text
    source.chmod(0o644)
    with pytest.raises(SystemExit):
        main(["audit", "--input", str(source), "--output", str(tmp_path.resolve() / "new.html")])
    assert not (tmp_path / "new.html").exists()


def test_empty_and_comparison_html():
    data = snapshot()
    data["runs"][0]["rows"] = []
    assert "No saved decisions" in render(audit.audit_export(data))
    html = render(audit.compare_revealed(comparison(), ["control", "structured"]))
    assert "Unknown" in html and "Changed selections" in html


def test_real_opportunity_receipt_export(tmp_path):
    """Use actual importer/decision writer, including their frozen hash formats."""
    from sqlmodel import SQLModel, Session, create_engine
    from app.engine import opportunity_replay, scanner_replay
    from app.models import Account, Fill
    from tests.test_opportunity_replay import bundle

    root = tmp_path.resolve() / "actual"
    (root / "data").mkdir(parents=True)
    (root / ".sample-installation").touch()
    engine = create_engine(f"sqlite:///{root / 'data/trial.db'}")
    SQLModel.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            account = Account(name="Fixture", type="test", last4="0000")
            db.add(account)
            db.flush()
            db.add(Fill(account_id=account.id, ticker="NVDA", instrument_type="stock", side="buy", contracts=1,
                        price=100, executed_at=datetime(2024, 2, 5, 10), raw_email_id="seed:audit"))
            run = opportunity_replay.prepare(db, bundle(), "jo-audit-fixture")[0]
            rid = str(run.id)
            entry = scanner_replay.entries(run)[0]
            run.timings_json = json.dumps({"served": {entry["opportunity_id"]: datetime.now(timezone.utc).isoformat()}})
            scanner_replay.choose(db, run, entry, "jo-audit-fixture", ["NVDA"], {"decision": "take", "rationale": "risk 1.00; cost 0.02R"})
            db.commit()
        report = audit.audit_export(export_saved(root, [rid]))
        assert report["runs"][0]["saved_decisions"] == 1
        assert report["claims"]["match"] == 2
        assert report["rows"][0]["facts"]["bar_volume_ratio"] is None
    finally:
        engine.dispose()
