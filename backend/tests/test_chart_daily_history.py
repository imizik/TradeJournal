"""C0.7 daily/weekly depth: one Tradier series per symbol per New York day, paged by slicing."""

from datetime import date, datetime, timedelta
from math import sin
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.database import get_session
from app.engine import chart_daily as daily_module, chart_feed as feed_module, chart_history
from app.engine.chart_feed import ChartFeed, ChartFeedError
from app.engine.chart_math import ET, chart_bars, normalize_bars
from app.models import Account, Fill
from app.routers import charts

TODAY = date(2026, 10, 1)
HOLIDAYS = {date(2020, 5, 25), date(2024, 9, 2)}  # Monday closures
CLOSURE = {date(2019, 4, 8) + timedelta(days=i) for i in range(4)}  # Monday-Thursday, a week with one session


def rows(start: date, end: date) -> list[dict]:
    """Deterministic weekday rows between the dates, with a holiday Monday and a four-day closure week."""
    out, day, i = [], start, 0
    while day <= end:
        if day.weekday() < 5 and day not in HOLIDAYS and day not in CLOSURE:
            close = 100 + 20 * sin(i / 40) + i * 0.01
            out.append({"date": day.isoformat(), "open": close - 0.3, "high": close + 1, "low": close - 1, "close": close, "volume": 1000 + i})
            i += 1
        day += timedelta(days=1)
    return out


HISTORY = rows(date(2013, 1, 2), TODAY)  # 13 years; the last row is today's forming bar


class Tradier:
    """A Tradier stand-in that answers /history from `data` for the requested dates and counts every call."""

    def __init__(self, monkeypatch, data=HISTORY, guard=True):
        self.data, self.calls, self.status, self.body = data, [], 200, None
        monkeypatch.setattr(feed_module.tradier, "TRADIER_API_KEY", "test-secret")
        monkeypatch.setattr(feed_module.tradier, "TRADIER_BASE_URL", "https://api.tradier.com")
        monkeypatch.setattr(feed_module.httpx, "get", self.get)

        class Clock(datetime):  # 10:00 New York on TODAY, whenever the suite runs
            @classmethod
            def now(cls, tz=None):
                return datetime(TODAY.year, TODAY.month, TODAY.day, 10, tzinfo=ET).astimezone(tz)

        monkeypatch.setattr(feed_module, "datetime", Clock)
        monkeypatch.setattr(daily_module, "datetime", Clock)
        # Daily paging must never touch the minute path.
        if guard:
            monkeypatch.setattr(chart_history.chart_history, "page", lambda *a, **k: pytest.fail("minute history was used"))

    def get(self, url, params, headers, timeout):
        assert url.startswith("https://api.tradier.com/"), url
        self.calls.append((url.rsplit("/", 1)[-1], dict(params)))
        if self.status != 200:
            return httpx.Response(self.status, json={}, request=httpx.Request("GET", url))
        if self.body is not None:
            return httpx.Response(200, content=self.body, request=httpx.Request("GET", url))
        if url.endswith("/history"):
            wanted = [r for r in self.data if params["start"] <= r["date"] <= params["end"]]
            return httpx.Response(200, json={"history": {"day": wanted} if wanted else None}, request=httpx.Request("GET", url))
        if url.endswith("/timesales"):
            stamp = int(datetime(TODAY.year, TODAY.month, TODAY.day, 9, 30, tzinfo=ET).timestamp())
            candle = {"timestamp": stamp, "open": 100, "high": 101, "low": 99, "close": 100, "volume": 10}
            return httpx.Response(200, json={"series": {"data": candle}}, request=httpx.Request("GET", url))
        return httpx.Response(200, json={"quotes": {"quote": {"symbol": "SPY", "last": 100, "trade_date": 1000000}}}, request=httpx.Request("GET", url))

    def history_calls(self):
        return [p for name, p in self.calls if name == "history"]


@pytest.fixture
def tradier(monkeypatch):
    return Tradier(monkeypatch)


