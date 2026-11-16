"""Paper it from the phone: one tap under a Telegram ping that carries a tradable idea places a paper market order.

Which pings get the button (``PAPER_LABEL``, callback ``pp:<kind>:<key>``): a Radar setup ping whose card names a
candidate contract (``pp:r:<RadarSetup id>``, beside Plan it), and a copilot trade plan card the bot sends after an
answer whose contract words name one call or put, or a long share plan (``pp:p:<card client id>``, beside Confirm). The
idea is read as the desk's Paper it reads it (``RadarPaperIt``, ``TradePlanCard``'s ``PaperIt`` and ``planOrder``): the
same contract, size, stop, target and note, recorded as Radar's or the copilot's idea with its id, so the paper
scorecard's split by source counts it. No button when the idea has not enough to place an order, the ticker is set to not
followed, or Copilot Lab (which owns the paper book) is off.

A tap runs ``tap``: the order goes through ``paper_book.open_order``, the desk's own path, never a second one: a fill
only in the regular session at a fresh ask, refused with the reason otherwise (stale quote with its time, market closed,
not enough paper buying power), and the desk's simulated-evidence and lab-off refusals. The order key is the ping's own
(``tg-<kind>-<key>``, unique in the paper book), so a second tap, or a tap read again after a restart, never places a
second order: it answers with the fill already recorded. His rules (#827) are checked at the fill as on the desk; the
tick-box ones are kept as not answered (phone). His paper-book weekly goals are checked against the fill too. A broken
rule or goal never blocks the order; the reply names them on one short line.

The reply is ``(text, chosen)``: the chat line ("PAPER · bought 1 NVDA 11/21 150C at 3.45 (ask, 10:42 ET) · …") and
``PAPERED`` once filled (the keyboard then shows it), or None after a refusal so a later tap can try again.

Paper only: never Robinhood, never an order tool, never fills, trades or accounts. Database reads and the paper book's
one quote read through the chart feed (its single-flight and minute budget).
"""
from __future__ import annotations

import json
import logging
import re
import time
import uuid
from datetime import date, datetime

from sqlmodel import Session, select

from app.engine import paper_book
from app.engine.chart_math import ET

log = logging.getLogger(__name__)

PAPER_LABEL = "📝 Paper it"
VERB = "pp"
RADAR, PLAN = "r", "p"
PAPERED = "Papered"
RADAR_CONTRACTS = 1  # the desk's Paper it on a Radar setup card: 1 contract
PLAN_CONTRACTS, PLAN_SHARES = 1, 10  # the desk's Paper it on a plan card: 1 contract, or 10 shares
NOT_REAL = "not real money"
_HEX = re.compile(r"^[0-9a-f]{32}$")
_MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")


def button(kind: str, key: str) -> tuple[str, str]:
    return PAPER_LABEL, f"{VERB}:{kind}:{key}"


def _lab_on() -> bool:
    from app.ai import copilot
    try:
        return bool(copilot.settings().enabled)
    except Exception:  # noqa: BLE001 -- unreadable settings: no button, the ping still goes
        return False


def _hidden(db: Session, symbol: str) -> bool:
    from app.engine import day_journal
    return symbol.upper() in day_journal.quiet(db)


# --- the idea, as the desk's Paper it reads it -------------------------------------------------------------------------

def radar_idea(setup) -> dict | str:
    """A Radar setup card's paper order (``RadarPaperIt``): its candidate contract, 1 contract, the invalidation as the
    stop, no target; or why there is none."""
    contract = paper_book.idea_contract(json.loads(setup.contract_json) if setup.contract_json else None)
    if contract is None:
        return "No liquid contract on this card to paper."
    from app.engine import radar_setup
    from app.engine.radar_setup_plan import setup_words
    side = "below" if setup.direction == "up" else "above"
    move = (setup.invalidation - setup.entry) / setup.entry * 100
    levels = f"In near {setup.entry:.2f} · out {side} {setup.invalidation:.2f} ({radar_setup._signed(move)}%)"
    return {"order": {"instrument": "option", "symbol": setup.symbol, **contract}, "quantity": RADAR_CONTRACTS,
            "stop": setup.invalidation, "target": None, "note": f"Radar: {setup.symbol} {setup_words(setup)}. {levels}",
            "source": "radar", "idea_id": str(setup.id), "size": "1 contract, the desk's size for a Radar idea"}


