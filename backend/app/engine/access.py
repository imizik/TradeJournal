"""Server-owned app identity. No browser-supplied role or local-IP bypass."""
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from functools import lru_cache
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
from urllib.parse import urlsplit

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError
from fastapi import HTTPException
from sqlalchemy import delete, text
from sqlmodel import Session, select

from app.database import engine
from app.models import AccessAudit, AccessLoginLimit, AccessPrincipal, AccessSession

HASHER = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=1)
_LOCK = threading.RLock()
OWNER = "owner"
AUTH_PATHS = frozenset({"GET /access/challenge", "POST /access/login", "POST /access/bootstrap",
    "GET /access/me", "POST /access/logout", "GET /access/assistants", "POST /access/assistants",
    "POST /access/assistants/{identifier}/reset", "POST /access/assistants/{identifier}/revoke",
    "GET /access/audit"})
MARKET_PATHS = frozenset({"GET /charts/workspace", "GET /charts/history", "GET /charts/stream",
    "GET /charts/options/{symbol:path}/ladder", "GET /charts/symbol/{symbol:path}/news",
    "GET /charts/symbol/{symbol:path}/overview", "GET /charts/symbol/{symbol:path}/events",
    "GET /charts/symbol/{symbol:path}/forecast", "GET /charts/symbol/{symbol:path}/analysts",
    "GET /charts/symbol/{symbol:path}/short", "GET /charts/symbol/{symbol:path}/peers",
    "GET /charts/symbol/{symbol:path}/financials", "GET /charts/symbol/{symbol:path}/reactions",
    "GET /charts/symbol/{symbol:path}/insiders",
    "GET /packets/analyze", "GET /packets/news", "GET /quotes"})
JOURNAL_PATHS = frozenset({"GET /accounts", "GET /fills", "GET /fills/{fill_id}", "GET /trades",
    "GET /trades/{trade_id}", "GET /trades/fills/bulk", "GET /trades/{trade_id}/fills",
    "GET /stats", "GET /stats/analytics", "GET /daily-review", "GET /daily-review/{review_day}",
    "POST /quotes/positions", "GET /market-context/fill/{fill_id}", "GET /market-context/fills/bulk",
    "GET /market-context/trade/{trade_id}", "GET /market-context/trade-path/bulk",
    "GET /charts/symbol/{symbol:path}/you", "GET /charts/journal/fills/{fill_id}",
    "GET /charts/journal/trades/{trade_id}", "GET /charts/journal/trades/{trade_id}/mark"})
PRACTICE_PATHS = frozenset({"GET /practice/runs", "GET /practice/runs/{run_id}",
    "GET /decisions", "GET /decisions/{record_id}", "GET /decisions/{record_id}/paper"})
SAMPLE_WRITER_PATHS = frozenset({"GET /practice/runs", "GET /practice/runs/{run_id}",
    "GET /decisions", "GET /decisions/{record_id}", "POST /practice/opportunities/{opp_id}/agent-choice"})
SAMPLE_REPLAY_PATH = "POST /practice/opportunities/{opp_id}/sample-replay"
SERVICE_PATHS = {
    "monitor": {"GET /health", "GET /gmail/health", "GET /sync/summary"},
    "automation": {"GET /health", "GET /gmail/health", "GET /gmail/watch/status", "POST /gmail/watch",
        "GET /sync/summary", "GET /sync/jobs", "GET /sync/runs", "POST /sync/pipeline/run",
        "POST /sync/jobs/{job_type}/run"},
    "manual_mcp": {"GET /health", "GET /packets/report", "GET /packets/analyze", "GET /packets/scalp", "GET /packets/news",
        "GET /trades", "GET /trades/{trade_id}", "GET /trades/{trade_id}/fills", "GET /stats",
        "GET /market-context/coverage", "GET /market-context/audit/{trade_id}",
        "GET /market-context/fill/{fill_id}", "GET /market-context/trade/{trade_id}",
        "POST /decisions/context/{symbol}", "POST /decisions", "GET /decisions", "GET /decisions/{record_id}"},
}


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def enabled():
    return os.environ.get("TJ_ACCESS_ENABLED", "false") == "true"


