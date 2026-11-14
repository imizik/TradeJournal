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
- ``plan_stop``: the saved plan's invalidation alert armed at the new price (``POST /charts/alerts/{id}/rearm``).

Nothing here writes. The reads are the desk's own state from the database (followed or not, the Watching list, the saved
plans) and, for a price, one quote through the evidence's own quote read. Never an order, never Robinhood.
"""
from __future__ import annotations

import math
import re
import time
import uuid
from datetime import date, datetime, timedelta
from typing import Any

from app.ai.copilot_tools import (DESK_ACTIONS as ACTIONS, DESK_LABEL_MAX as LABEL_MAX, DESK_OPTION_TYPES as OPTION_TYPES,
                                   DESK_SIDES as SIDES, DESK_TABS as TABS, DESK_TIMEFRAMES as TIMEFRAMES, ToolInputError, _symbol)
# The constants live beside the tool's schema in copilot_tools; this module is its checks and its words.

KEYS = {"show": {"timeframe", "tab"}, "alert": {"price", "side", "label"}, "watch": set(), "unwatch": set(),
        "draw": {"price", "label"}, "ticket": {"expiry", "strike", "option_type"}, "plan_stop": {"price"}}
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
        expiry = args.get("expiry")
        try:
            day = date.fromisoformat(expiry) if isinstance(expiry, str) and EXPIRY.match(expiry) else None
        except ValueError:
            day = None
        if day is None:
            raise ToolInputError("expiry must be a date, YYYY-MM-DD")
        if args.get("option_type") not in OPTION_TYPES:
            raise ToolInputError("option_type is call or put")
        out.update(expiry=day.isoformat(), strike=_price(args.get("strike"), "strike"), option_type=args["option_type"])
    return out


# --------------------------------------------------------------------------- the desk as it stands

def read_state(symbol: str) -> dict:
    """The desk's own state for ``symbol``: whether he set it to Not following, his Watching list, and his saved plans in
    it (each with its invalidation alert) and the ones a ticket can open. Database reads only; no quote is read."""
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
        tickets = [{"investigation_id": r["investigation_id"], "option_type": r["option_type"], "thesis": r["thesis"]}
                   for r in desk_ticket.armed(db) if r["symbol"] == symbol]
    return {"hidden": hidden, "watching": list(watching), "plans": plans, "tickets": tickets}


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


def act(evidence, request: dict, now: float | None = None) -> dict:
    """The card for a validated request, checked against the desk; ToolInputError says why there is none."""
    state_of = getattr(evidence, "desk_state", None)
    if state_of is None:
        raise ToolInputError("desk actions are not available here (a replay or a turn away from the desk)")
    symbol, action = request["symbol"], request["action"]
    desk = state_of(symbol)
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
        if plan["option_type"] and plan["option_type"] != request["option_type"]:
            raise ToolInputError(f"the saved {symbol} plan is for {plan['option_type']}s, not {request['option_type']}s")
        from app.engine.chart_math import ET
        today = datetime.fromtimestamp(card["made_at"], ET).date()
        if not today <= date.fromisoformat(request["expiry"]) <= today + timedelta(days=EXPIRY_DAYS):
            raise ToolInputError("that expiry has passed or is too far out")
        card["investigation_id"] = plan["investigation_id"]
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
        return f"Open ticket: {s} {card['strike']:g} {card['option_type']} {expiry.strftime('%b')} {expiry.day}"
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
    return out
