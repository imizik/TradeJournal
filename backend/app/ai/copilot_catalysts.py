"""What hit a symbol since the last close, lined up with the tape (the copilot's ``get_catalysts``).

Three free sources, newest first, each item with when it landed and how the stock traded in the 15 minutes after:

- **SEC filings** from EDGAR's per-company Atom feed (``browse-edgar ... output=atom``), which stamps each filing with
  its acceptance time and a UTC offset. Only the forms that move a short-dated trade are kept: current reports (8-K,
  6-K), offerings (S-1, S-3, F-1, F-3, 424B*, FWP), insider sales and notices (4, 144), ownership stakes (13D/13G) and
  periodic reports (10-Q, 10-K, 20-F, 40-F). The ``SEC_USER_AGENT`` contact the Financials tab uses goes with it.
- **Trading halts** from Nasdaq Trader's halts RSS (all US listings, today's halts, LULD pauses included). Read at most
  once a minute, as Nasdaq asks.
- **Headlines** from the Alpaca news feed (Benzinga's wire; machine-written summaries are dropped in ``news``).

Minute bars (the chart feed's Tradier time and sales, extended hours) give each item its reaction: the move over the
next 15 minutes and the volume of the next five minutes against the hour before. Sharp minutes no item explains are
listed as unexplained moves, so "no catalyst: the move follows its peers or the market" can be said from evidence.

Every text field here is third-party data (filing titles, halt reasons, headlines): shown as data, never followed. A
source that fails reads as unavailable and never hides the others. Read-only: no write, no model call.
"""
from __future__ import annotations

import html
import logging
import re
import threading
import time
from datetime import date, datetime, timedelta
from statistics import median
from typing import Callable
from xml.etree import ElementTree

import httpx

from app.engine.chart_math import ET

log = logging.getLogger(__name__)

SEC_FEED = ("https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=&dateb=&owner=include"
            "&count=40&output=atom")
HALTS_URL = "https://www.nasdaqtrader.com/rss.aspx?feed=tradehalts"
SEC_TTL = 60.0
HALTS_TTL = 60.0  # Nasdaq Trader asks for at most one read a minute
TIMEOUT = 8.0
MAX_ITEMS = 15
MAX_UNEXPLAINED = 3
REACTION_MINUTES = 15
BURST_MINUTES = 5
BASELINE_MINUTES = 60
MIN_BASELINE = 20  # bars before an item needed for a volume ratio
SPIKE_VOLUME_X = 5.0
SPIKE_MOVE_PCT = 1.0
EXPLAINED_WITHIN = 10 * 60  # a sharp minute this soon after an item is that item's reaction
FALLBACK_SINCE = 18 * 3600

# Form families, matched on the base form (an amendment's "/A" is dropped first).
FORMS = {
    "current_report": ("8-K", "6-K"),
    "offering": ("S-1", "S-3", "F-1", "F-3", "FWP", "424B1", "424B2", "424B3", "424B4", "424B5", "424B7", "424B8"),
    "insider": ("4", "144"),
    "ownership": ("SC 13D", "SC 13G", "SCHEDULE 13D", "SCHEDULE 13G"),
    "periodic": ("10-Q", "10-K", "20-F", "40-F"),
}
_KIND = {form: kind for kind, forms in FORMS.items() for form in forms}

FIXTURE_NOTE = "SIMULATED demo timeline, not real filings or headlines."
REPLAY_REASON = "Catalysts are read live only: a replay would mix in filings and headlines published after its moment."


def form_kind(form: str | None) -> str | None:
    base = (form or "").strip().upper().removesuffix("/A").strip()
    return _KIND.get(base)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _xml(text: str) -> ElementTree.Element:
    if "<!DOCTYPE" in text[:2000].upper() or "<!ENTITY" in text.upper():
        raise ValueError("refused a feed with a DOCTYPE or entity declarations")
    return ElementTree.fromstring(text)


def _child(node: ElementTree.Element, name: str) -> ElementTree.Element | None:
    return next((c for c in node if _local(c.tag) == name), None)


def _text(node: ElementTree.Element | None) -> str:
    return (node.text or "").strip() if node is not None else ""


def _plain(value: str, limit: int) -> str:
    value = re.sub(r"<[^>]+>", " ", html.unescape(value or ""))
    return re.sub(r"\s+", " ", value).strip()[:limit]


