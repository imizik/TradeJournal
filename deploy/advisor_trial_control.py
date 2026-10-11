"""Explicit, disabled side-by-side advisor trial upgrade. Never auto-deployed.

Only installation, six-unit shutdown and receipt-preserving rollback are
supported. No activation, assignment, keys, OAuth, proxy or frontend restart.
"""
from __future__ import annotations

import argparse
import grp
import json
import os
from pathlib import Path
import platform
import pwd
import shutil
import tempfile

import advisor_mcp_control as old
import advisor_mcp_stage as stage
import advisor_trial_stage as trial

ROOT = Path(trial.ROOT)
CONFIG = Path(trial.CONFIG)
STATE = Path(trial.STATE)
RECORD = ROOT / "installation.json"
UNITS = (*stage.UNITS, *trial.OWNER_UNITS)
DROPIN = old.UNIT_DIR / (trial.FRONTEND + ".d") / "advisor-trial.conf"
OWNER_ENV = Path("/etc/tradejournal-dot-trial/access-owner.env")
API_ENV = Path("/etc/tradejournal-dot-trial/access-backend.env")
ROLES = ("adapter", "backend", "frontend", "bin", "operator")
# Optional key upkeep (advisor_keys_control.py) must be removed before rollback.
KEYS_RECORD = Path("/opt/tradejournal-advisor-v2-keys/keys-installation.json")


def private_json(path):
    stage.exact(path)
    info = path.stat()
    if info.st_uid != 0 or info.st_mode & 0o077:
        raise ValueError("Require root-private operator record")
    return json.loads(path.read_text())


def runtime():
    return old.runtime_inventory(root=ROOT, roles=ROLES)


def effective_units(*, installed=False):
    """Ask systemd about effective authority, not only /etc leaf files."""
    for unit in (*UNITS, trial.FRONTEND):
        result = old.run("systemctl", "show", unit, "--property=FragmentPath", "--property=DropInPaths",
            "--property=LoadState", check=False)
        values = dict(line.split("=", 1) for line in result.stdout.decode().splitlines() if "=" in line)
        present = installed or unit not in trial.OWNER_UNITS
        fragment = str(old.UNIT_DIR / unit) if present else ""
        dropins = str(DROPIN) if installed and unit == trial.FRONTEND else ""
        if (set(values) != {"FragmentPath", "DropInPaths", "LoadState"}
                or values["FragmentPath"] != fragment or values["DropInPaths"] != dropins
                or values["LoadState"] != ("loaded" if present else "not-found")
                or (present and result.returncode != 0)):
            raise ValueError("Unreviewed effective systemd fragment/override: " + unit)


def atomic_file(source, target, *, expected, committed=None, source_sha256=None):
    """Validate a same-directory private temporary before atomic publication.

    Track commit intent before replace: a replace wrapper can publish and then
    raise. Cleanup may restore only the exact new bytes this attempt approved.
    """
    stage.exact(target.parent)
    fd, name = tempfile.mkstemp(prefix="." + target.name + ".", dir=target.parent)
    os.close(fd)
    temporary = Path(name)
    try:
        shutil.copyfile(source, temporary)
        temporary.chmod(0o644)
        info = temporary.stat()
        approved = stage.digest(source) if source_sha256 is None else source_sha256
        if info.st_uid != 0 or info.st_mode & 0o7777 != 0o644 or stage.digest(temporary) != approved:
            raise ValueError("Atomic unit temporary differs from reviewed source")
        if expected is None:
            if target.exists() or target.is_symlink():
                raise ValueError("Atomic destination collision")
        elif stage.digest(stage.exact(target)) != expected:
            raise ValueError("Atomic destination drift")
        if committed is not None:
            committed[target] = approved
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)  # Only this exclusive temporary.


def guards_current(guards):
    expected = {"old_record_sha256", "frontend_unit_sha256", "owner_env_sha256", "api_env_sha256"}
    if set(guards) != expected:
        raise ValueError("Require exact old-installation / private-owner guards")
    old.installed()  # Independently verify the old immutable runtime and units.
    files = {"old_record_sha256": old.RECORD, "frontend_unit_sha256": old.UNIT_DIR / trial.FRONTEND,
        "owner_env_sha256": OWNER_ENV, "api_env_sha256": API_ENV}
    for key, path in files.items():
        stage.exact(path)
        if path.stat().st_uid != 0 or path.stat().st_mode & 0o022 or stage.digest(path) != guards[key]:
            raise ValueError("Reviewed existing resource changed: " + key)
    # Do not trust loaded vendor/drop-in overrides absent from the approval.
    frontend_dropins = old.UNIT_DIR / (trial.FRONTEND + ".d")
    if frontend_dropins.exists() or frontend_dropins.is_symlink():
        raise ValueError("Refuse pre-existing private owner frontend drop-ins")
    effective_units()
    for unit in stage.UNITS:
        if old.run("systemctl", "is-active", "--quiet", unit, check=False).returncode == 0:
            raise ValueError("Old advisor must be stopped before replacement")


