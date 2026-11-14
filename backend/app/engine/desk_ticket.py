"""The desk's Ticket (docs/copilot-lab.md § Ticket): one saved plan's order fields, to copy into Robinhood by hand.

Copy only. Nothing here places, sends, previews or stages an order, and nothing calls a broker or the Robinhood
connection: it reads the journal (the plan and its account) and the option chain the copilot already reads, and does
arithmetic. A ticket exists only for a saved plan: a confirmed plan on the Plans board (``copilot_plans``; a plan card's
Confirm, a Radar setup's Plan it, a checked call's plan all save one) that has its pre-trade plan capture, is still
armed and is not yet entered (its board ``position`` is ``waiting``). Anything else has no ticket.

``armed`` lists those plans, newest first. ``build`` is one plan's ticket: the contract (the capture's own strike and
expiry, else read from the plan's "Contract: …" words; a contract the words do not state plainly is not named, never
guessed), else up to ``CANDIDATES`` real contracts from the option-candidates read for him to pick; the quantity from
the capture or the plan's size note (a count, else a risk in dollars at the default limit), else none; the contract's
live bid, ask and mid with their quote time (``stale`` or ``missing`` carries no number); the default limit (the mid,
only from a fresh quote); cost, the most he can lose (the premium: a long option only) and break-even with the move it
needs against the expiry's expected move (``figures``); and the accounts the switch offers, by journal label with the
number masked to its last four.

A two-leg vertical spread (same symbol, expiry and type; one leg bought, one sold) is a ticket too: from the Chain tab's
Make it a spread (``pick`` with ``short_strike``) or from plan words that state one plainly (``read_spread``). Both legs'
quotes come from the one chain read a single contract's ticket makes; the net debit or credit at the mid and at the
natural price, the most it can lose and make, break-even and its worth at expiry at the plan's levels are arithmetic
(``spread_figures``). Straddles, strangles, condors, butterflies, rolls and calendars stay refused as before.
"""
from __future__ import annotations

import calendar
from datetime import UTC, date, datetime
import math
import re
import time
from typing import Callable

from sqlmodel import Session, select

from app.engine import copilot_plans, play_check

CANDIDATES = 3
QUOTE_STALE_S = 15 * 60  # a contract whose bid or ask is older than this reads stale
READ_STALE_S = 5 * 60  # a chain or price read older than this reads stale
HORIZON_DAYS = {"day": 2, "swing": 7, "long": 30}  # the candidates' horizon from the symbol's horizon, without a time stop
SIDES = {"buy_calls": "call", "buy_puts": "put"}  # the long options a ticket covers
MONTHS = {name.lower(): i for i, name in enumerate(calendar.month_abbr) if name}


class TicketError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code  # no_plan | entered


# --- the arithmetic --------------------------------------------------------------------------------------------------

def figures(option_type: str, strike: float, limit: float | None, contracts: int | None, multiplier: int | None,
            spot: float | None, expected_move_pct: float | None = None) -> dict:
    """Cost, the most he can lose and break-even for a long call or put bought at ``limit``. The most a long option can
    lose is what it cost: the premium. Break-even at expiry is the strike plus the premium for a call, minus it for a
    put; ``move_pct`` is how far the underlying must go from ``spot`` to get there, and ``vs_expected`` that move over
    the expiry's expected move. Anything the inputs do not give is None."""
    out = {"cost": None, "max_loss": None, "breakeven": None, "move_pct": None, "vs_expected": None}
    if limit is None or not limit > 0:
        return out
    if contracts and contracts > 0 and multiplier:
        out["cost"] = out["max_loss"] = round(limit * multiplier * contracts, 2)
    out["breakeven"] = round(strike + limit if option_type == "call" else strike - limit, 4)
    if spot and spot > 0:
        out["move_pct"] = round((out["breakeven"] - spot) / spot * 100, 2)
        if expected_move_pct and expected_move_pct > 0:
            out["vs_expected"] = round(abs(out["move_pct"]) / expected_move_pct, 1)
    return out


def contracts_for_risk(risk_usd: float | None, limit: float | None, multiplier: int | None) -> int | None:
    """Whole contracts whose premium (all at risk on a long option) stays within ``risk_usd``; None when it buys none."""
    if not risk_usd or not limit or not multiplier or limit <= 0:
        return None
    count = math.floor(risk_usd / (limit * multiplier) + 1e-9)
    return count or None


# --- a two-leg vertical spread ---------------------------------------------------------------------------------------
# One long leg (bought) and one short leg (sold): same symbol, same expiry, same type, two strikes. Prices are per share
# like a single option's; the ticket's limit is the net price as a positive number, a debit (paid) or a credit (taken
# in) by the strikes: a call spread that buys the lower strike, or a put spread that buys the higher, is a debit.

def is_debit(kind: str, long_strike: float, short_strike: float) -> bool:
    """Whether buying ``long_strike`` and selling ``short_strike`` costs money: the long leg is the one nearer the money."""
    return long_strike < short_strike if kind == "call" else long_strike > short_strike