def secure():
    return os.environ.get("TJ_ACCESS_ALLOW_LOCAL_HTTP") != "true"


def cookie_name(kind="session"):
    return ("__Host-" if secure() else "") + "tj_" + kind


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def origin(audience):
    value = os.environ.get("TJ_OWNER_ORIGIN" if audience == "owner" else "TJ_ASSISTANT_ORIGIN", "")
    parsed = urlsplit(value)
    if parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
        raise HTTPException(503, "App access is not configured")
    if not secure() and parsed.hostname not in {"localhost", "127.0.0.1"}:
        raise HTTPException(503, "Insecure cookies are allowed only on loopback fixtures")
    if parsed.scheme == "http" and (secure() or parsed.hostname not in {"localhost", "127.0.0.1"}):
        raise HTTPException(503, "App access requires HTTPS")
    return value


def token_equal(candidate, expected):
    return isinstance(candidate, str) and isinstance(expected, str) and hmac.compare_digest(candidate.encode("utf-8"), expected.encode("utf-8"))


def gateway(request):
    supplied = request.headers.get("x-tj-gateway", "")
    private, public = (os.environ.get(name, "") for name in ("TJ_OWNER_GATEWAY_KEY", "TJ_ASSISTANT_GATEWAY_KEY"))
    if not private or not public or len(private) < 32 or len(public) < 32 or private == public:
        raise HTTPException(503, "App access is not configured")
    for audience, key in (("owner", private), ("assistant", public)):
        if supplied and token_equal(supplied, key):
            origin(audience)
            return audience
    raise HTTPException(401, "Authentication required")


@dataclass(frozen=True)
class Identity:
    identifier: str
    audience: str
    owner: bool = False
    grants: dict = field(default_factory=dict)
    session_digest: str | None = None
    csrf: str = ""
    service: bool = False


def _serialized(db):
    if db.bind.dialect.name == "postgresql":
        db.exec(text("SELECT pg_advisory_xact_lock(1747907280)"))
    else:
        db.exec(text("BEGIN IMMEDIATE"))


def prune(db):
    stamp = now()
    db.exec(delete(AccessSession).where(AccessSession.expires_at < stamp))
    db.exec(delete(AccessLoginLimit).where(AccessLoginLimit.window_at < stamp - timedelta(days=1)))
    db.exec(delete(AccessAudit).where(AccessAudit.created_at < stamp - timedelta(days=7)))
    kept = select(AccessAudit.id).order_by(AccessAudit.created_at.desc(), AccessAudit.id.desc()).offset(9999)
    db.exec(delete(AccessAudit).where(AccessAudit.id.in_(kept)))


def audit(db, principal, operation, outcome, resource=None):
    prune(db)
    db.add(AccessAudit(principal_id=principal, operation=operation[:100], outcome=outcome[:32],
        resource=resource[:100] if resource else None, request_id=secrets.token_hex(16)))


def _session(db, token, audience, *, challenge=False, touch=True):
    row = db.get(AccessSession, digest(token)) if token and len(token) < 128 else None
    if not row or row.audience != audience or row.expires_at <= now():
        raise HTTPException(401, "Authentication required")
    if challenge:
        if row.principal_id is not None:
            raise HTTPException(401, "Authentication required")
        return row, None
    principal = db.get(AccessPrincipal, row.principal_id) if row.principal_id else None
    idle = timedelta(hours=2 if audience == "owner" else 24)
    if not principal or not principal.enabled or row.version != principal.version or row.last_seen_at + idle <= now() or (principal.credential_expires_at and principal.credential_expires_at <= now()):
        raise HTTPException(401, "Authentication required")
    if (audience == "owner") != (principal.id == OWNER):
        raise HTTPException(401, "Authentication required")
    if touch:
        row.last_seen_at = now()
        db.add(row)
    return row, principal


