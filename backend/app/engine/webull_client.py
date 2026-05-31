"""
Webull OpenAPI HTTP client + signer.

Isolated, testable, and free of any FastAPI/SQLModel imports so it can be
swapped or reused. The rest of the app talks to Webull through this class;
no other module computes signatures or builds Webull URLs.

Auth scheme (per https://developer.webull.com/apis/docs/authentication/signature/):
  1. Required headers on every request:
       x-app-key
       x-timestamp                  (ISO 8601 UTC, e.g. 2025-11-13T01:37:20Z)
       x-signature
       x-signature-algorithm        ("HMAC-SHA1")
       x-signature-version          ("1.0")
       x-signature-nonce            (random string per request)
       x-version                    ("v2") — required header, NOT signed
       Content-Type: application/json (when a body is present)
       x-access-token               (only if 2FA/token flow is active)
  2. Signing headers included in the canonical string:
       x-app-key, x-signature-algorithm, x-signature-version,
       x-signature-nonce, x-timestamp, host
     (x-signature itself, x-version, x-access-token, and Content-Type are NOT signed.)
  3. Canonical string:
       params = merge(query_params, signing_headers)
       str1   = sorted(params).join("&", "k=v")
       if body present:
           str2 = MD5(body_string).upper()
           str3 = path + "&" + str1 + "&" + str2
       else:
           str3 = path + "&" + str1
       encoded = urllib.parse.quote(str3, safe="")
       sig     = base64( HMAC-SHA1( key=(app_secret + "&"), msg=encoded ) )

Notes:
  - The body string passed to MD5 MUST be the EXACT byte-for-byte JSON sent
    in the HTTP request. We control serialization here to guarantee that.
  - All errors raised from this module are sanitized through `_sanitize`
    before they escape — neither the app_secret nor the app_key appear in
    exception messages or log lines.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Environment / base URL resolution
# ---------------------------------------------------------------------------

# Base URLs from Webull's published documentation. Region selection is
# currently US-only; if you later support HK/EU, extend this map.
_BASE_URLS = {
    ("us", "prod"): "https://api.webull.com",
    ("us", "uat"):  "https://us-openapi-alb.uat.webullbroker.com",
}

WEBULL_APP_KEY = os.environ.get("WEBULL_APP_KEY", "")
WEBULL_APP_SECRET = os.environ.get("WEBULL_APP_SECRET", "")
WEBULL_ENVIRONMENT = os.environ.get("WEBULL_ENVIRONMENT", "prod").lower()
WEBULL_REGION_ID = os.environ.get("WEBULL_REGION_ID", os.environ.get("WEBULL_REGION", "us")).lower()
WEBULL_ACCESS_TOKEN = os.environ.get("WEBULL_ACCESS_TOKEN", "")  # optional, only when 2FA enabled
# Optional manual override (rare — sandbox-of-sandbox, mock servers, etc.)
WEBULL_API_BASE_OVERRIDE = os.environ.get("WEBULL_API_BASE", "").rstrip("/")

SIGNATURE_ALGORITHM = "HMAC-SHA1"
SIGNATURE_VERSION = "1.0"
API_VERSION_HEADER = "v2"


def resolve_base_url() -> str:
    """Return the active base URL based on env vars. Manual override wins."""
    if WEBULL_API_BASE_OVERRIDE:
        return WEBULL_API_BASE_OVERRIDE
    key = (WEBULL_REGION_ID, WEBULL_ENVIRONMENT)
    if key not in _BASE_URLS:
        raise WebullClientError(
            f"No base URL configured for region={WEBULL_REGION_ID!r} environment={WEBULL_ENVIRONMENT!r}"
        )
    return _BASE_URLS[key]


def webull_configured() -> bool:
    return bool(WEBULL_APP_KEY and WEBULL_APP_SECRET)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class WebullClientError(RuntimeError):
    """Raised on Webull API errors. Sanitized — never includes secrets."""


def _sanitize(msg: str) -> str:
    if WEBULL_APP_KEY and WEBULL_APP_KEY in msg:
        msg = msg.replace(WEBULL_APP_KEY, "<redacted_app_key>")
    if WEBULL_APP_SECRET and WEBULL_APP_SECRET in msg:
        msg = msg.replace(WEBULL_APP_SECRET, "<redacted_app_secret>")
    if WEBULL_ACCESS_TOKEN and WEBULL_ACCESS_TOKEN in msg:
        msg = msg.replace(WEBULL_ACCESS_TOKEN, "<redacted_access_token>")
    return msg


# ---------------------------------------------------------------------------
# Signing primitives — pure, no I/O, easy to unit-test
# ---------------------------------------------------------------------------

def iso8601_utc_now() -> str:
    """e.g. 2025-11-13T01:37:20Z. Webull-required format."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def make_nonce() -> str:
    """Random per-request nonce. 32 hex chars is plenty of entropy."""
    return secrets.token_hex(16)


