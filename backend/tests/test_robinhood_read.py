"""The read-only Robinhood client (app/engine/robinhood_read.py): the allowlist, the guard on the wire, and the sign-in
file. Runs against tests/robinhood_fake.py; nothing here reaches Robinhood."""

import json
import logging
import os
from pathlib import Path
import re
import stat

import pytest

from app.engine import robinhood_read as rh
from tests.robinhood_fake import ACCESS, GUIDE, RENEWED, RENEWED_REFRESH, SECRETS, FakeRobinhood, token_file

REPO = Path(__file__).resolve().parents[2]
WRITE_PREFIXES = ("place_", "cancel_", "exercise", "create_", "update_", "delete_", "add_", "remove_", "decline_",
                  "follow", "unfollow", "set_", "mark_", "review_", "preview_")
# Every tool the live connection listed on 2026-11-11 that changes or trades something, by name.
WRITE_TOOLS = (
    "place_option_order", "place_equity_order", "place_crypto_order", "place_advanced_order", "cancel_option_order",
    "cancel_equity_order", "cancel_crypto_order", "cancel_advanced_order", "cancel_option_exercise", "exercise_option",
    "create_alert", "create_scan", "create_watchlist", "update_alert", "update_watchlist", "update_scan_config",
    "update_scan_filters", "update_legend_indicator", "delete_alert", "add_to_watchlist", "add_option_to_watchlist",
    "add_legend_indicator", "remove_from_watchlist", "remove_option_from_watchlist", "remove_legend_indicator",
    "decline_trade_approval", "follow_watchlist", "unfollow_watchlist", "set_legend_chart_settings", "mark_alerts_read",
    "review_option_order", "review_equity_order", "review_advanced_order", "preview_crypto_order", "preview_scan",
)


@pytest.fixture
def fake(monkeypatch):
    server = FakeRobinhood()
    monkeypatch.setattr(rh, "_transport", server.transport)
    return server


@pytest.fixture
def sign(tmp_path):
    return rh.Sign(token_file(tmp_path / "robinhood-token.json"))


# --------------------------------------------------------------------------- the allowlist

def test_the_allowlist_is_exactly_the_reads_and_holds_no_write():
    assert rh.READ_TOOLS == {"get_accounts", "get_portfolio", "get_option_positions", "get_option_instruments",
                             "get_option_quotes", "get_equity_positions", "get_equity_quotes"}
    for name in rh.READ_TOOLS:
        assert name.startswith("get_") and not any(p in name for p in WRITE_PREFIXES), name


@pytest.mark.parametrize("name", WRITE_TOOLS + tuple(p + "anything" for p in WRITE_PREFIXES) + ("", "tools/list", "GET_ACCOUNTS", None))
def test_every_changing_or_trading_tool_is_refused_before_any_network(name, sign, monkeypatch):
    sent = []
    monkeypatch.setattr(rh, "_transport", lambda *a: sent.append(a) or (200, {}, ""))
    monkeypatch.setattr(rh.Sign, "access_token", lambda self: pytest.fail("the sign-in was read for a refused tool"))
    with pytest.raises(rh.RefusedTool):
        rh.Reader(sign)._call(name, {"account_number": "444447884"})
    assert sent == []


@pytest.mark.parametrize("name", WRITE_TOOLS[:6])
def test_the_wire_refuses_a_write_even_past_the_reader(name, monkeypatch):
    sent = []
    monkeypatch.setattr(rh, "_transport", lambda *a: sent.append(a) or (200, {}, ""))
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": {}}}).encode()
    with pytest.raises(rh.RefusedTool):
        rh._post(rh.MCP_URL, body, {})
    for bad in (b"[{\"method\": \"tools/call\"}]", b"not json", json.dumps({"method": "tools/list"}).encode(),
                json.dumps({"method": "resources/read"}).encode()):
        with pytest.raises(rh.ReadError):
            rh._post(rh.MCP_URL, bad, {})
    with pytest.raises(rh.ReadError):
        rh._post("https://example.com/mcp", b"{}", {})
    with pytest.raises(rh.ReadError):  # the token endpoint takes a renewal only
        rh._post(rh.TOKEN_URL, b"grant_type=authorization_code&code=x", {})
    assert sent == []