def parse_filings(atom: str) -> list[dict]:
    """The kept filings in an EDGAR company Atom feed: ``{at (epoch), form, kind, title, detail, url}``."""
    out = []
    for entry in (e for e in _xml(atom) if _local(e.tag) == "entry"):
        category = _child(entry, "category")
        form = (category.get("term") if category is not None else "") or ""
        kind = form_kind(form)
        if kind is None:
            continue
        try:
            at = datetime.fromisoformat(_text(_child(entry, "updated"))).timestamp()
        except ValueError:
            continue
        link = _child(entry, "link")
        detail = _plain(_text(_child(entry, "summary")), 240)
        items = re.findall(r"Item \d+\.\d+", detail)
        out.append({"at": at, "form": form.strip().upper(), "kind": kind,
                    "title": _plain(_text(_child(entry, "title")), 160),
                    "detail": ", ".join(dict.fromkeys(items)) if items else None,
                    "url": link.get("href") if link is not None else None})
    return out


def parse_halts(rss: str, symbol: str) -> list[dict]:
    """``symbol``'s halts in Nasdaq Trader's halts RSS: ``{at, resumed_at, reason}`` (times in New York)."""
    def moment(day: str, clock: str) -> float | None:
        try:
            return datetime.strptime(f"{day} {clock}", "%m/%d/%Y %H:%M:%S").replace(tzinfo=ET).timestamp()
        except ValueError:
            return None

    out = []
    for item in _xml(rss).iter():
        if _local(item.tag) != "item":
            continue
        fields = {_local(c.tag): (c.text or "").strip() for c in item}
        if fields.get("IssueSymbol", "").upper() != symbol.upper():
            continue
        at = moment(fields.get("HaltDate", ""), fields.get("HaltTime", ""))
        if at is None:
            continue
        resumed = fields.get("ResumptionTradeTime")
        out.append({"at": at, "reason": fields.get("ReasonCode") or None,
                    "resumed_at": moment(fields.get("ResumptionDate") or fields.get("HaltDate", ""), resumed) if resumed else None})
    return out


def _index_at(bars: list[dict], at: float) -> int:
    """The first bar starting at or after ``at`` (len(bars) when none)."""
    return next((i for i, b in enumerate(bars) if b["time"] >= at - 59), len(bars))


def reaction(bars: list[dict], at: float) -> dict | None:
    """The move from the last price before ``at`` to the close 15 minutes on, and the next five minutes' volume against
    the hour before (None without enough bars on each side). Bars are sorted minute bars with time, close, volume."""
    i = _index_at(bars, at)
    if i == 0 or i >= len(bars):
        return None
    before = bars[i - 1]["close"]
    end = next((b for b in bars[i:] if b["time"] >= at + REACTION_MINUTES * 60 - 59), bars[-1])
    out = {"move_15m_pct": round((end["close"] / before - 1) * 100, 2) if before else None, "volume_x": None}
    baseline = [b["volume"] for b in bars[max(0, i - BASELINE_MINUTES):i]]
    if len(baseline) >= MIN_BASELINE and (typical := median(baseline)) > 0:
        burst = [b["volume"] for b in bars[i:i + BURST_MINUTES]]
        out["volume_x"] = round(sum(burst) / (len(burst) * typical), 1)
    return out


def unexplained(bars: list[dict], explained_at: list[float]) -> list[dict]:
    """Sharp minutes (volume 5x the hour before and a 1%+ move over five minutes) no item explains, largest first."""
    found = []
    for i in range(MIN_BASELINE, len(bars) - 1):
        typical = median(b["volume"] for b in bars[max(0, i - BASELINE_MINUTES):i])
        if typical <= 0 or bars[i]["volume"] < SPIKE_VOLUME_X * typical:
            continue
        start, end = bars[i - 1]["close"], bars[min(i + BURST_MINUTES - 1, len(bars) - 1)]["close"]
        move = (end / start - 1) * 100 if start else 0.0
        if abs(move) < SPIKE_MOVE_PCT:
            continue
        t = bars[i]["time"]
        if any(-60 < t - at <= EXPLAINED_WITHIN for at in explained_at):  # the bar the item landed in counts
            continue
        if found and t - found[-1]["at"] < BURST_MINUTES * 60:  # one burst, one row
            continue
        found.append({"at": t, "move_5m_pct": round(move, 2), "volume_x": round(bars[i]["volume"] / typical, 1)})
    return sorted(found, key=lambda r: -abs(r["move_5m_pct"]))[:MAX_UNEXPLAINED]


