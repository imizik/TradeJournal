"""The desk's roll ticket (docs/copilot-lab.md § Ticket, "Roll"): close a held long call or put and open another of the
same type (a later expiry and/or another strike) as one order to copy into Robinhood by hand.

Copy only. Nothing here places, sends, previews or stages an order, and nothing calls a broker or the Robinhood
connection: the held contract's terms (strike, expiry, contracts held, cost a contract) come from the desk's book row,
the quotes from the one option-chain pass the ticket's own read makes (``options_feed.chains``, both expiries in one
paced pass), and the rest is arithmetic (``roll_figures``).

Only a single long call or put rolls: the screen offers Roll on nothing else, and this module prices a long leg closed
and a long leg opened on the same symbol and type. A contract with a stale or missing quote carries no number (it is
said with its time), so the roll has no net price then; a wide market gives one, said to be rough. Never a made-up price.

Prices are a share's premium, as Robinhood quotes them; dollars are x the multiplier x the contracts. A roll's net is
signed as money paid: positive is a debit (he pays), negative a credit (he takes money in).
"""
from __future__ import annotations

from datetime import date
import time
from typing import Callable

from app.engine.desk_ticket import _epoch, _find, cents, contract_quote, label, underlying

EVEN = 0.005  # a net under half a cent rounds to 0.00: neither a debit nor a credit


class RollError(Exception):
    """A roll this build does not price, with the plain reason."""


def signed_cents(value: float) -> float:
    """To the cent as ``desk_ticket.cents`` rounds, symmetric about zero: -1.405 is -1.41 as 1.405 is 1.41."""
    return cents(value) if value >= 0 else -cents(-value)


def net_type(net: float | None) -> str | None:
    """``debit`` (he pays), ``credit`` (he takes in) or ``even`` for a signed net a share; None without one."""
    if net is None:
        return None
    return "debit" if net >= EVEN else "credit" if net <= -EVEN else "even"


def roll_figures(kind: str, old_strike: float, new_strike: float, old_expiry: date, new_expiry: date, *,
                 close_qty: int | None, open_qty: int | None, multiplier: int | None, close_price: float | None,
                 open_price: float | None, net: float | None = None, cost_per_contract: float | None = None,
                 spot: float | None = None) -> dict:
    """What a roll does to the money, for ``close_qty`` contracts sold to close at ``close_price`` a share and
    ``open_qty`` of the new contract bought at ``open_price`` a share.

    ``net``: the roll's limit as one order, signed a share (+ debit, - credit), when both legs have the same count; it
    replaces the two prices for the dollars that change hands (Robinhood fills a roll at its net, not at each leg's).
    Without it the net is ``open_price - close_price`` (same count) or the two orders' dollars (different counts).

    - ``proceeds``: the close leg's dollars, ``close_price x multiplier x close_qty``; ``cost``: the open leg's.
    - ``net_usd``: dollars paid for the roll (+) or taken in (-): ``net x multiplier x qty``, else ``cost - proceeds``.
    - ``basis_before``: what the rolled contracts cost him, ``cost_per_contract x close_qty`` (the book keeps cost a
      contract, the premium x the multiplier); ``in_trade_after`` that plus ``net_usd``: the money in the trade after it.
    - ``at_risk_before``: what the rolled contracts are worth now at ``close_price`` (all he can still lose on them);
      ``at_risk_after`` that plus ``net_usd``: what the new contracts will have cost, all a long option can lose.
    - ``breakeven``: the new contract's at expiry at ``open_price`` (strike plus it for a call, less it for a put), as
      Robinhood will show the new position from its own fill; ``move_pct`` the stock's move from ``spot`` to it.
    - ``trade_breakeven``: where the new contracts at expiry pay back all the money in the trade (``in_trade_after``
      spread over ``open_qty x multiplier`` shares from the new strike); ``ahead`` when he has already taken out more
      than he put in, so there is none (taken out exactly what he put in: the new strike).
    - ``days_added``: new expiry less old, in days (negative when the new expiry is earlier).
    Anything the inputs do not give is None.
    """
    out = {"days_added": (new_expiry - old_expiry).days, "same_count": None, "net": None, "net_type": None,
           "proceeds": None, "cost": None, "net_usd": None, "basis_before": None, "in_trade_after": None,
           "at_risk_before": None, "at_risk_after": None, "breakeven": None, "move_pct": None,
           "trade_breakeven": None, "ahead": False}
    counts_ok = all(isinstance(q, int) and q > 0 for q in (close_qty, open_qty))
    out["same_count"] = close_qty == open_qty if counts_ok else None  # None: no counts yet, a share's net still stands
    sign = 1 if kind == "call" else -1
    if open_price is not None and open_price > 0:
        out["breakeven"] = round(new_strike + sign * open_price, 4)
        if spot and spot > 0:
            out["move_pct"] = round((out["breakeven"] - spot) / spot * 100, 2)
    if net is None and out["same_count"] is not False and close_price is not None and open_price is not None:
        net = open_price - close_price
    if net is not None and out["same_count"] is not False:
        out["net"] = round(abs(signed_cents(net)), 2)
        out["net_type"] = net_type(net)
    if not counts_ok or not multiplier or multiplier <= 0:
        return out
    if close_price is not None and close_price >= 0:
        out["proceeds"] = cents(close_price * multiplier * close_qty)
        out["at_risk_before"] = out["proceeds"]
    if open_price is not None and open_price > 0:
        out["cost"] = cents(open_price * multiplier * open_qty)
    if out["same_count"] and net is not None:
        out["net_usd"] = signed_cents(net * multiplier * close_qty)
    elif not out["same_count"] and out["proceeds"] is not None and out["cost"] is not None:
        out["net_usd"] = round(out["cost"] - out["proceeds"], 2)
    if out["net_usd"] is not None and out["at_risk_before"] is not None:
        out["at_risk_after"] = round(out["at_risk_before"] + out["net_usd"], 2)
    if cost_per_contract is not None and cost_per_contract > 0:
        out["basis_before"] = cents(cost_per_contract * close_qty)
        if out["net_usd"] is not None:
            out["in_trade_after"] = round(out["basis_before"] + out["net_usd"], 2)
            if out["in_trade_after"] < 0:  # at exactly 0 the new strike is the whole trade's break-even
                out["ahead"] = True
            else:
                out["trade_breakeven"] = round(new_strike + sign * out["in_trade_after"] / (multiplier * open_qty), 4)
    return out


