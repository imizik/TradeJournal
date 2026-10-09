"""Exercise real Caddy TLS, socket activation and network denial on disposable CI.

No external issuer, model service, production data or actual Dot is contacted.
Run only as root on the dedicated GitHub Ubuntu package runner.
"""
from __future__ import annotations

import base64
import ipaddress
import json
import os
import shutil
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = Path("/opt/tradejournal-d0")
CONFIG = Path("/etc/tradejournal-d0")
SOCKET = "tradejournal-d0-https.socket"
SERVICE = "tradejournal-d0-https.service"
PROXY = "tradejournal-d0-smoke-proxy.service"
USER = "tradejournal-d0"
RESOURCE = "https://127.0.0.1:18788/mcp"
ISSUER = "https://identity.example.test/"


def run(*args):
    return subprocess.run([str(arg) for arg in args], check=True, capture_output=True)


def prepare():
    if any(path.exists() for path in (ROOT, CONFIG)):
        raise ValueError("Refusing to overwrite an existing probe installation")
    for unit in (SOCKET, SERVICE, PROXY):
        if Path("/etc/systemd/system", unit).exists():
            raise ValueError("Refusing to overwrite an existing unit")
    if subprocess.run(["getent", "passwd", USER], check=False, capture_output=True).returncode == 0:
        raise ValueError("Refusing to reuse an existing probe user")
    run("useradd", "--system", "--no-create-home", "--shell", "/usr/sbin/nologin", USER)
    (ROOT / "backend").mkdir(parents=True)
    CONFIG.mkdir(mode=0o750)
    run("chown", f"root:{USER}", CONFIG)
    shutil.copy2(HERE.parents[1] / "backend/cloud_mcp_d0.py", ROOT / "backend/cloud_mcp_d0.py")
    run(sys.executable, "-m", "venv", ROOT / "backend/.venv")
    run(ROOT / "backend/.venv/bin/python", "-m", "pip", "install", "mcp==1.28.1", "PyJWT[crypto]==2.13.0")


def write_json(path, data):
    temporary = path.with_suffix(".new")
    temporary.write_text(json.dumps(data))
    temporary.chmod(0o640)
    run("chown", f"root:{USER}", temporary)
    temporary.replace(path)


