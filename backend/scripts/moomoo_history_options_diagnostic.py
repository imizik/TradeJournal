"""Manual, bounded historical/options comparison. No app imports or disk writes.

Run from backend: python -m scripts.moomoo_history_options_diagnostic
Reuses owner-only Phase 1 keys and reads only market-data endpoints. Raw
responses stay in memory; stdout contains allowlisted diagnostic summaries.
"""

from __future__ import annotations

import argparse
import base64
from contextlib import closing, contextmanager
from datetime import date, datetime, time as day_time, timedelta, timezone
from decimal import Decimal
import json
import logging
import os
from pathlib import Path
import re
import secrets
import signal
from statistics import median
import threading
import time
from zoneinfo import ZoneInfo

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from dotenv import dotenv_values
import httpx

from scripts.moomoo_diagnostic import (
    DiagnosticError, HOST, KEY_DIR, TIME_PATH, number, numeric_headers,
    secure_read, signing_payload, timestamp,
)

ET = ZoneInfo("America/New_York")
UNDERLYING = "US.NVDA"
DEFAULT_DAY = date(2026, 10, 9)
ACTIVE = "US.NVDA261016C230000"
EXPIRED = "US.NVDA261009C230000"
SYMBOLS = (UNDERLYING, ACTIVE, EXPIRED)
OCC = {UNDERLYING: "NVDA", ACTIVE: "NVDA261016C00230000", EXPIRED: "NVDA261009C00230000"}
BASIC_PATH = "/api/v1.0/quote/stock-basicinfo"
SCREEN_PATH = "/api/v1.0/quote/option-screen"
ALLOWED = {
    ("moomoo", "GET", "webapi.moomoo.com", TIME_PATH),
    ("moomoo", "POST", "webapi.moomoo.com", BASIC_PATH),
    ("moomoo", "POST", "webapi.moomoo.com", SCREEN_PATH),
    ("moomoo", "GET", "webapi.moomoo.com", "/api/v1.0/quote/US.NVDA/option-chain"),
    ("alpaca", "GET", "data.alpaca.markets", "/v2/stocks/bars"),
    ("alpaca", "GET", "data.alpaca.markets", "/v1beta1/options/bars"),
    ("alpaca", "GET", "data.alpaca.markets", "/v1beta1/options/snapshots"),
    ("tradier", "POST", "api.tradier.com", "/v1/markets/quotes"),
    ("tradier", "POST", "sandbox.tradier.com", "/v1/markets/quotes"),
}
ALLOWED.update(("moomoo", "GET", "webapi.moomoo.com", f"/api/v1.0/quote/{s}/history-kline") for s in SYMBOLS)
ALLOWED.update(("moomoo", "GET", "webapi.moomoo.com", f"/api/v1.0/quote/{s}/option-volatility") for s in (ACTIVE, EXPIRED))
MAX_BYTES = 2 * 1024 * 1024
MAX_REQUESTS = 18
REQUEST_SECONDS = 15


class ResponseDeadline(Exception):
    """Fixed-message deadline exception; no transport or credential details."""


@contextmanager
def quiet_logging():
    # Ancestor .disabled flags do not suppress descendant logger propagation.
    # This standalone probe uses only sanitized stdout, including on failures.
    previous = logging.root.manager.disable
    logging.disable(max(previous, logging.CRITICAL))
    try:
        yield
    finally:
        logging.disable(previous)


@contextmanager
def response_deadline(seconds: float):
    """Hard wall deadline across headers/body reads on this Unix CLI.

    Refuse an unsupported/reentrant environment instead of silently losing
    the bound. This is deliberately not reusable FastAPI connection code.
    """
    if not hasattr(signal, "setitimer") or threading.current_thread() is not threading.main_thread():
        raise DiagnosticError("The bounded probe requires a Unix main-thread CLI.")
    if signal.getitimer(signal.ITIMER_REAL) != (0.0, 0.0):
        raise DiagnosticError("An existing process timer prevents a safe diagnostic deadline.")
    previous = signal.getsignal(signal.SIGALRM)
    def expire(signum, frame):
        raise ResponseDeadline()
    signal.signal(signal.SIGALRM, expire)
    signal.setitimer(signal.ITIMER_REAL, max(0.001, seconds))
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def check_destination(provider: str, request: httpx.Request, day: date) -> None:
    url = request.url
    allowed = (provider, request.method, url.host, url.path) in ALLOWED
    polygon_path = f"/v2/aggs/ticker/NVDA/range/1/minute/{day}/{day}"
    allowed |= provider == "polygon" and request.method == "GET" and url.host == "api.polygon.io" and url.path == polygon_path
    if not allowed or url.scheme != "https" or url.port not in (None, 443) or url.username or url.password:
        raise DiagnosticError("Request is outside the market-data diagnostic allowlist.")


