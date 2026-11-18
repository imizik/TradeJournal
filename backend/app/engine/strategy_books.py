"""How the two QQQ strategy paper books are doing, for the copilot (``get_paper_book`` with ``book: "strategies"``) and
one line each in the Friday paper review (``engine/paper_review.py``).

The books are rule-based recorders that passed a research exam: QQQ overnight (``overnight_book``, #819) and QQQ
intraday momentum (``intraday_momentum_book``, #826). Each result here is the book's own: a night is (exit bid - entry
ask) / entry ask; a momentum day is the sum of its closed trades in basis points of the day's open, and a checked day
with no trade is a 0 day, as in the study. Dollars are at the book's own stake (``STAKE``), the way the desk shows them.

The backtest number is each book's ``BACKTEST`` mean per night or day; ``needed`` is roughly the fewest live results
before a live average like the backtest's could even be told from zero: the count at which the live 95% interval's
half-width (its margin) shrinks to the backtest mean, assuming the backtest's spread (backtest sample x (half the
interval / mean)^2). Below it the read says "too few to judge"; at or above it, it only compares, never a verdict.

Read only, from the books' own SQLite files: no provider call, no Robinhood call. A missing file is "no records", never
zero. Nothing here suggests a rule change: the books are judged after months, and the rules are fixed by their protocols.
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta

from app.engine import intraday_momentum_book as momentum
from app.engine import overnight_book as overnight
from app.engine.chart_math import ET

SYMBOL = "QQQ"
MISSED_SHOWN = 5
NOTE = ("Paper books that follow fixed research rules; no money. They are judged after months, not days, and these "
        "figures never change the rules.")
HIDDEN = "The strategy books trade a ticker on his Not-following list, so they stay silent."

SPECS = {
    "overnight": {"book": "QQQ overnight", "unit": "night", "stake": overnight.STAKE, "backtest": overnight.BACKTEST,
                  "sample": overnight.BACKTEST["nights"],
                  "rule": "buy QQQ at the 15:59 ask, sell at the next session's 09:30 bid"},
    "momentum": {"book": "QQQ intraday momentum", "unit": "day", "stake": momentum.STAKE, "backtest": momentum.BACKTEST,
                 "sample": 1213,  # exam sessions, research/notes/qqq-intraday-momentum-2026-11-14.md
                 "rule": "noise-area breakout at 1x: hourly checks 10:00 to 15:00, flat by 15:59",
                 "backtest_note": "in the exam about one day in five made money; most trading days were small stop-outs"},
}


def needed(spec: dict) -> int:
    low, high = spec["backtest"]["interval_bp"]
    mean = spec["backtest"]["mean_bp"]
    return math.ceil(spec["sample"] * (((high - low) / 2) / mean) ** 2)


def _usd(stake: float, bp: float) -> float:
    return round(stake * bp / 10_000, 2)


def _plural(n: int, unit: str) -> str:
    return f"{n} {unit}{'' if n == 1 else 's'}"


def _hhmm(minute: int) -> str:
    return f"{minute // 60:02d}:{minute % 60:02d}"


def _time(stamp: float | None) -> str | None:
    return None if stamp is None else datetime.fromtimestamp(stamp, ET).strftime("%Y-%m-%d %H:%M ET")


def report(key: str, units: list[dict], *, enabled: bool, recorded: bool, last: dict | None = None,
           missed: list[dict] | None = None, coverage: dict | None = None, holding: dict | None = None,
           trades: int | None = None) -> dict:
    """One book's figures. ``units``: each finished night or day, ``{"day", "bp"}`` (bp unrounded), oldest first.
    ``recorded``: the book's file exists on this server."""
    spec = SPECS[key]
    stake, unit, bt = spec["stake"], spec["unit"], spec["backtest"]
    n = len(units)
    out = {"book": spec["book"], "rule": spec["rule"], "unit": unit, "stake_usd": stake,
           "state": ("off" if not enabled else "holding" if holding else "recording") if recorded else "no records",
           "count": n}
    if key == "momentum":
        out["trades"] = trades
    bps = [u["bp"] for u in units]
    total = sum(bps)
    out.update({
        "from": units[0]["day"] if units else None, "to": units[-1]["day"] if units else None,
        "total_bp": round(total, 2) if n else None, "total_usd": _usd(stake, total) if n else None,
        "mean_bp": round(total / n, 2) if n else None, "mean_usd": _usd(stake, total / n) if n else None,
        "up": sum(1 for b in bps if b > 0) if n else None,
        "win_rate_pct": round(100 * sum(1 for b in bps if b > 0) / n, 1) if n else None,
    })
    need = needed(spec)
    out["backtest"] = {"mean_bp": bt["mean_bp"], "mean_usd": _usd(stake, bt["mean_bp"]), "interval_bp": bt["interval_bp"],
                       "sample": spec["sample"], "years": bt["years"], "per": unit}
    if spec.get("backtest_note"):
        out["backtest"]["note"] = spec["backtest_note"]
    out["vs_backtest"] = {"live_mean_bp": out["mean_bp"], "backtest_mean_bp": bt["mean_bp"],
                          "gap_bp": round(total / n - bt["mean_bp"], 2) if n else None, "sample": n, "needed": need,
                          "read": verdict(key, n, out["mean_bp"])}
    out["last"] = last
    out["missed_total"] = len(missed or [])
    out["missed"] = (missed or [])[-MISSED_SHOWN:][::-1]
    gaps = []
    if coverage and coverage.get("missing"):
        gaps.append(f"{coverage['missing']} expected record(s) in the last two weeks are missing, latest "
                    f"{coverage['latest_missing_day']}: the server was off or the book was not running")
    if coverage and coverage.get("unknown_days"):
        gaps.append(f"{coverage['unknown_days']} day(s) could not be checked against the market calendar")
    if gaps:
        out["unrecorded"] = "; ".join(gaps)
    if holding:
        out["holding"] = holding
    if not recorded:
        out["reason"] = "No records on this server: the book is off or was never switched on."
    elif not enabled:
        out["reason"] = "The book is switched off; these are the rows it recorded while on."
    return out


