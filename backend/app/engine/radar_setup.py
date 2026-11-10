"""Radar setup cards (``docs/radar.md``): a setup-kind Radar event as a trade idea, frozen the minute it is first seen.

For a ``dip_turn`` or ``gap_reversal`` event the phone ping shows a card instead of the bare fact: where the idea is
wrong (the invalidation level), one liquid option contract with its spread, and the owner's own record on that kind
of trade. Deterministic, no model call. Advice only: the wording describes, never instructs, and nothing here places,
changes or suggests an order.

Built once per event on the recorder's thread: sync, at most two option reads (expirations, then one chain) through
the shared Tradier options budget without waiting, no retries or sleeps. ``RADAR_SETUP_CARDS=true`` switches cards on
(off by default); the caller checks ``enabled()``.
"""
from __future__ import annotations

from datetime import date, datetime, time as dtime, timezone
import json
import logging
import os

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.engine import scanner_rules
from app.engine.chart_math import ET
from app.models import RadarSetup

log = logging.getLogger(__name__)

SETUP_KINDS = ("dip_turn", "gap_reversal")
MIN_OWNER_TRADES = 8
MIN_PAPER_TRADES = 5
# The owner's first hour, by the trade's opening time (naive New York wall time). The stored entry time buckets do
# not fit: "open" is only 09:30-10:00 and "mid" runs to 15:00.
FIRST_HOUR = (dtime(9, 30), dtime(10, 30))
# Each option read's HTTP timeout: the card is built on the recorder's minute pass, so two slow reads (instead of the
# chain reader's 20-second default) can never hold the pass for long; a timeout just means no contract on the card.
READ_TIMEOUT_SECONDS = 5
MINUS = "−"


def is_setup(event: dict) -> bool:
    return event.get("kind") in SETUP_KINDS


def enabled() -> bool:
    return os.environ.get("RADAR_SETUP_CARDS", "").strip().lower() == "true"


# ------------------------------------------------------------------ levels


def _symbol(event: dict) -> str | None:
    symbols = event.get("symbols") or []
    return symbols[0] if symbols else None


def levels(event: dict) -> dict | None:
    """Entry (the symbol's last at the first sighting) and invalidation (the session extreme the setup is built on).

    None unless the invalidation is strictly on the losing side of the entry: below for up, above for down."""
    symbol, direction = _symbol(event), event.get("direction")
    if symbol is None or direction not in ("up", "down"):
        return None
    rows = [r for r in event.get("evidence") or [] if r.get("symbol") == symbol and isinstance(r.get("last"), (int, float))]
    if not rows:
        return None
    entry = float(max(rows, key=lambda r: r.get("pass_id") or 0)["last"])
    extreme = (event.get("measures") or {}).get("extreme_price")
    if isinstance(extreme, (int, float)):
        invalidation = float(extreme)
    else:
        lasts = [float(r["last"]) for r in rows]
        invalidation = min(lasts) if direction == "up" else max(lasts)
    if entry <= 0 or (direction == "up" and not invalidation < entry) or (direction == "down" and not invalidation > entry):
        return None
    return {"entry": entry, "invalidation": invalidation, "risk_pct": round(abs(entry - invalidation) / entry * 100, 3)}


# ------------------------------------------------------------------ the contract


def pick_contract(symbol: str, direction: str, today: date, *, options=None) -> dict | None:
    """One liquid contract, a call for up and a put for down, by the setup scanner's limits; None when none qualifies.

    Two reads at most (the expiration list, then one chain) on the shared options budget, never waiting for a slot.
    Never raises."""
    try:
        if options is None:
            from app.engine.options_chain import options_chain as options
        expiration = scanner_rules.pick_expiration(options.expirations(symbol, timeout=READ_TIMEOUT_SECONDS), today)
        if expiration is None:
            log.info("Radar setup %s: no expiration today or 3-7 days out", symbol)
            return None
        chosen = scanner_rules.choose_contract(options.chain(symbol, expiration, timeout=READ_TIMEOUT_SECONDS).contracts,
                                               "long" if direction == "up" else "short")
        if chosen is None:
            log.info("Radar setup %s: no contract met the delta and liquidity limits", symbol)
            return None
        mid = (chosen["bid"] + chosen["ask"]) / 2
        return {**chosen, "mid": round(mid, 4), "spread_pct": round((chosen["ask"] - chosen["bid"]) / mid * 100, 2)}
    except Exception:
        log.exception("Radar setup contract pick failed for %s", symbol)
        return None


# ------------------------------------------------------------------ records


def _dollars(value: float) -> str:
    sign = "+" if value >= 0 else MINUS
    value = abs(value)
    if value >= 1000:
        return f"{sign}${value / 1000:.1f}k"
    return f"{sign}${value:,.0f}"


def _tally(pnl: list[float]) -> str:
    return f"{sum(1 for p in pnl if p > 0)} of {len(pnl)} green, {_dollars(sum(pnl))}"


def _first_hour(opened_at: str) -> bool:
    try:
        at = datetime.fromisoformat(opened_at).time()
    except (TypeError, ValueError):
        return False
    return FIRST_HOUR[0] <= at < FIRST_HOUR[1]