def sign_history(request: httpx.Request, appkey: str, key: Ed25519PrivateKey, at_ms: int, day: date) -> None:
    check_destination("moomoo", request, day)
    if request.url.path == TIME_PATH:
        raise DiagnosticError("Server time must remain unsigned.")
    raw_path = request.url.raw_path.split(b"?", 1)[0].decode("ascii")
    payload = signing_payload(at_ms, request.method, raw_path, request.url.query.decode("ascii"), request.content)
    request.headers.update({"X-Api-Key": appkey, "X-Timestamp": str(at_ms),
                            "X-Nonce": secrets.token_urlsafe(24),
                            "Authorization": base64.b64encode(key.sign(payload)).decode("ascii")})


class Reader:
    def __init__(self, client: httpx.Client, day: date, appkey: str, key: Ed25519PrivateKey):
        self.client, self.day, self.appkey, self.key = client, day, appkey, key
        self.count = 0
        self.started = time.monotonic()
        self.last_request = 0.0
        self.offset = 0.0
        self.blocked: set[str] = set()
        self.records: dict[str, dict] = {}

    def read(self, label: str, provider: str, method: str, url: str, *, params=None, body=None, headers=None, form=None):
        if provider in self.blocked:
            self.records[label] = {"status": "skipped_after_refusal"}
            return None
        if self.count >= MAX_REQUESTS or time.monotonic() - self.started > 150:
            self.records[label] = {"status": "diagnostic_budget_exhausted"}
            return None
        request = self.client.build_request(method, url, params=params, headers=headers, data=form,
                                            content=json.dumps(body, separators=(",", ":")).encode() if body is not None else None)
        request.headers["Accept-Encoding"] = "identity"
        check_destination(provider, request, self.day)
        if provider == "moomoo" and request.url.path != TIME_PATH:
            sign_history(request, self.appkey, self.key, int(time.time() * 1000 + self.offset), self.day)
        wait = max(0, 1 - (time.monotonic() - self.last_request))
        if wait:
            time.sleep(wait)
        self.last_request = time.monotonic()
        self.count += 1
        start = time.perf_counter()
        record = self.records[label] = {"status": "unavailable"}
        try:
            seconds = min(REQUEST_SECONDS, 180 - (time.monotonic() - self.started))
            deadline = time.monotonic() + seconds
            request.extensions["timeout"] = {k: seconds for k in ("connect", "read", "write", "pool")}
            with quiet_logging(), response_deadline(seconds):
                with closing(self.client.send(request, stream=True, follow_redirects=False)) as response:
                    record.update(http_status=response.status_code, rate_headers=numeric_headers(response.headers))
                    if response.status_code in (401, 403, 429):
                        self.blocked.add(provider)
                    if response.status_code != 200:
                        record["status"] = "http_error"
                        return None
                    if response.headers.get("content-encoding", "identity").lower() != "identity":
                        record["status"] = "unexpected_content_encoding"
                        return None
                    chunks = bytearray()
                    # No 64 KiB accumulator delaying the elapsed-time guard.
                    for chunk in response.iter_bytes():
                        if time.monotonic() >= deadline:
                            record["status"] = "response_deadline_exceeded"
                            return None
                        if len(chunks) + len(chunk) > MAX_BYTES:
                            record["status"] = "response_budget_exceeded"
                            return None
                        chunks.extend(chunk)
                payload = json.loads(chunks)
            if not isinstance(payload, dict):
                record["status"] = "malformed_response"
                return None
            if provider == "moomoo" and request.url.path != TIME_PATH:
                code = number(payload.get("ret_code"))
                if not isinstance(code, int):
                    record["status"] = "malformed_response"
                    return None
                record["ret_code"] = code
                if code != 0:
                    record["status"] = "api_error"
                    if -12100 < code <= -12000:
                        self.blocked.add(provider)
                    return None
            record["status"] = "success"
            return payload
        except ResponseDeadline:
            record["status"] = "response_deadline_exceeded"
            return None
        except (httpx.HTTPError, ValueError, OSError):
            record["status"] = "transport_or_json_error"
            return None
        finally:
            record["round_trip_ms"] = round((time.perf_counter() - start) * 1000, 3)
            record["received_at_ms"] = int(time.time() * 1000)


