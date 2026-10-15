"""Time-adjusted RVOL, and the loader its caller injects.

``compute_rvol_time_adjusted`` used to import ``app.engine.alpaca`` inside its
body to read the minute-bar cache, which is what kept ``app.engine.indicators``
out of the pure set in ``test_import_boundaries.py``. The bars now arrive
through a ``MinuteBarLoader`` the caller supplies, so these tests pin both
halves: that the function computes from whatever the loader returns and asks
for nothing else, and that the enricher's loader still reads the cache only.
"""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.engine import alpaca_enricher
from app.engine.indicators import compute_rvol_time_adjusted

ET = ZoneInfo("America/New_York")


def _daily_bar(day: date) -> dict:
    return {"t": f"{day.isoformat()}T04:00:00Z", "o": 1, "h": 1, "l": 1, "c": 1, "v": 1000}


def _minute_bars(day: date, volume_per_minute: float, minutes: int = 60) -> list[dict]:
    """One bar a minute from 09:30 ET, in UTC like Alpaca returns them."""
    start = datetime(day.year, day.month, day.day, 9, 30, tzinfo=ET)
    return [
        {
            "t": (start + timedelta(minutes=i)).astimezone(ZoneInfo("UTC")).isoformat(),
            "o": 1,
            "h": 1,
            "l": 1,
            "c": 1,
            "v": volume_per_minute,
        }
        for i in range(minutes)
    ]


# 10 trading days before the fill date, most recent last.
_PRIOR_DAYS = [date(2026, 5, d) for d in (1, 4, 5, 6, 7, 8, 11, 12, 13, 14)]
_FILL_DATE = date(2026, 5, 15)
_FILL_DT = datetime(2026, 5, 15, 10, 0)  # 30 minutes into the session


def _loader(volumes: dict[date, float]):
    """A MinuteBarLoader over fixed per-day volumes, recording what it was asked."""
    asked: list[tuple[str, date]] = []

    def load(ticker: str, day: date) -> list[dict]:
        asked.append((ticker, day))
        vol = volumes.get(day)
        return _minute_bars(day, vol) if vol is not None else []

    return load, asked


def test_rvol_is_computed_from_the_bars_the_loader_returns():
    # 31 bars land in the 09:30–10:00 window inclusive: today 31 x 200,
    # each of ten history days 31 x 100, so the ratio is exactly 2.
    volumes = {_FILL_DATE: 200.0} | {d: 100.0 for d in _PRIOR_DAYS}
    load, asked = _loader(volumes)

    rvol = compute_rvol_time_adjusted(
        "NVDA", _FILL_DATE, _FILL_DT, [_daily_bar(d) for d in _PRIOR_DAYS], load
    )

    assert rvol == 2.0
    # It asks for the fill date and the prior days from the daily bars, and for
    # nothing else — no widening of the window, no other ticker.
    assert asked == [("NVDA", _FILL_DATE)] + [("NVDA", d) for d in reversed(_PRIOR_DAYS)]


def test_days_the_loader_has_no_bars_for_do_not_count_as_history():
    # Four history days available: below the five-day floor, so no number
    # rather than a number built on a thin sample.
    volumes = {_FILL_DATE: 200.0} | {d: 100.0 for d in _PRIOR_DAYS[:4]}
    load, _ = _loader(volumes)

    assert (
        compute_rvol_time_adjusted(
            "NVDA", _FILL_DATE, _FILL_DT, [_daily_bar(d) for d in _PRIOR_DAYS], load
        )
        is None
    )

    volumes[_PRIOR_DAYS[4]] = 100.0
    load, _ = _loader(volumes)

    assert (
        compute_rvol_time_adjusted(
            "NVDA", _FILL_DATE, _FILL_DT, [_daily_bar(d) for d in _PRIOR_DAYS], load
        )
        == 2.0
    )


