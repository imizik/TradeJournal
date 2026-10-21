"""Bounded public market evidence for the existing morning packet; no inference."""
from datetime import date, datetime, timedelta, timezone
import math
import re
import time
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from sqlmodel import select

from app.engine import news, tradier
from app.models import MarketContextItem

UTC = timezone.utc
ET = ZoneInfo("America/New_York")
MAX_SYMBOLS = 20
MAX_HEADLINES = 8
# Market backdrop proxies, priced ahead of the owner's symbols. No futures feed exists.
BACKDROP = ("SPY", "QQQ", "SMH")
BACKDROP_NAMES = {"SPY": "S&P 500 ETF", "QQQ": "Nasdaq-100 ETF", "SMH": "semiconductor ETF"}
MAX_MARKET_HEADLINES = 4
# Broad-tape headlines kept only when the headline names a market-wide theme.
MACRO_WORDS = re.compile(r"\b(fed|fomc|powell|rate cuts?|rate hikes?|interest rates?|treasur(y|ies)|yields?|bonds?|inflation|"
    r"cpi|ppi|pce|jobs report|payrolls?|jobless|unemployment|gdp|recession|tariffs?|trade war|sanctions?|"
    r"war|ceasefire|opec|oil|crude|dollar|futures|stock market|wall street|s&p 500|nasdaq|dow)\b", re.I)
MINUTES_BUDGET_SECONDS = 45
EARNINGS_DAYS = 7  # About five sessions.
CALENDAR_DAYS = 7  # Today and the coming week, so a Thursday still sees next Wednesday's FOMC.


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
        gaps.append("No eligible saved symbols; only the market backdrop ETFs were priced.")
    priced = list(dict.fromkeys([*BACKDROP, *selected]))
    if snapshots_reader is None:
        snapshots_reader = tradier_snapshots
    # No tickers reads one page of the broad tape, which market_headlines filters by theme.
    news_reader = news_reader or (lambda tickers, start, end: news.fetch_news(
        symbols=tickers, start=start, end=end, limit=MAX_HEADLINES if tickers else 50, fast=True))
    try:
        snapshots = snapshots_reader(priced)
        if not isinstance(snapshots, dict):
            raise ValueError("Malformed snapshots")
    except Exception:
        snapshots = {}
        gaps.append("Price source unavailable; no substitute price feed was used.")
    retrieved = clock()
    missing, stale, unverified = [], [], []
    for symbol in priced:
        snap = snapshots.get(symbol)
        trade = snap.get("latestTrade") if isinstance(snap, dict) else None
        observed = stamp(trade.get("t")) if isinstance(trade, dict) else None
        price = trade.get("p") if isinstance(trade, dict) else None
        if (observed is None or observed > retrieved or not valid_price(price)):
            missing.append(symbol)
            continue
        age = (retrieved - observed).total_seconds()
        freshness = "recent" if age <= 600 else "stale"
        if freshness == "stale":
            stale.append(symbol)
        label = f"{symbol} ({BACKDROP_NAMES[symbol]}; market backdrop proxy)" if symbol in BACKDROP else symbol
        status = f"{freshness} at collection (age {int(age)} seconds)"
        if snap.get("session") == "extended":
            reference = snap.get("reference") if isinstance(snap.get("reference"), dict) else {}
            base, base_at = reference.get("p"), stamp(reference.get("t"))
            change = (f"; {(price - base) / base * 100:+.2f}% vs prior regular-session last trade ${base} "
                      f"({base_at.astimezone(ET):%b %d %H:%M} ET)"
                      if valid_price(base) and base_at and base_at.astimezone(ET).date() < observed.astimezone(ET).date() else
                      "; no prior regular-session trade available for a change")
            text = (f"{label}: extended-hours last ${price} (1-minute bar starting {observed.astimezone(ET):%H:%M} ET){change}; "
                    f"{status}. Thin extended-hours trading; not a bid/ask, official close or option mark.")
            source = "Tradier extended-hours 1-minute timesales and quote; not an executable quote"
        else:
            text = (f"{label}: last reported trade ${price}; {status}. "
                    "Unadjusted trade price, not a bid/ask or option mark. No split-adjusted change or return is inferred.")
            if snap.get("session") == "regular":
                text += " No extended-hours trade found today."
            elif snap.get("session") == "unverified":
                text += " Extended-hours minutes could not be read; premarket activity is unknown."
                unverified.append(symbol)
            source = "Tradier full-market latest trade; not an executable quote"
        rows.append(dict(id=f"market-{symbol}", kind="fact", observed_at=observed, retrieved_at=retrieved,
            source=source, text=text))
    if missing:
        gaps.append("No valid price at or before retrieval for: " + ", ".join(missing) + ".")
    if unverified:
        gaps.append("Extended-hours minutes unavailable (provider error, rate limit or time budget) for: " + ", ".join(unverified) + ".")
    if stale:
        gaps.append("Last trade older than 10 minutes; not current premarket evidence: " + ", ".join(stale) + ".")
    gaps.append("Prices use Tradier full-market data only; a recent retrieval does not make an old trade current. No IEX fallback.")
    gaps.append("No index futures, Treasury yields, dollar index or oil prices (no source without new provider access); "
                "SPY/QQQ/SMH extended-hours trades are the only market-direction proxy.")
    start = cutoff - timedelta(hours=36)
    if not selected:
        rows.extend(market_headlines(cutoff, news_reader, clock, gaps))
        return rows, gaps
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
    gaps.append(f"Headlines are a bounded 36-hour sample for {', '.join(selected)} (at most {MAX_HEADLINES}); not complete news coverage.")
    if not seen:
        gaps.append("No eligible headlines returned; do not infer that there are no catalysts.")
    rows.extend(market_headlines(cutoff, news_reader, clock, gaps, seen))
    return rows, gaps


