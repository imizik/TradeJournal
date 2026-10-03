"""Automatic chart levels (C2.1): each level pinned on fixture bars, and agreement with fill context."""

from datetime import date, datetime, timedelta, timezone

import pytest

from app.engine.chart_levels import compute_levels, round_step
from app.engine.chart_math import ET
from app.engine.indicators import analyze_minute_bars, get_previous_day_data


def ny(at: str) -> int:
    return int(datetime.fromisoformat(at).replace(tzinfo=ET).timestamp())


def utc(stamp: int) -> str:
    return datetime.fromtimestamp(stamp, timezone.utc).strftime("%Y-%m-%d %H:%M")


def minute(at: str, high: float, low: float, source: str = "tradier") -> dict:
    stamp = ny(at)
    mid = (high + low) / 2
    return {"time": stamp, "end_time": stamp + 60, "source": source, "open": mid, "high": high, "low": low, "close": mid, "volume": 100}


def session(day: str, high: float, low: float, close: float | None = None) -> dict:
    stamp = ny(f"{day}T09:30")
    return {"time": stamp, "end_time": ny(f"{day}T16:00"), "source": "tradier", "open": low, "high": high,
            "low": low, "close": (high + low) / 2 if close is None else close, "volume": 1000}


def weekdays(start: str, end: str) -> list[str]:
    day, last, out = date.fromisoformat(start), date.fromisoformat(end), []
    while day <= last:
        if day.weekday() < 5:
            out.append(day.isoformat())
        day += timedelta(days=1)
    return out


def by_kind(result) -> dict:
    return {level.kind: level for level in result.levels if level.kind != "round"}


def open_day(day: str, close: int = 960) -> dict:
    return {"date": day, "status": "open", "open": 570, "close": close, "description": "", "source": "tradier"}


def closed_day(day: str) -> dict:
    return {"date": day, "status": "closed", "open": None, "close": None, "description": "Holiday", "source": "tradier"}


# ---------------------------------------------------------------------------
# A DST Monday: Friday 2026-03-06 is EST (UTC-5), Monday 2026-03-09 is EDT (UTC-4)
# ---------------------------------------------------------------------------

DST_MINUTES = [
    minute("2026-03-06T15:59", 120, 80, "alpaca_sip"),  # regular session: never overnight
    minute("2026-03-06T16:00", 105, 99, "alpaca_sip"),
    minute("2026-03-06T19:59", 104, 97, "alpaca_sip"),  # overnight low
    minute("2026-03-09T04:00", 106, 100),
    minute("2026-03-09T08:15", 107, 101),  # premarket and overnight high: one bar
    minute("2026-03-09T09:29", 103, 98.5),  # premarket low
    minute("2026-03-09T09:30", 110, 102),
    minute("2026-03-09T09:33", 111, 101.5),  # OR5 high and low
    minute("2026-03-09T09:40", 112, 100.5),  # OR15 high and low
    minute("2026-03-09T09:45", 130, 90),  # after the opening ranges
]
DST_DAILY = [session(d, 110 + i, 90 - i) for i, d in enumerate(weekdays("2026-02-23", "2026-03-05"))] + [session("2026-03-06", 120, 80, 101)]