def completed(data=HISTORY) -> list[dict]:
    return normalize_bars([r for r in data if r["date"] < TODAY.isoformat()], daily=True)


def walk(feed: ChartFeed, interval: str, limit: int, symbol="SPY") -> list[dict]:
    """Every page from now back to the first bar, returned oldest page last."""
    pages, before = [], int(datetime(2026, 10, 1, 20, 0, tzinfo=ET).timestamp())
    while True:
        page = feed.daily.page(symbol, interval, before, limit, today=TODAY)
        pages.append(page)
        if page["exhausted"]:
            return pages
        assert page["older_cursor"] == page["bars"][0]["time"]
        before = page["older_cursor"]


@pytest.mark.parametrize("interval, limit", [("1D", 500), ("1D", 1200), ("1W", 100), ("1W", 333)])
def test_pages_walk_the_whole_series_with_no_duplicate_or_omission(tradier, interval, limit):
    feed = ChartFeed()
    pages = walk(feed, interval, limit)
    reference = chart_bars([], completed(), interval, "regular")
    stitched = [bar for page in reversed(pages) for bar in page["bars"]]
    assert stitched == reference  # prices, volume and every indicator equal the continuous series
    assert len({b["time"] for b in stitched}) == len(stitched)
    assert all(not p["exhausted"] for p in pages[:-1]) and pages[-1]["exhausted"] and pages[-1]["older_cursor"] is None
    assert all(p["continuation"] is None and p["warmup"] == "ready" and p["source"] == "tradier" and p["issue"] is None for p in pages)
    assert pages[0]["price_basis"] == "split_adjusted" and pages[0]["adjustment"]["basis"] == "split_adjusted"
    assert pages[-1]["history_start"] == HISTORY[0]["date"] == "2013-01-02"  # the earliest bar Tradier holds, not a listing date
    assert len(reference) > limit  # the walk really crossed page seams
    assert len(tradier.history_calls()) == 1  # scrolling ten years costs one provider call


def test_weekly_bars_start_on_monday_and_no_week_is_split_across_a_seam(tradier):
    pages = walk(ChartFeed(), "1W", 97)
    bars = [bar for page in reversed(pages) for bar in page["bars"]]
    assert all(datetime.fromtimestamp(b["time"], ET).weekday() == 0 for b in bars)
    assert sorted({b["time"] for b in bars}) == [b["time"] for b in bars]
    # The four-day closure week and the holiday Monday stay whole weeks, never a stub at a page edge.
    by_week = {datetime.fromtimestamp(b["time"], ET).date(): b for b in bars}
    assert by_week[date(2019, 4, 8)]["volume"] == sum(r["volume"] for r in HISTORY if date(2019, 4, 8) <= date.fromisoformat(r["date"]) <= date(2019, 4, 12))
    assert by_week[date(2020, 5, 25)]["volume"] == sum(r["volume"] for r in HISTORY if date(2020, 5, 25) <= date.fromisoformat(r["date"]) <= date(2020, 5, 29))
    for page in pages[:-1]:
        assert page["older_cursor"] == page["bars"][0]["time"]


def test_workspace_tail_joins_the_series_and_agrees_with_the_first_history_page(tradier):
    feed = ChartFeed()
    data = feed.workspace("SPY", ["1D", "1W"], [], "regular")
    everything = normalize_bars(HISTORY, daily=True)  # including today's forming bar
    for interval in ("1D", "1W"):
        series = chart_bars([], everything, interval, "regular")
        shown = data["panels"][interval]["bars"]
        assert shown == series[-1200:]  # the tail joined by date, indicators over the whole
        # A history page cut inside the window the workspace shows is the same bars, indicators included.
        cut = shown[300]["time"]
        page = feed.daily.page("SPY", interval, cut, 200, today=TODAY)
        assert page["bars"] == [b for b in series if b["time"] < cut][-200:]
        assert page["bars"] == shown[100:300]
        # Where the two overlap (completed bars), they are the same bars, indicators included.
        completed_series = chart_bars([], completed(), interval, "regular")
        overlap = [b for b in shown if b["time"] < completed_series[-1]["time"]]
        assert overlap == [b for b in completed_series if b["time"] in {x["time"] for x in overlap}]
    assert data["panels"]["1D"]["bars"][-1]["time"] == normalize_bars(HISTORY[-1:], daily=True)[0]["time"]  # today's forming bar
    assert data["adjustment"]["status"] == "unknown"  # no split source in this fixture, and the chart says so
    series = [p for p in tradier.history_calls() if p["start"] == "1970-01-01"]
    assert [p["end"] for p in series] == ["2026-09-30"]  # the series ends yesterday
    tail = [p for p in tradier.history_calls() if p["start"] != "1970-01-01"]
    assert tail and tail[0]["start"] == "2026-09-21" and tail[0]["end"] == "2026-10-01"  # ten days, through today


