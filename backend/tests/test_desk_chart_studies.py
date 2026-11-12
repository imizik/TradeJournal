"""The desk chart's studies (docs/copilot-lab.md § The desk): VWAP, EMA 9/21, SMA 50/200 and RVol on the cockpit's chart
read agree with the Charts workspace's own math for the same symbol and timeframe, are warmed on the candles before the
first one shown, and a series with nothing behind it is None rather than a flat line. No network: the chart feed's and
the chart history's reads are replaced by what they return, built with the workspace's own resampling (``chart_bars``)."""

from datetime import date, datetime, time as wall_time, timedelta
import math

import pandas as pd

from app.engine import chart_math, desk_context
from app.engine.chart_math import ET, chart_bars, indicators
from app.engine.indicators import _ema, _sma

TODAY = date(2026, 10, 21)  # a Wednesday
EARLIER = [date(2026, 10, d) for d in (12, 13, 14, 15, 16, 19, 20)]  # the seven sessions before it
NOW = datetime.combine(TODAY, wall_time(14, 49), ET).timestamp()


def session(day: date, end: float | None = None) -> list[dict]:
    """One day's raw minutes, 04:00 to 20:00 New York, with prices that wander and differ by day."""
    start = datetime.combine(day, wall_time(4), ET).timestamp()
    out = []
    for i in range(16 * 60):
        stamp = int(start + 60 * i)
        if end is not None and stamp > end:
            break
        k = day.toordinal() * 960 + i
        close = 100 + 2 * math.sin(k / 37) + 0.5 * math.sin(k / 7) + (day.toordinal() % 5) * 0.3
        out.append({"time": stamp, "open": close - 0.03, "high": close + 0.06, "low": close - 0.07, "close": close,
                    "volume": 1000 + (k % 13) * 50})
    return out


RAW = {day: session(day) for day in EARLIER}
RAW_TODAY = session(TODAY, NOW)


def fifteen(day: date, raw: list[dict]) -> list[dict]:
    return chart_bars(raw, [], "15m", "regular", {day: None})


def install(monkeypatch, stored: bool = True, today: list[dict] | None = None):
    """The desk's sources as the chart feed and the chart history return them."""
    raw_today = RAW_TODAY if today is None else today
    minutes = [{**b, "rvol": None if b["extended"] else 1.25} for b in chart_bars(raw_today, [], "1m", "extended", {TODAY: None})]
    monkeypatch.setattr(desk_context, "today_minutes", lambda symbol: minutes)
    # fifteen_bars: the two sessions before today from the history, today's from the feed (RVol on today's candles).
    monkeypatch.setattr(desk_context, "fifteen_bars", lambda symbol: [b for day in EARLIER[-2:] for b in fifteen(day, RAW[day])]
                        + [{**b, "rvol": 1.25} for b in fifteen(TODAY, raw_today)])

    def stored_sessions(symbol, before, count):
        days = [d for d in EARLIER if d < before][-count:] if stored else []
        return [(d, None, RAW[d]) for d in days]
    monkeypatch.setattr(desk_context, "stored_sessions", stored_sessions)
    return minutes


def workspace_fifteen() -> list[dict]:
    """What the workspace's 15m chart computes for these candles: each session resampled on its own, then the
    averages over all of them (a history page's indicators, warmed on everything before)."""
    return indicators([b for day in EARLIER for b in fifteen(day, RAW[day])] + fifteen(TODAY, RAW_TODAY))


def test_the_averages_are_the_workspace_ema_for_any_length_and_a_plain_simple_average():
    bars = workspace_fifteen()
    closes = [b["close"] for b in bars]
    assert chart_math.ema(closes, 9) == [b["ema9"] for b in bars]  # the same numbers, bit for bit
    assert chart_math.ema(closes, 20) == [b["ema20"] for b in bars]
    series = pd.Series(closes)
    for length in (21, 50):
        assert all(a is None and math.isnan(b) or abs(a - b) < 1e-9
                   for a, b in zip(chart_math.ema(closes, length)[length - 1:], _ema(series, length)[length - 1:]))
        assert all((a is None) == math.isnan(b) and (a is None or abs(a - b) < 1e-9)
                   for a, b in zip(chart_math.sma(closes, length), _sma(series, length)))


