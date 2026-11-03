"""The copilot's market regime and Radar-today reads (docs/copilot-lab.md § What runs, docs/radar.md § What the copilot reads).

``get_market_regime`` is the backdrop a move sits in: SPY, QQQ, IWM and RSP and the symbol's sector ETF from the latest
recorded Radar pass, VIX and the 10-year through the chart feed's index quotes, the macro calendar, and the symbol's
next earnings from the fundamentals cache. ``get_radar_today`` is the session's Radar feed as the screen shows it, cut
at a moment. Live reads the same stores and caches the Radar and Charts tabs use; replay cuts every recorded read at the
frozen moment and marks the fetched ones unavailable; the fixture serves the NBIS scenario. Nothing here writes.
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import UTC, date, datetime

from app.engine import radar_regime, radar_today
from app.engine.chart_math import ET
from app.engine.radar_movers import earlier_pass
from app.engine.radar_store import RadarStore, load_universe

log = logging.getLogger(__name__)

RADAR_NOTE = ("day_pct is versus the previous close from the latest recorded Radar pass; last_15m_pct is against the pass "
              "about 15 minutes earlier (null without one). Recorded sampled observations, not live quotes.")
VIX_NOTE = "VIX in index points; US10Y is the 10-year yield in percent (TNX / 10), change in basis points."
UNREADABLE = "The Radar file could not be read right now."
OFF_HOURS_INDEXES = ("SPY", "QQQ", "IWM", "SMH")  # the market's off-hours move, from their own pre- and after-hours trades


def _iso(value: float) -> str:
    return datetime.fromtimestamp(value, UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def pick_session(store: RadarStore, today: date) -> tuple[str, bool]:
    """Today's session when Radar has recorded it, else the newest recorded one (a weekend asks about the last session)."""
    sessions = store.sessions()
    day = today.isoformat()
    if day in sessions or not sessions:
        return day, False
    return sessions[0], True


def radar_backdrop(store: RadarStore, session: str, before: float | None, symbol: str | None,
                   universe: dict | None = None) -> dict:
    """The indices and the symbol's sector ETF from the latest recorded pass at or before ``before``."""
    universe = universe or load_universe()
    passes = [p for p in store.passes(session) if p["status"] in radar_today.RECORDED
              and radar_today._before(p["started_at"], before) and radar_today._before(p["finished_at"], before)]
    if not passes:
        return {"state": "no_data", "reason": "Nothing has been recorded for this session yet."}
    latest = passes[-1]
    earlier = earlier_pass(passes, latest)
    quotes = store.pass_quotes([latest["id"]] + ([earlier["id"]] if earlier else []))
    sector = radar_regime.sector_of(universe, symbol) if symbol else None
    wanted = [*radar_regime.INDICES, *([sector, symbol] if sector else [])]
    moves = radar_regime.day_moves(universe, list(quotes[latest["id"]].values()),
                                   list(quotes[earlier["id"]].values()) if earlier else None,
                                   latest=latest, earlier=earlier, symbols=wanted)
    out = {"state": "ok", "pass_at": latest["started_at"], "earlier_pass_at": earlier["started_at"] if earlier else None,
           "indices": {s: moves.get(s) for s in radar_regime.INDICES}, "note": RADAR_NOTE}
    if symbol:
        if sector is None:
            out["sector"] = {"state": "untracked", "reason": f"Radar does not track {symbol}, so it has no sector ETF here."}
        elif sector not in moves:
            out["sector"] = {"state": "missing", "etf": sector, "reason": f"{sector} has no usable quote in the latest pass."}
        else:
            mine = moves.get(symbol)
            out["sector"] = {"state": "ok", "etf": sector, **moves[sector],
                             "symbol_day_pct": mine["day_pct"] if mine else None,
                             "symbol_vs_sector_pct": round(mine["day_pct"] - moves[sector]["day_pct"], 3) if mine else None,
                             "symbol_vs_spy_pct": round(mine["day_pct"] - moves["SPY"]["day_pct"], 3)
                             if mine and moves.get("SPY") else None}
    return out