def owner_record(db: Session, direction: str) -> str | None:
    """The owner's closed calls (up) or puts (down): first-hour entries when there are enough, else all of them."""
    try:
        from app.engine.pretrade_check import build_feature_rows
        side = "call" if direction == "up" else "put"
        rows = [r for r in build_feature_rows(db) if r["side"] == side and r["realized_pnl"] is not None]
        first = [r["realized_pnl"] for r in rows if _first_hour(r["opened_at"])]
        if len(first) >= MIN_OWNER_TRADES:
            return f"Your first-hour {side}s: {_tally(first)}"
        if len(rows) >= MIN_OWNER_TRADES:
            return f"Your {side}s: {_tally([r['realized_pnl'] for r in rows])}"
        return None
    except Exception:
        log.exception("Radar setup owner record failed")
        db.rollback()
        return None


def paper_record(db: Session, kind: str, direction: str) -> str | None:
    """The closed paper results of earlier cards of this kind and direction, once there are enough."""
    try:
        pnl = db.exec(select(RadarSetup.paper_pnl).where(
            RadarSetup.kind == kind, RadarSetup.direction == direction, RadarSetup.paper_state == "closed",
            RadarSetup.paper_pnl.is_not(None))).all()
        if len(pnl) < MIN_PAPER_TRADES:
            return None
        return f"Paper record for this setup: {_tally([float(p) for p in pnl])}"
    except Exception:
        log.exception("Radar setup paper record failed")
        db.rollback()
        return None


# ------------------------------------------------------------------ the card


def _title(event: dict, symbol: str) -> str:
    if event.get("kind") == "gap_reversal":
        if event.get("direction") == "up":
            return f"Radar setup: {symbol} reversing up after a gap down"
        return f"Radar setup: {symbol} reversing down after a gap up"
    return f"Radar setup: {symbol} {'dip turning up' if event.get('direction') == 'up' else 'turning down'}"


def _signed(value: float, places: int = 1) -> str:
    return f"{'+' if value >= 0 else MINUS}{abs(value):.{places}f}"


def _strike(value: float) -> str:
    return f"{value:g}"


def _contract_line(symbol: str, c: dict) -> str:
    expiry = date.fromisoformat(c["expiration"])
    letter = "C" if c["option_type"] == "call" else "P"
    line = (f"Candidate: {symbol} {expiry.strftime('%b')} {expiry.day} {_strike(c['strike'])}{letter} · "
            f"{c['bid']:.2f} × {c['ask']:.2f} ({c['spread_pct']:.1f}% wide)")
    if c.get("delta") is not None:
        line += f" · Δ{_signed(c['delta'], 2).lstrip('+')}"
    return line


def _clock(iso: str | None) -> str | None:
    try:
        at = datetime.fromisoformat(str(iso).replace("Z", "+00:00")).astimezone(ET)
    except (TypeError, ValueError):
        return None
    return f"{(at.hour - 1) % 12 + 1}:{at.minute:02d} {'AM' if at.hour < 12 else 'PM'} ET"


def card_text(event: dict, setup: RadarSetup, paper_line: str | None = None) -> tuple[str, str]:
    """(title, body) for the phone. Describes the setup; never tells the owner to trade it."""
    symbol = setup.symbol
    move = (setup.invalidation - setup.entry) / setup.entry * 100
    side = "below" if setup.direction == "up" else "above"
    lines = [f"In near {setup.entry:.2f} · out {side} {setup.invalidation:.2f} ({_signed(move)}%)"]
    contract = json.loads(setup.contract_json) if setup.contract_json else None
    lines.append(_contract_line(symbol, contract) if contract else "No liquid contract found.")
    if setup.record_text:
        lines.append(setup.record_text)
    if paper_line:
        lines.append(paper_line)
    seen = _clock(event.get("first_seen_at"))
    lines.append(f"{event.get('summary', '')}{f' · {seen}' if seen else ''}")
    return _title(event, symbol), "\n".join(lines)


# ------------------------------------------------------------------ freeze


def _existing(db: Session, event_id: str) -> RadarSetup | None:
    return db.exec(select(RadarSetup).where(RadarSetup.event_id == event_id)).first()


_READ = object()  # build's default: read the owner's record for this card


def build(db: Session, event: dict, *, now: datetime, options=None, record: str | None | object = _READ) -> RadarSetup | None:
    """The event's card row, written once: an existing row comes back unchanged. None when the levels do not hold.

    ``record`` is the owner's record line when the caller already read it (``owner_record``, once a pass per
    direction); left out, it is read here."""
    event_id = event["event_id"]
    found = _existing(db, event_id)
    if found is not None:
        return found
    lv = levels(event)
    if lv is None:
        return None
    symbol, direction = _symbol(event), event["direction"]
    aware = now if now.tzinfo else now.replace(tzinfo=timezone.utc)  # naive means UTC
    utc, today = aware.astimezone(timezone.utc).replace(tzinfo=None), aware.astimezone(ET).date()
    contract = pick_contract(symbol, direction, today, options=options)
    row = RadarSetup(
        event_id=event_id, session_date=event.get("session_date") or today.isoformat(),
        rule_version=event.get("rule_version", ""), kind=event["kind"], symbol=symbol, direction=direction,
        entry=lv["entry"], invalidation=lv["invalidation"],
        contract_json=json.dumps(contract, sort_keys=True) if contract else None,
        record_text=owner_record(db, direction) if record is _READ else record, created_at=utc,
        paper_state="pending" if contract else "none")
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return _existing(db, event_id)
    db.refresh(row)
    return row
