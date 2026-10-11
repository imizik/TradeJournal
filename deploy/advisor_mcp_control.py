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


def run(*args, check=True):
    result = subprocess.run([str(a) for a in args], capture_output=True, check=False)
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
            run("/usr/bin/python3.12", "-m", "venv", ROOT / name / ".venv")
            packages = ["mcp==1.28.1", "PyJWT[crypto]==2.13.0"] if name == "adapter" else ["trade-journal-backend==0.1.0"]
            run(ROOT / name / ".venv/bin/python", "-m", "pip", "install", "--no-index", "--find-links",
                bundle / "wheels", *packages)
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
            "source_files": {str(p.relative_to(ROOT)): digest(p) for role in ("adapter", "backend")
                for p in (ROOT / role).rglob("*") if p.is_file() and ".venv" not in p.parts},
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
    for relative, expected in record["source_files"].items():
        path = exact(ROOT / relative)
        if digest(path) != expected or path.stat().st_uid != 0 or path.stat().st_mode & 0o022:
            raise ValueError("Advisor runtime source changed or is writable")
    return record


def activation_identity():
    """Read-only preflight in the private runtime; no issuer/provider access."""
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
    subprocess.run([ROOT / "backend/.venv/bin/python", "-c", script, str(CONFIG / "config.json"), str(STATE / "fixture.db")],
        cwd=ROOT / "backend", env={"PATH": "/usr/bin:/bin", "PYTHON_DOTENV_DISABLED": "1"},
        capture_output=True, check=True)
    return {"installation_sha256": digest(RECORD), "config_sha256": digest(CONFIG / "config.json"),
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