def index_quotes() -> tuple[dict, dict]:
    """VIX and the 10-year through the chart feed's index mapping (one bounded Tradier GET, 15 s cache)."""
    from app.engine.chart_feed import ChartFeedError, chart_feed
    try:
        rows, _stamp, issue = chart_feed.quote_rows(["VIX", "US10Y"])
    except ChartFeedError as exc:
        gone = {"state": "unavailable", "reason": str(exc)}
        return gone, dict(gone)
    found = {r["symbol"]: r for r in rows}

    def when(row):
        return _iso(row["trade_time"]) if row.get("trade_time") else None

    vix = found.get("VIX")
    tnx = found.get("US10Y")
    out_vix = ({"state": "ok", "last": vix.get("last"), "change_pct": _round(vix.get("change_percentage")), "as_of": when(vix)}
               if vix and vix.get("last") is not None else {"state": "unavailable", "reason": issue or "VIX was not in the quote read."})
    out_tnx = ({"state": "ok", "yield_pct": _round(tnx.get("last"), 3), "change_bps": _round(tnx.get("change_bps"), 1),
                "as_of": when(tnx)}
               if tnx and tnx.get("last") is not None else {"state": "unavailable", "reason": issue or "US10Y was not in the quote read."})
    if issue:
        out_vix["issue"] = out_tnx["issue"] = issue
    return out_vix, out_tnx


def _round(value, digits: int = 2):
    return None if value is None else round(float(value), digits)


def macro(day: date) -> dict:
    from app.ai.review_context import macro_events
    try:
        return {"state": "ok", **macro_events(day)}
    except (LookupError, OSError, ValueError) as exc:
        return {"state": "unavailable", "reason": str(exc)}


def earnings_from_cache(symbol: str, today: date) -> dict:
    """The symbol's next report from the fundamentals cache only (a cold symbol refreshes in the background: no wait)."""
    from app.engine import symbol_info_tradier
    block = symbol_info_tradier.symbol_events.chart_earnings([symbol], [], today).get(symbol) or {}
    out = {"state": block.get("state"), "next": block.get("next"),
           "fetched_at": _iso(block["fetched_at"]) if block.get("fetched_at") else None}
    if block.get("state") == "loading":
        out["reason"] = "Not cached yet; get_symbol_events reads it."
    elif block.get("message"):
        out["reason"] = block["message"]
    return out


def live_regime(symbol: str | None, now: datetime) -> dict:
    from app.routers import radar
    today = now.astimezone(ET).date()
    out: dict = {"symbol": symbol, "as_of": _iso(now.timestamp()), "session": today.isoformat()}
    store, reason = radar._store(read_only=True)
    if store is None:
        out["radar"] = {"state": "off", "reason": reason}
    else:
        try:
            session, prior = pick_session(store, today)
            out["session"] = session
            if prior:
                out["prior_session"] = True
            out["radar"] = radar_backdrop(store, session, None, symbol)
        except (sqlite3.Error, ValueError, KeyError, OSError) as exc:
            log.warning("copilot regime radar unreadable: %s", exc)
            out["radar"] = {"state": "error", "reason": UNREADABLE}
    out["vix"], out["us10y"] = index_quotes()
    from app.ai import copilot_extended
    off_hours = copilot_extended.extended([*OFF_HOURS_INDEXES, *([symbol] if symbol else [])], now)
    if off_hours:
        out["extended"] = off_hours  # before the open Radar has no pass yet and VIX reads its last close
    out["macro"] = macro(today)
    out["earnings"] = earnings_from_cache(symbol, today) if symbol else None
    out["note"] = VIX_NOTE
    return out


def replay_regime(store: RadarStore, session: str, now: float, at: datetime, symbol: str | None,
                  next_earnings: dict | None) -> dict:
    """The frozen moment's backdrop: Radar cut at ``now``; VIX and the 10-year are not in the snapshot."""
    gone = {"state": "unavailable", "reason": "Not in the Radar snapshot, so unavailable in replay."}
    return {"symbol": symbol, "as_of": at.isoformat(timespec="minutes"), "session": session,
            "radar": radar_backdrop(store, session, now, symbol), "vix": gone, "us10y": dict(gone),
            "macro": macro(at.date()),
            "earnings": {"state": "ready" if next_earnings else "none", "next": next_earnings} if symbol else None,
            "note": VIX_NOTE}