def mapping(value) -> dict:
    return value if isinstance(value, dict) else {}


def items(value) -> list:
    return value if isinstance(value, list) else []


def iso_ms(value) -> int | None:
    if not isinstance(value, str) or len(value) > 64:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return int(dt.timestamp() * 1000) if dt.tzinfo is not None else None
    except (ValueError, OverflowError, OSError):
        return None


def parse_bars(raw, provider: str, day: date, timestamp_shift_ms: int = 0) -> tuple[dict[int, dict], dict]:
    result, duplicates = {}, set()
    stats = {"returned": len(items(raw)), "invalid": 0, "outside_regular_session": 0, "duplicates": 0}
    for row in items(raw):
        row = mapping(row)
        stamp = timestamp(row.get("time_key" if provider == "moomoo" else "t")) if provider != "alpaca" else iso_ms(row.get("t"))
        stamp = stamp + timestamp_shift_ms if stamp else None
        fields = ("open", "high", "low", "close", "volume") if provider == "moomoo" else ("o", "h", "l", "c", "v")
        values = {name: number(row.get(field)) for name, field in zip(("o", "h", "l", "c", "v"), fields)}
        if not stamp or stamp % 60000 or any(values[k] is None or values[k] <= 0 for k in ("o", "h", "l", "c")) or values["v"] is None or values["v"] < 0:
            stats["invalid"] += 1
            continue
        if not values["l"] <= min(values["o"], values["c"]) <= max(values["o"], values["c"]) <= values["h"]:
            stats["invalid"] += 1
            continue
        local = datetime.fromtimestamp(stamp / 1000, ET)
        if local.date() != day or not day_time(9, 30) <= local.time() < day_time(16):
            stats["outside_regular_session"] += 1
            continue
        if stamp in result or stamp in duplicates:
            stats["duplicates"] += 1
            duplicates.add(stamp)
            result.pop(stamp, None)
            continue
        result[stamp] = values
    stats.update(valid_regular_minutes=len(result), first_ms=min(result) if result else None,
                 last_ms=max(result) if result else None, expected_session_minutes=390,
                 diagnostic_timestamp_shift_ms=timestamp_shift_ms,
                 zero_volume_minutes=sum(bar["v"] == 0 for bar in result.values()),
                 note="Absent minutes may mean no qualifying trades or truncated coverage; not proven data loss.")
    return result, stats


def compare_bars(left: dict, right: dict) -> dict:
    shared = sorted(left.keys() & right.keys())
    result = {"matched_minutes": len(shared), "moomoo_only_minutes": len(left.keys() - right.keys()),
              "baseline_only_minutes": len(right.keys() - left.keys()),
              "status": "compared" if shared else "no_overlap", "fields": {}}
    for field in ("o", "h", "l", "c", "v"):
        if any(left[t][field] is None or right[t][field] is None for t in shared):
            result["fields"][field] = {"status": "unavailable_units"}
            continue
        differences = [abs(Decimal(str(left[t][field])) - Decimal(str(right[t][field]))) for t in shared]
        result["fields"][field] = {"equal_minutes": sum(d <= Decimal("0.000001") for d in differences),
                                    "median_abs_difference": float(median(differences)) if differences else None,
                                    "max_abs_difference": float(max(differences)) if differences else None}
    result["shared_window_extremes"] = {
        name: {"high": max((bars[t]["h"] for t in shared), default=None),
               "low": min((bars[t]["l"] for t in shared), default=None)}
        for name, bars in (("moomoo", left), ("baseline", right))}
    result["limitation"] = "Shared minute inputs only, not journal MFE/MAE or executable prices; feed and adjustment differences remain."
    return result