def test_fifteen_minute_studies_agree_with_the_workspace_from_the_first_candle(monkeypatch):
    install(monkeypatch)
    read = desk_context._desk_read("NBIS", "15m", NOW)
    shown, studies = read["bars"], read["studies"]
    assert {datetime.fromtimestamp(b["time"], ET).date() for b in shown} == {*EARLIER[-2:], TODAY}
    expected = {b["time"]: b for b in workspace_fifteen()}
    closes = pd.Series([b["close"] for b in workspace_fifteen()])
    ema21 = dict(zip([b["time"] for b in workspace_fifteen()], _ema(closes, 21)))
    for i, bar in enumerate(shown):
        want = expected[bar["time"]]
        assert bar["close"] == want["close"]
        # To the chart's displayed precision (cents), from the very first candle shown.
        assert abs(studies["ema9"][i] - want["ema9"]) < 0.005
        assert abs(studies["ema21"][i] - ema21[bar["time"]]) < 0.005
        assert studies["vwap"][i] == round(want["vwap"], 4)
    # RVol only on today's candles; the earlier sessions show none rather than a made-up one.
    assert {datetime.fromtimestamp(b["time"], ET).date() for b, v in zip(shown, studies["rvol"]) if v is not None} == {TODAY}
    assert set(studies) == {"ema9", "ema21", "vwap", "rvol"}


def test_two_minute_vwap_is_the_workspace_minute_vwap_and_the_averages_carry_over_from_the_session_before(monkeypatch):
    minutes = install(monkeypatch)
    read = desk_context._desk_read("NBIS", "2m", NOW)
    shown, studies = read["bars"], read["studies"]
    by_minute = {m["time"]: m for m in minutes}
    for bar, vwap in zip(shown, studies["vwap"]):
        last = by_minute.get(bar["time"] + 60) or by_minute[bar["time"]]  # the candle's last minute
        assert vwap == (None if last["vwap"] is None else round(last["vwap"], 4))
    assert studies["vwap"][0] is None and shown[0]["extended"]  # 04:00: VWAP is a regular-session study
    # The EMAs run through yesterday's whole day of 2-minute candles first: a value from the first candle, and the same
    # numbers as one run over both days.
    warm = desk_context._two_minute(chart_bars(RAW[EARLIER[-1]], [], "1m", "extended", {EARLIER[-1]: None}))
    closes = pd.Series([b["close"] for b in warm] + [b["close"] for b in shown])
    for name, length in (("ema9", 9), ("ema21", 21)):
        full = list(_ema(closes, length))[len(warm):]
        assert studies[name][0] is not None
        assert all(abs(a - b) < 1e-3 for a, b in zip(studies[name], full))


def test_without_stored_history_the_averages_start_empty_and_nothing_is_drawn_for_the_previous_close(monkeypatch):
    install(monkeypatch, stored=False)
    read = desk_context._desk_read("NBIS", "2m", NOW)
    studies = read["studies"]
    assert studies["ema9"][:8] == [None] * 8 and studies["ema9"][8] is not None  # no flat line from a made-up start
    assert studies["ema21"][:20] == [None] * 20
    assert read["reading"]["prev_close"] is None
    assert [line["key"] for line in read["reference"]] == ["pm_high", "pm_low"]