def test_a_new_listing_ends_at_listing_and_withholds_what_it_cannot_compute(monkeypatch):
    data = rows(date(2026, 8, 3), TODAY)[:40]
    provider = Tradier(monkeypatch, data)
    page = ChartFeed().daily.page("NEW", "1D", int(datetime(2026, 10, 1, 20, tzinfo=ET).timestamp()), today=TODAY)
    assert len(page["bars"]) == 40 and page["exhausted"] and page["older_cursor"] is None
    assert page["history_start"] == data[0]["date"]
    assert all(b["ema200"] is None for b in page["bars"])
    assert [b["ema9"] is not None for b in page["bars"]][:9] == [False] * 8 + [True]
    assert len(provider.history_calls()) == 1


def test_one_series_call_per_symbol_per_new_york_date(tradier):
    feed = ChartFeed()
    for interval, limit in (("1D", 1200), ("1W", 100), ("1D", 50), ("1W", 1200)):
        walk(feed, interval, limit)
    feed.workspace("SPY", ["1D"], [], "regular")
    series = [p for p in tradier.history_calls() if p["start"] == "1970-01-01"]
    assert len(series) == 1
    tradier.data = HISTORY + rows(date(2026, 10, 2), date(2026, 10, 2))
    feed.daily.page("SPY", "1D", int(datetime(2026, 10, 2, 20, tzinfo=ET).timestamp()), today=TODAY + timedelta(days=1))
    assert len([p for p in tradier.history_calls() if p["start"] == "1970-01-01"]) == 2  # a new date reads once more
    feed.daily.page("QQQ", "1D", int(datetime(2026, 10, 1, 20, tzinfo=ET).timestamp()), today=TODAY)
    assert len([p for p in tradier.history_calls() if p["start"] == "1970-01-01"]) == 3  # each symbol has its own


def test_only_eight_symbols_stay_in_memory(tradier):
    feed = ChartFeed()
    for n in range(10):
        feed.daily.page(f"S{n}", "1D", int(datetime(2026, 10, 1, 20, tzinfo=ET).timestamp()), today=TODAY)
    assert len(feed.daily._entries) == 8 and "S0" not in feed.daily._entries and "S9" in feed.daily._entries


@pytest.mark.parametrize("status, code", [(429, "rate_limited"), (401, "access_denied"), (403, "access_denied"), (500, "provider_unavailable")])
def test_provider_failures_are_coded_and_never_exhausted(tradier, status, code):
    tradier.status = status
    with pytest.raises(ChartFeedError) as failure:
        ChartFeed().daily.page("SPY", "1D", int(datetime(2026, 10, 1, 20, tzinfo=ET).timestamp()), today=TODAY)
    assert failure.value.code == code


@pytest.mark.parametrize("body", [b"not json", b"{}", b'{"history": "oops"}', b'{"history": {"day": "oops"}}', b'{"fault": {"faultstring": "x"}}'])
def test_malformed_payloads_are_provider_failures_not_empty_history(tradier, body):
    tradier.body = body
    with pytest.raises(ChartFeedError) as failure:
        ChartFeed().daily.page("SPY", "1W", int(datetime(2026, 10, 1, 20, tzinfo=ET).timestamp()), today=TODAY)
    assert failure.value.code == "provider_unavailable"


