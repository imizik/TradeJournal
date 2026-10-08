from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.engine.symbol_info_reactions import calculate, summary

ET = ZoneInfo("America/New_York")


class Calendar:
    def __init__(self, holidays=(), early_closes=()):
        self.holidays = set(holidays)
        self.early_closes = set(early_closes)

    def hours(self, day):
        if day.weekday() >= 5 or day in self.holidays:
            return {"status": "closed"}
        close = 13 * 60 if day in self.early_closes else 16 * 60
        return {"status": "open", "open": 9 * 60 + 30, "close": close}


def bar(day, opened, closed):
    return {"time": int(datetime.combine(day, time(9, 30), ET).timestamp()), "open": opened,
            "close": closed, "high": max(opened, closed), "low": min(opened, closed), "volume": 1}


def bars_for(report_day, first, second, *, prior=100, first_open=100):
    calendar = Calendar()
    dates = [report_day - timedelta(days=offset) for offset in range(1, 8)]
    prior_day = next(day for day in dates if calendar.hours(day)["status"] == "open")
    return [bar(prior_day, prior, prior), bar(first, first_open, first), bar(second, 109, second)]


def test_before_open_selects_larger_full_day_move_and_computes_gap():
    first, second = date(2026, 1, 5), date(2026, 1, 6)
    daily = [bar(date(2026, 1, 2), 100, 100), bar(first, 110, 108), bar(second, 105, 106)]
    rows = calculate([{"date": first.isoformat(), "label": "Q4 FY2025"}], daily, Calendar(), datetime(2026, 1, 7, 17, tzinfo=ET))
    row = rows[0]
    assert row["state"] == "ready"
    assert row["reaction_date"] == first.isoformat()
    assert row["gap_pct"] == pytest.approx(10)
    assert row["reaction_pct"] == pytest.approx(8)


def test_after_close_uses_next_session_when_its_absolute_move_is_larger():
    report, first, second = date(2026, 1, 5), date(2026, 1, 5), date(2026, 1, 6)
    daily = [bar(date(2026, 1, 2), 100, 100), bar(first, 100, 101), bar(second, 111.1, 113.2331)]
    rows = calculate([{"date": report.isoformat()}], daily, Calendar(), datetime(2026, 1, 8, 17, tzinfo=ET))
    assert rows[0]["reaction_date"] == second.isoformat()
    assert round(rows[0]["gap_pct"], 2) == 10
    assert round(rows[0]["reaction_pct"], 2) == 12.11


def test_exact_tie_chooses_first_session_and_zero_move_is_valid():
    report, first, second = date(2026, 1, 5), date(2026, 1, 5), date(2026, 1, 6)
    daily = [bar(date(2026, 1, 2), 100, 100), bar(first, 100, 101), bar(second, 101, 99.99)]
    rows = calculate([{"date": report.isoformat()}], daily, Calendar(), datetime(2026, 1, 7, 17, tzinfo=ET))
    assert rows[0]["reaction_date"] == first.isoformat()
    zero = calculate([{"date": first.isoformat()}], [bar(date(2026, 1, 2), 100, 100), bar(first, 100, 100), bar(second, 100, 100)],
                     Calendar(), datetime(2026, 1, 7, 17, tzinfo=ET))
    assert zero[0]["state"] == "ready" and zero[0]["reaction_pct"] == 0


def test_holiday_weekend_early_close_and_incomplete_candidate():
    report = date(2026, 1, 19)  # The report date is a holiday, followed by a weekend/holiday gap.
    holiday = date(2026, 1, 19)
    first, second = date(2026, 1, 20), date(2026, 1, 21)
    calendar = Calendar(holidays={holiday}, early_closes={first})
    daily = [bar(date(2026, 1, 16), 100, 100), bar(first, 101, 102), bar(second, 103, 104)]
    ready = calculate([{"date": report.isoformat()}], daily, calendar, datetime(2026, 1, 22, 17, tzinfo=ET))[0]
    assert [session["date"] for session in ready["sessions"]] == [first.isoformat(), second.isoformat()]
    incomplete = calculate([{"date": report.isoformat()}], daily, calendar, datetime(2026, 1, 21, 12, tzinfo=ET))[0]
    assert incomplete["state"] == "unavailable"
    assert "not complete" in incomplete["reason"]


def test_missing_prior_invalid_prices_and_conflicting_duplicate_refuse_number():
    report, first, second = date(2026, 1, 5), date(2026, 1, 5), date(2026, 1, 6)
    no_prior = calculate([{"date": report.isoformat()}], [bar(first, 100, 101), bar(second, 100, 101)], Calendar(),
                         datetime(2026, 1, 7, 17, tzinfo=ET))[0]
    assert no_prior["state"] == "unavailable"
    invalid = [bar(date(2026, 1, 2), 100, 100), bar(first, 0, 101), bar(second, 100, 101)]
    assert calculate([{"date": report.isoformat()}], invalid, Calendar(), datetime(2026, 1, 7, 17, tzinfo=ET))[0]["state"] == "unavailable"
    duplicate = [bar(date(2026, 1, 2), 100, 100), bar(first, 100, 101), bar(first, 100, 103), bar(second, 100, 101)]
    assert calculate([{"date": report.isoformat()}], duplicate, Calendar(), datetime(2026, 1, 7, 17, tzinfo=ET))[0]["state"] == "unavailable"


def test_select_eight_before_validity_filter_and_mean_absolute_requires_four():
    reports = [{"date": (date(2023, 1, 1) + timedelta(days=i * 90)).isoformat()} for i in range(10)]
    selected_dates = {r["date"] for r in reports[-8:]}
    # No bars/calendar coverage makes all selected reports unavailable; older rows are not substituted.
    rows = calculate(reports, [], Calendar(), datetime(2026, 10, 8, 17, tzinfo=ET))
    assert {row["report_date"] for row in rows} == selected_dates
    values = [{"state": "ready", "report_date": f"2026-0{i}-01", "reaction_pct": value}
              for i, value in enumerate((8, -4, 0, -12), 1)]
    assert summary(values)["average_abs_pct"] == 6
    assert summary(values[:3])["average_abs_pct"] is None
