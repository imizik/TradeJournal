from datetime import datetime, timedelta, timezone

from app.engine.jo_morning_market import collect_market

NOW = datetime(2026, 10, 19, 12, 45, tzinfo=timezone.utc)


def article(**kwargs):
    return dict(headline="Company reports an update", symbols=["MU"], created_at=(NOW-timedelta(hours=1)).isoformat(),
                url="https://example.com/update", **kwargs)


def collect(symbols=("MU",), snapshots=None, articles=None):
    return collect_market(symbols, NOW, snapshots_reader=lambda _: snapshots or {},
                          news_reader=lambda *_: articles or [], clock=lambda: NOW+timedelta(seconds=2))


def test_observation_and_retrieval_are_distinct_and_only_scoped_data_is_returned():
    rows, gaps = collect(snapshots={"MU": {"latestTrade": {"p": 123.1234567, "t": (NOW-timedelta(seconds=30)).isoformat()}},
                                  "SECRET": {"latestTrade": {"p": 999, "t": NOW.isoformat()}}}, articles=[article()])
    assert [r["id"] for r in rows] == ["market-MU", "headline-1"]
    assert rows[0]["observed_at"] == NOW-timedelta(seconds=30)
    assert rows[0]["retrieved_at"] == NOW+timedelta(seconds=2)
    assert "123.1234567" in rows[0]["text"] and "recent" in rows[0]["text"]
    assert "SECRET" not in str(rows)
    assert "not complete" in gaps[-1]


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
    assert calls == ["prices"] and len(rows) == 1
    assert "private credentials" not in str(gaps)
    assert any("Price source unavailable" in gap for gap in gaps)


def test_scope_is_deduplicated_bounded_and_no_news_does_not_imply_no_catalysts():
    calls = []
    symbols = ["MU", "MU"] + ["A"+chr(65+i) for i in range(25)] + ["invalid/symbol"]
    rows, gaps = collect_market(symbols, NOW, snapshots_reader=lambda s: calls.append(s) or {},
        news_reader=lambda s, start, end: calls.append(s) or [], clock=lambda: NOW)
    assert len(calls) == 2 and calls[0] == calls[1] and len(calls[0]) == 20 and calls[0][0] == "MU"
    assert not rows
    assert any("unsupported" in gap for gap in gaps)
    assert any("limited to 20" in gap for gap in gaps)
    assert any("do not infer" in gap for gap in gaps)


def test_trade_observed_during_request_is_kept_before_actual_retrieval():
    rows, _ = collect(snapshots={"MU": {"latestTrade": {"p": 123, "t": (NOW+timedelta(seconds=1)).isoformat()}}})
    assert rows[0]["observed_at"] == NOW+timedelta(seconds=1)
    assert rows[0]["retrieved_at"] == NOW+timedelta(seconds=2)


def test_default_prices_use_existing_tradier_quotes_once_and_keep_news_independent(monkeypatch):
    from app.engine import jo_morning_market as market, tradier
    calls = []
    def quotes(symbols):
        calls.append(symbols)
        return {"MU": tradier.TradierQuote(symbol="MU", last=123,
            trade_date=int((NOW-timedelta(seconds=30)).timestamp()*1000))}
    monkeypatch.setattr(tradier, "TRADIER_BASE_URL", "https://api.tradier.com")
    monkeypatch.setattr(tradier, "get_quotes_once", quotes)
    rows, gaps = market.collect_market(["MU"], NOW, news_reader=lambda *_: [article()], clock=lambda: NOW)
    assert calls == [["MU"]]
    assert rows[0]["source"] == "Tradier full-market latest trade; not an executable quote"
    assert rows[0]["observed_at"] == NOW-timedelta(seconds=30)
    assert rows[1]["id"] == "headline-1"
    monkeypatch.setattr(tradier, "TRADIER_BASE_URL", "https://sandbox.tradier.com")
    rows, gaps = market.collect_market(["MU"], NOW, news_reader=lambda *_: [article()], clock=lambda: NOW)
    assert calls == [["MU"]]  # Sandbox must not be advertised as live full-market evidence.
    assert [row["id"] for row in rows] == ["headline-1"]
    assert any("Price source unavailable" in gap for gap in gaps)