def cents(value: float) -> float:
    """To the cent, a half cent up, as ``lib/spreadTicket.ts`` rounds, so the Chain tab and the ticket show one net."""
    return math.floor(value * 100 + 0.5 + 1e-9) / 100


def spread_value(kind: str, long_strike: float, short_strike: float, price: float) -> float:
    """What one spread is worth per share at expiry with the stock at ``price``, signed: the long leg's intrinsic value
    minus the short leg's. A debit spread's is from 0 to the width; a credit spread's from minus the width to 0."""
    payoff = (lambda k: max(price - k, 0.0)) if kind == "call" else (lambda k: max(k - price, 0.0))
    return payoff(long_strike) - payoff(short_strike)


def spread_figures(kind: str, long_strike: float, short_strike: float, limit: float | None, contracts: int | None,
                   multiplier: int | None, spot: float | None, expected_move_pct: float | None = None,
                   levels: dict[str, float | None] | None = None) -> dict:
    """A vertical at the net ``limit`` (per share, positive). Debit: he pays the limit; the most he can lose is what he
    paid and the most he can make is the width less it. Credit: he takes in the limit; the most he can make is that and
    the most he can lose is the width less it. Dollars are ×``multiplier``×``contracts`` (None without a count).
    Break-even at expiry: a call spread's lower strike plus the limit, a put spread's higher strike less it, debit or
    credit alike. A limit at or over the width gives no figures and says why. ``at_levels``: for each plan level (the
    stock's price), the spread's worth at expiry (what it sells for, or what buying a credit spread back costs) and the
    profit or loss then."""
    width = abs(short_strike - long_strike)
    debit = is_debit(kind, long_strike, short_strike)
    out = {"type": "debit" if debit else "credit", "width": round(width, 4), "cost": None, "credit": None, "max_loss": None,
           "max_gain": None, "breakeven": None, "move_pct": None, "vs_expected": None, "at_levels": [], "warning": None}
    if limit is None or not limit > 0 or not width > 0:
        return out
    if limit >= width - 1e-9:
        out["warning"] = (f"A {limit:g} debit is the {width:g} width or more: the spread can never be worth more than you pay."
                          if debit else f"A {limit:g} credit is the {width:g} width or more: no real market pays that. Check the price.")
        return out
    per = multiplier * contracts if contracts and contracts > 0 and multiplier else None
    if per:
        paid_or_taken = cents(limit * per)
        other = cents((width - limit) * per)
        if debit:
            out.update(cost=paid_or_taken, max_loss=paid_or_taken, max_gain=other)
        else:
            out.update(credit=paid_or_taken, max_gain=paid_or_taken, max_loss=other)
    low, high = sorted((long_strike, short_strike))
    out["breakeven"] = round(low + limit if kind == "call" else high - limit, 4)
    if spot and spot > 0:
        out["move_pct"] = round((out["breakeven"] - spot) / spot * 100, 2)
        if expected_move_pct and expected_move_pct > 0:
            out["vs_expected"] = round(abs(out["move_pct"]) / expected_move_pct, 1)
    net = limit if debit else -limit  # what he pays per share, signed: a credit is money in
    for role, price in (levels or {}).items():
        if price is None or not price > 0:
            continue
        value = spread_value(kind, long_strike, short_strike, price)
        out["at_levels"].append({"role": role, "price": price, "worth": round(abs(value), 4),
                                 "pnl": cents((value - net) * per) if per else None})
    return out


def spreads_for_risk(risk_usd: float | None, type_: str, limit: float | None, width: float, multiplier: int | None) -> int | None:
    """Whole spreads whose most-to-lose stays within ``risk_usd``: the debit paid, or the width less the credit."""
    if not risk_usd or not limit or not multiplier or limit <= 0 or limit >= width:
        return None
    each = (limit if type_ == "debit" else width - limit) * multiplier
    count = math.floor(risk_usd / each + 1e-9)
    return count or None


def spread_label(symbol: str, kind: str, long_strike: float, short_strike: float, expiry: date) -> str:
    """As Robinhood names a vertical: "NBIS $100/$110 Call Debit Spread 12/19/26", the strikes low to high."""
    low, high = sorted((long_strike, short_strike))
    type_ = "Debit" if is_debit(kind, long_strike, short_strike) else "Credit"
    return f"{symbol} ${low:g}/${high:g} {kind.title()} {type_} Spread {expiry.month}/{expiry.day}/{expiry.year % 100:02d}"


def spread_bullish(kind: str, long_strike: float, short_strike: float) -> bool:
    """A debit call spread and a credit put spread gain as the stock rises; the other two as it falls."""
    return is_debit(kind, long_strike, short_strike) == (kind == "call")


# --- reading the plan ------------------------------------------------------------------------------------------------

