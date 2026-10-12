"""Exercise the disabled pre-trade check install in real systemd on disposable CI.

Runs as root only on the dedicated GitHub Ubuntu runner. Generated signing
keys, invented provider credentials and invented feature rows only. A
smoke-only drop-in denies the service all IP traffic, so no provider, issuer
or production service is ever contacted; the UID network policy is proven
separately with probes against the runner's own Postgres port.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import uuid

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "deploy"))
import check_control as control  # noqa: E402

RESOURCE = "https://check.example.test/check/mcp"
ISSUER = "https://identity.example.test/"
JWKS_URL = ISSUER + ".well-known/jwks.json"
CLIENT = "check-smoke-client"
SUBJECT = "check-smoke-subject"
DROPIN = control.UNIT_DIR / "tradejournal-check.service.d"
PROBE_UNITS = [f"check-egress-probe-{os.getpid()}-{n}.service" for n in range(3)]
ADMIN_PATH = "/usr/sbin:/usr/bin:/sbin:/bin"


def run(*args, check=True, **kwargs):
    result = subprocess.run([str(a) for a in args], capture_output=True, check=False, **kwargs)
    if check and result.returncode:
        sys.stderr.write(result.stdout.decode(errors="replace"))
        sys.stderr.write(result.stderr.decode(errors="replace"))
        result.check_returncode()
    return result


def guard():
    if (os.geteuid() != 0 or os.environ.get("GITHUB_ACTIONS") != "true"
            or os.environ.get("TJ_DISPOSABLE_RUNNER") != "1"):
        raise ValueError("Check native smoke only runs as root on explicitly disposable CI")
    for path in (control.ROOT, control.CONFIG, control.STATE, control.KEYS, control.FEATURES, control.RUN,
            control.OWNER_RUN, DROPIN,
            *[control.UNIT_DIR / u for u in control.UNITS]):
        if path.exists() or path.is_symlink():
            raise ValueError("Refuse a pre-existing check native-smoke resource: " + str(path))
    if Path("/var/cache/tradejournal-check").exists():
        raise ValueError("Refuse a pre-existing check cache directory")
    for name in (control.GROUP, *control.ACCOUNTS.values(), control.OWNER_WEB):
        for database in ("passwd", "group"):
            if run("getent", database, name, check=False).returncode == 0:
                raise ValueError("Refuse a pre-existing check identity: " + name)
    if run("nft", "list", "table", "inet", "tj_check", check=False).returncode == 0:
        raise ValueError("Refuse a pre-existing tj_check nftables table")


def b64(number):
    return base64.urlsafe_b64encode(number.to_bytes((number.bit_length() + 7) // 8, "big")).rstrip(b"=").decode()


def owned(path, body, owner, mode=0o640):
    path.write_bytes(body)
    path.chmod(mode)
    run("chown", owner, path)


def egress(account, port):
    """True when this UID can open TCP to the runner's own loopback port."""
    script = ("import socket,sys\ns=socket.socket();s.settimeout(3)\n"
        f"sys.exit(0 if s.connect_ex(('127.0.0.1',{port}))==0 else 1)")
    unit = PROBE_UNITS[0 if account == "tj-check" else 1]
    result = run("systemd-run", f"--unit={unit}", "--wait", "--pipe", "--collect", "--property=Type=oneshot",
        f"--property=User={account}", f"--property=Group={control.GROUP}", "/usr/bin/python3.12", "-c", script, check=False)
    return result.returncode == 0


def owner_get(path, account):
    """GET over the owner socket as a real UID; the kernel supplies the peer."""
    script = ("import socket,sys\ns=socket.socket(socket.AF_UNIX);s.settimeout(10)\n"
        f"s.connect({str(control.OWNER_RUN / 'owner.sock')!r})\n"
        f"s.sendall(b'GET {path} HTTP/1.1\\r\\nHost: owner\\r\\nConnection: close\\r\\n\\r\\n')\n"
        "b=b''\nwhile (c:=s.recv(65536)): b+=c\nsys.stdout.write(b.decode())")
    result = run("systemd-run", f"--unit={PROBE_UNITS[2]}", "--wait", "--pipe", "--collect", "--property=Type=oneshot",
        f"--property=User={account}", "/usr/bin/python3.12", "-c", script, check=False)
    if result.returncode:
        return None, result.stderr.decode(errors="replace")
    head, _, body = result.stdout.decode().partition("\r\n\r\n")
    return int(head.split()[1]), body