def verdict(key: str, n: int, mean: float | None) -> str:
    spec = SPECS[key]
    unit, need, bt = spec["unit"], needed(spec), spec["backtest"]["mean_bp"]
    if not n or mean is None:
        return f"No finished {unit}s yet: nothing to compare with the backtest's {bt:+.1f} bp a {unit}."
    if n < need:
        return (f"{_plural(n, unit)}: too few to judge; it takes roughly {need:,} {unit}s before a live average like the "
                f"backtest's {bt:+.1f} bp a {unit} could even be told from zero. Live so far {mean:+.2f} bp a {unit}.")
    return (f"Live {mean:+.2f} bp a {unit} over {_plural(n, unit)} against the backtest's {bt:+.1f} bp "
            f"({mean - bt:+.2f} bp).")


# --------------------------------------------------------------------------- from the stores

def overnight_report(nights: list[dict], *, enabled: bool, recorded: bool, coverage: dict | None = None) -> dict:
    closed = sorted((n for n in nights if n["status"] == "closed"), key=lambda n: (n["exit_day"], n["day"]))
    units = [{"day": n["exit_day"], "bp": overnight.result_bp(n)} for n in closed]
    last = None
    if closed:
        n = closed[-1]
        b = overnight.result_bp(n)
        last = {"bought": n["day"], "sold": n["exit_day"], "entry_ask": n["entry_ask"], "exit_bid": n["exit_bid"],
                "bp": round(b, 2), "usd": _usd(overnight.STAKE, b)}
    missed = [{"day": n["day"], "reason": n.get("note") or "no reason recorded"} for n in nights if n["status"] == "missed"]
    held = next((n for n in nights if n["status"] == "open"), None)
    holding = None if held is None else {"bought": held["day"], "entry_ask": held["entry_ask"]}
    return report("overnight", units, enabled=enabled, recorded=recorded, last=last, missed=missed, coverage=coverage,
                  holding=holding)


