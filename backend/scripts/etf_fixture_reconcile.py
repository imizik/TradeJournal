"""Offline accounting check for one pinned invented receipt; not a strategy runner.

No arbitrary file/market input, persistence, provider, broker or Factory imports.
The pure checker supports altered invented values for regression tests only.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
import hashlib
import json
from pathlib import Path

FIXTURE = Path(__file__).resolve().parents[2] / "research/notes/etf-trend-accounting-example-2026-10-25.json"
FIXTURE_SHA256 = "d1e6c3e632a2d320cefebf89192420c97b156e6d22fd0d25cc41c0067a866470"
SEQUENCE = (
    "initial", "invented_buy", "rejected_intent", "ex_dividend",
    "pay_dividend", "split", "invented_sell", "sale_settlement",
)
COMMON = {"id", "type", "cash", "shares", "mark", "receivable", "nav"}
EXTRA = (
    set(), {"intent_id", "quantity", "ask", "fee"},
    {"intent_id", "reason", "fill"}, {"per_share"}, set(), {"new_per_old"},
    {"intent_id", "signal", "quantity", "bid", "fee", "settled_cash", "unsettled_sale_proceeds"},
    {"settled_cash", "unsettled_sale_proceeds"},
)


def number(value: object) -> Decimal:
    """Reject binary floats, nonfinite numbers and unbounded fixture magnitudes."""
    if not isinstance(value, str) or len(value) > 32:
        raise ValueError("decimal fields must be short strings")
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("invalid decimal") from exc
    if not result.is_finite() or result < 0 or result > Decimal("1e12"):
        raise ValueError("nonfinite, negative or excessive decimal")
    if result.as_tuple().exponent < -8:
        raise ValueError("excessive precision")
    return result


def quantity(value: object) -> int:
    if type(value) is not int or not 0 <= value <= 10**9:
        raise ValueError("quantity must be a bounded whole number")
    return value


@dataclass(frozen=True)
class Snapshot:
    event_id: str
    cash: Decimal
    shares: int
    receivable: Decimal
    unsettled_sale_proceeds: Decimal
    settled_cash: Decimal
    nav: Decimal


def reconcile(document: dict) -> tuple[Snapshot, ...]:
    """Rebuild the eight-stage invented example; never trust its expected balances.

    Exact repeated event IDs/payloads are ignored. Changed payloads under an ID,
    extra economic events, unknown event types and incomplete receipts fail.
    Restart means replaying the complete receipt, not loading mutable state.
    """
    with localcontext() as context:
        context.prec = 40
        return _reconcile(document)


def _reconcile(document: dict) -> tuple[Snapshot, ...]:
    if (document.get("kind") != "invented_accounting_example_only"
            or type(document.get("version")) is not int or document["version"] != 1
            or document.get("market_data_used") is not False
            or document.get("fee_rounding") != "ROUND_HALF_UP_cents"):
        raise ValueError("only version 1 invented accounting receipts are supported")
    cash = number(document["capital"])
    budget = number(document["sleeve_budget"])
    rate = number(document["fee_rate"])
    if budget > cash or rate > 1:
        raise ValueError("invalid sleeve budget or fee rate")
    shares = 0
    receivable = unsettled = Decimal(0)
    seen: dict[str, str] = {}
    intents: set[str] = set()
    output: list[Snapshot] = []
    for event in document["events"]:
        event_id = event["id"]
        if not isinstance(event_id, str) or not event_id:
            raise ValueError("event ID required")
        encoded = json.dumps(event, sort_keys=True, allow_nan=False)
        if event_id in seen:
            if seen[event_id] != encoded:
                raise ValueError("conflicting duplicate event")
            continue
        stage = len(output)
        if stage >= len(SEQUENCE) or event["type"] != SEQUENCE[stage]:
            raise ValueError("unsupported or out-of-order fixture event")
        if set(event) != COMMON | EXTRA[stage]:
            raise ValueError("unsupported or missing event fields")
        if "intent_id" in event:
            intent = event["intent_id"]
            if not isinstance(intent, str) or not intent or intent in intents:
                raise ValueError("invalid or reused intent ID")
            intents.add(intent)
        mark = number(event["mark"])
        if mark <= 0:
            raise ValueError("missing or nonpositive raw mark")
        if stage in (1, 6):
            count = quantity(event["quantity"])
            price = number(event["ask" if stage == 1 else "bid"])
            if not count or not price:
                raise ValueError("positive quantity and price required")
            notional = count * price
            fee = (notional * rate).quantize(Decimal(".01"), rounding=ROUND_HALF_UP)
            if fee != number(event["fee"]):
                raise ValueError("fee mismatch")
            if stage == 1:
                if notional + fee > min(budget, cash - unsettled):
                    raise ValueError("insufficient sleeve budget or settled cash")
                cash -= notional + fee
                shares += count
            else:
                if count != shares or fee > notional:
                    raise ValueError("fixture sale must close the position without overdraft")
                unsettled = notional - fee
                cash += unsettled
                shares -= count
        elif stage == 2:
            if event["fill"] is not None or event["reason"] != "missing_eligible_quote":
                raise ValueError("missing quote must remain an unfilled rejection")
        elif stage == 3:
            receivable = shares * number(event["per_share"])
        elif stage == 4:
            cash += receivable
            receivable = Decimal(0)
        elif stage == 5:
            ratio = number(event["new_per_old"])
            new_shares = shares * ratio
            if not ratio or new_shares != new_shares.to_integral_value():
                raise ValueError("fractional split entitlement unsupported")
            shares = quantity(int(new_shares))
        elif stage == 7:
            unsettled = Decimal(0)
        nav = cash + shares * mark + receivable
        snapshot = Snapshot(event_id, cash, shares, receivable, unsettled, cash - unsettled, nav)
        for field in ("cash", "receivable", "nav", "settled_cash", "unsettled_sale_proceeds"):
            if field in event and number(event[field]) != getattr(snapshot, field):
                raise ValueError(f"{event_id}: {field} mismatch")
        if quantity(event["shares"]) != shares:
            raise ValueError(f"{event_id}: shares mismatch")
        seen[event_id] = encoded
        output.append(snapshot)
    if len(output) != len(SEQUENCE):
        raise ValueError("incomplete fixture receipt")
    return tuple(output)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()  # Deliberately no input-path or execution switches.
    raw = FIXTURE.read_bytes()
    if hashlib.sha256(raw).hexdigest() != FIXTURE_SHA256:
        raise ValueError("pinned invented fixture changed; review required")
    result = reconcile(json.loads(raw))
    print(json.dumps({"kind": "invented_accounting_check_only", "events": len(result),
                      "final": asdict(result[-1])}, default=str, sort_keys=True))


if __name__ == "__main__":
    main()
