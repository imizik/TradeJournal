"""Manual, disabled installer for the isolated pre-trade check service.

`stage` copies the reviewed check files, units and offline wheels into a
private bundle. `install` (root, exact manifest approval) creates three
dedicated UIDs, the runtime, private state/key/feature directories, the
UID-only network policy and unit files. Nothing is started, enabled or
granted; no provider or database credential is written (activation is a
separate approval). `check` reports state, `stop` stops every check unit and
`remove` retires the units while preserving the ledger, keys and features.
`upgrade` (all units stopped, exact manifest approval) replaces only the
runtime code and explicitly hash-approved units, preserving backups.
Never called by normal deployment. See docs/agent/advisor-pretrade-check-contract.md.
"""
from __future__ import annotations

import argparse
import grp
import json
import os
import stat
from pathlib import Path
import platform
import pwd
import shutil
import signal
import sys
import tempfile
import time

import advisor_mcp_control as old
from advisor_mcp_stage import SOURCE, digest, exact, inventory, reviewed_git
from check_network import check_policy
from check_scope import CAPTURE_VIEW, MARKET_VIEW, POSITION_VIEW, context_view_sql, market_view_sql, view_sql

FORMAT = "check-disabled-bundle-v1"
ROOT = Path("/opt/tradejournal-check")
CONFIG = Path("/etc/tradejournal-check")
STATE = Path("/var/lib/tradejournal-check")
SHADOW = Path("/var/lib/tradejournal-shadow")
API_USER = "tradejournal"
KEYS = Path("/var/lib/tradejournal-check-keys")
FEATURES = Path("/var/lib/tradejournal-check-features")
RUN = Path("/run/tradejournal-check")
OWNER_RUN = Path("/run/tradejournal-check-owner")
JOURNAL_RUN = Path("/run/tradejournal-check-journal")
RECORD = ROOT / "installation.json"
UNIT_DIR = old.UNIT_DIR
GROUP = "tj-check"
ACCOUNTS = {"service": "tj-check", "keys": "tj-check-keys", "features": "tj-check-features"}
# The private owner frontend (advisor trial) is the only peer of the owner reader.
OWNER_WEB = "tj-advisor-web-owner"
# The private journal frontend reads saved checks through its own socket and
# reader instance (Dots step 5), so neither frontend joins the other's group.
TEMPLATES = SOURCE / "deploy/cloud-mcp-check"
UNITS = ("tradejournal-check.socket", "tradejournal-check.service", "tradejournal-check-network.service",
    "tradejournal-check-keys.service", "tradejournal-check-keys.timer",
    "tradejournal-check-features.service", "tradejournal-check-features.timer",
    "tradejournal-check-owner.socket", "tradejournal-check-owner.service",
    "tradejournal-check-journal.socket", "tradejournal-check-journal.service")
RUNTIME_FILES = ("followup_common.py", "followup_ledger.py", "followup_tools.py", "tradier_stock_data.py", "jo_briefing_common.py", "jo_briefing_exchange.py", "jo_briefing_tools.py", "jo_research_common.py", "jo_research_exchange.py", "jo_research_tools.py", "company_research_common.py", "company_research_exchange.py", "company_research_tools.py", "conditional_plan_common.py", "conditional_plan_ledger.py", "conditional_plan_tools.py", "stock_watch_common.py", "stock_watch_ledger.py", "market_watch_owner.py", "market_watch_common.py", "market_watch_ledger.py", "cloud_check_owner.py", "cloud_mcp_check.py", "cloud_mcp_check_common.py", "cloud_mcp_check_ledger.py", "cloud_mcp_d0.py",
    "cloud_mcp_d0_refresh.py", "pretrade_features.py", "pretrade_feature_publish.py",
    "journal_coach_publication.py", "journal_coach_snapshot.py", "journal_coach_refresh.py")
