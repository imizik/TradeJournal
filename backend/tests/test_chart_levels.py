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


# ---------------------------------------------------------------------------
# Confluence (C2.2)
# ---------------------------------------------------------------------------

def level(kind, label, price, timeframe="1m", bar_time=None, developing=False, formed_at=None):
    from app.engine.chart_levels import Level
    return Level(kind, label, price, "calculated", timeframe, "tradier" if bar_time else None, bar_time, formed_at, developing)


def test_levels_within_one_band_merge_into_a_zone_spanning_their_prices():
    from app.engine.chart_levels import confluence
    levels = [level("prior_day_high", "PDH", 21500.0, "1D", 1), level("opening_range_15m_high", "OR15 high", 21497.25, bar_time=2),
              level("round", "21,500", 21500.0), level("prior_day_low", "PDL", 21300.0, "1D", 1)]
    zones = confluence(levels, band=5.0)
    assert [(z.low, z.high, z.label, z.score) for z in zones] == [
        (21300.0, 21300.0, "PDL", 1),
        (21497.25, 21500.0, "PDH + 21,500 + OR15 high", 3),  # the members' own prices, highest first
    ]
    assert zones[1].id == "opening_range_15m_high@21497.25|prior_day_high@21500.0|round@21500.0"


def test_levels_a_band_apart_stay_apart_and_neighbour_chains_cannot_expand_a_zone():
    from app.engine.chart_levels import confluence
    apart = confluence([level("premarket_high", "PMH", 100.0, bar_time=1), level("overnight_high", "ONH", 100.1, bar_time=2)], band=0.1)
    assert [z.label for z in apart] == ["PMH", "ONH"]
    chain = confluence([level("a", "A", 100.0, bar_time=1), level("b", "B", 100.08, bar_time=2), level("c", "C", 100.16, bar_time=3)], band=0.1)
    assert [(z.low, z.high, z.score) for z in chain] == [(100.0, 100.08, 2), (100.16, 100.16, 1)]
    # Without a band (no ATR yet) only levels at the very same price merge.
    assert [z.label for z in confluence([level("a", "A", 100.0, bar_time=1), level("b", "B", 100.01, bar_time=2), level("round", "100", 100.0)], None)] == ["A + 100", "B"]


def test_levels_set_by_the_same_bar_count_as_one_source():
    from app.engine.chart_levels import confluence
    same_minute = [level("premarket_high", "PMH", 50.0, bar_time=7), level("overnight_high", "ONH", 50.0, bar_time=7)]
    assert confluence(same_minute, 0.2)[0].score == 1
    same_day = [level("prior_day_high", "PDH", 50.0, "1D", 9), level("prior_week_high", "PWH", 50.0, "1D", 9), level("swing_high", "Swing high", 50.05, "1D", 9)]
    assert confluence(same_day, 0.2)[0].score == 1
    # A minute and a daily bar that start at the same second are still different bars; a round number is its own source.
    mixed = [level("premarket_high", "PMH", 50.0, "1m", 9), level("prior_day_high", "PDH", 50.0, "1D", 9), level("round", "50", 50.0)]
    assert confluence(mixed, 0.2)[0].score == 3


# ---------------------------------------------------------------------------
# Interactions (C2.3): level 100, band 0.5, so the band is 99.5..100.5
# ---------------------------------------------------------------------------

def candle(index, open_, high, low, close):
    return {"time": 1000 + index * 300, "open": open_, "high": high, "low": low, "close": close}