def test_a_dst_monday_reads_its_windows_in_new_york_time():
    result = compute_levels(date(2026, 3, 9), DST_MINUTES, DST_DAILY, ny("2026-03-09T10:00"))
    levels = by_kind(result)
    prices = {kind: level.price for kind, level in levels.items()}
    assert prices == {
        "prior_day_high": 120, "prior_day_low": 80, "prior_day_close": 101,
        "prior_week_high": 120, "prior_week_low": 80,
        "overnight_high": 107, "overnight_low": 97,
        "premarket_high": 107, "premarket_low": 98.5,
        "opening_range_5m_high": 111, "opening_range_5m_low": 101.5,
        "opening_range_15m_high": 112, "opening_range_15m_low": 100.5,
    }
    # Monday 09:30 New York is 13:30 UTC; Friday's 16:00 close was 21:00 UTC.
    assert utc(levels["premarket_high"].bar_time) == "2026-03-09 12:15"
    assert utc(levels["premarket_high"].formed_at) == "2026-03-09 13:30"
    assert utc(levels["overnight_high"].formed_at) == "2026-03-09 13:30"
    assert utc(levels["opening_range_5m_high"].formed_at) == "2026-03-09 13:35"
    assert utc(levels["opening_range_15m_low"].formed_at) == "2026-03-09 13:45"
    assert utc(levels["overnight_low"].bar_time) == "2026-03-07 00:59"
    assert utc(levels["prior_day_high"].formed_at) == "2026-03-06 21:00"
    # One bar set both: confluence counts it once.
    assert levels["overnight_high"].bar_time == levels["premarket_high"].bar_time
    assert levels["prior_week_high"].bar_time == levels["prior_day_high"].bar_time
    assert levels["overnight_low"].source == "alpaca_sip" and levels["premarket_low"].source == "tradier"
    assert {level.timeframe for level in levels.values()} == {"1m", "1D"}
    assert levels["prior_day_high"].evidence == "observed"
    assert levels["opening_range_5m_high"].evidence == "calculated"
    assert not any(level.developing for level in levels.values())
    assert result.missing == {}


def test_premarket_and_overnight_develop_until_the_open_and_opening_ranges_wait():
    result = compute_levels(date(2026, 3, 9), DST_MINUTES, DST_DAILY, ny("2026-03-09T08:16"))
    levels = by_kind(result)
    # The 08:15 bar ends at 08:16, so it counts; nothing later exists yet.
    assert (levels["premarket_high"].price, levels["premarket_low"].price) == (107, 100)
    assert (levels["overnight_high"].price, levels["overnight_low"].price) == (107, 97)
    for kind in ("premarket_high", "overnight_low"):
        assert levels[kind].developing and levels[kind].formed_at is None
    assert result.missing["opening_range_5m"] == "Forms at 09:35."
    assert result.missing["opening_range_15m"] == "Forms at 09:45."


def test_a_bar_still_forming_at_as_of_does_not_count():
    levels = by_kind(compute_levels(date(2026, 3, 9), DST_MINUTES, DST_DAILY, ny("2026-03-09T08:15") + 59))
    assert levels["premarket_high"].price == 106
    assert levels["overnight_high"].price == 106


# ---------------------------------------------------------------------------
# A half day: Thanksgiving 2026-11-26 closed, 2026-11-27 closes at 13:00
# ---------------------------------------------------------------------------

HALF_CALENDAR = {date.fromisoformat(d): open_day(d) for d in weekdays("2026-11-16", "2026-12-04")}
HALF_CALENDAR[date(2026, 11, 26)] = closed_day("2026-11-26")
HALF_CALENDAR[date(2026, 11, 27)] = open_day("2026-11-27", close=780)
HALF_DAILY = [session(d, 200 + i, 180 - i) for i, d in enumerate(weekdays("2026-11-16", "2026-11-20"))] + [
    session("2026-11-23", 210, 190), session("2026-11-24", 214, 191),
    session("2026-11-25", 212, 186), session("2026-11-27", 213, 195, 205),
]
HALF_MINUTES = [
    minute("2026-11-27T12:59", 260, 150, "alpaca_sip"),  # regular session on a half day
    minute("2026-11-27T13:00", 209, 204, "alpaca_sip"),  # postmarket starts at the early close
    minute("2026-11-27T16:59", 207, 199, "alpaca_sip"),
    minute("2026-11-27T17:00", 300, 100, "alpaca_sip"),  # after the extended session: never counted
    minute("2026-11-30T07:00", 208, 203),
    minute("2026-11-30T09:30", 210, 202),
]


