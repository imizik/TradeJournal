"""Bounded, advisory-only price plans. No orders, fills, or S1 decisions."""

from datetime import timedelta
import json
import math
import os
from pathlib import Path
import tempfile

from market_watch_common import parse_time, verify
from stock_watch_common import ET, identifier

FORMAT = "conditional-plan-v1"
TERMINAL = {"invalidated", "expired", "cancelled", "unavailable"}
FRESH_SECONDS = 180
HEARTBEAT_SECONDS = 90
MAX_DAILY_PLANS = 24
REFUSAL_FORMAT = "conditional-plan-refusal-v1"
MAX_DAILY_REFUSALS = 24


def price(value):
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
        raise ValueError("Require a positive finite price")
    return value


def validate_plan(p):
    verify(p)
    if (
        set(p)
        != {
            "format",
            "plan_id",
            "actor",
            "session_date",
            "symbol",
            "direction",
            "trigger_price",
            "invalidation_price",
            "confirm_bars",
            "rationale",
            "source",
            "session_open_at",
            "session_close_at",
            "expires_at",
            "created_at",
            "schema_version",
            "content_sha256",
        }
        or p["format"] != FORMAT
    ):
        raise ValueError("Invalid conditional plan schema")
    identifier(p["plan_id"], "cpl")
    if not isinstance(p["actor"], str) or not p["actor"]:
        raise ValueError("Missing plan owner")
    import re

    if not isinstance(p["symbol"], str) or not re.fullmatch(
        r"[A-Z]{1,6}(\.[A-Z])?", p["symbol"]
    ):
        raise ValueError("Invalid plan symbol")
    trigger, invalidation = price(p["trigger_price"]), price(p["invalidation_price"])
    if p["direction"] not in ("long", "short") or (
        trigger <= invalidation if p["direction"] == "long" else trigger >= invalidation
    ):
        raise ValueError("Invalid directional plan levels")
    if type(p["confirm_bars"]) is not int or not 1 <= p["confirm_bars"] <= 3:
        raise ValueError("Require one to three consecutive completed minute closes")
    if (
        not isinstance(p["rationale"], str)
        or not 1 <= len(p["rationale"].strip()) <= 1000
    ):
        raise ValueError("Require a bounded plan rationale")
    opened, created, expires, closed = [
        parse_time(p[k])
        for k in ("session_open_at", "created_at", "expires_at", "session_close_at")
    ]
    if not opened <= created < expires <= closed or expires - created > timedelta(
        hours=4
    ):
        raise ValueError("Plan must expire within four hours and this regular session")
    if any(
        t.astimezone(ET).date().isoformat() != p["session_date"]
        for t in (opened, created, expires, closed)
    ):
        raise ValueError("Plan session mismatch")
    src = p["source"]
    if not isinstance(src, dict) or set(src) != {
        "kind",
        "id",
        "sha256",
        "observed_at",
        "price",
    }:
        raise ValueError("Invalid source reference")
    if src["kind"] not in ("check", "stock_alert") or not isinstance(src["id"], str):
        raise ValueError("Invalid source kind")
    if not isinstance(src["sha256"], str) or not re.fullmatch(
        r"[0-9a-f]{64}", src["sha256"]
    ):
        raise ValueError("Invalid source digest")
    price(src["price"])
    if (
        not 0
        <= (created - parse_time(src["observed_at"])).total_seconds()
        <= FRESH_SECONDS
    ):
        raise ValueError("Plan source is stale or future")
    return p


def validate_cancel(c, plan):
    verify(c)
    if set(c) != {
        "format",
        "plan_id",
        "plan_sha256",
        "actor",
        "session_date",
        "created_at",
        "schema_version",
        "content_sha256",
    }:
        raise ValueError("Invalid cancellation schema")
    if c["format"] != "conditional-plan-cancel-v1" or any(
        c[k] != plan[k] for k in ("plan_id", "actor", "session_date")
    ):
        raise ValueError("Cancellation owner/plan mismatch")
    if c["plan_sha256"] != plan["content_sha256"] or parse_time(
        c["created_at"]
    ) < parse_time(plan["created_at"]):
        raise ValueError("Cancellation does not match plan")
    return c