def roll_label(symbol: str, kind: str, old_strike: float, old_expiry: date, new_strike: float, new_expiry: date) -> str:
    """"NBIS 100C Nov 21 → 105C Dec 19"."""
    k = "C" if kind == "call" else "P"
    return f"{symbol} {old_strike:g}{k} {old_expiry:%b} {old_expiry.day} → {new_strike:g}{k} {new_expiry:%b} {new_expiry.day}"


def sentence(symbol: str, kind: str, old_strike: float, old_expiry: date, new_strike: float, new_expiry: date, f: dict) -> str | None:
    """The roll in one plain line: "Roll NBIS 100C Nov 21 → 105C Dec 19: pay $1.40 a share more ($140), break-even
    110.40, 28 more days." None without a net."""
    if f["net"] is None and f["net_usd"] is None:
        return None
    head = f"Roll {roll_label(symbol, kind, old_strike, old_expiry, new_strike, new_expiry)}: "
    usd = f["net_usd"]
    dollars = f" (${abs(usd):,.2f})" if usd is not None else ""
    if f["net"] is not None and f["net_type"] == "debit":
        money = f"pay ${f['net']:.2f} a share more{dollars}"
    elif f["net"] is not None and f["net_type"] == "credit":
        money = f"take in ${f['net']:.2f} a share{dollars}"
    elif f["net"] is not None:
        money = "even money"
    else:
        money = f"pay ${usd:,.2f} more in all" if usd > 0 else f"take in ${-usd:,.2f} in all" if usd < 0 else "even money"
    parts = [money]
    if f["breakeven"] is not None:
        parts.append(f"break-even {f['breakeven']:.2f}")
    days = f["days_added"]
    parts.append(f"{days} more day{'s' if days != 1 else ''}" if days > 0 else "same expiry" if days == 0
                 else f"{-days} fewer day{'s' if days != -1 else ''}")
    return head + ", ".join(parts) + "."


