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
- **Expiry.** An option or spread still open after its expiration's close settles at intrinsic value from the
  underlying's regular-session close (``_close_for``: the stored close, else one daily-history read through the feed).
- **Append-only.** Every fill is a ``PaperEvent``; a position is their fold, so nothing is ever edited. A position's
  P&L at a moment is the sum of its cash flows plus what it is worth then.
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

from app.engine import desk_ticket
from app.engine import scanner_rules as rules
from app.engine.chart_math import ET
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
_TICKER = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")
_KEY = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


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


def price(spec: dict, quotes: dict, now: float, closing: bool) -> dict:
    """One unit's cash per share at the live quote, signed (+ money in, − money out): each leg bought at its ask, each
    sold at its bid (a closing order reverses the legs). Refuses a leg with no quote, no usable bid and ask, or a quote
    either of whose sides is older than ``FRESH_SECONDS``."""
    cash, legs, times = 0.0, {}, []
    for leg in spec["legs"]:
        action = leg["action"] if not closing else ("sell" if leg["action"] == "buy" else "buy")
        quote, name = quotes.get(leg["quote"]), _name(leg["quote"], spec)
        if quote is None:
            raise PaperError(f"No quote for {name} right now, so no paper fill.", 409)
        bid, ask = quote.bid, quote.ask
        if bid is None or ask is None or bid < 0 or ask < bid or (action == "buy" and not ask > 0):
            raise PaperError(f"{name.capitalize() if name.startswith('the') else name} has no usable bid and ask right now, so no paper fill.", 409)
        if not _fresh(quote, now - FRESH_SECONDS):
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

def current_run(db: Session) -> PaperRun | None:
    return db.exec(select(PaperRun).order_by(col(PaperRun.started_at).desc(), col(PaperRun.id).desc())).first()


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
    (the last one takes what is left, so the cash flows and the realized P&L add up to the cent)."""
    out: dict[uuid.UUID, dict] = {}
    for event in events:
        data = json.loads(event.data_json)
        if event.kind == "open":
            out[event.position_id] = {**data, "id": str(event.position_id), "opened_at": _epoch(event.effective_at),
                                      "remaining": data["quantity"], "basis_left": data["cash"], "realized": 0.0,
                                      "exits": [], "status": "open", "closed_at": None}
            continue
        position = out.get(event.position_id)
        if position is None or position["remaining"] <= 0:
            continue
        qty = min(data["quantity"], position["remaining"])
        basis = position["basis_left"] if qty == position["remaining"] else round(position["cash"] * qty / position["quantity"], 2)
        pnl = round(data["cash"] + basis, 2)
        position["basis_left"] = round(position["basis_left"] - basis, 2)
        position["remaining"] -= qty
        position["realized"] = round(position["realized"] + pnl, 2)
        position["exits"].append({**data, "kind": event.kind, "at": _epoch(event.effective_at), "pnl": pnl})
        if position["remaining"] <= 0:
            position["status"] = "expired" if event.kind == "expire" else "closed"
            position["closed_at"] = _epoch(event.effective_at)
    return list(out.values())


def account(run: PaperRun, events: list[PaperEvent], positions: list[dict]) -> dict:
    """Cash is the start plus every fill's cash; a credit spread's width is held as collateral, so buying power is the
    cash less it."""
    cash = round(run.starting_cash + sum(json.loads(e.data_json)["cash"] for e in events), 2)
    collateral = round(sum(p["width"] * p["multiplier"] * p["remaining"] for p in positions
                           if p["status"] == "open" and p["credit"]), 2)
    return {"cash": cash, "collateral": collateral, "buying_power": round(cash - collateral, 2)}


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


def _note(body: dict) -> str | None:
    text = " ".join(str(body.get("note") or "").split())[:NOTE_CHARS]
    return text or None


def open_order(db: Session, body: dict, now: float, preview: bool = False) -> dict:
    """Open a paper position at the live quote (``preview``: what it would fill at, nothing stored)."""
    run = current_run(db)
    if run is None:
        raise PaperError("Start a paper account first.", 409)
    spec = contract(body, _ny_day(now))
    qty = _quantity(body.get("quantity"))
    note = _note(body)
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
    book = account(run, events, fold(events))
    held = round(spec["width"] * spec["multiplier"] * qty, 2) if spec["credit"] else 0.0
    need = round(held - cash, 2)  # a debit: what it costs; a credit spread: the width held less the credit taken in
    if need > book["buying_power"] + 0.005:
        raise PaperError(f"Not enough paper buying power: this needs {usd(need)} and you have {usd(book['buying_power'])}.", 409)
    data = {**spec, "quantity": qty, "per_share": per, "cash": cash, "legs_filled": fill["legs"], "stock": stock,
            "note": note, "stop": stop, "target": target}
    result = {"label": spec["label"], "quantity": qty, "per_share": per, "cash": cash, "quoted_at": fill["quoted_at"],
              "legs": fill["legs"], "stock": stock, "buying_power_after": round(book["buying_power"] - need, 2)}
    if preview:
        return {"preview": result}
    position_id = uuid.uuid4()
    if not _store(db, run, position_id, "open", key, fill["quoted_at"], data):
        return {"filled": None, "duplicate": True}
    return {"filled": {**result, "position_id": str(position_id)}}


def close_order(db: Session, body: dict, now: float, preview: bool = False) -> dict:
    """Close all of an open paper position, or trim part of it, at the live quote."""
    run = current_run(db)
    if run is None:
        raise PaperError("Start a paper account first.", 409)
    try:
        position_id = uuid.UUID(str(body.get("position_id")))
    except ValueError:
        raise PaperError("Name the paper position.") from None
    position = next((p for p in fold(_events(db, run)) if p["id"] == str(position_id)), None)
    if position is None or position["status"] != "open":
        raise PaperError("That paper position is not open.", 409)
    qty = position["remaining"] if body.get("quantity") is None else _quantity(body.get("quantity"), position["remaining"])
    key = None if preview else _key(body)
    if not _market_open(now):
        raise PaperError("The market is closed: paper orders fill only in the regular session, on a live quote.", 409)
    quotes = _live_quotes([leg["quote"] for leg in position["legs"]] + [position["symbol"]])
    fill = price(position, quotes, now, closing=True)
    cash = round(fill["per_share"] * position["multiplier"] * qty, 2)
    basis = position["basis_left"] if qty == position["remaining"] else round(position["cash"] * qty / position["quantity"], 2)
    stock = _stock_price(position, quotes)
    data = {"quantity": qty, "per_share": fill["per_share"], "cash": cash, "legs_filled": fill["legs"], "stock": stock}
    result = {"label": position["label"], "quantity": qty, "per_share": fill["per_share"], "cash": cash,
              "quoted_at": fill["quoted_at"], "legs": fill["legs"], "stock": stock, "pnl": round(cash + basis, 2),
              "all": qty == position["remaining"]}
    if preview:
        return {"preview": result}
    if not _store(db, run, position_id, "close", key, fill["quoted_at"], data):
        return {"filled": None, "duplicate": True}
    return {"filled": result}


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
    """Closed trades' win rate, average winner and loser and largest loss; P&L by day from every realized amount."""
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


