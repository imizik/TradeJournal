"""The owner's own paper book (docs/copilot-lab.md § Paper): trade the way he would on Robinhood, with no money, and see
whether he is right.

- **An account.** A run starts with the cash he names (default ``DEFAULT_CASH``). It keeps cash and buying power and
  refuses an order it cannot pay for. A reset starts a new run; every older run keeps its history.
- **Fills on a live quote only.** In the regular session, from one quote read through the chart feed (its single-flight
  and minute budget): a leg bought fills at the ask, a leg sold at the bid, and only when both sides of every leg's
  quote were updated in the last ``FRESH_SECONDS`` (``setup_scanner._fresh``, the shadow book's rule). Otherwise the
  order is refused with the quote's time; never a stale or made-up price.
- **What it trades.** Shares (bought, then sold), a long call or put, and a two-leg vertical (debit or credit) as the
  desk's ticket builds one. Options carry the ×100 multiplier. A credit spread holds its width as collateral, as
  Robinhood does, so buying power falls by its most-to-lose.
- **Limit orders (day orders).** Placed from 4:00 AM New York to the close on a trading day, a limit works until a fresh
  quote crosses it or until the day's close or his cancel, whichever is first: a buy (or any order that pays) fills when
  the natural price paid is at or below the limit, at the ask; a sell (or any order that receives) when the natural price
  taken in is at or above it, at the bid. An opening limit holds its most-to-pay (a credit spread: its width less the
  limit credit) out of buying power while it works; a closing one holds its quantity, so a second close cannot sell it
  twice. ``minute_pass`` checks the working orders once a minute in the regular session with one quote read through the
  chart feed; a quote whose sides are older than ``FRESH_SECONDS`` never fills, and the order shows the last check's
  quote time (``_checks``, kept in memory).
- **Stop and target.** Stock prices. By default they are only recorded and graded after the exit; a touch (the first
  completed regular-session 1-minute bar of the underlying past the level, the setup scanner's rule) is recorded once
  per level (``touch``) for a ping. The session's final minute is not judged (it completes after the close). With the position's switch on (``auto``), the first such bar after the switch
  triggers (``trigger``; a bar touching both is the stop) a sell of all that is left at the next fresh bid, and the
  exit's grade says "auto".
- **Expiry.** An option or spread still open after its expiration's close settles at intrinsic value from the
  underlying's regular-session close (``_close_for``: the stored close, else one daily-history read through the feed).
- **Append-only.** Every fill is a ``PaperEvent``; a position is their fold, so nothing is ever edited. An order's life
  (``order``, then its fill or one ``cancel``/``lapse`` keyed ``end:<order>``), the switch and the touches are events too. A position's
  P&L at a moment is the sum of its cash flows plus what it is worth then.
- **Whose idea.** Each order records where it came from (``source``): ``mine`` (his own ticket, the default), or
  ``copilot``, ``radar`` or ``scanner`` when he tapped Paper it on one of their ideas, with the idea's id where there is
  one (``idea_id``). Fields in the event data, nothing else changes; a position recorded before them is his own.
- **His rules.** Each entry is checked against his own rules (``trading_rules``) as it fills: a market order at the fill,
  a limit order at its fill with the answers and the rules as they stood when he placed it. The checklist rides in the
  open fill's data (``rules``); a rule broken never blocks the order. The scorecard splits closed trades by followed
  versus broken.
- **Progress.** Closed paper trades (win rate, average winner and loser, largest loss, P&L by day, each trade's note and
  how it ended against his stop and target) beside his real closed trades over the same dates, read from the journal's
  ``trade`` table and never written.

It never writes fills, trades, accounts, notifications or the shadow and scanner books, and never calls Robinhood.
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import UTC, date, datetime

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from app.engine import desk_ticket, trading_rules
from app.engine import scanner_rules as rules
from app.engine.chart_math import ET
from app.engine.level_alerts import LATENESS
from app.engine.occ import occ_symbol
from app.engine.setup_scanner import _fresh
from app.models import Account, PaperEvent, PaperRun, Trade

log = logging.getLogger(__name__)

DEFAULT_CASH = 10_000.0
MIN_CASH, MAX_CASH = 100.0, 10_000_000.0
MAX_QTY = 100_000
MULTIPLIER = 100  # one standard option contract
FRESH_SECONDS = rules.MAX_DELAY_SECONDS  # both sides of a fill's quote were updated this recently
SETTLE_AFTER_SECONDS = 15 * 60  # an expiry settles this long after its close, once the close is known
NOTE_CHARS = 280
CLOSED_SHOWN = 50
POSITION_KINDS = ("open", "close", "expire")  # the events a position folds; orders, switches and touches are their own
SPEC_KEYS = ("symbol", "instrument", "option_type", "expiry", "multiplier", "label", "bias", "credit", "width", "legs")
LATE_PING_SECONDS = 10 * 60  # a touch noticed later than this after its bar is recorded without a ping
EPS = 1e-9
_checks: dict[str, dict] = {}  # order id -> the last check: when, the quote's time, the natural price or what stopped it
_TICKER = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")
_KEY = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
SOURCES = ("mine", "copilot", "radar", "scanner")  # whose idea a paper order was: his own ticket, or Paper it on an idea
_IDEA = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")


class PaperError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


# --- small helpers ---------------------------------------------------------------------------------------------------

def _utc(stamp: float) -> datetime:
    return datetime.fromtimestamp(stamp, UTC).replace(tzinfo=None)


def _epoch(moment: datetime) -> float:
    return moment.replace(tzinfo=UTC).timestamp()


def _ny_day(stamp: float) -> date:
    return datetime.fromtimestamp(stamp, ET).date()


def usd(value: float) -> str:
    return f"{'-' if value < 0 else ''}${abs(value):,.2f}"


def clock(stamp: float | None) -> str:
    if stamp is None:
        return "an unknown time"
    moment = datetime.fromtimestamp(stamp, ET)
    return f"{moment.strftime('%b')} {moment.day} {moment.strftime('%I:%M %p').lstrip('0')} ET"


def _money(value) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise PaperError("Prices are numbers.")
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise PaperError("Prices are numbers.") from None
    if not 0 < number < 1_000_000:
        raise PaperError("A price must be positive.")
    return round(number, 4)


# --- what is traded --------------------------------------------------------------------------------------------------

def contract(body: dict, today: date) -> dict:
    """The order's instrument as legs, each named by the symbol its quote is read under. Raises PaperError."""
    symbol = str(body.get("symbol") or "").strip().upper()
    if not _TICKER.match(symbol):
        raise PaperError("Name a ticker.")
    instrument = body.get("instrument")
    if instrument == "stock":
        return {"symbol": symbol, "instrument": "stock", "option_type": None, "expiry": None, "multiplier": 1,
                "label": f"{symbol} shares", "bias": "long", "credit": False, "width": None,
                "legs": [{"quote": symbol, "action": "buy", "strike": None}]}
    kind = body.get("option_type")
    if instrument not in ("option", "spread") or kind not in ("call", "put"):
        raise PaperError("Paper trades shares, a call or a put, or a vertical spread.")
    try:
        expiry = date.fromisoformat(str(body.get("expiry")))
    except ValueError:
        raise PaperError("Name the expiration as YYYY-MM-DD.") from None
    if expiry < today:
        raise PaperError("That contract has expired.")

    def strike(value) -> float:
        found = _money(value)
        if found is None:
            raise PaperError("Name the strike.")
        return found

    def leg(at: float, action: str) -> dict:
        occ = occ_symbol(symbol, expiry, kind, at)
        if not occ:
            raise PaperError("That contract cannot be named.")
        return {"quote": occ, "action": action, "strike": at}

    if instrument == "option":
        at = strike(body.get("strike"))
        return {"symbol": symbol, "instrument": "option", "option_type": kind, "expiry": expiry.isoformat(),
                "multiplier": MULTIPLIER, "bias": "long" if kind == "call" else "short", "credit": False, "width": None,
                "label": f"{symbol} ${at:g} {kind.title()} {expiry.month}/{expiry.day}/{expiry.year % 100:02d}",
                "legs": [leg(at, "buy")]}
    long_strike, short_strike = strike(body.get("long_strike")), strike(body.get("short_strike"))
    if long_strike == short_strike:
        raise PaperError("A spread's two strikes differ.")
    return {"symbol": symbol, "instrument": "spread", "option_type": kind, "expiry": expiry.isoformat(),
            "multiplier": MULTIPLIER, "credit": not desk_ticket.is_debit(kind, long_strike, short_strike),
            "bias": "long" if desk_ticket.spread_bullish(kind, long_strike, short_strike) else "short",
            "width": round(abs(long_strike - short_strike), 4),
            "label": desk_ticket.spread_label(symbol, kind, long_strike, short_strike, expiry),
            "legs": [leg(long_strike, "buy"), leg(short_strike, "sell")]}


