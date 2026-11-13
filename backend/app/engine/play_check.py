"""The Ticket's Play check (docs/copilot-lab.md § Ticket, "Play check"): before he copies an order into Robinhood, whether
this is a play he planned or one of his costly habits, and what holding it overnight costs.

Facts and arithmetic. No model call; nothing here places, previews or stages an order, and nothing reads Robinhood: it
reads the journal, the saved plan, and the option chains the ticket already read (one more expiry at most, for the
later-expiry alternative, in the same options-feed pass and under its pacing).

- **Play** (``play``): stop (the plan's invalidation), target (only when the plan carries one), time (the plan's time
  stop, else the symbol's horizon check-in) and size (contracts or dollars at risk). A missing part is said plainly and
  never blocks the ticket: it copies, and he decides.
- **Your habits** (``habits``): ``fill_interrupts``' own rule functions on the order he is about to place, as if it
  filled now (this contract, the ticket's count, the ticket's limit), with the same records and record lines as the
  after-fill message ("Your record, not advice."). The records come from the same ``load_history`` and are kept in
  memory under the same signature the after-fill pass rebuilds on. Adding to a loser reads the open journal position in
  this exact contract (Webull left out); the green day reads the plan account's trades closed today. A ticker he set
  to Not following stays silent. The size rule is also returned as its parts (``size``) so the desk can judge it again
  when he edits the count or the limit.
- **Holding overnight** (``overnight``): for the ticket's contract, time decay a day from the chain's theta (greeks are
  refreshed hourly, so with their as-of), and, at the end of the hold (the plan's time stop, else its horizon, else the
  next close), what an unchanged price costs and the price it needs to break even, against the move the contract's
  implied volatility gives over that time. Beside it the same-exposure alternatives ``expression_recorder.choose``
  picks (deeper, debit spread, later expiry, shares), each sized to the same delta as his contract and priced at the
  mid, with its cost, the most it can lose, its decay a day and the same break-even. Repricing is Black-Scholes at the
  volatility each leg's own mid implies now (so the model prices it at what it costs; the provider's hourly implied
  volatility only when the mid implies none), rate and dividend zero (``options_positioning``'s inputs), the
  volatility held where it is: a model, and said to be one. Dollars are per one of his contracts (``basis``); the desk scales them by the
  count he types, which every dollar figure here is linear in.

A quote that is stale or missing carries its time and reason and no number, never a zero.
"""
from __future__ import annotations

from datetime import date, datetime, time as clock_time, timedelta
from math import erf, log as ln, sqrt
import logging

from sqlalchemy import or_
from sqlmodel import Session, select

from app.engine import expression_recorder
from app.engine import fill_interrupts as rules
from app.engine.analytics import wall_time
from app.engine.chart_math import ET
from app.engine.options_positioning import YEAR_SECONDS, expires_at, primary_root

log = logging.getLogger(__name__)

HOLD_DAYS = {"swing": 7, "long": 30}  # calendar days a horizon check-in runs without a time stop
CLOSE = clock_time(16, 0)
SEARCH = (0.05, 20.0)  # the break-even is searched between these multiples of the price
NAMES = ("as_traded", "deeper", "spread", "later", "shares")


# --- Play ------------------------------------------------------------------------------------------------------------

