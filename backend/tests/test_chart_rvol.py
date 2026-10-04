"""Chart relative volume (C2.4): agreement with fill context, the baseline's rules, and its delivery."""

from datetime import date, datetime, timedelta, timezone

import httpx
import pytest

from app.engine import chart_rvol
from app.engine.chart_math import ET, chart_bars
from app.engine.chart_rvol import MINUTES, baseline, candle_rvol, session_profile, window
from app.engine.indicators import compute_rvol_time_adjusted

TODAY = date(2026, 9, 29)  # a Tuesday; the window reaches back across Labor Day (2026-09-07)
LABOR_DAY = date(2026, 9, 7)


def ny(day: date, clock: str) -> datetime:
    return datetime.fromisoformat(f"{day}T{clock}").replace(tzinfo=ET)


def alpaca(day: date, start: str, end: str, seed: int, skip=lambda i: False) -> list[dict]:
    """Alpaca minute bars from start to end New York time, integer volumes that vary by minute and day."""
    at, last, bars, i = ny(day, start), ny(day, end), [], 0
    while at <= last:
        if not skip(i):
            bars.append({"t": at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"), "o": 100.0, "h": 100.5,
                         "l": 99.5, "c": 100.2, "v": 100 + (i * 37 + seed * 11) % 500})
        at += timedelta(minutes=1)
        i += 1
    return bars


def chart(bars: list[dict], source: str = "alpaca_sip") -> list[dict]:
    out = []
    for bar in bars:
        stamp = int(datetime.fromisoformat(bar["t"].replace("Z", "+00:00")).timestamp())
        out.append({"time": stamp, "end_time": stamp + 60, "source": source, "open": bar["o"], "high": bar["h"],
                    "low": bar["l"], "close": bar["c"], "volume": float(bar["v"])})
    return out


def weekdays(start: date, end: date) -> list[date]:
    out, day = [], start
    while day <= end:
        if day.weekday() < 5:
            out.append(day)
        day += timedelta(days=1)
    return out


def open_day(close: int = 960, open_: int = 570) -> dict:
    return {"status": "open", "open": open_, "close": close, "description": "", "source": "tradier"}


CLOSED = {"status": "closed", "open": None, "close": None, "description": "Holiday", "source": "tradier"}


class Calendar:
    def __init__(self, closed=(LABOR_DAY,), unknown=()):
        self.closed, self.unknown = set(closed), set(unknown)

    def hours(self, day: date) -> dict | None:
        if day in self.unknown:
            return None
        return CLOSED if day.weekday() >= 5 or day in self.closed else open_day()


# Two older sessions too, so both sides must pick the same 20.
HISTORY = [d for d in weekdays(date(2026, 8, 27), TODAY - timedelta(days=1)) if d != LABOR_DAY]


def history_bars(day: date) -> list[dict]:
    seed = day.toordinal()
    if day == date(2026, 9, 2):
        return alpaca(day, "04:00", "09:29", seed)  # premarket only: never traded in regular hours
    if day == date(2026, 9, 10):
        return []  # stored empty, as before a listing
    if day == date(2026, 9, 15):
        return alpaca(day, "09:47", "19:59", seed, skip=lambda i: i % 3 == 1)  # starts late, then every third minute missing
    if day == date(2026, 9, 25):
        return alpaca(day, "04:00", "12:59", seed)  # stops at 13:00, as a half day does
    return alpaca(day, "04:00", "19:59", seed)


TODAY_BARS = alpaca(TODAY, "04:00", "11:00", 3, skip=lambda i: i in (377, 378))  # no 10:17 or 10:18 bar