def _quantity(value, most: int = MAX_QTY) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != int(value) or not 1 <= value <= most:
        raise PaperError(f"The quantity is a whole number from 1 to {most:,}.")
    return int(value)


# --- live quotes and the fill price ----------------------------------------------------------------------------------

def _market_open(now: float) -> bool:
    from app.engine import desk_sparks
    _day, phase, _hours, regular = desk_sparks._session(now)
    return phase == "regular" and regular is not None


def _live_quotes(symbols: list[str]) -> dict:
    """One quote read for every symbol, through the chart feed (its single-flight and minute budget). Raises PaperError."""
    from app.engine.chart_feed import ChartFeedError, _rows, chart_feed
    from app.engine.tradier import _parse_quote
    try:
        data, _stamp, issue = chart_feed.read("/v1/markets/quotes", {"symbols": ",".join(sorted(set(symbols)))}, 0, keep=False)
    except ChartFeedError as exc:
        raise PaperError(f"No quote right now: {exc}", 503) from None
    if issue:
        raise PaperError(f"No quote right now: {issue}", 503)
    out = {}
    for row in _rows(data, "quotes", "quote"):
        name = str(row.get("symbol") or "").upper()
        if name:
            out[name] = _parse_quote(name, row)
    return out


def _name(quote_symbol: str, spec: dict) -> str:
    leg = next((leg for leg in spec["legs"] if leg["quote"] == quote_symbol), None)
    if spec["instrument"] == "stock" or leg is None or leg["strike"] is None:
        return spec["symbol"]
    return f"the ${leg['strike']:g} {spec['option_type']}"


def price(spec: dict, quotes: dict, now: float, closing: bool, since: float | None = None) -> dict:
    """One unit's cash per share at the live quote, signed (+ money in, − money out): each leg bought at its ask, each
    sold at its bid (a closing order reverses the legs). Refuses a leg with no quote, no usable bid and ask, or a quote
    either of whose sides is older than ``FRESH_SECONDS`` (or than ``since``, when that is later: an automatic exit's
    trigger)."""
    cutoff = max(now - FRESH_SECONDS, since or 0.0)
    cash, legs, times = 0.0, {}, []
    for leg in spec["legs"]:
        action = leg["action"] if not closing else ("sell" if leg["action"] == "buy" else "buy")
        quote, name = quotes.get(leg["quote"]), _name(leg["quote"], spec)
        if quote is None:
            raise PaperError(f"No quote for {name} right now, so no paper fill.", 409)
        bid, ask = quote.bid, quote.ask
        if bid is None or ask is None or bid < 0 or ask < bid or (action == "buy" and not ask > 0):
            raise PaperError(f"{name.capitalize() if name.startswith('the') else name} has no usable bid and ask right now, so no paper fill.", 409)
        if not _fresh(quote, cutoff):
            stamps = [t / 1000 for t in (quote.bid_date, quote.ask_date) if isinstance(t, (int, float))]
            when = clock(min(stamps)) if stamps else "an unknown time"
            raise PaperError(f"The quote for {name} is from {when}, not live: no paper fill on a stale price.", 409)
        fill = ask if action == "buy" else bid
        cash += fill if action == "sell" else -fill
        times += [quote.bid_date / 1000, quote.ask_date / 1000]
        legs[leg["quote"]] = {"action": action, "bid": bid, "ask": ask, "price": fill,
                              "bid_at": quote.bid_date / 1000, "ask_at": quote.ask_date / 1000}
    return {"per_share": round(cash, 4), "legs": legs, "quoted_at": min(times)}


def _stock_price(spec: dict, quotes: dict) -> float | None:
    quote = quotes.get(spec["symbol"])
    if quote is None:
        return None
    for value in (quote.last, quote.mid, quote.bid):
        if isinstance(value, (int, float)) and value > 0:
            return round(float(value), 4)
    return None


# --- the book: runs, events and their fold ----------------------------------------------------------------------------

def current_run(db: Session, lock: bool = False) -> PaperRun | None:
    """The newest run; ``lock`` holds its row until the order's commit, so two orders on one run go one after the other
    (Postgres; SQLite has one writer anyway)."""
    newest = db.exec(select(PaperRun).where(PaperRun.kind == "live")  # replay runs are paper_replay's own
                     .order_by(col(PaperRun.started_at).desc(), col(PaperRun.id).desc())).first()
    if newest is None or not lock:
        return newest
    return db.exec(select(PaperRun).where(PaperRun.id == newest.id).with_for_update()).one()


def start_run(db: Session, starting_cash, reset: bool, now: float) -> PaperRun:
    cash = DEFAULT_CASH if starting_cash is None else starting_cash
    if isinstance(cash, bool) or not isinstance(cash, (int, float)) or not MIN_CASH <= cash <= MAX_CASH:
        raise PaperError(f"Start with {usd(MIN_CASH)} to {usd(MAX_CASH)}.")
    if current_run(db) is not None and not reset:
        raise PaperError("A paper account is already running; a reset starts a new run.", 409)
    run = PaperRun(starting_cash=round(float(cash), 2), started_at=_utc(now))
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def _events(db: Session, run: PaperRun) -> list[PaperEvent]:
    return list(db.exec(select(PaperEvent).where(PaperEvent.run_id == run.id)
                        .order_by(col(PaperEvent.effective_at), col(PaperEvent.recorded_at), col(PaperEvent.id))).all())


def fold(events: list[PaperEvent]) -> list[dict]:
    """Each position from its events, oldest first. A close (or the expiry) is matched to its share of the opening cash
    (the last one takes what is left, so the cash flows and the realized P&L add up to the cent). A close of more than is
    left (two closes racing) counts only for what was left, and one after the position is closed counts for nothing:
    ``applied`` is the cash the fold actually used, the only cash the account counts."""
    out: dict[uuid.UUID, dict] = {}
    for event in events:
        if event.kind not in POSITION_KINDS:
            continue
        data = json.loads(event.data_json)
        if event.kind == "open":
            out[event.position_id] = {**data, "id": str(event.position_id), "opened_at": _epoch(event.effective_at),
                                      "remaining": data["quantity"], "basis_left": data["cash"], "realized": 0.0,
                                      "exits": [], "status": "open", "closed_at": None, "applied": data["cash"]}
            continue
        position = out.get(event.position_id)
        if position is None or position["remaining"] <= 0:
            continue
        qty = min(data["quantity"], position["remaining"])
        cash = data["cash"] if qty == data["quantity"] else round(data["cash"] * qty / data["quantity"], 2)
        basis = position["basis_left"] if qty == position["remaining"] else round(position["cash"] * qty / position["quantity"], 2)
        pnl = round(cash + basis, 2)
        position["applied"] = round(position["applied"] + cash, 2)
        position["basis_left"] = round(position["basis_left"] - basis, 2)
        position["remaining"] -= qty
        position["realized"] = round(position["realized"] + pnl, 2)
        position["exits"].append({**data, "quantity": qty, "cash": cash, "kind": event.kind, "at": _epoch(event.effective_at), "pnl": pnl})
        if position["remaining"] <= 0:
            position["status"] = "expired" if event.kind == "expire" else "closed"
            position["closed_at"] = _epoch(event.effective_at)
    return list(out.values())


