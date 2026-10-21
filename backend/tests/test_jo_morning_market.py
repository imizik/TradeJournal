from datetime import datetime, timedelta, timezone

from sqlmodel import Session, SQLModel, create_engine

from app.engine.jo_morning_market import BACKDROP, collect_backdrop, collect_market, tradier_snapshots
from app.models import MarketContextItem

NOW = datetime(2026, 10, 19, 12, 45, tzinfo=timezone.utc)


def article(**kwargs):
    return dict(headline="Company reports an update", symbols=["MU"], created_at=(NOW-timedelta(hours=1)).isoformat(),
                url="https://example.com/update", **kwargs)


def collect(symbols=("MU",), snapshots=None, articles=None):
    rows, gaps = collect_market(symbols, NOW, snapshots_reader=lambda _: snapshots or {},
                          news_reader=lambda tickers, *_: (articles or []) if tickers else [], clock=lambda: NOW+timedelta(seconds=2))
    return [r for r in rows if r["id"] != "discovery-scope"], gaps


def test_observation_and_retrieval_are_distinct_and_only_scoped_data_is_returned():
    rows, gaps = collect(snapshots={"MU": {"latestTrade": {"p": 123.1234567, "t": (NOW-timedelta(seconds=30)).isoformat()}},
                                  "SECRET": {"latestTrade": {"p": 999, "t": NOW.isoformat()}}}, articles=[article()])
    assert [r["id"] for r in rows] == ["market-MU", "headline-1"]
    assert rows[0]["observed_at"] == NOW-timedelta(seconds=30)
    assert rows[0]["retrieved_at"] == NOW+timedelta(seconds=2)
    assert "123.1234567" in rows[0]["text"] and "recent" in rows[0]["text"]
    assert "SECRET" not in str(rows)
    assert any("not complete news" in gap for gap in gaps)


def test_old_trade_is_stale_even_with_new_retrieval_and_future_invalid_prices_are_omitted():
    symbols = ["OLD", "FUTURE", "BAD", "NAN", "BOOL"]
    rows, gaps = collect(symbols, {"OLD": {"latestTrade": {"p": 3, "t": (NOW-timedelta(days=3)).isoformat()}},
        "FUTURE": {"latestTrade": {"p": 4, "t": (NOW+timedelta(seconds=3)).isoformat()}},
        "BAD": {"latestTrade": {"p": -1, "t": NOW.isoformat()}},
        "NAN": {"latestTrade": {"p": float("nan"), "t": NOW.isoformat()}},
        "BOOL": {"latestTrade": {"p": True, "t": NOW.isoformat()}}})
    assert len(rows) == 1 and "stale" in rows[0]["text"]
    assert "FUTURE, BAD, NAN, BOOL" in " ".join(gaps)
    assert "not current premarket" in " ".join(gaps)


def test_headlines_reject_future_naive_out_of_window_unrelated_and_unsafe_urls():
    base = article()
    articles = [base, base, {**base, "created_at": (NOW+timedelta(seconds=1)).isoformat()},
        {**base, "created_at": NOW.replace(tzinfo=None).isoformat()},
        {**base, "created_at": (NOW-timedelta(days=4)).isoformat()}, {**base, "symbols": ["SECRET"]},
        {**base, "url": "javascript:alert(1)"}, {**base, "url": "https://user:secret@example.com"}]
    rows, _ = collect(articles=articles)
    assert len(rows) == 1 and rows[0]["id"] == "headline-1"


def test_sources_fail_independently_without_retries_or_raw_exception_leaks():
    calls = []
    def fail(_):
        calls.append("prices")
        raise RuntimeError("private credentials should not leak")
    rows, gaps = collect_market(["MU"], NOW, snapshots_reader=fail, news_reader=lambda *_: [article()], clock=lambda: NOW)
    assert calls == ["prices"] and len(rows) == 2
    assert "private credentials" not in str(gaps)
    assert any("Price source unavailable" in gap for gap in gaps)


