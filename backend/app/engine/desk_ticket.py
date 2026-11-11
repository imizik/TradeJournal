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
"""
from __future__ import annotations

import calendar
from datetime import UTC, date, datetime
import math
import re
import time
from typing import Callable

from sqlmodel import Session, select

from app.engine import copilot_plans

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
    from app.engine.options_feed import options_feed
    last, at, issue = copilot_plans._quotes([symbol])
    out = {"spot": last.get(symbol), "spot_at": at, "spot_issue": issue, "simulated": False, "chain": None, "fetched": None}
    try:
        reads, problem = options_feed.chains(symbol, lambda live: [expiry] if expiry in live else [])
    except ValueError:
        return {**out, "issue": f"{symbol} is not an optionable symbol."}
    read = next((r for r in reads if r.value.expiration == expiry), None)
    if read is None:
        return {**out, "issue": problem or f"{expiry:%b} {expiry.day}, {expiry.year} is not a listed {symbol} expiry."}
    return {**out, "chain": read.value, "fetched": read.fetched, "issue": None}


def _fixture_chain(symbol: str, expiry: date) -> dict:
    """SIMULATED: the copilot fixture's NBIS chain at its fixed price and time (``copilot_fixture``)."""
    from app.ai.copilot_fixture import AT, SESSION, simulated_chains
    at = _epoch(AT)
    out = {"spot": 94.35 if symbol == "NBIS" else None, "spot_at": at, "simulated": True, "chain": None, "fetched": at,
           "spot_issue": "The fixture has a simulated NBIS chain only."}
    chain = simulated_chains("NBIS", 94.35, date.fromisoformat(SESSION)).get(expiry) if symbol == "NBIS" else None
    return {**out, "chain": chain, "issue": None if chain else "The fixture has no simulated chain for this contract."}


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
    saved = {p["investigation_id"] for p in plans if p["capture"] is not None} - _entered(db, plans)
    rows = [{"investigation_id": p["investigation_id"], "symbol": p["symbol"], "direction": p["direction"],
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
          pick: tuple[date, float] | None = None, chain_read: Callable[[str, date], dict] | None = None,
          candidates_read: Callable[[str, int, str], dict] | None = None) -> dict:
    """One saved plan's ticket. ``pick``: the candidate he chose (its expiry and strike) for a plan that names none.
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
           "time_stop": row["time_stop"] and row["time_stop"]["text"], "plan_contract_words": words, "size": size,
           "accounts": account_list, "account": selected, "contract": None, "candidates": None, "quote": None,
           "underlying": None, "expected_move_pct": None, "limit": None, "contracts": size["contracts"], "figures": None,
           "simulated": mode == "fixture"}
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
    if named is None and pick is not None:
        named, source = (pick[1], pick[0], kind), "picked"
    if named is None:
        read = (candidates_read or _candidates_reader(mode))(symbol, _horizon_days(db, row, now), row["direction"] or ("long" if kind == "call" else "short"))
        return {**out, "candidates": _candidates(read, now, mode == "fixture")}

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
    return {**out, "contract": {"strike": strike, "expiry": expiry.isoformat(), "type": kind, "label": label(symbol, strike, expiry, kind),
                                "source": source, "multiplier": multiplier},
            "quote": quote, "underlying": stock, "expected_move_pct": move, "limit": limit, "contracts": count,
            "figures": figures(kind, strike, limit, count, multiplier, stock.get("last"), move)}


def _candidates_reader(mode: str) -> Callable[[str, int, str], dict]:
    if mode == "fixture":
        from app.ai.copilot_fixture import FixtureEvidence
        return lambda symbol, days, direction: FixtureEvidence().get_option_candidates(symbol, days, direction)
    from app.ai import copilot_options
    return copilot_options.live_candidates
