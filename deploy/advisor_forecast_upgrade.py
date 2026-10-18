"""Guarded v1-to-v2 study upgrade and dormant MCP installation, never activation.

Only the reviewed disabled v1 is accepted. Old sources, units and receipts are
retained. No approval, OAuth binding, credential, proxy or schedule is created.
Dependencies come from an explicitly fingerprinted, existing offline wheelhouse.
"""
import argparse
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import stat
import subprocess
from urllib.parse import urlsplit

import advisor_forecast_prepare as prep

OLD = Path("/opt/tj-forecast/v1")
MCP_CONFIG = Path("/etc/tj-forecast-mcp")
KEYS = Path("/var/lib/tj-forecast-keys")
UNITS = Path("/etc/systemd/system")
KEY_USER = "tj-forecast-keys"
EXCHANGE_USER = "tj-forecast-exchange"
OLD_MANIFEST_SHA = "9a703484a46e0a82fcac113cda3b5136ff840bd5feb43f438f153fb503395a02"
OLD_UNITS = {
    "tj-forecast-history.timer": "ce23992157192d1a4f1bb02949c3e3e62d65958e9115fc00a25a4f850b0111fb",
    "tj-forecast-history.service": "9b7ed5bed9d67340531c3de6d6a8a59b025e2d57548cf1edfeee473121806732",
    "tj-forecast-snapshot.timer": "dbd168365ea47681054548e6e18abdc9449069ebb4d9fb7ba8075e5824c67c8f",
    "tj-forecast-snapshot.service": "c816a1fb26fcf3fccac889a2cd4f5181160b7fde68d254149ecfbac15592f751",
    "tj-forecast-outcomes.timer": "f02ecc2b0886018df68e4b45f916198195ca91370cf08dc84ae1d0f99d6c5d4b",
    "tj-forecast-outcomes.service": "f48c0134c76bcafcd5de776b8c53ff4bf5d49553ca53dcf3bae231f428f8b398",
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def owned(path, *, directory=False):
    """Refuse mutable/unexpected root-owned inputs, including symlink ancestors."""
    for parent in (path, *path.parents):
        info = parent.lstat()
        if stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError("root-owned immutable input required")
    if not (path.is_dir() if directory else path.is_file()):
        raise ValueError("unexpected input type")


def absent(path):
    if path.exists() or path.is_symlink():
        raise ValueError(f"destination already exists: {path}")


def inactive(name, *, disabled=False):
    result = subprocess.run(["systemctl", "is-active", name], capture_output=True, text=True)
    if result.stdout.strip() != "inactive":
        raise ValueError("study unit is not inactive")
    if disabled:
        result = subprocess.run(["systemctl", "is-enabled", name], capture_output=True, text=True)
        if result.stdout.strip() != "disabled":
            raise ValueError("study timer is not disabled")


def mcp_units():
    runtime = prep.RUNTIME
    common = """UMask=0027
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ProtectProc=invisible
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectKernelLogs=true
ProtectControlGroups=true
RestrictSUIDSGID=true
CapabilityBoundingSet=
SystemCallArchitectures=native
LockPersonality=true
MemoryDenyWriteExecute=true
TasksMax=32
MemoryMax=192M
CPUQuota=20%
Environment=PYTHONNOUSERSITE=1
Environment=PYTHONDONTWRITEBYTECODE=1
TimeoutStopSec=15
"""
    return {
        "tj-forecast-mcp.socket": f"""[Unit]
Description=Isolated forecast MCP socket; explicit activation required
ConditionPathExists={MCP_CONFIG}/config.json
[Socket]
ListenStream=/run/tj-forecast/mcp.sock
SocketUser={EXCHANGE_USER}
SocketGroup=caddy
SocketMode=0660
DirectoryMode=0755
RemoveOnStop=true
Accept=no
[Install]
WantedBy=sockets.target
""",
        "tj-forecast-mcp.service": f"""[Unit]
Description=Isolated forecast-only MCP; no network or application data
Requires=tj-forecast-mcp.socket
After=tj-forecast-mcp.socket
ConditionPathExists={MCP_CONFIG}/config.json
[Service]
Type=exec
User={EXCHANGE_USER}
Group={EXCHANGE_USER}
WorkingDirectory={runtime}
ExecStart={runtime}/.venv/bin/python -B {runtime}/backend/cloud_mcp_forecast.py --config {MCP_CONFIG}/config.json
PrivateNetwork=true
RestrictAddressFamilies=AF_UNIX
TemporaryFileSystem=/etc:ro /var:ro /opt:ro /run:ro
BindReadOnlyPaths={runtime} {MCP_CONFIG} {KEYS} {prep.STATE}/snapshots
BindPaths={prep.RECEIPTS}
ReadWritePaths={prep.RECEIPTS}
InaccessiblePaths=-/srv -/mnt -/media
{common}""",
        "tj-forecast-keys.service": f"""[Unit]
Description=Public OAuth key refresh only; no forecasts or data credentials
After=network-online.target
Wants=network-online.target
ConditionPathExists={MCP_CONFIG}/refresh.json
[Service]
Type=oneshot
User={KEY_USER}
Group={EXCHANGE_USER}
WorkingDirectory={runtime}
ExecStart={runtime}/.venv/bin/python -B {runtime}/backend/cloud_mcp_d0_refresh.py --config {MCP_CONFIG}/refresh.json
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
ReadWritePaths={KEYS}
InaccessiblePaths=-/opt/tradejournal -/etc/tradejournal -/var/lib/tradejournal -{prep.CONFIG} -{prep.STATE} -{prep.OUTCOMES} -{prep.BASELINES} -{prep.RECEIPTS}
TimeoutStartSec=30
{common}""",
        "tj-forecast-keys.timer": """[Unit]
Description=Disabled forecast public-key refresh
[Timer]
OnCalendar=*-*-* *:00/15:00 UTC
AccuracySec=1s
RandomizedDelaySec=0
Persistent=false
Unit=tj-forecast-keys.service
[Install]
WantedBy=timers.target
""",
    }


def proxy_stanza(resource_url, bind_address):
    """Render only this study's two public paths; installation is explicit."""
    parsed = urlsplit(resource_url)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.netloc != parsed.hostname
            or parsed.path != "/forecast/mcp" or parsed.query or parsed.fragment
            or not re.fullmatch(r"[a-z0-9.-]+", parsed.hostname)):
        raise ValueError("exact forecast HTTPS origin required")
    address = ipaddress.IPv4Address(bind_address)
    if not address.is_global:
        raise ValueError("explicit public IPv4 bind required")
    return f"""https://{parsed.hostname} {{
    bind {address}
    @forecast {{
        path /forecast/mcp /.well-known/oauth-protected-resource/forecast/mcp
        method GET HEAD POST DELETE OPTIONS
    }}
    handle @forecast {{
        request_body {{
            max_size 65536
        }}
        reverse_proxy unix//run/tj-forecast/mcp.sock {{
            flush_interval -1
            transport http {{
                dial_timeout 3s
                response_header_timeout 15s
            }}
        }}
    }}
    handle {{
        respond 404
    }}
}}
"""