def _clock(at: float) -> str:
    return datetime.fromtimestamp(at, ET).strftime("%m-%d %H:%M ET")


def timeline(symbol: str, since: float, now: float, *, filings: dict, halts: dict, headlines: dict,
             bars: list[dict] | None) -> dict:
    """One symbol's catalysts since ``since``. Each source is ``{"state": "ok", "items": [...]}`` or
    ``{"state": "unavailable", "reason": ...}``; headlines are ``{at, headline, source, url}``."""
    bars = sorted((b for b in bars or [] if since - BASELINE_MINUTES * 60 <= b["time"] <= now), key=lambda b: b["time"])
    items: list[dict] = []
    for f in filings.get("items") or []:
        items.append({"at": f["at"], "type": "filing", "kind": f["kind"], "form": f["form"], "title": f["title"],
                      **({"detail": f["detail"]} if f.get("detail") else {}), "url": f["url"], "source": "SEC EDGAR"})
    for h in halts.get("items") or []:
        items.append({"at": h["at"], "type": "halt", "reason": h["reason"],
                      "resumed": _clock(h["resumed_at"]) if h.get("resumed_at") else None, "source": "Nasdaq Trader"})
    for n in headlines.get("items") or []:
        items.append({"at": n["at"], "type": "headline", "title": n["headline"], "url": n.get("url"),
                      "source": n.get("source") or "Alpaca news"})
    items = sorted((i for i in items if since <= i["at"] <= now), key=lambda i: -i["at"])[:MAX_ITEMS]
    for item in items:
        item["reaction"] = reaction(bars, item["at"]) if bars else None
    sharp = unexplained([b for b in bars if b["time"] >= since], [i["at"] for i in items]) if bars else []
    sources = {name: src.get("state", "unavailable") if src.get("state") == "ok" else f"unavailable: {src.get('reason') or 'no read'}"
               for name, src in (("sec_filings", filings), ("halts", halts), ("headlines", headlines))}
    primary = [i for i in items if i["type"] in ("filing", "halt")]
    out = {"symbol": symbol, "state": "ok", "since": _clock(since), "as_of": _clock(now), "sources": sources,
           "items": [{**i, "at": _clock(i["at"])} for i in items],
           "unexplained_moves": [{**s, "at": _clock(s["at"])} for s in sharp],
           "minute_bars": "ok" if bars else "unavailable"}
    if not items and all(s == "ok" for s in sources.values()):
        out["note"] = "No filing, halt or headline since the close: the move is not news-driven by these sources; check peers and the market."
    elif not primary and sources["sec_filings"] == "ok":
        out["note"] = "No SEC filing or halt since the close; headlines only."
    return out


# --------------------------------------------------------------------------- live reads

_lock = threading.Lock()
_cache: dict[str, tuple[float, dict]] = {}


def _cached(key: str, ttl: float, read: Callable[[], dict]) -> dict:
    now = time.monotonic()
    with _lock:
        hit = _cache.get(key)
    if hit and now - hit[0] < ttl:
        return hit[1]
    value = read()
    with _lock:
        _cache[key] = (now, value)
    return value


def _get_text(url: str, headers: dict) -> str:
    response = httpx.get(url, headers=headers, timeout=TIMEOUT, follow_redirects=True)
    if response.status_code != 200:
        raise RuntimeError(f"answered {response.status_code}")
    return response.text


def live_filings(symbol: str) -> dict:
    from app.engine import symbol_info_financials_feed as sec

    def read() -> dict:
        try:
            cik = sec.symbol_financials._cik(symbol)
            if cik is None:
                return {"state": "unavailable", "reason": "no SEC filer for this ticker (an ETF or fund)"}
            sec._pacer.wait()
            text = _get_text(SEC_FEED.format(cik=f"{cik:010d}"), {"User-Agent": sec.user_agent(), "Accept": "application/atom+xml"})
            return {"state": "ok", "items": parse_filings(text)}
        except Exception as exc:  # noqa: BLE001 - one failed source never hides the others
            log.info("catalysts: SEC filings unavailable for %s: %s", symbol, type(exc).__name__)
            return {"state": "unavailable", "reason": "SEC EDGAR could not be read"}
    return _cached(f"sec:{symbol}", SEC_TTL, read)


