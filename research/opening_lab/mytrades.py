"""Replay Claude at the owner's own opening option entries.

For each journal option trade opened 09:30-10:29 ET, a packet is frozen at the
entry minute E with what was knowable then (bars that ended by E, headlines by
E - 60 s), and Claude is asked blind - without being told what the owner did -
whether to buy short-dated CALLS, PUTS or PASS on that stock right now.

The packet holds the stock (its bars and features, plus up to
``STOCK_NEWS_LIMIT`` headlines that name it), SPY and QQQ, the cross-market
section and index-level headlines and macro, as in the full variant. SPXW
trades use SPY as the underlying (same index, one tenth the price). The stock's
rvol is null: volume profiles exist only for SPY and QQQ.

Grading compares Claude's call with the owner's on the same moment:
- the owner's real result (realized P&L and P&L %, from the journal);
- the underlying's move 15 and 30 minutes after the minute following entry
  (``trades.price_at``), signed by each side: who called the direction?

Journal trades are read from a JSON list exported from the journal API
(``/trades``); they stay in the gitignored ``.cache``.
"""

from datetime import date, timedelta

from . import data
from . import packet as pk
from .contract import ET, SYMBOLS, checkpoint_ts, et_datetime
from .cross import cross_block
from .trades import price_at

VERSION = "opening-lab-mytrade-v1"
WINDOW = ("09:30", "10:30")
FIRST_DAY = "2026-07-01"   # replay only after the models' training cutoffs
STOCK_NEWS_LIMIT = 8
HORIZONS = (15, 30)
UNDERLYING = {"SPXW": "SPY", "SPX": "SPY", "XSP": "SPY", "NDXP": "QQQ"}
STOCK_DIR = data.CACHE_DIR / "stocks"

DECISION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["action", "reason"],
    "properties": {
        "action": {"type": "string", "enum": ["CALLS", "PUTS", "PASS"]},
        "reason": {"type": "string", "description": "At most 400 characters."},
    },
}


def validate_call(value):
    if not isinstance(value, dict) or set(value) != {"action", "reason"}:
        raise ValueError("call_fields")
    if value["action"] not in ("CALLS", "PUTS", "PASS"):
        raise ValueError("call_action")
    if not isinstance(value["reason"], str) or len(value["reason"]) > 400:
        raise ValueError("call_reason")
    return {"action": value["action"], "reason": value["reason"]}


def select_trades(journal):
    """Option trades opened in the window on or after FIRST_DAY, oldest first."""
    out = []
    for t in journal:
        day, hhmm = t["opened_at"][:10], t["opened_at"][11:16]
        if (t.get("instrument_type") == "option" and t.get("option_type") in ("call", "put")
                and WINDOW[0] <= hhmm < WINDOW[1] and day >= FIRST_DAY):
            out.append({"id": t["id"], "ticker": t["ticker"], "underlying": UNDERLYING.get(t["ticker"], t["ticker"]),
                        "date": day, "entry_et": hhmm, "side": t["option_type"],
                        "strike": t.get("strike"), "expiration": t.get("expiration"),
                        "realized_pnl": t.get("realized_pnl"), "pnl_pct": t.get("pnl_pct"),
                        "hold_minutes": t.get("hold_duration_mins"), "status": t.get("status")})
    return sorted(out, key=lambda r: (r["date"], r["entry_et"], r["id"]))


# Stock data (raw SIP minutes 04:00-11:00 and raw daily bars, cached) ---------------
def _minutes_path(sym, day):
    return STOCK_DIR / "minutes" / sym / f"{day}.json"


def _daily_path(sym):
    return STOCK_DIR / "daily" / f"{sym}.json"


def ensure_stocks(picks, *, fetch=False):
    if not fetch:
        return
    by_sym = {}
    for p in picks:
        if p["underlying"] not in SYMBOLS:
            by_sym.setdefault(p["underlying"], set()).add(p["date"])
    for sym, days in sorted(by_sym.items()):
        for day in sorted(days):
            if data._read_json(_minutes_path(sym, day)) is None and data._session_complete(day):
                raw = data._fetch_bars("1Min", et_datetime(day, data.WINDOW_START),
                                       et_datetime(day, data.WINDOW_END), (sym,))
                data._write_json(_minutes_path(sym, day), data.normalize_bars(raw[sym], day)[0])
        have = {b["date"] for b in data._read_json(_daily_path(sym)) or []}
        want_start = (date.fromisoformat(min(days)) - timedelta(days=50)).isoformat()
        if not have or min(have) > want_start or max(have) < max(days):
            raw = data._fetch_bars("1Day", et_datetime(want_start, "00:00"), et_datetime(max(days), "20:00"), (sym,))
            bars = [b for b in (data._daily_bar(r) for r in raw[sym]) if b and data._session_complete(b["date"])]
            data._write_json(_daily_path(sym), sorted(bars, key=lambda b: b["date"]))


