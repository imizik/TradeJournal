"""
Tests for the Webull request signer.

Strategy: lock down each primitive against deterministic inputs so we catch
any drift (param ordering, body MD5 case, signing-key trailing '&',
encoding scope). The exact signature byte the server expects is not
predictable from the docs alone — but the steps each primitive performs
ARE deterministic and individually testable.
"""

from __future__ import annotations

import base64
import hashlib
import hmac

import pytest

from app.engine.webull_client import (
    WebullHttpClient,
    build_canonical_string,
    compute_signature,
    md5_upper,
    serialize_body,
)


# ---------------------------------------------------------------------------
# Primitive: body serialization + MD5
# ---------------------------------------------------------------------------

def test_serialize_body_uses_compact_separators() -> None:
    assert serialize_body({"a": 1, "b": "x"}) == '{"a":1,"b":"x"}'


def test_serialize_body_handles_none_and_string_passthrough() -> None:
    assert serialize_body(None) is None
    assert serialize_body("raw_already") == "raw_already"


def test_md5_upper_returns_uppercase_hex() -> None:
    out = md5_upper("hello")
    assert out == "5D41402ABC4B2A76B9719D911017C592"
    assert out == out.upper()


# ---------------------------------------------------------------------------
# Primitive: canonical string
# ---------------------------------------------------------------------------

def test_canonical_string_sorts_merged_params_and_excludes_signature() -> None:
    encoded = build_canonical_string(
        path="/openapi/account/list",
        query_params={"region": "us"},
        signing_headers={
            "x-app-key": "KEY123",
            "x-signature-algorithm": "HMAC-SHA1",
            "x-signature-version": "1.0",
            "x-signature-nonce": "abc",
            "x-timestamp": "2025-11-13T01:37:20Z",
            "host": "api.webull.com",
        },
        body_string=None,
    )
    # URL-decode to make assertions readable
    import urllib.parse
    decoded = urllib.parse.unquote(encoded)
    # Path comes first, then '&', then sorted k=v pairs
    assert decoded.startswith("/openapi/account/list&")
    # Sorted alphabetically: host, region, x-app-key, x-signature-algorithm,
    # x-signature-nonce, x-signature-version, x-timestamp
    expected_tail = (
        "host=api.webull.com&"
        "region=us&"
        "x-app-key=KEY123&"
        "x-signature-algorithm=HMAC-SHA1&"
        "x-signature-nonce=abc&"
        "x-signature-version=1.0&"
        "x-timestamp=2025-11-13T01:37:20Z"
    )
    assert decoded == f"/openapi/account/list&{expected_tail}"
    # And x-signature is NOT in the canonical string.
    assert "x-signature=" not in decoded or "x-signature-" in decoded


def test_canonical_string_appends_body_md5_when_body_present() -> None:
    body = '{"k":"v"}'
    encoded = build_canonical_string(
        path="/openapi/trade/test",
        query_params={},
        signing_headers={
            "x-app-key": "KEY",
            "x-signature-algorithm": "HMAC-SHA1",
            "x-signature-version": "1.0",
            "x-signature-nonce": "nonce",
            "x-timestamp": "2025-01-01T00:00:00Z",
            "host": "host.example",
        },
        body_string=body,
    )
    import urllib.parse
    decoded = urllib.parse.unquote(encoded)
    assert decoded.endswith("&" + md5_upper(body))


def test_canonical_string_url_encodes_everything() -> None:
    encoded = build_canonical_string(
        path="/p",
        query_params={},
        signing_headers={
            "x-app-key": "K",
            "x-signature-algorithm": "HMAC-SHA1",
            "x-signature-version": "1.0",
            "x-signature-nonce": "n",
            "x-timestamp": "2025-01-01T00:00:00Z",
            "host": "h",
        },
        body_string=None,
    )
    # '/' '&' '=' must be percent-encoded (safe="")
    assert "/" not in encoded
    assert "&" not in encoded
    assert "=" not in encoded


# ---------------------------------------------------------------------------
# Primitive: signature
# ---------------------------------------------------------------------------

def test_compute_signature_uses_app_secret_plus_ampersand_as_key() -> None:
    """The trailing '&' on the signing key is per the Webull spec."""
    secret = "S3CR3T"
    msg = "hello"
    expected = base64.b64encode(
        hmac.new((secret + "&").encode("utf-8"), msg.encode("utf-8"), hashlib.sha1).digest()
    ).decode("ascii")
    assert compute_signature(app_secret=secret, encoded_string=msg) == expected


