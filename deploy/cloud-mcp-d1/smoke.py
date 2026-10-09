"""Real sample API namespace and Unix-only MCP on a disposable Ubuntu CI host.

Uses generated signed tokens and seeded data, never an external issuer or Dot.
"""
import base64
from datetime import timedelta
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parents[1]
RUNTIME = Path("/opt/tradejournal-d1-ci")
D0 = Path("/opt/tradejournal-d0")
STATE = Path("/var/lib/tradejournal-dot-trial")
CONFIG = Path("/etc/tradejournal-dot-trial")
LINK = Path("/etc/tradejournal-d1")
KEYS = Path("/var/lib/tradejournal-d0-keys")
API = "tradejournal-dot-trial-api.service"
SOCKET = "tradejournal-d1-reads.socket"
BRIDGE = "tradejournal-d1-reads.service"
MCP_SOCKET = "tradejournal-d0-https.socket"
MCP = "tradejournal-d0-https.service"
UNITS = (API, SOCKET, BRIDGE, MCP_SOCKET, MCP)
USERS = ("tradejournal-d0", "tj-dot-trial")
RESOURCE = "https://journal.example.test/mcp"
ISSUER = "https://identity.example.test/"


def run(*args, **kwargs):
    return subprocess.run([str(arg) for arg in args], check=True, capture_output=True, text=True, **kwargs)


def write(path, value, *, group="tradejournal-d0"):
    path.write_text(value)
    path.chmod(0o640)
    run("chown", f"root:{group}", path)


def prepare(python):
    from dot_trial_install import units
    for user in USERS:
        run("useradd", "--system", "--no-create-home", "--shell", "/usr/sbin/nologin", user)
    shutil.copytree(SOURCE / "backend", RUNTIME / "backend", ignore=shutil.ignore_patterns(
        ".venv", "data", "tests", ".env", ".env.*", "__pycache__", ".ruff_cache", ".pytest_cache"))
    (RUNTIME / "backend/.venv").symlink_to(python.parent.parent)
    shutil.copy2(SOURCE / "deploy/dot_trial_app.py", RUNTIME / "backend/dot_trial_app.py")
    (D0 / "backend").mkdir(parents=True)
    (D0 / "backend/.venv").symlink_to(python.parent.parent)
    for name in ("cloud_mcp_d0.py", "cloud_mcp_d1_common.py", "cloud_mcp_d2_common.py", "cloud_mcp_d1.py"):
        shutil.copy2(SOURCE / "backend" / name, D0 / "backend" / name)
    for path, group in ((CONFIG, "tj-dot-trial"), (LINK, "tradejournal-d0"), (KEYS, "tradejournal-d0")):
        path.mkdir(mode=0o750)
        run("chown", f"root:{group}", path)
    (STATE / "data").mkdir(parents=True)
    (STATE / ".sample-installation").touch()
    (RUNTIME / "backend/data").symlink_to(STATE / "data", target_is_directory=True)
    url = f"sqlite:///{STATE}/data/trial.db"
    env = {"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin", "DATABASE_URL": url, "MIGRATION_DATABASE_URL": url,
        "TJ_ACCESS_ENABLED": "true", "TJ_ACCESS_SAMPLE_DATA": "true", "TJ_DOT_TRIAL_ENABLED": "true",
        "TJ_SAMPLE_DECISION_WRITES": "true", "JOB_EXECUTION_MODE": "external",
        "TJ_CLOUD_MCP_DECISION_WRITES": "true",
        "JOB_LOCK_DIR": str(STATE / "job_locks"), "CAPTURE_TRANSCRIBER": "off"}
    from dot_trial_app import OFF_FLAGS
    env.update({flag: "false" for flag in OFF_FLAGS})
    run(python, "scripts/seed_dev_data.py", "--database-url", url, cwd=RUNTIME / "backend", env=env)
    write(CONFIG / "trial-runtime.env", "".join(f"{k}={v}\n" for k, v in env.items()), group="tj-dot-trial")
    write(CONFIG / "access-backend.env", "TJ_OWNER_GATEWAY_KEY=" + "o" * 43 + "\nTJ_ASSISTANT_GATEWAY_KEY=" + "p" * 43
        + "\nTJ_OWNER_ORIGIN=https://owner.example.test\nTJ_ASSISTANT_ORIGIN=https://assistant.example.test\n", group="tj-dot-trial")
    os.environ.update(env)
    sys.path.insert(0, str(RUNTIME / "backend"))
    from app.database import engine
    from app.engine import access, sample_practice
    from app.models import AccessPrincipal
    from sqlmodel import Session
    with Session(engine) as db:
        exercise = sample_practice.prepare(db)
        db.add(AccessPrincipal(id="native-inspector", key_hash="unusable-fixture-key", enabled=True,
            version=1, credential_expires_at=access.now() + timedelta(hours=1), grants_json=json.dumps({
                "symbols": ["MU", "NBIS"], "run_ids": [str(exercise.id)], "journal_read": False})))
        db.commit()
        run_id, day = str(exercise.id), exercise.day.isoformat()
    run("chown", "-R", "tj-dot-trial:tj-dot-trial", STATE)
    definitions = {API: units(RUNTIME)[API]}
    for name in (SOCKET, BRIDGE):
        definitions[name] = (HERE / name).read_text()
    for name in (MCP_SOCKET, MCP):
        definitions[name] = (HERE.parent / "cloud-mcp-d0" / name).read_text()
    for name, content in definitions.items():
        Path("/etc/systemd/system", name).write_text(content)
    for name, template in ((API, "sample-api.conf"), (MCP, "mcp.conf")):
        folder = Path("/etc/systemd/system", name + ".d")
        folder.mkdir()
        (folder / "d1.conf").write_text((HERE / template).read_text())
    # Run the IP refusal probe inside the exact installed MCP sandbox.
    check = D0 / "assert_no_network.py"
    check.write_text('import socket\nfor family in (socket.AF_INET, socket.AF_INET6):\n'
        '    try:\n        sock = socket.socket(family, socket.SOCK_STREAM)\n'
        '    except OSError:\n        continue\n'
        '    sock.close()\n    raise SystemExit("IP sockets permitted")\n')
    Path("/etc/systemd/system", MCP + ".d/check.conf").write_text(f"[Service]\nExecStartPre={python} {check}\n")
    return run_id, day


