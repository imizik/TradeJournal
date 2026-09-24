#!/usr/bin/env python3
"""Push a phone notification when the private server stops doing its job.

tradejournal-alerts.timer runs `check` every two minutes. Each pass reads the
loopback API and systemd, compares what it sees with the previous pass, and
sends one ntfy message when a problem starts and one when it clears — never a
repeat. It can also ping a dead-man's-switch URL, so an outside service
notices when this server goes quiet altogether.
"""

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
from http.client import HTTPException
import json
import os
from pathlib import Path
import subprocess
import time
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

API = "http://127.0.0.1:8080"
ENV_FILE = Path("/etc/tradejournal/alerts.env")
STATE_FILE = Path("/var/lib/tradejournal/alerts/state.json")

# How long a problem must last before it is worth waking a phone. A deploy
# restarts the API for about a minute; the five-minute Gmail timer retries.
API_GRACE = 5 * 60
GMAIL_GRACE = 10 * 60
TIMER_GRACE = 15 * 60

# Listeners report through their own checks, not as failed jobs.
LISTENER_JOBS = {"gmail_listener", "webull_listener"}
GMAIL_JOBS = {"gmail_sync", "gmail_push", "gmail_watch_renew"}
# An interrupted import can leave fills saved without the rebuild that follows.
IMPORT_JOBS = {"gmail_sync", "gmail_push", "full_pipeline", "resync_all"}

SERVICES = {
    "tradejournal-backup.service": (
        "Nightly backup", "The nightly backup didn't finish, so there's no fresh restore point yet."
    ),
    "tradejournal-offsite-backup.service": (
        "Offsite backup", "The encrypted copy to Cloudflare R2 didn't finish."
    ),
    "tradejournal-sync-pipeline.service": (
        "Scheduled Sync Everything", "The 8 AM / 5 PM Sync Everything couldn't be started."
    ),
}
TIMERS = {
    "tradejournal-backup.timer": "Nightly backup",
    "tradejournal-offsite-backup.timer": "Offsite backup",
    "tradejournal-sync-pipeline.timer": "Scheduled Sync Everything",
    "tradejournal-gmail-sync.timer": "Five-minute Gmail check",
}


@dataclass
class Problem:
    title: str
    message: str
    grace: float = 0
    recovered: str = ""


def load_config() -> dict[str, str]:
    """systemd passes alerts.env as the environment; a manual root run reads it."""
    config = {}
    try:
        for line in ENV_FILE.read_text().splitlines():
            key, sep, value = line.strip().partition("=")
            if sep and key and not key.startswith("#"):
                config[key.strip()] = value.strip().strip("'\"")
    except OSError:
        pass
    config.update({key: value for key, value in os.environ.items() if key in {"NTFY_URL", "NTFY_TOKEN", "ALERT_APP_URL", "HEALTHCHECK_PING_URL"}})
    return config


def get(path: str):
    with urlopen(f"{API}{path}", timeout=15) as response:
        return json.load(response)


def timestamp(value: str | None) -> float | None:
    if not value:
        return None
    moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return (moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)).timestamp()


def first_line(text: str | None, limit: int = 180) -> str:
    lines = (text or "").strip().splitlines()
    line = lines[0] if lines else "no error was recorded"
    return line if len(line) <= limit else f"{line[:limit - 1]}…"


def duration(seconds: float) -> str:
    minutes = max(1, round(seconds / 60))
    return f"{minutes} minute{'s' * (minutes != 1)}" if minutes < 120 else f"{round(minutes / 60)} hours"


def gmail_problem(health: dict) -> Problem | None:
    if health.get("status") not in {"down", "degraded"}:
        return None
    title = "Gmail needs reconnecting" if health.get("action") == "reconnect_gmail" else "Robinhood import stopped"
    return Problem(title, str(health.get("message")), GMAIL_GRACE, "Robinhood import is live again")


def webull_problem(status: dict, watching_since: float) -> dict[str, Problem | None]:
    job = status.get("job") or {}
    if job.get("status") in {"queued", "running", "succeeded"}:
        return {"webull": None}
    finished = timestamp(job.get("finished_at")) or timestamp(job.get("updated_at"))
    if job.get("status") == "failed" and finished is not None and finished >= watching_since:
        return {"webull": Problem(
            "Webull connection stopped",
            f"Webull fills won't import until the listener is started again. {first_line(job.get('error'))}",
            recovered="Webull is connected again",
        )}
    return {}  # never started, or it failed before alerts were watching


