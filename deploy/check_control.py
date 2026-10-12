"""Manual, disabled installer for the isolated pre-trade check service.

`stage` copies the reviewed check files, units and offline wheels into a
private bundle. `install` (root, exact manifest approval) creates three
dedicated UIDs, the runtime, private state/key/feature directories, the
UID-only network policy and unit files. Nothing is started, enabled or
granted; no provider or database credential is written (activation is a
separate approval). `check` reports state, `stop` stops every check unit and
`remove` retires the units while preserving the ledger, keys and features.
Never called by normal deployment. See docs/agent/advisor-pretrade-check-contract.md.
"""
from __future__ import annotations

import argparse
import grp
import json
from pathlib import Path
import platform
import pwd
import shutil
import sys
import time

import advisor_mcp_control as old
from advisor_mcp_stage import SOURCE, digest, exact, inventory, reviewed_git
from check_network import check_policy
from check_scope import view_sql

FORMAT = "check-disabled-bundle-v1"
ROOT = Path("/opt/tradejournal-check")
CONFIG = Path("/etc/tradejournal-check")
STATE = Path("/var/lib/tradejournal-check")
KEYS = Path("/var/lib/tradejournal-check-keys")
FEATURES = Path("/var/lib/tradejournal-check-features")
RUN = Path("/run/tradejournal-check")
RECORD = ROOT / "installation.json"
UNIT_DIR = old.UNIT_DIR
GROUP = "tj-check"
ACCOUNTS = {"service": "tj-check", "keys": "tj-check-keys", "features": "tj-check-features"}
TEMPLATES = SOURCE / "deploy/cloud-mcp-check"
UNITS = ("tradejournal-check.socket", "tradejournal-check.service", "tradejournal-check-network.service",
    "tradejournal-check-keys.service", "tradejournal-check-keys.timer",
    "tradejournal-check-features.service", "tradejournal-check-features.timer")
RUNTIME_FILES = ("cloud_mcp_check.py", "cloud_mcp_check_common.py", "cloud_mcp_check_ledger.py", "cloud_mcp_d0.py",
    "cloud_mcp_d0_refresh.py", "pretrade_features.py", "pretrade_feature_publish.py",
    "journal_coach_publication.py", "journal_coach_snapshot.py", "journal_coach_refresh.py")
SETTINGS = ("config.json", "refresh-keys.json", "network.nft", "feature-view.sql")
# Activation edits config.json and refresh-keys.json (real issuer, grant,
# client); the network policy and view SQL stay pinned.
PINNED_SETTINGS = ("network.nft", "feature-view.sql")


