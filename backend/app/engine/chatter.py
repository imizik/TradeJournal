"""Chatter (docs/copilot-lab.md § Chatter): r/wallstreetbets buzz and NYT business headlines for the desk Feed's own
Chatter filter. Both are off until configured; a source that is off makes no network call and costs nothing.

- **r/wallstreetbets** (``CHATTER_REDDIT_ENABLED=true`` with ``REDDIT_CLIENT_ID`` and ``REDDIT_CLIENT_SECRET``): Reddit's
  official API with the app's own credentials (application-only OAuth, the user-agent Reddit asks for), every
  ``PASS_SECONDS`` on market days between ``READ_FROM`` and ``REDDIT_UNTIL`` New York. Each pass reads the subreddit's
  hot, rising and new listings (three calls, far inside Reddit's limit; the remaining-calls header is respected) and
  keeps, per post with a known ticker in its title, the post's time and those tickers, for ``HISTORY_DAYS``. Mentions
  are counted by post time, each post once: "the last hour" against the same hour on up to ``USUAL_DAYS`` recent
  market days the reader covered. Fewer than ``MIN_USUAL_DAYS`` covered days: the raw count, "no usual yet".
- **NYT** (``CHATTER_NYT_ENABLED=true``): its public business and economy RSS feeds, or its official Top Stories API when
  ``NYT_API_KEY`` is set: headline, the feed's own summary, time and link, every ``PASS_SECONDS`` from ``READ_FROM`` to
  ``NYT_UNTIL``. No article page is ever fetched.

What is read is saved under ``backend/data/chatter`` (no table); the Feed reads those files only, never the network.
Third-party text is data shown as data: it never reaches a model's context and never carries Plan it. Facts and counts.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, time as dtime, timedelta
from email.utils import parsedate_to_datetime
import json
import logging
import os
from pathlib import Path
import re
import threading
import time as _time
from urllib.parse import quote
import xml.etree.ElementTree as ET_XML

import httpx

from app.engine.chart_math import ET, session_windows

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2] / "data" / "chatter"
SUBREDDIT = "wallstreetbets"
REDDIT_NAME = f"r/{SUBREDDIT}"
NYT_NAME = "NYT"
PASS_SECONDS = 15 * 60
READ_FROM = dtime(6, 0)
REDDIT_UNTIL = dtime(20, 0)
NYT_UNTIL = dtime(22, 0)
HISTORY_DAYS = 30
USUAL_DAYS = 5
MIN_USUAL_DAYS = 3
LOOKBACK_DAYS = 14  # calendar days searched for USUAL_DAYS covered market days
SPIKE_MULTIPLE = 3.0
SPIKE_MIN = 3  # mentions in the hour before a ticker is buzz at all
MAX_BUZZ = 5
MAX_POSTS = 5
MAX_NYT = 8
NYT_KEEP_HOURS = 36
RATE_FLOOR = 5  # calls left in Reddit's window below which a pass waits for the reset
TIMEOUT = 15

REDDIT_TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
REDDIT_API = "https://oauth.reddit.com"
NYT_FEEDS = ("https://rss.nytimes.com/services/xml/rss/nyt/Business.xml",
             "https://rss.nytimes.com/services/xml/rss/nyt/Economy.xml")
NYT_API = "https://api.nytimes.com/svc/topstories/v2/business.json"

# All-caps words that are not tickers in a post title, even where a known symbol shares the letters. One of them still
# counts written as a cashtag ("$ON", "$ALL").
STOP = frozenset({
    "A", "I", "AI", "AM", "PM", "ET", "CPI", "PPI", "PCE", "GDP", "PMI", "NFP", "FOMC", "EPS", "IV", "DTE", "ATM", "OTM",
    "ITM", "VWAP", "ORB", "ETF", "USD", "US", "MA", "EMA", "SMA", "RSI", "ATH", "YTD", "HOD", "LOD", "IPO", "CEO", "OK",
    "PT",  # the morning brief scorecard's list (brief_scorecard.STOP), then the subreddit's own words
    "YOLO", "DD", "WSB", "FD", "FDS", "IMO", "LOL", "LMAO", "TLDR", "WTF", "OMG", "RIP", "FOMO", "HODL", "APE", "APES",
    "MOON", "GAIN", "GAINS", "LOSS", "LOSSES", "BUY", "SELL", "HOLD", "CALL", "CALLS", "PUT", "PUTS", "ALL", "NOW", "ONE",
    "IT", "BE", "SO", "GO", "ON", "OR", "ARE", "CAN", "FOR", "NEW", "BIG", "HAS", "OUT", "RUN", "TWO", "WAY", "REAL",
    "LOVE", "GOOD", "BEST", "FAST", "FUN", "HOT", "LOW", "HIGH", "OPEN", "EDIT", "USA", "SEC", "FED", "IRS", "NYSE",
    "OTC", "AH", "EOD", "DOW", "CFO", "YOY", "QOQ", "AMA", "BRO", "MAN", "NEXT", "PLAY", "LIFE", "WORK", "CASH", "SAFE",
    "ANY", "KEY", "VERY", "WELL", "EVER", "MOST", "PEAK", "TRUE", "NICE", "DUDE", "TECH", "UP", "AT", "BY", "DO",
    "AN", "AS", "HE", "ME", "MY", "NO", "OF", "TO", "WE", "IS", "IN", "IF", "OUR", "THE", "AND", "BUT", "NOT", "YOU",
    "WHO", "WHY", "HOW", "WHAT", "JUST", "LIKE", "THIS", "THAT", "WITH", "FROM", "INTO", "OVER", "BACK", "TIME", "WEEK",
    "YEAR", "DAY", "DAYS", "MOVE", "PUMP", "DUMP", "BEAR", "BULL", "RED", "GREEN", "UK", "EU", "CNBC", "LLC", "INC",
})
TOKEN = re.compile(r"(?<![\w&.$])(\$?)([A-Z]{1,6})(?![\w&]|\.[A-Za-z])")
CASHTAG = re.compile(r"(?<![\w$])\$([a-z][a-z]{0,5})\b")

_lock = threading.Lock()
_token: dict = {}  # Reddit's application-only token and when it lapses
_rate: dict = {}  # Reddit's remaining calls and when its window resets


def _on(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() == "true"


def reddit_enabled() -> bool:
    return (_on("CHATTER_REDDIT_ENABLED") and bool(os.environ.get("REDDIT_CLIENT_ID", "").strip())
            and bool(os.environ.get("REDDIT_CLIENT_SECRET", "").strip()))


def nyt_enabled() -> bool:
    return _on("CHATTER_NYT_ENABLED")


def enabled() -> bool:
    return (reddit_enabled() or nyt_enabled()) and os.environ.get("TJ_DOT_TRIAL_ENABLED") != "true"


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


# --------------------------------------------------------------------------- mentions

def mentions(title: str, known: frozenset[str]) -> list[str]:
    """The distinct known tickers a post title names, in first-seen order: a whole uppercase token not on ``STOP``, or
    any cashtag ("$ON", "$nvda")."""
    seen: dict[str, None] = {}
    text = title or ""
    for match in TOKEN.finditer(text):
        dollar, symbol = match.groups()
        if symbol in known and (dollar or symbol not in STOP):
            seen.setdefault(symbol, None)
    for match in CASHTAG.finditer(text):
        symbol = match.group(1).upper()
        if symbol in known:
            seen.setdefault(symbol, None)
    return list(seen)


def record_pass(state: dict, listings: dict[str, list[dict]], known: frozenset[str], now: float) -> dict:
    """``state`` with one pass's listings folded in: each post with a known ticker kept once by id (its time and
    tickers), the pass's time, and the rising posts to show; anything older than ``HISTORY_DAYS`` dropped."""
    keep_from = now - HISTORY_DAYS * 86400
    seen = {k: v for k, v in (state.get("mentions") or {}).items() if v[0] >= keep_from}
    for posts in listings.values():
        for post in posts:
            if post.get("stickied") or not post.get("id"):
                continue
            created = float(post.get("created_utc") or 0)
            if created < keep_from or post["id"] in seen:
                continue
            if found := mentions(post.get("title", ""), known):
                seen[post["id"]] = [created, found]
    passes = [p for p in state.get("passes") or [] if p >= keep_from] + [now]
    rising = []
    for post in listings.get("rising", []):
        if post.get("stickied") or post.get("over_18") or not post.get("permalink"):
            continue
        rising.append({"id": post["id"], "title": " ".join(str(post.get("title", "")).split())[:300],
                       "score": int(post.get("score") or 0), "comments": int(post.get("num_comments") or 0),
                       "created": float(post.get("created_utc") or now),
                       "url": "https://www.reddit.com" + str(post["permalink"]),
                       "symbols": mentions(post.get("title", ""), known)})
        if len(rising) >= MAX_POSTS:
            break
    return {**state, "mentions": seen, "passes": passes, "posts": rising}