def preflight(bundle, approved):
    old.root_only()
    old.approval(bundle / "manifest.json", approved)
    manifest = stage.validate(bundle)
    for path in (bundle, *bundle.rglob("*"), *bundle.parents):
        info = path.stat()
        if info.st_uid != 0 or (info.st_mode & 0o022 and not info.st_mode & 0o1000):
            raise ValueError("Require root-owned immutable reviewed bundle/ancestors")
    plan = json.loads((bundle / "trial.json").read_text())
    if set(plan) != {"format", "guards", "artifact_sha256", "release"} or plan["format"] != "advisor-trial-disabled-v1":
        raise ValueError("Unknown side-by-side trial plan")
    distro = platform.freedesktop_os_release()
    if distro.get("ID") != "ubuntu" or distro.get("VERSION_ID") != "24.04" or platform.machine() != "x86_64":
        raise ValueError("Require artifact-matched Ubuntu 24.04 x86_64 host")
    guards_current(plan["guards"])
    for path in (ROOT, CONFIG, STATE, Path(trial.RUN), Path(trial.OWNER_RUN),
            *[old.UNIT_DIR / name for name in trial.OWNER_UNITS],
            *[old.UNIT_DIR / (name + ".d") for name in trial.OWNER_UNITS]):
        stage.exact(path.parent)
        if path.exists() or path.is_symlink():
            raise ValueError("Refuse side-by-side destination collision: " + str(path))
    for name in (trial.READER_ACCOUNT, trial.WEB_ACCOUNT):
        for database in ("passwd", "group"):
            if old.run("getent", database, name, check=False).returncode == 0:
                raise ValueError("Refuse pre-existing new identity")
    for name in trial.OWNER_UNITS:
        if old.run("systemctl", "cat", name, check=False).returncode == 0:
            raise ValueError("Refuse owner unit from any search path")
    for relative in ("backend/cloud_advisor_owner.py", "frontend/server.js", "bin/node", "units/frontend.conf",
            "config/owner.json", "config/frontend.env", *["units/" + name for name in UNITS]):
        stage.exact(bundle / relative)
    if json.loads((bundle / "config/owner.json").read_text())["enabled"] is not False or "TJ_ADVISOR_OWNER_ENABLED=false\n" not in (bundle / "config/frontend.env").read_text():
        raise ValueError("Owner reader/frontend must remain disabled")
    if not list((bundle / "wheels").glob("*.whl")):
        raise ValueError("Verified offline wheels required")
    return manifest, plan