_STRIKE = re.compile(r"\$?(\d+(?:\.\d+)?)\s?(C|P|calls?|puts?)\b", re.I)
_SLASH = re.compile(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{4}|\d{2}))?\b")
_MONTH_WORDS = r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?"
# A month word as itself, the day, and a year only when it is marked as one: "'26" or a four-digit year.
_MONTH = re.compile(r"\b(" + _MONTH_WORDS + r")\.?\s+(\d{1,2})\b(?:\s*'(\d{2})\b|,?\s+(\d{4})\b)?", re.I)
# More than one leg (a strike range, two strikes, a spread): not one contract.
_LEGS = re.compile(r"\bspreads?\b|\bverticals?\b|\bstraddles?\b|\bstrangles?\b|\bcondors?\b|\bbutterfl(?:y|ies)\b|\brolls?\b"
                   r"|\d(?:\.\d+)?\s*-\s*\$?\d|\b\d+(?:\.\d+)?\s*/\s*\d+(?:\.\d+)?\s*(?:C|P|calls?|puts?)\b", re.I)


def _year(text: str | None, month: int, day: int, since: date) -> date | None:
    try:
        if text:
            year = int(text)
            return date(year + 2000 if year < 100 else year, month, day)
        found = date(since.year, month, day)
        return found if found >= since else date(since.year + 1, month, day)
    except ValueError:
        return None


def read_contract(text: str | None, since: date) -> tuple[float, date, str] | None:
    """``(strike, expiry, "call"|"put")`` when the plan's contract words state all three plainly ("NBIS 11/14 105C",
    "Nov 14 '26 105C", "100C Oct 24"); a missing year is the next such date on or after ``since``. None otherwise."""
    if not text or _LEGS.search(text):
        return None
    strikes = {(float(m.group(1)), "call" if m.group(2)[0].lower() == "c" else "put") for m in _STRIKE.finditer(text)}
    dates = {d for m in _SLASH.finditer(text) if (d := _year(m.group(3), int(m.group(1)), int(m.group(2)), since))}
    dates |= {d for m in _MONTH.finditer(text) if (d := _year(m.group(3) or m.group(4), MONTHS[m.group(1).lower()[:3]], int(m.group(2)), since))}
    if len(strikes) != 1 or len(dates) != 1:
        return None  # none, or more than one: not stated plainly
    (strike, kind), = strikes
    return strike, dates.pop(), kind


# A vertical: two strikes with a slash ("100/110C", "$100/$110 Call", "95P/90P"), or a dash when the words also say
# spread or vertical ("105-110 call spread"), then the type.
_PAIR = re.compile(r"\$?(\d+(?:\.\d+)?)\s*([CP]\b)?\s*(/|-)\s*\$?(\d+(?:\.\d+)?)\s*(C|P|calls?|puts?)\b", re.I)
_SPREAD_WORD = re.compile(r"\bspreads?\b|\bverticals?\b", re.I)
_NOT_VERTICAL = re.compile(r"\bstraddles?\b|\bstrangles?\b|\bcondors?\b|\bbutterfl(?:y|ies)\b|\brolls?\b|\bcalendars?\b"
                           r"|\bdiagonals?\b|\biron\b|\bratio\b|\bflys?\b", re.I)


def read_spread(text: str | None, since: date) -> dict | None:
    """A same-expiry two-leg vertical when the plan's words state it plainly: one strike pair, one type, one date
    ("NBIS 12/19 100/110C", "100/110 call spread Dec 19", "Dec 19 '26 95/90 put credit spread"). A debit spread unless
    the words say credit; which strike is bought follows from that (a debit buys the strike nearer the money). Straddles,
    strangles, condors, butterflies, rolls, calendars and anything vaguer: None."""
    if not text or _NOT_VERTICAL.search(text):
        return None
    pairs = list(_PAIR.finditer(text))
    if len(pairs) != 1:
        return None
    pair = pairs[0]
    if re.search(r"[/-]\s*\$?$", text[:pair.start()]) or re.match(r"\s*[CP]?\s*[/-]", text[pair.end():], re.I):
        return None  # a third strike chained on ("100/110/120C"): not a vertical
    if pair.group(3) == "-" and not _SPREAD_WORD.search(text):
        return None  # "105-110 calls" may be a range of single strikes; only "spread" makes it two legs
    a, b = float(pair.group(1)), float(pair.group(4))
    if a == b or not a > 0 or not b > 0:
        return None
    kind = "call" if pair.group(5)[0].lower() == "c" else "put"
    if pair.group(2) and pair.group(2).lower() != pair.group(5)[0].lower():
        return None  # a call and a put ("100C/110P"): a strangle or a risk reversal, not a vertical
    rest = text[:pair.start()] + " | " + text[pair.end():]
    if _STRIKE.search(rest):
        return None  # another strike besides the pair: more than two legs
    dates = {d for m in _SLASH.finditer(rest) if (d := _year(m.group(3), int(m.group(1)), int(m.group(2)), since))}
    dates |= {d for m in _MONTH.finditer(rest) if (d := _year(m.group(3) or m.group(4), MONTHS[m.group(1).lower()[:3]], int(m.group(2)), since))}
    if len(dates) != 1:
        return None
    credit = bool(re.search(r"\bcredit\b", text, re.I))
    low, high = sorted((a, b))
    near, far = (low, high) if kind == "call" else (high, low)  # the strike nearer the money first
    long_strike, short_strike = (far, near) if credit else (near, far)
    return {"kind": kind, "expiry": dates.pop(), "long": long_strike, "short": short_strike}