def play(ticket: dict, row: dict, horizon: str | None) -> dict:
    """The plan's four parts, each ``ok`` with its words or missing with what to add. ``target`` appears only when the
    plan board carries a target field at all."""
    lines = []
    stop = ticket.get("invalidation")
    lines.append({"part": "stop", "ok": stop is not None,
                  "text": f"out at {stop:g}" if stop is not None else "missing: no level where the idea is wrong"})
    if "target" in row:
        target = row["target"]
        price = target.get("price") if isinstance(target, dict) else target
        lines.append({"part": "target", "ok": price is not None,
                      "text": f"take profit at {price:g}" if price is not None else "missing: no target"})
    stop_row = row.get("time_stop")
    if stop_row and stop_row.get("state") == "pending":
        lines.append({"part": "time", "ok": True, "text": stop_row["text"]})
    elif horizon in ("day", "swing", "long"):
        lines.append({"part": "time", "ok": True, "text": f"{horizon} horizon (your check-in; no time stop)"})
    else:
        lines.append({"part": "time", "ok": False, "text": "missing: no time stop"})
    size = ticket.get("size") or {}
    if size.get("contracts"):
        lines.append({"part": "size", "ok": True, "text": f"{size['contracts']} contract{'s' if size['contracts'] != 1 else ''}"})
    elif size.get("risk_usd"):
        lines.append({"part": "size", "ok": True, "text": f"risk ${size['risk_usd']:,.0f}"})
    else:
        lines.append({"part": "size", "ok": False, "text": "missing: no size (contracts or dollars at risk)"})
    missing = [line["part"] for line in lines if not line["ok"]]
    return {"lines": lines, "missing": missing,
            "fill": f"Add {_words(missing)} to the plan." if missing else None}


def _words(parts: list[str]) -> str:
    named = {"stop": "a stop", "target": "a target", "time": "a time stop", "size": "a size"}
    said = [named[p] for p in parts]
    return said[0] if len(said) == 1 else ", ".join(said[:-1]) + " and " + said[-1]


# --- Your habits -----------------------------------------------------------------------------------------------------

_history: tuple | None = None  # (signature, rows): the after-fill pass's records, kept for the ticket's own process


def history(db: Session, today: date) -> list[dict]:
    """``fill_interrupts.load_history``, rebuilt only on a new day or when the closed trades' count or total moved."""
    global _history
    signature = rules.history_signature(db, today)
    if _history is None or _history[0] != signature:
        _history = (signature, rules.load_history(db))
    return _history[1]


def _holdings(db: Session, symbol: str, kind: str, strike: float, expiry: date) -> list[list[dict]]:
    """The fills of each open journal position in exactly this contract, Webull left out, in the reconstructor's order."""
    from app.models import Account, Fill, Trade, TradeFill
    trades = db.exec(select(Trade).join(Account, Account.id == Trade.account_id)
                     .where(Trade.status == "open", Trade.ticker == symbol, Trade.instrument_type == "option",
                            Trade.option_type == kind, Trade.expiration == expiry,
                            or_(Account.broker.is_(None), Account.broker != "webull"))).all()
    out = []
    for trade in trades:
        if trade.strike is None or abs(float(trade.strike) - strike) > 1e-6:
            continue
        links = db.exec(select(TradeFill.role, Fill.id, Fill.raw_email_id, Fill.side, Fill.contracts, Fill.price, Fill.executed_at)
                        .join(Fill, Fill.id == TradeFill.fill_id).where(TradeFill.trade_id == trade.id)).all()
        out.append(sorted(({"id": f.id, "key": f.raw_email_id or str(f.id), "role": f.role, "side": f.side,
                            "contracts": float(f.contracts), "price": float(f.price), "executed_at": wall_time(f.executed_at)}
                           for f in links), key=rules._order))
    return out


def _day_pnl(db: Session, account_id, moment: datetime) -> float | None:
    """The account's realized P&L for ``moment``'s New York day so far (naive New York wall time, as trades keep it)."""
    from app.models import Trade
    if account_id is None:
        return None
    start = datetime.combine(moment.date(), clock_time())
    closes = db.exec(select(Trade.closed_at, Trade.realized_pnl).where(
        Trade.account_id == account_id, Trade.status.in_(("closed", "expired")),
        Trade.closed_at >= start, Trade.closed_at < moment)).all()
    return rules.day_pnl_before([(wall_time(c), float(p or 0)) for c, p in closes], moment)


