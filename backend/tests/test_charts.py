"""Chart data integrity, request sharing, and private journal marker boundaries."""

from datetime import date, datetime, timezone
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.database import get_session
from app.engine import chart_feed as feed_module
from app.engine.chart_feed import ChartFeed, ChartFeedError
from app.engine.chart_math import CLOCK_NOTE, ET, chart_bars, indicators, market_day, normalize_bars, session_part
from app.models import Account, Fill
from app.routers import charts


def minute(at, close=100, volume=10):
    stamp = int(datetime.fromisoformat(at).replace(tzinfo=ET).timestamp())
    return {"time": stamp, "end_time": stamp + 60, "open": close, "high": close + 1, "low": close - 1, "close": close, "volume": volume}


@pytest.mark.parametrize("date,utc_hour", [("2026-07-06", 13), ("2026-11-02", 14)])
def test_hour_buckets_obey_new_york_dst_and_do_not_mix_sessions(date, utc_hour):
    raw = [minute(f"{date}T{t}", p) for t, p in [("09:29", 80), ("09:30", 100), ("10:29", 110), ("10:30", 120), ("16:00", 130)]]
    regular = chart_bars(raw, [], "1h", "regular")
    extended = chart_bars(raw, [], "1h", "extended")
    assert len(regular) == 2
    assert regular[0]["open"] == 100
    assert regular[0]["close"] == 110
    assert regular[0]["volume"] == 20
    assert datetime.fromtimestamp(regular[0]["time"], timezone.utc).hour == utc_hour
    assert [b for b in extended if not b["extended"]][0]["open"] == 100
    assert len(extended) == 4


def test_vwap_is_minute_weighted_and_resets_at_regular_open():
    raw = [minute("2026-09-28T09:00", 10, 10000), minute("2026-09-28T09:30", 100, 10),
           minute("2026-09-28T09:31", 110, 30), minute("2026-09-28T16:01", 900, 10000),
           minute("2026-09-29T09:30", 200, 1)]
    one = chart_bars(raw, [], "1m", "extended")
    five = chart_bars(raw, [], "5m", "extended")
    assert one[0]["vwap"] is None
    assert one[2]["vwap"] == pytest.approx(107.5)
    assert five[1]["vwap"] == one[2]["vwap"]
    assert one[3]["vwap"] is None
    assert one[4]["vwap"] == 200


def test_wilder_rsi_matches_published_reference_sequence_and_warmup_is_null():
    closes = [44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08, 45.89, 46.03, 45.61, 46.28, 46.28, 46.00, 46.03]
    out = indicators([{"close": close} for close in closes])
    assert all(b["rsi"] is None for b in out[:14])
    assert out[14]["rsi"] == pytest.approx(70.464135, abs=0.000001)
    assert out[15]["rsi"] == pytest.approx(66.249619, abs=0.000001)
    assert out[16]["rsi"] == pytest.approx(66.480942, abs=0.000001)
    assert all(b["ema20"] is None for b in out)
    assert indicators([{"close": 100}] * 16)[-1]["rsi"] == 50


def test_normalization_rejects_bad_prices_and_deduplicates_updated_candle():
    first = {"timestamp": 1790693820, "open": 100, "high": 102, "low": 99, "close": 101, "volume": 10}
    out = normalize_bars([first, {**first, "close": 102}, {**first, "timestamp": 10, "high": 90},
                          {**first, "timestamp": 20, "close": "nan"}, {**first, "timestamp": 30, "volume": -1}])
    assert len(out) == 1 and out[0]["close"] == 102


def test_daily_and_weekly_keep_provider_daily_ohlc_and_do_not_use_extended_minutes():
    daily = normalize_bars([{"date": "2026-09-28", "open": 100, "high": 120, "low": 90, "close": 110, "volume": 10},
                            {"date": "2026-09-29", "open": 110, "high": 130, "low": 100, "close": 125, "volume": 20}], daily=True)
    assert chart_bars([minute("2026-09-29T17:00", 999)], daily, "1D", "extended")[-1]["close"] == 125
    week = chart_bars([], daily, "1W", "extended")[0]
    assert (week["open"], week["high"], week["low"], week["close"], week["volume"]) == (100, 130, 90, 125, 30)
    assert week["vwap"] is None


