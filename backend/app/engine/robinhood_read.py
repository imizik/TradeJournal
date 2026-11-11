"""The read-only Robinhood connection (docs/robinhood-read-feed.md): the one module that speaks to Robinhood.

Robinhood's agent connection (an MCP server over streamable HTTP) has one sign-in scope and no read-only version:
the same sign-in that reads the owner's accounts can place, cancel and exercise orders. This module is the guard.

- ``READ_TOOLS`` is a hard-coded allowlist of the read tools the desk's feed needs. ``_call`` is the only function that
  builds a ``tools/call`` and refuses any other name before any network I/O; ``_post`` (every byte sent to Robinhood
  passes through it) refuses again on the bytes themselves: only ``initialize``, ``notifications/initialized`` and a
  ``tools/call`` of an allowlisted name may reach the MCP endpoint, and only a ``refresh_token`` grant the token
  endpoint. There is no generic "call this tool" entry point: callers get the named read functions on ``Reader``, and
  no tool name comes from a request, configuration, the environment or a model.
- The sign-in lives in one file (``ROBINHOOD_TOKEN_FILE``), never in the database: owned by the service user, mode
  0600, refused when wider. It is renewed a day before it expires and written back atomically. Any renewal failure
  (or a 401) marks it expired and stops every call until a new file is put in place: no retry storm. No token appears
  in a log line, an exception, a repr or anything this module returns.
- Every result's ``guide`` text (Robinhood's instructions to an AI agent) is dropped here; callers get ``data`` only,
  as third-party data.

Stdlib only.
"""

from __future__ import annotations

import json
import logging
import os
import stat
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

MCP_URL = "https://agent.robinhood.com/mcp/trading"
TOKEN_URL = "https://api.robinhood.com/oauth2/token/"
PROTOCOL = "2025-06-18"
CLIENT_INFO = {"name": "TradeJournal read-only feed", "version": "1"}

# The only tools this app may ever call. Each reads; none changes or trades anything. Adding a name here is a
# consequential, user-gated change (tests/test_robinhood_read.py fails on any name that looks like a write).
READ_TOOLS = frozenset({
    "get_accounts",
    "get_portfolio",
    "get_option_positions",
    "get_option_instruments",
    "get_option_quotes",
    "get_equity_positions",
    "get_equity_quotes",
})
MCP_METHODS = frozenset({"initialize", "notifications/initialized", "tools/call"})

TIMEOUT_SECONDS = 15
RENEW_BEFORE_SECONDS = 24 * 3600  # the sign-in lasts about five days; renew on the last day
MAX_TOKEN_FILE_BYTES = 64 * 1024
MAX_REPLY_BYTES = 4 * 1024 * 1024


class ReadError(Exception):
    """A read that did not happen. ``kind``: ``refused`` (not a read tool), ``signed_out`` (no usable sign-in file),
    ``expired`` (the sign-in ended or renewal failed), ``http``, ``network`` or ``shape``. The message never carries a
    token or a reply body."""

    def __init__(self, kind: str, detail: str = ""):
        super().__init__(f"{kind}: {detail}" if detail else kind)
        self.kind = kind
        self.detail = detail


class RefusedTool(ReadError):
    def __init__(self, name: object):
        super().__init__("refused", f"{str(name)[:60]!r} is not a read tool on the allowlist")


# --------------------------------------------------------------------------- the wire

def _transport(url: str, body: bytes, headers: dict[str, str]) -> tuple[int, dict[str, str], str]:
    """One HTTPS POST. Tests replace this with a fake server; nothing else in the app sends to Robinhood."""
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as reply:  # noqa: S310 - fixed https URLs only
            return reply.status, dict(reply.headers), reply.read(MAX_REPLY_BYTES).decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers or {}), ""  # an error body is never read: it may echo the request
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ReadError("network", type(exc).__name__) from None


def _post(url: str, body: bytes, headers: dict[str, str]) -> tuple[int, dict[str, str], str]:
    """Every byte bound for Robinhood passes here, and is checked on its way out."""
    if url == MCP_URL:
        try:
            message = json.loads(body)
        except ValueError:
            raise ReadError("refused", "not a JSON-RPC message") from None
        if not isinstance(message, dict) or message.get("method") not in MCP_METHODS:
            raise ReadError("refused", "not an allowed MCP method")
        if message["method"] == "tools/call":
            name = (message.get("params") or {}).get("name") if isinstance(message.get("params"), dict) else None
            if name not in READ_TOOLS:
                raise RefusedTool(name)
    elif url == TOKEN_URL:
        form = urllib.parse.parse_qs(body.decode("ascii", "replace"))
        if form.get("grant_type") != ["refresh_token"]:
            raise ReadError("refused", "only a sign-in renewal may go to the token endpoint")
    else:
        raise ReadError("refused", "not a Robinhood endpoint this app reads")
    return _transport(url, body, headers)


# --------------------------------------------------------------------------- the sign-in file

