"""Actual requests prove identity, operation, resource and stream boundaries."""
from datetime import timedelta
import json
from types import SimpleNamespace
import uuid

from fastapi.testclient import TestClient
from fastapi.routing import APIRoute
import pytest
from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine, select

from app import access_middleware
from app.access_manifest import DOMAIN_ROUTES
from app.database import get_session
from app.engine import access
from app.main import app
from app.models import AccessPrincipal, AccessSession, AccessAudit, PracticeRun, PracticeOpportunity, JobRun
from app.routers import charts, quotes

OWNER_KEY, PUBLIC_KEY = "o" * 43, "p" * 43
OWNER_ORIGIN, PUBLIC_ORIGIN = "http://127.0.0.1:3100", "http://127.0.0.1:3101"


@pytest.fixture
def boundary(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'auth.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    for name, value in {"TJ_ACCESS_ENABLED": "true", "TJ_OWNER_GATEWAY_KEY": OWNER_KEY,
        "TJ_ASSISTANT_GATEWAY_KEY": PUBLIC_KEY, "TJ_OWNER_ORIGIN": OWNER_ORIGIN,
        "TJ_ASSISTANT_ORIGIN": PUBLIC_ORIGIN, "TJ_ACCESS_ALLOW_LOCAL_HTTP": "true"}.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(access, "engine", engine)
    monkeypatch.setattr(access_middleware, "engine", engine)
    def session():
        with Session(engine) as db:
            yield db
    app.dependency_overrides[get_session] = session
    owner, public = TestClient(app), TestClient(app)
    owner.headers.update({"x-tj-gateway": OWNER_KEY, "origin": OWNER_ORIGIN})
    public.headers.update({"x-tj-gateway": PUBLIC_KEY, "origin": PUBLIC_ORIGIN})
    assert owner.post("/access/bootstrap", headers={"x-tj-bootstrap": "true"}).status_code == 200
    owner.headers["x-tj-csrf"] = owner.get("/access/me").json()["csrf"]
    created = owner.post("/access/assistants", json={"identifier": "dot", "grants": {"symbols": ["SPY", "MU", "NBIS"], "run_ids": [], "journal_read": False}})
    assert created.status_code == 201, created.text
    yield SimpleNamespace(engine=engine, owner=owner, public=public, key=created.json()["key"], patch=monkeypatch)
    app.dependency_overrides.clear()
    owner.close()
    public.close()
    engine.dispose()


def signin(b, *, identifier="dot", key=None):
    challenge = b.public.get("/access/challenge")
    assert challenge.status_code == 200, challenge.text
    response = b.public.post("/access/login", headers={"x-tj-csrf": challenge.json()["csrf"]}, json={"identifier": identifier, "key": key or b.key})
    if response.status_code == 200:
        b.public.headers["x-tj-csrf"] = b.public.get("/access/me").json()["csrf"]
    return response


def test_route_inventory_is_exhaustive():
    actual = {f"{method} {r.path}" for r in access_middleware.registered_routes(app.routes) if isinstance(getattr(r, "original_route", r), APIRoute) for method in r.methods}
    assert actual == DOMAIN_ROUTES | access.AUTH_PATHS
    assert access.MARKET_PATHS | access.JOURNAL_PATHS | access.PRACTICE_PATHS <= DOMAIN_ROUTES
    for allowed in access.SERVICE_PATHS.values():
        assert allowed <= DOMAIN_ROUTES


def test_fake_headers_and_anonymous_requests_never_query_fills(boundary):
    queried = []
    event.listen(boundary.engine, "before_cursor_execute", lambda _, __, statement, *rest: queried.append(statement.lower()))
    response = boundary.public.get("/fills", headers={"x-tj-role": "owner", "x-tj-bootstrap": "true", "x-forwarded-for": "127.0.0.1"})
    assert response.status_code == 401
    assert not any("from fill" in sql for sql in queried)
    assert TestClient(app).get("/health").json() == {"status": "ok"}
    assert TestClient(app).get("/docs").status_code == 404
    assert boundary.public.post("/access/bootstrap", headers={"x-tj-bootstrap": "true"}).status_code == 403


