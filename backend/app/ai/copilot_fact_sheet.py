"""One symbol's facts on one page, for a deep read (the copilot's ``get_fact_sheet``; docs/copilot-lab.md § Fact sheet).

A turn has four rounds and eight tool calls. Reading price, tape, options, catalysts, peers, the owner's record and his
position one tool at a time spends them before the model can think, so this reads them side by side and hands back
the numbers that decide a short-dated trade, each with where it came from:

- **price**: last, day change, open against the prior close (the gap), the day's range; off hours, the extended move;
- **volume**: the regular session's time-of-day relative volume, or before the open the pre-market's volume so far
  against the same minutes of the five sessions before (``copilot_extended.premarket_pace``);
- **tape**: VWAP and the distance to it, the nearest level each side, the ATR;
- **implied move**: the at-the-money straddle for the nearest expiration and the nearest Friday, with each leg's
  spread as a share of its mid (what a round trip costs before the stock moves);
- **catalysts**: ``get_catalysts`` counted, its newest primary item (filing or halt) and newest headline, its note;
- **peers and market**: how many peers are up, the leader and laggard, SPY and QQQ;
- **record**: the owner's closed trades in the symbol (win rate, P&L, cut-rule breaks, best setup, worst mistake);
- **position**: each open position in the symbol with its mark and P&L, and for a short-dated long option the cut
  line (``fill_interrupts.cut_line``: 30% under the first entry) and how far the mark sits from it.

Every section stands alone: one that cannot be read says so in ``missing`` and never hides the rest. Numbers only; no
verdict, no model call, no write. It carries the owner's book, so it is offered on the desk and Telegram only, never to
a research job.
"""
from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from statistics import median
from typing import Callable

log = logging.getLogger(__name__)

MAX_POSITIONS_SHOWN = 6  # the sheet stays inside the tool result's 6,000 characters
READ_DEADLINE = 8.5  # every read, inside the copilot's 10 s tool timeout (get_catalysts keeps its own 7 s)
SHORT_DATED_DAYS = 3  # the cut-line rule's own window (fill_interrupts.BUILT_DAYS)
FIXTURE_NOTE = "SIMULATED demo fact sheet: the fixture's numbers, not live data."
REPLAY_REASON = "The fact sheet reads live quotes, chains, catalysts and the owner's book, so it is unavailable in replay."


def _num(value, digits: int = 2) -> float | None:
    return round(float(value), digits) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _pct(a, b) -> float | None:
    return round((a / b - 1) * 100, 2) if isinstance(a, (int, float)) and isinstance(b, (int, float)) and b else None


def _ok(d) -> bool:
    return isinstance(d, dict) and d.get("state") in ("ok", "ready", "partial")


# --------------------------------------------------------------------------- sections (pure)

def price(symbol: str, quotes: dict, chart: dict) -> dict | None:
    q = (quotes.get("quotes") or {}).get(symbol) if _ok(quotes) else None
    cq = chart.get("quote") if _ok(chart) else None
    if not q and not cq:
        return None
    q, cq = q or {}, cq or {}
    last = q.get("last") if q.get("last") is not None else cq.get("last")
    prev = cq.get("previous_close") or q.get("prev_close")
    out = {"last": _num(last), "change_pct": _num(q.get("change_pct") if q.get("change_pct") is not None else cq.get("change_pct")),
           "prev_close": _num(prev), "open": _num(cq.get("open")), "gap_pct": _pct(cq.get("open"), prev),
           "day_high": _num(cq.get("day_high") or q.get("day_high")), "day_low": _num(cq.get("day_low") or q.get("day_low")),
           "volume": cq.get("volume") or q.get("volume"), "as_of": q.get("trade_time") or cq.get("trade_time")}
    ext = (quotes.get("extended") or {}) if _ok(quotes) else {}
    row = (ext.get("symbols") or {}).get(symbol)
    if row:
        out["extended"] = {"phase": ext.get("phase"), **row}
    return {k: v for k, v in out.items() if v is not None}


