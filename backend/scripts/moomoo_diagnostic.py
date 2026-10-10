"""Manual, bounded moomoo Phase 1 probe. No app, database or provider imports.

Run from backend with the backend Python environment:
    python -m scripts.moomoo_diagnostic --configure
    python -m scripts.moomoo_diagnostic

AppKey WebSocket signing is deliberately blocked: the official authentication
page describes the frame but does not specify the signing payload.
"""

from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
from getpass import GetPassWarning, getpass
import hashlib
import json
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

HOST = "https://webapi.moomoo.com"
QUOTE_PATH = "/api/v1.0/quote/stock-quote"
BOOK_PATH = "/api/v1.0/quote/order-book"
TIME_PATH = "/api/v1.0/server-time"
SYMBOL = "US.NVDA"
KEY_DIR = Path.home() / ".config/tradejournal/moomoo"
WS_BLOCKER = "Official AppKey WebSocket signing payload not verified; no connection attempted."


class DiagnosticError(Exception):
    """Only fixed, credential-free messages may reach this exception."""


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
              "websocket": {"status": "blocked", "reason": WS_BLOCKER},
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--configure", action="store_true", help="Save AppKey via hidden input outside Git.")
    parser.add_argument("--stream-seconds", type=int, choices=range(1, 61), metavar="1..60",
                        help="Reserved bounded streaming probe; currently returns the verified signing blocker.")
    args = parser.parse_args()
    if args.stream_seconds is not None:
        print(json.dumps({"websocket": {"status": "blocked", "reason": WS_BLOCKER}}, indent=2))
        return 2
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