def habits(db: Session, *, symbol: str, kind: str, strike: float | None, expiry: date | None, contracts: int | None,
           limit: float | None, multiplier: int | None, account_id, moment: datetime, quiet: set[str] | None = None) -> dict:
    """The after-fill rules on this order as if it filled at ``moment`` (naive New York). ``fired`` lists each rule
    with its record line, in the after-fill order; ``size`` is the size rule's parts for the desk to judge again when
    he edits the count or the limit (None until there are enough entries to have a median)."""
    from app.engine import day_journal
    if symbol in (quiet if quiet is not None else day_journal.quiet(db)):
        return {"state": "quiet", "fired": [], "size": None, "footer": rules.FOOTER}
    price = limit * multiplier if limit and multiplier else None  # fills keep an option's price per contract
    fill = {"side": "buy_to_open", "instrument_type": "option", "option_type": kind, "expiration": expiry,
            "executed_at": moment, "contracts": float(contracts or 0) if price else 0.0, "price": price or 0.0}
    held = _holdings(db, symbol, kind, strike, expiry) if strike is not None and expiry is not None else []
    prior = next((p for p in held if rules.adds_to_loser(fill, p)), held[0] if held else []) if price else []
    rows = history(db, moment.date())
    day = _day_pnl(db, account_id, moment)
    recs = {"ticker_record": rules.record(rows, "ticker_record", ticker=symbol),
            "large_size": rules.record(rows, "large_size", day=moment.date())}
    kinds = rules.fired(fill, prior, day, recs["ticker_record"], recs["large_size"])
    paid = rules.premium(fill)
    fired = [{"kind": k, "line": rules.line(k, recs.get(k) or rules.record(rows, k), day, paid)} for k in kinds]
    usual = recs["large_size"]["median"]
    size = {"median": usual, "multiple": rules.LARGE_MULTIPLE, "tail": rules.size_tail(recs["large_size"])} if usual else None
    return {"state": "ok", "fired": fired, "size": size, "footer": rules.FOOTER}


# --- Holding overnight: the model ------------------------------------------------------------------------------------

def _cdf(x: float) -> float:
    return 0.5 * (1 + erf(x / sqrt(2)))


def bs_value(kind: str, spot: float, strike: float, years: float, iv: float | None) -> float | None:
    """Black-Scholes value per share, rate and dividend zero; at or past expiry the intrinsic value. None without a
    volatility while time is left."""
    if years <= 0:
        return max(spot - strike, 0.0) if kind == "call" else max(strike - spot, 0.0)
    if iv is None or iv <= 0 or spot <= 0 or strike <= 0:
        return None
    vol = iv * sqrt(years)
    d1 = (ln(spot / strike) + vol * vol / 2) / vol
    d2 = d1 - vol
    return spot * _cdf(d1) - strike * _cdf(d2) if kind == "call" else strike * _cdf(-d2) - spot * _cdf(-d1)


def implied_vol(kind: str, spot: float, strike: float, years: float, price: float | None) -> float | None:
    """The volatility at which ``bs_value`` equals ``price`` (bisection, 1% to 500%); None at or past expiry, without a
    price, or for a price at or below the intrinsic value (no time value to explain)."""
    if price is None or years <= 0 or spot <= 0 or strike <= 0:
        return None
    intrinsic = max(spot - strike, 0.0) if kind == "call" else max(strike - spot, 0.0)
    if price <= intrinsic + 1e-9:
        return None
    lo, hi = 0.01, 5.0
    if bs_value(kind, spot, strike, years, hi) < price or bs_value(kind, spot, strike, years, lo) > price:
        return None
    for _ in range(100):
        mid = (lo + hi) / 2
        if bs_value(kind, spot, strike, years, mid) < price:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def structure_value(legs: list[dict], spot: float, at: datetime) -> float | None:
    """One unit's model value at ``spot`` and moment ``at``: each option leg's Black-Scholes value times its sign and
    multiplier, a share leg its sign times the price."""
    total = 0.0
    for leg in legs:
        if leg["kind"] == "share":
            total += leg["sign"] * spot
            continue
        years = max((leg["expires"] - at).total_seconds(), 0.0) / YEAR_SECONDS
        each = bs_value(leg["type"], spot, leg["strike"], years, leg["iv"])
        if each is None:
            return None
        total += leg["sign"] * leg["multiplier"] * each
    return total


