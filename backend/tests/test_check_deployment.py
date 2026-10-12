"""Offline proof for the disabled pre-trade check installer, units and policy."""
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from tests.test_advisor_mcp_bundle import REPO, load

sys.path.insert(0, str(REPO / "deploy"))

network = load("check_network")
scope = load("check_scope")
control = load("check_control")
old = control.old
UNITS = REPO / "deploy/cloud-mcp-check"


def unit(name):
    return (UNITS / name).read_text()


def test_service_unit_is_isolated_and_gets_provider_key_only_by_credential():
    text = unit("tradejournal-check.service")
    assert "User=tj-check\n" in text and "\nEnvironmentFile=" not in text and "[Install]" not in text
    assert "LoadCredential=alpaca-key-id:/etc/tradejournal-check/alpaca-key-id" in text
    assert "LoadCredential=alpaca-secret-key:/etc/tradejournal-check/alpaca-secret-key" in text
    assert "database" not in text.split("InaccessiblePaths=")[0].lower()
    assert "ReadWritePaths=/var/lib/tradejournal-check\n" in text
    assert "Requires=tradejournal-check.socket tradejournal-check-network.service" in text
    for hidden in ("-/etc/tradejournal-check/features-database-url", "-/etc/tradejournal ", "-/opt/tradejournal ",
            "-/var/lib/tradejournal ", "-/run/postgresql"):
        assert hidden in text
    socket = unit("tradejournal-check.socket")
    assert "ListenStream=/run/tradejournal-check/mcp.sock" in socket and "SocketGroup=caddy" in socket
    assert "[Install]" not in socket


def test_owner_reader_unit_is_private_readonly_and_networkless():
    service = unit("tradejournal-check-owner.service")
    assert "User=tj-check\n" in service and "PrivateNetwork=true" in service and "RestrictAddressFamilies=AF_UNIX\n" in service
    assert "LoadCredential" not in service and "EnvironmentFile" not in service and "[Install]" not in service
    assert "TemporaryFileSystem=/etc:ro /var:ro /opt:ro /run:ro" in service
    assert "BindReadOnlyPaths=/opt/tradejournal-check/backend /etc/tradejournal-check/owner " in service
    socket = unit("tradejournal-check-owner.socket")
    assert "ListenStream=/run/tradejournal-check-owner/owner.sock" in socket and "SocketUser=root" in socket
    assert f"SocketGroup={control.OWNER_WEB}\n" in socket and "SocketMode=0660" in socket and "[Install]" not in socket


def test_publisher_and_key_units_are_finite_and_separate():
    features = unit("tradejournal-check-features.service")
    assert "Type=oneshot" in features and "User=tj-check-features" in features
    assert "LoadCredential=database-url:/etc/tradejournal-check/features-database-url" in features
    assert "IPAddressDeny=any\nIPAddressAllow=localhost" in features
    service = unit("tradejournal-check.service")
    assert "IPAddressDeny=localhost link-local multicast 10.0.0.0/8" in service and "IPAddressAllow=127.0.0.53\n" in service and "alpaca" not in features.split("InaccessiblePaths=")[0]
    for hidden in ("alpaca-key-id", "alpaca-secret-key", "-/var/lib/tradejournal-check "):
        assert hidden in features
    keys = unit("tradejournal-check-keys.service")
    assert "User=tj-check-keys" in keys and "cloud_mcp_d0_refresh.py" in keys and "LoadCredential" not in keys
    for timer in ("tradejournal-check-keys.timer", "tradejournal-check-features.timer"):
        assert "WantedBy=timers.target" in unit(timer)
    caddy = unit("Caddyfile.example")
    assert "path /check/mcp" in caddy and "/.well-known/oauth-protected-resource/check/mcp" in caddy
    assert "8080" not in caddy and "8000" not in caddy


def test_network_policy_service_dns_https_only_features_postgres_only():
    policy = network.check_policy(1001, 1002, 1003, ["1.1.1.1"], ["203.0.113.5"])
    assert policy.startswith("table inet tj_check {")
    assert "meta skuid 1001 ip daddr { 1.1.1.1 } udp dport 53 accept" in policy
    blocked = next(line for line in policy.splitlines() if "skuid 1001 ip daddr {" in line and "drop" in line)
    assert "127.0.0.0/8" in blocked and "10.0.0.0/8" in blocked and "203.0.113.5" in blocked
    assert policy.index(blocked) < policy.index("meta skuid 1001 meta nfproto ipv4 tcp dport 443 accept")
    assert "meta skuid 1003 ip daddr 127.0.0.1 tcp dport 5432 accept" in policy
    assert "skuid 1003 meta nfproto ipv4 tcp dport 443" not in policy
    assert "flush" not in policy
    with pytest.raises(ValueError):
        network.check_policy(1001, 1001, 1003, ["1.1.1.1"], [])