def validate_refusal(r):
    """A refused create: what Jo asked for and why; nothing was saved or watched."""
    import re

    verify(r)
    if set(r) != {
        "format",
        "refusal_id",
        "actor",
        "session_date",
        "symbol",
        "source_kind",
        "direction",
        "trigger_price",
        "invalidation_price",
        "confirm_bars",
        "expires_at",
        "reason",
        "reason_code",
        "created_at",
        "schema_version",
        "content_sha256",
    } or r["format"] != REFUSAL_FORMAT:
        raise ValueError("Invalid conditional-plan refusal schema")
    identifier(r["refusal_id"], "cpr")
    if not isinstance(r["actor"], str) or not r["actor"]:
        raise ValueError("Missing refusal owner")
    if r["symbol"] is not None and not (
        isinstance(r["symbol"], str) and re.fullmatch(r"[A-Z]{1,6}(\.[A-Z])?", r["symbol"])
    ):
        raise ValueError("Invalid refusal symbol")
    if (
        r["direction"] not in (None, "long", "short")
        or r["source_kind"] not in (None, "check", "stock_alert")
        or r["confirm_bars"] not in (None, 1, 2, 3)
        or r["reason_code"]
        not in ("ticker_not_selected", "monitor_off", "no_session", "daily_cap", "other")
        or not isinstance(r["reason"], str)
        or not 1 <= len(r["reason"]) <= 300
    ):
        raise ValueError("Invalid refusal content")
    for k in ("trigger_price", "invalidation_price"):
        if r[k] is not None:
            price(r[k])
    if r["expires_at"] is not None:
        parse_time(r["expires_at"])
    if parse_time(r["created_at"]).astimezone(ET).date().isoformat() != r["session_date"]:
        raise ValueError("Refusal session mismatch")
    return r


def read_json(path, limit=128 * 1024):
    from app.engine.market_watch_snapshot import _read_bounded

    return json.loads(_read_bounded(Path(path).absolute(), limit))


def publish(directory, name, value):
    """Atomic replace of derived status only; immutable evidence lives in the ledger."""
    if Path(name).name != name:
        raise ValueError("Require plain publication filename")
    fd, temporary = tempfile.mkstemp(prefix=".conditional-plan-", dir=directory)
    try:
        with os.fdopen(fd, "w") as handle:
            os.fchmod(handle.fileno(), 0o640)
            json.dump(value, handle, sort_keys=True, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, Path(directory) / name)
        dirfd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(dirfd)
        finally:
            os.close(dirfd)
    finally:
        Path(temporary).unlink(missing_ok=True)


def readiness(directory, now):
    r = read_json(Path(directory) / "conditional-plan-readiness.json")
    verify(r)
    if (
        r.get("format") != "conditional-plan-readiness-v1"
        or r.get("enabled") is not True
    ):
        raise ValueError("Conditional-plan monitor is not enabled")
    if (
        not 0
        <= (now - parse_time(r["created_at"])).total_seconds()
        <= HEARTBEAT_SECONDS
    ):
        raise ValueError("Conditional-plan monitor heartbeat is stale")
    if (
        not r["session_open_at"]
        or not r["session_close_at"]
        or not parse_time(r["session_open_at"])
        <= now
        < parse_time(r["session_close_at"])
    ):
        raise ValueError("No verified open regular session")
    return r


def status(directory, plan, now):
    """Never label a queued plan, stopped monitor, or stale status as actively watched."""
    result = {
        "plan": plan,
        "state": "pending_activation",
        "monitoring": False,
        "events": [],
        "delivery": [],
    }
    try:
        value = read_json(
            Path(directory) / f"conditional-plan-status-{plan['plan_id']}.json"
        )
        verify(value)
        if (
            value.get("format") != "conditional-plan-status-v1"
            or value.get("plan_sha256") != plan["content_sha256"]
            or value.get("plan_id") != plan["plan_id"]
        ):
            raise ValueError("Plan status mismatch")
        result.update(
            {
                k: value[k]
                for k in ("state", "events", "delivery", "last_bar_end", "checked_at")
            }
        )
        result["monitoring"] = (
            value["enabled"]
            and value["state"] in ("watching", "triggered")
            and 0
            <= (now - parse_time(value["checked_at"])).total_seconds()
            <= HEARTBEAT_SECONDS
        )
    except FileNotFoundError:
        pass
    if now >= parse_time(plan["expires_at"]):
        result["monitoring"] = False
    return result
