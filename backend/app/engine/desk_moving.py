"""The desk's "what's moving" strip (``GET /copilot/desk/moving``): where the action is today, at a glance.

Two kinds of tile, in this order:

- **Groups**: SPY, QQQ and IWM, the sector ETFs, then his own groupings: the Watching list as one group and the
  Research tab's AI-buildout groups (``ai_buildout_seed.json`` ``layers[].group``, the workspace's saved copy when there
  is one). An ETF's change is its own; a group's is the median of its members' with a change (at least half of them,
  or the group is left out). Each group lists its members for the strip's popover.
- **Movers**: the biggest day changes among the names he holds or watches first, then the broad movers Radar's recorder
  already has (its universe's stocks), each with a one- or two-word reason only when the app already knows one: an
  earnings report today or the session before (the earnings cache), a Radar setup card or a Radar event today.

Where a change comes from, cheapest first:

1. **Radar's recorder**: the newest recorded pass of the newest session with one (no provider call). In the regular
   session it is used only while it is current (``STALE_SECONDS``); outside it, it is the last session's close.
2. **One batched quote read** (``chart_feed.quote_rows``: one Tradier call for every symbol at once, inside the chart
   feed's call cap) for the names the recorder does not cover, only in the regular session and after today's close
   (then from the quote's regular-session close). Before the open and on a day with no session the quote's previous
   close has rolled, so those names have no change rather than a wrong one.

A change is kept ``CACHE_SECONDS``; the Radar read too. A ticker set to Not following never appears in a mover or a
group's member list; if that setting cannot be read, no movers and no Watching group are shown. When neither source
has anything, ``state`` is ``unavailable`` and the strip says so in one grey line: never a zero.

Read-only: no Robinhood call (his live positions come from the feed's last snapshot, ``kick=False``), no write.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
import logging
import math
from statistics import median
import threading
import time

from sqlmodel import Session, select

from app.engine.chart_math import ET

log = logging.getLogger(__name__)

CACHE_SECONDS = 45
STALE_SECONDS = 180  # the recorder writes a pass a minute (routers/radar.py STALE_SECONDS)
INDEX = ("SPY", "QQQ", "IWM")
SECTORS = ("XLK", "SMH", "XLC", "XLY", "XLF", "XLV", "XLI", "XLE", "XLP", "XLU", "XLB", "XLRE")
SECTOR_NAMES = {"XLK": "Tech", "SMH": "Semis", "XLC": "Comms", "XLY": "Discretionary", "XLF": "Financials",
                "XLV": "Health care", "XLI": "Industrials", "XLE": "Energy", "XLP": "Staples", "XLU": "Utilities",
                "XLB": "Materials", "XLRE": "Real estate"}
MINE = 6  # his own movers shown
BROAD = 8  # the recorder's movers shown after his
MEMBERS = 30  # a group's popover list
QUOTE_MAX = 250  # symbols in the one batched read: the ETFs, his held and watched names and every research company fit
REASON = {"dip_turn": "Dip turn", "gap_reversal": "Gap reversal", "group_move": "Group move",
          "relative_to_spy": "Radar", "relative_to_sector": "Radar"}

_lock = threading.Lock()  # one fill at a time: a second request waits and finds the first one's read
_changes: dict[str, tuple[float, date, float | None]] = {}  # symbol -> (valid until, New York date, change %)
_radar: tuple[float, dict] | None = None  # (valid until, the recorder's read)


def clear() -> None:
    global _radar
    with _lock:
        _changes.clear()
        _radar = None


# ------------------------------------------------------------------ Radar's recorder


def _pct(last, prev) -> float | None:
    try:
        last, prev = float(last), float(prev)
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(last) and math.isfinite(prev)) or last <= 0 or prev <= 0:
        return None
    return round((last / prev - 1) * 100, 2)


def _read_radar(day: date) -> dict:
    """{"session", "pass_at" (epoch), "pct": {symbol: change %}, "universe", "sectors": {stock: sector ETF},
    "events": {symbol: reason}} from the newest session on or before ``day`` with a recorded pass; {} when Radar is off,
    unreadable or has nothing."""
    from app.engine.radar_comparison import _endpoint, epoch
    from app.engine.radar_store import load_universe
    from app.routers import radar
    store, _reason = radar._store(read_only=True)
    if store is None:
        return {}
    for session in store.sessions():
        if session > day.isoformat():
            continue
        recorded = [p for p in store.passes(session) if p["status"] in ("ok", "partial")]
        if not recorded:
            continue
        latest = recorded[-1]
        pct = {}
        for q in store.quotes(pass_id=latest["id"]):
            if _endpoint(q, latest)[0] is not None and (change := _pct(q.get("last"), q.get("prev_close"))) is not None:
                pct[q["symbol"]] = change
        universe = load_universe()
        events: dict[str, str] = {}
        for event in store.events(session):  # oldest first: the newest event's words win
            words = REASON.get(event.get("kind"))
            for symbol in event.get("symbols") or []:
                if words and isinstance(symbol, str):
                    events[symbol] = words
        return {"session": session, "pass_at": epoch(latest["started_at"]), "pct": pct,
                "stocks": [r["symbol"] for r in universe["symbols"] if r["kind"] == "stock" and not r.get("benchmark")],
                "sectors": {r["symbol"]: r["sector"] for r in universe["symbols"] if r.get("sector")}, "events": events}
    return {}


def _recorded(now: float, day: date) -> dict:
    global _radar
    if _radar is not None and now < _radar[0]:
        return _radar[1]
    try:
        found = _read_radar(day)
    except Exception:  # noqa: BLE001 -- the file is one source: the quote read still serves the strip
        log.warning("desk moving: the Radar file could not be read", exc_info=True)
        found = {}
    _radar = (now + CACHE_SECONDS, found)
    return found


# ------------------------------------------------------------------ the batched quote read


def _quote(symbols: list[str], now: float, day: date, after_close: bool) -> None:
    """One batched read for the symbols with no kept change; each is kept (a missing one as None, so a name the provider
    does not know is not asked again for ``CACHE_SECONDS``). A failed or stale read keeps nothing."""
    from app.engine.chart_feed import chart_feed
    if not symbols:
        return
    try:
        rows, stamp, issue = chart_feed.quote_rows(symbols[:QUOTE_MAX])
    except Exception:  # noqa: BLE001 -- these names go without a change this time
        log.warning("desk moving: the batched quote read failed", exc_info=True)
        return
    if issue and (stamp is None or time.time() - stamp > 120):
        return  # old rows handed back by a failed read are not today's move
    found = {r.get("symbol"): r for r in rows}
    for symbol in symbols[:QUOTE_MAX]:
        row = found.get(symbol) or {}
        if after_close:  # the regular session's close, not an after-hours print
            change = _pct(row.get("regular_close"), row.get("previous_close"))
        else:
            change = row.get("change_percentage")
            change = round(float(change), 2) if isinstance(change, (int, float)) and math.isfinite(change) else None
        _changes[symbol] = (now + CACHE_SECONDS, day, change)


# ------------------------------------------------------------------ his names, groups and reasons


def _hidden(db: Session) -> set[str] | None:
    from app.engine import day_journal
    try:
        return day_journal.not_following(db)
    except Exception:  # noqa: BLE001 -- unread: nothing personal is shown rather than risk a hidden ticker
        log.warning("desk moving: the follow setting could not be read", exc_info=True)
        db.rollback()
        return None


def _held(db: Session) -> list[str]:
    """Open positions' tickers (the journal, Webull left out like the rest of the desk) and Robinhood's last snapshot,
    read without asking Robinhood again."""
    from app.ai.copilot_book import _not_webull
    from app.models import Account, Trade
    held = set(db.exec(select(Trade.ticker).join(Account, Account.id == Trade.account_id)
                       .where(Trade.status == "open").where(_not_webull())).all())
    try:
        from app.engine.robinhood_book import feed
        _view, snapshot = feed.snapshot(kick=False)
        held |= {p["symbol"] for p in (snapshot or {}).get("positions", []) if p.get("symbol")}
    except Exception:  # noqa: BLE001 -- the journal's list stands
        log.warning("desk moving: the Robinhood snapshot could not be read", exc_info=True)
    return sorted(s.upper() for s in held if s)


def _watched(db: Session) -> list[str]:
    from app.engine import desk_watch
    try:
        return list(desk_watch.state(db)["symbols"])
    except Exception:  # noqa: BLE001 -- no Watching group this time
        log.warning("desk moving: the Watching list could not be read", exc_info=True)
        db.rollback()
        return []


def _research(db: Session) -> list[tuple[str, list[str]]]:
    """His Research tab's AI-buildout groups in the tab's order, each with its companies' tickers (the saved workspace
    when there is one, else the seed). Read only: the workspace is never created here."""
    import json
    from app.engine import research
    from app.models import ResearchWorkspace
    data = research.load_seed("ai-buildout") or {}
    try:
        row = db.exec(select(ResearchWorkspace).where(ResearchWorkspace.slug == "ai-buildout")).first()
        if row is not None:
            data = research.deep_merge(data, json.loads(row.data_json))
    except Exception:  # noqa: BLE001 -- the seed's groups stand
        log.warning("desk moving: the research workspace could not be read", exc_info=True)
        db.rollback()
    layers = data.get("layers") or {}
    by_layer: dict[str, list[str]] = defaultdict(list)
    for ticker, company in (data.get("companies") or {}).items():
        if isinstance(company, dict) and isinstance(company.get("layer"), str):
            by_layer[company["layer"]].append(str(company.get("ticker") or ticker).upper())
    groups: dict[str, list[str]] = {}
    for layer in data.get("order") or list(layers):
        name = (layers.get(layer) or {}).get("group")
        if isinstance(name, str) and name:
            members = groups.setdefault(name, [])
            members += [t for t in by_layer.get(layer, []) if t not in members]
    return [(name, members) for name, members in groups.items() if members]


def _previous_weekday(day: date) -> date:
    back = day - timedelta(days=1)
    while back.weekday() >= 5:
        back -= timedelta(days=1)
    return back


def _earnings(symbols: list[str], session: date) -> set[str]:
    """Symbols that report on ``session`` or reported the weekday before it (after that close), from the earnings cache
    only: a symbol with no cached calendar has no reason, and nothing here starts a refresh (``chart_earnings`` would)."""
    from app.engine.chart_indices import is_index
    from app.engine.symbol_info_tradier import symbol_events
    wanted = [s for s in symbols if not is_index(s)]
    if not wanted:
        return set()
    try:
        blocks = {s: symbol_events._earnings(s, session, None, None) for s in wanted}
    except Exception:  # noqa: BLE001 -- no earnings reason this time
        log.warning("desk moving: the earnings cache could not be read", exc_info=True)
        return set()
    days = {session.isoformat(), _previous_weekday(session).isoformat()}
    out = set()
    for symbol, block in blocks.items():
        upcoming = (block or {}).get("next") or {}
        reports = (block or {}).get("reports") or []
        if upcoming.get("date") == session.isoformat() or (reports and reports[0].get("date") in days):
            out.add(symbol)
    return out


def _setups(db: Session, session: str) -> dict[str, str]:
    from app.models import RadarSetup
    try:
        rows = db.exec(select(RadarSetup.symbol, RadarSetup.kind).where(RadarSetup.session_date == session)
                       .order_by(RadarSetup.created_at)).all()
    except Exception:  # noqa: BLE001 -- the Radar events' words stand
        db.rollback()
        return {}
    return {symbol: REASON[kind] for symbol, kind in rows if kind in REASON}


# ------------------------------------------------------------------ building


def _group(key: str, label: str, kind: str, members: list[str], change: float | None, pct: dict, hidden: set[str],
           symbol: str | None = None) -> dict:
    listed = [m for m in members if m not in hidden][:MEMBERS]
    return {"key": key, "label": label, "kind": kind, "symbol": symbol, "change_pct": change,
            "members": [{"symbol": m, "change_pct": pct.get(m)} for m in listed]}


def _down(pct: dict):
    """Members by change, biggest gain first; a member with no change last."""
    return lambda m: (pct.get(m) is None, -(pct.get(m) or 0.0), m)


def _median(members: list[str], pct: dict) -> float | None:
    known = [pct[m] for m in members if pct.get(m) is not None]
    if not known or len(known) * 2 < len(members):
        return None
    return round(median(known), 2)


def build(db: Session, now: float) -> dict:
    from app.engine.desk_sparks import _session
    from app.engine.request_timing import timed
    day, phase, _hours, regular = _session(now)
    hidden = _hidden(db)
    held = _held(db)
    watched = _watched(db)
    research = _research(db)
    after_close = regular is not None and now >= regular[1]
    with _lock:
        with timed("moving radar"):
            radar = _recorded(now, day)
        radar_live = bool(radar) and radar["session"] == day.isoformat() and now - radar["pass_at"] <= STALE_SECONDS
        if phase == "regular":
            mode, recorded = "live", radar if radar_live else {}
        elif after_close:
            mode, recorded = "close", radar if radar.get("session") == day.isoformat() else {}
        else:  # before the open, or a day with no session: the last session's close, the recorder's only
            mode, recorded = "close", radar
        from_radar = recorded.get("pct", {})
        names = [*INDEX, *SECTORS, *held, *watched, *(m for _n, members in research for m in members)]
        names = list(dict.fromkeys(n for n in names if n not in from_radar))
        if phase == "regular" or after_close:
            with timed("moving quotes"):
                need = [n for n in names if not (n in _changes and now < _changes[n][0] and _changes[n][1] == day)]
                _quote(need, now, day, after_close)
            quoted = {n: _changes[n][2] for n in names if n in _changes and _changes[n][1] == day and now < _changes[n][0]}
        else:
            quoted = {}
        if len(_changes) > 512:
            _changes.clear()
    pct = {**{k: v for k, v in quoted.items() if v is not None}, **from_radar}
    session = recorded.get("session") or (day.isoformat() if quoted else None)
    # A follow setting that cannot be read lists no members (a hidden name could be among them) and no movers.
    shown_hidden = hidden if hidden is not None else set()
    listed = hidden is not None

    groups = [_group(s, s, "index", [], pct.get(s), pct, shown_hidden, symbol=s) for s in INDEX if pct.get(s) is not None]
    sectors = defaultdict(list)
    for stock, sector in (recorded.get("sectors") or {}).items():
        sectors[sector].append(stock)
    sector_tiles = [_group(s, SECTOR_NAMES[s], "sector", sorted(sectors.get(s, []), key=_down(pct)) if listed else [],
                           pct.get(s), pct, shown_hidden, symbol=s) for s in SECTORS if pct.get(s) is not None]
    groups += sorted(sector_tiles, key=lambda g: -g["change_pct"])
    if hidden is not None:
        mine = [s for s in watched if s not in hidden]
        if mine and (change := _median(mine, pct)) is not None:
            groups.append(_group("watching", "Watching", "watching", sorted(mine, key=_down(pct)),
                                 change, pct, hidden))
    own = []
    for name, members in research:
        members = [m for m in members if m not in shown_hidden]  # a hidden name does not move his group either
        if (change := _median(members, pct)) is not None:
            own.append(_group(f"research:{name}", name, "research", sorted(members, key=_down(pct)) if listed else [],
                              change, pct, shown_hidden))
    groups += sorted(own, key=lambda g: -g["change_pct"])

    movers: list[dict] = []
    if hidden is not None:
        etfs = {*INDEX, *SECTORS}
        personal = [s for s in dict.fromkeys([*held, *watched]) if s not in hidden and s not in etfs and pct.get(s) is not None]
        personal.sort(key=lambda s: (-abs(pct[s]), s))
        movers = [{"symbol": s, "change_pct": pct[s], "mine": True} for s in personal[:MINE]]
        taken = {m["symbol"] for m in movers}
        broad = [s for s in recorded.get("stocks", []) if s not in hidden and s not in taken and from_radar.get(s) is not None]
        broad.sort(key=lambda s: (-abs(from_radar[s]), s))
        movers += [{"symbol": s, "change_pct": from_radar[s], "mine": False} for s in broad[:BROAD]]
        if movers and session:
            with timed("moving reasons"):
                reported = _earnings([m["symbol"] for m in movers], date.fromisoformat(session))
                setups = _setups(db, session)
            events = recorded.get("events", {}) if recorded.get("session") == session else {}
            for m in movers:
                s = m["symbol"]
                m["reason"] = "Earnings" if s in reported else setups.get(s) or events.get(s)

    available = bool(groups or movers)
    return {
        "state": "ok" if available else "unavailable",
        "mode": mode if available else None,
        "session": session if available else None,
        "as_of": datetime.fromtimestamp(now, ET).isoformat(timespec="seconds"),
        "reason": None if available else "Market moves are unavailable right now.",
        "groups": groups,
        "movers": movers,
    }
