"""Offline proof for optional advisor public-key upkeep on the trial install."""
import json
from pathlib import Path
import sys
import time
import os
from types import SimpleNamespace

import pytest

from tests import test_advisor_mcp_bundle as base
from tests import test_advisor_trial_bundle as trial_tests

sys.path.insert(0, str(base.REPO / "deploy"))
stage = base.stage
old = base.control
trial = trial_tests.control
keys = base.load("advisor_keys_control")
prepared = trial_tests.prepared
ISSUER = "https://advisor-identity.example.test/"
JWKS = "https://advisor-identity.example.test/.well-known/jwks.json"


def snapshot(expires_in=3600, issuer=ISSUER):
    now = int(time.time())
    return json.dumps({"issuer_url": issuer, "jwks_url": JWKS, "fetched_at": now,
        "expires_at": now + expires_in, "keys": [{"kid": "fixture", "kty": "RSA"}]}) + "\n"


def installed_trial(prepared, tmp_path, monkeypatch, *, expires_in=3600):
    bundle, calls = trial_tests.host(tmp_path, monkeypatch, prepared)
    trial.install(bundle, stage.digest(bundle / "manifest.json"))
    config_path = trial.CONFIG / "advisor/config.json"
    original = trial.CONFIG / "advisor/public-keys.json"
    original.write_text(snapshot(expires_in))
    config = json.loads(config_path.read_text())
    trial.write_private(config_path, {**config, "jwks_file": str(original)})
    for name, path in (("RUNTIME", "keys-runtime"), ("SETTINGS", "keys-settings"), ("KEYS", "keys-state")):
        monkeypatch.setattr(keys, name, tmp_path / path)
    monkeypatch.setattr(trial, "KEYS_RECORD", keys.record_path())
    monkeypatch.setattr(keys.os, "chown", lambda *args: None)
    lookup = keys.pwd.getpwnam
    publisher = SimpleNamespace(pw_name=keys.ACCOUNT, pw_uid=os.getuid(), pw_gid=280, pw_shell="/usr/sbin/nologin")
    monkeypatch.setattr(keys.pwd, "getpwnam", lambda name: publisher if name == keys.ACCOUNT else lookup(name))
    command = old.run
    def execute(*args, **kwargs):
        result = command(*args, **kwargs)
        if args[:2] == ("getent", "passwd") and args[2] == keys.ACCOUNT:
            result.returncode = 2
        return result
    monkeypatch.setattr(old, "run", execute)
    key_bundle = tmp_path / "key-bundle"
    keys.stage_bundle(key_bundle)
    calls.clear()
    return key_bundle, calls


def install(key_bundle):
    return keys.install(key_bundle, stage.digest(key_bundle / "manifest.json"),
        dns_servers=["127.0.0.53"], host_ips=["15.204.255.2"])


