"""Explicit, disabled side-by-side advisor trial upgrade. Never auto-deployed.

Only installation, six-unit shutdown, receipt-preserving rollback, the
stopped runtime-only `upgrade`/`downgrade` and a separate additive
`migrate-ledger` are supported. No activation, assignment, keys, OAuth, proxy
or frontend restart.
"""
from __future__ import annotations

import argparse
import grp
import hashlib
import json
import os
from pathlib import Path
import platform
import pwd
import re
import shutil
import sqlite3
import subprocess
import tempfile
import time

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
# Runtime upgrade keeps each retired runtime here and journals an in-flight swap.
KEPT = ROOT / "previous-runtime"
FAILED = ROOT / "failed-upgrades"
INTENT = ROOT / "upgrade-intent.json"
LEDGER_BACKUPS = ROOT / "ledger-backups"
# The enabled loopback bridge socket starts the owner frontend on demand.
OWNER_BRIDGE = ("tradejournal-dot-trial-owner-bridge.socket", "tradejournal-dot-trial-owner-bridge.service")


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


def reviewed_bundle(bundle, approved):
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
    for relative in ("backend/cloud_advisor_owner.py", "frontend/server.js", "bin/node", "units/frontend.conf",
            "config/owner.json", "config/frontend.env", *["units/" + name for name in UNITS]):
        stage.exact(bundle / relative)
    if json.loads((bundle / "config/owner.json").read_text())["enabled"] is not False or "TJ_ADVISOR_OWNER_ENABLED=false\n" not in (bundle / "config/frontend.env").read_text():
        raise ValueError("Owner reader/frontend must remain disabled")
    if not list((bundle / "wheels").glob("*.whl")):
        raise ValueError("Verified offline wheels required")
    return manifest, plan


def preflight(bundle, approved):
    manifest, plan = reviewed_bundle(bundle, approved)
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
    return manifest, plan