def test_scope_is_deduplicated_bounded_and_no_news_does_not_imply_no_catalysts():
    calls = []
    symbols = ["MU", "MU"] + ["A"+chr(65+i) for i in range(25)] + ["invalid/symbol"]
    rows, gaps = collect_market(symbols, NOW, snapshots_reader=lambda s: calls.append(s) or {},
        news_reader=lambda s, start, end: calls.append(s) or [], clock=lambda: NOW)
    # Backdrop ETFs are priced ahead of, and outside, the 20 owner symbols; ticker news stays owner-only.
    assert len(calls) == 3 and calls[1] == [*BACKDROP, *calls[2]] and len(calls[2]) == 20 and calls[2][0] == "MU"
    assert calls[0] is None
    assert [r["id"] for r in rows] == ["discovery-scope"]
    assert any("unsupported" in gap for gap in gaps)
    assert any("limited to 20" in gap for gap in gaps)
    assert any("do not infer" in gap for gap in gaps)


def test_trade_observed_during_request_is_kept_before_actual_retrieval():
    rows, _ = collect(snapshots={"MU": {"latestTrade": {"p": 123, "t": (NOW+timedelta(seconds=1)).isoformat()}}})
    assert rows[0]["observed_at"] == NOW+timedelta(seconds=1)
    assert rows[0]["retrieved_at"] == NOW+timedelta(seconds=2)


def minutes(*bars):
    return {"series": {"data": [dict(timestamp=int(t.timestamp()), open=p, high=p, low=p, close=p, volume=100) for t, p in bars]}}


def test_default_prices_use_existing_tradier_quotes_once_and_keep_news_independent(monkeypatch):
    from app.engine import jo_morning_market as market, tradier
    from app.engine.chart_feed import ChartFeedError, chart_feed
    calls = []
    def quotes(symbols):
        calls.append(symbols)
        return {"MU": tradier.TradierQuote(symbol="MU", last=123,
            trade_date=int((NOW-timedelta(seconds=30)).timestamp()*1000))}
    def no_minutes(*_):
        raise ChartFeedError("offline")
    monkeypatch.setattr(tradier, "TRADIER_BASE_URL", "https://api.tradier.com")
    monkeypatch.setattr(tradier, "get_quotes_once", quotes)
    monkeypatch.setattr(chart_feed, "read", no_minutes)
    rows, gaps = market.collect_market(["MU"], NOW, news_reader=lambda *_: [article()], clock=lambda: NOW)
    assert calls == [[*BACKDROP, "MU"]]
    rows = [r for r in rows if r["id"] != "discovery-scope"]
    assert rows[0]["id"] == "market-MU"
    assert rows[0]["source"] == "Tradier full-market latest trade; not an executable quote"
    assert rows[0]["observed_at"] == NOW-timedelta(seconds=30)
    assert "premarket activity is unknown" in rows[0]["text"]
    assert rows[1]["id"] == "headline-1"
    assert any("SPY, QQQ, SMH" in gap for gap in gaps)  # Backdrop ETFs with no quote are disclosed.
    monkeypatch.setattr(tradier, "TRADIER_BASE_URL", "https://sandbox.tradier.com")
    rows, gaps = market.collect_market(["MU"], NOW, news_reader=lambda *_: [article()], clock=lambda: NOW)
    assert len(calls) == 1  # Sandbox must not be advertised as live full-market evidence.
    assert [row["id"] for row in rows] == ["discovery-scope", "headline-1"]
    assert any("Price source unavailable" in gap for gap in gaps)