def account(run: PaperRun, positions: list[dict], working: list[dict] = ()) -> dict:
    """Cash is the start plus every fill's cash the fold applied; a credit spread's width is held as collateral, and a
    working opening limit holds its most-to-pay, so buying power is the cash less both."""
    cash = round(run.starting_cash + sum(p["applied"] for p in positions), 2)
    collateral = round(sum(p["width"] * p["multiplier"] * p["remaining"] for p in positions
                           if p["status"] == "open" and p["credit"]), 2)
    reserved = round(sum(o["reserve"] for o in working if o["status"] == "working" and o["side"] == "open"), 2)
    return {"cash": cash, "collateral": collateral, "reserved": reserved, "buying_power": round(cash - collateral - reserved, 2)}


def orders(events: list[PaperEvent]) -> list[dict]:
    """Each limit order from its events, oldest first: ``working`` until its fill (an event carrying its ``order_id``)
    or its one ``cancel``/``lapse``. Placed orders first, then what ended them in the order they were recorded (a fill is
    stamped with its quote's time, which may be a moment before the order)."""
    out: dict[str, dict] = {}
    for event in events:
        if event.kind == "order":
            out[str(event.position_id)] = {**json.loads(event.data_json), "id": str(event.position_id),
                                           "placed_at": _epoch(event.effective_at), "status": "working", "ended_at": None,
                                           "reason": None, "filled": None}
    for event in sorted(events, key=lambda e: (e.recorded_at, str(e.id))):
        if event.kind in ("order", "auto", "touch", "trigger", "expire"):
            continue
        data = json.loads(event.data_json)
        found = out.get(str(event.position_id) if event.kind in ("cancel", "lapse") else str(data.get("order_id") or ""))
        if found is None or found["status"] != "working":
            continue
        found["ended_at"] = _epoch(event.effective_at)
        if event.kind in ("cancel", "lapse"):
            found["status"], found["reason"] = ("canceled" if event.kind == "cancel" else "expired"), data.get("reason")
        else:
            found["status"] = "filled"
            found["filled"] = {k: data.get(k) for k in ("quantity", "per_share", "cash")}
    return list(out.values())


def switches(events: list[PaperEvent]) -> dict[str, dict]:
    """Each position's "Close automatically at stop/target" switch: its newest setting (off when never set), the event
    that set it and when."""
    out: dict[str, dict] = {}
    for event in sorted((e for e in events if e.kind == "auto"), key=lambda e: (e.effective_at, e.recorded_at, str(e.id))):
        out[str(event.position_id)] = {"on": bool(json.loads(event.data_json).get("on")), "id": str(event.id),
                                       "at": _epoch(event.effective_at)}
    return out


def _held(working: list[dict], position_id: str) -> int:
    """How many of a position a working closing limit holds."""
    return sum(o["quantity"] for o in working if o["status"] == "working" and o["side"] == "close" and o["position"] == position_id)


def _store(db: Session, run: PaperRun, position_id: uuid.UUID, kind: str, key: str, at: float, data: dict) -> bool:
    db.add(PaperEvent(run_id=run.id, position_id=position_id, kind=kind, order_key=key, effective_at=_utc(at),
                      data_json=json.dumps(data, sort_keys=True)))
    try:
        db.commit()
        return True
    except IntegrityError:  # this order (or this settlement) is already recorded
        db.rollback()
        return False


def _key(body: dict) -> str:
    key = str(body.get("order_key") or "")
    if not _KEY.match(key):
        raise PaperError("The order has no key.")
    return key


def _levels(body: dict, bias: str, stock: float | None) -> tuple[float | None, float | None]:
    """His stop and target, stock prices: for a trade that gains as the stock rises the stop sits below the stock's price
    now and the target above it; for one that gains as it falls, the other way round."""
    stop, target = _money(body.get("stop")), _money(body.get("target"))
    if stock is not None:
        for name, level in (("stop", stop), ("target", target)):
            below = (name == "stop") == (bias == "long")
            if level is not None and (level >= stock if below else level <= stock):
                raise PaperError(f"For this trade the {name} is a stock price {'below' if below else 'above'} {stock:g}.")
    return stop, target


def _source(body: dict) -> dict:
    """Whose idea the order was (``mine`` when unnamed) and the idea's id, if any."""
    source = body.get("source") or "mine"
    if source not in SOURCES:
        raise PaperError(f"A paper order's source is one of {', '.join(SOURCES)}.")
    idea = body.get("idea_id")
    if idea is not None and (source == "mine" or not isinstance(idea, str) or not _IDEA.match(idea)):
        raise PaperError("That idea's id cannot be recorded.")
    return {"source": source, "idea_id": idea}


def idea_contract(contract: dict | None) -> dict | None:
    """An idea's candidate contract (Radar's or the scanner's saved quote) as the desk's Paper it names it: its type,
    expiration and strike, or None when it does not name one."""
    if not isinstance(contract, dict) or contract.get("option_type") not in ("call", "put"):
        return None
    try:
        expiry = date.fromisoformat(str(contract.get("expiration") or contract.get("expiry")))
        strike = float(contract["strike"])
    except (KeyError, TypeError, ValueError):
        return None
    return {"option_type": contract["option_type"], "expiry": expiry.isoformat(), "strike": strike} if strike > 0 else None


def rules_context(db: Session, events: list[PaperEvent] | None = None, run: PaperRun | None = None,
                  skip: str | None = None) -> dict | None:
    """What his rules check a paper entry against: the paper cash now, and how many paper positions are open plus
    working paper buys (``skip``: the order being filled, which is this entry)."""
    run = run or current_run(db)
    if run is None:
        return None
    events = _events(db, run) if events is None else events
    positions = fold(events)
    working = [o for o in orders(events) if o["status"] == "working"]
    count = sum(1 for p in positions if p["status"] == "open") + sum(1 for o in working if o["side"] == "open" and o["id"] != skip)
    return trading_rules.paper_context(account(run, positions, working)["cash"], count)


def _rules_at(db: Session, rules: list[dict], answers: dict, spec: dict, need: float, stop, at: float,
              events: list[PaperEvent], run: PaperRun, skip: str | None = None) -> list[dict]:
    """The entry's checklist at its fill: the most it can lose (``need``: a debit's cost, a credit spread's width less
    its credit) against the paper cash, and the rest of his rules."""
    if not rules:
        return []
    order = {"instrument": spec["instrument"], "expiry": spec.get("expiry"), "size": need, "stop": stop, "at": at}
    return trading_rules.evaluate(rules, order, rules_context(db, events, run, skip), answers)


def _note(body: dict) -> str | None:
    text = " ".join(str(body.get("note") or "").split())[:NOTE_CHARS]
    return text or None


