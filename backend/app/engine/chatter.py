"""Chatter (docs/copilot-lab.md § Chatter): r/wallstreetbets buzz and NYT business headlines for the desk Feed's own
Chatter filter. Both are off until configured; a source that is off makes no network call and costs nothing.

- **r/wallstreetbets** (``CHATTER_WSB_SOURCE=apewisdom``): ApeWisdom's free public API (apewisdom.io, a third party
  that counts ticker mentions on Reddit; no key), one call per pass every ``PASS_SECONDS`` on market days between
  ``READ_FROM`` and ``WSB_UNTIL`` New York: the subreddit's top 100 tickers by mentions in the last 24 hours, each with
  its mentions the 24 hours before, its rank and its rank then. Only the app's known tickers are kept, as counts.
  Buzz is a ticker named at least ``MIN_MENTIONS`` times in the last 24 hours and at least ``BUZZ_MULTIPLE``× the 24
  hours before (or not counted then). Counts older than ``STALE_SECONDS`` show grey with their time, never as zero.
- **NYT** (``CHATTER_NYT_ENABLED=true``): its public business and economy RSS feeds, or its official Top Stories API when
  ``NYT_API_KEY`` is set: headline, the feed's own summary, time and link, every ``PASS_SECONDS`` from ``READ_FROM`` to
  ``NYT_UNTIL``. No article page is ever fetched.

What is read is saved under ``backend/data/chatter`` (no table); the Feed reads those files only, never the network.
Third-party text is data shown as data: it never reaches a model's context and never carries Plan it. Facts and counts.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, time as dtime
from email.utils import parsedate_to_datetime
import json
import logging
import math
import os
from pathlib import Path
import re
import time as _time
from urllib.parse import quote
import xml.etree.ElementTree as ET_XML

import httpx

from app.engine.chart_math import ET, session_windows

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2] / "data" / "chatter"
SUBREDDIT = "wallstreetbets"
WSB_NAME = f"r/{SUBREDDIT}"
NYT_NAME = "NYT"
PASS_SECONDS = 15 * 60
READ_FROM = dtime(6, 0)
WSB_UNTIL = dtime(20, 0)
NYT_UNTIL = dtime(22, 0)
MIN_MENTIONS = 10  # mentions in the last 24 hours before a ticker is buzz at all
BUZZ_MULTIPLE = 2.0  # against the 24 hours before
MAX_BUZZ = 5
STALE_SECONDS = 45 * 60  # counts older than this show grey with their time
KEEP_SECONDS = 4 * 86400  # counts older than this (a long weekend and more) are not shown at all
MAX_NYT = 8
NYT_KEEP_HOURS = 36
TIMEOUT = 15

APEWISDOM_URL = f"https://apewisdom.io/api/v1.0/filter/{SUBREDDIT}/page/1"
NYT_FEEDS = ("https://rss.nytimes.com/services/xml/rss/nyt/Business.xml",
             "https://rss.nytimes.com/services/xml/rss/nyt/Economy.xml")
NYT_API = "https://api.nytimes.com/svc/topstories/v2/business.json"
TICKER = re.compile(r"[A-Z][A-Z.]{0,5}")


def _on(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() == "true"


def wsb_enabled() -> bool:
    return os.environ.get("CHATTER_WSB_SOURCE", "").strip().lower() == "apewisdom"


def nyt_enabled() -> bool:
    return _on("CHATTER_NYT_ENABLED")


def enabled() -> bool:
    return (wsb_enabled() or nyt_enabled()) and os.environ.get("TJ_DOT_TRIAL_ENABLED") != "true"


# --------------------------------------------------------------------------- the saved state

def _path(name: str, root: Path | None = None) -> Path:
    return (root or ROOT) / f"{name}.json"


def load(name: str, root: Path | None = None) -> dict:
    try:
        return json.loads(_path(name, root).read_text())
    except (OSError, ValueError):
        return {}


def save(name: str, state: dict, root: Path | None = None) -> None:
    path = _path(name, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    spare = path.with_suffix(".tmp")
    spare.write_text(json.dumps(state, separators=(",", ":")))
    spare.replace(path)


# --------------------------------------------------------------------------- r/wallstreetbets through ApeWisdom

def _int(value) -> int | None:
    """A count or rank as ApeWisdom sends it (a number, or a numeric string in its own docs); None when absent."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return int(number) if math.isfinite(number) and number >= 0 else None


