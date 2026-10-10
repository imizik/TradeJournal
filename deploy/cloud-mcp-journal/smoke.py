"""Exercise the journal coach in its installed systemd sandbox on disposable CI.

This creates only synthetic journal data and an offline signing key. Run as root
only on the dedicated GitHub Ubuntu deployment runner. It never contacts an
issuer, application database, model provider, production service, or Dot.
"""
from __future__ import annotations

import argparse
import base64
import errno
import hashlib
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
INSTALL = Path("/opt/tradejournal-journal")
RUNTIME = Path("/opt/tradejournal-journal/runtime")
BACKEND = RUNTIME / "backend"
VENV = BACKEND / ".venv"
CONFIG_DIR = Path("/etc/tradejournal-journal")
CONFIG = CONFIG_DIR / "config.json"
STATE = Path("/var/lib/tradejournal-journal")
RUNDIR = Path("/run/tradejournal-journal-coach")
APPROVED = STATE / "approved.json"
JWKS = STATE / "jwks.json"
WRITE_PROBE = STATE / "sandbox-write-probe.bin"
UNIT_DIR = Path("/etc/systemd/system")
SOCKET_UNIT = "tradejournal-journal-coach.socket"
SERVICE_UNIT = "tradejournal-journal-coach.service"
ACCOUNT = "tj-journal-coach"
RESOURCE = "https://journal.example.test/mcp"
ISSUER = "https://identity.example.test/"
JWKS_URL = ISSUER + ".well-known/jwks.json"
CLIENT_ID = "journal-smoke-client"
SUBJECT = "journal-smoke-subject"
PROFILE_ID = "d0_11111111-1111-4111-8111-111111111111"
SCOPES = "d0:profile journal:read"
OWNER_MARKER = BACKEND / ".native-smoke-ownership"
PRODUCTION_MARKER_DIR = Path("/opt/tradejournal")
PRODUCTION_MARKER = PRODUCTION_MARKER_DIR / f".journal-coach-smoke-{os.getpid()}"


def run(*args: object, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run([str(arg) for arg in args], check=False, capture_output=True)
    if check and result.returncode:
        # Disposable fixtures contain no real credentials or journal records.
        # Preserve the failing child diagnostic before cleanup removes its state.
        sys.stderr.write(result.stdout.decode(errors="replace"))
        sys.stderr.write(result.stderr.decode(errors="replace"))
        result.check_returncode()
    return result


def occupied_account() -> bool:
    result = run("getent", "passwd", ACCOUNT, check=False)
    group = run("getent", "group", ACCOUNT, check=False)
    return result.returncode == 0 or group.returncode == 0


def preflight() -> None:
    """Refuse unsafe hosts before creating or changing any file or service."""
    if os.geteuid() != 0:
        raise RuntimeError("journal smoke must run as root on disposable CI")
    if os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("TJ_DISPOSABLE_RUNNER") != "1":
        raise RuntimeError("journal smoke requires the explicitly disposable GitHub runner")
    paths = (INSTALL, RUNTIME, CONFIG_DIR, CONFIG, STATE, APPROVED, JWKS, RUNDIR, PRODUCTION_MARKER,
             UNIT_DIR / SOCKET_UNIT, UNIT_DIR / SERVICE_UNIT,
             UNIT_DIR / f"{SOCKET_UNIT}.d", UNIT_DIR / f"{SERVICE_UNIT}.d")
    existing = [str(path) for path in paths if path.exists() or path.is_symlink()]
    if existing:
        raise RuntimeError("refusing pre-existing journal smoke paths: " + ", ".join(existing))
    if PRODUCTION_MARKER_DIR.is_symlink() or (
        PRODUCTION_MARKER_DIR.exists() and not PRODUCTION_MARKER_DIR.is_dir()
    ):
        raise RuntimeError("production-path read control must be a real directory")
    if occupied_account():
        raise RuntimeError(f"refusing pre-existing {ACCOUNT} user or group")
    # A unit may already be loaded from another unit search path or be active.
    for unit in (SOCKET_UNIT, SERVICE_UNIT):
        if run("systemctl", "is-active", "--quiet", unit, check=False).returncode == 0:
            raise RuntimeError(f"refusing active pre-existing {unit}")
        if run("systemctl", "cat", unit, check=False).returncode == 0:
            raise RuntimeError(f"refusing pre-existing {unit}")
    if run("getent", "group", "caddy", check=False).returncode != 0:
        raise RuntimeError("the disposable runner must provide the caddy socket group")
    for filename in (SOCKET_UNIT, SERVICE_UNIT):
        if not (HERE / filename).is_file():
            raise RuntimeError(f"missing journal gateway unit: {filename}")


def write_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".new")
    temporary.write_text(json.dumps(value, separators=(",", ":")), encoding="utf-8")
    temporary.chmod(0o640)
    run("chown", f"root:{ACCOUNT}", temporary)
    temporary.replace(path)