def open_order(db: Session, body: dict, now: float, preview: bool = False) -> dict:
    """Open a paper position at the live quote (``preview``: what it would fill at, nothing stored)."""
    run = current_run(db, lock=not preview)
    if run is None:
        raise PaperError("Start a paper account first.", 409)
    spec = contract(body, _ny_day(now))
    qty = _quantity(body.get("quantity"))
    note = _note(body)
    origin = _source(body)
    key = None if preview else _key(body)
    if not _market_open(now):
        raise PaperError("The market is closed: paper orders fill only in the regular session, on a live quote.", 409)
    quotes = _live_quotes([leg["quote"] for leg in spec["legs"]] + [spec["symbol"]])
    fill = price(spec, quotes, now, closing=False)
    per = fill["per_share"]
    if spec["instrument"] == "spread":
        if spec["credit"] and not per > 0:
            raise PaperError(f"No credit at the natural price right now (the sold leg's bid less the bought leg's ask is {per:.2f}).", 409)
        if not spec["credit"] and not per < 0:
            raise PaperError("This debit spread costs nothing at the natural price right now: the quotes are off. No paper fill.", 409)
        if abs(per) >= spec["width"]:
            raise PaperError(f"A {abs(per):.2f} net on a {spec['width']:g}-wide spread is no real market. No paper fill.", 409)
    stock = _stock_price(spec, quotes)
    stop, target = _levels(body, spec["bias"], stock)
    cash = round(per * spec["multiplier"] * qty, 2)
    events = _events(db, run)
    book = account(run, fold(events), orders(events))
    held = round(spec["width"] * spec["multiplier"] * qty, 2) if spec["credit"] else 0.0
    need = round(held - cash, 2)  # a debit: what it costs; a credit spread: the width held less the credit taken in
    if need > book["buying_power"] + 0.005:
        raise PaperError(f"Not enough paper buying power: this needs {usd(need)} and you have {usd(book['buying_power'])}.", 409)
    data = {**spec, "quantity": qty, "per_share": per, "cash": cash, "legs_filled": fill["legs"], "stock": stock,
            "note": note, "stop": stop, "target": target, **origin}
    if not preview:  # his rules at the fill: a broken one is recorded, never a refusal
        data["rules"] = _rules_at(db, trading_rules.current(db), trading_rules.answers_of(body.get("rule_answers")), spec,
                                  need, stop, fill["quoted_at"], events, run)
    result = {"label": spec["label"], "quantity": qty, "per_share": per, "cash": cash, "quoted_at": fill["quoted_at"],
              "legs": fill["legs"], "stock": stock, "buying_power_after": round(book["buying_power"] - need, 2),
              "buying_power": book["buying_power"], "need_each": round(need / qty, 4)}
    if preview:
        return {"preview": result}
    position_id = uuid.uuid4()
    if not _store(db, run, position_id, "open", key, fill["quoted_at"], data):
        return {"filled": None, "duplicate": True}
    return {"filled": {**result, "position_id": str(position_id)}}


def close_order(db: Session, body: dict, now: float, preview: bool = False) -> dict:
    """Close all of an open paper position, or trim part of it, at the live quote."""
    run = current_run(db, lock=not preview)
    if run is None:
        raise PaperError("Start a paper account first.", 409)
    try:
        position_id = uuid.UUID(str(body.get("position_id")))
    except ValueError:
        raise PaperError("Name the paper position.") from None
    events = _events(db, run)
    position = next((p for p in fold(events) if p["id"] == str(position_id)), None)
    if position is None or position["status"] != "open":
        raise PaperError("That paper position is not open.", 409)
    held = _held(orders(events), position["id"])
    free = position["remaining"] - held
    if free <= 0:
        raise PaperError(f"All {position['remaining']:,} are held for a working limit order: cancel it to sell another way.", 409)
    qty = free if body.get("quantity") is None else _quantity(body.get("quantity"), free)
    key = None if preview else _key(body)
    if not _market_open(now):
        raise PaperError("The market is closed: paper orders fill only in the regular session, on a live quote.", 409)
    quotes = _live_quotes([leg["quote"] for leg in position["legs"]] + [position["symbol"]])
    fill = price(position, quotes, now, closing=True)
    if position["instrument"] == "spread" and position["credit"] and fill["per_share"] >= 0:
        raise PaperError("Buying this credit spread back pays nothing at the natural price right now: the quotes are off. No paper fill.", 409)
    cash = round(fill["per_share"] * position["multiplier"] * qty, 2)
    basis = position["basis_left"] if qty == position["remaining"] else round(position["cash"] * qty / position["quantity"], 2)
    stock = _stock_price(position, quotes)
    data = {"quantity": qty, "per_share": fill["per_share"], "cash": cash, "legs_filled": fill["legs"], "stock": stock}
    result = {"label": position["label"], "quantity": qty, "per_share": fill["per_share"], "cash": cash,
              "quoted_at": fill["quoted_at"], "legs": fill["legs"], "stock": stock, "pnl": round(cash + basis, 2),
              "all": qty == position["remaining"], "held": held}
    if preview:
        return {"preview": result}
    if not _store(db, run, position_id, "close", key, fill["quoted_at"], data):
        return {"filled": None, "duplicate": True}
    return {"filled": result}


# --- limit orders (day orders) ---------------------------------------------------------------------------------------

def _window(now: float) -> tuple[str, tuple[int, int] | None]:
    """The New York phase now (pre, regular, post or closed) and today's regular session in epoch seconds."""
    from app.engine import desk_sparks
    _day, phase, _hours, regular = desk_sparks._session(now)
    return phase, regular


def _px(value: float) -> str:
    return f"{value:,.2f}" if abs(value) >= 1 or round(value, 2) == value else f"{value:.4f}".rstrip("0")


def _pays(spec: dict, closing: bool) -> bool:
    """Whether the order pays (buying, opening a debit, buying back a credit spread) rather than takes money in."""
    return spec["credit"] if closing else not spec["credit"]


def _side_words(spec: dict, closing: bool) -> str:
    if spec["instrument"] == "spread":
        return "Close" if closing else "Open"
    return "Sell" if closing else "Buy"


def place_limit(db: Session, body: dict, now: float, preview: bool = False) -> dict:
    """Place a day limit order (``action`` open, or close for an open position): it works until a fresh quote crosses
    the limit, the day's close or his cancel. Placed from 4:00 AM New York until the close on a trading day; checked at
    once when the market is open, then once a minute (``minute_pass``)."""
    run = current_run(db, lock=not preview)
    if run is None:
        raise PaperError("Start a paper account first.", 409)
    limit = _money(body.get("limit_price"))
    if limit is None:
        raise PaperError("Name the limit price.")
    phase, regular = _window(now)
    if regular is None or phase not in ("pre", "regular") or now >= regular[1]:
        raise PaperError("A paper limit is a day order: place it from 4:00 AM ET until the close on a trading day.", 409)
    expires = float(regular[1])
    events = _events(db, run)
    positions = fold(events)
    working = [o for o in orders(events) if o["status"] == "working"]
    book = account(run, positions, working)
    closing = body.get("action") == "close"
    if closing:
        try:
            position_id = uuid.UUID(str(body.get("position_id")))
        except ValueError:
            raise PaperError("Name the paper position.") from None
        position = next((p for p in positions if p["id"] == str(position_id)), None)
        if position is None or position["status"] != "open":
            raise PaperError("That paper position is not open.", 409)
        free = position["remaining"] - _held(working, position["id"])
        if free <= 0:
            raise PaperError(f"All {position['remaining']:,} are already held for a working limit order.", 409)
        qty = free if body.get("quantity") is None else _quantity(body.get("quantity"), free)
        spec = {k: position[k] for k in SPEC_KEYS}
        extra = {"position": position["id"]}
    else:
        spec = contract(body, _ny_day(now))
        qty = _quantity(body.get("quantity"))
        stock = _marks([spec["symbol"]]).get(spec["symbol"], {}).get("last")
        stop, target = _levels(body, spec["bias"], stock if isinstance(stock, (int, float)) and stock > 0 else None)
        extra = {"note": _note(body), "stop": stop, "target": target, **_source(body)}
        if not preview:  # checked at the fill, against the rules as they stand now
            extra.update(rule_answers=trading_rules.answers_of(body.get("rule_answers")), rules_set=trading_rules.current(db))
    if spec["instrument"] == "spread" and limit >= spec["width"]:
        raise PaperError(f"A {limit:g} limit on a {spec['width']:g}-wide spread can never be a real market.")
    pays = _pays(spec, closing)
    reserve = 0.0 if closing else round((limit if pays else spec["width"] - limit) * spec["multiplier"] * qty, 2)
    if reserve > book["buying_power"] + 0.005:
        raise PaperError(f"Not enough paper buying power: this limit holds {usd(reserve)} and you have {usd(book['buying_power'])}.", 409)
    data = {**spec, **extra, "side": "close" if closing else "open", "pays": pays, "limit": limit, "quantity": qty,
            "reserve": reserve, "expires_at": expires}
    shown = {"label": spec["label"], "quantity": qty, "limit": limit, "pays": pays, "reserve": reserve, "expires_at": expires,
             "buying_power": book["buying_power"], "buying_power_after": round(book["buying_power"] - reserve, 2)}
    if preview:
        return {"preview": shown}
    key = _key(body)
    order_id = uuid.uuid4()
    if not _store(db, run, order_id, "order", key, now, data):
        return {"working": None, "filled": None, "duplicate": True}
    filled = None
    if _market_open(now):
        try:  # marketable now: one quote read, as a market order makes
            found = _execute(db, now, only=str(order_id))
            filled = found[0]["filled"] if found else None
        except Exception:  # noqa: BLE001 -- the order stands and is checked again within the minute
            log.exception("paper limit: the first check failed")
    return {"working": None if filled else {**shown, "id": str(order_id)}, "filled": filled}