def test_the_reading_line_and_the_reference_lines(monkeypatch):
    minutes = install(monkeypatch)
    read = desk_context._desk_read("NBIS", "2m", NOW)
    regular_before = [m for m in chart_bars(RAW[EARLIER[-1]], [], "1m", "extended", {EARLIER[-1]: None}) if not m["extended"]]
    pre = [m for m in RAW_TODAY if datetime.fromtimestamp(m["time"], ET).hour < 9
           or (datetime.fromtimestamp(m["time"], ET).hour == 9 and datetime.fromtimestamp(m["time"], ET).minute < 30)]
    regular = [m for m in minutes if not m["extended"]]
    assert read["reading"] == {
        "last": round(minutes[-1]["close"], 4), "at": minutes[-1]["time"], "daily": False,
        "prev_close": round(regular_before[-1]["close"], 4), "vwap": round(regular[-1]["vwap"], 4), "vwap_at": regular[-1]["time"],
        "rvol": 1.25}
    assert read["reference"] == [
        {"key": "prev_close", "price": round(regular_before[-1]["close"], 4), "label": f"Prev close {regular_before[-1]['close']:,.2f}"},
        {"key": "pm_high", "price": round(max(m["high"] for m in pre), 4), "label": f"PM high {max(m['high'] for m in pre):,.2f}"},
        {"key": "pm_low", "price": round(min(m["low"] for m in pre), 4), "label": f"PM low {min(m['low'] for m in pre):,.2f}"}]
    # 15m reads the previous close from its own earlier candles: the same number.
    assert desk_context._desk_read("NBIS", "15m", NOW)["reading"]["prev_close"] == read["reading"]["prev_close"]


def test_in_the_pre_market_there_is_no_vwap_or_rvol_yet(monkeypatch):
    early = datetime.combine(TODAY, wall_time(8, 15), ET).timestamp()
    install(monkeypatch, today=session(TODAY, early))
    read = desk_context._desk_read("NBIS", "2m", early)
    assert set(read["studies"]["vwap"]) == {None} and set(read["studies"]["rvol"]) == {None}
    assert read["reading"]["vwap"] is None and read["reading"]["rvol"] is None and read["reading"]["vwap_at"] is None
    assert [line["key"] for line in read["reference"]] == ["prev_close", "pm_high", "pm_low"]


def test_daily_averages_run_over_the_whole_history_and_volume_is_against_the_thirty_days_before(monkeypatch):
    start = datetime.combine(TODAY - timedelta(days=599), wall_time(9, 30), ET).timestamp()
    daily = [{"time": int(start + 86400 * i), "open": 50.0, "high": 52.0, "low": 49.0, "close": 50 + 10 * math.sin(i / 23) + i / 50,
              "volume": 1_000_000 + (i % 17) * 10_000} for i in range(600)]
    monkeypatch.setattr(desk_context, "daily_bars", lambda symbol: daily)
    install(monkeypatch)
    read = desk_context._desk_read("NBIS", "1D", NOW)
    shown, studies = read["bars"], read["studies"]
    assert len(shown) == desk_context.DAILY_DAYS and read["reference"] == []
    first = len(daily) - len(shown)
    closes = pd.Series([b["close"] for b in daily])
    for name, series in (("ema21", _ema(closes, 21)), ("sma50", _sma(closes, 50)), ("sma200", _sma(closes, 200))):
        assert all(abs(a - b) < 1e-3 for a, b in zip(studies[name], list(series)[first:])), name
    i = len(daily) - 1
    usual = sum(b["volume"] for b in daily[i - 30:i]) / 30
    assert studies["rvol"][-1] == round(daily[-1]["volume"] / usual, 4)
    assert set(studies) == {"ema21", "sma50", "sma200", "vwap", "rvol"} and set(studies["vwap"]) == {None}
    # The reading line still comes from today's minutes on the daily chart.
    assert read["reading"]["at"] == RAW_TODAY[-1]["time"] and read["reading"]["vwap"] is not None


def test_a_failed_minute_read_on_the_daily_chart_still_shows_the_candles(monkeypatch):
    start = datetime.combine(date(2026, 1, 2), wall_time(9, 30), ET).timestamp()
    daily = [{"time": int(start + 86400 * i), "open": 50.0, "high": 52.0, "low": 49.0, "close": 50.0, "volume": 10}
             for i in range(300) if start + 86400 * i <= NOW]
    monkeypatch.setattr(desk_context, "daily_bars", lambda symbol: daily)

    def broken(symbol):
        raise RuntimeError("Tradier unavailable")
    monkeypatch.setattr(desk_context, "today_minutes", broken)
    read = desk_context._desk_read("NBIS", "1D", NOW)
    assert read["bars"] and read["reading"]["daily"] is True and read["reading"]["vwap"] is None
    assert read["reading"]["at"] <= NOW and read["reading"]["prev_close"] == 50.0
    assert timedelta(seconds=NOW - read["reading"]["at"]) < timedelta(days=1)
