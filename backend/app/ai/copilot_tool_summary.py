"""One plain fact line per tool result, for the copilot's wait before the model's first word.

Built on the server from the result itself, never by the model: numbers only at the precision the result gives, times
in New York. A tool with nothing summarisable gets ``None``; so does any result this cannot read (``summarize`` never
raises). Headlines and other third-party text are summarised by counts and times, never quoted.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from typing import Any, Callable
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
MAX_CHARS = 90


def _pct(value: Any) -> str:
    return f"{value:+g}%"


def _num(value: Any) -> str:
    return f"{value:,g}" if abs(value) < 1e6 else f"{value:,.0f}"


def _usd(value: Any) -> str:
    return f"{'-' if value < 0 else '+'}${abs(value):,g}"


def _when(value: Any) -> datetime | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return datetime.fromtimestamp(value, ET)
    if isinstance(value, str) and value:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return stamp.astimezone(ET) if stamp.tzinfo else stamp
    return None


def _clock(value: Any) -> str | None:
    stamp = _when(value)
    return f"{stamp:%H:%M}" if stamp else None


def _at(value: Any) -> str:
    clock = _clock(value)
    return f" ({clock})" if clock else ""


def _short_date(value: str) -> str:
    day = datetime.fromisoformat(value[:10])
    return f"{day:%b} {day.day}"


def _is_num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def group_comparison(d: dict) -> str | None:
    window = d.get("recent_15m") or {}
    rows = {r["symbol"]: r for r in window.get("rows") or [] if _is_num(r.get("change_pct"))}
    cov = window.get("coverage") or {}
    parts = []
    sel = d.get("symbol")
    if sel in rows:
        bench = next((s for s in ("SPY", "QQQ") if s in rows), None)
        parts.append(f"{sel} {_pct(rows[sel]['change_pct'])}" + (f" vs {bench} {_pct(rows[bench]['change_pct'])}" if bench else ""))
    if cov.get("peers_total"):
        parts.append(f"{cov.get('peers_up')} of {cov['peers_total']} peers up")
    if not parts:
        return None
    minutes = window.get("window_minutes")
    span = f"{minutes:g}m" if _is_num(minutes) else ""
    end = _clock((window.get("window") or {}).get("end"))
    tail = ", ".join(x for x in (span, end) if x)
    return ", ".join(parts) + (f" ({tail})" if tail else "")


def peer_moves(d: dict) -> str | None:
    peers = [p for p in d.get("peers") or [] if _is_num(p.get("change_pct"))]
    if not peers:
        return None
    lead = max(peers, key=lambda p: p["change_pct"])
    up = sum(p["change_pct"] > 0 for p in peers)
    return f"Peers: {up} of {len(peers)} up, {lead['symbol']} leads {_pct(lead['change_pct'])}"


def symbol_news(d: dict) -> str | None:
    articles = d.get("articles")
    if not isinstance(articles, list):
        return None
    if not articles:
        return "No headlines found"
    times = sorted(t for t in (_when(a.get("published_at")) for a in articles if isinstance(a, dict)) if t)
    count = f"{len(articles)} headline{'s' if len(articles) != 1 else ''}"
    if not times:
        return count
    first, last = times[0], times[-1]
    if first.date() == last.date():
        return f"{count} since {first:%H:%M}, latest {last:%H:%M}" if first != last else f"{count}, at {last:%H:%M}"
    return f"{count}, latest {last:%b} {last.day} {last:%H:%M}"


def quotes(d: dict) -> str | None:
    rows = d.get("quotes") or {}
    parts = []
    for symbol, q in rows.items():
        if not isinstance(q, dict) or not _is_num(q.get("last")):
            continue
        parts.append(f"{symbol} {_num(q['last'])}" + (f" {_pct(q['change_pct'])}" if _is_num(q.get("change_pct")) else ""))
    if not parts:  # the price-only fallback
        parts = [f"{s} {_num(p)}" for s, p in (d.get("prices") or {}).items() if _is_num(p)]
    if not parts:
        return None
    shown = ", ".join(parts[:3]) + (f", +{len(parts) - 3} more" if len(parts) > 3 else "")
    return shown + _at(d.get("fetched_at"))


def option_candidates(d: dict) -> str | None:
    rows = d.get("candidates") or []
    if d.get("state") not in ("ok", "partial") or not rows:
        return None
    r = rows[0]
    label = f"{d.get('symbol')} {_short_date(r['expiry'])} {r['strike']:g}{str(r['type'])[0].upper()}"
    parts = [f"{label} ask {_num(r['ask'])}" if _is_num(r.get("ask")) else label]
    if _is_num(r.get("iv_pct")):
        parts.append(f"IV {r['iv_pct']:g}%")
    if _is_num(r.get("delta")):
        parts.append(f"Δ {r['delta']:g}")
    head = f"{len(rows)} {d.get('side') or 'contracts'}: " if len(rows) > 1 else ""
    return head + ", ".join(parts)


def market_regime(d: dict) -> str | None:
    radar = d.get("radar") or {}
    indices = radar.get("indices") or {} if radar.get("state") == "ok" else {}
    parts = [f"{s} {_pct(indices[s]['day_pct'])}" for s in ("SPY", "QQQ")
             if _is_num((indices.get(s) or {}).get("day_pct"))]
    vix = d.get("vix") or {}
    if vix.get("state") == "ok" and _is_num(vix.get("last")):
        parts.append(f"VIX {vix['last']:g}")
    ten = d.get("us10y") or {}
    if ten.get("state") == "ok" and _is_num(ten.get("yield_pct")):
        parts.append(f"10y {ten['yield_pct']:g}%")
    sector = radar.get("sector") or {}
    if d.get("symbol") and sector.get("state") == "ok" and _is_num(sector.get("symbol_vs_sector_pct")):
        parts.append(f"{d['symbol']} {_pct(sector['symbol_vs_sector_pct'])} vs {sector.get('etf')}")
    if not parts:
        return None
    return "Regime: " + ", ".join(parts) + _at(radar.get("pass_at") or d.get("as_of"))


def radar_today(d: dict) -> str | None:
    if d.get("state") != "ok":
        return None
    events = d.get("events") or []
    total = d.get("events_total")
    total = total if _is_num(total) else len(events)
    if not total:
        return "Radar today: no events"
    times = sorted(t for t in (_when(e.get("first_seen_at")) for e in events if isinstance(e, dict)) if t)
    counts: dict[str, int] = {}
    for e in events:
        for s in e.get("symbols") or []:
            counts[s] = counts.get(s, 0) + 1
    top = max(counts.items(), key=lambda kv: kv[1]) if counts else None
    line = f"Radar today: {total:g} event{'s' if total != 1 else ''}"
    if top and top[1] > 1:
        line += f", {top[1]} on {top[0]}"
    return line + (f", latest {times[-1]:%H:%M}" if times else "")


def breadth(d: dict) -> str | None:
    if d.get("state") == "unavailable" or not _is_num(d.get("advancers")) or not _is_num(d.get("decliners")):
        return None
    line = f"S&P 500 breadth: {d['advancers']:g} up, {d['decliners']:g} down"
    if _is_num(d.get("median_day_pct")):
        line += f", median {_pct(d['median_day_pct'])}"
    if _is_num(d.get("new_52w_highs")) and _is_num(d.get("new_52w_lows")):
        line += f", {d['new_52w_highs']:g} highs / {d['new_52w_lows']:g} lows"
    return line


def positioning(d: dict) -> str | None:
    if d.get("state") not in ("ok", "partial"):
        return None
    parts = []
    vix = (d.get("vol_indexes") or {})
    if _is_num((vix.get("VIX") or {}).get("last")):
        parts.append(f"VIX {vix['VIX']['last']:g}" + (f" ({vix['curve']})" if vix.get("curve") else ""))
    near = (d.get("expiries") or [{}])[0] or {}
    if _is_num(near.get("atm_iv_pct")):
        parts.append(f"{d.get('symbol')} ATM IV {near['atm_iv_pct']:g}%")
    if _is_num(near.get("skew_25d")):
        parts.append(f"skew {near['skew_25d']:g}")
    if _is_num(near.get("put_call_volume")):
        parts.append(f"P/C vol {near['put_call_volume']:g}")
    return ", ".join(parts) or None


_MACRO = (("DGS10", "10y", "%"), ("DGS2", "2y", "%"), ("BAMLH0A0HYM2", "HY spread", "%"), ("DCOILWTICO", "WTI $", ""),
          ("NFCI", "NFCI", ""))


def macro(d: dict) -> str | None:
    rows = {r.get("id"): r for r in d.get("series") or [] if isinstance(r, dict) and _is_num(r.get("value"))}
    parts = [f"{label} {rows[i]['value']:g}{unit}" for i, label, unit in _MACRO if i in rows]
    if not parts:
        return None
    latest = d.get("latest_date")
    return "FRED: " + ", ".join(parts) + (f" ({_short_date(latest)})" if isinstance(latest, str) and latest else "")


def base_rates(d: dict) -> str | None:
    if d.get("state") != "ok" or not _is_num(d.get("episodes")):
        return None
    h = ((d.get("horizons") or {}).get("63d") or {}).get("episodes") or {}
    line = f"{d['episodes']:g} drops of {d['threshold_pct']:g}%+ since {str(d['since'])[:4]}"
    if _is_num(h.get("median_pct")):
        line += f", 63d median {_pct(h['median_pct'])}"
    return line


def trade_review(d: dict) -> str | None:
    if d.get("state") != "ok":
        return None
    t = d.get("trade") or {}
    if not t.get("contract") and not t.get("symbol"):
        return None
    name = t.get("contract") or t.get("symbol")
    if t.get("status") == "open":
        now = d.get("now") or {}
        pnl, pct, word = now.get("open_pnl_usd"), now.get("open_pnl_pct"), "open"
    else:
        pnl, pct, word = t.get("pnl_usd"), t.get("pnl_pct"), "closed"
    line = f"{name} {word}"
    if _is_num(pnl):
        line += f" {_usd(pnl)}" + (f" ({_pct(pct)})" if _is_num(pct) else "")
    sent = (d.get("alerts") or {}).get("sent")
    if _is_num(sent):
        line += f", {sent:g} alert{'s' if sent != 1 else ''}"
    return line


def symbol_profile(d: dict) -> str | None:
    if d.get("state") != "ok":
        return None
    parts = []
    nxt = (d.get("events") or {}).get("next_earnings") or {}
    if isinstance(nxt.get("date"), str):
        parts.append(f"earnings {_short_date(nxt['date'])}" + (f" ({nxt['status']})" if nxt.get("status") else ""))
    short = ((d.get("short") or {}).get("interest") or {}).get("pct_of_shares_outstanding")
    if _is_num(short):
        parts.append(f"short {short:g}% of shares")
    cap = (d.get("valuation") or {}).get("market_cap")
    if _is_num(cap):
        parts.append(f"cap {cap / 1e9:.1f}B")
    return f"{d.get('symbol')}: " + ", ".join(parts) if parts else None


def symbol_events(d: dict) -> str | None:
    nxt = d.get("next_earnings") or {}
    if not isinstance(nxt.get("date"), str):
        return None
    return f"{d.get('symbol')} earnings {_short_date(nxt['date'])}" + (f" ({nxt['status']})" if nxt.get("status") else "")


def web_search(d: dict) -> str | None:
    count = d.get("results")
    return f"Web: {count:g} result{'s' if count != 1 else ''}" if _is_num(count) else None


SUMMARISERS: dict[str, Callable[[dict], str | None]] = {
    "get_group_comparison": group_comparison, "get_peer_moves": peer_moves, "get_symbol_news": symbol_news,
    "get_quotes": quotes, "get_option_candidates": option_candidates, "get_market_regime": market_regime,
    "get_radar_today": radar_today, "get_breadth": breadth, "get_positioning": positioning, "get_macro": macro,
    "get_base_rates": base_rates, "get_trade_review": trade_review, "get_symbol_profile": symbol_profile,
    "get_symbol_events": symbol_events, "web_search": web_search,
}

_UNSAFE = re.compile(r"\s+")


def _plain(text: str) -> str:
    """Control, format (bidirectional marks included) and other non-printing characters out; whitespace to one space."""
    kept = "".join(" " if ch.isspace() else ch for ch in text if ch.isspace() or not unicodedata.category(ch).startswith("C"))
    return _UNSAFE.sub(" ", kept).strip()


def summarize(name: str, result: Any) -> str | None:
    """The fact line for one tool result, at most ``MAX_CHARS`` of plain text, or None. Never raises."""
    try:
        fn = SUMMARISERS.get(name)
        if fn is None or not isinstance(result, dict):
            return None
        line = fn(result)
        if not isinstance(line, str):
            return None
        line = _plain(line)
        if not line:
            return None
        return line if len(line) <= MAX_CHARS else line[:MAX_CHARS - 1].rstrip() + "…"
    except Exception:  # noqa: BLE001 - a fact line is a convenience; a shape it cannot read gets none
        return None