def prepare() -> None:
    run("groupadd", "--system", ACCOUNT)
    run("useradd", "--system", "--no-create-home", "--shell", "/usr/sbin/nologin", "--gid", ACCOUNT, ACCOUNT)
    INSTALL.mkdir(mode=0o750)
    RUNTIME.mkdir(parents=True, mode=0o750)
    BACKEND.mkdir(mode=0o750)
    CONFIG_DIR.mkdir(mode=0o750)
    STATE.mkdir(mode=0o750)
    run("chown", f"root:{ACCOUNT}", INSTALL, RUNTIME, CONFIG_DIR, STATE)
    run("chmod", "0750", INSTALL, RUNTIME, CONFIG_DIR, STATE)
    run("chown", f"root:{ACCOUNT}", BACKEND)
    run("chmod", "0750", BACKEND)
    WRITE_PROBE.write_bytes(b"sandbox write probe\n")
    WRITE_PROBE.chmod(0o660)
    run("chown", f"root:{ACCOUNT}", WRITE_PROBE)

    for name in ("cloud_mcp_d0.py", "cloud_mcp_journal.py", "journal_coach_snapshot.py"):
        shutil.copy2(REPO / "backend" / name, BACKEND / name)
    run(sys.executable, "-m", "venv", VENV)
    run(VENV / "bin/python", "-m", "pip", "install", "--disable-pip-version-check",
        "mcp==1.28.1", "PyJWT[crypto]==2.13.0")
    for path in BACKEND.iterdir():
        if path.name != ".venv":
            run("chown", f"root:{ACCOUNT}", path)
            if path.is_file():
                run("chmod", "0640", path)

    shutil.copy2(HERE / SOCKET_UNIT, UNIT_DIR / SOCKET_UNIT)
    shutil.copy2(HERE / SERVICE_UNIT, UNIT_DIR / SERVICE_UNIT)
    (UNIT_DIR / SOCKET_UNIT).chmod(0o644)
    (UNIT_DIR / SERVICE_UNIT).chmod(0o644)
    run("systemctl", "daemon-reload")


def fixture(trades: list[dict] | None = None, *, generated_at: str | None = None) -> dict:
    if trades is None:
        trades = [
            {"id": f"00000000-0000-4000-8000-{index:012d}", "ticker": "MU" if index % 2 else "NBIS",
             "instrument_type": "stock", "quantity": "2.500000",
             "realized_pnl": None if index == 50 else ("1.250000" if index % 2 else "-0.500000"),
             "status": "closed", "opened_at": "2026-01-02T09:30:00",
             "closed_at": "2026-01-02T10:00:00"}
            for index in range(51)
        ]
    return {"schema_version": "journal-coach-snapshot-v1",
            "generated_at": generated_at or datetime.now(timezone.utc).isoformat(),
            "start_day": "2026-01-01", "end_day": "2026-01-03",
            "source": "approved_journal_export", "sample_data": True, "trades": trades}


