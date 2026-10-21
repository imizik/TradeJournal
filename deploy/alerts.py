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
from datetime import date, datetime, timezone
from http.client import HTTPException
import json
import math
import os
from pathlib import Path
import subprocess
import time
from urllib.parse import urlsplit
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

import httpx

API = "http://127.0.0.1:8080"
ENV_FILE = Path("/etc/tradejournal/alerts.env")
STATE_FILE = Path("/var/lib/tradejournal/alerts/state.json")

# How long a problem must last before it is worth waking a phone. A deploy
# restarts the API for about a minute; the five-minute Gmail timer retries.
API_GRACE = 5 * 60
GMAIL_GRACE = 10 * 60
TIMER_GRACE = 15 * 60
# A deploy briefly holds an extra ~1.7 GB release; only a lasting warning counts.
DISK_GRACE = 30 * 60

# PostgreSQL, releases, runtimes and backups share these; each disk is checked once.
DISK_PATHS = ("/", "/var/lib/postgresql", "/var/backups/tradejournal")
DISK_WARNING = 80
DISK_CRITICAL = 90

# Listeners are not finite jobs. Gmail's has its own check; Webull is dormant.
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
    "tradejournal-options-snapshot.service": (
        "Options snapshot", "Today's after-close options snapshot couldn't be queued; it can't be taken after 8 PM New York."
    ),
    "tradejournal-rvol-history.service": (
        "Relative volume history", "The morning relative-volume history couldn't be started, so chart RVol may be missing today."
    ),
    "tradejournal-market-context.service": (
        "Earnings and VIX for Jo", "The earnings and VIX refresh couldn't be started; Jo's checks show the older values with their age."
    ),
    "tradejournal-plan-reviews.service": (
        "Nightly AI reviews", "Tonight's daily reviews on the Claude plan didn't run; the Daily page says why."
    ),
    "tradejournal-depth-recorder.service": (
        "Depth recorder", "The Level 2 depth recorder stopped, so the watchlist isn't being recorded."
    ),
    "tradejournal-depth-upload.service": (
        "Depth upload", "Finished depth days didn't reach R2; they stay on the VPS until an upload succeeds."
    ),
}
TIMERS = {
    "tradejournal-backup.timer": "Nightly backup",
    "tradejournal-offsite-backup.timer": "Offsite backup",
    "tradejournal-sync-pipeline.timer": "Scheduled Sync Everything",
    "tradejournal-gmail-sync.timer": "Five-minute Gmail check",
    "tradejournal-options-snapshot.timer": "After-close options snapshot",
    "tradejournal-rvol-history.timer": "Morning relative volume history",
    "tradejournal-market-context.timer": "Earnings and VIX for Jo",
}
# Opt-in schedules: only one the owner enabled can be "switched off".
OPT_IN_TIMERS = {
    "tradejournal-plan-reviews.timer": "Nightly AI reviews",
    "tradejournal-depth-upload.timer": "Nightly depth upload",
}


# Jo's morning brief, opt-in with JO_MORNING_ALERTS=true. Judged from the API's own
# GET /jo/morning delivery state; this check schedules, publishes and imports nothing.
ET = ZoneInfo("America/New_York")
MORNING_RUNNER_STALE = 3 * 60  # the runner passes every 30 s; six missed passes
MORNING_IMPORT_STALL = 2 * 60  # a submission with no receipt after four import passes
# The first pass after publication time takes up to 30 s plus two short provider reads;
# five minutes also covers a deploy restart, like API_GRACE.
MORNING_PUBLICATION_GRACE = 5 * 60
MORNING_CALENDAR_GRACE = TIMER_GRACE  # the calendar retries on its own; a lasting gap counts
MORNING_STATUS_GRACE = 10 * 60  # /jo/morning unreadable while the rest of the API answers
MORNING_KEEP_DAYS = 7  # long enough to review a five-session acceptance run

