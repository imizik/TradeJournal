"""The copilot's desk actions (docs/copilot-lab.md § Desk actions): what the owner asked the desk to do, as a card.

``desk_action`` is a tool like ``propose_plan``: the model calls it, this module checks the request against the desk as
it stands (the ticker is one he follows, the price is sane, the plan exists and is his, the name is or is not on his
Watching list) and returns the card. The browser shows it; a view change (the ticker on the desk chart, its timeframe,
the Chain tab, the Tape) is applied when the card arrives, with Undo; anything that saves waits for his tap, and the tap
calls the desk's own route, the one the same action by hand calls:

- ``alert``: ``POST /charts/alerts`` (the chart's alerts);
- ``watch`` / ``unwatch``: ``POST`` / ``DELETE /copilot/desk/watching`` (the app's own watchlist, never Robinhood's);
- ``draw``: the chart settings' horizontal level (``PUT /charts/settings``, the store the desk's drawings use);
- ``ticket``: the Ticket tab opened on a saved plan with that contract (copy-only, as by hand: nothing is sent);
- ``plan_stop``: the saved plan's invalidation alert armed at the new price (``POST /charts/alerts/{id}/rearm``);
- ``close`` / ``trim``: the closing ticket of a position he holds (a long call or put, or a held vertical's closing
  spread), all of it or part, at the mark now: the Ticket tab's closing view, copy-only, as "Close at target/stop" opens;
- ``note``: his one-line note on that position (``POST /copilot/desk/notes``, the book row's pen);
- ``plan_idea``: today's Radar setup card's own Plan it (the Feed's and the Scanner's), the plan card for him to confirm.

Nothing here writes. The reads are the desk's own state from the database (followed or not, the Watching list, the saved
plans, his open positions, today's setup cards), the Robinhood snapshot the desk already holds in memory (never a
Robinhood read) and, for a price, one quote through the evidence's own quote read. Never an order.
"""
from __future__ import annotations

import math
import re
import time
import uuid
from datetime import date, datetime, timedelta
from typing import Any

from app.ai.copilot_tools import (DESK_ACTIONS as ACTIONS, DESK_DIRECTIONS as DIRECTIONS, DESK_LABEL_MAX as LABEL_MAX,
                                   DESK_NOTE_MAX as NOTE_MAX, DESK_OPTION_TYPES as OPTION_TYPES, DESK_SIDES as SIDES,
                                   DESK_TABS as TABS, DESK_TIMEFRAMES as TIMEFRAMES, ToolInputError, _symbol)
# The constants live beside the tool's schema in copilot_tools; this module is its checks and its words.

KEYS = {"show": {"timeframe", "tab"}, "alert": {"price", "side", "label"}, "watch": set(), "unwatch": set(),
        "draw": {"price", "label"}, "ticket": {"expiry", "strike", "short_strike", "option_type"}, "plan_stop": {"price"},
        # A held position: the contract picks one when he holds more than one in the ticker.
        "close": {"expiry", "strike", "option_type"}, "trim": {"expiry", "strike", "option_type", "quantity", "half"},
        "note": {"expiry", "strike", "option_type", "text"}, "plan_idea": {"direction"}}
HELD = ("close", "trim", "note")  # the actions on a position he holds
MAX_CONTRACTS = 10_000
EXPIRY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
PRICE_BAND = 0.5  # a level more than 50% from the last price is refused as a likely slip, not acted on
EXPIRY_DAYS = 800  # a listed equity option expires within about two years


def _price(value: Any, name: str = "price") -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) or not 0 < value < 1_000_000:
        raise ToolInputError(f"{name} must be a positive number")
    return round(float(value), 2)


def _label(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value.strip()) > LABEL_MAX:
        raise ToolInputError(f"label must be at most {LABEL_MAX} characters")
    return " ".join(value.split()) or None


def _expiry(value: Any) -> str:
    try:
        day = date.fromisoformat(value) if isinstance(value, str) and EXPIRY.match(value) else None
    except ValueError:
        day = None
    if day is None:
        raise ToolInputError("expiry must be a date, YYYY-MM-DD")
    return day.isoformat()