HALF_DAY = date(2025, 11, 28)  # Tradier: "Market closes early at 13:00"
HALF_HOURS = {"date": "2025-11-28", "status": "open", "open": 570, "close": 780, "description": "Market closes early at 13:00", "source": "tradier"}


def test_older_half_day_ends_regular_session_vwap_and_buckets_at_13_00():
    raw = [minute(f"2025-11-28T{t}", p, v) for t, p, v in [("09:30", 100, 10), ("12:59", 110, 30), ("13:00", 120, 1000),
                                                          ("16:59", 130, 5), ("17:00", 140, 5)]]
    calendar = {HALF_DAY: HALF_HOURS}
    regular = chart_bars(raw, [], "1h", "regular", calendar)
    assert [datetime.fromtimestamp(b["time"], ET).strftime("%H:%M") for b in regular] == ["09:30", "12:30"]
    assert datetime.fromtimestamp(regular[-1]["end_time"], ET).strftime("%H:%M") == "13:00"
    assert regular[-1]["close"] == 110 and regular[-1]["vwap"] == pytest.approx((100 * 10 + 110 * 30) / 40)
    extended = chart_bars(raw, [], "1h", "extended", calendar)
    post = [b for b in extended if b["extended"]]
    # The 13:00 closing print is postmarket; trading ends four hours after the close.
    assert [datetime.fromtimestamp(b["time"], ET).strftime("%H:%M") for b in post] == ["13:00", "16:00"]
    assert datetime.fromtimestamp(post[-1]["end_time"], ET).strftime("%H:%M") == "17:00"
    assert all(b["vwap"] is None for b in post) and 140 not in [b["close"] for b in extended]
    # Without the calendar the clock rule would call 13:00-15:59 regular trading.
    assert chart_bars(raw, [], "1h", "regular")[-1]["close"] == 120


def test_calendar_classifies_regular_extended_and_closed_days():
    def at(clock):
        return datetime.fromisoformat(f"2025-11-28T{clock}").replace(tzinfo=ET)

    assert session_part(at("04:00"), HALF_HOURS) == ("pre", 240, 570)
    assert session_part(at("12:59"), HALF_HOURS) == ("regular", 570, 780)
    assert session_part(at("13:00"), HALF_HOURS) == ("post", 780, 1020)
    assert session_part(at("17:00"), HALF_HOURS) is None
    assert session_part(at("13:00")) == ("regular", 570, 960)
    holiday = {"date": "2025-11-27", "status": "closed", "open": None, "close": None, "description": "Thanksgiving", "source": "tradier"}
    thursday = [minute("2025-11-27T10:00")]
    assert chart_bars(thursday, [], "5m", "extended", {date(2025, 11, 27): holiday}) == []
    assert session_part(datetime(2025, 11, 27, 10, tzinfo=ET), holiday) is None


def test_market_day_sends_the_same_windows_to_the_browser():
    half = market_day(HALF_DAY, HALF_HOURS)
    def stamp(clock):
        return int(datetime.fromisoformat(f"2025-11-28T{clock}").replace(tzinfo=ET).timestamp())

    assert half["sessions"] == [{"part": "pre", "start": stamp("04:00"), "end": stamp("09:30")},
                                {"part": "regular", "start": stamp("09:30"), "end": stamp("13:00")},
                                {"part": "post", "start": stamp("13:00"), "end": stamp("17:00")}]
    assert (half["status"], half["source"], half["note"]) == ("open", "tradier", None)
    closed = market_day(date(2025, 11, 27), {"status": "closed", "open": None, "close": None, "description": "Market is closed for Thanksgiving Day", "source": "tradier"})
    assert closed["sessions"] == [] and closed["description"] == "Market is closed for Thanksgiving Day"
    unknown = market_day(date(2025, 11, 27), None)
    assert unknown["status"] == "unknown" and unknown["note"] == CLOCK_NOTE and len(unknown["sessions"]) == 3