def _by_symbol(state: dict) -> dict[str, list[float]]:
    out: dict[str, list[float]] = {}
    for created, symbols in (state.get("mentions") or {}).values():
        for symbol in symbols:
            out.setdefault(symbol, []).append(created)
    return out


def _count(times: list[float], start: float, end: float) -> int:
    return sum(1 for t in times if start <= t < end)


def _usual_windows(state: dict, now: float) -> list[tuple[float, float]]:
    """The same New York hour on up to ``USUAL_DAYS`` earlier weekdays the reader covered (a pass within the hour or
    the hour after it, since a later pass still sees an hour's new posts)."""
    passes = state.get("passes") or []
    moment = datetime.fromtimestamp(now, ET)
    windows = []
    for back in range(1, LOOKBACK_DAYS + 1):
        day = moment.date() - timedelta(days=back)
        if day.weekday() >= 5:
            continue
        end = datetime.combine(day, moment.time(), ET).timestamp()
        if any(end - 3600 <= p < end + 3600 for p in passes):
            windows.append((end - 3600, end))
        if len(windows) >= USUAL_DAYS:
            break
    return windows


def buzz(state: dict, now: float, held: set[str] = frozenset()) -> list[dict]:
    """Tickers named in at least ``SPIKE_MIN`` posts in the last hour. With enough history only those at
    ``SPIKE_MULTIPLE``× their usual or more (or usually unnamed at this hour), highest multiple first; without it the raw counts
    ("no usual yet"), most named first. At most ``MAX_BUZZ``."""
    by_symbol = _by_symbol(state)
    windows = _usual_windows(state, now)
    history = len(windows) >= MIN_USUAL_DAYS
    rows = []
    for symbol, times in by_symbol.items():
        count = _count(times, now - 3600, now)
        if count < SPIKE_MIN:
            continue
        usual = sum(_count(times, a, b) for a, b in windows) / len(windows) if history else None
        multiple = count / usual if usual else None
        if history and usual and multiple < SPIKE_MULTIPLE:
            continue
        rows.append({"symbol": symbol, "count": count, "usual": None if usual is None else round(usual, 2),
                     "multiple": None if multiple is None else round(multiple, 1), "history": history,
                     "held": symbol in held})
    # Highest multiple first; a ticker usually never named at this hour ranks by its count, as if its usual were one.
    rows.sort(key=lambda r: (-(r["multiple"] or (r["count"] if r["history"] else 0)), -r["count"], r["symbol"]))
    return rows[:MAX_BUZZ]


