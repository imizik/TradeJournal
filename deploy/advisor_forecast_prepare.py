"""Additive, disabled non-model installation; no approval, credentials or Jo task."""
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import pwd
import shutil
import socket
import subprocess
from zoneinfo import ZoneInfo

RUNTIME = Path("/opt/tj-forecast/v1")
CONFIG = Path("/etc/tj-forecast")
STATE = Path("/var/lib/tj-forecast")
OUTCOMES = Path("/var/lib/tj-forecast-outcomes")
RECEIPTS = Path("/var/lib/tj-forecast-receipts")
FILES = ("scripts/advisor_forecast.py", "scripts/advisor_forecast_runtime.py", "scripts/advisor_forecast_exchange.py",
         "research/advisor-forecast/spec.json", "research/advisor-forecast/prompt.txt", "deploy/advisor_forecast_prepare.py",
         "backend/cloud_mcp_forecast.py", "backend/cloud_mcp_d0.py", "backend/cloud_mcp_advisor_common.py")
ACTIONS = ("history", "snapshot", "outcomes")


def service(action):
    outcome = action == "outcomes"
    user = "tj-forecast-outcomes" if outcome else "tj-forecast-collector"
    state = OUTCOMES if outcome else STATE
    supplementary = "" if outcome else "SupplementaryGroups=tj-forecast-exchange\n"
    hidden = STATE if outcome else OUTCOMES
    return f"""[Unit]
Description=Non-model advisor study {action}; owner activation required
After=network-online.target
Wants=network-online.target
ConditionPathExists={CONFIG}/approval.json

[Service]
Type=oneshot
User={user}
Group={user}
{supplementary}WorkingDirectory={RUNTIME}
Environment=PYTHONNOUSERSITE=1
Environment=PYTHONDONTWRITEBYTECODE=1
EnvironmentFile=-{CONFIG}/data.env
ExecStart=/usr/bin/python3 {RUNTIME}/scripts/advisor_forecast_runtime.py {action}
UMask=0027
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectKernelLogs=true
ProtectControlGroups=true
RestrictSUIDSGID=true
LockPersonality=true
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
CapabilityBoundingSet=
ReadWritePaths={state}
InaccessiblePaths=-/opt/tradejournal -/etc/tradejournal -/var/lib/tradejournal -{hidden}
CPUQuota=20%
MemoryMax=128M
TasksMax=16
TimeoutStartSec={350 if action == 'history' else 60}
Restart=no
"""


def timer(action):
    times = {"history": ["09:45:00"], "snapshot": ["10:00:00", "10:05:00"], "outcomes": ["11:05:00"]}[action]
    schedule = "\n".join(f"OnCalendar=Mon..Fri *-*-* {t} America/New_York" for t in times)
    return f"""[Unit]
Description=Disabled non-model advisor study {action}

[Timer]
{schedule}
AccuracySec=1s
RandomizedDelaySec=0
Persistent=false
Unit=tj-forecast-{action}.service

[Install]
WantedBy=timers.target
"""


def check_source(source):
    manifest = json.loads((source / "research/advisor-forecast/manifest.json").read_text())
    if set(manifest["files"]) != set(FILES):
        raise ValueError("unexpected bundle files")
    for name in FILES:
        path = source / name
        if not path.resolve().is_relative_to(source.resolve()) or path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != manifest["files"][name]:
            raise ValueError("bundle digest mismatch")
    return manifest


def install(source):
    current = datetime.now(ZoneInfo("America/New_York"))
    if os.geteuid() != 0 or socket.gethostname() != "vps-c6302cfc":
        raise ValueError("explicit host/root required")
    if current.weekday() < 5 and 9 <= current.hour < 17:
        raise ValueError("market-hours hold; no override")
    if shutil.disk_usage("/var/lib").free < 1024**3:
        raise ValueError("one GiB free-space reserve required")
    mem = {line.split(':')[0]: int(line.split()[1]) for line in Path('/proc/meminfo').read_text().splitlines()}
    if mem["MemAvailable"] < 512 * 1024:
        raise ValueError("512 MiB memory reserve required")
    if subprocess.check_output(["timedatectl", "show", "-p", "NTPSynchronized", "--value"], text=True).strip() != "yes":
        raise ValueError("synchronized clock required")
    check_source(source)
    if any(p.exists() or p.is_symlink() for p in (RUNTIME.parent, CONFIG, STATE, OUTCOMES, RECEIPTS)):
        raise ValueError("existing study paths; refuse overwrite")
    unit_dir = Path("/etc/systemd/system")
    for action in ACTIONS:
        for kind in ("service", "timer"):
            if (unit_dir / f"tj-forecast-{action}.{kind}").exists():
                raise ValueError("existing unit; refuse overwrite")
    users = ("tj-forecast-collector", "tj-forecast-exchange", "tj-forecast-outcomes")
    for user in users:
        try:
            pwd.getpwnam(user)
        except KeyError:
            pass
        else:
            raise ValueError("existing account; refuse adoption")
    # No production DB/services or release changes; source remains recoverable.
    for user in users:
        subprocess.run(["useradd", "--system", "--no-create-home", "--shell", "/usr/sbin/nologin", user], check=True)
    RUNTIME.mkdir(parents=True, mode=0o755)
    for name in (*FILES, "research/advisor-forecast/manifest.json"):
        target = RUNTIME / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / name, target)
        target.chmod(0o644)
    check_source(RUNTIME)
    CONFIG.mkdir(mode=0o755)
    fd = os.open(CONFIG / "data.env", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as handle:
        handle.write("# Existing authorized market-data credentials only; provision after review.\nALPACA_API_KEY=\nALPACA_API_SECRET=\n")
    for path, user, mode in ((STATE, users[0], 0o750), (RECEIPTS, users[1], 0o750), (OUTCOMES, users[2], 0o700)):
        path.mkdir(mode=mode)
        identity = pwd.getpwnam(user)
        os.chown(path, identity.pw_uid, identity.pw_gid)
    for action in ACTIONS:
        for kind, content in (("service", service(action)), ("timer", timer(action))):
            path = unit_dir / f"tj-forecast-{action}.{kind}"
            path.write_text(content)
            path.chmod(0o644)
    subprocess.run(["systemd-analyze", "verify", *[str(unit_dir / f"tj-forecast-{a}.{k}") for a in ACTIONS for k in ("service", "timer")]], check=True)
    subprocess.run(["systemctl", "daemon-reload"], check=True)
    for action in ACTIONS:
        enabled = subprocess.run(["systemctl", "is-enabled", f"tj-forecast-{action}.timer"], text=True, capture_output=True)
        active = subprocess.run(["systemctl", "is-active", f"tj-forecast-{action}.timer"], text=True, capture_output=True)
        if enabled.stdout.strip() != "disabled" or active.stdout.strip() != "inactive":
            raise ValueError("timer unexpectedly enabled/active")
    print(json.dumps({"installed": str(RUNTIME), "timers": "disabled/inactive", "approval": "absent", "market_credentials": "empty placeholders", "model_runtime": "none", "mcp_listener": "not installed", "production_services_modified": False}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    args = parser.parse_args()
    install(args.source)
