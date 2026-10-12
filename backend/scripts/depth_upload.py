"""Move finished depth-recorder days to a private R2 bucket (python -m scripts.depth_upload).

Runs from its own nightly timer, after the recording window. For each finished
day (before today in New York, or today once the 20:00 window has closed) it PUTs every ticker file to
`depth/v1/<TICKER>/<YYYY>/<YYYY-MM-DD>.jsonl.gz`, confirms the stored size
with a HEAD, then marks the day uploaded. Uploaded days older than
LOCAL_DAYS are deleted locally; a day that has not been confirmed is never
deleted here. Credentials come only from its own environment file (a
bucket-scoped token, never the offsite backup's), and are never logged.
"""
from __future__ import annotations

from datetime import date, datetime, time as day_time, timezone
import hashlib
import hmac
import logging
import os
from pathlib import Path
import re
import shutil
from urllib.parse import quote, urlsplit
from zoneinfo import ZoneInfo

import httpx

STATE = Path(os.environ.get("TJ_DEPTH_DIR", "/var/lib/tradejournal-depth"))
NEW_YORK = ZoneInfo("America/New_York")
LOCAL_DAYS = 3
MARKER = ".uploaded"
# Tells the recorder an uploader exists, so it never deletes an unconfirmed day itself.
UPLOADER_SEEN = ".uploader"
LOG = logging.getLogger("depth-upload")
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()


class UploadError(Exception):
    """Fixed, credential-free messages only."""


def config(environ=os.environ) -> dict:
    endpoint = environ.get("TJ_DEPTH_R2_ENDPOINT", "")
    parts = urlsplit(endpoint)
    if (parts.scheme != "https" or not parts.hostname or not parts.hostname.endswith(".r2.cloudflarestorage.com")
            or parts.path.strip("/") or parts.query or parts.port or parts.username):
        raise UploadError("TJ_DEPTH_R2_ENDPOINT must be the account endpoint https://ACCOUNT_ID.r2.cloudflarestorage.com.")
    bucket = environ.get("TJ_DEPTH_R2_BUCKET", "")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]", bucket):
        raise UploadError("TJ_DEPTH_R2_BUCKET is not a valid bucket name.")
    key_id, secret = environ.get("TJ_DEPTH_R2_ACCESS_KEY_ID", ""), environ.get("TJ_DEPTH_R2_SECRET_ACCESS_KEY", "")
    if not key_id or not secret:
        raise UploadError("The depth bucket's access key is not configured.")
    return {"host": parts.hostname, "bucket": bucket, "key_id": key_id, "secret": secret}


def sign(method: str, host: str, path: str, headers: dict[str, str], payload_sha256: str, key_id: str, secret: str,
         moment: datetime, region: str = "auto", service: str = "s3") -> dict[str, str]:
    """AWS Signature Version 4 headers for one path-style request (no query string)."""
    stamp, day = moment.strftime("%Y%m%dT%H%M%SZ"), moment.strftime("%Y%m%d")
    signed = {**{name.lower(): value.strip() for name, value in headers.items()},
              "host": host, "x-amz-content-sha256": payload_sha256, "x-amz-date": stamp}
    names = sorted(signed)
    canonical = "\n".join([method, quote(path, safe="/~"), "", *[f"{name}:{signed[name]}" for name in names], "",
                           ";".join(names), payload_sha256])
    scope = f"{day}/{region}/{service}/aws4_request"
    to_sign = "\n".join(["AWS4-HMAC-SHA256", stamp, scope, hashlib.sha256(canonical.encode()).hexdigest()])
    key = ("AWS4" + secret).encode()
    for part in (day, region, service, "aws4_request"):
        key = hmac.new(key, part.encode(), hashlib.sha256).digest()
    signature = hmac.new(key, to_sign.encode(), hashlib.sha256).hexdigest()
    return {**{name: value for name, value in signed.items() if name != "host"},
            "authorization": f"AWS4-HMAC-SHA256 Credential={key_id}/{scope}, SignedHeaders={';'.join(names)}, Signature={signature}"}


def object_key(ticker: str, day: str) -> str:
    return f"depth/v1/{ticker}/{day[:4]}/{day}.jsonl.gz"


def upload_file(client: httpx.Client, settings: dict, path: Path, key: str) -> None:
    body = path.read_bytes()
    digest = hashlib.sha256(body).hexdigest()
    target = f"/{settings['bucket']}/{key}"
    url = f"https://{settings['host']}{quote(target, safe='/~')}"
    headers = sign("PUT", settings["host"], target, {"content-type": "application/gzip"}, digest,
                   settings["key_id"], settings["secret"], datetime.now(timezone.utc))
    response = client.put(url, content=body, headers=headers)
    if response.status_code != 200:
        raise UploadError(f"Upload was refused (HTTP {response.status_code}).")
    headers = sign("HEAD", settings["host"], target, {}, EMPTY_SHA256, settings["key_id"], settings["secret"], datetime.now(timezone.utc))
    check = client.head(url, headers=headers)
    if check.status_code != 200 or check.headers.get("content-length") != str(len(body)):
        raise UploadError("The stored object did not match the local file.")


def finished_days(root: Path, now: datetime) -> list[Path]:
    local = now.astimezone(NEW_YORK)
    last = local.date() if local.time() >= day_time(20, 5) else date.fromordinal(local.date().toordinal() - 1)
    days = []
    for folder in sorted(root.glob("????-??-??")):
        try:
            if date.fromisoformat(folder.name) <= last:
                days.append(folder)
        except ValueError:
            continue
    return days


def run(root: Path = STATE, settings: dict | None = None, client: httpx.Client | None = None, now: datetime | None = None) -> dict:
    settings = settings or config()
    now = now or datetime.now(timezone.utc)
    today = now.astimezone(NEW_YORK).date()
    result = {"uploaded": 0, "days": 0, "removed": 0}
    own = client is None
    client = client or httpx.Client(timeout=60, follow_redirects=False, trust_env=False)
    (root / UPLOADER_SEEN).touch()
    try:
        for folder in finished_days(root, now):
            if not (folder / MARKER).exists():
                for path in sorted(folder.glob("*.jsonl.gz")):
                    ticker = path.name.removesuffix(".jsonl.gz")
                    if not re.fullmatch(r"[A-Z]{1,5}(\.[A-Z])?", ticker):
                        continue
                    upload_file(client, settings, path, object_key(ticker, folder.name))
                    result["uploaded"] += 1
                (folder / MARKER).write_text(datetime.now(timezone.utc).isoformat())
                result["days"] += 1
            if (today - date.fromisoformat(folder.name)).days > LOCAL_DAYS and (folder / MARKER).exists():
                shutil.rmtree(folder)
                result["removed"] += 1
    finally:
        if own:
            client.close()
    return result


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        result = run()
    except (UploadError, httpx.HTTPError, OSError) as exc:
        # UploadError text is fixed; other errors are reduced to their type.
        raise SystemExit(str(exc) if isinstance(exc, UploadError) else f"Depth upload failed ({type(exc).__name__}).") from None
    LOG.info("Uploaded %s files for %s days; removed %s local days.", result["uploaded"], result["days"], result["removed"])


if __name__ == "__main__":
    main()
