"""
Polygon enrichment.

Two things this module guards, in order of importance:

1. Locally computed indicators reproduce Polygon's own indicator endpoints for
   the same bars. The fixtures are real Polygon output (bars and series) for
   CRWV, which listed on 2025-03-28 — inside Polygon's two-year window — so
   every value of every series, warmup included, is reproducible. If someone
   "fixes" the seeding toward the textbook form, these fail.
2. The call budget: one daily-bars, one hourly-bars and one minute-window call
   per ticker; nothing when the caches cover the fills; only the hourly and
   minute calls when a later session is needed.
"""

import json
import re
import uuid
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from sqlmodel import Session, SQLModel, create_engine

from app.engine import enricher
from app.engine.indicators import polygon_daily_indicators, polygon_hourly_ema
from app.models import Account, Fill

FIXTURES = Path(__file__).parent / "fixtures" / "polygon"
ET = ZoneInfo("America/New_York")


# ---------------------------------------------------------------------------
# 1. Golden values: real Polygon output
# ---------------------------------------------------------------------------

def _assert_series_matches(local: dict[str, float], polygon: dict[str, float], tol: float) -> float:
    # Same shape: the first reported bar and every bar after it, no extras.
    assert set(local) == set(polygon), (
        f"date sets differ: only local {sorted(set(local) - set(polygon))[:3]}, "
        f"only polygon {sorted(set(polygon) - set(local))[:3]}"
    )
    max_diff = max(abs(local[k] - polygon[k]) for k in polygon)
    assert max_diff <= tol, f"max |local - polygon| = {max_diff}"
    return max_diff


def test_daily_indicators_reproduce_polygon_series():
    fx = json.loads((FIXTURES / "crwv_daily.json").read_text())
    by_date = polygon_daily_indicators(fx["bars"])
    assert len(by_date) == len(fx["bars"]) == 272

    for name, polygon in fx["polygon"].items():
        local = {d: row[name] for d, row in by_date.items() if row[name] is not None}
        # SMA sums in a different order than Polygon (1e-13 noise); everything
        # else is bit-for-bit.
        tol = 1e-9 if name.startswith("sma") else 0.0
        _assert_series_matches(local, polygon, tol)

    # The shape Polygon reports: SMA/EMA from bar `window`, RSI-14 from bar 14
    # (not 15), MACD from bar 26 with the signal present from the same bar.
    first = {name: min(series) for name, series in fx["polygon"].items()}
    dates = [enricher.polygon_bar_et_date(b) for b in sorted(fx["bars"], key=lambda b: b["t"])]
    assert first["sma_20"] == first["ema_20"] == dates[19]
    assert first["sma_50"] == dates[49]
    assert first["ema_9"] == dates[8]
    assert first["rsi_14"] == dates[13]
    assert first["macd"] == first["macd_signal"] == first["macd_histogram"] == dates[25]


def test_hourly_ema_reproduces_polygon_series():
    fx = json.loads((FIXTURES / "crwv_hourly_ema9.json").read_text())
    local = polygon_hourly_ema(fx["bars"], fx["window"])
    _assert_series_matches(local, fx["polygon"], 0.0)
    # Reported from bar 9 of the window: the fixture's bars start 8 bars
    # before Polygon's first value.
    assert min(local) == min(fx["polygon"])


def test_textbook_seeding_is_not_what_polygon_does():
    """Documented so nobody 'corrects' the EMA seed: an SMA-seeded EMA-20
    (the common textbook form) disagrees with Polygon by cents for months."""
    fx = json.loads((FIXTURES / "crwv_daily.json").read_text())
    closes = [float(b["c"]) for b in sorted(fx["bars"], key=lambda b: b["t"])]
    dates = [enricher.polygon_bar_et_date(b) for b in sorted(fx["bars"], key=lambda b: b["t"])]
    alpha = 2 / 21
    ema = sum(closes[:20]) / 20
    textbook = {dates[19]: ema}
    for i in range(20, len(closes)):
        ema = alpha * closes[i] + (1 - alpha) * ema
        textbook[dates[i]] = ema
    polygon = fx["polygon"]["ema_20"]
    diffs = [abs(textbook[d] - polygon[d]) for d in sorted(polygon)]
    # The seed difference decays by (1 - 2/21) per session: dollars at the
    # start, still a tenth of a cent 50 sessions in.
    assert diffs[0] > 1.0
    assert diffs[50] > 1e-3


# ---------------------------------------------------------------------------
# 2. Call budget and cache freshness, against a fake Polygon
# ---------------------------------------------------------------------------

_AGGS = re.compile(r"https://api\.polygon\.io/v2/aggs/ticker/(\w+)/range/1/(day|hour|minute)/(\d{4}-\d{2}-\d{2})/(\d{4}-\d{2}-\d{2})")