def stock_data(sym, day, session):
    if sym in SYMBOLS:
        return session["symbols"][sym]
    minutes = data._read_json(_minutes_path(sym, day))
    if not minutes:
        return None
    daily = [b for b in data._read_json(_daily_path(sym)) or [] if b["date"] < day][-data.DAILY_SESSIONS:]
    return {"minutes": minutes, "daily": daily, "volume_profile": {}}


# Packet ---------------------------------------------------------------------
def _stock_news(items, symbol, c_ts):
    cutoff = c_ts - pk.NEWS_LAG_SECONDS
    rows, seen = [], set()
    for item in sorted(items or [], key=lambda i: pk._parse_utc(i["created_at"]), reverse=True):
        created = int(pk._parse_utc(item["created_at"]).timestamp())
        key = " ".join((item.get("headline") or "").lower().split())
        if created > cutoff or key in seen or symbol not in (item.get("symbols") or []):
            continue
        seen.add(key)
        rows.append({"age_min": (c_ts - created) // 60, "headline": pk._clip(item.get("headline"), pk.HEADLINE_CHARS),
                     "summary": pk._clip(item.get("summary"), pk.SUMMARY_CHARS)})
        if len(rows) == STOCK_NEWS_LIMIT:
            break
    return rows


def build_mytrade_packet(session, pick, stock):
    """Causal packet at the owner's entry minute (nothing about the owner's trade)."""
    day = session["date"]
    schedule = session.get("schedule") or {}
    open_ts = checkpoint_ts(day, schedule.get("open") or "09:30")
    c_ts = checkpoint_ts(day, pick["entry_et"])
    sym = pick["underlying"]
    return {
        "version": VERSION,
        "checkpoint_et": pick["entry_et"],
        "weekday": date.fromisoformat(day).strftime("%A"),
        "minutes_since_open": (c_ts - open_ts) // 60,
        "early_close": bool(schedule.get("early_close", False)),
        "stock": {"symbol": sym, **pk._symbol_block(stock, day, open_ts, c_ts, "full")},
        "index": {s: pk._symbol_block(session["symbols"][s], day, open_ts, c_ts, "full") for s in SYMBOLS},
        "cross": cross_block(session, c_ts),
        "stock_news": _stock_news(session.get("news"), sym, c_ts),
        "news": pk._news(session.get("news"), c_ts),
        "macro": pk._macro(session.get("macro"), day, c_ts),
    }


# Outcomes and scoring -----------------------------------------------------------
def moves(stock, day, entry_et):
    """Underlying move in bps from the minute after entry, at each horizon (None if missing)."""
    by_t = {b["t"]: b for b in stock["minutes"]}
    start = checkpoint_ts(day, entry_et) + 60
    entry = price_at(by_t, start)
    out = {}
    for h in HORIZONS:
        later = price_at(by_t, start + h * 60)
        out[h] = None if entry is None or later is None else round((later / entry - 1) * 1e4, 2)
    return out


def _side(action):
    return {"CALLS": 1, "call": 1, "PUTS": -1, "put": -1}.get(action, 0)


