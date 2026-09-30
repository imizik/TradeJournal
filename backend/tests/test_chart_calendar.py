"""Market calendar: Tradier parsing, bounded caching and honest unavailability."""

from calendar import monthrange
from datetime import date, datetime, time as wall_time

import httpx
import pytest

from app.engine import chart_calendar as module
from app.engine import chart_feed as feed_module
from app.engine.chart_calendar import ChartCalendar, parse_month
from app.engine.chart_feed import ChartFeed, ChartFeedError
from app.engine.chart_math import ET


def tradier_month(year: int, month: int, closed: dict[int, str] | None = None, early: dict[int, str] | None = None) -> dict:
    """The response shape Tradier returned for November 2026 on 2026-09-30."""
    closed, early = closed or {}, early or {}
    days = []
    for number in range(1, monthrange(year, month)[1] + 1):
        day = date(year, month, number)
        if day.weekday() >= 5 or number in closed:
            days.append({"date": day.isoformat(), "status": "closed", "description": closed.get(number, "Market is closed")})
            continue
        end = early.get(number, "16:00")
        post = "16:55" if number in early else "19:55"
        days.append({"date": day.isoformat(), "status": "open",
                     "description": f"Market closes early at {end}" if number in early else "Market is open",
                     "premarket": {"start": "07:00", "end": "09:24"}, "open": {"start": "09:30", "end": end},
                     "postmarket": {"start": end, "end": post}})
    return {"calendar": {"month": month, "year": year, "days": {"day": days}}}


NOVEMBER = tradier_month(2026, 11, closed={26: "Market is closed for Thanksgiving Day"}, early={27: "13:00"})


class Feed:
    def __init__(self, payload=NOVEMBER):
        self.payload, self.calls, self.error = payload, [], None

    def read(self, path, params, ttl):
        self.calls.append((path, dict(params)))
        if self.error:
            raise self.error
        return self.payload, 0.0, None


def on(monkeypatch, day: date):
    class Fixed(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.combine(day, wall_time(10), ET).astimezone(tz)

    monkeypatch.setattr(module, "datetime", Fixed)


def test_holiday_and_early_close_parse_into_new_york_minutes():
    days = parse_month(NOVEMBER, 2026, 11)
    assert days[date(2026, 11, 26)] == {"date": "2026-11-26", "status": "closed", "open": None, "close": None,
                                        "description": "Market is closed for Thanksgiving Day", "source": "tradier"}
    assert (days[date(2026, 11, 27)]["open"], days[date(2026, 11, 27)]["close"]) == (570, 780)
    assert (days[date(2026, 11, 25)]["open"], days[date(2026, 11, 25)]["close"]) == (570, 960)
    assert days[date(2026, 11, 28)]["status"] == "closed"


@pytest.mark.parametrize("damage", [
    lambda rows: rows.pop(),                                         # incomplete month
    lambda rows: rows[2].update(status="halted"),                    # unknown status
    lambda rows: rows[2]["open"].update(end="25:00"),                # impossible time
    lambda rows: rows[2]["open"].update(start="16:00", end="09:30"),  # inverted window
    lambda rows: rows[2].update(date="2026-12-03"),                  # wrong month
    lambda rows: rows[2].pop("open"),                                # open day without hours
])
def test_malformed_or_incomplete_month_is_unavailable(damage):
    payload = tradier_month(2026, 11)
    damage(payload["calendar"]["days"]["day"])
    with pytest.raises(ValueError):
        parse_month(payload, 2026, 11)
    with pytest.raises(ValueError):
        parse_month({"calendar": None}, 2026, 11)


def test_completed_month_is_kept_on_disk_and_costs_nothing_after_restart(tmp_path, monkeypatch):
    on(monkeypatch, date(2026, 12, 2))
    feed = Feed()
    calendar = ChartCalendar(tmp_path, feed)
    assert calendar.hours(date(2026, 11, 27))["close"] == 780
    assert calendar.hours(date(2026, 11, 26))["status"] == "closed"
    assert feed.calls == [("/v1/markets/calendar", {"month": 11, "year": 2026})]
    assert (tmp_path / "2026-11.json").exists()
    restarted = ChartCalendar(tmp_path, Feed())
    restarted.feed.error = ChartFeedError("offline")
    assert restarted.hours(date(2026, 11, 27))["close"] == 780
    assert restarted.feed.calls == []


def test_damaged_disk_copy_is_refetched_and_replaced(tmp_path, monkeypatch):
    on(monkeypatch, date(2026, 12, 2))
    (tmp_path / "2026-11.json").write_text('{"schema": 1, "provider": "tradier", "days": "edited"}')
    feed = Feed()
    assert ChartCalendar(tmp_path, feed).hours(date(2026, 11, 27))["close"] == 780
    assert len(feed.calls) == 1
    assert ChartCalendar(tmp_path, Feed()).hours(date(2026, 11, 27))["close"] == 780


def test_current_month_refreshes_once_per_new_york_date_and_keeps_yesterday_on_failure(tmp_path, monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])
    on(monkeypatch, date(2026, 11, 20))
    feed = Feed()
    calendar = ChartCalendar(tmp_path, feed)
    calendar.hours(date(2026, 11, 20))
    calendar.hours(date(2026, 11, 27))
    assert len(feed.calls) == 1
    assert not (tmp_path / "2026-11.json").exists()  # an unfinished month is never final
    on(monkeypatch, date(2026, 11, 23))
    feed.payload = tradier_month(2026, 11, closed={24: "Market is closed for an announced closure"})
    assert calendar.hours(date(2026, 11, 24))["status"] == "closed"
    assert len(feed.calls) == 2
    on(monkeypatch, date(2026, 11, 24))
    feed.error = ChartFeedError("Tradier could not load these charts.")
    assert calendar.hours(date(2026, 11, 24))["status"] == "closed"  # yesterday's copy
    calendar.hours(date(2026, 11, 24))
    assert len(feed.calls) == 3  # failures back off instead of retrying each call
    clock[0] += module.RETRY_SECONDS + 1
    feed.error = None
    calendar.hours(date(2026, 11, 24))
    assert len(feed.calls) == 4