def _et_ms(day: date, hour: int = 0, minute: int = 0) -> int:
    return int(datetime(day.year, day.month, day.day, hour, minute, tzinfo=ET).timestamp() * 1000)


def _weekdays(frm: date, to: date):
    day = frm
    while day <= to:
        if day.weekday() < 5:
            yield day
        day += timedelta(days=1)


class FakePolygon:
    """Deterministic aggregates for any /v2/aggs request, with optional
    Polygon-style paging (`next_url` carrying a cursor)."""

    def __init__(self, page_bars: int | None = None):
        self.page_bars = page_bars
        self.calls: list[str] = []

    def bars(self, ticker: str, timespan: str, frm: date, to: date) -> list[dict]:
        seed = sum(ord(c) for c in ticker) % 7
        out = []
        for day in _weekdays(frm, to):
            base = 100.0 + seed + (day.toordinal() % 40) * 0.25
            if timespan == "day":
                out.append({"t": _et_ms(day), "o": base, "h": base + 1, "l": base - 1, "c": base, "v": 1000})
            elif timespan == "hour":
                for hour in range(4, 20):
                    c = base + hour * 0.05
                    out.append({"t": _et_ms(day, hour), "o": c, "h": c, "l": c, "c": c, "v": 10})
            else:
                for idx in range(390):
                    hour, minute = divmod(9 * 60 + 30 + idx, 60)
                    c = base + idx * 0.01
                    out.append({"t": _et_ms(day, hour, minute), "o": c, "h": c, "l": c, "c": c, "v": 1, "vw": c - 0.05})
        return out

    def __call__(self, url: str, params: dict | None = None) -> dict:
        self.calls.append(url)
        m = _AGGS.match(url)
        assert m, url
        ticker, timespan, frm, to = m.group(1), m.group(2), date.fromisoformat(m.group(3)), date.fromisoformat(m.group(4))
        offset = int(url.split("cursor=")[1]) if "cursor=" in url else 0
        bars = self.bars(ticker, timespan, frm, to)
        if self.page_bars and len(bars) > offset + self.page_bars:
            return {
                "results": bars[offset : offset + self.page_bars],
                "next_url": f"https://api.polygon.io/v2/aggs/ticker/{ticker}/range/1/{timespan}/{frm}/{to}?cursor={offset + self.page_bars}",
            }
        return {"results": bars[offset:], "status": "OK"}

    def count(self, timespan: str) -> int:
        return sum(1 for u in self.calls if f"/range/1/{timespan}/" in u)


@pytest.fixture
def fake(monkeypatch, tmp_path):
    fake = FakePolygon()
    monkeypatch.setattr(enricher, "_polygon_request", fake)
    monkeypatch.setattr(enricher, "POLYGON_API_KEY", "test")
    monkeypatch.setattr(enricher, "CACHE_DIR", tmp_path)
    return fake


def _session():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    # As the job does (app/engine/jobs.py): keep the enricher's floats on the
    # objects instead of reloading DECIMAL columns after each batch commit.
    session = Session(engine, expire_on_commit=False)
    account = Account(id=uuid.uuid4(), name="Roth IRA", type="roth_ira", last4="8267")
    session.add(account)
    session.commit()
    return session, account


def _fill(account: Account, ticker: str, day: date, at: time, option: bool = False, strike: float = 100) -> Fill:
    kwargs = dict(
        id=uuid.uuid4(),
        account_id=account.id,
        ticker=ticker,
        instrument_type="option" if option else "stock",
        side="buy_to_open" if option else "buy",
        contracts=1,
        price=500 if option else 100,  # option: $5/share premium, struck at the money
        executed_at=datetime.combine(day, at),
        raw_email_id=f"{ticker}-{day}-{at}",
    )
    if option:
        kwargs.update(option_type="call", strike=strike, expiration=day + timedelta(days=7))
    return Fill(**kwargs)


def _recent_sessions() -> tuple[date, date, date, date]:
    """d1 < d2 < d3 < d4, all weekdays, d4 <= yesterday, d1..d3 within 60 days."""
    today = datetime.now(ET).date()
    d3 = today - timedelta(days=4)
    while d3.weekday() >= 5:
        d3 -= timedelta(days=1)
    d4 = d3 + timedelta(days=1)
    while d4.weekday() >= 5:
        d4 += timedelta(days=1)
    d2 = d3 - timedelta(days=7)
    d1 = d3 - timedelta(days=21)
    for d in (d1, d2):
        assert d.weekday() < 5
    assert d4 <= today - timedelta(days=1)
    return d1, d2, d3, d4