def identify(request, *, consume_budget=True):
    service_key = request.headers.get("x-tj-service", "")
    if service_key and not request.headers.get("x-tj-gateway"):
        try:
            config = json.loads(os.environ.get("TJ_ACCESS_SERVICES", "{}"))
            if not isinstance(config, dict) or set(config) - set(SERVICE_PATHS):
                raise ValueError()
            values = list(config.values())
            if any(not isinstance(value, str) or len(value) < 32 for value in values) or len(set(values)) != len(values) or any(value in {os.environ.get("TJ_OWNER_GATEWAY_KEY"), os.environ.get("TJ_ASSISTANT_GATEWAY_KEY")} for value in values):
                raise ValueError()
        except (ValueError, TypeError):
            raise HTTPException(503, "Service access is not configured") from None
        for name, value in config.items():
            if name in SERVICE_PATHS and isinstance(value, str) and len(value) >= 32 and token_equal(value, service_key):
                return Identity(f"service:{name}", "service", service=True)
        raise HTTPException(401, "Authentication required")
    audience = gateway(request)
    token = request.cookies.get(cookie_name(), "")
    with _LOCK, Session(engine) as db:
        _serialized(db)
        row, principal = _session(db, token, audience)
        if principal.id != OWNER and consume_budget:
            consume_request_budget(db, principal.id)
        identity = Identity(principal.id, audience, principal.id == OWNER,
            json.loads(principal.grants_json), row.digest, row.csrf)
        db.commit()
        return identity


def consume_request_budget(db, identifier):
    # Browser and connector share the persisted per-principal budget.
    bucket_id = digest("requests:" + identifier)
    bucket = db.get(AccessLoginLimit, bucket_id) or AccessLoginLimit(id=bucket_id)
    if bucket.window_at + timedelta(minutes=1) <= now():
        bucket.window_at, bucket.attempts = now(), 0
    if bucket.attempts >= 240:
        raise HTTPException(429, "Request budget exceeded; try again later")
    bucket.attempts += 1
    db.add(bucket)


def csrf_check(request, identity):
    if identity.service:
        return
    if request.headers.get("origin") != origin(identity.audience) or not token_equal(request.headers.get("x-tj-csrf", ""), identity.csrf):
        raise HTTPException(403, "Request verification failed")


def issue_session(db, principal, audience):
    token = secrets.token_urlsafe(32)
    expiry = now() + timedelta(hours=12) if audience == "owner" else now() + timedelta(days=7)
    if principal.credential_expires_at:
        expiry = min(expiry, principal.credential_expires_at)
    active = db.exec(select(AccessSession).where(AccessSession.principal_id == principal.id).order_by(AccessSession.created_at.desc())).all()
    for item in active[3:]:
        db.delete(item)
    row = AccessSession(digest=digest(token), principal_id=principal.id, version=principal.version,
        audience=audience, csrf=secrets.token_urlsafe(32), expires_at=expiry)
    db.add(row)
    return token, row


def set_cookie(response, value, *, kind="session", max_age=604800):
    response.set_cookie(cookie_name(kind), value, secure=secure(), httponly=True, samesite="lax", path="/", max_age=max_age)
    response.headers["Cache-Control"] = "no-store"


@lru_cache(maxsize=1)
def _dummy_hash():
    return HASHER.hash(secrets.token_urlsafe(32))