def _contract_words(note: str | None) -> str | None:
    found = re.search(r"Contract: (.+?)\.(?:\s|$)", note or "")
    return found.group(1).strip() if found else None


def read_size(wording: str | None, quantity: float | None) -> dict:
    """The plan's size: the capture's quantity, else the count or the risk in its "Size: …" words; the words as said."""
    said = re.search(r"Size: (.+?)\.(?:\s|$)", wording or "")
    text = said.group(1).strip() if said else None
    count = int(quantity) if quantity and quantity > 0 and float(quantity).is_integer() else None
    if count is None and text and (m := re.search(r"(?<![\d.\-/])\b(\d+)\s+contracts?\b", text, re.I)) \
            and not re.search(r"\d\s*(?:-|to|or)\s*\d+\s+contracts?\b", text, re.I):  # "1-2 contracts" is no one count
        count = int(m.group(1)) or None
    risk = None
    if text and (m := re.search(r"risk \$?([\d,]+(?:\.\d+)?)", text, re.I)):
        risk = float(m.group(1).replace(",", "")) or None
    return {"contracts": count, "risk_usd": risk, "text": text}


def label(symbol: str, strike: float, expiry: date, kind: str) -> str:
    """As Robinhood names an option: "NBIS $105 Call 11/14/26"."""
    return f"{symbol} ${strike:g} {kind.title()} {expiry.month}/{expiry.day}/{expiry.year % 100:02d}"


# --- accounts --------------------------------------------------------------------------------------------------------

def _kind(account) -> str:
    if "mcp" in (account.name or "").lower():
        return "mcp"
    return "roth" if account.type == "roth_ira" else "other"


def _account(account) -> dict:
    return {"id": str(account.id), "label": account.name, "last4": account.last4[-4:] if account.last4 else None,
            "kind": _kind(account)}


def accounts(db: Session, plan_account_id) -> tuple[list[dict], str | None]:
    """The switch: the plan's journal account, the Roth IRA and the MCP account (Webull stays out); and the selected id.
    An MCP account not yet in the journal (no fill has named it) still shows, with no number."""
    from sqlalchemy import or_
    from app.models import Account
    rows = db.exec(select(Account).where(or_(Account.broker.is_(None), Account.broker != "webull")).order_by(Account.name)).all()
    out = [_account(a) for a in rows if a.id == plan_account_id or _kind(a) in ("roth", "mcp")]
    out.sort(key=lambda a: (a["id"] != str(plan_account_id), ("roth", "mcp", "other").index(a["kind"]), a["label"]))
    if not any(a["kind"] == "mcp" for a in out):
        out.append({"id": "mcp", "label": "MCP", "last4": None, "kind": "mcp"})
    selected = str(plan_account_id) if any(a["id"] == str(plan_account_id) for a in out) else (out[0]["id"] if out else None)
    return out, selected


# --- quotes ----------------------------------------------------------------------------------------------------------

def _epoch(moment) -> float | None:
    if moment is None:
        return None
    if isinstance(moment, (int, float)):
        return float(moment)
    if isinstance(moment, str):
        moment = datetime.fromisoformat(moment.replace("Z", "+00:00"))
    return (moment if moment.tzinfo else moment.replace(tzinfo=UTC)).timestamp()


def contract_quote(contract, fetched: float | None, now: float, simulated: bool) -> dict:
    """The contract's bid, ask and mid with their quote time; ``stale`` or ``missing`` (with why) carries no number."""
    if contract is None:
        return {"state": "missing", "reason": "The option chain has no quote for this contract."}
    stamps = [_epoch(contract.bid_time), _epoch(contract.ask_time)]
    # The older of bid and ask: both must be fresh, and a side with no time is not (``options_implied``'s rule).
    quoted = None if None in stamps else min(stamps)
    base = {"as_of": quoted if quoted is not None else (fetched if simulated else None), "read_at": fetched, "simulated": simulated, "multiplier": contract.multiplier}
    if contract.bid is None or contract.ask is None or not contract.ask > 0 or not 0 <= contract.bid <= contract.ask:
        return {**base, "state": "missing", "reason": "No usable bid and ask for this contract."}
    if not simulated and (quoted is None or fetched is None or now - quoted > QUOTE_STALE_S or now - fetched > READ_STALE_S):
        return {**base, "state": "stale", "reason": "The latest bid and ask are too old to price an order from."}
    mid = (contract.bid + contract.ask) / 2
    return {**base, "state": "ok", "bid": round(contract.bid, 4), "ask": round(contract.ask, 4), "mid": round(mid, 2),
            "spread": round(contract.ask - contract.bid, 4), "spread_pct": round((contract.ask - contract.bid) / mid * 100, 1) if mid else None}