def write_private(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")
    path.chmod(0o600)


def stop():
    old.root_only()
    private_json(RECORD)  # Fixed names remain stoppable after code/unit drift.
    results = [old.run("systemctl", "stop", *[u for u in UNITS if u.endswith(suffix)], check=False)
        for suffix in (".socket", ".service")]
    active = any(old.run("systemctl", "is-active", "--quiet", u, check=False).returncode == 0 for u in UNITS)
    sockets = [Path(trial.RUN) / "mcp.sock", Path(trial.RUN) / "backend.sock", Path(trial.OWNER_RUN) / "owner.sock"]
    if active or any(p.exists() for p in sockets) or any(r.returncode for r in results):
        raise RuntimeError("Six-unit shutdown incomplete; both groups attempted")


def installed():
    old.root_only()
    record = private_json(RECORD)
    if record.get("format") != "advisor-trial-installation-v1" or set(record["units"]) != set(UNITS):
        raise ValueError("Unknown trial installation")
    effective_units(installed=True)
    for name, expected in record["units"].items():
        path = stage.exact(old.UNIT_DIR / name)
        if path.stat().st_uid != 0 or path.stat().st_mode & 0o022 or stage.digest(path) != expected or (old.UNIT_DIR / (name + ".d")).exists():
            raise ValueError("Trial unit drift")
    stage.exact(DROPIN)
    if stage.digest(DROPIN) != record["dropin_sha256"] or set(DROPIN.parent.iterdir()) != {DROPIN}:
        raise ValueError("Private owner override drift")
    for path, expected in record["preserved"].items():
        if stage.digest(stage.exact(Path(path))) != expected:
            raise ValueError("Preserved old installation/auth resource drift")
    previous = private_json(old.RECORD)
    if old.runtime_inventory() != previous["runtime_inventory"]:
        raise ValueError("Preserved old executable/dependency inventory drift")
    if runtime() != record["runtime_inventory"]:
        raise ValueError("Trial executable/dependency inventory drift")
    for name, identity in record["new_accounts"].items():
        account = pwd.getpwnam(name)
        group = grp.getgrnam(name)
        if (account.pw_uid != identity["uid"] or account.pw_gid != identity["gid"]
                or group.gr_gid != identity["gid"] or group.gr_mem or account.pw_shell != "/usr/sbin/nologin"
                or [g.gr_name for g in grp.getgrall() if name in g.gr_mem]
                or [p.pw_name for p in pwd.getpwall() if p.pw_gid == identity["gid"] and p.pw_name != name]):
            raise ValueError("Dedicated trial account changed")
    uids = [identity["uid"] for identity in record["new_accounts"].values()]
    if len(set(uids)) != 2 or set(uids) & {pwd.getpwnam(n).pw_uid for n in (old.ACCOUNT, old.BACKEND_ACCOUNT)}:
        raise ValueError("Owner/frontend/writer identity collision")
    return record


def install(bundle, approved):
    bundle = stage.exact(bundle)
    manifest, plan = preflight(bundle, approved)
    old_record = old.installed()
    backups = {name: (old.UNIT_DIR / name).read_bytes() for name in stage.UNITS}
    preserved = {str(path): stage.digest(path) for path in (old.RECORD, old.STATE / "fixture.db",
        old.ROOT / "recovery/request.json", OWNER_ENV, API_ENV, old.UNIT_DIR / trial.FRONTEND)}
    changed = {}
    dropin_directory_created = False
    try:
        ROOT.mkdir(mode=0o755)
        (ROOT / "previous-units").mkdir(mode=0o700)
        for name, data in backups.items():
            (ROOT / "previous-units" / name).write_bytes(data)
            (ROOT / "previous-units" / name).chmod(0o600)
        # An incomplete attempt remains inert and collision-blocked. Preserve
        # all new/old data rather than deleting an unknown partial receipt.
        for account in (trial.READER_ACCOUNT, trial.WEB_ACCOUNT):
            old.run("useradd", "--system", "--user-group", "--no-create-home", "--shell", "/usr/sbin/nologin", account)
        new_accounts = {name: {"uid": pwd.getpwnam(name).pw_uid, "gid": pwd.getpwnam(name).pw_gid}
            for name in (trial.READER_ACCOUNT, trial.WEB_ACCOUNT)}
        for role in ROLES:
            shutil.copytree(bundle / role, ROOT / role)
            if role in ("adapter", "backend"):
                old.run("/usr/bin/python3.12", "-B", "-m", "venv", ROOT / role / ".venv")
                packages = ["mcp==1.28.1", "PyJWT[crypto]==2.13.0"] if role == "adapter" else ["trade-journal-backend==0.1.0"]
                old.run(ROOT / role / ".venv/bin/python", "-B", "-m", "pip", "install", "--no-index", "--find-links", bundle / "wheels", *packages)
            if role == "backend":
                (ROOT / role / "data/alpaca_cache").mkdir(parents=True, mode=0o755)
            if role == "bin":
                (ROOT / "bin/node").chmod(0o755)
            if role != "operator":
                old.normalize_new_runtime(role, root=ROOT, record=RECORD)
            else:
                (ROOT / role).chmod(0o700)
        CONFIG.mkdir(mode=0o755)
        for role, account in (("advisor", old.ACCOUNT), ("owner", trial.READER_ACCOUNT)):
            directory = CONFIG / role
            directory.mkdir(mode=0o750)
            old.run("chown", "root:" + account, directory)
        advisor = json.loads((bundle / "config/config.json").read_text())
        advisor["owner_reader_uid"] = new_accounts[trial.READER_ACCOUNT]["uid"]
        owner = json.loads((bundle / "config/owner.json").read_text())
        owner.update(reader_uid=new_accounts[trial.READER_ACCOUNT]["uid"], peer_uid=new_accounts[trial.WEB_ACCOUNT]["uid"])
        for path, content in ((CONFIG / "advisor/config.json", advisor), (CONFIG / "owner/config.json", owner)):
            write_private(path, content)
        shutil.copyfile(bundle / "config/public-keys.json", CONFIG / "advisor/public-keys.json")
        for role, account in (("advisor", old.ACCOUNT), ("owner", trial.READER_ACCOUNT)):
            for path in (CONFIG / role).iterdir():
                path.chmod(0o640)
                old.run("chown", "root:" + account, path)
        shutil.copyfile(bundle / "config/frontend.env", CONFIG / "frontend.env")
        (CONFIG / "frontend.env").chmod(0o600)  # systemd reads public fields as root.
        STATE.mkdir(mode=0o700)
        shutil.copyfile(bundle / "state/fixture.db", STATE / "fixture.db")
        (STATE / "fixture.db").chmod(0o600)
        old.run("chown", f"{old.BACKEND_ACCOUNT}:{old.ACCOUNT}", STATE, STATE / "fixture.db")
        shutil.copytree(bundle / "recovery", ROOT / "recovery")
        for path in (ROOT / "recovery").rglob("*"):
            path.chmod(0o600 if path.is_file() else 0o700)
        (ROOT / "recovery").chmod(0o700)
        # Recheck after slow offline installation, before switching any unit.
        guards_current(plan["guards"])
        for name in UNITS:
            atomic_file(bundle / "units" / name, old.UNIT_DIR / name,
                expected=old_record["units"].get(name), committed=changed,
                source_sha256=manifest["inventory"]["units/" + name]["sha256"])
        DROPIN.parent.mkdir(mode=0o755)
        dropin_directory_created = True
        atomic_file(bundle / "units/frontend.conf", DROPIN, expected=None, committed=changed,
            source_sha256=manifest["inventory"]["units/frontend.conf"]["sha256"])
        record = {"format": "advisor-trial-installation-v1", "manifest_sha256": approved,
            "source_commit": manifest["source_commit"], "release": plan["release"], "enabled": False,
            "units": {name: stage.digest(old.UNIT_DIR / name) for name in UNITS},
            "dropin_sha256": stage.digest(DROPIN), "runtime_inventory": runtime(), "new_accounts": new_accounts,
            "preserved": preserved, "previous_units": old_record["units"],
            "original_fixture_sha256": stage.digest(STATE / "fixture.db")}
        write_private(RECORD, record)
        old.run("systemctl", "daemon-reload")
        installed()
        return record  # No restart/start/enable/ACL/keys/grant/route operation.
    except BaseException:
        # Both socket/process groups attempted, even if systemctl itself fails.
        old.run("systemctl", "stop", *[p.name for p in changed if p.name.endswith(".socket")], check=False)
        old.run("systemctl", "stop", *[p.name for p in changed if p.name.endswith(".service")], check=False)
        for path, approved in changed.items():
            if path.exists() and not path.is_symlink() and stage.digest(path) == approved:
                if path.name in backups:
                    atomic_file(ROOT / "previous-units" / path.name, path, expected=approved)
                else:
                    path.unlink()
        if dropin_directory_created and not any(DROPIN.parent.iterdir()):
            DROPIN.parent.rmdir()
        old.run("systemctl", "daemon-reload", check=False)
        raise


def rollback():
    stop()  # Drift never prevents shutting down all advisor entrances.
    if KEYS_RECORD.exists() or KEYS_RECORD.is_symlink():
        raise ValueError("Run advisor_keys_control.py remove before trial rollback")
    record = installed()
    for name, expected in record["previous_units"].items():
        previous = stage.exact(ROOT / "previous-units" / name)
        if stage.digest(previous) != expected:
            raise ValueError("Preserved unit backup changed")
    for name in UNITS:
        path = old.UNIT_DIR / name
        if name in record["previous_units"]:
            atomic_file(ROOT / "previous-units" / name, path, expected=record["units"][name])
        else:
            path.unlink()
    DROPIN.unlink()
    DROPIN.parent.rmdir()
    old.run("systemctl", "daemon-reload")
    # All old/new ledgers, receipts, recovery, users and runtimes remain. An
    # already-running owner frontend is never stopped/restarted implicitly.


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("install", "preflight", "stop", "rollback"))
    parser.add_argument("--bundle", type=Path)
    parser.add_argument("--approve-install")
    args = parser.parse_args()
    if args.action == "install":
        if not args.bundle:
            parser.error("install requires a reviewed bundle")
        install(args.bundle, args.approve_install)
    elif args.action == "preflight":
        print(json.dumps({"enabled": False, "installation_sha256": stage.digest(RECORD), "record": installed()}))
    elif args.action == "stop":
        stop()
    else:
        rollback()


if __name__ == "__main__":
    main()