def stage(destination, *, wheels):
    destination = exact(destination, exists=False)
    exact(destination.parent)
    if destination.exists():
        raise ValueError("Refuse an existing staging destination")
    originals = {f"backend/{name}": SOURCE / "backend" / name for name in RUNTIME_FILES}
    # Only tracked engine/model sources; never dotenv, data, tests or caches.
    for relative in filter(None, reviewed_git("ls-files", "-z", "backend/app").decode().split("\0")):
        if relative.endswith(".py"):
            originals[relative] = SOURCE / relative
    originals.update({f"units/{name}": TEMPLATES / name for name in UNITS})
    originals["proxy/Caddyfile.example"] = TEMPLATES / "Caddyfile.example"
    wheels = exact(wheels)
    if not wheels.is_dir() or not list(wheels.glob("*.whl")):
        raise ValueError("Require verified offline wheel artifacts")
    originals.update({f"wheels/{p.name}": p for p in wheels.glob("*.whl")})
    for file in originals.values():
        if not exact(file).is_file():
            raise ValueError("Require regular source files")
    config = json.loads((TEMPLATES / "config.example.json").read_text())
    if config["enabled"] is not False or any(p["enabled"] is not False for p in config["profiles"]):
        raise ValueError("Staged check configuration must be disabled")
    destination.mkdir(mode=0o700)
    try:
        for relative, source in originals.items():
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())
        generated = {"config/config.json": json.dumps(config, indent=2) + "\n",
            "config/feature-view.sql": view_sql()}
        for relative, body in generated.items():
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(body)
        for path in destination.rglob("*"):
            path.chmod(0o600 if path.is_file() else 0o700)
        manifest = {"format": FORMAT, "enabled": False, "source_commit": reviewed_git("rev-parse", "HEAD").decode().strip(),
            "inventory": inventory(destination)}
        (destination / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        (destination / "manifest.json").chmod(0o600)
        return validate(destination)
    except BaseException:
        shutil.rmtree(destination)  # Only this call's exclusive new destination.
        raise


def validate(bundle):
    bundle = exact(bundle)
    if not bundle.is_dir() or bundle.stat().st_mode & 0o777 != 0o700:
        raise ValueError("Require a private check bundle directory")
    manifest = json.loads(exact(bundle / "manifest.json").read_text())
    if (set(manifest) != {"format", "enabled", "source_commit", "inventory"} or manifest["format"] != FORMAT
            or manifest["enabled"] is not False or manifest["inventory"] != inventory(bundle)):
        raise ValueError("Check bundle inventory, modes or disabled provenance changed")
    expected = {f"units/{name}" for name in UNITS} | {f"backend/{name}" for name in RUNTIME_FILES} | {
        "config/config.json", "config/feature-view.sql", "proxy/Caddyfile.example", "backend/app/engine/pretrade_check.py"}
    if not expected <= set(manifest["inventory"]):
        raise ValueError("Incomplete check bundle")
    config = json.loads((bundle / "config/config.json").read_text())
    if config.get("enabled") is not False or any(p.get("enabled") is not False for p in config["profiles"]):
        raise ValueError("Check bundle must remain disabled")
    return manifest


def preflight(bundle, approved, *, dns_servers, host_ips):
    old.root_only()
    check_policy(1001, 1002, 1003, dns_servers, host_ips)  # Validate addresses before any identity exists.
    old.approval(exact(bundle) / "manifest.json", approved)
    manifest = validate(bundle)
    for path in (bundle, *bundle.rglob("*"), *bundle.parents):
        info = path.stat()
        if info.st_uid != 0 or (info.st_mode & 0o022 and not info.st_mode & 0o1000):
            raise ValueError("Require root-owned immutable reviewed bundle/ancestors")
    distro = platform.freedesktop_os_release()
    if distro.get("ID") != "ubuntu" or distro.get("VERSION_ID") != "24.04" or platform.machine() != "x86_64":
        raise ValueError("Require artifact-matched Ubuntu 24.04 x86_64 host")
    for path in (ROOT, CONFIG, STATE, KEYS, FEATURES, RUN, *[UNIT_DIR / u for u in UNITS],
            *[UNIT_DIR / (u + ".d") for u in UNITS]):
        exact(path.parent)
        if path.exists() or path.is_symlink():
            raise ValueError("Refuse pre-existing check destination: " + str(path))
    for name in (GROUP, *ACCOUNTS.values()):
        for database in ("passwd", "group"):
            if old.run("getent", database, name, check=False).returncode == 0:
                raise ValueError("Refuse a pre-existing check identity: " + name)
    for unit in UNITS:
        if old.run("systemctl", "cat", unit, check=False).returncode == 0:
            raise ValueError("Refuse a loaded check unit from any search path")
    if old.run("getent", "group", "caddy", check=False).returncode != 0:
        raise ValueError("Dedicated reverse proxy socket group missing")
    if not list((bundle / "wheels").glob("*.whl")):
        raise ValueError("Offline verified runtime wheels required")
    return manifest


def private_file(path, data, *, mode, owner="root", group="root"):
    if path.exists() or path.is_symlink():
        raise ValueError("Destination collision: " + str(path))
    path.write_bytes(data)
    path.chmod(mode)
    old.run("chown", f"{owner}:{group}", path)


def install(bundle, approved, *, dns_servers, host_ips):
    bundle = exact(bundle)
    manifest = preflight(bundle, approved, dns_servers=dns_servers, host_ips=host_ips)
    owned_units = []
    try:
        old.run("groupadd", "--system", GROUP)
        for name in ACCOUNTS.values():
            old.run("useradd", "--system", "--no-create-home", "--shell", "/usr/sbin/nologin", "--gid", GROUP, name)
        uids = {role: pwd.getpwnam(name).pw_uid for role, name in ACCOUNTS.items()}
        policy = check_policy(uids["service"], uids["keys"], uids["features"], dns_servers, host_ips).encode()
        ROOT.mkdir(mode=0o755)
        shutil.copytree(bundle / "backend", ROOT / "backend")
        old.run("/usr/bin/python3.12", "-B", "-m", "venv", ROOT / "backend/.venv")
        old.run(ROOT / "backend/.venv/bin/python", "-B", "-m", "pip", "install", "--no-index", "--find-links",
            bundle / "wheels", "trade-journal-backend==0.1.0")
        # The shared Alpaca module creates this at import; supply it empty and
        # read-only. The service points its cache at its own CacheDirectory.
        (ROOT / "backend/data/alpaca_cache").mkdir(parents=True)
        old.normalize_new_runtime("backend", root=ROOT, record=RECORD)
        CONFIG.mkdir(mode=0o750)
        old.run("chown", f"root:{GROUP}", CONFIG)
        config = json.loads((bundle / "config/config.json").read_text())
        refresh = {"issuer_url": config["issuer_url"], "jwks_url": config["jwks_url"], "jwks_file": config["jwks_file"]}
        private_file(CONFIG / "config.json", (bundle / "config/config.json").read_bytes(), mode=0o640, group=GROUP)
        private_file(CONFIG / "refresh-keys.json", (json.dumps(refresh, indent=2) + "\n").encode(), mode=0o644)
        private_file(CONFIG / "network.nft", policy, mode=0o644)
        private_file(CONFIG / "feature-view.sql", (bundle / "config/feature-view.sql").read_bytes(), mode=0o644)
        for path, owner, mode in ((STATE, ACCOUNTS["service"], 0o700), (KEYS, ACCOUNTS["keys"], 0o750),
                (FEATURES, ACCOUNTS["features"], 0o750)):
            path.mkdir(mode=mode)
            old.run("chown", f"{owner}:{GROUP}", path)
            path.chmod(mode)
        for name in UNITS:
            private_file(UNIT_DIR / name, (bundle / "units" / name).read_bytes(), mode=0o644)
            owned_units.append(name)
        record = {"format": "check-installation-v1", "manifest_sha256": approved,
            "source_commit": manifest["source_commit"], "enabled": False, "uids": uids,
            "gid": grp.getgrnam(GROUP).gr_gid,
            "units": {u: digest(UNIT_DIR / u) for u in UNITS},
            "settings": {name: digest(CONFIG / name) for name in PINNED_SETTINGS},
            "runtime_inventory": old.runtime_inventory(root=ROOT, roles=("backend",), python_roles=("backend",))}
        RECORD.write_text(json.dumps(record, indent=2) + "\n")
        RECORD.chmod(0o600)
        old.run("systemctl", "daemon-reload")
        # No start, enable, nft load, proxy reload, credential, grant or issuer contact.
        return record
    except BaseException:
        # Only unit files this attempt created are removed; partial directories
        # and identities stay inert and force explicit recovery, never overwrite.
        for name in owned_units:
            (UNIT_DIR / name).unlink(missing_ok=True)
        if owned_units:
            old.run("systemctl", "daemon-reload", check=False)
        raise


def installed():
    old.root_only()
    exact(RECORD)
    if RECORD.stat().st_uid != 0 or RECORD.stat().st_mode & 0o077:
        raise ValueError("Require root-private check installation record")
    record = json.loads(RECORD.read_text())
    if record.get("format") != "check-installation-v1":
        raise ValueError("Unknown check installation")
    for role, name in ACCOUNTS.items():
        account = pwd.getpwnam(name)
        if (account.pw_uid != record["uids"][role] or account.pw_gid != record["gid"]
                or account.pw_shell != "/usr/sbin/nologin"):
            raise ValueError("Check identity changed: " + name)
    for name, expected in record["units"].items():
        path = exact(UNIT_DIR / name)
        if path.stat().st_uid != 0 or path.stat().st_mode & 0o022 or digest(path) != expected \
                or (UNIT_DIR / (name + ".d")).exists():
            raise ValueError("Check unit drift: " + name)
    for name, expected in record["settings"].items():
        if digest(exact(CONFIG / name)) != expected:
            raise ValueError("Check settings drift: " + name)
    if old.runtime_inventory(root=ROOT, roles=("backend",), python_roles=("backend",)) != record["runtime_inventory"]:
        raise ValueError("Check executable/dependency inventory drift")
    return record


def _age(path):
    try:
        return int(time.time() - exact(path).stat().st_mtime)
    except (OSError, ValueError):
        return None


def check():
    """Read-only operator health: drift, activity and freshness ages; never secrets."""
    record = installed()
    active = {u: old.run("systemctl", "is-active", "--quiet", u, check=False).returncode == 0 for u in UNITS}
    keys = {"age_seconds": _age(KEYS / "public-keys.json")}
    try:
        snapshot = json.loads(exact(KEYS / "public-keys.json").read_text())
        keys["expires_in_seconds"] = int(snapshot["expires_at"] - time.time())
    except (OSError, ValueError, KeyError, TypeError):
        keys["expires_in_seconds"] = None
    credentials = {name: (CONFIG / name).exists() for name in ("alpaca-key-id", "alpaca-secret-key", "features-database-url")}
    policy_loaded = old.run("nft", "list", "table", "inet", "tj_check", check=False).returncode == 0
    if active["tradejournal-check.service"] and not policy_loaded:
        raise RuntimeError("Check service is running without its UID network policy; stop it")
    return {"installed": True, "enabled": record["enabled"], "active": active, "network_policy_loaded": policy_loaded, "keys": keys,
        "features_age_seconds": _age(FEATURES / "current.json"), "credentials_present": credentials,
        "ledger_present": (STATE / "ledger.db").exists()}


def stop():
    old.root_only()
    json.loads(exact(RECORD).read_text())  # Fixed names stay stoppable after drift.
    timers = [u for u in UNITS if u.endswith(".timer")]
    results = [old.run("systemctl", "stop", *group, check=False) for group in (
        timers, ["tradejournal-check.socket"], [u for u in UNITS if u.endswith(".service")])]
    if any(old.run("systemctl", "is-active", "--quiet", u, check=False).returncode == 0 for u in UNITS) \
            or (RUN / "mcp.sock").exists() or any(r.returncode for r in results):
        raise RuntimeError("Check shutdown incomplete; all groups were attempted")


def remove():
    """Retire units after a full stop. Ledger, keys, features, config and UIDs remain."""
    record = installed()
    old.run("systemctl", "disable", *[u for u in UNITS if u.endswith(".timer")], check=False)
    stop()
    for name in UNITS:
        (UNIT_DIR / name).unlink()
    RECORD.rename(ROOT / ("removed-" + str(int(time.time())) + "-installation.json"))
    old.run("systemctl", "daemon-reload")
    return {"removed_units": sorted(record["units"]), "preserved": [str(STATE), str(KEYS), str(FEATURES), str(CONFIG)]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("stage", "install", "check", "stop", "remove"))
    parser.add_argument("--bundle", type=Path)
    parser.add_argument("--wheels", type=Path, help="Already verified release wheels; no downloading")
    parser.add_argument("--approve-install")
    parser.add_argument("--dns", action="append", default=[], help="Resolver IP literal the check UIDs may query")
    parser.add_argument("--host-ip", action="append", default=[], help="This host's own IPs, denied to the check UIDs")
    args = parser.parse_args()
    if args.action == "stage":
        if not args.bundle or not args.wheels:
            parser.error("stage requires a new --bundle destination and --wheels")
        stage(args.bundle, wheels=args.wheels)
        print(json.dumps({"manifest_sha256": digest(args.bundle / "manifest.json"), "enabled": False, "started": False}))
    elif args.action == "install":
        if not args.bundle or not args.dns or not args.host_ip:
            parser.error("install requires --bundle, at least one --dns and this host's --host-ip")
        install(args.bundle, args.approve_install, dns_servers=args.dns, host_ips=args.host_ip)
        print(json.dumps({"installed": True, "started": False, "enabled": False}))
    elif args.action == "check":
        print(json.dumps(check()))
    elif args.action == "stop":
        stop()
        print(json.dumps({"stopped": True}))
    else:
        print(json.dumps(remove()))


if __name__ == "__main__":
    sys.exit(main())