def test_view_sql_is_narrow_and_hashes_fill_keys():
    sql = scope.view_sql()
    assert "WITH (security_barrier=true)" in sql and "GRANT SELECT ON public.pretrade_feature_source TO tj_check_features" in sql
    assert "encode(sha256(convert_to(f.raw_email_id, 'UTF8')), 'hex') AS source_fill_key" in sql
    selected = sql.split("FROM trade t")[0]
    for forbidden in ("account_id", "t.id", "last4", "broker_account_id", "notes", "a."):
        assert forbidden not in selected
    assert "NOT IN ('webull')" in sql


@pytest.fixture
def staged(tmp_path):
    wheels = tmp_path / "wheels"
    wheels.mkdir()
    (wheels / "trade_journal_backend-0.1.0-py3-none-any.whl").write_bytes(b"fixture wheel")
    bundle = tmp_path / "bundle"
    control.stage(bundle, wheels=wheels)
    return bundle


def test_stage_is_private_disabled_and_complete(staged):
    manifest = control.validate(staged)
    assert manifest["enabled"] is False and "backend/app/engine/pretrade_check.py" in manifest["inventory"]
    assert not any(name.endswith((".env", ".db")) or "/tests/" in name for name in manifest["inventory"])
    assert json.loads((staged / "config/config.json").read_text())["enabled"] is False
    (staged / "config/config.json").write_text(json.dumps({"enabled": True, "profiles": []}))
    with pytest.raises(ValueError):
        control.validate(staged)


@pytest.fixture
def host(tmp_path, monkeypatch):
    """A fake Ubuntu host: paths under tmp_path, recorded commands, no systemd."""
    for name in ("ROOT", "CONFIG", "STATE", "KEYS", "FEATURES", "RUN", "OWNER_RUN"):
        monkeypatch.setattr(control, name, tmp_path / ("host-" + name.lower()))
    monkeypatch.setattr(control, "RECORD", control.ROOT / "installation.json")
    unit_dir = tmp_path / "systemd"
    unit_dir.mkdir()
    monkeypatch.setattr(control, "UNIT_DIR", unit_dir)
    calls = []

    def run(*args, check=True):
        calls.append([str(a) for a in args])
        if str(args[0]).endswith("python3.12"):
            python = Path(args[-1]) / "bin/python"
            python.parent.mkdir(parents=True)
            python.write_text("")
        if args[:3] in (("getent", "group", "caddy"), ("getent", "passwd", control.OWNER_WEB)):
            return SimpleNamespace(returncode=0)
        if args[:2] == ("systemctl", "show"):
            return SimpleNamespace(returncode=0, stdout=b"inactive\n")
        return SimpleNamespace(returncode=2 if args[0] in ("getent", "systemctl") and args[1] in ("passwd", "group", "cat", "is-active") else 0)
    monkeypatch.setattr(old, "run", run)
    monkeypatch.setattr(old, "root_only", lambda: None)
    monkeypatch.setattr(old, "normalize_new_runtime", lambda *a, **k: None)
    monkeypatch.setattr(old, "runtime_inventory", lambda **k: {"fixture": True})
    monkeypatch.setattr(control.platform, "freedesktop_os_release", lambda: {"ID": "ubuntu", "VERSION_ID": "24.04"})
    monkeypatch.setattr(control.platform, "machine", lambda: "x86_64")
    ids = iter(range(1001, 1004))
    monkeypatch.setattr(control.pwd, "getpwnam", lambda name: SimpleNamespace(
        pw_uid=2001 if name == control.OWNER_WEB else next(ids)))
    monkeypatch.setattr(control.grp, "getgrnam", lambda name: SimpleNamespace(gr_gid=990))
    original_stat = Path.stat
    monkeypatch.setattr(Path, "stat", lambda path, *a, **k: os.stat_result(
        [*list(original_stat(path, *a, **k))[:4], 0, *list(original_stat(path, *a, **k))[5:]]))
    return calls