def underlying(read: dict, now: float) -> dict:
    last, at = read.get("spot"), read.get("spot_at")
    if not isinstance(last, (int, float)) or not last > 0:
        return {"state": "missing", "reason": read.get("spot_issue") or "No current price for the stock."}
    if not read.get("simulated") and (at is None or now - at > READ_STALE_S):
        return {"state": "stale", "as_of": at, "reason": "The stock's latest price is too old."}
    return {"state": "ok", "last": round(float(last), 4), "as_of": at}


def _live_chain(symbol: str, expiry: date) -> dict:
    """The live read: the stock's price from the quote service and the expiry's chain from the options feed's cache."""
    from app.engine.chart_math import ET
    from app.engine.expression_recorder import later_expiration
    from app.engine.options_feed import options_feed
    last, at, issue = copilot_plans._quotes([symbol])
    out = {"spot": last.get(symbol), "spot_at": at, "spot_issue": issue, "simulated": False, "chain": None, "fetched": None,
           "later": None, "later_fetched": None}
    today = datetime.now(ET).date()

    def pick(live: list[date]) -> list[date]:  # the contract's expiry, and the Play check's later expiry in the same pass
        if expiry not in live:
            return []
        later = later_expiration(live, expiry, today)
        return [expiry] + ([later] if later else [])

    try:
        reads, problem = options_feed.chains(symbol, pick)
    except ValueError:
        return {**out, "issue": f"{symbol} is not an optionable symbol."}
    read = next((r for r in reads if r.value.expiration == expiry), None)
    if read is None:
        return {**out, "issue": problem or f"{expiry:%b} {expiry.day}, {expiry.year} is not a listed {symbol} expiry."}
    later = next((r for r in reads if r.value.expiration != expiry), None)
    return {**out, "chain": read.value, "fetched": read.fetched, "issue": None,
            "later": later and later.value, "later_fetched": later and later.fetched}


def _fixture_chain(symbol: str, expiry: date) -> dict:
    """SIMULATED: the copilot fixture's NBIS chain at its fixed price and time (``copilot_fixture``)."""
    from app.ai.copilot_fixture import AT, SESSION, simulated_chains
    from app.engine.expression_recorder import later_expiration
    at = _epoch(AT)
    out = {"spot": 94.35 if symbol == "NBIS" else None, "spot_at": at, "simulated": True, "chain": None, "fetched": at,
           "spot_issue": "The fixture has a simulated NBIS chain only.", "later": None, "later_fetched": at}
    chains = simulated_chains("NBIS", 94.35, date.fromisoformat(SESSION)) if symbol == "NBIS" else {}
    chain = chains.get(expiry)
    later = later_expiration(list(chains), expiry, date.fromisoformat(SESSION)) if chain else None
    return {**out, "chain": chain, "later": chains.get(later), "issue": None if chain else "The fixture has no simulated chain for this contract."}


def _find(chain, strike: float, kind: str, symbol: str):
    from app.engine.options_positioning import primary_root
    if chain is None:
        return None
    root = primary_root(symbol)
    return next((c for c in chain.contracts if c.root == root and c.option_type == kind and abs(c.strike - strike) < 1e-6), None)


# --- the ticket ------------------------------------------------------------------------------------------------------

def _no_quotes(symbols):
    return {}, None, None


def _entered(db: Session, plans: list[dict]) -> set[str]:
    """Plans whose symbol has an open trade opened since the plan, linked or not: the fill arrives by email, often
    later than the linker's window, and a ticket is only for an entry not yet made. Webull stays out."""
    from sqlalchemy import or_
    from app.engine.chart_math import ET
    from app.models import Account, Trade
    if not plans:
        return set()
    trades = db.exec(select(Trade.ticker, Trade.opened_at).join(Account, Account.id == Trade.account_id)
                     .where(Trade.status == "open", Trade.ticker.in_({p["symbol"] for p in plans}))
                     .where(or_(Account.broker.is_(None), Account.broker != "webull"))).all()
    wall = lambda moment: moment.replace(tzinfo=UTC).astimezone(ET).replace(tzinfo=None)  # noqa: E731 -- trades keep New York wall time
    return {p["investigation_id"] for p in plans
            if any(t == p["symbol"] and opened >= wall(p["since"]) for t, opened in trades)}