def _position_view(p: dict, marks: dict | None) -> dict:
    keep = ("id", "symbol", "instrument", "option_type", "expiry", "label", "bias", "credit", "width", "multiplier",
            "quantity", "remaining", "per_share", "cash", "stock", "note", "stop", "target", "opened_at", "status",
            "closed_at", "realized")
    out = {k: p.get(k) for k in keep}
    out["legs"] = [{"quote": leg["quote"], "action": leg["action"], "strike": leg["strike"]} for leg in p["legs"]]
    out["basis"] = p["basis_left"]
    out["awaiting_close"] = bool(p.get("awaiting_close"))
    if marks is not None:
        out["mark"] = worth(p, marks)
    else:
        out["exits"] = [{k: e.get(k) for k in ("kind", "at", "quantity", "per_share", "cash", "pnl", "stock")} for e in p["exits"]]
        out["verdict"] = verdict(p)
    return out


def view(db: Session, now: float) -> dict:
    """The paper account, its open positions (with the desk's newest prices), closed trades and the scorecard."""
    run = current_run(db)
    runs = list(db.exec(select(PaperRun).order_by(col(PaperRun.started_at), col(PaperRun.id))).all())
    if run is None:
        return {"run": None, "default_cash": DEFAULT_CASH, "earlier": [], "market_open": _market_open(now)}
    events = _events(db, run)
    positions = fold(events)
    if settle(db, run, positions, now):
        events = _events(db, run)
        positions = fold(events)
    book = account(run, events, positions)
    open_ = [p for p in positions if p["status"] == "open"]
    marks = _marks(sorted({leg["quote"] for p in open_ for leg in p["legs"]}))
    shown = [_position_view(p, marks) for p in reversed(open_)]
    priced = [s["mark"] for s in shown if s["mark"] is not None]
    equity = round(book["cash"] + sum(m["value"] for m in priced), 2) if len(priced) == len(shown) else None
    closed = [p for p in positions if p["status"] != "open"]
    realized = [(_ny_day(e["at"]), e["pnl"]) for p in positions for e in p["exits"]]
    paper = stats([p["realized"] for p in closed], realized)
    paper["open_pnl"] = round(sum(m["pnl"] for m in priced), 2) if priced else None
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
                    "unpriced": len(shown) - len(priced)},
        "positions": shown,
        "closed": [_position_view(p, None) for p in sorted(closed, key=lambda p: p["closed_at"], reverse=True)[:CLOSED_SHOWN]],
        "score": {"paper": paper, "real": real_trades(db, run.started_at)},
        "earlier": list(reversed(earlier)), "market_open": _market_open(now), "fresh_seconds": FRESH_SECONDS,
    }