SETTINGS = ("config.json", "refresh-keys.json", "network.nft", "feature-view.sql", "owner", "journal")
# Activation edits config.json and refresh-keys.json (real issuer, grant,
# client) and enables owner/config.json; the network policy and view SQL stay pinned.
PINNED_SETTINGS = ("network.nft", "feature-view.sql", "context-views.sql", "market-view.sql")
# Database changes an upgrade may add, each applied only under its own SHA-256 approval.
ADDITIVE_SQL = {"context-views.sql": (POSITION_VIEW, CAPTURE_VIEW), "market-view.sql": (MARKET_VIEW,)}


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
    # The one data file the checks read: the official FOMC/CPI/jobs calendar (no personal data).
    originals["backend/app/data/macro_calendar.json"] = SOURCE / "backend/app/data/macro_calendar.json"
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
            "config/feature-view.sql": view_sql(), "config/context-views.sql": context_view_sql(),
            "config/market-view.sql": market_view_sql()}
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
    for path in (ROOT, CONFIG, STATE, KEYS, FEATURES, RUN, OWNER_RUN, JOURNAL_RUN, *[UNIT_DIR / u for u in UNITS],
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
    if old.run("getent", "passwd", OWNER_WEB, check=False).returncode != 0:
        raise ValueError("Private owner frontend identity missing: " + OWNER_WEB)
    if not list((bundle / "wheels").glob("*.whl")):
        raise ValueError("Offline verified runtime wheels required")
    return manifest


def private_file(path, data, *, mode, owner="root", group="root"):
    if path.exists() or path.is_symlink():
        raise ValueError("Destination collision: " + str(path))
    path.write_bytes(data)
    path.chmod(mode)
    old.run("chown", f"{owner}:{group}", path)


def build_runtime(bundle, record_path):
    """Build ROOT/backend from the reviewed bundle's code and offline wheels."""
    shutil.copytree(bundle / "backend", ROOT / "backend")
    old.run("/usr/bin/python3.12", "-B", "-m", "venv", ROOT / "backend/.venv")
    old.run(ROOT / "backend/.venv/bin/python", "-B", "-m", "pip", "install", "--no-index", "--find-links",
        bundle / "wheels", "trade-journal-backend==0.1.0")
    # The shared Alpaca module creates this at import; supply it empty and
    # read-only. The service points its cache at its own CacheDirectory.
    (ROOT / "backend/data/alpaca_cache").mkdir(parents=True)
    old.normalize_new_runtime("backend", root=ROOT, record=record_path)


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
        build_runtime(bundle, RECORD)
        CONFIG.mkdir(mode=0o750)
        old.run("chown", f"root:{GROUP}", CONFIG)
        config = json.loads((bundle / "config/config.json").read_text())
        refresh = {"issuer_url": config["issuer_url"], "jwks_url": config["jwks_url"], "jwks_file": config["jwks_file"]}
        private_file(CONFIG / "config.json", (bundle / "config/config.json").read_bytes(), mode=0o640, group=GROUP)
        private_file(CONFIG / "refresh-keys.json", (json.dumps(refresh, indent=2) + "\n").encode(), mode=0o644)
        private_file(CONFIG / "network.nft", policy, mode=0o644)
        private_file(CONFIG / "feature-view.sql", (bundle / "config/feature-view.sql").read_bytes(), mode=0o644)
        owner = {"enabled": False, "peer_uid": pwd.getpwnam(OWNER_WEB).pw_uid,
            "socket_path": str(OWNER_RUN / "owner.sock"), "ledger_path": config["ledger_file"]}
        # Its own directory, bound whole: a replaced (renamed) file still reaches the running reader.
        (CONFIG / "owner").mkdir(mode=0o750)
        old.run("chown", f"root:{GROUP}", CONFIG / "owner")
        private_file(CONFIG / "owner/config.json", (json.dumps(owner, indent=2) + "\n").encode(), mode=0o640, group=GROUP)
        journal_config(config["ledger_file"])
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
            "settings": {name: digest(CONFIG / name) for name in PINNED_SETTINGS if (CONFIG / name).exists()},
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


def psql(sql_bytes):
    """Run SQL as the database superuser against the publisher's database, stopping on any error."""
    from urllib.parse import urlsplit
    import subprocess
    url = (CONFIG / "features-database-url").read_text().strip()
    database = urlsplit(url).path.lstrip("/")
    if not database or "/" in database:
        raise ValueError("Cannot read the target database name")
    result = subprocess.run(["runuser", "-u", "postgres", "--", "psql", "-X", "-q", "-A", "-t", "-v", "ON_ERROR_STOP=1",
        "-d", database], input=sql_bytes, capture_output=True, check=False,
        env={"PATH": old.ADMIN_PATH, "PGOPTIONS": "-c statement_timeout=30000"})
    if result.returncode:
        raise RuntimeError("Database statement refused")
    return result.stdout.decode().strip()


def apply_additive(name, sql_bytes):
    """Additive and re-runnable. Apply when none of the file's views exist and record the exact SQL beside the
    config; when all exist, skip only if that recorded SQL is these exact bytes; refuse anything else."""
    names = ADDITIVE_SQL[name]
    applied = CONFIG / name
    present = int(psql(("SELECT count(*) FROM pg_views WHERE schemaname = 'public' AND viewname IN (%s);"
        % ", ".join(f"'{view}'" for view in names)).encode()))
    if present == 0:
        if applied.exists() or applied.is_symlink():
            raise RuntimeError(f"{name} is recorded but its views are missing; review the database")
        psql(sql_bytes)
        private_file(applied, sql_bytes, mode=0o644)
    elif present != len(names) or not applied.is_file() or applied.read_bytes() != sql_bytes:
        raise RuntimeError(f"Existing views for {name} do not match this reviewed SQL; review the database before upgrading")


def apply_context_views(sql_bytes):
    apply_additive("context-views.sql", sql_bytes)


def add_context_views(bundle, sql_approval):
    """Apply the reviewed context views to an installed service (fresh installs and activation); nothing starts."""
    record = installed()
    validate(bundle)
    sql = exact(bundle / "config/context-views.sql")
    if digest(sql) != sql_approval:
        raise ValueError("Approve the exact context-views.sql SHA-256 with --approve-sql")
    apply_context_views(sql.read_bytes())
    updated = {**record, "settings": {**record["settings"], "context-views.sql": digest(CONFIG / "context-views.sql")}}
    temporary = ROOT / "installation.json.new"
    temporary.write_text(json.dumps(updated, indent=2) + "\n")
    temporary.chmod(0o600)
    temporary.rename(RECORD)
    return installed()


def journal_config(ledger_file):
    """The journal reader's own bound directory with a disabled config; enabling it is the owner's grant."""
    journal = {"enabled": False, "peer_uid": pwd.getpwnam(API_USER).pw_uid,
        "socket_path": str(JOURNAL_RUN / "owner.sock"), "ledger_path": ledger_file}
    (CONFIG / "journal").mkdir(mode=0o750)
    old.run("chown", f"root:{GROUP}", CONFIG / "journal")
    private_file(CONFIG / "journal/config.json", (json.dumps(journal, indent=2) + "\n").encode(), mode=0o640, group=GROUP)


def upgrade(bundle, approved, sql_approvals=(), unit_approvals=()):
    """Replace stopped runtime and individually hash-approved units. Config,
    credentials, ledger, keys, features, identities and policy stay unchanged; nothing starts.

    The replaced runtime is kept under ROOT/previous-runtime/. After a hard kill
    mid-swap (SIGKILL, power loss) every action refuses on inventory drift; move
    the partial ROOT/backend aside and move previous-runtime/<newest>/backend
    back to ROOT/backend, restore saved previous-runtime/<newest>/units files
    into UNIT_DIR, delete any unit the old record lacks (and a new
    CONFIG/journal) and run daemon-reload before inventory verification. Changed
    units require --approve-unit per hash; pinned SQL changes retain their own approval.
    """
    record = installed()
    old.approval(exact(bundle) / "manifest.json", approved)
    manifest = validate(bundle)
    for path in (bundle, *bundle.rglob("*"), *bundle.parents):
        info = path.stat()
        if info.st_uid != 0 or (info.st_mode & 0o022 and not info.st_mode & 0o1000):
            raise ValueError("Require root-owned immutable reviewed bundle/ancestors")
    if approved == record["manifest_sha256"]:
        raise ValueError("Bundle is already the installed runtime")
    # A unit the installation never had counts as changed and needs its own approval too.
    changed_units = [u for u in UNITS if digest(bundle / "units" / u) != record["units"].get(u)]
    if any(digest(bundle / "units" / u) not in unit_approvals for u in changed_units):
        raise ValueError("Bundle changes check units; approve each reviewed SHA-256 with --approve-unit")
    additions = []
    for name in PINNED_SETTINGS:
        if name not in record["settings"] and name in ADDITIVE_SQL:
            if digest(bundle / "config" / name) not in sql_approvals:
                raise ValueError(f"Bundle adds {name}; approve its SHA-256 with --approve-sql to apply it")
            additions.append(name)
        elif name != "network.nft" and digest(bundle / "config" / name) != record["settings"].get(name):
            raise ValueError(f"Bundle changes {name}; review that database change separately")
    # A oneshot refresh reports "activating" for its whole run; only inactive/failed count as stopped.
    running = [u for u in UNITS if old.run("systemctl", "show", u, "--property=ActiveState", "--value",
        check=False).stdout.decode().strip() not in {"inactive", "failed"}]
    if running:
        raise ValueError("Stop every check unit first (check_control.py stop): " + ", ".join(running))
    # A unit added by this upgrade gets the same collision checks as a fresh install.
    for unit in [u for u in changed_units if u not in record["units"]]:
        if (UNIT_DIR / unit).exists() or (UNIT_DIR / unit).is_symlink() or (UNIT_DIR / (unit + ".d")).exists() \
                or old.run("systemctl", "cat", unit, check=False).returncode == 0:
            raise ValueError("Refuse a pre-existing check unit: " + unit)
    if not (CONFIG / "journal").exists() and (CONFIG / "journal").is_symlink():
        raise ValueError("Refuse a symlinked journal config")
    for name in additions:  # Additive database change first: on refusal nothing else has moved.
        apply_additive(name, (bundle / "config" / name).read_bytes())
    previous = ROOT / "previous-runtime" / (time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "-" + record["manifest_sha256"][:12])
    previous.mkdir(parents=True, mode=0o700)
    (previous / "units").mkdir()
    for unit in changed_units:
        if unit in record["units"]:
            shutil.copyfile(UNIT_DIR / unit, previous / "units" / unit)
    (ROOT / "backend").rename(previous / "backend")
    added_journal = False
    scratch = ROOT / "upgrade-unrecorded.json"  # normalize_new_runtime refuses an existing record path.

    def interrupted(signum, frame):
        raise SystemExit("Upgrade interrupted by signal " + str(signum))  # Runs the rollback below.
    handlers = {s: signal.signal(s, interrupted) for s in (signal.SIGHUP, signal.SIGTERM, signal.SIGINT)}
    try:
        build_runtime(bundle, scratch)
        for unit in changed_units:
            replacement = UNIT_DIR / (unit + ".new")
            replacement.write_bytes((bundle / "units" / unit).read_bytes())
            replacement.chmod(0o644)
            replacement.replace(UNIT_DIR / unit)
        if not (CONFIG / "journal").exists():
            # Additive and disabled, as on a fresh install; nothing starts.
            added_journal = True  # Set first so a partial directory is rolled back too.
            journal_config(json.loads((CONFIG / "owner/config.json").read_text())["ledger_path"])
        if changed_units:
            old.run("systemctl", "daemon-reload")
        settings = dict(record["settings"])
        for name in additions:
            settings[name] = digest(CONFIG / name)  # Written only by apply_additive, byte-equal to the bundle.
        updated = {**record, "units": {u: digest(UNIT_DIR / u) for u in UNITS}, "manifest_sha256": approved, "settings": settings, "source_commit": manifest["source_commit"],
            "runtime_inventory": old.runtime_inventory(root=ROOT, roles=("backend",), python_roles=("backend",)),
            "previous_runtimes": [*record.get("previous_runtimes", []), {"path": str(previous),
                "manifest_sha256": record["manifest_sha256"], "source_commit": record["source_commit"]}]}
        temporary = ROOT / "installation.json.new"
        temporary.write_text(json.dumps(updated, indent=2) + "\n")
        temporary.chmod(0o600)
        temporary.rename(RECORD)
    except BaseException:
        # Put the recorded runtime back; the partial build is kept for review, never deleted.
        if (ROOT / "backend").exists():
            (ROOT / "backend").rename(previous / "failed-backend")
        (previous / "backend").rename(ROOT / "backend")
        for unit in changed_units:
            if unit in record["units"]:
                shutil.copyfile(previous / "units" / unit, UNIT_DIR / unit)
                (UNIT_DIR / unit).chmod(0o644)
            else:
                (UNIT_DIR / unit).unlink(missing_ok=True)
        if added_journal:
            shutil.rmtree(CONFIG / "journal", ignore_errors=True)
        if changed_units:
            old.run("systemctl", "daemon-reload")
        raise
    finally:
        for number, handler in handlers.items():
            signal.signal(number, handler)
    return installed()


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
    credentials = {name: (CONFIG / name).exists() for name in ("alpaca-key-id", "alpaca-secret-key", "tradier-api-key", "features-database-url")}
    policy_loaded = old.run("nft", "list", "table", "inet", "tj_check", check=False).returncode == 0
    if active["tradejournal-check.service"] and not policy_loaded:
        raise RuntimeError("Check service is running without its UID network policy; stop it")
    return {"installed": True, "enabled": record["enabled"], "active": active, "network_policy_loaded": policy_loaded, "keys": keys,
        "features_age_seconds": _age(FEATURES / "current.json"), "credentials_present": credentials,
        "ledger_present": (STATE / "ledger.db").exists()}


def stop():
    old.root_only()
    # Fixed names stay stoppable after drift.
    record = json.loads(exact(RECORD).read_text())
    # Units an older installation never had (the journal reader) are skipped; recorded ones never are.
    units = [u for u in UNITS if u in record.get("units", {}) or (UNIT_DIR / u).exists()]
    timers = [u for u in units if u.endswith(".timer")]
    results = [old.run("systemctl", "stop", *group, check=False) for group in (
        timers, [u for u in units if u.endswith(".socket")], [u for u in units if u.endswith(".service")])]
    if any(old.run("systemctl", "is-active", "--quiet", u, check=False).returncode == 0 for u in units) \
            or (RUN / "mcp.sock").exists() or (OWNER_RUN / "owner.sock").exists() or (JOURNAL_RUN / "owner.sock").exists() \
            or any(r.returncode for r in results):
        raise RuntimeError("Check shutdown incomplete; all groups were attempted")


def remove():
    """Retire units after a full stop. Ledger, keys, features, config and UIDs remain."""
    record = installed()
    old.run("systemctl", "disable", *[u for u in UNITS if u.endswith(".timer")], check=False)
    stop()
    for name in record["units"]:
        (UNIT_DIR / name).unlink()
    RECORD.rename(ROOT / ("removed-" + str(int(time.time())) + "-installation.json"))
    old.run("systemctl", "daemon-reload")
    return {"removed_units": sorted(record["units"]), "preserved": [str(STATE), str(KEYS), str(FEATURES), str(CONFIG)]}


def _exchange_acl(path, allowed):
    result = old.run("getfacl", "-cpn", path)
    entries = set(line.strip() for line in result.stdout.decode().splitlines() if line and not line.startswith("#"))
    if not entries <= allowed:
        raise ValueError("Unknown shadow exchange ACL: " + str(path))
    return entries


def shadow_exchange(enable):
    """Operator-only filesystem handoff. No service, config, grant or unit changes."""
    record = installed()
    api = pwd.getpwnam(API_USER)
    service_uid, gid = record["uids"]["service"], record["gid"]
    if api.pw_uid == service_uid or api.pw_gid == gid or gid in os.getgrouplist(API_USER, api.pw_gid):
        raise ValueError("API identity must not belong to the check group")
    outbox, setups = STATE / "shadow-outbox", SHADOW / "setups"
    candles = SHADOW / "candles"
    receipt = exact(ROOT / "shadow-exchange.json", exists=False)
    result = {"enabled": enable, "ledger_readable_by_api": False, "api_uid": api.pw_uid,
        "setups": str(setups), "outbox": str(outbox), "candles": str(candles)}
    if receipt.exists():
        info = receipt.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or stat.S_IMODE(info.st_mode) != 0o600:
            raise ValueError("Require a root-private shadow exchange receipt")
        previous = json.loads(receipt.read_text())
        expected = {**result, "enabled": previous.get("enabled")} if isinstance(previous, dict) else {}
        legacy = {k: v for k, v in expected.items() if k != "candles"}
        if not isinstance(previous, dict) or type(previous.get("enabled")) is not bool or previous not in (expected, legacy):
            raise ValueError("Unknown shadow exchange receipt")
    ledger = exact(STATE / "ledger.db")
    if not ledger.is_file() or ledger.stat().st_uid != service_uid or ledger.stat().st_mode & 0o077:
        raise ValueError("Require an existing private check ledger")
    reader = f"user:{api.pw_uid}:"
    state_info = exact(STATE).stat()
    if not stat.S_ISDIR(state_info.st_mode) or state_info.st_uid != service_uid or state_info.st_gid != gid:
        raise ValueError("Unknown check state ownership")
    state_acl = _exchange_acl(STATE, {"user::rwx", "group::---", "other::---", reader + "--x", "mask::--x", "mask::---"})
    directories = ((SHADOW, api.pw_uid, gid, 0o2750), (setups, api.pw_uid, gid, 0o2750),
        (candles, api.pw_uid, gid, 0o2750),
        (outbox, service_uid, gid, 0o750))
    outbox_acl = set()
    for path, uid, group, mode in directories:
        exact(path, exists=False)
        if path.exists():
            info = path.stat()
            if not stat.S_ISDIR(info.st_mode) or (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) != (uid, group, mode):
                raise ValueError("Unknown shadow exchange directory: " + str(path))
            base = {"user::rwx", "group::r-x", "other::---"}
            if path == outbox:
                base |= {reader + "r-x", "mask::r-x", "default:user::rwx", "default:group::r-x",
                    "default:other::---", "default:" + reader + "r-x", "default:mask::r-x"}
            entries = _exchange_acl(path, base)
            if path == outbox:
                outbox_acl = entries
    if old.run("sudo", "-u", API_USER, "test", "-r", ledger, check=False).returncode == 0:
        raise ValueError("API can already read the private ledger; refuse exchange")
    if enable:
        try:
            for path, uid, group, mode in directories:
                if not path.exists():
                    path.mkdir(mode=mode)
                    old.run("chown", f"{uid}:{group}", path)
                    path.chmod(mode)
            old.run("setfacl", "-m", f"u:{API_USER}:--x", STATE)
            old.run("setfacl", "-m", f"u:{API_USER}:r-x,d:u:{API_USER}:r-x", outbox)
            if old.run("sudo", "-u", API_USER, "test", "-r", ledger, check=False).returncode == 0:
                raise ValueError("API ledger isolation failed")
            if old.run("sudo", "-u", API_USER, "test", "-r", outbox, check=False).returncode != 0:
                raise ValueError("API outbox read verification failed")
        except BaseException:
            old.run("setfacl", "-x", f"u:{API_USER}", STATE, check=False)
            if outbox.exists():
                old.run("setfacl", "-x", f"u:{API_USER},d:u:{API_USER}", outbox, check=False)
            raise
    else:
        if reader + "--x" in state_acl:
            old.run("setfacl", "-x", f"u:{API_USER}", STATE)
        remove = ([f"u:{API_USER}"] if reader + "r-x" in outbox_acl else [])
        if "default:" + reader + "r-x" in outbox_acl:
            remove.append(f"d:u:{API_USER}")
        if remove:
            old.run("setfacl", "-x", ",".join(remove), outbox)
    # A receipt is replaced on enable/disable; private_file deliberately refuses
    # collisions and is reserved for new installation files.
    fd, temporary = tempfile.mkstemp(prefix=".shadow-exchange-", dir=ROOT)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write((json.dumps(result, indent=2) + "\n").encode())
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, receipt)
        directory_fd = os.open(ROOT, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("stage", "install", "check", "stop", "upgrade", "add-context-views", "remove",
        "enable-shadow-exchange", "disable-shadow-exchange"))
    parser.add_argument("--bundle", type=Path)
    parser.add_argument("--wheels", type=Path, help="Already verified release wheels; no downloading")
    parser.add_argument("--approve-install")
    parser.add_argument("--approve-upgrade")
    parser.add_argument("--approve-unit", action="append", default=[], help="SHA-256 of each reviewed replacement unit; requires all check services stopped")
    parser.add_argument("--approve-sql", action="append", default=[], help="SHA-256 of a reviewed additive SQL file")
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
    elif args.action == "upgrade":
        if not args.bundle:
            parser.error("upgrade requires a reviewed --bundle")
        record = upgrade(args.bundle, args.approve_upgrade, tuple(args.approve_sql), tuple(args.approve_unit))
        print(json.dumps({"upgraded": True, "started": False, "source_commit": record["source_commit"]}))
    elif args.action == "add-context-views":
        if not args.bundle or len(args.approve_sql) != 1:
            parser.error("add-context-views requires --bundle and one --approve-sql")
        add_context_views(args.bundle, args.approve_sql[0])
        print(json.dumps({"context_views": "applied", "started": False}))
    elif args.action in ("enable-shadow-exchange", "disable-shadow-exchange"):
        print(json.dumps(shadow_exchange(args.action == "enable-shadow-exchange")))
    elif args.action == "check":
        print(json.dumps(check()))
    elif args.action == "stop":
        stop()
        print(json.dumps({"stopped": True}))
    else:
        print(json.dumps(remove()))


if __name__ == "__main__":
    sys.exit(main())