def test_the_session_after_a_half_day_reads_its_early_close():
    result = compute_levels(date(2026, 11, 30), HALF_MINUTES, HALF_DAILY, ny("2026-11-30T09:40"), HALF_CALENDAR)
    levels = by_kind(result)
    assert (levels["overnight_high"].price, levels["overnight_low"].price) == (209, 199)
    assert levels["overnight_high"].bar_time == ny("2026-11-27T13:00")
    assert (levels["prior_day_high"].price, levels["prior_day_close"].price) == (213, 205)
    assert levels["prior_day_high"].formed_at == ny("2026-11-27T13:00")
    # The prior week has four sessions; the holiday is not a missing bar.
    assert (levels["prior_week_high"].price, levels["prior_week_low"].price) == (214, 186)
    assert levels["prior_week_high"].bar_time == ny("2026-11-24T09:30")
    assert levels["prior_week_high"].formed_at == ny("2026-11-27T13:00")
    assert (levels["opening_range_5m_high"].price, levels["opening_range_5m_low"].price) == (210, 202)
    assert result.missing.get("prior_week") is None and result.missing.get("prior_day") is None


def test_the_half_day_itself_uses_the_session_before_the_holiday():
    minutes = [minute("2026-11-25T17:00", 220, 211, "alpaca_sip"), minute("2026-11-27T09:31", 215, 207)]
    levels = by_kind(compute_levels(date(2026, 11, 27), minutes, HALF_DAILY, ny("2026-11-27T12:00"), HALF_CALENDAR))
    assert levels["prior_day_high"].price == 212
    assert levels["prior_day_high"].bar_time == ny("2026-11-25T09:30")
    assert levels["overnight_high"].price == 220
    assert levels["opening_range_5m_high"].price == 215


def test_without_the_calendar_a_holiday_reads_as_a_missing_bar_never_as_the_prior_day():
    result = compute_levels(date(2026, 11, 27), [], HALF_DAILY, ny("2026-11-27T12:00"))
    kinds = by_kind(result)
    assert "prior_day_high" not in kinds and "swing_high" not in kinds
    assert result.missing["prior_day"] == "No daily bar for 2026-11-26."
    assert result.missing["swings"] == "No daily bar for 2026-11-26."
    assert result.missing["overnight"] == "No minute bars for 2026-11-26."


def test_a_closed_day_has_no_session_levels_but_keeps_the_prior_session():
    result = compute_levels(date(2026, 11, 26), [], HALF_DAILY, ny("2026-11-26T12:00"), HALF_CALENDAR)
    assert by_kind(result)["prior_day_high"].price == 212
    for group in ("premarket", "overnight", "opening_range_5m", "opening_range_15m"):
        assert result.missing[group] == "The market is closed on 2026-11-26."


def test_a_late_open_leaves_out_the_clock_defined_ranges():
    calendar = {**HALF_CALENDAR, date(2026, 11, 30): {**open_day("2026-11-30"), "open": 630}}
    minutes = HALF_MINUTES[:-1] + [minute("2026-11-30T10:15", 230, 210)]
    result = compute_levels(date(2026, 11, 30), minutes, HALF_DAILY, ny("2026-11-30T11:00"), calendar)
    note = "The session opens at 10:30; premarket and opening ranges are defined from 09:30."
    assert result.missing["premarket"] == result.missing["opening_range_5m"] == note
    # The overnight range follows the calendar instead, so 10:15 is still before the open.
    assert by_kind(result)["overnight_high"].price == 230
    assert by_kind(result)["overnight_high"].formed_at == ny("2026-11-30T10:30")


# ---------------------------------------------------------------------------
# Missing data stays missing
# ---------------------------------------------------------------------------

def test_missing_daily_bars_are_reported_not_skipped():
    without_wednesday = [b for b in HALF_DAILY if b["time"] != ny("2026-11-25T09:30")]
    result = compute_levels(date(2026, 11, 30), HALF_MINUTES, without_wednesday, ny("2026-11-30T09:40"), HALF_CALENDAR)
    assert result.missing["prior_week"] == "No daily bar for 2026-11-25."
    assert "prior_week_high" not in by_kind(result)

    stale = [b for b in HALF_DAILY if b["time"] < ny("2026-11-25T00:00")]
    result = compute_levels(date(2026, 11, 30), HALF_MINUTES, stale, ny("2026-11-30T09:40"), HALF_CALENDAR)
    assert result.missing["prior_day"] == "No daily bar for 2026-11-25."
    assert not {"prior_day_high", "swing_high", "swing_low"} & set(by_kind(result))