def _expiry_in(text: str, today: date) -> tuple[str, str] | None:
    """The expiry a contract's words name, with the words it was read from (``expiryIn`` in ``frontend/lib/paperBook.ts``):
    "2026-11-20", "11/20/26", "11/20", "Nov 20 '26", "Nov 20, 2026", "Nov 20"; a date with no year is its next one."""
    def fill(m: int, d: int, y: int | None) -> str | None:
        year = (today.year + 1 if (m, d) < (today.month, today.day) else today.year) if y is None else 2000 + y if y < 100 else y
        try:
            return date(year, m, d).isoformat()
        except ValueError:
            return None

    def found(hit: re.Match, iso: str | None) -> tuple[str, str] | None:
        return (iso, hit.group(0)) if iso else None
    if hit := re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", text):
        return found(hit, fill(int(hit[2]), int(hit[3]), int(hit[1])))
    if hit := re.search(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2}|\d{4}))?\b", text):
        return found(hit, fill(int(hit[1]), int(hit[2]), int(hit[3]) if hit[3] else None))
    if hit := re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?\b"
                        r"(?:,?\s*(?:['’](\d{2})|(20\d{2}))\b)?", text, re.I):
        year = hit[3] or hit[4]
        return found(hit, fill(_MONTHS.index(hit[1].lower()) + 1, int(hit[2]), int(year) if year else None))
    return None


def plan_order(symbol: str, instrument: str, direction: str, contract: str, today: date) -> dict | str:
    """A plan's contract words as a paper order (``planOrder`` in ``frontend/lib/paperBook.ts``, strict on purpose): one
    call or put by strike and expiry, the plan's instrument deciding which; long shares. Otherwise why not."""
    if instrument == "stock":
        return {"instrument": "stock", "symbol": symbol} if direction == "long" else "Paper buys shares; it cannot short them."
    words = (contract or "").strip()
    if not words:
        return "No contract named: pick one from the Contract list to paper it."
    unclear = f"\"{words}\" does not name one strike and an expiry plainly: pick a contract from the Contract list to paper it."
    expiry = _expiry_in(words, today)
    if expiry is None:
        return unclear
    rest = words.replace(expiry[1], " ", 1)
    if _expiry_in(rest, today):
        return unclear
    if re.search(r"\d\s*[cp]?\s*/\s*\$?\d", rest, re.I):
        return f"\"{words}\" names a spread: paper it from the Ticket or the Chain."
    strikes = list(re.finditer(r"(?<![\w.$])\$?(\d+(?:\.\d+)?)\s*(c|p|call|put)\b", rest, re.I))
    if len(strikes) != 1:
        return unclear
    hit = strikes[0]
    if re.search(r"\d", rest.replace(hit.group(0), " ", 1)):
        return unclear
    kind = "call" if hit[2].lower().startswith("c") else "put"
    want = "call" if instrument == "calls" else "put"
    if kind != want:
        return f"{words} is a {kind}, but this plan buys {instrument}."
    return {"instrument": "option", "symbol": symbol, "option_type": kind, "expiry": expiry[0], "strike": float(hit[1])}


def _level(text) -> float | None:
    try:
        n = float(str(text).strip())
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def plan_idea(card: dict, today: date) -> dict | str:
    """A copilot plan card's paper order (``TradePlanCard``'s ``PaperIt``): the card as it stands (a card confirmed on
    the desk keeps the fields he left), 1 contract or 10 shares, its invalidation as the stop and its target; or why not."""
    saved = card.get("outcome") if (card.get("outcome") or {}).get("state") == "confirmed" else None
    fields = (saved or {}).get("fields") or {}
    contract = fields["contract"] if fields.get("contract") is not None else card.get("contract") or ""
    order = plan_order(card["symbol"], card.get("instrument"), card.get("direction"), contract, today)
    if isinstance(order, str):
        return order
    stop = _level(fields["invalidation"] if fields.get("invalidation") is not None else (card.get("invalidation") or {}).get("price"))
    target = _level((fields.get("target") or "") if saved else card.get("target_price"))
    thesis = str(fields["thesis"] if fields.get("thesis") is not None else card.get("thesis") or "").strip()
    shares = order["instrument"] == "stock"
    return {"order": order, "quantity": PLAN_SHARES if shares else PLAN_CONTRACTS, "stop": stop, "target": target,
            "note": f"Copilot: {thesis}" if thesis else None, "source": "copilot", "idea_id": card.get("client_id") or card.get("id"),
            "size": f"{'10 shares' if shares else '1 contract'}, the desk's size for a plan"}


