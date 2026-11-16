"""``draft_paper_order``: the copilot drafts a paper order card from the owner's words (docs/copilot-lab.md § Paper).

He types "paper 2 NBIS 100c Friday, stop 96" or "close my paper NBIS"; the model calls this tool and he sees one card:
the contract in plain words, the live price it would fill at (the ask to buy, the bid to sell) with the quote's time, the
cash it costs or brings in and the buying power left, and his stop and target. **It never fills.** Only his tap on the
card fills, through the paper book's own route (``POST /copilot/paper/orders``), as by hand.

- **Open** (``action`` open): shares, or one call or put. An option is matched to the listed contracts first (the options
  feed's expiration list and that expiry's chain, under its cache and per-minute pacing): the listed expiry nearest the
  date he named, then the listed strike nearest his. Every substitution is said in ``picked``; when the list cannot be
  read the contract is drafted as he named it and ``picked`` says it was not checked. Never a silent guess.
- **Close / trim**: the one open paper position in the ticker that fits (type, strike, expiry pick one when there are
  more), all of what is free of working limit orders, or part (``quantity``, or ``half`` rounded down, at least one).
- **The price**: ``paper_book.open_order`` / ``close_order`` with ``preview``: one quote read through the chart feed (its
  single-flight and minute budget), nothing stored. A refusal that only time fixes (market closed, a stale or missing
  quote, no buying power, no paper account) leaves ``preview`` null and says why in ``issue``: the card shows it greyed and
  its button off, never a made-up price. A refusal of the request itself (a stop on the wrong side, no such position) is
  a ``ToolInputError`` for the model to say or ask about.

A ticker he set to Not following is refused, so the copilot stays silent on it. No Robinhood call, no write.
"""
from __future__ import annotations

import math
import re
import time
from datetime import date, datetime
from typing import Any

from app.ai.copilot_tools import ToolInputError, _symbol

ACTIONS = ("open", "close", "trim")
IDEAS = ("mine", "copilot")  # whose idea: he dictated it, or the copilot suggested it
KEYS = {"open": {"instrument", "option_type", "expiry", "strike", "quantity", "stop", "target", "idea"},
        "close": {"option_type", "expiry", "strike"},
        "trim": {"option_type", "expiry", "strike", "quantity", "half"}}
EXPIRY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
LIST_TTL = 6 * 3600  # the strikes listed today: a chain already read today is reused, never re-read for this
PICKED_CHARS = 160
ISSUE_CHARS = 240


def _price(value: Any, name: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) or not 0 < value < 1_000_000:
        raise ToolInputError(f"{name} must be a positive number")
    return round(float(value), 4)


def _count(value: Any, name: str) -> int:
    from app.engine.paper_book import MAX_QTY
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= MAX_QTY:
        raise ToolInputError(f"{name} must be a whole number from 1 to {MAX_QTY:,}")
    return value


def _expiry(value: Any) -> str:
    try:
        day = date.fromisoformat(value) if isinstance(value, str) and EXPIRY.match(value) else None
    except ValueError:
        day = None
    if day is None:
        raise ToolInputError("expiry must be a date, YYYY-MM-DD")
    return day.isoformat()


def validate(args: dict) -> dict:
    """The request as the card keeps it, or ToolInputError. Each action takes only its own arguments."""
    action = args.get("action")
    if action not in ACTIONS:
        raise ToolInputError("action must be open, close or trim")
    extra = set(args) - KEYS[action] - {"action", "symbol"}
    if extra:
        raise ToolInputError(f"unexpected arguments for {action}: {sorted(extra)}")
    out: dict[str, Any] = {"action": action, "symbol": _symbol(args.get("symbol"))}
    if action == "open":
        instrument = args.get("instrument")
        if instrument not in ("stock", "option"):
            raise ToolInputError("instrument is stock (shares) or option (one call or put); a spread is drafted from the Ticket")
        out["instrument"] = instrument
        out["quantity"] = _count(args.get("quantity"), "quantity")
        if instrument == "option":
            if args.get("option_type") not in ("call", "put"):
                raise ToolInputError("option_type is call or put")
            if args.get("expiry") is None or args.get("strike") is None:
                raise ToolInputError("an option needs its expiry and strike: ask the owner which")
            out.update(option_type=args["option_type"], expiry=_expiry(args["expiry"]), strike=_price(args["strike"], "strike"))
        elif any(args.get(k) is not None for k in ("option_type", "expiry", "strike")):
            raise ToolInputError("shares take no option_type, expiry or strike")
        for key in ("stop", "target"):
            if args.get(key) is not None:
                out[key] = _price(args[key], key)
        idea = args.get("idea", "mine")
        if idea not in IDEAS:
            raise ToolInputError("idea is mine (he named the trade) or copilot (you suggested it)")
        out["idea"] = idea
        return out
    if args.get("option_type") is not None:
        if args["option_type"] not in ("call", "put"):
            raise ToolInputError("option_type is call or put")
        out["option_type"] = args["option_type"]
    if args.get("strike") is not None:
        out["strike"] = _price(args["strike"], "strike")
    if args.get("expiry") is not None:
        out["expiry"] = _expiry(args["expiry"])
    if action == "trim":
        half = args.get("half")
        if half is not None and not isinstance(half, bool):
            raise ToolInputError("half is true or false")
        if (args.get("quantity") is None) == (not half):
            raise ToolInputError("a trim takes either quantity or half, one of them")
        if half:
            out["half"] = True
        else:
            out["quantity"] = _count(args.get("quantity"), "quantity")
    return out


