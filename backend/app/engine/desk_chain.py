"""The desk's Chain tab (docs/copilot-lab.md § Chain): one expiry of the selected ticker's option chain, to pick a
contract without opening Robinhood.

Read-only. Nothing here places, sends or stages an order and nothing reads Robinhood: the chain comes from the options
feed (``options_feed.chains``, Tradier through the C4.1 adapter, its 30-a-minute budget and its own 24-a-minute
pacing), the stock's price from the chart feed's shared 15-second quote cache, and the held and planned marks from the
journal.

- **One read per expiry, kept briefly.** The feed keeps every chain it reads; a chain this tab asks for is read again
  only once it is older than ``LIVE_TTL`` seconds in the regular session (``CLOSED_TTL`` outside it), and the feed's
  one-pass lock makes a second request wait for the first read instead of repeating it. A read the pacing refuses
  answers from the chain already kept, with its read time.
- **The strike window.** ``WINDOW`` strikes either side of the strike nearest the price (the at-the-money strike, which
  is marked). Without a price the window centres where the calls and puts cost the same (put-call parity), and says so.
- **Honest quotes.** A missing bid or ask is None, never zero, and the contract has no mark. In the regular session a
  contract whose older side is more than ``QUOTE_STALE_S`` old is ``stale``, and the whole chain is ``stale`` once its
  read is more than ``CHAIN_STALE_S`` old; both keep their numbers with their time, for the desk to grey. Outside the
  session the chain says it is closed and when it was read.
- **Spreads in plain words.** A spread at or over ``WIDE_PCT`` of the mark is flagged wide, with what crossing it costs
  a contract.
- **Marks.** Contracts he holds (open journal trades, Webull left out) carry their count; the contract a saved plan
  names is ``planned``; a plan's entry or exit price within half a strike step of a strike marks that strike.
"""
from __future__ import annotations

from datetime import UTC, date, datetime
import time

from sqlmodel import Session, select

from app.engine import request_timing

WINDOW = 10  # strikes either side of the at-the-money strike
LIVE_TTL = 12  # seconds a chain read serves this tab in the regular session
CLOSED_TTL = 300  # outside it
POLL_SECONDS = 15  # how often the desk asks while the tab is open in the regular session
CHAIN_STALE_S = 45  # a chain read older than this in the session reads stale (three missed refreshes)
QUOTE_STALE_S = 15 * 60  # as the ticket's
WIDE_PCT = 10.0  # a spread this share of the mark, or more, is wide
SIDES = {"buy_calls": "call", "sell_calls": "call", "buy_puts": "put", "sell_puts": "put"}


class ChainError(Exception):
    """A request the chain cannot answer at all (not an optionable symbol)."""


# --- the expiry list -------------------------------------------------------------------------------------------------

def _third_friday(day: date) -> bool:
    return day.weekday() == 4 and 15 <= day.day <= 21


def expiries(live: list[date], today: date, held: set[date], report: date | None = None) -> list[dict]:
    """Every unexpired expiry, nearest first (today's 0DTE first when there is one), each with its days left, a kind
    (``0dte``, ``monthly`` for a third Friday, else ``weekly``), whether he holds a contract in it and whether it lives
    through the next earnings ``report`` (on or after its date: the calendar has no time of day)."""
    out = []
    for day in sorted(set(live)):
        days = (day - today).days
        kind = "0dte" if days == 0 else "monthly" if _third_friday(day) else "weekly"
        out.append({"date": day.isoformat(), "days": days, "kind": kind, "held": day in held,
                    "earnings": report is not None and day >= report})
    return out


# --- the strike window -----------------------------------------------------------------------------------------------

def _usable(contract) -> bool:
    return contract.bid is not None and contract.ask is not None and contract.ask > 0 and 0 <= contract.bid <= contract.ask


def _mid(contract) -> float | None:
    return (contract.bid + contract.ask) / 2 if contract is not None and _usable(contract) else None