def test_no_bars_for_the_fill_day_itself_yields_no_rvol():
    load, asked = _loader({d: 100.0 for d in _PRIOR_DAYS})

    assert (
        compute_rvol_time_adjusted(
            "NVDA", _FILL_DATE, _FILL_DT, [_daily_bar(d) for d in _PRIOR_DAYS], load
        )
        is None
    )
    # And it stops there rather than reading 20 days of history for nothing.
    assert asked == [("NVDA", _FILL_DATE)]


def test_a_premarket_fill_has_no_rvol():
    load, asked = _loader({_FILL_DATE: 200.0} | {d: 100.0 for d in _PRIOR_DAYS})

    assert (
        compute_rvol_time_adjusted(
            "NVDA",
            _FILL_DATE,
            datetime(2026, 5, 15, 9, 0),
            [_daily_bar(d) for d in _PRIOR_DAYS],
            load,
        )
        is None
    )
    assert asked == []


def test_the_enrichers_loader_reads_the_cache_and_never_fetches(monkeypatch):
    calls: list[tuple] = []

    def fake_fetch(tickers, day, cache_only=False):
        calls.append((tickers, day, cache_only))
        return {"NVDA": [{"t": "2026-05-15T13:30:00Z", "v": 1}]}

    monkeypatch.setattr(alpaca_enricher, "fetch_minute_bars_for_date", fake_fetch)

    assert alpaca_enricher._cached_minute_bars("NVDA", _FILL_DATE) == [
        {"t": "2026-05-15T13:30:00Z", "v": 1}
    ]
    assert calls == [(["NVDA"], _FILL_DATE, True)]

    # A ticker the cache does not hold is an empty list, not a KeyError.
    monkeypatch.setattr(alpaca_enricher, "fetch_minute_bars_for_date", lambda *a, **k: {})
    assert alpaca_enricher._cached_minute_bars("NVDA", _FILL_DATE) == []


def test_enrichment_fetches_the_rvol_history_it_compares_against(monkeypatch):
    # Only the fill's own day used to be fetched; the history was whatever the
    # cache already held, so a ticker traded once had no RVOL. Enrichment now
    # caches the prior sessions first, one request per day for all tickers.
    import uuid
    from sqlmodel import Session, SQLModel, create_engine
    from app.models import Account, Fill, FillMarketContext

    provider = {_FILL_DATE: 200.0} | {d: 100.0 for d in _PRIOR_DAYS}
    cache: dict[tuple[str, date], list[dict]] = {}
    requests: list[tuple[frozenset[str], date]] = []

    def fake_minute_fetch(tickers, day, cache_only=False):
        if not cache_only:
            requests.append((frozenset(tickers), day))
            for ticker in tickers:
                if day in provider:
                    cache[(ticker, day)] = _minute_bars(day, provider[day])
        return {t: cache[(t, day)] for t in tickers if (t, day) in cache}

    monkeypatch.setattr(alpaca_enricher, "alpaca_configured", lambda: True)
    monkeypatch.setattr(alpaca_enricher, "fetch_minute_bars_for_date", fake_minute_fetch)
    monkeypatch.setattr(alpaca_enricher, "fetch_daily_bars", lambda tickers, start, end: {
        t: [_daily_bar(d) for d in _PRIOR_DAYS] for t in tickers})

    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        account = Account(id=uuid.uuid4(), name="Roth IRA", type="roth_ira", last4="8267")
        fills = [Fill(id=uuid.uuid4(), account_id=account.id, ticker=ticker, instrument_type="stock", side="buy",
                      contracts=1, price=1, executed_at=_FILL_DT, raw_email_id=ticker) for ticker in ("NVDA", "AMD")]
        session.add_all([account, *fills])
        session.commit()

        assert alpaca_enricher.enrich_fills_alpaca(fills, session) == 2

        for fill in fills:
            assert session.get(FillMarketContext, fill.id).rvol_time_adjusted == 2.0
    both = frozenset({"AMD", "NVDA"})
    assert sorted(requests, key=lambda r: r[1]) == [(both, d) for d in [*_PRIOR_DAYS, _FILL_DATE]]