def test_enrich_fills_uses_three_calls_per_ticker_and_refreshes_only_what_a_later_session_needs(fake):
    session, account = _session()
    d1, d2, d3, d4 = _recent_sessions()
    bar_1035 = next(b for b in fake.bars("AAA", "minute", d2, d2) if b["t"] == _et_ms(d2, 10, 35))
    fills = [
        _fill(account, "AAA", d1, time(10, 35)),
        _fill(account, "AAA", d2, time(10, 35), option=True, strike=round(bar_1035["c"])),
        _fill(account, "AAA", d3, time(14, 5)),
        _fill(account, "BBB", d2, time(9, 45)),
        _fill(account, "BBB", d3, time(15, 59)),
    ]
    for fill in fills:
        session.add(fill)
    session.commit()

    assert enricher.enrich_fills(fills, session) == 5

    # One daily, one hourly and one minute-window call per ticker. The old
    # design made 7 indicator calls per ticker plus one minute call per
    # (ticker, day): 14 + 5 = 19 for this set.
    assert fake.count("day") == 2
    assert fake.count("hour") == 2
    assert fake.count("minute") == 2
    assert len(fake.calls) == 6

    today = datetime.now(ET).date()
    daily_from = today - timedelta(days=enricher._DAILY_HISTORY_DAYS)
    daily = fake.bars("AAA", "day", daily_from, today - timedelta(days=1))
    closes = [(enricher.polygon_bar_et_date(b), b["c"]) for b in daily]

    # Daily indicators: last completed session strictly before the fill date.
    f_d3 = fills[2]
    prior = [c for d, c in closes if d < d3.isoformat()]
    assert f_d3.sma_20_at_fill == pytest.approx(sum(prior[-20:]) / 20, abs=1e-9)
    assert f_d3.sma_50_at_fill == pytest.approx(sum(prior[-50:]) / 50, abs=1e-9)
    expected = polygon_daily_indicators(daily)
    prior_day = max(d for d, _ in closes if d < d3.isoformat())
    assert f_d3.ema_9_at_fill == expected[prior_day]["ema_9"]
    assert f_d3.ema_20_at_fill == expected[prior_day]["ema_20"]
    assert f_d3.rsi_14_at_fill == expected[prior_day]["rsi_14"]
    assert f_d3.macd_at_fill == expected[prior_day]["macd"]
    assert f_d3.macd_signal_at_fill == expected[prior_day]["macd_signal"]

    # Hourly EMA-9: the last completed hour bar (13:00 for a 14:05 fill).
    hourly = fake.bars("AAA", "hour", d1 - timedelta(days=enricher._HOURLY_WARMUP_DAYS), d3)
    assert f_d3.ema_9h_at_fill == polygon_hourly_ema(hourly, 9)[f"{d3.isoformat()} 13"]

    # Underlying price/VWAP from the minute bar at the fill, greeks for the option.
    f_opt = fills[1]
    assert f_opt.underlying_price_at_fill == bar_1035["c"]
    assert f_opt.vwap_at_fill == bar_1035["vw"]
    assert f_opt.iv_at_fill is not None and f_opt.delta_at_fill is not None
    assert fills[0].iv_at_fill is None  # stock

    # Warm caches: the same fills again cost nothing.
    fake.calls.clear()
    assert enricher.enrich_fills(fills, session) == 5
    assert fake.calls == []

    # A later session: the daily cache was fetched through yesterday so it
    # still covers d4-1; the hourly window and that day's minute bars are new.
    later = [_fill(account, "AAA", d4, time(11, 0)), _fill(account, "BBB", d4, time(11, 0))]
    for fill in later:
        session.add(fill)
    session.commit()
    fake.calls.clear()
    assert enricher.enrich_fills(later, session) == 2
    assert fake.count("day") == 0
    assert fake.count("hour") == 2
    assert fake.count("minute") == 2
    assert later[0].sma_20_at_fill is not None and later[0].ema_9h_at_fill is not None
    assert later[0].underlying_price_at_fill is not None


def test_minute_window_writes_the_per_day_cache_files_single_day_lookups_use(fake):
    d1, d2, d3, _ = _recent_sessions()
    by_day = enricher.fetch_minute_bars_for_days("AAA", [d1, d2, d3])
    assert len(fake.calls) == 1 and fake.count("minute") == 1
    assert set(by_day) == {d1, d2, d3}
    assert by_day[d2]["10:35"]["close"] == pytest.approx(next(
        b["c"] for b in fake.bars("AAA", "minute", d2, d2) if b["t"] == _et_ms(d2, 10, 35)
    ))

    # Same file name the single-day request always used.
    path = enricher._minute_day_path("AAA", d2)
    assert path.name == f"_v2_aggs_ticker_AAA_range_1_minute_{d2}_{d2}_adjusted=true_limit=1000_sort=asc.json"
    assert path.exists()

    fake.calls.clear()
    assert enricher.fetch_minute_bars("AAA", d2) == by_day[d2]
    assert fake.calls == []

    # A single missing day is still fetched with the original per-day request.
    d0 = d1 - timedelta(days=7)
    assert enricher.fetch_minute_bars("AAA", d0)["09:30"]["close"] > 0
    assert fake.calls == [f"https://api.polygon.io/v2/aggs/ticker/AAA/range/1/minute/{d0}/{d0}"]


