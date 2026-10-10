"""Root-only preparation of the approved MU/NBIS simulated decision exercise."""
import argparse
import json
import os
from pathlib import Path
import re
import secrets
import sys
import tempfile

RUNTIME = Path("/opt/tradejournal-dot-trial/runtime")
CONFIG = Path("/etc/tradejournal-dot-trial")


def main():
    if os.geteuid() != 0:
        raise SystemExit("Run as root on the approved sample trial")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--identifier")
    parser.add_argument("--rotate", action="store_true")
    parser.add_argument("--replay", action="store_true", help="Prepare the separate sample paper replay")
    parser.add_argument("--scenarios", action="store_true", help="New distinct frozen MU/NBIS exercise (requires --replay)")
    args = parser.parse_args()
    if args.scenarios and not args.replay:
        parser.error("--scenarios requires --replay")
    args.identifier = args.identifier or ("trader-jo-scenarios" if args.scenarios else "trader-jo-replay" if args.replay else "trader-jo-decisions")
    if not re.fullmatch(r"[a-z][a-z0-9_-]{2,63}", args.identifier) or args.identifier == "owner":
        raise ValueError("Choose a separate sample assistant ID")
    sys.path.insert(0, str(RUNTIME / "backend"))
    from dot_trial_control import environment
    from dot_trial_app import validate_environment
    values = environment()
    validate_environment(values)
    if values.get("TJ_SAMPLE_DECISION_WRITES") != "true":
        raise ValueError("Sample decision writing must be explicitly enabled first")
    credential_file = CONFIG / (args.identifier + "-credential.json")
    if credential_file.is_symlink() or (credential_file.exists() and not args.rotate):
        raise ValueError("Credential already exists; explicit --rotate is required")
    os.environ.clear()
    os.environ.update(values)
    from sqlmodel import Session
    from app.database import engine
    from app.engine import access, sample_practice, sample_replay
    from app.models import AccessPrincipal
    from datetime import timedelta
    with Session(engine) as db:
        previous = db.get(AccessPrincipal, args.identifier)
        if previous and not args.rotate:
            raise ValueError("Assistant already exists; explicit --rotate is required")
        run = sample_replay.prepare(db, scenarios=args.scenarios) if args.replay else sample_practice.prepare(db)
        grants = {"symbols": ["MU", "NBIS"], "run_ids": [str(run.id)], "journal_read": False, "decision_write": True}
        if args.replay:
            grants["sample_replay"] = True
        access.grant_valid(grants)
        if previous:
            key = secrets.token_urlsafe(32)
            previous.key_hash = access.HASHER.hash(key)
            previous.version += 1
            previous.enabled = True
            previous.credential_expires_at = access.now() + timedelta(days=30)
            previous.grants_json = json.dumps(grants)
            db.add(previous)
            access.audit(db, access.OWNER, "assistant_reset", "accepted", args.identifier)
            db.commit()
        else:
            key = access.create_assistant(db, args.identifier, grants)
        credential = {"identifier": args.identifier, "key": key, "origin": values["TJ_ASSISTANT_ORIGIN"],
            "run_id": str(run.id), "day": run.day.isoformat()}
        try:
            with tempfile.NamedTemporaryFile(mode="w", dir=CONFIG, delete=False) as target:
                staged = Path(target.name)
                json.dump(credential, target)
            staged.chmod(0o600)
            os.replace(staged, credential_file)
        except BaseException:
            row = db.get(AccessPrincipal, args.identifier)
            row.enabled = False
            row.version += 1
            db.add(row)
            db.commit()
            raise
    print("Sample decision run and scoped login prepared. Credential saved privately; no key printed.")


if __name__ == "__main__":
    main()
