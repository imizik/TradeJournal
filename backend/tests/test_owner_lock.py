"""Owner lock: browsers need the owner session, server processes do not, off changes nothing."""
import base64
from datetime import timedelta
import logging
import re

from argon2 import PasswordHasher
from fastapi.testclient import TestClient
import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from app.access_manifest import DOMAIN_ROUTES
from app.access_middleware import AccessMiddleware
from app.engine import access, owner_lock
from app.main import app
from app.models import AccessLoginLimit, AccessSession

PASSPHRASE = "plum-orbit-cable-lantern-9241-quiet"
LOCAL_KEY = "l" * 43
FIXTURE_HASHER = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1)
BROWSER = {"x-tj-lock-browser": "1"}


def encoded(passphrase):
    return base64.urlsafe_b64encode(FIXTURE_HASHER.hash(passphrase).encode()).decode().rstrip("=")


@pytest.fixture
def lock(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'lock.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    monkeypatch.delenv("TJ_ACCESS_ENABLED", raising=False)
    monkeypatch.setenv("TJ_OWNER_LOCK", "on")
    monkeypatch.setenv("TJ_OWNER_LOCK_PASSPHRASE_HASH", encoded(PASSPHRASE))
    monkeypatch.setenv("TJ_OWNER_LOCK_LOCAL_KEY", LOCAL_KEY)
    monkeypatch.setattr(owner_lock, "engine", engine)
    monkeypatch.setattr(access, "HASHER", FIXTURE_HASHER)
    yield engine
    engine.dispose()


def concrete(template):
    return re.sub(r"\{[^}]+\}", "1", template)


class Recorder:
    """Stands in for the application behind the middleware: did the request get through?"""
    def __init__(self):
        self.calls = []

    async def __call__(self, scope, receive, send):
        self.calls.append((scope["method"], scope["path"]))
        await send({"type": "http.response.start", "status": 299, "headers": [(b"content-type", b"text/plain")]})
        await send({"type": "http.response.body", "body": b"passed"})


def harness(peer="127.0.0.1"):
    recorder = Recorder()
    client = TestClient(AccessMiddleware(recorder, routes=app.router.routes), client=(peer, 50000))
    return client, recorder


def send(client, operation, **kwargs):
    method, template = operation.split(" ", 1)
    return client.request(method, concrete(template), **kwargs)


def browser_routes():
    # /access/* answers 503 in the private profile before the lock is consulted.
    return sorted((DOMAIN_ROUTES | owner_lock.LOCK_PATHS) - owner_lock.OPEN_OPERATIONS - {owner_lock.LIVENESS})


def sign_in(passphrase=PASSPHRASE, headers=None):
    client = TestClient(app, client=("127.0.0.1", 50000))
    return client.post("/lock/sign-in", json={"passphrase": passphrase}, headers={**BROWSER, **(headers or {})})


def token(lock):
    response = sign_in()
    assert response.status_code == 200, response.text
    return response.json()["token"]


def test_off_by_default_changes_nothing(monkeypatch, tmp_path):
    for name in ("TJ_OWNER_LOCK", "TJ_ACCESS_ENABLED"):
        monkeypatch.delenv(name, raising=False)
    assert owner_lock.mode() == "off"
    client, recorder = harness()
    remote, remote_recorder = harness(peer="100.64.0.7")
    for operation in sorted(DOMAIN_ROUTES):
        assert send(client, operation, headers=BROWSER).status_code == 299, operation
        assert send(remote, operation, headers={"x-forwarded-for": "100.64.0.7"}).status_code == 299, operation
    assert len(recorder.calls) == len(remote_recorder.calls) == len(DOMAIN_ROUTES)
    # The lock's own routes are indistinguishable from a route that does not exist.
    plain = TestClient(app)
    for operation in sorted(owner_lock.LOCK_PATHS):
        response = send(plain, operation, json={"passphrase": "x"} if "sign-in" in operation else None)
        assert (response.status_code, response.json()) == (404, {"detail": "Not Found"}), operation


def test_every_inventoried_route_needs_the_owner_session(lock):
    client, recorder = harness()
    remote, remote_recorder = harness(peer="100.64.0.7")
    for operation in browser_routes():
        response = send(client, operation, headers=BROWSER)
        assert (response.status_code, response.json()) == (401, {"detail": "Sign in required"}), operation
        assert send(remote, operation).status_code == 401, operation
    assert recorder.calls == remote_recorder.calls == []
    # Liveness stays open and says nothing about the release or database.
    health = send(client, "GET /health", headers=BROWSER)
    assert (health.status_code, health.json()) == (200, {"status": "ok"})
    assert recorder.calls == []


def test_signed_in_owner_reaches_every_route(lock):
    session = token(lock)
    client, recorder = harness()
    for operation in browser_routes() + [owner_lock.LIVENESS]:
        assert send(client, operation, headers=BROWSER, cookies={"__Host-tj_owner_lock": session}).status_code == 299, operation
    assert len(recorder.calls) == len(browser_routes()) + 1


def test_unclassified_routes_are_refused_to_browsers(lock):
    session = token(lock)
    client, recorder = harness()
    for path in ("/docs", "/openapi.json", "/not-a-route"):
        assert client.get(path, headers=BROWSER, cookies={"tj_owner_lock": session}).status_code == 404, path
    assert recorder.calls == []


def test_server_processes_keep_working_without_a_session(lock):
    client, recorder = harness()
    for operation in sorted(DOMAIN_ROUTES):
        assert send(client, operation).status_code == 299, operation
    ipv6, ipv6_recorder = harness(peer="::1")
    assert send(ipv6, "GET /sync/summary").status_code == 299
    # The deploy health check reaches the API through the frontend with the server's local key.
    vouched = send(client, "GET /sync/summary", headers={**BROWSER, "x-tj-lock-local": LOCAL_KEY})
    assert vouched.status_code == 299
    assert len(recorder.calls) == len(DOMAIN_ROUTES) + 1 and len(ipv6_recorder.calls) == 1


@pytest.mark.parametrize("peer,headers", [
    ("127.0.0.1", {"x-forwarded-for": "127.0.0.1"}),
    ("127.0.0.1", {"X-Forwarded-For": "100.64.0.9"}),
    ("127.0.0.1", {"x-forwarded-host": "journal.example.ts.net"}),
    ("127.0.0.1", {"forwarded": "for=127.0.0.1"}),
    ("127.0.0.1", {"x-real-ip": "127.0.0.1"}),
    ("127.0.0.1", {"tailscale-user-login": "owner@example.com"}),
    ("127.0.0.1", {"x-tj-lock-browser": "1", "x-tj-lock-local": "l" * 42 + "m"}),
    ("127.0.0.1", {"x-tj-lock-browser": "", "x-tj-lock-local": ""}),
    ("127.0.0.1", {"x-tj-lock-browser": "1", "x-tj-gateway": "o" * 43}),
    ("127.0.0.1", {"x-tj-lock-browser": "1", "x-tj-service": "s" * 43}),
    ("100.64.0.7", {}),
    ("100.64.0.7", {"x-tj-lock-local": LOCAL_KEY}),
    ("100.64.0.7", {"x-tj-lock-browser": "1", "x-tj-lock-local": LOCAL_KEY}),
    ("10.0.0.5", {"x-forwarded-for": "127.0.0.1"}),
])
def test_identity_cannot_be_claimed_with_headers(lock, peer, headers):
    client, recorder = harness(peer=peer)
    for operation in ("GET /trades", "POST /sync/advanced/resync-all", "POST /copilot/desk/robinhood/refresh", "POST /lock/sign-out-everywhere"):
        response = send(client, operation, headers=headers, cookies={"tj_owner_lock": "forged-session-token"})
        assert response.status_code in {401, 503}, (operation, headers)
    assert recorder.calls == []


def test_a_short_local_key_is_never_accepted(lock, monkeypatch):
    monkeypatch.setenv("TJ_OWNER_LOCK_LOCAL_KEY", "short")
    client, recorder = harness()
    assert send(client, "GET /trades", headers={**BROWSER, "x-tj-lock-local": "short"}).status_code == 401
    monkeypatch.setenv("TJ_OWNER_LOCK_LOCAL_KEY", "")
    assert send(client, "GET /trades", headers={**BROWSER, "x-tj-lock-local": ""}).status_code == 401
    assert recorder.calls == []


def test_sign_in_issues_a_server_side_session(lock):
    wrong = sign_in("not-the-passphrase")
    assert (wrong.status_code, wrong.json()) == (401, {"detail": "Sign-in failed"})
    response = sign_in()
    body = response.json()
    assert response.status_code == 200 and body["max_age"] == 30 * 86400 and len(body["token"]) >= 43
    assert response.headers["cache-control"] == "no-store"
    with Session(lock) as db:
        rows = db.exec(select(AccessSession).where(AccessSession.audience == owner_lock.AUDIENCE)).all()
    assert [row.digest for row in rows] == [access.digest(body["token"])]  # only the digest is stored
    browser = TestClient(app, client=("127.0.0.1", 50000), headers=BROWSER)
    assert browser.get("/lock/session").json() == {"mode": "on", "signed_in": False}
    assert browser.get("/lock/session", cookies={"__Host-tj_owner_lock": body["token"]}).json() == {"mode": "on", "signed_in": True}


def test_an_unset_or_malformed_passphrase_cannot_sign_in(lock, monkeypatch):
    for value in ("", "not base64 !", base64.urlsafe_b64encode(b"$argon2i$v=19$plain").decode()):
        monkeypatch.setenv("TJ_OWNER_LOCK_PASSPHRASE_HASH", value)
        response = sign_in()
        assert response.status_code == 503, value
    monkeypatch.setenv("TJ_OWNER_LOCK_PASSPHRASE_HASH", encoded(PASSPHRASE))
    assert sign_in("x" * 300).status_code == 422


def test_sessions_expire_when_idle_or_old(lock):
    session = token(lock)
    digest = access.digest(session)
    assert owner_lock.signed_in(session)
    with Session(lock) as db:
        row = db.get(AccessSession, digest)
        row.last_seen_at = access.now() - owner_lock.IDLE_LIMIT - timedelta(minutes=1)
        db.add(row)
        db.commit()
    assert not owner_lock.signed_in(session)
    with Session(lock) as db:
        row = db.get(AccessSession, digest)
        row.last_seen_at = access.now()
        row.expires_at = access.now() - timedelta(seconds=1)
        db.add(row)
        db.commit()
    assert not owner_lock.signed_in(session)


def test_use_extends_the_idle_clock_but_not_the_lifetime(lock):
    session = token(lock)
    digest = access.digest(session)
    with Session(lock) as db:
        row = db.get(AccessSession, digest)
        expires = row.expires_at
        row.last_seen_at = access.now() - timedelta(days=6)
        db.add(row)
        db.commit()
    assert owner_lock.signed_in(session)
    with Session(lock) as db:
        row = db.get(AccessSession, digest)
        assert row.last_seen_at > access.now() - timedelta(minutes=1) and row.expires_at == expires


def test_sign_out_ends_this_device_only(lock):
    first, second = token(lock), token(lock)
    browser = TestClient(app, client=("127.0.0.1", 50000), headers=BROWSER)
    assert browser.post("/lock/sign-out", cookies={"tj_owner_lock": first}).status_code == 200
    assert not owner_lock.signed_in(first) and owner_lock.signed_in(second)


def test_sign_out_everywhere_needs_the_session_or_the_server(lock):
    first, second = token(lock), token(lock)
    browser = TestClient(app, client=("127.0.0.1", 50000), headers=BROWSER)
    assert browser.post("/lock/sign-out-everywhere").status_code == 401
    assert owner_lock.signed_in(first) and owner_lock.signed_in(second)
    response = browser.post("/lock/sign-out-everywhere", cookies={"tj_owner_lock": first})
    assert response.json() == {"ended": 2}
    assert not owner_lock.signed_in(first) and not owner_lock.signed_in(second)
    third = token(lock)
    # Break-glass: from a shell on the server, with no session at all.
    server = TestClient(app, client=("127.0.0.1", 50001))
    assert server.post("/lock/sign-out-everywhere").json() == {"ended": 1}
    assert not owner_lock.signed_in(third)


def test_a_new_passphrase_ends_every_session(lock, monkeypatch):
    session = token(lock)
    monkeypatch.setenv("TJ_OWNER_LOCK_PASSPHRASE_HASH", encoded("a-brand-new-passphrase-0001"))
    assert not owner_lock.signed_in(session)
    assert sign_in().status_code == 401
    assert sign_in("a-brand-new-passphrase-0001").status_code == 200


def test_sign_in_attempts_are_rate_limited(lock):
    for _ in range(owner_lock.MAX_FAILURES):
        assert sign_in("wrong").status_code == 401
    blocked = sign_in()
    assert (blocked.status_code, blocked.json()) == (429, {"detail": "Too many attempts; try again later"})
    with Session(lock) as db:
        bucket = db.get(AccessLoginLimit, owner_lock.LIMIT_ID)
        bucket.blocked_until = access.now() - timedelta(seconds=1)
        bucket.window_at = access.now() - owner_lock.FAILURE_WINDOW - timedelta(seconds=1)
        db.add(bucket)
        db.commit()
    assert sign_in().status_code == 200
    # A success clears the count, and existing sessions never depend on it.
    with Session(lock) as db:
        assert db.get(AccessLoginLimit, owner_lock.LIMIT_ID).attempts == 0


def test_report_only_logs_and_never_refuses(lock, monkeypatch, caplog):
    monkeypatch.setenv("TJ_OWNER_LOCK", "report")
    client, recorder = harness()
    with caplog.at_level(logging.WARNING, logger="owner_lock"):
        assert send(client, "GET /trades/{trade_id}", headers=BROWSER).status_code == 299
        assert send(client, "POST /fills/resync-all", headers=BROWSER).status_code == 299
        assert client.get("/docs", headers=BROWSER).status_code == 299
        assert send(client, "GET /health", headers=BROWSER).status_code == 299
    assert len(recorder.calls) == 4
    lines = [record.getMessage() for record in caplog.records]
    assert "owner-lock report-only: would refuse GET /trades/{trade_id} (no owner session)" in lines
    assert "owner-lock report-only: would refuse POST /fills/resync-all (no owner session)" in lines
    assert "owner-lock report-only: would refuse GET <unclassified> (unclassified route)" in lines
    # Sign-in works in report mode so every device can be signed in before enforcement.
    assert sign_in().status_code == 200


def test_nothing_secret_is_logged(lock, caplog):
    with caplog.at_level(logging.DEBUG):
        session = sign_in(headers={"x-tj-lock-source": "100.64.0.7"}).json()["token"]
        sign_in("wrong-guess-123", headers={"x-tj-lock-source": "100.64.0.8"})
        client, _ = harness()
        send(client, "GET /trades", headers=BROWSER, cookies={"tj_owner_lock": session})
        send(client, "GET /trades", headers=BROWSER, cookies={"tj_owner_lock": "forged"})
    text = "\n".join(record.getMessage() for record in caplog.records)
    assert "signed in from 100.64.0.7" in text and "refused (wrong passphrase) from 100.64.0.8" in text
    for secret in (PASSPHRASE, "wrong-guess-123", session, LOCAL_KEY, "forged"):
        assert secret not in text


def test_long_streams_recheck_the_session(lock):
    session = token(lock)
    request = TestClient(app).build_request("GET", "/charts/stream", headers=BROWSER, cookies={"tj_owner_lock": session})
    from starlette.requests import Request

    scope = {"type": "http", "method": "GET", "path": "/charts/stream", "headers": [(k.lower().encode(), v.encode()) for k, v in request.headers.items()],
             "client": ("127.0.0.1", 50000), "query_string": b""}
    assert access.still_authorized(Request(scope))
    owner_lock.sign_out_everywhere()
    assert not access.still_authorized(Request(scope))


def test_mode_values(monkeypatch):
    monkeypatch.delenv("TJ_ACCESS_ENABLED", raising=False)
    for value, expected in (("off", "off"), ("", "off"), (" OFF ", "off"), ("report", "report"), ("on", "on"), ("yes", "on"), ("of", "on")):
        monkeypatch.setenv("TJ_OWNER_LOCK", value)
        assert owner_lock.mode() == expected, value
    # The full assistant access mode authenticates every request itself.
    monkeypatch.setenv("TJ_OWNER_LOCK", "on")
    monkeypatch.setenv("TJ_ACCESS_ENABLED", "true")
    assert owner_lock.mode() == "off"