# --------------------------------------------------------------------------- the contract he named, against what is listed

def _day(d: date) -> str:
    return f"{d.strftime('%a')} {d.strftime('%b')} {d.day}"


def nearest_expiry(listed: list[date], asked: date) -> date | None:
    """The listed expiration nearest ``asked`` (a tie goes to the earlier one), or None when nothing is listed."""
    return min(listed, key=lambda d: (abs((d - asked).days), d)) if listed else None


def nearest_strike(strikes: list[float], asked: float) -> float | None:
    """The listed strike nearest ``asked`` (a tie goes to the lower one), or None when none is listed."""
    return min(strikes, key=lambda s: (abs(s - asked), s)) if strikes else None


def resolve(symbol: str, option_type: str, expiry: str, strike: float, chains=None) -> tuple[str, float, list[str]]:
    """The listed contract nearest the one he named: ``(expiry, strike, picked)``, ``picked`` saying in words each part
    that differs from his. The expiration list and that expiry's chain come from the options feed (its cache and
    pacing; a chain read today is reused). When they cannot be read, his contract as named, and ``picked`` says so."""
    if chains is None:
        from app.engine.options_feed import options_feed
        chains = options_feed.chains
    asked_day = date.fromisoformat(expiry)
    chosen: list[date] = []

    def pick(live: list[date]) -> list[date]:
        found = nearest_expiry(live, asked_day)
        chosen[:] = [found] if found else []
        return chosen
    try:
        reads, issue = chains(symbol, pick, LIST_TTL)
    except ValueError:
        raise ToolInputError(f"{symbol} has no listed options") from None
    if not chosen:
        if issue:
            return expiry, strike, [f"Could not check the listed {symbol} contracts just now ({issue[:80]}): drafted as you named it."]
        raise ToolInputError(f"{symbol} has no listed options")
    day = chosen[0]
    picked = [] if day == asked_day else [f"{_day(asked_day)} is not a listed {symbol} expiry; the nearest is {_day(day)}."]
    chain = next((r.value for r in reads if r.value.expiration == day), None)
    if chain is None:
        return day.isoformat(), strike, picked + [f"Could not read the {_day(day)} strikes just now: drafted at ${strike:g} as you named it."]
    contracts = [c for c in chain.contracts if c.option_type == option_type and c.root == symbol]
    found = nearest_strike(sorted({c.strike for c in contracts}), strike)
    if found is None:
        raise ToolInputError(f"no {symbol} {option_type}s are listed for {_day(day)}")
    contract = next(c for c in contracts if c.strike == found)
    if contract.multiplier not in (None, 100):
        raise ToolInputError(f"the {symbol} ${found:g} {option_type} is an adjusted contract ({contract.multiplier} shares): "
                             "paper trades standard contracts only, so say so")
    if abs(found - strike) > 1e-6:
        picked.append(f"${strike:g} is not a listed strike; the nearest is ${found:g}.")
    return day.isoformat(), found, picked


def _said(lines: list[str]) -> list[str]:
    """The picked lines as the card keeps them: at most three, each within ``PICKED_CHARS``."""
    return [w if len(w) <= PICKED_CHARS else w[:PICKED_CHARS - 1] + "…" for w in lines[:3]]


# --------------------------------------------------------------------------- the card