def test_session_storage_csrf_and_logout(boundary):
    response = signin(boundary)
    assert response.status_code == 200
    assert "httponly" in response.headers["set-cookie"].lower()
    assert "samesite=lax" in response.headers["set-cookie"].lower()
    assert not boundary.public.get("/access/me").json()["owner"]
    with Session(boundary.engine) as db:
        assert db.get(AccessPrincipal, "dot").key_hash.startswith("$argon2id$")
        token = boundary.public.cookies.get(access.cookie_name())
        assert db.get(AccessSession, token) is None
        assert db.get(AccessSession, access.digest(token)) is not None
        assert boundary.key not in repr(db.exec(select(AccessAudit)).all())
    assert boundary.public.post("/access/logout", headers={"x-tj-csrf": "wrong"}).status_code == 403
    assert boundary.public.post("/access/logout", headers={"origin": "https://evil.example"}).status_code == 403
    assert boundary.public.post("/access/logout").status_code == 200
    assert boundary.public.get("/access/me").status_code == 401


def test_bad_login_rate_limit_and_uniform_errors(boundary):
    assert signin(boundary, key="wrong").json() == signin(boundary, identifier="unknown", key="wrong").json()
    for _ in range(10):
        signin(boundary, key="wrong")
    assert signin(boundary, key="wrong").status_code == 429
    assert boundary.public.get("/access/me").status_code == 401


def test_cross_audience_and_missing_configuration(boundary):
    boundary.public.cookies.set(access.cookie_name(), boundary.owner.cookies.get(access.cookie_name()))
    assert boundary.public.get("/access/me").status_code == 401
    boundary.patch.delenv("TJ_ASSISTANT_GATEWAY_KEY")
    assert boundary.owner.get("/access/me").status_code == 503


@pytest.mark.parametrize("method,path", [("GET", "/fills"), ("GET", "/accounts"), ("GET", "/charts/settings"),
    ("GET", "/charts/symbol/SPY/you"), ("GET", "/gmail/health"), ("GET", "/access/assistants"),
    ("POST", "/sync/pipeline/run"), ("POST", "/decisions"), ("POST", "/practice/prepare"),
    ("POST", f"/practice/opportunities/{uuid.uuid4()}/choice"), ("POST", f"/decisions/{uuid.uuid4()}/arm"),
    ("PUT", "/charts/settings"), ("POST", "/access/assistants")])
def test_read_only_inspector_denied(boundary, method, path):
    assert signin(boundary).status_code == 200
    assert boundary.public.request(method, path, json={} if method != "GET" else None).status_code == 403


def test_symbols_checked_before_provider(boundary):
    assert signin(boundary).status_code == 200
    called = []
    boundary.patch.setattr(quotes, "get_stock_quotes", lambda symbols: called.append(symbols) or {s: 12 for s in symbols})
    assert boundary.public.get("/quotes?tickers=MU,NBIS").status_code == 200
    for query in ("tickers=SPY,NVDA", "tickers=MU&tickers=NVDA"):
        assert boundary.public.get(f"/quotes?{query}").status_code == 403
    assert called == [["MU", "NBIS"]]


def test_market_history_does_not_query_journal(boundary):
    assert signin(boundary).status_code == 200
    boundary.patch.setattr(charts.chart_feed.daily, "page", lambda *a: {"bars": []})
    boundary.patch.setattr(charts, "_markers", lambda *a: pytest.fail("Market-only history queried journal"))
    response = boundary.public.get("/charts/history?symbol=SPY&interval=1D&session=regular&before=123456")
    assert response.status_code == 200, response.text
    assert response.json()["markers"] == []