def cancel_order(db: Session, body: dict, now: float) -> dict:
    run = current_run(db, lock=True)
    if run is None:
        raise PaperError("Start a paper account first.", 409)
    order_id = str(body.get("order_id") or "")
    found = next((o for o in orders(_events(db, run)) if o["id"] == order_id), None)
    if found is None or found["status"] != "working":
        db.rollback()
        raise PaperError("That paper order is no longer working." if found else "No such paper order.", 409 if found else 404)
    _store(db, run, uuid.UUID(order_id), "cancel", f"end:{order_id}", now, {"reason": "You canceled it."})
    _checks.pop(order_id, None)
    return {"canceled": order_id}


def set_auto(db: Session, body: dict, now: float) -> dict:
    """Turn a position's "Close automatically at stop/target" switch on or off (an ``auto`` event; the newest wins)."""
    run = current_run(db, lock=True)
    if run is None:
        raise PaperError("Start a paper account first.", 409)
    position_id = str(body.get("position_id") or "")
    events = _events(db, run)
    position = next((p for p in fold(events) if p["id"] == position_id), None)
    if position is None or position["status"] != "open":
        db.rollback()
        raise PaperError("That paper position is not open.", 409)
    if position.get("stop") is None and position.get("target") is None:
        db.rollback()
        raise PaperError("This position has no stop or target to close at.", 409)
    on = body.get("on") is True
    current = switches(events).get(position_id)
    if bool(current and current["on"]) == on:
        db.rollback()
        return {"auto": on}
    _store(db, run, uuid.UUID(position_id), "auto", f"auto:{_key(body)}", now, {"on": on})
    return {"auto": on}


def _tidy(db: Session, run: PaperRun, now: float) -> None:
    """End each working order whose day is over (``lapse`` at the close) or whose position closed (``cancel``)."""
    def due(events: list[PaperEvent]) -> list[tuple[dict, str, float, str]]:
        positions = {p["id"]: p for p in fold(events)}
        out = []
        for o in orders(events):
            if o["status"] != "working":
                continue
            if now >= o["expires_at"]:
                out.append((o, "lapse", o["expires_at"], "A day order ends at the close."))
            elif o["side"] == "close" and positions.get(o["position"], {}).get("status") != "open":
                out.append((o, "cancel", now, "The position closed before it filled."))
        return out
    if not due(_events(db, run)):
        return
    locked = current_run(db, lock=True)
    ending = due(_events(db, locked)) if locked is not None and locked.id == run.id else []
    if not ending:
        db.rollback()
        return
    for order, kind, at, reason in ending:
        _store(db, locked, uuid.UUID(order["id"]), kind, f"end:{order['id']}", at, {"reason": reason})
        _checks.pop(order["id"], None)


def _quote_time(spec: dict, quotes: dict) -> float | None:
    stamps = [t / 1000 for leg in spec["legs"] for q in [quotes.get(leg["quote"])] if q is not None
              for t in (q.bid_date, q.ask_date) if isinstance(t, (int, float))]
    return min(stamps) if stamps else None


def _did(spec: dict, qty: int, per: float, legs: dict, at: float, closing: bool) -> str:
    """"Bought 2 × NBIS $100 Call 11/20/26 at 3.40 (the ask), Nov 13 10:42 AM ET"."""
    if spec["instrument"] == "spread":
        verb, how = ("Closed" if closing else "Opened"), f"{_px(abs(per))} net {'credit' if per > 0 else 'debit'}"
    else:
        one = next(iter(legs.values()))
        verb = "Bought" if one["action"] == "buy" else "Sold"
        how = f"{_px(one['price'])} (the {'ask' if one['action'] == 'buy' else 'bid'})"
    what = f"{qty:,} {spec['symbol']} shares" if spec["instrument"] == "stock" else f"{qty:,} × {spec['label']}"
    return f"{verb} {what} at {how}, {clock(at)}"


def _try_limit(db: Session, order: dict, quotes: dict, now: float, floor: float | None = None) -> dict | None:
    closing = order["side"] == "close"
    try:
        fill = price(order, quotes, now, closing=closing, since=floor)
    except PaperError as exc:
        _checks[order["id"]] = {"at": now, "quoted_at": _quote_time(order, quotes), "natural": None, "issue": str(exc)}
        return None
    per = fill["per_share"]
    crossed = -per <= order["limit"] + EPS if order["pays"] else per >= order["limit"] - EPS
    issue = None
    if order["instrument"] == "spread" and (abs(per) >= order["width"] or (not closing and (per >= 0) == order["pays"])
                                            or (closing and order["pays"] and per >= 0)):
        issue = "The spread's quotes are off right now (no real market at the natural price)."
    _checks[order["id"]] = {"at": now, "quoted_at": fill["quoted_at"], "natural": round(abs(per), 4), "issue": issue}
    if not crossed or issue:
        return None
    run = current_run(db, lock=True)
    events = _events(db, run)
    state = next((o for o in orders(events) if o["id"] == order["id"]), None)
    if state is None or state["status"] != "working":
        db.rollback()
        return None
    stock = _stock_price(order, quotes)
    pnl = None
    if closing:
        position = next((p for p in fold(events) if p["id"] == order["position"]), None)
        if position is None or position["status"] != "open":
            db.rollback()
            return None  # ``_tidy`` ends it
        qty = min(order["quantity"], position["remaining"])
        cash = round(per * position["multiplier"] * qty, 2)
        basis = position["basis_left"] if qty == position["remaining"] else round(position["cash"] * qty / position["quantity"], 2)
        pnl = round(cash + basis, 2)
        data = {"quantity": qty, "per_share": per, "cash": cash, "legs_filled": fill["legs"], "stock": stock,
                "order_id": order["id"], "limit": order["limit"]}
        kind, position_id = "close", uuid.UUID(position["id"])
    else:
        qty = order["quantity"]
        cash = round(per * order["multiplier"] * qty, 2)
        data = {**{k: order[k] for k in SPEC_KEYS}, "quantity": qty, "per_share": per, "cash": cash, "legs_filled": fill["legs"],
                "stock": stock, "note": order.get("note"), "stop": order.get("stop"), "target": order.get("target"),
                "source": order.get("source") or "mine", "idea_id": order.get("idea_id"),
                "order_id": order["id"], "limit": order["limit"]}
        if order.get("rules_set") is not None:
            need = round((order["width"] * order["multiplier"] * qty if order["credit"] else 0.0) - cash, 2)
            data["rules"] = _rules_at(db, order["rules_set"], order.get("rule_answers") or {}, order, need, order.get("stop"),
                                      fill["quoted_at"], events, run, skip=order["id"])
        kind, position_id = "open", uuid.UUID(order["id"])
    key = f"fill:{order['id']}"
    if not _store(db, run, position_id, kind, key, fill["quoted_at"], data):
        return None
    _checks.pop(order["id"], None)
    did = _did(order, qty, per, fill["legs"], fill["quoted_at"], closing)
    money = f"{'Took in' if cash >= 0 else 'Cost'} {usd(abs(cash))}" + ("" if pnl is None else f"; {'made' if pnl >= 0 else 'lost'} {usd(abs(pnl))}")
    return {"source": key, "symbol": order["symbol"], "title": f"PAPER · {order['symbol']} limit filled",
            "body": f"Paper, not real money. {did}; your limit {_px(order['limit'])}. {money}.",
            "filled": {"label": order["label"], "quantity": qty, "per_share": per, "cash": cash, "quoted_at": fill["quoted_at"],
                       "legs": fill["legs"], "stock": stock, "pnl": pnl, "position_id": str(position_id), "limit": order["limit"]}}