def exercise(run_id, day):
    import httpx
    import jwt
    from cryptography.hazmat.primitives.asymmetric import rsa
    from app.database import engine
    from app.models import AccessPrincipal, DecisionContext, DecisionRecord, DecisionEvent, PracticeRun
    from sqlmodel import Session, select
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    numbers = key.public_key().public_numbers()
    def b64(value):
        return base64.urlsafe_b64encode(value.to_bytes((value.bit_length() + 7) // 8, "big")).rstrip(b"=").decode()
    now = int(time.time())
    snapshot = {"issuer_url": ISSUER, "jwks_url": ISSUER + "keys", "fetched_at": now,
        "expires_at": now + 3600, "keys": [{"kid": "native", "kty": "RSA", "use": "sig", "alg": "RS256",
            "n": b64(numbers.n), "e": b64(numbers.e)}]}
    write(KEYS / "jwks.json", json.dumps(snapshot))
    config = {"enabled": True, "synthetic_only": True, "sample_only": True, "issuer_url": ISSUER,
        "resource_url": RESOURCE, "jwks_url": ISSUER + "keys", "jwks_file": str(KEYS / "jwks.json"),
        "client_id": "native-client", "profiles": [{"subject": "native-subject", "id": "d0_11111111-1111-4111-8111-111111111111",
            "enabled": True, "principal_id": "native-inspector", "principal_version": 1}]}
    write(LINK / "config.json", json.dumps(config))
    def token(**changes):
        claims = {"iss": ISSUER, "aud": RESOURCE, "sub": "native-subject", "client_id": "native-client",
            "scope": "d0:profile practice:read", "iat": now, "exp": now + 300, **changes}
        return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "native"})
    signed = token()
    run("systemctl", "daemon-reload")
    run("systemctl", "start", API, SOCKET, MCP_SOCKET)
    def call(name, arguments, *, bearer=signed):
        with httpx.Client(transport=httpx.HTTPTransport(uds="/run/tradejournal-d0/mcp.sock"), timeout=15,
                trust_env=False, follow_redirects=False) as client:
            response = client.post("http://localhost:8788/mcp", headers={"Authorization": "Bearer " + bearer,
                "Accept": "application/json"}, json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                    "params": {"name": name, "arguments": arguments}})
            response.raise_for_status()
            return response.json()["result"]
    def ready():
        deadline = time.monotonic() + 45
        while True:
            try:
                reply = call("get_practice_run", {"run_id": run_id})
                if reply.get("isError") is not True:
                    return reply
            except (OSError, httpx.HTTPError):
                pass
            if time.monotonic() > deadline:
                raise AssertionError("Actual sample bridge did not become ready")
            time.sleep(.5)
    reply = ready()
    assert run_id in json.dumps(reply) and "sample_fixture" in json.dumps(reply)
    assert run_id in json.dumps(call("list_practice_runs", {"day": day}))
    with Session(engine) as db:
        before = {model.__name__: [row.model_dump(mode="json") for row in db.exec(select(model)).all()]
            for model in (PracticeRun, DecisionRecord, DecisionEvent)}
    assert call("get_practice_run", {"run_id": run_id}, bearer=token(scope="d0:profile"))["isError"] is True
    # Bypass MCP through its real Unix bridge: the API still authenticates.
    with httpx.Client(transport=httpx.HTTPTransport(uds="/run/tradejournal-d1/reads.sock"), timeout=10) as client:
        path = "/cloud-mcp/practice/runs/" + run_id
        assert client.get("http://localhost" + path).status_code == 401
        assert client.get("http://localhost" + path, headers={"Authorization": "Bearer " + token(aud="https://other.test/mcp")}).status_code == 401
        assert client.get("http://localhost/trades", headers={"Authorization": "Bearer " + signed}).status_code == 401
        assert client.post("http://localhost/practice/prepare", headers={"Authorization": "Bearer " + signed}, json={}).status_code == 401
    with Session(engine) as db:
        after = {model.__name__: [row.model_dump(mode="json") for row in db.exec(select(model)).all()]
            for model in (PracticeRun, DecisionRecord, DecisionEvent)}
        assert before == after
        principal = db.get(AccessPrincipal, "native-inspector")
        principal.enabled = False
        db.add(principal)
        db.commit()
    assert call("get_practice_run", {"run_id": run_id})["isError"] is True
    with Session(engine) as db:
        principal = db.get(AccessPrincipal, "native-inspector")
        principal.enabled = True
        db.add(principal)
        db.commit()
    run("systemctl", "restart", API)
    assert ready().get("isError") is not True
    snapshot["expires_at"] = now - 1
    write(KEYS / "jwks.json", json.dumps(snapshot))
    try:
        call("get_practice_run", {"run_id": run_id})
    except httpx.HTTPStatusError as error:
        assert error.response.status_code == 401
    else:
        raise AssertionError("Expired keys accepted")
    for unit in (API, BRIDGE, MCP):
        pid = run("systemctl", "show", unit, "--property=MainPID", "--value").stdout.strip()
        assert pid != "0"
        ns = Path(f"/proc/{pid}/ns/net").readlink()
        assert ns != Path("/proc/1/ns/net").readlink()
    assert run("systemctl", "show", MCP, "--property=RestrictAddressFamilies", "--value").stdout.strip() == "AF_UNIX"
    # Opt into D2 only after the unchanged D1 reader/refusal checks above.
    snapshot["expires_at"] = now + 3600
    write(KEYS / "jwks.json", json.dumps(snapshot))
    with Session(engine) as db:
        principal = db.get(AccessPrincipal, "native-inspector")
        grants = json.loads(principal.grants_json)
        principal.grants_json = json.dumps({**grants, "decision_write": True})
        db.add(principal)
        db.commit()
        original_contexts = [row.model_dump(mode="json") for row in db.exec(select(DecisionContext)).all()]
        original_events = [row.model_dump(mode="json") for row in db.exec(select(DecisionEvent)).all()]
    config["decision_writes"] = True
    write(LINK / "config.json", json.dumps(config))
    run("systemctl", "restart", MCP)
    write_token = token(scope="d0:profile practice:read practice:write")
    def content(reply):
        assert reply.get("isError") is not True, reply
        # FastMCP wraps dict outputs under result in its structured schema.
        structured = reply["structuredContent"]
        return structured.get("result", structured)
    assigned = content(call("get_practice_run", {"run_id": run_id}))["run"]
    opportunity_id = assigned["opportunities"][0]["id"]
    arguments = {"opportunity_id": opportunity_id, "decision": "skip",
        "rationale": "Native simulated choice; no paper or provider activity"}
    assert content(call("get_practice_choice", {"opportunity_id": opportunity_id}))["status"] == "not_recorded"
    assert call("record_practice_choice", arguments)["isError"] is True  # reader token
    saved = content(call("record_practice_choice", arguments, bearer=write_token))
    assert saved["created"] is True and saved["choice"]["status"] == "practice_draft_unarmed"
    again = content(call("record_practice_choice", arguments, bearer=write_token))
    assert again["created"] is False and again["choice"] == saved["choice"]
    assert call("record_practice_choice", {**arguments, "rationale": "Changed content"}, bearer=write_token)["isError"] is True
    # The backend still validates scope when callers bypass MCP.
    with httpx.Client(transport=httpx.HTTPTransport(uds="/run/tradejournal-d1/reads.sock"), timeout=10) as client:
        path = "/cloud-mcp/practice/opportunities/" + opportunity_id + "/choice"
        body = {key: value for key, value in arguments.items() if key != "opportunity_id"}
        assert client.post("http://localhost" + path, headers={"Authorization": "Bearer " + signed}, json=body).status_code == 401
    run("systemctl", "restart", API)
    ready()
    recovered = content(call("get_practice_choice", {"opportunity_id": opportunity_id}))
    assert recovered["choice"] == saved["choice"]
    with Session(engine) as db:
        assert len(db.exec(select(DecisionRecord)).all()) == 1
        assert [row.model_dump(mode="json") for row in db.exec(select(DecisionContext)).all()] == original_contexts
        assert [row.model_dump(mode="json") for row in db.exec(select(DecisionEvent)).all()] == original_events
        principal = db.get(AccessPrincipal, "native-inspector")
        principal.grants_json = json.dumps(grants)  # revoke writes, retain receipt reads
        db.add(principal)
        db.commit()
    assert call("record_practice_choice", arguments, bearer=write_token)["isError"] is True
    assert content(call("get_practice_choice", {"opportunity_id": opportunity_id}))["choice"] == saved["choice"]
    # Exercise the updater's actual pause/restore helpers against installed units.
    from dot_trial_update import cloud_reads_state, stop_cloud_reads as pause_reads, restore_cloud_reads
    cloud_units, cloud_active = cloud_reads_state()
    assert cloud_active and set(cloud_units) == {SOCKET, BRIDGE}
    pause_reads(cloud_units)
    run("systemctl", "stop", API)
    with httpx.Client(transport=httpx.HTTPTransport(uds="/run/tradejournal-d1/reads.sock"), timeout=2) as client:
        try:
            client.get("http://localhost/cloud-mcp/practice/runs", params={"day": day})
        except httpx.ConnectError:
            pass
        else:
            raise AssertionError("Updater pause allowed socket activation")
    assert run("systemctl", "show", API, "--property=ActiveState", "--value").stdout.strip() == "inactive"
    assert cloud_reads_state()[1] is False
    snapshot["expires_at"] = now + 3600
    write(KEYS / "jwks.json", json.dumps(snapshot))
    run("systemctl", "start", API)
    deadline = time.monotonic() + 45
    while True:
        pid = run("systemctl", "show", API, "--property=MainPID", "--value").stdout.strip()
        try:
            run("nsenter", "--target", pid, "--net", "--", "python3", "-c",
                "import json\nfrom urllib.request import urlopen\n"
                "with urlopen('http://127.0.0.1:8091/health', timeout=2) as r: assert json.load(r)['status'] == 'ok'")
            break
        except subprocess.CalledProcessError:
            if time.monotonic() > deadline:
                raise AssertionError("Paused API did not recover")
            time.sleep(.5)
    assert cloud_reads_state()[1] is False
    restore_cloud_reads(cloud_active)
    assert ready().get("isError") is not True
    from dot_trial_control import stop_cloud_reads
    stop_cloud_reads()
    run("systemctl", "stop", API)
    with httpx.Client(transport=httpx.HTTPTransport(uds="/run/tradejournal-d1/reads.sock"), timeout=2) as client:
        try:
            client.get("http://localhost/cloud-mcp/practice/runs", params={"day": day})
        except httpx.ConnectError:
            pass
        else:
            raise AssertionError("Stopped socket reactivated the sample API")
    assert run("systemctl", "show", API, "--property=ActiveState", "--value").stdout.strip() == "inactive"
    print("Native D1/D2 passed: actual Unix bridge, independent bearer checks, assigned simulation, read invariance, opt-in immutable choice/retry/recovery, write-scope and principal denials, revocation, restart, expired keys, updater pause/recovery and stopped activation; MCP IP sockets denied")