def centre(strikes: list[float], by_strike: dict[float, dict], spot: float | None) -> int | None:
    """The index of the at-the-money strike: nearest the price, else where call and put marks are closest."""
    if not strikes:
        return None
    if spot is not None and spot > 0:
        return min(range(len(strikes)), key=lambda i: (abs(strikes[i] - spot), strikes[i]))
    gaps = [(abs(c - p), i) for i, s in enumerate(strikes)
            if (c := _mid(by_strike[s].get("call"))) is not None and (p := _mid(by_strike[s].get("put"))) is not None]
    return min(gaps)[1] if gaps else len(strikes) // 2


def window(strikes: list[float], at: int | None, size: int = WINDOW) -> list[float]:
    """``size`` strikes either side of ``at`` (fewer at the ends of the chain)."""
    if at is None:
        return []
    return strikes[max(at - size, 0): at + size + 1]


def _epoch(moment) -> float | None:
    if moment is None:
        return None
    return (moment if moment.tzinfo else moment.replace(tzinfo=UTC)).timestamp()


def contract_row(contract, now: float, live_session: bool, simulated: bool) -> dict:
    """One contract as the chain shows it: bid, ask, mark, spread (wide in plain words), volume, open interest, delta,
    IV and its quote time; ``state`` ok, stale (numbers kept with their time) or missing (no usable bid and ask)."""
    stamps = [_epoch(contract.bid_time), _epoch(contract.ask_time)]
    quoted = None if None in stamps else min(stamps)
    usable = _usable(contract)
    mark = round((contract.bid + contract.ask) / 2, 4) if usable else None
    spread = round(contract.ask - contract.bid, 4) if usable else None
    spread_pct = round(spread / mark * 100, 1) if usable and mark else None
    wide = spread_pct is not None and spread_pct >= WIDE_PCT
    multiplier = contract.multiplier or 100
    if not usable:
        state = "missing"
    elif live_session and not simulated and (quoted is None or now - quoted > QUOTE_STALE_S):
        state = "stale"
    else:
        state = "ok"
    return {
        "symbol": contract.symbol, "bid": contract.bid, "ask": contract.ask, "mark": mark, "last": contract.last,
        "spread": spread, "spread_pct": spread_pct, "wide": wide,
        "spread_note": (f"Wide spread: ${spread * multiplier:,.0f} a contract between bid and ask ({spread_pct:g}% of the mark)"
                        if wide else None),
        "volume": contract.volume, "open_interest": contract.open_interest, "delta": contract.delta,
        "iv": round(contract.iv * 100, 1) if contract.iv is not None else None,
        "quoted_at": int(quoted) if quoted is not None else None, "state": state, "multiplier": multiplier,
        "held": None, "planned": False,
    }


def _root(chain, symbol: str) -> str:
    from app.engine.options_positioning import primary_root
    roots = [c.root for c in chain.contracts]
    want = primary_root(symbol)
    return want if want in roots else max(set(roots), key=roots.count) if roots else want


# --- the marks -------------------------------------------------------------------------------------------------------

def held_contracts(db: Session, symbol: str) -> dict[tuple[date, str, float], float]:
    """His open option contracts in ``symbol`` from the journal, by (expiry, side, strike): the count. Webull stays out."""
    from sqlalchemy import or_
    from app.models import Account, Trade
    rows = db.exec(select(Trade.expiration, Trade.option_type, Trade.strike, Trade.contracts)
                   .join(Account, Account.id == Trade.account_id)
                   .where(Trade.status == "open", Trade.instrument_type == "option", Trade.ticker == symbol)
                   .where(or_(Account.broker.is_(None), Account.broker != "webull"))).all()
    out: dict[tuple[date, str, float], float] = {}
    for expiration, side, strike, count in rows:
        if expiration is None or side not in ("call", "put") or strike is None:
            continue
        key = (expiration, side, round(float(strike), 3))
        out[key] = out.get(key, 0) + float(count or 0)
    return out


