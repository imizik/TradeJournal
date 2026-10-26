"""Prepare one fixed ETF input archive; no returns, evaluator or Factory writes.

Default prints the request plan. --acquire requires separate owner approval of
this plan and credential source. A successful archive is still unaccepted input.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
from io import StringIO
import json
from pathlib import Path
import re
import signal
import time
from zoneinfo import ZoneInfo

from dotenv import dotenv_values
import httpx

SYMBOLS = ("SPY", "EFA", "EEM", "IEF", "BIL")
BARS = "https://data.alpaca.markets/v2/stocks/bars"
ACTIONS = "https://data.alpaca.markets/v1/corporate-actions"
CREDENTIAL_SOURCE = Path("/Users/user/TradeJournal-factory/backend/.env")
PRICE_START, PRICE_END = "2016-01-01", "2024-09-30"
ACTION_END = "2026-10-26"  # fixed retrieval cutoff, never today's implicit default
DATES_SHA256 = "e146c2a83fc72017fdde4f6f4fcb4b9862e5def917e435fbe72f642a1bbed9e7"
MAX_SECONDS, MAX_BYTES = 120, 3_000_000
ET = ZoneInfo("America/New_York")


class AcquisitionError(ValueError):
    pass


def request_plan() -> dict:
    return {
        "kind": "etf_input_acquisition_plan_only", "symbols": list(SYMBOLS),
        "credential_source": str(CREDENTIAL_SOURCE),
        "credential_fields": ["ALPACA_API_KEY", "ALPACA_API_SECRET"],
        "max_requests": 12, "max_seconds": MAX_SECONDS, "max_response_bytes": MAX_BYTES,
        "retries": 0, "evaluation_authorized": False,
        "requests": [
            {"name": "bars", "url": BARS, "max_pages": 4, "params": {
                "symbols": ",".join(SYMBOLS), "timeframe": "1Day", "start": "2016-01-01T00:00:00-05:00",
                "end": "2024-09-30T23:59:59-04:00", "adjustment": "raw", "feed": "sip",
                "currency": "USD", "asof": PRICE_END, "sort": "asc", "limit": 10000}},
            {"name": "actions", "url": ACTIONS, "max_pages": 8, "params": {
                "symbols": ",".join(SYMBOLS), "start": PRICE_START, "end": ACTION_END,
                "data_quality": "all", "sort": "asc", "limit": 1000}}],
        "late_metadata_policy": "Retain source archive; only effective dates through 2024-09-30 may enter a future normalized input. No post-cutoff prices.",
    }


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_new(path: Path, raw: bytes) -> None:
    with path.open("xb") as handle:
        handle.write(raw)
    path.chmod(0o400)


def read_keys() -> tuple[str, str]:
    # Do not load app settings or any other dotenv entry, even for interpolation.
    selected = []
    with CREDENTIAL_SOURCE.open() as source:
        for line in source:
            if re.match(r"^\s*(?:export\s+)?(?:ALPACA_API_KEY|ALPACA_API_SECRET)\s*=", line):
                selected.append(line)
    values = dotenv_values(stream=StringIO("".join(selected)), interpolate=False)
    key, secret = values.get("ALPACA_API_KEY"), values.get("ALPACA_API_SECRET")
    if not key or not secret:
        raise AcquisitionError("named market-data credentials unavailable")
    return key, secret


def coverage(bar_pages: list[dict]) -> dict:
    """No return arithmetic. Compare dates to the previously audited calendar."""
    dates = {s: [] for s in SYMBOLS}
    for page in bar_pages:
        groups = page.get("bars")
        if not isinstance(groups, dict) or set(groups) - set(SYMBOLS):
            raise AcquisitionError("unexpected bar symbols/envelope")
        for symbol, rows in groups.items():
            if not isinstance(rows, list):
                raise AcquisitionError("invalid bar rows")
            for row in rows:
                try:
                    timestamp = datetime.fromisoformat(row["t"].replace("Z", "+00:00"))
                    if timestamp.tzinfo is None:
                        raise ValueError("naive timestamp")
                    day = timestamp.astimezone(ET).date().isoformat()
                    values = {f: Decimal(str(row[f])) for f in ("o", "h", "l", "c", "v", "n", "vw")}
                    valid = (all(v.is_finite() for v in values.values())
                             and values["l"] > 0 and values["vw"] > 0
                             and values["l"] <= values["o"] <= values["h"]
                             and values["l"] <= values["c"] <= values["h"]
                             and values["v"] >= 0 and values["n"] >= 0)
                    if not valid or not PRICE_START <= day <= PRICE_END:
                        raise ValueError("invalid/out-of-window bar")
                except (KeyError, TypeError, ValueError, ArithmeticError):
                    raise AcquisitionError("invalid/out-of-window bar") from None
                dates[symbol].append(day)
    output = {}
    for symbol, days in dates.items():
        digest = hashlib.sha256(("\n".join(days) + "\n").encode()).hexdigest()
        if len(days) != 2200 or days != sorted(set(days)) or digest != DATES_SHA256:
            raise AcquisitionError("daily dates do not match the audited 2,200-session calendar")
        output[symbol] = {"count": len(days), "dates_sha256": digest}
    return output


def acquire(destination: Path, key: str, secret: str, *, transport=None,
            clock=time.monotonic) -> dict:
    """Archive fixed GETs once; failures retain partial evidence, never retry.

    No performance module is imported. Terminal pagination is traversal evidence,
    not proof of complete historical distributions, dated identity or known-at.
    """
    if not key or not secret or not destination.is_absolute():
        raise AcquisitionError("credentials and an absolute fresh destination required")
    destination.mkdir(mode=0o700, parents=False, exist_ok=False)
    plan = request_plan()
    receipt = {"kind": "etf_input_archive_unaccepted", "plan": plan, "pages": [],
               "status": "incomplete", "eligible_for_evaluation": False,
               "known_at": None, "issuer_reconciliation": "not_performed",
               "historical_actions_complete": "unverified", "strategy_evaluated": False}
    started, bar_pages = clock(), []
    try:
        with httpx.Client(headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret},
                          transport=transport, follow_redirects=False, trust_env=False, timeout=10) as client:
            for request in plan["requests"]:
                token, seen = None, set()
                for page in range(request["max_pages"]):
                    if clock() - started >= MAX_SECONDS:
                        raise AcquisitionError("elapsed-time cap reached")
                    params = dict(request["params"])
                    if token is not None:
                        params["page_token"] = token
                    at = utc_now()
                    with client.stream("GET", request["url"], params=params) as response:
                        if response.status_code != 200:
                            raise AcquisitionError(f"GET refused: HTTP {response.status_code}")
                        chunks, size = [], 0
                        for chunk in response.iter_bytes():
                            size += len(chunk)
                            if size > MAX_BYTES or clock() - started >= MAX_SECONDS:
                                raise AcquisitionError("response size/time cap reached")
                            chunks.append(chunk)
                    raw = b"".join(chunks)
                    name = f'{request["name"]}-{page}.json'
                    write_new(destination / name, raw)
                    item = {"file": name, "url": request["url"], "params": params,
                            "request_started_at": at, "response_received_at": utc_now(),
                            "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(), "http_status": 200}
                    receipt["pages"].append(item)
                    document = json.loads(raw)
                    if not isinstance(document, dict):
                        raise AcquisitionError("invalid response envelope")
                    if request["name"] == "bars":
                        bar_pages.append(document)
                    elif not isinstance(document.get("corporate_actions"), dict):
                        raise AcquisitionError("invalid actions envelope")
                    token = document.get("next_page_token")
                    item["terminal_page"] = token is None or token == ""
                    if item["terminal_page"]:
                        break
                    if not isinstance(token, str) or len(token) > 4096 or token in seen:
                        raise AcquisitionError("invalid or repeated pagination token")
                    seen.add(token)
                else:
                    raise AcquisitionError("page cap reached; traversal incomplete")
                if request["name"] == "bars":
                    receipt["daily_coverage"] = coverage(bar_pages)
            receipt["status"] = "acquired_unaccepted"
    except (httpx.HTTPError, ValueError, TypeError, OSError) as exc:
        # Never include provider body, credentials or exception text in output.
        receipt["failure_type"] = type(exc).__name__
        raise AcquisitionError("acquisition incomplete; inspect metadata receipt, no automatic retry") from None
    finally:
        write_new(destination / "receipt.json", (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode())
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--acquire", action="store_true", help="separate approval required; fixed request plan only")
    parser.add_argument("--output", type=Path, help="new absolute local archive directory")
    args = parser.parse_args(argv)
    if not args.acquire:
        if args.output:
            parser.error("--output requires --acquire")
        print(json.dumps(request_plan(), sort_keys=True))
        return
    if args.output is None or not args.output.is_absolute() or args.output.exists():
        parser.error("--acquire needs a new absolute --output directory")
    def deadline(signum, frame):
        raise AcquisitionError("process deadline reached")
    previous = signal.signal(signal.SIGALRM, deadline)
    signal.alarm(MAX_SECONDS)  # Hard deadline also covers blocked socket reads.
    try:
        key, secret = read_keys()
        result = acquire(args.output, key, secret)
    except (AcquisitionError, OSError):
        parser.exit(1, "ETF acquisition failed; no automatic retry or evaluation.\n")
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
