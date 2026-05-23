"""
Webull OpenAPI integration — config, client wrapper, and event normalization.

Scope (Phase 1, read/listen/import only):
  - Read env-driven credentials (never logged).
  - Thin HTTP client for health + accounts + (best-effort) orders.
  - `ingest_event(...)` normalizes a single Webull TRADE event into:
      1. a WebullRawEvent row (saved first, idempotent on event_id),
      2. a Fill row (only when scene_type is FILLED or FINAL_FILLED).

This module does NOT touch existing Gmail/Robinhood ingestion. Live trading
endpoints are intentionally absent.

Webull event shape (per user-supplied sample):
  {
    "id": "event_<uuid>",
    "event_type": "TRADE",
    "timestamp": "...Z",
    "payload": {
      "account_id":        "<opaque>",
      "client_order_id":   "<uuid>",
      "instrument_id":     "<int as string>",
      "order_status":      "PARTIAL_FILLED" | "FILLED" | ...,
      "symbol":            "AAPL",
      "qty":               "10.00",        # order qty
      "filled_price":      "180.00",       # per-share (stocks) / per-share for options too
      "filled_qty":        "1.00",         # THIS leg only — sum across legs = total filled
      "filled_time":       "...Z",
      "side":              "BUY" | "SELL",
      "category":          "US_STOCK" | "US_OPTION" | ...,
      "order_type":        "LIMIT" | ...,
      "scene_type":        "FILLED" | "FINAL_FILLED" | ...,
      "biz_type":          "TRADE"
    }
  }

Idempotency: the envelope `id` is the unique key in webull_raw_event AND the
suffix for Fill.raw_email_id (`webull:{event_id}`). Duplicate deliveries are
detected at both layers.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

import httpx
from dotenv import load_dotenv
from sqlmodel import Session, select

from app.models import Account, Fill, WebullRawEvent

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

log = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")

WEBULL_APP_KEY = os.environ.get("WEBULL_APP_KEY", "")
WEBULL_APP_SECRET = os.environ.get("WEBULL_APP_SECRET", "")
WEBULL_API_BASE = os.environ.get("WEBULL_API_BASE", "https://api.webull.com").rstrip("/")
WEBULL_REGION = os.environ.get("WEBULL_REGION", "us")
WEBULL_ALLOW_TEST_INGEST = os.environ.get("WEBULL_ALLOW_TEST_INGEST", "true").lower() in ("1", "true", "yes")

_FILL_SCENE_TYPES = {"FILLED", "FINAL_FILLED"}
_STOCK_CATEGORIES = {"US_STOCK", "STOCK"}
_OPTION_CATEGORIES = {"US_OPTION", "OPTION"}


def webull_configured() -> bool:
    return bool(WEBULL_APP_KEY and WEBULL_APP_SECRET)


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class IngestResult:
    result: str                     # "normalized" | "duplicate" | "non_trade" | "non_execution" | "error" | "rejected"
    event_id: Optional[str] = None
    fill_id: Optional[uuid.UUID] = None
    account_id: Optional[uuid.UUID] = None
    reason: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "result": self.result,
            "event_id": self.event_id,
            "fill_id": str(self.fill_id) if self.fill_id else None,
            "account_id": str(self.account_id) if self.account_id else None,
            "reason": self.reason,
            "error": self.error,
        }


# ---------------------------------------------------------------------------
# HTTP client (thin)
# ---------------------------------------------------------------------------

class WebullClientError(RuntimeError):
    """Raised on Webull API errors. Sanitized — never includes secrets."""


def _client() -> httpx.Client:
    if not webull_configured():
        raise WebullClientError("Webull credentials are not configured")
    headers = {
        "x-app-key": WEBULL_APP_KEY,
        # NOTE: Webull's real auth is signature-based; this header layout is a
        # placeholder. The signing implementation lives behind a TODO until we
        # wire the official SDK or hand-rolled signer.
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    return httpx.Client(base_url=WEBULL_API_BASE, headers=headers, timeout=15.0)


def health_check() -> dict[str, Any]:
    """
    Best-effort health check. Returns whether keys are configured and whether
    a trivial probe to the API base succeeds. Never returns secret material.
    """
    info: dict[str, Any] = {
        "configured": webull_configured(),
        "base_url": WEBULL_API_BASE,
        "region": WEBULL_REGION,
        "auth_ok": None,
        "error": None,
    }
    if not webull_configured():
        info["error"] = "WEBULL_APP_KEY / WEBULL_APP_SECRET not set"
        return info
    try:
        with _client() as client:
            # Webull-specific probe endpoint to be confirmed; using a benign GET
            # against the base. A 401/403 still proves we reached the API.
            resp = client.get("/")
            info["auth_ok"] = resp.status_code < 500
            info["status_code"] = resp.status_code
    except httpx.HTTPError as exc:
        info["auth_ok"] = False
        info["error"] = _sanitize_error(exc)
    return info


def list_accounts_remote() -> list[dict[str, Any]]:
    """
    Fetch the list of Webull accounts visible to the API key.

    TODO: replace the path below with the official Webull endpoint once the
    SDK/spec is wired. Until then this raises WebullClientError on a non-2xx.
    """
    raise WebullClientError("Webull accounts endpoint not yet wired — see TODO in engine/webull.py")


def list_recent_orders_remote(account_id: str, limit: int = 50) -> list[dict[str, Any]]:
    """TODO: implement once order-history endpoint is confirmed."""
    raise WebullClientError("Webull order history endpoint not yet wired — see TODO in engine/webull.py")


def get_order_detail_remote(account_id: str, order_id: str) -> dict[str, Any]:
    """TODO: implement once order-detail endpoint is confirmed."""
    raise WebullClientError("Webull order detail endpoint not yet wired — see TODO in engine/webull.py")


def _sanitize_error(exc: Exception) -> str:
    """Strip anything that might contain secrets from the exception message."""
    msg = str(exc)
    if WEBULL_APP_KEY and WEBULL_APP_KEY in msg:
        msg = msg.replace(WEBULL_APP_KEY, "<redacted>")
    if WEBULL_APP_SECRET and WEBULL_APP_SECRET in msg:
        msg = msg.replace(WEBULL_APP_SECRET, "<redacted>")
    return msg


# ---------------------------------------------------------------------------
# Account resolution
# ---------------------------------------------------------------------------

def _synthetic_last4(broker_account_id: str) -> str:
    """
    Webull account ids are opaque (~26 chars). The existing Account.last4
    unique constraint expects a short identifier; we synthesize one from the
    tail of the broker id. Collisions are extraordinarily unlikely in a
    single-user journal; if we ever see one, fall back to a UUID suffix.
    """
    if not broker_account_id:
        return uuid.uuid4().hex[-4:].upper()
    return broker_account_id[-4:].upper()


def resolve_webull_account(session: Session, broker_account_id: str) -> Account:
    """Look up or create the Account row keyed by (broker='webull', broker_account_id)."""
    account = session.exec(
        select(Account)
        .where(Account.broker == "webull")
        .where(Account.broker_account_id == broker_account_id)
    ).first()
    if account:
        return account

    last4 = _synthetic_last4(broker_account_id)
    # If a Robinhood account already owns this synthetic last4, append a
    # disambiguating char until we find a free slot.
    while session.exec(select(Account).where(Account.last4 == last4)).first():
        last4 = (last4 + uuid.uuid4().hex[:1].upper())[-4:]

    account = Account(
        id=uuid.uuid4(),
        name=f"Webull ({broker_account_id[-6:]})",
        type="webull_pending",       # mapped to roth_ira / individual later
        last4=last4,
        broker="webull",
        broker_account_id=broker_account_id,
    )
    session.add(account)
    session.flush()
    log.info("Created Webull Account row id=%s last4=%s", account.id, account.last4)
    return account


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------

def ingest_event(event: dict[str, Any], session: Session) -> IngestResult:
    """
    Save the raw event, then conditionally normalize into a Fill.

    Idempotent: a repeated event_id returns result='duplicate' without
    touching the Fill table.
    """
    event_id = event.get("id") if isinstance(event, dict) else None
    if not event_id or not isinstance(event_id, str):
        return IngestResult(result="rejected", reason="missing_event_id",
                            error="event.id is required and must be a string")

    # --- 1. Raw save (idempotent) ---
    existing_raw = session.get(WebullRawEvent, event_id)
    if existing_raw is not None:
        return IngestResult(
            result="duplicate",
            event_id=event_id,
            fill_id=existing_raw.fill_id,
            reason=existing_raw.normalize_reason,
        )

    payload = event.get("payload") or {}
    if not isinstance(payload, dict):
        payload = {}

    raw = WebullRawEvent(
        event_id=event_id,
        event_type=str(event.get("event_type") or "UNKNOWN"),
        scene_type=_opt_str(payload.get("scene_type")),
        order_status=_opt_str(payload.get("order_status")),
        account_id=_opt_str(payload.get("account_id")),
        client_order_id=_opt_str(payload.get("client_order_id")),
        symbol=_opt_str(payload.get("symbol")),
        category=_opt_str(payload.get("category")),
        filled_time=_parse_utc(payload.get("filled_time")),
        payload_json=json.dumps(event, separators=(",", ":")),
        normalized=False,
    )
    session.add(raw)
    session.flush()

    # --- 2. Routing ---
    if raw.event_type != "TRADE":
        raw.normalized = True
        raw.normalize_reason = "non_trade"
        session.add(raw)
        session.commit()
        return IngestResult(result="non_trade", event_id=event_id, reason="event_type!=TRADE")

    scene = (raw.scene_type or "").upper()
    if scene not in _FILL_SCENE_TYPES:
        raw.normalized = True
        raw.normalize_reason = "non_execution"
        session.add(raw)
        session.commit()
        return IngestResult(result="non_execution", event_id=event_id, reason=f"scene_type={scene or 'missing'}")

    # --- 3. Normalize -> Fill ---
    try:
        fill = _build_fill_from_payload(session, event_id, payload)
        session.add(fill)
        session.flush()
        raw.fill_id = fill.id
        raw.normalized = True
        raw.normalize_reason = "fill"
        session.add(raw)
        session.commit()
        return IngestResult(
            result="normalized",
            event_id=event_id,
            fill_id=fill.id,
            account_id=fill.account_id,
            reason="fill",
        )
    except _NormalizationError as exc:
        session.rollback()
        # Re-attach a fresh raw row reflecting the error (the rollback dropped it).
        raw_err = WebullRawEvent(
            event_id=event_id,
            event_type=str(event.get("event_type") or "UNKNOWN"),
            scene_type=_opt_str(payload.get("scene_type")),
            order_status=_opt_str(payload.get("order_status")),
            account_id=_opt_str(payload.get("account_id")),
            client_order_id=_opt_str(payload.get("client_order_id")),
            symbol=_opt_str(payload.get("symbol")),
            category=_opt_str(payload.get("category")),
            filled_time=_parse_utc(payload.get("filled_time")),
            payload_json=json.dumps(event, separators=(",", ":")),
            normalized=False,
            normalize_reason="error",
            normalize_error=str(exc),
        )
        session.add(raw_err)
        session.commit()
        log.warning("Webull ingest failed for event %s: %s", event_id, exc)
        return IngestResult(result="error", event_id=event_id, reason="normalization_failed", error=str(exc))


# ---------------------------------------------------------------------------
# Normalization helpers
# ---------------------------------------------------------------------------

class _NormalizationError(RuntimeError):
    pass


def _build_fill_from_payload(session: Session, event_id: str, payload: dict[str, Any]) -> Fill:
    broker_account_id = _opt_str(payload.get("account_id"))
    if not broker_account_id:
        raise _NormalizationError("payload.account_id missing")

    symbol = _opt_str(payload.get("symbol"))
    if not symbol:
        raise _NormalizationError("payload.symbol missing")

    filled_time_utc = _parse_utc(payload.get("filled_time"))
    if filled_time_utc is None:
        raise _NormalizationError("payload.filled_time missing or unparseable")
    executed_at_et = filled_time_utc.astimezone(ET)

    filled_qty = _to_decimal(payload.get("filled_qty"), "filled_qty")
    filled_price = _to_decimal(payload.get("filled_price"), "filled_price")
    if filled_qty <= 0:
        raise _NormalizationError(f"filled_qty must be positive, got {filled_qty}")
    if filled_price < 0:
        raise _NormalizationError(f"filled_price must be non-negative, got {filled_price}")

    side_raw = (_opt_str(payload.get("side")) or "").upper()
    category = (_opt_str(payload.get("category")) or "").upper()

    account = resolve_webull_account(session, broker_account_id)

    if category in _STOCK_CATEGORIES:
        instrument_type = "stock"
        if side_raw == "BUY":
            side = "buy"
        elif side_raw == "SELL":
            side = "sell"
        else:
            raise _NormalizationError(f"unsupported stock side {side_raw!r}")
        price = filled_price
        option_type: Optional[str] = None
        strike: Optional[Decimal] = None
        expiration: Optional[date] = None
    elif category in _OPTION_CATEGORIES:
        instrument_type = "option"
        # PROVISIONAL: Webull executions don't expose positionEffect on the
        # event payload. BUY -> buy_to_open and SELL -> sell_to_close are
        # placeholders that are correct for the long-only happy path. A
        # future enrichment pass should resolve via order detail.
        if side_raw == "BUY":
            side = "buy_to_open"
        elif side_raw == "SELL":
            side = "sell_to_close"
        else:
            raise _NormalizationError(f"unsupported option side {side_raw!r}")
        # Options: per-contract premium = per-share price * 100
        price = filled_price * Decimal("100")
        # TODO: resolve option_type / strike / expiration / OCC symbol from
        # order detail. Until then these stay None — Fill saves safely, but
        # the FIFO reconstructor will skip option fills missing metadata.
        option_type = None
        strike = None
        expiration = None
        log.warning(
            "Webull option fill saved with unresolved metadata "
            "(event=%s symbol=%s instrument_id=%s) — option_type/strike/expiration are None",
            event_id, symbol, payload.get("instrument_id"),
        )
    else:
        raise _NormalizationError(f"unsupported category {category!r}")

    raw_email_id = f"webull:{event_id}"

    # Final dedupe guard: same raw_email_id may have leaked in from elsewhere.
    if session.exec(select(Fill).where(Fill.raw_email_id == raw_email_id)).first():
        raise _NormalizationError(f"raw_email_id collision: {raw_email_id}")

    return Fill(
        id=uuid.uuid4(),
        account_id=account.id,
        ticker=symbol.upper(),
        instrument_type=instrument_type,
        side=side,
        contracts=float(filled_qty),
        price=float(price),
        executed_at=executed_at_et,
        raw_email_id=raw_email_id,
        option_type=option_type,
        strike=float(strike) if strike is not None else None,
        expiration=expiration,
    )


def _opt_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def _parse_utc(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    # Trim sub-microsecond nanos that fromisoformat can't parse.
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    # Truncate over-precise fractional seconds (>6 digits) — Webull samples
    # show 9-digit precision (".200962333"), which fromisoformat rejects.
    if "." in text:
        head, _, tail = text.partition(".")
        # tail looks like "200962333+00:00"
        if "+" in tail or "-" in tail:
            # find the tz sign after the fractional part
            for sign in ("+", "-"):
                idx = tail.find(sign)
                if idx >= 0:
                    frac, tz = tail[:idx], tail[idx:]
                    text = f"{head}.{frac[:6]}{tz}"
                    break
        else:
            text = f"{head}.{tail[:6]}"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _to_decimal(value: Any, field_name: str) -> Decimal:
    if value is None:
        raise _NormalizationError(f"{field_name} is required")
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise _NormalizationError(f"{field_name} not a number: {value!r}") from exc