def test_unavailable_calendar_is_none_and_memory_reads_never_call_the_provider(tmp_path, monkeypatch):
    on(monkeypatch, date(2026, 11, 20))
    feed = Feed()
    feed.error = ChartFeedError("Connect your Tradier account", "not_configured")
    calendar = ChartCalendar(tmp_path, feed)
    assert calendar.cached(date(2026, 11, 20)) is None
    assert feed.calls == []
    assert calendar.hours(date(2026, 11, 20)) is None
    feed.error, feed.payload = None, {"calendar": {"days": {"day": []}}}
    calendar._retry.clear()
    assert calendar.hours(date(2026, 11, 20)) is None  # malformed is unavailable, not "open"
    assert calendar.hours(date(2027, 1, 4)) is None  # unpublished future year: no request
    assert len(feed.calls) == 2
    feed.payload = NOVEMBER
    calendar._retry.clear()
    calendar.hours(date(2026, 11, 20))
    assert calendar.cached(date(2026, 11, 27))["close"] == 780
    assert len(feed.calls) == 3


def test_calendar_requests_share_the_chart_feed_budget(tmp_path, monkeypatch):
    on(monkeypatch, date(2026, 11, 20))
    monkeypatch.setattr(feed_module.tradier, "TRADIER_API_KEY", "test-secret")
    monkeypatch.setattr(feed_module.tradier, "TRADIER_BASE_URL", "https://api.tradier.com")
    requests = []

    def get(url, params, headers, timeout):
        requests.append((url, params))
        return httpx.Response(200, json=NOVEMBER, request=httpx.Request("GET", url))

    monkeypatch.setattr(feed_module.httpx, "get", get)
    feed = ChartFeed()
    calendar = ChartCalendar(tmp_path, feed)
    assert calendar.hours(date(2026, 11, 27))["close"] == 780
    assert requests == [("https://api.tradier.com/v1/markets/calendar", {"month": 11, "year": 2026})]
    assert len(feed._calls) == 1  # counted against the chart's 60/minute Tradier budget
