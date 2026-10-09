"""Root-only controls for the isolated sample trial; never operates on production data."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess

CONFIG = Path("/etc/tradejournal-dot-trial")
RUNTIME = Path("/opt/tradejournal-dot-trial/runtime")
STATE = Path("/var/lib/tradejournal-dot-trial")


def environment():
    values = {"PATH": os.environ["PATH"]}
    for name in ("access-backend.env", "trial-runtime.env"):
        for line in (CONFIG / name).read_text().splitlines():
            if line and not line.startswith("#"):
                key, value = line.split("=", 1)
                values[key] = value.strip("'")
    expected = f"sqlite:///{STATE}/data/trial.db"
    if values.get("DATABASE_URL") != expected or values.get("MIGRATION_DATABASE_URL") != expected:
        raise ValueError("Trial controls refuse any other database")
    return values


def revoke(identifier):
    if not re.fullmatch(r"[a-z][a-z0-9_-]{2,63}", identifier) or identifier == "owner":
        raise ValueError("Choose an assistant ID")
    revoke_assistants(identifier)


def revoke_rows(db, identifier=None):
    from sqlmodel import select
    from app.engine import access
    from app.models import AccessPrincipal
    access._serialized(db)
    rows = db.exec(select(AccessPrincipal).where(AccessPrincipal.id != access.OWNER)).all()
    if identifier is not None:
        rows = [row for row in rows if row.id == identifier]
        if not rows:
            raise ValueError("Assistant not found")
    for row in rows:
        row.enabled = False
        row.version += 1
        db.add(row)
        access.audit(db, access.OWNER, "assistant_revoke", "accepted", row.id)
    db.commit()


def revoke_assistants(identifier=None):
    script = """
from sqlmodel import Session
from app.database import engine
from dot_trial_control import revoke_rows
from dot_trial_app import validate_environment
import os
validate_environment(os.environ)
with Session(engine) as db:
    revoke_rows(db, IDENTIFIER)
"""
    subprocess.run([str(RUNTIME / "backend/.venv/bin/python"), "-c", f"IDENTIFIER={identifier!r}\n" + script],
        cwd=RUNTIME / "backend", env={**environment(), "PYTHONPATH": str(RUNTIME / "deploy")}, check=True, capture_output=True, text=True)
    print("Trial assistants revoked; existing sessions are invalidated.")


def disable():
    source = Path("/etc/caddy/Caddyfile")
    old = source.read_text()
    marker = "import /etc/caddy/tradejournal-dot-trial.caddy"
    if old.count(marker) != 1:
        raise ValueError("Trial proxy entry is missing or ambiguous; active configuration unchanged")
    candidate = source.with_name("Caddyfile.dot-trial-disable")
    candidate.write_text(old.replace(marker, "# Isolated sample trial disabled"))
    candidate.chmod(source.stat().st_mode & 0o777)
    subprocess.run(["caddy", "validate", "--config", str(candidate), "--adapter", "caddyfile"],
        check=True, capture_output=True, text=True)
    os.replace(candidate, source)
    try:
        reload = subprocess.run(["systemctl", "reload", "caddy"], capture_output=True)
        if reload.returncode:
            subprocess.run(["systemctl", "restart", "caddy"], check=True, capture_output=True)
    except BaseException:
        source.write_text(old)
        subprocess.run(["systemctl", "restart", "caddy"], capture_output=True)
        raise
    # Remove public access first, revoke every trial login and disable its
    # frontend profile before stopping services. Re-enabling needs a new key.
    revoke_assistants()
    assistant_file = CONFIG / "access-assistant.env"
    assistant_file.write_text(assistant_file.read_text().replace("TJ_ASSISTANT_ENABLED=true", "TJ_ASSISTANT_ENABLED=false"))
    services = ["tradejournal-dot-trial-api.service", "tradejournal-dot-trial-assistant.service", "tradejournal-dot-trial-owner.service"]
    sockets = [f"tradejournal-dot-trial-{profile}-bridge.socket" for profile in ("assistant", "owner")]
    bridges = [f"tradejournal-dot-trial-{profile}-bridge.service" for profile in ("assistant", "owner")]
    subprocess.run(["systemctl", "disable", "--now", *sockets, *services], check=True, capture_output=True)
    subprocess.run(["systemctl", "stop", *bridges], check=True, capture_output=True)
    manifest = json.loads((CONFIG / "manifest.json").read_text())
    manifest["published"] = False
    (CONFIG / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print("Public trial entry disabled and trial processes stopped. Production configuration and trial data retained.")


def main():
    if os.geteuid() != 0:
        raise SystemExit("Run as root on the approved trial VPS")
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    command = commands.add_parser("revoke")
    command.add_argument("identifier")
    commands.add_parser("disable")
    args = parser.parse_args()
    if args.action == "revoke":
        revoke(args.identifier)
    else:
        disable()


if __name__ == "__main__":
    main()
