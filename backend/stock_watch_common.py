"""Stock-only alert/review contract; never a paper-trade instruction."""

from datetime import UTC, timedelta
import math
import os
from pathlib import Path
import re
import tempfile
import uuid
from zoneinfo import ZoneInfo

from market_watch_common import parse_time, verify

FORMAT = "stock-alert-v1"
REVIEW_FORMAT = "stock-review-v1"
POLICY = {
    "version": "stock-watch-v2",
    "window_minutes": 15,
    "move_fraction": 0.01,
    "move_atr": 0.35,
    "reversal_fraction": 0.03,
    "reversal_atr": 0.5,
    "cooldown_minutes": 30,
    "freshness_seconds": 180,
    "expiry_minutes": 10,
}
ET = ZoneInfo("America/New_York")


def identifier(value, prefix):
    if not isinstance(value, str) or not value.startswith(prefix + "_"):
        raise ValueError("Invalid stock-watch identifier")
    if str(uuid.UUID(value[len(prefix) + 1 :])) != value[len(prefix) + 1 :]:
        raise ValueError("Require canonical stock-watch UUID")
    return value


def stamp(value):
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def finite(value, *, positive=False):
    if (
        type(value) not in (int, float)
        or not math.isfinite(value)
        or (positive and value <= 0)
    ):
        raise ValueError("Invalid stock price/volume")
    return value


def validate_alert(p):
    verify(p)
    if (
        set(p)
        != {
            "format",
            "alert_id",
            "session_date",
            "symbol",
            "kind",
            "direction",
            "source",
            "detected_at",
            "expires_at",
            "observed_at",
            "selected_symbols",
            "selection_revision",
            "evidence",
            "trade_eligibility",
            "diagnostic_code",
            "schema_version",
            "created_at",
            "content_sha256",
        }
        or p["format"] != FORMAT
    ):
        raise ValueError("Invalid stock alert schema")
    identifier(p["alert_id"], "sta")
    symbols = p["selected_symbols"]
    if (
        not isinstance(symbols, list)
        or not 1 <= len(symbols) <= 12
        or any(
            not isinstance(s, str) or not re.fullmatch(r"[A-Z]{1,6}(\.[A-Z])?", s)
            for s in symbols
        )
        or len(set(symbols)) != len(symbols)
        or p["symbol"] not in symbols
        or type(p["selection_revision"]) is not int
        or p["selection_revision"] < 0
    ):
        raise ValueError("Invalid frozen ticker selection")
    detected, expires, observed = [
        parse_time(p[k]) for k in ("detected_at", "expires_at", "observed_at")
    ]
    if (
        p["created_at"] != p["detected_at"]
        or detected.astimezone(ET).date().isoformat() != p["session_date"]
        or expires != detected + timedelta(minutes=POLICY["expiry_minutes"])
        or not 0 <= (detected - observed).total_seconds() <= POLICY["freshness_seconds"]
    ):
        raise ValueError("Invalid stock alert times")
    if p["direction"] not in ("up", "down") or p["kind"] not in (
        "scanner_setup",
        "move",
        "diagnostic",
    ):
        raise ValueError("Invalid stock alert kind/direction")
    eligibility = p["trade_eligibility"]
    if (
        not isinstance(eligibility, dict)
        or set(eligibility) != {"status", "reason"}
        or eligibility["status"] not in ("blocked", "not_evaluated")
        or not isinstance(eligibility["reason"], str)
        or not 1 <= len(eligibility["reason"]) <= 500
    ):
        raise ValueError("Stock awareness cannot authorize a trade")
    evidence = p["evidence"]
    if not isinstance(evidence, dict) or set(evidence) != {
        "price",
        "bars",
        "trigger",
        "candidate_id",
    }:
        raise ValueError("Invalid stock evidence")
    finite(evidence["price"], positive=True)
    if (
        not isinstance(evidence["trigger"], dict)
        or len(str(evidence["trigger"])) > 8000
    ):
        raise ValueError("Invalid stock trigger")
    if (
        evidence["candidate_id"] is not None
        and str(uuid.UUID(evidence["candidate_id"])) != evidence["candidate_id"]
    ):
        raise ValueError("Invalid original candidate")
    bars = evidence["bars"]
    if not isinstance(bars, list) or not 1 <= len(bars) <= 60:
        raise ValueError("Require bounded frozen minute bars")
    prior = None
    for b in bars:
        if set(b) != {"time", "end_time", "open", "high", "low", "close", "volume"}:
            raise ValueError("Invalid stock minute bar")
        for key in b:
            finite(b[key], positive=key in ("open", "high", "low", "close"))
        if (
            b["end_time"] != b["time"] + 60
            or b["time"] % 60
            or b["end_time"] > observed.timestamp()
            or (prior is not None and b["time"] <= prior)
            or b["volume"] < 0
            or not b["low"]
            <= min(b["open"], b["close"])
            <= max(b["open"], b["close"])
            <= b["high"]
        ):
            raise ValueError("Invalid completed stock bar")
        prior = b["time"]
    if (
        evidence["price"] != bars[-1]["close"]
        or (observed.timestamp() - bars[-1]["end_time"]) > POLICY["freshness_seconds"]
    ):
        raise ValueError("Stock alert bars are stale")
    if p["kind"] == "diagnostic":
        if (
            p["source"] != "delivery_diagnostic"
            or not isinstance(p["diagnostic_code"], str)
            or not re.fullmatch(r"STK-[A-Z0-9-]{1,60}", p["diagnostic_code"])
        ):
            raise ValueError("Invalid explicit delivery diagnostic")
    elif p["source"] != "tradier_timesales_1min" or p["diagnostic_code"] is not None:
        raise ValueError("Invalid stock source")
    return p