@pytest.fixture
def provider(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(feed_module.time, "time", lambda: clock[0])
    monkeypatch.setattr(feed_module.tradier, "TRADIER_API_KEY", "test-secret")
    monkeypatch.setattr(feed_module.tradier, "TRADIER_BASE_URL", "https://api.tradier.com")
    calls = []
    status = [200]
    today = datetime.now(ET).date().isoformat()

    def get(url, params, headers, timeout):
        calls.append((url, params))
        assert headers["Authorization"] == "Bearer test-secret"
        if "timesales" in url:
            candle = minute(f"{today}T09:30")
            payload = {"series": {"data": {**candle, "timestamp": candle["time"]}}}
        elif "history" in url:
            payload = {"history": {"day": {"date": today, "open": 100, "high": 101, "low": 99, "close": 100, "volume": 100}}}
        else:
            payload = {"quotes": {"quote": {"symbol": "SPY", "last": 100, "trade_date": 1000000}}}
        return httpx.Response(status[0], json=payload, request=httpx.Request("GET", url))

    monkeypatch.setattr(feed_module.httpx, "get", get)
    return ChartFeed(), calls, clock, status


def test_five_panels_share_history_and_poll_only_recent_data(provider):
    feed, calls, clock, _ = provider
    frames = ["1m", "5m", "15m", "1h", "1D"]
    feed.workspace("SPY", frames, ["QQQ", "SPY"], "extended")
    assert len(calls) == 3
    feed.workspace("SPY", frames, ["SPY", "QQQ"], "regular")
    assert len(calls) == 3  # today, daily and quotes; completed minutes use SIP history
    clock[0] += 16
    feed.workspace("SPY", frames, ["SPY", "QQQ"], "regular")
    assert len(calls) == 5  # current minute history + one batch of quotes
    clock[0] += 60
    feed.workspace("SPY", frames, ["SPY", "QQQ"], "regular")
    assert len(calls) == 8  # daily history now due; no Tradier historical request


def test_workspace_uses_todays_calendar_and_discloses_when_it_is_missing(provider):
    feed, calls, _, _ = provider
    today = datetime.now(ET).date()

    class Calendar:
        def hours(self, day):
            assert day == today
            return {"date": today.isoformat(), "status": "open", "open": 570, "close": 780, "description": "Market closes early at 13:00", "source": "tradier"}

    data = feed.workspace("SPY", ["5m"], [], "regular", calendar=Calendar())
    regular = [s for s in data["market"]["sessions"] if s["part"] == "regular"][0]
    assert datetime.fromtimestamp(regular["end"], ET).strftime("%H:%M") == "13:00"
    assert data["market"]["note"] is None
    assert data["panels"]["5m"]["bars"][0]["extended"] is False
    missing = feed.workspace("SPY", ["5m"], [], "regular")
    assert missing["market"]["status"] == "unknown" and missing["market"]["note"] == CLOCK_NOTE
    assert "issues" in missing and not missing["issues"]  # disclosed, not reported as stale data


def test_provider_failure_retains_previous_data_with_original_timestamp(provider):
    feed, calls, clock, status = provider
    path, params = "/v1/markets/quotes", {"symbols": "SPY"}
    original, stamp, issue = feed.read(path, params, 15)
    clock[0] += 16
    status[0] = 429
    result, retained_stamp, issue = feed.read(path, params, 15)
    assert result == original and retained_stamp == stamp
    assert "allowance" in issue
    feed.read(path, params, 15)
    assert len(calls) == 2
    with pytest.raises(ChartFeedError, match="cooling down"):
        feed.read(path, {"symbols": "AAPL"}, 15)
    clock[0] += 59
    feed.read(path, params, 15)
    clock[0] += 2
    status[0] = 200
    feed.read(path, params, 15)
    assert len(calls) == 3  # cooldown reads cannot extend the original deadline


def test_chart_budget_bounds_rapid_symbol_changes_and_recovers(provider):
    feed, calls, clock, _ = provider
    for index in range(60):
        feed.read("/v1/markets/quotes", {"symbols": f"S{index}"}, 15)
    with pytest.raises(ChartFeedError) as exc:
        feed.read("/v1/markets/quotes", {"symbols": "NEXT"}, 15)
    assert exc.value.code == "rate_limited"
    assert len(calls) == 60
    clock[0] += 61
    feed.read("/v1/markets/quotes", {"symbols": "NEXT"}, 15)
    assert len(calls) == 61


def test_missing_key_and_denied_access_do_not_fall_back_to_other_feeds(provider, monkeypatch):
    feed, calls, _, status = provider
    monkeypatch.setattr(feed_module.tradier, "TRADIER_API_KEY", "")
    with pytest.raises(ChartFeedError) as exc:
        feed.workspace("SPY", ["1m"], [], "regular")
    assert exc.value.code == "not_configured" and not calls
    monkeypatch.setattr(feed_module.tradier, "TRADIER_API_KEY", "test-secret")
    status[0] = 403
    with pytest.raises(ChartFeedError, match="refused"):
        feed.workspace("SPY", ["1m"], [], "regular")
    assert len(calls) == 1


@pytest.fixture
def route_client(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as db:
        account = Account(id=UUID(int=1), name="Charts test", type="individual", last4="9876")
        db.add(account)
        for i, when in enumerate(("2026-09-29T09:20", "2026-09-29T09:32", "2026-09-29T10:01"), start=1):
            db.add(Fill(id=UUID(int=10 + i), account_id=account.id, ticker="SPY", side="buy_to_open", instrument_type="option",
                        option_type="put", price=250, contracts=1, executed_at=datetime.fromisoformat(when), raw_email_id=f"charts:{i}"))
        db.commit()
    app = FastAPI()
    app.include_router(charts.router, prefix="/charts")

    def session():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_session] = session

    def fake_workspace(*_, **__):
        return {"panels": {"5m": {"bars": chart_bars([minute("2026-09-29T09:30"), minute("2026-09-29T10:00")], [], "5m", "regular"), "markers": []}}}

    monkeypatch.setattr(charts.chart_feed, "workspace", fake_workspace)
    with TestClient(app) as client:
        yield client
    engine.dispose()


def test_fill_markers_use_new_york_time_and_preserve_option_identity(route_client):
    response = route_client.get("/charts/workspace?symbol=SPY&intervals=5m&session=regular")
    assert response.status_code == 200
    data = response.json()
    assert len(data["fills"]) == 2  # the 9:20 fill is outside the visible session
    markers = data["panels"]["5m"]["markers"]
    assert len(markers) == 2
    assert markers[0]["time"] == minute("2026-09-29T09:30")["time"]
    assert "put" in markers[0]["label"] and "price" not in markers[0]


def test_history_route_identifies_window_and_returns_bounded_old_markers(route_client, monkeypatch):
    bars = chart_bars([minute("2026-09-29T09:30"), minute("2026-09-29T10:00")], [], "5m", "regular")
    before = bars[-1]["end_time"] + 1
    monkeypatch.setattr(charts.chart_history, "page", lambda symbol, interval, session, cursor, limit, continuation: {
        "symbol": symbol, "interval": interval, "session": session, "before": cursor, "limit": limit,
        "bars": bars, "older_cursor": bars[0]["time"], "exhausted": False, "continuation": None,
        "warmup": "ready", "source": "alpaca_sip", "price_basis": "raw", "issue": None,
    })
    response = route_client.get(f"/charts/history?symbol=SPY&interval=5m&session=regular&before={before}")
    assert response.status_code == 200
    result = response.json()
    assert result["before"] == before and result["older_cursor"] == bars[0]["time"]
    assert [m["id"] for m in result["markers"]] == ["00000000-0000-0000-0000-00000000000c", "00000000-0000-0000-0000-00000000000d"]
    assert route_client.get(f"/charts/history?symbol=SPY&interval=5m&session=regular&before={before}&limit=1201").status_code == 422


@pytest.mark.parametrize("query", ["symbol=../../secret", "intervals=1s", "session=overnight", "intervals=", "watchlist=" + ",".join(f"S{i}" for i in range(31))])
def test_route_rejects_unsupported_requests(route_client, query):
    assert route_client.get(f"/charts/workspace?{query}").status_code == 422