def test_every_candle_matches_fill_context_rvol_on_the_same_bars():
    days = window(TODAY, Calendar().hours)
    assert days == HISTORY[-20:] and LABOR_DAY not in days
    found = baseline([(day, session_profile(chart(history_bars(day)))) for day in days])
    assert len(found.sessions) == 20 and date(2026, 9, 2) not in found.traded and date(2026, 9, 10) not in found.traded
    assert len(found.traded) == 18

    # What fill enrichment computes for a fill at a moment (alpaca_enricher._build_context).
    daily = [{"t": f"{day}T04:00:00Z", "v": 1e6} for day in HISTORY]
    loader = {**{day: history_bars(day) for day in HISTORY}, TODAY: TODAY_BARS}

    def fill_context(at: datetime):
        return compute_rvol_time_adjusted("TEST", TODAY, at.replace(tzinfo=None), daily, lambda _ticker, day: loader.get(day, []))

    minutes = chart(TODAY_BARS, "tradier")
    calendar = {TODAY: open_day()}
    last_minute = 11 * 60
    checked = 0
    for interval, width in (("1m", 1), ("5m", 5), ("1h", 60)):
        bars = chart_bars(minutes, [], interval, "extended", calendar)
        values = candle_rvol(bars, found.average, TODAY, last_minute)
        for bar, value in zip(bars, values):
            start = datetime.fromtimestamp(bar["time"], ET)
            if bar["extended"]:
                assert value is None
                continue
            # Through the candle's last minute; the forming candle ends at the newest minute.
            through = min(start + timedelta(minutes=width), ny(TODAY, "11:01"))
            assert value == fill_context(through), (interval, start)
            checked += value is not None
    assert checked == 89 + 19 + 2  # 09:30-11:00 less the two missing minutes, its nineteen 5m candles, and two hours


def test_a_session_counts_toward_a_minute_only_once_it_has_traded_by_then():
    late = session_profile(chart(alpaca(TODAY, "09:47", "10:00", 1)))
    assert late[:17] == (None,) * 17 and late[17] == 100 + (11 % 500)
    # Premarket and postmarket volume never count; the last minute is 15:59.
    profile = session_profile(chart(alpaca(TODAY, "04:00", "19:59", 1)))
    assert len(profile) == MINUTES and profile[0] == 100 + (330 * 37 + 11) % 500 and profile[-1] == sum(100 + (i * 37 + 11) % 500 for i in range(330, 720))


def test_a_minute_needs_five_sessions_that_had_traded_by_then():
    early = [(date(2026, 9, d), session_profile(chart(alpaca(date(2026, 9, d), "09:30", "15:59", d)))) for d in (21, 22, 23, 24)]
    late = [(date(2026, 9, 25), session_profile(chart(alpaca(date(2026, 9, 25), "10:00", "15:59", 25))))]
    found = baseline(early + late)
    assert found.average[:30] == (None,) * 30  # only four sessions traded before 10:00
    assert found.average[30] == pytest.approx(sum(p[30] for _, p in early + late) / 5)
    assert found.traded == tuple(date(2026, 9, d) for d in (21, 22, 23, 24, 25))


def test_the_window_is_the_calendars_twenty_sessions_and_needs_the_calendar():
    days = window(date(2026, 9, 8), Calendar().hours)  # the day after Labor Day
    assert len(days) == 20 and days[-1] == date(2026, 9, 4) and days[0] == date(2026, 8, 10)
    # Saturday's window is Monday's: nothing trades in between.
    assert window(date(2026, 9, 26), Calendar().hours) == window(date(2026, 9, 28), Calendar().hours)
    assert window(TODAY, Calendar(unknown={date(2026, 9, 14)}).hours) is None


def test_only_todays_regular_candles_have_rvol_and_a_zero_baseline_has_none():
    average = tuple([1000.0] * MINUTES)
    bars = [
        {"time": int(ny(TODAY - timedelta(days=1), "15:59").timestamp()), "end_time": int(ny(TODAY - timedelta(days=1), "16:00").timestamp()), "volume": 9.0, "extended": False},
        {"time": int(ny(TODAY, "09:00").timestamp()), "end_time": int(ny(TODAY, "09:30").timestamp()), "volume": 400.0, "extended": True},
        {"time": int(ny(TODAY, "09:30").timestamp()), "end_time": int(ny(TODAY, "10:00").timestamp()), "volume": 500.0, "extended": False},
        {"time": int(ny(TODAY, "10:00").timestamp()), "end_time": int(ny(TODAY, "10:30").timestamp()), "volume": 700.0, "extended": False},
    ]
    assert candle_rvol(bars, average, TODAY, None) == [None, None, 0.5, 1.2]
    # A candle still forming at 10:07 is read against the baseline through 10:07.
    rising = tuple(float(10 * (i + 1)) for i in range(MINUTES))
    assert candle_rvol(bars, rising, TODAY, 10 * 60 + 7)[3] == round(1200 / rising[37], 4)
    assert candle_rvol(bars, tuple([0.0] * MINUTES), TODAY, None) == [None] * 4


