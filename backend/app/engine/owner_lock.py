"""Owner lock for the private installation: one passphrase, server-side sessions.

Off by default (``TJ_OWNER_LOCK`` unset or ``off``): nothing here runs and the
private app behaves exactly as before. ``report`` signs in and logs what would
have been refused without refusing it. ``on`` (or any unrecognised value, so a
typo fails closed) refuses browser requests that carry no owner session.

Who counts as a browser and who as a process on the server (see
docs/owner-lock.md for the full caller map):

* The private frontend marks every request it forwards for a browser with
  ``x-tj-lock-browser``. A marked request needs an owner session cookie, unless
  the frontend also presents the server's local key (the deploy health check
  reaches the frontend that way).
* An unmarked request from a loopback peer that carries no proxy or Tailscale
  identity header is a process on the server (timers, workers, scripts,
  server-rendered pages, the operator's curl) and keeps working unchanged.
* Anything else (another peer address, or forwarding/Tailscale headers that a
  proxy pointed straight at the API would add) is treated as a browser.

The lock does not replace the full assistant access mode: when
``TJ_ACCESS_ENABLED`` is on, that mode authenticates every request itself and
this lock stays out of the way.
"""
from __future__ import annotations

import base64
import binascii
from datetime import timedelta
import hashlib
import hmac
import logging
import os
import re
import secrets
import threading

from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from sqlalchemy import delete
from sqlmodel import Session, select

from app.database import engine
from app.engine import access
from app.models import AccessLoginLimit, AccessSession

log = logging.getLogger("owner_lock")

AUDIENCE = "owner-lock"
COOKIES = ("__Host-tj_owner_lock", "tj_owner_lock")
BROWSER_HEADER = "x-tj-lock-browser"
LOCAL_HEADER = "x-tj-lock-local"
SOURCE_HEADER = "x-tj-lock-source"
# Headers a reverse proxy (Tailscale Serve included) adds. A request carrying
# one did not come from a plain process on the server, whatever its address.
PROXY_HEADERS = ("x-forwarded-for", "x-forwarded-host", "x-forwarded-proto", "forwarded", "x-real-ip",
                 "tailscale-user-login", "tailscale-user-name", "tailscale-user-profile-pic", "tailscale-headers-info")
LOOPBACK = frozenset({"127.0.0.1", "::1"})

SESSION_LIFETIME = timedelta(days=30)
IDLE_LIMIT = timedelta(days=7)
TOUCH_EVERY = timedelta(minutes=10)
MAX_SESSIONS = 10
FAILURE_WINDOW = timedelta(minutes=15)
MAX_FAILURES = 10
LIMIT_ID = hashlib.sha256(b"owner-lock:sign-in").hexdigest()
MAX_PASSPHRASE = 256

# Browser requests that need no session: the sign-in check itself, sign-in and
# sign-out of the presented cookie. Liveness gets its reduced answer instead.
OPEN_OPERATIONS = frozenset({"GET /lock/session", "POST /lock/sign-in", "POST /lock/sign-out"})
LIVENESS = "GET /health"
LOCK_PATHS = frozenset({"GET /lock/session", "POST /lock/sign-in", "POST /lock/sign-out",
                        "POST /lock/sign-out-everywhere"})

_SIGN_IN = threading.Lock()


def mode() -> str:
    if access.enabled():
        return "off"
    value = os.environ.get("TJ_OWNER_LOCK", "off").strip().lower()
    if value in ("", "off"):
        return "off"
    if value == "report":
        return "report"
    return "on"


def _stored_hash() -> str | None:
    raw = os.environ.get("TJ_OWNER_LOCK_PASSPHRASE_HASH", "").strip()
    if not raw:
        return None
    try:
        decoded = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode("ascii")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return None
    return decoded if decoded.startswith("$argon2id$") else None


def generation() -> str:
    """Sessions belong to the passphrase they were issued under: a new passphrase ends them all."""
    return hashlib.sha256(("owner-lock:" + os.environ.get("TJ_OWNER_LOCK_PASSPHRASE_HASH", "").strip()).encode()).hexdigest()


def _local_key() -> str:
    value = os.environ.get("TJ_OWNER_LOCK_LOCAL_KEY", "")
    return value if len(value) >= 32 else ""


def is_local(request) -> bool:
    """True only for a process on this server talking to the API directly."""
    headers = request.headers
    peer = request.client.host if request.client else ""
    if peer not in LOOPBACK:
        return False
    if headers.get(BROWSER_HEADER) is not None:
        key = _local_key()
        return bool(key) and access.token_equal(headers.get(LOCAL_HEADER, ""), key)
    return not any(headers.get(name) is not None for name in PROXY_HEADERS)