def _preview(fill: dict, closing: bool) -> dict:
    """What the card shows of a preview: the price per share (one leg: its ask or bid; a spread: the net), the cash
    (negative paid, positive taken in), the quote's time and, opening, the buying power before and after; closing, the
    P&L of what it sells."""
    legs = list(fill["legs"].values())
    out = {"per_share": fill["per_share"], "cash": fill["cash"], "quoted_at": fill["quoted_at"], "stock": fill.get("stock")}
    if len(legs) == 1:
        out.update(price=legs[0]["price"], side="ask" if legs[0]["action"] == "buy" else "bid")
    if closing:
        out["pnl"] = fill["pnl"]
    else:
        out.update(buying_power=fill["buying_power"], buying_power_after=fill["buying_power_after"])
    return out


def _try(call, closing: bool) -> tuple[dict | None, str | None]:
    """A preview, or the reason there is none now. A refusal of the request itself (400) goes to the model."""
    from app.engine.paper_book import PaperError
    try:
        return _preview(call()["preview"], closing), None
    except PaperError as exc:
        if exc.status == 400:
            raise ToolInputError(str(exc)) from None
        return None, str(exc)[:ISSUE_CHARS]


def _open(db, request: dict, now: float, chains=None) -> dict:
    from app.engine import paper_book
    card = {**request, "picked": []}
    if request["instrument"] == "option":
        card["expiry"], card["strike"], picked = resolve(request["symbol"], request["option_type"], request["expiry"],
                                                         request["strike"], chains)
        card["picked"] = _said(picked)
    body = {"symbol": card["symbol"], "instrument": card["instrument"], "quantity": card["quantity"],
            "option_type": card.get("option_type"), "expiry": card.get("expiry"), "strike": card.get("strike"),
            "stop": card.get("stop"), "target": card.get("target"), "source": card["idea"]}
    from app.engine.chart_math import ET
    try:
        spec = paper_book.contract(body, datetime.fromtimestamp(now, ET).date())
    except paper_book.PaperError as exc:
        raise ToolInputError(str(exc)) from None
    card.update(label=spec["label"], multiplier=spec["multiplier"])
    card["preview"], card["issue"] = _try(lambda: paper_book.open_order(db, body, now, preview=True), False)
    return card


def _words(p: dict) -> str:
    return p["label"]


def _position(db, request: dict) -> tuple[dict, int]:
    """The one open paper position the request means and how many of it are free of working limit orders."""
    from app.engine import paper_book
    run = paper_book.current_run(db)
    if run is None:
        raise ToolInputError("he has not started paper trading yet, so there is nothing to close")
    events = paper_book._events(db, run)
    symbol = request["symbol"]
    found = [p for p in paper_book.fold(events) if p["status"] == "open" and p["symbol"] == symbol]
    if not found:
        raise ToolInputError(f"he holds no open paper {symbol} position: say so and do nothing")
    pick = {k: request[k] for k in ("option_type", "strike", "expiry") if k in request}
    if pick:
        found = [p for p in found if p["instrument"] != "stock"
                 and ("option_type" not in pick or p["option_type"] == pick["option_type"])
                 and ("expiry" not in pick or p["expiry"] == pick["expiry"])
                 and ("strike" not in pick or any(leg["strike"] is not None and abs(leg["strike"] - pick["strike"]) < 1e-6
                                                  for leg in p["legs"]))]
        if not found:
            raise ToolInputError(f"no open paper {symbol} position fits that contract: ask the owner")
    if len(found) > 1:
        words = "; ".join(_words(p) for p in found[:4])
        raise ToolInputError(f"he holds {len(found)} open paper {symbol} positions ({words}): ask the owner which one")
    one = found[0]
    free = one["remaining"] - paper_book._held(paper_book.orders(events), one["id"])
    if free <= 0:
        raise ToolInputError(f"all of his paper {one['label']} is held for a working limit order: he cancels it first")
    return one, free