def breakeven(legs: list[dict], cost: float, spot: float, at: datetime) -> float | None:
    """The price at which one unit's model value at ``at`` equals what it cost, by bisection between ``SEARCH``
    multiples of ``spot`` (each structure here is monotonic in the price); None when no price in that range gets there."""
    lo, hi = spot * SEARCH[0], spot * SEARCH[1]
    f_lo, f_hi = structure_value(legs, lo, at), structure_value(legs, hi, at)
    if f_lo is None or f_hi is None:
        return None
    f_lo, f_hi = f_lo - cost, f_hi - cost
    if f_lo == 0:
        return lo
    if f_lo * f_hi > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        f_mid = structure_value(legs, mid, at) - cost
        if abs(f_mid) < 1e-9 or hi - lo < 1e-9:
            break
        if (f_mid > 0) == (f_hi > 0):
            hi, f_hi = mid, f_mid
        else:
            lo, f_lo = mid, f_mid
    return (lo + hi) / 2


def hold_until(now: datetime, time_stop: dict | None, horizon: str | None) -> tuple[datetime, str, bool]:
    """When the hold ends (aware New York), what set it, and whether it runs past today's close: the plan's pending
    time stop, else a swing or long horizon's days to that day's close, else the next weekday's close (a day horizon
    a time stop due today, or no plan for time: the overnight figures then answer "if I held it to the next close")."""
    today = now.date()
    stop = None
    if time_stop and time_stop.get("state") == "pending" and time_stop.get("due_at"):
        stop = datetime.fromtimestamp(time_stop["due_at"], ET)
        if stop.date() > today:
            return stop, "time stop", True
    # A time stop due today ends the hold today, whatever the horizon: the folded figures answer the next close.
    if stop is None and horizon in HOLD_DAYS:
        return datetime.combine(today + timedelta(days=HOLD_DAYS[horizon]), CLOSE, ET), f"{horizon} horizon", True
    day = today + timedelta(days=1)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return datetime.combine(day, CLOSE, ET), "next close", False


# --- Holding overnight: the alternatives -----------------------------------------------------------------------------

def _label(name: str, symbol: str, legs: list[dict]) -> str:
    from app.engine.desk_ticket import label
    if name == "shares":
        return f"{'Short ' if legs[0]['sign'] < 0 else ''}{symbol} shares"
    first = legs[0]
    text = label(symbol, first["strike"], first["expiration"], first["type"])
    if name == "spread":
        return text.replace(f"${first['strike']:g} ", f"${first['strike']:g}/${legs[1]['strike']:g} ") + " spread"
    return text