def config(digest: str, **changes) -> dict:
    value = {"enabled": True, "journal_only": True, "issuer_url": ISSUER,
             "resource_url": RESOURCE, "jwks_url": JWKS_URL, "jwks_file": str(JWKS),
             "client_id": CLIENT_ID,
             "profiles": [{"subject": SUBJECT, "id": PROFILE_ID, "enabled": True}],
             "snapshot_file": str(APPROVED), "snapshot_sha256": digest,
             "start_day": "2026-01-01", "end_day": "2026-01-03", "sample_data": True}
    value.update(changes)
    return value


def b64int(value: int) -> str:
    return base64.urlsafe_b64encode(value.to_bytes((value.bit_length() + 7) // 8, "big")).rstrip(b"=").decode()


def assert_owned_fixture(nonce: str | None) -> None:
    if os.geteuid() != 0:
        raise RuntimeError("journal fixture exercise must run as root")
    if os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("TJ_DISPOSABLE_RUNNER") != "1":
        raise RuntimeError("journal fixture exercise requires disposable CI guards")
    if not nonce or not OWNER_MARKER.is_file() or OWNER_MARKER.is_symlink():
        raise RuntimeError("journal fixture exercise requires its owned runtime marker")
    if OWNER_MARKER.read_text(encoding="ascii").strip() != nonce:
        raise RuntimeError("journal fixture ownership marker did not match")
    if not all(path.is_dir() for path in (INSTALL, RUNTIME, BACKEND, CONFIG_DIR, STATE)):
        raise RuntimeError("journal fixture directories are not the smoke-owned installation")
    if any(path.exists() for path in (CONFIG, APPROVED, JWKS)):
        raise RuntimeError("refusing pre-existing journal fixture files")


def exercise(nonce: str | None) -> None:
    assert_owned_fixture(nonce)
    import httpx
    import jwt
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    numbers = key.public_key().public_numbers()
    now = int(time.time())
    write_json(JWKS, {"issuer_url": ISSUER, "jwks_url": JWKS_URL,
                      "fetched_at": now, "expires_at": now + 3600,
                      "keys": [{"kid": "journal-smoke", "kty": "RSA", "use": "sig", "alg": "RS256",
                                "n": b64int(numbers.n), "e": b64int(numbers.e)}]})
    approved = fixture()
    raw = json.dumps(approved, separators=(",", ":")).encode()
    APPROVED.write_bytes(raw)
    APPROVED.chmod(0o640)
    run("chown", f"root:{ACCOUNT}", APPROVED)
    write_json(CONFIG, config(hashlib.sha256(raw).hexdigest()))

    # Start only after every file loaded by the service exists and is synthetic.
    run("systemctl", "enable", "--now", SOCKET_UNIT)
    run("systemctl", "start", SERVICE_UNIT)
    deadline = time.monotonic() + 20
    sockpath = RUNDIR / "mcp.sock"
    while time.monotonic() < deadline and not sockpath.exists():
        time.sleep(0.1)
    if not sockpath.exists():
        raise RuntimeError("systemd journal coach socket did not appear")

    def token(**overrides) -> str:
        issued = int(time.time())
        claims = {"iss": ISSUER, "aud": RESOURCE, "sub": SUBJECT,
                  "client_id": CLIENT_ID, "scope": SCOPES,
                  "iat": issued, "exp": issued + 300}
        claims.update(overrides)
        return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "journal-smoke"})

    def post(name: str, arguments: dict | None = None, *, bearer: str | None = None,
             method: str = "tools/call") -> httpx.Response:
        with httpx.Client(transport=httpx.HTTPTransport(uds="/run/tradejournal-journal-coach/mcp.sock"),
                          base_url="http://journal.example.test", timeout=10, trust_env=False) as client:
            params = {"name": name, "arguments": arguments or {}} if method == "tools/call" else {}
            return client.post("/mcp", headers={"Accept": "application/json, text/event-stream",
                              "MCP-Protocol-Version": "2025-03-26",
                              **({"Authorization": f"Bearer {bearer}"} if bearer else {})},
                              json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params})

    def content(response: httpx.Response) -> dict:
        response.raise_for_status()
        result = response.json()["result"]
        if result.get("isError"):
            raise AssertionError("authorized journal read returned an MCP error")
        return json.loads(result["content"][0]["text"])

    good = token()
    tools = post("", bearer=good, method="tools/list").json()["result"]["tools"]
    assert {item["name"] for item in tools} == {"get_journal_summary", "list_journal_trades"}
    assert all(item["annotations"]["readOnlyHint"] for item in tools)
    summary = content(post("get_journal_summary", bearer=good))["summary"]
    assert summary == {"start_day": "2026-01-01", "end_day": "2026-01-03", "trade_count": 51,
                      "known_pnl_count": 50, "missing_pnl_count": 1, "win_count": 25,
                      "loss_count": 25, "breakeven_count": 0, "win_rate": "0.500000",
                      "realized_pnl_total": "18.750000"}, summary
    first = content(post("list_journal_trades", bearer=good))
    second = content(post("list_journal_trades", {"offset": first["next_offset"]}, bearer=good))
    assert len(first["trades"]) == 50 and len(second["trades"]) == 1
    assert first["total_count"] == second["total_count"] == 51
    assert first["next_offset"] == 50 and second["next_offset"] is None
    forbidden = {"account_id", "broker", "option_symbol", "notes", "email", "fills", "review"}
    assert not forbidden.intersection(first["trades"][0])
    baseline_digest = hashlib.sha256(APPROVED.read_bytes()).hexdigest()
    baseline_rows = [row["id"] for row in first["trades"] + second["trades"]]

    for denied in (token(scope="d0:profile"), token(sub="other-subject"),
                   token(client_id="other-client")):
        response = post("get_journal_summary", bearer=denied)
        assert response.status_code in (401, 403) and not any(
            value in response.text for value in ("18.750000", "MU", "NBIS")
        )

    # A new approved digest is accepted within the same identity, path, window and class.
    refreshed = fixture(generated_at=datetime.now(timezone.utc).isoformat())
    raw_refresh = json.dumps(refreshed, separators=(",", ":")).encode()
    APPROVED.write_bytes(raw_refresh)
    APPROVED.chmod(0o640)
    run("chown", f"root:{ACCOUNT}", APPROVED)
    write_json(CONFIG, config(hashlib.sha256(raw_refresh).hexdigest()))
    refresh_read = content(post("get_journal_summary", bearer=good))
    assert refresh_read["generated_at"] == refreshed["generated_at"]
    refreshed_digest = hashlib.sha256(raw_refresh).hexdigest()

    write_json(CONFIG, config(refreshed_digest, end_day="2026-01-04"))
    response = post("get_journal_summary", bearer=good)
    assert response.json()["result"].get("isError")
    write_json(CONFIG, config(refreshed_digest))

    # Digest mismatch, stale data, unknown fields and changed pinned scope fail closed.
    APPROVED.write_text(json.dumps(fixture()) + " ", encoding="utf-8")
    response = post("get_journal_summary", bearer=good)
    assert response.json()["result"].get("isError")
    stale = fixture(generated_at="2020-01-01T00:00:00+00:00")
    stale_raw = json.dumps(stale, separators=(",", ":")).encode()
    APPROVED.write_bytes(stale_raw)
    APPROVED.chmod(0o640)
    run("chown", f"root:{ACCOUNT}", APPROVED)
    write_json(CONFIG, config(hashlib.sha256(stale_raw).hexdigest()))
    response = post("get_journal_summary", bearer=good)
    assert response.json()["result"].get("isError")
    bad_rows = fixture()
    bad_rows["trades"][0]["notes"] = "must be rejected"
    bad_raw = json.dumps(bad_rows, separators=(",", ":")).encode()
    APPROVED.write_bytes(bad_raw)
    APPROVED.chmod(0o640)
    run("chown", f"root:{ACCOUNT}", APPROVED)
    write_json(CONFIG, config(hashlib.sha256(bad_raw).hexdigest()))
    response = post("get_journal_summary", bearer=good)
    assert response.json()["result"].get("isError")
    write_json(CONFIG, config(hashlib.sha256(raw_refresh).hexdigest(), enabled=False))
    response = post("get_journal_summary", bearer=good)
    assert response.status_code in (401, 403) or response.json()["result"].get("isError")

    # Restore the first approved fixture, then prove clean restart state.
    APPROVED.write_bytes(raw)
    APPROVED.chmod(0o640)
    run("chown", f"root:{ACCOUNT}", APPROVED)
    write_json(CONFIG, config(baseline_digest))
    run("systemctl", "restart", SERVICE_UNIT)
    restored = content(post("get_journal_summary", bearer=good))
    assert restored["summary"] == summary and restored["snapshot_sha256"] == baseline_digest
    restored_first = content(post("list_journal_trades", bearer=good))
    restored_second = content(post("list_journal_trades", {"offset": 50}, bearer=good))
    assert [row["id"] for row in restored_first["trades"] + restored_second["trades"]] == baseline_rows
    assert hashlib.sha256(APPROVED.read_bytes()).hexdigest() == baseline_digest
    assert refreshed_digest != baseline_digest

    print("PASS: offline OAuth, two read tools, exact 51-row pagination, refusal cases, refresh, restart")
    print("PASS: synthetic fixture only; no external issuer, database, model, provider, or Dot call")