def test_no_generic_call_entry_point():
    public = {n for n in vars(rh.Reader) if not n.startswith("_")}
    assert public == {"get_accounts", "get_portfolio", "get_option_positions", "get_equity_positions",
                      "get_option_instruments", "get_option_quotes", "get_equity_quotes"}


def _app_files():
    roots = [REPO / "backend" / "app", REPO / "backend" / "scripts", REPO / "scripts", REPO / "frontend" / "app",
             REPO / "frontend" / "components", REPO / "frontend" / "lib", REPO / "deploy"]
    for root in roots:
        if root.exists():
            yield from (p for p in root.rglob("*") if p.is_file() and p.suffix in (".py", ".ts", ".tsx", ".js", ".sh", ".json", ".env", ".example"))


def test_only_the_client_names_the_endpoint_or_builds_a_tools_call():
    client = REPO / "backend" / "app" / "engine" / "robinhood_read.py"
    signin = REPO / "backend" / "scripts" / "robinhood_signin.py"  # needs the endpoint as the sign-in's resource; sends no call
    endpoint, call, users = [], [], []
    for path in _app_files():
        text = path.read_text(errors="ignore")
        if "agent.robinhood.com" in text or "api.robinhood.com" in text:
            endpoint.append(path)
        # The app's own MCP servers' smoke checks under deploy/ build tools/call for those servers, never Robinhood's.
        if "tools/call" in text and (path.is_relative_to(REPO / "backend") or "robinhood" in text.lower()):
            call.append(path)
        if "robinhood_read" in text and path != client:
            users.append(path.relative_to(REPO).as_posix())
    assert sorted(endpoint) == sorted([client, signin])
    assert call == [client]
    assert "tools/call" not in signin.read_text() and "_transport" not in signin.read_text()
    assert users == ["backend/app/engine/robinhood_book.py"]  # the feed is the client's one caller


# --------------------------------------------------------------------------- a read on the wire

@pytest.mark.parametrize("sse", [False, True])
def test_a_read_opens_a_session_sends_its_header_and_drops_the_guide(fake, sign, sse):
    fake.sse = sse
    reader = rh.Reader(sign)
    data = reader.get_accounts()
    assert [a["account_number"][-4:] for a in data["accounts"]] == ["8888", "8267", "7884"]
    assert "guide" not in data and GUIDE not in json.dumps(data)
    reader.get_portfolio("333338267")
    assert fake.methods == ["initialize", "notifications/initialized", "tools/call", "tools/call"]
    assert fake.sessions_seen == [None, "session-1", "session-1", "session-1"]
    assert reader.calls == 2


def test_the_call_budget_bounds_a_reader(fake, sign):
    reader = rh.Reader(sign, max_calls=2)
    reader.get_accounts()
    reader.get_accounts()
    with pytest.raises(rh.ReadError) as exc:
        reader.get_accounts()
    assert exc.value.kind == "refused" and len(fake.calls) == 2


def test_an_error_reply_or_a_bad_shape_is_unavailable_not_empty(fake, sign):
    fake.fail.add("get_portfolio")
    with pytest.raises(rh.ReadError) as exc:
        rh.Reader(sign).get_portfolio("333338267")
    assert exc.value.kind == "http"
    fake.tool_get_accounts = lambda args: ["not", "a", "dict"]
    with pytest.raises(rh.ReadError) as exc:
        rh.Reader(sign).get_accounts()
    assert exc.value.kind == "shape"


# --------------------------------------------------------------------------- the sign-in file

def test_a_missing_or_open_sign_in_file_is_refused(tmp_path, fake):
    with pytest.raises(rh.ReadError) as exc:
        rh.Sign(tmp_path / "none.json").access_token()
    assert exc.value.kind == "signed_out"
    for mode in (0o640, 0o604, 0o660, 0o644):
        path = token_file(tmp_path / f"open-{mode:o}.json", mode=mode)
        with pytest.raises(rh.ReadError) as exc:
            rh.Sign(path).access_token()
        assert exc.value.kind == "signed_out" and "0600" in str(exc.value)
    link = tmp_path / "link.json"
    link.symlink_to(token_file(tmp_path / "real.json"))
    with pytest.raises(rh.ReadError):
        rh.Sign(link).access_token()
    garbage = tmp_path / "garbage.json"
    garbage.write_text("{")
    os.chmod(garbage, 0o600)
    with pytest.raises(rh.ReadError):
        rh.Sign(garbage).access_token()
    assert fake.methods == [] and fake.token_posts == []