def momentum_report(trades: list[dict], checks: list[dict], now: float, *, enabled: bool, recorded: bool,
                    coverage: dict | None = None) -> dict:
    by_day = momentum.day_results(trades, checks, now)
    units = [{"day": d, "bp": by_day[d]} for d in sorted(by_day)]
    closed = [t for t in trades if t["status"] == "closed"]
    last = None
    if closed:
        t = closed[-1]
        b = momentum.bp(t)
        last = {"day": t["day"], "side": "long" if t["side"] > 0 else "short", "entry": t["entry"], "exit": t["exit"],
                "in": _time(t["entry_at"]), "out": _time(t["exit_at"]), "how": t["how"], "bp": round(b, 2),
                "usd": _usd(momentum.STAKE, b)}
    missed = [{"day": c["day"], "check": _hhmm(c["minute"]), "reason": c.get("note") or "no reason recorded"}
              for c in checks if c["status"] == "missed"]
    held = next((t for t in reversed(trades) if t["status"] == "open"), None)
    holding = None if held is None else {"day": held["day"], "side": "long" if held["side"] > 0 else "short",
                                         "entry": held["entry"], "in": _time(held["entry_at"])}
    return report("momentum", units, enabled=enabled, recorded=recorded, last=last, missed=missed, coverage=coverage,
                  holding=holding, trades=len(closed))


def _overnight_live(now: float) -> tuple[dict, list[dict]]:
    from app.engine import qqq_paper_coverage
    on, path = overnight.enabled(), overnight.store_path()
    if not path.exists():
        return overnight_report([], enabled=on, recorded=False), []
    nights = overnight.Store(path).nights()
    if not nights and not on:  # an empty file left by a switched-off book: no records
        return overnight_report([], enabled=on, recorded=False), []
    receipts = {(n["day"], overnight.ENTRY_MINUTE) for n in nights}
    coverage = qqq_paper_coverage.report(now, receipts, ((overnight.ENTRY_MINUTE, overnight.FULL_CLOSE),)) if on else None
    return overnight_report(nights, enabled=on, recorded=True, coverage=coverage), nights


def _momentum_live(now: float) -> tuple[dict, list[dict], list[dict]]:
    from app.engine import qqq_paper_coverage
    on, path = momentum.enabled(), momentum.store_path()
    if not path.exists():
        return momentum_report([], [], now, enabled=on, recorded=False), [], []
    store = momentum.Store(path, seed=None)
    trades, checks = store.trades(), store.checks()
    if not trades and not checks and not on:  # an empty file left by a switched-off book: no records
        return momentum_report([], [], now, enabled=on, recorded=False), [], []
    receipts = {(c["day"], c["minute"]) for c in checks}
    windows = tuple((m, m + momentum.LATE_MINUTES) for m in momentum.CHECKS)
    coverage = qqq_paper_coverage.report(now, receipts, windows) if on else None
    return momentum_report(trades, checks, now, enabled=on, recorded=True, coverage=coverage), trades, checks


def view(books: list[dict], now: float, note: str = NOTE) -> dict:
    as_of = datetime.fromtimestamp(now, ET).isoformat(timespec="seconds")
    return {"state": "ok", "book": "strategies", "as_of": as_of, "books": books, "note": note}


def live(now: float | None = None, hidden: set[str] | None = None) -> dict:
    """The copilot's read: both books, from their files alone."""
    import time
    if hidden is None:
        from sqlmodel import Session
        from app.database import engine
        from app.engine import day_journal
        with Session(engine) as db:
            hidden = day_journal.quiet(db)
    if SYMBOL in hidden:
        return {"state": "unavailable", "book": "strategies", "reason": HIDDEN}
    at = time.time() if now is None else now
    return view([_overnight_live(at)[0], _momentum_live(at)[0]], at)