def exercise(archive, scratch):
    import httpx
    import jwt
    from cryptography.hazmat.primitives.asymmetric import rsa

    sys.path.insert(0, str(REPO / "backend"))
    import pretrade_features

    wheels = scratch / "wheels"
    wheels.mkdir(mode=0o700)
    with tarfile.open(archive) as package:
        for entry in package.getmembers():
            if entry.isfile() and "/wheels/" in entry.name and entry.name.endswith(".whl"):
                (wheels / Path(entry.name).name).write_bytes(package.extractfile(entry).read())
    bundle = scratch / "bundle"
    # The private owner frontend identity the owner reader admits (the advisor trial's).
    run("useradd", "--system", "--user-group", "--no-create-home", "--shell", "/usr/sbin/nologin", control.OWNER_WEB)
    control.stage(bundle, wheels=wheels)
    resolvers = [line.split()[1] for line in Path("/etc/resolv.conf").read_text().splitlines()
        if line.startswith("nameserver ")]
    host_ips = run("hostname", "-I").stdout.decode().split()
    record = control.install(bundle, control.digest(bundle / "manifest.json"), dns_servers=resolvers, host_ips=host_ips)
    for unit in control.UNITS:
        assert run("systemctl", "is-active", "--quiet", unit, check=False).returncode != 0, unit
        assert run("systemctl", "is-enabled", unit, check=False).stdout.strip() in (b"static", b"disabled"), unit
    assert not control.RUN.exists() and not (control.CONFIG / "alpaca-key-id").exists()
    health = control.check()
    assert not any(health["active"].values()) and not any(health["credentials_present"].values())
    print("PASS: disabled install; nothing active/enabled; no credentials; record " + record["format"])

    # UID-only egress policy, proven against the runner's own Postgres.
    run("systemctl", "start", "tradejournal-check-network.service")
    assert control.check()["network_policy_loaded"]
    assert not egress("tj-check", 5432), "check service UID reached loopback Postgres"
    assert egress("tj-check-features", 5432), "feature publisher UID could not reach local Postgres"
    print("PASS: nftables UID policy denies loopback to the service UID and allows only local Postgres to the publisher")

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    numbers = key.public_key().public_numbers()
    now = int(time.time())
    owned(control.KEYS / "public-keys.json", json.dumps({"issuer_url": ISSUER, "jwks_url": JWKS_URL,
        "fetched_at": now, "expires_at": now + 3600, "keys": [{"kid": "check-smoke", "kty": "RSA", "use": "sig",
        "alg": "RS256", "n": b64(numbers.n), "e": b64(numbers.e)}]}).encode(), "tj-check-keys:tj-check")
    rows = [{"closed_at": f"2026-09-1{i % 4}T10:0{i}:00", "opened_at": f"2026-09-1{i % 4}T09:4{i}:00",
        "underlying": "SPY", "side": "stock", "time_bucket": "open", "vwap_bucket": "above", "trend_aligned": True,
        "chase": False, "late_move": False, "rvol_bucket": "normal", "dte_bucket": None, "realized_pnl": 10.0 - i,
        "pnl_pct": 1.0, "mfe_pct": 0.3, "mae_pct": -0.2, "giveback_pct": 0.1, "source_fill_key": f"{i:064x}"}
        for i in range(9)]
    pretrade_features.publish(rows, control.FEATURES / "current.json")
    for path in control.FEATURES.iterdir():
        run("chown", "tj-check-features:tj-check", path)
    config = json.loads((control.CONFIG / "config.json").read_text())
    config.update({"enabled": True, "issuer_url": ISSUER, "resource_url": RESOURCE, "jwks_url": JWKS_URL,
        "client_id": CLIENT, "profiles": [{"subject": SUBJECT, "id": "check_" + str(uuid.uuid4()), "enabled": True}]})
    owned(control.CONFIG / "config.json", json.dumps(config).encode(), "root:tj-check")
    for name in ("alpaca-key-id", "alpaca-secret-key"):
        owned(control.CONFIG / name, b"invented-not-a-provider-key\n", "root:root", 0o600)
    DROPIN.mkdir()
    (DROPIN / "smoke-no-ip.conf").write_text("[Service]\nIPAddressDeny=any\n")
    run("systemctl", "daemon-reload")
    run("systemctl", "start", "tradejournal-check.socket")
    run("systemctl", "start", "tradejournal-check.service")
    socket_path = control.RUN / "mcp.sock"
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline and not socket_path.exists():
        time.sleep(0.1)
    pid = int(run("systemctl", "show", "--property=MainPID", "--value", "tradejournal-check.service").stdout)
    status = Path(f"/proc/{pid}/status").read_text()
    uid = next(line for line in status.splitlines() if line.startswith("Uid:")).split()[1]
    assert int(uid) == record["uids"]["service"], "service is not running as its dedicated UID"

    def token(**changes):
        issued = int(time.time())
        # The staged config verifies the Auth0-style "azp" client claim.
        claims = {"iss": ISSUER, "aud": RESOURCE, "sub": SUBJECT, "azp": CLIENT,
            "scope": "check:read check:run check:note", "iat": issued, "exp": issued + 300, **changes}
        return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "check-smoke"})

    def rpc(name, arguments, bearer, method="tools/call"):
        with httpx.Client(transport=httpx.HTTPTransport(uds=str(socket_path)), base_url="http://check.example.test",
                timeout=20, trust_env=False) as client:
            return client.post("/check/mcp", headers={"Accept": "application/json, text/event-stream",
                "Authorization": "Bearer " + bearer}, json={"jsonrpc": "2.0", "id": 1, "method": method,
                "params": {"name": name, "arguments": arguments} if method == "tools/call" else {}})

    def call(name, arguments):
        response = rpc(name, arguments, token())
        assert response.status_code == 200, (name, response.status_code, response.headers.get("www-authenticate"))
        result = response.json()["result"]
        assert not result.get("isError"), result
        return result["structuredContent"]

    listing = rpc("", {}, token(), "tools/list")
    assert listing.status_code == 200, (listing.status_code, listing.headers.get("www-authenticate"))
    tools = listing.json()["result"]["tools"]
    assert rpc("pre_trade_check", {}, token(azp="other-client")).status_code == 401
    assert {t["name"] for t in tools} == {"pre_trade_check", "attach_model_verdict", "review_checks", "position_check", "get_notes"}
    assert rpc("pre_trade_check", {}, token(aud="https://check.example.test/mcp")).status_code == 401
    assert rpc("pre_trade_check", {}, token(scope="journal:read")).status_code == 403
    operation = str(uuid.uuid4())
    idea = {"ticker": "SPY", "side": "long", "instrument": "stock", "horizon": "intraday", "operation_id": operation}
    first = call("pre_trade_check", idea)
    assert first["verdict"] == "insufficient_data" and first["live"]["price"] is None
    assert first["history"]["cohorts"][1]["trades"] == 9 and "source_fill_keys" not in first["history"]
    assert first["timings_ms"]["total"] < 8000, first["timings_ms"]
    note = call("attach_model_verdict", {"check_id": first["check_id"], "verdict": "wait", "summary": "Smoke note."})
    assert note["rules_verdict"] == "insufficient_data"
    run("systemctl", "restart", "tradejournal-check.service")
    replay = call("pre_trade_check", idea)
    assert replay["replayed"] and replay["receipt"] == first["receipt"]
    ledger = control.STATE / "ledger.db"
    assert ledger.stat().st_uid == record["uids"]["service"] and ledger.stat().st_mode & 0o077 == 0
    print("PASS: dedicated UID, LoadCredential provider key, own OAuth audience/scopes, provider failure ->"
        " insufficient_data, real feature history, immutable ledger replay across restart, verdict note once."
        f" Server timings {first['timings_ms']}")

    owner = json.loads((control.CONFIG / "owner/config.json").read_text())
    owned(control.CONFIG / "owner/config.json", json.dumps({**owner, "enabled": True}).encode(), "root:tj-check")
    run("systemctl", "start", "tradejournal-check-owner.socket")
    status, body = owner_get("/owner/checks", control.OWNER_WEB)
    assert status == 200, (status, body)
    listing = json.loads(body)
    assert [c["check_id"] for c in listing["checks"]] == [first["check_id"]] and listing["checks"][0]["model_verdict"] == "wait"
    status, body = owner_get("/owner/checks/" + first["check_id"], control.OWNER_WEB)
    assert status == 200 and json.loads(body)["answer"]["verdict"] == "insufficient_data", (status, body)
    assert owner_get("/owner/checks", "tj-check-keys")[0] is None, "another UID reached the owner socket"
    reader_pid = int(run("systemctl", "show", "--property=MainPID", "--value", "tradejournal-check-owner.service").stdout)
    reader_uid = next(line for line in Path(f"/proc/{reader_pid}/status").read_text().splitlines()
        if line.startswith("Uid:")).split()[1]
    assert int(reader_uid) == record["uids"]["service"], "owner reader is not running as the check UID"
    print("PASS: owner reader lists and reopens the saved check for the owner frontend UID only")

    control.stop()
    shutil.rmtree(DROPIN)
    removed = control.remove()
    assert ledger.exists() and (control.FEATURES / "current.json").exists()
    assert not any((control.UNIT_DIR / unit).exists() for unit in control.UNITS)
    print("PASS: stop and remove retire every unit and preserve the ledger, keys and features: "
        + json.dumps(removed["preserved"]))


