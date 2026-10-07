"""News tab (T1.2): one headline shape from two feeds, merged and deduplicated.

Pure: the Alpaca (Benzinga) and Polygon normalizers, the merge and the Focused
flag compute on responses they are handed. Fetching and caching live in
``symbol_info_news_feed``. The browser sees only the shape below, never a
provider's:

    id, provider ("alpaca_benzinga" | "polygon"), publisher, headline, url,
    published_at (UTC ISO), summary, tickers, roundup, sentiment, also_in

``sentiment`` is Polygon's per-ticker ``insights`` (positive, negative,
neutral and a reasoning sentence). It is the provider's opinion, never ours.
"""

from datetime import datetime, timezone
import re
from urllib.parse import parse_qsl, urlencode, urlsplit

ALPACA = "alpaca_benzinga"
POLYGON = "polygon"
SHOWN = 20
POOL = 40  # newest articles sent, so Focused can still fill a list of 20 from the pool
ROUNDUP_OVER = 3  # an article tagging more than this many symbols is a roundup
SENTIMENTS = {"positive", "negative", "neutral"}
SENTIMENT_NOTE = "Sentiment is supplied by Polygon, not calculated here."
_TRACKING = re.compile(r"^(utm_|fbclid$|gclid$|mc_|ref$|source$|cmpid$|ocid$)", re.I)


def _when(value) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _tickers(values) -> list[str]:
    seen: dict[str, None] = {}
    for value in values if isinstance(values, list) else []:
        if isinstance(value, str) and value.strip():
            seen[value.strip().upper()] = None
    return list(seen)


def _article(provider, key, publisher, headline, url, published, summary, tickers, sentiment=None) -> dict | None:
    moment = _when(published)
    headline = (headline or "").strip() if isinstance(headline, str) else ""
    if not headline or not moment or not isinstance(url, str) or not url.startswith(("http://", "https://")):
        return None
    summary = summary.strip() if isinstance(summary, str) and summary.strip() else None
    return {"id": f"{provider}:{key}", "provider": provider, "publisher": publisher or None, "headline": headline,
            "url": url, "published_at": _iso(moment), "summary": summary, "tickers": tickers,
            "roundup": len(tickers) > ROUNDUP_OVER, "sentiment": sentiment or [], "also_in": []}


def normalize_alpaca(items: list[dict]) -> list[dict]:
    """Rows from ``news.fetch_news``: {id, headline, summary, symbols, source, created_at, url}."""
    rows = (_article(ALPACA, item.get("id"), item.get("source") or "Benzinga", item.get("headline"), item.get("url"),
                     item.get("created_at"), item.get("summary"), _tickers(item.get("symbols")))
            for item in items if isinstance(item, dict))
    return [row for row in rows if row]


def normalize_polygon(body: dict) -> list[dict]:
    """A ``/v2/reference/news`` response. Per-ticker ``insights`` become ``sentiment``."""
    rows = []
    for item in (body or {}).get("results") or []:
        if not isinstance(item, dict):
            continue
        publisher = item.get("publisher") if isinstance(item.get("publisher"), dict) else {}
        sentiment = [{"ticker": str(i["ticker"]).upper(), "sentiment": i["sentiment"],
                      "reasoning": i.get("sentiment_reasoning") or None}
                     for i in item.get("insights") or []
                     if isinstance(i, dict) and i.get("ticker") and i.get("sentiment") in SENTIMENTS]
        row = _article(POLYGON, item.get("id"), publisher.get("name"), item.get("title"), item.get("article_url"),
                       item.get("published_utc"), item.get("description"), _tickers(item.get("tickers")), sentiment)
        if row:
            rows.append(row)
    return rows


def canonical_url(url: str) -> str:
    """The same story's link however a feed spelled it: no scheme, ``www.``, tracking query, fragment or trailing slash."""
    parts = urlsplit(url.strip())
    host = parts.netloc.lower().removeprefix("www.")
    query = urlencode(sorted((k, v) for k, v in parse_qsl(parts.query) if not _TRACKING.match(k)))
    return f"{host}{parts.path.rstrip('/')}{'?' + query if query else ''}"


def headline_key(headline: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", headline.lower()).split())


def merge(*feeds: list[dict], shown: int = SHOWN, pool: int = POOL) -> list[dict]:
    """Newest first, one row per story. Two rows are one story when their canonical
    links or normalized headlines match; the earlier feed's row stays (Alpaca first),
    and takes the other's sentiment and providers. Returns ``pool`` rows with
    ``shown`` of them the newest ones the tab lists before Focused."""
    ordered = [row for feed in feeds for row in sorted(feed, key=lambda row: row["published_at"], reverse=True)]
    kept: list[dict] = []
    by_url: dict[str, dict] = {}
    by_headline: dict[str, dict] = {}
    for row in ordered:
        twin = by_url.get(canonical_url(row["url"])) or by_headline.get(headline_key(row["headline"]))
        if twin:
            if row["provider"] != twin["provider"] and row["provider"] not in twin["also_in"]:
                twin["also_in"].append(row["provider"])
            if row["sentiment"] and not twin["sentiment"]:
                twin["sentiment"] = row["sentiment"]
            if not twin["summary"]:
                twin["summary"] = row["summary"]
            continue
        row = {**row, "also_in": list(row["also_in"])}
        kept.append(row)
        by_url[canonical_url(row["url"])] = row
        by_headline[headline_key(row["headline"])] = row
    kept.sort(key=lambda row: row["published_at"], reverse=True)
    # Newest ``shown`` of everything, plus the newest ``shown`` of non-roundups (Focused),
    # in time order, capped at ``pool``.
    wanted = {row["id"] for row in kept[:shown]} | {row["id"] for row in [r for r in kept if not r["roundup"]][:shown]}
    return [row for row in kept if row["id"] in wanted][:pool]


def listed(articles: list[dict], focused: bool, shown: int = SHOWN) -> list[dict]:
    """What the tab lists: the newest ``shown``, Focused hiding roundups first."""
    return [row for row in articles if not (focused and row["roundup"])][:shown]