def fixture() -> dict:
    """SIMULATED books for the fixture backend: invented rows, run through the same arithmetic as the live read."""
    def stamp(day: str, minute: int) -> float:
        d = date.fromisoformat(day)
        return datetime(d.year, d.month, d.day, minute // 60, minute % 60, tzinfo=ET).timestamp()
    nights = [{"day": "2026-11-16", "status": "closed", "entry_ask": 600.0, "exit_day": "2026-11-17", "exit_bid": 601.2},
              {"day": "2026-11-17", "status": "closed", "entry_ask": 601.0, "exit_day": "2026-11-18", "exit_bid": 600.4},
              {"day": "2026-11-18", "status": "missed", "note": "no fresh QQQ quote between 15:59 and 16:00"},
              {"day": "2026-11-19", "status": "closed", "entry_ask": 598.0, "exit_day": "2026-11-20", "exit_bid": 599.5}]
    trades = [{"id": 1, "day": "2026-11-17", "side": 1, "day_open": 600.0, "entry_at": stamp("2026-11-17", 600), "entry": 602.0,
               "exit_at": stamp("2026-11-17", 959), "exit": 604.4, "how": "close", "status": "closed"},
              {"id": 2, "day": "2026-11-19", "side": -1, "day_open": 598.0, "entry_at": stamp("2026-11-19", 720), "entry": 596.0,
               "exit_at": stamp("2026-11-19", 780), "exit": 596.9, "how": "stop", "status": "closed"}]
    checks = [{"day": d, "minute": m, "status": "done", "note": None} for d in ("2026-11-16", "2026-11-17", "2026-11-18", "2026-11-19")
              for m in momentum.CHECKS]
    checks.append({"day": "2026-11-20", "minute": 600, "status": "missed", "note": "not reached within five minutes"})
    now = stamp("2026-11-20", 17 * 60)
    out = view([overnight_report(nights, enabled=True, recorded=True), momentum_report(trades, checks, now, enabled=True, recorded=True)],
               now, note="SIMULATED fixture strategy books (invented rows). " + NOTE)
    return out


# --------------------------------------------------------------------------- the Friday review

def week_line(book: dict, units: list[dict], missed: list[dict], monday: str, day: str) -> str:
    """One plain line: the week's result, the running total and live against the backtest. ``units`` and ``missed`` are
    the book's full lists (``{"day", ...}``); the week is ``monday`` to ``day``."""
    from app.engine.day_read import usd
    unit, stake = book["unit"], book["stake_usd"]
    head = f"{book['book']} (paper, ${stake:,.0f} a {unit})"
    if book["state"] == "no records":
        return f"{head}: no records on this server (off or never switched on)."
    week = [u for u in units if monday <= u["day"] <= day]
    wk = sum(u["bp"] for u in week)
    parts = [f"this week {wk:+.2f} bp ({usd(_usd(stake, wk))}) over {_plural(len(week), unit)}" if week
             else f"this week no finished {unit}s"]
    missed = [m for m in missed if monday <= m["day"] <= day]
    if missed:
        parts.append(f"{len(missed)} missed ({missed[-1]['reason']})")
    if book["count"]:
        parts.append(f"running total {book['total_bp']:+.2f} bp ({usd(book['total_usd'])}) over {_plural(book['count'], unit)}")
    if book.get("unrecorded"):
        parts.append(f"records missing ({book['unrecorded']})")
    off = " Switched off." if book["state"] == "off" else ""
    return f"{head}: " + "; ".join(parts) + f". {book['vs_backtest']['read']}{off}"


def week_lines(now: float, hidden: set[str]) -> list[str]:
    """The review's strategy lines for the week of ``now`` (New York), or none when QQQ is not followed."""
    if SYMBOL in hidden:
        return []
    day = datetime.fromtimestamp(now, ET).date()
    monday = (day - timedelta(days=day.weekday())).isoformat()
    lines = []
    o, nights = _overnight_live(now)
    units = [{"day": n["exit_day"], "bp": overnight.result_bp(n)} for n in nights if n["status"] == "closed"]
    lines.append(week_line(o, units, [{"day": n["day"], "reason": n.get("note") or "no reason recorded"}
                                      for n in nights if n["status"] == "missed"], monday, day.isoformat()))
    m, trades, checks = _momentum_live(now)
    by_day = momentum.day_results(trades, checks, now)
    lines.append(week_line(m, [{"day": d, "bp": by_day[d]} for d in sorted(by_day)],
                           [{"day": c["day"], "reason": f"{_hhmm(c['minute'])} check: {c.get('note') or 'no reason recorded'}"}
                            for c in checks if c["status"] == "missed"], monday, day.isoformat()))
    return lines