def _count(value: Any, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= MAX_CONTRACTS:
        raise ToolInputError(f"{name} must be a whole number of contracts, at least 1")
    return value


def _contract(args: dict, out: dict) -> None:
    """The optional contract that picks one held position: its type, strike and expiry, any of them."""
    if args.get("option_type") is not None:
        if args["option_type"] not in OPTION_TYPES:
            raise ToolInputError("option_type is call or put")
        out["option_type"] = args["option_type"]
    if args.get("strike") is not None:
        out["strike"] = _price(args["strike"], "strike")
    if args.get("expiry") is not None:
        out["expiry"] = _expiry(args["expiry"])


def validate(args: dict) -> dict:
    """The request as the card keeps it, or ToolInputError. Each action takes only its own arguments."""
    action = args.get("action")
    if action not in KEYS:
        raise ToolInputError(f"action must be one of {', '.join(ACTIONS)}")
    extra = set(args) - KEYS[action] - {"action", "symbol"}
    if extra:
        raise ToolInputError(f"unexpected arguments for {action}: {sorted(extra)}")
    out: dict[str, Any] = {"action": action, "symbol": _symbol(args.get("symbol"))}
    if action == "show":
        timeframe, tab = args.get("timeframe"), args.get("tab", "chart")
        if timeframe is not None and timeframe not in TIMEFRAMES:
            raise ToolInputError("the desk chart's timeframes are 2m, 15m and 1D")
        if tab not in TABS:
            raise ToolInputError("tab must be chart, chain or tape")
        out.update(timeframe=timeframe, tab=tab)
    elif action == "alert":
        if args.get("side") not in SIDES:
            raise ToolInputError("an alert's side is above or below")
        out.update(price=_price(args.get("price")), side=args["side"], label=_label(args.get("label")))
    elif action == "draw":
        out.update(price=_price(args.get("price")), label=_label(args.get("label")))
    elif action == "plan_stop":
        out["price"] = _price(args.get("price"))
    elif action == "ticket":
        expiry = _expiry(args.get("expiry"))
        if args.get("option_type") not in OPTION_TYPES:
            raise ToolInputError("option_type is call or put")
        out.update(expiry=expiry, strike=_price(args.get("strike"), "strike"), option_type=args["option_type"])
        if args.get("short_strike") is not None:  # a vertical spread: the sold leg, same expiry and type
            out["short_strike"] = _price(args["short_strike"], "short_strike")
            if out["short_strike"] == out["strike"]:
                raise ToolInputError("a spread's two strikes differ")
    elif action in HELD:
        _contract(args, out)
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
        elif action == "note":
            text = args.get("text")
            words = " ".join(text.split()) if isinstance(text, str) else ""
            if not words or len(words) > NOTE_MAX:
                raise ToolInputError(f"a note is one line of 1 to {NOTE_MAX} characters")
            out["text"] = words
    elif action == "plan_idea" and args.get("direction") is not None:
        if args["direction"] not in DIRECTIONS:
            raise ToolInputError("direction is long or short")
        out["direction"] = args["direction"]
    return out


# --------------------------------------------------------------------------- the money: what a trim sells and what is left

def trim_count(held: int, quantity: int | None = None, half: bool = False) -> int:
    """Contracts a trim sells out of ``held``: half rounds down and is at least 1; a count must not be more than he holds.
    ToolInputError otherwise. (``frontend/lib/closingTicket.ts`` ``trimCount`` is the same rule.)"""
    if not isinstance(held, int) or isinstance(held, bool) or held < 1:
        raise ToolInputError("he holds no whole contracts to trim")
    if half:
        return max(1, held // 2)
    if quantity is None or quantity < 1:
        raise ToolInputError("a trim sells at least 1 contract")
    if quantity > held:
        raise ToolInputError(f"he holds {held} contract{'' if held == 1 else 's'}, fewer than {quantity}: ask the owner")
    return quantity


def proceeds(mark_per_contract: float | None, contracts: int) -> float | None:
    """What selling ``contracts`` at the mark brings in, in dollars: the mark a contract (the premium x 100; a held
    vertical's is the bought leg's less the sold leg's) times the contracts. Negative when closing costs money (a held
    credit spread). None without a mark."""
    if mark_per_contract is None or not math.isfinite(mark_per_contract):
        return None
    return round(mark_per_contract * contracts, 2)


# --------------------------------------------------------------------------- the desk as it stands

def read_state(symbol: str, need: frozenset | tuple = ()) -> dict:
    """The desk's own state for ``symbol``: whether he set it to Not following, his Watching list, and his saved plans in
    it (each with its invalidation alert) and the ones a ticket can open; with ``need`` ``held``, his open positions in it
    (``_held``), with ``ideas``, today's Radar setup cards in it (``_ideas``). Database reads and the Robinhood snapshot
    already in memory; no quote is read and Robinhood is never called."""
    from sqlmodel import Session
    from app.database import engine
    from app.engine import copilot_plans, day_journal, desk_ticket, desk_watch
    with Session(engine) as db:
        hidden = symbol in day_journal.quiet(db)
        watching = desk_watch.state(db)["symbols"]
        board = [r for r in copilot_plans.board(db, quotes=desk_ticket._no_quotes)["plans"] if r["symbol"] == symbol]
        alerts = {p["investigation_id"]: p["invalidation"] for p in copilot_plans._plans(db)[0]}
        plans = []
        for row in board:
            alert = alerts.get(row["investigation_id"])
            plans.append({"investigation_id": row["investigation_id"], "direction": row["direction"], "thesis": row["thesis"],
                          "invalidation": None if alert is None else {"price": float(alert.price), "alert_id": str(alert.id),
                                                                      "state": alert.state}})
        # As the Chain's Put on ticket: only a long call or put plan has an option ticket.
        tickets = [{"investigation_id": r["investigation_id"], "option_type": r["option_type"], "thesis": r["thesis"]}
                   for r in desk_ticket.armed(db) if r["symbol"] == symbol and r["option_type"]]
        out = {"hidden": hidden, "watching": list(watching), "plans": plans, "tickets": tickets}
        if "held" in need and not hidden:
            out["held"] = _held(db, symbol)
        if "ideas" in need and not hidden:
            out["ideas"] = _ideas(db, symbol)
    return out


def _held(db, symbol: str) -> list[dict]:
    """His open positions in ``symbol`` as the desk's book has them: each journal position with its open contracts
    (Robinhood's quantity, P&L and mark when the snapshot the desk already holds matches it) and each one only Robinhood
    shows. ``trade_id`` is the journal's trade (None for one only Robinhood shows); ``account`` stays on the server (it
    only keeps two accounts' legs from reading as one spread). ``mark`` and ``usd`` are a contract's mark (the premium x
    100) and the unrealized P&L in dollars, None when the snapshot does not have it: never a quote read here."""
    from sqlmodel import select
    from app.ai import copilot_book
    from app.engine import chart_journal
    from app.models import Account, Trade
    trades = {str(t.id): t for t in db.exec(select(Trade).join(Account, Account.id == Trade.account_id)
                                            .where(Trade.ticker == symbol, Trade.status == "open")
                                            .where(copilot_book._not_webull())).all()}
    live = copilot_book.live_or_unavailable(db)  # the desk's last snapshot, kick=False: never a Robinhood read
    matched = live["matched"] if live and live.get("state") == "ok" else {}
    out = []
    for p in chart_journal.positions(db, symbol) if trades else []:
        trade = trades.get(p["trade_id"])
        if trade is None or not p.get("open"):
            continue
        numbers = matched.get(p["trade_id"]) or {}
        option = trade.instrument_type == "option"
        out.append({"trade_id": p["trade_id"], "instrument": trade.instrument_type, "direction": p.get("direction"),
                    "side": trade.option_type if option else None,
                    "strike": round(float(trade.strike), 3) if option and trade.strike is not None else None,
                    "expiry": trade.expiration.isoformat() if option and trade.expiration else None,
                    "quantity": numbers.get("quantity") if numbers.get("quantity") is not None else p["open"],
                    "usd": numbers.get("unrealized_usd"), "mark": numbers.get("mark") if numbers else None,
                    "account": p.get("last4")})
    for row in (live or {}).get("new", []):
        if row.get("symbol") != symbol:
            continue
        option = row.get("option") or {}
        out.append({"trade_id": None, "instrument": row["instrument"], "direction": row["direction"], "side": option.get("side"),
                    "strike": option.get("strike"), "expiry": option.get("expiry"), "quantity": row.get("quantity"),
                    "usd": row.get("unrealized_usd"), "mark": row.get("mark"), "account": row.get("account")})
    return out


def _ideas(db, symbol: str, day: date | None = None) -> list[dict]:
    """Today's Radar setup cards in ``symbol`` (the Feed's Radar setup rows, which a Scanner pick plans from too), newest
    first: the event, which way, the card's words and whether it can still be planned (``plan_state`` none)."""
    from sqlmodel import col, select
    from app.engine import desk_radar_setups
    from app.engine.chart_math import ET
    from app.models import RadarSetup
    day = day or datetime.now(ET).date()
    rows = db.exec(select(RadarSetup).where(RadarSetup.session_date == day.isoformat(), RadarSetup.symbol == symbol)
                   .order_by(col(RadarSetup.created_at).desc())).all()
    out = []
    for row in rows:
        card = desk_radar_setups.view(db, row)
        out.append({"event_id": row.event_id, "direction": "long" if row.direction == "up" else "short", "words": card["words"],
                    "levels_line": card["levels_line"], "plan_state": row.plan_state})
    return out


def _last(evidence, symbol: str) -> tuple[float, Any]:
    quote = evidence.get_quotes([symbol])
    last = (quote.get("prices") or {}).get(symbol)
    if not isinstance(last, (int, float)) or isinstance(last, bool) or not last > 0:
        raise ToolInputError(f"no current price for {symbol}, so the desk cannot check that level")
    return float(last), quote.get("fetched_at")


def _near(price: float, last: float, symbol: str) -> None:
    if abs(price / last - 1) > PRICE_BAND:
        raise ToolInputError(f"{price:.2f} is more than {PRICE_BAND:.0%} from {symbol}'s {last:.2f}: ask the owner to confirm the price")


def _which(plans: list[dict], symbol: str, what: str) -> dict:
    if not plans:
        raise ToolInputError(f"there is no saved plan in {symbol} {what}")
    if len(plans) > 1:
        theses = "; ".join((p.get("thesis") or "no thesis")[:60] for p in plans[:3])
        raise ToolInputError(f"{len(plans)} saved plans in {symbol} ({theses}): ask the owner which one")
    return plans[0]


def _words(p: dict) -> str:
    """A held leg in words: "100 call Nov 21", or "shares"."""
    if p["instrument"] != "option":
        return "shares"
    when = ""
    if p.get("expiry"):
        expiry = date.fromisoformat(p["expiry"])
        when = f" {expiry.strftime('%b')} {expiry.day}"
    return f"{p['strike']:g} {p['side']}{when}"


def _structures(held: list[dict]) -> list[dict]:
    """His positions as he would name them: a long and a short leg of one type, expiry and account in the same size are
    one vertical spread (closed together); every other leg, and shares, stands alone. Each is ``{"legs", "spread"}``, the
    bought leg first in a spread."""
    groups: dict[tuple, list[dict]] = {}
    out = []
    for p in held:
        if p["instrument"] == "option" and p.get("side") in OPTION_TYPES and p.get("strike") and p.get("expiry"):
            groups.setdefault((p["side"], p["expiry"], p.get("account")), []).append(p)
        else:
            out.append({"legs": [p], "spread": False})
    for legs in groups.values():
        longs = [p for p in legs if p["direction"] == "long"]
        shorts = [p for p in legs if p["direction"] == "short"]
        if (len(legs) == 2 and len(longs) == 1 and len(shorts) == 1 and longs[0]["quantity"] == shorts[0]["quantity"]
                and longs[0]["strike"] != shorts[0]["strike"]):
            out.append({"legs": [longs[0], shorts[0]], "spread": True})
        else:
            out += [{"legs": [p], "spread": False} for p in legs]
    return out


def _structure_words(found: dict) -> str:
    legs = found["legs"]
    if found["spread"]:
        low, high = sorted((legs[0]["strike"], legs[1]["strike"]))
        expiry = date.fromisoformat(legs[0]["expiry"])
        return f"{low:g}/{high:g} {legs[0]['side']} spread {expiry.strftime('%b')} {expiry.day}"
    return ("short " if legs[0]["direction"] == "short" else "") + _words(legs[0])


def _holding(desk: dict, request: dict, symbol: str) -> dict:
    """The one position the request means, as ``_structures`` reads his book; ToolInputError says why there is none
    (nothing held, no contract that fits) or asks which one (more than one fits)."""
    held = desk.get("held") or []
    if not held:
        raise ToolInputError(f"the owner holds no open {symbol} position on the desk's book: say so and do nothing")
    found = _structures(held)
    if request["action"] != "note":
        options = [f for f in found if f["legs"][0]["instrument"] == "option"]
        if not options:
            raise ToolInputError(f"his {symbol} position is shares: the desk's closing ticket is for options, so say so")
        found = options
    pick = {k: request[k] for k in ("option_type", "strike", "expiry") if k in request}
    if pick:
        found = [f for f in found if f["legs"][0]["instrument"] == "option"
                 and ("option_type" not in pick or f["legs"][0]["side"] == pick["option_type"])
                 and ("expiry" not in pick or f["legs"][0]["expiry"] == pick["expiry"])
                 and ("strike" not in pick or any(abs(p["strike"] - pick["strike"]) < 0.0005 for p in f["legs"]))]
    if not found:
        held_words = "; ".join(_structure_words(f) for f in _structures(held))[:200]
        raise ToolInputError(f"no {symbol} position he holds fits that contract (he holds {held_words}): ask the owner")
    if len(found) > 1:
        words = "; ".join(_structure_words(f) for f in found[:4])
        raise ToolInputError(f"he holds {len(found)} {symbol} positions that fit ({words}): ask the owner which one")
    one = found[0]
    if request["action"] != "note" and not one["spread"] and one["legs"][0]["direction"] != "long":
        raise ToolInputError(f"his {symbol} {_structure_words(one)} is a short leg: the desk's closing ticket is for a long "
                             "call or put or a vertical spread, so say so")
    return one


def _held_card(card: dict, one: dict, symbol: str) -> None:
    """What a close, trim or note card keeps of the position: its legs (journal trade, contract and side; never the
    account), and for a close or trim the contracts held, sold and left, its P&L and what the sale brings in at the mark
    (both from the Robinhood snapshot the desk holds; null without it)."""
    legs = one["legs"]
    card["legs"] = [{"trade_id": p["trade_id"], "instrument": p["instrument"], "direction": p["direction"], "side": p["side"],
                     "strike": p["strike"], "expiry": p["expiry"]} for p in legs]
    card["contract"] = _structure_words(one)
    if card["action"] == "note":
        # A note goes on a journal trade: a spread's on its bought leg, which the card names.
        if legs[0]["trade_id"] is None:
            raise ToolInputError(f"the journal does not have his {symbol} {card['contract']} yet (Robinhood shows it, its "
                                 "fill email is not in): a note can be added once it is")
        card["legs"] = card["legs"][:1]
        return
    quantity = legs[0]["quantity"]
    if not isinstance(quantity, (int, float)) or isinstance(quantity, bool) or not math.isfinite(quantity) or quantity < 1 \
            or quantity != int(quantity):
        raise ToolInputError(f"his {symbol} {card['contract']} is not a whole number of contracts on the book: ask the owner")
    held = int(quantity)
    sold = held if card["action"] == "close" else trim_count(held, card.get("quantity"), card.get("half", False))
    marks = [p["mark"] for p in legs]
    mark = None if any(m is None for m in marks) else round(marks[0] - (marks[1] if one["spread"] else 0), 2)
    usds = [p["usd"] for p in legs]
    card.update(held=held, contracts=sold, remains=held - sold, mark=mark, proceeds=proceeds(mark, sold),
                usd=None if any(u is None for u in usds) else round(sum(usds), 2))


def act(evidence, request: dict, now: float | None = None) -> dict:
    """The card for a validated request, checked against the desk; ToolInputError says why there is none."""
    state_of = getattr(evidence, "desk_state", None)
    if state_of is None:
        raise ToolInputError("desk actions are not available here (a replay or a turn away from the desk)")
    symbol, action = request["symbol"], request["action"]
    need = frozenset({"held"} if action in HELD else {"ideas"} if action == "plan_idea" else ())
    desk = state_of(symbol, need) if need else state_of(symbol)
    if desk["hidden"]:
        raise ToolInputError(f"the owner set {symbol} to Not following on the desk, so the copilot leaves it alone; "
                             "say so and do nothing")
    card = {**request, "made_at": int(now if now is not None else time.time())}
    if action == "watch":
        if symbol in desk["watching"]:
            raise ToolInputError(f"{symbol} is already on the Watching list")
    elif action == "unwatch":
        if symbol not in desk["watching"]:
            raise ToolInputError(f"{symbol} is not on the Watching list")
    elif action in ("alert", "draw"):
        last, as_of = _last(evidence, symbol)
        _near(request["price"], last, symbol)
        if action == "alert":
            if request["price"] == last:
                raise ToolInputError(f"{symbol} is at {last:.2f} now, so the alert has no side to wait on")
            if (request["side"] == "below") != (request["price"] < last):
                raise ToolInputError(f"{symbol} is at {last:.2f}, already {'below' if request['side'] == 'below' else 'above'} "
                                     f"{request['price']:.2f}: ask what the owner means")
        card.update(last=last, as_of=as_of)
    elif action == "plan_stop":
        plan = _which(desk["plans"], symbol, "to move a stop on")
        stop = plan["invalidation"]
        if stop is None:
            raise ToolInputError(f"the saved plan in {symbol} has no invalidation alert to move")
        last, as_of = _last(evidence, symbol)
        _near(request["price"], last, symbol)
        if abs(stop["price"] - request["price"]) < 0.005:
            raise ToolInputError(f"the plan's stop is already {stop['price']:.2f}")
        long = plan["direction"] != "short"
        if (long and request["price"] >= last) or (not long and request["price"] <= last):
            raise ToolInputError(f"{symbol} is at {last:.2f}, so a stop at {request['price']:.2f} is already past: ask the owner")
        card.update(last=last, as_of=as_of, investigation_id=plan["investigation_id"], alert_id=stop["alert_id"],
                    was=round(stop["price"], 2), direction="short" if not long else "long")
    elif action == "ticket":
        plan = _which(desk["tickets"], symbol, "that a ticket can open (a ticket opens only from a saved long call or put "
                      "plan not yet entered)")
        if not plan["option_type"]:
            raise ToolInputError(f"the saved {symbol} plan is not a long call or put plan, so it has no option ticket")
        if request.get("short_strike") is not None:
            # As the Chain's Make it a spread: a spread that gains as the stock rises goes on a call plan, one that gains as
            # it falls on a put plan.
            from app.engine import desk_ticket
            bullish = desk_ticket.spread_bullish(request["option_type"], request["strike"], request["short_strike"])
            if plan["option_type"] != ("call" if bullish else "put"):
                raise ToolInputError(f"that spread gains as {symbol} {'rises' if bullish else 'falls'}, against the saved "
                                     f"{plan['option_type']} plan")
        elif plan["option_type"] != request["option_type"]:
            raise ToolInputError(f"the saved {symbol} plan is for {plan['option_type']}s, not {request['option_type']}s")
        from app.engine.chart_math import ET
        today = datetime.fromtimestamp(card["made_at"], ET).date()
        if not today <= date.fromisoformat(request["expiry"]) <= today + timedelta(days=EXPIRY_DAYS):
            raise ToolInputError("that expiry has passed or is too far out")
        card["investigation_id"] = plan["investigation_id"]
    elif action in HELD:
        _held_card(card, _holding(desk, request, symbol), symbol)
    elif action == "plan_idea":
        ideas = desk.get("ideas") or []
        if not ideas:
            raise ToolInputError(f"there is no Radar setup card in {symbol} today (a Scanner pick plans from its setup card): "
                                 "say so and do nothing")
        open_ = [i for i in ideas if i["plan_state"] == "none" and i["direction"] == request.get("direction", i["direction"])]
        if not open_:
            raise ToolInputError(f"today's {symbol} setup card is already {ideas[0]['plan_state']}, so it has no Plan it: say so")
        if len({i["direction"] for i in open_}) > 1:
            raise ToolInputError(f"{symbol} has a long and a short setup card today: ask the owner which one")
        idea = open_[0]
        card.update(direction=idea["direction"], event_id=idea["event_id"], words=idea["words"][:200],
                    levels_line=idea["levels_line"][:200])
    return {"state": "ok", "action": card,
            "note": "Shown at once with an Undo." if action == "show"
            else "Shown to the owner as a card: nothing happens until they tap it."}


# --------------------------------------------------------------------------- words, and the card as saved

def _money(value: float) -> str:
    return f"{value:,.2f}"


def line(card: dict) -> str:
    """What the card will do, in one line: "Set alert: NBIS below 98.00"."""
    a, s = card["action"], card["symbol"]
    if a == "show":
        where = {"chain": " · Chain", "tape": " · Tape"}.get(card.get("tab") or "chart", "")
        return f"Show {s}{' · ' + card['timeframe'] if card.get('timeframe') else ''}{where}"
    if a == "alert":
        return f"Set alert: {s} {card['side']} {_money(card['price'])}"
    if a == "watch":
        return f"Watch {s}"
    if a == "unwatch":
        return f"Stop watching {s}"
    if a == "draw":
        return f"Draw {_money(card['price'])} on {s}{' · ' + card['label'] if card.get('label') else ''}"
    if a == "ticket":
        expiry = date.fromisoformat(card["expiry"])
        when = f"{expiry.strftime('%b')} {expiry.day}"
        if card.get("short_strike") is not None:
            from app.engine import desk_ticket
            low, high = sorted((card["strike"], card["short_strike"]))
            kind = "debit" if desk_ticket.is_debit(card["option_type"], card["strike"], card["short_strike"]) else "credit"
            return f"Open ticket: {s} {low:g}/{high:g} {card['option_type']} {kind} spread {when}"
        return f"Open ticket: {s} {card['strike']:g} {card['option_type']} {when}"
    if a == "close":
        return f"Close {s} {card['contract']} · all {card['held']}"
    if a == "trim":
        return f"Trim {s} {card['contract']} · sell {card['contracts']} of {card['held']}, {card['remains']} left"
    if a == "note":
        return f"Note on {s} {card['contract']}: {card['text']}"
    if a == "plan_idea":
        return f"Plan it: {s} {card['words']}"
    return f"Update plan: {s} stop {_money(card['was'])} → {_money(card['price'])}" if "was" in card else f"Update plan: {s} stop {_money(card['price'])}"


def summary(data: dict) -> str:
    card = data.get("action") or {}
    return f"desk action: {line(card)}"[:160] if card.get("action") else "desk action"


def _uuid(value: Any, name: str) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except ValueError:
        raise ToolInputError(f"{name} must be an id") from None


def saved(rest: dict) -> dict:
    """A stored desk action card (``kind`` already removed): the request as ``validate`` takes it and what ``act`` added.
    ToolInputError for anything else."""
    rest = dict(rest)
    made_at = rest.pop("made_at", None)
    if not isinstance(made_at, int) or isinstance(made_at, bool) or made_at <= 0:
        raise ToolInputError("a desk action keeps the time it was made")
    found = {k: rest.pop(k) for k in ("last", "as_of", "investigation_id", "alert_id", "was", "direction") if k in rest}
    kept = {k: rest.pop(k) for k in HELD_FIELDS + IDEA_FIELDS if k in rest}
    rest = {k: v for k, v in rest.items() if v is not None}  # the card keeps an absent timeframe or label as null
    out = {**validate(rest), "made_at": made_at}
    if "last" in found:
        out["last"] = _price(found["last"], "last")
    if "as_of" in found:
        as_of = found["as_of"]
        if as_of is not None and not ((isinstance(as_of, (int, float)) and not isinstance(as_of, bool)) or (isinstance(as_of, str) and len(as_of) <= 40)):
            raise ToolInputError("as_of is a time")
        out["as_of"] = as_of
    if "investigation_id" in found:
        out["investigation_id"] = _uuid(found["investigation_id"], "investigation_id")
    if "alert_id" in found:
        out["alert_id"] = _uuid(found["alert_id"], "alert_id")
    if "was" in found:
        out["was"] = _price(found["was"], "was")
    if "direction" in found:
        if found["direction"] not in ("long", "short"):
            raise ToolInputError("direction is long or short")
        out["direction"] = found["direction"]
    if out["action"] in HELD:
        out.update(_saved_held(out["action"], kept))
    elif out["action"] == "plan_idea":
        if set(kept) != set(IDEA_FIELDS) or "direction" not in out:
            raise ToolInputError("a plan card keeps its setup card")
        if not isinstance(kept["event_id"], str) or not EVENT_ID.fullmatch(kept["event_id"]):
            raise ToolInputError("event_id is a Radar event")
        for key in ("words", "levels_line"):
            if not isinstance(kept[key], str) or not 0 < len(kept[key]) <= 200:
                raise ToolInputError(f"{key} is a line of words")
        out.update(kept)
    elif kept:
        raise ToolInputError(f"unexpected fields for {out['action']}: {sorted(kept)}")
    return out


HELD_FIELDS = ("legs", "contract", "held", "contracts", "remains", "mark", "proceeds", "usd")
IDEA_FIELDS = ("event_id", "words", "levels_line")
EVENT_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,120}$")


def _money_or_none(value: Any, name: str) -> float | None:
    if value is None:
        return None
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) or abs(value) > 1e9:
        raise ToolInputError(f"{name} is an amount in dollars")
    return round(float(value), 2)


