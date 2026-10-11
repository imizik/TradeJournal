"""Disposable real-Unix management/browser fixture, with generated OAuth only."""
import json
import os
from pathlib import Path
import socket
import sys
import time

import httpx
from cryptography.hazmat.primitives.asymmetric import rsa

from tests.advisor_owner_fixture import initialize
from tests.test_cloud_mcp_d0 import _token, _jwks, ISSUER, JWKS_URL

RESOURCE = "https://advisor.example.test/advisor/mcp"


def init(directory):
    value = initialize(directory, saved=False)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    config = {"enabled": True, "advisor_only": True, "issuer_url": ISSUER, "resource_url": RESOURCE,
        "jwks_url": JWKS_URL, "jwks_file": str(directory / "keys.json"), "client_id": "advisor-client",
        "backend_socket": str(directory / "backend.sock"), "assignment_management": True,
        "owner_peer_uid": os.getuid(), "profiles": [{**value["config"]["binding"], "enabled": True}]}
    keys = {"issuer_url": ISSUER, "jwks_url": JWKS_URL, "fetched_at": int(time.time()) - 1,
        "expires_at": int(time.time()) + 1800, **_jwks(key.public_key())}
    # Signing key is test-only; each local save probe issues a fresh short-lived token.
    from cryptography.hazmat.primitives import serialization
    (directory / "fixture-key.pem").write_bytes(key.private_bytes(serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    for name, body in (("advisor.json", config), ("keys.json", keys)):
        (directory / name).write_text(json.dumps(body))
    for path in directory.iterdir():
        if path.is_file():
            path.chmod(0o600)


def serve(directory):
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(directory / "backend.sock"))
    os.chmod(directory / "backend.sock", 0o600)
    listener.listen(8)
    os.dup2(listener.fileno(), 3, inheritable=True)
    os.set_inheritable(3, True)
    script = "from cloud_mcp_advisor_bridge import create_app; from cloud_advisor_owner import OwnerProtocol; import uvicorn,sys; uvicorn.run(create_app(sys.argv[1],sys.argv[2]),fd=3,http=OwnerProtocol,access_log=False,proxy_headers=False)"
    os.execve(sys.executable, [sys.executable, "-B", "-c", script, str(directory / "advisor.json"), str(directory / "fixture.db")],
        {"PATH": "/usr/bin:/bin", "PYTHON_DOTENV_DISABLED": "1"})


def probe(directory, operation):
    from cryptography.hazmat.primitives.serialization import load_pem_private_key
    key = load_pem_private_key((directory / "fixture-key.pem").read_bytes(), password=None)
    config = json.loads((directory / "advisor.json").read_text())
    token = _token(key, audience=RESOURCE, subject=config["profiles"][0]["subject"], client_id="advisor-client",
        scope="advisor:profile advisor:read advisor:write")
    with httpx.Client(transport=httpx.HTTPTransport(uds=str(directory / "backend.sock")), headers={"Authorization": "Bearer " + token}) as client:
        read = client.get("http://fixture/cloud-mcp/advisor/request")
        if operation == "denied":
            assert read.status_code == 403
            old = json.loads((directory / "saved.json").read_text())
            body = {**{k: old["request"][k] for k in ("packet_sha256", "request_sha256")}, "answer": old["receipt"]["submitted_output"]["answer"]}
            assert client.post("http://fixture/cloud-mcp/advisor/answer", json=body).status_code == 409
            return
        assert read.status_code == 200, read.text
        request = read.json()["request"]
        first = request["packet"]["opportunities"][0]
        answer = {"summary": "Wait for verified inputs", "interpretation": "Invented evidence only", "risks": "Calendar unavailable",
            "conditions": "Verified trigger and fixed risk", "gaps": "Real prices unavailable",
            "references": [{"opportunity_id": first["opportunity_id"], "fact_name": first["price_facts"][0]["name"]}]}
        result = client.post("http://fixture/cloud-mcp/advisor/answer", json={"packet_sha256": request["packet_sha256"], "request_sha256": request["request_sha256"], "answer": answer})
        assert result.status_code == 200, result.text
        receipt = result.json()["receipt"]
        assert client.get("http://fixture/cloud-mcp/advisor/request").json()["receipt"] == receipt
        (directory / "saved.json").write_text(json.dumps({"request": request, "receipt": receipt}))


if __name__ == "__main__":
    operation, raw = sys.argv[1:]
    directory = Path(raw).resolve()
    if operation == "init":
        init(directory)
    elif operation == "serve":
        serve(directory)
    else:
        probe(directory, operation)