def token_from(request) -> str:
    for name in COOKIES:
        value = request.cookies.get(name)
        if value:
            return value
    return ""


def _valid_row(row, stamp) -> bool:
    return bool(row and row.audience == AUDIENCE and row.expires_at > stamp
                and row.last_seen_at + IDLE_LIMIT > stamp and hmac.compare_digest(row.csrf, generation()))


def signed_in(token: str, *, touch: bool = True) -> bool:
    if not token or len(token) > 128:
        return False
    stamp = access.now()
    with Session(engine) as db:
        row = db.get(AccessSession, access.digest(token))
        if not _valid_row(row, stamp):
            return False
        if touch and row.last_seen_at + TOUCH_EVERY <= stamp:
            row.last_seen_at = stamp
            db.add(row)
            db.commit()
        return True


def still_signed_in(request) -> bool:
    """For long-lived streams: re-check without extending the idle clock."""
    if mode() != "on" or is_local(request):
        return True
    return signed_in(token_from(request), touch=False)


def source_hint(request) -> str:
    value = request.headers.get(SOURCE_HEADER, "")
    return value[:64] if re.fullmatch(r"[0-9A-Fa-f:., ]{1,64}", value or "") else "unknown"


class SignInRefused(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status, self.detail = status, detail


def sign_in(passphrase: str, source: str = "unknown") -> tuple[str, int]:
    """Return (session token, cookie max-age seconds) or raise SignInRefused."""
    stored = _stored_hash()
    if not stored:
        raise SignInRefused(503, "Sign-in is not set up on this server")
    with _SIGN_IN, Session(engine) as db:
        stamp = access.now()
        bucket = db.get(AccessLoginLimit, LIMIT_ID) or AccessLoginLimit(id=LIMIT_ID, attempts=0, window_at=stamp)
        if bucket.blocked_until and bucket.blocked_until > stamp:
            raise SignInRefused(429, "Too many attempts; try again later")
        if bucket.window_at + FAILURE_WINDOW <= stamp:
            bucket.attempts, bucket.window_at, bucket.blocked_until = 0, stamp, None
        valid = False
        if isinstance(passphrase, str) and 0 < len(passphrase) <= MAX_PASSPHRASE:
            try:
                valid = access.HASHER.verify(stored, passphrase)
            except (VerifyMismatchError, VerificationError, InvalidHashError):
                valid = False
        if not valid:
            bucket.attempts += 1
            if bucket.attempts >= MAX_FAILURES:
                bucket.blocked_until = stamp + FAILURE_WINDOW
            db.add(bucket)
            access.audit(db, access.OWNER, "owner_lock_sign_in", "denied")
            db.commit()
            log.warning("owner-lock: sign-in refused (wrong passphrase) from %s", source)
            raise SignInRefused(401, "Sign-in failed")
        bucket.attempts, bucket.window_at, bucket.blocked_until = 0, stamp, None
        db.add(bucket)
        active = db.exec(select(AccessSession).where(AccessSession.audience == AUDIENCE)
                         .order_by(AccessSession.created_at.desc())).all()
        for old in active[MAX_SESSIONS - 1:]:
            db.delete(old)
        token = secrets.token_urlsafe(32)
        # csrf holds the passphrase generation for lock sessions; they never use
        # the assistant mode's CSRF tokens and their audience keeps them apart.
        db.add(AccessSession(digest=access.digest(token), principal_id=None, version=0, audience=AUDIENCE,
                             csrf=generation(), created_at=stamp, last_seen_at=stamp,
                             expires_at=stamp + SESSION_LIFETIME))
        access.audit(db, access.OWNER, "owner_lock_sign_in", "accepted")
        db.commit()
        log.info("owner-lock: signed in from %s", source)
        return token, int(SESSION_LIFETIME.total_seconds())


def sign_out(token: str) -> None:
    if not token or len(token) > 128:
        return
    with Session(engine) as db:
        row = db.get(AccessSession, access.digest(token))
        if row and row.audience == AUDIENCE:
            db.delete(row)
            access.audit(db, access.OWNER, "owner_lock_sign_out", "accepted")
            db.commit()


def sign_out_everywhere() -> int:
    with Session(engine) as db:
        count = len(db.exec(select(AccessSession.digest).where(AccessSession.audience == AUDIENCE)).all())
        db.exec(delete(AccessSession).where(AccessSession.audience == AUDIENCE))
        access.audit(db, access.OWNER, "owner_lock_sign_out_everywhere", "accepted")
        db.commit()
    log.warning("owner-lock: every session ended (%d)", count)
    return count