# ---------------------------------------------------------------------------
# The workspace carries each candle's RVol and what the baseline covers
# ---------------------------------------------------------------------------

NOW = ny(TODAY, "10:02")


@pytest.fixture
def feed(monkeypatch):
    from app.engine import chart_feed as feed_module
    from app.engine.chart_feed import ChartFeed

    class Fixed(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz)

    monkeypatch.setattr(feed_module, "datetime", Fixed)
    monkeypatch.setattr(feed_module.time, "time", lambda: NOW.timestamp())
    monkeypatch.setattr(feed_module.tradier, "TRADIER_API_KEY", "test-secret")
    monkeypatch.setattr(feed_module.tradier, "TRADIER_BASE_URL", "https://api.tradier.com")
    today_rows = [{"timestamp": int(ny(TODAY, clock).timestamp()), "open": 100, "high": 101, "low": 99, "close": 100, "volume": volume}
                  for clock, volume in [("08:00", 50), ("09:30", 300), ("09:31", 100), ("09:45", 200), ("10:01", 400)]]

    def get(url, params, headers, timeout):
        if "timesales" in url:
            payload = {"series": {"data": today_rows}}
        elif "history" in url:
            payload = {"history": {"day": [{"date": d.isoformat(), "open": 99, "high": 101, "low": 97, "close": 100, "volume": 1e6}
                                           for d in weekdays(date(2026, 6, 1), TODAY) if params["start"] <= d.isoformat() <= params["end"]]}}
        else:
            payload = {"quotes": {"quote": []}}
        return httpx.Response(200, json=payload, request=httpx.Request("GET", url))

    monkeypatch.setattr(feed_module.httpx, "get", get)
    return ChartFeed()


def flat(per_minute: float, traded: bool = True) -> chart_rvol.Profile:
    return tuple(per_minute * (i + 1) for i in range(MINUTES)) if traded else (None,) * MINUTES


def test_the_workspace_sends_each_candles_rvol_and_the_sessions_its_baseline_covers(feed):
    asked = []

    def profile(symbol, day):
        asked.append((symbol, day))
        return flat(100.0)

    data = feed.workspace("SPY", ["1m", "5m", "1D"], [], "extended", calendar=Calendar(), volume_profile=profile)
    days = window(TODAY, Calendar().hours)
    assert sorted(day for _, day in asked) == days and {symbol for symbol, _ in asked} == {"SPY"}
    assert data["rvol"] == {"state": "ready", "day": "2026-09-29", "sessions": [d.isoformat() for d in days], "traded": 20, "missing": [], "message": None}
    one = {datetime.fromtimestamp(b["time"], ET).strftime("%H:%M"): b["rvol"] for b in data["panels"]["1m"]["bars"]}
    # 09:30: 300 against 100; 09:31: 400 against 200; 09:45: 600 against 1,600; 10:01: 1,000 against 3,200.
    assert one == {"08:00": None, "09:30": 3.0, "09:31": 2.0, "09:45": 0.375, "10:01": 0.3125}
    five = {datetime.fromtimestamp(b["time"], ET).strftime("%H:%M"): b["rvol"] for b in data["panels"]["5m"]["bars"]}
    # The 10:00 candle is still forming: through 10:01, the newest minute.
    assert five == {"08:00": None, "09:30": 400 / 500, "09:45": 600 / 2000, "10:00": 0.3125}
    assert all("rvol" not in bar for bar in data["panels"]["1D"]["bars"])


def test_a_session_not_stored_yet_means_no_baseline_and_says_so(feed):
    missing = date(2026, 9, 14)
    data = feed.workspace("SPY", ["5m"], [], "extended", calendar=Calendar(),
                          volume_profile=lambda _symbol, day: None if day == missing else flat(100.0))
    rvol = data["rvol"]
    assert (rvol["state"], rvol["missing"], len(rvol["sessions"])) == ("building", ["2026-09-14"], 20)
    assert "1 not stored yet" in rvol["message"]
    assert [bar["rvol"] for bar in data["panels"]["5m"]["bars"]] == [None] * 4


def test_sessions_that_never_traded_stay_in_the_window_and_too_few_traders_is_said(feed):
    traded = set(window(TODAY, Calendar().hours)[-4:])
    data = feed.workspace("SPY", ["5m"], [], "extended", calendar=Calendar(),
                          volume_profile=lambda _symbol, day: flat(100.0, day in traded))
    assert (data["rvol"]["state"], data["rvol"]["traded"]) == ("insufficient", 4)
    assert "Only 4 of the 20 sessions" in data["rvol"]["message"]


