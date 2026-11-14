"""Redo a real trade in replay (docs/copilot-lab.md § Redo a real trade): the owner picks one of his closed real trades,
the desk opens Replay on that trade's day and ticker (at the open, or 15 minutes before his first entry), he paper trades
it without seeing what he really did, and when he ends the redo one card compares the two.

- **The plan** (``plan``): the trade's New York day, ticker and, for a call or put, its contract preselected when the
  day is inside option replay's window (``replay_options.off_reason``); otherwise shares, with the reason. Nothing about
  how the real trade went (fills, P&L, notes) is in it: only what Replay needs to start.
- **The link.** A redo is an ordinary replay run (``paper_replay``) plus one ``redo`` event on it (``order_key``
  ``redo:<run>``, its data the original trade's id and where the redo started), so every trade in that run is a redo
  of that trade. Additive: no schema change, and the paper book's fold, orders and switches ignore the kind.
- **The comparison** (``compare``): his real trade (entry, exit, P&L, time held, read from the journal's ``trade`` row)
  beside the redo run's closed trades (the same fields, size-weighted when there are several), the difference in
  dollars (redo less real), and one plain line of what changed, built from those facts alone (skipped it, entered or
  exited earlier or later, smaller or bigger size, shares instead of the option).
- **Redo my worst** (``worst``): his five biggest real losing trades opened on a day Replay offers, Webull and
  not-followed tickers left out.

Reads ``trade`` and ``account`` rows and never writes them, fills or FIFO; writes only replay runs' paper rows. No
provider call of its own: the bars and option trades are Replay's.
"""
from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime, timedelta

from sqlmodel import Session, col, select

from app.engine import paper_book as pb, paper_replay as pr, replay_options as ro
from app.engine.chart_math import ET
from app.models import Account, PaperEvent, PaperRun, Trade

KIND = pr.REDO  # the link event's kind on a replay run
BEFORE_MINUTES = 15  # "15 minutes before your first entry"
WORST_SHOWN = 5
SAME_MINUTES = 5  # entry or exit times closer than this read as the same


def _ny_epoch(moment: datetime) -> float:
    """A journal time (a New York wall clock, naive) as epoch seconds."""
    return (moment.replace(tzinfo=ET) if moment.tzinfo is None else moment).timestamp()


def _ny_day(moment: datetime) -> date:
    return (moment if moment.tzinfo is None else moment.astimezone(ET)).date()


def _label(trade: Trade) -> str:
    symbol = trade.ticker.upper()
    if trade.instrument_type != "option" or trade.strike is None or trade.expiration is None or trade.option_type not in ("call", "put"):
        return f"{symbol} shares"
    e = trade.expiration
    return f"{symbol} ${float(trade.strike):g} {trade.option_type.title()} {e.month}/{e.day}/{e.year % 100:02d}"


def _trade(db: Session, trade_id) -> Trade:
    try:
        key = uuid.UUID(str(trade_id))
    except ValueError:
        raise pr.ReplayError("Name the trade.") from None
    found = db.get(Trade, key)
    if found is None:
        raise pr.ReplayError("That trade is not in the journal.", 404)
    if found.status == "open" or found.closed_at is None:
        raise pr.ReplayError("That trade is still open: redo it once it has closed.", 409)
    return found


# --- the plan --------------------------------------------------------------------------------------------------------

def plan(db: Session, trade_id, now: float) -> dict:
    """What Replay needs to redo the trade: its day and ticker, where it can start, and the contract to preselect (or
    shares with the reason). Refused on today's trades (the day is not over) and days the market was closed."""
    trade = _trade(db, trade_id)
    day = _ny_day(trade.opened_at)
    pr._past_day(day.isoformat(), now)  # today's session is live paper, not replay
    hours = pr.regular(day)
    if hours is None:
        raise pr.ReplayError(f"The market was closed on {day:%b %-d}.", 409)
    symbol = pr.ticker(trade.ticker)
    entry = _ny_epoch(trade.opened_at)
    before = entry - BEFORE_MINUTES * 60
    before_at = None if before < hours[0] or before >= hours[1] - 60 else int(before) - int(before) % 60
    before_reason = None
    if before_at is None:
        where = ("before the open" if entry < hours[0] else "within 15 minutes of the open" if before < hours[0]
                 else "too late in the session to start before it")
        before_reason = f"Your first entry was {where}, so the redo starts at the open."
    contract, shares_reason = None, None
    if trade.instrument_type == "option":
        off = ro.off_reason(day, now)
        if off:
            shares_reason = off
        elif trade.option_type not in ("call", "put") or trade.strike is None or trade.expiration is None:
            shares_reason = "This trade's contract cannot be named, so the redo starts on shares."
        else:
            try:
                spec = pb.contract({"symbol": symbol, "instrument": "option", "option_type": trade.option_type,
                                    "expiry": trade.expiration.isoformat(), "strike": float(trade.strike)}, day)
                contract = {"option_type": spec["option_type"], "expiry": spec["expiry"],
                            "strike": spec["legs"][0]["strike"], "label": spec["label"]}
            except pb.PaperError as exc:
                shares_reason = f"{exc} The redo starts on shares."
    return {"trade_id": str(trade.id), "day": day.isoformat(), "symbol": symbol, "label": _label(trade),
            "instrument": "option" if trade.instrument_type == "option" else "stock", "contract": contract,
            "shares_reason": shares_reason, "open_at": hours[0], "close_at": hours[1], "before_at": before_at,
            "before_reason": before_reason}