def spiking(state: dict, by_symbol: dict[str, list[float]], symbol: str, at: float) -> bool:
    """Was ``symbol`` buzz at ``at`` (the rule ``buzz`` uses), with enough history to say so?"""
    times = by_symbol.get(symbol) or []
    count = _count(times, at - 3600, at)
    if count < SPIKE_MIN:
        return False
    windows = _usual_windows(state, at)
    if len(windows) < MIN_USUAL_DAYS:
        return False
    usual = sum(_count(times, a, b) for a, b in windows) / len(windows)
    return not usual or count / usual >= SPIKE_MULTIPLE


def spike_record(state: dict, trades: list[tuple[str, float, float | None]]) -> str | None:
    """His closed trades (ticker, entry time, realized P&L) entered while that ticker was buzz, as one line of counts;
    None when there are none to count."""
    by_symbol = _by_symbol(state)
    hits = [pnl for symbol, at, pnl in trades if pnl is not None and spiking(state, by_symbol, symbol, at)]
    if not hits:
        return None
    up = sum(1 for p in hits if p > 0)
    net = sum(hits)
    sign = "−" if net < 0 else "+"
    return (f"Your entries during a mention spike: {len(hits)} closed trade{'s' if len(hits) != 1 else ''}, {up} up, "
            f"net {sign}${abs(net):,.0f}.")