# Jo's scheduled market reads (09:50, 11:00, 12:30, 14:00 ET), opt-in with
# JO_MARKET_READ_ALERTS=true. Judged from GET /jo/market-reads, whose per-slot deadline
# (slot + 15 min, a proposal for the owner) and exchange calendar decide what is due.
MARKET_READ_IMPORT_STALE = 3 * 60  # the API checks Jo's read outbox every 30 s
MARKET_READ_STATUS_GRACE = MORNING_STATUS_GRACE


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
    config.update({key: value for key, value in os.environ.items() if key in {"NTFY_URL", "NTFY_TOKEN", "NTFY_IPV4_ONLY", "ALERT_APP_URL", "HEALTHCHECK_PING_URL", "JO_MORNING_ALERTS", "JO_MARKET_READ_ALERTS"}})
    return config


def get(path: str):
    with urlopen(Request(f"{API}{path}", headers={"x-tj-service": os.environ["TJ_SERVICE_KEY"]} if os.environ.get("TJ_SERVICE_KEY") else {}), timeout=15) as response:
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
    for name, label in {**TIMERS, **OPT_IN_TIMERS}.items():
        unit = units.get(name, {})
        if unit.get("LoadState") != "loaded" or (name in OPT_IN_TIMERS and unit.get("UnitFileState") != "enabled"):
            continue
        observed[name] = None if unit.get("ActiveState") == "active" else Problem(
            f"{label} is switched off",
            f"Its schedule isn't running, so it won't happen until it's turned back on. ({name})",
            TIMER_GRACE,
            f"{label} is scheduled again",
        )
    return observed


def disk_problems(paths=DISK_PATHS) -> dict[str, Problem | None]:
    """Percent used as df reports it. While critical, the warning keeps its state."""
    observed: dict[str, Problem | None] = {}
    seen = set()
    for path in paths:
        try:
            device = os.stat(path).st_dev
            usage = os.statvfs(path)
        except OSError:
            continue
        if device in seen:
            continue
        seen.add(device)
        used = usage.f_blocks - usage.f_bfree
        percent = math.ceil(100 * used / (used + usage.f_bavail)) if used + usage.f_bavail else 0
        free = f"{usage.f_bavail * usage.f_frsize / 1024**3:.1f} GB free on {path}"
        observed[f"disk:{path}:critical"] = Problem(
            f"Server disk is {percent}% full",
            f"Only {free}. Installs, backups and the database can fail soon; ask Claude what to clear.",
            recovered="Server disk is back under 90%",
        ) if percent >= DISK_CRITICAL else None
        if percent < DISK_CRITICAL:
            observed[f"disk:{path}:warning"] = Problem(
                f"Server disk is {percent}% full",
                f"{free}. Each deploy needs about 2 GB (a 1.7 GB release plus its download); ask Claude what to clear.",
                DISK_GRACE,
                "Server disk is back under 80%",
            ) if percent >= DISK_WARNING else None
    return observed