def start(db: Session, body: dict, now: float) -> dict:
    """Start a redo: a replay run on the trade's day with its ``redo`` link, its clock at the open (``start`` open) or
    15 minutes before the first entry (``start`` before)."""
    found = plan(db, body.get("trade_id"), now)
    where = body.get("start") or "open"
    if where not in ("open", "before"):
        raise pr.ReplayError("Start at the open or before your entry.")
    if where == "before" and found["before_at"] is None:
        raise pr.ReplayError(found["before_reason"], 409)
    at = found["open_at"] if where == "open" else found["before_at"]
    run = pr.start(db, {"day": found["day"]}, now)
    db.add(PaperEvent(run_id=run.id, position_id=run.id, kind=KIND, order_key=f"redo:{run.id}",
                      effective_at=datetime.fromtimestamp(at, UTC).replace(tzinfo=None),
                      data_json=json.dumps({"trade_id": found["trade_id"], "start": where, "at": at}, sort_keys=True)))
    db.commit()
    return {**pr.view(db, run, at), "redo": {**found, "start": where, "start_at": at}}


# --- the comparison --------------------------------------------------------------------------------------------------

def _real(trade: Trade) -> dict:
    """The journal row as one side. An option's journal prices are dollars a contract (docs/agent/domain-rules.md):
    shown a share, as the paper book's are. ``quantity`` is the most held at once, the journal's ``contracts``."""
    opened, closed = _ny_epoch(trade.opened_at), _ny_epoch(trade.closed_at)
    per = 100.0 if trade.instrument_type == "option" else 1.0
    exit_price = trade.avg_exit_premium
    if exit_price is None and trade.status == "expired":
        exit_price = 0.0
    held = trade.hold_duration_mins if trade.hold_duration_mins is not None else round((closed - opened) / 60)
    return {"label": _label(trade), "instrument": "option" if trade.instrument_type == "option" else "stock",
            "quantity": float(trade.contracts), "entry": {"price": round(float(trade.avg_entry_premium) / per, 4), "at": opened},
            "exit": {"price": None if exit_price is None else round(float(exit_price) / per, 4), "at": closed},
            "pnl": None if trade.realized_pnl is None else round(float(trade.realized_pnl), 2), "held_minutes": int(held),
            "expired": trade.status == "expired",
            "overnight": _ny_day(trade.closed_at) != _ny_day(trade.opened_at), "closed_day": _ny_day(trade.closed_at).isoformat()}


def _weighted(pairs: list[tuple[float, float]]) -> float | None:
    total = sum(q for _, q in pairs)
    return None if total <= 0 else round(sum(p * q for p, q in pairs) / total, 4)


def _most_held(closed: list[dict]) -> float:
    """The most held at once across the redo's positions, as the journal sizes a trade (its ``contracts``)."""
    steps = sorted([(p["opened_at"], 1, p["quantity"]) for p in closed] + [(x["at"], 0, -x["quantity"]) for p in closed for x in p["exits"]])
    held = most = 0.0
    for _, _, qty in steps:  # at one moment an exit counts before an entry
        held += qty
        most = max(most, held)
    return float(most)


def _redo(closed: list[dict]) -> dict | None:
    """The redo run's closed trades as one side: size-weighted entry and exit prices a share, first entry, last exit,
    the most held at once and total P&L. Shares and options together have no one price or size: those read None."""
    if not closed:
        return None
    exits = [x for p in closed for x in p["exits"]]
    first, last = min(p["opened_at"] for p in closed), max(x["at"] for x in exits)
    kinds = {p["instrument"] for p in closed}
    labels = {p["label"] for p in closed}
    mixed = len(kinds) > 1
    return {"label": next(iter(labels)) if len(labels) == 1 else f"{len(closed)} trades",
            "instrument": "mixed" if mixed else next(iter(kinds)), "trades": len(closed),
            "quantity": None if mixed else _most_held(closed),
            "entry": {"price": None if mixed else _weighted([(abs(p["per_share"]), p["quantity"]) for p in closed]), "at": first},
            "exit": {"price": None if mixed else _weighted([(abs(x["per_share"]), x["quantity"]) for x in exits]), "at": last},
            "pnl": round(sum(p["realized"] for p in closed), 2), "held_minutes": int(round((last - first) / 60))}


def _span(minutes: float) -> str:
    minutes = int(round(abs(minutes)))
    hours, rest = divmod(minutes, 60)
    return f"{hours} h {rest} min" if hours and rest else f"{hours} h" if hours else f"{rest} min"