def test_overnight_needs_the_previous_sessions_bars():
    result = compute_levels(date(2026, 11, 30), HALF_MINUTES[-2:], HALF_DAILY, ny("2026-11-30T09:40"), HALF_CALENDAR)
    assert result.missing["overnight"] == "No minute bars for 2026-11-27."
    assert by_kind(result)["premarket_high"].price == 208


def test_a_session_without_premarket_trades_says_so():
    minutes = HALF_MINUTES[:4] + [minute("2026-11-30T09:30", 210, 202)]
    result = compute_levels(date(2026, 11, 30), minutes, HALF_DAILY, ny("2026-11-30T09:40"), HALF_CALENDAR)
    assert result.missing["premarket"] == "No bars from 04:00 to 09:30 on 2026-11-30."


# ---------------------------------------------------------------------------
# Swings and round numbers
# ---------------------------------------------------------------------------

def test_swings_are_daily_pivots_confirmed_two_sessions_later():
    days = weekdays("2026-06-01", "2026-09-30")  # 88 sessions, no calendar: weekdays only
    highs = [100.0] * len(days)
    lows = [90.0] * len(days)
    highs[5] = 150  # older than the 60-session lookback
    highs[-10], highs[-6], highs[-5] = 120, 115, 115  # a pivot, then equal highs: the first counts
    lows[-8] = 70
    highs[-2] = 130  # too recent: needs two later sessions to confirm
    daily = [session(d, h, low) for d, h, low in zip(days, highs, lows)]
    result = compute_levels(date(2026, 10, 1), [], daily, ny("2026-10-01T12:00"))
    swings = [(level.kind, level.price, level.bar_time, level.formed_at) for level in result.levels if level.kind.startswith("swing")]
    assert swings == [
        ("swing_high", 120, daily[-10]["time"], ny(f"{days[-8]}T16:00")),
        ("swing_low", 70, daily[-8]["time"], ny(f"{days[-6]}T16:00")),
        ("swing_high", 115, daily[-6]["time"], ny(f"{days[-4]}T16:00")),
    ]
    assert all(level.evidence == "inferred" and level.timeframe == "1D" for level in result.levels if level.kind.startswith("swing"))


@pytest.mark.parametrize("price,step", [(660, 5), (600, 5), (180, 1), (430, 5), (800, 10), (50, 0.5), (10, 0.1), (6600, 50), (2.5, 0.05), (2.0, 0.01)])
def test_round_number_spacing_scales_with_price(price, step):
    assert round_step(price) == pytest.approx(step)


def test_round_numbers_sit_three_at_or_below_and_three_above():
    def rounds(reference):
        result = compute_levels(date(2026, 11, 30), [], [], ny("2026-11-30T10:00"), reference=reference)
        return [(level.price, level.label) for level in result.levels if level.kind == "round"]

    assert [p for p, _ in rounds(662.4)] == [650, 655, 660, 665, 670, 675]
    assert [p for p, _ in rounds(660)] == [650, 655, 660, 665, 670, 675]
    assert rounds(10.3) == [(10.1, "10.1"), (10.2, "10.2"), (10.3, "10.3"), (10.4, "10.4"), (10.5, "10.5"), (10.6, "10.6")]
    assert [label for _, label in rounds(21480)] == ["21,200", "21,300", "21,400", "21,500", "21,600", "21,700"]
    level = compute_levels(date(2026, 11, 30), [], [], ny("2026-11-30T10:00"), reference=662.4).levels[0]
    assert (level.evidence, level.timeframe, level.source, level.bar_time, level.formed_at) == ("calculated", None, None, None, None)


