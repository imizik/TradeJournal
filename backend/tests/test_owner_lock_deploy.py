"""The owner lock's server setup: the operator script, the units and the deploy health check."""
import base64
import importlib.util
import json
from pathlib import Path

from argon2 import PasswordHasher
import pytest

from app.engine import access, owner_lock

ROOT = Path(__file__).resolve().parents[2]


def load(name):
    spec = importlib.util.spec_from_file_location(f"owner_lock_{name}", ROOT / "deploy" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def script(tmp_path, monkeypatch):
    module = load("owner_lock_config")
    restarts = []
    monkeypatch.setattr(module.subprocess, "run", lambda command, check: restarts.append(command))
    monkeypatch.setattr(module, "HASHER", PasswordHasher(time_cost=1, memory_cost=8, parallelism=1))
    module.restarts = restarts
    module.run = lambda *args: module.main(["--config-dir", str(tmp_path), *args])
    module.file = tmp_path / "owner-lock.env"
    return module


def values(path):
    return dict(line.split("=", 1) for line in path.read_text().splitlines() if line and not line.startswith("#"))


def test_hashing_matches_what_the_api_verifies():
    module = load("owner_lock_config")
    assert (module.HASHER.time_cost, module.HASHER.memory_cost, module.HASHER.parallelism) == (
        access.HASHER.time_cost, access.HASHER.memory_cost, access.HASHER.parallelism)


def test_passphrase_is_printed_once_and_only_its_hash_is_stored(script, capsys, monkeypatch):
    assert script.run("passphrase") == 0
    printed = capsys.readouterr().out
    passphrase = next(line.strip() for line in printed.splitlines() if line.startswith("    ") and line.strip())
    assert len(passphrase) == 35 and passphrase.count("-") == 5
    stored = values(script.file)
    assert passphrase not in script.file.read_text()
    assert script.file.stat().st_mode & 0o777 == 0o600
    assert stored["TJ_OWNER_LOCK"] == "off" and len(stored["TJ_OWNER_LOCK_LOCAL_KEY"]) >= 32
    assert "$" not in stored["TJ_OWNER_LOCK_PASSPHRASE_HASH"]
    # The API accepts exactly that passphrase from the stored value.
    monkeypatch.setenv("TJ_OWNER_LOCK_PASSPHRASE_HASH", stored["TJ_OWNER_LOCK_PASSPHRASE_HASH"])
    decoded = owner_lock._stored_hash()
    assert decoded and script.HASHER.verify(decoded, passphrase)
    assert script.restarts == []  # the lock is off: nothing to restart


def test_modes_need_a_passphrase_and_restart_the_app(script, capsys):
    assert script.run("mode", "on") == 1 and not script.file.exists()
    assert script.run("passphrase") == 0
    key = values(script.file)["TJ_OWNER_LOCK_LOCAL_KEY"]
    assert script.run("mode", "report") == 0 and values(script.file)["TJ_OWNER_LOCK"] == "report"
    assert script.run("mode", "on") == 0 and values(script.file)["TJ_OWNER_LOCK"] == "on"
    assert script.restarts == [["systemctl", "restart", "tradejournal-api.service", "tradejournal-frontend.service"]] * 2
    first_hash = values(script.file)["TJ_OWNER_LOCK_PASSPHRASE_HASH"]
    assert script.run("passphrase") == 0  # a new passphrase while on restarts so old sessions end now
    assert len(script.restarts) == 3 and values(script.file)["TJ_OWNER_LOCK_PASSPHRASE_HASH"] != first_hash
    assert values(script.file)["TJ_OWNER_LOCK_LOCAL_KEY"] == key and values(script.file)["TJ_OWNER_LOCK"] == "on"
    assert script.run("--no-restart", "mode", "off") == 0 and len(script.restarts) == 3
    assert values(script.file)["TJ_OWNER_LOCK"] == "off"
    capsys.readouterr()
    assert script.run("status") == 0
    assert capsys.readouterr().out.splitlines()[:3] == ["Lock: off", "Passphrase: set", "Server key for the deploy check: set"]


def test_real_config_directory_needs_root(monkeypatch):
    module = load("owner_lock_config")
    monkeypatch.setattr(module.os, "geteuid", lambda: 501)
    assert module.main(["status"]) == 2


def test_both_app_units_load_the_lock_file_last(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "deploy"))
    api = (ROOT / "deploy/systemd/tradejournal-api.service").read_text()
    frontend = (ROOT / "deploy/systemd/tradejournal-frontend.service").read_text()
    line = "EnvironmentFile=-/etc/tradejournal/owner-lock.env"
    assert line in api and line in frontend
    assert api.rindex("EnvironmentFile=") == api.index(line) and frontend.rindex("EnvironmentFile=") == frontend.index(line)
    assert "owner-lock.env" in load("backup").OPTIONAL_CONFIG_FILES


def test_deploy_health_check_presents_the_server_key(tmp_path, monkeypatch):
    control = load("control")
    monkeypatch.setattr(control, "CONFIG", tmp_path)
    assert control._lock_headers() == {}
    (tmp_path / "owner-lock.env").write_text("TJ_OWNER_LOCK=on\nTJ_OWNER_LOCK_LOCAL_KEY=" + "k" * 43 + "\n")
    assert control._lock_headers() == {"x-tj-lock-local": "k" * 43}
    seen = []

    class Response:
        def __init__(self, body):
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self, *_):
            return json.dumps(self.body).encode()

    def urlopen(request, timeout):
        url = request.full_url
        seen.append((url, request.headers.get("X-tj-lock-local")))
        if url.endswith("deployment.json"):
            return Response({"release_id": "r1"})
        if url.endswith("health"):
            return Response({"environment": {"identity": "db"}, "release": "r1"})
        return Response({})

    monkeypatch.setattr(control.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(control.json, "load", lambda response: json.loads(response.read()))
    control.health(Path("/opt/tradejournal/releases/r1"), "db")
    frontend = [key for url, key in seen if ":3000/" in url]
    assert len(frontend) == 3 and set(frontend) == {"k" * 43}
    assert [key for url, key in seen if ":8080/" in url] == [None]


def test_stored_hash_round_trip_without_padding(monkeypatch):
    encoded = base64.urlsafe_b64encode(b"$argon2id$v=19$m=8,t=1,p=1$c2FsdHNhbHQ$aGFzaA").decode().rstrip("=")
    monkeypatch.setenv("TJ_OWNER_LOCK_PASSPHRASE_HASH", encoded)
    assert owner_lock._stored_hash() == "$argon2id$v=19$m=8,t=1,p=1$c2FsdHNhbHQ$aGFzaA"