def write_private(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")
    path.chmod(0o600)


def build_runtime(bundle, *, record):
    """Construct all roles at their final ROOT paths (venv paths are absolute)."""
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
            old.normalize_new_runtime(role, root=ROOT, record=record)
        else:
            (ROOT / role).chmod(0o700)


def stop():
    old.root_only()
    private_json(RECORD)  # Fixed names remain stoppable after code/unit drift.
    results = [old.run("systemctl", "stop", *[u for u in UNITS if u.endswith(suffix)], check=False)
        for suffix in (".socket", ".service")]
    active = any(old.run("systemctl", "is-active", "--quiet", u, check=False).returncode == 0 for u in UNITS)
    sockets = [Path(trial.RUN) / "mcp.sock", Path(trial.RUN) / "backend.sock", Path(trial.OWNER_RUN) / "owner.sock"]
    if active or any(p.exists() for p in sockets) or any(r.returncode for r in results):
        raise RuntimeError("Six-unit shutdown incomplete; both groups attempted")


def installed(*, journal_ok=False):
    old.root_only()
    if not journal_ok and (INTENT.exists() or INTENT.is_symlink()):
        raise ValueError("Runtime swap journal pending; run resume first")
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
        build_runtime(bundle, record=RECORD)
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


def write_atomic(path, value):
    """Root-private same-directory replace: readers see either whole record."""
    fd, name = tempfile.mkstemp(prefix="." + path.name + ".", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(json.dumps(value, indent=2) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)  # Only this exclusive temporary.


def ledger_revision(path):
    """Alembic heads, read-only. Upgrade never migrates or rewrites the ledger."""
    connection = sqlite3.connect(stage.exact(path).as_uri() + "?mode=ro", uri=True)
    try:
        return sorted(row[0] for row in connection.execute("SELECT version_num FROM alembic_version"))
    finally:
        connection.close()


def expected_unit_digests(bundle):
    """Bundle units as they would be installed, including key upkeep's binds."""
    units = {name: (bundle / "units" / name).read_bytes() for name in UNITS}
    if KEYS_RECORD.exists() or KEYS_RECORD.is_symlink():
        import advisor_keys_control as keys  # Lazy: that module imports this one.
        for name in keys.SERVING:
            units[name] = keys.serving_unit(units[name].decode(), keys.unit_binds(name)).encode()
    return {name: hashlib.sha256(data).hexdigest() for name, data in units.items()}


def runtime_stopped():
    # The owner frontend executes ROOT/bin/node and ROOT/frontend under its drop-in,
    # and its bridge socket would start it. "activating"/"deactivating" count as running.
    for unit in (*UNITS, trial.FRONTEND, *OWNER_BRIDGE):
        state = old.run("systemctl", "show", unit, "--property=ActiveState", "--value", check=False).stdout.decode().strip()
        if state not in {"inactive", "failed"}:
            raise ValueError("Stop the six advisor units, the owner bridge socket and the owner frontend first: " + unit)


def resume():
    """Finish or reverse an interrupted runtime swap from its journal; re-runnable.

    Before the record switch, put the recorded runtime back (a partial new build
    moves to failed-upgrades, never deleted). After it, only clear the journal.
    """
    if not (INTENT.exists() or INTENT.is_symlink()):
        return
    intent = private_json(INTENT)
    out = KEPT / intent["out"]
    incoming = None if intent["in"] is None else KEPT / intent["in"]
    if stage.digest(RECORD) == intent["record_sha256"]:
        for role in ROLES:
            current = ROOT / role
            if incoming is not None:
                if not (incoming / role).exists() and current.exists():
                    current.rename(incoming / role)  # Moved-in previous runtime goes back.
            elif (out / role).exists() and current.exists():
                FAILED.mkdir(mode=0o700, exist_ok=True)
                (FAILED / intent["out"]).mkdir(mode=0o700, exist_ok=True)
                current.rename(FAILED / intent["out"] / role)
        for role in ROLES:
            if (out / role).exists():
                (out / role).rename(ROOT / role)
        if out.exists():
            out.rmdir()
        installed(journal_ok=True)
    else:
        installed(journal_ok=True)
        if incoming is not None and incoming.exists():
            incoming.rmdir()
    INTENT.unlink()


def swap_ready():
    """Stopped, verified trial (and key upkeep when present), no swap in flight."""
    runtime_stopped()
    resume()
    record = installed()
    if KEYS_RECORD.exists() or KEYS_RECORD.is_symlink():
        import advisor_keys_control as keys
        keys.installed()
    return record


def begin_swap(record, incoming):
    KEPT.mkdir(mode=0o700, exist_ok=True)
    stage.exact(KEPT)
    # Unique and exclusive before the journal names it (failed-upgrades reuses the name).
    prefix = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "-" + record["manifest_sha256"][:12] + "-"
    slot = Path(tempfile.mkdtemp(prefix=prefix, dir=KEPT)).name
    write_atomic(INTENT, {"format": "advisor-trial-runtime-swap-v1", "record_sha256": stage.digest(RECORD),
        "out": slot, "in": incoming})
    for role in ROLES:
        (ROOT / role).rename(KEPT / slot / role)
    return slot


def retired(record, slot, schema):
    return {"slot": slot, **{key: record[key] for key in ("manifest_sha256", "source_commit", "release", "runtime_inventory")},
        "schema_revision": schema, "schema_sql": record.get("schema_sql"),
        "kept_inventory": old.runtime_inventory(root=KEPT / slot, roles=ROLES)}


def migration_ancestors(bundle, heads):
    """Revisions at or below the bundle's heads, read from its own scripts."""
    parents = {}
    for script in (bundle / "backend/alembic/versions").glob("*.py"):
        text = script.read_text()
        revision = re.search(r'^revision\s*(?::[^=]*)?=\s*["\']([^"\']+)["\']', text, re.M)
        down = re.search(r'^down_revision\s*(?::[^=]*)?=\s*(.+)$', text, re.M)
        if revision and down:
            parents[revision[1]] = re.findall(r'["\']([^"\']+)["\']', down[1])
    seen, pending = set(), list(heads)
    while pending:
        revision = pending.pop()
        if revision not in seen:
            seen.add(revision)
            pending.extend(parents.get(revision, ()))
    return seen


def ledger_content(path):
    """Schema SQL and row digests per table, read-only, for before/after equality."""
    connection = sqlite3.connect(stage.exact(path).as_uri() + "?mode=ro", uri=True)
    try:
        schema = dict(connection.execute("SELECT name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"))
        rows = {}
        for (name,) in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall():
            if name != "alembic_version":
                values = sorted(repr(row) for row in connection.execute('SELECT * FROM "' + name.replace('"', '""') + '"'))
                rows[name] = hashlib.sha256("\n".join(values).encode()).hexdigest()
        return {"schema": schema, "rows": rows}
    finally:
        connection.close()


def upgrade(bundle, approved):
    """Replace only the five runtime roles; config, ledger, units, accounts stay."""
    bundle = stage.exact(bundle)
    manifest, plan = reviewed_bundle(bundle, approved)
    record = swap_ready()
    if approved == record["manifest_sha256"]:
        raise ValueError("Bundle is already the installed runtime")
    if expected_unit_digests(bundle) != record["units"] or stage.digest(bundle / "units/frontend.conf") != record["dropin_sha256"]:
        raise ValueError("Bundle changes advisor units or the owner drop-in; review that replacement separately")
    live, schema = ledger_revision(STATE / "fixture.db"), ledger_revision(bundle / "state/fixture.db")
    if live != schema and not set(live) <= migration_ancestors(bundle, schema):
        raise ValueError("Ledger schema is not an ancestor of the bundle's; upgrade never migrates the ledger")
    try:
        slot = begin_swap(record, None)
        # Every role tree below is new from this attempt; no record describes it yet.
        build_runtime(bundle, record=KEPT / slot / "unrecorded-new-runtime.json")
        entry = retired(record, slot, live)
        os.sync()  # The new tree is durable before the record names it.
        write_atomic(RECORD, {**record, "manifest_sha256": approved, "source_commit": manifest["source_commit"],
            "release": plan["release"], "runtime_inventory": runtime(), "schema_revision": schema,
            "schema_sql": ledger_content(bundle / "state/fixture.db")["schema"],
            "previous_runtimes": [*record.get("previous_runtimes", []), entry]})
    except BaseException:
        resume()
        raise
    resume()
    return installed()  # No start/enable/restart/config/unit/ledger change.


def downgrade():
    """Swap back to the most recently retired runtime, keeping the current one."""
    record = swap_ready()
    kept = record.get("previous_runtimes") or []
    if not kept:
        raise ValueError("No retained previous runtime")
    target = kept[-1]
    live = ledger_revision(STATE / "fixture.db")
    if live != target["schema_revision"]:
        raise ValueError("Ledger was migrated past the retained runtime; restoring it needs a reviewed ledger procedure")
    incoming = stage.exact(KEPT / target["slot"])
    if (set(incoming.iterdir()) != {incoming / role for role in ROLES}
            or old.runtime_inventory(root=incoming, roles=ROLES) != target["kept_inventory"]):
        raise ValueError("Retained previous runtime changed")
    try:
        slot = begin_swap(record, target["slot"])
        for role in ROLES:
            (incoming / role).rename(ROOT / role)
        if runtime() != target["runtime_inventory"]:
            raise ValueError("Restored runtime differs from its recorded inventory")
        entry = retired(record, slot, live)
        os.sync()
        write_atomic(RECORD, {**record, **{key: target.get(key) for key in ("manifest_sha256", "source_commit", "release",
            "runtime_inventory", "schema_revision", "schema_sql")}, "previous_runtimes": [*kept[:-1], entry]})
    except BaseException:
        resume()
        raise
    resume()
    return installed()


def run_alembic(*args):
    """The installed, verified backend's own Alembic against only the v2 ledger."""
    url = "sqlite:///" + str(STATE / "fixture.db")
    subprocess.run([str(ROOT / "backend/.venv/bin/python"), "-B", "-m", "alembic", *args], cwd=ROOT / "backend",
        env={"PATH": old.ADMIN_PATH, "PYTHON_DOTENV_DISABLED": "1", "PYTHONDONTWRITEBYTECODE": "1",
            "DATABASE_URL": url, "MIGRATION_DATABASE_URL": url}, capture_output=True, check=True)


def migrate_ledger():
    """Separate step: bring the ledger to the installed runtime's schema.

    Only additive change is accepted: every existing table's SQL and rows must be
    identical afterwards. A root-private byte copy is kept first; a failed attempt
    puts those bytes back in place (same inode, so owner, mode and ACL stay).
    """
    record = swap_ready()
    ledger = STATE / "fixture.db"
    current, target, expected = ledger_revision(ledger), record.get("schema_revision"), record.get("schema_sql")
    if not target or not expected or current == target:
        raise ValueError("Ledger already matches the installed runtime schema")
    info, entries = ledger.stat(), set(STATE.iterdir())
    before = ledger_content(ledger)
    # The exact reviewed schema, plus any objects the ledger already had beyond it.
    wanted = {**{name: sql for name, sql in before["schema"].items() if name not in expected}, **expected}
    LEDGER_BACKUPS.mkdir(mode=0o700, exist_ok=True)
    stage.exact(LEDGER_BACKUPS)
    fd, name = tempfile.mkstemp(prefix=time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "-" + "-".join(current) + "-",
        suffix=".db", dir=LEDGER_BACKUPS)  # Unique, exclusive, 0600.
    backup = Path(name)
    with ledger.open("rb") as source, os.fdopen(fd, "wb") as copy:
        shutil.copyfileobj(source, copy)
        copy.flush()
        os.fsync(copy.fileno())
    original = stage.digest(ledger)
    if stage.digest(backup) != original:
        raise ValueError("Ledger backup differs from the ledger")
    try:
        run_alembic("upgrade", "heads")  # The installed scripts' heads are the recorded schema.
        after = ledger_content(ledger)
        final = ledger.stat()
        if (ledger_revision(ledger) != target or set(STATE.iterdir()) != entries or after["schema"] != wanted
                or any(after["schema"].get(name) != sql for name, sql in before["schema"].items() if name != "alembic_version")
                or any(after["rows"].get(name) != digest for name, digest in before["rows"].items())
                or (final.st_uid, final.st_gid, final.st_mode) != (info.st_uid, info.st_gid, info.st_mode)):
            raise ValueError("Migration changed existing ledger content or did not reach the runtime schema")
        installed()  # Runtime untouched by running its Alembic.
    except BaseException as error:
        # A leftover SQLite journal would be replayed onto restored bytes; leave that for review.
        if set(STATE.iterdir()) == entries and stage.digest(ledger) != original:
            with backup.open("rb") as source, ledger.open("r+b") as target_file:
                shutil.copyfileobj(source, target_file)
                target_file.truncate()
                target_file.flush()
                os.fsync(target_file.fileno())
            if stage.digest(ledger) != original:
                raise RuntimeError("Ledger restore incomplete; pre-migration copy is " + str(backup))
        error.add_note("Pre-migration ledger copy: " + str(backup))
        raise
    write_atomic(RECORD, {**record, "ledger_migrations": [*record.get("ledger_migrations", []),
        {"from": current, "to": target, "backup": str(backup), "backup_sha256": original}]})
    return installed()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("install", "preflight", "stop", "rollback", "upgrade", "downgrade", "resume",
        "migrate-ledger"))
    parser.add_argument("--bundle", type=Path)
    parser.add_argument("--approve-install")
    parser.add_argument("--approve-upgrade")
    args = parser.parse_args()
    if args.action == "install":
        if not args.bundle:
            parser.error("install requires a reviewed bundle")
        install(args.bundle, args.approve_install)
    elif args.action == "preflight":
        record = installed()
        print(json.dumps({"enabled": False, "installation_sha256": stage.digest(RECORD), "record": record,
            "ledger_revision": ledger_revision(STATE / "fixture.db")}))
    elif args.action == "stop":
        stop()
    elif args.action == "upgrade":
        if not args.bundle:
            parser.error("upgrade requires a reviewed bundle")
        record = upgrade(args.bundle, args.approve_upgrade)
        print(json.dumps({"upgraded": True, "started": False, "source_commit": record["source_commit"]}))
    elif args.action == "downgrade":
        record = downgrade()
        print(json.dumps({"downgraded": True, "started": False, "source_commit": record["source_commit"]}))
    elif args.action == "migrate-ledger":
        record = migrate_ledger()
        print(json.dumps({"migrated": record["ledger_migrations"][-1], "started": False}))
    elif args.action == "resume":
        old.root_only()
        runtime_stopped()
        resume()
        print(json.dumps({"installation_sha256": stage.digest(RECORD), "record": installed()}))
    else:
        rollback()


if __name__ == "__main__":
    main()