def armed(db: Session) -> list[dict]:
    """The saved plans a ticket can open: on the board, armed, not yet entered, with a pre-trade plan; newest first."""
    board = copilot_plans.board(db, quotes=_no_quotes)["plans"]
    plans = copilot_plans._plans(db)[0]
    sides = {p["investigation_id"]: p["capture"].side for p in plans if p["capture"] is not None}
    saved = set(sides) - _entered(db, plans)
    rows = [{"investigation_id": p["investigation_id"], "symbol": p["symbol"], "direction": p["direction"],
             "option_type": SIDES.get(sides[p["investigation_id"]]),  # a long call or put; None: no option ticket
             "instrument": p["instrument"], "thesis": p["thesis"], "confirmed_at": p["confirmed_at"],
             "entry": p["entry"] and p["entry"]["price"], "invalidation": p["invalidation"] and p["invalidation"]["price"]}
            for p in board if p["position"] == "waiting" and p["investigation_id"] in saved]
    rows.sort(key=lambda r: r["confirmed_at"], reverse=True)
    return rows


def _plan(db: Session, investigation_id: str) -> tuple[dict, object]:
    row = next((r for r in copilot_plans.board(db, quotes=_no_quotes)["plans"] if r["investigation_id"] == investigation_id), None)
    plan = next((p for p in copilot_plans._plans(db)[0] if p["investigation_id"] == investigation_id), None)
    if row is None or plan is None or plan["capture"] is None:
        raise TicketError("no_plan", "There is no saved plan for this ticket. A ticket opens only from a saved plan.")
    if row["position"] != "waiting" or _entered(db, [plan]):
        raise TicketError("entered", "This plan's position is already open; its ticket is only for an entry not yet made.")
    return row, plan["capture"]


def _horizon_days(db: Session, row: dict, now: float) -> int:
    from app.engine import day_journal
    from app.engine.chart_math import ET
    stop = row.get("time_stop")
    if stop and stop.get("state") == "pending":
        due = datetime.fromtimestamp(stop["due_at"], ET).date()
        return max((due - datetime.fromtimestamp(now, ET).date()).days, 0)
    horizons, _asked = day_journal.check_ins(db)
    return HORIZON_DAYS.get(horizons.get(row["symbol"], "swing"), HORIZON_DAYS["swing"])


def _candidates(read: dict, now: float, simulated: bool) -> dict:
    """Up to ``CANDIDATES`` contracts from the option-candidates read: the expiry first at or after the horizon, its
    strikes nearest the price, by strike. Facts to compare; none is picked."""
    if read.get("state") not in ("ok", "partial") or not read.get("candidates"):
        return {"state": "missing", "rows": [], "reason": read.get("reason") or "No option candidates could be read."}
    expiries = {e["expiry"]: e for e in read.get("expiries", [])}
    first = next((e["expiry"] for e in read.get("expiries", []) if e.get("role") == "first_at_or_after" and not e.get("missing")), None)
    rows = [r for r in read["candidates"] if r["expiry"] == first] or read["candidates"]
    spot = read.get("spot") or 0
    rows = sorted(sorted(rows, key=lambda r: abs(r["strike"] - spot))[:CANDIDATES], key=lambda r: (r["expiry"], r["strike"]))
    as_of = _epoch(read.get("as_of"))
    if not simulated and (as_of is None or now - as_of > READ_STALE_S):
        return {"state": "stale", "as_of": as_of, "reason": "The option chain read is too old to compare premiums.",
                "rows": [{"expiry": r["expiry"], "strike": r["strike"], "type": r["type"], "days": r["days"]} for r in rows]}
    out = []
    for r in rows:
        move = (expiries.get(r["expiry"]) or {}).get("expected_move") or {}
        per = r.get("per_contract")
        out.append({"expiry": r["expiry"], "strike": r["strike"], "type": r["type"], "days": r["days"], "bid": r["bid"],
                    "ask": r["ask"], "mid": r["mid"], "ask_contract": per.get("ask") if isinstance(per, dict) else None,
                    "spread_pct": r["spread_pct"], "breakeven_move_pct": r["breakeven_move_pct"],
                    "expected_move_pct": move.get("move_pct"), "move_needed_vs_expected": r.get("move_needed_vs_expected")})
    return {"state": "ok", "as_of": as_of, "simulated": simulated, "rows": out}


