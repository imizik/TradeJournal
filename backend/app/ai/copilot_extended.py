"""The copilot's extended-hours reads (docs/copilot-lab.md § Extended hours).

Outside the regular session a quote's last price and day change are the regular session's, so before the open every name
reads flat at the prior close. This reads Tradier's 1-minute timesales with ``session_filter=all`` (04:00-20:00 New York)
through the chart feed, the request the Charts tab makes for today, and summarises what traded off hours:

- pre-market (04:00 to the open): today's pre-market move against the previous session's regular close, with that
  session's after-hours move;
- after-hours (the close to 20:00): the move since today's regular close;
- closed (overnight, a weekend or a holiday): the latest session's complete after-hours.

Every reference close comes from the minute bars and the market calendar (early closes included), not from the quote's
fields. Tradier carries no overnight (20:00-04:00) trading. ``get_radar_today`` also reads the Radar pre-market pilot's
recorded 08:50 and 09:20 scans when the pilot is on (``premarket_scan``). Live only: replay and the fixture leave it out.
Nothing here writes.
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import date, datetime, timedelta

from app.engine.chart_math import ET, normalize_bars, session_windows

log = logging.getLogger(__name__)

TODAY_TTL_S = 15  # the Charts tab's own key and lifetime for today's minutes
PAST_TTL_S = 6 * 3600  # a completed session does not change
LOOKBACK_DAYS = 6  # a long weekend plus a holiday
MAX_SYMBOLS = 8
PREMARKET_MOVERS = 10
AGAINST = {"pre-market": "premarket: the previous session's regular close; previous_session.after_hours: that session's close",
           "after-hours": "today's regular close", "closed": "that session's regular close"}
NOTE = ("Extended hours from 1-minute trades (Tradier timesales, 04:00-20:00 New York; no overnight trading). change_pct "
        "is against the regular-session close in change_against; last_at is New York time. Off-hours volume is thin: weigh dollar_volume before "
        "reading much into a move, and say when it last traded.")


def _hours(day: date) -> dict | None:
    from app.engine.chart_calendar import chart_calendar
    try:
        return chart_calendar.hours(day)
    except Exception as exc:  # noqa: BLE001 - the clock hours stand in, without holidays or early closes
        log.warning("extended hours: calendar unavailable: %s", type(exc).__name__)
        return None


def _windows(day: date) -> dict[str, tuple[int, int]]:
    return {name: (start, end) for name, start, end in session_windows(day, _hours(day))}


def phase(now: datetime) -> str:
    """``pre-market``, ``regular``, ``after-hours`` or ``closed`` for the New York moment ``now``."""
    et = now.astimezone(ET)
    minute = et.hour * 60 + et.minute
    for name, (start, end) in _windows(et.date()).items():
        if start <= minute < end:
            return {"pre": "pre-market", "regular": "regular", "post": "after-hours"}[name]
    return "closed"


def _minute(bar: dict) -> int:
    at = datetime.fromtimestamp(bar["time"], ET)
    return at.hour * 60 + at.minute


def _bars(symbol: str, day: date, now: datetime) -> list[dict]:
    """``day``'s completed minutes, 04:00-20:00. Raises ChartFeedError when the feed cannot read."""
    from app.engine.chart_feed import _rows, chart_feed
    if now < datetime.combine(day, datetime.min.time(), ET).replace(hour=4):
        return []  # Tradier refuses a start in the future, and that failure would cool every chart read down
    today = day == now.astimezone(ET).date()
    data, _, _ = chart_feed.read("/v1/markets/timesales", {
        "symbol": symbol, "interval": "1min", "session_filter": "all",
        "start": day.strftime("%Y-%m-%d 04:00"), "end": day.strftime("%Y-%m-%d 20:00"),
    }, TODAY_TTL_S if today else PAST_TTL_S)
    cut = now.timestamp()
    return [b for b in normalize_bars(_rows(data, "series", "data"))
            if b["time"] + 60 <= cut and datetime.fromtimestamp(b["time"], ET).date() == day]


def _session(symbol: str, before: date, now: datetime) -> tuple[date, list[dict]] | None:
    """The latest session before ``before`` that has minutes, stepping over weekends and holidays."""
    for back in range(1, LOOKBACK_DAYS + 1):
        day = before - timedelta(days=back)
        if not _windows(day).get("regular"):
            continue
        bars = _bars(symbol, day, now)
        if bars:
            return day, bars
    return None


def _part(bars: list[dict], day: date, name: str) -> list[dict]:
    window = _windows(day).get(name)
    return [b for b in bars if window and window[0] <= _minute(b) < window[1]]


def _at(bar: dict) -> str:
    return datetime.fromtimestamp(bar["time"], ET).isoformat(timespec="minutes")