@dataclass
class Signin:
    """The stored sign-in. Its repr shows no token."""
    access_token: str = field(repr=False)
    refresh_token: str = field(repr=False)
    expires_at: float
    client_id: str = field(repr=False)


def _signature(st: os.stat_result) -> tuple:
    return (st.st_ino, st.st_mtime_ns, st.st_size)


class TokenFile:
    """The sign-in file at ``path``: read only when it is a regular file owned by this process's user with no group or
    other permission bits; written back through a 0600 temporary file in the same folder and an atomic rename."""

    def __init__(self, path: str | os.PathLike):
        self.path = Path(path)

    def stat(self) -> os.stat_result | None:
        try:
            return os.stat(self.path, follow_symlinks=False)
        except OSError:
            return None

    def read(self) -> tuple[Signin, tuple]:
        try:
            fd = os.open(self.path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        except FileNotFoundError:
            raise ReadError("signed_out", "no sign-in file") from None
        except OSError:
            raise ReadError("signed_out", "the sign-in file cannot be opened") from None
        try:
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode):
                raise ReadError("signed_out", "the sign-in file is not a regular file")
            if st.st_uid != os.geteuid():
                raise ReadError("signed_out", "the sign-in file belongs to another user")
            if st.st_mode & 0o077:
                raise ReadError("signed_out", "the sign-in file is readable by others (needs mode 0600)")
            raw = os.read(fd, MAX_TOKEN_FILE_BYTES + 1)
        finally:
            os.close(fd)
        if len(raw) > MAX_TOKEN_FILE_BYTES:
            raise ReadError("signed_out", "the sign-in file is too large")
        try:
            data = json.loads(raw)
            signin = Signin(access_token=str(data["access_token"]), refresh_token=str(data.get("refresh_token") or ""),
                            expires_at=float(data["expires_at"]), client_id=str(data.get("client_id") or ""))
        except (ValueError, KeyError, TypeError):
            raise ReadError("signed_out", "the sign-in file does not hold a sign-in") from None
        if not signin.access_token:
            raise ReadError("signed_out", "the sign-in file does not hold a sign-in")
        return signin, _signature(st)

    def write(self, signin: Signin) -> tuple:
        """Atomically replace the file; returns the new file's signature."""
        body = json.dumps({"access_token": signin.access_token, "refresh_token": signin.refresh_token,
                           "expires_at": int(signin.expires_at), "client_id": signin.client_id}).encode()
        tmp = self.path.with_name(f".{self.path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            os.fchmod(fd, 0o600)
            os.write(fd, body)
            os.fsync(fd)
        except BaseException:
            os.close(fd)
            tmp.unlink(missing_ok=True)
            raise
        os.close(fd)
        try:
            os.replace(tmp, self.path)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        try:
            dir_fd = os.open(self.path.parent, os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError:
            pass
        st = self.stat()
        return _signature(st) if st else ()


class Sign:
    """The feed's sign-in state over one ``TokenFile``. Once renewal fails (or Robinhood answers 401) it is expired and
    every call refuses without touching the network, until the file itself changes (a new sign-in put in place)."""

    def __init__(self, path: str | os.PathLike, now=time.time):
        self.file = TokenFile(path)
        self._now = now
        self._lock = threading.Lock()
        self._dead: tuple | None = None  # the file signature that was found expired

    @property
    def expired(self) -> bool:
        st = self.file.stat()
        return self._dead is not None and st is not None and _signature(st) == self._dead

    def expire(self, signature: tuple | None = None) -> None:
        st = self.file.stat()
        self._dead = signature or (_signature(st) if st else ("missing",))

    def access_token(self) -> str:
        with self._lock:
            signin, signature = self.file.read()
            if self._dead is not None:
                if signature == self._dead:
                    raise ReadError("expired", "sign in again")
                self._dead = None  # a new file: try it
            if signin.expires_at - self._now() > RENEW_BEFORE_SECONDS:
                return signin.access_token
            try:
                renewed = self._renew(signin)
            except ReadError as exc:
                log.warning("Robinhood sign-in renewal failed (%s); the feed stops until a new sign-in", exc.kind)
                self._dead = signature
                raise ReadError("expired", "renewal failed; sign in again") from None
            self.file.write(renewed)
            log.info("Robinhood sign-in renewed")
            return renewed.access_token

    def _renew(self, signin: Signin) -> Signin:
        if not signin.refresh_token or not signin.client_id:
            raise ReadError("expired", "nothing to renew with")
        form = urllib.parse.urlencode({"grant_type": "refresh_token", "refresh_token": signin.refresh_token,
                                       "client_id": signin.client_id, "resource": MCP_URL}).encode()
        status, _headers, text = _post(TOKEN_URL, form, {"Content-Type": "application/x-www-form-urlencoded",
                                                        "Accept": "application/json"})
        if status != 200:
            raise ReadError("http", f"token endpoint status {status}")
        try:
            got = json.loads(text)
            access, expires_in = str(got["access_token"]), float(got["expires_in"])
        except (ValueError, KeyError, TypeError):
            raise ReadError("shape", "token endpoint reply") from None
        if not access or expires_in <= 0:
            raise ReadError("shape", "token endpoint reply")
        return Signin(access_token=access, refresh_token=str(got.get("refresh_token") or signin.refresh_token),
                      expires_at=self._now() + expires_in, client_id=signin.client_id)


# --------------------------------------------------------------------------- the MCP session and the read tools

def _reply(text: str) -> dict | None:
    """The JSON-RPC reply: plain JSON, or an event stream of ``data:`` lines (the last JSON message wins)."""
    found = None
    for line in text.splitlines():
        line = line[5:].strip() if line.startswith("data:") else line.strip()
        if line.startswith("{"):
            try:
                found = json.loads(line)
            except ValueError:
                continue
    return found


class Reader:
    """One MCP session's read calls, opened lazily. ``calls`` counts every ``tools/call`` sent; ``max_calls`` bounds
    them (a refresh never sends more)."""

    def __init__(self, sign: Sign, max_calls: int = 40):
        self.sign = sign
        self.max_calls = max_calls
        self.calls = 0
        self._session: str | None = None
        self._opened = False
        self._id = 0

    def _send(self, method: str, params: dict | None, notify: bool = False) -> dict | None:
        token = self.sign.access_token()
        body: dict = {"jsonrpc": "2.0", "method": method}
        if not notify:
            self._id += 1
            body["id"] = self._id
        if params is not None:
            body["params"] = params
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
                   "Authorization": f"Bearer {token}", "MCP-Protocol-Version": PROTOCOL}
        if self._session:
            headers["Mcp-Session-Id"] = self._session
        status, reply_headers, text = _post(MCP_URL, json.dumps(body).encode(), headers)
        session = next((v for k, v in reply_headers.items() if k.lower() == "mcp-session-id"), None)
        if session:
            self._session = session
        if status == 401:
            self.sign.expire()
            raise ReadError("expired", "Robinhood refused the sign-in")
        if notify:
            return None
        if status != 200:
            raise ReadError("http", f"status {status}")
        reply = _reply(text)
        if not isinstance(reply, dict) or "result" not in reply:
            raise ReadError("shape", "no JSON-RPC result")
        return reply["result"]

    def _open(self) -> None:
        if self._opened:
            return
        self._send("initialize", {"protocolVersion": PROTOCOL, "capabilities": {}, "clientInfo": CLIENT_INFO})
        self._send("notifications/initialized", None, notify=True)
        self._opened = True

    def _call(self, name: str, arguments: dict) -> dict:
        """The only place a ``tools/call`` is built. Refuses a name off the allowlist before any I/O."""
        if name not in READ_TOOLS:
            raise RefusedTool(name)
        if self.calls >= self.max_calls:
            raise ReadError("refused", "call budget for this refresh spent")
        self._open()
        self.calls += 1
        result = self._send("tools/call", {"name": name, "arguments": arguments})
        if not isinstance(result, dict) or result.get("isError"):
            raise ReadError("shape", f"{name} returned an error")
        content = result.get("content")
        text = next((c.get("text") for c in content if isinstance(c, dict) and c.get("type") == "text"), None) \
            if isinstance(content, list) else None
        try:
            payload = json.loads(text) if isinstance(text, str) else None
        except ValueError:
            payload = None
        if not isinstance(payload, dict):
            raise ReadError("shape", f"{name} reply")
        data = payload.get("data", payload) if "data" in payload else {k: v for k, v in payload.items() if k != "guide"}
        if not isinstance(data, dict):
            raise ReadError("shape", f"{name} data")
        return data  # the ``guide`` text is dropped here and never reaches a caller

    # The read functions. Account numbers pass through to Robinhood; nothing here returns them beyond the raw data.
    def get_accounts(self) -> dict:
        return self._call("get_accounts", {})

    def get_portfolio(self, account_number: str) -> dict:
        return self._call("get_portfolio", {"account_number": str(account_number)})

    def get_option_positions(self, account_number: str, cursor: str | None = None) -> dict:
        return self._call("get_option_positions", {"account_number": str(account_number), "nonzero": True,
                                                   **({"cursor": str(cursor)} if cursor else {})})

    def get_equity_positions(self, account_number: str, cursor: str | None = None) -> dict:
        return self._call("get_equity_positions", {"account_number": str(account_number), **({"cursor": str(cursor)} if cursor else {})})

    def get_option_instruments(self, ids: list[str]) -> dict:
        return self._call("get_option_instruments", {"ids": ",".join(str(i) for i in ids)})

    def get_option_quotes(self, ids: list[str]) -> dict:
        return self._call("get_option_quotes", {"instrument_ids": [str(i) for i in ids]})

    def get_equity_quotes(self, symbols: list[str]) -> dict:
        return self._call("get_equity_quotes", {"symbols": [str(s) for s in symbols]})