def test_fetch_aggregates_follows_next_url_pages(fake):
    fake.page_bars = 100
    frm, to = date(2025, 1, 6), date(2025, 12, 31)
    data = enricher._fetch_aggregates("AAA", "day", frm, to)
    expected = fake.bars("AAA", "day", frm, to)
    assert len(expected) > 200
    assert data["results"] == expected
    assert "next_url" not in data
    assert len(fake.calls) == -(-len(expected) // 100)


def test_date_windows_group_fill_dates_by_span():
    d = date(2026, 1, 5)
    days = [d, d + timedelta(days=10), d + timedelta(days=59), d + timedelta(days=60), d + timedelta(days=200)]
    assert enricher._date_windows(days, 60) == [days[:3], [days[3]], [days[4]]]
    assert enricher._date_windows([], 60) == []


def test_bars_cache_covers_requires_the_needed_session_to_be_published():
    now = datetime(2026, 9, 15, 8, 0, tzinfo=ET)
    bar = {"t": _et_ms(date(2026, 9, 11)), "c": 1.0}

    def entry(frm: str, to: str, fetched: datetime, results: list[dict]) -> dict:
        return {"from": frm, "to": to, "fetched_at": fetched.timestamp(), "results": results}

    covers = enricher._bars_cache_covers
    # Window must start no later than needed.
    assert not covers(entry("2024-10-01", "2026-09-14", now, [bar]), date(2024, 9, 16), date(2026, 9, 11), now)
    # Has a bar on/after the needed session.
    assert covers(entry("2024-09-01", "2026-09-11", now, [bar]), date(2024, 9, 16), date(2026, 9, 11), now)
    # Needs Monday 9/14 (a bar Polygon would have published by 9/15) but was
    # fetched on 9/14: not trusted; fetched on 9/15: trusted (holiday or
    # missing session, nothing more will appear).
    same_day = datetime(2026, 9, 14, 17, 0, tzinfo=ET)
    assert not covers(entry("2024-09-01", "2026-09-14", same_day, [bar]), date(2024, 9, 16), date(2026, 9, 14), now)
    assert covers(entry("2024-09-01", "2026-09-14", now, [bar]), date(2024, 9, 16), date(2026, 9, 14), now)
    # Requested only through 9/11 — cannot vouch for 9/14.
    assert not covers(entry("2024-09-01", "2026-09-11", now, [bar]), date(2024, 9, 16), date(2026, 9, 14), now)
    # Empty windows are retried weekly.
    assert covers(entry("2024-09-01", "2026-09-14", now - timedelta(days=6), []), date(2024, 9, 16), date(2026, 9, 14), now)
    assert not covers(entry("2024-09-01", "2026-09-14", now - timedelta(days=8), []), date(2024, 9, 16), date(2026, 9, 14), now)


def test_calls_per_minute_setting(monkeypatch):
    f = enricher._configured_calls_per_minute
    assert f("") == 4.5
    assert f("abc") == 4.5
    assert f("0") == 4.5
    assert f("-3") == 4.5
    assert f("nan") == 4.5
    assert f("30") == 30.0
    monkeypatch.setenv("POLYGON_CALLS_PER_MINUTE", "12")
    assert f() == 12.0
    monkeypatch.delenv("POLYGON_CALLS_PER_MINUTE")
    assert f() == 4.5
    assert enricher._RateLimiter(60)._interval == pytest.approx(1.0)


def test_polygon_request_appends_the_key_to_next_url_without_dropping_its_cursor(monkeypatch):
    seen = {}

    class Resp:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"results": []}

    def fake_get(url, timeout):
        seen["url"] = url
        return Resp()

    monkeypatch.setattr(enricher.httpx, "get", fake_get)
    monkeypatch.setattr(enricher, "POLYGON_API_KEY", "KEY")
    monkeypatch.setattr(enricher._limiter, "wait", lambda: None)
    enricher._polygon_request("https://api.polygon.io/v2/aggs/ticker/AAA/range/1/hour/1/2?cursor=abc")
    assert seen["url"] == "https://api.polygon.io/v2/aggs/ticker/AAA/range/1/hour/1/2?cursor=abc&apiKey=KEY"
    enricher._polygon_request("https://api.polygon.io/v2/x", {"limit": 5, "adjusted": "true"})
    assert seen["url"] == "https://api.polygon.io/v2/x?limit=5&adjusted=true&apiKey=KEY"
