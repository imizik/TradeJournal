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
    elif service == "ingress":
        from sqlalchemy.engine import make_url

        if os.environ.get("TRADINGVIEW_INGRESS_ENABLED", "").lower() != "true":
            raise SystemExit("TradingView ingress is disabled")
        raw_url = os.environ.get("TRADINGVIEW_DATABASE_URL", "").strip()
        try:
            url = make_url(raw_url)
            valid = url.drivername == "postgresql+psycopg" and bool(url.host and url.database and url.username)
        except Exception:
            valid = False
        if not valid:
            raise SystemExit("Ingress requires an explicit postgresql+psycopg database URL")
        if len(os.environ.get("TRADINGVIEW_WEBHOOK_TOKEN", "").strip().encode("utf-8")) < 32:
            raise SystemExit("Ingress requires a dedicated webhook token of at least 32 bytes")
        # Never pass inherited private credentials, Python overrides or libpq
        # routing options to the public process, even in a manual launch.
        allowed = {"TRADINGVIEW_DATABASE_URL", "TRADINGVIEW_WEBHOOK_TOKEN", "TRADINGVIEW_INGRESS_ENABLED"}
        environment = {key: os.environ[key] for key in allowed}
        environment.update(
            PATH="/usr/bin:/bin", HOME="/nonexistent", LANG="C.UTF-8",
            PYTHONDONTWRITEBYTECODE="1", PYTHONUNBUFFERED="1",
            TRADEJOURNAL_RELEASE=metadata["release_id"],
        )
        os.chdir(RELEASE / "backend")
        command = [sys.executable, "-m", "uvicorn", "app.tradingview_ingress:app",
                   "--host", "127.0.0.1", "--port", "8090", "--no-access-log"]
        os.execve(command[0], command, environment)
        return
    else:
        if not os.environ.get("DATABASE_URL"):
            raise SystemExit("DATABASE_URL is required; deployment never falls back to a new SQLite database")
        if os.environ.get("MIGRATION_DATABASE_URL"):
            raise SystemExit("Migration credentials belong only in migration.env")
        os.chdir(RELEASE / "backend")
        os.environ.update(JOB_EXECUTION_MODE="external", JOB_LOCK_DIR=str(STATE / "job-locks"))
        if service == "api":
            command = [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8080"]
        elif service == "worker" and args in (["sync"], ["polygon"], ["webull"], ["gmail"]):
            command = [sys.executable, "-m", "app.jobs.worker", "--lane", args[0]]
        else:
            raise SystemExit("Expected api, frontend, or worker sync|polygon|webull|gmail")
    os.execv(command[0], command)


if __name__ == "__main__":
    main()
