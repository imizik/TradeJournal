#!/usr/bin/env python3
"""Small localhost-only deployment automations."""

import argparse
import json
import re
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

API = "http://127.0.0.1:8080"


def request(path: str, method: str = "GET"):
    request = Request(f"{API}{path}", method=method)
    try:
        with urlopen(request, timeout=15) as response:
            return response.status, json.load(response)
    except HTTPError as exc:
        if exc.code == 409:
            return exc.code, json.load(exc)
        raise


def wait_for_job(job_id: str, timeout: float = 240) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        _, runs = request("/sync/runs?limit=100")
        row = next((run for run in runs if run["id"] == job_id), None)
        if row and row["status"] in {"succeeded", "failed"}:
            if row["status"] == "failed":
                raise RuntimeError(row.get("error_summary") or f"Job failed: {job_id}")
            return row
        time.sleep(1)
    raise TimeoutError(f"Timed out waiting for job: {job_id}")


def start_job(job_type: str, *, retry_conflict: bool = False) -> str | None:
    deadline = time.monotonic() + 240
    while True:
        status, response = request(f"/sync/jobs/{job_type}/run", "POST")
        if status != 409:
            return response["run_id"]
        if not retry_conflict or time.monotonic() >= deadline:
            return None
        time.sleep(5)


def gmail_sync() -> None:
    job_id = start_job("gmail_sync")
    if job_id is None:
        print("Gmail sync skipped: another sync or enrichment job is active")
        return
    result = wait_for_job(job_id)
    message = result.get("message") or ""
    match = re.search(r"Imported (\d+) new fill", message)
    if not match:
        raise RuntimeError(f"Gmail sync returned an unexpected result: {message}")
    imported = int(match.group(1))
    print(f"Gmail sync succeeded: {message}")
    if not imported:
        return
    rebuild_id = start_job("trade_rebuild", retry_conflict=True)
    if rebuild_id is None:
        raise RuntimeError("Could not queue trade rebuild after importing fills")
    rebuilt = wait_for_job(rebuild_id)
    print(f"Trade rebuild succeeded: {rebuilt.get('message') or ''}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["gmail-sync"])
    args = parser.parse_args()
    if args.action == "gmail-sync":
        gmail_sync()


if __name__ == "__main__":
    main()