# --------------------------------------------------------------------------- Reddit

def _user_agent() -> str:
    who = re.sub(r"[^\w-]", "", os.environ.get("REDDIT_USERNAME", "").strip().removeprefix("u/")) or "tradejournal"
    return f"server:tradejournal.chatter:v1 (by /u/{who})"


def _reddit_token(client: httpx.Client, now: float) -> str:
    with _lock:
        if _token.get("value") and _token.get("until", 0) > now + 60:
            return _token["value"]
    response = client.post(REDDIT_TOKEN_URL, data={"grant_type": "client_credentials"},
                           auth=(os.environ["REDDIT_CLIENT_ID"].strip(), os.environ["REDDIT_CLIENT_SECRET"].strip()),
                           headers={"User-Agent": _user_agent()})
    response.raise_for_status()
    body = response.json()
    with _lock:
        _token.update(value=body["access_token"], until=now + float(body.get("expires_in") or 3600))
    return body["access_token"]


def read_reddit(client: httpx.Client, now: float) -> dict[str, list[dict]]:
    """One pass: the subreddit's hot, rising and new listings (100 posts each) as plain post dicts."""
    with _lock:
        if _rate.get("remaining", RATE_FLOOR) < RATE_FLOOR and now < _rate.get("reset_at", 0):
            raise RuntimeError("Reddit rate limit: waiting for the window to reset")
    token = _reddit_token(client, now)
    out = {}
    for kind in ("hot", "rising", "new"):
        response = client.get(f"{REDDIT_API}/r/{SUBREDDIT}/{kind}", params={"limit": 100, "raw_json": 1},
                              headers={"Authorization": f"bearer {token}", "User-Agent": _user_agent()})
        try:
            with _lock:
                _rate.update(remaining=float(response.headers["x-ratelimit-remaining"]),
                             reset_at=now + float(response.headers["x-ratelimit-reset"]))
        except (KeyError, ValueError):
            pass
        if response.status_code == 401:
            with _lock:
                _token.clear()
        response.raise_for_status()
        out[kind] = [c.get("data") or {} for c in (response.json().get("data") or {}).get("children") or []]
    return out


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

    def _market_day(self, day: date) -> bool:
        hours = self.calendar.hours(day) if self.calendar is not None else None
        return day.weekday() < 5 and any(w[0] == "regular" for w in session_windows(day, hours))

    def _due(self, name: str, until: dtime, now: float, market_only: bool) -> bool:
        local = datetime.fromtimestamp(now, ET)
        if not READ_FROM <= local.time() < until or (market_only and not self._market_day(local.date())):
            return False
        state = load(name, self.root)
        return now - max(state.get("ok_at") or 0, state.get("error_at") or 0) >= PASS_SECONDS

    def run_once(self) -> None:
        now = self.clock()
        if reddit_enabled() and self._due("reddit", REDDIT_UNTIL, now, True):
            self._read("reddit", lambda client: self._reddit(client, now), now)
        if nyt_enabled() and self._due("nyt", NYT_UNTIL, now, False):
            self._read("nyt", lambda client: {**load("nyt", self.root), "items": read_nyt(client)}, now)

    def _reddit(self, client: httpx.Client, now: float) -> dict:
        return record_pass(load("reddit", self.root), read_reddit(client, now), _known(self.engine), now)

    def _read(self, name: str, read, now: float) -> None:
        try:
            with self.client_factory() as client:
                state = read(client)
            save(name, {**state, "ok_at": now, "error": None}, self.root)
        except Exception as error:  # one source failing leaves the other and the app alone
            log.warning("Chatter %s read unavailable (%s)", name, type(error).__name__)
            save(name, {**load(name, self.root), "error_at": now, "error": type(error).__name__}, self.root)

    async def loop(self) -> None:
        while True:
            try:
                await asyncio.to_thread(self.run_once)
            except Exception:
                log.exception("Chatter pass failed")
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