def _row(name: str, symbol: str, legs: list[dict], base_delta: float, spot: float, now: datetime, end: datetime,
         expected_pct: float | None) -> dict:
    """One alternative per one of his contracts: units sized to his contract's delta, its cost at the mid, the most it
    can lose, decay a day from the chain's theta, what an unchanged price costs by ``end`` and the break-even then."""
    row = {"name": name, "label": _label(name, symbol, legs),
           "unit": "shares" if name == "shares" else "spreads" if name == "spread" else "contracts"}
    bad = next((leg for leg in legs if leg["kind"] == "option" and leg["quote"]["state"] != "ok"), None)
    if bad is not None:
        return {**row, "state": bad["quote"]["state"], "as_of": bad["quote"].get("as_of"),
                "reason": bad["quote"].get("reason") or "No usable quote."}
    if any(leg["kind"] == "option" and leg["delta"] is None for leg in legs):
        return {**row, "state": "missing", "reason": "The chain has no delta for this contract, so it cannot be sized to yours."}
    per_delta = sum(leg["sign"] * (1 if leg["kind"] == "share" else leg["delta"] * leg["multiplier"]) for leg in legs)
    if not per_delta or per_delta * base_delta <= 0:
        return {**row, "state": "missing", "reason": "Its delta does not match your contract's direction."}
    units = base_delta / per_delta
    cost_each = sum(leg["sign"] * (spot if leg["kind"] == "share" else leg["mid"] * leg["multiplier"]) for leg in legs)
    cost = units * cost_each
    short = name == "shares" and legs[0]["sign"] < 0
    thetas = [leg["theta"] for leg in legs if leg["kind"] == "option"]
    decay = None if None in thetas else -units * sum(leg["sign"] * leg["theta"] * leg["multiplier"] for leg in legs if leg["kind"] == "option")
    now_value, end_value = structure_value(legs, spot, now), structure_value(legs, spot, end)
    hold_cost = units * (now_value - end_value) if now_value is not None and end_value is not None else None
    even = breakeven(legs, cost_each, spot, end)
    move = (even - spot) / spot * 100 if even is not None else None
    out = {**row, "state": "ok", "units": round(units, 6),  # unrounded: the desk scales it by his count, then rounds
           "cost": round(abs(cost), 2), "credit": cost < 0,
           "max_loss": None if short else round(cost, 2),
           "max_loss_note": "no limit" if short else None,
           "decay_day": round(decay, 2) + 0.0 if decay is not None else None,
           "decay_pct": round(decay / cost * 100, 1) + 0.0 if decay is not None and cost > 0 else None,
           "hold_cost": round(hold_cost, 2) if hold_cost is not None else None,
           "hold_cost_pct": round(hold_cost / cost * 100, 1) if hold_cost is not None and cost > 0 else None,
           "breakeven": round(even, 2) if even is not None else None,
           "breakeven_move_pct": round(move, 2) if move is not None else None,
           "vs_expected": round(abs(move) / expected_pct, 1) if move is not None and expected_pct else None}
    if short:
        out["note"] = "not in a Roth IRA"
    return out


def _leg(contract, sign: int, quote: dict, root: str, closes, spot: float, now: datetime) -> dict:
    """One option leg. Its volatility is the one its own mid implies now, so the model prices it at what it costs;
    the provider's (hourly) implied volatility only when the mid implies none."""
    expires = expires_at(contract.expiration, root, closes)
    years = max((expires - now).total_seconds(), 0.0) / YEAR_SECONDS
    implied = implied_vol(contract.option_type, spot, contract.strike, years, quote.get("mid"))
    return {"kind": "option", "symbol": contract.symbol, "type": contract.option_type, "strike": contract.strike,
            "expiration": contract.expiration, "expires": expires, "sign": sign,
            "multiplier": contract.multiplier or 100, "delta": contract.delta, "theta": contract.theta,
            "iv": implied if implied is not None else contract.iv if contract.iv is not None else contract.iv_smoothed,
            "quote": quote, "mid": quote.get("mid")}