def read(bars, start=0, low=100.0, high=100.0):
    from app.engine.chart_levels import interactions
    result = interactions(low, high, 0.5, bars, start)
    return result["state"], [(e["event"], (e["time"] - 1000) // 300) for e in result["events"]], result["at_level"]


def test_price_that_never_reaches_the_band_leaves_a_level_untested():
    assert read([candle(0, 102, 103, 101.5, 102.5), candle(1, 102.5, 102.8, 100.6, 101)]) == ("untested", [], False)


def test_a_touch_counts_as_a_test_once_price_moves_away():
    bars = [candle(0, 102, 102.2, 101.2, 101.5), candle(1, 101.5, 101.6, 99.9, 101), candle(2, 101, 101.8, 101.1, 101.6)]
    assert read(bars[:2]) == ("touched", [], True)  # actual contact, departure not yet confirmed
    assert read(bars) == ("tested", [("tested", 2)], False)
    # A close inside the visible zone is not a break.
    inside = [candle(0, 102, 102.2, 101.2, 101.5), candle(1, 101.5, 101.5, 99.6, 99.8), candle(2, 99.8, 101.9, 99.7, 101.7), candle(3, 101.7, 102, 101, 101.9)]
    assert read(inside, low=99.5, high=100.5) == ("tested", [("tested", 3)], False)


def test_a_close_beyond_the_visible_zone_breaks_and_a_close_back_reclaims():
    bars = [candle(0, 102, 102.2, 101.2, 101.5), candle(1, 101.5, 101.6, 99.9, 101), candle(2, 101, 101.8, 101.1, 101.6),
            candle(3, 101.6, 101.7, 99.0, 99.2), candle(4, 99.2, 99.4, 98.5, 98.8), candle(5, 98.8, 101.0, 98.7, 100.8)]
    assert read(bars[:4]) == ("broken", [("tested", 2), ("broken", 3)], True)
    assert read(bars) == ("reclaimed", [("tested", 2), ("broken", 3), ("reclaimed", 5)], True)
    # A gap through the band breaks without touching it.
    assert read([candle(0, 102, 103, 101.5, 102), candle(1, 98, 98.5, 97.5, 98)]) == ("broken", [("broken", 1)], False)


def test_a_retest_from_the_other_side_after_a_break_is_a_test_and_the_break_stands():
    bars = [candle(0, 102, 102, 101, 101.2), candle(1, 101.2, 101.3, 99, 99.1), candle(2, 99.1, 100.0, 98.9, 99.2), candle(3, 99.2, 99.3, 98.5, 98.6)]
    assert read(bars) == ("broken", [("broken", 1), ("tested", 3)], False)


def test_only_bars_from_when_the_level_formed_count_but_the_close_before_sets_the_side():
    bars = [candle(0, 99, 99.2, 98, 98.5), candle(1, 98.5, 100.2, 98.4, 100.0), candle(2, 100.1, 101.2, 99.9, 101)]
    # The earlier close is inside; a contact establishes no completed departure yet.
    assert read(bars, start=1000 + 2 * 300) == ("touched", [], True)
    # Counting from bar 0: price came from below and closed above, a break.
    assert read(bars) == ("broken", [("broken", 2)], True)


def test_price_that_starts_at_the_level_and_leaves_it_has_tested_it():
    bars = [candle(0, 100.2, 100.4, 99.8, 100.1), candle(1, 100.1, 101.2, 100.0, 101.0), candle(2, 101.0, 101.6, 100.8, 101.4)]
    assert read(bars, low=99.5, high=100.5) == ("tested", [("tested", 2)], False)
    # Leaving downward through the band is not a break: there was no side to break from.
    down = [candle(0, 100.2, 100.4, 99.8, 100.1), candle(1, 100.1, 100.2, 99.0, 99.2), candle(2, 99.2, 99.4, 98.6, 98.8)]
    assert read(down, low=99.5, high=100.5) == ("tested", [("tested", 2)], False)


def test_a_contact_uses_the_visible_zone_not_its_outer_buffer():
    bars = [candle(0, 103, 103.5, 102, 102.5), candle(1, 102.5, 102.6, 101.1, 102), candle(2, 102, 102.8, 102.1, 102.6)]
    assert read(bars, low=100.0, high=101.2) == ("tested", [("tested", 2)], False)
    assert read(bars, low=100.0, high=100.5)[0] == "untested"


def test_a_zone_waits_for_its_last_confirmed_member_and_any_developing_member():
    from app.engine.chart_levels import confluence, zone_start
    developing = confluence([level("premarket_high", "PMH", 10.0, bar_time=5, developing=True)], 0.1)[0]
    assert zone_start(developing) is None
    mixed = confluence([level("opening_range_5m_high", "OR5 high", 10.0, bar_time=5, formed_at=500), level("round", "10", 10.0)], 0.1)[0]
    assert zone_start(mixed) == 500
    later = confluence([level("opening_range_5m_high", "OR5 high", 10.0, bar_time=5, formed_at=500), level("premarket_high", "PMH", 10.0, bar_time=6, developing=True)], 0.1)[0]
    assert zone_start(later) is None


def test_the_users_wide_zone_does_not_count_a_near_miss_as_a_contact():
    from app.engine.chart_levels import interactions
    bars = [candle(0, 234, 234.5, 233, 233.5), candle(1, 233.5, 233.6, 231.5, 232.2), candle(2, 232.2, 233, 232.1, 232.8)]
    result = interactions(228.38, 230.30, 1.62, bars, 0)
    assert result["state"] == "approached" and not result["at_level"]
    assert [event["event"] for event in result["events"]] == ["approached"]


def test_complete_link_zones_are_bounded_order_independent_and_keep_all_landmarks():
    from app.engine.chart_levels import confluence
    levels = [level(f"p{i}", f"P{i}", 100 + .9 * i, bar_time=i + 1) for i in range(20)]
    forward, backward = confluence(levels, 1), confluence(list(reversed(levels)), 1)
    assert [(z.low, z.high) for z in forward] == [(z.low, z.high) for z in backward]
    assert all(z.high - z.low < 1 for z in forward)
    assert sum(len(z.members) for z in forward) == len(levels) and len(forward) > 1
    example = [level("high", "H", p, bar_time=i) for i, p in enumerate([228.38, 228.50, 229.47, 230, 230.30])]
    assert [(z.low, z.high) for z in confluence(example, 1.62)] == [(228.38, 228.50), (229.47, 230.30)]


def test_a_gap_away_from_an_unknown_side_does_not_invent_contact():
    bars = [candle(0, 100, 100.2, 99.8, 100), candle(1, 102, 103, 101.9, 102.5), candle(2, 102.5, 103, 102, 102.8)]
    assert read(bars, start=1300) == ("untested", [], False)


def test_contacts_need_departure_once_and_events_are_known_at_candle_close():
    from app.engine.chart_levels import interactions
    bars = [candle(0, 102, 103, 101, 102), candle(1, 102, 102.1, 99.9, 101),
            candle(2, 101, 101.2, 100, 101.1), candle(3, 101.1, 102, 101.1, 101.8)]
    for bar in bars:
        bar["end_time"] = bar["time"] + 300
    result = interactions(100, 100, .5, bars, 0)
    assert result["events"] == [{"event": "tested", "time": 2200, "bar_time": 1900, "direction": "above"}]
    assert result["last_close"] == 101.8 and result["last_close_at"] == 2200


def test_newly_confirmed_members_cannot_manufacture_earlier_contacts():
    from app.engine.chart_levels import confluence, interactions, zone_start
    zone = confluence([level("round", "100", 100), level("opening_range_5m_high", "OR5", 100.7, formed_at=2000)], .8)[0]
    early = [candle(0, 103, 103.2, 101.3, 102), candle(1, 102, 103.1, 101.7, 102.9)]
    result = interactions(zone.low, zone.high, .8, early, zone_start(zone))
    assert result["events"] == [] and result["last_close"] is None and result["since"] == 2000


def test_an_interior_daily_gap_cannot_invent_a_pivot_or_an_atr():
    days = weekdays("2026-08-03", "2026-10-02")
    daily = [session(d, 110 if d == "2026-09-16" else 120 if d == "2026-09-17" else 105, 95, 100) for d in days]
    calendar = {date.fromisoformat(d): open_day(d) for d in days + ["2026-10-05"]}
    full = compute_levels(date(2026, 10, 5), [], daily, ny("2026-10-05T10:00"), calendar)
    assert not any(item.kind == "swing_high" and item.price == 110 for item in full.levels)
    gap = [b for b in daily if b["time"] != ny("2026-09-17T09:30")]
    partial = compute_levels(date(2026, 10, 5), [], gap, ny("2026-10-05T10:00"), calendar)
    assert not any(item.kind.startswith("swing") for item in partial.levels)
    assert partial.atr is None and partial.missing["swings"] == partial.missing["atr"] == "No daily bar for 2026-09-17."
    assert by_kind(partial)["prior_day_high"].price == 105  # today's independent anchors remain available


def test_a_known_holiday_inside_the_daily_tail_is_not_a_missing_session():
    days = weekdays("2026-08-03", "2026-10-02")
    calendar = {date.fromisoformat(d): open_day(d) for d in days + ["2026-10-05"]}
    calendar[date(2026, 9, 7)] = closed_day("2026-09-07")
    daily = [session(d, 105, 95, 100) for d in days if d != "2026-09-07"]
    result = compute_levels(date(2026, 10, 5), [], daily, ny("2026-10-05T10:00"), calendar)
    assert result.atr is not None and "swings" not in result.missing and "atr" not in result.missing


@pytest.mark.parametrize("minute_at,expected", [("09:59", None), ("10:01", 100.0), ("10:03", None)])
def test_range_capture_receives_only_a_recent_underlying_minute(monkeypatch, minute_at, expected):
    from app.engine import chart_feed as feed_module
    monkeypatch.setattr(feed_module.time, "time", lambda: ny("2026-10-05T10:02"))
    spots = []

    def ranges(symbol, spot):
        spots.append(spot)
        return [], {"state": "unavailable"}

    feed_module.ChartFeed()._levels("XYZ", date(2026, 10, 5), [minute(f"2026-10-05T{minute_at}", 101, 99)], [],
                                    {"splits": []}, None, lambda *_: None, {}, range_levels=ranges)
    assert spots == [expected]


def test_a_real_zero_atr_does_not_become_missing_or_disable_exact_contacts(monkeypatch):
    from app.engine import chart_feed as feed_module
    monkeypatch.setattr(feed_module.time, "time", lambda: ny("2026-10-05T10:00"))
    daily = [session(d, 100, 100, 100) for d in weekdays("2026-08-03", "2026-10-02")]
    bar = minute("2026-10-05T09:55", 100, 100)
    panels = {"5m": {"bars": [bar]}}
    auto = feed_module.ChartFeed()._levels("XYZ", date(2026, 10, 5), [bar], daily, {"splits": []}, None, lambda *_: None, panels)
    assert auto["atr"] == 0 and auto["band"] == 0 and "confluence" not in auto["missing"]
    assert any(h["at_level"] for h in panels["5m"]["level_events"].values())


def test_sparse_history_does_not_fetch_years_of_market_calendars(monkeypatch):
    from app.engine import chart_feed as feed_module
    monkeypatch.setattr(feed_module.time, "time", lambda: ny("2026-10-05T10:00"))
    asked = []

    class Calendar:
        def hours(self, day):
            asked.append(day)
            return open_day(day.isoformat()) if day.weekday() < 5 else closed_day(day.isoformat())

    daily = [session("2000-01-03", 105, 95), session("2026-10-02", 105, 95)]
    auto = feed_module.ChartFeed()._levels("XYZ", date(2026, 10, 5), [], daily, {"splits": []}, Calendar(), lambda *_: None, {})
    assert max(asked) - min(asked) <= timedelta(days=160)
    assert date(2026, 10, 2) in asked and auto["atr"] is None


# ---------------------------------------------------------------------------
# The workspace carries the levels (C2.3)
# ---------------------------------------------------------------------------

def test_the_workspace_sends_zones_and_each_intraday_panels_interactions(monkeypatch):
    import httpx
    from app.engine import chart_feed as feed_module
    from app.engine.chart_feed import ChartFeed

    now = datetime(2026, 9, 30, 10, 2, tzinfo=ET)  # a Wednesday, 32 minutes into the session

    class Fixed(datetime):
        @classmethod
        def now(cls, tz=None):
            return now.astimezone(tz)

    monkeypatch.setattr(feed_module, "datetime", Fixed)
    monkeypatch.setattr(feed_module.time, "time", lambda: now.timestamp())
    monkeypatch.setattr(feed_module.tradier, "TRADIER_API_KEY", "test-secret")
    monkeypatch.setattr(feed_module.tradier, "TRADIER_BASE_URL", "https://api.tradier.com")
    days = weekdays("2026-08-03", "2026-09-30")
    today_rows = [{"timestamp": ny(f"2026-09-30T{t}"), "open": c, "high": h, "low": low, "close": c, "volume": 1000}
                  for t, h, low, c in [("08:00", 101.0, 100.4, 100.6), ("09:30", 100.9, 100.1, 100.5), ("09:35", 101.6, 100.7, 101.4),
                                       ("09:40", 102.4, 101.5, 102.2), ("09:45", 102.5, 101.8, 102.0), ("09:50", 102.6, 101.9, 102.3)]]

    def get(url, params, headers, timeout):
        if "timesales" in url:
            payload = {"series": {"data": today_rows}}
        elif "history" in url:
            rows = [{"date": d, "open": 99, "high": 101 + i % 3, "low": 97 - i % 2, "close": 100, "volume": 1e6}
                    for i, d in enumerate(days) if params["start"] <= d <= params["end"]]
            payload = {"history": {"day": rows}}
        else:
            payload = {"quotes": {"quote": []}}
        return httpx.Response(200, json=payload, request=httpx.Request("GET", url))

    monkeypatch.setattr(feed_module.httpx, "get", get)
    asked = []

    def stored(symbol, day):
        asked.append((symbol, day))
        return [minute("2026-09-29T17:00", 103.0, 102.0, "alpaca_sip")]

    data = ChartFeed().workspace("SPY", ["5m", "1D"], [], "extended", stored_session=stored)
    auto = data["auto_levels"]
    assert asked == [("SPY", date(2026, 9, 29))]
    assert auto["day"] == "2026-09-30" and auto["atr"] > 0 and auto["band"] == pytest.approx(auto["atr"] * 0.1)
    members = {m["kind"]: m for z in auto["zones"] for m in z["members"]}
    assert members["overnight_high"]["price"] == 103.0 and members["overnight_high"]["source"] == "alpaca_sip"
    assert members["premarket_high"]["price"] == 101.0 and members["opening_range_5m_high"]["price"] == 100.9
    assert members["opening_range_15m_high"]["price"] == 102.4 and members["opening_range_15m_high"]["formed_at"] == ny("2026-09-30T09:45")
    # Each intraday panel reads its own closed bars; a daily panel reads none.
    events = data["panels"]["5m"]["level_events"]
    assert set(events) == {z["id"] for z in auto["zones"]} and "level_events" not in data["panels"]["1D"]
    zone = {z["label"]: z for z in auto["zones"]}
    # OR5 starts at 09:35: the first close crosses above; the later retest only approaches.
    morning = next(z for z in auto["zones"] if any(m["kind"] == "opening_range_5m_high" for m in z["members"]))
    history = events[morning["id"]]
    assert history["state"] == "broken" and history["since"] == ny("2026-09-30T09:35")
    assert history["events"] == [
        {"event": "broken", "time": ny("2026-09-30T09:40"), "bar_time": ny("2026-09-30T09:35"), "direction": "above"},
        {"event": "approached", "time": ny("2026-09-30T09:50"), "bar_time": ny("2026-09-30T09:45"), "direction": "above"},
    ]
    late = events[zone["OR15 high + 102"]["id"]]
    assert late["state"] == "touched" and late["at_level"] and late["since"] == ny("2026-09-30T09:45")
    assert auto["session"] == "extended"
    assert zone["104"]["score"] == 1 and events[zone["104"]["id"]]["state"] == "untested"
    assert "Swing high ×" in next(label for label in zone if label.startswith("PDH"))
    # A layout without a daily panel still reads daily bars for the levels, and does not report their failures as chart issues.
    assert ChartFeed().workspace("SPY", ["5m"], [], "extended", stored_session=stored)["auto_levels"]["zones"]
