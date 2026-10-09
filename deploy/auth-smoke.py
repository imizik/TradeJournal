"""Authenticated native trial on the explicitly disposable deployment CI host."""
import http.cookiejar
import json
import os
from pathlib import Path
import subprocess
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, HTTPCookieProcessor, build_opener

import control

OWNER = "http://127.0.0.1:3000"
ASSISTANT = "http://127.0.0.1:3001"
IDENTITY = "127.0.0.1:5432/tj_deployment"


def call(browser, base, path, *, body=None, csrf=None):
    headers = {}
    if body is not None:
        headers.update({"Content-Type": "application/json", "Origin": base})
    if csrf:
        headers["x-tj-csrf"] = csrf
    request = Request(base + path, data=json.dumps(body).encode() if body is not None else None, headers=headers)
    try:
        with browser.open(request, timeout=10) as response:
            value = response.read()
            return response.status, json.loads(value) if response.headers.get_content_type() == "application/json" else value
    except HTTPError as denied:
        return denied.code, None


def wait_login(browser):
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        try:
            if call(browser, ASSISTANT, "/login")[0] == 200:
                return
        except (URLError, TimeoutError):
            pass
        time.sleep(1)
    raise AssertionError("Native assistant login did not become available")


def main():
    if os.geteuid() != 0 or os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("TJ_DISPOSABLE_RUNNER") != "1":
        raise SystemExit("Native auth smoke requires an explicitly disposable CI host")
    reader = build_opener()
    status, health = call(reader, "http://127.0.0.1:8080", "/health")
    if status != 200 or not isinstance(health, dict) or health.get("environment", {}).get("identity") != IDENTITY:
        raise SystemExit("Native auth smoke refuses any other database")
    release = control.current()
    control.run(release / "backend/.venv/bin/python", release / "deploy/access-config.py", "--directory", control.CONFIG,
        "--owner-origin", OWNER, "--assistant-origin", ASSISTANT, "--local-http", "--sample-data")
    control.run("systemctl", "restart", "tradejournal-api", "tradejournal-frontend")
    control.health(release, IDENTITY)
    assert subprocess.run(["systemctl", "is-enabled", "--quiet", "tradejournal-assistant.service"], check=False).returncode != 0
    # This only enables a loopback fixture on this verified CI database.
    config = control.CONFIG / "access-assistant.env"
    config.write_text(config.read_text().replace("TJ_ASSISTANT_ENABLED=false", "TJ_ASSISTANT_ENABLED=true"))
    control.run("systemctl", "start", "tradejournal-assistant.service")
    owner = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))
    public = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))
    try:
        wait_login(public)
        assert call(public, ASSISTANT, "/api/backend/fills")[0] == 401
        status, owner_session = call(owner, OWNER, "/api/access/me")
        assert status == 200 and owner_session["owner"]
        status, credential = call(owner, OWNER, "/api/access/assistants", csrf=owner_session["csrf"], body={
            "identifier": "native-inspector", "grants": {"symbols": ["SPY"], "run_ids": [], "journal_read": False}})
        assert status == 201
        _, challenge = call(public, ASSISTANT, "/api/access/challenge")
        assert call(public, ASSISTANT, "/api/access/login", csrf=challenge["csrf"], body={"identifier": "native-inspector", "key": credential["key"]})[0] == 200
        status, session = call(public, ASSISTANT, "/api/access/me")
        assert status == 200 and not session["owner"]
        assert call(public, ASSISTANT, "/api/backend/practice/runs")[0] == 200
        assert call(public, ASSISTANT, "/api/backend/fills")[0] == 403
        assert call(public, ASSISTANT, "/api/backend/decisions", csrf=session["csrf"], body={})[0] == 403
        # Test the actual service's mount namespace and dynamic UID, not only
        # the declaration in its unit file. Capture output so keys never print.
        pid = control.run("systemctl", "show", "tradejournal-assistant", "--property=MainPID", "--value", capture_output=True, text=True).stdout.strip()
        status_text = Path(f"/proc/{pid}/status").read_text()
        uid = next(line.split()[1] for line in status_text.splitlines() if line.startswith("Uid:"))
        gid = next(line.split()[1] for line in status_text.splitlines() if line.startswith("Gid:"))
        assert uid != "0"
        for path in (control.CONFIG / "access-owner.env", control.STATE / "data/deployment-smoke-state.txt"):
            probe = subprocess.run(["nsenter", "--target", pid, "--mount", f"--setgid={gid}", f"--setuid={uid}", "--", "cat", str(path)], capture_output=True, check=False)
            assert probe.returncode != 0, "Assistant process could read private state/configuration"
        sockets = control.run("ss", "-ltnH", capture_output=True, text=True).stdout
        assert [line.split()[3] for line in sockets.splitlines() if line.split()[3].endswith(":3001")] == ["127.0.0.1:3001"]
        assert call(owner, OWNER, "/api/backend/stats")[1]["total_trades"] == 6
        assert call(owner, OWNER, "/api/access/assistants/native-inspector/revoke", csrf=owner_session["csrf"], body={})[0] == 200
        assert call(public, ASSISTANT, "/api/access/me")[0] == 401
        print("Native auth smoke passed: separate identity, private owner continuity, assistant login, denied reads/writes, private-file isolation and revocation")
    finally:
        control.run("systemctl", "stop", "tradejournal-assistant.service")
        config.write_text(config.read_text().replace("TJ_ASSISTANT_ENABLED=true", "TJ_ASSISTANT_ENABLED=false"))


if __name__ == "__main__":
    main()