def login(request, identifier, key):
    audience = gateway(request)
    if audience != "assistant":
        raise HTTPException(403, "Use the private owner entrance")
    identifier = identifier.lower().strip()
    with _LOCK, Session(engine) as db:
        _serialized(db)
        challenge, _ = _session(db, request.cookies.get(cookie_name("challenge"), ""), audience, challenge=True)
        csrf_check(request, Identity("challenge", audience, csrf=challenge.csrf))
        # Source is observed by the API, not a browser-supplied forwarding header.
        keys = [digest("identity:" + identifier), digest("source:" + (request.client.host if request.client else "unknown"))]
        for i, bucket_key in enumerate(keys):
            bucket = db.get(AccessLoginLimit, bucket_key)
            if not bucket:
                if len(db.exec(select(AccessLoginLimit.id).limit(2001)).all()) >= 2000:
                    raise HTTPException(429, "Try again later")
                bucket = AccessLoginLimit(id=bucket_key)
            if bucket.window_at + timedelta(minutes=15) < now():
                bucket.attempts = 0
                bucket.blocked_until = None
                bucket.window_at = now()
            if bucket.blocked_until and bucket.blocked_until > now():
                raise HTTPException(429, "Try again later")
            bucket.attempts += 1
            if bucket.attempts > (10 if i == 0 else 60):
                bucket.blocked_until = now() + timedelta(minutes=15)
            db.add(bucket)
        principal = db.get(AccessPrincipal, identifier)
        valid = False
        try:
            valid = HASHER.verify(principal.key_hash if principal and principal.key_hash else _dummy_hash(), key)
        except (VerificationError, InvalidHashError):
            pass
        if not valid or not principal or principal.id == OWNER or not principal.enabled or not principal.credential_expires_at or principal.credential_expires_at <= now():
            audit(db, principal.id if principal else None, "login", "denied")
            db.commit()
            raise HTTPException(401, "Sign-in failed")
        db.delete(challenge)
        token, row = issue_session(db, principal, audience)
        audit(db, principal.id, "login", "accepted")
        db.commit()
        return token


def bootstrap(request):
    if gateway(request) != "owner":
        raise HTTPException(403, "Private owner entrance required")
    # Only the authenticated private frontend's server-side bootstrap can reach this.
    if request.headers.get("x-tj-bootstrap") != "true":
        raise HTTPException(403, "Private owner entrance required")
    with _LOCK, Session(engine) as db:
        _serialized(db)
        principal = db.get(AccessPrincipal, OWNER)
        if principal is None:
            principal = AccessPrincipal(id=OWNER)
            db.add(principal)
            db.flush()
        token, row = issue_session(db, principal, "owner")
        audit(db, OWNER, "owner_session", "accepted")
        db.commit()
        return token


def grant_valid(grants):
    if not {"symbols", "run_ids", "journal_read"} <= set(grants) <= {"symbols", "run_ids", "journal_read", "decision_write", "sample_replay", "market_decision_write"}:
        raise HTTPException(422, "Invalid permission grant")
    if not isinstance(grants["symbols"], list) or len(grants["symbols"]) > 10 or not grants["symbols"] or any(not isinstance(s, str) or not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,14}", s) for s in grants["symbols"]):
        raise HTTPException(422, "Choose one to ten market symbols")
    import uuid
    try:
        if not isinstance(grants["run_ids"], list) or len(grants["run_ids"]) > 30:
            raise ValueError()
        for value in grants["run_ids"]:
            if str(uuid.UUID(value)) != value:
                raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(422, "Choose valid practice run IDs") from None
    if not isinstance(grants["journal_read"], bool) or (grants["journal_read"] and os.environ.get("TJ_ACCESS_SAMPLE_DATA") != "true"):
        raise HTTPException(403, "Journal inspection is available only on the sample installation")
    if not isinstance(grants.get("decision_write", False), bool):
        raise HTTPException(422, "Invalid decision permission")
    if grants.get("decision_write") and (not sample_writes_enabled() or grants["journal_read"]
            or len(grants["run_ids"]) != 1 or len(grants["symbols"]) > 2):
        raise HTTPException(403, "Sample writers require one selected run, at most two symbols, and no journal access")
    if not isinstance(grants.get("sample_replay", False), bool):
        raise HTTPException(422, "Invalid sample replay permission")
    if grants.get("sample_replay") and (not sample_replays_enabled() or grants.get("decision_write") is not True):
        raise HTTPException(403, "Replay requires an enabled sample writer and explicit sample replay flag")
    if not isinstance(grants.get("market_decision_write", False), bool):
        raise HTTPException(422, "Invalid market decision permission")
    if grants.get("market_decision_write") and (not market_writes_enabled() or grants["journal_read"]
            or grants.get("decision_write") or grants.get("sample_replay") or len(grants["run_ids"]) != 1
            or not set(grants["symbols"]) <= {"MU", "NBIS"}):
        raise HTTPException(403, "Market writer requires one MU/NBIS session and no other write/journal grant")