def history(reader: Reader, symbol: str) -> tuple[dict, dict, dict]:
    payload = reader.read("history_" + symbol, "moomoo", "GET", HOST + f"/api/v1.0/quote/{symbol}/history-kline",
                          params={"start": str(reader.day), "end": str(reader.day + timedelta(days=1)), "ktype": 1,
                                  "autype": 0, "num": 370, "extended_time": 0})
    data = mapping(mapping(payload).get("data"))
    raw = data.get("kline_list")
    precision = number(data.get("volume_precision", mapping(payload).get("volume_precision")))
    bars, stats = parse_bars(raw, "moomoo", reader.day)
    shifted, shifted_stats = parse_bars(raw, "moomoo", reader.day, -60000)
    if isinstance(precision, int) and 0 <= precision <= 9:
        for bar in list(bars.values()) + list(shifted.values()):
            bar["v"] /= 10**precision
    else:
        # Price comparison may proceed, but unknown volume units cannot.
        for bar in list(bars.values()) + list(shifted.values()):
            bar["v"] = None
        stats["volume_comparison"] = "unavailable_precision"
    stats.update(schema="documented" if isinstance(raw, list) else "missing_kline_list",
                 end_label_hypothesis=shifted_stats,
                 volume_precision=precision, pagination_has_more=mapping(mapping(payload).get("pagination")).get("has_more") is True,
                 next_time_present=any("next_time" in mapping(part) for part in (payload, data, mapping(payload).get("extra"))),
                 page_limit=1, adjustment="raw", interval="1Min", requested_start=str(reader.day),
                 requested_end=str(reader.day + timedelta(days=1)))
    return bars, stats, shifted


def compare_interpretations(bars: dict, shifted: dict, baseline: dict, volume_available: bool) -> dict:
    result = {"as_reported_labels": compare_bars(bars, baseline),
              "moomoo_end_label_hypothesis": compare_bars(shifted, baseline),
              "timestamp_semantics": "Minus one minute is an explicitly unverified diagnostic hypothesis, not production normalization."}
    if not volume_available:
        for key in ("as_reported_labels", "moomoo_end_label_hypothesis"):
            result[key]["fields"].pop("v", None)
    return result


def volatility(payload) -> dict:
    rows = items(mapping(mapping(payload).get("data")).get("item_list"))
    valid = [row for row in rows if isinstance(row, dict) and timestamp(row.get("timestamp"))]
    sample = [{k: number(row.get(k)) for k in ("timestamp", "implied_volatility", "history_volatility", "volatility_premium")}
              for row in sorted(valid, key=lambda r: r["timestamp"])[-2:]]
    return {"returned_points": len(rows), "timestamped_points": len(valid), "last_two": sample,
            "observed_spacing_ms": sorted({b["timestamp"] - a["timestamp"] for a, b in zip(sorted(valid, key=lambda r: r["timestamp"]), sorted(valid, key=lambda r: r["timestamp"])[1:])}),
            "units": "IV/HV percent; premium percentage points", "historical_cadence_verified": False}


def option_quantity(value) -> int | None:
    """Decode reported nonnegative int64 quantities, including JSON strings.

    This does not convert shares, lots or contracts. Reject arbitrary text,
    fractional values and floating integers whose precision cannot be trusted.
    Price, IV and Greek parsing deliberately retain their existing rules.
    """
    if isinstance(value, str):
        if not re.fullmatch(r"[0-9]{1,19}", value):
            return None
        value = int(value)
    numeric = number(value)
    if numeric is None or not 0 <= numeric <= 2**63 - 1:
        return None
    if isinstance(numeric, float) and (not numeric.is_integer() or numeric > 2**53 - 1):
        return None
    return int(numeric)


def quote_fields(row: dict, provider: str) -> dict:
    if provider == "tradier":
        greek = mapping(row.get("greeks"))
        result = {k: number(row.get(k)) for k in ("bid", "ask", "last", "bidsize", "asksize", "open_interest")}
        result["greeks"] = {k: number(greek.get(k)) for k in ("delta", "gamma", "theta", "vega", "mid_iv")}
        result["source_times_ms"] = {k: timestamp(row.get(k)) for k in ("bid_date", "ask_date", "trade_date")}
        result["greeks_time_ms"] = iso_ms(greek.get("updated_at"))
        result["greeks_timestamp_present"] = bool(greek.get("updated_at"))
    elif provider == "alpaca":
        q, trade = mapping(row.get("latestQuote")), mapping(row.get("latestTrade"))
        result = {"bid": number(q.get("bp")), "ask": number(q.get("ap")), "last": number(trade.get("p")),
                  "bid_size": number(q.get("bs")), "ask_size": number(q.get("as")),
                  "iv": number(row.get("impliedVolatility")),
                  "greeks": {k: number(mapping(row.get("greeks")).get(k)) for k in ("delta", "gamma", "theta", "vega")},
                  "source_times_ms": {"quote": iso_ms(q.get("t")), "trade": iso_ms(trade.get("t"))}}
    else:
        quantities = {"bid_volume", "ask_volume", "open_interest", "volume"}
        result = {k: option_quantity(row.get(k)) if k in quantities else number(row.get(k))
                  for k in ("price", "bid_price", "ask_price", "bid_volume", "ask_volume", "open_interest", "volume", "implied_volatility", "delta", "gamma", "theta", "vega", "multiplier", "contract_share_size")}
        result.update(units="Reported values; screener wire scaling and Greek conventions not established.",
                      source_time_ms=None, freshness="No documented per-contract quote timestamp in screen response.")
    return result


