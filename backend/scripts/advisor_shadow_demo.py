"""Create/revoke a disposable manual assignment; never use a hosted database."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

from sqlmodel import Session, create_engine

from app.engine import advisor_shadow


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["create", "revoke"])
    parser.add_argument("config", type=Path, help="Private local capability file; never paste its contents into chat")
    args = parser.parse_args()
    config = args.config.resolve()
    if args.action == "create":
        database = config.with_suffix(".db")
        if config.exists() or database.exists():
            parser.error("Use fresh paths; existing demo evidence is never replaced")
        # Reserve both files exclusively; an interrupted creation is not silently retried.
        config.parent.mkdir(parents=True, exist_ok=True)
        for path in (config, database):
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(fd)
        backend = Path(__file__).resolve().parents[1]
        url = f"sqlite:///{database}"
        env = {"PATH": os.environ.get("PATH", ""), "DATABASE_URL": url, "MIGRATION_DATABASE_URL": url}
        subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=backend, env=env, check=True)
        engine = create_engine(url)
        with Session(engine) as db:
            run_id, assignment_id, capability = advisor_shadow.create_fixture(db)
        config.write_text(json.dumps({"database": str(database), "assignment_id": str(assignment_id), "capability": capability}))
        print(f"Invented demo run: {run_id}. Capability saved privately. No provider/model call or paper arm.")
        print(f"Serve with: .venv/bin/python advisor_shadow_demo.py {config}")
        print(f"Owner UI: use this demo database, then open /?practice_run={run_id}")
    else:
        if config.stat().st_mode & 0o077:
            parser.error("Require a private capability file")
        data = json.loads(config.read_text())
        database = Path(data["database"])
        if not database.is_absolute() or not database.is_file() or database.suffix != ".db":
            parser.error("Invalid local demo database")
        engine = create_engine(f"sqlite:///{database}")
        with Session(engine) as db:
            advisor_shadow.set_enabled(db, uuid.UUID(data["assignment_id"]), False)
        print("Demo capability revoked; original choices retained.")


if __name__ == "__main__":
    main()
