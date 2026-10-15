"""Manual approved advisor installation; never invoked by normal deployment.

Install remains disabled. Activate requires a separate exact reviewed-binding
approval; this controller creates no OAuth client/grant and publishes no proxy.
Stop/rollback always preserve the isolated receipt ledger and recovery files.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

from advisor_mcp_stage import UNITS, digest, exact, validate

ROOT = Path("/opt/tradejournal-advisor")
CONFIG = Path("/etc/tradejournal-advisor")
STATE = Path("/var/lib/tradejournal-advisor")
RUN = Path("/run/tradejournal-advisor")
UNIT_DIR = Path("/etc/systemd/system")
ACCOUNT = "tj-advisor"
BACKEND_ACCOUNT = "tj-advisor-backend"
RECORD = ROOT / "installation.json"
SOCKETS = tuple(u for u in UNITS if u.endswith(".socket"))
SERVICES = tuple(u for u in UNITS if u.endswith(".service"))
ADMIN_PATH = "/usr/sbin:/usr/bin:/sbin:/bin"


def run(*args, check=True):
    result = subprocess.run([str(a) for a in args], capture_output=True, check=False,
        env={"PATH": ADMIN_PATH, "PYTHON_DOTENV_DISABLED": "1", "PYTHONDONTWRITEBYTECODE": "1"})
    if check and result.returncode:
        raise RuntimeError("Advisor operation refused: " + str(args[0]))
    return result


def root_only():
    if os.geteuid() != 0:
        raise ValueError("Explicit advisor operations require root")


def approval(path, approved):
    exact(path)
    if not approved or approved != digest(path):
        raise ValueError("Approval must name the exact independently reviewed file SHA256")


def preflight_install(bundle):
    validate(bundle)
    if any(p.stat().st_uid != 0 for p in (bundle, *bundle.rglob("*"))):
        raise ValueError("Root must own the private reviewed bundle before installation")
    for parent in bundle.parents:
        mode = parent.stat().st_mode
        if parent.stat().st_uid != 0 or (mode & 0o022 and not mode & 0o1000):
            raise ValueError("Bundle ancestors must be root-owned and immutable or sticky")
    for path in (ROOT, CONFIG, STATE, RUN, *[UNIT_DIR / u for u in UNITS], *[UNIT_DIR / (u + ".d") for u in UNITS]):
        exact(path.parent)
        if path.exists() or path.is_symlink():
            raise ValueError("Refuse pre-existing advisor destination: " + str(path))
    for name in (ACCOUNT, BACKEND_ACCOUNT):
        for database in ("passwd", "group"):
            if run("getent", database, name, check=False).returncode == 0:
                raise ValueError("Refuse an existing advisor identity")
    for unit in UNITS:
        if run("systemctl", "cat", unit, check=False).returncode == 0:
            raise ValueError("Refuse a loaded advisor unit from any search path")
    if run("getent", "group", "caddy", check=False).returncode != 0:
        raise ValueError("Dedicated reverse proxy socket group missing")
    if not list((bundle / "wheels").glob("*.whl")):
        raise ValueError("Offline verified runtime wheels required for installation")


def stop():
    root_only()
    # Stop sockets first, then processes. A socket must not reactivate a worker.
    socket_result = run("systemctl", "stop", *SOCKETS, check=False)
    service_result = run("systemctl", "stop", *SERVICES, check=False)
    for unit in UNITS:
        if run("systemctl", "is-active", "--quiet", unit, check=False).returncode == 0:
            raise RuntimeError("Advisor shutdown incomplete")
    if any((RUN / name).exists() for name in ("mcp.sock", "backend.sock")):
        raise RuntimeError("Advisor sockets remain after shutdown")
    if socket_result.returncode or service_result.returncode:
        raise RuntimeError("Advisor shutdown command failed; both groups were attempted")


def runtime_inventory(*, root=None, roles=("adapter", "backend"), python_roles=("adapter", "backend")):
    """Hash all installed code/dependencies before invoking their interpreter.

    Nothing is ignored: installed bytecode and import hooks are code too. The
    read-only serving mounts cannot generate caches; preflight uses -B. OS
    interpreter symlink targets are pinned as well as the links themselves.
    """
    root = ROOT if root is None else root
    result = {}
    for role in roles:
        tree = exact(root / role)
        for path in (tree, *sorted(tree.rglob("*"))):
            relative = os.path.relpath(path, root)  # Same string; relative_to walks every parent.
            info = path.lstat()
            mode = info.st_mode & 0o7777
            if info.st_uid != 0 or (not path.is_symlink() and mode & 0o022):
                raise ValueError(f"Advisor runtime ownership or writable mode changed: {relative} uid={info.st_uid} mode={mode:o}")
            entry = {"mode": mode, "uid": info.st_uid, "gid": info.st_gid}
            if path.is_symlink():
                if ".venv" not in path.parts:
                    raise ValueError("Advisor runtime source symlink refused")
                target = path.resolve(strict=True)
                target_info = target.stat()
                if target_info.st_uid != 0 or target_info.st_mode & 0o022:
                    raise ValueError(f"Advisor runtime interpreter target is writable: {relative} uid={target_info.st_uid} mode={target_info.st_mode & 0o7777:o}")
                if target.is_dir() and not target.is_relative_to(tree):
                    raise ValueError("External runtime directory symlink refused")
                entry.update(kind="symlink", link=os.readlink(path), target=str(target),
                    target_mode=target_info.st_mode & 0o7777, target_uid=target_info.st_uid,
                    target_gid=target_info.st_gid, target_sha256=digest(target) if target.is_file() else None)
            elif path.is_file():
                entry.update(kind="file", sha256=digest(path))
            elif path.is_dir():
                entry.update(kind="directory")
            else:
                raise ValueError("Advisor runtime special file refused")
            result[relative] = entry
        if role in python_roles and not (tree / ".venv/bin/python").is_file():
            raise ValueError("Advisor runtime interpreter missing")
    return result


def normalize_new_runtime(role, *, root=None, record=None):
    """Only during a fresh exclusive install, before recording any approval.

    Wheel/venv modes vary with the build and umask. Make new owned code read-only
    to service identities, without touching a symlink target or installed drift.
    """
    root = ROOT if root is None else root
    record = RECORD if record is None else record
    if role not in {"adapter", "backend", "frontend", "bin"} or record.exists():
        raise ValueError("Refuse normalizing an existing recorded runtime")
    tree = exact(root / role)
    for path in (tree, *sorted(tree.rglob("*"))):
        info = path.lstat()
        relative = str(path.relative_to(root))
        if info.st_uid != 0:
            raise ValueError(f"New advisor runtime not root-owned: {relative} uid={info.st_uid} mode={info.st_mode & 0o7777:o}")
        if path.is_symlink():
            continue  # Never follow/chmod the OS interpreter or directory alias.
        if path.is_dir():
            mode = 0o755
        elif path.is_file():
            mode = 0o755 if info.st_mode & 0o111 else 0o644
        else:
            raise ValueError("New advisor runtime special file refused: " + relative)
        # O_NOFOLLOW is portable on the supported Ubuntu/macOS test hosts; the
        # descriptor prevents a leaf symlink from redirecting the chmod.
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            os.fchmod(descriptor, mode)
        finally:
            os.close(descriptor)


def install(bundle, *, approve_install):
    root_only()
    bundle = exact(bundle)
    approval(bundle / "manifest.json", approve_install)
    preflight_install(bundle)
    owned_units = []
    try:
        run("groupadd", "--system", ACCOUNT)
        for name in (ACCOUNT, BACKEND_ACCOUNT):
            run("useradd", "--system", "--no-create-home", "--shell", "/usr/sbin/nologin", "--gid", ACCOUNT, name)
        ROOT.mkdir(mode=0o755)
        CONFIG.mkdir(mode=0o750)
        STATE.mkdir(mode=0o700)
        run("chown", f"root:{ACCOUNT}", CONFIG)
        run("chown", f"{BACKEND_ACCOUNT}:{ACCOUNT}", STATE)
        for name in ("adapter", "backend"):
            shutil.copytree(bundle / name, ROOT / name)
            for p in (ROOT / name).rglob("*"):
                p.chmod(0o644 if p.is_file() else 0o755)
            (ROOT / name).chmod(0o755)
            run("/usr/bin/python3.12", "-B", "-m", "venv", ROOT / name / ".venv")
            packages = ["mcp==1.28.1", "PyJWT[crypto]==2.13.0"] if name == "adapter" else ["trade-journal-backend==0.1.0"]
            run(ROOT / name / ".venv/bin/python", "-B", "-m", "pip", "install", "--no-index", "--find-links",
                bundle / "wheels", *packages)
            if name == "backend":
                # Shared pure engines import Alpaca's cache path constructor.
                # Supply only empty readonly compatibility directories up front;
                # no cache/provider files or writable runtime mounts are allowed.
                data = ROOT / name / "data"
                cache = data / "alpaca_cache"
                if data.is_symlink() or cache.is_symlink():
                    raise ValueError("New backend import directory symlink refused")
                data.mkdir(mode=0o755, exist_ok=True)
                cache.mkdir(mode=0o755, exist_ok=True)
                if set(data.iterdir()) != {cache} or list(cache.iterdir()):
                    raise ValueError("Only empty backend import directories are allowed")
            normalize_new_runtime(name)
        for name in ("config.json", "public-keys.json"):
            shutil.copyfile(bundle / "config" / name, CONFIG / name)
            (CONFIG / name).chmod(0o640)
            run("chown", f"root:{ACCOUNT}", CONFIG / name)
        shutil.copyfile(bundle / "state/fixture.db", STATE / "fixture.db")
        (STATE / "fixture.db").chmod(0o600)
        run("chown", f"{BACKEND_ACCOUNT}:{ACCOUNT}", STATE / "fixture.db")
        shutil.copytree(bundle / "recovery", ROOT / "recovery")
        for name in UNITS:
            shutil.copyfile(bundle / "units" / name, UNIT_DIR / name)
            (UNIT_DIR / name).chmod(0o644)
            owned_units.append(name)
        record = {"format": "advisor-installation-v1", "manifest_sha256": approve_install,
            "source_commit": validate(bundle)["source_commit"], "enabled": False,
            "units": {u: digest(UNIT_DIR / u) for u in UNITS},
            "runtime_inventory": runtime_inventory(),
            "original_fixture_sha256": digest(STATE / "fixture.db")}
        RECORD.write_text(json.dumps(record, indent=2) + "\n")
        RECORD.chmod(0o600)
        run("systemctl", "daemon-reload")
        # No start, enable, proxy reload, binding/assignment change, or grant creation.
        return record
    except BaseException:
        # Never delete a copied ledger/recovery or guess at pre-existing resources.
        # Only unit files this attempt created are removed. Incomplete destinations
        # stay inert and force explicit recovery instead of an overwrite/retry.
        if owned_units:
            run("systemctl", "stop", *[u for u in owned_units if u.endswith(".socket")], check=False)
            run("systemctl", "stop", *[u for u in owned_units if u.endswith(".service")], check=False)
            for name in owned_units:
                (UNIT_DIR / name).unlink()
            run("systemctl", "daemon-reload", check=False)
        raise


def installed(*, verify_runtime=True):
    root_only()
    exact(RECORD)
    if RECORD.stat().st_mode & 0o077 or RECORD.stat().st_uid != 0:
        raise ValueError("Require the root-private installation record")
    record = json.loads(RECORD.read_text())
    if record.get("format") != "advisor-installation-v1" or set(record["units"]) != set(UNITS):
        raise ValueError("Unknown advisor installation")
    if not verify_runtime:
        return record  # Shutdown must still work after runtime/unit drift.
    for name, expected in record["units"].items():
        exact(UNIT_DIR / name)
        if digest(UNIT_DIR / name) != expected or (UNIT_DIR / (name + ".d")).exists():
            raise ValueError("Advisor units changed; review replacement before activation")
    if runtime_inventory() != record.get("runtime_inventory"):
        raise ValueError("Advisor runtime inventory changed; review replacement before execution")
    return record


def activation_identity():
    """Read-only preflight in the private runtime; no issuer/provider access."""
    record = installed()  # Must precede any call into the installed interpreter.
    config = json.loads((CONFIG / "config.json").read_text())
    if (not config["enabled"] or not config["profiles"][0]["enabled"]
            or config["backend_socket"] != str(RUN / "backend.sock")
            or config["jwks_file"] != str(CONFIG / "public-keys.json")
            or "REQUIRES" in config["client_id"] or "REQUIRES" in config["profiles"][0]["subject"]
            or ".example.test" in config["resource_url"] or ".example.test" in config["issuer_url"]):
        raise ValueError("Reviewed dedicated binding remains incomplete or disabled")
    # Check active migrated invented assignment and digests using the supported
    # clean executable's factory in a credential-free child, not owner/app.main.
    script = ('from cloud_mcp_advisor_bridge import create_app; '
        'from cloud_mcp_advisor_common import read_config; from cloud_mcp_d0 import local_keys; '
        'import sys; local_keys(read_config(sys.argv[1])); create_app(sys.argv[1],sys.argv[2])')
    subprocess.run([ROOT / "backend/.venv/bin/python", "-B", "-c", script, str(CONFIG / "config.json"), str(STATE / "fixture.db")],
        cwd=ROOT / "backend", env={"PATH": "/usr/bin:/bin", "PYTHON_DOTENV_DISABLED": "1"},
        capture_output=True, check=True)
    installed()  # An unexpected import side effect cannot receive approval.
    return {"installation_sha256": digest(RECORD),
        "runtime_inventory_sha256": hashlib.sha256(json.dumps(record["runtime_inventory"], sort_keys=True).encode()).hexdigest(),
        "config_sha256": digest(CONFIG / "config.json"),
        "keys_sha256": digest(CONFIG / "public-keys.json"), "fixture_sha256": digest(STATE / "fixture.db")}


def activate(*, approve_activation):
    installed()
    # Approval binds all exact reviewed inputs, separate from installation.
    identity = activation_identity()
    approved = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    if approve_activation != approved:
        raise ValueError("Activation approval must name the current binding preflight SHA256")
    try:
        run("systemctl", "start", *SOCKETS)
        run("systemctl", "start", *SERVICES)
        for unit in UNITS:
            run("systemctl", "is-active", "--quiet", unit)
    except BaseException:
        stop()
        raise


def rollback():
    record = installed(verify_runtime=False)
    stop()
    installed()  # Refuse removing modified resources, but stop first regardless.
    for unit in record["units"]:
        (UNIT_DIR / unit).unlink()
    run("systemctl", "daemon-reload")
    # Retain source/config/users/fixture/recovery for private owner retrieval.
    # This removes only the optional advisor entrance, not any journal route.


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["install", "activation-preflight", "activate", "stop", "rollback"])
    parser.add_argument("--bundle", type=Path)
    parser.add_argument("--approve-install")
    parser.add_argument("--approve-activation")
    args = parser.parse_args()
    if args.action == "install":
        if not args.bundle:
            parser.error("install requires a reviewed disabled bundle")
        install(args.bundle, approve_install=args.approve_install)
    elif args.action == "activation-preflight":
        installed()
        identity = activation_identity()
        print(json.dumps({"identity": identity, "approval_sha256": hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()}))
    elif args.action == "activate":
        activate(approve_activation=args.approve_activation)
    elif args.action == "stop":
        installed(verify_runtime=False)
        stop()
    else:
        rollback()


if __name__ == "__main__":
    main()