def screen_occ(code) -> str | None:
    """Map only validated standard-format NVDA screen codes to OCC IDs.

    The fixed chain trial established the unpadded strike suffix in moomoo.
    This mapping is diagnostic only; adjusted/nonstandard roots are excluded.
    """
    if not isinstance(code, str):
        return None
    match = re.fullmatch(r"US\.(NVDA)(\d{6})([CP])(\d{1,8})", code)
    if not match:
        return None
    try:
        datetime.strptime(match[2], "%y%m%d")
    except ValueError:
        return None
    if int(match[4]) <= 0:
        return None
    return match[1] + match[2] + match[3] + match[4].zfill(8)


def settings(path: Path) -> dict:
    names = ("ALPACA_API_KEY", "ALPACA_API_SECRET", "ALPACA_DATA_FEED", "ALPACA_OPTIONS_FEED", "TRADIER_API_KEY", "TRADIER_BASE_URL", "POLYGON_API_KEY")
    values = dotenv_values(path, interpolate=False) if path.is_file() else {}
    return {name: os.environ.get(name, values.get(name) or "") for name in names}


def run(reader: Reader, config: dict) -> dict:
    day = reader.day
    report = {"captured_at_utc": datetime.now(timezone.utc).isoformat(), "session": str(day),
              "symbol": UNDERLYING, "contracts": {"active": ACTIVE, "expired": EXPIRED},
              "market_hours_streaming": "deferred; no WebSocket", "history": {}, "comparisons": {},
              "warnings": ["One session, two fixed NVDA calls; no general provider superiority claim.",
                           "Current snapshots are market-closed observations, not historical fill Greeks."]}
    clock = reader.read("clock", "moomoo", "GET", HOST + TIME_PATH)
    server = mapping(clock).get("server_time_ms")
    if isinstance(server, str) and re.fullmatch(r"\d{1,14}", server):
        reader.offset = int(server) - reader.records["clock"]["received_at_ms"] + reader.records["clock"]["round_trip_ms"] / 2
    basic = reader.read("basic", "moomoo", "POST", HOST + BASIC_PATH, body={"code_list": list(SYMBOLS)}, headers={"Content-Type": "application/json"})
    metadata = [row for row in items(mapping(mapping(basic).get("data")).get("basic_list")) if isinstance(row, dict) and row.get("code") in SYMBOLS]
    report["metadata"] = {row["code"]: {k: number(row.get(k)) for k in ("lot_size", "contract_size", "stock_id")} for row in metadata}
    for label, expiry in (("active_chain", "2026-10-16"), ("expired_chain", "2026-10-09")):
        chain = reader.read(label, "moomoo", "GET", HOST + "/api/v1.0/quote/US.NVDA/option-chain", params={"start": expiry, "end": expiry})
        chain_rows = items(mapping(mapping(chain).get("data")).get("option_chain"))
        report[label] = {"returned_contracts": len(chain_rows), "requested_contract_present": any(mapping(row).get("code") == (ACTIVE if label == "active_chain" else EXPIRED) for row in chain_rows)}
    moomoo_bars, shifted_bars = {}, {}
    for symbol in SYMBOLS:
        moomoo_bars[symbol], report["history"][symbol], shifted_bars[symbol] = history(reader, symbol)
    for symbol in (ACTIVE, EXPIRED):
        payload = reader.read("volatility_" + symbol, "moomoo", "GET", HOST + f"/api/v1.0/quote/{symbol}/option-volatility", params={"query_time_period": 1, "hv_time_period": 30})
        report.setdefault("volatility", {})[symbol] = volatility(payload)
    screen_comparisons = {}
    stock = next((row for row in metadata if row["code"] == UNDERLYING), {})
    stock_id = number(stock.get("stock_id"))
    if isinstance(stock_id, int) and stock_id > 0:
        fields = {k: 1 for k in ("price", "bid_price", "ask_price", "bid_volume", "ask_volume", "volume",
                                "open_interest", "multiplier", "contract_share_size", "delta", "gamma", "theta", "vega", "implied_volatility")}
        screen = reader.read("option_screen", "moomoo", "POST", HOST + SCREEN_PATH, headers={"Content-Type": "application/json"},
                             body={"strategy": {"market_category_list": [0], "filter_group_list": [{"underlying_list": [{"indicator_type": 101, "indicator_value": {"value_list": [stock_id]}}]}]},
                                   "field_filter": fields, "limit": 5, "next_key": ""})
        screen_rows = items(mapping(mapping(screen).get("data")).get("option_list"))
        report["option_screen"] = {"returned_contracts": len(screen_rows), "requested_contracts": {s: quote_fields(row, "moomoo") for row in screen_rows if isinstance(row, dict) and (s := row.get("code")) in (ACTIVE, EXPIRED)},
                                   "bounded_sample": [{"symbol": row["code"], **quote_fields(row, "moomoo")} for row in screen_rows[:2] if isinstance(row, dict) and screen_occ(row.get("code"))],
                                   "limited_to": "Five highest-volume NVDA contracts; absence does not prove lack of access."}
        for row in screen_rows[:2]:
            symbol = screen_occ(mapping(row).get("code"))
            if symbol:
                screen_comparisons[symbol] = {"moomoo": quote_fields(row, "moomoo"),
                                              "interpretation": "Side-by-side reported values only; moomoo timestamp/units/models unverified."}
    quote_symbols = list(dict.fromkeys([OCC[ACTIVE], OCC[EXPIRED], *screen_comparisons]))
    start = datetime.combine(day, day_time(9, 30), ET).isoformat()
    end = datetime.combine(day, day_time(16), ET).isoformat()
    alpaca_headers = {"APCA-API-KEY-ID": config.get("ALPACA_API_KEY", ""), "APCA-API-SECRET-KEY": config.get("ALPACA_API_SECRET", "")}
    stock_feed = config.get("ALPACA_DATA_FEED") or "iex"
    option_feed = config.get("ALPACA_OPTIONS_FEED") or "indicative"
    if stock_feed not in ("iex", "sip") or option_feed not in ("indicative", "opra"):
        raise DiagnosticError("Configured comparison feed is unsupported by this diagnostic.")
    report["baseline_feeds"] = {"alpaca_stock": stock_feed, "alpaca_option_snapshot": option_feed,
                                "alpaca_option_history": "endpoint default; existing fetch_option_bars omits feed", "polygon_stock": "split-adjusted", "moomoo_history": "raw"}
    if all(alpaca_headers.values()):
        for label, path, symbols, feed in (("alpaca_stock_history", "/v2/stocks/bars", ["NVDA"], stock_feed),
                                          ("alpaca_option_history", "/v1beta1/options/bars", [OCC[ACTIVE], OCC[EXPIRED]], None)):
            params = {"symbols": ",".join(symbols), "timeframe": "1Min", "start": start, "end": end, "limit": 1000, "sort": "asc"}
            if feed:
                params.update(feed=feed, adjustment="raw")
            payload = reader.read(label, "alpaca", "GET", "https://data.alpaca.markets" + path, params=params, headers=alpaca_headers)
            for symbol in symbols:
                bars, stats = parse_bars(mapping(mapping(payload).get("bars")).get(symbol), "alpaca", day)
                stats["next_page_present"] = bool(mapping(payload).get("next_page_token"))
                report["history"]["alpaca_" + symbol] = stats
                moomoo_symbol = next(s for s in SYMBOLS if OCC[s] == symbol)
                comparison = compare_interpretations(moomoo_bars[moomoo_symbol], shifted_bars[moomoo_symbol], bars,
                                                     not report["history"][moomoo_symbol].get("volume_comparison"))
                report["comparisons"]["moomoo_vs_alpaca_" + symbol] = comparison
        payload = reader.read("alpaca_option_snapshots", "alpaca", "GET", "https://data.alpaca.markets/v1beta1/options/snapshots",
                              params={"symbols": ",".join(quote_symbols), "feed": option_feed}, headers=alpaca_headers)
        report["alpaca_snapshots"] = {s: quote_fields(mapping(mapping(mapping(payload).get("snapshots")).get(s)), "alpaca") for s in quote_symbols}
        for s, comparison in screen_comparisons.items():
            comparison["alpaca"] = report["alpaca_snapshots"][s]
    else:
        report["alpaca"] = "credentials_unavailable"
    if config.get("TRADIER_API_KEY"):
        host = config.get("TRADIER_BASE_URL") or "https://api.tradier.com"
        if host not in ("https://api.tradier.com", "https://sandbox.tradier.com"):
            raise DiagnosticError("Configured Tradier host is outside the diagnostic allowlist.")
        report["tradier_environment"] = "production_market_data" if host == "https://api.tradier.com" else "sandbox_market_data"
        payload = reader.read("tradier_quotes", "tradier", "POST", host + "/v1/markets/quotes", form={"symbols": ",".join(["NVDA", *quote_symbols]), "greeks": "true"},
                              headers={"Authorization": "Bearer " + config["TRADIER_API_KEY"], "Accept": "application/json"})
        quote = mapping(mapping(payload).get("quotes")).get("quote")
        quotes = [quote] if isinstance(quote, dict) else items(quote)
        report["tradier_quotes"] = {s: quote_fields(row, "tradier") for row in quotes if isinstance(row, dict) and (s := row.get("symbol")) in ["NVDA", *quote_symbols]}
        for s, comparison in screen_comparisons.items():
            comparison["tradier"] = report["tradier_quotes"].get(s, {"status": "absent"})
    else:
        report["tradier"] = "credentials_unavailable"
    if config.get("POLYGON_API_KEY"):
        path = f"/v2/aggs/ticker/NVDA/range/1/minute/{day}/{day}"
        payload = reader.read("polygon_stock_history", "polygon", "GET", "https://api.polygon.io" + path,
                              params={"adjusted": "true", "sort": "asc", "limit": 1000}, headers={"Authorization": "Bearer " + config["POLYGON_API_KEY"]})
        bars, stats = parse_bars(mapping(payload).get("results"), "polygon", day)
        stats["next_page_present"] = bool(mapping(payload).get("next_url"))
        report["history"]["polygon_NVDA"] = stats
        comparison = compare_interpretations(moomoo_bars[UNDERLYING], shifted_bars[UNDERLYING], bars,
                                             not report["history"][UNDERLYING].get("volume_comparison"))
        report["comparisons"]["moomoo_vs_polygon_NVDA"] = comparison
    else:
        report["polygon"] = "credentials_unavailable"
    report.update(screen_current_comparison=screen_comparisons, requests=reader.records, request_count=reader.count, max_requests=MAX_REQUESTS,
                  elapsed_seconds=round(time.monotonic() - reader.started, 3),
                  status="completed" if all(row["status"] == "success" for row in reader.records.values()) else "completed_with_request_failures",
                  conclusion="Diagnostic evidence only. No data-source replacement, journal metric recalculation or live collection.")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--day", type=date.fromisoformat, default=DEFAULT_DAY, help="One historical regular session; default 2026-10-09.")
    parser.add_argument("--baseline-env", type=Path, default=Path.home() / "TradeJournal/backend/.env", help="Existing local provider credential file; values are never printed.")
    args = parser.parse_args()
    # The fixed contracts must both exist during the chosen historical session.
    if not date(2026, 10, 5) <= args.day <= DEFAULT_DAY or args.day.weekday() >= 5:
        parser.error("--day must be a weekday from 2026-10-05 through 2026-10-09 for the fixed contracts.")
    try:
        appkey = secure_read(KEY_DIR / "appkey").decode("ascii").strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", appkey):
            raise DiagnosticError("AppKey format is invalid.")
        key = serialization.load_pem_private_key(secure_read(KEY_DIR / "phase1-ed25519.pem"), password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise DiagnosticError("An Ed25519 key is required.")
        with quiet_logging(), httpx.Client(timeout=15, follow_redirects=False, trust_env=False) as client:
            report = run(Reader(client, args.day, appkey, key), settings(args.baseline_env))
        print(json.dumps(report, indent=2, allow_nan=False))
        return 0 if report["status"] == "completed" else 1
    except DiagnosticError as exc:
        print(str(exc))
    except (OSError, ValueError, TypeError, UnicodeError):
        print("Diagnostic configuration or response could not be read safely; details withheld.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