def sample_writes_enabled():
    return all(os.environ.get(name) == "true" for name in
        ("TJ_ACCESS_ENABLED", "TJ_ACCESS_SAMPLE_DATA", "TJ_DOT_TRIAL_ENABLED", "TJ_SAMPLE_DECISION_WRITES"))


def decision_writer(request):
    who = getattr(request.state, "access", None)
    return bool(who and not who.owner and not who.service and who.grants.get("decision_write")
                and not who.grants.get("journal_read") and sample_writes_enabled())


def sample_replays_enabled():
    return sample_writes_enabled() and os.environ.get("TJ_SAMPLE_REPLAY_ENABLED") == "true"


def replay_writer(request):
    return (decision_writer(request) and request.state.access.grants.get("sample_replay") is True
        and sample_replays_enabled() and getattr(request.app.state, "sample_replay_isolated", False) is True)


def market_writes_enabled():
    return all(os.environ.get(name) == "true" for name in
        ("TJ_ACCESS_ENABLED", "TJ_ACCESS_SAMPLE_DATA", "TJ_DOT_TRIAL_ENABLED", "TJ_MARKET_DECISION_WRITES"))


def market_writer(request):
    who = getattr(request.state, "access", None)
    return bool(who and not who.owner and not who.service and who.grants.get("market_decision_write") is True
        and not any(who.grants.get(k) for k in ("journal_read", "decision_write", "sample_replay"))
        and len(who.grants.get("run_ids", [])) == 1 and set(who.grants.get("symbols", [])) <= {"MU", "NBIS"}
        and market_writes_enabled() and getattr(request.app.state, "market_decisions_isolated", False) is True)


def create_assistant(db, identifier, grants):
    if not re.fullmatch(r"[a-z][a-z0-9_-]{2,63}", identifier) or identifier == OWNER:
        raise HTTPException(422, "Invalid assistant ID")
    grant_valid(grants)
    grant_targets_valid(db, identifier, grants)
    if db.get(AccessPrincipal, identifier):
        raise HTTPException(409, "Assistant ID already exists")
    key = secrets.token_urlsafe(32)
    db.add(AccessPrincipal(id=identifier, key_hash=HASHER.hash(key), grants_json=json.dumps(grants),
        credential_expires_at=now() + timedelta(days=30)))
    audit(db, OWNER, "assistant_create", "accepted", identifier)
    db.commit()
    return key


def grant_targets_valid(db, identifier, grants):
    """The new market dataset is bound to one frozen actor, including read grants."""
    import uuid
    from app.engine import market_practice
    from app.models import PracticeRun
    for value in grants["run_ids"]:
        run = db.get(PracticeRun, uuid.UUID(value))
        if run and market_practice.recognized(run):
            if (not market_practice.eligible(run) or not market_practice.visible_to(run, identifier)
                    or grants.get("decision_write") or grants.get("sample_replay")):
                raise HTTPException(403, "Market session is outside this frozen assignment")
        elif grants.get("market_decision_write"):
            raise HTTPException(403, "Market writer requires its assigned real-market session")


def assistant_row(principal):
    return {"identifier": principal.id, "enabled": principal.enabled,
        "grants": json.loads(principal.grants_json), "expires_at": principal.credential_expires_at}


def is_journal(request):
    who = getattr(request.state, "access", None)
    return who is None or who.owner or who.service or who.grants.get("journal_read", False)


def permitted_runs(request):
    who = getattr(request.state, "access", None)
    return None if who is None or who.owner or who.service else frozenset(who.grants.get("run_ids", []))