def test_extended_hours_minutes_give_premarket_change_and_fall_back_per_symbol(monkeypatch):
    from app.engine import jo_morning_market as market, tradier
    monkeypatch.setattr(tradier, "TRADIER_BASE_URL", "https://api.tradier.com")
    today = datetime.now(market.ET).replace(hour=8, minute=44, second=0, microsecond=0)
    yesterday_close = (today - timedelta(days=1)).replace(hour=15, minute=59)
    def quotes(symbols):
        return {s: tradier.TradierQuote(symbol=s, last=100, trade_date=int(yesterday_close.timestamp()*1000)) for s in symbols}
    reads = []
    def read(path, params, ttl):
        reads.append((path, params["symbol"], params["session_filter"]))
        if params["symbol"] == "MU":
            raise RuntimeError("timeout")
        if params["symbol"] == "QQQ":
            return minutes((today - timedelta(days=1), 99), ), 0, None  # Yesterday's bars are not today's premarket.
        return minutes((today - timedelta(minutes=5), 101), (today, 101.5)), 0, None
    snaps = tradier_snapshots(["SPY", "QQQ", "MU"], quotes=quotes, read=read, now=today + timedelta(minutes=1))
    assert reads[0] == ("/v1/markets/timesales", "SPY", "all")
    assert snaps["SPY"]["session"] == "extended" and snaps["SPY"]["latestTrade"]["p"] == 101.5
    assert snaps["QQQ"]["session"] == "regular" and snaps["MU"]["session"] == "unverified"
    now = today.astimezone(timezone.utc) + timedelta(minutes=1)
    rows, gaps = collect_market(["MU"], now, snapshots_reader=lambda _: snaps, news_reader=lambda *_: [],
                                clock=lambda: now)
    text = {r["id"]: r["text"] for r in rows}
    assert "SPY (S&P 500 ETF; market backdrop proxy): extended-hours last $101.5 (1-minute bar starting 08:44 ET)" in text["market-SPY"]
    assert "+1.50% vs prior regular-session last trade $100" in text["market-SPY"] and "recent" in text["market-SPY"]
    assert "stale" in text["market-QQQ"] and "No extended-hours trade" in text["market-QQQ"]
    assert "premarket activity is unknown" in text["market-MU"] and "No extended-hours trade" not in text["market-MU"]
    assert any("Extended-hours minutes unavailable" in gap and "MU" in gap for gap in gaps)
    assert any("No index futures, Treasury yields" in gap for gap in gaps)
    # A spent time budget stops further minute reads; quotes still answer.
    clock = iter([0, 100, 100, 100])
    reads.clear()
    snaps = tradier_snapshots(["SPY", "QQQ"], quotes=quotes, read=read, monotonic=lambda: next(clock))
    assert not reads and snaps["SPY"]["session"] == "unverified"


def test_market_wide_headlines_are_theme_filtered_bounded_and_fail_alone():
    def news(tickers, start, end):
        if tickers:
            return [article()]
        broad = [article(), {**article(), "headline": "Fed's Powell signals patience on rate cuts", "url": "https://example.com/fed",
                 "symbols": []}]
        broad += [{**article(), "headline": f"Treasury yields climb {i}", "url": f"https://example.com/y{i}", "symbols": []} for i in range(6)]
        return broad + [{**article(), "headline": "Oil jumps", "url": "http://insecure.example.com", "symbols": []}]
    rows, gaps = collect_market(["MU"], NOW, snapshots_reader=lambda _: {},
        news_reader=news, clock=lambda: NOW)
    ids = [r["id"] for r in rows]
    assert ids == ["discovery-scope", "headline-1", "macro-headline-1", "macro-headline-2", "macro-headline-3", "macro-headline-4"]
    assert "Powell" in rows[2]["text"] and rows[2]["text"].startswith("Market-wide")
    assert any("keyword-filtered" in gap for gap in gaps)
    def broad_fails(tickers, start, end):
        if tickers is None:
            raise RuntimeError("secret")
        return [article()]
    rows, gaps = collect_market(["MU"], NOW, snapshots_reader=lambda _: {}, news_reader=broad_fails, clock=lambda: NOW)
    assert [r["id"] for r in rows] == ["discovery-scope", "headline-1"]
    assert any("Broad-market discovery/news unavailable" in gap for gap in gaps) and "secret" not in str(gaps)