def validate_review(r, alert):
    verify(r)
    if (
        set(r)
        != {
            "format",
            "review_id",
            "alert_id",
            "alert_sha256",
            "session_date",
            "symbol",
            "stance",
            "summary",
            "invalidation",
            "notify",
            "received_at",
            "schema_version",
            "created_at",
            "content_sha256",
        }
        or r["format"] != REVIEW_FORMAT
    ):
        raise ValueError("Invalid stock review schema")
    identifier(r["review_id"], "str")
    if (
        any(r[k] != alert[k] for k in ("alert_id", "session_date", "symbol"))
        or r["alert_sha256"] != alert["content_sha256"]
    ):
        raise ValueError("Review does not match frozen stock alert")
    if (
        r["stance"] not in ("watch", "avoid", "no_view")
        or type(r["notify"]) is not bool
    ):
        raise ValueError("Invalid stock assessment")
    for key, limit in [("summary", 2000), ("invalidation", 1000)]:
        if not isinstance(r[key], str) or not r[key].strip() or len(r[key]) > limit:
            raise ValueError("Invalid review text")
    received = parse_time(r["received_at"])
    if r["created_at"] != r["received_at"] or received < parse_time(
        alert["detected_at"]
    ):
        raise ValueError("Review predates alert")
    if r["notify"] and (
        received >= parse_time(alert["expires_at"]) or r["stance"] == "no_view"
    ):
        raise ValueError("Expired/no-view review cannot notify")
    if alert["kind"] == "diagnostic" and (
        alert["diagnostic_code"] not in r["summary"]
        or "diagnostic" not in r["summary"].lower()
    ):
        raise ValueError("Diagnostic review must name its diagnostic code and purpose")
    return r


def write_once(directory, name, value):
    """Atomic immutable publication, preserving the existing default reader ACL."""
    from market_watch_common import canonical
    from app.engine.market_watch_snapshot import _read_bounded

    if Path(name).name != name:
        raise ValueError("Require a plain publication filename")
    body = canonical(value)
    destination = Path(directory) / name
    fd, temporary = tempfile.mkstemp(prefix=".stock-publish-", dir=directory)
    try:
        with os.fdopen(fd, "wb") as handle:
            os.fchmod(handle.fileno(), 0o640)
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, destination, follow_symlinks=False)
        except FileExistsError:
            if (
                _read_bounded(destination.absolute(), 1024 * 1024).encode("utf-8")
                != body
            ):
                raise ValueError("Stock publication conflicts")
        dirfd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(dirfd)
        finally:
            os.close(dirfd)
    finally:
        Path(temporary).unlink(missing_ok=True)