def job_problems(runs: list[dict], watching_since: float, gmail_down: bool) -> dict[str, Problem | None]:
    """Judge each job type by its newest finished run; /sync/runs is newest first."""
    latest: dict[str, dict] = {}
    for run in runs:
        if run["status"] in {"succeeded", "failed"} and run["job_type"] not in LISTENER_JOBS:
            latest.setdefault(run["job_type"], run)
    observed: dict[str, Problem | None] = {}
    for job_type, run in latest.items():
        if gmail_down and job_type in GMAIL_JOBS:
            continue  # the Gmail alert already covers these
        label = run.get("label") or job_type
        if run["status"] == "succeeded":
            observed[f"job:{job_type}"] = None
            continue
        finished = timestamp(run.get("finished_at")) or timestamp(run.get("created_at")) or 0
        if finished < watching_since:
            continue
        message = first_line(run.get("error_summary"))
        if "interrupted" in message.lower():
            message = (
                "It stopped part-way. Open Sync Center and run Rebuild trades so P&L is right, then run it again."
                if job_type in IMPORT_JOBS
                else "It stopped part-way. Run it again from Sync Center."
            )
        observed[f"job:{job_type}"] = Problem(
            f"{label} failed", message, GMAIL_GRACE if job_type in GMAIL_JOBS else 0, f"{label} is working again"
        )
    return observed


def unit_problems(units: dict[str, dict[str, str]]) -> dict[str, Problem | None]:
    observed: dict[str, Problem | None] = {}
    for name, (label, explanation) in SERVICES.items():
        unit = units.get(name, {})
        if unit.get("ActiveState") == "failed":
            observed[name] = Problem(f"{label} failed", f"{explanation} ({name})", recovered=f"{label} is working again")
        elif unit.get("Result") == "success" and unit.get("ExecMainExitTimestampMonotonic", "0") != "0":
            # Only a run since boot proves recovery; a reboot resets the result.
            observed[name] = None
    for name, label in TIMERS.items():
        unit = units.get(name, {})
        if unit.get("LoadState") != "loaded":
            continue
        observed[name] = None if unit.get("ActiveState") == "active" else Problem(
            f"{label} is switched off",
            f"Its schedule isn't running, so it won't happen until it's turned back on. ({name})",
            TIMER_GRACE,
            f"{label} is scheduled again",
        )
    return observed


def systemd_units() -> dict[str, dict[str, str]]:
    output = subprocess.run(
        ["systemctl", "show", *SERVICES, *TIMERS,
         "--property=Id,LoadState,ActiveState,Result,ExecMainExitTimestampMonotonic"],
        check=True, capture_output=True, text=True,
    ).stdout
    units = {}
    for block in output.strip().split("\n\n"):
        fields = dict(line.split("=", 1) for line in block.splitlines() if "=" in line)
        if fields.get("Id"):
            units[fields["Id"]] = fields
    return units


def observe(watching_since: float) -> dict[str, Problem | None]:
    observed: dict[str, Problem | None] = {}
    try:
        get("/health")
        gmail = get("/gmail/health")
        webull = get("/webull/events/status")
        runs = get("/sync/runs?limit=200")
    except (OSError, ValueError, HTTPException) as exc:
        # Everything below comes from the API, so its answers are unknown now.
        observed["api"] = Problem(
            "TradeJournal isn't responding",
            f"The app on the server hasn't answered for over five minutes, so fills aren't importing. ({first_line(str(exc), 120)})",
            API_GRACE,
            "TradeJournal is responding again",
        )
    else:
        observed["api"] = None
        observed["gmail"] = gmail_problem(gmail)
        observed.update(webull_problem(webull, watching_since))
        observed.update(job_problems(runs, watching_since, gmail_down=observed["gmail"] is not None))
    observed.update(unit_problems(systemd_units()))
    return observed