def backdrop_db(tmp_path):
    db = create_engine("sqlite:///" + str(tmp_path / "backdrop.sqlite"))
    SQLModel.metadata.create_all(db)
    naive = NOW.replace(tzinfo=None)
    with Session(db) as session:
        session.add_all([
            MarketContextItem(kind="vix", symbol="VIX", value=18.42, change_pct=-3.1, observed_at=naive - timedelta(hours=16),
                              fetched_at=naive - timedelta(minutes=5), source="Tradier"),
            MarketContextItem(kind="earnings", symbol="TSLA", event_date=NOW.date(), status="confirmed", label="Q3 2026",
                              fetched_at=naive - timedelta(hours=3), source="Tradier"),
            MarketContextItem(kind="earnings", symbol="MU", event_date=NOW.date() + timedelta(days=30), status="estimated",
                              fetched_at=naive - timedelta(hours=3), source="Tradier"),
            MarketContextItem(kind="earnings", symbol="SECRET", event_date=NOW.date(), status="confirmed",
                              fetched_at=naive - timedelta(hours=3), source="Tradier"),
            MarketContextItem(kind="earnings", symbol="BRK/B", event_date=NOW.date(), status="confirmed",
                              fetched_at=naive - timedelta(hours=3), source="Tradier")])
        session.commit()
    return db


def test_backdrop_reads_coming_week_calendar_saved_vix_and_near_earnings(tmp_path):
    db = backdrop_db(tmp_path)
    with Session(db) as session:
        rows, gaps = collect_backdrop(session, ["TSLA", "MU", "BRK/B"], NOW)  # Monday Oct 19 2026, real calendar file
    by_id = {r["id"]: r for r in rows}
    assert list(by_id) == ["macro-calendar", "vix", "earnings-TSLA"]
    assert by_id["macro-calendar"]["text"] == "No FOMC, CPI or jobs releases are scheduled Mon Oct 19 through Mon Oct 26."
    assert by_id["macro-calendar"]["observed_at"] is None and by_id["macro-calendar"]["retrieved_at"] == NOW
    assert "VIX 18.42, provider-reported -3.10% vs its prior close" in by_id["vix"]["text"]
    assert "5 minutes before collection." in by_id["vix"]["text"]
    assert by_id["vix"]["observed_at"] == NOW - timedelta(minutes=5)
    assert "TSLA earnings Mon Oct 19 (today); confirmed, Q3 2026" in by_id["earnings-TSLA"]["text"]
    assert "SECRET" not in str(rows)
    assert any("FOMC, CPI and jobs reports only" in gap for gap in gaps)
    with Session(db) as session:
        rows, _ = collect_backdrop(session, ["TSLA"], NOW + timedelta(hours=1))
    assert "(stale; older than 30 minutes)" in next(r for r in rows if r["id"] == "vix")["text"]
    with Session(db) as session:  # Thursday still sees next Wednesday's FOMC.
        rows, _ = collect_backdrop(session, ["TSLA"], NOW + timedelta(days=3))
    assert rows[0]["text"] == "Scheduled US macro releases Thu Oct 22 through Thu Oct 29: Wed Oct 28 14:00 ET: FOMC decision."


def test_backdrop_parts_fail_independently(tmp_path):
    db = backdrop_db(tmp_path)
    def broken(day, end):
        raise LookupError("not covered")
    with Session(db) as session:
        rows, gaps = collect_backdrop(session, ["TSLA"], NOW, events_reader=broken)
    assert [r["id"] for r in rows] == ["vix", "earnings-TSLA"]
    assert any("Macro calendar unavailable" in gap for gap in gaps)
    empty = create_engine("sqlite:///" + str(tmp_path / "empty.sqlite"))
    SQLModel.metadata.create_all(empty)
    with Session(empty) as session:
        rows, gaps = collect_backdrop(session, ["TSLA"], NOW, events_reader=lambda day, end: [])
    assert [r["id"] for r in rows] == ["macro-calendar"] and "No FOMC, CPI or jobs releases" in rows[0]["text"]
    assert any("No saved VIX reading" in gap for gap in gaps)


