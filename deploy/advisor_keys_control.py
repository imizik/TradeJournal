"""Optional public-key upkeep for the installed side-by-side advisor trial.

`stage` copies only the reviewed key publisher files into a private bundle.
`install` (advisor stopped) adds a dedicated key UID, a public snapshot
directory, three key units and a UID-only network policy, mounts that directory
read-only into the two serving units and points the advisor config at it.
Nothing is started or enabled. `check` reports freshness. `remove` reverses
the unit/config switch and preserves the key UID, directories and snapshots.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import pwd
import shutil
import stat
import sys
import tempfile
import time

import advisor_mcp_control as old
import advisor_mcp_stage as stage
import advisor_trial_control as trial
from journal_coach_network import key_policy

FORMAT = "advisor-keys-bundle-v1"
ACCOUNT = "tj-advisor-keys"
RUNTIME = Path("/opt/tradejournal-advisor-v2-keys")
SETTINGS = Path("/etc/tradejournal-advisor-v2-keys")
KEYS = Path("/var/lib/tradejournal-advisor-v2-keys")
SNAPSHOT_NAME = "public-keys.json"
KEY_UNITS = ("tradejournal-advisor-keys-network.service", "tradejournal-advisor-keys.service",
    "tradejournal-advisor-keys.timer")
SERVING = ("tradejournal-advisor-mcp.service", "tradejournal-advisor-backend.service")
BUNDLE_FILES = ("cloud_mcp_d0_refresh.py", *[f"units/{name}" for name in KEY_UNITS])
RECORD_NAME = "keys-installation.json"
FRESH_MARGIN = 15 * 60
MAX_SNAPSHOT = 64 * 1024


def record_path():
    return RUNTIME / RECORD_NAME


def read_snapshot(path, *, owner=None):
    """Read a public snapshot without following links or blocking on special files.

    The key UID owns the maintained directory, so root must not trust its leaf:
    require a small regular file (owned by the key UID when given) that parses.
    """
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or (owner is not None and info.st_uid != owner):
            raise ValueError("Public-key snapshot must be a regular file owned by its publisher")
        body = os.read(descriptor, MAX_SNAPSHOT + 1)
    finally:
        os.close(descriptor)
    if len(body) > MAX_SNAPSHOT:
        raise ValueError("Public-key snapshot is too large")
    snapshot = json.loads(body)
    if (not isinstance(snapshot, dict) or set(snapshot) != {"issuer_url", "jwks_url", "fetched_at", "expires_at", "keys"}
            or not isinstance(snapshot["keys"], list)):
        raise ValueError("Not a public-key snapshot")
    return body, snapshot


def bundle_sources():
    sources = {"cloud_mcp_d0_refresh.py": stage.SOURCE / "backend/cloud_mcp_d0_refresh.py"}
    sources.update({f"units/{name}": stage.TEMPLATES / name for name in KEY_UNITS})
    return sources


def stage_bundle(destination):
    destination = stage.exact(destination, exists=False)
    stage.exact(destination.parent)
    if destination.exists():
        raise ValueError("Refuse an existing staging destination")
    destination.mkdir(mode=0o700)
    try:
        for relative, source in bundle_sources().items():
            target = destination / relative
            target.parent.mkdir(mode=0o700, exist_ok=True)
            target.write_bytes(stage.exact(source).read_bytes())
            target.chmod(0o600)
        manifest = {"format": FORMAT, "source_commit": stage.reviewed_git("rev-parse", "HEAD").decode().strip(),
            "inventory": stage.inventory(destination)}
        (destination / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        (destination / "manifest.json").chmod(0o600)
        return validate(destination)
    except BaseException:
        shutil.rmtree(destination)  # Only this call's exclusive new staging path.
        raise


def validate(bundle):
    bundle = stage.exact(bundle)
    if not bundle.is_dir() or bundle.stat().st_mode & 0o777 != 0o700:
        raise ValueError("Require a private key bundle directory")
    manifest = json.loads(stage.exact(bundle / "manifest.json").read_text())
    if (set(manifest) != {"format", "source_commit", "inventory"} or manifest["format"] != FORMAT
            or manifest["inventory"] != stage.inventory(bundle)
            or {k for k, v in manifest["inventory"].items() if v["sha256"]} != set(BUNDLE_FILES)):
        raise ValueError("Key bundle inventory, modes or format changed")
    return manifest


def serving_unit(text):
    """Add the public snapshot directory to the existing read-only binds only."""
    lines = text.splitlines(keepends=True)
    binds = [i for i, line in enumerate(lines) if line.startswith("BindReadOnlyPaths=")]
    if len(binds) != 1 or str(KEYS) in text:
        raise ValueError("Unexpected serving unit read-only bind layout")
    lines[binds[0]] = lines[binds[0]].rstrip("\n") + " " + str(KEYS) + "\n"
    return "".join(lines)


def write_file(path, data, *, mode, uid=0, gid=0, expected=None):
    """Atomic same-directory replace; refuses collisions or unexpected bytes."""
    stage.exact(path.parent)
    if expected is None:
        if path.exists() or path.is_symlink():
            raise ValueError("Destination collision: " + str(path))
    elif stage.digest(stage.exact(path)) != expected:
        raise ValueError("Destination drift: " + str(path))
    fd, name = tempfile.mkstemp(prefix="." + path.name + ".", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.chown(temporary, uid, gid)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def advisor_config_path():
    return trial.CONFIG / "advisor/config.json"


def snapshot_state(config, *, now=None):
    """Public freshness facts only; never key material."""
    now = time.time() if now is None else now
    try:
        _, snapshot = read_snapshot(config["jwks_file"])
        expires = int(snapshot["expires_at"])
        matches = snapshot["issuer_url"] == config["issuer_url"] and snapshot["jwks_url"] == config["jwks_url"]
    except (OSError, ValueError, KeyError, TypeError):
        return {"state": "unreadable", "expires_at": None}
    if not matches:
        state = "issuer-mismatch"
    elif now >= expires:
        state = "expired"
    elif expires - now <= FRESH_MARGIN:
        state = "expiring"
    else:
        state = "fresh"
    return {"state": state, "expires_at": expires, "seconds_left": max(0, int(expires - now))}


def advisor_stopped():
    for unit in trial.UNITS:
        if old.run("systemctl", "is-active", "--quiet", unit, check=False).returncode == 0:
            raise ValueError("Stop all six advisor units before changing key upkeep")


def install(bundle, approved, *, dns_servers, host_ips):
    old.root_only()
    old.approval(stage.exact(bundle) / "manifest.json", approved)
    manifest = validate(bundle)
    for path in (bundle, *bundle.rglob("*"), *bundle.parents):
        info = path.stat()
        if info.st_uid != 0 or (info.st_mode & 0o022 and not info.st_mode & 0o1000):
            raise ValueError("Require root-owned immutable reviewed key bundle/ancestors")
    record = trial.installed()
    advisor_stopped()
    for path in (RUNTIME, SETTINGS, KEYS, *[old.UNIT_DIR / name for name in KEY_UNITS]):
        stage.exact(path.parent)
        if path.exists() or path.is_symlink():
            raise ValueError("Refuse key upkeep destination collision: " + str(path))
    if old.run("getent", "passwd", ACCOUNT, check=False).returncode == 0:
        raise ValueError("Refuse pre-existing key publisher identity")
    config_path = advisor_config_path()
    config_bytes = config_path.read_bytes()
    config = json.loads(config_bytes)
    current = snapshot_state(config)
    if current["state"] not in {"fresh", "expiring"}:
        raise ValueError("Seed requires a current matching public-key snapshot (" + current["state"] + ")")
    snapshot = KEYS / SNAPSHOT_NAME
    reader_gid = pwd.getpwnam(old.ACCOUNT).pw_gid
    serving_before = {name: (old.UNIT_DIR / name).read_bytes() for name in SERVING}
    switched = {}
    try:
        old.run("useradd", "--system", "--no-create-home", "--shell", "/usr/sbin/nologin", "--gid", old.ACCOUNT, ACCOUNT)
        key_uid = pwd.getpwnam(ACCOUNT).pw_uid
        policy = key_policy(key_uid, dns_servers, host_ips).encode()
        RUNTIME.mkdir(mode=0o755)
        write_file(RUNTIME / "cloud_mcp_d0_refresh.py", (bundle / "cloud_mcp_d0_refresh.py").read_bytes(), mode=0o644)
        (RUNTIME / "previous").mkdir(mode=0o700)
        for name, data in serving_before.items():
            write_file(RUNTIME / "previous" / name, data, mode=0o600)
        write_file(RUNTIME / "previous/config.json", config_bytes, mode=0o600)
        SETTINGS.mkdir(mode=0o755)
        refresh = {"issuer_url": config["issuer_url"], "jwks_url": config["jwks_url"], "jwks_file": str(snapshot)}
        write_file(SETTINGS / "refresh-keys.json", (json.dumps(refresh, indent=2) + "\n").encode(), mode=0o644)
        write_file(SETTINGS / "network.nft", policy, mode=0o644)
        KEYS.mkdir(mode=0o750)
        os.chown(KEYS, key_uid, reader_gid)
        write_file(snapshot, read_snapshot(config["jwks_file"])[0], mode=0o640, uid=key_uid, gid=reader_gid)
        for name in KEY_UNITS:
            write_file(old.UNIT_DIR / name, (bundle / "units" / name).read_bytes(), mode=0o644)
            switched[name] = None
        for name in SERVING:
            write_file(old.UNIT_DIR / name, serving_unit(serving_before[name].decode()).encode(), mode=0o644,
                expected=record["units"][name])
            switched[name] = serving_before[name]
        info = config_path.stat()
        write_file(config_path, (json.dumps({**config, "jwks_file": str(snapshot)}, indent=2) + "\n").encode(),
            mode=info.st_mode & 0o777, uid=info.st_uid, gid=info.st_gid, expected=stage.digest(config_path))
        switched["config"] = config_bytes
        units = {**record["units"], **{name: stage.digest(old.UNIT_DIR / name) for name in SERVING}}
        trial.write_private(trial.RECORD, {**record, "units": units})
        keys_record = {"format": "advisor-keys-installation-v1", "manifest_sha256": approved,
            "source_commit": manifest["source_commit"], "key_uid": key_uid, "reader_gid": reader_gid,
            "script_sha256": stage.digest(RUNTIME / "cloud_mcp_d0_refresh.py"),
            "settings": {name: stage.digest(SETTINGS / name) for name in ("refresh-keys.json", "network.nft")},
            "units": {name: stage.digest(old.UNIT_DIR / name) for name in KEY_UNITS},
            "serving_units_before": {name: stage.digest(RUNTIME / "previous" / name) for name in SERVING},
            "config_before_sha256": stage.digest(RUNTIME / "previous/config.json"), "snapshot": str(snapshot)}
        trial.write_private(record_path(), keys_record)
        old.run("systemctl", "daemon-reload")
        installed()
        return keys_record  # No start, enable, restart, grant or issuer contact.
    except BaseException:
        # Restore only what this attempt switched; keep the inert UID/directories
        # as a collision marker rather than deleting unknown partial state.
        for name, data in switched.items():
            if name == "config":
                info = config_path.stat()
                write_file(config_path, data, mode=info.st_mode & 0o777, uid=info.st_uid, gid=info.st_gid,
                    expected=stage.digest(config_path))
            elif data is None:
                (old.UNIT_DIR / name).unlink(missing_ok=True)
            else:
                write_file(old.UNIT_DIR / name, data, mode=0o644, expected=stage.digest(old.UNIT_DIR / name))
        if trial.RECORD.exists() and json.loads(trial.RECORD.read_text())["units"] != record["units"]:
            trial.write_private(trial.RECORD, record)
        if "config" in switched and record_path().exists():
            record_path().unlink()  # Written only by this attempt; nothing it describes remains.
        old.run("systemctl", "daemon-reload", check=False)
        raise


def installed():
    old.root_only()
    keys_record = trial.private_json(record_path())
    if keys_record.get("format") != "advisor-keys-installation-v1":
        raise ValueError("Unknown key upkeep installation")
    trial.installed()
    account = pwd.getpwnam(ACCOUNT)
    if (account.pw_uid != keys_record["key_uid"] or account.pw_gid != keys_record["reader_gid"]
            or account.pw_shell != "/usr/sbin/nologin"):
        raise ValueError("Key publisher identity changed")
    if stage.digest(stage.exact(RUNTIME / "cloud_mcp_d0_refresh.py")) != keys_record["script_sha256"]:
        raise ValueError("Key publisher script drift")
    for name, expected in keys_record["settings"].items():
        if stage.digest(stage.exact(SETTINGS / name)) != expected:
            raise ValueError("Key publisher settings drift")
    for name, expected in keys_record["units"].items():
        path = stage.exact(old.UNIT_DIR / name)
        if path.stat().st_uid != 0 or path.stat().st_mode & 0o022 or stage.digest(path) != expected:
            raise ValueError("Key unit drift")
    if json.loads(advisor_config_path().read_text())["jwks_file"] != keys_record["snapshot"]:
        raise ValueError("Advisor config no longer reads the maintained snapshot")
    return keys_record


def check():
    """Read-only operator health: state, expiry and timer activity, never keys."""
    old.root_only()
    config = json.loads(advisor_config_path().read_text())
    result = {"keys": snapshot_state(config), "jwks_file": config["jwks_file"]}
    if record_path().exists():
        installed()
        result["timer_active"] = old.run("systemctl", "is-active", "--quiet", KEY_UNITS[2], check=False).returncode == 0
    else:
        result["timer_active"] = None
    return result


def finish_removal():
    """Retire the leftover key units and record once everything else is restored."""
    for name in KEY_UNITS:
        (old.UNIT_DIR / name).unlink(missing_ok=True)
    record_path().rename(RUNTIME / ("removed-" + str(int(time.time())) + "-" + RECORD_NAME))
    old.run("systemctl", "daemon-reload")
    trial.installed()


def interrupted_after_config_switch():
    keys_record = trial.private_json(record_path())
    previous = json.loads(stage.exact(RUNTIME / "previous/config.json").read_text())
    if json.loads(advisor_config_path().read_text())["jwks_file"] != previous["jwks_file"]:
        return False
    return all(stage.digest(old.UNIT_DIR / name) == keys_record["serving_units_before"][name] for name in SERVING)


def remove():
    old.root_only()
    if record_path().exists() and interrupted_after_config_switch():
        advisor_stopped()
        trial.installed()  # Units and record already restored; only leftovers remain.
        return finish_removal()
    keys_record = installed()
    advisor_stopped()
    record = trial.private_json(trial.RECORD)
    config_path = advisor_config_path()
    # Verify every preserved input before the first write, so a refusal leaves
    # the installed state intact and retryable.
    saved_config = stage.exact(RUNTIME / "previous/config.json")
    if stage.digest(saved_config) != keys_record["config_before_sha256"]:
        raise ValueError("Preserved advisor config changed")
    saved_units = {}
    for name in SERVING:
        saved = stage.exact(RUNTIME / "previous" / name)
        if stage.digest(saved) != keys_record["serving_units_before"][name]:
            raise ValueError("Preserved serving unit changed")
        saved_units[name] = saved.read_bytes()
    previous = json.loads(saved_config.read_text())
    original = stage.exact(Path(previous["jwks_file"]))
    latest, _ = read_snapshot(keys_record["snapshot"], owner=keys_record["key_uid"])
    old.run("systemctl", "disable", "--now", KEY_UNITS[2], check=False)
    old.run("systemctl", "stop", KEY_UNITS[1], KEY_UNITS[0], check=False)
    for unit in KEY_UNITS:
        if old.run("systemctl", "is-active", "--quiet", unit, check=False).returncode == 0:
            raise RuntimeError("Key upkeep shutdown incomplete")
    # Carry the latest maintained public snapshot back to the original path, so
    # the advisor stays usable until it expires normally. Old bytes are kept.
    keep = RUNTIME / "previous/original-public-keys.json"
    if not keep.exists():
        write_file(keep, read_snapshot(original)[0], mode=0o600)
    info = original.stat()
    write_file(original, latest, mode=info.st_mode & 0o777, uid=info.st_uid, gid=info.st_gid,
        expected=stage.digest(original))
    units = dict(record["units"])
    for name in SERVING:
        write_file(old.UNIT_DIR / name, saved_units[name], mode=0o644, expected=record["units"][name])
        units[name] = stage.digest(old.UNIT_DIR / name)
        trial.write_private(trial.RECORD, {**record, "units": units})  # Keep the record matching each switch.
    # Config last: before it switches a failed remove retries as installed; after
    # it, remove() resumes at finish_removal().
    current = json.loads(config_path.read_text())
    info = config_path.stat()
    write_file(config_path, (json.dumps({**current, "jwks_file": previous["jwks_file"]}, indent=2) + "\n").encode(),
        mode=info.st_mode & 0o777, uid=info.st_uid, gid=info.st_gid, expected=stage.digest(config_path))
    finish_removal()  # Re-runnable if interrupted from here on.
    # The key UID, directories, snapshots and preserved files remain.


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("stage", "install", "check", "remove"))
    parser.add_argument("--bundle", type=Path)
    parser.add_argument("--approve-install")
    parser.add_argument("--dns", action="append", default=[], help="Resolver IP literal the key UID may query")
    parser.add_argument("--host-ip", action="append", default=[], help="This host's own IPs, denied to the key UID")
    args = parser.parse_args()
    if args.action == "stage":
        if not args.bundle:
            parser.error("stage requires a new --bundle destination")
        stage_bundle(args.bundle)
        print(json.dumps({"manifest_sha256": stage.digest(args.bundle / "manifest.json"), "started": False}))
    elif args.action == "install":
        if not args.bundle or not args.dns or not args.host_ip:
            parser.error("install requires --bundle, at least one --dns and this host's --host-ip")
        install(args.bundle, args.approve_install, dns_servers=args.dns, host_ips=args.host_ip)
        print(json.dumps({"installed": True, "started": False, "enabled": False}))
    elif args.action == "check":
        print(json.dumps(check()))
    else:
        remove()
        print(json.dumps({"removed": True}))


if __name__ == "__main__":
    sys.exit(main())