def overnight(*, symbol: str, traded, chain, later, spot: float, now: datetime, time_stop: dict | None, horizon: str | None,
              quote_for, closes=None) -> dict:
    """The holding-overnight block for one of his contracts (``basis``: dollars per contract). ``traded`` is his
    contract as listed in ``chain``; ``later`` the later expiry's chain or None; ``quote_for(contract, chain)`` judges
    a contract's quote as the ticket does (``desk_ticket.contract_quote``)."""
    root = traded.root or primary_root(symbol)
    end, source, past_close = hold_until(now, time_stop, horizon)
    expiry = expires_at(traded.expiration, root, closes)
    expires_first = end >= expiry
    picks = expression_recorder.choose(traded, chain, later, spot, None if symbol in expression_recorder.NO_SHARES else symbol)
    found = {c.symbol: (c, chain) for c in chain.contracts}
    if later is not None:
        found.update({c.symbol: (c, later) for c in later.contracts})
    hold_years = (min(end, expiry) - now).total_seconds() / YEAR_SECONDS
    mine = _leg(traded, 1, quote_for(traded, chain), root, closes, spot, now)
    iv = mine["iv"]
    expected_pct = round(iv * sqrt(hold_years) * 100, 2) if iv and hold_years > 0 else None
    base_delta = (traded.delta or 0) * mine["multiplier"]
    rows = []
    for name in NAMES:
        if name not in picks:
            continue
        legs = []
        for part in picks[name]:
            if part["kind"] == "share":
                legs.append({"kind": "share", "sign": part["sign"], "multiplier": 1})
                continue
            contract, its_chain = found[part["symbol"]]
            legs.append(_leg(contract, part["sign"], quote_for(contract, its_chain), root, closes, spot, now))
        rows.append(_row(name, symbol, legs, base_delta, spot, now, end, expected_pct))
    return {"state": "ok", "show": past_close, "until": int(end.timestamp()), "until_source": source,
            "expires_first": expires_first, "trading_days": rules.trading_days(now.date(), min(end, expiry).date()),
            "hold_days": round((min(end, expiry) - now).total_seconds() / 86400, 2),
            "greeks_as_of": traded.greeks_updated_at, "expected_move_pct": expected_pct, "basis": "per contract", "rows": rows}


# --- the check -------------------------------------------------------------------------------------------------------

def check(db: Session, ticket: dict, row: dict, *, account_id, now: float, chain_read: dict | None = None,
          traded=None, quote_for=None) -> dict:
    """The ticket's Play check. ``chain_read`` is the ticket's chain read (with ``later``); ``traded`` the ticket's
    contract in it; ``now`` the ticket's moment (the fixture's own time in the sandbox)."""
    from app.engine import day_journal
    moment = datetime.fromtimestamp(now, ET)
    horizon = day_journal.check_ins(db)[0].get(ticket["symbol"])
    out = {"play": play(ticket, row, horizon), "habits": None, "overnight": None}
    contract = ticket.get("contract")
    expiry = date.fromisoformat(contract["expiry"]) if contract else None
    try:
        out["habits"] = habits(db, symbol=ticket["symbol"], kind=ticket["option_type"], strike=contract and contract["strike"],
                               expiry=expiry, contracts=ticket.get("contracts"), limit=ticket.get("limit"),
                               multiplier=contract and contract["multiplier"], account_id=account_id,
                               moment=moment.replace(tzinfo=None))
    except Exception:  # noqa: BLE001 -- the ticket matters more than its check
        log.warning("Play check habits failed", exc_info=True)
        db.rollback()
        out["habits"] = {"state": "error", "fired": [], "size": None, "footer": rules.FOOTER}
    if contract is None:
        return out
    quote, stock = ticket.get("quote") or {}, ticket.get("underlying") or {}
    if quote.get("state") != "ok" or stock.get("state") != "ok" or traded is None or chain_read is None:
        bad = quote if quote.get("state") != "ok" else stock
        out["overnight"] = {"state": bad.get("state") or "missing", "as_of": bad.get("as_of"), "show": False,
                            "reason": bad.get("reason") or "The contract could not be read."}
        return out
    try:
        out["overnight"] = overnight(symbol=ticket["symbol"], traded=traded, chain=chain_read["chain"], later=chain_read.get("later"),
                                     spot=stock["last"], now=moment, time_stop=row.get("time_stop"), horizon=horizon,
                                     quote_for=quote_for)
    except Exception:  # noqa: BLE001
        log.warning("Play check overnight failed", exc_info=True)
        out["overnight"] = {"state": "missing", "show": False, "reason": "The overnight figures could not be worked out."}
    return out