def test_round_numbers_center_on_the_last_completed_close():
    minutes = [minute("2026-11-30T09:30", 181, 179), minute("2026-11-30T09:31", 199, 197)]
    result = compute_levels(date(2026, 11, 30), minutes, [], ny("2026-11-30T09:31") + 30)
    assert [level.price for level in result.levels if level.kind == "round"] == [178, 179, 180, 181, 182, 183]
    assert compute_levels(date(2026, 11, 30), [], [], ny("2026-11-30T09:31")).missing["round"] == "No price to place round numbers around."


# ---------------------------------------------------------------------------
# Chart and fill context agree on the same bars
# ---------------------------------------------------------------------------

def _alpaca_day(day: str, start: str, end: str, seed: float) -> list[dict]:
    """Alpaca minute bars with uneven prices, every minute from start to end New York time."""
    at, last, bars, i = datetime.fromisoformat(f"{day}T{start}").replace(tzinfo=ET), datetime.fromisoformat(f"{day}T{end}").replace(tzinfo=ET), [], 0
    while at <= last:
        mid = 500 + 7 * ((i * 37 + seed) % 23) / 23 + 0.1234567 * (i % 5)
        bars.append({"t": at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"), "o": mid, "h": mid + 0.3333337,
                     "l": mid - 0.2222221, "c": mid + 0.01, "v": 100 + i, "vw": mid})
        at += timedelta(minutes=1)
        i += 1
    return bars


def _chart(bar: dict, source: str) -> dict:
    stamp = int(datetime.fromisoformat(bar["t"].replace("Z", "+00:00")).timestamp())
    return {"time": stamp, "end_time": stamp + 60, "source": source, "open": bar["o"], "high": bar["h"],
            "low": bar["l"], "close": bar["c"], "volume": bar["v"]}


@pytest.mark.parametrize("fill_at", ["2026-09-29T08:10:00", "2026-09-29T09:37:30", "2026-09-29T09:44:59", "2026-09-29T11:00:00"])
def test_chart_levels_equal_fill_context_levels_on_the_same_bars(fill_at):
    yesterday = _alpaca_day("2026-09-28", "04:00", "19:59", 3)
    today = _alpaca_day("2026-09-29", "04:00", "12:00", 11)
    daily_rows = [(f"2026-09-{d:02d}", 505 + d % 3 + 0.4444444, 495 - d % 4 - 0.5555555, 500 + d % 2 + 0.1111111) for d in (21, 22, 23, 24, 25, 28)]
    alpaca_daily = [{"t": f"{d}T04:00:00Z", "o": c, "h": h, "l": low, "c": c, "v": 1e6} for d, h, low, c in daily_rows]
    chart_daily = [session(d, h, low, c) for d, h, low, c in daily_rows]
    fill_dt = datetime.fromisoformat(fill_at)

    # What fill enrichment stores for a fill at that moment (alpaca_enricher._build_context).
    context = analyze_minute_bars(today, fill_dt)
    previous = get_previous_day_data(alpaca_daily, fill_dt.date())
    fill_levels = {f"prior_day_{k}": previous[k] for k in ("high", "low", "close")}
    for group in ("premarket", "opening_range_5m", "opening_range_15m"):
        for side in ("high", "low"):
            if context.get(f"{group}_{side}") is not None:
                fill_levels[f"{group}_{side}"] = context[f"{group}_{side}"]

    minutes = [_chart(b, "alpaca_sip") for b in yesterday] + [_chart(b, "tradier") for b in today]
    as_of = int(fill_dt.replace(tzinfo=ET).timestamp())
    chart = by_kind(compute_levels(fill_dt.date(), minutes, chart_daily, as_of))
    shared = {kind: level.price for kind, level in chart.items() if kind in fill_levels or kind.startswith(("premarket", "opening_range"))}

    assert shared == fill_levels
    assert len(fill_levels) == {"08:10": 5, "09:37": 7, "09:44": 7, "11:00": 9}[fill_at[11:16]]
    for kind in shared:
        assert chart[kind].bar_time is not None and chart[kind].source is not None