def tape(chart: dict) -> dict | None:
    if not _ok(chart):
        return None
    last = chart.get("last")
    vwap = (chart.get("vwap") or {}).get("vwap")
    levels = chart.get("levels") or {}

    def nearest(rows: list[dict], side: str) -> dict | None:
        if not rows:
            return None
        r = rows[0]
        edge = r.get("low") if side == "above" else r.get("high")
        return {"label": r.get("label"), "low": r.get("low"), "high": r.get("high"), "state": r.get("state"),
                "distance_pct": _pct(edge, last)}
    rvol = chart.get("rvol") or {}
    out = {"vwap": _num(vwap), "vs_vwap_pct": _pct(last, vwap), "atr": _num(levels.get("atr")),
           "level_above": nearest(levels.get("above") or [], "above"), "level_below": nearest(levels.get("below") or [], "below"),
           "at_level": [r.get("label") for r in levels.get("at") or []] or None,
           "rvol": _num(rvol.get("last_bar")) if rvol.get("state") == "ready" else None,
           "rvol_state": rvol.get("state") if rvol.get("state") != "ready" else None}
    return {k: v for k, v in out.items() if v is not None}


def implied(forecast: dict | None) -> dict | None:
    """The straddles ``options_feed.forecast`` priced, with each leg's spread over its mid."""
    if not isinstance(forecast, dict) or not forecast.get("moves"):
        return None

    def spread(leg: dict | None) -> float | None:
        bid, ask = (leg or {}).get("bid"), (leg or {}).get("ask")
        if not isinstance(bid, (int, float)) or not isinstance(ask, (int, float)) or bid + ask <= 0:
            return None
        return round((ask - bid) / ((ask + bid) / 2) * 100, 1)
    rows = []
    for m in forecast["moves"]:
        row = {"expiration": m.get("expiration"), "days": m.get("days"), "tags": m.get("tags"), "state": m.get("state")}
        if m.get("state") == "ready":
            row.update(move=_num(m.get("move")), move_pct=_num((m.get("percent") or 0) * 100), strike=m.get("strike"),
                       call_spread_pct=spread(m.get("call")), put_spread_pct=spread(m.get("put")),
                       iv=_num((m.get("iv") or 0) * 100, 1) if m.get("iv") else None)
        elif m.get("reason"):
            row["reason"] = m["reason"]
        rows.append({k: v for k, v in row.items() if v is not None})
    return {"expirations": rows, "source": forecast.get("source")}


def catalysts(d: dict) -> dict | None:
    if not _ok(d):
        return None
    items = d.get("items") or []
    primary = next((i for i in items if i.get("type") in ("filing", "halt")), None)
    headline = next((i for i in items if i.get("type") == "headline"), None)
    out = {"since": d.get("since"),
           "counts": d.get("counts") or {t: sum(1 for i in items if i.get("type") == t) for t in ("filing", "halt", "headline")},
           "newest_primary": primary, "newest_headline": headline,
           "unexplained_moves": d.get("unexplained_moves") or None, "note": d.get("note"),
           "headlines_from": d.get("headlines_from"),  # only the newest page was read: the headline count is a floor
           "unavailable": {k: v for k, v in (d.get("sources") or {}).items() if v != "ok"} or None}
    return {k: v for k, v in out.items() if v is not None}


def peers(d: dict, quotes: dict) -> dict | None:
    rows = [p for p in (d.get("peers") or []) if isinstance(p.get("change_pct"), (int, float))] if isinstance(d, dict) else []
    market = {s: q.get("change_pct") for s, q in ((quotes.get("quotes") or {}).items() if _ok(quotes) else ())
              if s in ("SPY", "QQQ")}
    if not rows and not market:
        return None
    out: dict = {"market": market or None}
    if rows:
        ranked = sorted(rows, key=lambda p: p["change_pct"])
        out.update(up=sum(1 for p in rows if p["change_pct"] > 0), of=len(rows), median_pct=round(median(p["change_pct"] for p in rows), 2),
                   leader={"symbol": ranked[-1]["symbol"], "change_pct": ranked[-1]["change_pct"]},
                   laggard={"symbol": ranked[0]["symbol"], "change_pct": ranked[0]["change_pct"]})
    return {k: v for k, v in out.items() if v is not None}


def record(d: dict) -> dict | None:
    if not _ok(d):
        return None
    setups = sorted(d.get("setups") or [], key=lambda s: -(s.get("total_pnl") or 0))
    mistakes = sorted(d.get("top_mistakes") or [], key=lambda m: m.get("total_pnl") or 0)
    out = {"trades": d.get("trades"), "win_rate": d.get("win_rate"), "total_pnl": d.get("total_pnl"),
           "median_pnl": d.get("median_pnl"), "broke_cut_rule": d.get("broke_cut_rule"), "small_sample": d.get("small_sample"),
           "best_setup": setups[0] if setups else None, "worst_mistake": mistakes[0] if mistakes else None}
    return {k: v for k, v in out.items() if v is not None}


