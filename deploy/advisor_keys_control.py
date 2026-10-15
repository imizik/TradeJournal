"""Optional public-key upkeep for the installed side-by-side advisor trial.

`stage` copies only the reviewed key publisher files into a private bundle.
`install` (advisor stopped) adds a dedicated key UID, a public snapshot
directory, three key units and a UID-only network policy, mounts that directory
read-only into the two serving units and points the advisor config at it. For
the owner status it grants the owner-reader UID read-only access (named-UID
ACL) to the snapshot and advisor config directories and mounts both read-only
into the owner reader. Nothing is started or enabled. `check` reports freshness. `remove` reverses
the unit/config switch and preserves the key UID, directories and snapshots.
`extend-owner-status` brings an install made before the owner status (only the
two serving units bound) up to that layout without reinstalling.
"""
from __future__ import annotations

import argparse
import errno
import hashlib
import json
import os
from pathlib import Path
import pwd
import shutil
import stat
import struct
import sys
import tempfile
import time

sys.path.append(str(Path(__file__).resolve().parent.parent / "backend"))
from advisor_key_state import FRESH_MARGIN, MAX_SNAPSHOT, read_snapshot, snapshot_state  # noqa: E402,F401
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
OWNER_SERVICE = "tradejournal-advisor-owner.service"
# Units that read the snapshot: the two serving units plus the owner status reader.
SERVING = ("tradejournal-advisor-mcp.service", "tradejournal-advisor-backend.service", OWNER_SERVICE)
# Installs made before the owner status bound only these (see extend_owner_status).
OLD_SERVING = SERVING[:2]
BUNDLE_FILES = ("cloud_mcp_d0_refresh.py", *[f"units/{name}" for name in KEY_UNITS])
RECORD_NAME = "keys-installation.json"


def record_path():
    return RUNTIME / RECORD_NAME


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


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def unit_binds(name):
    """The owner reader also needs the advisor config for its enabled/issuer status."""
    return (advisor_config_path().parent, KEYS) if name == OWNER_SERVICE else (KEYS,)


def serving_unit(text, paths=None):
    """Add the public snapshot directory to the existing read-only binds only."""
    paths = (KEYS,) if paths is None else paths
    lines = text.splitlines(keepends=True)
    binds = [i for i, line in enumerate(lines) if line.startswith("BindReadOnlyPaths=")]
    if len(binds) != 1 or any(str(path) in text for path in paths):
        raise ValueError("Unexpected serving unit read-only bind layout")
    lines[binds[0]] = lines[binds[0]].rstrip("\n") + "".join(" " + str(path) for path in paths) + "\n"
    return "".join(lines)


def owner_read_acl(uid, *, default):
    """Linux POSIX ACL for a 0750 directory plus one named owner-reader UID.

    The access ACL lets that UID traverse (never list or write); the default
    ACL gives files created later, such as each atomically replaced snapshot
    or config, read for that UID. Owner, group and other keep their modes.
    """
    undefined = 0xFFFFFFFF
    user, named, group, mask = (6, 4, 4, 4) if default else (7, 1, 5, 5)
    entries = ((1, user, undefined), (2, named, uid), (4, group, undefined), (16, mask, undefined), (32, 0, undefined))
    return struct.pack("<I", 2) + b"".join(struct.pack("<HHI", *entry) for entry in entries)


def grant_owner_read(directory, uid):
    if stat.S_IMODE(directory.lstat().st_mode) != 0o750 or not directory.is_dir() or directory.is_symlink():
        raise ValueError("Owner read grant requires an exact 0750 directory: " + str(directory))
    os.setxattr(directory, "system.posix_acl_access", owner_read_acl(uid, default=False))
    os.setxattr(directory, "system.posix_acl_default", owner_read_acl(uid, default=True))


def revoke_owner_read(directory):
    """Drop the named-UID grant from a root-owned directory and its direct files."""
    targets = [(directory, ("system.posix_acl_default", "system.posix_acl_access"))]
    targets += [(path, ("system.posix_acl_access",)) for path in sorted(directory.iterdir())
        if path.is_file() and not path.is_symlink()]
    for path, names in targets:
        for name in names:
            try:
                os.removexattr(path, name, follow_symlinks=False)
            except OSError as error:
                if error.errno != errno.ENODATA:
                    raise


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
    reader_uid = config.get("owner_reader_uid")
    if not isinstance(reader_uid, int) or reader_uid < 1:
        raise ValueError("Owner status grant requires the trial's exact owner reader UID")
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
        grant_owner_read(KEYS, reader_uid)  # Kept with the directory on remove.
        write_file(snapshot, read_snapshot(config["jwks_file"])[0], mode=0o640, uid=key_uid, gid=reader_gid)
        for name in KEY_UNITS:
            write_file(old.UNIT_DIR / name, (bundle / "units" / name).read_bytes(), mode=0o644)
            switched[name] = None
        for name in SERVING:
            write_file(old.UNIT_DIR / name, serving_unit(serving_before[name].decode(), unit_binds(name)).encode(),
                mode=0o644, expected=record["units"][name])
            switched[name] = serving_before[name]
        switched["grant"] = None
        grant_owner_read(config_path.parent, reader_uid)
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
            if name == "grant":
                continue
            if name == "config":
                info = config_path.stat()
                write_file(config_path, data, mode=info.st_mode & 0o777, uid=info.st_uid, gid=info.st_gid,
                    expected=stage.digest(config_path))
            elif data is None:
                (old.UNIT_DIR / name).unlink(missing_ok=True)
            else:
                write_file(old.UNIT_DIR / name, data, mode=0o644, expected=stage.digest(old.UNIT_DIR / name))
        if "grant" in switched:
            revoke_owner_read(config_path.parent)  # After the config restore wrote into it.
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
    revoke_owner_read(advisor_config_path().parent)
    record_path().rename(RUNTIME / ("removed-" + str(int(time.time())) + "-" + RECORD_NAME))
    old.run("systemctl", "daemon-reload")
    trial.installed()