def test_discovery_is_independent_of_saved_symbols_and_prices_new_candidates_first():
    broad = [dict(article(), symbols=["HELD", "WATCH", "CAPPED", "NEW"], headline="NEW wins a major contract")]
    calls = []
    def snapshots(symbols):
        calls.append(symbols)
        return {"NEW": {"latestTrade": {"p": 42, "t": (NOW-timedelta(minutes=1)).isoformat()},
                        "session": "extended", "premarket": dict(low=40, high=43, volume=100000, bars=20,
                            observed_at=(NOW-timedelta(minutes=1)).isoformat())}}
    rows, gaps = collect_market(["HELD", "WATCH"], NOW, excluded_symbols={"CAPPED"}, snapshots_reader=snapshots,
        news_reader=lambda tickers, *_: broad if tickers is None else [], clock=lambda: NOW)
    ids = [r["id"] for r in rows]
    assert calls == [[*BACKDROP, "NEW", "HELD", "WATCH"]]
    assert "discovery-NEW" in ids and "setup-NEW" in ids and "market-NEW" in ids
    assert not any(f"discovery-{s}" in ids for s in ["HELD", "WATCH", "CAPPED"])
    assert "$40–$43" in next(r["text"] for r in rows if r["id"] == "setup-NEW")
    assert any("not a complete market scan" in gap for gap in gaps)


def test_discovery_bounds_rejects_unsafe_news_and_prioritizes_material_catalysts():
    base = article()
    broad = [{**base, "symbols": ["NOISE"], "headline": "Commentator likes a stock", "url": "https://example.com/noise"}]
    broad += [{**base, "symbols": [f"A{chr(65+i)}"], "headline": "Company raises guidance", "url": f"https://example.com/{i}"} for i in range(9)]
    broad += [{**base, "symbols": ["UNSAFE"], "url": "https://user:secret@example.com"},
              {**base, "symbols": ["FUTURE"], "created_at": (NOW+timedelta(minutes=1)).isoformat()},
              {**base, "symbols": ["NAIVE"], "created_at": NOW.replace(tzinfo=None).isoformat()}]
    calls = []
    rows, _ = collect_market([], NOW, snapshots_reader=lambda s: calls.append(s) or {},
        news_reader=lambda *_: broad, clock=lambda: NOW)
    discovered = [r["id"] for r in rows if r["id"].startswith("discovery-") and r["id"] != "discovery-scope"]
    assert discovered == [f"discovery-A{chr(65+i)}" for i in range(6)]
    assert calls == [[*BACKDROP, *[f"A{chr(65+i)}" for i in range(6)]]]
    assert "UNSAFE" not in str(rows) and "secret" not in str(rows)


def test_saved_symbol_catalysts_survive_newer_generic_headline_crowding():
    base = article()
    articles = [{**base, "headline": "A commentator's market view", "symbols": ["SPY"],
                 "url": f"https://example.com/noise{i}"} for i in range(10)]
    articles += [{**base, "headline": "Applied Digital announces joint venture", "symbols": ["APLD"], "url": "https://example.com/apld"},
                 {**base, "headline": "Analyst cuts Nebius price target", "symbols": ["NBIS"], "url": "https://example.com/nbis"}]
    rows, _ = collect_market(["SPY", "APLD", "NBIS"], NOW, snapshots_reader=lambda _: {},
        news_reader=lambda tickers, *_: articles if tickers else [], clock=lambda: NOW)
    headlines = [r["text"] for r in rows if r["id"].startswith("headline-")]
    assert len(headlines) == 4
    assert "joint venture" in headlines[0] and "price target" in headlines[1]


def test_setup_range_uses_completed_premarket_bars_and_preserves_its_own_time(monkeypatch):
    from app.engine import jo_morning_market as market
    t = NOW - timedelta(minutes=3)
    bars = minutes((t, 40), (t+timedelta(minutes=1), 42), (t+timedelta(hours=2), 99), (t+timedelta(hours=4), 999))
    last, stats = market.session_minutes(lambda *_: (bars, 0, None), "NEW", NOW.astimezone(market.ET).date(),
                                        now=NOW+timedelta(hours=3))
    assert last["close"] == 99  # Future/incomplete minutes cannot supply levels.
    assert stats["low"] == 40 and stats["high"] == 42 and stats["bars"] == 2 and stats["volume"] == 200
    assert stats["observed_at"] == (t+timedelta(minutes=1)).isoformat()