def build(db: Session, investigation_id: str, *, mode: str = "live", now: float | None = None,
          pick: tuple[date, float] | None = None, short_strike: float | None = None, pick_kind: str | None = None,
          chain_read: Callable[[str, date], dict] | None = None,
          candidates_read: Callable[[str, int, str], dict] | None = None) -> dict:
    """One saved plan's ticket. ``pick``: the contract he chose (its expiry and strike), from the ticket's candidates or
    the Chain tab; it replaces the contract the plan names, on the plan's own side. With ``short_strike`` the pick is
    the long leg of a vertical spread (the Chain tab's Make it a spread) of ``pick_kind`` (the plan's side when None)
    that sells ``short_strike`` in the same expiry; the plan's own words naming a vertical give one too (``read_spread``).
    ``mode``: the copilot's evidence (``live``; ``fixture`` reads the simulated chain; ``replay`` reads no quote).
    Raises ``TicketError`` without a saved, armed, not-entered plan."""
    now = time.time() if now is None else now
    row, capture = _plan(db, investigation_id)
    symbol = row["symbol"]
    kind = SIDES.get(capture.side) if capture.instrument == "option" else None
    account_list, selected = accounts(db, capture.account_id)
    size = read_size(capture.wording, capture.quantity)
    words = _contract_words(capture.note)
    out = {"state": "ok", "investigation_id": investigation_id, "symbol": symbol, "direction": row["direction"],
           "thesis": row["thesis"], "confirmed_at": row["confirmed_at"], "option_type": kind,
           "entry": row["entry"] and row["entry"]["price"], "invalidation": row["invalidation"] and row["invalidation"]["price"],
           "target": _target(row),
           "time_stop": row["time_stop"] and row["time_stop"]["text"], "plan_contract_words": words, "size": size,
           "accounts": account_list, "account": selected, "contract": None, "candidates": None, "quote": None,
           "underlying": None, "expected_move_pct": None, "limit": None, "contracts": size["contracts"], "figures": None,
           "spread": None, "simulated": mode == "fixture"}
    if kind is None:
        return {**out, "state": "not_option",
                "reason": "This plan is not a long call or put; the ticket covers single long calls and puts only."}
    if mode == "replay":
        return {**out, "state": "no_quotes", "reason": "Replay reads no live quotes, so there is no ticket to price."}

    since = capture.received_at.replace(tzinfo=UTC).date()
    named = (capture.strike, capture.expiration, kind) if capture.strike and capture.expiration else read_contract(words, since)
    if named and named[2] != kind:
        named = None  # a contract on the other side is not this plan's
    source = "plan" if named else None
    spread = read_spread(words, since) if named is None and not (capture.strike and capture.expiration) else None
    if spread is not None:
        source = "plan"
    if pick is not None:  # his pick (a candidate here, or a contract from the Chain tab) wins; the plan's words still show
        if short_strike is not None and abs(short_strike - pick[1]) > 1e-9:
            named, spread, source = None, {"kind": pick_kind or kind, "expiry": pick[0], "long": pick[1], "short": short_strike}, "picked"
        else:
            named, spread, source = (pick[1], pick[0], kind), None, "picked"
    if spread is not None:
        return _spread_ticket(db, out, row, capture, spread, source, mode=mode, now=now, chain_read=chain_read)
    if named is None:
        read = (candidates_read or _candidates_reader(mode))(symbol, _horizon_days(db, row, now), row["direction"] or ("long" if kind == "call" else "short"))
        found = {**out, "candidates": _candidates(read, now, mode == "fixture")}
        return {**found, "check": play_check.check(db, found, row, account_id=capture.account_id, now=now)}

    strike, expiry, _ = named
    chain = (chain_read or (_fixture_chain if mode == "fixture" else _live_chain))(symbol, expiry)
    contract = _find(chain.get("chain"), strike, kind, symbol)
    quote = contract_quote(contract, chain.get("fetched"), now, chain.get("simulated", False)) if chain.get("chain") is not None \
        else {"state": "missing", "reason": chain.get("issue") or "The option chain could not be read."}
    stock = underlying(chain, now)
    move = None
    if chain.get("chain") is not None and stock["state"] == "ok":
        from app.ai.copilot_options import expected_move
        move = expected_move(chain["chain"], stock["last"]).get("move_pct")
    limit = quote.get("mid") if quote["state"] == "ok" else None
    multiplier = quote.get("multiplier") or (contract.multiplier if contract is not None else None)
    count = size["contracts"] or contracts_for_risk(size["risk_usd"], limit, multiplier)
    found = {**out, "contract": {"strike": strike, "expiry": expiry.isoformat(), "type": kind, "label": label(symbol, strike, expiry, kind),
                                 "source": source, "multiplier": multiplier},
             "quote": quote, "underlying": stock, "expected_move_pct": move, "limit": limit, "contracts": count,
             "figures": figures(kind, strike, limit, count, multiplier, stock.get("last"), move)}

    def quote_for(other, its_chain):  # a contract the check prices, judged as this ticket's own quote is
        fetched = chain.get("later_fetched") if its_chain is chain.get("later") else chain.get("fetched")
        return contract_quote(other, fetched, now, chain.get("simulated", False))

    simulated = chain.get("simulated", False)
    return {**found, "check": play_check.check(db, found, row, account_id=capture.account_id,
                                               now=chain["fetched"] if simulated and chain.get("fetched") else now,
                                               chain_read=chain if chain.get("chain") is not None else None,
                                               traded=contract, quote_for=quote_for)}


def _target(row: dict) -> float | None:
    target = row.get("target")
    return target.get("price") if isinstance(target, dict) else target