def test_install_writes_disabled_units_and_no_credentials(staged, host, monkeypatch):
    calls = host
    with pytest.raises(ValueError):
        control.install(staged, "0" * 64, dns_servers=["1.1.1.1"], host_ips=["203.0.113.5"])
    with pytest.raises(ValueError):  # A bad resolver refuses before any identity exists.
        control.install(staged, control.digest(staged / "manifest.json"), dns_servers=["resolver.example"], host_ips=[])
    assert not any(c[0] in ("groupadd", "useradd") for c in calls)
    record = control.install(staged, control.digest(staged / "manifest.json"), dns_servers=["1.1.1.1"],
        host_ips=["203.0.113.5"])
    assert record["enabled"] is False and record["uids"] == {"service": 1001, "keys": 1002, "features": 1003}
    assert set(record["units"]) == set(control.UNITS) and sorted(p.name for p in control.UNIT_DIR.iterdir()) == sorted(control.UNITS)
    assert not any(c[0] == "systemctl" and c[1] in ("start", "enable", "restart") for c in calls)
    assert not any(c[0] == "nft" or c[0].endswith("/nft") for c in calls)
    config_dir = control.CONFIG
    assert sorted(p.name for p in config_dir.iterdir()) == sorted(control.SETTINGS)  # No credential files.
    assert "meta skuid 1001" in (config_dir / "network.nft").read_text()
    assert json.loads((config_dir / "config.json").read_text())["enabled"] is False
    owner = json.loads((config_dir / "owner/config.json").read_text())
    assert owner == {"enabled": False, "peer_uid": 2001, "socket_path": str(control.OWNER_RUN / "owner.sock"),
        "ledger_path": "/var/lib/tradejournal-check/ledger.db"}
    assert (control.ROOT / "backend/data/alpaca_cache").is_dir()
    assert not list((control.ROOT / "backend").glob("**/.env"))
    with pytest.raises(ValueError):  # A second install refuses every collision.
        control.install(staged, control.digest(staged / "manifest.json"), dns_servers=["1.1.1.1"], host_ips=[])
    # Activation edits config.json; that is not drift, but a changed policy is.
    monkeypatch.setattr(control.pwd, "getpwnam", lambda name: SimpleNamespace(
        pw_uid=record["uids"][next(r for r, a in control.ACCOUNTS.items() if a == name)], pw_gid=990,
        pw_shell="/usr/sbin/nologin"))
    (config_dir / "config.json").write_text(json.dumps({"enabled": True}))
    (config_dir / "refresh-keys.json").write_text(json.dumps({"issuer_url": "https://real.example/"}))
    assert control.installed()["format"] == "check-installation-v1"
    removed = control.remove()
    assert set(removed["removed_units"]) == set(control.UNITS) and not list(control.UNIT_DIR.iterdir())
    assert (config_dir / "config.json").exists() and control.STATE.exists()
    assert not control.RECORD.exists()
    stopped = [c for c in calls if c[:2] == ["systemctl", "stop"]]
    assert stopped and any("tradejournal-check.service" in c for c in stopped)


def test_check_modules_never_import_the_owner_api_or_database_engine():
    for name in ("cloud_mcp_check.py", "cloud_mcp_check_common.py", "cloud_mcp_check_ledger.py", "pretrade_features.py"):
        text = (REPO / "backend" / name).read_text()
        for forbidden in ("from app.main", "import app.main", "from app.database", "import app.database", "127.0.0.1:8080", ":8000"):
            assert forbidden not in text
    result = subprocess.run(["git", "grep", "-l", "cloud_mcp_check", "--", "backend/app"], cwd=REPO, capture_output=True)
    assert result.stdout == b""