def score(results):
    """results: [{pick, call (CALLS/PUTS/PASS or None), moves}] -> summary dict."""
    rows = [r for r in results if r["call"] is not None]

    def stats(group):
        pnl = [r["pick"]["realized_pnl"] for r in group if r["pick"]["realized_pnl"] is not None]
        pct = [r["pick"]["pnl_pct"] for r in group if r["pick"]["pnl_pct"] is not None]
        return {"trades": len(group), "wins": sum(p > 0 for p in pnl),
                "total_pnl": round(sum(pnl), 2), "avg_pnl_pct": round(100 * sum(pct) / len(pct), 1) if pct else None}

    def relation(r):
        c = _side(r["call"])
        return "pass" if c == 0 else ("agree" if c == _side(r["pick"]["side"]) else "opposite")

    groups = {k: [r for r in rows if relation(r) == k] for k in ("agree", "opposite", "pass")}
    direction = {}
    for h in HORIZONS:
        yours = [r for r in rows if r["moves"][h] is not None]
        claude = [r for r in yours if _side(r["call"])]
        direction[f"{h}m"] = {
            "yours_right": f"{sum(_side(r['pick']['side']) * r['moves'][h] > 0 for r in yours)}/{len(yours)}",
            "claude_right": f"{sum(_side(r['call']) * r['moves'][h] > 0 for r in claude)}/{len(claude)}",
            "avg_signed_move_bps_yours": round(sum(_side(r['pick']['side']) * r['moves'][h] for r in yours)
                                               / len(yours), 1) if yours else None,
            "avg_signed_move_bps_claude": round(sum(_side(r['call']) * r['moves'][h] for r in claude)
                                                / len(claude), 1) if claude else None,
        }
    return {"answered": len(rows), "unanswered": len(results) - len(rows),
            "all": stats(rows), **{k: stats(v) for k, v in groups.items()},
            "only_agreed": stats(groups["agree"]), "direction": direction}


def render(summary, results):
    s = summary
    lines = [f"Claude at your opening option entries - {s['answered']} trades answered "
             f"({s['unanswered']} unanswered)", ""]
    lines.append(f"{'':<34}{'trades':>7}{'wins':>6}{'your P&L $':>12}{'avg P&L %':>11}")
    for key, label in (("all", "all your trades"), ("agree", "Claude agreed"),
                       ("opposite", "Claude took the other side"), ("pass", "Claude would pass")):
        g = s[key]
        avg = "-" if g["avg_pnl_pct"] is None else f"{g['avg_pnl_pct']:.1f}"
        lines.append(f"{label:<34}{g['trades']:>7}{g['wins']:>6}{g['total_pnl']:>12.0f}{avg:>11}")
    lines += ["", "Who called the underlying's direction (from the minute after entry):"]
    for h, d in s["direction"].items():
        lines.append(f"  {h}: you {d['yours_right']} (avg {d['avg_signed_move_bps_yours']} bp your way); "
                     f"Claude {d['claude_right']} when it picked a side (avg {d['avg_signed_move_bps_claude']} bp)")
    lines += ["", "Trades:"]
    for r in results:
        p, m = r["pick"], r["moves"]
        lines.append(f"  {p['date']} {p['entry_et']} {p['ticker']:<5} you {p['side']:<4} "
                     f"P&L {p['realized_pnl'] if p['realized_pnl'] is not None else '-':>8} | Claude {r['call'] or '-':<5} "
                     f"| move 15m {m[15]} 30m {m[30]} | {(r.get('reason') or '')[:140]}")
    return "\n".join(lines)


def replay(run_dir, picks, *, sessions, model, model_name, workers=2, log=print):
    """Ask ``model`` once per pick; resumable (Run store, keyed by trade id)."""
    from concurrent.futures import ThreadPoolExecutor

    from .runner import RETRYABLE, Run, _record, source_fingerprint

    run = Run(run_dir, {"kind": "mytrades", "trades": [p["id"] for p in picks], "model": model_name,
                        "model_settings": getattr(model, "settings", None), "source": source_fingerprint()})

    def one(pick):
        session = sessions.get(pick["date"])
        stock = stock_data(pick["underlying"], pick["date"], session) if session else None
        if stock is None:
            log(f"skip {pick['date']} {pick['ticker']}: no data")
            return None
        key = (pick["date"], pick["entry_et"], model_name, pick["id"])
        row = run.records.get(key)
        if row is None or row["status"] in RETRYABLE:
            packet = build_mytrade_packet(session, pick, stock)
            row = _record(pick["date"], pick["entry_et"], model_name, pick["id"], packet, model.forecast(packet))
            run.add(row, packet)
        forecast = row["forecast"] if row["status"] == "ok" else None
        return {"pick": pick, "call": forecast["action"] if forecast else None,
                "reason": forecast["reason"] if forecast else row.get("error"),
                "moves": moves(stock, pick["date"], pick["entry_et"])}

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        results = [r for r in pool.map(one, picks) if r is not None]
    return run, results
