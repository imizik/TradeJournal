"""Read-only saved-decision export, factual audit and already-revealed comparison.

No environment database defaults, app imports, provider calls or reveal operation.
Run with PYTHONPATH=backend python backend/scripts/jo_decision_audit.py --help.
"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import sys
import uuid

# Prefer the pure backend module over this identically named CLI file.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from jo_decision_audit import MAX_ROWS, audit_export, compare_revealed, validate_run  # noqa: E402
from jo_decision_audit_report import render  # noqa: E402
from scripts.scanner_replay_operator import private_json, write_private_report  # noqa: E402


def export_saved(root, run_ids):
    """Take a consistent read-only snapshot; never query calendars or outcome seals."""
    if not 1 <= len(run_ids) <= 20 or len(set(run_ids)) != len(run_ids):
        raise ValueError("Require 1–20 distinct runs")
    ids = [uuid.UUID(value) for value in run_ids]
    marker, path = root / ".sample-installation", root / "data/trial.db"
    if (not root.is_absolute() or root.resolve() != root or not root.is_dir()
            or not marker.is_file() or marker.is_symlink() or path.resolve() != path or not path.is_file()):
        raise ValueError("Require a canonical marked isolated sample installation")
    runs = []
    db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5)
    try:
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")
        count, foreign = db.execute("SELECT COUNT(*), SUM(CASE WHEN raw_email_id IS NULL OR raw_email_id NOT LIKE 'seed:%' THEN 1 ELSE 0 END) FROM fill").fetchone()
        if not count or foreign:
            raise ValueError("Require exclusively seeded sample fills")
        for run_id in ids:
            record = db.execute("SELECT status, brief_json, policy_hash FROM practice_run WHERE id=?", (run_id.hex,)).fetchone()
            if record is None:
                raise ValueError("Requested run missing")
            status, brief, policy = record
            manifest = json.loads(brief)["manifest"]
            actor = "agent:" + manifest["actor"]
            prefix = f"scanner:{run_id}:"
            saved = db.execute("SELECT actor, decision_json, evidence_json, record_sha256, evidence_sha256 FROM decision_record WHERE actor=? AND substr(operation_id,1,?)=? ORDER BY operation_id LIMIT ?",
                               (actor, len(prefix), prefix, MAX_ROWS + 1)).fetchall()
            rows = [{"actor": a, "receipt": json.loads(r), "evidence": json.loads(e), "receipt_sha256": rh, "evidence_sha256": eh}
                    for a, r, e, rh, eh in saved]
            run = {"run_id": str(run_id), "status": status, "manifest": manifest, "policy_hash": policy, "rows": rows}
            validate_run(run)
            runs.append(run)
    finally:
        db.close()
    return {"format": "jo-decision-evidence-v1", "exported_at": datetime.now(timezone.utc).isoformat(), "runs": runs}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("export", help="Saved facts only, including partial runs; never outcomes")
    export.add_argument("--trial-root", type=Path, required=True)
    export.add_argument("--run-id", action="append", required=True)
    export.add_argument("--output", type=Path, required=True)
    for name in ("audit", "compare"):
        command = commands.add_parser(name)
        command.add_argument("--input", type=Path, required=True, help="Owned 0600 JSON export")
        command.add_argument("--output", type=Path, required=True, help="Fresh standalone HTML report")
        command.add_argument("--json-output", type=Path, help="Optional fresh machine-readable report")
        if name == "compare":
            command.add_argument("--expected-arm", action="append", required=True, help="Repeat for EVERY arm in the frozen study")
            command.add_argument("--control", default="control")
    args = parser.parse_args(argv)
    try:
        outputs = [args.output] + ([args.json_output] if getattr(args, "json_output", None) else [])
        if len(set(outputs)) != len(outputs) or any(p.exists() or p.is_symlink() for p in outputs):
            raise ValueError("Report destinations must be distinct and fresh")
        if args.command == "export":
            result = export_saved(args.trial_root, args.run_id)
            write_private_report(args.output, json.dumps(result, indent=2, allow_nan=False))
        else:
            data = private_json(args.input, 20 * 1024 * 1024)
            result = audit_export(data) if args.command == "audit" else compare_revealed(data, args.expected_arm, args.control)
            html = render(result)
            if args.json_output:
                write_private_report(args.json_output, json.dumps(result, indent=2, allow_nan=False))
            write_private_report(args.output, html)
    except (ValueError, KeyError, TypeError, AttributeError, OSError, sqlite3.Error, OverflowError):
        # Do not echo private source values or database contents in error messages.
        parser.exit(2, "Audit refused: invalid, inconsistent or inaccessible input/output. No study state was changed.\n")
    print("Private report written.")


if __name__ == "__main__":
    main()