def _spread_ticket(db: Session, out: dict, row: dict, capture, spread: dict, source: str, *, mode: str, now: float,
                   chain_read: Callable[[str, date], dict] | None) -> dict:
    """A vertical's ticket: each leg's own quote (bid, ask, mid and time from the one chain read the ticket makes), the
    net price at the mid and at the natural price (buy the long leg at its ask, sell the short leg at its bid: the worst
    fill), the width, and ``spread_figures`` at the default limit, the net mid. A leg that is stale or missing gives no
    net number at all; a wide leg (``desk_chain.WIDE_PCT``) gives one, said to be rough."""
    from app.engine.desk_chain import WIDE_PCT
    symbol, kind, expiry = out["symbol"], spread["kind"], spread["expiry"]
    long_strike, short_strike = spread["long"], spread["short"]
    chain = (chain_read or (_fixture_chain if mode == "fixture" else _live_chain))(symbol, expiry)
    have = chain.get("chain") is not None
    simulated = chain.get("simulated", False)
    debit = is_debit(kind, long_strike, short_strike)
    width = abs(short_strike - long_strike)
    legs, listed, rough = [], [], []
    for role, strike in (("long", long_strike), ("short", short_strike)):
        contract = _find(chain.get("chain"), strike, kind, symbol)
        quote = contract_quote(contract, chain.get("fetched"), now, simulated) if have \
            else {"state": "missing", "reason": chain.get("issue") or "The option chain could not be read."}
        wide = quote["state"] == "ok" and quote.get("spread_pct") is not None and quote["spread_pct"] >= WIDE_PCT
        legs.append({"role": role, "action": "buy" if role == "long" else "sell", "strike": strike,
                     "label": label(symbol, strike, expiry, kind), "quote": quote, "wide": wide})
        listed.append(contract)
        name = f"the ${strike:g} leg"
        if quote["state"] != "ok":
            rough.append(f"{name} has {'a stale quote' if quote['state'] == 'stale' else 'no usable quote'}")
        elif wide:
            rough.append(f"{name}'s market is wide ({quote['spread_pct']:g}% of its mid)")
    multipliers = {c.multiplier for c in listed if c is not None and c.multiplier}
    multiplier = next(iter(multipliers)) if len(multipliers) == 1 else None
    if len(multipliers) > 1:
        rough.append("the two legs have different multipliers (an adjusted contract), so no dollar figures")
    stock = underlying(chain, now)
    move = None
    if have and stock["state"] == "ok":
        from app.ai.copilot_options import expected_move
        move = expected_move(chain["chain"], stock["last"]).get("move_pct")
    net_mid = net_natural = None
    long_q, short_q = legs[0]["quote"], legs[1]["quote"]
    if long_q["state"] == "ok" and short_q["state"] == "ok":
        paid_mid = (long_q["bid"] + long_q["ask"]) / 2 - (short_q["bid"] + short_q["ask"]) / 2  # per share, signed: + is paid
        paid_natural = long_q["ask"] - short_q["bid"]  # buy at the ask, sell at the bid
        net_mid = cents(paid_mid if debit else -paid_mid)
        net_natural = cents(paid_natural if debit else -paid_natural)
    limit = net_mid if net_mid is not None and 0 < net_mid < width and multiplier else None
    if net_mid is not None and limit is None and multiplier:
        rough.append(f"the quotes put the net mid at {net_mid:.2f}, outside 0 to the {width:g} width")
    type_ = "debit" if debit else "credit"
    count = out["size"]["contracts"] or spreads_for_risk(out["size"]["risk_usd"], type_, limit, width, multiplier)
    bullish = spread_bullish(kind, long_strike, short_strike)
    against = row["direction"] in ("long", "short") and (row["direction"] == "long") != bullish
    levels = {"entry": out["entry"], "target": out["target"], "stop": out["invalidation"]}
    found = {**out, "option_type": kind, "underlying": stock, "expected_move_pct": move, "limit": limit, "contracts": count,
             "spread": {"kind": kind, "expiry": expiry.isoformat(), "type": type_, "width": round(width, 4),
                        "long": long_strike, "short": short_strike, "label": spread_label(symbol, kind, long_strike, short_strike, expiry),
                        "source": source, "multiplier": multiplier, "legs": legs, "net_mid": net_mid, "net_natural": net_natural,
                        "rough": rough, "bullish": bullish,
                        "against_plan": (f"This {type_} {kind} spread gains as {symbol} {'rises' if bullish else 'falls'}; "
                                         f"your plan is {row['direction']}.") if against else None},
             "figures": spread_figures(kind, long_strike, short_strike, limit, count, multiplier, stock.get("last"), move, levels)}

    def quote_for(other, its_chain):
        return contract_quote(other, chain.get("fetched"), now, simulated)

    return {**found, "check": play_check.check(db, found, row, account_id=capture.account_id,
                                               now=chain["fetched"] if simulated and chain.get("fetched") else now,
                                               chain_read=chain if have else None, traded=tuple(listed), quote_for=quote_for)}


def _candidates_reader(mode: str) -> Callable[[str, int, str], dict]:
    if mode == "fixture":
        from app.ai.copilot_fixture import FixtureEvidence
        return lambda symbol, days, direction: FixtureEvidence().get_option_candidates(symbol, days, direction)
    from app.ai import copilot_options
    return copilot_options.live_candidates