def test_install_mounts_maintained_snapshot_and_starts_nothing_then_remove_restores(prepared, tmp_path, monkeypatch):
    key_bundle, calls = installed_trial(prepared, tmp_path, monkeypatch)
    config_path = trial.CONFIG / "advisor/config.json"
    before = {path: path.read_bytes() for path in (config_path, *[old.UNIT_DIR / n for n in keys.SERVING])}
    record = install(key_bundle)
    snapshot_path = keys.KEYS / keys.SNAPSHOT_NAME
    assert json.loads(config_path.read_text())["jwks_file"] == str(snapshot_path) == record["snapshot"]
    assert snapshot_path.read_bytes() == (trial.CONFIG / "advisor/public-keys.json").read_bytes()
    for name in keys.SERVING:
        text = (old.UNIT_DIR / name).read_text()
        bind = next(line for line in text.splitlines() if line.startswith("BindReadOnlyPaths="))
        assert bind.endswith(" " + str(keys.KEYS))
        assert text.replace(" " + str(keys.KEYS), "") == before[old.UNIT_DIR / name].decode()
    for name in keys.KEY_UNITS:
        assert (old.UNIT_DIR / name).read_bytes() == (key_bundle / "units" / name).read_bytes()
    assert f"meta skuid {os.getuid()}" in (keys.SETTINGS / "network.nft").read_text()
    assert json.loads((keys.SETTINGS / "refresh-keys.json").read_text()) == {
        "issuer_url": ISSUER, "jwks_url": JWKS, "jwks_file": str(snapshot_path)}
    trial.installed()
    keys.installed()
    assert not any(word in command for command in calls for word in ("start", "restart", "enable"))
    assert keys.check()["keys"]["state"] == "fresh"
    with pytest.raises(ValueError, match="remove before trial rollback"):
        trial.rollback()  # Trial rollback cannot strand the key timer and network table.

    snapshot_path.write_text(snapshot(3000))  # The timer refreshed while installed.
    keys.remove()
    assert all(path.read_bytes() == value for path, value in before.items())
    assert (trial.CONFIG / "advisor/public-keys.json").read_text() == snapshot_path.read_text()
    assert not any((old.UNIT_DIR / name).exists() for name in keys.KEY_UNITS)
    assert snapshot_path.exists() and (keys.RUNTIME / "previous/original-public-keys.json").exists()
    trial.installed()
    trial.rollback()  # The original side-by-side rollback still works afterwards.


@pytest.mark.parametrize("change", ["approval", "active", "expired", "collision", "bundle", "identity"])
def test_refuses_before_any_host_change(prepared, tmp_path, monkeypatch, change):
    key_bundle, calls = installed_trial(prepared, tmp_path, monkeypatch, expires_in=-5 if change == "expired" else 3600)
    config_path = trial.CONFIG / "advisor/config.json"
    before = config_path.read_bytes()
    approved = stage.digest(key_bundle / "manifest.json")
    if change == "approval":
        approved = "0" * 64
    elif change == "active":
        command = old.run
        def active(*args, **kwargs):
            result = command(*args, **kwargs)
            if "is-active" in args:
                result.returncode = 0
            return result
        monkeypatch.setattr(old, "run", active)
    elif change == "collision":
        keys.KEYS.mkdir()
    elif change == "bundle":
        (key_bundle / "cloud_mcp_d0_refresh.py").write_text("unreviewed")
    elif change == "identity":
        command = old.run
        def exists(*args, **kwargs):
            result = command(*args, **kwargs)
            if args[:2] == ("getent", "passwd"):
                result.returncode = 0
            return result
        monkeypatch.setattr(old, "run", exists)
    with pytest.raises(ValueError):
        keys.install(key_bundle, approved, dns_servers=["127.0.0.53"], host_ips=[])
    assert config_path.read_bytes() == before
    assert not any("useradd" in command for command in calls)
    assert not any((old.UNIT_DIR / name).exists() for name in keys.KEY_UNITS)
    trial.installed()


def test_failed_config_switch_restores_units_and_record(prepared, tmp_path, monkeypatch):
    key_bundle, calls = installed_trial(prepared, tmp_path, monkeypatch)
    config_path = trial.CONFIG / "advisor/config.json"
    before = {path: path.read_bytes() for path in (config_path, trial.RECORD, *[old.UNIT_DIR / n for n in keys.SERVING])}
    replace = keys.os.replace
    def fail(source, target):
        if Path(target) == config_path:
            raise OSError("Controlled config switch failure")
        return replace(source, target)
    monkeypatch.setattr(keys.os, "replace", fail)
    with pytest.raises(OSError, match="Controlled"):
        install(key_bundle)
    assert all(path.read_bytes() == value for path, value in before.items())
    assert not any((old.UNIT_DIR / name).exists() for name in keys.KEY_UNITS)
    trial.installed()
    with pytest.raises(ValueError, match="collision"):  # Inert partial state blocks a blind retry.
        install(key_bundle)