def parse_apewisdom(body: dict, known: frozenset[str]) -> list[dict]:
    """ApeWisdom's ``results`` as counts: each known ticker's mentions in the last 24 hours and the 24 hours before,
    its rank and its rank then (None where ApeWisdom has none), upvotes. Its company names are not kept."""
    rows = []
    for result in body.get("results") or []:
        if not isinstance(result, dict):
            continue
        symbol = str(result.get("ticker") or "").strip().upper()
        mentions = _int(result.get("mentions"))
        if not TICKER.fullmatch(symbol) or symbol not in known or mentions is None:
            continue
        rows.append({"symbol": symbol, "mentions": mentions, "before": _int(result.get("mentions_24h_ago")),
                     "rank": _int(result.get("rank")), "rank_before": _int(result.get("rank_24h_ago")),
                     "upvotes": _int(result.get("upvotes"))})
    return rows


def read_apewisdom(client: httpx.Client) -> dict:
    """One pass, one call: the subreddit's first page (its top 100 tickers by mentions)."""
    response = client.get(APEWISDOM_URL, headers={"User-Agent": "tradejournal-chatter/1", "Accept": "application/json"})
    response.raise_for_status()
    body = response.json()
    if not isinstance(body, dict) or not isinstance(body.get("results"), list):
        raise ValueError("ApeWisdom reply without results")
    return body


def buzz(rows: list[dict], held: set[str] = frozenset(), blocked: set[str] = frozenset()) -> list[dict]:
    """Tickers named at least ``MIN_MENTIONS`` times in the last 24 hours and at least ``BUZZ_MULTIPLE``× the 24 hours
    before, or not counted then; highest multiple first (one not counted before ranks by its count, as if it had one).
    Tickers he does not follow are left out before the cut. At most ``MAX_BUZZ``."""
    out = []
    for row in rows:
        count, before = row["mentions"], row.get("before")
        if count < MIN_MENTIONS or row["symbol"] in blocked:
            continue
        multiple = round(count / before, 1) if before else None
        if multiple is not None and multiple < BUZZ_MULTIPLE:
            continue
        rank, rank_before = row.get("rank"), row.get("rank_before")
        out.append({"symbol": row["symbol"], "count": count, "before": before,
                    "multiple": multiple, "rank": rank, "rank_before": rank_before,
                    "climbed": rank_before - rank if rank and rank_before else None, "held": row["symbol"] in held})
    out.sort(key=lambda r: (-(r["multiple"] or r["count"]), -r["count"], r["symbol"]))
    return out[:MAX_BUZZ]


# --------------------------------------------------------------------------- NYT

def parse_rss(body: str) -> list[dict]:
    """An RSS document's items: headline, the feed's own summary, time (epoch) and link. A document declaring a DTD or
    entities is refused unread."""
    if "<!DOCTYPE" in body or "<!ENTITY" in body:
        raise ValueError("RSS with a DTD is not read")
    rows = []
    for item in ET_XML.fromstring(body).iter("item"):
        title, link = (item.findtext("title") or "").strip(), (item.findtext("link") or "").strip()
        if not title or not link.startswith("https://"):
            continue
        try:
            at = parsedate_to_datetime(item.findtext("pubDate") or "").timestamp()
        except (TypeError, ValueError):
            continue
        rows.append({"title": title, "summary": (item.findtext("description") or "").strip(), "at": at, "url": link})
    return rows


def parse_api(body: dict) -> list[dict]:
    """The Top Stories API's results in the RSS reader's shape."""
    rows = []
    for result in body.get("results") or []:
        title, link = str(result.get("title") or "").strip(), str(result.get("url") or "").strip()
        if not title or not link.startswith("https://"):
            continue
        try:
            at = datetime.fromisoformat(str(result.get("published_date"))).timestamp()
        except ValueError:
            continue
        rows.append({"title": title, "summary": str(result.get("abstract") or "").strip(), "at": at, "url": link})
    return rows