def interrupted_after_config_switch():
    keys_record = trial.private_json(record_path())
    previous = json.loads(stage.exact(RUNTIME / "previous/config.json").read_text())
    if json.loads(advisor_config_path().read_text())["jwks_file"] != previous["jwks_file"]:
        return False
    return all(stage.digest(old.UNIT_DIR / name) == digest for name, digest in keys_record["serving_units_before"].items())


def half_extended():
    """An interrupted extend-owner-status switched the owner unit but not the keys record."""
    saved = RUNTIME / "previous" / OWNER_SERVICE
    named = OWNER_SERVICE in trial.private_json(record_path())["serving_units_before"]
    return not named and saved.exists() and stage.digest(old.UNIT_DIR / OWNER_SERVICE) != stage.digest(stage.exact(saved))


def remove():
    old.root_only()
    if record_path().exists() and half_extended():
        raise ValueError("Owner unit is half-extended; re-run extend-owner-status before remove")
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
    for name in keys_record["serving_units_before"]:  # Two units for an old-layout install, else three.
        if name not in SERVING:
            raise ValueError("Unknown serving unit in key upkeep record")
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
    for name in saved_units:
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


def extend_owner_status():
    """Bring an old-layout key install (two serving units bound) up to `install`'s layout.

    With the advisor, owner bridge and owner frontend stopped, this adds the
    owner-reader grant and the two owner-unit binds exactly as `install` does,
    then records the owner unit in both records so `upgrade` sees the units it
    expects. Re-runnable after an interruption; restores on failure; starts nothing.
    """
    old.root_only()
    keys_record = trial.private_json(record_path())
    layout = set(keys_record.get("serving_units_before", ()))
    if layout == set(SERVING):
        installed()
        raise ValueError("Key upkeep already has the owner status layout")
    if layout != set(OLD_SERVING):
        raise ValueError("Unknown key upkeep serving-unit layout")
    trial.runtime_stopped()  # Same requirement as the trial's runtime upgrade.
    unit, saved = old.UNIT_DIR / OWNER_SERVICE, RUNTIME / "previous" / OWNER_SERVICE
    record = trial.private_json(trial.RECORD)
    if saved.exists() or saved.is_symlink():
        # An earlier attempt saved the original owner unit; if it was killed
        # between the unit switch and the record write, finish that record write.
        before = stage.exact(saved).read_bytes()
        after = serving_unit(before.decode(), unit_binds(OWNER_SERVICE)).encode()
        if stage.digest(stage.exact(unit)) == sha256(after) and record["units"][OWNER_SERVICE] == sha256(before):
            trial.write_atomic(trial.RECORD, {**record, "units": {**record["units"], OWNER_SERVICE: sha256(after)}})
    keys_record = installed()  # Full key upkeep and trial verification; refuses any other drift.
    record = trial.private_json(trial.RECORD)
    config_path = advisor_config_path()
    reader_uid = json.loads(config_path.read_text()).get("owner_reader_uid")
    if not isinstance(reader_uid, int) or reader_uid < 1:
        raise ValueError("Owner status grant requires the trial's exact owner reader UID")
    before = stage.exact(saved).read_bytes() if saved.exists() else unit.read_bytes()
    after = serving_unit(before.decode(), unit_binds(OWNER_SERVICE)).encode()
    if record["units"][OWNER_SERVICE] not in {sha256(before), sha256(after)}:
        raise ValueError("Owner unit does not match its preserved original")
    if not saved.exists():
        write_file(saved, before, mode=0o600)  # Root-private copy that `remove` restores.
    try:
        grant_owner_read(KEYS, reader_uid)  # Kept with the directory, as for install.
        grant_owner_read(config_path.parent, reader_uid)
        # Rewrite the config's own bytes so it carries the default ACL, as install's config switch does.
        info = config_path.stat()
        write_file(config_path, config_path.read_bytes(), mode=info.st_mode & 0o777, uid=info.st_uid,
            gid=info.st_gid, expected=stage.digest(config_path))
        if stage.digest(unit) == sha256(before):
            write_file(unit, after, mode=0o644, expected=sha256(before))
        trial.write_atomic(trial.RECORD, {**record, "units": {**record["units"], OWNER_SERVICE: sha256(after)}})
        old.run("systemctl", "daemon-reload")
        # Last: once the keys record names the owner unit, the extension is complete.
        trial.write_atomic(record_path(), {**keys_record, "serving_units_before": {
            **keys_record["serving_units_before"], OWNER_SERVICE: stage.digest(saved)}})
        return installed()  # No start, enable, restart or issuer contact.
    except BaseException:
        # Reverse order of the forward writes, so a crash here leaves a state re-running resumes.
        trial.write_atomic(record_path(), keys_record)
        trial.write_atomic(trial.RECORD, {**record, "units": {**record["units"], OWNER_SERVICE: sha256(before)}})
        if stage.digest(unit) == sha256(after):
            write_file(unit, before, mode=0o644, expected=sha256(after))
        revoke_owner_read(config_path.parent)
        old.run("systemctl", "daemon-reload", check=False)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("stage", "install", "check", "remove", "extend-owner-status"))
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
    elif args.action == "extend-owner-status":
        extend_owner_status()
        print(json.dumps({"extended": True, "started": False, "enabled": False}))
    else:
        remove()
        print(json.dumps({"removed": True}))


if __name__ == "__main__":
    sys.exit(main())
