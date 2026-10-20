"""Bounded public market evidence for the existing morning packet; no inference."""
from datetime import datetime, timedelta, timezone
import math
import re
from urllib.parse import urlsplit

from app.engine import news, tradier

UTC = timezone.utc
MAX_SYMBOLS = 20
MAX_HEADLINES = 8


def stamp(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.astimezone(UTC) if parsed.tzinfo is not None else None
    except (ValueError, TypeError):
        return None


def collect_market(symbols, cutoff, *, snapshots_reader=None, news_reader=None, clock=None):
    """Two bounded existing-provider reads, each independently allowed to fail.

    Only symbol names leave the app. Trade observations after actual retrieval are excluded. News stays within
    the requested cutoff window; retrieval time is the actual completion time.
    """
    clock = clock or (lambda: datetime.now(UTC))
    selected = list(dict.fromkeys(s for s in symbols if isinstance(s, str) and re.fullmatch(r"[A-Z]{1,6}(\.[A-Z])?", s)))
    gaps = []
    if any(s not in selected for s in symbols):
        gaps.append("Some saved symbols are unsupported by this stock-only market reader.")
    if len(selected) > MAX_SYMBOLS:
        gaps.append("Market coverage limited to 20 symbols, approved holdings first, then saved watchlist.")
    selected = selected[:MAX_SYMBOLS]
    rows = []
    if not selected:
        return rows, ["No eligible saved symbols for market context."]
    if snapshots_reader is None:
        def snapshots_reader(tickers):
            if tradier.TRADIER_BASE_URL != "https://api.tradier.com":
                raise ValueError("Live Tradier data required")
            quotes = tradier.get_quotes_once(tickers)
            return {symbol: {"latestTrade": {"p": quote.last,
                "t": datetime.fromtimestamp(quote.trade_date / 1000, UTC).isoformat()
                     if quote.trade_date else None}}
                for symbol, quote in quotes.items()}
    news_reader = news_reader or (lambda tickers, start, end: news.fetch_news(
        symbols=tickers, start=start, end=end, limit=MAX_HEADLINES, fast=True))
    try:
        snapshots = snapshots_reader(selected)
        if not isinstance(snapshots, dict):
            raise ValueError("Malformed snapshots")
    except Exception:
        snapshots = {}
        gaps.append("Price source unavailable; no substitute price feed was used.")
    retrieved = clock()
    missing, stale = [], []
    for symbol in selected:
        snap = snapshots.get(symbol)
        trade = snap.get("latestTrade") if isinstance(snap, dict) else None
        observed = stamp(trade.get("t")) if isinstance(trade, dict) else None
        price = trade.get("p") if isinstance(trade, dict) else None
        if (observed is None or observed > retrieved or type(price) not in (int, float)
                or not math.isfinite(price) or price <= 0):
            missing.append(symbol)
            continue
        age = (retrieved - observed).total_seconds()
        freshness = "recent" if age <= 600 else "stale"
        if freshness == "stale":
            stale.append(symbol)
        rows.append(dict(id=f"market-{symbol}", kind="fact", observed_at=observed, retrieved_at=retrieved,
            source="Tradier full-market latest trade; not an executable quote",
            text=f"{symbol}: last reported trade ${price}; {freshness} at collection (age {int(age)} seconds). "
                 "Unadjusted trade price, not a bid/ask or option mark. No split-adjusted change or return is inferred."))
    if missing:
        gaps.append("No valid price at or before retrieval for: " + ", ".join(missing) + ".")
    if stale:
        gaps.append("Last trade older than 10 minutes; not current premarket evidence: " + ", ".join(stale) + ".")
    gaps.append("Prices use Tradier full-market data only; a recent retrieval does not make an old trade current. No IEX fallback.")
    start = cutoff - timedelta(hours=36)
    try:
        articles = news_reader(selected, start, cutoff)
        if not isinstance(articles, list):
            raise ValueError("Malformed news")
    except Exception:
        articles = []
        gaps.append("Headline source unavailable; absence of headlines is not evidence of no catalyst.")
    retrieved = clock()
    seen = set()
    for article in articles[:MAX_HEADLINES]:
        if not isinstance(article, dict):
            continue
        observed = stamp(article.get("created_at"))
        title, url = article.get("headline"), article.get("url")
        tickers = article.get("symbols")
        if (not observed or not start <= observed <= cutoff or not isinstance(title, str) or not title.strip()
                or not isinstance(tickers, list) or not set(selected).intersection(s for s in tickers if isinstance(s, str))
                or not isinstance(url, str)):
            continue
        try:
            parsed = urlsplit(url)
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
                continue
        except ValueError:
            continue
        if url in seen:
            continue
        seen.add(url)
        rows.append(dict(id=f"headline-{len(seen)}", kind="fact", observed_at=observed, retrieved_at=retrieved,
            source="Alpaca / Benzinga headline; article claims are not independently verified",
            text=f"{', '.join(s for s in selected if s in tickers)} — {title.strip()[:500]}\n{url[:1200]}"))
    gaps.append(f"Headlines are a bounded 36-hour sample for {', '.join(selected)} (at most {MAX_HEADLINES}); not complete news, earnings or macro-calendar coverage.")
    if not seen:
        gaps.append("No eligible headlines returned; do not infer that there are no catalysts.")
    return rows, gaps
