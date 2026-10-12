"""Manual, bounded moomoo Phase 1 probe. No app, database or provider imports.

Run from backend with the backend Python environment:
    python -m scripts.moomoo_diagnostic --configure
    python -m scripts.moomoo_diagnostic

The official Chinese authentication reference specifies the four-field
WebSocket signing payload; the English page omits that detail.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
from contextlib import suppress
from datetime import datetime, timezone
from getpass import GetPassWarning, getpass
import hashlib
import json
import logging
import math
import os
from pathlib import Path
import re
import secrets
import stat
import time
import warnings

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import httpx
from websockets.asyncio.client import connect
from websockets.exceptions import WebSocketException

HOST = "https://webapi.moomoo.com"
QUOTE_PATH = "/api/v1.0/quote/stock-quote"
BOOK_PATH = "/api/v1.0/quote/order-book"
TIME_PATH = "/api/v1.0/server-time"
SYMBOL = "US.NVDA"
# A US stock or ETF ticker in moomoo form; streaming accepts any that matches.
STREAM_SYMBOL = re.compile(r"US\.[A-Z]{1,5}(\.[A-Z])?")
KEY_DIR = Path.home() / ".config/tradejournal/moomoo"
WS_URL = "wss://webapi-quote.moomoo.com/ws"
STREAM_TYPES = ("quote", "order_book", "ticker")
# A refreshed manual session still ends by itself; it is never a background collector.
MAX_REFRESHED_SECONDS = 8 * 3600
REFRESH_ACK_SECONDS = 30
MIN_REFRESH_SECONDS = 30


class NoRedirectConnect(connect):
    """Refuse handshake redirects before any signed auth can be sent."""

    def process_redirect(self, exc: Exception) -> Exception:
        return exc


class DiagnosticError(Exception):
    """Only fixed, credential-free messages may reach this exception."""


async def bounded_await(awaitable, timeout: float):
    """Bound an operation without Python 3.11 wait_for's cancellation race.

    asyncio.wait never treats downstream cancellation as a completed result.
    Always cancel/await a pending child so no receive remains on the socket.
    """
    child = asyncio.create_task(awaitable)
    try:
        done, _ = await asyncio.wait({child}, timeout=timeout)
        if not done:
            raise asyncio.TimeoutError
        return child.result()
    finally:
        if not child.done():
            child.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await child
        elif not child.cancelled():
            child.exception()  # Retrieve any raced error without wire logging.


def secure_read(path: Path) -> bytes:
    """Reject symlinks, insecure modes and non-owned files before reading."""
    parent = path.parent.lstat()
    if not stat.S_ISDIR(parent.st_mode) or parent.st_uid != os.getuid() or parent.st_mode & 0o077:
        raise DiagnosticError("Credential directory must be owned by you with mode 0700.")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as file:
        info = os.fstat(file.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise DiagnosticError("Credential files must be owned by you with mode 0600.")
        value = file.read(16385)
        if len(value) > 16384:
            raise DiagnosticError("Credential file exceeds the size limit.")
        return value


def configure() -> None:
    # Directory and signing key are created separately during account setup.
    secure_read(KEY_DIR / "phase1-ed25519.pem")
    with warnings.catch_warnings():
        warnings.simplefilter("error", GetPassWarning)
        try:
            value = getpass("moomoo AppKey (hidden): ").strip()
        except GetPassWarning:
            raise DiagnosticError("Hidden terminal input is unavailable; AppKey was not read or saved.") from None
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", value):
        raise DiagnosticError("AppKey format is invalid; nothing saved.")
    fd = os.open(KEY_DIR / "appkey", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as file:
        file.write(value)
    print("AppKey saved privately outside Git.")


def signing_payload(timestamp_ms: int, method: str, path: str, query: str, body: bytes) -> bytes:
    """Five fields; hash the exact body bytes; preserve the raw query order."""
    digest = hashlib.sha256(body).hexdigest() if body else ""
    return "\n".join((str(timestamp_ms), method.upper(), path, query, digest)).encode("utf-8")


def sign_request(request: httpx.Request, appkey: str, key: Ed25519PrivateKey, timestamp_ms: int, nonce: str) -> None:
    if request.url.host != "webapi.moomoo.com" or request.url.scheme != "https" or request.url.port not in (None, 443):
        raise DiagnosticError("Request destination is outside the diagnostic allowlist.")
    if request.method != "POST" or request.url.path not in (QUOTE_PATH, BOOK_PATH):
        raise DiagnosticError("Only the two market-quote diagnostic endpoints are allowed.")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", nonce):
        raise DiagnosticError("Nonce format is invalid.")
    # raw_path includes the percent-encoded path; query is the final wire query.
    path = request.url.raw_path.split(b"?", 1)[0].decode("ascii")
    payload = signing_payload(timestamp_ms, request.method, path, request.url.query.decode("ascii"), request.content)
    request.headers.update({
        "X-Api-Key": appkey,
        "X-Timestamp": str(timestamp_ms),
        "X-Nonce": nonce,
        "Authorization": base64.b64encode(key.sign(payload)).decode("ascii"),
    })


def number(value):
    # Never copy arbitrary provider strings into diagnostic output.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, int):
        return value if -(2**63) <= value < 2**63 else None
    return value if math.isfinite(value) else None


def timestamp(value):
    value = number(value)
    return value if isinstance(value, int) and 0 < value < 10**14 else None


def freshness(source_ms, received_ms: int, offset_ms: float | None) -> dict:
    reported = number(source_ms)
    source_ms = timestamp(source_ms)
    return {
        "reported_source_time_ms": reported,
        "source_time_ms": source_ms,
        "local_receive_time_ms": received_ms,
        "estimated_age_ms": round(received_ms + offset_ms - source_ms, 3) if source_ms and offset_ms is not None else None,
    }


def rows(data, key: str) -> list:
    if not isinstance(data, dict) or not isinstance(data.get(key), list):
        raise DiagnosticError("Response shape does not match the documented schema.")
    return data[key]


def api_result(payload) -> dict:
    if not isinstance(payload, dict) or not isinstance(payload.get("ret_code"), int) or isinstance(payload["ret_code"], bool):
        raise DiagnosticError("API result code is missing or malformed.")
    code = payload["ret_code"]
    # Do not echo ret_msg/error.message; a gateway can reflect credentials.
    return {"ret_code": code, "status": "success" if code == 0 else "api_error"}


def parse_quote(payload, received_ms: int, offset_ms: float | None) -> dict:
    result = api_result(payload)
    if result["status"] != "success":
        return result
    matches = [row for row in rows(payload.get("data"), "quote_list") if isinstance(row, dict) and row.get("code") == SYMBOL]
    if len(matches) != 1:
        raise DiagnosticError("Requested US.NVDA quote is missing or duplicated.")
    row = matches[0]
    return {**result, "symbol": SYMBOL, "last_price": number(row.get("last_price")),
            "volume": number(row.get("volume")), "freshness": freshness(row.get("data_time"), received_ms, offset_ms)}


def parse_book(payload, received_ms: int, offset_ms: float | None) -> dict:
    result = api_result(payload)
    if result["status"] != "success":
        return result
    matches = [row for row in rows(payload, "data") if isinstance(row, dict) and row.get("code") == SYMBOL]
    if len(matches) != 1:
        raise DiagnosticError("Requested US.NVDA book is missing or duplicated.")
    books = []
    for book in rows(matches[0], "books"):
        if not isinstance(book, dict):
            raise DiagnosticError("Order-book element is malformed.")
        exchange = book.get("exchange")
        exchange = exchange if exchange in ("NASDAQ", "ARCA", "") else "UNKNOWN"
        entry = {"exchange": exchange, "order_volume_precision": number(book.get("order_volume_precision")),
                 "freshness": freshness(book.get("exchange_data_time_ms"), received_ms, offset_ms),
                 "server_send_to_client_time_ms": timestamp(book.get("server_send_to_client_time_ms"))}
        for side in ("bid", "ask"):
            levels = rows(book, side + "_list")
            if not all(isinstance(level, dict) for level in levels):
                raise DiagnosticError("Order-book level is malformed.")
            flag = book.get(side + "_flag")
            valid = flag == 1 and not isinstance(flag, bool)
            usable = [level for level in levels if number(level.get("price")) is not None
                      and level["price"] > 0 and number(level.get("volume")) is not None and level["volume"] >= 0]
            entry[side + "_valid"] = valid
            entry[side + "_returned_levels"] = len(levels)
            entry[side + "_verified_levels"] = len(usable) if valid else 0
            entry[side + "_sample"] = [
                {field: number(level.get(field)) for field in ("price", "volume", "order_count")}
                for level in levels[:2]
            ]
        depth = max(entry["bid_verified_levels"], entry["ask_verified_levels"])
        entry["classification"] = (
            "NASDAQ exchange-labeled depth; TotalView product entitlement unconfirmed" if exchange == "NASDAQ" and depth > 1 else
            "ARCA exchange-labeled depth; ArcaBook product entitlement unconfirmed" if exchange == "ARCA" and depth > 1 else
            "unlabeled multi-level depth; consolidation unconfirmed" if depth > 1 else
            "top-of-book observed; maximum entitlement unconfirmed" if depth == 1 else
            "no valid levels observed"
        )
        sent = entry["server_send_to_client_time_ms"]
        entry["reported_server_send_to_client_time_ms"] = number(book.get("server_send_to_client_time_ms"))
        generated = entry["freshness"]["source_time_ms"]
        entry["provider_dispatch_delay_ms"] = sent - generated if sent and generated else None
        entry["estimated_dispatch_to_receive_ms"] = round(received_ms + offset_ms - sent, 3) if sent and offset_ms is not None else None
        books.append(entry)
    if not books:
        raise DiagnosticError("Order-book response contains no books.")
    return {**result, "symbol": SYMBOL, "books": books,
            "entitlement": "Observed returned depth only; API permission tier and product license not proven."}


def numeric_headers(headers: httpx.Headers) -> dict:
    result = {}
    for name in ("retry-after", "x-ratelimit-limit", "x-ratelimit-remaining", "x-ratelimit-reset",
                 "ratelimit-limit", "ratelimit-remaining", "ratelimit-reset"):
        value = headers.get(name, "")
        if re.fullmatch(r"[0-9]{1,16}(?:\.[0-9]{1,6})?", value):
            result[name] = value
    return result


def probe(client: httpx.Client, appkey: str, key: Ed25519PrivateKey) -> dict:
    report = {"symbol": SYMBOL, "started_at_utc": datetime.now(timezone.utc).isoformat(),
              "websocket": {"status": "not_requested", "command": "--stream-seconds 30"},
              "subscription_quota": "unverified; no subscriptions or quota-exhaustion probes",
              "historical_depth": "no historical Level 2 endpoint found in current direct API reference",
              "recording_license": "unverified; bounded samples only"}
    offset = None
    try:
        start_wall = time.time_ns() / 1e6
        start_mono = time.perf_counter()
        response = client.get(HOST + TIME_PATH)
        elapsed = (time.perf_counter() - start_mono) * 1000
        received = time.time_ns() / 1e6
        if response.status_code in (401, 403, 429):
            report["clock"] = {"http_status": response.status_code, "status": "http_error",
                               "observed_rate_headers": numeric_headers(response.headers)}
            report["remaining_request"] = "skipped after server-time authentication, permission or rate refusal"
            return report
        server = response.json().get("server_time_ms") if response.status_code == 200 else None
        if isinstance(server, str) and re.fullmatch(r"[0-9]{1,14}", server):
            server = int(server)
        server = timestamp(server)
        if server:
            offset = server - (start_wall + received) / 2
        report["clock"] = {"http_status": response.status_code, "server_time_ms": server,
                           "round_trip_ms": round(elapsed, 3), "estimated_server_minus_local_ms": offset,
                           "uncertainty_note": "One midpoint sample; asymmetric network delay is unknown."}
    except (httpx.HTTPError, ValueError, AttributeError):
        report["clock"] = {"status": "unavailable; freshness estimates disabled"}

    for label, path, body, parser in (
        ("quote", QUOTE_PATH, {"code_list": [SYMBOL]}, parse_quote),
        ("order_book", BOOK_PATH, {"code": SYMBOL}, parse_book),
    ):
        raw_body = json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        request = client.build_request("POST", HOST + path, content=raw_body, headers={"Content-Type": "application/json"})
        # Synchronize signing time when server-time works, without hiding skew.
        signed_ms = int(time.time_ns() / 1e6 + (offset or 0))
        sign_request(request, appkey, key, signed_ms, secrets.token_urlsafe(24))
        start_mono = time.perf_counter()
        try:
            response = client.send(request)
            received_ms = time.time_ns() // 1_000_000
            entry = {"http_status": response.status_code, "round_trip_ms": round((time.perf_counter() - start_mono) * 1000, 3),
                     "observed_rate_headers": numeric_headers(response.headers)}
            if 200 <= response.status_code < 300:
                try:
                    entry.update(parser(response.json(), received_ms, offset))
                except (ValueError, DiagnosticError):
                    entry.update(status="invalid_response", reason="Response does not match the documented market-data schema.")
            else:
                entry["status"] = "http_error"
            report[label] = entry
            if response.status_code in (401, 403, 429) or entry.get("ret_code") in (-12006,):
                report["remaining_request"] = "skipped after authentication, permission, rate or timestamp refusal"
                break
        except httpx.HTTPError:
            report[label] = {"status": "network_error", "reason": "Network request failed; exception details withheld."}
            break
        if label == "quote":
            time.sleep(1)  # no burst, retries, quota testing or polling
    return report


def websocket_auth(appkey: str, key: Ed25519PrivateKey, timestamp_ms: int, nonce: str) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", nonce):
        raise DiagnosticError("Nonce format is invalid.")
    payload = f"{timestamp_ms}\n{nonce}\nWEBSOCKET\nws/auth".encode("utf-8")
    return {"id": "auth-1", "action": "auth", "data": {
        "auth_type": "appkey", "credential_id": appkey, "timestamp_ms": timestamp_ms, "nonce": nonce,
        "authorization": base64.b64encode(key.sign(payload)).decode("ascii"),
    }}


def websocket_refresh(appkey: str, key: Ed25519PrivateKey, timestamp_ms: int, nonce: str, request_id: str) -> dict:
    """Documented in-session AppKey refresh: a fresh signature over the auth layout."""
    frame = websocket_auth(appkey, key, timestamp_ms, nonce)["data"]
    return {"id": request_id, "action": "refresh", "data": {field: frame[field] for field in ("credential_id", "authorization", "timestamp_ms", "nonce")}}


def protocol_summary(message: dict) -> dict:
    """Never echo messages/session identifiers; retain only safe protocol evidence."""
    code = number(message.get("code", message.get("ret_code")))
    known_ids = ("auth-1", "sub-quote", "sub-order_book", "sub-ticker", "unsub-1")
    nested = message.get("data") if isinstance(message.get("data"), dict) else {}
    return {"code": code,
            "request_id": message.get("id") if message.get("id") in known_ids else None,
            "id_present": "id" in message,
            "known_fields_present": [field for field in ("id", "code", "ret_code", "action", "type", "data", "message", "error", "session_id", "server_time", "req_id", "request_id") if field in message],
            "data_known_fields_present": [field for field in ("id", "code", "ret_code", "action", "quote", "order_book", "ticker", "req_id", "request_id") if field in nested],
            "data_request_id": nested.get("id") if nested.get("id") in known_ids else None,
            "action": message.get("action") if message.get("action") in ("auth", "subscribe", "unsubscribe") else None,
            "session_assigned": bool(message.get("session_id")),
            "server_time_us": number(message.get("server_time")),
            "error_present": bool(message.get("error")) or (code is not None and code != 0)}


def push_summary(message: dict, received_ms: int, offset_ms: float | None, symbol: str = SYMBOL) -> dict | None:
    kind = message.get("type")
    data = message.get("data")
    if message.get("symbol") != symbol or kind not in ("QUOTE", "ORDER_BOOK", "TICKER") or not isinstance(data, dict):
        return None
    result = {"type": kind, "freshness": freshness(data.get("data_time_ms"), received_ms, offset_ms)}
    if kind == "QUOTE":
        result["last_price"] = number(data.get("last_price"))
    elif kind == "TICKER":
        ticks = rows(data, "ticker_list")
        if not all(isinstance(tick, dict) for tick in ticks):
            raise DiagnosticError("Ticker batch is malformed.")
        result["tick_count"] = len(ticks)
        result["sample"] = [{**{field: number(tick.get(field)) for field in ("price", "volume", "sequence")},
                              "freshness": freshness(tick.get("time_ms"), received_ms, offset_ms)} for tick in ticks[:2]]
    else:
        books = data.get("books", [data])
        if not isinstance(books, list) or len(books) > 10:
            raise DiagnosticError("Streaming book shape is malformed.")
        result["books"] = []
        for book in books:
            if not isinstance(book, dict):
                raise DiagnosticError("Streaming book element is malformed.")
            exchange = book.get("exchange")
            entry = {"exchange": exchange if exchange in ("NASDAQ", "ARCA", "") else "UNKNOWN",
                     "order_volume_precision": number(book.get("order_volume_precision")),
                     "freshness": freshness(book.get("exchange_data_time_ms", data.get("data_time_ms")), received_ms, offset_ms)}
            for side in ("bid", "ask"):
                levels = book.get(side + "_list")
                entry[side + "_list_available"] = levels is not None
                if levels is None:
                    entry[side + "_levels"] = None
                    entry[side + "_valid_entries"] = 0
                    entry[side + "_distinct_prices"] = 0
                    entry[side + "_sample"] = []
                    continue
                if not isinstance(levels, list):
                    raise DiagnosticError("Streaming book list is malformed.")
                if not all(isinstance(level, dict) for level in levels):
                    raise DiagnosticError("Streaming book level is malformed.")
                usable = [level for level in levels if number(level.get("price")) is not None and level["price"] > 0
                          and number(level.get("volume")) is not None and level["volume"] >= 0]
                entry[side + "_levels"] = len(levels)
                entry[side + "_valid_entries"] = len(usable)
                entry[side + "_distinct_prices"] = len({level["price"] for level in usable})
                entry[side + "_sample"] = [{**{field: number(level.get(field)) for field in ("price", "volume", "order_count")},
                    "mpid": level.get("mpid") if isinstance(level.get("mpid"), str) and re.fullmatch(r"[A-Z0-9]{1,8}", level["mpid"]) else None} for level in levels[:2]]
                entry[side + "_mpid_present"] = any(bool(level.get("mpid")) for level in levels)
                entry[side + "_mpids"] = sorted({level["mpid"] for level in levels if isinstance(level.get("mpid"), str)
                                                and re.fullmatch(r"[A-Z0-9]{1,8}", level["mpid"])})[:12]
            result["books"].append(entry)
    return result


def display_book(message: dict, received_ms: int, offset_ms: float | None, symbol: str = SYMBOL) -> dict:
    """Allowlisted latest-book view, never infer venue from MPID or missing time.

    No delta merging: each push is displayed independently. Partial sides stay
    empty rather than borrowing levels from a previous message.
    """
    data = message.get("data")
    if message.get("symbol") != symbol or message.get("type") != "ORDER_BOOK" or not isinstance(data, dict):
        raise DiagnosticError("Unexpected lab book message.")
    books = data.get("books", [data])
    if not isinstance(books, list) or len(books) > 10:
        raise DiagnosticError("Book count exceeds the lab bound.")
    output = []
    for book in books:
        if not isinstance(book, dict):
            raise DiagnosticError("Book is malformed.")
        clock = freshness(book.get("exchange_data_time_ms", data.get("data_time_ms")), received_ms, offset_ms)
        entry = {"exchange": book.get("exchange") if book.get("exchange") in ("ARCA", "NASDAQ", "") else "UNKNOWN",
                 "source_time_ms": clock["source_time_ms"], "estimated_age_ms": clock["estimated_age_ms"],
                 "order_volume_precision": number(book.get("order_volume_precision"))}
        for source, target in (("bid", "bids"), ("ask", "asks")):
            levels = book.get(source + "_list")
            if levels is None:
                levels = []  # Absent/null sides are unavailable, never deltas.
            if not isinstance(levels, list) or len(levels) > 60:
                raise DiagnosticError("Book level count exceeds the lab bound.")
            entry[target] = []
            flag = book.get(source + "_flag")
            if flag is not None and (isinstance(flag, bool) or flag != 1):
                continue
            for level in levels:
                if not isinstance(level, dict):
                    raise DiagnosticError("Book level is malformed.")
                price, volume = number(level.get("price")), number(level.get("volume"))
                if price is None or price <= 0 or volume is None or volume < 0:
                    raise DiagnosticError("Book price or size is unavailable.")
                count = number(level.get("order_count"))
                mpid = level.get("mpid")
                entry[target].append({"price": price, "volume": volume,
                    "order_count": count if isinstance(count, int) and count >= 0 else None,
                    "mpid": mpid if isinstance(mpid, str) and re.fullmatch(r"[A-Z0-9]{1,8}", mpid) else None})
        output.append(entry)
    return {"event": "book", "symbol": symbol, "received_ms": received_ms, "books": output}


async def stream_probe(appkey: str, key: Ed25519PrivateKey, seconds: int, connector=NoRedirectConnect, observer=None,
                       refresh_seconds: int | None = None, symbol: str = SYMBOL) -> dict:
    # Without refresh the hard cap stays well below the documented ten-minute
    # auth refresh limit. A longer manual session must refresh in place
    # (recommended cycle five minutes); an unconfirmed refresh ends it.
    if refresh_seconds is not None and not MIN_REFRESH_SECONDS <= refresh_seconds <= 300:
        raise DiagnosticError("Refresh interval must be 30..300 seconds.")
    if not 1 <= seconds <= (MAX_REFRESHED_SECONDS if refresh_seconds else 60):
        raise DiagnosticError("Streaming diagnostic duration is outside the permitted cap.")
    if not isinstance(symbol, str) or not STREAM_SYMBOL.fullmatch(symbol):
        raise DiagnosticError("Streaming symbol must be a US stock or ETF ticker.")
    report = {"symbol": symbol, "started_at_utc": datetime.now(timezone.utc).isoformat(),
              "requested_seconds": seconds, "refresh_policy": f"Refresh every {refresh_seconds} seconds; ends if unconfirmed." if refresh_seconds
              else "Hard cap 60 seconds; below the 10-minute refresh requirement.",
              "refreshes": {"sent": 0, "confirmed": 0},
              "subscriptions": {kind: {"status": "not_attempted"} for kind in STREAM_TYPES},
              "message_counts": {kind: 0 for kind in ("QUOTE", "ORDER_BOOK", "TICKER")},
              "samples": {}, "protocol_samples": [], "unsubscribe": {"status": "not_needed"}, "closed": False}
    offset = None
    attempted = []
    started = time.perf_counter()
    deadline = started + seconds
    socket = None

    def notify(event):
        if observer is not None:
            observer(event)

    def capture(message):
        nonlocal offset
        try:
            sample = push_summary(message, time.time_ns() // 1_000_000, offset, symbol)
        except DiagnosticError:
            report["invalid_data_messages"] = report.get("invalid_data_messages", 0) + 1
            return
        if sample:
            kind = sample["type"]
            report["message_counts"][kind] += 1
            saved = report["samples"].setdefault(kind, {})
            saved.setdefault("first", sample)
            saved["last"] = sample
            if kind == "ORDER_BOOK" and observer is not None and report.get("authentication", {}).get("status") == "success":
                notify(display_book(message, time.time_ns() // 1_000_000, offset, symbol))

    def correlated(message: dict, request_id: str) -> dict | None:
        if message.get("id") == request_id:
            return message
        nested = message.get("data")
        if number(message.get("ret_code")) == 0 and isinstance(nested, dict) and nested.get("id") == request_id:
            return nested
        return None

    async def receive_until(request_id: str, timeout: float) -> dict:
        until = time.perf_counter() + timeout
        while True:
            remaining = until - time.perf_counter()
            if remaining <= 0:
                raise asyncio.TimeoutError
            message = json.loads(await bounded_await(socket.recv(), remaining))
            if not isinstance(message, dict):
                raise DiagnosticError("WebSocket protocol message is malformed.")
            reply = correlated(message, request_id)
            if reply is not None:
                return reply
            if message.get("type") not in ("QUOTE", "ORDER_BOOK", "TICKER"):
                summary = protocol_summary(message)
                if len(report["protocol_samples"]) < 4:
                    report["protocol_samples"].append(summary)
                if summary["error_present"]:
                    raise DiagnosticError("Uncorrelated protocol error.")
            capture(message)

    try:
        notify({"event": "status", "phase": "connecting"})
        # Independent silent logger prevents wire logging of signed auth frames.
        logger = logging.Logger("moomoo.diagnostic", level=logging.CRITICAL)
        async with connector(WS_URL, proxy=None, open_timeout=min(10, seconds), close_timeout=5,
                             ping_interval=20, ping_timeout=10, max_size=1024 * 1024, max_queue=16, logger=logger) as socket:
            try:
                frame = websocket_auth(appkey, key, time.time_ns() // 1_000_000, secrets.token_urlsafe(24))
                auth_start_ms = time.time_ns() / 1e6
                await socket.send(json.dumps(frame, separators=(",", ":")))
                auth = await receive_until("auth-1", min(5, max(0, deadline - time.perf_counter())))
                report["authentication"] = protocol_summary(auth)
                if not auth.get("session_id") or report["authentication"]["error_present"]:
                    report["authentication"]["status"] = "failed"
                    notify({"event": "status", "phase": "failed", "code": report["authentication"]["code"]})
                    return report
                report["authentication"]["status"] = "success"
                notify({"event": "status", "phase": "authenticated"})
                server_us = number(auth.get("server_time"))
                if server_us and server_us > 0:
                    offset = server_us / 1000 - (auth_start_ms + time.time_ns() / 1e6) / 2
                for kind in STREAM_TYPES:
                    request_id = "sub-" + kind
                    attempted.append(kind)
                    report["subscriptions"][kind] = {"status": "sent_unconfirmed"}
                    await socket.send(json.dumps({"id": request_id, "action": "subscribe", kind: [symbol]}))
                    ack = await receive_until(request_id, min(5, max(0, deadline - time.perf_counter())))
                    result = protocol_summary(ack)
                    result["status"] = "success" if result["code"] == 0 and not result["error_present"] else "failed"
                    report["subscriptions"][kind] = result
                    notify({"event": "status", "phase": "subscribed" if result["status"] == "success" else "failed",
                            "kind": kind, "code": result["code"]})
                next_refresh = time.perf_counter() + refresh_seconds if refresh_seconds else None
                pending = None  # (request id, give-up time) of the one unconfirmed refresh
                while (now := time.perf_counter()) < deadline:
                    if pending is None and next_refresh is not None and now >= next_refresh:
                        request_id = f"refresh-{report['refreshes']['sent'] + 1}"
                        await socket.send(json.dumps(websocket_refresh(appkey, key, time.time_ns() // 1_000_000,
                                                                       secrets.token_urlsafe(24), request_id), separators=(",", ":")))
                        report["refreshes"]["sent"] += 1
                        pending = (request_id, now + REFRESH_ACK_SECONDS)
                    if pending is not None and now >= pending[1]:
                        report["refresh_failed"] = True
                        raise DiagnosticError("Refresh was not acknowledged.")
                    wake = min(deadline, pending[1] if pending else next_refresh or deadline)
                    try:
                        message = json.loads(await bounded_await(socket.recv(), max(0.01, wake - now)))
                    except asyncio.TimeoutError:
                        continue
                    if not isinstance(message, dict):
                        raise DiagnosticError("WebSocket protocol message is malformed.")
                    reply = correlated(message, pending[0]) if pending else None
                    if reply is not None:
                        if protocol_summary(reply)["error_present"]:
                            report["refresh_failed"] = True
                            raise DiagnosticError("Refresh was refused.")
                        report["refreshes"]["confirmed"] += 1
                        notify({"event": "status", "phase": "refreshed"})
                        pending, next_refresh = None, time.perf_counter() + refresh_seconds
                        continue
                    capture(message)
                report["status"] = "completed"
            finally:
                if attempted:
                    try:
                        await socket.send(json.dumps({"id": "unsub-1", "action": "unsubscribe", **{kind: [symbol] for kind in attempted}}))
                        ack = await receive_until("unsub-1", 5)
                        result = protocol_summary(ack)
                        result["status"] = "success" if result["code"] == 0 and not result["error_present"] else "failed"
                        report["unsubscribe"] = result
                    except (OSError, WebSocketException, asyncio.TimeoutError, ValueError, DiagnosticError):
                        report["unsubscribe"] = {"status": "unconfirmed; connection will close"}
    except (OSError, WebSocketException, asyncio.TimeoutError, ValueError, DiagnosticError):
        report["status"] = "failed_or_timed_out"
        report.setdefault("authentication", {"status": "unconfirmed"})
        report["error"] = "Connection, acknowledgment or protocol failed; details withheld. No retries."
    finally:
        report["closed"] = socket is not None and socket.close_code is not None
        report["elapsed_seconds"] = round(time.perf_counter() - started, 3)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--configure", action="store_true", help="Save AppKey via hidden input outside Git.")
    parser.add_argument("--stream-seconds", type=int, choices=range(1, 61), metavar="1..60",
                        help="Run one bounded quote/order_book/ticker WebSocket diagnostic.")
    args = parser.parse_args()
    try:
        if args.configure:
            configure()
            return 0
        appkey = secure_read(KEY_DIR / "appkey").decode("ascii").strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", appkey):
            raise DiagnosticError("AppKey file format is invalid.")
        key = serialization.load_pem_private_key(secure_read(KEY_DIR / "phase1-ed25519.pem"), password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise DiagnosticError("The diagnostic requires an Ed25519 private key.")
        if args.stream_seconds is not None:
            report = asyncio.run(stream_probe(appkey, key, args.stream_seconds))
            print(json.dumps(report, indent=2, allow_nan=False))
            return 0 if report.get("status") == "completed" and all(report["subscriptions"][kind]["status"] == "success" for kind in STREAM_TYPES) and report["unsubscribe"]["status"] == "success" and report["closed"] else 1
        # Never follow credential-bearing redirects, use inherited proxies, or
        # enable wire logging. The context manager closes all REST connections.
        with httpx.Client(timeout=15, follow_redirects=False, trust_env=False) as client:
            report = probe(client, appkey, key)
        print(json.dumps(report, indent=2, allow_nan=False))
        return 0 if all(report.get(label, {}).get("status") == "success" for label in ("quote", "order_book")) else 1
    except DiagnosticError as exc:
        print(str(exc))
    except FileNotFoundError:
        print("Credentials missing. Complete account setup, then run with --configure.")
    except FileExistsError:
        print("AppKey file already exists; configuration will not overwrite it.")
    except (OSError, ValueError, TypeError, UnicodeError):
        print("Credential setup could not be read safely; details withheld.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