def view(trades: list[tuple[str, float, float | None]], held: set[str], blocked: set[str], now: float,
         root: Path | None = None) -> dict:
    """What the Feed's Chatter filter shows: each source's state, the buzz chips, one line of his record on spike
    entries, and the rows (buzz, rising posts, headlines). Saved files only: no network, no model."""
    from app.engine.desk_feed import _item, _trim
    reddit_state, reddit = _state("reddit", reddit_enabled(), root)
    nyt_state, nyt = _state("nyt", nyt_enabled(), root)
    named = re.compile(r"\b(?:" + "|".join(re.escape(s) for s in sorted(blocked)) + r")\b") if blocked else None

    def hidden(symbols, *texts) -> bool:
        return bool(set(symbols) & blocked) or bool(named and any(named.search(t or "") for t in texts))

    chips, items, record = [], [], None
    if reddit:
        record = spike_record(reddit, trades)
        for row in buzz(reddit, now, held):
            if hidden([row["symbol"]]):
                continue
            chips.append(row)
            symbol, count = row["symbol"], row["count"]
            if not row["history"]:
                text, detail = f"{symbol} mentioned in {_times(count, 'post')} in the last hour", "No usual yet."
            elif row["multiple"] is None:
                text, detail = f"{symbol} mentioned in {_times(count, 'post')} in the last hour", "Usually none at this hour."
            else:
                text = f"{symbol} mentioned {row['multiple']:g}× its usual rate in the last hour"
                detail = f"{_times(count, 'post')} in the last hour; usually {row['usual']:g} at this hour."
            if record:
                detail = f"{detail} {record}"
            search = f"https://www.reddit.com/r/{SUBREDDIT}/search/?q={quote(symbol)}&restrict_sr=1&sort=new"
            items.append(_item(REDDIT_NAME, f"buzz:{symbol}", int(now), text, symbol=symbol, detail=detail, href=None,
                               publisher=REDDIT_NAME, url=search, buzz=True))
        for post in reddit.get("posts") or []:
            if hidden(post.get("symbols") or [], post["title"]):
                continue
            detail = f"{_times(post['score'], 'point')} · {_times(post['comments'], 'comment')}"
            symbols = post.get("symbols") or []
            items.append(_item(REDDIT_NAME, f"post:{post['id']}", int(post["created"]), _trim(post["title"], 200),
                               symbol=symbols[0] if symbols else None, detail=detail, href=None,
                               publisher=REDDIT_NAME, url=post["url"], buzz=False))
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
    return {"sources": {REDDIT_NAME: reddit_state, NYT_NAME: nyt_state}, "buzz": chips, "record": record,
            "items": items}


def off(reason: str = "unavailable") -> dict:
    """The view when it could not be built: each source that is set up reads ``reason``."""
    return {"sources": {REDDIT_NAME: reason if reddit_enabled() else "not set up",
                        NYT_NAME: reason if nyt_enabled() else "not set up"},
            "buzz": [], "record": None, "items": []}