def serialize_body(body: Any) -> Optional[str]:
    """
    Serialize body to the EXACT string that will be sent on the wire and
    fed into MD5. We use compact separators so the wire bytes match the
    MD5 input byte-for-byte. None / empty dict => no body.
    """
    if body is None:
        return None
    if isinstance(body, str):
        return body
    return json.dumps(body, separators=(",", ":"), ensure_ascii=False)


def md5_upper(body_string: str) -> str:
    return hashlib.md5(body_string.encode("utf-8")).hexdigest().upper()


def build_canonical_string(
    *,
    path: str,
    query_params: dict[str, Any],
    signing_headers: dict[str, str],
    body_string: Optional[str],
) -> str:
    """
    Construct the URL-encoded canonical string that gets HMAC'd.

    Steps per Webull docs:
      1. Merge query params + signing headers.
      2. Sort by key, join as k=v separated by "&" (str1).
      3. If body: str3 = path + "&" + str1 + "&" + MD5(body)
         Else:    str3 = path + "&" + str1
      4. URL-encode str3 (all chars).
    """
    # Lowercase all keys before merging to match the SDK exactly.
    # If a query collides with a signing header, the SDK joins the values
    # with "&". Our query params are never named like x-* headers, so we
    # use simple overwrite semantics for the rare collision case.
    merged: dict[str, str] = {}
    for k, v in query_params.items():
        if v is None:
            continue
        merged[k.lower()] = str(v)
    for k, v in signing_headers.items():
        merged[k.lower()] = str(v)

    sorted_pairs = "&".join(f"{k}={merged[k]}" for k in sorted(merged.keys()))

    if body_string:
        str3 = f"{path}&{sorted_pairs}&{md5_upper(body_string)}"
    else:
        str3 = f"{path}&{sorted_pairs}"

    # URL-encode the entire string. `safe=""` means even '/' '&' '=' are encoded.
    return urllib.parse.quote(str3, safe="")


def compute_signature(*, app_secret: str, encoded_string: str) -> str:
    """
    base64( HMAC-SHA1( key = app_secret + "&", message = encoded_string ) )

    Note the trailing "&" on the signing key — this is per the Webull spec
    and is NOT a typo.
    """
    signing_key = (app_secret + "&").encode("utf-8")
    digest = hmac.new(signing_key, encoded_string.encode("utf-8"), hashlib.sha1).digest()
    return base64.b64encode(digest).decode("ascii")


# ---------------------------------------------------------------------------
# HTTP client
# ---------------------------------------------------------------------------