def cleanup():
    run("systemctl", "stop", "tradejournal-check.socket", "tradejournal-check.service", "tradejournal-check-owner.socket",
        "tradejournal-check-owner.service", *PROBE_UNITS, check=False)
    run("systemctl", "stop", "tradejournal-check-network.service", check=False)
    run("nft", "delete", "table", "inet", "tj_check", check=False)
    for name in control.UNITS:
        (control.UNIT_DIR / name).unlink(missing_ok=True)
    shutil.rmtree(DROPIN, ignore_errors=True)
    run("systemctl", "daemon-reload", check=False)
    for path in (control.ROOT, control.CONFIG, control.STATE, control.KEYS, control.FEATURES, control.RUN,
            control.OWNER_RUN, Path("/var/cache/tradejournal-check")):
        shutil.rmtree(path, ignore_errors=True)
    for account in control.ACCOUNTS.values():
        run("userdel", account, check=False)
    run("groupdel", control.GROUP, check=False)
    run("userdel", control.OWNER_WEB, check=False)
    run("groupdel", control.OWNER_WEB, check=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--inner", action="store_true")
    args = parser.parse_args()
    guard()
    if not args.inner:
        python = Path("/opt/tradejournal/current/backend/.venv/bin/python")
        if not python.is_file():
            raise ValueError("Existing disposable package smoke runtime required")
        result = run(python, "-B", __file__, args.archive.resolve(), "--inner", env={"PATH": ADMIN_PATH,
            "GITHUB_ACTIONS": "true", "TJ_DISPOSABLE_RUNNER": "1", "PYTHON_DOTENV_DISABLED": "1"})
        sys.stdout.write(result.stdout.decode())
        return
    try:
        with tempfile.TemporaryDirectory(prefix="check-native-ci-") as directory:
            exercise(args.archive.resolve(), Path(directory))
    except BaseException:
        for unit in control.UNITS:
            sys.stderr.write(run("journalctl", "-u", unit, "--no-pager", "-n", "60", check=False).stdout.decode(errors="replace"))
        raise
    finally:
        cleanup()


if __name__ == "__main__":
    main()