def test_upgrade_swaps_only_the_stopped_runtime_and_keeps_the_previous(staged, host, monkeypatch):
    approved = control.digest(staged / "manifest.json")
    record = control.install(staged, approved, dns_servers=["1.1.1.1"], host_ips=["203.0.113.5"])
    monkeypatch.setattr(control.pwd, "getpwnam", lambda name: SimpleNamespace(
        pw_uid=record["uids"][next(r for r, a in control.ACCOUNTS.items() if a == name)], pw_gid=990,
        pw_shell="/usr/sbin/nologin"))
    config_before = {p.name: p.read_bytes() for p in control.CONFIG.iterdir() if p.is_file()}
    (control.STATE / "ledger.db").write_bytes(b"saved checks")
    with pytest.raises(ValueError, match="already"):
        control.upgrade(staged, approved)
    # A newer reviewed bundle: same units and view, different code.
    (staged / "backend/cloud_mcp_check.py").write_text((staged / "backend/cloud_mcp_check.py").read_text() + "\n# newer\n")
    manifest = json.loads((staged / "manifest.json").read_text())
    manifest["inventory"] = control.inventory(staged)
    (staged / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    newer_approval = control.digest(staged / "manifest.json")
    monkeypatch.setattr(old, "runtime_inventory", lambda **k: {"fixture": (control.ROOT / "backend/cloud_mcp_check.py").read_text()[-8:]})
    (control.CONFIG / "context-views.sql").write_bytes((staged / "config/context-views.sql").read_bytes())
    record = json.loads(control.RECORD.read_text())
    record = {**record, "settings": {**record["settings"], "context-views.sql": control.digest(control.CONFIG / "context-views.sql")},
        "runtime_inventory": {"fixture": (control.ROOT / "backend/cloud_mcp_check.py").read_text()[-8:]}}
    control.RECORD.write_text(json.dumps(record))
    config_before = {p.name: p.read_bytes() for p in control.CONFIG.iterdir() if p.is_file()}
    control.RECORD.chmod(0o600)
    with pytest.raises(ValueError):
        control.upgrade(staged, "0" * 64)
    running = old.run
    monkeypatch.setattr(old, "run", lambda *a, check=True: SimpleNamespace(returncode=0, stdout=b"activating\n")
        if a[:2] == ("systemctl", "show") else running(*a, check=check))
    with pytest.raises(ValueError, match="Stop every check unit"):
        control.upgrade(staged, newer_approval)
    monkeypatch.setattr(old, "run", running)
    upgraded = control.upgrade(staged, newer_approval)
    assert upgraded["manifest_sha256"] == newer_approval and upgraded["previous_runtimes"][0]["manifest_sha256"] == approved
    assert (control.ROOT / "backend/cloud_mcp_check.py").read_text().endswith("# newer\n")
    previous = Path(upgraded["previous_runtimes"][0]["path"])
    assert not (previous / "backend/cloud_mcp_check.py").read_text().endswith("# newer\n")
    assert {p.name: p.read_bytes() for p in control.CONFIG.iterdir() if p.is_file()} == config_before
    assert (control.STATE / "ledger.db").read_bytes() == b"saved checks"
    # A bundle that changes a unit is refused before anything moves.
    (staged / "units/tradejournal-check.service").write_text("[Service]\n")
    manifest["inventory"] = control.inventory(staged)
    (staged / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    with pytest.raises(ValueError, match="units"):
        control.upgrade(staged, control.digest(staged / "manifest.json"))
    assert (control.ROOT / "backend/cloud_mcp_check.py").read_text().endswith("# newer\n")


def test_upgrade_adds_context_views_only_with_their_own_approval(staged, host, monkeypatch):
    approved = control.digest(staged / "manifest.json")
    record = control.install(staged, approved, dns_servers=["1.1.1.1"], host_ips=["203.0.113.5"])
    monkeypatch.setattr(control.pwd, "getpwnam", lambda name: SimpleNamespace(
        pw_uid=record["uids"][next(r for r, a in control.ACCOUNTS.items() if a == name)], pw_gid=990,
        pw_shell="/usr/sbin/nologin"))
    # The live host was installed before context views existed.
    record = json.loads(control.RECORD.read_text())
    assert "context-views.sql" not in record["settings"]  # Install never applies or pins database views.
    record["manifest_sha256"] = "1" * 64
    control.RECORD.write_text(json.dumps(record))
    control.RECORD.chmod(0o600)
    statements, present = [], {"count": "0"}

    def fake_psql(sql):
        statements.append(sql.decode())
        return present["count"] if sql.startswith(b"SELECT count(*)") else ""
    monkeypatch.setattr(control, "psql", fake_psql)
    sql_digest = control.digest(staged / "config/context-views.sql")
    with pytest.raises(ValueError, match="approve-sql"):
        control.upgrade(staged, approved)
    assert statements == []
    upgraded = control.upgrade(staged, approved, (sql_digest,))
    assert any("CREATE VIEW public.pretrade_position_source" in s for s in statements)
    assert upgraded["settings"]["context-views.sql"] == sql_digest == control.digest(control.CONFIG / "context-views.sql")
    # Re-runs: the exact recorded SQL skips; different SQL over existing views or a half state refuses.
    statements.clear()
    present["count"] = "2"
    sql = (staged / "config/context-views.sql").read_bytes()
    control.apply_context_views(sql)
    assert not any(s.startswith("BEGIN") for s in statements)
    with pytest.raises(RuntimeError, match="do not match"):
        control.apply_context_views(sql.replace(b"LIMIT 200", b"LIMIT 201"))
    present["count"] = "1"
    with pytest.raises(RuntimeError, match="do not match"):
        control.apply_context_views(sql)
    present["count"] = "0"
    with pytest.raises(RuntimeError, match="recorded but its views are missing"):
        control.apply_context_views(sql)