def position(symbol: str, book: dict, today: date) -> list[dict] | None:
    """The owner's open positions in ``symbol``; a long option within the cut-line window gets its cut line (dollars per
    contract, as marks are) and the mark's distance from it. A row's ``_cut`` is its own trade's cut line (``live_book``),
    so the same contract held twice never borrows the other's."""
    if not _ok(book):
        return None
    out = []
    for p in book.get("positions") or []:
        if p.get("symbol") != symbol:
            continue
        row = {k: p.get(k) for k in ("instrument", "direction", "quantity", "avg_entry", "mark", "unrealized_usd", "unrealized_pct")}
        opt = p.get("option") or {}
        if opt:
            row["option"] = opt
            try:
                dte = (date.fromisoformat(str(opt.get("expiry"))) - today).days
            except ValueError:
                dte = None
            row["days_to_expiry"] = dte
            cut = p.get("_cut")
            if cut is not None:
                row["cut_line"] = round(cut, 2)
                if isinstance(p.get("mark"), (int, float)):
                    row["mark_vs_cut_pct"] = _pct(p["mark"], cut)
                    row["past_cut"] = p["mark"] <= cut
            if (dte is not None and dte <= SHORT_DATED_DAYS and p.get("direction") == "long"
                    and isinstance(p.get("unrealized_pct"), (int, float)) and p["unrealized_pct"] < 0):
                row["short_dated_red"] = True  # the leak the edge audit measured: never answered with "hold"
        out.append({k: v for k, v in row.items() if v is not None})
    return out


def assemble(symbol: str, as_of: datetime, *, quotes: dict, chart: dict, forecast: dict | None, premarket: dict | None,
             catalyst: dict, peer: dict, mine: dict, book: dict) -> dict:
    tp = tape(chart)
    rvol = tp.pop("rvol", None) if tp else None
    volume = premarket or ({"kind": "regular session, time-of-day relative volume against 20 sessions", "rvol": rvol}
                           if rvol is not None else None)
    held = position(symbol, book, as_of.astimezone(_et()).date())
    omitted = 0
    if held and len(held) > MAX_POSITIONS_SHOWN:  # the ones near or past their cut first; the count of the rest is said
        held.sort(key=lambda r: (not r.get("past_cut"), not r.get("short_dated_red"), r.get("mark_vs_cut_pct") or 999))
        held, omitted = held[:MAX_POSITIONS_SHOWN], len(held) - MAX_POSITIONS_SHOWN
    sections = {
        "price": price(symbol, quotes, chart),
        "position": held,  # second: the risk is never what a long result loses to the size cap
        "volume": volume,
        "tape": tp,
        "implied_move": implied(forecast),
        "catalysts": catalysts(catalyst),
        "peers": peers(peer, quotes),
        "my_record": record(mine),
    }
    missing = [k for k, v in sections.items() if v is None]
    out: dict = {"symbol": symbol, "state": "ok" if not missing else "partial",
                 "as_of": as_of.astimezone(_et()).isoformat(timespec="minutes"), "missing": missing}
    if _ok(chart) and chart.get("delayed"):  # the chart's fallback: say so before any number it gave
        out["delayed"] = {"provider": chart.get("provider"),
                          "note": "The chart (tape, levels, VWAP, volume) is a delayed fallback, about 15 minutes behind; not live."}
    if held is not None and book.get("incomplete"):
        out["position_incomplete"] = book["incomplete"]
    if omitted:
        out["position_omitted"] = f"{omitted} more open position{'' if omitted == 1 else 's'} in {symbol} not shown"
    out.update({k: v for k, v in sections.items() if v is not None})
    return out


def _et():
    from app.engine.chart_math import ET
    return ET


# --------------------------------------------------------------------------- reads

def _safe(name: str, read: Callable[[], dict | None]) -> dict | None:
    try:
        return read()
    except Exception as exc:  # noqa: BLE001 - one failed section never hides the others
        log.info("fact sheet: %s unavailable: %s", name, type(exc).__name__)
        return {"state": "unavailable"}