def main():
    if os.geteuid() != 0 or os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("TJ_DISPOSABLE_RUNNER") != "1":
        raise SystemExit("D1 smoke requires the explicitly disposable GitHub Ubuntu runner")
    sys.path.insert(0, str(SOURCE / "deploy"))
    import control
    python = control.current() / "backend/.venv/bin/python"
    if Path(sys.prefix) != python.parent.parent:
        os.execv(str(python), [str(python), str(Path(__file__).resolve())])
    roots = (RUNTIME, D0, STATE, CONFIG, LINK, KEYS)
    paths = [Path("/etc/systemd/system", name) for name in UNITS]
    dropins = [Path("/etc/systemd/system", name + ".d") for name in (API, MCP)]
    if any(path.exists() or path.is_symlink() for path in (*roots, *paths, *dropins)) or any(
            subprocess.run(["getent", "passwd", user], capture_output=True).returncode == 0 for user in USERS):
        raise SystemExit("Refusing to overwrite an existing trial")
    try:
        run_id, day = prepare(python)
        exercise(run_id, day)
    finally:
        subprocess.run(["systemctl", "stop", *UNITS], capture_output=True)
        subprocess.run(["journalctl", "--no-pager", "-n", "80", *["--unit=" + unit for unit in UNITS]], check=False)
        for path in paths:
            path.unlink(missing_ok=True)
        for path in (*dropins, *roots):
            if path.exists():
                shutil.rmtree(path)
        run("systemctl", "daemon-reload")
        for user in USERS:
            subprocess.run(["userdel", user], capture_output=True)


if __name__ == "__main__":
    main()