def test_compute_signature_is_deterministic() -> None:
    a = compute_signature(app_secret="X", encoded_string="msg")
    b = compute_signature(app_secret="X", encoded_string="msg")
    assert a == b


# ---------------------------------------------------------------------------
# WebullHttpClient: wire-level header construction
# ---------------------------------------------------------------------------

def test_client_builds_signed_headers_for_get(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.engine.webull_client.iso8601_utc_now", lambda: "2025-01-01T00:00:00Z")
    monkeypatch.setattr("app.engine.webull_client.make_nonce", lambda: "FIXED_NONCE")

    client = WebullHttpClient(
        app_key="TEST_KEY",
        app_secret="TEST_SECRET",
        base_url="https://api.example.com",
    )
    headers = client._build_signed_headers(
        path="/openapi/account/list",
        query_params={},
        body_string=None,
    )

    # Required wire headers
    assert headers["x-app-key"] == "TEST_KEY"
    assert headers["x-timestamp"] == "2025-01-01T00:00:00Z"
    assert headers["x-signature-algorithm"] == "HMAC-SHA1"
    assert headers["x-signature-version"] == "1.0"
    assert headers["x-signature-nonce"] == "FIXED_NONCE"
    assert headers["x-version"] == "v2"
    assert "x-signature" in headers
    assert headers["x-signature"]  # non-empty
    # 'host' was used for signing but should NOT be set as a wire header (httpx sets it)
    assert "host" not in headers
    # GET has no Content-Type
    assert "Content-Type" not in headers

    # Signature must match the canonical-string + HMAC pipeline we expose
    expected_canonical = build_canonical_string(
        path="/openapi/account/list",
        query_params={},
        signing_headers={
            "x-app-key": "TEST_KEY",
            "x-signature-algorithm": "HMAC-SHA1",
            "x-signature-version": "1.0",
            "x-signature-nonce": "FIXED_NONCE",
            "x-timestamp": "2025-01-01T00:00:00Z",
            "host": "api.example.com",
        },
        body_string=None,
    )
    expected_sig = compute_signature(app_secret="TEST_SECRET", encoded_string=expected_canonical)
    assert headers["x-signature"] == expected_sig


def test_client_sets_content_type_when_body_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.engine.webull_client.iso8601_utc_now", lambda: "2025-01-01T00:00:00Z")
    monkeypatch.setattr("app.engine.webull_client.make_nonce", lambda: "N")

    client = WebullHttpClient(
        app_key="K",
        app_secret="S",
        base_url="https://api.example.com",
    )
    headers = client._build_signed_headers(
        path="/p",
        query_params={},
        body_string='{"x":1}',
    )
    assert headers["Content-Type"] == "application/json"


def test_client_adds_access_token_header_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.engine.webull_client.iso8601_utc_now", lambda: "2025-01-01T00:00:00Z")
    monkeypatch.setattr("app.engine.webull_client.make_nonce", lambda: "N")

    client = WebullHttpClient(
        app_key="K",
        app_secret="S",
        base_url="https://api.example.com",
        access_token="TOKEN_X",
    )
    headers = client._build_signed_headers(path="/p", query_params={}, body_string=None)
    assert headers["x-access-token"] == "TOKEN_X"


def test_client_rejects_missing_credentials() -> None:
    from app.engine.webull_client import WebullClientError
    with pytest.raises(WebullClientError):
        WebullHttpClient(app_key="", app_secret="")


# ---------------------------------------------------------------------------
# Base URL resolution
# ---------------------------------------------------------------------------

def test_resolve_base_url_picks_uat_when_env_is_uat(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib
    monkeypatch.setenv("WEBULL_ENVIRONMENT", "uat")
    monkeypatch.setenv("WEBULL_REGION_ID", "us")
    monkeypatch.setenv("WEBULL_API_BASE", "")
    # Force a module reload so the env reads happen with the patched values.
    from app.engine import webull_client as mod
    importlib.reload(mod)
    try:
        assert mod.resolve_base_url() == "https://us-openapi-alb.uat.webullbroker.com"
    finally:
        # Reload again with the original env to leave global state clean.
        importlib.reload(mod)


def test_resolve_base_url_respects_manual_override(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib
    monkeypatch.setenv("WEBULL_API_BASE", "https://custom.example.com")
    from app.engine import webull_client as mod
    importlib.reload(mod)
    try:
        assert mod.resolve_base_url() == "https://custom.example.com"
    finally:
        importlib.reload(mod)