def plan_marks(db: Session, symbol: str) -> tuple[list[dict], set[tuple[date, str, float]]]:
    """The live plans' levels for ``symbol`` (entry and exit prices, from the Plans board) and the contracts their saved
    plans name, by (expiry, side, strike). Journal only; no quote read."""
    from app.engine import copilot_plans
    from app.engine.desk_ticket import _no_quotes
    board = [p for p in copilot_plans.board(db, quotes=_no_quotes)["plans"] if p["symbol"] == symbol]
    levels = []
    for plan in board:
        for role, name in (("entry", "entry"), ("invalidation", "exit")):
            level = plan.get(role)
            if level and isinstance(level.get("price"), (int, float)):
                levels.append({"role": name, "price": float(level["price"]), "investigation_id": plan["investigation_id"]})
    ids = {p["investigation_id"] for p in board}
    named = set()
    for plan in copilot_plans._plans(db)[0]:
        capture = plan.get("capture")
        if plan["investigation_id"] in ids and capture is not None and capture.strike and capture.expiration:
            side = SIDES.get(capture.side)
            if side:
                named.add((capture.expiration, side, round(float(capture.strike), 3)))
    return levels, named


def level_strike(strikes: list[float], price: float) -> float | None:
    """The strike a level marks: the nearest one, when the level is within half a strike step of it."""
    if not strikes:
        return None
    i = min(range(len(strikes)), key=lambda k: abs(strikes[k] - price))
    steps = [abs(strikes[i] - strikes[j]) for j in (i - 1, i + 1) if 0 <= j < len(strikes)]
    half = (min(steps) if steps else max(abs(strikes[i]) * 0.01, 0.5)) / 2
    return strikes[i] if abs(strikes[i] - price) <= half + 1e-9 else None


# --- reading ---------------------------------------------------------------------------------------------------------

def _session(now: float) -> tuple[str, tuple[int, int] | None]:
    from app.engine import desk_sparks
    _day, phase, _hours, regular = desk_sparks._session(now)
    return phase, regular


def _live_read(symbol: str, expiration: date | None, ttl: int) -> dict:
    """The expiry list and one expiry's chain from the options feed, and the stock's price from the quote cache."""
    from app.engine import copilot_plans
    from app.engine.options_chain import _symbol
    from app.engine.options_feed import options_feed
    try:
        symbol = _symbol(symbol)
    except ValueError as exc:
        raise ChainError(f"{symbol!r} is not a ticker.") from exc
    seen: dict[str, list[date]] = {}

    def pick(live: list[date]) -> list[date]:
        seen["live"] = live
        chosen = expiration if expiration in live else (live[0] if live else None)
        return [chosen] if chosen else []
    with request_timing.timed("chain_read"):
        reads, issue = options_feed.chains(symbol, pick, ttl=ttl)
    with request_timing.timed("chain_spot"):
        last, spot_at, spot_issue = copilot_plans._quotes([symbol])
    read = reads[0] if reads else None
    return {"live": seen.get("live"), "chain": read.value if read else None, "fetched": read.fetched if read else None,
            "issue": issue, "spot": last.get(symbol), "spot_at": spot_at, "spot_issue": spot_issue, "simulated": False}


def _fixture_read(symbol: str, expiration: date | None, ttl: int) -> dict:
    """SIMULATED: the copilot fixture's NBIS chains at its fixed price and time (``copilot_fixture``)."""
    from app.ai.copilot_fixture import AT, SESSION, simulated_chains
    at = datetime.fromisoformat(AT.replace("Z", "+00:00")).timestamp()
    if symbol != "NBIS":
        return {"live": [], "chain": None, "fetched": None, "issue": "The sandbox fixture has a simulated NBIS chain only.",
                "spot": None, "spot_at": None, "spot_issue": None, "simulated": True}
    chains = simulated_chains("NBIS", 94.35, date.fromisoformat(SESSION), walls=True)
    live = sorted(d for d in chains if d >= date.fromisoformat(SESSION))
    chosen = expiration if expiration in live else live[0]
    return {"live": live, "chain": chains[chosen], "fetched": at, "issue": None, "spot": 94.35, "spot_at": at,
            "spot_issue": None, "simulated": True}