def summary(bars: list[dict], reference: float | None, range_: bool = True) -> dict:
    """What traded in one off-hours window, against ``reference`` (a regular-session close); compact, since eight of these
    share one tool result."""
    if not bars:
        return {"state": "no_trades"}
    last = bars[-1]["close"]
    out = {"last": round(last, 4), "last_at": _at(bars[-1])[11:16],
           "change_pct": round((last / reference - 1) * 100, 2) if reference else None}
    if range_:
        out.update(high=round(max(b["high"] for b in bars), 4), low=round(min(b["low"] for b in bars), 4))
    return {**out, "volume": int(sum(b["volume"] for b in bars)), "dollar_volume": round(sum(b["close"] * b["volume"] for b in bars))}


def _close(bars: list[dict], day: date) -> float | None:
    regular = _part(bars, day, "regular")
    return regular[-1]["close"] if regular else None


def _after(day: date, bars: list[dict], range_: bool = True) -> dict:
    close = _close(bars, day)
    return {"date": day.isoformat(), "regular_close": close, "after_hours": summary(_part(bars, day, "post"), close, range_)}


def one(symbol: str, now: datetime, part: str) -> dict:
    """One symbol's off-hours picture for the phase ``part``."""
    today = now.astimezone(ET).date()
    if part == "pre-market":
        previous = _session(symbol, today, now)
        close = _close(previous[1], previous[0]) if previous else None
        out = {"premarket": summary(_part(_bars(symbol, today, now), today, "pre"), close)}
        if previous:
            out["previous_session"] = _after(*previous, range_=False)
        return out
    if part == "after-hours" or (part == "closed" and _windows(today).get("regular") and now.astimezone(ET).hour >= 16):
        return {"today": _after(today, _bars(symbol, today, now))}
    previous = _session(symbol, today + timedelta(days=1), now)  # today included: a session that ended before 04:00 is yesterday's
    if previous is None:
        return {"state": "no_trades", "reason": f"No session with trades in the last {LOOKBACK_DAYS} days."}
    return {"last_session": _after(*previous)}


def extended(symbols: list[str], now: datetime) -> dict | None:
    """Off-hours pictures for up to ``MAX_SYMBOLS`` symbols; None during the regular session."""
    from app.engine.chart_feed import ChartFeedError
    part = phase(now)
    if part == "regular":
        return None
    rows: dict[str, dict] = {}
    for symbol in list(dict.fromkeys(symbols))[:MAX_SYMBOLS]:
        try:
            rows[symbol] = one(symbol, now, part)
        except ChartFeedError as exc:
            rows[symbol] = {"state": "unavailable", "reason": str(exc)[:200]}
    return {"phase": part, "as_of": now.astimezone(ET).isoformat(timespec="minutes"), "change_against": AGAINST[part],
            "symbols": rows, "note": NOTE}


def premarket_scan(radar_store_path: str | None, today: date) -> dict:
    """Today's latest Radar pre-market pilot scan: the tracked universe's pre-market moves against SPY's."""
    from pathlib import Path

    from app.engine import radar_premarket
    if not radar_store_path or not radar_premarket.enabled():
        return {"state": "off", "reason": "The Radar pre-market pilot is not switched on."}
    path = radar_premarket.store_path(radar_store_path)
    if not Path(path).exists():
        return {"state": "none", "reason": "The pre-market pilot has not recorded a scan yet."}
    try:
        store = radar_premarket.PremarketStore(path, read_only=True)
        scans = [s for s in store.scans() if s["session_date"] == today.isoformat() and s["status"] in ("ok", "partial")]
        if not scans:
            return {"state": "none", "reason": "No pre-market scan today yet (the pilot scans at 08:50 and 09:20)."}
        scan = scans[-1]
        readings = [r for r in store.readings(scan["id"]) if r["change_pct"] is not None]
    except (ValueError, OSError, sqlite3.Error) as exc:
        log.warning("copilot pre-market scan unreadable: %s", exc)
        return {"state": "error", "reason": "The pre-market pilot's file could not be read."}
    ranked = sorted(readings, key=lambda r: abs(r["excess_pct"] or 0), reverse=True)
    return {"state": scan["status"], "checkpoint": scan["checkpoint"], "rule_version": scan["rule_version"],
            "symbols_read": scan["symbols_read"], "up": sum(r["change_pct"] > 0 for r in readings),
            "down": sum(r["change_pct"] < 0 for r in readings),
            "flagged": [r["symbol"] for r in ranked if r["flagged"]],
            "movers": [{"symbol": r["symbol"], "change_pct": round(r["change_pct"], 2), "vs_spy_pts": round(r["excess_pct"], 2)
                        if r["excess_pct"] is not None else None, "dollar_volume": round(r["dollar_volume"]),
                        "last_bar_at": r["last_bar_at"]} for r in ranked[:PREMARKET_MOVERS]],
            "note": ("The Radar universe's pre-market moves at the checkpoint against the previous close; vs_spy_pts is "
                     "the move minus SPY's. flagged met the pilot's frozen rule (3 points, $250k traded, a trade within "
                     "10 minutes). A record, not an alert.")}