def valid_price(value):
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def tradier_snapshots(tickers, *, quotes=None, read=None, monotonic=time.monotonic):
    """Today's last extended-hours minute per symbol, else the regular-session last trade.

    One batched quote read plus one cached 1-minute timesales read per symbol (the same
    request level alerts make). Minute reads stop after a fixed time budget; a symbol
    whose minutes fail or are empty falls back to its quote, labelled as such.
    """
    if tradier.TRADIER_BASE_URL != "https://api.tradier.com":
        raise ValueError("Live Tradier data required")
    if read is None:
        from app.engine.chart_feed import chart_feed
        read = chart_feed.read
    found = (quotes or tradier.get_quotes_once)(tickers)
    today = datetime.now(ET).date()
    deadline = monotonic() + MINUTES_BUDGET_SECONDS
    result = {}
    for symbol in tickers:
        quote = found.get(symbol)
        regular = {"p": quote.last, "t": datetime.fromtimestamp(quote.trade_date / 1000, UTC).isoformat()
                   if quote.trade_date else None} if quote else None
        # "regular": minutes were read and today has none; "unverified": they could not be read.
        session = "unverified"
        bar = None
        if monotonic() < deadline:
            try:
                bar = last_minute(read, symbol, today)
                session = "regular"
            except Exception:
                pass
        snap = {"latestTrade": regular, "session": session} if regular else {}
        if bar:
            snap = {"latestTrade": {"p": bar["close"], "t": datetime.fromtimestamp(bar["time"], UTC).isoformat()},
                    "session": "extended", "reference": regular}
        if snap:
            result[symbol] = snap
    return result


def last_minute(read, symbol, day):
    from app.engine.chart_math import normalize_bars
    data, _, _ = read("/v1/markets/timesales", {"symbol": symbol, "interval": "1min", "session_filter": "all",
        "start": day.strftime("%Y-%m-%d 04:00"), "end": day.strftime("%Y-%m-%d 20:00")}, 15)
    series = (data or {}).get("series") or {}
    found = series.get("data") if isinstance(series, dict) else None
    bars = normalize_bars(found if isinstance(found, list) else [found] if isinstance(found, dict) else [])
    return bars[-1] if bars and datetime.fromtimestamp(bars[-1]["time"], ET).date() == day else None


def market_headlines(cutoff, news_reader, clock, gaps, seen=None):
    """A few broad-tape headlines on market-wide themes (Fed, rates, geopolitics), not the owner's tickers."""
    seen = seen if seen is not None else set()
    start = cutoff - timedelta(hours=18)
    try:
        articles = news_reader(None, start, cutoff)
        if not isinstance(articles, list):
            raise ValueError("Malformed news")
    except Exception:
        gaps.append("Market-wide headline source unavailable; absence is not evidence of a quiet macro backdrop.")
        return []
    retrieved = clock()
    rows = []
    for article in articles:
        if len(rows) >= MAX_MARKET_HEADLINES:
            break
        if not isinstance(article, dict):
            continue
        observed = stamp(article.get("created_at"))
        title, url = article.get("headline"), article.get("url")
        if (not observed or not start <= observed <= cutoff or not isinstance(title, str) or not MACRO_WORDS.search(title)
                or not isinstance(url, str) or url in seen):
            continue
        try:
            parsed = urlsplit(url)
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
                continue
        except ValueError:
            continue
        seen.add(url)
        rows.append(dict(id=f"macro-headline-{len(rows) + 1}", kind="fact", observed_at=observed, retrieved_at=retrieved,
            source="Alpaca / Benzinga broad-tape headline; article claims are not independently verified",
            text=f"Market-wide — {title.strip()[:500]}\n{url[:1200]}"))
    gaps.append(f"Market-wide headlines are a keyword-filtered 18-hour broad-tape sample (at most {MAX_MARKET_HEADLINES}); "
                "not complete macro or geopolitical coverage.")
    return rows