def permitted_record_ids(request, db):
    allowed = permitted_runs(request)
    if allowed is None:
        return None
    import uuid
    from app.models import PracticeOpportunity, PracticeRun, DecisionRecord
    from app.engine import market_practice
    who = request.state.access
    selected = db.exec(select(PracticeRun).where(PracticeRun.id.in_([uuid.UUID(value) for value in allowed]))).all()
    visible_ids = [run.id for run in selected if not market_practice.recognized(run) or market_practice.visible_to(run, who.identifier)]
    market_opps = set(db.exec(select(PracticeOpportunity.id).where(PracticeOpportunity.run_id.in_(
        [run.id for run in selected if market_practice.recognized(run)]))).all())
    opps = db.exec(select(PracticeOpportunity.id).where(PracticeOpportunity.run_id.in_(visible_ids))).all()
    query = select(DecisionRecord.id).where(DecisionRecord.opportunity_id.in_([f"a3:{value}" for value in opps]))
    if request.state.access.grants.get("decision_write") or request.state.access.grants.get("market_decision_write"):
        query = query.where(DecisionRecord.actor == "agent:" + request.state.access.identifier,
            DecisionRecord.symbol.in_(request.state.access.grants.get("symbols", [])))
    if market_opps:
        query = query.where((~DecisionRecord.opportunity_id.in_([f"a3:{value}" for value in market_opps]))
            | (DecisionRecord.actor == "agent:" + who.identifier))
    return frozenset(db.exec(query).all())


def validate_symbols(request, params):
    who = request.state.access
    if who.owner or who.service:
        return
    allowed = frozenset(who.grants.get("symbols", []))
    if request.url.path == "/charts/workspace" and (not request.query_params.get("symbol") or not request.query_params.get("watchlist")):
        raise HTTPException(403, "Explicit symbol and watchlist are required")
    wanted = []
    for key in ("symbol", "symbols", "tickers", "watchlist"):
        for source in request.query_params.getlist(key):
            wanted.extend(filter(None, (s.strip().upper() for s in source.split(","))))
    if params.get("symbol"):
        wanted.append(params["symbol"].upper())
    for value in request.query_params.getlist("extras"):
        wanted.extend(s.split(":", 1)[0].strip().upper() for s in value.split(",") if s)
    if not wanted or not set(wanted) <= allowed:
        raise HTTPException(403, "Symbol is outside the assistant grant")


def authorize(request, operation, params):
    who = request.state.access
    if who.service:
        if operation not in SERVICE_PATHS.get(who.identifier.removeprefix("service:"), set()):
            raise HTTPException(403, "Operation not permitted")
        if who.identifier == "service:automation" and operation == "POST /sync/jobs/{job_type}/run" and params.get("job_type") not in {"gmail_sync", "trade_rebuild", "options_snapshot", "rvol_history"}:
            raise HTTPException(403, "Job is outside the service grant")
        return
    if request.method not in {"GET", "HEAD"}:
        csrf_check(request, who)
    if who.owner:
        return
    if operation in {"GET /access/me", "POST /access/logout"}:
        return
    if who.grants.get("market_decision_write"):
        if not market_writer(request):
            raise HTTPException(403, "Market decision writing is disabled")
        if operation in SAMPLE_WRITER_PATHS:
            return
        raise HTTPException(403, "Operation not permitted for the frozen market session")
    if who.grants.get("decision_write"):
        if not decision_writer(request):
            raise HTTPException(403, "Sample decision writing is disabled")
        if operation == SAMPLE_REPLAY_PATH:
            if not replay_writer(request):
                raise HTTPException(403, "Sample replay is not permitted")
            return
        if operation in SAMPLE_WRITER_PATHS:
            return
        if operation in MARKET_PATHS:
            validate_symbols(request, params)
            return
        raise HTTPException(403, "Operation not permitted")
    if operation in MARKET_PATHS:
        validate_symbols(request, params)
        return
    if operation in PRACTICE_PATHS or operation in {"GET /access/me", "POST /access/logout"}:
        return
    if who.grants.get("journal_read") and operation in JOURNAL_PATHS:
        return
    raise HTTPException(403, "Operation not permitted")


def still_authorized(request):
    if not enabled():
        return True
    try:
        return identify(request, consume_budget=False).identifier == request.state.access.identifier
    except HTTPException:
        return False