def test_revoke_reset_and_idle_expiry(boundary):
    assert signin(boundary).status_code == 200
    assert boundary.owner.post("/access/assistants/dot/revoke", json={}).status_code == 200
    assert boundary.public.get("/access/me").status_code == 401
    reset = boundary.owner.post("/access/assistants/dot/reset", json={"grants": {"symbols": ["SPY"], "run_ids": [], "journal_read": False}})
    assert reset.status_code == 200
    assert signin(boundary).status_code == 401
    boundary.key = reset.json()["key"]
    assert signin(boundary).status_code == 200
    with Session(boundary.engine) as db:
        row = db.get(AccessSession, access.digest(boundary.public.cookies.get(access.cookie_name())))
        row.last_seen_at = access.now() - timedelta(hours=25)
        db.add(row)
        db.commit()
    assert boundary.public.get("/access/me").status_code == 401


def test_granted_practice_read_does_not_repair_interrupted_run(boundary):
    with Session(boundary.engine) as db:
        job = JobRun(job_type="practice_prepare", status="failed")
        db.add(job)
        db.flush()
        run = PracticeRun(session_key="test", day=access.now().date(), job_id=job.id, status="preparing", mode="manual", comparison="independent", deadline=access.now(), policy_version="p0", policy_hash="x")
        db.add(run)
        db.flush()
        db.add(PracticeOpportunity(run_id=run.id, symbol="SPY"))
        db.commit()
        run_id = str(run.id)
    reset = boundary.owner.post("/access/assistants/dot/reset", json={"grants": {"symbols": ["SPY"], "run_ids": [run_id], "journal_read": False}})
    boundary.key = reset.json()["key"]
    assert signin(boundary).status_code == 200
    response = boundary.public.get(f"/practice/runs/{run_id}")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "preparing"
    assert response.json()["opportunities"][0]["agent"] is None
    assert boundary.public.get(f"/practice/runs/{uuid.uuid4()}").status_code == 404
    with Session(boundary.engine) as db:
        assert db.get(PracticeRun, uuid.UUID(run_id)).status == "preparing"


def test_actual_revocation_closes_active_stream(boundary):
    assert signin(boundary).status_code == 200
    unsubscribed = []
    clock = [0.0]
    boundary.patch.setattr(charts, "stream_clock", lambda: clock[0])
    class Queue:
        async def get(self):
            with Session(boundary.engine) as db:
                row = db.get(AccessPrincipal, "dot")
                row.enabled = False
                db.add(row)
                db.commit()
            clock[0] = 16.0
            return {"type": "trade", "price": 12}
    boundary.patch.setattr(charts.tradier, "tradier_configured", lambda: True)
    boundary.patch.setattr(app.state, "chart_market_stream", SimpleNamespace(subscribe=lambda wanted: (1, Queue()), unsubscribe=unsubscribed.append), raising=False)
    response = boundary.public.get("/charts/stream?symbol=SPY")
    assert response.status_code == 200
    assert response.text.count("event: trade") <= 1
    assert unsubscribed == [1]


def test_sample_grants_and_internal_service_limits(boundary):
    assert boundary.owner.post("/access/assistants", json={"identifier": "coach", "grants": {"symbols": ["SPY"], "run_ids": [], "journal_read": True}}).status_code == 403
    boundary.patch.setenv("TJ_ACCESS_SERVICES", json.dumps({"monitor": "m" * 43}))
    client = TestClient(app)
    client.headers["x-tj-service"] = "m" * 43
    assert "environment" in client.get("/health").json()
    assert client.get("/fills").status_code == 403
    assert client.post("/access/bootstrap", headers={"x-tj-bootstrap": "true"}).status_code == 401


def test_workspace_defaults_cannot_expand_symbol_access(boundary):
    assert signin(boundary).status_code == 200
    boundary.patch.setattr(charts.chart_feed, "workspace", lambda *a, **kw: pytest.fail("Unauthorized provider call"))
    assert boundary.public.get("/charts/workspace?symbol=MU").status_code == 403
    assert boundary.public.get("/charts/workspace?watchlist=MU").status_code == 403
    assert boundary.public.get("/charts/workspace?symbol=MU&watchlist=MU&extras=NVDA:5m").status_code == 403