def test_drifted_key_unit_or_script_is_refused(prepared, tmp_path, monkeypatch):
    key_bundle, _ = installed_trial(prepared, tmp_path, monkeypatch)
    install(key_bundle)
    (old.UNIT_DIR / keys.KEY_UNITS[1]).write_text("[Service]\nExecStart=/bin/sh\n")
    with pytest.raises(ValueError, match="Key unit drift"):
        keys.check()
    with pytest.raises(ValueError, match="Key unit drift"):
        keys.remove()


@pytest.mark.parametrize("expires_in,issuer,state", [(3600, ISSUER, "fresh"), (600, ISSUER, "expiring"),
    (-1, ISSUER, "expired"), (3600, "https://other.example.test/", "issuer-mismatch")])
def test_snapshot_state_reports_freshness_without_key_material(tmp_path, expires_in, issuer, state):
    path = tmp_path / "keys.json"
    path.write_text(snapshot(expires_in, issuer))
    result = keys.snapshot_state({"jwks_file": str(path), "issuer_url": ISSUER, "jwks_url": JWKS})
    assert result["state"] == state and "keys" not in result
    assert keys.snapshot_state({"jwks_file": str(tmp_path / "missing"), "issuer_url": ISSUER, "jwks_url": JWKS})["state"] == "unreadable"


def test_serving_unit_bind_is_added_once_to_the_existing_read_only_line():
    text = (stage.TEMPLATES / "tradejournal-advisor-mcp.service").read_text()
    changed = keys.serving_unit(text)
    assert changed.count(str(keys.KEYS)) == 1 and len(changed.splitlines()) == len(text.splitlines())
    with pytest.raises(ValueError):
        keys.serving_unit(changed)


def test_key_units_are_disabled_templates_scoped_to_public_snapshot():
    service = (stage.TEMPLATES / "tradejournal-advisor-keys.service").read_text()
    assert "User=tj-advisor-keys\nGroup=tj-advisor\n" in service
    assert "ReadWritePaths=/var/lib/tradejournal-advisor-v2-keys\n" in service
    assert "Requires=tradejournal-advisor-keys-network.service" in service
    for hidden in ("/etc/tradejournal-advisor-v2/advisor", "/var/lib/tradejournal-advisor-v2 ", "/run/tradejournal-advisor-v2 ",
            "/etc/tradejournal-journal-real", "/etc/tradejournal "):
        assert "-" + hidden in service
    network = (stage.TEMPLATES / "tradejournal-advisor-keys-network.service").read_text()
    assert "ExecStop=/usr/sbin/nft delete table inet tj_advisor_keys" in network
    assert not any("flush" in line for line in network.splitlines() if line.startswith("Exec"))
    for name in keys.KEY_UNITS[:2]:
        assert "[Install]" not in (stage.TEMPLATES / name).read_text()


def test_key_policy_only_names_the_publisher_uid():
    from journal_coach_network import key_policy
    policy = key_policy(304, ["127.0.0.53"], ["15.204.255.2"])
    assert policy.startswith("table inet tj_advisor_keys {")
    assert {line.split()[2] for line in policy.splitlines() if "skuid" in line} == {"304"}
    assert "15.204.255.2" in policy and "127.0.0.53" in policy


def test_real_record_paths_agree():
    assert trial_tests.trial.ROOT  # Loaded module, unpatched constants below.
    assert base.load("advisor_trial_control").KEYS_RECORD == base.load("advisor_keys_control").RUNTIME / keys.RECORD_NAME