def copy_text(symbol: str, kind: str, old_strike: float, old_expiry: date, new_strike: float, new_expiry: date, *,
              close_qty: int, open_qty: int, net: float | None, net_type_: str | None,
              close_limit: float | None = None, open_limit: float | None = None) -> str:
    """What Copy all puts on the clipboard. Same count: Robinhood's roll screen (the close leg, the open leg, the net
    limit as a debit or credit, the quantity). Different counts: two orders, in order, the close first."""
    old, new = label(symbol, old_strike, old_expiry, kind), label(symbol, new_strike, new_expiry, kind)
    if close_qty == open_qty:
        price = f"{net:.2f} {net_type_}" if net is not None and net_type_ else "(set it)"
        return "\n".join([f"{symbol} · Roll", f"Leg 1: Sell to close · {old}", f"Leg 2: Buy to open · {new}",
                          f"Limit price {price}", f"Quantity {close_qty}"])
    money = lambda p: f"{p:.2f}" if p is not None else "(set it)"  # noqa: E731
    return "\n".join([f"Order 1 of 2 · {symbol} · Sell to close · {old}", f"Limit price {money(close_limit)}", f"Contracts {close_qty}",
                      "", f"Order 2 of 2 · {symbol} · Buy to open · {new}", f"Limit price {money(open_limit)}", f"Contracts {open_qty}"])


# --- the read --------------------------------------------------------------------------------------------------------

def _live_pair(symbol: str, old_expiry: date, new_expiry: date) -> dict:
    """Both expiries' chains in one paced pass of the options feed, and the stock's price."""
    from app.engine import copilot_plans
    from app.engine.options_feed import options_feed
    last, at, issue = copilot_plans._quotes([symbol])
    out = {"spot": last.get(symbol), "spot_at": at, "spot_issue": issue, "simulated": False, "chains": {}, "fetched": {}}
    try:
        reads, problem = options_feed.chains(symbol, lambda live: [d for d in (old_expiry, new_expiry) if d in live])
    except ValueError:
        return {**out, "issue": f"{symbol} is not an optionable symbol."}
    for read in reads:
        out["chains"][read.value.expiration] = read.value
        out["fetched"][read.value.expiration] = read.fetched
    return {**out, "issue": problem}


def _fixture_pair(symbol: str, old_expiry: date, new_expiry: date) -> dict:
    """SIMULATED: the copilot fixture's NBIS chains at its fixed price and time (``copilot_fixture``)."""
    from app.ai.copilot_fixture import AT, SESSION, simulated_chains
    at = _epoch(AT)
    chains = simulated_chains("NBIS", 94.35, date.fromisoformat(SESSION)) if symbol == "NBIS" else {}
    wanted = {d: chains[d] for d in (old_expiry, new_expiry) if d in chains}
    return {"spot": 94.35 if symbol == "NBIS" else None, "spot_at": at, "simulated": True, "chains": wanted,
            "fetched": {d: at for d in wanted}, "spot_issue": "The fixture has a simulated NBIS chain only.",
            "issue": None if wanted else "The fixture has no simulated chain for this contract."}


def _leg(read: dict, symbol: str, kind: str, strike: float, expiry: date, now: float) -> tuple[dict, object]:
    chain = read["chains"].get(expiry)
    if chain is None:
        listed = f"{expiry:%b} {expiry.day}, {expiry.year} is not a listed {symbol} expiry, or its chain could not be read."
        return {"state": "missing", "reason": read.get("issue") or listed}, None
    contract = _find(chain, strike, kind, symbol)
    return contract_quote(contract, read["fetched"].get(expiry), now, read.get("simulated", False)), contract