def sandbox_check(marker: Path) -> None:
    # Runs as ExecStartPre under the exact service sandbox, before gateway code.
    assert os.geteuid() != 0, "service sandbox ran as root"
    left, right = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    left.close()
    right.close()
    for family in (socket.AF_INET, socket.AF_INET6):
        try:
            sock = socket.socket(family, socket.SOCK_STREAM)
        except OSError as exc:
            if exc.errno not in (errno.EPERM, errno.EACCES, errno.EAFNOSUPPORT):
                raise AssertionError(f"unexpected {family} socket refusal: {exc}") from exc
            continue
        sock.close()
        raise AssertionError(f"service sandbox permits {family} socket creation")
    for path in (CONFIG, APPROVED, JWKS):
        try:
            with path.open("ab"):
                pass
        except OSError as exc:
            if exc.errno not in (errno.EROFS, errno.EACCES, errno.EPERM):
                raise AssertionError(f"unexpected write refusal for {path}: {exc}") from exc
            continue
        raise AssertionError(f"service sandbox can write {path}")
    try:
        with WRITE_PROBE.open("ab") as output:
            output.write(b"sandbox-write-must-fail\n")
    except OSError as exc:
        if exc.errno not in (errno.EROFS, errno.EACCES, errno.EPERM):
            raise AssertionError(f"unexpected write-probe refusal: {exc}") from exc
    else:
        raise AssertionError("service sandbox can write its DAC-permitted probe")
    try:
        marker.read_bytes()
    except OSError as exc:
        if exc.errno not in (errno.ENOENT, errno.EACCES, errno.EPERM):
            raise AssertionError(f"unexpected production marker refusal: {exc}") from exc
    else:
        raise AssertionError("service sandbox can read production-path marker")
    print("service sandbox denies IP sockets, config/state writes and production-path reads")


