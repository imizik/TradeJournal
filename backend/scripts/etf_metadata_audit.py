"""Bounded, read-only ETF reference audit. No prices, strategy or trading APIs."""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import time

import httpx

SYMBOLS = ("SPY", "EFA", "EEM", "IEF")
CUSIPS = dict(zip(SYMBOLS, ("78462F103", "464287465", "464287234", "464287440")))
ASSET_URL = "https://api.alpaca.markets/v2/assets/"
ACTIONS_URL = "https://data.alpaca.markets/v1/corporate-actions"
FIXTURE = Path(__file__).resolve().parents[1] / "tests/fixtures/etf_metadata/audit.json"
MAX_PAGES = 10
MAX_BYTES = 2_000_000
# Exchange notice: https://www.nasdaqtrader.com/content/phlxmemos/2008/Jul/1410-08.pdf
KNOWN_SPLIT = {"symbol": "EEM", "ex_date": "2008-07-24", "kind": "forward_splits"}


class AuditError(ValueError):
    pass


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def window(start: str, end: str) -> None:
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    if first > last or (last - first).days > 366:
        raise AuditError("metadata window must be ordered and at most 367 inclusive days")


def audit(fetch, start: str, end: str, *, expected=None, clock=utc_now) -> dict:
    """Fetch current identities and all action pages in a process-date window.

    Transport failure aborts without publishing a partial manifest. A terminal
    page proves traversal only, never historical coverage or knowledge time.
    Expected events are metadata sentinels, not completeness assertions.
    """
    window(start, end)
    if expected is None:
        expected = [KNOWN_SPLIT] if start <= "2008-07-01" and end >= "2008-08-15" else []
    assets, pages, actions, issues = [], [], [], []
    asset_ids = set()
    for symbol in SYMBOLS:
        raw = fetch(ASSET_URL + symbol, {})
        if not isinstance(raw, dict) or raw.get("symbol") != symbol or not raw.get("id"):
            raise AuditError("invalid asset identity response")
        if not isinstance(raw["id"], str) or raw["id"] in asset_ids:
            raise AuditError("invalid or reused asset identity")
        asset_ids.add(raw["id"])
        if raw.get("class", raw.get("asset_class")) != "us_equity":
            raise AuditError("unexpected asset class")
        assets.append({"symbol": symbol, "provider_id": raw["id"], "observed_at": clock(),
                       "known_at": None, "scope": "current_reference_only", "raw": raw,
                       "sha256": digest(raw)})
    token = None
    tokens = set()
    by_id = {}
    duplicates = 0
    for page_index in range(MAX_PAGES):
        params = {"symbols": ",".join(SYMBOLS), "start": start, "end": end,
                  "limit": 1000, "sort": "asc", "data_quality": "all"}
        if token is not None:
            params["page_token"] = token
        raw = fetch(ACTIONS_URL, params)
        observed = clock()
        if not isinstance(raw, dict) or not isinstance(raw.get("corporate_actions"), dict):
            raise AuditError("invalid corporate-actions envelope")
        pages.append({"index": page_index, "observed_at": observed, "sha256": digest(raw)})
        for kind, rows in raw["corporate_actions"].items():
            if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
                raise AuditError("invalid action group")
            for row in rows:
                action_id = row.get("id")
                fingerprint = digest({"kind": kind, "raw": row})
                if isinstance(action_id, str) and action_id:
                    if action_id in by_id:
                        if by_id[action_id] == fingerprint:
                            duplicates += 1
                            continue
                        issues.append({"reason": "conflicting_action_id", "id": action_id})
                    else:
                        by_id[action_id] = fingerprint
                else:
                    issues.append({"reason": "missing_action_id", "page": page_index})
                symbol = row.get("symbol")
                if symbol not in SYMBOLS:
                    issues.append({"reason": "missing_or_unexpected_symbol", "id": action_id})
                if symbol in CUSIPS and row.get("cusip") != CUSIPS[symbol]:
                    issues.append({"reason": "missing_or_changed_cusip", "id": action_id})
                dates = {}
                for field in ("ex_date", "effective_date", "record_date", "payable_date", "process_date"):
                    value = row.get(field)
                    dates[field] = value
                    if value is not None:
                        try:
                            date.fromisoformat(value)
                        except (ValueError, TypeError):
                            issues.append({"reason": "invalid_date", "id": action_id, "field": field})
                if dates["process_date"] is None:
                    issues.append({"reason": "missing_process_date", "id": action_id})
                if dates["ex_date"] is None and dates["effective_date"] is None:
                    issues.append({"reason": "missing_effective_date", "id": action_id})
                # Never substitute process/pay dates for ex/effective or known-at.
                actions.append({"kind": kind, "dates": dates, "observed_at": observed,
                                "known_at": None, "page": page_index, "raw": row,
                                "sha256": fingerprint})
        token = raw.get("next_page_token")
        if token is None or token == "":
            break
        if not isinstance(token, str) or len(token) > 4096 or token in tokens:
            raise AuditError("invalid or repeated pagination token")
        tokens.add(token)
    else:
        raise AuditError("page cap reached; traversal incomplete")
    for sentinel in expected:
        if not sentinel or not isinstance(sentinel, dict):
            raise AuditError("expected events must be nonempty metadata objects")
        if not any(all((row["kind"] if k == "kind" else row["raw"].get(k)) == v for k, v in sentinel.items()) for row in actions):
            issues.append({"reason": "expected_event_not_observed", "expected": sentinel})
    return {"kind": "etf_metadata_audit_only", "version": 1,
            "requested_process_window": {"start": start, "end": end},
            "shortlist": list(SYMBOLS), "pagination_complete": True,
            "historical_coverage": "unverified", "historical_identity": "unverified",
            "historical_known_at": "unavailable", "eligible_for_evaluation": False,
            "assets": assets, "pages": pages, "actions": actions, "issues": issues,
            "expected_events_checked": list(expected), "exact_duplicates_ignored": duplicates}