def _pending_exits(events: list[PaperEvent], positions: dict[str, dict]) -> list[tuple[dict, dict]]:
    """Each open position whose switch is still on with a trigger from that switch and no automatic exit yet."""
    keys = {e.order_key for e in events}
    sw = switches(events)
    out = []
    for event in events:
        if event.kind != "trigger":
            continue
        trigger = json.loads(event.data_json)
        position = positions.get(str(event.position_id))
        switch = sw.get(str(event.position_id))
        if (position is None or position["status"] != "open" or not switch or not switch["on"]
                or switch["id"] != trigger["auto_id"] or f"autoexit:{position['id']}:{trigger['auto_id']}" in keys):
            continue
        out.append((position, trigger))
    return out


def _try_exit(db: Session, position: dict, trigger: dict, quotes: dict, now: float, floor: float | None = None) -> dict | None:
    """Sell all that is left of a triggered position at the first quote both of whose sides moved after the trigger's bar."""
    try:
        fill = price(position, quotes, now, closing=True, since=max(trigger["condition_at"], floor or 0.0))
    except PaperError:
        return None
    per = fill["per_share"]
    if position["instrument"] == "spread" and (abs(per) >= position["width"] or (position["credit"] and per >= 0)):
        return None  # crossed legs: no real market to buy a credit spread back at
    run = current_run(db, lock=True)
    events = _events(db, run)
    current = next((p for p in fold(events) if p["id"] == position["id"]), None)
    switch = switches(events).get(position["id"])
    if current is None or current["status"] != "open" or not switch or not switch["on"] or switch["id"] != trigger["auto_id"]:
        db.rollback()
        return None
    qty = current["remaining"]
    cash = round(per * current["multiplier"] * qty, 2)
    pnl = round(cash + current["basis_left"], 2)
    stock = _stock_price(current, quotes)
    key = f"autoexit:{current['id']}:{trigger['auto_id']}"
    data = {"quantity": qty, "per_share": per, "cash": cash, "legs_filled": fill["legs"], "stock": stock,
            "auto": trigger["level"], "reference": trigger["reference"], "condition_at": trigger["condition_at"]}
    if not _store(db, run, uuid.UUID(current["id"]), "close", key, fill["quoted_at"], data):
        return None
    _tidy(db, run, now)
    level = trigger["level"]
    return {"source": key, "symbol": current["symbol"], "title": f"PAPER · {current['symbol']} auto exit at the {level}",
            "body": (f"Paper, not real money. {_touched_words(current, trigger)} "
                     f"{_did(current, qty, per, fill['legs'], fill['quoted_at'], True)}: {'made' if pnl >= 0 else 'lost'} {usd(abs(pnl))}."),
            "filled": {"label": current["label"], "quantity": qty, "per_share": per, "cash": cash, "pnl": pnl, "auto": level}}


def _execute(db: Session, now: float, only: str | None = None) -> list[dict]:
    """Check each working limit (or ``only`` that one) and each triggered automatic exit against one quote read."""
    run = current_run(db)
    if run is None or not _market_open(now):
        return []
    events = _events(db, run)
    positions = {p["id"]: p for p in fold(events)}
    working = [o for o in orders(events) if o["status"] == "working" and (only is None or o["id"] == only)]
    exits = [] if only else _pending_exits(events, positions)
    if not working and not exits:
        return []
    symbols = {leg["quote"] for spec in [*working, *(p for p, _ in exits)] for leg in spec["legs"]}
    symbols |= {spec["symbol"] for spec in [*working, *(p for p, _ in exits)]}
    try:
        quotes = _live_quotes(sorted(symbols))
    except PaperError as exc:
        for o in working:
            _checks[o["id"]] = {"at": now, "quoted_at": None, "natural": None, "issue": str(exc)}
        return []
    _phase, regular = _window(now)
    floor = float(regular[0]) if regular else None  # a quote from before the open never fills an order working at it
    out = [found for o in working if (found := _try_limit(db, o, quotes, now, floor))]
    out += [found for position, trigger in exits if (found := _try_exit(db, position, trigger, quotes, now, floor))]
    return out


# --- stop and target touches -----------------------------------------------------------------------------------------

def _touch(position: dict, bars: list[dict], start: float, now: float, only: str | None = None) -> dict | None:
    """The first completed bar after ``start``'s minute past the stop or the target (both: the stop), the setup
    scanner's rule (``scanner_rules.exit_condition``); ``only`` looks at one level."""
    long = position["bias"] == "long"
    stop = position.get("stop") if only in (None, "stop") else None
    target = position.get("target") if only in (None, "target") else None
    if stop is None and target is None:
        return None
    inf = float("inf")
    found = rules.exit_condition(position["bias"], stop if stop is not None else (-inf if long else inf),
                                 target if target is not None else (inf if long else -inf), bars, start, inf, inf, now, LATENESS)
    if found is None or found["bar_start"] is None:
        return None
    bar = next(b for b in bars if b["time"] == found["bar_start"])
    return {"level": found["reason"], "reference": found["reference"], "condition_at": found["condition_at"],
            "bar_start": found["bar_start"], "low": bar["low"], "high": bar["high"]}


def _touched_words(position: dict, touch: dict) -> str:
    """"NBIS touched your stop 95 (the 10:41 AM ET bar's low 94.80).\""""
    past = touch["low"] if (touch["level"] == "stop") == (position["bias"] == "long") else touch["high"]
    word = "low" if past == touch["low"] else "high"
    when = datetime.fromtimestamp(touch["bar_start"], ET).strftime("%I:%M %p").lstrip("0")
    return f"{position['symbol']} touched your {touch['level']} {_px(touch['reference'])} (the {when} ET bar's {word} {_px(past)})."


def _watch(db: Session, run: PaperRun, events: list[PaperEvent], now: float, minutes_for, opens_at: float) -> list[dict]:
    """Each open position with a stop or target against today's regular-session minute bars of its stock: with the
    switch on, the first touch after the switch is a ``trigger``; with it off, each level's first touch is a ``touch``
    (a ping unless noticed more than ``LATE_PING_SECONDS`` after its bar)."""
    today = _ny_day(now).isoformat()
    watched = [p for p in fold(events) if p["status"] == "open" and (p.get("stop") is not None or p.get("target") is not None)
               and not (p.get("expiry") and p["expiry"] < today)]  # an expired contract waits to settle, never pinged
    if not watched:
        return []
    keys = {e.order_key for e in events}
    sw = switches(events)
    bars_of: dict[str, list[dict] | None] = {}
    out = []
    for position in watched:
        symbol = position["symbol"]
        if symbol not in bars_of:
            try:
                bars_of[symbol] = [b for b in minutes_for(symbol, now) if b["time"] >= opens_at]
            except Exception as exc:  # noqa: BLE001 -- no bars this minute: the next pass looks again
                log.warning("paper watch: no minute bars for %s: %s", symbol, type(exc).__name__)
                bars_of[symbol] = None
        bars = bars_of[symbol]
        if not bars:
            continue
        switch = sw.get(position["id"])
        if switch and switch["on"]:
            key = f"trigger:{position['id']}:{switch['id']}"
            found = None if key in keys else _touch(position, bars, max(position["opened_at"], switch["at"]), now)
            if found is not None:
                _store(db, run, uuid.UUID(position["id"]), "trigger", key, found["condition_at"],
                       {**found, "auto_id": switch["id"], "noticed_at": now})
            continue
        for level in ("stop", "target"):
            key = f"touch:{position['id']}:{level}"
            if position.get(level) is None or key in keys:
                continue
            found = _touch(position, bars, position["opened_at"], now, only=level)
            if found is None:
                continue
            late = now - found["condition_at"] > LATE_PING_SECONDS
            if _store(db, run, uuid.UUID(position["id"]), "touch", key, found["condition_at"],
                      {**found, "noticed_at": now, "late": late}) and not late:
                out.append({"source": key, "symbol": symbol, "title": f"PAPER · {symbol} touched your {level}",
                            "body": (f"Paper, not real money. {_touched_words(position, found)} Nothing was closed: "
                                     f"Close automatically is off for {position['label']}.")})
    return out


