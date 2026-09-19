"""systemd entrypoint. Network bindings and worker ownership are not configurable."""

import json
import os
from pathlib import Path
import sys

RELEASE = Path(__file__).resolve().parents[1]
STATE = Path("/var/lib/tradejournal")


def main() -> None:
    service, *args = sys.argv[1:]
    metadata = json.loads((RELEASE / "release.json").read_text())
    os.environ["TRADEJOURNAL_RELEASE"] = metadata["release_id"]
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    if service == "frontend":
        os.chdir(RELEASE / "frontend")
        os.environ.update(HOSTNAME="127.0.0.1", PORT="3000", API_INTERNAL_URL="http://127.0.0.1:8080")
        command = [str(RELEASE / "bin/node"), "server.js"]
    else:
        if not os.environ.get("DATABASE_URL"):
            raise SystemExit("DATABASE_URL is required; deployment never falls back to a new SQLite database")
        if os.environ.get("MIGRATION_DATABASE_URL"):
            raise SystemExit("Migration credentials belong only in migration.env")
        os.chdir(RELEASE / "backend")
        os.environ.update(JOB_EXECUTION_MODE="external", JOB_LOCK_DIR=str(STATE / "job-locks"))
        if service == "api":
            command = [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8080"]
        elif service == "worker" and args in (["sync"], ["polygon"], ["webull"]):
            command = [sys.executable, "-m", "app.jobs.worker", "--lane", args[0]]
        else:
            raise SystemExit("Expected api, frontend, or worker sync|polygon|webull")
    os.execv(command[0], command)


if __name__ == "__main__":
    main()