def test_a_split_inside_the_window_scales_the_older_sessions_to_todays_basis(feed):
    feed.splits = type("Splits", (), {"get": lambda self, symbol: {"status": "ok", "splits": [{"ex_date": "2026-09-21", "ratio": 2.0}],
                                                                   "as_of": 1, "issue": None}})()
    before = {d for d in window(TODAY, Calendar().hours) if d < date(2026, 9, 21)}
    # Raw stored volume halves the split's way before it; on today's basis every session reads 100 a minute.
    data = feed.workspace("SPY", ["1m"], [], "extended", calendar=Calendar(),
                          volume_profile=lambda _symbol, day: flat(50.0 if day in before else 100.0))
    assert len(before) == 14 and data["panels"]["1m"]["bars"][1]["rvol"] == 3.0


def test_no_session_today_sends_nothing_and_no_calendar_says_why(feed):
    data = feed.workspace("SPY", ["5m"], [], "extended", calendar=Calendar(closed={LABOR_DAY, TODAY}), volume_profile=lambda *_: flat(1.0))
    assert data["rvol"] is None and all("rvol" not in bar for bar in data["panels"]["5m"]["bars"])
    data = feed.workspace("SPY", ["5m"], [], "extended", calendar=None, volume_profile=lambda *_: flat(1.0))
    assert data["rvol"]["state"] == "unavailable" and "calendar is unavailable" in data["rvol"]["message"]
    late = type("Late", (Calendar,), {"hours": lambda self, day: open_day(open_=630) if day == TODAY else Calendar.hours(self, day)})()
    data = feed.workspace("SPY", ["5m"], [], "extended", calendar=late, volume_profile=lambda *_: flat(1.0))
    assert data["rvol"]["state"] == "unavailable" and "9:30" in data["rvol"]["message"]
    # Without the hook (history pages, older callers) nothing about RVol is sent.
    assert "rvol" not in feed.workspace("SPY", ["5m"], [], "extended", calendar=Calendar())


# ---------------------------------------------------------------------------
# The history store's hooks: a stored session's profile, and one session for the job
# ---------------------------------------------------------------------------

def test_a_stored_sessions_profile_is_read_from_disk_once(tmp_path, monkeypatch):
    from app.engine.chart_history import ChartHistory

    history = ChartHistory(tmp_path)
    day = date(2026, 9, 28)
    history._publish("SPY", day, chart(alpaca(day, "09:30", "09:31", 1)))
    reads = []
    real = history.stored
    monkeypatch.setattr(history, "stored", lambda symbol, d: reads.append(d) or real(symbol, d))
    first = history.volume_profile("SPY", day)
    assert first[:2] == (111.0, 111.0 + 148) and first[-1] == 259.0
    assert history.volume_profile("SPY", day) is first and reads == [day]
    assert history.volume_profile("SPY", date(2026, 9, 25)) is None and history.volume_profile("BAD SYMBOL", day) is None


def test_the_job_fetches_one_session_once_through_the_chart_budget(tmp_path, monkeypatch):
    from app.engine import alpaca as credentials
    from app.engine import chart_history as module
    from app.engine.chart_history import ChartHistory

    monkeypatch.setattr(credentials, "ALPACA_API_KEY", "fixture-key")
    monkeypatch.setattr(credentials, "ALPACA_API_SECRET", "fixture-secret")
    day = date(2026, 9, 28)
    calls = []

    def get(url, params, headers, timeout):
        calls.append(params)
        return httpx.Response(200, json={"bars": alpaca_day, "next_page_token": None}, request=httpx.Request("GET", url))

    alpaca_day = alpaca(day, "09:30", "09:31", 1)
    monkeypatch.setattr(module.httpx, "get", get)
    history = ChartHistory(tmp_path)
    assert [b["volume"] for b in history.session("SPY", day)] == [111.0, 148.0]
    assert history.session("SPY", day) == history.stored("SPY", day)
    assert len(calls) == 1 and (calls[0]["feed"], calls[0]["adjustment"]) == ("sip", "raw")
    with pytest.raises(module.HistoryError) as refused:
        history.session("../SPY", day)
    assert refused.value.code == "invalid_request"
