"""Root-only import into the marked isolated trial; one fresh decision-only login."""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
from zoneinfo import ZoneInfo

RUNTIME = Path("/opt/tradejournal-dot-trial/runtime")
CONFIG = Path("/etc/tradejournal-dot-trial")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--identifier")
    parser.add_argument("--proof", action="store_true", help="Separate operational proof session; never Jo's decisions")
    args = parser.parse_args()
    args.identifier = args.identifier or ("market-writer-proof" if args.proof else "trader-jo-market")
    if os.geteuid() != 0 or CONFIG.is_symlink() or not CONFIG.is_dir():
        raise ValueError("Run only as root on the approved trial")
    if not re.fullmatch(r"[a-z][a-z0-9_-]{2,63}", args.identifier) or args.identifier == "owner":
        raise ValueError("Choose a separate market assistant ID")
    source = CONFIG / ("market-handoff-" + datetime.now(ZoneInfo("America/New_York")).date().isoformat() + ".json")
    if (source.is_symlink() or source.stat().st_uid != 0 or stat.S_IMODE(source.stat().st_mode) != 0o600
            or not source.is_file() or source.stat().st_size > 1_048_576):
        raise ValueError("Require the bounded root-private market handoff")
    bundle = json.loads(source.read_bytes())
    sys.path.insert(0, str(RUNTIME / "backend"))
    from dot_trial_control import environment
    from dot_trial_app import validate_environment
    values = environment()
    validate_environment(values)
    if values.get("TJ_MARKET_DECISION_WRITES") != "true":
        raise ValueError("Market decisions must be explicitly enabled first")
    os.environ.clear()
    os.environ.update(values)
    from sqlmodel import Session
    from app.database import engine
    from app.engine import access, market_practice
    from app.models import AccessPrincipal
    target = CONFIG / (args.identifier + "-credential.json")
    if target.is_symlink():
        raise ValueError("Credential cannot be a symlink")
    with access._LOCK, Session(engine) as db:
        access._serialized(db)
        if target.exists() and not db.get(AccessPrincipal, args.identifier):
            raise ValueError("An unmatched retained credential prevents a new import")
        run = market_practice.prepare(db, bundle, identifier=args.identifier, proof=args.proof)
        grants = {"symbols": ["MU", "NBIS"], "run_ids": [str(run.id)], "journal_read": False,
            "market_decision_write": True}
        previous = db.get(AccessPrincipal, args.identifier)
        if previous or target.exists():
            if (not previous or not previous.enabled or json.loads(previous.grants_json) != grants or not target.is_file()
                    or target.stat().st_uid != 0 or stat.S_IMODE(target.stat().st_mode) != 0o600):
                raise ValueError("Existing login cannot be rotated, reused or repointed implicitly")
            retained = json.loads(target.read_text())
            if (retained.get("identifier") != args.identifier or retained.get("run_id") != str(run.id)
                    or not access.HASHER.verify(previous.key_hash, retained.get("key", ""))):
                raise ValueError("Existing credential does not match the frozen session")
            print("Existing market session/login retained; no evidence or credential changed.")
            return
        key = access.create_assistant(db, args.identifier, grants)
        try:
            with tempfile.NamedTemporaryFile(mode="w", dir=CONFIG, delete=False) as staged:
                json.dump({"identifier": args.identifier, "key": key, "origin": values["TJ_ASSISTANT_ORIGIN"],
                    "run_id": str(run.id), "day": run.day.isoformat()}, staged)
                staging = Path(staged.name)
            staging.chmod(0o600)
            os.replace(staging, target)
        except BaseException:
            row = db.get(AccessPrincipal, args.identifier)
            row.enabled = False
            row.version += 1
            db.add(row)
            db.commit()
            raise
    print("Real-market decision session/login saved privately; no key printed. No watcher or order started.")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        raise SystemExit("Market import failed; original logins remain unchanged") from None