# --- the buttons -------------------------------------------------------------------------------------------------------

def radar_button(db: Session, setup_id) -> tuple[str, str] | None:
    """Paper it for a Radar setup ping, or None (no contract, a hidden ticker, the lab off, or anything unreadable: the
    ping goes without it)."""
    from app.models import RadarSetup
    try:
        row = db.get(RadarSetup, uuid.UUID(str(setup_id)))
        if row is None or not _lab_on() or isinstance(radar_idea(row), str) or _hidden(db, row.symbol):
            return None
        return button(RADAR, row.id.hex)
    except Exception:  # noqa: BLE001
        log.warning("Paper it button for a Radar setup not made", exc_info=True)
        return None


def plan_button(db: Session, card: dict, client_id: str, now: float | None = None) -> tuple[str, str] | None:
    """Paper it for a plan card the bot sends, or None (see ``radar_button``)."""
    try:
        today = datetime.fromtimestamp(time.time() if now is None else now, ET).date()
        if not _HEX.match(client_id or "") or not _lab_on() or isinstance(plan_idea(card, today), str) or _hidden(db, card["symbol"]):
            return None
        return button(PLAN, client_id)
    except Exception:  # noqa: BLE001
        log.warning("Paper it button for a plan card not made", exc_info=True)
        return None


# --- the tap -----------------------------------------------------------------------------------------------------------

def order_key(kind: str, key: str) -> str:
    return f"tg-{kind}-{key}"


def _short(spec: dict) -> str:
    """"NVDA 11/21 150C", "NVDA shares"."""
    if spec.get("instrument") == "stock":
        return f"{spec['symbol']} shares"
    expiry = date.fromisoformat(spec["expiry"])
    strike = next((leg["strike"] for leg in spec.get("legs") or () if leg.get("strike") is not None), spec.get("strike"))
    return f"{spec['symbol']} {expiry.month}/{expiry.day} {strike:g}{'C' if spec['option_type'] == 'call' else 'P'}"


def _clock(stamp: float) -> str:
    return datetime.fromtimestamp(stamp, ET).strftime("%I:%M").lstrip("0") + " ET"


def fill_line(spec: dict, quantity: int, per_share: float, quoted_at: float, size: str | None = None) -> str:
    """"PAPER · bought 1 NVDA 11/21 150C at 3.45 (ask, 10:42 ET) · 1 contract, … · not real money"."""
    parts = [f"PAPER · bought {quantity:,} {_short(spec)} at {paper_book._px(abs(per_share))} (ask, {_clock(quoted_at)})"]
    if size:
        parts.append(size)
    return " · ".join([*parts, NOT_REAL])


def _goals_broken(db: Session, spec: dict, quantity: int, per_share: float, stop, now: float) -> list[str]:
    """His paper-book weekly goals this entry breaks: more paper trades today than his daily limit, a most-to-lose above
    his max loss per trade (an option's premium; shares down to the stop, none without one), or the week's rules-followed
    share now below his goal. Real-book goals are about real trades and are not judged here."""
    from app.engine import weekly_goals
    goals = [g for g in weekly_goals.current(db) if g.get("book") == "paper"]
    if not goals:
        return []
    today = datetime.fromtimestamp(now, ET).date()
    out = []
    for goal in goals:
        n = goal["n"]
        if goal["kind"] == "max_trades_day":
            count = sum(1 for p in weekly_goals._paper_positions(db)
                        if datetime.fromtimestamp(p["opened_at"], ET).date() == today)
            if count > n:
                out.append(f"goal: {count} paper trades today (at most {n})")
        elif goal["kind"] == "max_loss":
            paid = abs(per_share)
            risk = (paid * spec.get("multiplier", 1) * quantity if spec.get("instrument") != "stock"
                    else (paid - stop) * quantity if isinstance(stop, (int, float)) else None)
            if risk is not None and risk > n + 0.005:
                out.append(f"goal: can lose {paper_book.usd(risk)} (max loss {paper_book.usd(n)})")
        elif goal["kind"] == "rules_pct":
            [line] = weekly_goals.progress(db, [goal], weekly_goals.monday_of(today), now)
            if line.get("ok") is False:
                out.append(f"goal: {line['text']}")
    return out