def view(db: Session, symbol: str, expiration: date | None = None, *, mode: str = "live", now: float | None = None,
         read=None, strike: float | None = None) -> dict:
    """One expiry of ``symbol``'s chain for the desk (nearest expiry when ``expiration`` is not listed or not given).
    ``strike``: a listed strike outside the window (an unusual contract picked from the Feed) widens it to include it.
    ``mode``: the copilot's evidence (``live``; ``fixture`` reads the simulated NBIS chain; ``replay`` reads none)."""
    symbol = (symbol or "").strip().upper()
    now = time.time() if now is None else now
    phase, regular = ("closed", None) if mode == "fixture" else _session(now)  # a fixed snapshot: no clock
    live_session = phase == "regular" and regular is not None
    base = {"symbol": symbol, "state": "ok", "session": "open" if live_session else "closed",
            "poll_seconds": POLL_SECONDS if live_session else None, "expiries": [], "expiration": None, "spot": None,
            "spot_at": None, "spot_issue": None, "atm_strike": None, "fetched_at": None, "age_s": None, "stale": False,
            "message": None, "rows": [], "levels": [], "simulated": mode == "fixture", "root": None, "earnings": None}
    if mode == "replay":
        return {**base, "state": "unavailable", "message": "Replay reads no live quotes, so there is no chain to show."}
    reader = read or (_fixture_read if mode == "fixture" else _live_read)
    got = reader(symbol, expiration, LIVE_TTL if live_session else CLOSED_TTL)
    simulated = bool(got.get("simulated"))
    if simulated:
        live_session = False  # a fixed snapshot: never judged by today's clock
    held = held_contracts(db, symbol)
    listed = got.get("live")
    if listed is None:
        return {**base, "state": "unavailable", "message": got.get("issue") or "The option expirations could not be read."}
    from app.engine.chart_math import ET
    today = datetime.fromtimestamp(now, ET).date() if not simulated else min(listed, default=date.today())
    # The next earnings from the cache only (``desk_events``); a simulated chain has none.
    from app.engine.desk_events import next_report
    report = None if simulated else next_report(symbol, today)
    out = {**base, "expiries": expiries(listed, today, {k[0] for k in held}, date.fromisoformat(report["date"]) if report else None),
           "spot_issue": got.get("spot_issue"), "simulated": simulated, "earnings": report}
    if not listed:
        return {**out, "state": "none", "message": f"{symbol} has no listed options."}
    chain = got.get("chain")
    if chain is None:
        return {**out, "state": "unavailable", "message": got.get("issue") or "The option chain could not be read."}
    spot = got.get("spot") if isinstance(got.get("spot"), (int, float)) and got["spot"] > 0 else None
    fetched = got.get("fetched")
    age = max(now - fetched, 0) if fetched is not None and not simulated else None
    stale = bool(live_session and age is not None and age > CHAIN_STALE_S)
    root = _root(chain, symbol)
    by_strike: dict[float, dict] = {}
    for c in chain.contracts:
        if c.root == root:
            by_strike.setdefault(round(c.strike, 3), {})[c.option_type] = c
    strikes = sorted(by_strike)
    at = centre(strikes, by_strike, spot)
    shown = window(strikes, at)
    if strike is not None and shown and (want := round(strike, 3)) in by_strike and want not in shown:
        lo, hi = strikes.index(shown[0]), strikes.index(shown[-1])
        shown = strikes[min(lo, strikes.index(want)): max(hi, strikes.index(want)) + 1]
    levels, named = plan_marks(db, symbol)
    expiry = chain.expiration
    rows = []
    for strike in shown:
        row = {"strike": strike, "atm": strikes[at] == strike, "levels": []}
        for side in ("call", "put"):
            contract = by_strike[strike].get(side)
            if contract is None:
                row[side] = None
                continue
            cell = contract_row(contract, now, live_session, simulated)
            cell["held"] = held.get((expiry, side, strike))
            cell["planned"] = (expiry, side, strike) in named
            row[side] = cell
        rows.append(row)
    marked = []
    for level in levels:
        strike = level_strike(shown, level["price"])
        if strike is not None:
            next(r for r in rows if r["strike"] == strike)["levels"].append(level["role"])
        marked.append({**level, "strike": strike})
    message = got.get("issue")
    if stale and not message:
        message = "The chain could not be read again just now; these quotes are from its last read."
    return {**out, "expiration": expiry.isoformat(), "spot": spot, "spot_at": got.get("spot_at"),
            "atm_strike": strikes[at] if at is not None else None, "fetched_at": int(fetched) if fetched is not None else None,
            "age_s": int(age) if age is not None else None, "stale": stale, "message": message, "rows": rows,
            "levels": marked, "root": root, "centred_on": "price" if spot is not None else "parity"}