def read_nyt(client: httpx.Client) -> list[dict]:
    """The newest headlines, one per link: the official API with ``NYT_API_KEY``, else the public RSS feeds."""
    key = os.environ.get("NYT_API_KEY", "").strip()
    rows = []
    if key:
        response = client.get(NYT_API, params={"api-key": key})
        response.raise_for_status()
        rows = parse_api(response.json())
    else:
        for url in NYT_FEEDS:
            response = client.get(url, headers={"User-Agent": "tradejournal-chatter/1"})
            response.raise_for_status()
            rows += parse_rss(response.text)
    unique = {}
    for row in sorted(rows, key=lambda r: r["at"], reverse=True):
        unique.setdefault(row["url"], row)
    return list(unique.values())[:40]


# --------------------------------------------------------------------------- the background reader

def _known(engine) -> frozenset[str]:
    from sqlmodel import Session
    from app.engine import spoken_tickers
    from app.engine.jo_morning_market import BACKDROP
    with Session(engine) as db:
        return spoken_tickers.known_symbols(spoken_tickers.traded(db)) | frozenset(BACKDROP)


class Chatter:
    """Reads each enabled source when it is due; ``run_once`` is called every minute from the API's lifespan."""

    def __init__(self, engine, calendar, *, clock=_time.time, root: Path | None = None, client_factory=None):
        self.engine, self.calendar, self.clock, self.root = engine, calendar, clock, root
        self.client_factory = client_factory or (lambda: httpx.Client(timeout=TIMEOUT))
        self._failed: dict[str, float] = {}  # a failure whose state could not be saved

    def _market_day(self, day: date) -> bool:
        hours = self.calendar.hours(day) if self.calendar is not None else None
        return day.weekday() < 5 and any(w[0] == "regular" for w in session_windows(day, hours))

    def _due(self, name: str, until: dtime, now: float, market_only: bool) -> bool:
        local = datetime.fromtimestamp(now, ET)
        if not READ_FROM <= local.time() < until or (market_only and not self._market_day(local.date())):
            return False
        state = load(name, self.root)
        last = max(state.get("ok_at") or 0, state.get("error_at") or 0, self._failed.get(name, 0))
        return now - last >= PASS_SECONDS

    def run_once(self) -> None:
        now = self.clock()
        if wsb_enabled() and self._due("wsb", WSB_UNTIL, now, True):
            self._read("wsb", lambda client: {"rows": parse_apewisdom(read_apewisdom(client), _known(self.engine))}, now)
        if nyt_enabled() and self._due("nyt", NYT_UNTIL, now, False):
            self._read("nyt", lambda client: {**load("nyt", self.root), "items": read_nyt(client)}, now)

    def _read(self, name: str, read, now: float) -> None:
        try:
            with self.client_factory() as client:
                state = read(client)
            save(name, {**state, "ok_at": now, "error": None}, self.root)
        except Exception as error:  # one source failing leaves the other and the app alone
            # Only the error's type is logged or saved: an httpx error's message holds the request URL, which carries
            # NYT_API_KEY on the API path.
            kind = type(error).__name__
            log.warning("Chatter %s read unavailable (%s)", name, kind)
            try:
                save(name, {**load(name, self.root), "error_at": now, "error": kind}, self.root)
            except OSError:
                log.warning("Chatter %s state could not be saved", name)
                self._failed[name] = now  # still wait PASS_SECONDS before the next read

    async def loop(self) -> None:
        while True:
            try:
                await asyncio.to_thread(self.run_once)
            except Exception as error:  # the type only: a traceback could carry a request URL with a key in it
                log.warning("Chatter pass failed (%s)", type(error).__name__)
            await asyncio.sleep(60)


def chatter_from_env(engine) -> Chatter | None:
    if not enabled():
        return None
    from app.engine.chart_calendar import chart_calendar
    return Chatter(engine, chart_calendar)


# --------------------------------------------------------------------------- the Feed's view

def _state(name: str, on: bool, root: Path | None) -> tuple[str, dict]:
    if not on:
        return "not set up", {}
    state = load(name, root)
    if (state.get("error_at") or 0) > (state.get("ok_at") or 0):
        return "unavailable", state
    return "on", state