def _close(db, request: dict, now: float) -> dict:
    from app.engine import paper_book
    one, free = _position(db, request)
    if request["action"] == "close":
        quantity = free
    elif request.get("half"):
        quantity = max(1, free // 2)
    else:
        quantity = request["quantity"]
        if quantity > free:
            raise ToolInputError(f"he has {free:,} of his paper {one['label']} free to sell, fewer than {quantity:,}: ask the owner")
    card = {"action": request["action"], "symbol": one["symbol"], "position_id": one["id"], "label": one["label"],
            "instrument": one["instrument"], "multiplier": one["multiplier"], "credit": bool(one.get("credit")),
            "held": free, "quantity": quantity, "remains": free - quantity, "picked": []}
    if free < one["remaining"]:  # "all" on the card means all that is free: say what a working limit keeps
        card["picked"] = _said([f"{one['remaining'] - free:,} of the {one['remaining']:,} are held for a working limit order "
                                f"and stay open; this sells the other {free:,}."])
    body = {"position_id": one["id"], "quantity": quantity}
    card["preview"], card["issue"] = _try(lambda: paper_book.close_order(db, body, now, preview=True), True)
    return card


def live_draft(request: dict, now: float | None = None, chains=None) -> dict:
    """The card for a validated request, priced at a live quote; ToolInputError says why there is none."""
    from sqlmodel import Session
    from app.database import engine
    from app.engine import day_journal
    at = time.time() if now is None else now
    with Session(engine) as db:
        if request["symbol"] in day_journal.quiet(db):
            raise ToolInputError(f"the owner set {request['symbol']} to Not following on the desk, so the copilot leaves it "
                                 "alone; say so and do nothing")
        card = _open(db, request, at, chains) if request["action"] == "open" else _close(db, request, at)
    return result(card, at)


def result(card: dict, now: float) -> dict:
    card = {**card, "made_at": int(now)}
    note = ("Shown to the owner as a paper order card: nothing is filled until they tap it, and the tap fills at that "
            "moment's live quote. Say any picked substitution plainly.")
    if card.get("issue"):
        note = f"No live price for the card now ({card['issue']}): its button is off until a fresh quote. Say so in a sentence."
    return {"state": "ok", "order": card, "note": note}


def fixture_draft(request: dict, now: float | None = None) -> dict:
    """SIMULATED: a card with invented prices for the fixture backend (the UX sandbox and the browser tests). The paper
    book's own route still refuses to fill on simulated evidence."""
    at = time.time() if now is None else now
    if request["action"] != "open":
        held = 2
        quantity = held if request["action"] == "close" else (max(1, held // 2) if request.get("half") else request["quantity"])
        if quantity > held:
            raise ToolInputError(f"he has {held} of his paper NBIS $100 Call 11/20/26 free to sell, fewer than {quantity}: ask the owner")
        if request["symbol"] != "NBIS":
            raise ToolInputError(f"he holds no open paper {request['symbol']} position: say so and do nothing")
        cash = round(4.10 * 100 * quantity, 2)
        card = {"action": request["action"], "symbol": "NBIS", "position_id": "00000000-0000-4000-8000-0000000000a1",
                "label": "NBIS $100 Call 11/20/26", "instrument": "option", "multiplier": 100, "credit": False, "held": held,
                "quantity": quantity, "remains": held - quantity, "picked": [],
                "preview": {"per_share": 4.10, "cash": cash, "quoted_at": at - 4, "stock": 97.20, "price": 4.10, "side": "bid",
                            "pnl": round(cash - 340.0 * quantity, 2)}, "issue": None}
        return result(card, at)
    stock = request["instrument"] == "stock"
    card = {**request, "picked": [], "multiplier": 1 if stock else 100}
    if stock:
        card["label"] = f"{request['symbol']} shares"
        per = 94.35
    else:
        day = date.fromisoformat(request["expiry"])
        strike = request["strike"]
        if strike != round(strike):
            card["picked"].append(f"${strike:g} is not a listed strike; the nearest is ${round(strike):g}.")
            strike = float(round(strike))
        card.update(strike=strike, label=f"{request['symbol']} ${strike:g} {request['option_type'].title()} "
                                         f"{day.month}/{day.day}/{day.year % 100:02d}")
        per = 3.40
    cash = -round(per * card["multiplier"] * request["quantity"], 2)
    card["preview"] = {"per_share": -per, "cash": cash, "quoted_at": at - 4, "stock": 94.35, "price": per, "side": "ask",
                       "buying_power": 9309.5, "buying_power_after": round(9309.5 + cash, 2)}
    card["issue"] = None
    return result(card, at)


# --------------------------------------------------------------------------- words, and the card as saved

def line(card: dict) -> str:
    """The card in one line: "Paper: buy 2 × NBIS $100 Call 11/20/26", "Paper: close NBIS shares · all 10"."""
    if card["action"] == "open":
        n = card["quantity"]
        return f"Paper: buy {n:,} {card['label']}" if card["instrument"] == "stock" else f"Paper: buy {n:,} × {card['label']}"
    if card["action"] == "close":
        return f"Paper: close {card['label']} · all {card['quantity']:,}"
    return f"Paper: trim {card['label']} · sell {card['quantity']:,} of {card['held']:,}"


def summary(data: dict) -> str:
    card = data.get("order") or {}
    if not card.get("action"):
        return "paper order"
    return (f"{line(card)}" + (f" · {card['issue']}" if card.get("issue") else ""))[:160]


def _num(value: Any, name: str, signed: bool = False) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) or abs(value) > 1e10 \
            or (not signed and value < 0):
        raise ToolInputError(f"{name} is a number")
    return float(value)


def _preview_saved(found: Any, closing: bool) -> dict | None:
    if found is None:
        return None
    if not isinstance(found, dict):
        raise ToolInputError("a preview is an object")
    keys = {"per_share", "cash", "quoted_at", "stock", "price", "side"} | ({"pnl"} if closing else {"buying_power", "buying_power_after"})
    if set(found) - keys:
        raise ToolInputError(f"unexpected preview fields: {sorted(set(found) - keys)}")
    out = {"per_share": _num(found.get("per_share"), "per_share", True), "cash": _num(found.get("cash"), "cash", True),
           "quoted_at": _num(found.get("quoted_at"), "quoted_at"),
           "stock": None if found.get("stock") is None else _num(found["stock"], "stock")}
    if "price" in found or "side" in found:
        if found.get("side") not in ("ask", "bid"):
            raise ToolInputError("side is ask or bid")
        out.update(price=_num(found.get("price"), "price"), side=found["side"])
    if closing:
        out["pnl"] = _num(found.get("pnl"), "pnl", True)
    else:
        out.update(buying_power=_num(found.get("buying_power"), "buying_power", True),
                   buying_power_after=_num(found.get("buying_power_after"), "buying_power_after", True))
    return out


def _words_list(found: Any) -> list[str]:
    if not isinstance(found, list) or len(found) > 3 or any(not isinstance(w, str) or len(w) > PICKED_CHARS for w in found):
        raise ToolInputError("picked is a few short lines")
    return list(found)


def saved(rest: dict) -> dict:
    """A stored paper order card (``kind`` already removed), checked field by field; ToolInputError for anything else."""
    rest = dict(rest)
    made_at = rest.pop("made_at", None)
    if not isinstance(made_at, int) or isinstance(made_at, bool) or made_at <= 0:
        raise ToolInputError("a paper order card keeps the time it was made")
    picked, preview, issue = _words_list(rest.pop("picked", [])), rest.pop("preview", None), rest.pop("issue", None)
    if issue is not None and (not isinstance(issue, str) or len(issue) > ISSUE_CHARS):
        raise ToolInputError("issue is a line")
    label, multiplier = rest.pop("label", None), rest.pop("multiplier", None)
    if not isinstance(label, str) or not 0 < len(label) <= 80:
        raise ToolInputError("label is the contract in words")
    if multiplier not in (1, 100):
        raise ToolInputError("multiplier is 1 or 100")
    action = rest.get("action")
    if action == "open":
        out = validate({k: v for k, v in rest.items() if v is not None})
    elif action in ("close", "trim"):
        kept = {k: rest.pop(k, None) for k in ("position_id", "instrument", "credit", "held", "quantity", "remains")}
        import uuid
        try:
            position_id = str(uuid.UUID(str(kept["position_id"])))
        except ValueError:
            raise ToolInputError("position_id is a paper position") from None
        if kept["instrument"] not in ("stock", "option", "spread") or not isinstance(kept["credit"], bool):
            raise ToolInputError("a paper position is shares, an option or a spread")
        counts = [kept[k] for k in ("held", "quantity", "remains")]
        if any(not isinstance(c, int) or isinstance(c, bool) or c < 0 for c in counts):
            raise ToolInputError("held, quantity and remains are whole numbers")
        held, quantity, remains = counts
        if quantity < 1 or quantity + remains != held or (action == "close" and remains != 0):
            raise ToolInputError("the quantity sold and left add up to what was held")
        out = {"action": action, "symbol": _symbol(rest.get("symbol")), **kept, "position_id": position_id}
        extra = set(rest) - {"action", "symbol"}
        if extra:
            raise ToolInputError(f"unexpected fields for {action}: {sorted(extra)}")
    else:
        raise ToolInputError("action must be open, close or trim")
    out.update(label=label, multiplier=multiplier, picked=picked, preview=_preview_saved(preview, action != "open"),
               issue=issue, made_at=made_at)
    return out