def minute_pass(db: Session, now: float, minutes_for) -> list[dict]:
    """The paper runner's minute (regular session only): end what is over, look for stop and target touches, then check
    the working limits and triggered exits against one quote read. Returns what to ping, each once (its event's key)."""
    run = current_run(db)
    if run is None:
        return []
    _tidy(db, run, now)
    phase, regular = _window(now)
    if phase != "regular" or regular is None or not _market_open(now):
        return []
    out = _watch(db, run, _events(db, run), now, minutes_for, regular[0])
    return out + _execute(db, now)


def chart_marks(db: Session, symbol: str, since: float) -> list[dict]:
    """The current run's paper entries and exits in ``symbol`` from ``since``, as the desk chart's marks (``kind``
    paper), each at the stock's price when it filled."""
    run = current_run(db)
    if run is None:
        return []
    out = []
    for p in fold(_events(db, run)):
        if p["symbol"] != symbol:
            continue
        opened_side = "sell" if p["credit"] else "buy"
        rows = [("open", p["opened_at"], p["quantity"], p["per_share"], p.get("stock"), p.get("limit"))]
        rows += [(e["kind"], e["at"], e["quantity"], e["per_share"], e.get("stock"), e.get("auto")) for e in p["exits"]]
        for kind, at, qty, per, stock, extra in rows:
            if at < since:
                continue
            what = f"{qty:,} {symbol} shares" if p["instrument"] == "stock" else f"{qty:,} × {p['label']}"
            if kind == "open":
                verb, side = ("Opened" if p["instrument"] == "spread" else "Bought"), opened_side
            elif kind == "expire":
                verb, side = "Settled at expiry", ("buy" if opened_side == "sell" else "sell")
            else:
                verb, side = ("Closed" if p["instrument"] == "spread" else "Sold"), ("buy" if opened_side == "sell" else "sell")
            auto = f" (auto at the {extra})" if kind == "close" and extra else ""
            text = f"Paper: {verb} {what} at {_px(abs(per))}{auto}" + (f" · {symbol} {_px(stock)}" if stock and p["instrument"] != "stock" else "")
            out.append({"kind": "paper", "at": int(at), "price": stock, "side": side, "text": text})
    return out


# --- expiry ----------------------------------------------------------------------------------------------------------

def intrinsic(kind: str, strike: float, stock: float) -> float:
    return max(stock - strike, 0.0) if kind == "call" else max(strike - stock, 0.0)


def _close_for(symbol: str, day: date, now: float) -> float | None:
    """The underlying's regular-session close on ``day``: the stored close, else one daily-history read (cached)."""
    from app.engine import day_report
    found = day_report.underlying_close(symbol, day, now)
    if found:
        return found
    from app.engine.chart_feed import ChartFeedError, _rows, chart_feed
    try:
        data, _stamp, _issue = chart_feed.read("/v1/markets/history", {"symbol": symbol, "interval": "daily",
                                                "start": day.isoformat(), "end": day.isoformat()}, 3600, low=True)
    except ChartFeedError:
        return None
    for row in _rows(data, "history", "day"):
        close = row.get("close")
        if row.get("date") == day.isoformat() and isinstance(close, (int, float)) and close > 0:
            return float(close)
    return None


def _close_moment(day: date) -> float:
    from app.engine import day_report
    return day_report._close_epoch(day)


def settle(db: Session, run: PaperRun, positions: list[dict], now: float) -> bool:
    """Settle each open option or spread whose expiration's close has passed, at intrinsic value from the underlying's
    close (a long leg's value in, a short leg's out). Returns whether any settled. One with no close yet waits."""
    settled = False
    for position in positions:
        if position["status"] != "open" or not position["expiry"]:
            continue
        day = date.fromisoformat(position["expiry"])
        at = _close_moment(day)
        if now < at + SETTLE_AFTER_SECONDS:
            continue
        try:
            close = _close_for(position["symbol"], day, now)
        except Exception as exc:  # noqa: BLE001 -- the next read tries again
            log.warning("paper settle: no close for %s %s: %s", position["symbol"], day, type(exc).__name__)
            close = None
        if close is None:
            position["awaiting_close"] = True
            continue
        value = sum((1 if leg["action"] == "buy" else -1) * intrinsic(position["option_type"], leg["strike"], close)
                    for leg in position["legs"])
        qty = position["remaining"]
        data = {"quantity": qty, "per_share": round(value, 4), "cash": round(value * position["multiplier"] * qty, 2),
                "stock": close, "day": day.isoformat()}
        settled |= _store(db, run, uuid.UUID(position["id"]), "expire", f"expire:{position['id']}", at, data)
    return settled


# --- marks, verdicts and the scorecard -------------------------------------------------------------------------------

def _marks(symbols: list[str]) -> dict:
    from app.engine import desk_ticks
    return desk_ticks.kept_rows(symbols)


def worth(position: dict, marks: dict) -> dict | None:
    """What the open part is worth at the desk's newest prices (an option at its mark), signed, with the oldest of those
    prices' times; None when a leg has no price."""
    value, times = 0.0, []
    for leg in position["legs"]:
        row = marks.get(leg["quote"])
        if row is None:
            return None
        value += row["last"] if leg["action"] == "buy" else -row["last"]
        times.append(row["at"])
    per = round(value, 4)
    market = round(per * position["multiplier"] * position["remaining"], 2)
    basis = position["basis_left"]
    return {"per_share": per, "value": market, "pnl": round(market + basis, 2),
            "pct": round((market + basis) / abs(basis) * 100, 1) if basis else None, "at": min(times)}


def verdict(position: dict) -> dict:
    """How a closed trade ended against his stop and target (stock prices): the stock's price at the last exit."""
    if position["status"] == "expired":
        last = position["exits"][-1]
        return {"kind": "expiry", "text": f"Held to expiry; settled on the {last['stock']:g} close"}
    stop, target = position.get("stop"), position.get("target")
    stock = position["exits"][-1].get("stock") if position["exits"] else None
    auto = position["exits"][-1].get("auto") if position["exits"] else None
    if auto in ("stop", "target"):
        level = stop if auto == "stop" else target
        sold = f"; out with the stock at {stock:g}" if stock is not None else ""
        return {"kind": auto, "auto": True, "text": f"Auto exit at the {auto}: the stock touched {level:g}{sold}"}
    if stop is None and target is None:
        return {"kind": "none", "text": "No stop or target set"}
    if stock is None:
        return {"kind": "unknown", "text": "No stock price at the exit"}
    up = position["bias"] == "long"
    if target is not None and (stock >= target if up else stock <= target):
        return {"kind": "target", "text": f"Took the target: stock {stock:g} vs target {target:g}"}
    if stop is not None and (stock <= stop if up else stock >= stop):
        past = abs(stock - stop) / stop * 100
        late = f", {past:.1f}% past it" if past >= 0.5 else ""
        return {"kind": "stop", "text": f"Out at the stop: stock {stock:g} vs stop {stop:g}{late}"}
    return {"kind": "early", "text": f"Out before the stop or target: stock {stock:g}"}