def test_absolute_expiry_and_challenge_replay(boundary):
    challenge = boundary.public.get("/access/challenge").json()
    body = {"identifier": "dot", "key": boundary.key}
    assert boundary.public.post("/access/login", headers={"x-tj-csrf": challenge["csrf"]}, json=body).status_code == 200
    assert boundary.public.post("/access/login", headers={"x-tj-csrf": challenge["csrf"]}, json=body).status_code == 401
    with Session(boundary.engine) as db:
        row = db.get(AccessSession, access.digest(boundary.public.cookies.get(access.cookie_name())))
        row.expires_at = access.now() - timedelta(seconds=1)
        db.add(row)
        db.commit()
    assert boundary.public.get("/access/me").status_code == 401


def test_secure_cookie_defaults_and_insecure_internet_config_denial(boundary):
    boundary.patch.delenv("TJ_ACCESS_ALLOW_LOCAL_HTTP")
    boundary.patch.setenv("TJ_OWNER_ORIGIN", "https://owner.example")
    boundary.patch.setenv("TJ_ASSISTANT_ORIGIN", "https://assistant.example")
    response = boundary.owner.post("/access/bootstrap", headers={"x-tj-bootstrap": "true"})
    assert response.status_code == 200
    assert "__Host-tj_session=" in response.headers["set-cookie"]
    assert "; Secure" in response.headers["set-cookie"]
    assert "Domain=" not in response.headers["set-cookie"]
    boundary.patch.setenv("TJ_ACCESS_ALLOW_LOCAL_HTTP", "true")
    assert boundary.owner.get("/access/me").status_code == 503


def test_request_rate_limit_persists_and_denies_before_provider(boundary):
    assert signin(boundary).status_code == 200
    from app.models import AccessLoginLimit
    with Session(boundary.engine) as db:
        bucket = db.get(AccessLoginLimit, access.digest("requests:dot"))
        bucket.attempts = 240
        db.add(bucket)
        db.commit()
    boundary.patch.setattr(quotes, "get_stock_quotes", lambda *a: pytest.fail("Rate-limited request reached provider"))
    assert boundary.public.get("/quotes?tickers=SPY").status_code == 429


def test_chunked_login_body_is_bounded_before_credential_validation(boundary):
    challenge = boundary.public.get("/access/challenge").json()
    content = json.dumps({"identifier": "dot", "key": "x" * 20_000}).encode()
    response = boundary.public.post("/access/login", headers={"x-tj-csrf": challenge["csrf"], "content-type": "application/json"}, content=iter([content[:10_000], content[10_000:]]))
    assert response.status_code == 413
    assert response.json() == {"detail": "Request too large"}


def test_non_ascii_forged_csrf_is_a_denial_not_a_server_error(boundary):
    assert signin(boundary).status_code == 200
    headers = [(b"x-tj-csrf", b"\xff")]
    assert boundary.public.post("/access/logout", headers=headers).status_code == 403


def test_stream_revalidation_does_not_spend_request_budget(boundary):
    assert signin(boundary).status_code == 200
    from app.models import AccessLoginLimit
    from starlette.requests import Request
    with Session(boundary.engine) as db:
        bucket = db.get(AccessLoginLimit, access.digest("requests:dot"))
        bucket.attempts = 240
        db.add(bucket)
        db.commit()
    request = Request({"type": "http", "method": "GET", "path": "/charts/stream", "headers": [(b"x-tj-gateway", PUBLIC_KEY.encode()), (b"cookie", f"{access.cookie_name()}={boundary.public.cookies.get(access.cookie_name())}".encode())], "query_string": b"symbol=SPY", "server": ("localhost", 8080), "scheme": "http"})
    identity = access.identify(request, consume_budget=False)
    request.state.access = identity
    assert access.still_authorized(request)
    with Session(boundary.engine) as db:
        assert db.get(AccessLoginLimit, access.digest("requests:dot")).attempts == 240
    assert boundary.public.get("/access/me").status_code == 429