def stop_and_cleanup() -> None:
    # Cleanup targets are only paths that passed the empty-host preflight.
    run("systemctl", "disable", "--now", SOCKET_UNIT, check=False)
    run("systemctl", "stop", SERVICE_UNIT, check=False)
    for name in (SOCKET_UNIT, SERVICE_UNIT):
        (UNIT_DIR / name).unlink(missing_ok=True)
        shutil.rmtree(UNIT_DIR / f"{name}.d", ignore_errors=True)
    run("systemctl", "daemon-reload", check=False)
    shutil.rmtree(RUNTIME, ignore_errors=True)
    shutil.rmtree(INSTALL, ignore_errors=True)
    shutil.rmtree(CONFIG_DIR, ignore_errors=True)
    shutil.rmtree(STATE, ignore_errors=True)
    try:
        RUNDIR.rmdir()
    except OSError:
        pass
    run("userdel", ACCOUNT, check=False)
    run("groupdel", ACCOUNT, check=False)


def active_main_pid() -> int:
    return int(run("systemctl", "show", "--property=MainPID", "--value", SERVICE_UNIT).stdout.strip())


def expect_policy_failure(expected_message: str) -> None:
    result = run("systemctl", "start", SERVICE_UNIT, check=False)
    if result.returncode == 0:
        raise AssertionError(f"service started after removing a required policy: {expected_message}")
    logs = run("journalctl", "-u", SERVICE_UNIT, "--since", "5 minutes ago", "--no-pager", "-o", "cat",
               check=False)
    if expected_message.encode() not in logs.stdout + logs.stderr:
        raise AssertionError(f"service failed without the expected policy probe: {expected_message}")
    if run("systemctl", "is-active", "--quiet", SERVICE_UNIT, check=False).returncode == 0:
        raise AssertionError("service stayed active after a sandbox policy probe failed")