def breaks_line(rules: list[dict] | None, goals: list[str]) -> str | None:
    """The rules this entry broke and the goals it breaks, one short line; None when none."""
    broken = [f"rule “{r['text'][:60]}”" for r in rules or () if r.get("status") == "fail"]
    items = broken + goals
    return ("Breaks " + "; ".join(items) + ". Placed anyway, as on the desk.") if items else None


def _idea(db: Session, kind: str, key: str, today: date) -> dict | str:
    from app.models import RadarSetup
    if kind == RADAR:
        row = db.get(RadarSetup, uuid.UUID(key))
        return "That Radar setup is no longer in the journal." if row is None else radar_idea(row)
    from app.engine.telegram_replies import find_plan
    found = find_plan(db, key)
    return "That plan is no longer on the desk." if found is None else plan_idea(found[1], today)


def _already(db: Session, key: str) -> str | None:
    """The line for this ping's order when it is already in the paper book (any run), else None."""
    from app.models import PaperEvent
    event = db.exec(select(PaperEvent).where(PaperEvent.order_key == key)).first()
    if event is None:
        return None
    data = json.loads(event.data_json)
    return "Already papered from this ping: " + fill_line(data, data["quantity"], data["per_share"], paper_book._epoch(event.effective_at))


def tap(engine, rest: str, now: float | None = None) -> tuple[str, str | None]:
    """Paper it on a ping (``rest``: ``<kind>:<key>`` from ``pp:``): ``(chat line, PAPERED or None)``."""
    from app.ai import copilot
    kind, _, key = (rest or "").partition(":")
    if kind == RADAR:
        try:
            key = uuid.UUID(key).hex
        except ValueError:
            return "That button is not one the app knows.", None
    elif kind != PLAN or not _HEX.match(key):
        return "That button is not one the app knows.", None
    now = time.time() if now is None else now
    found = copilot.settings()
    if not found.enabled:
        return "PAPER · not placed: Copilot Lab is off on this server.", None
    if getattr(found, "evidence", "live") != "live":
        return "PAPER · not placed: paper fills need live quotes, and the desk is on simulated evidence.", None
    ordered = order_key(kind, key)
    with Session(engine) as db:
        if line := _already(db, ordered):
            return line, PAPERED
        idea = _idea(db, kind, key, datetime.fromtimestamp(now, ET).date())
        if isinstance(idea, str):
            return f"PAPER · not placed: {idea}", None
        symbol = idea["order"]["symbol"]
        if _hidden(db, symbol):
            return f"PAPER · not placed: you set {symbol} to not followed.", None
        body = {**idea["order"], "quantity": idea["quantity"], "stop": idea["stop"], "target": idea["target"], "note": idea["note"],
                "source": idea["source"], "idea_id": idea["idea_id"], "order_key": ordered}
        try:
            placed = paper_book.open_order(db, body, now, phone=True)
        except paper_book.PaperError as exc:
            db.rollback()
            return f"PAPER · not placed: {exc}", None
        filled = placed.get("filled")
        if filled is None:  # recorded by a tap a moment ago
            return _already(db, ordered) or "Already papered from this ping.", PAPERED
        spec = {**idea["order"], "multiplier": 1 if idea["order"]["instrument"] == "stock" else paper_book.MULTIPLIER}
        try:
            goals = _goals_broken(db, spec, filled["quantity"], filled["per_share"], idea["stop"], now)
        except Exception:  # noqa: BLE001 -- the order stands; the goals line is left out
            log.warning("Paper it goals not checked", exc_info=True)
            db.rollback()
            goals = []
    log.info("Paper it from Telegram: %s %s", idea["source"], symbol)
    line = fill_line(spec, filled["quantity"], filled["per_share"], filled["quoted_at"], idea["size"])
    broken = breaks_line(filled.get("rules"), goals)
    return line + (f"\n{broken}" if broken else ""), PAPERED
