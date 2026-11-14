"""Is everything behind the desk live? (``GET /copilot/desk/health``, docs/copilot-lab.md § Data health)

One row per source the desk draws on: Robinhood (positions and orders), prices (Tradier), chatter (ApeWisdom),
TradingView alerts, fill emails (Gmail), Radar and the copilot's API budget left today. Level 2 (moomoo) is a session
the browser opens itself, so the desk adds that row from its own Tape; the server never sees it.

Each row: ``state`` (below), a plain ``line`` with its last-good time, ``last_at`` (epoch seconds or None), what it
``affects`` when it is not live, and ``fix`` when a fix path already exists. Read from what each source already keeps
in memory, on disk or in the database: no provider call, no Robinhood call, no write. The Robinhood facts come from the
desk router, the feed's existing reader (the feed's ``snapshot(kick=False)`` never starts a read). Read once a minute inside the desk's batched minute request (``desk_minute.PATHS``).

States: ``live``; ``closed`` (a market-hours source outside its hours); ``off`` (not switched on: not an error);
``quiet`` (event-driven and nothing came in: TradingView); ``unknown`` (cannot tell yet: never shown green); ``stale``
(no good read for longer than ``STALE_AFTER``); ``down`` (failing, signed out or disconnected); ``low`` (the budget is
nearly spent). ``overall``: ``bad`` if any row is stale, down or low; else ``unknown`` if any row is unknown; else ``ok``.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlmodel import Session

from app.engine.chart_math import ET

log = logging.getLogger(__name__)

# How long after its last good read a source counts as stale (seconds at ``now``). One line each; change them here.
STALE_AFTER = {
    # Three missed refreshes, the Robinhood feed's own rule: 3 min in market hours, 45 min otherwise. The desk router (the
    # feed's reader) passes it in as ``refresh_window``; this module never imports the feed.
    "robinhood": lambda facts: facts["refresh_window"],
    # The order-history pass runs on the same interval as the positions feed, so the same three missed passes.
    "robinhood_orders": lambda facts: facts["refresh_window"],
    # An open desk asks for prices every 5 s in the regular session; a minute with no good read means quotes are failing.
    "prices": lambda now: 60,
    # ApeWisdom is read every 15 min on market days from 6:00 to 20:00 New York; the Feed greys counts after 45 min.
    "chatter": lambda now: 45 * 60,
    # The Radar recorder passes once a minute in the regular session; the Radar page calls it stale after 3 min.
    "radar": lambda now: 3 * 60,
}
LOW_BUDGET_USD = 0.50  # the copilot budget shows amber below this many dollars left today
BAD = frozenset({"stale", "down", "low"})


def _clock(at: float | None, now: float) -> str:
    """9:41 today, else Tue 9:41 (New York)."""
    if not at:
        return ""
    moment, today = datetime.fromtimestamp(at, ET), datetime.fromtimestamp(now, ET).date()
    said = f"{moment.hour}:{moment.minute:02d}"
    if moment.date() == today:
        return said
    if (today - moment.date()).days < 7:
        return f"{moment:%a} {said}"
    return f"{moment:%b} {moment.day}"


def _epoch(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value) or None
    if isinstance(value, datetime):
        return (value if value.tzinfo else value.replace(tzinfo=UTC)).timestamp()
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return (moment if moment.tzinfo else moment.replace(tzinfo=UTC)).timestamp()


def _row(source: str, name: str, state: str, line: str, last_at: float | None, affects: str, fix: dict | None = None) -> dict:
    return {"id": source, "name": name, "state": state, "line": line, "last_at": int(last_at) if last_at else None,
            "affects": affects, "fix": fix}


def _unknown(source: str, name: str, affects: str) -> dict:
    return _row(source, name, "unknown", "Could not read its state just now", None, affects)


# --------------------------------------------------------------------------- each source

ROBINHOOD_AFFECTS = "Positions, orders and account value may be behind; the book falls back to the journal."
ROBINHOOD_SIGN_IN = {"kind": "text", "text": "Sign in again with the Robinhood sign-in helper (steps in docs/robinhood-read-feed.md)."}


def robinhood(now: float, facts: dict) -> dict:
    """``facts`` from the desk router, the feed's reader (``copilot_desk._robinhood_health``): the feed's ``state``
    (``snapshot(kick=False)``: never starts a read), ``last_at`` of its newest good read, ``refresh_window`` and
    ``orders`` (the order-history pass's ``mode`` and ``status``)."""
    state, last = facts.get("state"), _epoch(facts.get("last_at"))
    since = f"last read {_clock(last, now)}" if last else "no read yet"
    name, affects = "Robinhood", ROBINHOOD_AFFECTS
    if state == "off":
        return _row("robinhood", name, "off", "Not switched on · the book is the journal's", None, affects)
    if state in ("signed_out", "expired"):
        word = "signed out" if state == "signed_out" else "sign-in expired"
        return _row("robinhood", name, "down", f"{since[0].upper()}{since[1:]}, {word}", last, affects, ROBINHOOD_SIGN_IN)
    if state == "loading":
        return _row("robinhood", name, "unknown", "Starting · no read yet", None, affects)
    if state == "unavailable" or last is None:
        return _row("robinhood", name, "down", f"Robinhood did not answer · {since}", last, affects,
                    {"kind": "text", "text": "Refresh beside the book asks again; it retries on its own every minute."})
    if now - last > STALE_AFTER["robinhood"](facts):
        return _row("robinhood", name, "stale", f"Last read {_clock(last, now)}", last, affects)
    # Positions are live; the order-history pass (its own poller, same sign-in) can still be behind.
    orders = facts.get("orders") or {}
    if orders.get("mode", "off") != "off":
        status = orders.get("status") or {}
        at = _epoch(status.get("at"))
        if str(status.get("state", "")).startswith("read failed"):
            return _row("robinhood", name, "down", f"Positions live · orders: last read failed {_clock(at, now)}".rstrip(), last,
                        "Orders and today's fills from Robinhood may be behind.")
        if status.get("state") == "ok" and at and now - at > STALE_AFTER["robinhood_orders"](facts):
            return _row("robinhood", name, "stale", f"Positions live · orders last read {_clock(at, now)}", at,
                        "Orders and today's fills from Robinhood may be behind.")
    return _row("robinhood", name, "live", f"Live · read {_clock(last, now)}", last, affects)


PRICES_AFFECTS = "Prices, marks and P&L on the desk may be behind."


def prices(now: float, phase: str) -> dict:
    from app.engine import desk_ticks
    good, failed = desk_ticks.health()
    name = "Prices"
    if phase != "regular":
        return _row("prices", name, "closed", "Market closed · live prices run in the regular session", good, PRICES_AFFECTS)
    late = good is None or now - good > STALE_AFTER["prices"](now)
    if failed is not None and late and (good is None or failed > good):
        line = f"Quotes failing · last price {_clock(good, now)}" if good else "Quotes failing"
        return _row("prices", name, "down", line, good, PRICES_AFFECTS)
    if good is None:
        return _row("prices", name, "unknown", "No price read yet", None, PRICES_AFFECTS)
    if late:
        return _row("prices", name, "stale", f"Last price {_clock(good, now)}", good, PRICES_AFFECTS)
    return _row("prices", name, "live", "Live", good, PRICES_AFFECTS)


CHATTER_AFFECTS = "The Feed's chatter (what r/wallstreetbets is talking about) may be old."


def chatter_row(now: float, regular: tuple[int, int] | None) -> dict:
    from app.engine import chatter
    name = "Chatter"
    if not chatter.wsb_enabled():
        return _row("chatter", name, "off", "Not switched on", None, CHATTER_AFFECTS)
    state = chatter.load("wsb")
    ok_at, error_at = _epoch(state.get("ok_at")), _epoch(state.get("error_at"))
    local = datetime.fromtimestamp(now, ET)
    start = datetime.combine(local.date(), chatter.READ_FROM, ET).timestamp()
    if regular is None or not chatter.READ_FROM <= local.time() < chatter.WSB_UNTIL:  # not a market day, or outside its hours
        said = f" · last read {_clock(ok_at, now)}" if ok_at else ""
        return _row("chatter", name, "closed", f"Reads on market days 6:00–20:00{said}", ok_at, CHATTER_AFFECTS)
    # Its first read of the day comes in the first minutes after 6:00: the day's start counts as its last good read.
    age = now - max(ok_at or 0, start)
    said = f"last read {_clock(ok_at, now)}" if ok_at else "no read yet"
    if error_at and error_at > (ok_at or 0) and age > STALE_AFTER["chatter"](now):
        return _row("chatter", name, "down", f"ApeWisdom did not answer · {said}", ok_at, CHATTER_AFFECTS)
    if age > STALE_AFTER["chatter"](now):
        return _row("chatter", name, "stale", said[0].upper() + said[1:], ok_at, CHATTER_AFFECTS)
    if not ok_at or ok_at < start:
        return _row("chatter", name, "unknown", "First read of the day due", ok_at, CHATTER_AFFECTS)
    return _row("chatter", name, "live", f"Live · read {_clock(ok_at, now)}", ok_at, CHATTER_AFFECTS)


TRADINGVIEW_AFFECTS = "Your TradingView alerts in the Feed (Mine) and as marks on the chart."


def tradingview(db: Session, now: float) -> dict:
    """Event-driven: an alert today proves the webhook is live; none is ``quiet`` (none may have fired), never green.
    Only alerts on tickers he follows count, so a hidden ticker's alert never shows here."""
    from app.engine import day_journal, desk_feed
    name = "TradingView"
    last = _epoch(desk_feed._last_alert_at(db, now, "live", day_journal.not_following(db)))
    if last is None:
        return _row("tradingview", name, "quiet", "No alert has come in yet", None, TRADINGVIEW_AFFECTS)
    if datetime.fromtimestamp(last, ET).date() == datetime.fromtimestamp(now, ET).date():
        return _row("tradingview", name, "live", f"Last alert {_clock(last, now)}", last, TRADINGVIEW_AFFECTS)
    return _row("tradingview", name, "quiet", f"No alerts today · last {_clock(last, now)}", last, TRADINGVIEW_AFFECTS)


GMAIL_AFFECTS = "New fills reach the journal from Robinhood's emails; fills and P&L may be behind."


def gmail(db: Session, now: float) -> dict:
    from app.engine.gmail_health import gmail_health
    health = gmail_health(db)
    status = health.get("status")
    last = _epoch(health.get("last_notification_at")) or _epoch(health.get("last_import_at"))
    said = f"last email {_clock(last, now)}" if last else "no email yet"
    name = "Fill emails"
    if health.get("action") == "reconnect_gmail":
        return _row("gmail", name, "down", f"Gmail disconnected · {said}", last, GMAIL_AFFECTS, {"kind": "gmail_reconnect"})
    if status == "live":
        return _row("gmail", name, "live", f"Live · {said}", last, GMAIL_AFFECTS)
    if status == "off":
        return _row("gmail", name, "off", "Real-time off · fills arrive with the scheduled check", last, GMAIL_AFFECTS)
    if status == "degraded":
        return _row("gmail", name, "stale", f"{health.get('message') or 'Reconnecting'} · {said}", last, GMAIL_AFFECTS)
    if status == "down":
        return _row("gmail", name, "down", f"{health.get('message') or 'Not responding'} · {said}", last, GMAIL_AFFECTS)
    return _unknown("gmail", name, GMAIL_AFFECTS)


RADAR_AFFECTS = "Radar flags, setup cards and Moving may be missing or late."


def radar(now: float, phase: str, regular: tuple[int, int] | None) -> dict:
    from app.engine import radar_runner
    from app.routers import radar as radar_router
    name = "Radar"
    if not radar_runner.enabled():
        return _row("radar", name, "off", "Not switched on", None, RADAR_AFFECTS)
    store, reason = radar_router._store(read_only=True)
    if store is None:
        return _row("radar", name, "down", reason or "Its file could not be opened", None, RADAR_AFFECTS)
    day = datetime.fromtimestamp(now, ET).date().isoformat()
    passes = store.passes(day)
    good = [p for p in passes if p["status"] in ("ok", "partial")]
    last = _epoch(good[-1]["started_at"]) if good else None
    if last is None and phase != "regular":  # before today's first pass: the newest session's last pass
        before = next((d for d in store.sessions() if d < day), None)  # newest first
        earlier = [p for p in store.passes(before) if p["status"] in ("ok", "partial")] if before else []
        last = _epoch(earlier[-1]["started_at"]) if earlier else None
    if phase != "regular" or regular is None:
        said = f" · last pass {_clock(last, now)}" if last else ""
        return _row("radar", name, "closed", f"Market closed{said}", last, RADAR_AFFECTS)
    # The first pass lands in the session's first minute: the open counts as its last good pass.
    age = now - max(last or 0, regular[0])
    if age > STALE_AFTER["radar"](now):
        said = f"Last pass {_clock(last, now)}" if last else "No pass recorded today"
        return _row("radar", name, "stale", said, last, RADAR_AFFECTS)
    if last is None:
        return _row("radar", name, "unknown", "First pass of the day due", None, RADAR_AFFECTS)
    return _row("radar", name, "live", f"Recording · pass {_clock(last, now)}", last, RADAR_AFFECTS)


BUDGET_AFFECTS = "Copilot answers, desk reads and the day read stop for the day when it runs out; it resets at midnight New York."


def budget(db: Session) -> dict:
    from app.ai import copilot, copilot_spend
    found = copilot.settings()
    name = "Copilot budget"
    if getattr(found, "backend", None) != "anthropic":
        return _row("budget", name, "off", "Not on the paid API", None, BUDGET_AFFECTS)
    cap = float(found.daily_budget_usd)
    left = round(cap - copilot_spend.spent_today(db), 2)
    if left <= 0:
        return _row("budget", name, "down", f"Spent for today (${cap:.2f})", None, BUDGET_AFFECTS)
    state = "low" if left < LOW_BUDGET_USD else "live"
    return _row("budget", name, state, f"${left:.2f} left of ${cap:.2f} today", None, BUDGET_AFFECTS)


# --------------------------------------------------------------------------- the strip

def overall(rows: list[dict]) -> str:
    states = {r["state"] for r in rows}
    return "bad" if states & BAD else "unknown" if "unknown" in states else "ok"


def build(db: Session, now: float, robinhood_facts, mode: str = "live") -> dict:
    """The strip at ``now``. Each source fails on its own as ``unknown``, never green. ``robinhood_facts``: a callable
    giving the desk router's facts about the Robinhood feed (``robinhood``)."""
    from app.engine import desk_sparks
    from app.routers import today
    if mode == "fixture":
        return fixture(now)
    _day, phase, _hours, regular = desk_sparks._session(now)

    def one(source: str, name: str, affects: str, read) -> dict:
        found = today._section(db, f"desk health {source}", read)
        return found if "id" in found else _unknown(source, name, affects)

    rows = [
        one("robinhood", "Robinhood", ROBINHOOD_AFFECTS, lambda: robinhood(now, robinhood_facts())),
        one("prices", "Prices", PRICES_AFFECTS, lambda: prices(now, phase)),
        one("chatter", "Chatter", CHATTER_AFFECTS, lambda: chatter_row(now, regular)),
        one("tradingview", "TradingView", TRADINGVIEW_AFFECTS, lambda: tradingview(db, now)),
        one("gmail", "Fill emails", GMAIL_AFFECTS, lambda: gmail(db, now)),
        one("radar", "Radar", RADAR_AFFECTS, lambda: radar(now, phase, regular)),
        one("budget", "Copilot budget", BUDGET_AFFECTS, lambda: budget(db)),
    ]
    return {"as_of": today._iso(now), "now": int(now), "phase": phase, "overall": overall(rows), "sources": rows}


def fixture(now: float) -> dict:
    """Invented rows for the fixture desk (screenshots, the UX sandbox): one source stale, the rest live or off."""
    rows = [
        _row("robinhood", "Robinhood", "down", f"Last read {_clock(now - 9 * 60, now)}, signed out", now - 9 * 60,
             ROBINHOOD_AFFECTS, ROBINHOOD_SIGN_IN),
        _row("prices", "Prices", "live", "Live", now - 3, PRICES_AFFECTS),
        _row("chatter", "Chatter", "live", f"Live · read {_clock(now - 6 * 60, now)}", now - 6 * 60, CHATTER_AFFECTS),
        _row("tradingview", "TradingView", "live", f"Last alert {_clock(now - 14 * 60, now)}", now - 14 * 60, TRADINGVIEW_AFFECTS),
        _row("gmail", "Fill emails", "live", f"Live · last email {_clock(now - 41 * 60, now)}", now - 41 * 60, GMAIL_AFFECTS),
        _row("radar", "Radar", "live", f"Recording · pass {_clock(now - 40, now)}", now - 40, RADAR_AFFECTS),
        _row("budget", "Copilot budget", "live", "$2.40 left of $4.00 today", None, BUDGET_AFFECTS),
    ]
    return {"as_of": datetime.fromtimestamp(now, UTC).isoformat(), "now": int(now), "phase": "regular",
            "overall": overall(rows), "sources": rows}