def stats(results: list[float], realized: list[tuple[date, float]]) -> dict:
    """Closed trades' win rate, average winner and loser and largest loss; closed P&L by day."""
    wins = [r for r in results if r > 0]
    losses = [r for r in results if r < 0]
    curve, total = [], 0.0
    for day in sorted({d for d, _ in realized}):
        total = round(total + sum(v for d, v in realized if d == day), 2)
        curve.append({"day": day.isoformat(), "pnl": total})
    return {"trades": len(results), "pnl": round(sum(v for _, v in realized), 2),
            "win_rate": round(len(wins) / len(results) * 100, 1) if results else None,
            "avg_win": round(sum(wins) / len(wins), 2) if wins else None,
            "avg_loss": round(sum(losses) / len(losses), 2) if losses else None,
            "largest_loss": round(min(losses), 2) if losses else None, "curve": curve}


def by_source(closed: list[dict]) -> list[dict]:
    """Closed paper trades split by whose idea they were: P&L, trade count and win rate for each source, in ``SOURCES``
    order (a source with no closed trade shows zero trades and no win rate)."""
    out = []
    for source in SOURCES:
        mine = [p["realized"] for p in closed if (p.get("source") or "mine") == source]
        wins = sum(1 for r in mine if r > 0)
        out.append({"source": source, "trades": len(mine), "pnl": round(sum(mine), 2),
                    "win_rate": round(wins / len(mine) * 100, 1) if mine else None})
    return out


def real_trades(db: Session, since: datetime) -> dict:
    """His real closed trades (the journal's ``trade`` rows; Webull left out) from ``since`` (UTC): read only."""
    start = since.replace(tzinfo=UTC).astimezone(ET).replace(tzinfo=None)  # trade times are naive New York
    webull = select(Account.id).where(Account.broker == "webull")
    rows = db.exec(select(Trade.realized_pnl, Trade.closed_at).where(col(Trade.status).in_(("closed", "expired")))
                   .where(Trade.closed_at.is_not(None)).where(col(Trade.closed_at) >= start)
                   .where(Trade.realized_pnl.is_not(None))
                   .where(col(Trade.account_id).not_in(webull))).all()
    results = [float(pnl) for pnl, _ in rows]
    return stats(results, [(closed.date(), float(pnl)) for pnl, closed in rows])


def _order_view(o: dict) -> dict:
    keep = ("id", "side", "symbol", "instrument", "label", "multiplier", "quantity", "limit", "pays", "reserve", "placed_at",
            "expires_at", "position", "note", "stop", "target", "idea_id")
    return {**{k: o.get(k) for k in keep}, "source": o.get("source") or "mine", "check": _checks.get(o["id"])}


def _position_view(p: dict, marks: dict | None, extra: dict | None = None) -> dict:
    keep = ("id", "symbol", "instrument", "option_type", "expiry", "label", "bias", "credit", "width", "multiplier",
            "quantity", "remaining", "per_share", "cash", "stock", "note", "stop", "target", "opened_at", "status",
            "closed_at", "realized", "idea_id")
    out = {k: p.get(k) for k in keep}
    out["source"] = p.get("source") or "mine"  # recorded before sources: his own ticket
    out["rules"] = p.get("rules")  # None: entered before his rules were checked
    out["rules_outcome"] = trading_rules.outcome(p.get("rules"))
    out["legs"] = [{"quote": leg["quote"], "action": leg["action"], "strike": leg["strike"]} for leg in p["legs"]]
    out["basis"] = p["basis_left"]
    out["awaiting_close"] = bool(p.get("awaiting_close"))
    if marks is not None:
        out["mark"] = worth(p, marks)
        out.update(extra or {})
    else:
        out["exits"] = [{k: e.get(k) for k in ("kind", "at", "quantity", "per_share", "cash", "pnl", "stock")} for e in p["exits"]]
        out["verdict"] = verdict(p)
    return out


def view(db: Session, now: float, settle_expired: bool = True) -> dict:
    """The paper account, its open positions (with the desk's newest prices), closed trades and the scorecard.
    ``settle_expired=False`` (the copilot's read) writes nothing: an expired option still open, and a day order past its
    close, are shown as they stand until the desk's own read settles or ends them."""
    run = current_run(db)
    runs = list(db.exec(select(PaperRun).where(PaperRun.kind == "live").order_by(col(PaperRun.started_at), col(PaperRun.id))).all())
    if run is None:
        return {"run": None, "default_cash": DEFAULT_CASH, "earlier": [], "market_open": _market_open(now)}
    if settle_expired:
        _tidy(db, run, now)
    events = _events(db, run)
    positions = fold(events)
    if settle_expired and settle(db, run, positions, now):
        events = _events(db, run)
        positions = fold(events)
    working = [o for o in orders(events) if o["status"] == "working"]
    book = account(run, positions, working)
    open_ = [p for p in positions if p["status"] == "open"]
    marks = _marks(sorted({leg["quote"] for p in open_ for leg in p["legs"]}))
    sw = switches(events)
    keys = {e.order_key: e for e in events}
    exiting = {p["id"] for p, _ in _pending_exits(events, {p["id"]: p for p in positions})}

    def extra(p: dict) -> dict:
        touched = {}
        for level in ("stop", "target"):
            found = keys.get(f"touch:{p['id']}:{level}")
            if found is not None:
                touched[level] = _epoch(found.effective_at)
        return {"auto": bool(sw.get(p["id"], {}).get("on")), "touched": touched, "exiting": p["id"] in exiting,
                "held": _held(working, p["id"])}
    shown = [_position_view(p, marks, extra(p)) for p in reversed(open_)]
    priced = [s["mark"] for s in shown if s["mark"] is not None]
    equity = round(book["cash"] + sum(m["value"] for m in priced), 2) if len(priced) == len(shown) else None
    closed = [p for p in positions if p["status"] != "open"]
    # As the journal's trades: a position counts once it is fully closed, on its close day (a trim waits for the rest).
    paper = stats([p["realized"] for p in closed], [(_ny_day(p["closed_at"]), p["realized"]) for p in closed])
    paper["open_pnl"] = round(sum(m["pnl"] for m in priced), 2) if priced else None
    paper["by_source"] = by_source(closed)
    rules = trading_rules.current(db)
    paper["rules"] = trading_rules.split([(p.get("rules"), p["realized"]) for p in closed], rules)
    number = next(i for i, r in enumerate(runs, 1) if r.id == run.id)
    earlier = []
    for i, older in enumerate(runs[:number - 1], 1):
        folded = fold(_events(db, older))
        earlier.append({"number": i, "started_at": _epoch(older.started_at), "ended_at": _epoch(runs[i].started_at),
                        "starting_cash": older.starting_cash, "realized": round(sum(p["realized"] for p in folded), 2),
                        "trades": sum(1 for p in folded if p["status"] != "open"),
                        "left_open": sum(1 for p in folded if p["status"] == "open")})
    return {
        "run": {"id": str(run.id), "number": number, "starting_cash": run.starting_cash, "started_at": _epoch(run.started_at)},
        "account": {**book, "equity": equity, "pnl": None if equity is None else round(equity - run.starting_cash, 2),
                    "unpriced": len(shown) - len(priced), "prices_at": min((m["at"] for m in priced), default=None)},
        "positions": shown,
        "orders": [_order_view(o) for o in reversed(working)],
        "closed": [_position_view(p, None) for p in sorted(closed, key=lambda p: p["closed_at"], reverse=True)[:CLOSED_SHOWN]],
        "score": {"paper": paper, "real": real_trades(db, run.started_at), "real_rules": trading_rules.real_split(db, rules)},
        "my_rules": rules,
        "earlier": list(reversed(earlier)), "market_open": _market_open(now), "fresh_seconds": FRESH_SECONDS,
    }
