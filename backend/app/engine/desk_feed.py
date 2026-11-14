"""The desk's Feed (``GET /copilot/desk/feed``, docs/copilot-lab.md § The desk): one stream of what the app already
knows today, each item one small row.

Sources, each read on its own (``today._section``): one that fails reads ``unavailable`` in ``sources`` and is named in
``unavailable``; the rest stand.

- ``pings``: phone pings the notification policy judged today, sent or held. Position alerts read **Alert**; plan pings
  (entry or invalidation reached, time stop, plan nudge) read **Plan**; the position companion's updates read
  **Copilot note** (written when they were sent: no model call here). Radar's own pings, the morning brief's and the
  day's meta pings (evening review, week review, replay, research) are left to their own sources or screens.
- ``plans``: plan time stops still ahead today (**Plan**, coming up), and a plan's entry or invalidation alert that fired
  today without a ping of its own.
- ``radar``: today's Radar events (**Radar**); ``radar setups``: today's setup cards (**Radar setup**), worded as the
  desk's Radar card shows them (``desk_radar_setups.view``). An event with a setup card shows as the card only.
- ``news`` and ``market news``: headlines since the previous regular close naming a symbol the owner holds or has an
  armed plan on (catalysts first, at most two each), and up to three market-wide ones (Fed, CPI, yields...). Two batched
  provider reads, each cached ``NEWS_TTL_S`` seconds. Headline text is third-party data shown as data with its
  publisher and time; nothing reads it as an instruction, and it never carries Plan it.
- ``calendar``: this week's earnings for those symbols (the earnings cache only; a cold symbol refreshes in the
  background) and FOMC, CPI and jobs reports today through Sunday (``app/data/macro_calendar.json``).
- ``brief``: today's morning brief, its saved lines (**Copilot note**).
- ``tradingview``: his own TradingView alerts that reached the webhook today (**TradingView**, always his: ``mine``, Plan
  it), newest first, each with what fired and the price at that moment, read from the stored rows only
  (``tradingview_today``). ``tradingview.last_at`` is the newest stored alert on a ticker he follows, so the screen can
  say when the last one came on a day with none. In the sandbox (``evidence`` "fixture") two invented ones stand in.
- ``chatter`` (``app/engine/chatter.py``): r/wallstreetbets buzz (ApeWisdom's counts) and NYT headlines, returned
  apart from ``items`` for the screen's own Chatter filter only: never ranked with the rest, never counted as new, never
  Plan it. ``chatter.sources`` names each source's state (``on``, ``stale``, ``not set up``, ``unavailable``).

Rank: items that touch the owner's book or plans (``mine``) first, then the rest, each newest first; then what is still
ahead (``upcoming``), soonest first. A symbol the owner set to not followed is left out everywhere: an item about it,
a headline or Radar event naming it among others, and any row whose words name it. If that setting cannot be read,
only the macro calendar shows. At most ``MAX_ITEMS`` rows (``MAX_UPCOMING`` of them ahead);
``total`` counts them all. Read-only: no write, no model call. Facts and counts; nothing here tells the owner to trade.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
import json
import logging
import re
import threading
import time as _time
from pathlib import Path
from urllib.parse import quote, urlencode

from sqlmodel import Session, col, select

from app.engine.chart_math import ET

log = logging.getLogger(__name__)

MAX_ITEMS = 40
MAX_UPCOMING = 8
MAX_PINGS = 20
MAX_RADAR = 10
MAX_NEWS_SYMBOLS = 12
MAX_SYMBOL_HEADLINES = 10
PER_SYMBOL_HEADLINES = 2
MAX_MARKET_HEADLINES = 3
MAX_BRIEF_LINES = 5
MAX_TRADINGVIEW = 12
NEWS_TTL_S = 120
TEXT = 220

MACRO_FILE = Path(__file__).resolve().parents[1] / "data" / "macro_calendar.json"
SYMBOL = re.compile(r"[A-Z]{1,6}(\.[A-Z])?")

# Phone ping kinds by the feed's source; a kind not named here (and not skipped) reads as an Alert.
PLAN_KINDS = {"entry", "invalidation", "time_stop", "nudge", "no_plan", "link"}
NOTE_KINDS = {"companion_update", "companion_adopt"}
SKIP_KINDS = {"prep", "evening_review", "week_review", "day_replay", "research", "radar_setup", "radar_event", "radar_digest",
              "paper_review"}
HELD = {"merged": "Held back: merged into an earlier ping", "suppressed": "Held back: quiet window",
        "over_cap": "Held back: over the day's budget", "not_followed": "Held back: not followed"}
RADAR_KIND = {"relative_to_spy": "vs SPY", "relative_to_sector": "vs sector", "group_move": "Group move",
              "dip_turn": "Dip turning up", "gap_reversal": "Gap reversal"}
DESK_RADAR_KINDS = ("relative_to_spy", "relative_to_sector", "dip_turn", "gap_reversal")
ROLE = {"entry": "Entry", "invalidation": "Invalidation"}
# Setup-name words TradingView alerts use that read better in capitals ("orb_break" reads "ORB break").
CAPS = {"orb", "vwap", "ema", "sma", "rsi", "macd", "hod", "lod", "pdh", "pdl", "atr", "or"}
BROAD = {"SPY", "QQQ", "DIA", "IWM", "VOO", "VTI", "TLT", "GLD", "USO", "UUP"}


# --------------------------------------------------------------------------- small helpers

def _utc_epoch(moment: datetime) -> int:
    return int(moment.replace(tzinfo=UTC).timestamp())


def _epoch(iso: str | None) -> int | None:
    if not iso:
        return None
    try:
        return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())
    except ValueError:
        return None


def _trim(text: str | None, most: int = TEXT) -> str:
    words = " ".join(str(text or "").split())
    return words if len(words) <= most else words[: most - 1].rstrip(" ,;.") + "…"


def _desk(symbol: str) -> str:
    return f"/copilot-lab?{urlencode({'symbol': symbol})}"


def _item(source: str, key: str, at: int, text: str, *, symbol: str | None = None, detail: str | None = None,
          has_time: bool = True, **more) -> dict:
    return {"id": f"{source.lower().replace(' ', '-')}:{key}", "source": source, "at": at, "has_time": has_time,
            "symbol": symbol or None, "text": text, "detail": detail or None, "publisher": None, "url": None,
            "href": _desk(symbol) if symbol else None, "investigation_id": None, "radar_event_id": None,
            "setup": None, "plan": None, "mine": False, "upcoming": False, **more}


# --------------------------------------------------------------------------- the owner's book (symbols only)

def _book(db: Session) -> dict:
    """Symbols the owner holds (open trades, Webull left out like the rest of the desk) and has a live plan on (an armed
    level, a time stop still scheduled, or in position), from the journal alone: no quote read."""
    from app.ai.copilot_book import _not_webull
    from app.engine import copilot_plans
    from app.models import Account, Trade
    held = set(db.exec(select(Trade.ticker).join(Account, Account.id == Trade.account_id)
                       .where(Trade.status == "open").where(_not_webull())).all())
    plans = set()
    for plan in copilot_plans._plans(db)[0]:
        if (row := plan.get("adopted")) is not None and row.state == "ignored":
            continue
        armed = any(a is not None and a.state == "active" for a in (plan["entry"], plan["invalidation"]))
        pending = plan["stop"] is not None and plan["stop"].delivery == "scheduled"
        if armed or pending or plan["position"] == "in_position":
            plans.add(plan["symbol"])
    return {"state": "ok", "held": held, "plans": plans}


def _hidden(db: Session) -> dict:
    from app.engine import day_journal
    return {"state": "ok", "symbols": day_journal.not_following(db)}


# --------------------------------------------------------------------------- sources

def _pings(db: Session, now: float) -> dict:
    from app.engine import notification_policy as policy
    from app.models import PhonePing
    start, end = policy.day_bounds(now)
    found = db.exec(select(PhonePing).where(PhonePing.decided_at >= start, PhonePing.decided_at < end)
                    .order_by(col(PhonePing.decided_at).desc())).all()
    rows = []
    for p in found:
        if p.kind in SKIP_KINDS:
            continue
        source = "Copilot note" if p.kind in NOTE_KINDS else "Plan" if p.kind in PLAN_KINDS else "Alert"
        held = HELD.get(p.decision) if p.decision != "sent" else None
        body = _trim(p.body)
        text = _trim(p.title, 120) if source != "Copilot note" else body or _trim(p.title, 120)
        detail = body if source != "Copilot note" else None
        if held:
            detail = f"{held}. {detail}" if detail else f"{held}."
        rows.append(_item(source, str(p.id), _utc_epoch(p.decided_at), text, symbol=p.symbol, detail=detail, kind=p.kind))
        if len(rows) >= MAX_PINGS:
            break
    return {"state": "ok", "rows": rows}


def _plans(db: Session, now: float, pinged: set[tuple[str, str]]) -> dict:
    """Time stops still ahead today; a plan level that fired today with no ping of its kind for the symbol."""
    from app.engine import notification_policy as policy
    from app.models import LevelAlert, PlanTimeStop
    start, end = policy.day_bounds(now)
    rows = []
    for stop in db.exec(select(PlanTimeStop).where(PlanTimeStop.delivery == "scheduled", PlanTimeStop.due_at >= start,
                                                   PlanTimeStop.due_at < end).order_by(PlanTimeStop.due_at)).all():
        clock = datetime.fromtimestamp(_utc_epoch(stop.due_at), ET).strftime("%H:%M")
        rows.append(_item("Plan", f"stop:{stop.id}", _utc_epoch(stop.due_at), f"Time stop due {clock}",
                          symbol=stop.symbol, detail=f"Your words: {_trim(stop.text, 120)}",
                          investigation_id=stop.investigation_id))
    for alert in db.exec(select(LevelAlert).where(LevelAlert.source_kind == "copilot", col(LevelAlert.plan_role).is_not(None),
                                                  LevelAlert.fired_at >= start, LevelAlert.fired_at < end)).all():
        if (alert.symbol, alert.plan_role) in pinged:
            continue
        role = ROLE.get(alert.plan_role, alert.plan_role)
        rows.append(_item("Plan", f"level:{alert.id}", _utc_epoch(alert.fired_at), f"{role} {alert.price:.2f} reached",
                          symbol=alert.symbol, kind=alert.plan_role))
    return {"state": "ok", "rows": rows}


def _radar(day: date) -> dict:
    from app.routers import radar
    store, _reason = radar._store(read_only=True)
    if store is None:
        return {"state": "off", "rows": []}
    rows = []
    for event in store.events(day.isoformat()):
        at = _epoch(event.get("first_seen_at"))
        if at is None:
            continue
        symbols = [x for x in event.get("symbols") or [] if isinstance(x, str)]
        symbol = symbols[0] if symbols else None
        kind = RADAR_KIND.get(event.get("kind"), str(event.get("kind") or "event").replace("_", " "))
        href = (f"/copilot-lab?{urlencode({'symbol': symbol, 'radar': event['event_id']})}"
                if symbol and event.get("kind") in DESK_RADAR_KINDS else f"/radar?{urlencode({'event': event['event_id']})}")
        text = _trim(event.get("summary") or f"{symbol or 'Group'} {kind}", 160)
        rows.append(_item("Radar", event["event_id"], at, text, symbol=symbol, detail=kind, href=href,
                          radar_event_id=event["event_id"], symbols=symbols))
    rows.sort(key=lambda r: r["at"], reverse=True)
    return {"state": "ok", "rows": rows[:MAX_RADAR]}


def _setups(db: Session, day: date) -> dict:
    from app.engine import desk_radar_setups
    from app.models import RadarSetup
    rows = []
    for row in db.exec(select(RadarSetup).where(RadarSetup.session_date == day.isoformat())
                       .order_by(col(RadarSetup.created_at).desc())).all()[:MAX_RADAR]:
        card = desk_radar_setups.view(db, row)
        setup = {k: card[k] for k in ("id", "event_id", "words", "levels_line", "contract_line", "record", "paper_record",
                                      "plan_state", "investigation_id", "direction", "invalidation", "contract")}
        href = f"/copilot-lab?{urlencode({'symbol': row.symbol, 'radar': row.event_id})}"
        rows.append(_item("Radar setup", str(row.id), _utc_epoch(row.created_at), f"{row.symbol} {card['words']}",
                          symbol=row.symbol, href=href, radar_event_id=row.event_id, setup=setup,
                          plan="setup" if card["plan_state"] == "none" else None))
    return {"state": "ok", "rows": rows}


_news_cache: dict[tuple, tuple[float, list[dict]]] = {}
_news_lock = threading.Lock()


def _read_news(symbols: list[str] | None, since: datetime, now: datetime) -> list[dict]:
    """One batched provider read (``None``: the broad tape), strict so a refused key is unavailable, never "no news";
    cached ``NEWS_TTL_S`` seconds per symbol set and window start."""
    from app.engine import premarket_prep
    key, clock = (tuple(symbols) if symbols else None, since.isoformat(timespec="minutes")), _time.monotonic()
    with _news_lock:
        hit = _news_cache.get(key)
        if hit and clock - hit[0] < NEWS_TTL_S:
            return hit[1]
    found = premarket_prep.read_news(symbols, since, now)
    with _news_lock:
        for stale in [k for k, (at, _) in _news_cache.items() if clock - at >= NEWS_TTL_S]:
            del _news_cache[stale]
        _news_cache[key] = (clock, found)
    return found


def _news_since(day: date) -> datetime:
    """The previous regular close (the morning brief's window)."""
    from app.engine import premarket_prep
    from app.engine.chart_calendar import chart_calendar
    return premarket_prep._previous_close(chart_calendar, day)


def _headline_item(row: dict, key: str, symbol: str | None) -> dict:
    item = _item("News", key, int(row["_at"].timestamp()), _trim(row["headline"], 200), symbol=symbol)
    item.update(publisher=row["publisher"], url=row["url"], symbols=row["symbols"])  # every symbol it names, for the hidden check
    return item


def _news(symbols: list[str], since: datetime, now: datetime) -> dict:
    from app.engine.jo_morning_market import catalyst_first
    from app.engine.premarket_prep import _headline
    wanted = [s for s in symbols if SYMBOL.fullmatch(s)][:MAX_NEWS_SYMBOLS]
    if not wanted:
        return {"state": "ok", "rows": []}
    found = [h for a in _read_news(wanted, since, now) if (h := _headline(a, since, now))]
    rows, per = [], {}
    for row in catalyst_first(sorted(found, key=lambda h: h["_at"], reverse=True)):
        named = [s for s in wanted if s in row["symbols"] and per.get(s, 0) < PER_SYMBOL_HEADLINES]
        if not named or any(r["url"] == row["url"] for r in rows):
            continue
        for s in named:
            per[s] = per.get(s, 0) + 1
        rows.append(_headline_item(row, row["url"], named[0]))
        if len(rows) >= MAX_SYMBOL_HEADLINES:
            break
    return {"state": "ok", "rows": rows}


def _market_news(since: datetime, now: datetime) -> dict:
    from app.engine.jo_morning_market import MACRO_WORDS
    from app.engine.premarket_prep import _headline
    found = [h for a in _read_news(None, since, now) if (h := _headline(a, since, now))]
    rows = []
    for row in sorted(found, key=lambda h: h["_at"], reverse=True):
        stocks = [x for x in row["symbols"] if x not in BROAD]
        if 1 <= len(stocks) <= 2:
            continue  # a story about one or two companies, whatever words it uses ("Nasdaq notice"), is not the market's
        if MACRO_WORDS.search(row["headline"]) and all(r["url"] != row["url"] for r in rows):
            rows.append(_headline_item(row, row["url"], None))
        if len(rows) >= MAX_MARKET_HEADLINES:
            break
    return {"state": "ok", "rows": rows}


def _read_earnings(symbols: list[str], day: date) -> dict[str, dict]:
    """Each symbol's next report from the earnings cache only (``chart_earnings``: stale ones refresh in the background)."""
    from app.engine.symbol_info_tradier import symbol_events
    return symbol_events.chart_earnings(symbols, [], day)


def _read_macro() -> list[dict]:
    return json.loads(MACRO_FILE.read_text())["events"]


def _calendar(symbols: list[str], day: date, now: float) -> dict:
    """This week's earnings for the owner's symbols and the macro calendar's FOMC, CPI and jobs reports, today through
    Sunday. A day-only date (earnings) sorts as the start of its day."""
    from app.engine.chart_indices import is_index
    week_end = day + timedelta(days=6 - day.weekday())
    rows = []
    wanted = [s for s in symbols if not is_index(s)][:MAX_NEWS_SYMBOLS]
    blocks = _read_earnings(wanted, day) if wanted else {}
    for symbol in wanted:
        upcoming = (blocks.get(symbol) or {}).get("next") or None
        if not upcoming or not upcoming.get("date"):
            continue
        when = date.fromisoformat(upcoming["date"])
        if not day <= when <= week_end:
            continue
        at = int(datetime(when.year, when.month, when.day, tzinfo=ET).timestamp())
        status = upcoming.get("status")
        said = "today" if when == day else f"on {when:%A}"
        rows.append(_item("Calendar", f"earnings:{symbol}:{when}", at, f"{symbol} reports earnings {said}",
                          symbol=symbol, detail=f"Date {status}." if status else None, has_time=False))
    for event in _read_macro():
        when = date.fromisoformat(event["date"])
        if not day <= when <= week_end:
            continue
        hour, minute = (int(x) for x in event["time"].split(":"))
        at = int(datetime(when.year, when.month, when.day, hour, minute, tzinfo=ET).timestamp())
        rows.append(_item("Calendar", f"macro:{event['kind']}:{when}", at, f"{event['name']} at {event['time']} ET"))
    return {"state": "ok", "rows": rows}


def _chatter(now: float, held: set[str], blocked: set[str]) -> dict:
    from app.engine import chatter
    if not (chatter.wsb_enabled() or chatter.nyt_enabled()):
        return chatter.off()  # nothing set up: nothing read
    try:
        return chatter.view(held, blocked, now)
    except Exception as exc:  # chatter failing leaves the feed alone
        log.warning("feed chatter unavailable: %s", type(exc).__name__)
        return chatter.off()


def _brief(db: Session, day: date, symbols: set[str]) -> dict:
    from app.routers import today
    found = today._prep(db, day).get("prep")
    if not found:
        return {"state": "ok", "rows": []}
    at = _epoch(found.get("at"))
    if at is None:
        return {"state": "ok", "rows": []}
    rows = []
    for i, line in enumerate(found.get("lines") or []):
        named = next((w for w in re.findall(r"\b[A-Z]{1,6}\b", line) if w in symbols), None)
        item = _item("Copilot note", f"brief:{day}:{i}", at, _trim(line), symbol=named, detail="Morning brief")
        if found.get("path"):
            item["href"] = found["path"]
        rows.append(item)
        if len(rows) >= MAX_BRIEF_LINES:
            break
    return {"state": "ok", "rows": rows}


def _setup_words(setup: str) -> str:
    words = [w.upper() if w in CAPS else w for w in setup.split("_") if w]
    text = " ".join(words) or "Alert"
    return text[0].upper() + text[1:]


def _timeframe_words(timeframe: str) -> str:
    """TradingView's interval as the desk says it: "5" reads 5m, "60" 1h, "D" 1D."""
    if timeframe.isdigit():
        minutes = int(timeframe)
        return f"{minutes // 60}h" if minutes >= 60 and minutes % 60 == 0 else f"{minutes}m"
    return timeframe if timeframe[:1].isdigit() else f"1{timeframe}"


def _alert_price(value) -> str:
    number = float(value)
    return f"{number:,.2f}" if number >= 1 else f"{number:.4f}"


def tradingview_words(alert: dict) -> str:
    """One short line for what fired: "ORB break long · 5m at 94.12"."""
    return (f"{_setup_words(alert['setup'])} {alert['side']} · {_timeframe_words(alert['timeframe'])} "
            f"at {_alert_price(alert['price'])}")


def _fixture_alerts(now: float) -> list[dict]:
    """SIMULATED (sandbox only): two invented TradingView alerts today, on the copilot fixture's names."""
    return [
        {"alert_id": "fixture:nbis:orb_break:long", "symbol": "NBIS", "setup": "orb_break", "side": "long",
         "timeframe": "5", "price": 94.12, "at": int(now) - 14 * 60},
        {"alert_id": "fixture:crwv:vwap_reject:short", "symbol": "CRWV", "setup": "vwap_reject", "side": "short",
         "timeframe": "2", "price": 131.4, "at": int(now) - 52 * 60},
    ]


def tradingview_today(db: Session, now: float, mode: str = "live", symbol: str | None = None,
                      limit: int = MAX_TRADINGVIEW) -> list[dict]:
    """Today's stored TradingView alerts (New York day, by when they reached the webhook), newest first, as
    ``{alert_id, symbol, setup, side, timeframe, price, at}``. Light columns only; no provider call."""
    from app.engine import notification_policy as policy
    from app.models import TRADINGVIEW_ALERT_LIGHT, TradingViewAlert
    if mode == "fixture":
        return [a for a in _fixture_alerts(now) if symbol is None or a["symbol"] == symbol][:limit]
    start, end = policy.day_bounds(now)
    query = (select(TradingViewAlert).options(*TRADINGVIEW_ALERT_LIGHT)
             .where(TradingViewAlert.received_at >= start, TradingViewAlert.received_at < end))
    if symbol is not None:
        query = query.where(TradingViewAlert.symbol == symbol)
    rows = db.exec(query.order_by(col(TradingViewAlert.received_at).desc()).limit(limit)).all()
    return [{"alert_id": r.alert_id, "symbol": r.symbol, "setup": r.setup, "side": r.side, "timeframe": r.timeframe,
             "price": float(r.price), "at": _utc_epoch(r.received_at)} for r in rows]


def _last_alert_at(db: Session, now: float, mode: str, blocked: set[str]) -> int | None:
    """When the newest stored alert on a ticker he follows came in."""
    from app.models import TradingViewAlert
    if mode == "fixture":
        return max(a["at"] for a in _fixture_alerts(now))
    query = select(TradingViewAlert.received_at)
    if blocked:
        query = query.where(col(TradingViewAlert.symbol).not_in(sorted(blocked)))
    found = db.exec(query.order_by(col(TradingViewAlert.received_at).desc()).limit(1)).first()
    return _utc_epoch(found) if found is not None else None


def _tradingview(db: Session, now: float, mode: str) -> dict:
    rows = []
    for alert in tradingview_today(db, now, mode):
        item = _item("TradingView", alert["alert_id"], alert["at"], tradingview_words(alert), symbol=alert["symbol"],
                     plan="own")
        item["href"] = f"/signals/{quote(alert['alert_id'], safe='')}" if mode != "fixture" else None
        rows.append(item)
    return {"state": "ok", "rows": rows}


# --------------------------------------------------------------------------- the feed

def rank(items: list[dict], now: float) -> list[dict]:
    """Mine first, then the rest, each newest first; then what is still ahead, soonest first."""
    past = [i for i in items if not i["upcoming"]]
    ahead = sorted((i for i in items if i["upcoming"]), key=lambda i: i["at"])
    past.sort(key=lambda i: (not i["mine"], -i["at"]))
    return past + ahead


def build(db: Session, now: float, mode: str = "live") -> dict:
    """The feed at ``now`` as ``GET /copilot/desk/feed`` returns it."""
    from app.routers import today
    day = datetime.fromtimestamp(now, ET).date()
    moment = datetime.fromtimestamp(now, UTC)
    book = today._section(db, "feed book", lambda: _book(db))
    hidden = today._section(db, "feed hidden", lambda: _hidden(db))
    mine = (book.get("held", set()) | book.get("plans", set())) - hidden.get("symbols", set())
    symbols = sorted(mine)
    # The headlines and the Radar file wait on a provider or a file, not the journal: they start here, side by side,
    # and the journal's sections run beside them.
    since = today._section(db, "feed news window", lambda: {"state": "ok", "since": _news_since(day)})
    ahead = {"radar": today._ahead("feed radar", lambda: _radar(day))}
    if since["state"] == "ok":
        ahead["news"] = today._ahead("feed news", lambda: _news(symbols, since["since"], moment))
        ahead["market news"] = today._ahead("feed market news", lambda: _market_news(since["since"], moment))
    pings = today._section(db, "feed pings", lambda: _pings(db, now))
    pinged = {(r["symbol"], r.get("kind")) for r in pings.get("rows", [])}
    plans = today._section(db, "feed plans", lambda: _plans(db, now, pinged))
    setups = today._section(db, "feed radar setups", lambda: _setups(db, day))
    brief = today._section(db, "feed brief", lambda: _brief(db, day, mine))
    calendar = today._section(db, "feed calendar", lambda: _calendar(symbols, day, now))
    tradingview = today._section(db, "feed tradingview", lambda: _tradingview(db, now, mode))
    parts = {"pings": pings, "plans": plans, "radar": ahead["radar"].get(), "radar setups": setups, "brief": brief, "calendar": calendar,
             "tradingview": tradingview}
    if since["state"] == "ok":
        parts["news"], parts["market news"] = ahead["news"].get(), ahead["market news"].get()
    else:
        parts["news"] = parts["market news"] = since
    parts["book"], parts["hidden"] = book, hidden

    carded = {r["radar_event_id"] for r in parts["radar setups"].get("rows", [])}
    items = []
    for name, part in parts.items():
        for item in part.get("rows", []):
            if name == "radar" and item["radar_event_id"] in carded:
                continue  # its setup card says more
            items.append(item)
    blocked = hidden.get("symbols", set())
    if hidden["state"] != "ok":
        # Not knowing what is hidden, show only what cannot name a ticker: the macro calendar.
        items = [i for i in items if not i["symbol"] and i["source"] == "Calendar"]
    named = re.compile(r"\b(?:" + "|".join(re.escape(s) for s in sorted(blocked)) + r")\b") if blocked else None
    items = [i for i in items if i["symbol"] not in blocked and not set(i.pop("symbols", None) or ()) & blocked
             and not (named and (named.search(i["text"]) or named.search(i["detail"] or "")))]
    for item in items:
        item.pop("kind", None)
        own = item["source"] in ("Alert", "Plan", "Copilot note", "TradingView")  # always his book, plans, day or alerts
        item["mine"] = own or item["symbol"] in mine
        item["upcoming"] = item["at"] > now
        if item["plan"] is None and item["source"] in ("Alert", "Plan") and item["symbol"] in mine:
            item["plan"] = "own"  # his own position or plan: its plan thread, or the plan form; never on a model's note
    ranked = rank(items, now)
    ahead = [i for i in ranked if i["upcoming"]][:MAX_UPCOMING]
    shown = [i for i in ranked if not i["upcoming"]][: MAX_ITEMS - len(ahead)] + ahead
    states = {name: part["state"] for name, part in parts.items()}
    if hidden["state"] == "ok":
        chatter = _chatter(now, book.get("held", set()), blocked)
    else:  # not knowing what is hidden, chatter (which names tickers) stays out
        from app.engine.chatter import off
        chatter = off()
    last = None
    if hidden["state"] == "ok" and tradingview["state"] == "ok":
        last = today._section(db, "feed tradingview last", lambda: {"state": "ok", "at": _last_alert_at(db, now, mode, blocked)})
    return {"as_of": today._iso(now), "now": int(now), "day": day.isoformat(), "items": shown, "total": len(ranked),
            "sources": states, "unavailable": sorted(n for n, s in states.items() if s == "unavailable"),
            "chatter": chatter, "tradingview": {"last_at": (last or {}).get("at")}}