def build(symbol: str, kind: str, old_strike: float, old_expiry: date, held: int, new_strike: float, new_expiry: date, *,
          close_qty: int | None = None, open_qty: int | None = None, cost_per_contract: float | None = None,
          mode: str = "live", now: float | None = None,
          pair_read: Callable[[str, date, date], dict] | None = None) -> dict:
    """The roll ticket: each leg's quote, the net at the mid and at the natural price (sell the held contract at its bid,
    buy the new one at its ask: the worst fill), and ``roll_figures`` at the mids for the counts given (all held by
    default; the new count follows the closed one). Raises ``RollError`` for a roll this build does not price."""
    from app.engine.desk_chain import WIDE_PCT
    now = time.time() if now is None else now
    if kind not in ("call", "put"):
        raise RollError("Only a long call or put rolls on the ticket in this build.")
    if not isinstance(held, int) or held <= 0:
        raise RollError("The book shows no whole number of contracts held, so there is nothing to roll.")
    close_qty = held if close_qty is None else close_qty
    open_qty = close_qty if open_qty is None else open_qty
    if close_qty <= 0 or open_qty <= 0:
        raise RollError("A roll closes and opens at least one contract.")
    if close_qty > held:
        raise RollError(f"You hold {held}; a roll can close at most that many.")
    if abs(new_strike - old_strike) < 1e-9 and new_expiry == old_expiry:
        raise RollError("That is the contract you hold. Pick another strike or expiry to roll to.")
    if mode == "replay":
        raise RollError("Replay reads no live quotes, so there is no roll to price.")
    read = (pair_read or (_fixture_pair if mode == "fixture" else _live_pair))(symbol, old_expiry, new_expiry)
    legs, listed, rough = [], [], []
    for role, strike, expiry in (("close", old_strike, old_expiry), ("open", new_strike, new_expiry)):
        quote, contract = _leg(read, symbol, kind, strike, expiry, now)
        wide = quote["state"] == "ok" and quote.get("spread_pct") is not None and quote["spread_pct"] >= WIDE_PCT
        legs.append({"role": role, "action": "sell_to_close" if role == "close" else "buy_to_open", "strike": strike,
                     "expiry": expiry.isoformat(), "label": label(symbol, strike, expiry, kind), "quote": quote, "wide": wide})
        listed.append(contract)
        name = "the contract you hold" if role == "close" else "the new contract"
        if quote["state"] != "ok":
            rough.append(f"{name} has {'a stale quote' if quote['state'] == 'stale' else 'no usable quote'}")
        elif wide:
            rough.append(f"{name}'s market is wide ({quote['spread_pct']:g}% of its mid)")
    multipliers = {c.multiplier for c in listed if c is not None and c.multiplier}
    multiplier = next(iter(multipliers)) if len(multipliers) == 1 else None
    if len(multipliers) > 1:
        rough.append("the two contracts have different multipliers (an adjusted contract), so no dollar figures")
    close_q, open_q = legs[0]["quote"], legs[1]["quote"]
    both = close_q["state"] == "ok" and open_q["state"] == "ok"
    # Each leg at its mid to the cent, and the net as their difference, so proceeds + net = cost to the cent.
    close_mid = cents((close_q["bid"] + close_q["ask"]) / 2) if close_q["state"] == "ok" else None
    open_mid = cents((open_q["bid"] + open_q["ask"]) / 2) if open_q["state"] == "ok" else None
    net_mid = round(open_mid - close_mid, 2) if both else None  # + paid
    net_natural = signed_cents(open_q["ask"] - close_q["bid"]) if both else None  # sell at the bid, buy at the ask
    stock = underlying({"spot": read.get("spot"), "spot_at": read.get("spot_at"), "spot_issue": read.get("spot_issue"),
                        "simulated": read.get("simulated", False)}, now)
    f = roll_figures(kind, old_strike, new_strike, old_expiry, new_expiry, close_qty=close_qty, open_qty=open_qty,
                     multiplier=multiplier, close_price=close_mid, open_price=open_mid,
                     net=net_mid if close_qty == open_qty else None, cost_per_contract=cost_per_contract,
                     spot=stock.get("last"))
    return {"state": "ok", "symbol": symbol, "kind": kind, "simulated": read.get("simulated", False), "held": held,
            "close_qty": close_qty, "open_qty": open_qty, "kept": held - close_qty, "multiplier": multiplier,
            "cost_per_contract": cost_per_contract, "legs": legs, "rough": rough,
            "label": roll_label(symbol, kind, old_strike, old_expiry, new_strike, new_expiry),
            "net_mid": None if net_mid is None else round(abs(net_mid), 2), "net_mid_type": net_type(net_mid),
            "net_natural": None if net_natural is None else round(abs(net_natural), 2), "net_natural_type": net_type(net_natural),
            "underlying": stock, "figures": f,
            "sentence": sentence(symbol, kind, old_strike, old_expiry, new_strike, new_expiry, f) if both else None,
            "copy": copy_text(symbol, kind, old_strike, old_expiry, new_strike, new_expiry, close_qty=close_qty, open_qty=open_qty,
                              net=f["net"] if both else None, net_type_=f["net_type"] if both else None,
                              close_limit=close_mid, open_limit=open_mid),
            "close_mid": close_mid, "open_mid": open_mid}