def week_events(day, end):
    """Scheduled FOMC, CPI and jobs releases from today through ``end``, via the Daily Review's reader."""
    from app.ai.review_context import macro_events
    events = []
    for offset in range((end - day).days + 1):
        current = day + timedelta(days=offset)
        if current.weekday() < 5:
            events += [{"date": current, **event} for event in macro_events(current)["events"] if event["when"] == "today"]
    return events


def collect_backdrop(session, symbols, now, *, events_reader=week_events):
    """Local, provider-free backdrop: the coming week's macro calendar, the saved VIX and upcoming earnings.

    Each part fails on its own and becomes a gap. VIX and earnings are the pre-trade check's
    market_context_item snapshot, refreshed every 15 minutes on weekdays; their read times are kept.
    """
    rows, gaps = [], []
    day = now.astimezone(ET).date()
    try:
        end = day + timedelta(days=CALENDAR_DAYS)
        events = events_reader(day, end)
        if events:
            lines = [f"{e['date']:%a %b %d} {e['time_et']} ET: {e['event']}" + (" (today)" if e["date"] == day else "") for e in events]
            text = f"Scheduled US macro releases {day:%a %b %d} through {end:%a %b %d}: " + "; ".join(lines) + "."
        else:
            text = f"No FOMC, CPI or jobs releases are scheduled {day:%a %b %d} through {end:%a %b %d}."
        rows.append(dict(id="macro-calendar", kind="fact", observed_at=None, retrieved_at=now,
            source="Saved macro calendar from Federal Reserve and BLS schedules (FOMC, CPI and jobs only)", text=text))
        gaps.append("Macro calendar covers FOMC, CPI and jobs reports only; PPI, retail sales, PCE, GDP, jobless claims, "
                    "Fed speakers and Treasury auctions are not included.")
    except Exception:
        gaps.append("Macro calendar unavailable for this week; do not infer that no releases are scheduled.")
    try:
        vix = session.exec(select(MarketContextItem).where(MarketContextItem.kind == "vix")
                           .order_by(MarketContextItem.fetched_at.desc()).limit(1)).first()
        fetched = vix.fetched_at.replace(tzinfo=UTC) if vix else None
        if vix is None or not valid_price(vix.value) or fetched > now:
            gaps.append("No saved VIX reading; volatility backdrop unknown.")
        else:
            observed = vix.observed_at.replace(tzinfo=UTC) if vix.observed_at else None
            age = int((now - fetched).total_seconds())
            change = f", provider-reported {vix.change_pct:+.2f}% vs its prior close" if vix.change_pct is not None else ""
            traded = f"; index value time {observed.astimezone(ET):%b %d %H:%M} ET" if observed and observed <= now else ""
            rows.append(dict(id="vix", kind="fact", observed_at=fetched, retrieved_at=now,
                source="Tradier VIX quote saved by the market-context job; not a live feed",
                text=f"VIX {vix.value:.2f}{change}{traded}; read from Tradier {age // 60} minutes before collection"
                     + (" (stale; older than 30 minutes)." if age > 1800 else ".")))
    except Exception:
        gaps.append("Saved VIX reading unavailable; volatility backdrop unknown.")
    try:
        # Same symbol rule as collect_market, so every evidence ID passes Check validation.
        wanted = list(dict.fromkeys(s for s in symbols if isinstance(s, str) and re.fullmatch(r"[A-Z]{1,6}(\.[A-Z])?", s)))
        upcoming = session.exec(select(MarketContextItem).where(MarketContextItem.kind == "earnings",
            MarketContextItem.symbol.in_(wanted), MarketContextItem.event_date >= day,
            MarketContextItem.event_date <= day + timedelta(days=EARNINGS_DAYS))
            .order_by(MarketContextItem.event_date, MarketContextItem.symbol)).all()
        seen = set()
        for row in upcoming[:10]:
            fetched = row.fetched_at.replace(tzinfo=UTC)
            if fetched > now or row.symbol in seen:
                continue
            seen.add(row.symbol)
            days = (row.event_date - day).days
            when = "today" if days == 0 else "tomorrow" if days == 1 else f"in {days} days"
            rows.append(dict(id=f"earnings-{row.symbol}", kind="fact", observed_at=fetched, retrieved_at=now,
                source="Tradier corporate calendar saved by the market-context job",
                text=f"{row.symbol} earnings {row.event_date:%a %b %d} ({when}); {row.status or 'unknown status'}"
                     + (f", {row.label}" if row.label else "") + "; before-open or after-close timing is not known."))
        gaps.append(f"Earnings dates cover saved holdings, recent trades and the watchlist for the next {EARNINGS_DAYS} days only; "
                    "a report already released appears only through headlines.")
    except Exception:
        gaps.append("Saved earnings dates unavailable; do not infer that no holding reports this week.")
    return rows, gaps