def live_radar_today(group: str | None, limit: int, now: datetime, most: int) -> dict:
    from app.routers import radar
    today = now.astimezone(ET).date()
    store, reason = radar._store(read_only=True)
    from app.ai import copilot_extended
    early = copilot_extended.phase(now) == "pre-market"
    if store is None:
        out = {"state": "off", "reason": reason, "session": today.isoformat(), "events": [], "movers": None}
        return {**out, "premarket_scan": copilot_extended.premarket_scan(None, today)} if early else out
    try:
        session, prior = pick_session(store, today)
        out = radar_today.feed(store, session, None, group=group, limit=limit)
    except (sqlite3.Error, ValueError, KeyError, OSError) as exc:
        log.warning("copilot radar today unreadable: %s", exc)
        return {"state": "error", "reason": UNREADABLE, "session": today.isoformat(), "events": [], "movers": None}
    if prior:
        out["prior_session"] = True
    if early:  # Radar's first pass is at the open; the pilot's scans are the pre-market's
        out["premarket_scan"] = copilot_extended.premarket_scan(str(store.path), today)
    return radar_today.bounded(out, most)


def replay_radar_today(store: RadarStore, session: str, now: float, group: str | None, limit: int, most: int) -> dict:
    return radar_today.bounded(radar_today.feed(store, session, now, group=group, limit=limit), most)


# --------------------------------------------------------------------------- the fixture's NBIS scenario

FIXTURE_AT = "2026-10-23T15:12:00Z"
_FIXTURE_INDICES = {"SPY": {"last": 671.10, "day_pct": -0.20, "from_open_pct": -0.35, "open_gap_pct": 0.15, "last_15m_pct": 0.09},
                    "QQQ": {"last": 598.40, "day_pct": -0.35, "from_open_pct": -0.52, "open_gap_pct": 0.17, "last_15m_pct": 0.18},
                    "IWM": {"last": 241.30, "day_pct": -0.62, "from_open_pct": -0.70, "open_gap_pct": 0.08, "last_15m_pct": 0.05},
                    "RSP": {"last": 188.75, "day_pct": -0.28, "from_open_pct": -0.33, "open_gap_pct": 0.05, "last_15m_pct": 0.04}}
_FIXTURE_XLK = {"last": 262.10, "day_pct": -0.48, "from_open_pct": -0.61, "open_gap_pct": 0.13, "last_15m_pct": 0.12}


def fixture_regime(symbol: str | None, session_pct: dict, next_earnings: dict | None) -> dict:
    universe = load_universe()
    radar = {"state": "ok", "pass_at": FIXTURE_AT, "earlier_pass_at": "2026-10-23T14:57:00Z", "indices": _FIXTURE_INDICES,
             "note": RADAR_NOTE}
    if symbol:
        sector = radar_regime.sector_of(universe, symbol)
        mine = session_pct.get(symbol)
        if sector is None:
            radar["sector"] = {"state": "untracked", "reason": f"Radar does not track {symbol}, so it has no sector ETF here."}
        else:
            radar["sector"] = {"state": "ok", "etf": sector, **_FIXTURE_XLK, "symbol_day_pct": mine,
                               "symbol_vs_sector_pct": round(mine - _FIXTURE_XLK["day_pct"], 3) if mine is not None else None,
                               "symbol_vs_spy_pct": round(mine - _FIXTURE_INDICES["SPY"]["day_pct"], 3) if mine is not None else None}
    return {"symbol": symbol, "as_of": FIXTURE_AT, "session": "2026-10-23", "radar": radar,
            "vix": {"state": "ok", "last": 18.4, "change_pct": 4.2, "as_of": FIXTURE_AT},
            "us10y": {"state": "ok", "yield_pct": 4.12, "change_bps": 3.0, "as_of": FIXTURE_AT},
            "macro": macro(date(2026, 10, 23)),
            "earnings": {"state": "ready" if next_earnings else "none", "next": next_earnings} if symbol else None,
            "note": VIX_NOTE}