def preflight(source, wheels, expected_wheel_hash):
    prep.host_guard()
    prep.check_source(source)
    owned(OLD, directory=True)
    manifest_path = OLD / "research/advisor-forecast/manifest.json"
    owned(manifest_path)
    if sha(manifest_path) != OLD_MANIFEST_SHA:
        raise ValueError("unrecognized old study manifest")
    manifest = json.loads(manifest_path.read_text())
    for name, expected in manifest["files"].items():
        path = OLD / name
        owned(path)
        if not path.is_relative_to(OLD) or ".." in path.parts or sha(path) != expected:
            raise ValueError("old study bundle changed")
    if set(p.name for p in UNITS.glob("tj-forecast-*")) != set(OLD_UNITS):
        raise ValueError("unexpected study units")
    for name, expected in OLD_UNITS.items():
        owned(UNITS / name)
        if sha(UNITS / name) != expected:
            raise ValueError("old study unit changed")
        inactive(name, disabled=name.endswith(".timer"))
    for name in ("approval.json", "registration.json", "evaluation-timing.json"):
        absent(prep.CONFIG / name)
    # A partial install is retained for inspection, never automatically adopted.
    for path in (prep.RUNTIME, prep.BASELINES, MCP_CONFIG, KEYS, OLD / "units-before-v2", prep.STATE / "snapshots"):
        absent(path)
    for path in (prep.CONFIG, prep.STATE, prep.RECEIPTS, prep.OUTCOMES):
        if path.is_symlink() or not path.is_dir():
            raise ValueError("study directory boundary changed")
    for path, owner, group, mode in (
        (prep.STATE, "tj-forecast-collector", EXCHANGE_USER, 0o750),
        (prep.RECEIPTS, EXCHANGE_USER, EXCHANGE_USER, 0o750),
        (prep.OUTCOMES, "tj-forecast-outcomes", "tj-forecast-outcomes", 0o700),
    ):
        info = path.stat()
        if (info.st_uid != pwd.getpwnam(owner).pw_uid or info.st_gid != pwd.getpwnam(group).pw_gid
                or stat.S_IMODE(info.st_mode) != mode):
            raise ValueError("study directory ownership changed")
    try:
        pwd.getpwnam(KEY_USER)
    except KeyError:
        pass
    else:
        raise ValueError("existing key publisher account")
    for name in ("tj-forecast-collector", EXCHANGE_USER, "tj-forecast-outcomes"):
        user = pwd.getpwnam(name)
        if user.pw_shell != "/usr/sbin/nologin" or user.pw_uid == 0:
            raise ValueError("study identity changed")
    owned(wheels, directory=True)
    if wheels.name != "wheels" or wheels.parent.parent != Path("/opt/tradejournal/releases"):
        raise ValueError("explicit existing release wheelhouse required")
    inventory = {}
    for path in wheels.iterdir():
        owned(path)
        if path.suffix != ".whl":
            raise ValueError("wheelhouse contains non-wheel input")
        inventory[path.name] = sha(path)
    digest = hashlib.sha256(json.dumps(inventory, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if not inventory or digest != expected_wheel_hash:
        raise ValueError("offline wheelhouse digest mismatch")
    return inventory


def install(source, wheels, expected_wheel_hash):
    inventory = preflight(source, wheels, expected_wheel_hash)
    prep.RUNTIME.mkdir(mode=0o755)
    for name in (*prep.FILES, "research/advisor-forecast/manifest.json"):
        target = prep.RUNTIME / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / name, target)
        target.chmod(0o644)
    prep.check_source(prep.RUNTIME)
    # A separate venv; never install the application wheel or inference SDKs.
    subprocess.run(["/usr/bin/python3.12", "-m", "venv", str(prep.RUNTIME / ".venv")], check=True)
    python = str(prep.RUNTIME / ".venv/bin/python")
    env = {"PATH": "/usr/bin:/bin", "PIP_CONFIG_FILE": "/dev/null", "PYTHONNOUSERSITE": "1"}
    subprocess.run([python, "-m", "pip", "--isolated", "install", "--no-index", "--no-cache-dir",
        "--disable-pip-version-check", "--only-binary=:all:", "--find-links", str(wheels),
        "mcp", "pyjwt[crypto]", "uvicorn"], env=env, check=True)
    packages = json.loads(subprocess.check_output([python, "-m", "pip", "list", "--format=json"], env=env, text=True))
    if {p["name"].lower() for p in packages} & {"anthropic", "openai", "trade-journal-backend", "sqlalchemy", "psycopg"}:
        raise ValueError("unexpected runtime dependency")
    (prep.RUNTIME / "dependency-receipt.json").write_text(json.dumps({"wheelhouse": inventory, "installed": packages}, indent=2) + "\n")
    subprocess.run(["useradd", "--system", "--no-create-home", "--shell", "/usr/sbin/nologin", KEY_USER], check=True)
    exchange = pwd.getpwnam(EXCHANGE_USER)
    for path, user, group in ((prep.BASELINES, "tj-forecast-collector", "tj-forecast-outcomes"),
                              (KEYS, KEY_USER, EXCHANGE_USER)):
        path.mkdir(mode=0o750)
        os.chown(path, pwd.getpwnam(user).pw_uid, pwd.getpwnam(group).pw_gid)
    MCP_CONFIG.mkdir(mode=0o755)
    # Empty read mount; collector creates immutable dated snapshot children.
    snapshots = prep.STATE / "snapshots"
    snapshots.mkdir(mode=0o750)
    os.chown(snapshots, pwd.getpwnam("tj-forecast-collector").pw_uid, exchange.pw_gid)
    backup = OLD / "units-before-v2"
    backup.mkdir(mode=0o700)
    for name in OLD_UNITS:
        shutil.copyfile(UNITS / name, backup / name)
    units = mcp_units()
    units.update({f"tj-forecast-{a}.{k}": f(a) for a in prep.ACTIONS
                  for k, f in (("service", prep.service), ("timer", prep.timer))})
    try:
        for name, content in units.items():
            path = UNITS / name
            path.write_text(content)
            path.chmod(0o644)
        subprocess.run(["systemd-analyze", "verify", *[str(UNITS / n) for n in units]], check=True)
        subprocess.run(["systemctl", "daemon-reload"], check=True)
        for name in units:
            inactive(name, disabled=name.endswith((".timer", ".socket")))
    except Exception:
        # No unit was started. Restore only the exact old study unit bytes.
        for name in units:
            if name in OLD_UNITS:
                shutil.copyfile(backup / name, UNITS / name)
            else:
                (UNITS / name).unlink(missing_ok=True)
        subprocess.run(["systemctl", "daemon-reload"], check=True)
        raise
    print(json.dumps({"installed": str(prep.RUNTIME), "units": "disabled/inactive",
        "old_runtime": "preserved", "activation": "not performed", "proxy": "unchanged",
        "credentials": "unchanged", "model_calls": 0}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--wheels", type=Path, required=True)
    parser.add_argument("--wheelhouse-sha256", required=True)
    args = parser.parse_args()
    install(args.source.resolve(), args.wheels, args.wheelhouse_sha256)