class WebullHttpClient:
    """
    Thin signed-HTTP client for Webull OpenAPI.

    Use the module-level convenience functions in `engine/webull.py`
    (list_accounts_remote, etc.) rather than constructing this directly,
    unless you're writing a test.
    """

    def __init__(
        self,
        *,
        app_key: Optional[str] = None,
        app_secret: Optional[str] = None,
        base_url: Optional[str] = None,
        access_token: Optional[str] = None,
        timeout: float = 15.0,
    ) -> None:
        self._app_key = app_key if app_key is not None else WEBULL_APP_KEY
        self._app_secret = app_secret if app_secret is not None else WEBULL_APP_SECRET
        self._access_token = access_token if access_token is not None else WEBULL_ACCESS_TOKEN
        self._base_url = (base_url or resolve_base_url()).rstrip("/")
        self._timeout = timeout

        if not (self._app_key and self._app_secret):
            raise WebullClientError("Webull credentials are not configured")

    # -- request building ----------------------------------------------------

    def _host_for_signature(self) -> str:
        """Just the host portion of base_url, no scheme/port. Used as a signed header."""
        parsed = urllib.parse.urlparse(self._base_url)
        return parsed.hostname or ""

    def _build_signed_headers(
        self,
        *,
        path: str,
        query_params: dict[str, Any],
        body_string: Optional[str],
    ) -> dict[str, str]:
        timestamp = iso8601_utc_now()
        nonce = make_nonce()
        signing_headers = {
            "x-app-key": self._app_key,
            "x-signature-algorithm": SIGNATURE_ALGORITHM,
            "x-signature-version": SIGNATURE_VERSION,
            "x-signature-nonce": nonce,
            "x-timestamp": timestamp,
            "host": self._host_for_signature(),
        }
        encoded = build_canonical_string(
            path=path,
            query_params=query_params,
            signing_headers=signing_headers,
            body_string=body_string,
        )
        signature = compute_signature(app_secret=self._app_secret, encoded_string=encoded)

        # Headers actually sent on the wire (signature + non-signed extras)
        wire_headers: dict[str, str] = {
            **signing_headers,
            "x-signature": signature,
            "x-version": API_VERSION_HEADER,
            "Accept": "application/json",
        }
        # Drop 'host' from wire_headers — httpx sets it automatically and
        # duplicates can confuse some servers. It still participated in the
        # signature calculation above, which is the part that matters.
        wire_headers.pop("host", None)

        if body_string is not None:
            wire_headers["Content-Type"] = "application/json"
        if self._access_token:
            wire_headers["x-access-token"] = self._access_token
        return wire_headers

    # -- public methods ------------------------------------------------------

    def get(self, path: str, *, query: Optional[dict[str, Any]] = None) -> Any:
        query = {k: v for k, v in (query or {}).items() if v is not None}
        headers = self._build_signed_headers(path=path, query_params=query, body_string=None)
        url = self._base_url + path
        try:
            with httpx.Client(timeout=self._timeout) as client:
                resp = client.get(url, params=query, headers=headers)
        except httpx.HTTPError as exc:
            raise WebullClientError(_sanitize(str(exc))) from exc
        return _decode_response(resp)

    def post(self, path: str, *, body: Optional[dict[str, Any]] = None) -> Any:
        body_string = serialize_body(body)
        headers = self._build_signed_headers(path=path, query_params={}, body_string=body_string)
        url = self._base_url + path
        try:
            with httpx.Client(timeout=self._timeout) as client:
                resp = client.request(
                    "POST", url,
                    headers=headers,
                    content=body_string.encode("utf-8") if body_string else None,
                )
        except httpx.HTTPError as exc:
            raise WebullClientError(_sanitize(str(exc))) from exc
        return _decode_response(resp)

    # -- introspection helpers (for /webull/health diagnostics) --------------

    def describe(self) -> dict[str, Any]:
        """Returns the active config (NO secrets) for diagnostic display."""
        return {
            "base_url": self._base_url,
            "region": WEBULL_REGION_ID,
            "environment": WEBULL_ENVIRONMENT,
            "has_access_token": bool(self._access_token),
            "api_version": API_VERSION_HEADER,
            "signature_algorithm": SIGNATURE_ALGORITHM,
        }


def _decode_response(resp: httpx.Response) -> Any:
    """
    Decode a Webull response. Webull typically wraps payloads as:
       { "code": "200", "msg": "success", "data": {...} }
    On non-2xx HTTP, or a non-success code field, raise WebullClientError.
    """
    # Trap non-2xx first
    if resp.status_code >= 400:
        snippet = (resp.text or "")[:400]
        raise WebullClientError(
            f"Webull HTTP {resp.status_code} on {resp.request.method} {resp.request.url.path}: {_sanitize(snippet)}"
        )
    try:
        payload = resp.json()
    except ValueError as exc:
        raise WebullClientError(f"Non-JSON response from Webull: {_sanitize(str(exc))}") from exc

    # Webull-style success envelope (best-effort — older endpoints may differ)
    if isinstance(payload, dict):
        code = payload.get("code")
        if code is not None and str(code) not in ("200", "0", "success", "SUCCESS"):
            msg = _sanitize(str(payload.get("msg") or payload.get("message") or ""))
            raise WebullClientError(f"Webull error code={code} msg={msg}")
        # If a `data` envelope exists, return its contents; otherwise the raw dict.
        if "data" in payload and len(payload) <= 4:
            return payload["data"]
    return payload
