"""Advisor-specific native proof, ONLY on the disposable Ubuntu CI runner.

Generated keys/invented SQLite, no issuer/provider/Jo calls. This smoke is not a
retained-server installer; operator installation lives in advisor_mcp_control.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import shutil
import ssl
import subprocess
import sys
import tarfile
import tempfile
import time
import uuid
from datetime import datetime, timedelta, timezone

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "deploy"))
import advisor_mcp_control as control  # noqa: E402
import advisor_mcp_stage as staging  # noqa: E402

PROXY = "tradejournal-advisor-ci-proxy.service"
RESOURCE = "https://127.0.0.1:18810/advisor/mcp"
ISSUER = "https://127.0.0.1:18811/"
MARKER = Path("/opt/tradejournal/.advisor-ci-public-read-control")


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
        raise ValueError("Advisor native smoke only runs as root on explicitly disposable CI")
    for path in (control.ROOT, control.CONFIG, control.STATE, control.RUN, MARKER,
                 control.UNIT_DIR / PROXY, *[control.UNIT_DIR / u for u in control.UNITS],
                 *[control.UNIT_DIR / (u + ".d") for u in (*control.UNITS, PROXY)]):
        if path.exists() or path.is_symlink():
            raise ValueError("Refuse a pre-existing advisor native-smoke resource")
    for account in (control.ACCOUNT, control.BACKEND_ACCOUNT):
        for database in ("passwd", "group"):
            if run("getent", database, account, check=False).returncode == 0:
                raise ValueError("Refuse a pre-existing advisor native-smoke identity")
    for unit in (*control.UNITS, PROXY):
        if run("systemctl", "cat", unit, check=False).returncode == 0:
            raise ValueError("Refuse a pre-existing loaded advisor unit")


def write(path, value):
    temporary = path.with_suffix(".new")
    temporary.write_text(json.dumps(value))
    temporary.chmod(0o640)
    run("chown", "root:tj-advisor", temporary)
    temporary.replace(path)


def exercise(archive, scratch):
    import httpx
    import jwt
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    from sqlmodel import Session, create_engine, select

    sys.path.insert(0, str(REPO / "backend"))
    from app.engine import advisor_shadow as service
    from app.models import DecisionEvent, DecisionRecord
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    wheels = scratch / "wheels"
    wheels.mkdir(mode=0o700)
    with tarfile.open(archive) as package:
        for entry in package.getmembers():
            if entry.isfile() and "/wheels/" in entry.name and entry.name.endswith(".whl"):
                target = wheels / Path(entry.name).name
                if target.exists():
                    raise ValueError("Duplicate offline wheel")
                target.write_bytes(package.extractfile(entry).read())
    bundle = scratch / "bundle"
    staging.stage(bundle, wheels=wheels)
    staging.validate(bundle)
    record = control.install(bundle, approve_install=staging.digest(bundle / "manifest.json"))
    for unit in control.UNITS:
        assert run("systemctl", "is-active", "--quiet", unit, check=False).returncode != 0
        assert run("systemctl", "is-enabled", unit, check=False).stdout.strip() in (b"static", b"disabled")
    assert not control.RUN.exists(), "Install activated a socket"
    try:
        control.activate(approve_activation="unapproved")
    except ValueError:
        pass
    else:
        raise AssertionError("Disabled installation could be activated")

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    def b64(number):
        return base64.urlsafe_b64encode(number.to_bytes((number.bit_length() + 7) // 8, "big")).rstrip(b"=").decode()
    numbers = key.public_key().public_numbers()
    now = int(time.time())
    config = json.loads((control.CONFIG / "config.json").read_text())
    config.update(enabled=True, issuer_url=ISSUER, jwks_url=ISSUER + "keys", resource_url=RESOURCE, client_id="advisor-ci-client")
    config["profiles"][0].update(enabled=True, subject="advisor-ci-subject")
    keys = {"issuer_url": ISSUER, "jwks_url": ISSUER + "keys", "fetched_at": now,
        "expires_at": now + 3600, "keys": [{"kid": "advisor-ci", "kty": "RSA", "alg": "RS256", "use": "sig",
            "n": b64(numbers.n), "e": b64(numbers.e)}]}
    write(control.CONFIG / "config.json", config)
    write(control.CONFIG / "public-keys.json", keys)
    engine = create_engine("sqlite:///" + str(control.STATE / "fixture.db"))
    # Pin even the unused owner dependency engine to this invented database;
    # the actual owner route overrides sessions below. Never read default data.
    os.environ["DATABASE_URL"] = str(engine.url)
    os.environ["MIGRATION_DATABASE_URL"] = str(engine.url)
    from app.database import get_session
    from app.routers.advisor_shadow import router
    owner_app = FastAPI()
    owner_app.include_router(router, prefix="/advisor-shadow")
    def owner_session():
        with Session(engine) as db:
            yield db
    owner_app.dependency_overrides[get_session] = owner_session
    def owner_record():
        with TestClient(owner_app) as owner:
            response = owner.get(f"/advisor-shadow/runs/{run_id}")
            assert response.status_code == 200
            return response.json()["advisor"]
    assignment = uuid.UUID(config["profiles"][0]["assignment_id"])
    run_id = uuid.UUID(config["profiles"][0]["run_id"])
    with Session(engine) as db:
        service.set_enabled(db, assignment, True)
        original_export = service.owner_view(db, run_id)["advisor"]["export"]
    identity = control.activation_identity()
    approved = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    control.activate(approve_activation=approved)

    # Extra positive/negative controls run via ExecStartPre inside the exact
    # installed service sandbox. These disposable drop-ins are removed before
    # controller stop/rollback; they never ship or loosen a restriction.
    MARKER.write_text("invented readable host marker")
    MARKER.chmod(0o644)
    for role in ("adapter", "backend"):
        probe = control.CONFIG / ("native-boundary-" + role + ".py")
        probe.write_text('''import errno,os,socket,sys
from pathlib import Path
assert os.geteuid()!=0
positive=sys.argv[1:]==["positive"]
for family in (socket.AF_INET,socket.AF_INET6):
    try:
        s=socket.socket(family,socket.SOCK_STREAM)
    except OSError as e:
        assert not positive and e.errno in (errno.EPERM,errno.EACCES,errno.EAFNOSUPPORT)
    else:
        s.close(); assert positive,"IP socket permitted"
marker=Path("''' + str(MARKER) + '''")
if positive:
    assert marker.read_text()
else:
    try: marker.read_bytes()
    except OSError as e: assert e.errno in (errno.ENOENT,errno.EACCES,errno.EPERM)
    else: raise AssertionError("production mount readable")
    runtime=Path("/opt/tradejournal-advisor/"+("adapter" if "adapter" in __file__ else "backend")+"/cloud_mcp_advisor.py")
    for p in (Path("/etc/tradejournal-advisor/config.json"),runtime):
        try:
            with p.open("ab"): pass
        except OSError as e: assert e.errno in (errno.EROFS,errno.EACCES,errno.EPERM)
        else: raise AssertionError("immutable config/runtime writable")
    state=Path("/var/lib/tradejournal-advisor/fixture.db")
    if "adapter" in __file__:
        assert not state.parent.exists(),"adapter state directory mounted"
        try: state.read_bytes()
        except OSError as e: assert e.errno in (errno.ENOENT,errno.EACCES,errno.EPERM)
        else: raise AssertionError("adapter reads fixture database")
    else:
        assert state.read_bytes() and os.access(state,os.W_OK)
print("advisor native boundary positive" if positive else "advisor native boundary denied IP/private mounts/config writes")
''')
        probe.chmod(0o644)
        account = control.ACCOUNT if role == "adapter" else control.BACKEND_ACCOUNT
        python = control.ROOT / role / ".venv/bin/python"
        run("runuser", "-u", account, "--", python, "-B", probe, "positive")
        unit = "tradejournal-advisor-mcp.service" if role == "adapter" else "tradejournal-advisor-backend.service"
        dropin = control.UNIT_DIR / (unit + ".d")
        dropin.mkdir()
        (dropin / "native-ci.conf").write_text(f"[Service]\nExecStartPre={python} -B {probe}\n")
    run("systemctl", "daemon-reload")
    run("systemctl", "restart", *control.SERVICES)
    for unit in control.SERVICES:
        pid = int(run("systemctl", "show", "--property=MainPID", "--value", unit).stdout)
        assert pid > 0
        account = control.ACCOUNT if "-mcp." in unit else control.BACKEND_ACCOUNT
        uid = int(run("id", "-u", account).stdout)
        status = Path(f"/proc/{pid}/status").read_text()
        observed = next(line for line in status.splitlines() if line.startswith("Uid:")).split()[1:]
        print(f"Advisor native identity: unit={unit} pid={pid} expected_uid={uid} observed_uids={observed}", flush=True)
        assert observed == [str(uid)] * 4
        mounts = Path(f"/proc/{pid}/mountinfo").read_text()
        assert (str(control.STATE) in mounts) == (account == control.BACKEND_ACCOUNT)
        assert Path(f"/proc/{pid}/ns/net").stat().st_ino != Path("/proc/1/ns/net").stat().st_ino
        assert run("systemctl", "show", "--property=RestrictAddressFamilies", "--value", unit).stdout.strip() == b"AF_UNIX"
    assert (control.RUN / "mcp.sock").stat().st_mode & 0o777 == 0o660
    assert (control.RUN / "backend.sock").stat().st_mode & 0o777 == 0o660
    assert (control.STATE / "fixture.db").stat().st_mode & 0o777 == 0o600
    assert (control.STATE / "fixture.db").stat().st_uid == int(run("id", "-u", control.BACKEND_ACCOUNT).stdout)
    assert (control.CONFIG / "config.json").stat().st_mode & 0o777 == 0o640

    tls = scratch / "tls"
    tls.mkdir(mode=0o755)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "advisor disposable CI")])
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(datetime.now(timezone.utc) - timedelta(minutes=1))
        .not_valid_after(datetime.now(timezone.utc) + timedelta(hours=1))
        .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), critical=False)
        .sign(key, hashes.SHA256()))
    (tls / "cert.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    (tls / "key.pem").write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    (tls / "key.pem").chmod(0o640)
    run("chown", "root:caddy", tls / "key.pem")
    scratch.chmod(0o755)
    proxy = (REPO / "deploy/cloud-mcp-advisor/Caddyfile.example").read_text().replace("advisor.example.test {", "https://127.0.0.1:18810 {\n    bind 127.0.0.1\n    tls " + str(tls / "cert.pem") + " " + str(tls / "key.pem"))
    caddyfile = scratch / "Caddyfile"
    caddyfile.write_text("{\n    admin off\n    auto_https disable_redirects\n}\n" + proxy)
    run("caddy", "validate", "--config", caddyfile, "--adapter", "caddyfile")
    (control.UNIT_DIR / PROXY).write_text(f"[Service]\nUser=caddy\nGroup=caddy\nExecStart=/usr/bin/caddy run --config {caddyfile} --adapter caddyfile\n")
    run("systemctl", "daemon-reload")
    run("systemctl", "start", PROXY)
    context = ssl.create_default_context(cafile=str(tls / "cert.pem"))
    def token(**changes):
        claims = {"iss": ISSUER, "aud": RESOURCE, "sub": "advisor-ci-subject", "client_id": "advisor-ci-client",
            "scope": "advisor:profile advisor:read advisor:write", "iat": int(time.time()), "exp": int(time.time()) + 300, **changes}
        return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "advisor-ci"})
    with httpx.Client(verify=context, trust_env=False, timeout=10) as client:
        for attempt in range(50):
            try:
                metadata = client.get(RESOURCE.replace("/advisor/mcp", "/.well-known/oauth-protected-resource/advisor/mcp"))
                if metadata.status_code == 200:
                    break
            except httpx.TransportError:
                pass
            time.sleep(0.1)  # Bounded process readiness, not a test retry.
        else:
            raise AssertionError("Advisor proxy did not become ready")
        assert metadata.json()["resource"] == RESOURCE
        assert metadata.json()["scopes_supported"] == ["advisor:profile", "advisor:read", "advisor:write"]
        for path in ("/mcp", "/advisor/mcp/extra", "/health", "/.well-known/oauth-protected-resource", "/journal"):
            assert client.get(RESOURCE.replace("/advisor/mcp", path)).status_code == 404
        def rpc(name, args=None, bearer=None):
            response = client.post(RESOURCE, headers={"Authorization": "Bearer " + (bearer or token()), "Accept": "application/json"},
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args or {}}})
            return response
        assert client.post(RESOURCE, json={}).status_code == 401
        for case, bearer, expected in (("subject", token(sub="owner"), 401),
                ("audience", token(aud="https://journal.invalid/mcp"), 401),
                ("scope", token(scope="journal:read d0:profile"), 403), ("expiry", token(iat=1, exp=2), 401)):
            denied = rpc("get_advisor_request", bearer=bearer)
            print(f"Advisor native token denial: case={case} expected={expected} observed={denied.status_code}", flush=True)
            assert denied.status_code == expected
            assert ('error="insufficient_scope"' if expected == 403 else 'error="invalid_token"') in denied.headers["www-authenticate"]
        listing = client.post(RESOURCE, headers={"Authorization": "Bearer " + token(), "Accept": "application/json"},
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}).json()
        assert {t["name"] for t in listing["result"]["tools"]} == {"get_profile", "get_advisor_request", "save_advisor_answer"}
        read = rpc("get_advisor_request").json()["result"]["structuredContent"]
        assert read["request"] == original_export and read["receipt"] is None
        opp = original_export["packet"]["opportunities"][0]
        fact = opp["price_facts"][0]
        answer = {k: "Invented evidence is insufficient; wait for verified inputs." for k in ("summary", "interpretation", "risks", "conditions", "gaps")}
        answer["references"] = [{"opportunity_id": opp["opportunity_id"], "fact_name": fact["name"]}]
        body = {"packet_sha256": read["request"]["packet_sha256"], "request_sha256": read["request"]["request_sha256"], "answer": answer}
        # Commit then deliberately discard the response, simulating uncertain delivery.
        rpc("save_advisor_answer", body)
        receipt = rpc("get_advisor_request").json()["result"]["structuredContent"]["receipt"]
        assert receipt["submitted_output"]["answer"] == answer and receipt["transport"] == "oauth-mcp"
        assert owner_record()["receipt"] == receipt and owner_record()["export"] == original_export
        assert rpc("save_advisor_answer", body).json()["result"]["structuredContent"]["receipt"] == receipt
        changed = json.loads(json.dumps(body))
        changed["answer"]["summary"] = "Conflicting answer"
        assert rpc("save_advisor_answer", changed).json()["result"]["isError"]
        assert rpc("get_advisor_request", {"run_id": str(uuid.uuid4())}).json()["result"]["isError"]
        transport = httpx.HTTPTransport(uds=str(control.RUN / "backend.sock"), retries=0)
        with httpx.Client(transport=transport, trust_env=False, timeout=10) as backend:
            for path in ("/health", "/journal", "/docs", "/cloud-mcp/practice/runs"):
                assert backend.get("http://backend" + path).status_code == 404
            assert backend.get("http://backend/cloud-mcp/advisor/request").status_code == 401
            for bearer in (token(sub="owner"), token(aud="https://journal.invalid/mcp"), token(scope="d0:profile journal:read"), token(iat=1, exp=2)):
                headers = {"Authorization": "Bearer " + bearer}
                assert backend.get("http://backend/cloud-mcp/advisor/request", headers=headers).status_code == 401
                assert backend.post("http://backend/cloud-mcp/advisor/answer", headers=headers, json=body).status_code == 401
        with Session(engine) as db:
            assert service.owner_view(db, run_id)["advisor"]["receipt"] == receipt
            assert service.owner_view(db, run_id)["advisor"]["export"] == original_export
            assert not db.exec(select(DecisionRecord)).all() and not db.exec(select(DecisionEvent)).all()
        run("systemctl", "restart", *control.SERVICES)
        assert rpc("get_advisor_request").json()["result"]["structuredContent"]["receipt"] == receipt
        assert owner_record()["receipt"] == receipt
        config["profiles"][0]["enabled"] = False
        write(control.CONFIG / "config.json", config)
        assert rpc("get_advisor_request").status_code == 401
        with Session(engine) as db:
            assert service.owner_view(db, run_id)["advisor"]["receipt"] == receipt
        assert owner_record()["receipt"] == receipt
        config["profiles"][0]["enabled"] = True
        write(control.CONFIG / "config.json", config)
        keys["expires_at"] = keys["fetched_at"]
        write(control.CONFIG / "public-keys.json", keys)
        assert rpc("get_advisor_request").status_code == 401
        keys["expires_at"] = keys["fetched_at"] + 3600
        write(control.CONFIG / "public-keys.json", keys)
        with Session(engine) as db:
            service.set_enabled(db, assignment, False)
        denied = rpc("get_advisor_request")
        assert denied.status_code == 200 and denied.json()["result"]["isError"]
        assert rpc("save_advisor_answer", body).json()["result"]["isError"]
        with Session(engine) as db:
            assert service.owner_view(db, run_id)["advisor"]["receipt"] == receipt
    for unit in control.SERVICES:
        shutil.rmtree(control.UNIT_DIR / (unit + ".d"))
    run("systemctl", "daemon-reload")
    before = staging.digest(control.STATE / "fixture.db")
    control.stop()
    assert staging.digest(control.STATE / "fixture.db") == before
    control.rollback()
    assert staging.digest(control.STATE / "fixture.db") == before
    assert all(not (control.UNIT_DIR / u).exists() for u in control.UNITS)
    assert record["original_fixture_sha256"] == staging.digest(bundle / "state/fixture.db")
    engine.dispose()
    print("Advisor native smoke passed: disabled install, distinct UIDs, private mounts/AF_UNIX, exact TLS routes/catalog, independent OAuth, invented cited save/uncertain recovery/retry/conflict, owner equality, restart, expiry/revocation, stop BOTH socket/process pairs and receipt-preserving rollback")


def cleanup():
    run("systemctl", "stop", *control.SOCKETS, check=False)
    run("systemctl", "stop", *control.SERVICES, PROXY, check=False)
    if any(run("systemctl", "is-active", "--quiet", unit, check=False).returncode == 0 for unit in (*control.UNITS, PROXY)):
        raise RuntimeError("Advisor disposable cleanup left an active unit; retaining diagnostics")
    if any((control.RUN / name).exists() for name in ("mcp.sock", "backend.sock")):
        raise RuntimeError("Advisor disposable cleanup left a socket; retaining diagnostics")
    for name in (*control.UNITS, PROXY):
        (control.UNIT_DIR / name).unlink(missing_ok=True)
        shutil.rmtree(control.UNIT_DIR / (name + ".d"), ignore_errors=True)
    run("systemctl", "daemon-reload", check=False)
    for path in (control.ROOT, control.CONFIG, control.STATE, control.RUN):
        shutil.rmtree(path, ignore_errors=True)
    MARKER.unlink(missing_ok=True)
    for account in (control.BACKEND_ACCOUNT, control.ACCOUNT):
        run("userdel", account, check=False)
    run("groupdel", control.ACCOUNT, check=False)


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
        result = run(python, "-B", __file__, args.archive.resolve(), "--inner", env={"PATH": control.ADMIN_PATH,
            "GITHUB_ACTIONS": "true", "TJ_DISPOSABLE_RUNNER": "1", "PYTHON_DOTENV_DISABLED": "1"})
        sys.stdout.write(result.stdout.decode())
        return
    try:
        with tempfile.TemporaryDirectory(prefix="advisor-native-ci-") as directory:
            exercise(args.archive.resolve(), Path(directory))
    except BaseException:
        for unit in (*control.UNITS, PROXY):
            result = run("journalctl", "-u", unit, "--no-pager", "-n", "60", check=False)
            sys.stderr.write(result.stdout.decode(errors="replace"))
        raise
    finally:
        cleanup()


if __name__ == "__main__":
    main()
