"""The desk's day report, the server's part (docs/copilot-lab.md § The desk): what the app scored on its own so the owner
never has to rate anything. Read-only; no provider fetch, no model, no write.

**Checked calls** (``engine/call_check.py`` keeps each with the underlying's price and the contract's quote at the moment
he checked). A call is scored from *that* price, never from the one in the Discord post, to the underlying's regular
session close on the check's New York day:

- the underlying's close comes from the chart cache on disk (a completed session's minutes) or, for today after 16:00,
  from the chart feed's response cache when it was read after the close; never a request;
- the contract's close comes from the options feed's cached chain for that expiry when it was read after today's close;
  a past day's contract is measured only if an earlier read scored it (a measured score is kept in memory per check);
- either price missing is "not measured", with the reason. A check made after the close, one with no stored price, and
  one from the fake backend (``simulated``) are not measured either.

``way`` is what the owner would have held: the contract's move when both of its prices are known, otherwise the stock's
(reversed for a put). ``up`` or ``down`` is that move's sign; ``flat`` is exactly zero. A passed call is scored the
same flat way as a planned one. Counts and percentages only: no advice, no "missed".

**Entries today**: the trades opened today (New York) and how many had a plan saved before the fill
(``plan_streak.streak``'s ``planned`` state), tickers the owner does not follow left out.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, time as wall_time, timedelta

from sqlmodel import Session, col, select

from app.engine import call_check, day_journal
from app.engine.chart_math import ET

log = logging.getLogger(__name__)

WINDOW_DAYS = 30
MAX_CHECKS = 200
CLOSE = wall_time(16, 0)
_scored: dict[str, dict] = {}  # a finished day's measured scores, by check id; bounded
_closes: dict[tuple[str, date], float] = {}  # a finished session's close, by symbol and day; bounded
CACHE_CAP = 512


def _remember(store: dict, key, value) -> None:
    if len(store) >= CACHE_CAP:
        store.clear()
    store[key] = value


def _close_epoch(day: date) -> float:
    return datetime.combine(day, CLOSE, ET).timestamp()


def _last_regular_close(bars: list[dict], day: date) -> float | None:
    """The close of the last minute that started before 16:00 New York on ``day`` (the regular session's last bar)."""
    end = _close_epoch(day)
    start = datetime.combine(day, wall_time(9, 30), ET).timestamp()
    regular = [b for b in bars if start <= b["time"] < end]
    if not regular or end - regular[-1]["time"] > 15 * 60:  # a session cut short in the cache is not the close
        return None
    close = regular[-1].get("close")
    return float(close) if close else None


def underlying_close(symbol: str, day: date, now: float) -> float | None:
    """The symbol's regular-session close on ``day``, or None. Disk first (``ping_images.stored_bars``); for today after
    16:00, the chart feed's cached minutes if they were read after the close. Never a provider request."""
    key = (symbol, day)
    if key in _closes:
        return _closes[key]
    from app.engine import ping_images
    close = _last_regular_close(ping_images.stored_bars(symbol, day), day)
    if close is None and day == datetime.fromtimestamp(now, ET).date() and now >= _close_epoch(day):
        try:
            from app.engine.chart_feed import chart_feed
            cached = chart_feed.peek_minutes(symbol, day)
        except Exception as exc:  # noqa: BLE001 -- the cache is extra; an unreadable one is "not measured"
            log.warning("day report cached minutes unreadable for %s: %s", symbol, exc)
            cached = None
        if cached and cached[1] >= _close_epoch(day) + 30:  # read after the closing bell settled
            close = _last_regular_close(cached[0], day)
    if close is not None:
        _remember(_closes, key, close)
    return close


def contract_close(symbol: str, reading: dict, day: date, now: float) -> float | None:
    """The contract's mid from the options feed's cached chain, only when that chain was read after today's close;
    None for any other day (the feed keeps today's chains only) or when it is not cached."""
    if day != datetime.fromtimestamp(now, ET).date() or now < _close_epoch(day):
        return None
    try:
        from app.engine.options_feed import options_feed
        found = options_feed.cached_contract(symbol, date.fromisoformat(reading["expiry"]), float(reading["strike"]), reading["side"])
    except Exception as exc:  # noqa: BLE001 -- the cache is extra
        log.warning("day report cached contract unreadable for %s: %s", symbol, exc)
        return None
    if not found or found["fetched"] < _close_epoch(day) + 30:
        return None
    return found.get("mid")


def _pct(after: float, before: float) -> float:
    return round((after / before - 1) * 100, 2) + 0.0  # + 0.0: never "-0"


def _way(pct: float | None) -> str | None:
    return None if pct is None else "up" if pct > 0 else "down" if pct < 0 else "flat"


def _not_measured(check: dict, why: str) -> dict:
    return {**_base(check), "state": "not_measured", "why": why, "way": None}


def _base(check: dict) -> dict:
    r = check["reading"]
    passed = check["outcome"] == "passed"
    return {"id": check["id"], "checked_at": check["checked_at"], "day": check["day"], "symbol": check["symbol"],
            "label": contract_label(check), "verdict": check["verdict"],
            "decision": "planned" if check["planned"] else "passed" if passed else "neither",
            "side": r.get("side")}


def contract_label(check: dict) -> str:
    r = check["reading"]
    if r.get("expiry") and r.get("strike") and r.get("side") and check["symbol"]:
        when = date.fromisoformat(r["expiry"])
        return f"{check['symbol']} {when.month}/{when.day} {r['strike']:g}{r['side'][0].upper()}"
    return check["symbol"] or "No ticker read"


def score(check: dict, now: float) -> dict:
    """One check, scored (see the module text). ``state``: ``measured`` or ``not_measured`` with ``why``."""
    cached = _scored.get(check["id"])
    if cached:
        return cached
    symbol, day = check["symbol"], date.fromisoformat(check["day"])
    if not symbol:
        return _not_measured(check, "no ticker was read")
    quote = check.get("quote") or {}
    if quote.get("simulated"):
        return _not_measured(check, "the price at the check was simulated")
    before = check.get("underlying_price")
    if not before or before <= 0:
        return _not_measured(check, "no price was stored when you checked")
    checked = datetime.fromisoformat(check["checked_at"].replace("Z", "+00:00")).timestamp()
    if checked >= _close_epoch(day):
        return _not_measured(check, "checked after the close")
    after = underlying_close(symbol, day, now)
    if after is None:
        return _not_measured(check, "no closing price stored yet" if day >= datetime.fromtimestamp(now, ET).date() else "no closing price stored")
    out = {**_base(check), "state": "measured", "why": None,
           "stock": {"at_check": before, "close": round(after, 2), "pct": _pct(after, before)},
           "contract": None, "basis": "stock"}
    r = check["reading"]
    stored = (quote.get("contract") or {})
    mid_then = stored.get("mid") if stored.get("state") == "ok" else None
    contract_wanted = bool(r.get("expiry") and r.get("strike") and r.get("side"))
    if contract_wanted and mid_then:
        mid_after = contract_close(symbol, r, day, now)
        if mid_after:
            out["contract"] = {"at_check": mid_then, "close": mid_after, "pct": _pct(mid_after, mid_then)}
            out["basis"] = "contract"
    pct = out["contract"]["pct"] if out["contract"] else (-out["stock"]["pct"] if r.get("side") == "put" else out["stock"]["pct"])
    out["way"] = _way(pct + 0.0)
    out["contract_note"] = (None if out["contract"] else "no contract identified" if not contract_wanted
                            else "no contract quote stored at the check" if not mid_then else "no contract close stored")
    today = datetime.fromtimestamp(now, ET).date()
    if day < today or out["contract"] or not contract_wanted or not mid_then:
        _remember(_scored, check["id"], out)  # final: nothing later can add to it
    return out


def _tally(rows: list[dict]) -> dict:
    return {"checked": len(rows), "up": sum(r["way"] == "up" for r in rows), "down": sum(r["way"] == "down" for r in rows),
            "flat": sum(r["way"] == "flat" for r in rows), "not_measured": sum(r["state"] == "not_measured" for r in rows)}


def checks_report(db: Session, today: date, now: float, hidden: set[str]) -> dict:
    """Today's checked calls scored, with ``today`` and ``window`` (the last ``WINDOW_DAYS`` days, today included)
    tallies. Tickers in ``hidden`` (not followed) are left out of both."""
    from app.models import CallCheck
    first = today - timedelta(days=WINDOW_DAYS - 1)
    found = db.exec(select(CallCheck).where(CallCheck.day >= first, CallCheck.day <= today)
                    .order_by(col(CallCheck.checked_at).desc()).limit(MAX_CHECKS)).all()
    found = [c for c in found if c.symbol not in hidden]
    planned = call_check._planned(db, [str(c.id) for c in found])
    scored = [score(call_check.view(c, str(c.id) in planned), now) for c in found]
    mine = [s for s in scored if s["day"] == today.isoformat()]
    return {"state": "ok", "rows": mine, "today": _tally(mine), "window": {"days": WINDOW_DAYS, **_tally(scored)},
            "capped": len(found) >= MAX_CHECKS}


def entries_today(db: Session, day: date, hidden: set[str]) -> dict:
    """The trades opened on ``day`` and how many had a plan saved before the fill, as the plan streak counts a week's
    entries; tickers in ``hidden`` left out."""
    from app.engine import plan_streak
    week = plan_streak.streak(db).get("this_week") or {}
    start = datetime.combine(day, wall_time(0), ET).timestamp()
    mine = [e for e in week.get("entries", []) if e["entry_time"] and start <= e["entry_time"] < start + 86400
            and e["short"].split(" ")[0] not in hidden]
    return {"state": "ok", "entries": len(mine), "planned": sum(e["state"] == "planned" for e in mine),
            "late": sum(e["state"] == "late" for e in mine), "pending": sum(e["state"] == "pending" for e in mine),
            "rows": [{"contract": e["short"], "state": e["state"], "at": e["entry_time"]} for e in sorted(mine, key=lambda e: e["entry_time"])]}


def not_followed(db: Session) -> set[str]:
    return day_journal.not_following(db)