class MetadataReader:
    """Fixed GET destinations; no redirects, proxies, retries or body logging."""
    def __init__(self, key: str, secret: str, *, transport=None):
        if not key or not secret:
            raise AuditError("ALPACA_API_KEY and ALPACA_API_SECRET must be explicitly supplied")
        self.client = httpx.Client(headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret},
                                   timeout=10, follow_redirects=False, trust_env=False,
                                   transport=transport)
        self.started = time.monotonic()
        self.requests = 0

    def __call__(self, url: str, params: dict) -> dict:
        if url not in {ACTIONS_URL, *(ASSET_URL + s for s in SYMBOLS)}:
            raise AuditError("endpoint outside metadata allowlist")
        if self.requests >= len(SYMBOLS) + MAX_PAGES or time.monotonic() - self.started > 90:
            raise AuditError("request/time cap reached")
        self.requests += 1
        try:
            with self.client.stream("GET", url, params=params) as response:
                if response.status_code != 200:
                    raise AuditError(f"metadata request refused: HTTP {response.status_code}")
                chunks, size = [], 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > MAX_BYTES or time.monotonic() - self.started > 90:
                        raise AuditError("response size/time cap reached")
                    chunks.append(chunk)
                return json.loads(b"".join(chunks))
        except (httpx.HTTPError, json.JSONDecodeError, UnicodeDecodeError):
            raise AuditError("metadata transport or JSON failure; response details withheld") from None

    def close(self):
        self.client.close()


def fixture_audit() -> dict:
    fixture = json.loads(FIXTURE.read_text())
    def fetch(url, params):
        if url.startswith(ASSET_URL):
            return fixture["assets"][url.removeprefix(ASSET_URL)]
        index = int(params.get("page_token", "0"))
        return fixture["pages"][index]
    result = audit(fetch, fixture["start"], fixture["end"], expected=fixture["expected"],
                   clock=lambda: "2026-10-26T12:00:00+00:00")
    result["source"] = "invented_fixture"
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch-metadata", action="store_true")
    parser.add_argument("--start")
    parser.add_argument("--end")
    args = parser.parse_args()
    if args.fetch_metadata:
        if not args.start or not args.end:
            parser.error("explicit start and end required")
        window(args.start, args.end)
        reader = MetadataReader(os.environ.get("ALPACA_API_KEY", ""), os.environ.get("ALPACA_API_SECRET", ""))
        try:
            result = audit(reader, args.start, args.end)
            result["source"] = "alpaca_rest_metadata"
        finally:
            reader.close()
    else:
        if args.start or args.end:
            parser.error("dates require --fetch-metadata")
        result = fixture_audit()
    print(json.dumps(result, sort_keys=True, indent=2, allow_nan=False))


if __name__ == "__main__":
    try:
        main()
    except (AuditError, ValueError) as exc:
        raise SystemExit(str(exc)) from None