def _saved_held(action: str, kept: dict) -> dict:
    """A stored close, trim or note card's position, checked: its legs, its contract words and, for a close or trim, the
    contracts held, sold and left (sold + left = held) and its money (null when it had none)."""
    legs = kept.get("legs")
    if not isinstance(legs, list) or not 1 <= len(legs) <= (1 if action == "note" else 2):
        raise ToolInputError("a position card keeps its legs")
    clean = []
    for leg in legs:
        if not isinstance(leg, dict) or set(leg) != {"trade_id", "instrument", "direction", "side", "strike", "expiry"}:
            raise ToolInputError("a leg is a trade and its contract")
        if leg["instrument"] not in ("option", "stock") or leg["direction"] not in ("long", "short"):
            raise ToolInputError("a leg is an option or shares, long or short")
        option = leg["instrument"] == "option"
        if option and leg["side"] not in OPTION_TYPES:
            raise ToolInputError("an option leg is a call or a put")
        clean.append({"trade_id": None if leg["trade_id"] is None else _uuid(leg["trade_id"], "trade_id"),
                      "instrument": leg["instrument"], "direction": leg["direction"], "side": leg["side"] if option else None,
                      "strike": _price(leg["strike"], "strike") if option else None,
                      "expiry": _expiry(leg["expiry"]) if option else None})
    if action == "note" and clean[0]["trade_id"] is None:
        raise ToolInputError("a note card names a journal trade")
    if len(clean) == 2 and not (clean[0]["direction"] == "long" and clean[1]["direction"] == "short"
                                and clean[0]["instrument"] == clean[1]["instrument"] == "option"
                                and clean[0]["side"] == clean[1]["side"] and clean[0]["expiry"] == clean[1]["expiry"]):
        raise ToolInputError("a spread card keeps its bought leg, then its sold leg")
    contract = kept.get("contract")
    if not isinstance(contract, str) or not 0 < len(contract) <= 60:
        raise ToolInputError("contract is a few words")
    out: dict[str, Any] = {"legs": clean, "contract": contract}
    if action == "note":
        if set(kept) - {"legs", "contract"}:
            raise ToolInputError("a note card keeps no money")
        return out
    counts = [kept.get(k) for k in ("held", "contracts", "remains")]
    if any(not isinstance(c, int) or isinstance(c, bool) or c < 0 or c > MAX_CONTRACTS for c in counts):
        raise ToolInputError("held, contracts and remains are whole contracts")
    held, sold, left = counts
    if sold < 1 or sold + left != held or (action == "close" and left != 0):
        raise ToolInputError("the contracts sold and left add up to the contracts held")
    out.update(held=held, contracts=sold, remains=left, mark=_money_or_none(kept.get("mark"), "mark"),
               proceeds=_money_or_none(kept.get("proceeds"), "proceeds"), usd=_money_or_none(kept.get("usd"), "usd"))
    if (out["mark"] is None) != (out["proceeds"] is None):
        raise ToolInputError("proceeds go with a mark")
    return out