def exercise():
    import jwt
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    numbers = key.public_key().public_numbers()
    def b64(value):
        return base64.urlsafe_b64encode(value.to_bytes((value.bit_length() + 7) // 8, "big")).rstrip(b"=").decode()
    now = int(time.time())
    keys = {"issuer_url": ISSUER, "jwks_url": ISSUER + "keys", "fetched_at": now,
        "expires_at": now + 3600, "keys": [{"kid": "smoke", "kty": "RSA", "use": "sig", "alg": "RS256",
        "n": b64(numbers.n), "e": b64(numbers.e)}]}
    config = {"enabled": True, "synthetic_only": True, "issuer_url": ISSUER,
        "jwks_url": ISSUER + "keys", "jwks_file": str(CONFIG / "jwks.json"),
        "resource_url": RESOURCE, "client_id": "smoke-client",
        "profiles": [{"subject": "smoke-subject", "id": "d0_11111111-1111-4111-8111-111111111111", "enabled": True}]}
    write_json(CONFIG / "jwks.json", keys)
    write_json(CONFIG / "config.json", config)
    claims = {"iss": ISSUER, "aud": RESOURCE, "sub": "smoke-subject", "client_id": "smoke-client",
        "scope": "d0:profile", "iat": now, "exp": now + 300}
    token = jwt.encode(claims, key, algorithm="RS256", headers={"kid": "smoke"})

    # This pre-start check runs under the exact service sandbox before D0 starts.
    check = ROOT / "assert_no_network.py"
    check.write_text('''import socket
for family in (socket.AF_INET, socket.AF_INET6):
    try:
        sock = socket.socket(family, socket.SOCK_STREAM)
    except OSError:
        continue
    sock.close()
    raise SystemExit("Network socket creation was permitted")
print("IPv4 and IPv6 socket creation denied in the D0 service sandbox")
''')
    for unit in (SOCKET, SERVICE):
        shutil.copy2(HERE / unit, Path("/etc/systemd/system") / unit)
    dropin = Path("/etc/systemd/system", SERVICE + ".d")
    dropin.mkdir()
    (dropin / "smoke.conf").write_text(f"[Service]\nExecStartPre={ROOT}/backend/.venv/bin/python {check}\n")

    tls = ROOT / "tls"
    tls.mkdir(mode=0o755)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "D0 disposable CI")])
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(datetime.now(timezone.utc) - timedelta(minutes=1))
        .not_valid_after(datetime.now(timezone.utc) + timedelta(hours=1))
        .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), critical=False)
        .sign(key, hashes.SHA256()))
    (tls / "cert.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    (tls / "key.pem").write_bytes(key.private_bytes(serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    (tls / "key.pem").chmod(0o640)
    run("chown", "root:caddy", tls / "key.pem")
    # Use the shipped routing stanza with a local, verified TLS certificate.
    template = (HERE / "Caddyfile.example").read_text()
    site = template[template.index("probe.example {"):].replace("probe.example {",
        f"https://127.0.0.1:18788 {{\n    bind 127.0.0.1\n    tls {tls}/cert.pem {tls}/key.pem", 1)
    caddyfile = ROOT / "Caddyfile"
    caddyfile.write_text("{\n    admin off\n    auto_https off\n}\n" + site)
    run("caddy", "validate", "--config", caddyfile, "--adapter", "caddyfile")
    Path("/etc/systemd/system", PROXY).write_text(f"""[Unit]
Description=Disposable TLS proxy for D0 acceptance
[Service]
User=caddy
Group=caddy
ExecStart=/usr/bin/caddy run --config {caddyfile} --adapter caddyfile
""")
    run("systemctl", "daemon-reload")
    run("systemctl", "start", SOCKET, PROXY)
    context = ssl.create_default_context(cafile=str(tls / "cert.pem"))
    client = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=context))

    def request(path="/mcp", method=None, params=None, bearer=None):
        headers = {"Accept": "application/json"}
        if bearer:
            headers["Authorization"] = "Bearer " + bearer
        body = None
        if method:
            headers["Content-Type"] = "application/json"
            body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}).encode()
        req = urllib.request.Request("https://127.0.0.1:18788" + path, data=body, headers=headers)
        try:
            with client.open(req, timeout=10) as response:
                return response.status, response.read(), response.headers
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read(), exc.headers

    for _ in range(30):
        try:
            status, body, _ = request("/.well-known/oauth-protected-resource/mcp")
            if status == 200:
                break
        except (OSError, urllib.error.URLError):
            pass
        time.sleep(1)
    else:
        raise AssertionError("Socket-activated TLS discovery did not become ready")
    assert json.loads(body)["resource"] == RESOURCE
    run("systemctl", "is-active", "--quiet", SERVICE)
    assert run("systemctl", "show", SERVICE, "--property=PrivateNetwork", "--value").stdout.strip() == b"yes"
    assert run("systemctl", "show", SERVICE, "--property=RestrictAddressFamilies", "--value").stdout.strip() == b"AF_UNIX"
    status, body, headers = request(method="tools/call", params={"name": "get_profile", "arguments": {}})
    assert status == 401 and "WWW-Authenticate" in headers
    assert b"synthetic profile" not in body
    status, body, _ = request(method="initialize", params={"protocolVersion": "2025-11-25",
        "capabilities": {}, "clientInfo": {"name": "CI", "version": "1"}}, bearer=token)
    assert status == 200 and json.loads(body)["result"]["protocolVersion"] == "2025-11-25"
    status, body, _ = request(method="tools/list", bearer=token)
    assert status == 200 and [item["name"] for item in json.loads(body)["result"]["tools"]] == ["get_profile"]
    status, body, _ = request(method="tools/call", params={"name": "get_profile", "arguments": {}}, bearer=token)
    assert status == 200 and config["profiles"][0]["id"].encode() in body
    status, body, _ = request(method="tools/call", params={"name": "analyze", "arguments": {}}, bearer=token)
    result = json.loads(body)
    assert status == 200 and (result.get("error") or result.get("result", {}).get("isError"))
    for path in ("/api/backend/health", "/api/analyze", "/mcp/extra", "/health", "/.well-known/oauth-protected-resource/mcp/extra"):
        assert request(path)[0] == 404
    keys["expires_at"] = int(time.time()) - 1
    write_json(CONFIG / "jwks.json", keys)
    assert request(method="tools/list", bearer=token)[0] == 401
    keys["expires_at"] = now + 3600
    write_json(CONFIG / "jwks.json", keys)
    assert request(method="tools/list", bearer=token)[0] == 200
    config["profiles"][0]["enabled"] = False
    write_json(CONFIG / "config.json", config)
    assert request(method="tools/list", bearer=token)[0] == 401
    config["profiles"][0]["enabled"] = True
    write_json(CONFIG / "config.json", config)
    run("systemctl", "restart", SERVICE)
    assert request(method="tools/call", params={"name": "get_profile", "arguments": {}}, bearer=token)[0] == 200
    # Stop both activation and the process. Stopping just the service is insufficient.
    run("systemctl", "stop", SOCKET, SERVICE)
    assert request(method="tools/list", bearer=token)[0] in (502, 503)
    assert not Path("/run/tradejournal-d0/mcp.sock").exists()
    print("D0 native TLS/Unix ingress, OAuth refusal, offline key expiry, revocation, restart, stop and IPv4/IPv6 denial passed.")


def cleanup():
    subprocess.run(["systemctl", "stop", SOCKET, SERVICE, PROXY], check=False, capture_output=True)
    for unit in (SOCKET, SERVICE, PROXY):
        Path("/etc/systemd/system", unit).unlink(missing_ok=True)
    shutil.rmtree(Path("/etc/systemd/system", SERVICE + ".d"), ignore_errors=True)
    subprocess.run(["systemctl", "daemon-reload"], check=False, capture_output=True)
    shutil.rmtree(ROOT, ignore_errors=True)
    shutil.rmtree(CONFIG, ignore_errors=True)
    shutil.rmtree("/run/tradejournal-d0", ignore_errors=True)
    subprocess.run(["userdel", USER], check=False, capture_output=True)


def main():
    if (os.geteuid() != 0 or os.environ.get("GITHUB_ACTIONS") != "true"
            or os.environ.get("TJ_DISPOSABLE_RUNNER") != "1"):
        raise SystemExit("This smoke test requires a root-owned disposable GitHub runner")
    if sys.argv[1:] == ["--exercise"]:
        exercise()
        return
    prepare()
    try:
        result = subprocess.run([str(ROOT / "backend/.venv/bin/python"), str(Path(__file__).resolve()), "--exercise"],
            check=False, capture_output=True)
        if result.returncode:
            # Fixture assertions/logs contain no bearer values; service logs are not dumped.
            sys.stderr.write(result.stderr.decode())
            raise SystemExit(result.returncode)
        sys.stdout.write(result.stdout.decode())
    finally:
        cleanup()


if __name__ == "__main__":
    main()
