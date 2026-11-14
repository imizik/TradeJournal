"""``get_paper_book``: the copilot's read of the owner's own paper book (docs/copilot-lab.md § Paper).

A compact view of ``paper_book.view`` and nothing else: no new math. The account (cash, buying power, value and P&L
at the desk's newest prices), open paper positions with their P&L and the time of the price behind it, his working
day limit orders, the latest closed paper trades with his note and how each ended against his stop and target,
and the scorecard beside his real closed trades over the same dates.

Read only: it never places, closes or changes a paper order, and it neither settles an expired option nor ends a day
order past its close (the desk's own minute read does both); each says so. Prices come from the desk's kept ticks
(``desk_ticks.kept_rows``: no quote read, no Robinhood call). A position without a price says so and is never zero; a
price carries its time. Tickers the owner does not follow are left out of the lists (their trades stay in the totals).
"""
from __future__ import annotations

import json
import logging
from datetime import UTC, date, datetime

log = logging.getLogger(__name__)

MAX_OPEN = 8
MAX_CLOSED = 8
NOTE_CHARS = 120
LIMIT = 5800  # under copilot_tools.MAX_RESULT_CHARS, so the answer is never cut mid-JSON
NO_ORDERS = "none working"


def _now_iso(now: float) -> str:
    return datetime.fromtimestamp(now, UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _note(text: str | None) -> str | None:
    if not text:
        return None
    return text if len(text) <= NOTE_CHARS else text[: NOTE_CHARS - 1] + "…"


def _stats(s: dict) -> dict:
    return {k: s.get(k) for k in ("trades", "pnl", "win_rate", "avg_win", "avg_loss", "largest_loss")}


def _open_row(p: dict, now: float, today: date) -> dict:
    from app.engine.paper_book import clock
    row = {"label": p["label"], "symbol": p["symbol"], "quantity": p["remaining"], "opened": clock(p["opened_at"]),
           "cash_at_open": p["basis"]}
    for key in ("stop", "target"):
        if p.get(key) is not None:
            row[key] = p[key]
    if note := _note(p.get("note")):
        row["note"] = note
    if p.get("expiry") and date.fromisoformat(p["expiry"]) < today:
        row["past_expiry"] = f"expired {p['expiry']}; it settles at the close on the desk's next read"
    if p.get("auto"):
        row["auto_exit"] = "on: it closes at the next fresh bid once the stock touches his stop or target"
    mark = p.get("mark")
    if mark is None:
        row["price"] = "none: the desk has no price for it yet, so its P&L is unknown"
    else:
        row.update(value=mark["value"], pnl=mark["pnl"], pnl_pct=mark["pct"], price_at=clock(mark["at"]),
                   price_age_minutes=max(0, round((now - mark["at"]) / 60)))
    return row


def _closed_row(c: dict) -> dict:
    from app.engine.paper_book import clock
    row = {"label": c["label"], "symbol": c["symbol"], "quantity": c["quantity"], "opened": clock(c["opened_at"]),
           "closed": clock(c["closed_at"]), "realized": c["realized"], "ended": (c.get("verdict") or {}).get("text"),
           "ended_kind": (c.get("verdict") or {}).get("kind")}
    if (c.get("verdict") or {}).get("auto"):
        row["auto_exit"] = True  # the close-at-stop/target switch sold it, not his own tap
    for key in ("stop", "target"):
        if c.get(key) is not None:
            row[key] = c[key]
    if note := _note(c.get("note")):
        row["note"] = note
    return row


def _orders(view: dict, now: float, hidden: set[str], symbol: str | None) -> list[dict] | str:
    """His working paper limit orders (day orders: each ends at the close), or the plain reason there are none."""
    from app.engine.paper_book import clock
    found = [o for o in view.get("orders") or [] if o.get("symbol") not in hidden and symbol in (None, o.get("symbol"))]
    if not found:
        return NO_ORDERS
    out = []
    for o in found[:MAX_OPEN]:
        row = {k: o[k] for k in ("side", "label", "symbol", "quantity", "limit", "stop", "target") if o.get(k) is not None}
        row["placed"] = clock(o["placed_at"]) if o.get("placed_at") else None
        if o.get("expires_at"):
            row["ends"] = (f"ended at the close ({clock(o['expires_at'])}); the desk's next read records it"
                           if now >= o["expires_at"] else f"at the close, {clock(o['expires_at'])}")
        if note := _note(o.get("note")):
            row["note"] = note
        out.append(row)
    return out


def compact(view: dict, hidden: set[str], now: float, symbol: str | None = None) -> dict:
    """The tool's answer from ``paper_book.view``: bounded, hidden tickers left out of the lists, ``symbol`` narrowing
    them to one ticker."""
    from app.engine.chart_math import ET
    from app.engine.paper_book import clock
    out = {"state": "ok", "as_of": _now_iso(now), "symbol": symbol,
           "note": "His paper book: practice with no money, fills at the live ask to buy and the bid to sell. Every price "
                   "has its time; a position without a price has no P&L yet. cash_at_open is the open part's cash at "
                   "the fill: negative is what he paid, positive a credit he took in; pnl is value plus cash_at_open. "
                   "Read only: nothing here places or changes a paper order."}
    run = view.get("run")
    if run is None:
        return {**out, "state": "none", "reason": "He has not started paper trading yet (the desk's Paper section starts it)."}
    acct = view["account"]
    out["run"] = {"number": run["number"], "started": clock(run["started_at"]), "starting_cash": run["starting_cash"]}
    account = {"cash": acct["cash"], "buying_power": acct["buying_power"], "held_for_spreads": acct["collateral"]}
    if acct.get("equity") is None:
        account["value"] = f"unknown: {acct.get('unpriced', 0)} open position(s) have no price yet"
    else:
        account.update(value=acct["equity"], pnl=acct["pnl"],
                       prices_at=clock(acct["prices_at"]) if acct.get("prices_at") else "no open positions")
    out["account"] = account
    today = datetime.fromtimestamp(now, ET).date()

    def shown(rows: list[dict]) -> list[dict]:
        return [r for r in rows if r["symbol"] not in hidden and (symbol is None or r["symbol"] == symbol)]
    positions, closed = shown(view.get("positions") or []), shown(view.get("closed") or [])
    left_out = sum(1 for r in (view.get("positions") or []) + (view.get("closed") or []) if r["symbol"] in hidden)
    out["open"] = [_open_row(p, now, today) for p in positions[:MAX_OPEN]]
    if len(positions) > MAX_OPEN:
        out["open_more"] = len(positions) - MAX_OPEN
    out["working_orders"] = _orders(view, now, hidden, symbol)
    out["closed"] = [_closed_row(c) for c in closed[:MAX_CLOSED]]  # newest first
    if len(closed) > MAX_CLOSED:
        out["closed_more"] = len(closed) - MAX_CLOSED
    if left_out:
        out["not_followed_left_out"] = f"{left_out} paper position(s) in tickers he does not follow; they stay in the totals"
    score = view["score"]
    out["score"] = {"since": clock(run["started_at"]), "paper": {**_stats(score["paper"]), "open_pnl": score["paper"].get("open_pnl")},
                    "real": _stats(score["real"]),
                    "note": "Closed trades only. Real is his journal's closed trades over the same dates (Webull left out); "
                            "a paper position counts once fully closed, on its close day."}
    if symbol is not None:
        out["score"]["note"] += " The score is the whole run, not just this ticker."
    return _fit(out)


def _fit(out: dict) -> dict:
    def size() -> int:
        return len(json.dumps(out, default=str, separators=(",", ":")))
    while size() > LIMIT and (out["closed"] or out["open"]):
        rows = out["closed"] if len(out["closed"]) >= len(out["open"]) or not out["open"] else out["open"]
        rows.pop()
        key = "closed_more" if rows is out["closed"] else "open_more"
        out[key] = out.get(key, 0) + 1
        out["trimmed"] = "the oldest rows left out to fit"
    return out


def live_paper_book(symbol: str | None = None, now: float | None = None) -> dict:
    import time
    from sqlmodel import Session
    from app.database import engine
    from app.engine import day_journal, paper_book
    at = time.time() if now is None else now
    with Session(engine) as db:
        view = paper_book.view(db, at, settle_expired=False)
        hidden = day_journal.quiet(db)
    return compact(view, hidden, at, symbol)


def fixture_paper_book(symbol: str | None = None) -> dict:
    """A SIMULATED paper book for the fixture backend: invented numbers, shaped like the live read."""
    open_ = [{"label": "NBIS $100 Call 11/20/26", "symbol": "NBIS", "quantity": 2, "opened": "Nov 12 10:41 AM ET", "cash_at_open": -680.0,
              "stop": 92.4, "target": 108.0, "note": "reclaim of the morning low", "value": 820.0, "pnl": 140.0, "pnl_pct": 20.6,
              "price_at": "Nov 13 3:58 PM ET", "price_age_minutes": 2}]
    closed = [{"label": "NBIS shares", "symbol": "NBIS", "quantity": 10, "opened": "Nov 10 9:52 AM ET", "closed": "Nov 11 2:15 PM ET",
               "realized": 84.5, "ended": "Took the target: stock 104.2 vs target 104", "ended_kind": "target", "stop": 96.0,
               "target": 104.0},
              {"label": "NBIS $105 Call 11/14/26", "symbol": "NBIS", "quantity": 1, "opened": "Nov 11 10:05 AM ET",
               "closed": "Nov 12 3:40 PM ET", "realized": -95.0, "ended": "Out at the stop: stock 95.1 vs stop 96, 0.9% past it",
               "ended_kind": "stop", "stop": 96.0}]
    return {"state": "ok", "as_of": "2026-11-13T21:00:00Z", "symbol": symbol,
            "note": "SIMULATED fixture paper book (invented numbers), shaped like his paper book.",
            "run": {"number": 1, "started": "Nov 10 9:30 AM ET", "starting_cash": 10000.0},
            "account": {"cash": 9309.5, "buying_power": 9309.5, "held_for_spreads": 0.0, "value": 10129.5, "pnl": 129.5,
                        "prices_at": "Nov 13 3:58 PM ET"},
            "open": [r for r in open_ if symbol in (None, r["symbol"])], "working_orders": NO_ORDERS,
            "closed": [r for r in closed if symbol in (None, r["symbol"])],
            "score": {"since": "Nov 10 9:30 AM ET",
                      "paper": {"trades": 2, "pnl": -10.5, "win_rate": 50.0, "avg_win": 84.5, "avg_loss": -95.0, "largest_loss": -95.0,
                                "open_pnl": 140.0},
                      "real": {"trades": 3, "pnl": -212.0, "win_rate": 33.3, "avg_win": 150.0, "avg_loss": -181.0, "largest_loss": -240.0},
                      "note": "Closed trades only (simulated)."}}