def test_a_fresh_sign_in_is_used_as_is(sign, fake):
    assert sign.access_token() == ACCESS and fake.token_posts == []


def test_a_sign_in_near_expiry_is_renewed_and_written_back_atomically_with_0600(tmp_path, fake, monkeypatch):
    path = token_file(tmp_path / "t.json", expires_in=3600)
    before = os.stat(path).st_ino
    replaced = []
    real = os.replace
    monkeypatch.setattr(rh.os, "replace", lambda a, b: replaced.append((Path(a).name, Path(b).name)) or real(a, b))
    assert rh.Sign(path).access_token() == RENEWED
    [form] = fake.token_posts
    assert form["grant_type"] == "refresh_token" and form["client_id"] == "public-client-id" and form["resource"] == rh.MCP_URL
    saved = json.loads(path.read_text())
    assert (saved["access_token"], saved["refresh_token"]) == (RENEWED, RENEWED_REFRESH) and saved["expires_at"] > 400000
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600 and os.stat(path).st_ino != before
    assert replaced and replaced[0][1] == "t.json" and replaced[0][0].endswith(".tmp")
    assert [p.name for p in tmp_path.iterdir()] == ["t.json"]  # no temporary file left behind
    assert rh.Sign(path).access_token() == RENEWED and len(fake.token_posts) == 1


def test_a_failed_renewal_expires_the_feed_without_a_retry_storm(tmp_path, fake):
    path = token_file(tmp_path / "t.json", expires_in=3600)
    fake.token_status = 400
    sign = rh.Sign(path)
    for _ in range(5):
        with pytest.raises(rh.ReadError) as exc:
            rh.Reader(sign).get_accounts()
        assert exc.value.kind == "expired"
    assert len(fake.token_posts) == 1 and fake.methods == [] and sign.expired
    token_file(path, expires_in=4 * 86400)  # a new sign-in put in place
    fake.token_status = 200
    assert not sign.expired and rh.Reader(sign).get_accounts()["accounts"]


def test_an_expired_sign_in_with_no_refresh_token_stops(tmp_path, fake):
    path = tmp_path / "t.json"
    path.write_text(json.dumps({"access_token": ACCESS, "expires_at": 1, "client_id": "x"}))
    os.chmod(path, 0o600)
    with pytest.raises(rh.ReadError) as exc:
        rh.Sign(path).access_token()
    assert exc.value.kind == "expired" and fake.token_posts == []


def test_a_401_from_robinhood_marks_the_sign_in_expired(fake, sign):
    fake.status = 401
    with pytest.raises(rh.ReadError) as exc:
        rh.Reader(sign).get_accounts()
    assert exc.value.kind == "expired"
    fake.status = 200
    with pytest.raises(rh.ReadError):
        rh.Reader(sign).get_accounts()
    assert fake.methods == ["initialize"]  # nothing more was sent


def test_no_token_in_a_log_line_an_error_or_a_repr(tmp_path, fake, caplog):
    caplog.set_level(logging.DEBUG)
    path = token_file(tmp_path / "t.json", expires_in=3600)
    sign = rh.Sign(path)
    rh.Reader(sign).get_accounts()  # renewed
    token_file(path, expires_in=3600)
    fake.token_status = 500
    errors = []
    for _ in range(2):
        try:
            rh.Reader(rh.Sign(path)).get_accounts()
        except rh.ReadError as exc:
            errors.append(f"{exc!r} {exc} {exc.detail}")
    signin, _ = rh.TokenFile(path).read()
    text = caplog.text + " ".join(errors) + repr(signin)
    assert errors and not any(secret in text for secret in SECRETS)
    assert "public-client-id" not in repr(signin)


def test_the_sign_in_never_appears_in_a_test_fixture_or_the_repo():
    pattern = re.compile(r"(access|refresh)_token\"?\s*[:=]\s*\"[A-Za-z0-9_\-\.]{30,}\"")
    for path in _app_files():
        assert not pattern.search(path.read_text(errors="ignore")), path