def live_book(symbol: str) -> dict:
    """The owner's open positions in ``symbol``, read ahead of the book's limit (``first``), each long option with its own
    trade's cut line under ``_cut``: the cut joins by trade, never by contract, so two accounts holding the same contract
    at different entries keep their own lines."""
    from sqlmodel import Session
    from app.ai import copilot_book
    from app.database import engine
    from app.engine.fill_interrupts import cut_line
    from app.engine.position_alerts import open_positions
    with Session(engine) as db:
        live = copilot_book.live_or_unavailable(db)
        pairs, total = copilot_book.position_rows(db, first=symbol, live=live)
        cuts = {}
        for p in open_positions(db):
            t = p["trade"]
            if t.ticker == symbol and p.get("first_entry"):
                cut = cut_line({**p["first_entry"], "instrument_type": "option", "expiration": p["expiration"]}, [])
                if cut is not None:
                    cuts[str(t.id)] = cut
    rows = [{**row, "_cut": cuts.get(str(trade.id))} for trade, row in pairs if trade.ticker == symbol]
    rows += [r for r in (live or {}).get("new", []) if r.get("symbol") == symbol]
    out: dict = {"state": "ok", "positions": rows}
    if len(pairs) == copilot_book.MAX_POSITIONS < total and all(trade.ticker == symbol for trade, _ in pairs):
        out["incomplete"] = f"only the first {copilot_book.MAX_POSITIONS} of this symbol's open positions were read"
    return out


def live_sheet(evidence, symbol: str) -> dict:
    """Every read side by side under one deadline inside the tool's timeout: a section still reading then is missing,
    never a reason to lose the others. The implied move waits for the quote's price within the same deadline."""
    import time
    from concurrent.futures import ThreadPoolExecutor, wait
    from app.ai import copilot_extended
    from app.engine.options_feed import options_feed
    now = datetime.now(UTC)
    until = time.monotonic() + READ_DEADLINE
    pool = ThreadPoolExecutor(max_workers=9)
    jobs = {
        "quotes": pool.submit(_safe, "quotes", lambda: evidence.get_quotes([symbol, "SPY", "QQQ"])),
        "chart": pool.submit(_safe, "chart", lambda: evidence.get_chart_context(symbol, "5m")),
        "catalyst": pool.submit(_safe, "catalysts", lambda: evidence.get_catalysts(symbol)),
        "peer": pool.submit(_safe, "peers", lambda: evidence.get_peer_moves(symbol)),
        "mine": pool.submit(_safe, "record", lambda: evidence.get_my_record(symbol=symbol)),
        "book": pool.submit(_safe, "book", lambda: live_book(symbol)),
        "premarket": pool.submit(_safe, "premarket", lambda: copilot_extended.premarket_pace(symbol, now)),
    }

    def forecast() -> dict | None:
        quotes = jobs["quotes"].result(timeout=max(0.0, until - time.monotonic()))
        spot = ((quotes or {}).get("quotes") or {}).get(symbol, {}).get("last") if _ok(quotes) else None
        return options_feed.forecast(symbol, spot, None) if spot else None
    jobs["forecast"] = pool.submit(_safe, "implied move", forecast)
    done, _ = wait(jobs.values(), timeout=READ_DEADLINE)
    pool.shutdown(wait=False, cancel_futures=True)  # a slow read finishes on its own
    got = {k: (f.result() if f in done else None) for k, f in jobs.items()}
    premarket = got["premarket"] if isinstance(got["premarket"], dict) and got["premarket"].get("state") == "ok" else None
    forecast_read = got["forecast"] if isinstance(got["forecast"], dict) and got["forecast"].get("moves") else None
    return assemble(symbol, now, quotes=got["quotes"] or {}, chart=got["chart"] or {}, forecast=forecast_read, premarket=premarket,
                    catalyst=got["catalyst"] or {}, peer=got["peer"] or {}, mine=got["mine"] or {}, book=got["book"] or {})


def fixture_sheet(evidence, symbol: str, now: datetime) -> dict:
    forecast = {"source": "simulated", "moves": [
        {"tags": ["nearest", "friday"], "expiration": "2026-10-24", "days": 1, "state": "ready", "strike": 95.0, "move": 3.1,
         "percent": 0.0329, "iv": 0.84, "call": {"bid": 1.5, "ask": 1.65}, "put": {"bid": 1.4, "ask": 1.6}}]}
    out = assemble(symbol, now, quotes=evidence.get_quotes([symbol, "SPY", "QQQ"]), chart=evidence.get_chart_context(symbol, "5m"),
                   forecast=forecast, premarket=None, catalyst=evidence.get_catalysts(symbol), peer=evidence.get_peer_moves(symbol),
                   mine=evidence.get_my_record(symbol=symbol), book=evidence.get_positions())
    return {**out, "simulated": True, "note": FIXTURE_NOTE}