def exercise_policy_removals(dropin: Path) -> None:
    """Prove the marker and DAC-permitted write probes detect lost policy."""
    regression = dropin / "policy-test.conf"
    run("systemctl", "stop", SERVICE_UNIT)
    regression.write_text("[Service]\nRestart=no\nInaccessiblePaths=\n", encoding="utf-8")
    run("systemctl", "daemon-reload")
    run("systemctl", "reset-failed", SERVICE_UNIT, check=False)
    expect_policy_failure("service sandbox can read production-path marker")

    regression.unlink()
    run("systemctl", "daemon-reload")
    run("systemctl", "reset-failed", SERVICE_UNIT, check=False)
    run("systemctl", "start", SERVICE_UNIT)
    if active_main_pid() <= 0:
        raise AssertionError("service did not return to its hardened template")
    print("PASS: removing InaccessiblePaths lets the positive marker control detect lost isolation")

    run("systemctl", "stop", SERVICE_UNIT)
    regression.write_text("[Service]\nRestart=no\nProtectSystem=false\n", encoding="utf-8")
    run("systemctl", "daemon-reload")
    run("systemctl", "reset-failed", SERVICE_UNIT, check=False)
    expect_policy_failure("service sandbox can write its DAC-permitted probe")

    regression.unlink()
    run("systemctl", "daemon-reload")
    run("systemctl", "reset-failed", SERVICE_UNIT, check=False)
    run("systemctl", "start", SERVICE_UNIT)
    if active_main_pid() <= 0:
        raise AssertionError("service did not restart after restoring its hardened template")
    print("PASS: removing ProtectSystem lets the DAC-permitted write control detect lost isolation")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exercise", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--sandbox-check", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--marker", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--nonce", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.exercise:
        exercise(args.nonce)
        return
    if args.sandbox_check:
        sandbox_check(args.marker or PRODUCTION_MARKER)
        return
    preflight()
    production_dir_created = not PRODUCTION_MARKER_DIR.exists()
    try:
        prepare()
        nonce = secrets.token_hex(32)
        OWNER_MARKER.write_text(nonce + "\n", encoding="ascii")
        OWNER_MARKER.chmod(0o600)
        # Probe one unpredictable production-path marker using exclusive create;
        # remove only the marker and directory created by this invocation.
        PRODUCTION_MARKER_DIR.mkdir(mode=0o755, exist_ok=True)
        if production_dir_created:
            PRODUCTION_MARKER_DIR.chmod(0o755)
        fd = os.open(PRODUCTION_MARKER, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        with os.fdopen(fd, "wb") as marker:
            marker.write(b"disposable journal sandbox marker")
        check = BACKEND / "assert_sandbox.py"
        check.write_text(f'''import errno, os, socket, sys
from pathlib import Path
if sys.argv[1:] == ["--host-control"]:
    assert os.geteuid() != 0, "positive control must use the service identity"
    for family in (socket.AF_INET, socket.AF_INET6):
        sock = socket.socket(family, socket.SOCK_STREAM)
        sock.close()
    Path("{PRODUCTION_MARKER}").read_bytes()
    with Path("{WRITE_PROBE}").open("ab") as output:
        output.write(b"unsandboxed-positive-control\\n")
    print("unsandboxed socket, marker-read and write-probe controls passed")
    raise SystemExit(0)
assert os.geteuid() != 0, "service sandbox ran as root"
left, right = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
left.close()
right.close()
for family in (socket.AF_INET, socket.AF_INET6):
    try:
        sock = socket.socket(family, socket.SOCK_STREAM)
    except OSError as exc:
        assert exc.errno in (errno.EPERM, errno.EACCES, errno.EAFNOSUPPORT), str(exc)
    else:
        sock.close()
        raise AssertionError(f"service sandbox permits {{family}} socket creation")
for path in (Path("{CONFIG}"), Path("{APPROVED}"), Path("{JWKS}")):
    try:
        with path.open("ab"):
            pass
    except OSError as exc:
        assert exc.errno in (errno.EROFS, errno.EACCES, errno.EPERM), str(exc)
    else:
        raise AssertionError(f"service sandbox can write {{path}}")
try:
    with Path("{WRITE_PROBE}").open("ab") as output:
        output.write(b"sandbox-write-must-fail\\n")
except OSError as exc:
    assert exc.errno in (errno.EROFS, errno.EACCES, errno.EPERM), str(exc)
else:
    raise AssertionError("service sandbox can write its DAC-permitted probe")
try:
    Path("{PRODUCTION_MARKER}").read_bytes()
except OSError as exc:
    assert exc.errno in (errno.ENOENT, errno.EACCES, errno.EPERM), str(exc)
else:
    raise AssertionError("service sandbox can read production-path marker")
print("service sandbox denies IP sockets, config/state writes and production-path reads")
''', encoding="utf-8")
        check.chmod(0o640)
        run("chown", f"root:{ACCOUNT}", check)
        dropin = UNIT_DIR / f"{SERVICE_UNIT}.d"
        dropin.mkdir()
        (dropin / "smoke.conf").write_text(f"[Service]\nExecStartPre={VENV}/bin/python {check}\n")
        run("systemctl", "daemon-reload")
        run("runuser", "-u", ACCOUNT, "--", VENV / "bin/python", check, "--host-control")
        print("PASS: unsandboxed coach identity can create IPv4/IPv6 sockets, read marker and write probe")
        run(VENV / "bin/python", __file__, "--exercise", "--nonce", nonce)
        main_pid = active_main_pid()
        if main_pid <= 0:
            raise AssertionError("journal coach service has no active process")
        service_netns = Path(f"/proc/{main_pid}/ns/net").stat().st_ino
        host_netns = Path("/proc/1/ns/net").stat().st_ino
        if service_netns == host_netns:
            raise AssertionError("journal coach did not enter a private network namespace")
        address_families = run(
            "systemctl", "show", "--property=RestrictAddressFamilies", "--value", SERVICE_UNIT
        ).stdout.decode().strip()
        if address_families != "AF_UNIX":
            raise AssertionError(f"unexpected service address families: {address_families}")
        exercise_policy_removals(dropin)
        # The listener must be socket activated and stop with its socket.
        run("systemctl", "stop", SOCKET_UNIT)
        run("systemctl", "stop", SERVICE_UNIT)
        for unit in (SOCKET_UNIT, SERVICE_UNIT):
            if run("systemctl", "is-active", "--quiet", unit, check=False).returncode == 0:
                raise AssertionError(f"journal coach unit remained active after stopping: {unit}")
        sockpath = RUNDIR / "mcp.sock"
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
                probe.settimeout(1)
                probe.connect(str(sockpath))
        except OSError:
            pass
        else:
            raise AssertionError("journal MCP socket remained reachable after its unit stopped")
        print("PASS: systemd Unix socket/service lifecycle and isolated runtime")
    finally:
        stop_and_cleanup()
        PRODUCTION_MARKER.unlink(missing_ok=True)
        try:
            if production_dir_created:
                PRODUCTION_MARKER_DIR.rmdir()
        except OSError:
            pass


if __name__ == "__main__":
    main()