def _times(n: float, word: str) -> str:
    said = f"{int(n):,}" if float(n).is_integer() else f"{n:g}"
    return f"{said} {word}{'' if n == 1 else 's'}"


def _clock(at: float, now: float) -> str:
    moment, today = datetime.fromtimestamp(at, ET), datetime.fromtimestamp(now, ET).date()
    return moment.strftime("%H:%M") if moment.date() == today else moment.strftime("%a %H:%M")


def view(held: set[str], blocked: set[str], now: float, root: Path | None = None) -> dict:
    """What the Feed's Chatter filter shows: each source's state, the buzz chips and the rows (buzz, headlines). Saved
    files only: no network, no model. Counts older than ``STALE_SECONDS`` (or kept after a failed read) are marked
    stale with their time; older than ``KEEP_SECONDS`` they are not shown."""
    from app.engine.desk_feed import _item, _trim
    wsb_state, wsb = _state("wsb", wsb_enabled(), root)
    nyt_state, nyt = _state("nyt", nyt_enabled(), root)
    named = re.compile(r"\b(?:" + "|".join(re.escape(s) for s in sorted(blocked)) + r")\b") if blocked else None

    def hidden(symbols, *texts) -> bool:
        return bool(set(symbols) & blocked) or bool(named and any(named.search(t or "") for t in texts))

    chips, items = [], []
    as_of = wsb.get("ok_at") or 0
    if wsb_state != "not set up" and as_of and now - as_of < KEEP_SECONDS:
        stale = wsb_state == "unavailable" or now - as_of >= STALE_SECONDS
        if stale and wsb_state == "on":
            wsb_state = "stale"
        for row in buzz(wsb.get("rows") or [], held, blocked):
            row.update(as_of=int(as_of), stale=stale)
            chips.append(row)
            symbol, count = row["symbol"], row["count"]
            said = _times(count, "mention")
            if row["multiple"] is None:
                text = f"{symbol}: {said} in the last 24h, none counted the 24h before"
            else:
                text = f"{symbol}: {said} in the last 24h, {row['multiple']:g}× the 24h before ({row['before']:,})"
            if row["rank"] and row["rank_before"]:
                rank = f"Rank {row['rank']}, was {row['rank_before']}."
            elif row["rank"]:
                rank = f"Rank {row['rank']}, not ranked the day before."
            else:
                rank = ""
            detail = " ".join(p for p in (f"Not updated since {_clock(as_of, now)}." if stale else "", rank) if p) or None
            search = f"https://www.reddit.com/r/{SUBREDDIT}/search/?q={quote(symbol)}&restrict_sr=1&sort=new"
            items.append(_item(WSB_NAME, f"buzz:{symbol}", int(as_of), text, symbol=symbol, detail=detail, href=None,
                               publisher=WSB_NAME, url=search, buzz=True, stale=stale))
    for row in (nyt.get("items") or []):
        if row["at"] < now - NYT_KEEP_HOURS * 3600 or hidden([], row["title"], row["summary"]):
            continue
        items.append(_item(NYT_NAME, f"nyt:{row['url']}", int(row["at"]), _trim(row["title"], 200),
                           detail=_trim(row["summary"], 220) or None, href=None, publisher=NYT_NAME, url=row["url"],
                           buzz=False))
        if sum(1 for i in items if i["source"] == NYT_NAME) >= MAX_NYT:
            break
    items = [i for i in items if i["buzz"]] + sorted((i for i in items if not i["buzz"]), key=lambda i: -i["at"])
    for item in items:
        item.update(plan=None, mine=False, upcoming=False, chatter=True)
        item.pop("buzz")
    return {"sources": {WSB_NAME: wsb_state, NYT_NAME: nyt_state}, "buzz": chips, "items": items}


def off(reason: str = "unavailable") -> dict:
    """The view when it could not be built: each source that is set up reads ``reason``."""
    return {"sources": {WSB_NAME: reason if wsb_enabled() else "not set up",
                        NYT_NAME: reason if nyt_enabled() else "not set up"},
            "buzz": [], "items": []}