def fixture_radar_today(group_name: str, session_pct: dict, group: str | None, limit: int) -> dict:
    spy = session_pct["SPY"]
    stocks = {s: v for s, v in session_pct.items() if s not in ("SPY", "QQQ")}
    ranked = sorted(stocks, key=lambda s: -(stocks[s] - spy))

    def row(s):
        return {"symbol": s, "last": None, "day_pct": stocks[s], "from_open_pct": None, "vs_spy": round(stocks[s] - spy, 3),
                "sector": "XLK", "vs_sector": round(stocks[s] - _FIXTURE_XLK["day_pct"], 3), "last_15m_pct": None}

    events = [
        {"event_id": "rad_sim_neocloud_1", "kind": "group_move", "direction": "up", "symbols": ["CRWV", "APLD", "NBIS", "WULF", "IREN"],
         "benchmark": group_name, "group": group_name, "first_seen_at": "2026-10-23T14:58:00Z",
         "summary": f"{group_name}: 5 of 7 members up against SPY over 15 minutes, led by CRWV +1.9%.",
         "measures": {"members_up": 5, "members": 7, "median_vs_spy": 0.45}, "latest": None, "news": None, "rating": None},
        {"event_id": "rad_sim_crwv_1", "kind": "relative_to_sector", "direction": "up", "symbols": ["CRWV"], "benchmark": "XLK",
         "group": group_name, "first_seen_at": "2026-10-23T13:56:00Z",
         "summary": "CRWV up 3.4% while XLK is down 0.2%: 3.6 points ahead of its sector on 2.1x usual volume.",
         "measures": {"change_pct": 3.4, "benchmark_change_pct": -0.2, "relative_pct": 3.6, "volume_ratio": 2.1},
         "latest": {"status": "faded", "recorded_at": "2026-10-23T14:46:00Z", "note": "Lead narrowed from 3.6 to 0.2 points over the next 50 minutes.",
                    "measures": {"change_pct": -0.4, "benchmark_change_pct": -0.6, "relative_pct": 0.2, "volume_ratio": 1.8}},
         "news": {"status": "found", "checked_at": "2026-10-23T14:05:00Z",
                  "headlines": [{"headline": "CoreWeave extends gains on reported capacity deal", "source": "Simulated Wire",
                                 "published_at": "2026-10-23T13:55:00Z", "timing": "before"}]}, "rating": None},
        {"event_id": "rad_sim_nbis_1", "kind": "dip_turn", "direction": "up", "symbols": ["NBIS"], "benchmark": "SPY", "group": group_name,
         "first_seen_at": "2026-10-23T14:30:00Z",
         "summary": "NBIS turned up from its session low 92.40 (down 4.9%) and has recovered 2.1% while SPY is flat.",
         "measures": {"from_low_pct": 2.1, "session_pct": -2.95, "spy_pct": -0.2}, "latest": None,
         "news": {"status": "none_found", "checked_at": "2026-10-23T14:35:00Z", "headlines": []}, "rating": None},
    ]
    kept = [e for e in events if radar_today._matches(e, group)]
    out = {"state": "ok", "session": "2026-10-23", "as_of": FIXTURE_AT, "events_total": len(kept), "events": kept[:limit],
           "movers": {"pass_at": FIXTURE_AT, "earlier_pass_at": "2026-10-23T14:57:00Z", "spy_day_pct": spy,
                      "qqq_day_pct": session_pct["QQQ"], "symbols_with_data": 9, "symbols_tracked": 9,
                      "leaders": [row(s) for s in ranked[:radar_today.MAX_LEADERS]],
                      "laggards": [row(s) for s in ranked[::-1][:radar_today.MAX_LEADERS]],
                      "groups": [{"name": group_name, "members_with_data": 7, "ahead": sum(stocks[s] > spy for s in stocks),
                                  "behind": sum(stocks[s] < spy for s in stocks), "median_vs_spy": round(sorted(stocks[s] - spy for s in stocks)[3], 3),
                                  "most": {"symbol": ranked[-1], "vs_spy": round(stocks[ranked[-1]] - spy, 3)}}]},
           "passes_recorded": 103}
    if group:
        out["group"] = group
    return out