def systemd_units() -> dict[str, dict[str, str]]:
    output = subprocess.run(
        ["systemctl", "show", *SERVICES, *TIMERS, *OPT_IN_TIMERS,
         "--property=Id,LoadState,UnitFileState,ActiveState,Result,ExecMainExitTimestampMonotonic"],
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
        observed.update(job_problems(runs, watching_since, gmail_down=observed["gmail"] is not None))
    observed.update(unit_problems(systemd_units()))
    observed.update(disk_problems())
    return observed


def et_clock(value: str | None) -> str:
    moment = datetime.fromisoformat(value) if value else None
    return moment.astimezone(ET).strftime("%-I:%M %p ET") if moment else "the deadline"


def morning_problems(view: dict, now: float) -> dict[str, Problem | None]:
    """Morning-brief conditions from one /jo/morning read; a key left out is unknown this pass."""
    day = view["day"]
    automation, delivery = view.get("automation") or {}, view.get("delivery") or {}
    brief, publication = f"jo_morning:{day}:brief", f"jo_morning:{day}:publication"
    if not automation.get("enabled"):
        # Settings that fail to load stop the runner; that is a problem, not "turned off".
        # The brief and its packet stay unknown rather than being reported resolved.
        return {"jo_morning:runner": Problem(
            "Morning brief automation can't load its settings",
            "The app can't read the morning brief configuration, so it isn't publishing or importing.",
            API_GRACE, "Morning brief automation is running again",
        )} if automation.get("configuration_error") else {}
    observed: dict[str, Problem | None] = {}
    last = timestamp(automation.get("last_pass"))
    if last is None or now - last > MORNING_RUNNER_STALE:
        observed["jo_morning:runner"] = Problem(
            "Morning brief automation stopped",
            "The app hasn't published or imported Jo's morning brief for a few minutes, so a brief Jo sends may not reach TradeJournal.",
            API_GRACE, "Morning brief automation is running again",
        )
    else:
        # Pending and calendar facts come from the runner's last pass; only a fresh pass counts.
        observed["jo_morning:runner"] = None
        pending = automation.get("pending") or {}
        oldest = timestamp(pending.get("oldest_submitted_at"))
        observed["jo_morning:import"] = Problem(
            "A Jo submission is waiting to be imported",
            f"Check received it at {et_clock(pending.get('oldest_submitted_at'))}, but it isn't in the journal yet.",
            recovered="Jo's waiting submission was imported",
        ) if oldest is not None and now - oldest > MORNING_IMPORT_STALL else None
        observed["jo_morning:unreadable"] = Problem(
            "A Jo submission can't be read",
            "A file in the morning outbox is unreadable, so it can't be imported. Ask Claude to look at it.",
            recovered="No unreadable Jo submissions remain",
        ) if (pending.get("unreadable") or 0) > 0 else None
        # Weekends say nothing about the calendar either way, so the condition keeps its state.
        if date.fromisoformat(day).weekday() < 5:
            observed["jo_morning:calendar"] = Problem(
                "Market calendar unavailable for the morning brief",
                "The app can't confirm today's session, so it won't publish Jo's packet. Nothing is published on a guess.",
                MORNING_CALENDAR_GRACE, "The market calendar is available again",
            ) if automation.get("last_status") == "calendar_unavailable" else None
    state, fulfilment = delivery.get("publication"), delivery.get("fulfilment")
    if state == "missing":
        observed[publication] = Problem(
            "Jo's morning packet wasn't published",
            f"No packet for {day} by {et_clock(delivery.get('publish_at'))}. Jo can only report the gap.",
            MORNING_PUBLICATION_GRACE, "Jo's morning packet was published",
        )
    elif state in ("published", "pending", "not_expected"):
        observed[publication] = None
    if fulfilment == "missing":
        # Only the first alert is sent, so a read recorded later never triggers a resend.
        read = {"recorded": f" Jo read the packet at {et_clock(delivery.get('context_read_at'))} but nothing was saved"
                    " (a read doesn't show who started the run).",
                "not_recorded": " No read of the packet was recorded."}.get(delivery.get("context_read"), "")
        # A missing packet already explains the missing brief; one message, not two.
        observed[brief] = None if state == "missing" else Problem(
            "Jo's morning brief is missing",
            f"No brief for {day} was in TradeJournal by {et_clock(delivery.get('deadline'))}.{read} A later save will still show as late.",
            recovered="Jo's morning brief arrived late",
        )
    elif fulfilment in ("on_time", "late", "pending", "not_expected"):
        observed[brief] = None
    return observed


def observe_morning(now: float) -> tuple[dict[str, Problem | None], str | None, bool]:
    """Read today's morning state: (conditions, read error, automation deliberately off).

    A failed read leaves the other morning conditions unknown and is a condition itself.
    """
    day = datetime.fromtimestamp(now, ET).date().isoformat()
    unreadable = Problem(
        "Morning brief status unreadable",
        "The app answers, but its morning brief status doesn't, so the watchdog can't tell whether Jo's brief arrived.",
        MORNING_STATUS_GRACE, "Morning brief status is readable again",
    )
    try:
        view = get(f"/jo/morning?day={day}")
        automation = view.get("automation") or {}
        off = not automation.get("enabled") and not automation.get("configuration_error")
        return {**morning_problems(view, now), "jo_morning:status": None}, None, off
    except (OSError, ValueError, KeyError, TypeError, AttributeError, HTTPException) as exc:
        return {"jo_morning:status": unreadable}, f"Morning status unreadable ({type(exc).__name__})", False


def market_read_problems(view: dict, day: str, now: float) -> dict[str, Problem | None]:
    """Scheduled market-read conditions from one /jo/market-reads read; a key left out is unknown."""
    importer = view.get("importer") or {}
    stopped = Problem(
        "Jo's market reads aren't being checked",
        "The app isn't checking for Jo's market reads, so a missed read can't be seen.",
        API_GRACE, "Jo's market reads are being checked again",
    )
    if not importer.get("outbox_configured"):
        return {"jo_market_read:importer": stopped}
    last = timestamp(importer.get("last_ingest"))
    if last is None or now - last > MARKET_READ_IMPORT_STALE:
        # Without fresh imports a read may have arrived unseen; the slots stay unknown.
        return {"jo_market_read:importer": stopped}
    observed: dict[str, Problem | None] = {"jo_market_read:importer": None}
    session = next((s for s in view.get("sessions") or [] if s.get("session_date") == day), None)
    for slot in (session or {}).get("slots") or []:
        key, state = f"jo_market_read:{day}:{slot['slot'].replace(':', '')}", slot.get("delivery")
        label = et_clock(slot.get("scheduled_at")).removesuffix(" ET")
        if state == "missing":
            packet = (slot.get("packet") or {}).get("status")
            cause = {"failed": " The app's packet for this read failed, so Jo had no fresh data.",
                     "no_receipt": " The app has no record of preparing this read's packet."}.get(packet, "")
            observed[key] = Problem(
                f"Jo's {label} market read is missing",
                f"No read for the {label} slot was seen in TradeJournal by {et_clock(slot.get('deadline'))}.{cause}"
                " A read saved within 30 minutes of the slot will still be shown.",
                # Usually late, but a read Check saved in time can be imported after a failed handoff.
                recovered=f"Jo's {label} market read arrived; see the reliability screen for on time or late",
            )
        elif state in ("on_time", "late", "pending", "not_expected"):
            observed[key] = None
    return observed


def observe_market_reads(now: float) -> tuple[dict[str, Problem | None], str | None, bool]:
    """Read today's scheduled market reads: (conditions, read error, market watch deliberately off)."""
    day = datetime.fromtimestamp(now, ET).date().isoformat()
    unreadable = Problem(
        "Market read status unreadable",
        "The app answers, but its scheduled market read status doesn't, so the watchdog can't tell whether Jo's reads arrived.",
        MARKET_READ_STATUS_GRACE, "Market read status is readable again",
    )
    try:
        view = get("/jo/market-reads")
        if not view.get("market_watch_enabled"):
            return {"jo_market_read:status": None}, None, True
        return {**market_read_problems(view, day, now), "jo_market_read:status": None}, None, False
    except (OSError, ValueError, KeyError, TypeError, AttributeError, HTTPException) as exc:
        return {"jo_market_read:status": unreadable}, f"Market read status unreadable ({type(exc).__name__})", False


# Opt-in Jo watchdogs: state section, condition prefix, alerts.env flag, observer.
JO_WATCHES = (
    ("jo_morning", "jo_morning:", "JO_MORNING_ALERTS", lambda now: observe_morning(now)),
    ("jo_market_reads", "jo_market_read:", "JO_MARKET_READ_ALERTS", lambda now: observe_market_reads(now)),
)


def notice_day(key: str, today: str) -> str:
    parts = key.split(":")
    return parts[1] if len(parts) == 3 else today


def uncertain(exc: BaseException) -> bool:
    """A timeout once the request may have reached ntfy: delivery is unknown, not failed.

    urlopen wraps connect/send errors (nothing reached ntfy) in URLError, and raises a bare
    TimeoutError while waiting for the reply. The IPv4 path names the httpx timeout instead.
    """
    if isinstance(exc, HTTPError):
        return False
    if isinstance(exc, URLError):
        return any(name in str(exc.reason) for name in ("ReadTimeout", "WriteTimeout"))
    return isinstance(exc, TimeoutError)


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
        entry = entry or {"since": now, "alerted": False}
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
    if config.get("NTFY_IPV4_ONLY", "").strip().lower() == "true":
        try:
            with httpx.Client(transport=httpx.HTTPTransport(local_address="0.0.0.0"), timeout=15) as client:
                response = client.post(request.full_url, content=request.data, headers=headers)
        except httpx.HTTPError as exc:
            raise URLError(f"ntfy could not be reached ({type(exc).__name__})") from exc
        if not 200 <= response.status_code < 300:
            raise HTTPError(request.full_url, response.status_code, "ntfy refused the notification", {}, None)
        return
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
    observed = observe(state["watching_since"])
    today = datetime.fromtimestamp(now, ET).date().isoformat()
    watches, logs = {}, {}
    for section, prefix, flag, observer in JO_WATCHES:
        on = config.get(flag, "").strip().lower() == "true"
        record = dict(state.get(section) or {}, enabled=on)
        found, off = {}, False
        if on and observed.get("api", False) is None:
            found, error, off = observer(now)
            record.update(error=error, **({} if error else {"checked_at": datetime.fromtimestamp(now, timezone.utc).isoformat()}))
        # Yesterday's conditions end with their day, and switching a watchdog or the
        # automation it watches off ends them all: silently, neither "resolved" nor repeated.
        state["conditions"] = {key: value for key, value in state.get("conditions", {}).items()
            if not key.startswith(prefix) or (on and not off and notice_day(key, today) == today)}
        observed.update(found)
        watches[prefix] = (section, record)
        logs[prefix] = {day: entries for day, entries in (record.get("notices") or {}).items()
            if (date.fromisoformat(today) - date.fromisoformat(day)).days < MORNING_KEEP_DAYS}
    notices, following = evaluate(observed, state, now)
    delivered = True
    for notice in notices:
        prefix = next((p for p in watches if notice["keys"][0].startswith(p)), None)
        is_jo = prefix is not None
        try:
            publish(config, notice["title"], notice["message"], recovered=notice["recovered"])
            print(f"Sent: {notice['title']}")
            outcome = "sent"
        except OSError as exc:
            print(f"Could not send '{notice['title']}': {first_line(str(exc), 120)}")
            outcome = "unknown" if is_jo and uncertain(exc) else "failed"
            if outcome == "failed":
                delivered = False
                # Leave the condition as it was so the next pass tries again.
                for key in notice["keys"]:
                    if notice["recovered"]:
                        following["conditions"][key] = state["conditions"][key]
                    else:
                        following["conditions"][key]["alerted"] = False
            # An unknown Jo send may have reached the phone; it is recorded, never resent.
        if is_jo:
            key = notice["keys"][0]
            entries = logs[prefix].setdefault(notice_day(key, today), [])
            entry = {"kind": key.split(":")[-1], "title": notice["title"], "recovered": notice["recovered"],
                "outcome": outcome, "at": datetime.fromtimestamp(now, timezone.utc).isoformat(), "attempts": 1}
            last = entries[-1] if entries else None
            if last and last["outcome"] == "failed" and (last["kind"], last["recovered"]) == (entry["kind"], entry["recovered"]):
                # A retry replaces its failed attempt instead of adding a line per pass.
                entries[-1] = dict(entry, attempts=last.get("attempts", 1) + 1)
            else:
                entries.append(entry)
    for prefix, (section, record) in watches.items():
        following[section] = dict(record, notices=logs[prefix])
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