def _unit(instrument: str, qty: float) -> str:
    return ("contract" if qty == 1 else "contracts") if instrument == "option" else ("share" if qty == 1 else "shares")


def note(real: dict, redo: dict | None, left_open: int = 0) -> str:
    """One plain line of what changed, from the facts only: skipped it; shares instead of the option; entered or exited earlier or later (5 minutes or more apart); smaller or bigger size. At most three parts."""
    if redo is None:
        return "You skipped it: no trade in the redo." + (f" {left_open} still open." if left_open else "")
    parts: list[str] = []
    if redo["instrument"] != real["instrument"]:
        parts.append("traded shares instead of the option" if redo["instrument"] == "stock"
                     else "traded an option instead of shares" if redo["instrument"] == "option" else "traded shares and options")
    entered = (redo["entry"]["at"] - real["entry"]["at"]) / 60
    if abs(entered) >= SAME_MINUTES:
        parts.append(f"entered {_span(entered)} {'later' if entered > 0 else 'earlier'}")
    if real["overnight"]:
        parts.append("sold the same day (the real one was held overnight)")
    else:
        exited = (redo["exit"]["at"] - real["exit"]["at"]) / 60
        if abs(exited) >= SAME_MINUTES:
            parts.append(f"exited {_span(exited)} {'later' if exited > 0 else 'earlier'}")
    if redo["instrument"] == real["instrument"] and redo["quantity"] is not None and abs(redo["quantity"] - real["quantity"]) > 1e-9:
        unit = _unit(real["instrument"], real["quantity"])
        parts.append(f"{'smaller' if redo['quantity'] < real['quantity'] else 'bigger'} size "
                     f"({redo['quantity']:g} vs {real['quantity']:g} {unit})")
    text = ", ".join(parts[:3]) if parts else "same entry, exit and size within 5 minutes; only the prices differed"
    text = text[0].upper() + text[1:] + "."
    return text + (f" {left_open} still open." if left_open else "")


def compare(db: Session, run_id) -> dict:
    """The redo beside the real trade: each side's entry, exit, P&L and time held, the difference (redo less real) and
    the line of what changed. A position still open in the redo is counted as open, never guessed at."""
    run: PaperRun = pr._run(db, run_id)
    events = pb._events(db, run)
    found = pr.redo_link(events)
    if found is None:
        raise pr.ReplayError("This replay is not a redo of a real trade.", 404)
    trade = db.get(Trade, uuid.UUID(found["trade_id"]))
    if trade is None:
        raise pr.ReplayError("The original trade is no longer in the journal.", 404)
    positions = pb.fold(events)
    closed = [p for p in positions if p["status"] != "open"]
    left_open = sum(1 for p in positions if p["status"] == "open")
    real, redo = _real(trade), _redo(closed)
    redo_pnl = 0.0 if redo is None else redo["pnl"]
    difference = None if real["pnl"] is None else round(redo_pnl - real["pnl"], 2)
    return {"run_id": str(run.id), "trade_id": str(trade.id), "day": run.replay_day.isoformat(), "start": found.get("start"),
            "real": real, "redo": redo, "left_open": left_open, "difference": difference, "note": note(real, redo, left_open)}


# --- redo my worst ---------------------------------------------------------------------------------------------------

def worst(db: Session, days: list[dict], count: int = WORST_SHOWN) -> list[dict]:
    """His ``count`` biggest real losing trades opened on one of Replay's ``days`` (closed, Webull and not-followed
    tickers left out), biggest loss first."""
    from app.ai.copilot_book import _not_webull
    from app.engine import day_journal
    offered = {d["date"] for d in days}
    if not offered:
        return []
    first = date.fromisoformat(min(offered))
    last = date.fromisoformat(max(offered)) + timedelta(days=1)
    hidden = day_journal.quiet(db)
    rows = db.exec(select(Trade).join(Account, Account.id == Trade.account_id).where(_not_webull())
                   .where(Trade.status != "open", col(Trade.realized_pnl).is_not(None), Trade.realized_pnl < 0)
                   .where(Trade.opened_at >= datetime(first.year, first.month, first.day),
                          Trade.opened_at < datetime(last.year, last.month, last.day))
                   .order_by(col(Trade.realized_pnl), col(Trade.opened_at))).all()
    out = []
    for trade in rows:
        day = _ny_day(trade.opened_at).isoformat()
        if day not in offered or trade.ticker.upper() in hidden or not pr.TICKER.match(trade.ticker.upper()):
            continue
        out.append({"trade_id": str(trade.id), "day": day, "symbol": trade.ticker.upper(), "label": _label(trade),
                    "instrument": "option" if trade.instrument_type == "option" else "stock",
                    "pnl": round(float(trade.realized_pnl), 2), "opened_at": _ny_epoch(trade.opened_at)})
        if len(out) >= count:
            break
    return out