def live_halts(symbol: str) -> dict:
    def read() -> dict:
        try:
            return {"state": "ok", "text": _get_text(HALTS_URL, {"User-Agent": "TradeJournal personal-research app"})}
        except Exception as exc:  # noqa: BLE001
            log.info("catalysts: halts unavailable: %s", type(exc).__name__)
            return {"state": "unavailable", "reason": "Nasdaq Trader halts could not be read"}
    feed = _cached("halts", HALTS_TTL, read)
    if feed["state"] != "ok":
        return feed
    try:
        return {"state": "ok", "items": parse_halts(feed["text"], symbol)}
    except (ValueError, ElementTree.ParseError):
        return {"state": "unavailable", "reason": "Nasdaq Trader halts were unreadable"}


def live_headlines(symbol: str, since: float) -> dict:
    from app.engine import news
    try:
        found = news.fetch_news(symbols=[symbol], start=datetime.fromtimestamp(since, ET), limit=20, fast=True, strict=True)
    except Exception as exc:  # noqa: BLE001
        log.info("catalysts: headlines unavailable for %s: %s", symbol, type(exc).__name__)
        return {"state": "unavailable", "reason": "Alpaca news could not be read"}
    items = []
    for a in found:
        try:
            at = datetime.fromisoformat(str(a.get("created_at")).replace("Z", "+00:00")).timestamp()
        except ValueError:
            continue
        items.append({"at": at, "headline": _plain(a.get("headline") or "", 200), "source": a.get("source"), "url": a.get("url")})
    return {"state": "ok", "items": items}


def last_close(now: float, hours: Callable[[date], dict | None]) -> float:
    """The most recent regular-session close before today's session, from the market calendar; 18 hours back when the
    calendar cannot say."""
    day = datetime.fromtimestamp(now, ET).date()
    for back in range(1, 10):
        d = day - timedelta(days=back)
        h = hours(d)
        if h is None:
            break
        if h.get("status") == "open" and h.get("close") is not None:
            return datetime.combine(d, datetime.min.time(), ET).timestamp() + h["close"] * 60
    return now - FALLBACK_SINCE


def _bars(symbol: str, since: float, now: float) -> list[dict] | None:
    from app.engine.chart_feed import chart_feed
    bars: list[dict] = []
    try:
        first = datetime.fromtimestamp(since, ET).date()
        today = datetime.fromtimestamp(now, ET).date()
        if first < today:  # the last session's after-hours, the same read the chart makes for that day
            from app.engine.chart_feed import _rows
            from app.engine.chart_math import normalize_bars
            data, _, _ = chart_feed.read("/v1/markets/timesales", chart_feed._minutes_params(symbol, first), 300, low=True)
            bars += normalize_bars(_rows(data, "series", "data"))
        bars += chart_feed.today_minutes(symbol, now)
    except Exception as exc:  # noqa: BLE001 - items stand without their reactions
        log.info("catalysts: minute bars unavailable for %s: %s", symbol, type(exc).__name__)
        return bars or None
    return bars


def live_catalysts(symbol: str, now: datetime) -> dict:
    from app.engine.chart_calendar import chart_calendar
    from concurrent.futures import ThreadPoolExecutor
    at = now.timestamp()
    since = last_close(at, chart_calendar.hours)
    with ThreadPoolExecutor(max_workers=4) as pool:  # four independent reads side by side, inside the tool's timeout
        filings, halts = pool.submit(live_filings, symbol), pool.submit(live_halts, symbol)
        headlines, bars = pool.submit(live_headlines, symbol, since), pool.submit(_bars, symbol, since, at)
        return timeline(symbol, since, at, filings=filings.result(), halts=halts.result(),
                        headlines=headlines.result(), bars=bars.result())


def fixture_catalysts(symbol: str, now: datetime) -> dict:
    at = now.timestamp()
    since = at - 16 * 3600
    bars = [{"time": since + 60 * i, "close": 100 + (0.5 if i >= 700 else 0), "volume": 900 if i == 700 else 100}
            for i in range(0, int((at - since) // 60))]
    out = timeline(symbol, since, at,
                   filings={"state": "ok", "items": [{"at": since + 700 * 60, "form": "8-K", "kind": "current_report",
                                                      "title": "8-K - Current report", "detail": "Item 1.01",
                                                      "url": "https://www.sec.gov/"}]},
                   halts={"state": "ok", "items": []},
                   headlines={"state": "ok", "items": [{"at": since + 705 * 60, "headline": f"{symbol} announces supply agreement",
                                                        "source": "benzinga", "url": None}]},
                   bars=bars)
    return {**out, "simulated": True, "note": FIXTURE_NOTE}
