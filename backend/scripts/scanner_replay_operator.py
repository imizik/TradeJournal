"""Prepare, report or abandon a scanner replay on a marked isolated sample SQLite trial.

This operator reads private captures and writes only frozen replay rows or a
private Markdown report. It issues no login, starts no service, and never reads
production journal data. Prefer cutoff aggregates from the approved publisher
host for history. Optional Isaac trade snapshots remain a separate comparison.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import uuid

DEPLOY = Path(__file__).resolve().parents[2] / "deploy"
MAX_BUNDLES = 30
MAX_BUNDLE_BYTES = 20 * 1024 * 1024
MAX_SNAPSHOT_BYTES = 20 * 1024 * 1024
MAX_PROMPT_BYTES = 64 * 1024


def private_json(path: Path, limit: int):
    """Read an owner-private regular JSON file, without following symlinks."""
    data = private_bytes(path, limit)
    return json.loads(data)


def private_bytes(path: Path, limit: int) -> bytes:
    if not path.is_absolute() or path.is_symlink() or path.resolve() != path:
        raise ValueError("Require an absolute private regular file")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600
                or info.st_uid != os.geteuid() or not 0 < info.st_size <= limit):
            raise ValueError("Require an owned 0600 file within its size bound")
        data = os.read(fd, limit + 1)
        if len(data) != info.st_size:
            raise ValueError("Private file changed while reading")
        return data
    finally:
        os.close(fd)


def trial_root(path: Path) -> Path:
    if not path.is_absolute() or path.is_symlink() or path.resolve() != path or not path.is_dir():
        raise ValueError("Require an existing canonical isolated trial root")
    return path


def validate_trial(root: Path) -> str:
    """Run the owning sample-installation guard before any app or DB import."""
    root = trial_root(root)
    sys.path.insert(0, str(DEPLOY))
    try:
        from dot_trial_app import validate_environment
        validate_environment(os.environ, root)
    finally:
        sys.path.remove(str(DEPLOY))
    return os.environ["DATABASE_URL"]


def write_private_report(path: Path, report: str) -> None:
    """Publish an exclusive 0600 report after its seal check has passed."""
    if (not path.is_absolute() or path.is_symlink() or path.resolve() != path
            or not path.parent.is_dir() or path.parent.is_symlink()):
        raise ValueError("Require an absolute report path in an existing directory")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".scanner-report-", delete=False) as output:
            temporary = Path(output.name)
            output.write(report)
            output.flush()
            os.fsync(output.fileno())
        os.link(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trial-root", type=Path, required=True, help="Canonical root of the marked sample SQLite installation")
    actions = parser.add_subparsers(dest="action", required=True)
    prepare = actions.add_parser("prepare", help="Freeze a batch before any choices or reports")
    prepare.add_argument("--bundle", type=Path, action="append", required=True, help="Private 0600 capture, repeat up to 30")
    prepare.add_argument("--identifier", required=True, help="Fresh isolated assistant identity")
    prepare.add_argument("--seed", type=int, required=True, help="Recorded practice/exam split seed")
    prepare.add_argument("--exam-count", type=int, required=True, help="Number of held-out exam sessions")
    prepare.add_argument("--allow-holdout", action="store_true", help="Explicitly permit sessions on/after 2026-09-14")
    history = prepare.add_mutually_exclusive_group()
    history.add_argument("--history-rows", type=Path, help="Optional private precomputed historical feature rows")
    history.add_argument("--history-cards", type=Path, help="Private cutoff aggregate cards; no per-trade rows required")
    prepare.add_argument("--prompt-file", type=Path, help="Optional private frozen Jo prompt text")
    prepare.add_argument("--prompt-version", default="tj-shadow-selection-v3")
    prepare.add_argument("--decision-delay-seconds", type=int, default=60)
    prepare.add_argument("--cost-per-share", type=float, default=0, help="Proxy dollars per share per side")
    prepare.add_argument("--slippage-bps", type=float, default=0, help="Adverse proxy slippage per side")
    opportunity = actions.add_parser("prepare-opportunities", help="Import an unchanged discovery-only Mac opportunity pilot")
    opportunity.add_argument("--bundle", type=Path, required=True, help="Private 0600 frozen bridge bundle")
    opportunity.add_argument("--identifier", required=True, help="Fresh isolated opportunity identity")
    report = actions.add_parser("report", help="Write a sealed run's Markdown report")
    report.add_argument("--run-id", required=True)
    report.add_argument("--output", type=Path, required=True, help="Fresh absolute 0600 Markdown path")
    report.add_argument("--isaac-trades", type=Path, help="Optional private actual option-trade snapshot")
    abandon = actions.add_parser("abandon", help="End an unfinished run without unlocking an exam")
    abandon.add_argument("--run-id", required=True)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    url = validate_trial(args.trial_root)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    # Imports below this line may load app.database or model metadata. The
    # validator already pinned the exact marked SQLite URL and checked fills.
    from sqlmodel import Session, create_engine
    from app.engine import access, scanner_replay
    from app.models import PracticeRun

    engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30})
    try:
        if args.action == "prepare-opportunities":
            from app.engine import opportunity_replay
            bundle = private_json(args.bundle, MAX_BUNDLE_BYTES)
            with access._LOCK, Session(engine) as db:
                access._serialized(db)
                runs = opportunity_replay.prepare(db, bundle, args.identifier)
                manifest = scanner_replay.metadata(runs[0])["manifest"]
            grants = {"symbols": manifest["symbols"], "run_ids": [str(r.id) for r in runs],
                      "journal_read": False, "market_decision_write": True,
                      "historical_replay": True, "scanner_replay": True, "opportunity_feed": True}
            print(json.dumps({"run_ids": grants["run_ids"], "grants": grants}, sort_keys=True))
        elif args.action == "prepare":
            if len(args.bundle) > MAX_BUNDLES:
                raise ValueError("Too many capture files")
            bundles = [private_json(path, MAX_BUNDLE_BYTES) for path in args.bundle]
            if not all(isinstance(bundle, dict) for bundle in bundles):
                raise ValueError("Capture must contain JSON objects")
            history = private_json(args.history_rows, MAX_SNAPSHOT_BYTES) if args.history_rows else []
            if not isinstance(history, list):
                raise ValueError("Historical feature file must contain a list")
            cards = private_json(args.history_cards, MAX_SNAPSHOT_BYTES) if args.history_cards else None
            if cards is not None and not isinstance(cards, dict):
                raise ValueError("History aggregate file must contain an object")
            prompt = (private_bytes(args.prompt_file, MAX_PROMPT_BYTES).decode("utf-8")
                      if args.prompt_file else scanner_replay.DEFAULT_PROMPT)
            with access._LOCK, Session(engine) as db:
                access._serialized(db)
                runs = scanner_replay.prepare_batch(db, bundles, identifier=args.identifier, seed=args.seed,
                    exam_count=args.exam_count, prompt_text=prompt, prompt_version=args.prompt_version,
                    history_rows=history, history_cards=cards, allow_holdout=args.allow_holdout,
                    policy=scanner_replay.market.scoring_policy(args.decision_delay_seconds,
                                                               args.cost_per_share, args.slippage_bps))
                run_ids = [str(run.id) for run in runs]
            grants = {"symbols": list(scanner_replay.market.rules.UNIVERSE),
                      "run_ids": run_ids, "journal_read": False,
                      "market_decision_write": True, "historical_replay": True, "scanner_replay": True}
            print(json.dumps({"run_ids": grants["run_ids"], "grants": grants}, sort_keys=True))
        else:
            run_id = uuid.UUID(args.run_id)
            if str(run_id) != args.run_id:
                raise ValueError("Require a canonical run UUID")
            with Session(engine) as db:
                run = db.get(PracticeRun, run_id)
                if not scanner_replay.eligible(run):
                    raise ValueError("Scanner replay run unavailable")
                if args.action == "abandon":
                    with access._LOCK:
                        access._serialized(db)
                        scanner_replay.abandon(db, run)
                    print(json.dumps({"run_id": args.run_id, "status": run.status, "phase": scanner_replay.metadata(run)["phase"]}))
                else:
                    from app.engine import scanner_replay_report
                    snapshot = private_json(args.isaac_trades, MAX_SNAPSHOT_BYTES) if args.isaac_trades else None
                    if snapshot is not None and not isinstance(snapshot, list):
                        raise ValueError("Isaac snapshot must contain a list")
                    if scanner_replay.metadata(run)["manifest"].get("kind") == "opportunity_feed":
                        if snapshot is not None:
                            raise ValueError("Opportunity pilot does not link real trades")
                        markdown = "# Opportunity selection development\n\n```json\n" + json.dumps(scanner_replay.report(db, run), indent=2) + "\n```\n"
                    else:
                        markdown = scanner_replay_report.render_markdown(db, run, isaac_trades=snapshot)
                    write_private_report(args.output, markdown)
                    print(json.dumps({"run_id": args.run_id, "report": str(args.output)}))
    finally:
        engine.dispose()


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001 -- never echo provider data, path contents or credentials
        raise SystemExit("Scanner replay operator refused; check isolated trial, private files and run seal") from None