def evaluate(observed: dict[str, Problem | None], state: dict, now: float) -> tuple[list[dict], dict]:
    """Return the notifications this pass owes and the state that follows them.

    A key missing from `observed` is unknown this pass and keeps its state.
    """
    conditions = {key: dict(value) for key, value in state.get("conditions", {}).items()}
    notices = []
    for key, problem in observed.items():
        entry = conditions.get(key)
        if problem is None:
            if entry and entry.get("alerted"):
                notices.append({
                    "keys": [key], "recovered": True, "title": entry["recovered"],
                    "message": f"Resolved after {duration(now - entry['since'])}.",
                })
            conditions.pop(key, None)
            continue
        entry = entry or {"since": now}
        entry.update(title=problem.title, message=problem.message, recovered=problem.recovered or f"{problem.title}: resolved")
        if not entry.get("alerted") and now - entry["since"] >= problem.grace:
            entry["alerted"] = True
            notices.append({"keys": [key], "recovered": False, "title": problem.title, "message": problem.message})
        conditions[key] = entry
    return merge_jobs(notices), {**state, "conditions": conditions}


def merge_jobs(notices: list[dict]) -> list[dict]:
    """A pipeline fails with its step; send the pair as one message."""
    merged = []
    for recovered in (False, True):
        jobs = [n for n in notices if n["recovered"] is recovered and n["keys"][0].startswith("job:")]
        if len(jobs) > 1:
            title = f"{len(jobs)} sync jobs are working again" if recovered else f"{len(jobs)} sync jobs failed"
            lines = [n["title"] if recovered else f"• {n['title']}: {n['message']}" for n in jobs]
            merged.append({"keys": [n["keys"][0] for n in jobs], "recovered": recovered, "title": title, "message": "\n".join(lines)})
            notices = [n for n in notices if n not in jobs]
    return notices + merged


def publish(config: dict[str, str], title: str, message: str, *, recovered: bool = False) -> None:
    """ntfy's JSON form carries any title text; headers are limited to Latin-1."""
    target = urlsplit(config["NTFY_URL"])
    body = {
        "topic": target.path.strip("/"),
        "title": title,
        "message": message,
        "priority": 2 if recovered else 4,
        "tags": ["white_check_mark"] if recovered else ["warning"],
    }
    if config.get("ALERT_APP_URL"):
        body["click"] = config["ALERT_APP_URL"]
    headers = {"Content-Type": "application/json"}
    if config.get("NTFY_TOKEN"):
        headers["Authorization"] = f"Bearer {config['NTFY_TOKEN']}"
    request = Request(f"{target.scheme}://{target.netloc}/", data=json.dumps(body).encode(), headers=headers, method="POST")
    with urlopen(request, timeout=15):
        pass


def ping(config: dict[str, str], healthy: bool) -> None:
    url = config.get("HEALTHCHECK_PING_URL")
    if not url:
        return
    try:
        with urlopen(url if healthy else f"{url.rstrip('/')}/fail", timeout=10):
            pass
    except OSError as exc:
        print(f"Dead-man's-switch ping failed: {first_line(str(exc), 120)}")


def read_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except (OSError, ValueError):
        return {}


def write_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    pending = STATE_FILE.with_suffix(".tmp")
    pending.write_text(json.dumps(state, indent=2, sort_keys=True))
    pending.replace(STATE_FILE)


def check(config: dict[str, str], now: float | None = None) -> bool:
    now = time.time() if now is None else now
    state = read_state()
    # Failures that finished before the first pass are history, not news.
    state.setdefault("watching_since", now)
    notices, following = evaluate(observe(state["watching_since"]), state, now)
    delivered = True
    for notice in notices:
        try:
            publish(config, notice["title"], notice["message"], recovered=notice["recovered"])
            print(f"Sent: {notice['title']}")
        except OSError as exc:
            delivered = False
            print(f"Could not send '{notice['title']}': {first_line(str(exc), 120)}")
            # Leave the condition as it was so the next pass tries again.
            for key in notice["keys"]:
                if notice["recovered"]:
                    following["conditions"][key] = state["conditions"][key]
                else:
                    following["conditions"][key]["alerted"] = False
    following["checked_at"] = now
    write_state(following)
    ping(config, delivered)
    return delivered


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["check", "test"])
    args = parser.parse_args()
    config = load_config()
    if not config.get("NTFY_URL"):
        raise SystemExit(f"NTFY_URL is not set; configure {ENV_FILE}")
    if args.action == "test":
        publish(config, "TradeJournal alerts are on", "This is a test. Problems with the server will arrive here.")
        print("Test notification sent")
    elif not check(config):
        raise SystemExit("One or more notifications could not be sent")


if __name__ == "__main__":
    main()