@pytest.mark.parametrize("leaf", ["symlink", "fifo", "foreign-owner"])
def test_remove_never_follows_publisher_controlled_snapshot(prepared, tmp_path, monkeypatch, leaf):
    key_bundle, _ = installed_trial(prepared, tmp_path, monkeypatch)
    record = install(key_bundle)
    snapshot_path = Path(record["snapshot"])
    secret = tmp_path / "backend.env"
    secret.write_text("DATABASE_URL=postgres://secret\n")
    snapshot_path.unlink()
    if leaf == "symlink":
        snapshot_path.symlink_to(secret)
    elif leaf == "fifo":
        os.mkfifo(snapshot_path)
    else:
        snapshot_path.write_text(snapshot())
        record = json.loads(keys.record_path().read_text())
        trial.write_private(keys.record_path(), {**record, "key_uid": os.getuid() + 1})
        monkeypatch.setattr(keys.pwd, "getpwnam", lambda name, lookup=keys.pwd.getpwnam: SimpleNamespace(
            pw_name=name, pw_uid=os.getuid() + 1, pw_gid=280, pw_shell="/usr/sbin/nologin") if name == keys.ACCOUNT else lookup(name))
    original = trial.CONFIG / "advisor/public-keys.json"
    before = original.read_bytes()
    config_before = (trial.CONFIG / "advisor/config.json").read_bytes()
    with pytest.raises((ValueError, OSError)):
        keys.remove()
    assert original.read_bytes() == before and b"secret" not in original.read_bytes()
    assert (trial.CONFIG / "advisor/config.json").read_bytes() == config_before
    if leaf != "foreign-owner":  # check() never follows or blocks on the leaf either.
        assert keys.check()["keys"]["state"] == "unreadable"


def test_remove_verifies_preserved_files_before_any_write_and_stays_retryable(prepared, tmp_path, monkeypatch):
    key_bundle, _ = installed_trial(prepared, tmp_path, monkeypatch)
    install(key_bundle)
    saved = keys.RUNTIME / "previous" / keys.SERVING[1]
    good = saved.read_bytes()
    watched = [trial.CONFIG / "advisor/config.json", trial.CONFIG / "advisor/public-keys.json", trial.RECORD,
        *[old.UNIT_DIR / n for n in (*keys.SERVING, *keys.KEY_UNITS)]]
    before = {path: path.read_bytes() for path in watched}
    saved.write_bytes(good + b"# drift\n")
    with pytest.raises(ValueError, match="Preserved serving unit changed"):
        keys.remove()
    assert all(path.read_bytes() == value for path, value in before.items())
    keys.installed()
    saved.write_bytes(good)
    keys.remove()
    trial.installed()


def test_remove_retries_after_failure_between_unit_restores(prepared, tmp_path, monkeypatch):
    key_bundle, _ = installed_trial(prepared, tmp_path, monkeypatch)
    install(key_bundle)
    replace = keys.os.replace
    target = old.UNIT_DIR / keys.SERVING[1]
    def fail(source, destination):
        if Path(destination) == target:
            raise OSError("Controlled unit restore failure")
        return replace(source, destination)
    monkeypatch.setattr(keys.os, "replace", fail)
    with pytest.raises(OSError, match="Controlled"):
        keys.remove()
    trial.installed()  # Record matches the one restored unit.
    keys.installed()
    monkeypatch.setattr(keys.os, "replace", replace)
    keys.remove()
    trial.installed()
    trial.rollback()


def test_remove_resumes_when_interrupted_after_config_switch(prepared, tmp_path, monkeypatch):
    key_bundle, _ = installed_trial(prepared, tmp_path, monkeypatch)
    install(key_bundle)
    unlink = Path.unlink
    def fail(path, *args, **kwargs):
        if path.name == keys.KEY_UNITS[0]:
            raise OSError("Controlled interruption after config switch")
        return unlink(path, *args, **kwargs)
    monkeypatch.setattr(Path, "unlink", fail)
    with pytest.raises(OSError, match="Controlled"):
        keys.remove()
    monkeypatch.setattr(Path, "unlink", unlink)
    keys.remove()
    assert not keys.record_path().exists()
    assert not any((old.UNIT_DIR / name).exists() for name in keys.KEY_UNITS)
    trial.rollback()