def test_a_failed_daily_read_leaves_intraday_panels_loading(tradier, monkeypatch):
    original = tradier.get

    def get(url, params, headers, timeout):
        if url.endswith("/history"):
            return httpx.Response(429, json={}, request=httpx.Request("GET", url))
        return original(url, params, headers, timeout)

    monkeypatch.setattr(feed_module.httpx, "get", get)
    data = ChartFeed().workspace("SPY", ["5m", "1D"], [], "regular")
    assert data["panels"]["5m"]["bars"] and data["panels"]["1D"]["bars"] == []
    assert data["issues"] and data["intraday_as_of"] is not None


@pytest.fixture
def route(monkeypatch):
    provider = Tradier(monkeypatch, guard=False)  # the route test sends unsupported intervals to the real minute validator
    feed = ChartFeed()
    monkeypatch.setattr(charts, "chart_feed", feed)
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as db:
        account = Account(id=UUID(int=1), name="Charts test", type="individual", last4="9876")
        db.add(account)
        db.add(Fill(id=UUID(int=2), account_id=account.id, ticker="SPY", side="buy_to_open", instrument_type="stock",
                    price=100, contracts=1, executed_at=datetime(2026, 9, 29, 10, 0), raw_email_id="daily:1"))
        db.commit()
    app = FastAPI()
    app.include_router(charts.router, prefix="/charts")

    def session():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_session] = session
    with TestClient(app) as client:
        yield client, provider
    engine.dispose()


def test_history_route_serves_daily_and_weekly_with_markers(route):
    client, provider = route
    before = int(datetime(2026, 10, 1, 20, tzinfo=ET).timestamp())
    for interval in ("1D", "1W"):
        response = client.get(f"/charts/history?symbol=SPY&interval={interval}&session=extended&before={before}&limit=1200")
        assert response.status_code == 200
        body = response.json()
        assert body["interval"] == interval and body["before"] == before and body["session"] == "extended"
        assert body["source"] == "tradier" and body["price_basis"] == "split_adjusted" and body["continuation"] is None
        assert body["warmup"] == "ready" and body["issue"] is None and body["history_start"] == "2013-01-02"
        if interval == "1D":
            assert body["exhausted"] is False and body["older_cursor"] == body["bars"][0]["time"] and len(body["bars"]) == 1200
        else:  # thirteen years is under 1,200 weeks: one page reaches the first bar
            assert body["exhausted"] is True and body["older_cursor"] is None and 600 < len(body["bars"]) < 1200
        assert body["fills_truncated"] is False
    daily = client.get(f"/charts/history?symbol=SPY&interval=1D&session=regular&before={before}").json()
    marker_bar = next(b for b in daily["bars"] if datetime.fromtimestamp(b["time"], ET).date() == date(2026, 9, 29))
    assert [m["time"] for m in daily["markers"]] == [marker_bar["time"]]  # the 10:00 fill sits inside 09:30-16:00
    oldest = client.get(f"/charts/history?symbol=SPY&interval=1D&session=regular&before={daily['older_cursor']}&limit=1200").json()
    assert oldest["exhausted"] is False and oldest["bars"][-1]["time"] < daily["bars"][0]["time"]
    assert len([p for p in provider.history_calls() if p["start"] == "1970-01-01"]) == 1


def test_history_route_rejects_unsupported_intervals_and_reports_provider_failures(route):
    client, provider = route
    before = int(datetime(2026, 10, 1, 20, tzinfo=ET).timestamp())
    for interval in ("1M", "2m", "1d"):
        assert client.get(f"/charts/history?symbol=SPY&interval={interval}&session=regular&before={before}").status_code == 422
    provider.status = 429
    response = client.get(f"/charts/history?symbol=QQQ&interval=1D&session=regular&before={before}")
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "rate_limited" and response.json()["detail"]["retry_at"] > before - 10**9
